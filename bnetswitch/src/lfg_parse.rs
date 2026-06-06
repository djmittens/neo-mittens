//! Heuristic parser for free-form LFG embed descriptions.
//!
//! The OW LFG bot's embed `description` field carries unstructured text
//! like "2 supports needed:) silver 1 - gold 1" or "plat supp". We need
//! to extract:
//!   - rank range (min, max)
//!   - roles needed
//!   - count of open slots (when stated)
//!
//! ## Why heuristic instead of LLM
//!
//! - LLM shell-out (`opencode` CLI) takes 1-3s per message; the LFG
//!   channel produces ~1 msg/min so this is borderline acceptable BUT
//!   it adds a runtime dependency and makes parsing non-deterministic.
//! - The free-form text follows a small number of common patterns.
//!   Regex handles ~85% of real-world LFG posts cleanly.
//! - Heuristic is unit-testable and fast (microseconds per call).
//! - For the remaining ~15% of weird/cute/multi-rank posts, the parser
//!   returns "unknown" rather than guessing wrong, and we display them
//!   in the TUI with raw text. User can decide manually.
//!
//! Future hook: if a message parses with low confidence, we could shell
//! out to opencode as a fallback. Not implemented yet — see TODO at end.

use serde::{Deserialize, Serialize};

// ============================================================================
// Domain types
// ============================================================================

/// Overwatch competitive tier. Ordered from lowest skill to highest.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Tier {
    Bronze,
    Silver,
    Gold,
    Platinum,
    Diamond,
    Master,
    Grandmaster,
    /// Top 500 / Champion. Single tier above Grandmaster.
    Champion,
}

impl Tier {
    fn rank(self) -> u8 {
        match self {
            Tier::Bronze => 0,
            Tier::Silver => 1,
            Tier::Gold => 2,
            Tier::Platinum => 3,
            Tier::Diamond => 4,
            Tier::Master => 5,
            Tier::Grandmaster => 6,
            Tier::Champion => 7,
        }
    }

    /// Human-readable short label for TUI display.
    pub fn short(self) -> &'static str {
        match self {
            Tier::Bronze => "Br",
            Tier::Silver => "Si",
            Tier::Gold => "Go",
            Tier::Platinum => "Pl",
            Tier::Diamond => "Di",
            Tier::Master => "Ma",
            Tier::Grandmaster => "GM",
            Tier::Champion => "Ch",
        }
    }

    /// A single Unicode glyph that visually distinguishes tiers in the
    /// TUI when graphics protocols aren't available (Alacritty, tmux
    /// without passthrough, SSH, etc.).
    ///
    /// Each tier gets a UNIQUE glyph -- previous version reused ◆ for
    /// three tiers and ▰ for three tiers, which made fallback rendering
    /// visually ambiguous. Now: shape escalates with tier rank:
    ///   - Bronze/Silver/Gold:   triangle / outline gem / boxed gem
    ///     (primitive shapes, plain stacking)
    ///   - Platinum/Diamond:     filled gem / multi-faceted gem
    ///     (refined gem progression)
    ///   - Master/Grandmaster/
    ///     Champion:             4-pt star / 5-pt star / circled star
    ///     (star prestige tier)
    pub fn glyph(self) -> &'static str {
        match self {
            Tier::Bronze      => "▼", // filled down-triangle (anchor)
            Tier::Silver      => "◇", // outline diamond
            Tier::Gold        => "◈", // boxed diamond
            Tier::Platinum    => "◆", // filled diamond
            Tier::Diamond     => "❖", // multi-faceted diamond
            Tier::Master      => "✦", // 4-point star
            Tier::Grandmaster => "★", // 5-point star (classic)
            Tier::Champion    => "✪", // circled emblem
        }
    }

    /// 24-bit RGB color for the tier glyph + PNG underlay tint. Picked
    /// to be MAXIMALLY DISTINCT across tiers (every adjacent pair is
    /// from a different region of the color wheel) while still loosely
    /// matching the in-game palette.
    ///
    /// Why distinct over accurate: in-game OW Plat and Diamond ARE
    /// both pale cyan-teal -- visually similar even on the actual
    /// rank badges. In a TUI cell that's only ~16px tall, two pale
    /// teals are indistinguishable. We bias toward gameplay
    /// comprehension over color authenticity:
    ///   Bronze    → copper-brown
    ///   Silver    → silver-gray
    ///   Gold      → gold-yellow      (warm)
    ///   Platinum  → SATURATED TEAL   (greenish, distinct from Diamond)
    ///   Diamond   → SATURATED BLUE   (cyan-blue, distinct from Plat)
    ///   Master    → VIOLET           (cool, distinct from GM)
    ///   GM        → CRIMSON          (warm red)
    ///   Champion  → ORANGE           (warmest, top of ladder)
    /// Color cycle: brown → gray → yellow → green → blue → violet →
    /// red → orange. Every neighbor is different hue *and* different
    /// brightness.
    pub fn color_rgb(self) -> (u8, u8, u8) {
        match self {
            Tier::Bronze      => (0xcd, 0x7f, 0x32), // copper-brown
            Tier::Silver      => (0xc0, 0xc0, 0xc0), // silver-gray
            Tier::Gold        => (0xff, 0xd7, 0x00), // warm gold
            Tier::Platinum    => (0x4d, 0xc9, 0xb0), // saturated teal
            Tier::Diamond     => (0x4d, 0x9e, 0xff), // saturated blue
            Tier::Master      => (0xc2, 0x66, 0xff), // saturated violet
            Tier::Grandmaster => (0xff, 0x55, 0x77), // crimson
            Tier::Champion    => (0xff, 0x88, 0x00), // burning orange
        }
    }

    /// Convert from the rank-fetcher's `Division` enum (defined in
    /// `ranks.rs` against the OverFast API schema) to our local `Tier`.
    /// They're conceptually identical except `Division::Top500` collapses
    /// into our `Champion` (OW2 renamed Top500 to Champion in S15-ish; the
    /// API still emits both names depending on season).
    pub fn from_division(d: crate::ranks::Division) -> Self {
        use crate::ranks::Division;
        match d {
            Division::Bronze => Tier::Bronze,
            Division::Silver => Tier::Silver,
            Division::Gold => Tier::Gold,
            Division::Platinum => Tier::Platinum,
            Division::Diamond => Tier::Diamond,
            Division::Master => Tier::Master,
            Division::Grandmaster => Tier::Grandmaster,
            Division::Champion | Division::Top500 => Tier::Champion,
        }
    }
}

impl RankPoint {
    /// Build a RankPoint from the rank-fetcher's `RankSnapshot`.
    pub fn from_snapshot(s: &crate::ranks::RankSnapshot) -> Self {
        let div = if s.tier >= 1 && s.tier <= 5 {
            s.tier
        } else {
            // Top500 has no internal divisions; we model as div=1 (top).
            1
        };
        RankPoint {
            tier: Tier::from_division(s.division),
            division: div,
        }
    }
}

/// A specific point on the OW skill ladder. `division` is 1-5 where 1
/// is the highest (most skilled) within that tier.
///
/// Examples:
///   - Bronze 5    = lowest Bronze division
///   - Diamond 1   = top Diamond
///   - Champion 1  = top of the ladder
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct RankPoint {
    pub tier: Tier,
    /// 1 (highest) through 5 (lowest). When LFG poster doesn't specify
    /// a division, default to 5 for a "min" point and 1 for a "max" point
    /// so the range covers the whole tier.
    pub division: u8,
}

impl RankPoint {
    /// Convert to a single integer score for easy range comparison.
    /// Higher score = higher rank. Each tier spans 5 score points
    /// (one per division).
    pub fn score(self) -> u32 {
        // 5 divisions per tier, division 1 (top) = 4, division 5 (bottom) = 0.
        // So Bronze 5 = 0, Bronze 1 = 4, Silver 5 = 5, ..., Champion 1 = 39.
        let div_score = if self.division >= 1 && self.division <= 5 {
            5 - self.division
        } else {
            // Out-of-range divisions clamp to "middle" rather than failing.
            2
        } as u32;
        self.tier.rank() as u32 * 5 + div_score
    }

    /// Display like "Plat 1" or "GM 3".
    pub fn label(self) -> String {
        format!("{} {}", self.tier.short(), self.division)
    }

    /// Build a RankPoint from a 0..=39 ladder score (the inverse of
    /// `score()`). Returns None for out-of-range scores.
    fn from_score(score: u32) -> Option<Self> {
        if score > 39 {
            return None;
        }
        let tier_idx = (score / 5) as u8;
        let div_offset = (score % 5) as u8;
        let tier = match tier_idx {
            0 => Tier::Bronze,
            1 => Tier::Silver,
            2 => Tier::Gold,
            3 => Tier::Platinum,
            4 => Tier::Diamond,
            5 => Tier::Master,
            6 => Tier::Grandmaster,
            7 => Tier::Champion,
            _ => return None,
        };
        // div_offset 0 = bottom of tier (div 5), 4 = top (div 1)
        let division = 5 - div_offset;
        Some(RankPoint { tier, division })
    }

    /// Add `n` divisions, walking UP the ladder. Saturates at Champion 1.
    /// Used for the Bronze-Diamond "5 division wide-group" rule when
    /// expanding a bare tier mention like "plat" -> Plat 5 to Diamond 5.
    fn add_divisions(self, n: u32) -> RankPoint {
        let target = self.score().saturating_add(n).min(39);
        Self::from_score(target).unwrap_or(self)
    }
}

impl PartialOrd for RankPoint {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for RankPoint {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.score().cmp(&other.score())
    }
}

/// One of the three OW competitive roles, plus a "Flex" catch-all that
/// some LFG posters use when role doesn't matter to them.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Role {
    Tank,
    Dps,
    Support,
    Flex,
}

impl Role {
    pub fn label(self) -> &'static str {
        match self {
            Role::Tank => "Tank",
            Role::Dps => "DPS",
            Role::Support => "Supp",
            Role::Flex => "Flex",
        }
    }
}

/// Region the LFG is recruiting in. We only carry common ones; unknown
/// values fall through to `None`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Region {
    Na,
    Eu,
    Asia,
    Oce,
}

impl Region {
    #[allow(dead_code)] // surfaced in TUI in a future iteration
    pub fn label(self) -> &'static str {
        match self {
            Region::Na => "NA",
            Region::Eu => "EU",
            Region::Asia => "ASIA",
            Region::Oce => "OCE",
        }
    }
}

/// Output of parsing one LFG message description. All fields optional
/// because the LFG poster may omit anything; consumers should treat
/// missing fields as "unspecified" not as failures.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParsedLfg {
    pub rank_min: Option<RankPoint>,
    pub rank_max: Option<RankPoint>,
    pub roles_needed: Vec<Role>,
    /// Number of open slots, when explicitly stated (e.g. "2 supports
    /// needed"). 0 means unspecified.
    pub slots_open: u32,
    pub region: Option<Region>,
    /// Raw description after lowercasing + whitespace normalization.
    /// Useful for the TUI to display the original intent when our
    /// structured fields are empty/wrong.
    pub normalized_text: String,
}

// ============================================================================
// Parser
// ============================================================================

/// Parse a raw LFG description (the embed's `description` field) into
/// structured form.
pub fn parse_description(text: &str) -> ParsedLfg {
    let normalized = normalize(text);
    let mut out = ParsedLfg {
        normalized_text: normalized.clone(),
        ..Default::default()
    };

    out.roles_needed = parse_roles(&normalized);
    out.slots_open = parse_slot_count(&normalized);
    out.region = parse_region(&normalized);

    let (min, max) = parse_rank_range(&normalized);
    out.rank_min = min;
    out.rank_max = max;

    out
}

impl ParsedLfg {
    /// Merge another ParsedLfg into self, taking the most informative
    /// value per field. Used when grouping multiple LFG posts for the
    /// same voice channel: people make typos, omit ranks, post conflicting
    /// role requests, etc.
    ///
    /// Field-by-field strategy:
    /// - rank_min / rank_max: take the INTERSECTION (highest min, lowest
    ///   max). Rationale: when two stackmates recruit for the SAME group,
    ///   a candidate must satisfy BOTH posters' rank requirements. If
    ///   teammate A says "gold" (Go5-Pl5) and teammate B says "gold+"
    ///   (Go5-Ch1), the group's effective acceptance is Go5-Pl5 -- A
    ///   wouldn't accept a Master, even though B would. Taking the
    ///   union (the previous behavior) was misleading: it inflated the
    ///   displayed range to cover ranks neither poster actually agreed
    ///   on together. If the intersection is empty (one says bronze,
    ///   another says diamond -- they disagree wildly), we fall back to
    ///   self's original range to preserve the canonical post's intent.
    /// - roles_needed: union of all roles mentioned (anyone in the group
    ///   may have called out a role -- additive recruitment).
    /// - slots_open: take the MAX (someone forgot to update after a fill;
    ///   the largest stated count is the most-recent-truth surrogate).
    /// - region: prefer Some over None, otherwise self.
    /// - normalized_text: concatenate distinct snippets so the user can
    ///   read all the original posts (deduplicated for visual cleanliness).
    pub fn merge_in(&mut self, other: &ParsedLfg) {
        // Rank range: INTERSECTION
        let new_min = match (self.rank_min, other.rank_min) {
            // Take the HIGHER lower bound: both posters have to be
            // satisfied, so the floor moves up.
            (Some(a), Some(b)) => Some(if a > b { a } else { b }),
            (Some(a), None) => Some(a),
            (None, Some(b)) => Some(b),
            (None, None) => None,
        };
        let new_max = match (self.rank_max, other.rank_max) {
            // Take the LOWER upper bound: both posters have to be
            // satisfied, so the ceiling drops.
            (Some(a), Some(b)) => Some(if a < b { a } else { b }),
            (Some(a), None) => Some(a),
            (None, Some(b)) => Some(b),
            (None, None) => None,
        };
        // Validate the intersection isn't empty (e.g., one says bronze,
        // another says diamond). Empty intersection means the posts
        // disagree, and silently mashing them together produces a
        // nonsense range. Prefer self's stated range in that case --
        // the caller should choose `self` as whichever is more
        // canonical (typically the most recent post).
        let intersection_valid = match (new_min, new_max) {
            (Some(a), Some(b)) => a <= b,
            _ => true,
        };
        if intersection_valid {
            self.rank_min = new_min;
            self.rank_max = new_max;
        }
        // else: keep self's existing range unchanged.

        // Roles: union (preserve order: self's roles then any new from other)
        for role in &other.roles_needed {
            if !self.roles_needed.contains(role) {
                self.roles_needed.push(*role);
            }
        }

        // Slots: max
        if other.slots_open > self.slots_open {
            self.slots_open = other.slots_open;
        }

        // Region: prefer non-None
        if self.region.is_none() && other.region.is_some() {
            self.region = other.region;
        }

        // Normalized text: concat distinct snippets, separated by " | "
        if !other.normalized_text.is_empty()
            && !self.normalized_text.contains(&other.normalized_text)
        {
            if !self.normalized_text.is_empty() {
                self.normalized_text.push_str(" | ");
            }
            self.normalized_text.push_str(&other.normalized_text);
        }
    }
}

fn normalize(s: &str) -> String {
    // Lowercase, trim, collapse runs of whitespace, drop common emoji/punct.
    //
    // Kept chars: alphanumeric, `-` (rank ranges), `+` (open-ended ranks
    // like "d3+"), `#` (BattleTag tags), `@` (mentions).
    //
    // Treated as whitespace separator: `/` (e.g. "dps/sup"), `,`, `;`,
    // `\`, `.`, `=` (some posts use `=` as range separator like "d3=m2").
    // So "dps/sup" tokenizes to ["dps", "sup"], not "dpssup".
    //
    // PRE-PROCESS Discord custom emoji `<:Name:numeric_id>` → just `Name`
    // so semantic info embedded in :Gold: :Tank: emoji isn't lost when
    // we strip `<` `>` `:` as punctuation.
    let s = strip_discord_emoji(s);

    let mut out = String::with_capacity(s.len());
    let mut prev_ws = true;
    for c in s.chars() {
        let lc = c.to_ascii_lowercase();
        if lc.is_whitespace() || matches!(lc, '/' | ',' | ';' | '\\' | '.' | '=') {
            if !prev_ws {
                out.push(' ');
                prev_ws = true;
            }
        } else if lc.is_ascii_alphanumeric() || "-+#@".contains(lc) {
            out.push(lc);
            prev_ws = false;
        }
        // Drop everything else (emoji, other punctuation, non-ASCII).
    }
    out.trim().to_string()
}

/// Replace Discord custom emoji syntax with just the emoji name so the
/// semantic info (e.g. `<:Gold:1272892603561541694>` → `gold`) survives
/// punctuation stripping. Animated variant `<a:Name:id>` handled too.
fn strip_discord_emoji(s: &str) -> String {
    // s.as_bytes() is safe to byte-index because we only match ASCII
    // delimiters (`<` `:` `>` `a`); we slice the original `s` only at
    // those byte offsets which are guaranteed to be UTF-8 char boundaries.
    // Non-ASCII bytes in between get passed through via the `s` string slice.
    let bytes = s.as_bytes();
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    while i < bytes.len() {
        let lookahead_2 = i + 2 <= bytes.len() && &bytes[i..i + 2] == b"<:";
        let lookahead_3 = i + 3 <= bytes.len() && &bytes[i..i + 3] == b"<a:";
        let prefix_len = if lookahead_3 { 3 } else if lookahead_2 { 2 } else { 0 };
        if prefix_len > 0 {
            let after_prefix = i + prefix_len;
            if let Some(colon2_off) = bytes[after_prefix..].iter().position(|&b| b == b':') {
                let colon2 = after_prefix + colon2_off;
                if let Some(gt_off) = bytes[colon2 + 1..].iter().position(|&b| b == b'>') {
                    let gt = colon2 + 1 + gt_off;
                    let id_part = &bytes[colon2 + 1..gt];
                    if !id_part.is_empty() && id_part.iter().all(|c| c.is_ascii_digit()) {
                        out.push(' ');
                        out.push_str(&s[after_prefix..colon2]);
                        out.push(' ');
                        i = gt + 1;
                        continue;
                    }
                }
            }
        }
        // Pass through one full UTF-8 char.
        let c = s[i..].chars().next().unwrap();
        out.push(c);
        i += c.len_utf8();
    }
    out
}

// ----------------------------------------------------------------------
// Tier / rank parsing
// ----------------------------------------------------------------------

/// Map a normalized rank-name fragment to a Tier.
///
/// Includes single-letter abbreviations (b/s/g/p/d/m -- ambiguous letters
/// resolved by-frequency: g=Gold not Grandmaster, m=Master not anything
/// else) for compact range syntax like "d3-m4". Also covers common typos
/// observed in real LFG posts (gld, plt, brz, dmnd, sil, mstr, tnk).
fn tier_from_word(w: &str) -> Option<Tier> {
    Some(match w {
        // Single-letter compact (most-common-tier-by-letter heuristic)
        "b" => Tier::Bronze,
        "s" => Tier::Silver,
        "g" => Tier::Gold,
        "p" => Tier::Platinum,
        "d" => Tier::Diamond,
        "m" => Tier::Master,
        // Multi-char abbreviations + canonical names + observed typos
        "br" | "brz" | "bronze" | "bronz" => Tier::Bronze,
        "si" | "sil" | "silv" | "silver" | "sliver" | "silvr" => Tier::Silver,
        "go" | "gld" | "gold" => Tier::Gold,
        "pl" | "plt" | "plat" | "plats" | "platinum" | "platinim" => Tier::Platinum,
        "di" | "dia" | "diam" | "dmnd" | "diamond"
            | "daimond" | "dimaond" | "dimoand" | "diomand" | "diamound"
            | "dia." => Tier::Diamond,
        "ma" | "mast" | "mstr" | "master" | "masters" | "mastrs" => Tier::Master,
        "gm" | "grand" | "grandmaster" | "grandmasters" => Tier::Grandmaster,
        "ch" | "champ" | "champion" | "champs" | "t500" | "top500" => Tier::Champion,
        _ => return None,
    })
}

/// Parse a "compact" token like "d3", "plat5", "g1", "dia5" -- a tier
/// prefix glued directly to a 1-5 division digit. Strict: returns None
/// if there's no digit (use `tier_from_word` for bare-tier tokens).
fn parse_compact_rank_strict(token: &str) -> Option<RankPoint> {
    // Find first digit; alpha prefix is everything before it.
    let split = token.char_indices().find(|(_, c)| c.is_ascii_digit())?.0;
    if split == 0 {
        return None; // No alpha prefix
    }
    let prefix = &token[..split];
    let suffix = &token[split..];
    let tier = tier_from_word(prefix)?;
    let div = suffix
        .parse::<u8>()
        .ok()
        .filter(|&n| (1..=5).contains(&n))?;
    Some(RankPoint { tier, division: div })
}

/// Parse a token as either a compact "tier+digit" (e.g. "d3") OR a bare
/// tier word (e.g. "diamond") with the supplied default division.
fn parse_rank_token(token: &str, default_div: u8) -> Option<RankPoint> {
    if let Some(rp) = parse_compact_rank_strict(token) {
        return Some(rp);
    }
    let tier = tier_from_word(token)?;
    Some(RankPoint {
        tier,
        division: default_div,
    })
}

/// Parse a single rank descriptor anywhere within a phrase.
///
/// Handles real-world LFG text where the rank is often surrounded by
/// role/slot-count cruft:
///   "diamond 3"                      -> Diamond 3
///   "plat 1"                         -> Platinum 1
///   "GM"                             -> Grandmaster (default div)
///   "low dia"                        -> Diamond, division 5
///   "2 supports needed silver 1"     -> Silver 1   (rank at end)
///   "looking for support, plat"      -> Platinum   (rank at end)
///
/// Source of a parsed rank's division -- determines whether to expand
/// it as a wide-group range or use as-is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DivSource {
    /// Poster wrote a specific division ("plat 3", "d3"). This is
    /// usually their own rank; the matcher should expand by ±5 div.
    Explicit,
    /// Bare tier mention ("plat") with no division. Apply tier-bottom
    /// + 5 div wide-group rule (single_tier_range).
    BareTier,
    /// "low" / "high" / "mid" modifier ("low plat"). Treat as a near-
    /// point: anchor at that division ±0 (preserve poster's intent).
    Modified,
}
struct ParsedRank {
    rank: RankPoint,
    source: DivSource,
}

/// Algorithm: scan every position in the phrase for a tier word.
/// Prefer matches with an explicit division (immediately following
/// digit). Fall back to bare tier matches with the default division.
/// "low"/"high"/"mid" prefixes adjust the default for bare matches.
///
/// Returns ParsedRank carrying the source so callers can decide whether
/// to apply Blizzard's ±5-div pairing expansion.
///
/// `default_div_for_unspecified` is the division to use when the poster
/// omits it AND no low/high/mid modifier is present. Use 5 for a "min"
/// interpretation and 1 for a "max" interpretation, so a bare "diamond"
/// expands to the full Diamond tier when used as a range bound.
fn parse_rank_phrase(phrase: &str, default_div_for_unspecified: u8) -> Option<ParsedRank> {
    let words: Vec<&str> = phrase.split_whitespace().collect();
    if words.is_empty() {
        return None;
    }

    let mut last_explicit: Option<RankPoint> = None;
    let mut last_bare_tier: Option<(usize, Tier)> = None;

    for (i, w) in words.iter().enumerate() {
        let w_clean = w.strip_suffix('+').unwrap_or(w);

        if let Some(rp) = parse_compact_rank_strict(w_clean) {
            last_explicit = Some(rp);
            continue;
        }
        if let Some(tier) = tier_from_word(w_clean) {
            let div = words
                .get(i + 1)
                .and_then(|d| d.parse::<u8>().ok())
                .filter(|&n| (1..=5).contains(&n));
            if let Some(d) = div {
                last_explicit = Some(RankPoint { tier, division: d });
            } else {
                last_bare_tier = Some((i, tier));
            }
        }
    }

    if let Some(rp) = last_explicit {
        return Some(ParsedRank { rank: rp, source: DivSource::Explicit });
    }

    if let Some((idx, tier)) = last_bare_tier {
        let (div, source) = if idx > 0 {
            match words[idx - 1] {
                "low" | "lower" => (5, DivSource::Modified),
                "high" | "higher" | "top" => (1, DivSource::Modified),
                "mid" | "middle" => (3, DivSource::Modified),
                _ => (default_div_for_unspecified, DivSource::BareTier),
            }
        } else {
            (default_div_for_unspecified, DivSource::BareTier)
        };
        return Some(ParsedRank { rank: RankPoint { tier, division: div }, source });
    }

    None
}

/// Find a rank range (min, max) in the normalized text.
///
/// Recognized patterns:
///   "plat 1 - diamond 3"       → both ends specified
///   "silver to gold"           → both ends specified, no divisions
///   "low dia"                  → single point: low diamond
///   "GM"                       → single point: any GM (min=GM5, max=GM1)
///   "diamond"                  → single point: any diamond
///
/// When only one rank is found, both min and max are set to that rank's
/// boundaries (so a "plat" group has min=Plat 5, max=Plat 1 = entire
/// platinum tier).
fn parse_rank_range(text: &str) -> (Option<RankPoint>, Option<RankPoint>) {
    // 1. Open-ended "<rank>+" suffix. Two forms in the wild:
    //      a) Joined: "d3+", "dia5+", "gm+" -- one token.
    //      b) Spaced: "plat 1+", "diamond 5+" -- two tokens, the +
    //         attaches to the division number.
    //    Min = the named rank. Max = anchor + Blizzard's max group spread
    //    (5 divs / 3 for GM / 0 for Champion). Capping at Ch1 was wrong:
    //    a Plat 1+ post can't actually accept Champion players (Blizzard
    //    refuses to queue groups with >5-div spread), so showing them as
    //    matches is a false positive that wastes the user's attention.
    let words: Vec<&str> = text.split_whitespace().collect();
    for (i, word) in words.iter().enumerate() {
        if let Some(stem) = word.strip_suffix('+') {
            // Form (a): the whole token (sans +) is a rank.
            let mut anchor = parse_rank_token(stem, 5);
            // Form (b): if not, try previous word + stem joined together
            // ("plat" + "1" -> "plat1"). Necessary for spaced "plat 1+".
            if anchor.is_none() && i > 0 {
                let joined = format!("{}{}", words[i - 1], stem);
                anchor = parse_rank_token(&joined, 5);
            }
            if let Some(min) = anchor {
                let spread = tier_max_group_spread(min.tier);
                let max = RankPoint::from_score((min.score() + spread).min(39))
                    .unwrap_or(RankPoint { tier: Tier::Champion, division: 1 });
                return (Some(min), Some(max));
            }
        }
    }

    // 1b. Word-level open-ended modifiers: "and above" / "or above" /
    //     "and up" / "+ up" → open-upper-bound. "and below" / "or below"
    //     / "and down" → open-lower-bound.
    let upper_open = text.contains(" and above") || text.contains(" or above")
        || text.contains(" and up") || text.contains(" or up")
        || text.contains(" + up") || text.contains(" an above");
    let lower_open = text.contains(" and below") || text.contains(" or below")
        || text.contains(" and down") || text.contains(" or down");
    if upper_open || lower_open {
        // Strip the modifier and look for a single literal rank anchor
        // in the remaining text. The anchor is used as min (for "and
        // above") or max (for "and below") -- we don't apply the ±5
        // centered-expansion rule here because the poster's directional
        // modifier already explicitly states the boundary they care
        // about.
        let cleaned = text
            .replace(" and above", " ")
            .replace(" or above", " ")
            .replace(" and up", " ")
            .replace(" or up", " ")
            .replace(" + up", " ")
            .replace(" an above", " ")
            .replace(" and below", " ")
            .replace(" or below", " ")
            .replace(" and down", " ")
            .replace(" or down", " ");
        let anchor = find_literal_rank_anchor(&cleaned);
        if let Some(anchor_rp) = anchor {
            // "and up" doesn't mean "to the top of the ladder" -- it
            // means "anyone I'm allowed to group with going up". By
            // Blizzard's matchmaking rules that's anchor + 5 divs
            // (3 for GM, 0 for Champion). Same logic going down.
            //
            // Example: "plat 3+" → Pl3..Di3 (5 divs up), NOT Pl3..Ch1.
            // Example: "diamond 5+" → Di5..Ma5 (5 divs up), NOT Di5..Ch1.
            // Example: "GM 5+" → GM5..GM2 (3 divs up).
            //
            // Without this clamp the upper bound was wildly wrong --
            // a "plat 3 and up" LFG matched Champions, but a Champion
            // can't actually group with a Plat 3 (game-side restriction).
            let spread = tier_max_group_spread(anchor_rp.tier);
            let anchor_score = anchor_rp.score();
            let min = if lower_open {
                RankPoint::from_score(anchor_score.saturating_sub(spread))
                    .unwrap_or(RankPoint { tier: Tier::Bronze, division: 5 })
            } else {
                anchor_rp
            };
            let max = if upper_open {
                RankPoint::from_score((anchor_score + spread).min(39))
                    .unwrap_or(RankPoint { tier: Tier::Champion, division: 1 })
            } else {
                anchor_rp
            };
            return (Some(min), Some(max));
        }
    }

    // 2. Dash-normalize so "plat-low" and "d3-m4" both parse uniformly.
    //    Replacing `-` with ` - ` ensures whatever comes after will be
    //    discoverable by the explicit-range splitters below or by
    //    parse_rank_phrase's compact-token scan.
    let dash_normalized = text.replace('-', " - ");

    // 3. Explicit range " - " / " to " / " thru " / " through ".
    //    parse_rank_phrase tries compact tokens (d3, plat5) AND bare
    //    tiers, so this covers the bulk of real-world posts.
    //    Explicit ranges are used as-stated (no ±5 expansion); the
    //    poster intentionally chose those bounds.
    //
    //    Order normalization: posters sometimes write the high tier
    //    first ("gold to bronze wide q"), so we re-parse with flipped
    //    defaults (low side gets div=5, high side gets div=1) when the
    //    initial parse comes out reversed (min.score > max.score).
    for sep in [" - ", " to ", " thru ", " through "] {
        if let Some((left, right)) = dash_normalized.split_once(sep) {
            let lmin = parse_rank_phrase(left.trim(), 5).map(|p| p.rank);
            let rmax = parse_rank_phrase(right.trim(), 1).map(|p| p.rank);
            if let (Some(a), Some(b)) = (lmin, rmax) {
                if a.score() <= b.score() {
                    // Ascending as stated — use directly.
                    return (Some(a), Some(b));
                }
                // Descending ("gold to bronze") — re-parse with the
                // sides swapped AND defaults flipped, so we get the
                // BOTTOM of the (textually-second) lower tier and
                // the TOP of the (textually-first) higher tier.
                let new_min = parse_rank_phrase(right.trim(), 5).map(|p| p.rank);
                let new_max = parse_rank_phrase(left.trim(), 1).map(|p| p.rank);
                if new_min.is_some() && new_max.is_some() {
                    return (new_min, new_max);
                }
                // Fallback: just swap, even though the divisions may
                // be mid-tier instead of edge-aligned.
                return (Some(b), Some(a));
            }
        }
    }

    // 4. Slash-style range "gold/plat" (slash already → space in
    //    normalize, so this is just two adjacent rank tokens).
    //    Detect by scanning windows for "X Y" where both parse as ranks.
    let words: Vec<&str> = dash_normalized.split_whitespace().collect();
    for i in 0..words.len().saturating_sub(1) {
        let a = parse_rank_token(words[i], 5);
        let b = parse_rank_token(words[i + 1], 1);
        if let (Some(a_rp), Some(b_rp)) = (a, b) {
            // Sanity: must be DIFFERENT tiers (otherwise just a single
            // tier with division), and ordered low->high.
            if a_rp.tier != b_rp.tier && a_rp < b_rp {
                return (Some(a_rp), Some(b_rp));
            }
        }
    }

    // 5. Single-rank window fallback. Apply Blizzard's pairing rules:
    //
    //    - Bare tier ("plat") -> tier-bottom + 5 div up. Asymmetric
    //      because we don't know the poster's actual division.
    //      So "plat" -> Plat 5 to Diamond 5.
    //    - Specific tier+division ("plat 3", "d3") -> ±5 div centered.
    //      The poster is stating THEIR rank, not a target range; per
    //      Blizzard rules they can group with anyone within 5 divs.
    //      So "plat 3" -> Silver 3 to Diamond 3.
    //    - "low/high/mid plat" -> single point at the modified
    //      division. Poster was already specific about position.
    //
    //    Master+ tighter rules:
    //    - Bare master -> M5 → GM5 (1-tier rule, == 5 div)
    //    - Bare GM -> GM5 → GM2 (3-div rule)
    //    - Bare Champion -> Ch1 only (single-division tier)
    //
    //    Reference: https://us.forums.blizzard.com/en/overwatch/t/grouping-ranges-rank-allowances/878468
    for window_size in (1..=3).rev() {
        for start in 0..words.len() {
            if start + window_size > words.len() {
                break;
            }
            let phrase = words[start..start + window_size].join(" ");
            if let Some(parsed) = parse_rank_phrase(&phrase, 3) {
                return match parsed.source {
                    DivSource::Explicit => centered_pair_range(parsed.rank),
                    DivSource::BareTier => single_tier_range(parsed.rank.tier),
                    DivSource::Modified => (Some(parsed.rank), Some(parsed.rank)),
                };
            }
        }
    }

    // 6. Last-ditch substring scan for concatenated/embedded tier names
    //    (catches typos like "silvergold", "platdiamond", "Goofiediamond").
    //    Only matches FULL canonical tier names (≥4 chars) to avoid
    //    false positives ("go" in "good").
    const SUBSTRING_TIERS: &[(&str, Tier)] = &[
        ("grandmaster", Tier::Grandmaster),
        ("platinum", Tier::Platinum),
        ("champion", Tier::Champion),
        ("diamond", Tier::Diamond),
        ("masters", Tier::Master),
        ("master", Tier::Master),
        ("bronze", Tier::Bronze),
        ("silver", Tier::Silver),
        ("champ", Tier::Champion),
        ("gold", Tier::Gold),
        ("plat", Tier::Platinum),
    ];
    let mut found: Vec<Tier> = Vec::new();
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let mut matched = 0;
        for (name, tier) in SUBSTRING_TIERS {
            let n = name.len();
            if i + n <= bytes.len() && &bytes[i..i + n] == name.as_bytes() {
                found.push(*tier);
                matched = n;
                break;
            }
        }
        if matched > 0 {
            i += matched;
        } else {
            i += 1;
        }
    }
    if found.len() >= 2 {
        let lo = *found.first().unwrap();
        let hi = *found.last().unwrap();
        let min = RankPoint { tier: lo, division: 5 };
        let max = RankPoint { tier: hi, division: 1 };
        if min < max {
            return (Some(min), Some(max));
        } else if min > max {
            return (Some(max), Some(min)); // posted in reverse order
        }
        // Same tier — fall through to single
    }
    if let Some(t) = found.first() {
        return single_tier_range(*t);
    }

    (None, None)
}

/// Find a single literal rank reference in the text WITHOUT applying
/// the ±5 centered-expansion rule. Used by the "and above" / "and
/// below" handler where the poster's directional modifier already
/// states the boundary; we want the literal anchor point.
///
/// Bare-tier mentions resolve to the tier's bottom division (Plat → P5)
/// since posters writing "plat and above" mean "P5 onwards".
fn find_literal_rank_anchor(text: &str) -> Option<RankPoint> {
    let dash_normalized = text.replace('-', " - ");
    let words: Vec<&str> = dash_normalized.split_whitespace().collect();
    for window_size in (1..=3).rev() {
        for start in 0..words.len() {
            if start + window_size > words.len() {
                break;
            }
            let phrase = words[start..start + window_size].join(" ");
            if let Some(parsed) = parse_rank_phrase(&phrase, 5) {
                return Some(parsed.rank);
            }
        }
    }
    None
}

/// Expand a specific rank+division (e.g. "plat 3", "d3") into the
/// pairing range Blizzard's grouping rules allow: ±5 divisions for
/// Bronze-Diamond, ±1 tier (= 5 div) for Master, ±3 div for GM,
/// 0 for Champion.
///
/// Posters say "plat 3 dps" to mean "I'm Plat 3, looking for a DPS";
/// the matchable DPS is anyone within ±5 div of Plat 3.
fn centered_pair_range(rp: RankPoint) -> (Option<RankPoint>, Option<RankPoint>) {
    let spread_each_side = tier_max_group_spread(rp.tier);
    let center_score = rp.score();
    let min_score = center_score.saturating_sub(spread_each_side);
    let max_score = (center_score + spread_each_side).min(39);
    let min = RankPoint::from_score(min_score).unwrap_or(rp);
    let max = RankPoint::from_score(max_score).unwrap_or(rp);
    (Some(min), Some(max))
}

/// Maximum division-spread Blizzard's grouping rules allow for a given
/// tier. Used as the half-width when expanding a single anchor rank into
/// a pairable range, AND as the "and up" / "and below" implicit
/// directional cap.
///
/// Bronze through Master: 5 divs (== 1 tier). Group anyone within
/// ±5 divs of you without entering wide-group queue penalty.
/// Grandmaster: 3 divs (tighter queue rule near the top).
/// Champion: 0 divs (single rank, can only group with self).
///
/// Reference: https://us.forums.blizzard.com/en/overwatch/t/grouping-ranges-rank-allowances/878468
fn tier_max_group_spread(tier: Tier) -> u32 {
    match tier {
        Tier::Bronze
        | Tier::Silver
        | Tier::Gold
        | Tier::Platinum
        | Tier::Diamond
        | Tier::Master => 5,
        Tier::Grandmaster => 3,
        Tier::Champion => 0,
    }
}

/// Expand a bare-tier mention (e.g., "plat", "silver") into a min/max
/// range using Blizzard's wide-group threshold: 5 division spread.
///
/// Concrete rules:
/// - Bronze through Diamond: ±2 skill tiers allowed for grouping, but
///   the WIDE-GROUP threshold (= longer queue penalty) kicks in at >5
///   divisions spread. We use that as the practical "I'd rather queue
///   normal than wide" range. So "plat" → Plat 5 to Diamond 5.
/// - Master: ±1 tier allowed → "master" → Master 5 to GM 5 (5 divs up).
/// - Grandmaster: ±3 divisions allowed → "gm" → GM 5 to GM 2.
/// - Champion: ±3 divs but only one division exists; degenerates to
///   Champion 1.
///
/// Reference: https://us.forums.blizzard.com/en/overwatch/t/grouping-ranges-rank-allowances/878468
fn single_tier_range(tier: Tier) -> (Option<RankPoint>, Option<RankPoint>) {
    let bottom = RankPoint { tier, division: 5 };
    let divs_up = match tier {
        Tier::Bronze
        | Tier::Silver
        | Tier::Gold
        | Tier::Platinum
        | Tier::Diamond
        | Tier::Master => 5, // wide-group threshold = 1 tier
        Tier::Grandmaster => 3,
        Tier::Champion => 0, // Champion has only 1 division
    };
    let top = bottom.add_divisions(divs_up);
    (Some(bottom), Some(top))
}

// ----------------------------------------------------------------------
// Role parsing
// ----------------------------------------------------------------------

fn parse_roles(text: &str) -> Vec<Role> {
    let mut out: Vec<Role> = Vec::new();
    let padded = format!(" {} ", text);

    // Substring matches. "supports" satisfies "supp" / "support".
    let role_patterns: &[(&str, Role)] = &[
        ("tank", Role::Tank),
        (" mt ", Role::Tank),
        (" tnk ", Role::Tank),
        (" tnks ", Role::Tank),
        ("supp", Role::Support),
        ("support", Role::Support),
        ("suport", Role::Support),
        ("supoort", Role::Support),
        ("suppot", Role::Support),
        ("suppoert", Role::Support),
        ("suportt", Role::Support),
        (" sup ", Role::Support),
        (" sups ", Role::Support),
        ("heal", Role::Support),
        ("healer", Role::Support),
        ("dps", Role::Dps),
        ("damage", Role::Dps),
        (" dmg ", Role::Dps),
        (" dpa ", Role::Dps),
        (" duelist ", Role::Dps),
        ("flex", Role::Flex),
    ];

    for (needle, role) in role_patterns {
        if padded.contains(needle) && !out.contains(role) {
            out.push(*role);
        }
    }

    // OW hero names imply role -- people often say "mercy and tank" or
    // "1 dps + reaper". Map the common heroes (top ~15 per role by usage)
    // so we catch role intent even when the role word isn't said.
    let hero_role_patterns: &[(&str, Role)] = &[
        // Tanks
        (" rein ", Role::Tank),
        (" reinhardt ", Role::Tank),
        (" hog ", Role::Tank),
        (" roadhog ", Role::Tank),
        (" winston ", Role::Tank),
        (" monke ", Role::Tank),
        (" dva ", Role::Tank),
        (" ball ", Role::Tank),
        (" hammond ", Role::Tank),
        (" sigma ", Role::Tank),
        (" zarya ", Role::Tank),
        (" orisa ", Role::Tank),
        (" mauga ", Role::Tank),
        (" doom ", Role::Tank),
        (" doomfist ", Role::Tank),
        (" jq ", Role::Tank),
        (" junker queen ", Role::Tank),
        (" ramattra ", Role::Tank),
        (" hazard ", Role::Tank),
        // Supports
        (" mercy ", Role::Support),
        (" ana ", Role::Support),
        (" lucio ", Role::Support),
        (" zen ", Role::Support),
        (" zenyatta ", Role::Support),
        (" moira ", Role::Support),
        (" brig ", Role::Support),
        (" brigitte ", Role::Support),
        (" bap ", Role::Support),
        (" baptiste ", Role::Support),
        (" kiri ", Role::Support),
        (" kiriko ", Role::Support),
        (" lifeweaver ", Role::Support),
        (" lw ", Role::Support),
        (" illari ", Role::Support),
        (" juno ", Role::Support),
        // DPS
        (" tracer ", Role::Dps),
        (" widow ", Role::Dps),
        (" widowmaker ", Role::Dps),
        (" reaper ", Role::Dps),
        (" soldier ", Role::Dps),
        (" soldier76 ", Role::Dps),
        (" sojourn ", Role::Dps),
        (" sojo ", Role::Dps),
        (" hanzo ", Role::Dps),
        (" genji ", Role::Dps),
        (" cassidy ", Role::Dps),
        (" mccree ", Role::Dps),
        (" ashe ", Role::Dps),
        (" pharah ", Role::Dps),
        (" mei ", Role::Dps),
        (" symmetra ", Role::Dps),
        (" sym ", Role::Dps),
        (" torb ", Role::Dps),
        (" torbjorn ", Role::Dps),
        (" sombra ", Role::Dps),
        (" junkrat ", Role::Dps),
        (" bastion ", Role::Dps),
        (" echo ", Role::Dps),
        (" venture ", Role::Dps),
    ];
    for (needle, role) in hero_role_patterns {
        if padded.contains(needle) && !out.contains(role) {
            out.push(*role);
        }
    }

    // "all roles" / "any role" / "all" / "any" / "6v6" / "one of each"
    // / "1 of each" / "everything" / "everyone" → all 3 standard roles.
    // The 6v6 mode requires a full 6-player team; "all" / "any" / "one
    // of each" are explicit "we'll take anyone".
    let any_role_signal = padded.contains(" all roles ")
        || padded.contains(" any role ")
        || padded.contains(" all ")
        || padded.contains(" any ")
        || padded.contains(" 6v6 ")
        || padded.contains(" one of each ")
        || padded.contains(" one each ")
        || padded.contains(" 1 of each ")
        || padded.contains(" 2 of each ")
        || padded.contains(" 3 of each ")
        || padded.contains(" everything ")
        || padded.contains(" everyone ");
    if any_role_signal {
        for role in [Role::Tank, Role::Dps, Role::Support] {
            if !out.contains(&role) {
                out.push(role);
            }
        }
    }

    out
}

// ----------------------------------------------------------------------
// Slot count parsing
// ----------------------------------------------------------------------

fn parse_slot_count(text: &str) -> u32 {
    // Look for "N support(s)", "N tank", "N dps", "lf N", "need N"
    let words: Vec<&str> = text.split_whitespace().collect();
    for (i, w) in words.iter().enumerate() {
        if let Ok(n) = w.parse::<u32>() {
            if n >= 1 && n <= 5 {
                // Sanity: must be followed by a role-ish word OR preceded
                // by "lf"/"need"/"want"
                let next = words.get(i + 1).copied().unwrap_or("");
                let prev = if i > 0 { words[i - 1] } else { "" };
                let role_hits = ["tank", "supp", "support", "dps",
                                 "damage", "heal", "flex"];
                if role_hits.iter().any(|r| next.starts_with(r)) {
                    return n;
                }
                if matches!(prev, "lf" | "need" | "want" | "needs" | "wants") {
                    return n;
                }
            }
        }
    }
    0
}

// ----------------------------------------------------------------------
// Region parsing
// ----------------------------------------------------------------------

fn parse_region(text: &str) -> Option<Region> {
    let padded = format!(" {} ", text);
    if padded.contains(" na ") || padded.contains(" us ") || padded.contains(" usa ") {
        return Some(Region::Na);
    }
    if padded.contains(" eu ") || padded.contains(" europe ") {
        return Some(Region::Eu);
    }
    if padded.contains(" asia ") || padded.contains(" kr ") || padded.contains(" jp ") {
        return Some(Region::Asia);
    }
    if padded.contains(" oce ") || padded.contains(" oceanic ") || padded.contains(" au ") {
        return Some(Region::Oce);
    }
    None
}

// ----------------------------------------------------------------------
// Match check
// ----------------------------------------------------------------------

/// Decide whether `my_rank` is within the LFG's range. Permissive when
/// either bound is missing.
pub fn rank_in_range(my_rank: RankPoint, parsed: &ParsedLfg) -> bool {
    let my = my_rank.score();
    let lo = parsed.rank_min.map(|r| r.score()).unwrap_or(0);
    let hi = parsed.rank_max.map(|r| r.score()).unwrap_or(u32::MAX);
    lo <= my && my <= hi
}

// TODO: opencode LLM fallback for parses where rank_min == rank_max ==
// None AND roles_needed is empty (i.e., we extracted nothing useful).
// Would shell out to `opencode <some-command>` with a structured
// prompt and JSON output schema. Caching by message_id mandatory to
// avoid blowing through API quota on busy LFG channels.

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(s: &str) -> ParsedLfg {
        parse_description(s)
    }

    // ---- normalize ----

    #[test]
    fn normalize_strips_emoji_and_collapses_whitespace() {
        assert_eq!(normalize("Plat   1  ✨!! "), "plat 1");
        assert_eq!(normalize("LF 2 supports!! :)"), "lf 2 supports");
    }

    // ---- rank parsing ----

    #[test]
    fn parses_explicit_dash_range() {
        let p = parse("plat 1 - diamond 3");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 1 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
    }

    #[test]
    fn parses_to_keyword_range() {
        let p = parse("silver to gold");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Silver, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Gold, division: 1 }));
    }

    #[test]
    fn parses_single_rank_with_wide_group_rule() {
        // Per Blizzard's wide-group threshold: a bare "plat" mention
        // expands to Plat 5 -> Diamond 5 (5 divisions up = next tier
        // bottom). See single_tier_range docs.
        let p = parse("plat supp");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
    }

    #[test]
    fn parses_bare_silver_to_gold_5() {
        let p = parse("silver");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Silver, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Gold, division: 5 }));
    }

    #[test]
    fn specific_rank_expands_5_div_centered() {
        // "plat 3 dps" -- poster stating own rank.
        // Per Blizzard's pairing rule they can group with anyone within
        // 5 divisions of P3: Gold 3 (P3-5) up through Diamond 3 (P3+5).
        let p = parse("plat 3 dps");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Gold, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
    }

    #[test]
    fn specific_rank_d3_compact_centered() {
        // "d3" compact form -- same ±5 div rule.
        // D3 - 5 divs = Plat 3; D3 + 5 divs = Master 3.
        let p = parse("d3 looking for sup");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Master, division: 3 }));
    }

    #[test]
    fn specific_rank_clamps_at_ladder_bottom() {
        // "bronze 5 lf duo" -- B5 - 5 divs would go below ladder; clamp.
        // B5 is score 0, so min stays at B5. B5 + 5 = score 5 = Silver 5.
        let p = parse("bronze 5 lf duo");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Bronze, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Silver, division: 5 }));
    }

    #[test]
    fn specific_rank_clamps_at_ladder_top() {
        // "champ 1" can't go above. Champion is +0 div so single point.
        let p = parse("champion 1 only");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Champion, division: 1 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Champion, division: 1 }));
    }

    #[test]
    fn low_modifier_is_single_point() {
        // "low dia" -- explicit modifier, no expansion.
        let p = parse("low dia dps lf");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
    }

    #[test]
    fn parses_bare_diamond_to_master_5() {
        let p = parse("diamond");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Master, division: 5 }));
    }

    #[test]
    fn parses_bare_grandmaster_3_div_only() {
        // Grandmaster: ±3 div rule. GM 5 + 3 = GM 2.
        let p = parse("gm only");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Grandmaster, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Grandmaster, division: 2 }));
    }

    #[test]
    fn parses_bare_champion_single_point() {
        let p = parse("champion");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Champion, division: 5 }));
        // Champion has only 1 division but our model uses 5..1 like
        // every tier; range is degenerate at +0 divisions up.
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Champion, division: 5 }));
    }

    #[test]
    fn parses_low_modifier() {
        let p = parse("low dia dps lf");
        // "low dia" should narrow to a single low-diamond point.
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Diamond));
        assert_eq!(p.rank_min.map(|r| r.division), Some(5));
    }

    #[test]
    fn parses_gm_abbreviation() {
        let p = parse("GM only");
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Grandmaster));
    }

    // ---- roles ----

    #[test]
    fn parses_supports_plural() {
        let p = parse("2 supports needed silver 1 - gold 1");
        assert!(p.roles_needed.contains(&Role::Support));
        assert_eq!(p.slots_open, 2);
    }

    #[test]
    fn parses_solo_role() {
        let p = parse("plat supp");
        assert_eq!(p.roles_needed, vec![Role::Support]);
    }

    #[test]
    fn parses_dps_alias() {
        let p = parse("gold tank lf damage");
        assert!(p.roles_needed.contains(&Role::Tank));
        assert!(p.roles_needed.contains(&Role::Dps));
    }

    // ---- slot count ----

    #[test]
    fn parses_slot_count_with_role() {
        assert_eq!(parse("lf 2 dps").slots_open, 2);
        assert_eq!(parse("need 1 tank plat 3").slots_open, 1);
    }

    #[test]
    fn no_slot_count_for_unrelated_numbers() {
        // "silver 1" is a rank, not a slot count.
        assert_eq!(parse("silver 1 - gold 1").slots_open, 0);
    }

    // ---- region ----

    #[test]
    fn parses_na_region() {
        let p = parse("na plat tank");
        assert_eq!(p.region, Some(Region::Na));
    }

    #[test]
    fn no_region_when_absent() {
        assert_eq!(parse("plat support").region, None);
    }

    // ---- range checking ----

    #[test]
    fn rank_in_range_inclusive_endpoints() {
        let p = parse("plat 1 - diamond 3");
        assert!(rank_in_range(
            RankPoint { tier: Tier::Platinum, division: 1 },
            &p
        ));
        assert!(rank_in_range(
            RankPoint { tier: Tier::Diamond, division: 3 },
            &p
        ));
    }

    #[test]
    fn rank_outside_range_returns_false() {
        let p = parse("plat 1 - diamond 3");
        // Diamond 2 is HIGHER than Diamond 3 (lower number = higher).
        // Our range is plat 1 → diamond 3, so diamond 2 is OUT (above max).
        assert!(!rank_in_range(
            RankPoint { tier: Tier::Diamond, division: 2 },
            &p
        ));
        // Plat 5 is LOWER than Plat 1, so OUT (below min).
        assert!(!rank_in_range(
            RankPoint { tier: Tier::Platinum, division: 5 },
            &p
        ));
    }

    #[test]
    fn rank_score_ordering_sanity() {
        let bronze5 = RankPoint { tier: Tier::Bronze, division: 5 };
        let bronze1 = RankPoint { tier: Tier::Bronze, division: 1 };
        let silver5 = RankPoint { tier: Tier::Silver, division: 5 };
        let champ1 = RankPoint { tier: Tier::Champion, division: 1 };

        assert!(bronze5 < bronze1, "B5 should be less than B1 (B1 is higher)");
        assert!(bronze1 < silver5, "B1 should be less than S5");
        assert!(silver5 < champ1);
    }

    // ---- real-world examples from screenshot ----

    #[test]
    fn screenshot_example_1() {
        // From the user's screenshot: "2 supports needed:) silver 1 - gold 1"
        let p = parse("2 supports needed silver 1 - gold 1");
        assert_eq!(p.slots_open, 2);
        assert!(p.roles_needed.contains(&Role::Support));
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Silver, division: 1 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Gold, division: 1 }));
    }

    #[test]
    fn screenshot_example_2() {
        // From the user's screenshot: "plat supp"
        // After wide-group rule: Plat 5 to Diamond 5.
        let p = parse("plat supp");
        assert_eq!(p.roles_needed, vec![Role::Support]);
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Platinum));
        assert_eq!(p.rank_max.map(|r| r.tier), Some(Tier::Diamond));
        assert_eq!(p.rank_min.map(|r| r.division), Some(5));
        assert_eq!(p.rank_max.map(|r| r.division), Some(5));
    }

    // ---- merge_in (multi-post-per-VC backfill) ----

    #[test]
    fn merge_intersects_rank_range() {
        // Person 1 says "plat to dia" (Pl5=15 to Di1=24).
        // Person 2 says "gold to plat" (Go5=10 to Pl1=19).
        // Intersection (both posters accept): Pl5=15 to Pl1=19, i.e.
        // platinum tier only -- the OVERLAP between Pl5-Di1 and
        // Go5-Pl1 is exactly the platinum span.
        let mut p = parse("plat to dia");
        let other = parse("gold to plat");
        p.merge_in(&other);
        assert_eq!(
            p.rank_min,
            Some(RankPoint { tier: Tier::Platinum, division: 5 }),
            "intersection min = max(Pl5=15, Go5=10) = Pl5"
        );
        assert_eq!(
            p.rank_max,
            Some(RankPoint { tier: Tier::Platinum, division: 1 }),
            "intersection max = min(Di1=24, Pl1=19) = Pl1"
        );
    }

    #[test]
    fn merge_keeps_self_when_intersection_empty() {
        // Person 1 says "bronze". Person 2 says "diamond". Ranges
        // don't overlap at all -> intersection is empty. Should keep
        // self's range rather than produce a nonsense empty/inverted
        // range.
        let mut p = parse("bronze");
        let other = parse("diamond");
        let original_min = p.rank_min;
        let original_max = p.rank_max;
        p.merge_in(&other);
        assert_eq!(p.rank_min, original_min, "self.rank_min preserved");
        assert_eq!(p.rank_max, original_max, "self.rank_max preserved");
    }

    #[test]
    fn merge_narrows_with_open_upper() {
        // The actual screenshot bug case: WETLIQUID says "gold tank"
        // (Go5-Pl5). Tyler in the same VC says "need gold+ tank"
        // (Go5-Ch1). Group ACTUALLY accepts only Go5-Pl5 because
        // WETLIQUID would reject anyone above Plat. Old union merge
        // produced Go5-Ch1 (the misleading display).
        let mut p = parse("gold tank");
        let other = parse("need gold+ tank");
        p.merge_in(&other);
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Gold, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Platinum, division: 5 }));
    }

    #[test]
    fn merge_fills_missing_rank() {
        // Yahiko forgot ranks. Teammate posts with range. Backfill it.
        let mut yahiko = parse("1 supp lf");
        assert_eq!(yahiko.rank_min, None);
        assert_eq!(yahiko.rank_max, None);
        let teammate = parse("plat 1 to diamond 3");
        yahiko.merge_in(&teammate);
        assert_eq!(
            yahiko.rank_min,
            Some(RankPoint { tier: Tier::Platinum, division: 1 })
        );
        assert_eq!(
            yahiko.rank_max,
            Some(RankPoint { tier: Tier::Diamond, division: 3 })
        );
    }

    #[test]
    fn merge_unions_roles() {
        let mut p = parse("plat dps");
        let other = parse("plat supp");
        p.merge_in(&other);
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn merge_takes_max_slot_count() {
        let mut p = parse("lf 1 dps");
        let other = parse("lf 3 dps");
        p.merge_in(&other);
        assert_eq!(p.slots_open, 3);
    }

    #[test]
    fn merge_concatenates_distinct_text() {
        let mut p = parse("plat dps");
        let other = parse("we are bb latinas");
        p.merge_in(&other);
        assert!(p.normalized_text.contains("plat"));
        assert!(p.normalized_text.contains("bb latinas"));
        // No duplication on a second merge of identical text
        let third = parse("plat dps");
        p.merge_in(&third);
        // Should still appear exactly once
        assert_eq!(p.normalized_text.matches("plat").count(), 1);
    }

    // ---- backtest-driven heuristics (real-world failures fixed) ----

    #[test]
    fn parses_compact_letter_digit_range() {
        // Discord LFG common: "d3-m4" = Diamond 3 to Master 4
        let p = parse("d3-m4 dps and tank");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Master, division: 4 }));
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Tank));
    }

    #[test]
    fn parses_compact_g1_p1() {
        let p = parse("g1-p1 dps sup");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Gold, division: 1 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Platinum, division: 1 }));
    }

    #[test]
    fn parses_plus_suffix_open_upper_bound() {
        // "d3+" -- anchor Diamond 3, +5 divs (Blizzard's max group
        // spread) caps at Master 3. NOT Champion 1: a Champion can't
        // group with a Diamond 3 in OW2 anyway, so showing them as
        // potential matches creates false positives.
        let p = parse("d3+ tank supp");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Master, division: 3 }));
    }

    #[test]
    fn parses_dia5_plus() {
        // "dia5+" -- Di5 + 5 divs = Master 5.
        let p = parse("dia5+ support");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Master, division: 5 }));
    }

    #[test]
    fn parses_plat1_plus_caps_at_diamond1() {
        // User's stated rule: "plat1+" -> Pl1..Di1 (5 divs up).
        let p = parse("plat 1+ tank");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 1 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 1 }));
    }

    #[test]
    fn parses_plat3_and_up_caps_at_diamond3() {
        // The seeray_1 case from the screenshot: "plat 3 and up" was
        // parsed as Pl3..Ch1, should be Pl3..Di3.
        let p = parse("plat 3 and up");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
    }

    #[test]
    fn parses_gm_and_up_uses_3_div_spread() {
        // GM uses tighter +3 div rule, not +5.
        let p = parse("gm 5 and up");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Grandmaster, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Grandmaster, division: 2 }));
    }

    #[test]
    fn parses_bronze_5_and_below_clamps_at_floor() {
        // Anchor at the floor; "and below" can't go lower.
        let p = parse("bronze 5 and below");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Bronze, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Bronze, division: 5 }));
    }

    #[test]
    fn parses_diamond_3_and_below_uses_5_div_spread() {
        // "and below" mirrors "and up": Di3 - 5 divs = Plat 3.
        let p = parse("diamond 3 and below");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 3 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 3 }));
    }

    #[test]
    fn parses_diamond_masters_compact() {
        let p = parse("diamond-masters 6v6");
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Diamond));
        assert_eq!(p.rank_max.map(|r| r.tier), Some(Tier::Master));
        // 6v6 → all 3 roles
        assert!(p.roles_needed.contains(&Role::Tank));
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn parses_dps_slash_sup() {
        // Slash should tokenize as separator
        let p = parse("d3+ dps/sup");
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn parses_diamond_typo() {
        let p = parse("daimond dps and tank");
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Diamond));
        let p2 = parse("dimaond dps");
        assert_eq!(p2.rank_min.map(|r| r.tier), Some(Tier::Diamond));
    }

    #[test]
    fn parses_silver_gold_concatenated() {
        // No-space concatenated tier names
        let p = parse("high silvergold need 1 dps and 2 suppot");
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Silver));
        assert_eq!(p.rank_max.map(|r| r.tier), Some(Tier::Gold));
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn parses_discord_emoji_rank() {
        // Custom Discord emoji <:Gold:123456> should resolve to "gold"
        let p = parse("<:Gold:1272892603561541694> NEED TWO SUPPORTS");
        assert_eq!(p.rank_min.map(|r| r.tier), Some(Tier::Gold));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn parses_hero_implies_role() {
        // Mercy → Support, even without "support" word
        let p = parse("mercy and tank");
        assert!(p.roles_needed.contains(&Role::Support));
        assert!(p.roles_needed.contains(&Role::Tank));
    }

    #[test]
    fn parses_and_above() {
        // "plat 5 and above" -- Pl5 + 5 divs = Diamond 5. NOT Ch1.
        let p = parse("plat 5 and above");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Platinum, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Diamond, division: 5 }));
    }

    #[test]
    fn parses_slash_range_gold_plat() {
        let p = parse("gold/plat");
        assert_eq!(p.rank_min, Some(RankPoint { tier: Tier::Gold, division: 5 }));
        assert_eq!(p.rank_max, Some(RankPoint { tier: Tier::Platinum, division: 1 }));
    }

    #[test]
    fn parses_one_of_each_all_roles() {
        let p = parse("p3-d3 one of each");
        assert!(p.roles_needed.contains(&Role::Tank));
        assert!(p.roles_needed.contains(&Role::Dps));
        assert!(p.roles_needed.contains(&Role::Support));
    }

    #[test]
    fn parses_support_typos() {
        let p1 = parse("gold need 1 supoort");
        assert!(p1.roles_needed.contains(&Role::Support));
        let p2 = parse("plat need suppot");
        assert!(p2.roles_needed.contains(&Role::Support));
    }
}
