//! End-to-end exercise of the stats store against a real OverFast
//! career payload.
//!
//! The unit tests inside `src/stats.rs` cover the diff/apply algebra with
//! hand-built maps. This file covers the parts that only break against
//! real data and a real filesystem: parsing the actual API shape, the
//! keyframe/delta/tombstone state machine, season-rollover handling, and
//! whether the on-disk format is actually as compact as claimed.
//!
//! `stats.rs` belongs to a binary crate, so it is pulled in by path the
//! same way `tests/merge_check.rs` pulls in `ranks.rs`.

#[path = "../src/stats.rs"]
#[allow(dead_code)]
mod stats;

use stats::{RecordOutcome, Snapshot};

const FIXTURE: &str = include_str!("fixtures/career_competitive.json");

/// Serialises every test that redirects the cache directory.
///
/// `XDG_CACHE_HOME` is process-global, but libtest runs tests as threads
/// within a single process. A per-test directory name therefore does not
/// isolate anything on its own: whichever test calls `Scratch::new` most
/// recently silently repoints the cache for every test already in
/// flight, so they read and write each other's logs. Holding this lock
/// for the duration of each test is what actually makes the redirect
/// safe. The cost is nil -- the whole file runs in ~10ms.
static CACHE_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Point the cache at a scratch dir so tests never touch the real
/// `~/.cache/bnetswitch/stats`.
struct Scratch {
    _dir: std::path::PathBuf,
    /// Released on drop, i.e. at the end of the test that built it.
    _guard: std::sync::MutexGuard<'static, ()>,
}

impl Scratch {
    fn new(name: &str) -> Self {
        // A failing test poisons the lock. That failure already gets
        // reported on its own; propagating the poison here would bury it
        // under a cascade of unrelated failures, so take the guard anyway.
        let guard = CACHE_ENV_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let dir = std::env::temp_dir().join(format!("bnetswitch-stats-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("create scratch dir");
        // `dirs::cache_dir()` honours XDG_CACHE_HOME on Linux.
        unsafe { std::env::set_var("XDG_CACHE_HOME", &dir) };
        Scratch {
            _dir: dir,
            _guard: guard,
        }
    }
}

fn fixture_snapshot(season: Option<u32>) -> Snapshot {
    let body: serde_json::Value = serde_json::from_str(FIXTURE).expect("fixture parses");
    stats::parse_career(&body, season)
}

#[test]
fn parses_real_payload() {
    let snap = fixture_snapshot(Some(24));

    let genji = snap.hero("genji").expect("genji present");
    assert_eq!(genji["games_played"], 48);
    assert_eq!(genji["games_won"], 26, "triplicated key collapsed");
    assert_eq!(genji["eliminations"], 896);
    assert_eq!(genji["deaths"], 430);
    assert_eq!(genji["critical_hits"], 1046);
    assert_eq!(genji["weapon_accuracy"], 30);
    assert_eq!(genji["critical_hit_accuracy"], 11);
    // Hero-specific counters survive even though they aren't in the
    // short-code table.
    assert_eq!(genji["dragonblade_kills"], 140);
    assert_eq!(genji["damage_deflected"], 72160);

    // Derived / max stats must not be stored.
    for k in [
        "eliminations_avg_per_10_min",
        "eliminations_most_in_game",
        "dragonblade_kills_most_in_game",
        "win_percentage",
        "eliminations_per_life",
    ] {
        assert!(!genji.contains_key(k), "{k} should have been dropped");
    }

    // Rollup aliases normalized to the per-hero spelling.
    let all = snap.overall().expect("all-heroes present");
    assert_eq!(all["all_damage_done"], 412758);
    assert_eq!(all["obj_contest_time"], 1277);
}

#[test]
fn first_write_is_a_keyframe_then_unchanged_polls_tombstone() {
    let _s = Scratch::new("keyframe");
    let tag = "Fix#1001";

    let snap = fixture_snapshot(Some(24));
    assert_eq!(
        stats::record_observation(tag, &snap).unwrap(),
        RecordOutcome::Keyframe
    );

    // Re-observing identical counters must not append a second copy.
    let mut again = fixture_snapshot(Some(24));
    again.ts = snap.ts + 900;
    assert_eq!(
        stats::record_observation(tag, &again).unwrap(),
        RecordOutcome::Unchanged
    );

    let mut third = fixture_snapshot(Some(24));
    third.ts = snap.ts + 1800;
    assert_eq!(
        stats::record_observation(tag, &third).unwrap(),
        RecordOutcome::Unchanged
    );

    // Two idle polls must coalesce into a single trailing tombstone.
    let path = stats::log_path(tag).unwrap();
    let body = std::fs::read_to_string(&path).unwrap();
    let lines: Vec<&str> = body.lines().filter(|l| !l.trim().is_empty()).collect();
    assert_eq!(lines.len(), 2, "keyframe + one coalesced tombstone");

    let tomb: serde_json::Value = serde_json::from_str(lines[1]).unwrap();
    assert_eq!(tomb["y"], "t");
    assert_eq!(tomb["n"], 2, "run length, not two separate lines");
    assert_eq!(tomb["t"], third.ts, "tombstone tracks latest poll");
    assert_eq!(tomb["f"], again.ts, "and remembers when the run began");

    // Replay ignores tombstones entirely.
    assert_eq!(stats::replay(tag).unwrap().len(), 1);
}

#[test]
fn play_produces_a_delta_and_replays_to_absolute() {
    let _s = Scratch::new("delta");
    let tag = "Fix#1002";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();

    // Simulate a session: +5 games, +90 elims, +40 deaths on Genji.
    let mut after = fixture_snapshot(Some(24));
    after.ts = base.ts + 3600;
    {
        let g = after.heroes.get_mut("genji").unwrap();
        *g.get_mut("games_played").unwrap() += 5;
        *g.get_mut("eliminations").unwrap() += 90;
        *g.get_mut("deaths").unwrap() += 40;
    }

    assert_eq!(
        stats::record_observation(tag, &after).unwrap(),
        RecordOutcome::Delta
    );

    let obs = stats::replay(tag).unwrap();
    assert_eq!(obs.len(), 2);
    let latest = &obs[1].snapshot;
    assert_eq!(latest.hero("genji").unwrap()["games_played"], 53);
    assert_eq!(latest.hero("genji").unwrap()["eliminations"], 986);
    assert_eq!(latest.hero("genji").unwrap()["deaths"], 470);
    // Untouched counters survive the delta round trip.
    assert_eq!(latest.hero("genji").unwrap()["dragonblade_kills"], 140);
    assert!(!obs[1].was_reset);

    // The window is the session, not the season.
    let w = stats::window_since(tag, base.ts).unwrap().expect("window");
    assert_eq!(w.hero("genji").unwrap()["games_played"], 5);
    assert_eq!(w.hero("genji").unwrap()["eliminations"], 90);
    assert_eq!(w.hero("genji").unwrap()["deaths"], 40);
    assert!(
        w.hero("bastion").is_none(),
        "hero that wasn't played must not appear in the window"
    );
}

#[test]
fn delta_only_stores_heroes_that_moved() {
    let _s = Scratch::new("sparse");
    let tag = "Fix#1003";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();

    let mut after = fixture_snapshot(Some(24));
    after.ts = base.ts + 3600;
    *after
        .heroes
        .get_mut("genji")
        .unwrap()
        .get_mut("eliminations")
        .unwrap() += 30;
    stats::record_observation(tag, &after).unwrap();

    let body = std::fs::read_to_string(stats::log_path(tag).unwrap()).unwrap();
    let last = body.lines().last().unwrap();
    let rec: serde_json::Value = serde_json::from_str(last).unwrap();

    let heroes = rec["h"].as_object().unwrap();
    assert_eq!(heroes.len(), 1, "only the played hero is stored");
    assert!(heroes.contains_key("genji"));

    let g = heroes["genji"].as_object().unwrap();
    assert_eq!(g.len(), 1, "only the changed counter is stored");
    assert_eq!(g["e"], 30, "short-coded and stored as a difference");
}

#[test]
fn season_rollover_forces_a_keyframe_and_bounds_windows() {
    let _s = Scratch::new("rollover");
    let tag = "Fix#1004";

    let s24 = fixture_snapshot(Some(24));
    stats::record_observation(tag, &s24).unwrap();

    // New season: counters reset to a small value AND the season number
    // advances. Either signal alone must be enough; here both fire.
    let mut s25 = fixture_snapshot(Some(25));
    s25.ts = s24.ts + 86_400;
    for counters in s25.heroes.values_mut() {
        for (k, v) in counters.iter_mut() {
            if !stats::is_aggregate(k) {
                *v = 3;
            }
        }
    }

    assert_eq!(
        stats::record_observation(tag, &s25).unwrap(),
        RecordOutcome::Keyframe,
        "rollover must not be recorded as a negative delta"
    );

    let obs = stats::replay(tag).unwrap();
    assert_eq!(obs.len(), 2);
    assert!(obs[1].was_reset);
    assert_eq!(obs[1].snapshot.season, Some(25));
    assert_eq!(
        obs[1].snapshot.hero("genji").unwrap()["eliminations"],
        3,
        "new season starts from the fresh absolute, not old + delta"
    );

    // A window asking for "since before the rollover" must not straddle
    // it and report nonsense negatives.
    let w = stats::window_since(tag, s24.ts).unwrap();
    assert!(
        w.is_none() || w.unwrap().from_ts >= s25.ts,
        "windows must never cross a reset boundary"
    );
}

#[test]
fn counter_reset_without_season_change_is_still_caught() {
    let _s = Scratch::new("silent-reset");
    let tag = "Fix#1005";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();

    // Season metadata unchanged (the two endpoints disagree mid-rollover)
    // but counters collapsed. The decrease alone must force a keyframe.
    let mut reset = fixture_snapshot(Some(24));
    reset.ts = base.ts + 7200;
    *reset
        .heroes
        .get_mut("genji")
        .unwrap()
        .get_mut("eliminations")
        .unwrap() = 5;

    assert_eq!(
        stats::record_observation(tag, &reset).unwrap(),
        RecordOutcome::Keyframe
    );
    assert!(stats::replay(tag).unwrap()[1].was_reset);
}

#[test]
fn tombstone_then_play_brackets_the_session() {
    let _s = Scratch::new("bracket");
    let tag = "Fix#1006";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();

    let mut idle = fixture_snapshot(Some(24));
    idle.ts = base.ts + 600;
    stats::record_observation(tag, &idle).unwrap();

    let mut played = fixture_snapshot(Some(24));
    played.ts = base.ts + 1200;
    *played
        .heroes
        .get_mut("genji")
        .unwrap()
        .get_mut("games_played")
        .unwrap() += 2;
    stats::record_observation(tag, &played).unwrap();

    let obs = stats::replay(tag).unwrap();
    assert_eq!(
        obs[1].prev_poll,
        Some(idle.ts),
        "the delta must point at the last known-idle poll, so the session \
         is bracketed to (idle, now] rather than the whole gap since base"
    );
}

#[test]
fn on_disk_format_is_actually_compact() {
    let _s = Scratch::new("size");
    let tag = "Fix#1007";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();
    let path = stats::log_path(tag).unwrap();
    let keyframe_len = std::fs::metadata(&path).unwrap().len();

    let mut after = fixture_snapshot(Some(24));
    after.ts = base.ts + 3600;
    {
        let g = after.heroes.get_mut("genji").unwrap();
        *g.get_mut("games_played").unwrap() += 3;
        *g.get_mut("eliminations").unwrap() += 55;
        *g.get_mut("deaths").unwrap() += 26;
        *g.get_mut("time_played").unwrap() += 1900;
    }
    stats::record_observation(tag, &after).unwrap();
    let delta_len = std::fs::metadata(&path).unwrap().len() - keyframe_len;

    let raw = FIXTURE.len() as u64;

    // Guard rails rather than exact figures, so incidental changes don't
    // fail the suite but a regression in the compaction scheme does.
    assert!(
        keyframe_len * 8 < raw,
        "keyframe {keyframe_len}B should be far smaller than raw {raw}B"
    );
    assert!(
        delta_len < 300,
        "a 4-counter single-hero delta should be tiny, got {delta_len}B"
    );

    eprintln!(
        "raw fixture {raw}B (3 heroes) -> keyframe {keyframe_len}B, session delta {delta_len}B"
    );
}

/// End-to-end against the live OverFast instance.
///
/// Ignored by default: it needs network, depends on a third party being
/// up, and hits a real BattleTag. Run deliberately with
/// `cargo test --test stats_store -- --ignored --nocapture`.
#[test]
#[ignore = "requires network access to overfast-api.tekrop.fr"]
fn live_fetch_records_an_observation() {
    let _s = Scratch::new("live");
    let tag = "Pogo#11926";

    let snap = stats::fetch_career(tag, Some(24))
        .expect("request succeeded")
        .expect("profile is public");

    assert!(!snap.is_empty(), "live payload produced no heroes");
    let all = snap.overall().expect("all-heroes rollup present");
    assert!(all.contains_key("games_played"));
    assert!(all.contains_key("eliminations"));

    assert_eq!(
        stats::record_observation(tag, &snap).unwrap(),
        RecordOutcome::Keyframe
    );

    // Re-recording the same payload must be a no-op tombstone, not a
    // duplicate keyframe.
    assert_eq!(
        stats::record_observation(tag, &snap).unwrap(),
        RecordOutcome::Unchanged
    );

    let path = stats::log_path(tag).unwrap();
    let size = std::fs::metadata(&path).unwrap().len();
    let obs = stats::replay(tag).unwrap();
    eprintln!(
        "live: {} heroes, log {}B, {} observation(s)",
        snap.heroes.len(),
        size,
        obs.len()
    );
}

#[test]
fn keyframes_recur_so_replay_stays_bounded() {
    let _s = Scratch::new("cadence");
    let tag = "Fix#1008";

    let base = fixture_snapshot(Some(24));
    stats::record_observation(tag, &base).unwrap();

    // Drive well past the keyframe interval.
    let mut elims = base.hero("genji").unwrap()["eliminations"];
    for i in 1..=60u64 {
        let mut s = fixture_snapshot(Some(24));
        s.ts = base.ts + i * 600;
        elims += 10;
        *s.heroes
            .get_mut("genji")
            .unwrap()
            .get_mut("eliminations")
            .unwrap() = elims;
        stats::record_observation(tag, &s).unwrap();
    }

    let body = std::fs::read_to_string(stats::log_path(tag).unwrap()).unwrap();
    let keyframes = body
        .lines()
        .filter(|l| {
            serde_json::from_str::<serde_json::Value>(l)
                .map(|v| v["y"] == "k")
                .unwrap_or(false)
        })
        .count();
    assert!(
        keyframes >= 2,
        "a periodic keyframe should have been emitted, found {keyframes}"
    );

    // And the replayed total must still be exact.
    let obs = stats::replay(tag).unwrap();
    assert_eq!(
        obs.last().unwrap().snapshot.hero("genji").unwrap()["eliminations"],
        elims
    );
}
