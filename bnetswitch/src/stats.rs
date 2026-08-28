//! Longitudinal competitive statistics tracking via the OverFast API.
//!
//! ## Why this exists
//!
//! Blizzard's career profile exposes only *cumulative season-to-date*
//! counters. There is no per-match history, no "last 7 days" view, and
//! no way to ask "how did I play last session". What there *is*, is a
//! set of monotonically increasing counters.
//!
//! So we snapshot those counters over time and difference consecutive
//! observations. The difference between two snapshots is exactly the
//! play that happened between them. That yields windowed performance
//! data that Blizzard exposes nowhere.
//!
//! ## Endpoint
//!
//! `GET /players/{tag}/stats?gamemode=competitive` returns every hero's
//! full career stat block in a single ~44KB response, including the
//! `all-heroes` rollup. One request per account per poll.
//!
//! ## The season problem
//!
//! The stats endpoint carries **no season field** (verified: the payload
//! is exactly `{general, roles, heroes}` for the summary variant and a
//! bare hero map for the career variant). Competitive counters reset to
//! zero at season rollover, so a naive diff across a rollover produces
//! garbage negative deltas.
//!
//! Two independent guards:
//!
//! 1. Callers pass the season from the *ranks* fetch
//!    (`ranks::RoleRanks::current_season`, which reads
//!    `competitive.pc.season` off the `/summary` endpoint). A season
//!    change forces a keyframe.
//! 2. Any counter decreasing forces a keyframe regardless of what the
//!    season number says. The two endpoints can disagree mid-rollover,
//!    and a decreasing monotonic counter is unambiguous evidence of a
//!    reset whatever the metadata claims.
//!
//! ## On-disk format
//!
//! Append-mostly JSONL at `~/.cache/bnetswitch/stats/<tag>.jsonl`, one
//! record per line, three record kinds:
//!
//! - `k` **keyframe** — full absolute counters. Written on the first
//!   observation, on a season change, on a detected reset, and every
//!   [`KEYFRAME_INTERVAL`] deltas so replay cost stays bounded and a
//!   corrupt delta can't poison the rest of history.
//! - `d` **delta** — only heroes that moved, only fields that changed.
//!   Carries `p`, the previous poll timestamp, which brackets when the
//!   session actually occurred.
//! - `t` **tombstone** — "polled, nothing changed". Run-length encoded:
//!   `f` is the first unchanged poll, `n` the count. Consecutive
//!   no-change polls rewrite the trailing tombstone rather than
//!   appending, so an idle week costs one line rather than hundreds.
//!
//! Tombstones matter for correctness, not just bookkeeping: without
//! them a gap in the timeline is ambiguous between "the user didn't
//! play" and "bnetswitch wasn't running". With them, the window
//! preceding any delta is known to be genuinely idle.
//!
//! ## Space
//!
//! Raw payload is ~44KB. A keyframe is ~1.8KB (counters only; the 19
//! `*_avg_per_10_min` fields are dropped as derivable and the 25
//! `*_most_in_game` running maxes are not counters). A single-hero
//! delta is ~120 bytes. A tombstone is ~45 bytes and coalesces.
//!
//! ## Caveat: accuracy is not differenceable
//!
//! `weapon_accuracy` and `critical_hit_accuracy` are integer-rounded
//! season aggregates, and Blizzard exposes no `shots_fired`/`shots_hit`
//! counters to reconstruct them from. They are stored (see
//! [`is_aggregate`]) but *replaced* rather than summed on replay, and
//! must never be differenced — at integer-percent rounding the implied
//! hit count carries ~9% error, which differencing amplifies into pure
//! noise. Use `critical_hits` (a true counter) as the windowed proxy.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const OVERFAST_BASE: &str = "https://overfast-api.tekrop.fr/players";

/// Larger than the ranks timeout: this payload is ~44KB versus a few
/// hundred bytes, and OverFast applies an adaptive Blizzard throttle
/// with a 2s initial delay on cache misses.
const HTTP_TIMEOUT: Duration = Duration::from_secs(20);

/// Emit a fresh keyframe after this many consecutive deltas. Bounds
/// replay work and limits how much history a single corrupt delta line
/// can invalidate.
const KEYFRAME_INTERVAL: usize = 50;

/// Per-hero counter map: stat key -> cumulative value.
pub type Counters = BTreeMap<String, i64>;

/// Hero key -> counters. Includes the `all-heroes` rollup.
pub type HeroStats = BTreeMap<String, Counters>;

// ---------------------------------------------------------------------
// Key handling
// ---------------------------------------------------------------------

/// Stat keys that are *not* cumulative counters. These are season
/// aggregates and get replaced on replay rather than summed.
///
/// `of_match_on_fire` is included defensively: it reads as a percentage
/// in the `all-heroes` rollup, and treating a percentage as a counter
/// would silently corrupt every downstream figure.
pub fn is_aggregate(key: &str) -> bool {
    matches!(
        key,
        "weapon_accuracy" | "critical_hit_accuracy" | "of_match_on_fire"
    )
}

/// True for keys we refuse to store at all.
///
/// - `avg_per` / `_avg`: fully derivable from a counter plus
///   `time_played`, so storing them is pure duplication.
/// - `most_in` / `best`: running maxima, not counters. Differencing them
///   is meaningless.
/// - `per_life`: derived ratio.
/// - `percentage`: `win_percentage` is derivable from `games_won` and
///   `games_played`.
fn is_dropped(key: &str) -> bool {
    key.contains("avg_per")
        || key.ends_with("_avg")
        || key.contains("most_in")
        || key.contains("best")
        || key.contains("per_life")
        || key.contains("percentage")
}

/// Compact on-disk aliases for the highest-frequency keys. Anything not
/// listed round-trips under its full OverFast name, so a new Blizzard
/// stat is stored correctly (just verbosely) without a code change.
const SHORT_CODES: &[(&str, &str)] = &[
    ("games_played", "gp"),
    ("games_won", "gw"),
    ("games_lost", "gl"),
    ("game_tied", "gt"),
    ("hero_wins", "hw"),
    ("time_played", "tp"),
    ("eliminations", "e"),
    ("deaths", "d"),
    ("final_blows", "fb"),
    ("solo_kills", "sk"),
    ("all_damage_done", "dmg"),
    ("hero_damage_done", "hdmg"),
    ("healing_done", "heal"),
    ("assists", "as"),
    ("offensive_assists", "oas"),
    ("defensive_assists", "das"),
    ("critical_hits", "ch"),
    ("critical_hit_kills", "chk"),
    ("critical_hit_accuracy", "cha"),
    ("weapon_accuracy", "wa"),
    ("objective_kills", "ok"),
    ("objective_time", "ot"),
    ("obj_contest_time", "oct"),
    ("multikills", "mk"),
    ("melee_final_blows", "mfb"),
    ("time_spent_on_fire", "fire"),
    ("of_match_on_fire", "omf"),
    ("cards", "cd"),
];

fn to_short(key: &str) -> String {
    SHORT_CODES
        .iter()
        .find(|(long, _)| *long == key)
        .map(|(_, short)| (*short).to_string())
        .unwrap_or_else(|| key.to_string())
}

fn from_short(key: &str) -> String {
    SHORT_CODES
        .iter()
        .find(|(_, short)| *short == key)
        .map(|(long, _)| (*long).to_string())
        .unwrap_or_else(|| key.to_string())
}

/// The `all-heroes` rollup uses different names for several stats than
/// the per-hero blocks do. Normalize to the per-hero spelling so a
/// single downstream code path handles both.
fn canonical_key(key: &str) -> &str {
    match key {
        "damage_done" => "all_damage_done",
        "objective_contest_time" => "obj_contest_time",
        other => other,
    }
}

// ---------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------

/// One absolute observation of an account's competitive counters.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Snapshot {
    pub ts: u64,
    pub season: Option<u32>,
    pub heroes: HeroStats,
}

// The read/query surface below (`Snapshot` accessors, `Observation`,
// `Window`, `replay`, `latest`, `window_since`) is exercised by the test
// suite but has no caller in the binary yet: this pass builds the
// storage engine only, and the TUI that consumes it lands next. Marked
// explicitly rather than left as warning noise, so a genuinely dead
// function still stands out.
#[allow(dead_code)]
impl Snapshot {
    pub fn now_epoch() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    }

    /// Convenience accessor for the `all-heroes` rollup.
    pub fn overall(&self) -> Option<&Counters> {
        self.heroes.get("all-heroes")
    }

    pub fn hero(&self, hero: &str) -> Option<&Counters> {
        self.heroes.get(hero)
    }

    pub fn is_empty(&self) -> bool {
        self.heroes.is_empty()
    }
}

/// A replayed observation: absolute state plus the provenance needed to
/// interpret it.
#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct Observation {
    pub snapshot: Snapshot,
    /// Timestamp of the last poll that saw *no* change before this one.
    /// Together with `snapshot.ts` this brackets when the play happened.
    pub prev_poll: Option<u64>,
    /// True when this observation began a new counter epoch (first ever
    /// record, season rollover, or a detected reset). A window must
    /// never span a reset boundary.
    pub was_reset: bool,
}

/// Difference between two observations within a single season.
#[allow(dead_code)]
#[derive(Debug, Clone, Default)]
pub struct Window {
    pub from_ts: u64,
    pub to_ts: u64,
    pub season: Option<u32>,
    pub heroes: HeroStats,
}

#[allow(dead_code)]
impl Window {
    pub fn overall(&self) -> Option<&Counters> {
        self.heroes.get("all-heroes")
    }

    pub fn hero(&self, hero: &str) -> Option<&Counters> {
        self.heroes.get(hero)
    }

    /// True when no counter moved across the window.
    pub fn is_empty(&self) -> bool {
        self.heroes.is_empty()
    }
}

/// What [`record_observation`] did, so callers can report it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordOutcome {
    /// First record for this account, or a reset — full state written.
    Keyframe,
    /// Counters moved — delta written.
    Delta,
    /// Nothing moved — trailing tombstone created or extended.
    Unchanged,
}

// ---------------------------------------------------------------------
// Wire format
// ---------------------------------------------------------------------

/// One JSONL line. Field names are deliberately single-character; this
/// file grows without bound and the keys would otherwise dominate it.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Line {
    /// Record kind: "k" keyframe, "d" delta, "t" tombstone.
    #[serde(rename = "y")]
    kind: String,
    /// For k/d: observation time. For t: time of the *latest* no-change
    /// poll in the run.
    #[serde(rename = "t")]
    ts: u64,
    #[serde(rename = "s", default, skip_serializing_if = "Option::is_none")]
    season: Option<u32>,
    /// Previous poll timestamp (k/d only).
    #[serde(rename = "p", default, skip_serializing_if = "Option::is_none")]
    prev_poll: Option<u64>,
    /// Hero payload (k/d only). Short-coded keys.
    #[serde(rename = "h", default, skip_serializing_if = "Option::is_none")]
    heroes: Option<BTreeMap<String, BTreeMap<String, i64>>>,
    /// First no-change poll in the run (t only).
    #[serde(rename = "f", default, skip_serializing_if = "Option::is_none")]
    first: Option<u64>,
    /// Number of no-change polls in the run (t only).
    #[serde(rename = "n", default, skip_serializing_if = "Option::is_none")]
    count: Option<u32>,
}

fn encode_heroes(heroes: &HeroStats) -> BTreeMap<String, BTreeMap<String, i64>> {
    heroes
        .iter()
        .map(|(hero, counters)| {
            let c = counters
                .iter()
                .map(|(k, v)| (to_short(k), *v))
                .collect::<BTreeMap<_, _>>();
            (hero.clone(), c)
        })
        .collect()
}

fn decode_heroes(raw: &BTreeMap<String, BTreeMap<String, i64>>) -> HeroStats {
    raw.iter()
        .map(|(hero, counters)| {
            let c = counters
                .iter()
                .map(|(k, v)| (from_short(k), *v))
                .collect::<BTreeMap<_, _>>();
            (hero.clone(), c)
        })
        .collect()
}

// ---------------------------------------------------------------------
// Diff / apply
// ---------------------------------------------------------------------

/// Compute `cur - prev`, keeping only what changed.
///
/// Returns `(delta, reset_detected)`. A decreasing non-aggregate counter
/// sets the reset flag: cumulative counters can only grow within a
/// season, so a decrease means the season rolled over (or the profile
/// was reset/replaced) and the caller must write a keyframe instead.
fn diff(prev: &HeroStats, cur: &HeroStats) -> (HeroStats, bool) {
    let mut out: HeroStats = BTreeMap::new();
    let mut reset = false;

    for (hero, cur_counters) in cur {
        let empty = Counters::new();
        let prev_counters = prev.get(hero).unwrap_or(&empty);
        let mut changed = Counters::new();

        for (key, cur_val) in cur_counters {
            let prev_val = prev_counters.get(key).copied().unwrap_or(0);

            if is_aggregate(key) {
                // Not differenceable — carry the absolute value when it
                // moves so replay can replace it.
                if *cur_val != prev_val {
                    changed.insert(key.clone(), *cur_val);
                }
                continue;
            }

            if *cur_val < prev_val {
                reset = true;
            }
            if *cur_val != prev_val {
                changed.insert(key.clone(), cur_val - prev_val);
            }
        }

        if !changed.is_empty() {
            out.insert(hero.clone(), changed);
        }
    }

    (out, reset)
}

/// Fold a delta into an accumulating absolute state.
///
/// Counters sum; aggregates replace. Getting this backwards would make
/// `weapon_accuracy` climb into the hundreds over a season, which is
/// why the two are separated at the schema level rather than by
/// convention.
fn apply(acc: &mut HeroStats, delta: &HeroStats) {
    for (hero, counters) in delta {
        let entry = acc.entry(hero.clone()).or_default();
        for (key, val) in counters {
            if is_aggregate(key) {
                entry.insert(key.clone(), *val);
            } else {
                *entry.entry(key.clone()).or_insert(0) += *val;
            }
        }
    }
}

/// Subtract `from` out of `to`, for windowing across observations.
/// Aggregates are carried from `to` (the later value) rather than
/// differenced.
#[allow(dead_code)]
fn subtract(from: &HeroStats, to: &HeroStats) -> HeroStats {
    let mut out: HeroStats = BTreeMap::new();
    for (hero, to_counters) in to {
        let empty = Counters::new();
        let from_counters = from.get(hero).unwrap_or(&empty);
        let mut d = Counters::new();
        for (key, to_val) in to_counters {
            if is_aggregate(key) {
                d.insert(key.clone(), *to_val);
                continue;
            }
            let delta = to_val - from_counters.get(key).copied().unwrap_or(0);
            if delta != 0 {
                d.insert(key.clone(), delta);
            }
        }
        // Drop heroes whose only surviving entries are carried
        // aggregates — no actual play occurred on them in this window.
        if d.keys().any(|k| !is_aggregate(k)) {
            out.insert(hero.clone(), d);
        }
    }
    out
}

// ---------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------

fn stats_dir() -> Result<PathBuf> {
    let base = dirs::cache_dir().context("Could not determine cache directory")?;
    let dir = base.join("bnetswitch").join("stats");
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("Failed to create stats dir {}", dir.display()))?;
    Ok(dir)
}

fn log_filename(battletag: &str) -> String {
    format!("{}.jsonl", battletag.replace('#', "-"))
}

fn battletag_to_url_segment(battletag: &str) -> String {
    battletag.replace('#', "-")
}

pub fn log_path(battletag: &str) -> Result<PathBuf> {
    Ok(stats_dir()?.join(log_filename(battletag)))
}

fn read_lines(battletag: &str) -> Result<Vec<Line>> {
    let path = log_path(battletag)?;
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(e).with_context(|| format!("reading {}", path.display())),
    };

    let mut out = Vec::new();
    for (i, raw) in content.lines().enumerate() {
        let raw = raw.trim();
        if raw.is_empty() {
            continue;
        }
        match serde_json::from_str::<Line>(raw) {
            Ok(l) => out.push(l),
            Err(e) => {
                // A truncated tail (interrupted write) is recoverable:
                // skip it and keep the history we can parse. Keyframes
                // bound how much a bad line can cost us.
                eprintln!(
                    "[bnetswitch] stats log {} line {}: unparseable, skipping ({})",
                    path.display(),
                    i + 1,
                    e
                );
            }
        }
    }
    Ok(out)
}

/// Write the whole log atomically (temp + rename).
///
/// Full rewrite rather than append because tombstone coalescing has to
/// replace the trailing line. These files stay small (see module docs),
/// so the simplicity is worth more than the saved syscalls, and
/// temp+rename means a crash can never leave a half-written log.
fn write_lines(battletag: &str, lines: &[Line]) -> Result<()> {
    let path = log_path(battletag)?;
    let tmp = path.with_extension("jsonl.tmp");

    let mut buf = String::new();
    for l in lines {
        buf.push_str(&serde_json::to_string(l).context("serializing stats record")?);
        buf.push('\n');
    }

    std::fs::write(&tmp, buf).with_context(|| format!("writing {}", tmp.display()))?;
    std::fs::rename(&tmp, &path).with_context(|| format!("renaming into {}", path.display()))?;
    Ok(())
}

/// Replay the log into absolute observations, oldest first.
///
/// Tombstones contribute no observation of their own; they supply the
/// `prev_poll` bracket for the next real record.
#[allow(dead_code)]
pub fn replay(battletag: &str) -> Result<Vec<Observation>> {
    let lines = read_lines(battletag)?;
    let mut out = Vec::new();
    let mut acc: HeroStats = BTreeMap::new();
    let mut season: Option<u32> = None;

    for line in &lines {
        match line.kind.as_str() {
            "k" => {
                acc = line.heroes.as_ref().map(decode_heroes).unwrap_or_default();
                season = line.season;
                out.push(Observation {
                    snapshot: Snapshot {
                        ts: line.ts,
                        season,
                        heroes: acc.clone(),
                    },
                    prev_poll: line.prev_poll,
                    was_reset: true,
                });
            }
            "d" => {
                if let Some(h) = line.heroes.as_ref() {
                    apply(&mut acc, &decode_heroes(h));
                }
                if line.season.is_some() {
                    season = line.season;
                }
                out.push(Observation {
                    snapshot: Snapshot {
                        ts: line.ts,
                        season,
                        heroes: acc.clone(),
                    },
                    prev_poll: line.prev_poll,
                    was_reset: false,
                });
            }
            // Tombstones carry no counter information.
            _ => {}
        }
    }

    Ok(out)
}

/// Most recent absolute state, if any.
#[allow(dead_code)]
pub fn latest(battletag: &str) -> Result<Option<Snapshot>> {
    Ok(replay(battletag)?.pop().map(|o| o.snapshot))
}

/// Timestamp of the most recent poll of any kind, including no-change
/// polls. Used to decide whether the background timer is due.
pub fn last_poll_ts(battletag: &str) -> Result<Option<u64>> {
    Ok(read_lines(battletag)?.last().map(|l| l.ts))
}

/// Record a fresh observation, choosing keyframe / delta / tombstone.
pub fn record_observation(battletag: &str, snapshot: &Snapshot) -> Result<RecordOutcome> {
    let mut lines = read_lines(battletag)?;

    // Rebuild the current absolute state and count deltas since the last
    // keyframe, so we know when the next keyframe is due.
    let mut acc: HeroStats = BTreeMap::new();
    let mut prev_season: Option<u32> = None;
    let mut deltas_since_keyframe = 0usize;
    let mut have_any = false;

    for line in &lines {
        match line.kind.as_str() {
            "k" => {
                acc = line.heroes.as_ref().map(decode_heroes).unwrap_or_default();
                prev_season = line.season;
                deltas_since_keyframe = 0;
                have_any = true;
            }
            "d" => {
                if let Some(h) = line.heroes.as_ref() {
                    apply(&mut acc, &decode_heroes(h));
                }
                if line.season.is_some() {
                    prev_season = line.season;
                }
                deltas_since_keyframe += 1;
                have_any = true;
            }
            _ => {}
        }
    }

    // The poll immediately preceding this one, whatever kind it was.
    let prev_poll = lines.last().map(|l| l.ts);

    let (delta, reset_detected) = diff(&acc, &snapshot.heroes);

    let season_changed = match (prev_season, snapshot.season) {
        (Some(a), Some(b)) => a != b,
        // Learning the season for the first time is not a rollover.
        (None, Some(_)) | (Some(_), None) | (None, None) => false,
    };

    // --- Nothing moved: tombstone ---
    if delta.is_empty() && !reset_detected && !season_changed && have_any {
        match lines.last_mut() {
            Some(last) if last.kind == "t" => {
                // Extend the existing run in place.
                last.ts = snapshot.ts;
                last.count = Some(last.count.unwrap_or(1) + 1);
            }
            _ => lines.push(Line {
                kind: "t".into(),
                ts: snapshot.ts,
                season: None,
                prev_poll: None,
                heroes: None,
                first: Some(snapshot.ts),
                count: Some(1),
            }),
        }
        write_lines(battletag, &lines)?;
        return Ok(RecordOutcome::Unchanged);
    }

    // --- Keyframe conditions ---
    let need_keyframe =
        !have_any || reset_detected || season_changed || deltas_since_keyframe >= KEYFRAME_INTERVAL;

    if need_keyframe {
        lines.push(Line {
            kind: "k".into(),
            ts: snapshot.ts,
            season: snapshot.season,
            prev_poll,
            heroes: Some(encode_heroes(&snapshot.heroes)),
            first: None,
            count: None,
        });
        write_lines(battletag, &lines)?;
        return Ok(RecordOutcome::Keyframe);
    }

    // --- Delta ---
    lines.push(Line {
        kind: "d".into(),
        ts: snapshot.ts,
        season: snapshot.season,
        prev_poll,
        heroes: Some(encode_heroes(&delta)),
        first: None,
        count: None,
    });
    write_lines(battletag, &lines)?;
    Ok(RecordOutcome::Delta)
}

/// Aggregate play between `since_ts` and now.
///
/// Only spans observations within a single counter epoch: the window
/// starts at the latest reset at or after `since_ts` if one occurred,
/// because differencing across a season rollover is meaningless.
/// Returns `None` when there aren't two observations to compare.
#[allow(dead_code)]
pub fn window_since(battletag: &str, since_ts: u64) -> Result<Option<Window>> {
    let obs = replay(battletag)?;
    if obs.len() < 2 {
        return Ok(None);
    }

    let last_idx = obs.len() - 1;
    let last = &obs[last_idx];

    // Find the start of the counter epoch the newest observation belongs
    // to: the most recent reset at or before it. Note the base may be the
    // reset observation *itself* — a keyframe is a valid window start,
    // it's the records before it that are unusable.
    let mut epoch_start = 0;
    for i in (0..=last_idx).rev() {
        if obs[i].was_reset {
            epoch_start = i;
            break;
        }
    }

    // Within that epoch, base on the newest observation at or before
    // `since_ts` so the window fully covers the requested period. If the
    // epoch began after `since_ts`, fall back to the epoch start — we
    // report what we can rather than nothing, but never reach further
    // back than the reset.
    let mut base_idx = epoch_start;
    for i in (epoch_start..=last_idx).rev() {
        if obs[i].snapshot.ts <= since_ts {
            base_idx = i;
            break;
        }
    }

    // Base is the newest record: either nothing was played, or the epoch
    // only has one observation so far. Either way there's no diff.
    if base_idx >= last_idx {
        return Ok(None);
    }

    let base = &obs[base_idx];
    let heroes = subtract(&base.snapshot.heroes, &last.snapshot.heroes);

    Ok(Some(Window {
        from_ts: base.snapshot.ts,
        to_ts: last.snapshot.ts,
        season: last.snapshot.season,
        heroes,
    }))
}

// ---------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------

/// Fetch the full competitive career stat block.
///
/// `season` comes from the caller (the ranks fetch) because this
/// endpoint does not report it. Returns `Ok(None)` for 404, which
/// OverFast uses for "private profile or no such player" — the same
/// condition `ranks.rs` maps to `not_found`.
pub fn fetch_career(battletag: &str, season: Option<u32>) -> Result<Option<Snapshot>> {
    let url = format!(
        "{}/{}/stats?gamemode=competitive",
        OVERFAST_BASE,
        battletag_to_url_segment(battletag)
    );

    let agent = ureq::AgentBuilder::new()
        .timeout(HTTP_TIMEOUT)
        .user_agent("bnetswitch/0.1")
        .build();

    match agent.get(&url).call() {
        Ok(response) => {
            let body: serde_json::Value = response
                .into_json()
                .with_context(|| format!("Failed to parse OverFast stats JSON for {}", battletag))?;
            Ok(Some(parse_career(&body, season)))
        }
        Err(ureq::Error::Status(404, _)) => Ok(None),
        Err(e) => Err(anyhow::anyhow!("OverFast stats request failed: {}", e)),
    }
}

/// Parse the career payload: `{hero_key: [{category, label, stats:
/// [{key, label, value}]}]}`.
///
/// Two quirks handled here:
/// - `games_won` appears three times per hero in the `game` category.
///   Collecting into a map dedupes it (values agree).
/// - The `all-heroes` rollup spells several stats differently; see
///   [`canonical_key`].
pub fn parse_career(body: &serde_json::Value, season: Option<u32>) -> Snapshot {
    let mut heroes: HeroStats = BTreeMap::new();

    let Some(obj) = body.as_object() else {
        return Snapshot {
            ts: Snapshot::now_epoch(),
            season,
            heroes,
        };
    };

    for (hero, categories) in obj {
        let Some(cats) = categories.as_array() else {
            continue;
        };
        let mut counters = Counters::new();

        for cat in cats {
            let Some(stats) = cat.get("stats").and_then(|s| s.as_array()) else {
                continue;
            };
            for stat in stats {
                let Some(key) = stat.get("key").and_then(|k| k.as_str()) else {
                    continue;
                };
                if is_dropped(key) {
                    continue;
                }
                let Some(value) = stat.get("value") else {
                    continue;
                };
                // Values arrive as ints or floats depending on the stat.
                let num = if let Some(i) = value.as_i64() {
                    i
                } else if let Some(f) = value.as_f64() {
                    f.round() as i64
                } else {
                    continue;
                };
                counters.insert(canonical_key(key).to_string(), num);
            }
        }

        if !counters.is_empty() {
            heroes.insert(hero.clone(), counters);
        }
    }

    Snapshot {
        ts: Snapshot::now_epoch(),
        season,
        heroes,
    }
}

// ---------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn hero(pairs: &[(&str, i64)]) -> Counters {
        pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect()
    }

    fn stats(entries: &[(&str, Counters)]) -> HeroStats {
        entries
            .iter()
            .map(|(h, c)| (h.to_string(), c.clone()))
            .collect()
    }

    #[test]
    fn drops_derived_keys_but_keeps_counters() {
        assert!(is_dropped("eliminations_avg_per_10_min"));
        assert!(is_dropped("dragonblade_kills_most_in_game"));
        assert!(is_dropped("weapon_accuracy_best_in_game"));
        assert!(is_dropped("eliminations_per_life"));
        assert!(is_dropped("win_percentage"));

        assert!(!is_dropped("eliminations"));
        assert!(!is_dropped("critical_hits"));
        assert!(!is_dropped("weapon_accuracy"));
        assert!(!is_dropped("dragonblade_kills"));
    }

    #[test]
    fn short_codes_round_trip() {
        for (long, _) in SHORT_CODES {
            assert_eq!(&from_short(&to_short(long)), long, "round trip for {long}");
        }
        // Unknown keys pass through untouched.
        assert_eq!(to_short("dragonblade_kills"), "dragonblade_kills");
        assert_eq!(from_short("dragonblade_kills"), "dragonblade_kills");
    }

    #[test]
    fn diff_reports_only_changes() {
        let prev = stats(&[("genji", hero(&[("eliminations", 100), ("deaths", 50)]))]);
        let cur = stats(&[("genji", hero(&[("eliminations", 130), ("deaths", 50)]))]);

        let (d, reset) = diff(&prev, &cur);
        assert!(!reset);
        assert_eq!(d["genji"].get("eliminations"), Some(&30));
        assert!(!d["genji"].contains_key("deaths"), "unchanged key omitted");
    }

    #[test]
    fn diff_omits_untouched_heroes() {
        let prev = stats(&[
            ("genji", hero(&[("eliminations", 100)])),
            ("tracer", hero(&[("eliminations", 40)])),
        ]);
        let cur = stats(&[
            ("genji", hero(&[("eliminations", 120)])),
            ("tracer", hero(&[("eliminations", 40)])),
        ]);

        let (d, _) = diff(&prev, &cur);
        assert!(d.contains_key("genji"));
        assert!(!d.contains_key("tracer"), "unplayed hero must not appear");
    }

    #[test]
    fn decreasing_counter_flags_reset() {
        let prev = stats(&[("genji", hero(&[("eliminations", 900)]))]);
        let cur = stats(&[("genji", hero(&[("eliminations", 12)]))]);

        let (_, reset) = diff(&prev, &cur);
        assert!(reset, "season rollover must be detected from the counter");
    }

    #[test]
    fn aggregates_replace_rather_than_sum() {
        let mut acc = stats(&[("genji", hero(&[("weapon_accuracy", 30), ("eliminations", 100)]))]);
        let delta = stats(&[("genji", hero(&[("weapon_accuracy", 32), ("eliminations", 20)]))]);

        apply(&mut acc, &delta);

        assert_eq!(acc["genji"]["weapon_accuracy"], 32, "accuracy must replace");
        assert_eq!(acc["genji"]["eliminations"], 120, "counter must sum");
    }

    #[test]
    fn diff_carries_aggregate_absolutely() {
        let prev = stats(&[("genji", hero(&[("weapon_accuracy", 30)]))]);
        let cur = stats(&[("genji", hero(&[("weapon_accuracy", 33)]))]);

        let (d, reset) = diff(&prev, &cur);
        assert!(!reset, "a falling percentage is not a counter reset");
        assert_eq!(d["genji"]["weapon_accuracy"], 33, "absolute, not +3");
    }

    #[test]
    fn falling_aggregate_is_not_a_reset() {
        let prev = stats(&[("genji", hero(&[("critical_hit_accuracy", 14)]))]);
        let cur = stats(&[("genji", hero(&[("critical_hit_accuracy", 11)]))]);

        let (_, reset) = diff(&prev, &cur);
        assert!(!reset, "accuracy declining is normal, not a rollover");
    }

    #[test]
    fn subtract_drops_heroes_with_only_aggregates() {
        let from = stats(&[("genji", hero(&[("weapon_accuracy", 30), ("eliminations", 100)]))]);
        let to = stats(&[("genji", hero(&[("weapon_accuracy", 31), ("eliminations", 100)]))]);

        let w = subtract(&from, &to);
        assert!(
            w.is_empty(),
            "accuracy drift alone is not play and must not create a window entry"
        );
    }

    #[test]
    fn parse_career_handles_duplicates_and_rollup_aliases() {
        let body = serde_json::json!({
            "genji": [{
                "category": "game",
                "stats": [
                    {"key": "games_played", "value": 48},
                    {"key": "games_won", "value": 26},
                    {"key": "games_won", "value": 26},
                    {"key": "games_won", "value": 26},
                    {"key": "win_percentage", "value": 56}
                ]
            }, {
                "category": "combat",
                "stats": [
                    {"key": "eliminations", "value": 896},
                    {"key": "eliminations_avg_per_10_min", "value": 17.13},
                    {"key": "eliminations_most_in_game", "value": 41}
                ]
            }],
            "all-heroes": [{
                "category": "combat",
                "stats": [
                    {"key": "damage_done", "value": 412758},
                    {"key": "objective_contest_time", "value": 1277}
                ]
            }]
        });

        let snap = parse_career(&body, Some(24));
        let g = snap.hero("genji").expect("genji present");

        assert_eq!(g["games_played"], 48);
        assert_eq!(g["games_won"], 26, "triplicated key collapses");
        assert_eq!(g["eliminations"], 896);
        assert!(!g.contains_key("win_percentage"), "derived, dropped");
        assert!(!g.contains_key("eliminations_avg_per_10_min"));
        assert!(!g.contains_key("eliminations_most_in_game"));

        let all = snap.overall().expect("rollup present");
        assert_eq!(all["all_damage_done"], 412758, "rollup alias normalized");
        assert_eq!(all["obj_contest_time"], 1277, "rollup alias normalized");
    }

    #[test]
    fn parse_career_tolerates_garbage() {
        let snap = parse_career(&serde_json::json!("not an object"), None);
        assert!(snap.is_empty());

        let snap = parse_career(&serde_json::json!({"genji": "not an array"}), None);
        assert!(snap.is_empty());
    }

    #[test]
    fn encode_decode_round_trips() {
        let h = stats(&[(
            "genji",
            hero(&[
                ("eliminations", 896),
                ("deaths", 430),
                ("dragonblade_kills", 140),
                ("weapon_accuracy", 30),
            ]),
        )]);
        assert_eq!(decode_heroes(&encode_heroes(&h)), h);
    }

    #[test]
    fn encoding_actually_shortens_keys() {
        let h = stats(&[("genji", hero(&[("eliminations", 1), ("time_played", 2)]))]);
        let enc = encode_heroes(&h);
        assert!(enc["genji"].contains_key("e"));
        assert!(enc["genji"].contains_key("tp"));
        assert!(!enc["genji"].contains_key("eliminations"));
    }

    #[test]
    fn apply_reconstructs_absolute_state() {
        let mut acc = stats(&[("genji", hero(&[("eliminations", 100), ("deaths", 40)]))]);
        apply(&mut acc, &stats(&[("genji", hero(&[("eliminations", 25)]))]));
        apply(
            &mut acc,
            &stats(&[
                ("genji", hero(&[("eliminations", 10), ("deaths", 5)])),
                ("tracer", hero(&[("eliminations", 7)])),
            ]),
        );

        assert_eq!(acc["genji"]["eliminations"], 135);
        assert_eq!(acc["genji"]["deaths"], 45);
        assert_eq!(acc["tracer"]["eliminations"], 7, "new hero appears");
    }

    #[test]
    fn subtract_computes_window() {
        let from = stats(&[("genji", hero(&[("eliminations", 100), ("deaths", 40)]))]);
        let to = stats(&[("genji", hero(&[("eliminations", 160), ("deaths", 62)]))]);

        let w = subtract(&from, &to);
        assert_eq!(w["genji"]["eliminations"], 60);
        assert_eq!(w["genji"]["deaths"], 22);
    }
}
