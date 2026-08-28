use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Per-account metadata stored by bnetswitch.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountMeta {
    /// User-friendly nickname (e.g., "Main", "Alt DPS", "Tank Smurf")
    #[serde(default)]
    pub nickname: Option<String>,
    /// BattleTag if known (e.g., "Player#1234")
    #[serde(default)]
    pub battletag: Option<String>,
    /// Marked unusable for Overwatch (e.g., suspended/banned). bnetswitch
    /// flags it in the list and refuses to launch Overwatch for it.
    #[serde(default)]
    pub banned: bool,
}

/// The bnetswitch config file that stores account metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// Path to the Wine prefix (if manually set).
    #[serde(default)]
    pub wine_prefix: Option<String>,
    /// Whether to launch via Lutris.
    #[serde(default = "default_true")]
    pub use_lutris: bool,
    /// Whether to auto-launch Battle.net after switching.
    #[serde(default = "default_true")]
    pub auto_launch: bool,
    /// Account metadata keyed by email.
    #[serde(default)]
    pub accounts: HashMap<String, AccountMeta>,
    /// Emails temporarily removed from Battle.net.config during an
    /// "Add New Account" workflow. When the user finishes logging in
    /// and presses Save Current, these get merged back along with the
    /// newly added account.
    #[serde(default)]
    pub pending_merge_emails: Vec<String>,
    /// Safety snapshot of SavedAccountNames taken at the moment `add_new_account`
    /// clears the list. If `save_current` produces a shorter merged list than
    /// this snapshot, something went wrong (Battle.net didn't fully restore,
    /// user pressed `s` too early, etc.) and we use the snapshot as the floor.
    /// Cleared alongside `pending_merge_emails` on successful save.
    #[serde(default)]
    pub pending_snapshot_emails: Vec<String>,
    /// Maximum age in seconds of the Wine registry's `Launch Options\Pro`
    /// section for which we'll attempt a "warm launch" (spawn OW directly
    /// using the existing Battle.net-written auth tokens rather than
    /// asking Battle.net to relaunch via UI).
    ///
    /// Default: 4 hours. Bigger = more direct launches but higher risk
    /// of stale tokens causing OW to bounce to the login screen anyway.
    #[serde(default = "default_warm_launch_ttl")]
    pub warm_launch_ttl_secs: u64,

    /// Discord guild IDs to push the active account's BattleTag to as a
    /// per-server nickname when accounts switch. Empty = nickname sync
    /// disabled. Multiple guilds = sync to all of them.
    ///
    /// To find a guild ID: enable Discord Developer Mode (Settings →
    /// Advanced), right-click the server icon → "Copy Server ID".
    #[serde(default)]
    pub discord_nickname_sync_guilds: Vec<String>,

    /// LFG messages older than this (in seconds) are hidden from the
    /// TUI's LFG view. Most LFG groups fill within 5-10 min; older
    /// entries are usually stale. Set to a very large value to disable
    /// the filter.
    #[serde(default = "default_lfg_stale_secs")]
    pub lfg_stale_threshold_secs: u64,

    /// When true, only the most recent LFG embed per author is shown.
    /// Hides spam from people posting repeatedly. False = show all.
    #[serde(default = "default_true")]
    pub lfg_dedupe_by_author: bool,

    /// When true, only the most recent LFG embed per voice channel is
    /// shown. Multiple people from the same group often post separately
    /// for the same VC; this collapses them into one row. False = show
    /// all.
    #[serde(default = "default_true")]
    pub lfg_dedupe_by_voice_channel: bool,

    /// Every account email bnetswitch has observed in Battle.net's
    /// `SavedAccountNames`. Battle.net trims that list when its own UI is
    /// used to log in/out, which makes accounts disappear and prompt for a
    /// fresh login even though their credentials are still on disk.
    /// bnetswitch restores this superset (active account first) on launch so
    /// accounts stop being forgotten. Only emails actually saved by
    /// Battle.net here are recorded, so TCNO-imported-but-never-used accounts
    /// are never injected into the login list.
    #[serde(default)]
    pub remembered_emails: Vec<String>,

    /// How often (in seconds) to poll competitive career stats per
    /// account for the longitudinal history in `stats.rs`. Set to 0 to
    /// disable stats tracking entirely.
    ///
    /// Default: 15 minutes. There is little point polling faster --
    /// OverFast caches these responses for 10 minutes and Blizzard's
    /// career pages themselves update with a lag, so most extra polls
    /// would just write tombstones.
    #[serde(default = "default_stats_poll_interval")]
    pub stats_poll_interval_secs: u64,
}

fn default_lfg_stale_secs() -> u64 {
    10 * 60 // 10 minutes
}

fn default_stats_poll_interval() -> u64 {
    15 * 60 // 15 minutes
}

fn default_warm_launch_ttl() -> u64 {
    4 * 60 * 60 // 4 hours
}

fn default_true() -> bool {
    true
}

impl Default for AppConfig {
    fn default() -> Self {
        // Match the serde defaults so behavior is consistent whether the
        // config file is missing or merely missing fields.
        Self {
            wine_prefix: None,
            use_lutris: true,
            auto_launch: true,
            accounts: HashMap::new(),
            pending_merge_emails: Vec::new(),
            pending_snapshot_emails: Vec::new(),
            warm_launch_ttl_secs: default_warm_launch_ttl(),
            discord_nickname_sync_guilds: Vec::new(),
            lfg_stale_threshold_secs: default_lfg_stale_secs(),
            lfg_dedupe_by_author: true,
            lfg_dedupe_by_voice_channel: true,
            remembered_emails: Vec::new(),
            stats_poll_interval_secs: default_stats_poll_interval(),
        }
    }
}

impl AppConfig {
    /// Get the config file path.
    pub fn config_path() -> Result<PathBuf> {
        let config_dir = dirs::config_dir()
            .context("Could not determine config directory")?;
        let app_dir = config_dir.join("bnetswitch");
        std::fs::create_dir_all(&app_dir)
            .with_context(|| format!("Failed to create config dir {}", app_dir.display()))?;
        Ok(app_dir.join("config.toml"))
    }

    /// Load config from disk, or return default.
    pub fn load() -> Result<Self> {
        let path = Self::config_path()?;
        if !path.exists() {
            return Ok(Self::default());
        }
        let content = std::fs::read_to_string(&path)
            .with_context(|| format!("Failed to read {}", path.display()))?;
        let config: Self = toml::from_str(&content)
            .with_context(|| format!("Failed to parse {}", path.display()))?;
        Ok(config)
    }

    /// Save config to disk.
    pub fn save(&self) -> Result<()> {
        let path = Self::config_path()?;
        let content = toml::to_string_pretty(self)
            .context("Failed to serialize config")?;
        std::fs::write(&path, content)
            .with_context(|| format!("Failed to write {}", path.display()))?;
        Ok(())
    }

    /// Get the display name for an account: nickname, else BattleTag, else
    /// the email as a last resort. The email is intentionally NOT appended —
    /// it's only shown in the account detail view (`d`) to keep the list
    /// uncluttered and avoid exposing addresses at a glance.
    pub fn display_name(&self, email: &str) -> String {
        if let Some(meta) = self.accounts.get(email) {
            if let Some(nick) = &meta.nickname {
                return nick.clone();
            }
            if let Some(tag) = &meta.battletag {
                return tag.clone();
            }
        }
        email.to_string()
    }

    /// The email already attributed to `battletag`, if any.
    ///
    /// BattleTags are unique per Battle.net account, so at most one email
    /// should ever own one. Callers use this to avoid reassigning a tag that
    /// another account already claims — two accounts sharing a tag makes them
    /// render identically in the list (see `display_name`) and silently
    /// collide in any BattleTag-keyed map or cache.
    pub fn email_for_battletag(&self, battletag: &str) -> Option<&str> {
        self.accounts
            .iter()
            .find(|(_, meta)| meta.battletag.as_deref() == Some(battletag))
            .map(|(email, _)| email.as_str())
    }

    /// Attribute `battletag` to `email` unless another account already claims
    /// it. Returns true if the config changed (caller is responsible for
    /// persisting).
    ///
    /// Battle.net's `login_cache` exposes no email->BattleTag mapping (its
    /// `name` column is an opaque hash), so we infer one from recency: the
    /// newest row is assumed to belong to `SavedAccountNames[0]`. That holds
    /// only right after a real login. Switching accounts reorders
    /// SavedAccountNames *without* authenticating, so the newest tag can
    /// outlive its own session and would then be misattributed to whoever
    /// just became active. An existing claim was learned the same way but at
    /// a moment when it was correct, so it wins over a fresh guess.
    pub fn learn_battletag(&mut self, email: &str, battletag: String) -> bool {
        if matches!(self.email_for_battletag(&battletag), Some(owner) if owner != email) {
            return false;
        }
        if self.accounts.get(email).and_then(|m| m.battletag.as_deref())
            == Some(battletag.as_str())
        {
            return false;
        }
        self.set_battletag(email, battletag);
        true
    }

    /// Set a nickname for an account.
    pub fn set_nickname(&mut self, email: &str, nickname: String) {
        let meta = self.accounts.entry(email.to_string()).or_insert(AccountMeta {
            nickname: None,
            battletag: None,
            banned: false,
        });
        meta.nickname = Some(nickname);
    }

    /// Whether an account is marked banned/unusable for Overwatch.
    pub fn is_banned(&self, email: &str) -> bool {
        self.accounts.get(email).map(|m| m.banned).unwrap_or(false)
    }

    /// Toggle the banned flag for an account. Returns the new state.
    pub fn toggle_banned(&mut self, email: &str) -> bool {
        let meta = self.accounts.entry(email.to_string()).or_insert(AccountMeta {
            nickname: None,
            battletag: None,
            banned: false,
        });
        meta.banned = !meta.banned;
        meta.banned
    }

    /// Record account emails seen in Battle.net's `SavedAccountNames` into the
    /// persistent superset. Returns true if any new email was added (so the
    /// caller can decide whether to persist the config).
    pub fn remember_emails(&mut self, emails: &[String]) -> bool {
        let mut changed = false;
        for email in emails {
            if email.is_empty() {
                continue;
            }
            if !self.remembered_emails.iter().any(|e| e == email) {
                self.remembered_emails.push(email.clone());
                changed = true;
            }
        }
        changed
    }

    /// Set a battletag for an account.
    pub fn set_battletag(&mut self, email: &str, battletag: String) {
        let meta = self.accounts.entry(email.to_string()).or_insert(AccountMeta {
            nickname: None,
            battletag: None,
            banned: false,
        });
        meta.battletag = Some(battletag);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A config written before `stats_poll_interval_secs` existed must
    /// still load, picking up the default rather than failing the parse
    /// and silently resetting every account's metadata.
    #[test]
    fn config_without_stats_interval_still_loads() {
        let toml_src = r#"
use_lutris = true
auto_launch = true
remembered_emails = ["a@example.com"]

[accounts."a@example.com"]
battletag = "Player#1234"
banned = false
"#;
        let cfg: AppConfig = toml::from_str(toml_src).expect("legacy config parses");
        assert_eq!(cfg.stats_poll_interval_secs, default_stats_poll_interval());
        assert_eq!(
            cfg.accounts.get("a@example.com").unwrap().battletag.as_deref(),
            Some("Player#1234")
        );
    }

    /// 0 is the documented "disable stats tracking" value and must
    /// survive a round trip rather than being coerced to the default.
    #[test]
    fn stats_interval_zero_round_trips() {
        let mut cfg = AppConfig::default();
        cfg.stats_poll_interval_secs = 0;
        let s = toml::to_string_pretty(&cfg).unwrap();
        let back: AppConfig = toml::from_str(&s).unwrap();
        assert_eq!(back.stats_poll_interval_secs, 0);
    }

    #[test]
    fn ban_toggle_round_trips() {
        let mut cfg = AppConfig::default();
        let email = "smurf@example.com";
        // Unknown account defaults to not-banned.
        assert!(!cfg.is_banned(email));
        // First toggle bans it; creates the account entry.
        assert!(cfg.toggle_banned(email));
        assert!(cfg.is_banned(email));
        // Second toggle unbans.
        assert!(!cfg.toggle_banned(email));
        assert!(!cfg.is_banned(email));
    }

    /// Regression: a BattleTag lingering as the newest `login_cache` row was
    /// being re-stamped onto whichever email sat at SavedAccountNames[0] after
    /// a switch, leaving two accounts sharing one tag. Both then rendered with
    /// the same `display_name`, so one looked like it had vanished from the
    /// list. `email_for_battletag` is the lookup that lets the caller refuse.
    #[test]
    fn battletag_owner_lookup_identifies_existing_claim() {
        let mut cfg = AppConfig::default();
        cfg.set_battletag("onyx@example.com", "OnyxYeti#21315".to_string());
        cfg.set_battletag("smurf@example.com", "Pogo#11926".to_string());

        assert_eq!(
            cfg.email_for_battletag("Pogo#11926"),
            Some("smurf@example.com")
        );
        // A tag nobody owns is free to assign.
        assert_eq!(cfg.email_for_battletag("Stranger#0001"), None);
        // Distinct accounts keep distinct display names.
        assert_ne!(
            cfg.display_name("onyx@example.com"),
            cfg.display_name("smurf@example.com")
        );
    }

    /// The exact corruption seen in the wild: switching to `onyx` put it at
    /// SavedAccountNames[0] while `login_cache`'s newest row was still the
    /// previous session's `Pogo#11926`. Startup then attributed Pogo to onyx,
    /// so both rows rendered as "Pogo#11926" and onyx looked like it had
    /// vanished from the list.
    #[test]
    fn learn_battletag_refuses_to_steal_another_accounts_tag() {
        let mut cfg = AppConfig::default();
        cfg.set_battletag("onyx@example.com", "OnyxYeti#21315".to_string());
        cfg.set_battletag("smurf@example.com", "Pogo#11926".to_string());

        // Stale-but-owned tag must not be reattributed to the active account.
        assert!(!cfg.learn_battletag("onyx@example.com", "Pogo#11926".to_string()));
        assert_eq!(
            cfg.accounts["onyx@example.com"].battletag.as_deref(),
            Some("OnyxYeti#21315")
        );
        assert_eq!(
            cfg.accounts["smurf@example.com"].battletag.as_deref(),
            Some("Pogo#11926")
        );
    }

    #[test]
    fn learn_battletag_populates_unclaimed_tag() {
        let mut cfg = AppConfig::default();
        // A genuinely new account still gets its tag captured.
        assert!(cfg.learn_battletag("fresh@example.com", "Newbie#1111".to_string()));
        assert_eq!(
            cfg.accounts["fresh@example.com"].battletag.as_deref(),
            Some("Newbie#1111")
        );
        // Re-learning the same tag for the same owner is a no-op (no rewrite,
        // so callers don't churn the config file on every refresh).
        assert!(!cfg.learn_battletag("fresh@example.com", "Newbie#1111".to_string()));
    }

    #[test]
    fn learn_battletag_updates_owners_changed_tag() {
        let mut cfg = AppConfig::default();
        cfg.set_battletag("main@example.com", "OldName#1234".to_string());
        // A rename is still the same account, so it may update its own tag.
        assert!(cfg.learn_battletag("main@example.com", "NewName#5678".to_string()));
        assert_eq!(
            cfg.accounts["main@example.com"].battletag.as_deref(),
            Some("NewName#5678")
        );
    }

    #[test]
    fn ban_preserves_existing_metadata() {
        let mut cfg = AppConfig::default();
        let email = "main@example.com";
        cfg.set_battletag(email, "Player#1234".to_string());
        cfg.toggle_banned(email);
        let meta = cfg.accounts.get(email).unwrap();
        assert_eq!(meta.battletag.as_deref(), Some("Player#1234"));
        assert!(meta.banned);
    }
}
