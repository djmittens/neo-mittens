//! Observed voice sessions and evidence-backed moderation history.
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::OpenOptions,
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Member {
    pub user_id: String,
    pub nickname: String,
    #[serde(default)]
    pub avatar_url: Option<String>,
    #[serde(default)]
    pub speaking: bool,
    #[serde(default)]
    pub joined_at_ms: u64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Snapshot {
    pub channel_id: Option<String>,
    #[serde(default)]
    pub channel_name: Option<String>,
    #[serde(default)]
    pub guild_id: Option<String>,
    pub me_id: String,
    #[serde(default)]
    pub owner_id: Option<String>,
    #[serde(default)]
    pub owner_evidence: Option<String>,
    #[serde(default)]
    pub members: Vec<Member>,
    #[serde(default)]
    pub observed_at_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    /// Stable source ID makes retries and multiple tabs idempotent.
    pub event_id: String,
    pub kind: String,
    pub channel_id: String,
    #[serde(default)]
    pub user_id: Option<String>,
    #[serde(default)]
    pub actor_id: Option<String>,
    #[serde(default)]
    pub owner_id: Option<String>,
    #[serde(default)]
    pub me_id: String,
    pub evidence: String,
    #[serde(default)]
    pub timestamp_ms: u64,
    #[serde(default)]
    pub duration_ms: Option<u64>,
    #[serde(default)]
    pub member: Option<Member>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Flags {
    pub ban_requested: bool,
    pub banned_by_me: bool,
    pub banned_me: bool,
    pub troll: bool,
}

#[derive(Default)]
pub struct VoiceLog {
    pub current: Snapshot,
    pub flags: BTreeMap<String, Flags>,
    pub recent: std::collections::VecDeque<Event>,
    seen: std::collections::HashSet<String>,
    pub storage_error: Option<String>,
    path: Option<PathBuf>,
    checkpoint_at_ms: u64,
    unavailable: bool,
}

pub fn directory() -> Result<PathBuf> {
    Ok(dirs::data_local_dir()
        .context("no local data directory")?
        .join("bnetswitch/voice"))
}

impl VoiceLog {
    pub fn unavailable(error: String) -> Self {
        Self {
            unavailable: true,
            storage_error: Some(error),
            ..Self::default()
        }
    }
    pub fn open(path: PathBuf) -> Result<Self> {
        let mut log = Self {
            path: Some(path.clone()),
            ..Self::default()
        };
        let mut open = BTreeMap::new();
        match std::fs::File::open(&path) {
            Ok(file) => {
                for line in BufReader::new(file).lines() {
                    let line = line?;
                    // A crash may leave a partial final line; preserve all valid records.
                    if let Ok(event) = serde_json::from_str::<Event>(&line) {
                        let key = (event.channel_id.clone(), event.user_id.clone());
                        match event.kind.as_str() {
                            "join" | "observed" => {
                                open.insert(key, event.clone());
                            }
                            "leave" | "observation_gap" => {
                                open.remove(&key);
                            }
                            _ => {}
                        }
                        log.replay(event);
                    }
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        let checkpoint = std::fs::read(path.with_extension("snapshot.json"))
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Snapshot>(&bytes).ok());
        // Restart is an observation gap, not proof that anyone left Discord.
        for (_, mut event) in open {
            if let Some(snapshot) = &checkpoint {
                if snapshot.channel_id.as_deref() == Some(&event.channel_id)
                    && snapshot.members.iter().any(|m| {
                        Some(&m.user_id) == event.user_id.as_ref()
                            && event
                                .member
                                .as_ref()
                                .is_some_and(|old| old.joined_at_ms == m.joined_at_ms)
                    })
                {
                    event.timestamp_ms = snapshot.observed_at_ms;
                }
            }
            event.event_id = format!("restart-gap:{}", event.event_id);
            event.kind = "observation_gap".into();
            event.duration_ms = event
                .member
                .as_ref()
                .map(|m| event.timestamp_ms.saturating_sub(m.joined_at_ms));
            event.evidence = "bridge restarted; duration ends at last durable observation".into();
            log.record(event)?;
        }
        Ok(log)
    }

    fn replay(&mut self, event: Event) {
        if !self.seen.insert(event.event_id.clone()) {
            return;
        }
        if event.kind == "ban_requested"
            && event.actor_id.as_deref() == Some(&event.me_id)
            && !event.me_id.is_empty()
        {
            if let Some(id) = &event.user_id {
                self.flags.entry(id.clone()).or_default().ban_requested = true;
            }
        }
        if event.kind == "ban" {
            if event.actor_id.as_deref() == Some(&event.me_id) && !event.me_id.is_empty() {
                if let Some(id) = &event.user_id {
                    self.flags.entry(id.clone()).or_default().banned_by_me = true;
                }
            }
            if event.user_id.as_deref() == Some(&event.me_id) && !event.me_id.is_empty() {
                if let Some(id) = &event.actor_id {
                    self.flags.entry(id.clone()).or_default().banned_me = true;
                }
            }
        }
        if event.kind == "troll_flag" || event.kind == "troll_clear" {
            if let Some(id) = &event.user_id {
                self.flags.entry(id.clone()).or_default().troll = event.kind == "troll_flag";
            }
        }
        self.recent.push_back(event);
        while self.recent.len() > 200 {
            self.recent.pop_front();
        }
    }

    pub fn record(&mut self, event: Event) -> Result<()> {
        anyhow::ensure!(
            !self.unavailable,
            "voice history unavailable: {}",
            self.storage_error.as_deref().unwrap_or("load failed")
        );
        if self.seen.contains(&event.event_id) {
            return Ok(());
        }
        if let Some(path) = &self.path {
            std::fs::create_dir_all(path.parent().context("history path has no parent")?)?;
            let mut file = OpenOptions::new().create(true).append(true).open(path)?;
            // Leading newline isolates a partial record left by a crash.
            writeln!(file, "\n{}", serde_json::to_string(&event)?)?;
            file.flush()?;
        }
        self.replay(event);
        Ok(())
    }

    fn presence(&mut self, kind: &str, member: Member, now: u64, end: u64) -> Result<()> {
        self.record(Event {
            event_id: format!(
                "{}:{}:{}:{}",
                kind,
                self.current.channel_id.as_deref().unwrap_or(""),
                member.user_id,
                now
            ),
            kind: kind.into(),
            channel_id: self.current.channel_id.clone().unwrap_or_default(),
            user_id: Some(member.user_id.clone()),
            actor_id: None,
            owner_id: self.current.owner_id.clone(),
            me_id: self.current.me_id.clone(),
            evidence: "gateway membership observation (not a ban)".into(),
            timestamp_ms: end,
            duration_ms: (kind == "leave" || kind == "observation_gap")
                .then(|| end.saturating_sub(member.joined_at_ms)),
            member: Some(member),
        })
    }

    pub fn update(&mut self, mut next: Snapshot, now: u64) -> Result<()> {
        anyhow::ensure!(
            !self.unavailable,
            "voice history unavailable: {}",
            self.storage_error.as_deref().unwrap_or("load failed")
        );
        let gap = now.saturating_sub(self.current.observed_at_ms) > 60_000;
        let changed =
            next.channel_id != self.current.channel_id || next.me_id != self.current.me_id;
        let old = self.current.members.clone();
        for member in &old {
            if gap || changed || !next.members.iter().any(|m| m.user_id == member.user_id) {
                let end = if gap {
                    self.current.observed_at_ms
                } else {
                    now
                };
                self.presence(
                    if gap { "observation_gap" } else { "leave" },
                    member.clone(),
                    now,
                    end,
                )?;
            }
        }
        for member in &mut next.members {
            member.joined_at_ms = if !gap && !changed {
                old.iter()
                    .find(|m| m.user_id == member.user_id)
                    .map(|m| m.joined_at_ms)
                    .unwrap_or(now)
            } else {
                now
            };
        }
        let owner_changed = changed || next.owner_id != self.current.owner_id;
        next.observed_at_ms = now;
        self.current = next;
        for member in self.current.members.clone() {
            if gap || changed || !old.iter().any(|m| m.user_id == member.user_id) {
                self.presence("join", member, now, now)?;
            }
        }
        if changed || now.saturating_sub(self.checkpoint_at_ms) >= 20_000 {
            if let Some(path) = &self.path {
                std::fs::create_dir_all(path.parent().context("history path has no parent")?)?;
                let temp = path.with_extension("snapshot.tmp");
                std::fs::write(&temp, serde_json::to_vec(&self.current)?)?;
                std::fs::rename(temp, path.with_extension("snapshot.json"))?;
            }
            self.checkpoint_at_ms = now;
        }
        if owner_changed && self.current.channel_id.is_some() {
            self.record(Event {
                event_id: format!(
                    "owner:{}:{}",
                    self.current.channel_id.as_deref().unwrap_or(""),
                    now
                ),
                kind: "owner".into(),
                channel_id: self.current.channel_id.clone().unwrap(),
                user_id: self.current.owner_id.clone(),
                actor_id: None,
                owner_id: self.current.owner_id.clone(),
                me_id: self.current.me_id.clone(),
                evidence: self
                    .current
                    .owner_evidence
                    .clone()
                    .unwrap_or_else(|| "owner unknown".into()),
                timestamp_ms: now,
                duration_ms: None,
                member: None,
            })?;
        }
        Ok(())
    }
}

pub fn avatar_path(url: &str) -> Result<PathBuf> {
    use std::hash::{Hash, Hasher};
    anyhow::ensure!(
        url.starts_with("https://cdn.discordapp.com/avatars/")
            || url.starts_with("https://cdn.discordapp.com/guilds/")
            || url.starts_with("https://cdn.discordapp.com/embed/avatars/"),
        "unsupported avatar URL"
    );
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    url.hash(&mut hash);
    Ok(directory()?
        .join("avatars")
        .join(format!("{:016x}.png", hash.finish())))
}

pub fn cache_avatar(url: String) {
    use std::sync::{Mutex, OnceLock};
    static FETCHING: OnceLock<Mutex<std::collections::HashSet<String>>> = OnceLock::new();
    let Ok(path) = avatar_path(&url) else {
        return;
    };
    if path.exists() {
        return;
    }
    if !FETCHING
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .insert(url.clone())
    {
        return;
    }
    std::thread::spawn(move || {
        let result = (|| -> Result<()> {
            let response = ureq::AgentBuilder::new()
                .timeout(std::time::Duration::from_secs(10))
                .redirects(0)
                .build()
                .get(&url)
                .call()?;
            let mut bytes = Vec::new();
            std::io::Read::take(response.into_reader(), 1_048_577).read_to_end(&mut bytes)?;
            anyhow::ensure!(bytes.len() <= 1_048_576, "avatar too large");
            image::load_from_memory(&bytes)?;
            std::fs::create_dir_all(path.parent().unwrap())?;
            let temp = path.with_extension("tmp");
            std::fs::write(&temp, bytes)?;
            std::fs::rename(temp, path)?;
            Ok(())
        })();
        if result.is_err() { /* retry on the next snapshot */ }
        FETCHING.get().unwrap().lock().unwrap().remove(&url);
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot(ids: &[&str]) -> Snapshot {
        Snapshot {
            channel_id: Some("vc".into()),
            me_id: "me".into(),
            members: ids
                .iter()
                .map(|id| Member {
                    user_id: (*id).into(),
                    nickname: (*id).into(),
                    ..Member::default()
                })
                .collect(),
            ..Snapshot::default()
        }
    }
    #[test]
    fn membership_updates_preserve_duration_and_never_infer_bans() {
        let mut log = VoiceLog::default();
        log.update(snapshot(&["me", "other"]), 1000).unwrap();
        log.update(snapshot(&["me", "other"]), 2000).unwrap();
        assert_eq!(log.current.members[1].joined_at_ms, 1000);
        assert_eq!(log.recent.iter().filter(|e| e.kind == "join").count(), 2);
        log.update(snapshot(&["me"]), 3500).unwrap();
        assert_eq!(log.recent.back().unwrap().duration_ms, Some(2500));
        assert!(log.flags.is_empty());
        log.update(snapshot(&["me"]), 100000).unwrap();
        assert!(log
            .recent
            .iter()
            .any(|e| e.kind == "observation_gap" && e.duration_ms == Some(2500)));
    }
    #[test]
    fn evidence_is_deduped_and_flags_survive_restart() {
        let path =
            std::env::temp_dir().join(format!("bnet-voice-test-{}.jsonl", std::process::id()));
        let mut log = VoiceLog::open(path.clone()).unwrap();
        let event = Event {
            event_id: "ban-1".into(),
            kind: "ban".into(),
            channel_id: "vc".into(),
            user_id: Some("me".into()),
            actor_id: Some("other".into()),
            owner_id: Some("unrelated-owner".into()),
            me_id: "me".into(),
            evidence: "bot message".into(),
            timestamp_ms: 1000,
            duration_ms: None,
            member: None,
        };
        log.record(event.clone()).unwrap();
        log.record(event).unwrap();
        assert_eq!(log.recent.len(), 1);
        let restored = VoiceLog::open(path.clone()).unwrap();
        assert!(restored.flags["other"].banned_me);
        assert!(!restored.flags.contains_key("unrelated-owner"));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn restart_closes_observed_sessions_at_checkpoint_not_restart_time() {
        let path =
            std::env::temp_dir().join(format!("bnet-voice-restart-{}.jsonl", std::process::id()));
        let mut log = VoiceLog::open(path.clone()).unwrap();
        log.update(snapshot(&["me", "other"]), 1000).unwrap();
        log.update(snapshot(&["me", "other"]), 21000).unwrap();
        drop(log);
        let restored = VoiceLog::open(path.clone()).unwrap();
        let gaps: Vec<_> = restored
            .recent
            .iter()
            .filter(|e| e.kind == "observation_gap")
            .collect();
        assert_eq!(gaps.len(), 2);
        assert!(gaps
            .iter()
            .all(|e| e.timestamp_ms == 21000 && e.duration_ms == Some(20000)));
        assert!(restored.current.members.is_empty());
        drop(restored);
        let second = VoiceLog::open(path.clone()).unwrap();
        assert_eq!(
            second
                .recent
                .iter()
                .filter(|e| e.kind == "observation_gap")
                .count(),
            2
        );
        std::fs::remove_file(path.with_extension("snapshot.json")).unwrap();
        std::fs::remove_file(path).unwrap();
    }
}
