//! Overwatch 2 competitive rank lookup via the OverFast API.
//!
//! ## Why OverFast
//!
//! Blizzard provides no first-party API. OverFast is a community-run
//! scraper of `overwatch.blizzard.com` career pages. We hit its public
//! instance rather than scraping the HTML ourselves. Privacy: the
//! BattleTags we look up become visible to that third-party server. For
//! competitive smurf accounts the data is publicly visible on Blizzard's
//! site already, so this is generally acceptable.
//!
//! ## Historical placements
//!
//! Blizzard's career page only shows the *current* season's placements.
//! There is no public source of past-season rank data. To approximate
//! "last placed in any season" behaviour, we keep our own running cache:
//!
//! - Every fetch persists the rank snapshot per role with its season.
//! - When a fresh fetch returns `null` for a role, we keep the most
//!   recent non-null cached snapshot rather than overwriting with `null`.
//! - The TUI marks any snapshot whose season is older than the highest
//!   season we've ever seen as "stale" (dimmed, with season tag).
//!
//! The implication: bnetswitch's first run for an account only shows
//! current-season data. Across season transitions, the cache accumulates
//! a useful "last seen rank per role" history.
//!
//! ## Caching TTL
//!
//! Disk cache is considered fresh for one hour. Rank changes happen at
//! most once per match, so this avoids hammering OverFast across TUI
//! restarts while still keeping data near-current within a single play
//! session.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const OVERFAST_BASE: &str = "https://overfast-api.tekrop.fr/players";
const CACHE_TTL: Duration = Duration::from_secs(60 * 60); // 1 hour
const HTTP_TIMEOUT: Duration = Duration::from_secs(10);

/// Overwatch 2 competitive division. Tier within a division is 1-5
/// where 1 is the highest sub-division (Diamond 1 > Diamond 5).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Division {
    Bronze,
    Silver,
    Gold,
    Platinum,
    Diamond,
    Master,
    Grandmaster,
    Champion,
    /// Top 500 has no internal tiers; we still fit it into the model
    /// with tier=1 for display uniformity.
    #[serde(rename = "top500", alias = "top_500")]
    Top500,
}

impl Division {
    pub fn short_label(self) -> &'static str {
        match self {
            Division::Bronze => "Bronze",
            Division::Silver => "Silver",
            Division::Gold => "Gold",
            Division::Platinum => "Plat",
            Division::Diamond => "Diam",
            Division::Master => "Mast",
            Division::Grandmaster => "GM",
            Division::Champion => "Champ",
            Division::Top500 => "T500",
        }
    }
}

/// One observed rank for a single role at a particular season.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RankSnapshot {
    pub division: Division,
    pub tier: u8,
    /// Season number this rank was observed in. Used to determine whether
    /// to render the rank as "stale" (older than the current season).
    pub season: u32,
}

impl RankSnapshot {
    /// Compact display: "Plat 1", "Diam 3", "GM 2", "T500".
    pub fn label(&self) -> String {
        match self.division {
            Division::Top500 => "T500".to_string(),
            _ => format!("{} {}", self.division.short_label(), self.tier),
        }
    }
}

/// Cached rank record for one BattleTag.
///
/// `current_season` is the most recent season we've fetched data for,
/// across all the per-role snapshots. Each role's snapshot may be from
/// an earlier season if we haven't seen that role placed since.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RoleRanks {
    /// Latest season seen across any of this account's fetches.
    pub current_season: Option<u32>,
    pub tank: Option<RankSnapshot>,
    pub damage: Option<RankSnapshot>,
    pub support: Option<RankSnapshot>,
    /// Unix epoch seconds of the last fetch (cache freshness check).
    #[serde(default)]
    pub fetched_at_epoch: u64,
    /// True when the most recent fetch returned 404 / not found.
    /// Lets the TUI distinguish "private account" from "haven't tried yet".
    #[serde(default)]
    pub not_found: bool,
}

impl RoleRanks {
    fn now_epoch() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    }

    pub fn is_stale(&self) -> bool {
        let age = Self::now_epoch().saturating_sub(self.fetched_at_epoch);
        age > CACHE_TTL.as_secs()
    }

    /// True if a role's snapshot is from a season older than the latest
    /// season we've fetched for this account. Used by the UI to dim the
    /// rank rendering.
    pub fn is_role_from_past_season(&self, role: Role) -> bool {
        let snap = match self.role(role) {
            Some(s) => s,
            None => return false,
        };
        match self.current_season {
            Some(current) => snap.season < current,
            None => false,
        }
    }

    pub fn role(&self, role: Role) -> Option<&RankSnapshot> {
        match role {
            Role::Tank => self.tank.as_ref(),
            Role::Damage => self.damage.as_ref(),
            Role::Support => self.support.as_ref(),
        }
    }

    /// Merge a freshly fetched record into a cached one. The merged
    /// result keeps the latest season's snapshot for each role: if the
    /// fresh fetch has a non-null rank, it wins; otherwise the cached
    /// (potentially older-season) snapshot is preserved.
    fn merge_in(&mut self, fresh: RoleRanks) {
        // Track the highest season we've ever seen for this account.
        self.current_season = match (self.current_season, fresh.current_season) {
            (Some(a), Some(b)) => Some(a.max(b)),
            (Some(a), None) => Some(a),
            (None, b) => b,
        };
        // For each role, prefer the fresh non-null snapshot. If the fresh
        // value is null, retain whatever we had before (could be older).
        if fresh.tank.is_some() {
            self.tank = fresh.tank;
        }
        if fresh.damage.is_some() {
            self.damage = fresh.damage;
        }
        if fresh.support.is_some() {
            self.support = fresh.support;
        }
        self.fetched_at_epoch = fresh.fetched_at_epoch;
        self.not_found = fresh.not_found;
    }
}

/// Logical role enumeration for indexing snapshots.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    Tank,
    Damage,
    Support,
}

fn cache_dir() -> Result<PathBuf> {
    let base = dirs::cache_dir().context("Could not determine cache directory")?;
    let dir = base.join("bnetswitch").join("ranks");
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("Failed to create cache dir {}", dir.display()))?;
    Ok(dir)
}

fn cache_filename(battletag: &str) -> String {
    format!("{}.json", battletag.replace('#', "-"))
}

fn battletag_to_url_segment(battletag: &str) -> String {
    battletag.replace('#', "-")
}

/// Load whatever's in the cache file, regardless of staleness. Used as
/// the base for merging fresh fetches into.
pub fn load_any_cached(battletag: &str) -> Option<RoleRanks> {
    let dir = cache_dir().ok()?;
    let path = dir.join(cache_filename(battletag));
    let content = std::fs::read_to_string(&path).ok()?;
    serde_json::from_str(&content).ok()
}

/// Load the cached entry only if it's still within the freshness TTL.
pub fn load_fresh_cached(battletag: &str) -> Option<RoleRanks> {
    let cached = load_any_cached(battletag)?;
    if cached.is_stale() {
        None
    } else {
        Some(cached)
    }
}

/// Persist a rank record to disk. Cache write failures are non-fatal
/// (we just refetch next time), so errors are swallowed.
pub fn save_cached(battletag: &str, ranks: &RoleRanks) {
    let Ok(dir) = cache_dir() else { return };
    let path = dir.join(cache_filename(battletag));
    if let Ok(json) = serde_json::to_string_pretty(ranks) {
        let _ = std::fs::write(path, json);
    }
}

/// Drop the cached entry to force a network refetch on the next lookup.
pub fn invalidate_cache(battletag: &str) {
    let Ok(dir) = cache_dir() else { return };
    let path = dir.join(cache_filename(battletag));
    let _ = std::fs::remove_file(path);
}

/// Fetch fresh rank data from OverFast, merge into any existing cached
/// history, persist, and return the merged result.
///
/// Use `force=true` to bypass the freshness check and always hit the
/// network; otherwise a still-fresh cache entry is returned without an
/// HTTP call.
pub fn fetch_and_merge(battletag: &str, force: bool) -> Result<RoleRanks> {
    if !force {
        if let Some(fresh) = load_fresh_cached(battletag) {
            return Ok(fresh);
        }
    }

    let mut merged = load_any_cached(battletag).unwrap_or_default();

    let url = format!(
        "{}/{}/summary",
        OVERFAST_BASE,
        battletag_to_url_segment(battletag)
    );

    let agent = ureq::AgentBuilder::new()
        .timeout(HTTP_TIMEOUT)
        .user_agent("bnetswitch/0.1")
        .build();

    let result = agent.get(&url).call();

    match result {
        Ok(response) => {
            let body: serde_json::Value = response.into_json().with_context(|| {
                format!("Failed to parse OverFast JSON for {}", battletag)
            })?;
            let fresh = parse_overfast_response(&body);
            merged.merge_in(fresh);
            merged.not_found = false;
            save_cached(battletag, &merged);
            Ok(merged)
        }
        Err(ureq::Error::Status(404, _)) => {
            // Profile is private or doesn't exist. Mark as such so the
            // TUI can distinguish "private" from "we haven't tried yet".
            merged.fetched_at_epoch = RoleRanks::now_epoch();
            merged.not_found = true;
            save_cached(battletag, &merged);
            Ok(merged)
        }
        Err(e) => {
            // Transport / HTTP error. Don't update the cache; let the
            // existing entry (if any) stand.
            Err(anyhow::anyhow!("OverFast request failed: {}", e))
        }
    }
}

/// Parse the OverFast `/summary` response into our model.
fn parse_overfast_response(body: &serde_json::Value) -> RoleRanks {
    let pc = body
        .get("competitive")
        .and_then(|c| c.get("pc"))
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let season = pc.get("season").and_then(|v| v.as_u64()).map(|s| s as u32);

    RoleRanks {
        current_season: season,
        tank: parse_role_snapshot(pc.get("tank"), season),
        damage: parse_role_snapshot(pc.get("damage"), season),
        support: parse_role_snapshot(pc.get("support"), season),
        fetched_at_epoch: RoleRanks::now_epoch(),
        not_found: false,
    }
}

fn parse_role_snapshot(
    value: Option<&serde_json::Value>,
    season: Option<u32>,
) -> Option<RankSnapshot> {
    let v = value?;
    if v.is_null() {
        return None;
    }
    let division_str = v.get("division")?.as_str()?;
    let tier = v.get("tier")?.as_u64()? as u8;
    let division = match division_str.to_ascii_lowercase().as_str() {
        "bronze" => Division::Bronze,
        "silver" => Division::Silver,
        "gold" => Division::Gold,
        "platinum" => Division::Platinum,
        "diamond" => Division::Diamond,
        "master" => Division::Master,
        "grandmaster" => Division::Grandmaster,
        "champion" => Division::Champion,
        "top500" | "top_500" => Division::Top500,
        _ => return None,
    };
    Some(RankSnapshot {
        division,
        tier,
        // If the response is missing a season number, we still tag the
        // snapshot with 0 so it sorts as "older than anything sensible"
        // and the UI can dim it on later season comparisons.
        season: season.unwrap_or(0),
    })
}
