mod accounts;
mod agent;
mod config;
mod cpu_topology;
mod lfg;
mod lfg_parse;
mod lutris;
mod rank_icons;
mod ranks;
mod switcher;
mod tcno;
mod term_caps;
mod wine_reg;

use accounts::AppConfig;
use anyhow::Result;
use config::BnetInstall;
use crossterm::{
    event::{
        self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind,
        MouseButton, MouseEventKind,
    },
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
    execute,
};
use ranks::{Division, Role, RoleRanks};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Clear, List, ListItem, ListState, Paragraph},
    Terminal,
};
use std::collections::HashMap;
use std::io;
use std::sync::mpsc;
use std::time::Duration;

/// Categorization of where we know an account from. Used to color and
/// label the TUI rows so users can see at a glance whether an account is
/// switchable now, awaiting restore, or needs to be logged-in first.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AccountState {
    /// First entry in Battle.net's `SavedAccountNames` — Battle.net will
    /// auto-login as this account on next launch.
    Active,
    /// Listed in `SavedAccountNames` (so Battle.net has a remembered
    /// password for it on this machine), but not the active one. Switching
    /// is a one-click operation.
    Saved,
    /// Cleared from `SavedAccountNames` during an in-progress "Add New"
    /// workflow. The TUI will restore it to the list when the user presses
    /// 's'.
    Pending,
    /// Known to bnetswitch (e.g., from a TCNO import) but Battle.net has
    /// no remembered password for it on this machine yet. The user needs
    /// to log in via the Add New workflow before it becomes switchable.
    Known,
}

/// One row in the unified accounts list.
#[derive(Debug, Clone)]
struct AccountRow {
    email: String,
    state: AccountState,
}

/// Which TUI panel is currently visible. Toggled with 'g'.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum View {
    /// The default account-list view (existing behavior).
    Accounts,
    /// LFG bridge: shows live LFG embeds posted in the watched Discord
    /// channel, color-coded by whether they match the active account's
    /// rank.
    Lfg,
}

/// Per-role rank breakdown for the active account. Used by the LFG
/// matcher to do role-aware matching rather than collapsing to a single
/// "best rank" point (which gave wrong answers for off-meta groups).
#[derive(Debug, Default, Clone)]
struct ActiveRanks {
    tank: Option<lfg_parse::RankPoint>,
    dps: Option<lfg_parse::RankPoint>,
    support: Option<lfg_parse::RankPoint>,
}

impl ActiveRanks {
    /// Compact display: "T:Pl3 D:Ma5 S:Di1" — empty roles omitted.
    fn label(&self) -> String {
        let mut parts: Vec<String> = Vec::new();
        if let Some(r) = self.tank {
            parts.push(format!("T:{}", r.label()));
        }
        if let Some(r) = self.dps {
            parts.push(format!("D:{}", r.label()));
        }
        if let Some(r) = self.support {
            parts.push(format!("S:{}", r.label()));
        }
        if parts.is_empty() {
            "unranked".into()
        } else {
            parts.join(" ")
        }
    }

    /// Decide if any of the active account's role-ranks fits the parsed
    /// LFG range, considering the LFG's stated role needs.
    ///
    /// Logic:
    ///   - If LFG specifies roles_needed (e.g., "needs support"), only
    ///     check the rank for those roles.
    ///   - If LFG specifies no roles, check all three roles -- any fit
    ///     is a match (most generous interpretation).
    ///   - If a needed role is unranked on this account, that role
    ///     skips (doesn't count as match or mismatch).
    fn matches(&self, parsed: &lfg_parse::ParsedLfg) -> MatchKind {
        let candidate_roles: Vec<lfg_parse::Role> = if parsed.roles_needed.is_empty() {
            vec![
                lfg_parse::Role::Tank,
                lfg_parse::Role::Dps,
                lfg_parse::Role::Support,
            ]
        } else {
            parsed
                .roles_needed
                .iter()
                .copied()
                .filter(|r| !matches!(r, lfg_parse::Role::Flex))
                .collect()
        };

        let mut had_rank_to_check = false;
        let mut any_match = false;
        for role in candidate_roles {
            let my = match role {
                lfg_parse::Role::Tank => self.tank,
                lfg_parse::Role::Dps => self.dps,
                lfg_parse::Role::Support => self.support,
                lfg_parse::Role::Flex => continue,
            };
            if let Some(p) = my {
                had_rank_to_check = true;
                if lfg_parse::rank_in_range(p, parsed) {
                    any_match = true;
                    break;
                }
            }
        }

        match (had_rank_to_check, any_match) {
            (true, true) => MatchKind::Match,
            (true, false) => MatchKind::Mismatch,
            (false, _) => MatchKind::Unknown,
        }
    }
}

/// Geometry of the LFG list region captured at the end of each render
/// pass. Used by mouse-click handling to map screen coords -> LFG entry
/// index without re-running the sort/dedup pipeline. Mirrors the
/// list_area Rect plus the ListState scroll offset and a row-height
/// constant so the math is self-contained.
#[derive(Debug, Clone, Copy)]
struct LfgViewBounds {
    /// Inclusive top row of the first list entry (skips block top
    /// border + column header).
    top_y: u16,
    /// Exclusive bottom row -- past the last drawable list row.
    bottom_y: u16,
    /// Inclusive left column of the list area (just inside the left
    /// block border).
    left_x: u16,
    /// Exclusive right column.
    right_x: u16,
    /// Scroll offset captured from ListState. Add to (click_y - top_y)
    /// / row_height to get the absolute entry index.
    offset: usize,
    /// Two terminal rows per LFG entry (line1 + description line2).
    row_height: u16,
}

/// Outcome of comparing the active account's role-ranks to a parsed LFG.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MatchKind {
    /// At least one of our ranks for a role this LFG needs falls inside
    /// the LFG's range.
    Match,
    /// We have ranks for the relevant roles, but none fit the LFG's range.
    Mismatch,
    /// Either we have no rank info, or the LFG didn't specify a range,
    /// or it asks for roles we have no rank in.
    Unknown,
}

/// Shared sort key for the LFG view. Used by both `render_lfg_view` (to
/// produce the visible row order) and `App::lfg_visible_message_ids` (to
/// drive j/k navigation against that exact same order). KEEPING THESE
/// IN SYNC IS LOAD-BEARING -- if they diverge, j/k moves the cursor to
/// rows other than the one immediately above/below the highlight.
///
/// Sort priorities (lower = higher in list):
/// 1. Joinability: full VCs (5/5) sink to the bottom regardless of
///    compatibility -- you can't join them, no point burning attention.
/// 2. Compatibility: Match > Unknown > Mismatch given the active
///    account's role-ranks.
/// 3. Freshness: newest first by embed timestamp_ms.
fn lfg_sort_key(
    msg: &lfg::LfgMessage,
    parsed: &lfg_parse::ParsedLfg,
    my_ranks: &ActiveRanks,
) -> (u8, u8, std::cmp::Reverse<u64>) {
    let join_tier = if msg.voice_channel_full() { 1u8 } else { 0u8 };
    let compat_tier = match my_ranks.matches(parsed) {
        MatchKind::Match => 0u8,
        MatchKind::Unknown => 1u8,
        MatchKind::Mismatch => 2u8,
    };
    (join_tier, compat_tier, std::cmp::Reverse(msg.timestamp_ms))
}

/// One completed background rank fetch, sent from the worker thread back
/// to the TUI main loop via mpsc.
struct RankUpdate {
    email: String,
    ranks: Result<RoleRanks, String>,
}

/// One queued fetch request, sent from the TUI main loop to the worker.
struct FetchRequest {
    email: String,
    battletag: String,
    force: bool,
}

/// Run as a long-lived background thread. Pulls fetch requests off
/// `req_rx` and processes them one at a time, pacing requests at
/// ~1.1s/each to stay under OverFast's "1 req/sec shared" rate limit.
///
/// Retries transient errors (network, 5xx, 429) with exponential
/// backoff. 404s are not retried — they're the API's way of saying
/// "private profile or doesn't exist", which won't change.
fn fetch_worker(req_rx: mpsc::Receiver<FetchRequest>, res_tx: mpsc::Sender<RankUpdate>) {
    // Minimum gap between requests to avoid rate-limit hits. OverFast's
    // public instance enforces ~1/s shared across all clients, so we
    // pace slightly above that to leave headroom for other consumers.
    const MIN_GAP: Duration = Duration::from_millis(1100);

    let mut last_request_at: Option<std::time::Instant> = None;

    while let Ok(req) = req_rx.recv() {
        // Honor the inter-request gap.
        if let Some(prev) = last_request_at {
            let elapsed = prev.elapsed();
            if elapsed < MIN_GAP {
                std::thread::sleep(MIN_GAP - elapsed);
            }
        }

        let result = fetch_with_retry(&req.battletag, req.force);
        last_request_at = Some(std::time::Instant::now());
        let _ = res_tx.send(RankUpdate {
            email: req.email,
            ranks: result,
        });
    }
}

/// Fetch with up to 2 retries on transient errors, exponential backoff.
fn fetch_with_retry(battletag: &str, force: bool) -> Result<RoleRanks, String> {
    let mut last_err = String::new();
    for attempt in 0..3 {
        if attempt > 0 {
            // 1s, 2s, 4s
            let backoff = Duration::from_millis(1000 * (1u64 << (attempt - 1)));
            std::thread::sleep(backoff);
        }
        match ranks::fetch_and_merge(battletag, force) {
            Ok(r) => return Ok(r),
            Err(e) => {
                let msg = e.to_string();
                // Don't retry 404s — they're definitive.
                if msg.contains("status code 404") {
                    return Err(msg);
                }
                last_err = msg;
            }
        }
    }
    Err(last_err)
}

/// Application state.
struct App {
    /// Detected Battle.net installation.
    install: BnetInstall,
    /// Accounts currently in Battle.net.config's `SavedAccountNames`.
    /// First entry is the active (auto-login) account.
    accounts: Vec<String>,
    /// Our app config (nicknames, settings, pending merges).
    app_config: AppConfig,
    /// Currently selected index in the *displayed* list (which may contain
    /// pending and known entries beyond `accounts`).
    list_state: ListState,
    /// Status message shown at the bottom.
    status: String,
    /// Whether we're in nickname editing mode.
    editing_nickname: bool,
    /// Buffer for nickname input.
    nickname_input: String,
    /// Whether we're in manual placement entry mode.
    editing_placement: bool,
    /// Buffer for placement input ("T Diamond 3 12" etc.).
    placement_input: String,
    /// Whether to quit.
    should_quit: bool,
    /// Rank cache keyed by email. Updated as the background fetch worker
    /// completes requests and reports results via `rank_rx`.
    ranks_by_email: HashMap<String, RoleRanks>,
    /// Emails currently queued or in-flight on the fetch worker. Used by
    /// the UI to render a "..." indicator.
    fetching_emails: std::collections::HashSet<String>,
    /// Emails whose most recent fetch failed (network/5xx/429, NOT 404).
    /// Stays sticky until the next attempt succeeds. Surfaced as "err"
    /// in the rank cells so users can distinguish from genuinely-empty
    /// public profiles.
    failed_emails: std::collections::HashMap<String, String>,
    /// Receives results from the worker thread.
    rank_rx: mpsc::Receiver<RankUpdate>,
    /// Sends fetch requests to the worker thread.
    fetch_request_tx: mpsc::Sender<FetchRequest>,
    /// Which view is currently displayed. Toggled with 'g'.
    view: View,
    /// Selected row index within the LFG list, when `view == Lfg`.
    lfg_list_state: ListState,
    /// Message ID of the currently-selected LFG entry. Tracked
    /// separately from `lfg_list_state` (which only stores the row
    /// INDEX) so that when LFGs sort/dedup/expire and re-shuffle on
    /// every render tick, the cursor stays parked on the same actual
    /// message instead of skating across rows as items move beneath
    /// it. Set whenever the user navigates (j/k); cleared if the
    /// message disappears entirely.
    lfg_selected_message_id: Option<String>,
    /// Geometry of the LFG list area as rendered last frame, captured
    /// for click-to-row mapping. Stores (top_y, bottom_y, scroll_offset)
    /// of the actual list rows (excluding block borders + 1-row column
    /// header). Translation is `row_index = (click_y - top_y) / 2 +
    /// scroll_offset` because each LFG entry spans 2 terminal rows.
    /// None until the first LFG render.
    lfg_view_bounds: Option<LfgViewBounds>,
    /// Shared LFG state populated by the userscript via the local HTTP
    /// server. None when the LFG server failed to bind (e.g., port
    /// already in use); UI hides the panel in that case.
    lfg_state: Option<std::sync::Arc<std::sync::Mutex<lfg::LfgState>>>,

    /// Detected terminal capabilities (graphics protocol, tmux,
    /// TTY-or-not). Captured once at startup; used to decide whether
    /// to render OW rank icons as real PNGs (Kitty/Sixel/iTerm2) or
    /// fall back to Unicode glyphs.
    #[allow(dead_code)]
    term_caps: term_caps::TermCaps,

    /// Loaded + protocol-prepared OW rank icons (one per tier),
    /// allocated once and rendered into the LFG view inline. None when
    /// the terminal doesn't support graphics or when icon load failed
    /// (the TUI then uses the Unicode fallback in `Tier::glyph()`).
    rank_icons: Option<rank_icons::RankIcons>,
}

impl App {
    fn new(install: BnetInstall, accounts: Vec<String>, app_config: AppConfig) -> Self {
        let mut list_state = ListState::default();
        // Select the first row if we have anything to show — this includes
        // pending and known rows even when SavedAccountNames is empty.
        let any_displayable = !accounts.is_empty()
            || !app_config.pending_merge_emails.is_empty()
            || !app_config.accounts.is_empty();
        if any_displayable {
            list_state.select(Some(0));
        }
        // If we restarted in the middle of an Add New Account workflow,
        // make that obvious.
        let status = if !app_config.pending_merge_emails.is_empty() {
            format!(
                "Add New Account in progress. {} pending account(s) (yellow). Sign into Battle.net with new credentials, then press 's' to save.",
                app_config.pending_merge_emails.len()
            )
        } else {
            "Ready. Enter switch, a add, s save, x kill, n nickname, f refresh ranks, q quit."
                .to_string()
        };
        // Spin up the long-lived rank-fetch worker. It receives fetch
        // requests on `req_rx`, paces them under OverFast's rate limit,
        // and sends results back on `res_tx`.
        let (req_tx, req_rx) = mpsc::channel::<FetchRequest>();
        let (res_tx, res_rx) = mpsc::channel::<RankUpdate>();
        std::thread::spawn(move || {
            fetch_worker(req_rx, res_tx);
        });

        // Detect terminal capabilities ONCE at startup. Doesn't touch
        // the terminal state (just env vars + isatty), so safe to call
        // before any raw-mode/alt-screen setup.
        let caps = term_caps::TermCaps::detect();

        // Try to load OW rank icons if the terminal supports inline
        // graphics. Failure here is non-fatal: we silently fall back to
        // Unicode glyph rendering. Errors that DO surface (decode
        // failures, picker init errors) we log to stderr -- they'll
        // show after TUI exit, useful for diagnosis without disturbing
        // the alt-screen.
        let rank_icons = match rank_icons::RankIcons::try_new(&caps) {
            Ok(Some(icons)) => {
                eprintln!("[bnetswitch] rank icons: PNG mode active ({})", caps.summary());
                Some(icons)
            }
            Ok(None) => {
                eprintln!("[bnetswitch] rank icons: Unicode fallback ({})", caps.summary());
                None
            }
            Err(e) => {
                eprintln!(
                    "[bnetswitch] rank icons: Unicode fallback ({}, picker init failed: {})",
                    caps.summary(), e
                );
                None
            }
        };

        Self {
            install,
            accounts,
            app_config,
            list_state,
            status,
            editing_nickname: false,
            nickname_input: String::new(),
            editing_placement: false,
            placement_input: String::new(),
            should_quit: false,
            ranks_by_email: HashMap::new(),
            fetching_emails: std::collections::HashSet::new(),
            failed_emails: std::collections::HashMap::new(),
            rank_rx: res_rx,
            fetch_request_tx: req_tx,
            view: View::Accounts,
            lfg_list_state: ListState::default(),
            lfg_selected_message_id: None,
            lfg_view_bounds: None,
            lfg_state: None,
            term_caps: caps,
            rank_icons,
        }
    }

    /// Wire the LFG server's shared state into the App so the LFG view
    /// can read messages and the 'g'-Enter handler can enqueue actions.
    /// Called once after `LfgServer::start()` succeeds in main.
    fn attach_lfg(&mut self, state: std::sync::Arc<std::sync::Mutex<lfg::LfgState>>) {
        self.lfg_state = Some(state);
    }

    /// Number of LFG messages currently in the bridge's store. Used by
    /// j/k navigation in the LFG view.
    #[allow(dead_code)]  // legacy navigation path; kept for any callers
    fn lfg_message_count(&self) -> usize {
        self.lfg_state
            .as_ref()
            .and_then(|s| s.lock().ok().map(|g| g.messages.len()))
            .unwrap_or(0)
    }

    /// Compute the LFG message_ids in their final display order, mirroring
    /// what `render_lfg_view` produces row-by-row: stale-filter, author
    /// dedup, VC dedup, then sort by (compatibility tier, freshness).
    /// Returns IDs only -- callers that need full entry data do their
    /// own parse/merge.
    ///
    /// Used by j/k navigation so cursor moves through the same visible
    /// list the user sees, regardless of what list_state has stored.
    fn lfg_visible_message_ids(&self) -> Vec<String> {
        let state = match &self.lfg_state {
            Some(s) => s.clone(),
            None => return Vec::new(),
        };
        let raw_messages: Vec<lfg::LfgMessage> = match state.lock() {
            Ok(g) => g.messages.iter().cloned().collect(),
            Err(_) => return Vec::new(),
        };
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0);
        let stale_ms = self.app_config.lfg_stale_threshold_secs * 1000;
        let mut messages: Vec<lfg::LfgMessage> = raw_messages
            .into_iter()
            .filter(|m| now_ms.saturating_sub(m.timestamp_ms) <= stale_ms)
            .collect();
        if self.app_config.lfg_dedupe_by_author {
            let mut seen: std::collections::HashSet<String> =
                std::collections::HashSet::new();
            messages.retain(|m| seen.insert(m.author.clone()));
        }
        // VC dedup: keep canonical (first/most-recent) per VC, parse for
        // sort key + merge across VC mates so compatibility tiering uses
        // the merged rank/role view.
        let mut entries: Vec<(lfg::LfgMessage, lfg_parse::ParsedLfg)> =
            if self.app_config.lfg_dedupe_by_voice_channel {
                let mut by_vc: std::collections::HashMap<String, usize> =
                    std::collections::HashMap::new();
                let mut out: Vec<(lfg::LfgMessage, lfg_parse::ParsedLfg)> = Vec::new();
                for msg in messages.iter() {
                    let parsed = lfg_parse::parse_description(
                        msg.description.as_deref().unwrap_or(""),
                    );
                    match &msg.voice_channel_id {
                        Some(vc_id) => match by_vc.get(vc_id).copied() {
                            Some(idx) => {
                                out[idx].1.merge_in(&parsed);
                            }
                            None => {
                                by_vc.insert(vc_id.clone(), out.len());
                                out.push((msg.clone(), parsed));
                            }
                        },
                        None => {
                            out.push((msg.clone(), parsed));
                        }
                    }
                }
                out
            } else {
                messages
                    .iter()
                    .map(|m| {
                        let p = lfg_parse::parse_description(
                            m.description.as_deref().unwrap_or(""),
                        );
                        (m.clone(), p)
                    })
                    .collect()
            };

        let my_ranks = self.active_account_role_ranks();
        entries.sort_by_key(|(msg, parsed)| lfg_sort_key(msg, parsed, &my_ranks));
        entries.into_iter().map(|(m, _)| m.message_id).collect()
    }

    /// Translate a mouse click at (col, row) into a 0-based LFG row
    /// index, or None if the click was outside the list area.
    ///
    /// Relies on `lfg_view_bounds` having been populated by the most
    /// recent render. Computes:
    ///   relative_y = click_y - top_y
    ///   visible_idx = relative_y / row_height
    ///   absolute_idx = scroll_offset + visible_idx
    ///
    /// Returns None if the click is on the column-header row or in
    /// padding past the last drawn entry, even if it's within
    /// (top_y..bottom_y).
    fn row_index_at_click(&self, col: u16, row: u16) -> Option<usize> {
        let b = self.lfg_view_bounds?;
        if col < b.left_x || col >= b.right_x { return None; }
        if row < b.top_y || row >= b.bottom_y { return None; }
        let relative_y = row.saturating_sub(b.top_y) as usize;
        let visible_idx = relative_y / b.row_height as usize;
        Some(b.offset + visible_idx)
    }

    /// Move LFG selection by `delta` (positive = down, negative = up)
    /// through the visible (sorted/dedup'd) entries. Updates
    /// `lfg_selected_message_id` directly; the next render derives the
    /// row index from it. Wraps at boundaries.
    fn lfg_navigate(&mut self, delta: i32) {
        let ids = self.lfg_visible_message_ids();
        if ids.is_empty() {
            self.lfg_selected_message_id = None;
            self.lfg_list_state.select(None);
            return;
        }
        let cur_idx = self
            .lfg_selected_message_id
            .as_ref()
            .and_then(|id| ids.iter().position(|x| x == id))
            .unwrap_or(0) as i32;
        let len = ids.len() as i32;
        let new_idx = cur_idx.saturating_add(delta).rem_euclid(len) as usize;
        self.lfg_selected_message_id = Some(ids[new_idx].clone());
        self.lfg_list_state.select(Some(new_idx));
    }

    /// Enqueue a `JoinByMessage` action for the currently selected LFG
    /// row. Returns the display label of the queued message on success
    /// (for status bar feedback), None if no row is selected.
    ///
    /// IMPORTANT: indexing here uses the SAME filter+dedupe pipeline as
    /// the render path, so what the user sees on screen at index N is
    /// what gets joined. Without this, pressing Enter on row 3 (visually)
    /// could enqueue row 3 of the unfiltered list, which is a different
    /// LFG entirely.
    fn enqueue_join_for_selected_lfg(&mut self) -> Result<Option<String>> {
        let state = match &self.lfg_state {
            Some(s) => s.clone(),
            None => return Ok(None),
        };

        let idx = match self.lfg_list_state.selected() {
            Some(i) => i,
            None => return Ok(None),
        };

        // Replicate the render-time filtering: stale + author dedupe +
        // VC group-and-merge. Indexing here MUST match what render_lfg
        // produces row-by-row (same order, same dropped messages).
        let visible = {
            let guard = state
                .lock()
                .map_err(|_| anyhow::anyhow!("LFG state mutex poisoned"))?;
            let now_ms = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis() as u64)
                .unwrap_or(0);
            let stale_ms = self.app_config.lfg_stale_threshold_secs * 1000;
            let mut filtered: Vec<lfg::LfgMessage> = guard
                .messages
                .iter()
                .filter(|m| now_ms.saturating_sub(m.timestamp_ms) <= stale_ms)
                .cloned()
                .collect();
            if self.app_config.lfg_dedupe_by_author {
                let mut seen: std::collections::HashSet<String> =
                    std::collections::HashSet::new();
                filtered.retain(|m| seen.insert(m.author.clone()));
            }
            if self.app_config.lfg_dedupe_by_voice_channel {
                // Keep only the FIRST (most recent) message per VC --
                // matches render's group-and-merge canonical-message
                // selection. The merge of metadata happens render-side
                // and doesn't affect indexing.
                let mut seen_vcs: std::collections::HashSet<String> =
                    std::collections::HashSet::new();
                filtered.retain(|m| match &m.voice_channel_id {
                    Some(id) => seen_vcs.insert(id.clone()),
                    None => true,
                });
            }
            filtered
        };

        let entry = match visible.get(idx).cloned() {
            Some(m) => m,
            None => return Ok(None),
        };

        // Refuse joins on full VCs -- userscript clicking "Join Voice"
        // on a full channel would just bounce silently.
        if entry.voice_channel_full() {
            return Ok(Some(format!(
                "{} -- VC FULL ({}/{}); not queueing",
                entry.author,
                entry.voice_channel_users.unwrap_or(0),
                entry.voice_channel_capacity.unwrap_or(0)
            )));
        }

        let vc_name = entry
            .fields
            .iter()
            .find(|f| f.name.to_lowercase().contains("voice channel"))
            .map(|f| f.value.clone())
            .unwrap_or_else(|| "?".to_string());

        let label = format!("{} ({})", entry.author, vc_name);

        // Append to joined-VC history file. Best-effort; failures are
        // non-fatal (the join still queues).
        if let Err(e) = append_joined_vc_history(&entry, &vc_name) {
            self.status = format!("(history write failed: {})", e);
        }

        let mut guard = state
            .lock()
            .map_err(|_| anyhow::anyhow!("LFG state mutex poisoned"))?;
        guard.enqueue_action(lfg::LfgActionKind::JoinByMessage {
            message_id: entry.message_id.clone(),
            channel_id: entry.channel_id.clone(),
            guild_id: entry.guild_id.clone(),
            voice_channel_id: entry.voice_channel_id.clone(),
            // PRIMARY join target: the URL captured from the embed's
            // Join Voice button at parse time. Userscript navigates to
            // this via SPA routing; no DOM lookup needed.
            voice_channel_url: entry.voice_channel_url.clone(),
        });

        Ok(Some(label))
    }

    /// Per-role rank points for the active account. None values mean
    /// the role is unranked / not fetched.
    fn active_account_role_ranks(&self) -> ActiveRanks {
        let mut out = ActiveRanks::default();
        let active_email = match self.accounts.first() {
            Some(e) => e,
            None => return out,
        };
        let ranks = match self.ranks_by_email.get(active_email) {
            Some(r) => r,
            None => return out,
        };
        out.tank = ranks.tank.as_ref().map(lfg_parse::RankPoint::from_snapshot);
        out.dps = ranks.damage.as_ref().map(lfg_parse::RankPoint::from_snapshot);
        out.support = ranks.support.as_ref().map(lfg_parse::RankPoint::from_snapshot);
        out
    }

    /// Pre-load any rank cache files we have on disk into `ranks_by_email`
    /// so the TUI shows historical data immediately on startup, even
    /// before background fetches return.
    fn load_cached_ranks(&mut self) {
        for (email, meta) in &self.app_config.accounts {
            if let Some(tag) = &meta.battletag {
                if let Some(ranks) = ranks::load_any_cached(tag) {
                    self.ranks_by_email.insert(email.clone(), ranks);
                }
            }
        }
    }

    /// Queue a single rank fetch on the worker thread.
    fn queue_rank_fetch(&mut self, email: String, battletag: String, force: bool) {
        if self.fetching_emails.contains(&email) {
            return; // Already queued or in-flight.
        }
        self.fetching_emails.insert(email.clone());
        // Worker receiver dropped only on app shutdown, so send is
        // basically infallible here. If it does fail we just leave the
        // email marked as fetching; not worth panicking over.
        let _ = self.fetch_request_tx.send(FetchRequest {
            email,
            battletag,
            force,
        });
    }

    /// Queue fetches for every account we have a BattleTag for.
    /// Called once on startup and from the 'f' hotkey.
    fn refresh_all_ranks(&mut self, force: bool) {
        let pairs: Vec<(String, String)> = self
            .app_config
            .accounts
            .iter()
            .filter_map(|(email, meta)| {
                meta.battletag
                    .as_ref()
                    .map(|tag| (email.clone(), tag.clone()))
            })
            .collect();
        for (email, battletag) in pairs {
            self.queue_rank_fetch(email, battletag, force);
        }
    }

    /// Drain pending rank update messages from the channel, applying
    /// them to state. Called from the main loop on each tick so updates
    /// appear without requiring a key press.
    fn drain_rank_updates(&mut self) {
        while let Ok(update) = self.rank_rx.try_recv() {
            self.fetching_emails.remove(&update.email);
            match update.ranks {
                Ok(r) => {
                    self.failed_emails.remove(&update.email);
                    self.ranks_by_email.insert(update.email, r);
                }
                Err(e) => {
                    self.failed_emails.insert(update.email, e);
                }
            }
        }
    }

    /// Build the unified row list shown in the TUI.
    ///
    /// Order:
    /// 1. Active (always first if present)
    /// 2. Saved (other entries in `SavedAccountNames`)
    /// 3. Pending (cleared during Add New, will be restored on `s`)
    /// 4. Known (from TCNO import / config, not yet logged-in here)
    ///
    /// Within each group, sort order matches insertion / config order so
    /// the layout doesn't jump around between renders.
    fn displayed_accounts(&self) -> Vec<AccountRow> {
        let mut rows: Vec<AccountRow> = Vec::new();
        let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

        // Active + Saved (in order from SavedAccountNames).
        //
        // Defensive dedup: SavedAccountNames is supposed to be a unique
        // set of emails, but Battle.net occasionally writes duplicates
        // (especially after partial workflow exits). The HashSet skip
        // prevents the same email from being shown twice. The first
        // occurrence wins (so it stays Active if it was at index 0).
        for (i, email) in self.accounts.iter().enumerate() {
            if !seen.insert(email.clone()) {
                continue;
            }
            let state = if i == 0 {
                AccountState::Active
            } else {
                AccountState::Saved
            };
            rows.push(AccountRow {
                email: email.clone(),
                state,
            });
        }

        // Pending (during Add New workflow)
        for email in &self.app_config.pending_merge_emails {
            if !seen.insert(email.clone()) {
                continue;
            }
            rows.push(AccountRow {
                email: email.clone(),
                state: AccountState::Pending,
            });
        }

        // Known (from app_config.accounts map) — accounts we have BattleTags
        // for but aren't switchable yet on this machine.
        let mut known: Vec<String> = self
            .app_config
            .accounts
            .keys()
            .filter(|e| !seen.contains(*e))
            .cloned()
            .collect();
        known.sort(); // stable display order
        for email in known {
            rows.push(AccountRow {
                email,
                state: AccountState::Known,
            });
        }

        rows
    }

    /// Email of the row currently selected in the displayed list.
    fn selected_email(&self) -> Option<String> {
        let rows = self.displayed_accounts();
        self.list_state
            .selected()
            .and_then(|i| rows.get(i).cloned())
            .map(|r| r.email)
    }

    /// Full row info of the current selection, for state-aware actions.
    fn selected_row(&self) -> Option<AccountRow> {
        let rows = self.displayed_accounts();
        self.list_state
            .selected()
            .and_then(|i| rows.get(i).cloned())
    }

    fn switch_to_selected(&mut self) -> Result<()> {
        let row = match self.selected_row() {
            Some(r) => r,
            None => {
                self.status = "No account selected.".to_string();
                return Ok(());
            }
        };
        let email = row.email.clone();

        // Reject switching to non-switchable rows with a helpful hint.
        match row.state {
            AccountState::Active => {
                // If Battle.net isn't currently running, treat Enter on
                // the active account as "just launch it" — saves the user
                // from having to alt-tab to Lutris just to start the game.
                if switcher::is_bnet_running() {
                    self.status = format!(
                        "{} is already active and Battle.net is running.",
                        self.app_config.display_name(&email)
                    );
                } else if self.app_config.auto_launch {
                    match switcher::launch_bnet(&self.install, self.app_config.use_lutris) {
                        Ok(_) => {
                            self.status = format!(
                                "Launching Battle.net for {}...",
                                self.app_config.display_name(&email)
                            );
                        }
                        Err(e) => {
                            self.status = format!("Launch failed: {}", e);
                        }
                    }
                } else {
                    self.status = format!(
                        "{} is already active. Auto-launch is OFF (press 'l' to enable).",
                        self.app_config.display_name(&email)
                    );
                }
                return Ok(());
            }
            AccountState::Pending => {
                self.status = format!(
                    "{} is pending restore. Press 's' to finish the Add New workflow first.",
                    self.app_config.display_name(&email)
                );
                return Ok(());
            }
            AccountState::Known => {
                self.status = format!(
                    "{} has no remembered password on this machine. Press 'a' to log in for the first time.",
                    self.app_config.display_name(&email)
                );
                return Ok(());
            }
            AccountState::Saved => {
                // proceed below
            }
        }

        self.status = format!("Switching to {}...", self.app_config.display_name(&email));

        // Kill Battle.net
        switcher::kill_bnet_processes()?;

        // Reorder accounts
        let new_order = config::reorder_accounts(&self.accounts, &email);
        config::write_account_order(&self.install.config_path, &new_order)?;
        self.accounts = new_order;

        // Reset selection to top (the new active account)
        self.list_state.select(Some(0));

        // Launch if configured
        if self.app_config.auto_launch {
            switcher::launch_bnet(&self.install, self.app_config.use_lutris)?;
            self.status = format!("Switched to {} and launched Battle.net.", email);
        } else {
            self.status = format!("Switched to {}. Launch Battle.net manually.", email);
        }

        // Push the new account's BattleTag as a per-server nickname to all
        // configured Discord guilds. Best-effort: failures are surfaced
        // in the status bar but don't fail the switch itself.
        self.sync_discord_nickname_for(&email);

        Ok(())
    }

    /// Enqueue `set_nickname` actions for each configured Discord guild,
    /// using the email's BattleTag (or the email itself if no tag is known)
    /// as the nickname. The userscript polls /actions and executes the
    /// DOM walk to actually rename us in each guild.
    ///
    /// No-op when:
    ///   - LFG bridge isn't running (lfg_state None)
    ///   - No guilds configured for nickname sync
    ///   - Account has no BattleTag (we fall back to the email's local
    ///     part; Discord nicknames are 1-32 chars so we truncate)
    fn sync_discord_nickname_for(&mut self, email: &str) {
        let state = match &self.lfg_state {
            Some(s) => s.clone(),
            None => return,
        };
        let guilds = self.app_config.discord_nickname_sync_guilds.clone();
        if guilds.is_empty() {
            return;
        }

        // Resolve the nickname to push: BattleTag preferred, fallback to
        // email local part. Discord caps nicknames at 32 chars; we truncate.
        let nickname = self
            .app_config
            .accounts
            .get(email)
            .and_then(|m| m.battletag.clone())
            .unwrap_or_else(|| email.split('@').next().unwrap_or(email).to_string());
        let nickname = nickname.chars().take(32).collect::<String>();

        let mut guard = match state.lock() {
            Ok(g) => g,
            Err(_) => {
                self.status = format!("{}\n[lfg state mutex poisoned, skipping nickname sync]", self.status);
                return;
            }
        };
        for guild_id in &guilds {
            guard.enqueue_action(lfg::LfgActionKind::SetNickname {
                guild_id: guild_id.clone(),
                nickname: nickname.clone(),
            });
        }
        self.status = format!(
            "{} | Discord nickname queue: '{}' -> {} guild(s)",
            self.status,
            nickname,
            guilds.len()
        );
    }

    fn start_nickname_edit(&mut self) {
        if let Some(email) = self.selected_email() {
            let current = self
                .app_config
                .accounts
                .get(&email)
                .and_then(|m| m.nickname.clone())
                .unwrap_or_default();
            self.nickname_input = current;
            self.editing_nickname = true;
            self.status = "Type nickname, press Enter to save, Esc to cancel.".to_string();
        }
    }

    fn finish_nickname_edit(&mut self, save: bool) -> Result<()> {
        if save {
            if let Some(email) = self.selected_email() {
                let email = email.to_string();
                let nick = self.nickname_input.trim().to_string();
                if nick.is_empty() {
                    // Remove nickname
                    if let Some(meta) = self.app_config.accounts.get_mut(&email) {
                        meta.nickname = None;
                    }
                } else {
                    self.app_config.set_nickname(&email, nick.clone());
                }
                self.app_config.save()?;
                self.status = format!("Nickname saved for {}.", email);
            }
        } else {
            self.status = "Nickname edit cancelled.".to_string();
        }
        self.editing_nickname = false;
        self.nickname_input.clear();
        Ok(())
    }

    /// Begin the "Add New Account" workflow.
    ///
    /// Idempotent across repeated invocations:
    ///
    /// - **First press**: snapshots `SavedAccountNames` into
    ///   `pending_merge_emails`, clears the config, relaunches.
    /// - **Pressed again, no login happened**: `SavedAccountNames` is
    ///   already empty, so we don't lose `pending_merge_emails`. We just
    ///   relaunch Battle.net (in case the user closed it).
    /// - **Pressed again after a successful login** (user pressed `a`
    ///   instead of `s`): the new email gets appended to
    ///   `pending_merge_emails` so it's not lost, then we clear and
    ///   relaunch for the *next* new account. Effectively batches
    ///   multiple add-new operations before final save.
    ///
    /// In all cases, the persisted `pending_merge_emails` is the union of
    /// (previous pending) ∪ (current SavedAccountNames), with insertion
    /// order preserved.
    fn add_new_account(&mut self) -> Result<()> {
        let on_disk = config::read_saved_accounts(&self.install.config_path)?;

        // Merge — never overwrite. This is the critical bug fix vs an
        // earlier version that did `pending = on_disk`, which would clobber
        // the snapshot on a second 'a' press while SavedAccountNames was
        // empty (mid-workflow).
        for email in on_disk {
            if !self.app_config.pending_merge_emails.contains(&email) {
                self.app_config.pending_merge_emails.push(email);
            }
        }
        self.app_config.save()?;

        // Stop any running Battle.net so it doesn't fight us when we modify
        // the config file. OW must be quit before this point — if it isn't,
        // killing the launcher will probably take OW down with it.
        switcher::kill_bnet_processes()?;

        // Clear SavedAccountNames so the relaunch shows a blank login.
        config::write_account_order(&self.install.config_path, &[])?;
        self.accounts.clear();

        // Reset selection to the first row of the new displayed list,
        // which will be the first pending account (yellow). This avoids
        // stranding the highlight on a row that no longer exists.
        if !self.displayed_accounts().is_empty() {
            self.list_state.select(Some(0));
        } else {
            self.list_state.select(None);
        }

        // Launch fresh Battle.net.
        switcher::launch_bnet(&self.install, self.app_config.use_lutris)?;

        let pending_count = self.app_config.pending_merge_emails.len();
        self.status = format!(
            "Add New Account: Battle.net launched. Sign in (check 'Keep me logged in'), then press 's' to save. {} account(s) pending restore.",
            pending_count
        );
        Ok(())
    }

    /// Save whatever account is currently logged in to Battle.net.
    ///
    /// Two scenarios:
    ///
    /// **Pending merge active** (after `add_new_account`):
    /// - Battle.net's `SavedAccountNames` should now contain only the
    ///   newly-added account (assuming the user successfully logged in).
    /// - We merge the new account at position [0] with the previously
    ///   snapshotted `pending_merge_emails`, deduplicating in case the
    ///   "new" account was already known.
    /// - Write the merged list back to Battle.net.config.
    /// - Clear `pending_merge_emails`.
    ///
    /// **No pending merge** (just a manual refresh):
    /// - Reload accounts from disk.
    /// - Re-run BattleTag auto-detection for the active account.
    /// - Useful after the user logged in/out manually outside the TUI.
    fn save_current(&mut self) -> Result<()> {
        let current_on_disk = config::read_saved_accounts(&self.install.config_path)?;

        if !self.app_config.pending_merge_emails.is_empty() {
            // Pending merge path
            let new_email = current_on_disk.first().cloned();
            let pending = self.app_config.pending_merge_emails.clone();

            // Build merged list: new account first, then pending (deduped).
            let mut merged: Vec<String> = Vec::with_capacity(pending.len() + 1);
            if let Some(ref email) = new_email {
                merged.push(email.clone());
            }
            for email in pending {
                if !merged.contains(&email) {
                    merged.push(email);
                }
            }

            if merged.is_empty() {
                self.status =
                    "No new account detected and no pending accounts to restore.".to_string();
                return Ok(());
            }

            config::write_account_order(&self.install.config_path, &merged)?;
            self.accounts = merged.clone();
            self.list_state.select(Some(0));

            // Capture BattleTag for the newly active account.
            self.refresh_active_battletag();

            self.app_config.pending_merge_emails.clear();
            self.app_config.save()?;

            match new_email {
                Some(email) => {
                    let display = self.app_config.display_name(&email);
                    self.status = format!(
                        "Saved {}. Restored {} other account(s).",
                        display,
                        merged.len().saturating_sub(1)
                    );
                }
                None => {
                    self.status = format!(
                        "No new account login detected. Restored {} pending account(s).",
                        merged.len()
                    );
                }
            }
        } else {
            // Plain refresh path
            self.accounts = current_on_disk;
            if !self.accounts.is_empty() {
                self.list_state.select(Some(0));
            }
            self.refresh_active_battletag();
            if let Some(email) = self.accounts.first() {
                let display = self.app_config.display_name(email);
                self.status = format!("Refreshed. Active: {}", display);
            } else {
                self.status = "No accounts saved in Battle.net.config yet.".to_string();
            }
        }

        Ok(())
    }

    /// Begin manual placement editing for the selected row.
    /// Used to record historical rank info Blizzard's API can't give us
    /// (e.g., placements from past seasons that no longer appear on the
    /// career page).
    fn start_placement_edit(&mut self) {
        if let Some(row) = self.selected_row() {
            if matches!(row.state, AccountState::Pending | AccountState::Known) {
                self.status =
                    "Cannot annotate placements for pending/needs-login accounts.".to_string();
                return;
            }
            self.placement_input.clear();
            self.editing_placement = true;
            self.status =
                "Enter placement: <T|D|S> <division> <tier 1-5> <season#>. Esc to cancel."
                    .to_string();
        }
    }

    /// Apply parsed placement to the selected account's cached ranks.
    /// Persists to the on-disk rank cache so the value survives restarts.
    fn finish_placement_edit(&mut self, save: bool) -> Result<()> {
        if !save {
            self.editing_placement = false;
            self.placement_input.clear();
            self.status = "Placement edit cancelled.".to_string();
            return Ok(());
        }
        let email = match self.selected_email() {
            Some(e) => e,
            None => {
                self.editing_placement = false;
                self.placement_input.clear();
                return Ok(());
            }
        };

        let parsed = parse_placement_input(self.placement_input.trim());
        match parsed {
            Ok((role, snap)) => {
                let battletag = match self
                    .app_config
                    .accounts
                    .get(&email)
                    .and_then(|m| m.battletag.clone())
                {
                    Some(t) => t,
                    None => {
                        self.status = format!(
                            "Cannot save placement: no BattleTag known for {}.",
                            email
                        );
                        self.editing_placement = false;
                        self.placement_input.clear();
                        return Ok(());
                    }
                };

                // Load (or default) cached ranks, set the role, persist.
                let mut ranks = ranks::load_any_cached(&battletag).unwrap_or_default();
                match role {
                    Role::Tank => ranks.tank = Some(snap.clone()),
                    Role::Damage => ranks.damage = Some(snap.clone()),
                    Role::Support => ranks.support = Some(snap.clone()),
                }
                // Don't lower current_season — this is just a historical
                // entry, not a fresh fetch. If we've never fetched, the
                // entry's own season becomes the implicit current.
                if ranks.current_season.is_none() {
                    ranks.current_season = Some(snap.season);
                }
                ranks::save_cached(&battletag, &ranks);
                self.ranks_by_email.insert(email.clone(), ranks);
                self.status = format!(
                    "Saved placement for {}: {:?} {} (S{}).",
                    self.app_config.display_name(&email),
                    role,
                    snap.label(),
                    snap.season
                );
            }
            Err(e) => {
                self.status = format!("Could not parse placement: {}", e);
            }
        }
        self.editing_placement = false;
        self.placement_input.clear();
        Ok(())
    }

    /// Re-read the most recent BattleTag from CachedData.db and assign it
    /// to whichever email is currently active (`SavedAccountNames[0]`).
    fn refresh_active_battletag(&mut self) {
        let active = match self.accounts.first().cloned() {
            Some(e) => e,
            None => return,
        };
        if let Some(tag) = config::read_most_recent_battletag(&self.install.prefix) {
            let needs_update = self
                .app_config
                .accounts
                .get(&active)
                .and_then(|m| m.battletag.as_deref())
                != Some(tag.as_str());
            if needs_update {
                self.app_config.set_battletag(&active, tag);
                let _ = self.app_config.save();
            }
        }
    }
}

fn print_usage() {
    eprintln!("bnetswitch - Battle.net account switcher for Linux");
    eprintln!();
    eprintln!("USAGE:");
    eprintln!("    bnetswitch                       Run interactive TUI");
    eprintln!("    bnetswitch import-tcno <PATH>    Import BattleTags from TCNO");
    eprintln!("    bnetswitch --help                Show this help");
    eprintln!();
    eprintln!("IMPORT-TCNO:");
    eprintln!("    PATH can be:");
    eprintln!("      * a TCNO ids.json file");
    eprintln!("      * the LoginCache/BattleNet directory");
    eprintln!("      * the TCNO Account Switcher root directory");
    eprintln!();
    eprintln!("    Example:");
    eprintln!("      bnetswitch import-tcno \"/mnt/win-c/Users/me/AppData/Roaming/TcNo Account Switcher\"");
}

fn run_import_tcno(path: &str) -> Result<()> {
    use std::path::Path;

    let mut app_config = AppConfig::load()?;
    let imported = tcno::import_from_path(Path::new(path))?;

    if imported.is_empty() {
        println!("No accounts found in TCNO data at {}", path);
        return Ok(());
    }

    let mut new_count = 0;
    let mut updated_count = 0;
    let mut skipped_count = 0;

    for acc in &imported {
        let existing = app_config.accounts.get(&acc.email).cloned();
        match existing.and_then(|m| m.battletag) {
            Some(existing_tag) if existing_tag == acc.battletag => {
                skipped_count += 1;
            }
            Some(_) => {
                app_config.set_battletag(&acc.email, acc.battletag.clone());
                updated_count += 1;
            }
            None => {
                app_config.set_battletag(&acc.email, acc.battletag.clone());
                new_count += 1;
            }
        }
        println!("  {} -> {}", acc.email, acc.battletag);
    }

    app_config.save()?;
    println!();
    println!(
        "Imported {} accounts ({} new, {} updated, {} unchanged).",
        imported.len(),
        new_count,
        updated_count,
        skipped_count
    );
    println!("Saved to {}", AppConfig::config_path()?.display());
    Ok(())
}

/// Headless mode: start the LFG bridge HTTP server and block forever.
///
/// Used in two contexts:
///   1. Smoke testing the bridge without a real terminal (e.g., from
///      a non-tty shell).
///   2. Running the bridge as a long-lived systemd user service so the
///      userscript can post messages even when the bnetswitch TUI
///      isn't open.
///
/// In service mode, a separate bnetswitch TUI invocation can read
/// the same in-memory state? -- no, can't share memory across processes.
/// The TUI talks to the LFG server via the same HTTP endpoints as the
/// userscript. This is a future refactor; for now `lfg-server` is just
/// for testing.
fn run_lfg_server() -> Result<()> {
    println!("Starting LFG bridge HTTP server on 127.0.0.1:{}", lfg::LFG_PORT);
    println!("Auth token: {}", lfg::LFG_AUTH_TOKEN);
    println!();
    println!("Endpoints:");
    println!("  GET  /health");
    println!("  POST /lfg/message");
    println!("  POST /lfg/remove");
    println!("  GET  /lfg/active");
    println!("  GET  /actions");
    println!("  POST /actions/ack");
    println!("  POST /status");
    println!();
    println!("Press Ctrl-C to exit.");

    let _server = lfg::LfgServer::start()?;

    // Block forever waiting for SIGINT/SIGTERM. The server thread does
    // the actual work; this thread just parks so the process doesn't
    // exit and bring the server down with it.
    loop {
        std::thread::park();
    }
}

/// Run `parse_description` against every record in a JSONL dump and
/// report parse coverage per field, plus list a sample of failures.
///
/// JSONL record shape (matches what the playwright dump script writes):
///   {"id": "...", "ts": "...", "author": "...", "description": "...",
///    "voice_channel_id": "..."}
///
/// Output:
///   - Total messages, missing-rank count, missing-roles count, etc.
///   - Top-N descriptions that failed each parse stage (so we can see
///     patterns and improve heuristics).
///   - Optionally, --verbose dumps every failure.
fn run_lfg_backtest(path: &str, verbose: bool) -> Result<()> {
    use std::io::BufRead;

    #[derive(serde::Deserialize)]
    struct Record {
        #[serde(default)]
        id: String,
        #[allow(dead_code)]
        #[serde(default)]
        ts: String,
        #[allow(dead_code)]
        #[serde(default)]
        author: String,
        #[serde(default)]
        description: String,
        #[allow(dead_code)]
        #[serde(default)]
        voice_channel_id: Option<String>,
    }

    let file = std::fs::File::open(path)
        .map_err(|e| anyhow::anyhow!("failed to open {}: {}", path, e))?;
    let reader = std::io::BufReader::new(file);

    let mut total = 0usize;
    let mut empty_desc = 0usize;
    let mut no_rank = 0usize;
    let mut no_roles = 0usize;
    let mut no_anything = 0usize; // empty rank AND empty roles
    let mut single_rank = 0usize; // only min OR max set
    let mut full_rank = 0usize; // both min and max set

    // ====================================================================
    // CORRECTNESS invariants (introduced after coverage-only backtest
    // missed a real bug -- "gold to bronze" parsed as Go 5 - Br 1 with
    // min.score > max.score, but counted as "full_rank" because both
    // were set).
    //
    // Each violation produces a sample so we can fix the parser. The
    // bounds are conservative: catch the egregious cases without
    // false-flagging legitimate wide ranges (e.g., "all ranks welcome").
    // ====================================================================
    let mut inverted_range = 0usize; // min.score > max.score
    let mut absurdly_wide  = 0usize; // > 25 divisions (5+ tier span)
    let mut very_wide      = 0usize; // > 15 divisions (3+ tier span)

    let cap = if verbose { usize::MAX } else { 30 };
    let mut no_rank_samples: Vec<(String, String)> = Vec::new();
    let mut no_roles_samples: Vec<(String, String)> = Vec::new();
    let mut no_anything_samples: Vec<(String, String)> = Vec::new();
    let mut inverted_samples: Vec<(String, String, String, String)> = Vec::new();
    let mut absurd_samples: Vec<(String, String, String, String)> = Vec::new();
    let mut very_wide_samples: Vec<(String, String, String, String)> = Vec::new();

    for line in reader.lines() {
        let line = line?;
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let rec: Record = match serde_json::from_str(line) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("skipped malformed line: {}", e);
                continue;
            }
        };
        total += 1;

        let desc = rec.description.trim();
        if desc.is_empty() {
            empty_desc += 1;
            continue;
        }

        let parsed = lfg_parse::parse_description(desc);
        let has_rank = parsed.rank_min.is_some() || parsed.rank_max.is_some();
        let has_full_rank = parsed.rank_min.is_some() && parsed.rank_max.is_some();
        let has_roles = !parsed.roles_needed.is_empty();

        if !has_rank {
            no_rank += 1;
            if no_rank_samples.len() < cap {
                no_rank_samples.push((rec.id.clone(), desc.to_string()));
            }
        } else if !has_full_rank {
            single_rank += 1;
        } else {
            full_rank += 1;
        }
        if !has_roles {
            no_roles += 1;
            if no_roles_samples.len() < cap {
                no_roles_samples.push((rec.id.clone(), desc.to_string()));
            }
        }
        if !has_rank && !has_roles {
            no_anything += 1;
            if no_anything_samples.len() < cap {
                no_anything_samples.push((rec.id.clone(), desc.to_string()));
            }
        }

        // ---- correctness invariants on full-rank cases ----
        if let (Some(min), Some(max)) = (parsed.rank_min, parsed.rank_max) {
            let span = max.score().saturating_sub(min.score()) as i64
                - (min.score().saturating_sub(max.score())) as i64;
            // Strictly inverted: min.score > max.score (parser bug)
            if min.score() > max.score() {
                inverted_range += 1;
                if inverted_samples.len() < cap {
                    inverted_samples.push((
                        rec.id.clone(),
                        desc.to_string(),
                        min.label(),
                        max.label(),
                    ));
                }
            } else {
                // Wider-than-reasonable: catches greedy bare-tier
                // expansion or misfiring open-upper detection. The
                // thresholds are conservative -- a real "all welcome"
                // post does legitimately span the full ladder.
                if span > 25 {
                    absurdly_wide += 1;
                    if absurd_samples.len() < cap {
                        absurd_samples.push((
                            rec.id.clone(),
                            desc.to_string(),
                            min.label(),
                            max.label(),
                        ));
                    }
                } else if span > 15 {
                    very_wide += 1;
                    if very_wide_samples.len() < cap {
                        very_wide_samples.push((
                            rec.id.clone(),
                            desc.to_string(),
                            min.label(),
                            max.label(),
                        ));
                    }
                }
            }
        }
    }

    let pct = |n: usize| -> f64 {
        if total == 0 {
            0.0
        } else {
            (n as f64 / total as f64) * 100.0
        }
    };

    println!("================================================================");
    println!("LFG parser backtest -- {}", path);
    println!("================================================================");
    println!("Total messages         : {}", total);
    println!("Empty description      : {} ({:.1}%)", empty_desc, pct(empty_desc));
    let parseable = total - empty_desc;
    let parseable_pct = |n: usize| -> f64 {
        if parseable == 0 {
            0.0
        } else {
            (n as f64 / parseable as f64) * 100.0
        }
    };
    println!();
    println!("Of {} non-empty descriptions:", parseable);
    println!("  full rank range      : {:>5} ({:.1}%)", full_rank, parseable_pct(full_rank));
    println!("  partial rank range   : {:>5} ({:.1}%)", single_rank, parseable_pct(single_rank));
    println!("  NO rank parsed       : {:>5} ({:.1}%)  <-- gap",
        no_rank, parseable_pct(no_rank));
    println!("  NO roles parsed      : {:>5} ({:.1}%)  <-- gap",
        no_roles, parseable_pct(no_roles));
    println!("  NEITHER rank nor role: {:>5} ({:.1}%)  <-- worst gap",
        no_anything, parseable_pct(no_anything));
    println!();
    println!("Correctness invariants on full-rank parses:");
    println!("  inverted (min>max)   : {:>5} ({:.1}%)  <-- BUG",
        inverted_range, parseable_pct(inverted_range));
    println!("  absurdly wide (>25div): {:>5} ({:.1}%)  <-- likely BUG",
        absurdly_wide, parseable_pct(absurdly_wide));
    println!("  very wide (>15div)   : {:>5} ({:.1}%)  <-- review",
        very_wide, parseable_pct(very_wide));
    println!();

    let print_samples = |label: &str, samples: &[(String, String)]| {
        println!("---- {} ({} shown) ----", label, samples.len());
        for (id, desc) in samples {
            println!("  [{}] {:?}", id, desc);
        }
        println!();
    };

    print_samples("FAIL: no rank parsed", &no_rank_samples);
    print_samples("FAIL: no roles parsed", &no_roles_samples);
    print_samples("FAIL: no rank AND no roles", &no_anything_samples);

    let print_range_samples = |label: &str, samples: &[(String, String, String, String)]| {
        println!("---- {} ({} shown) ----", label, samples.len());
        for (id, desc, min, max) in samples {
            println!("  [{}] {} - {}  desc={:?}", id, min, max, desc);
        }
        println!();
    };
    print_range_samples("BUG: inverted range (min > max)", &inverted_samples);
    print_range_samples("BUG: absurdly wide range (>25 div)", &absurd_samples);
    print_range_samples("REVIEW: very wide range (>15 div)", &very_wide_samples);

    Ok(())
}

fn main() -> Result<()> {
    // Argument dispatch. Keep it simple - one optional subcommand.
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--help") | Some("-h") | Some("help") => {
            print_usage();
            return Ok(());
        }
        Some("import-tcno") => {
            let path = args.get(1).ok_or_else(|| {
                anyhow::anyhow!("import-tcno requires a path argument. See --help.")
            })?;
            return run_import_tcno(path);
        }
        Some("lfg-server") => {
            // Headless mode: just run the HTTP bridge for the userscript,
            // no TUI. Useful for:
            //   - Testing the userscript without a full terminal session
            //   - Running the bridge as a systemd user service so it
            //     stays up even when the TUI isn't open (the userscript
            //     can post messages whenever Discord is open in the
            //     browser).
            return run_lfg_server();
        }
        Some("lfg-backtest") => {
            let path = args.get(1).ok_or_else(|| {
                anyhow::anyhow!("lfg-backtest requires a JSONL path. See --help.")
            })?;
            let verbose = args.iter().any(|a| a == "-v" || a == "--verbose");
            return run_lfg_backtest(path, verbose);
        }
        Some(other) if other.starts_with("-") => {
            eprintln!("Unknown flag: {}", other);
            print_usage();
            std::process::exit(2);
        }
        _ => {} // fall through to TUI mode
    }

    // Load our app config
    let mut app_config = AppConfig::load()?;

    // Detect installations
    let mut installs = config::detect_installations();

    // If a prefix is manually configured, try that first
    if let Some(ref prefix_str) = app_config.wine_prefix {
        let prefix = std::path::PathBuf::from(prefix_str);
        if prefix.is_dir() {
            if let Some(config_path) = find_config_manual(&prefix) {
                let exe_path = find_exe_manual(&prefix);
                installs.insert(
                    0,
                    BnetInstall {
                        prefix,
                        config_path,
                        exe_path,
                    },
                );
            }
        }
    }

    if installs.is_empty() {
        eprintln!("No Battle.net installation found!");
        eprintln!();
        eprintln!("Searched in:");
        eprintln!("  ~/Games/battlenet/");
        eprintln!("  ~/Games/battle-net/");
        eprintln!("  ~/Games/Battle.net/");
        eprintln!("  ~/.wine/");
        eprintln!("  ~/Games/*/");
        eprintln!();
        eprintln!("To manually set the Wine prefix, create the config file:");
        if let Ok(path) = AppConfig::config_path() {
            eprintln!("  {}", path.display());
        }
        eprintln!("With contents:");
        eprintln!("  wine_prefix = \"/path/to/your/wine/prefix\"");
        std::process::exit(1);
    }

    // Use the first installation found
    let install = installs.into_iter().next().unwrap();

    // Read accounts from Battle.net.config
    let accounts = config::read_saved_accounts(&install.config_path)?;
    if accounts.is_empty() && app_config.pending_merge_emails.is_empty() {
        eprintln!("No saved accounts found in {}", install.config_path.display());
        eprintln!("Make sure you've logged into Battle.net at least once with 'Remember Password' checked.");
        std::process::exit(1);
    }
    // Note: an empty `accounts` list with non-empty `pending_merge_emails`
    // means we're mid-way through an "Add New Account" workflow. The TUI
    // will show the empty state and prompt the user to press 's' once
    // they've completed login.

    // Auto-detect BattleTag for the currently active account.
    //
    // Battle.net stores BattleTags in CachedData.db (SQLite) but doesn't
    // expose a direct email -> BattleTag mapping (the `name` column is an
    // opaque hash of the account ID). Instead, we use ROWID-based recency:
    // the most recently inserted/updated entry in `login_cache` corresponds
    // to whoever is currently logged in, which is `accounts[0]`.
    //
    // This means each time a user switches and Battle.net successfully
    // authenticates, we capture that account's BattleTag the next time
    // bnetswitch runs. Over multiple switches, every account gets populated.
    if let Some(active_email) = accounts.first() {
        if let Some(tag) = config::read_most_recent_battletag(&install.prefix) {
            // Only auto-populate if the user hasn't manually set a BattleTag.
            // A nickname always wins over auto-detection (set via `n` hotkey).
            let needs_update = app_config
                .accounts
                .get(active_email)
                .and_then(|m| m.battletag.as_deref())
                != Some(tag.as_str());
            if needs_update {
                app_config.set_battletag(active_email, tag);
                let _ = app_config.save();
            }
        }
    }

    // Set up terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    // EnableMouseCapture turns on the terminal's mouse-tracking mode
    // (DEC private modes 1000/1002/1006). Without it, crossterm only
    // emits keyboard events. We enable here so click-to-join in the
    // LFG view works on any terminal that supports SGR mouse mode
    // (kitty, foot, alacritty, xterm, ghostty, gnome-terminal, etc.).
    //
    // Caveat: while mouse capture is active the terminal swallows
    // text-selection drags. Most modern terminals offer a
    // hold-Shift-to-select escape hatch (kitty, gnome-terminal,
    // alacritty), but that's the user's burden to know about.
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::new(install, accounts, app_config);
    // Show whatever's in the on-disk rank cache immediately so the TUI
    // isn't a sea of "—" while background fetches run.
    app.load_cached_ranks();
    // Kick off non-forced fetches; fresh cached entries (< 1h old) will
    // short-circuit without making HTTP calls.
    app.refresh_all_ranks(false);

    // ====================================================================
    // LFG bridge server (Phase 4 minimum: just start it; TUI panel is
    // wired separately).
    //
    // Binds localhost:7172 in a background thread. The Tampermonkey
    // userscript posts Discord LFG embeds here. We hold the LfgServer
    // for the rest of main()'s scope so the listener thread keeps
    // running until the TUI exits.
    //
    // Failure to bind is non-fatal: maybe another bnetswitch instance
    // is already running. The TUI continues without LFG features.
    // ====================================================================
    let lfg_server = match lfg::LfgServer::start() {
        Ok(s) => {
            // Hand the shared LFG state to App so the LFG view can read
            // messages and the join-action hotkey can enqueue work for
            // the userscript.
            app.attach_lfg(s.state.clone());
            app.status = format!(
                "LFG bridge listening on :{}. Press 'g' to toggle LFG view.",
                lfg::LFG_PORT
            );
            Some(s)
        }
        Err(e) => {
            app.status = format!("LFG bridge unavailable: {}", e);
            None
        }
    };

    // Boot-time Discord nickname sync. If the user has configured
    // discord_nickname_sync_guilds and the LFG bridge is up, enqueue an
    // immediate SetNickname for the active account so the Discord
    // nickname catches up to whatever drifted while bnetswitch wasn't
    // running (manual rename, external account switch, etc.).
    //
    // The userscript polls /actions every 2s; once it sees the action
    // it executes the DOM walk in your Discord tab. Requires the OW
    // Discord tab to be open and viewing a channel in that guild.
    if let Some(active_email) = app.accounts.first().cloned() {
        app.sync_discord_nickname_for(&active_email);
    }

    // Drift detection: Battle.net occasionally trims SavedAccountNames
    // when its UI is used to log in/out. Compare against the count of
    // BattleTags Battle.net itself knows about (login_cache) — if there
    // are more known tags than visible emails, the user likely wants to
    // hit 'R' to rebuild.
    let known_tag_count = config::login_cache_count(&app.install.prefix);
    let visible_email_count = app.accounts.len();
    if known_tag_count > visible_email_count {
        app.status = format!(
            "Battle.net knows {} accounts but SavedAccountNames only lists {}. Press 'R' to rebuild.",
            known_tag_count, visible_email_count
        );
    }

    // Install a panic hook that restores terminal state before printing
    // the panic message. Without this, a panic mid-TUI leaves the user's
    // shell in raw mode + alternate-screen buffer, making the terminal
    // look broken until they reset it manually.
    //
    // We chain the previous hook so backtraces still display normally.
    let prev_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = restore_terminal();
        prev_hook(info);
    }));

    let result = run_tui(&mut terminal, &mut app);

    // Restore terminal in the normal-exit path too.
    restore_terminal()?;

    // Drop the LFG server explicitly so its bound port is released
    // immediately (rather than waiting for process exit). Idempotent
    // when None.
    drop(lfg_server);

    result
}

/// Restore the terminal from raw-mode + alt-screen back to a clean
/// state. Idempotent: safe to call from a panic hook AND the normal
/// exit path; calling twice is a no-op.
///
/// What was missing before:
///   - `terminal.show_cursor()` -- crossterm's enable_raw_mode hides
///     the cursor; without explicit Show, it stays hidden in some
///     terminals after we exit
///   - A trailing newline -- the cursor returns to wherever it was
///     before EnterAlternateScreen, which on most terminal emulators
///     is mid-line. The shell's next prompt then computes columns
///     from a non-zero starting position, leading to the wrap-anomaly
///     visible in the user's screenshot (closing `)` of starship's
///     `(took ...)` segment ending up on its own line)
fn restore_terminal() -> Result<()> {
    use crossterm::cursor::Show;
    use std::io::Write;

    // Pull stdout fresh so we don't depend on the closed-over Terminal
    // (which may have already been dropped during normal exit).
    let mut stdout = io::stdout();
    // Order matters: leave the alt-screen buffer FIRST (returns cursor
    // to its pre-alt position on the main screen), THEN disable raw
    // mode (re-enables ECHO, ICANON, etc.).
    // Disable mouse capture FIRST so the terminal stops swallowing
    // selection drags before we leave the alt screen. Doing it after
    // LeaveAlternateScreen wouldn't be wrong, but the order here is
    // symmetric with setup: capture-on, alt-on; alt-off, capture-off.
    let _ = execute!(stdout, DisableMouseCapture, LeaveAlternateScreen, Show);
    let _ = disable_raw_mode();
    // Newline + flush so the shell's next prompt starts cleanly at
    // column 0 of a new line. Without this, starship's multi-line
    // prompt computes columns from wherever the alt-screen restore
    // left the cursor.
    let _ = writeln!(stdout);
    let _ = stdout.flush();
    Ok(())
}

fn find_config_manual(prefix: &std::path::Path) -> Option<std::path::PathBuf> {
    let users_dir = prefix.join("drive_c/users");
    if !users_dir.is_dir() {
        return None;
    }
    for entry in std::fs::read_dir(&users_dir).ok()?.flatten() {
        if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            let candidate = entry
                .path()
                .join("AppData/Roaming/Battle.net/Battle.net.config");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn find_exe_manual(prefix: &std::path::Path) -> Option<std::path::PathBuf> {
    let candidates = [
        "drive_c/Program Files (x86)/Battle.net/Battle.net.exe",
        "drive_c/Program Files/Battle.net/Battle.net.exe",
    ];
    for c in &candidates {
        let p = prefix.join(c);
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

fn run_tui(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>, app: &mut App) -> Result<()> {
    // 100ms tick rate so background rank fetches surface quickly without
    // the user having to press a key.
    let tick = Duration::from_millis(100);
    loop {
        // Drain any completed background work first so the upcoming draw
        // reflects the latest state.
        app.drain_rank_updates();
        terminal.draw(|f| ui(f, app))?;

        // Use poll() so we yield back to the loop on the tick interval
        // even when no keys have been pressed. Without this, drain_rank
        // updates only ran on key press and ranks would appear stuck.
        if !event::poll(tick)? {
            continue;
        }
        let event = event::read()?;

        // ----- Mouse handling -----
        // Click-to-join in LFG view. Translate the click row to a
        // visible LFG row, set selection, queue a join. We use the
        // view bounds App.lfg_view_bounds saved during the last
        // render -- click maps directly to the row index.
        if let Event::Mouse(mouse) = &event {
            if matches!(mouse.kind, MouseEventKind::Down(MouseButton::Left))
                && app.view == View::Lfg
            {
                if let Some(visible_idx) = app.row_index_at_click(mouse.column, mouse.row) {
                    let ids = app.lfg_visible_message_ids();
                    if let Some(id) = ids.get(visible_idx).cloned() {
                        app.lfg_selected_message_id = Some(id);
                        app.lfg_list_state.select(Some(visible_idx));
                        // Fire join action immediately. Same path as
                        // the 'j' keybind so behavior matches.
                        let _ = app.enqueue_join_for_selected_lfg();
                    }
                }
            }
            // Wheel scrolling: behave like j/k repeated. Stays
            // anchored to the same lfg_visible_message_ids view.
            if app.view == View::Lfg {
                if matches!(mouse.kind, MouseEventKind::ScrollDown) {
                    app.lfg_navigate(1);
                } else if matches!(mouse.kind, MouseEventKind::ScrollUp) {
                    app.lfg_navigate(-1);
                }
            }
            continue;
        }

        if let Event::Key(key) = event {
            if key.kind != KeyEventKind::Press {
                continue;
            }

            if app.editing_nickname {
                match key.code {
                    KeyCode::Enter => app.finish_nickname_edit(true)?,
                    KeyCode::Esc => app.finish_nickname_edit(false)?,
                    KeyCode::Backspace => {
                        app.nickname_input.pop();
                    }
                    KeyCode::Char(c) => {
                        app.nickname_input.push(c);
                    }
                    _ => {}
                }
                continue;
            }

            if app.editing_placement {
                match key.code {
                    KeyCode::Enter => app.finish_placement_edit(true)?,
                    KeyCode::Esc => app.finish_placement_edit(false)?,
                    KeyCode::Backspace => {
                        app.placement_input.pop();
                    }
                    KeyCode::Char(c) => {
                        app.placement_input.push(c);
                    }
                    _ => {}
                }
                continue;
            }

            match key.code {
                KeyCode::Char('q') | KeyCode::Esc => {
                    app.should_quit = true;
                }

                // ----- view toggle -----
                // 'g' switches between the accounts view and the LFG view.
                // LFG view only available if the bridge server bound; if
                // it failed to start, this is a no-op with a status hint.
                KeyCode::Char('g') => {
                    if app.lfg_state.is_none() {
                        app.status = "LFG bridge not available (port 7172 in use?)".to_string();
                    } else {
                        app.view = match app.view {
                            View::Accounts => View::Lfg,
                            View::Lfg => View::Accounts,
                        };
                        // Reset LFG list selection on entry so we don't
                        // dangle on a row that no longer exists.
                        if app.view == View::Lfg {
                            app.lfg_list_state.select(Some(0));
                            app.status = "LFG view. j/k navigate, Enter joins, g back.".to_string();
                        } else {
                            app.status = "Accounts view.".to_string();
                        }
                    }
                }

                // ----- list navigation: routed by current view -----
                KeyCode::Down | KeyCode::Char('j') => {
                    match app.view {
                        View::Accounts => {
                            let len = app.displayed_accounts().len();
                            if len == 0 {
                                continue;
                            }
                            let i = match app.list_state.selected() {
                                Some(i) => {
                                    if i >= len.saturating_sub(1) { 0 } else { i + 1 }
                                }
                                None => 0,
                            };
                            app.list_state.select(Some(i));
                        }
                        View::Lfg => {
                            // lfg_navigate operates on the SAME sorted +
                            // deduped view that render_lfg_view produces,
                            // so cursor moves match what user sees on
                            // screen. Bypasses raw lfg_message_count.
                            app.lfg_navigate(1);
                        }
                    }
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    match app.view {
                        View::Accounts => {
                            let len = app.displayed_accounts().len();
                            if len == 0 {
                                continue;
                            }
                            let i = match app.list_state.selected() {
                                Some(i) => if i == 0 { len.saturating_sub(1) } else { i - 1 },
                                None => 0,
                            };
                            app.list_state.select(Some(i));
                        }
                        View::Lfg => {
                            app.lfg_navigate(-1);
                        }
                    }
                }
                KeyCode::Enter => {
                    match app.view {
                        View::Accounts => {
                            if let Err(e) = app.switch_to_selected() {
                                app.status = format!("Error: {}", e);
                            }
                        }
                        View::Lfg => {
                            // Enqueue a join action for the userscript to
                            // execute on its next /actions poll.
                            match app.enqueue_join_for_selected_lfg() {
                                Ok(Some(label)) => {
                                    app.status = format!("Queued join: {}", label);
                                }
                                Ok(None) => {
                                    app.status = "No LFG selected.".to_string();
                                }
                                Err(e) => {
                                    app.status = format!("Join error: {}", e);
                                }
                            }
                        }
                    }
                }
                KeyCode::Char('n') => {
                    app.start_nickname_edit();
                }
                KeyCode::Char('p') => {
                    app.start_placement_edit();
                }
                KeyCode::Char('o') => {
                    // Launch Overwatch for the selected (or active)
                    // account directly. If the selection is a different
                    // account, switch to it first, then launch with
                    // --exec=launch Pro so OW pops up immediately.
                    let row = match app.selected_row() {
                        Some(r) => r,
                        None => {
                            app.status = "No account selected.".to_string();
                            continue;
                        }
                    };
                    let needs_switch = !matches!(row.state, AccountState::Active);
                    if needs_switch && !matches!(row.state, AccountState::Saved) {
                        app.status = format!(
                            "Cannot launch OW for {}: account isn't ready (try Enter first).",
                            app.app_config.display_name(&row.email)
                        );
                        continue;
                    }
                    if needs_switch {
                        // Reuse the swap path so we don't duplicate logic.
                        // It already kills + writes config + relaunches,
                        // but we want to launch OW specifically. So:
                        // kill, rewrite, then launch_overwatch ourselves.
                        if let Err(e) = switcher::kill_bnet_processes() {
                            app.status = format!("Kill failed: {}", e);
                            continue;
                        }
                        let new_order =
                            config::reorder_accounts(&app.accounts, &row.email);
                        if let Err(e) =
                            config::write_account_order(&app.install.config_path, &new_order)
                        {
                            app.status = format!("Config write failed: {}", e);
                            continue;
                        }
                        app.accounts = new_order;
                        app.list_state.select(Some(0));
                    }
                    match switcher::launch_overwatch(
                        &app.install,
                        app.app_config.use_lutris,
                        app.app_config.warm_launch_ttl_secs,
                    ) {
                        Ok(switcher::LaunchOutcome::Warm) => {
                            app.status = format!(
                                "Launching Overwatch for {} (warm: direct spawn).",
                                app.app_config.display_name(&row.email)
                            );
                        }
                        Ok(switcher::LaunchOutcome::Cold) => {
                            app.status = format!(
                                "Opening Battle.net to OW tab for {} (cold: click Play).",
                                app.app_config.display_name(&row.email)
                            );
                        }
                        Err(e) => {
                            app.status = format!("OW launch failed: {}", e);
                        }
                    }
                }
                KeyCode::Char('y') => {
                    // Yank (vim-style copy) the selected account's
                    // BattleTag to the system clipboard.
                    let row = match app.selected_row() {
                        Some(r) => r,
                        None => {
                            app.status = "No account selected.".to_string();
                            continue;
                        }
                    };
                    let tag = app
                        .app_config
                        .accounts
                        .get(&row.email)
                        .and_then(|m| m.battletag.clone());
                    match tag {
                        Some(t) => match switcher::copy_to_clipboard(&t) {
                            Ok(_) => {
                                app.status = format!("Copied BattleTag '{}' to clipboard.", t);
                            }
                            Err(e) => {
                                app.status = format!("Clipboard copy failed: {}", e);
                            }
                        },
                        None => {
                            app.status = format!(
                                "No BattleTag known for {}.",
                                row.email
                            );
                        }
                    }
                }
                KeyCode::Char('Y') => {
                    // Shift-y copies email instead of BattleTag.
                    let row = match app.selected_row() {
                        Some(r) => r,
                        None => {
                            app.status = "No account selected.".to_string();
                            continue;
                        }
                    };
                    match switcher::copy_to_clipboard(&row.email) {
                        Ok(_) => {
                            app.status =
                                format!("Copied email '{}' to clipboard.", row.email);
                        }
                        Err(e) => {
                            app.status = format!("Clipboard copy failed: {}", e);
                        }
                    }
                }
                KeyCode::Char('l') => {
                    // Toggle auto-launch
                    app.app_config.auto_launch = !app.app_config.auto_launch;
                    app.app_config.save()?;
                    app.status = format!(
                        "Auto-launch: {}",
                        if app.app_config.auto_launch {
                            "ON"
                        } else {
                            "OFF"
                        }
                    );
                }
                KeyCode::Char('r') => {
                    // Reload accounts from disk
                    match config::read_saved_accounts(&app.install.config_path) {
                        Ok(accs) => {
                            app.accounts = accs;
                            if !app.accounts.is_empty() {
                                app.list_state.select(Some(0));
                            }
                            app.status = "Accounts reloaded.".to_string();
                        }
                        Err(e) => {
                            app.status = format!("Reload failed: {}", e);
                        }
                    }
                }
                KeyCode::Char('a') => {
                    // Add New Account: clear SavedAccountNames, relaunch
                    // Battle.net so the user gets a blank login screen.
                    if let Err(e) = app.add_new_account() {
                        app.status = format!("Add new failed: {}", e);
                    }
                }
                KeyCode::Char('s') => {
                    // Save Current: capture whatever Battle.net is logged into,
                    // merge with pending list if we're in an "add new" workflow.
                    if let Err(e) = app.save_current() {
                        app.status = format!("Save current failed: {}", e);
                    }
                }
                KeyCode::Char('x') => {
                    // Kill Battle.net + Agent + any running Blizzard games.
                    // Doesn't touch wineserver; faster than 'X' (aggressive).
                    match switcher::kill_bnet_processes() {
                        Ok(_) => {
                            app.status =
                                "Killed Battle.net launcher, Agent, and any running games.".to_string();
                        }
                        Err(e) => {
                            app.status = format!("Kill failed: {}", e);
                        }
                    }
                }
                KeyCode::Char('X') => {
                    // Aggressive kill: also tears down wineserver + lutris
                    // wrapper for the prefix. Slower; use when you want a
                    // truly clean shutdown.
                    match switcher::kill_bnet_aggressive(&app.install) {
                        Ok(_) => {
                            app.status =
                                "Killed Battle.net + wineserver + Lutris wrapper for prefix."
                                    .to_string();
                        }
                        Err(e) => {
                            app.status = format!("Aggressive kill failed: {}", e);
                        }
                    }
                }
                KeyCode::Char('f') => {
                    // Force-refresh ranks: invalidate disk cache for every
                    // known account, then kick off fresh fetches. Useful
                    // after playing matches that changed your SR.
                    let tags: Vec<String> = app
                        .app_config
                        .accounts
                        .values()
                        .filter_map(|m| m.battletag.clone())
                        .collect();
                    for tag in &tags {
                        ranks::invalidate_cache(tag);
                    }
                    app.refresh_all_ranks(true);
                    app.status = format!("Refreshing ranks for {} account(s)...", tags.len());
                }
                KeyCode::Char('R') => {
                    // Rebuild SavedAccountNames from accounts Battle.net
                    // *actually has credentials for*. Source of truth is
                    // the login_cache SQLite table — only BattleTags listed
                    // there have encrypted tokens on disk and can be
                    // auto-logged-in by Battle.net.
                    //
                    // We intentionally do NOT include accounts known only
                    // from a TCNO import; those don't have credentials on
                    // this machine yet and would just sit dead in the
                    // SavedAccountNames list.
                    //
                    // Order: login_cache returns BattleTags by recency
                    // (most recent first via ROWID DESC). We map those
                    // back to emails using bnetswitch's known mapping,
                    // which preserves the natural recency order.

                    let authed_tags = config::read_all_battletags(&app.install.prefix);

                    // Build BattleTag -> email reverse map from our config.
                    let mut tag_to_email: HashMap<String, String> = HashMap::new();
                    for (email, meta) in &app.app_config.accounts {
                        if let Some(tag) = &meta.battletag {
                            tag_to_email.insert(tag.clone(), email.clone());
                        }
                    }

                    let mut order: Vec<String> = Vec::new();
                    let mut unmapped_tags: Vec<String> = Vec::new();
                    for tag in &authed_tags {
                        match tag_to_email.get(tag) {
                            Some(email) => {
                                if !order.contains(email) {
                                    order.push(email.clone());
                                }
                            }
                            None => unmapped_tags.push(tag.clone()),
                        }
                    }

                    if order.is_empty() {
                        app.status = format!(
                            "No authenticated accounts found in login_cache (found {} tags but none mapped to known emails).",
                            authed_tags.len()
                        );
                    } else {
                        match config::write_account_order(&app.install.config_path, &order) {
                            Ok(_) => {
                                app.accounts = order.clone();
                                app.list_state.select(Some(0));
                                let mut msg = format!(
                                    "Rebuilt SavedAccountNames with {} authenticated account(s).",
                                    order.len()
                                );
                                if !unmapped_tags.is_empty() {
                                    msg.push_str(&format!(
                                        " {} BattleTag(s) in login_cache had no email mapping (skipped): {}",
                                        unmapped_tags.len(),
                                        unmapped_tags.join(", ")
                                    ));
                                }
                                app.status = msg;
                                app.refresh_all_ranks(false);
                            }
                            Err(e) => {
                                app.status = format!("Rebuild failed: {}", e);
                            }
                        }
                    }
                }
                _ => {}
            }
        }

        if app.should_quit {
            return Ok(());
        }
    }
}

/// Parse a manual placement entry of the form
/// `<role> <division> <tier> <season>`.
///
/// Examples that all parse identically to (Tank, Diamond 3, S12):
/// - `T Diamond 3 12`
/// - `tank diam 3 s12`
/// - `T diamond 3 S12`
///
/// Returns the parsed role and the resulting [`ranks::RankSnapshot`].
fn parse_placement_input(input: &str) -> Result<(Role, ranks::RankSnapshot), String> {
    let tokens: Vec<&str> = input.split_whitespace().collect();
    if tokens.len() < 4 {
        return Err(
            "expected 4 tokens: <role> <division> <tier> <season>".to_string(),
        );
    }

    let role = match tokens[0].to_ascii_lowercase().as_str() {
        "t" | "tank" => Role::Tank,
        "d" | "dps" | "damage" => Role::Damage,
        "s" | "sup" | "support" => Role::Support,
        other => return Err(format!("unknown role '{}'; use T/D/S", other)),
    };

    let division = match tokens[1].to_ascii_lowercase().as_str() {
        "bronze" | "b" => Division::Bronze,
        "silver" | "si" => Division::Silver,
        "gold" | "g" => Division::Gold,
        "platinum" | "plat" | "p" => Division::Platinum,
        "diamond" | "diam" | "di" => Division::Diamond,
        "master" | "mast" | "m" => Division::Master,
        "grandmaster" | "gm" => Division::Grandmaster,
        "champion" | "champ" | "c" => Division::Champion,
        "top500" | "top_500" | "t500" => Division::Top500,
        other => return Err(format!("unknown division '{}'", other)),
    };

    let tier: u8 = tokens[2]
        .parse()
        .map_err(|_| format!("tier '{}' is not a number", tokens[2]))?;
    if !(1..=5).contains(&tier) {
        return Err(format!("tier {} out of range (1-5)", tier));
    }

    // Season may have a leading "s" or "S" for readability.
    let season_str = tokens[3].trim_start_matches(|c: char| c == 's' || c == 'S');
    let season: u32 = season_str
        .parse()
        .map_err(|_| format!("season '{}' is not a number", tokens[3]))?;

    Ok((
        role,
        ranks::RankSnapshot {
            division,
            tier,
            season,
        },
    ))
}

/// Truncate or right-pad a string to exactly `width` columns.
/// Operates on chars rather than bytes so multi-byte BattleTags aren't
/// sliced mid-codepoint. We don't account for grapheme clusters or wide
/// emoji — BattleTags are constrained to plain ASCII/Latin so this is
/// safe in practice.
fn pad_or_truncate(s: &str, width: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    if chars.len() >= width {
        // Truncate with an ellipsis so the user knows the name was cut.
        let mut out: String = chars.into_iter().take(width.saturating_sub(1)).collect();
        out.push('…');
        out
    } else {
        let mut out = s.to_string();
        out.push_str(&" ".repeat(width - chars.len()));
        out
    }
}

/// Pick a foreground color for a given division, roughly matching the
/// in-game rank tier colors.
fn division_color(div: Division) -> Color {
    match div {
        Division::Bronze => Color::Rgb(184, 115, 51),       // copper
        Division::Silver => Color::Rgb(192, 192, 192),      // silver
        Division::Gold => Color::Rgb(255, 215, 0),          // gold
        Division::Platinum => Color::Rgb(127, 232, 233),    // teal-cyan
        Division::Diamond => Color::Rgb(176, 224, 230),     // pale blue
        Division::Master => Color::Rgb(255, 140, 0),        // orange
        Division::Grandmaster => Color::Rgb(255, 80, 130),  // pink
        Division::Champion => Color::Rgb(220, 100, 255),    // violet
        Division::Top500 => Color::Rgb(255, 255, 100),      // bright yellow
    }
}

/// Distinct visual states a role cell can be in. Determined by the
/// renderer based on rank snapshot, fetch state, and 404/error flags.
#[derive(Debug, Clone, Copy)]
enum CellState {
    /// Have a rank snapshot from the current season.
    Current,
    /// Have a rank snapshot from an earlier season (dim + season tag).
    PastSeason,
    /// Public profile but not placed for this role.
    Unranked,
    /// Profile is private or BattleTag doesn't exist (404 from API).
    Private,
    /// Most recent fetch errored out (network/5xx/429). Sticky until
    /// next attempt succeeds — distinguishes from Unranked/Private.
    FetchError,
    /// Queued or in-flight on the fetch worker.
    Fetching,
    /// No fetch has been attempted yet.
    NotAttempted,
}

/// Render a single role cell. Width-fixed, color-coded.
/// Render a role's rank cell. Returns a Vec of spans rather than a
/// single Span so we can include a tier-colored glyph alongside the
/// rank text without losing column alignment.
///
/// Cell layout: `[g] LABEL_PADDED_TO_FIT` (13 cells total, glyph
/// included). For non-Current/PastSeason states (no rank) the glyph
/// slot is empty space so columns still line up.
///
/// The tier returned (Option<Tier>) is the rank's tier, used by the
/// caller to record icon overlay positions for the PNG overlay pass.
fn render_role_cell(
    snap: Option<&ranks::RankSnapshot>,
    _is_stale: bool, // Kept for callers; semantics now driven by `state`.
    state: CellState,
) -> (Vec<Span<'static>>, Option<lfg_parse::Tier>) {
    let (text, base_style, tier) = match state {
        CellState::Current => {
            let s = snap.expect("Current state requires a snapshot");
            (
                s.label(),
                Style::default().fg(division_color(s.division)),
                Some(lfg_parse::Tier::from_division(s.division)),
            )
        }
        CellState::PastSeason => {
            let s = snap.expect("PastSeason state requires a snapshot");
            (
                format!("{} (S{})", s.label(), s.season),
                Style::default().fg(division_color(s.division)),
                Some(lfg_parse::Tier::from_division(s.division)),
            )
        }
        CellState::Unranked => (
            "unranked".to_string(),
            Style::default().fg(Color::Gray),
            None,
        ),
        CellState::Private => (
            "private".to_string(),
            Style::default().fg(Color::Rgb(140, 100, 130)),
            None,
        ),
        CellState::FetchError => (
            "err".to_string(),
            Style::default().fg(Color::Red),
            None,
        ),
        CellState::Fetching => (
            "...".to_string(),
            Style::default().fg(Color::DarkGray),
            None,
        ),
        CellState::NotAttempted => (
            "—".to_string(),
            Style::default().fg(Color::DarkGray),
            None,
        ),
    };
    let style = if matches!(state, CellState::PastSeason) {
        base_style
            .add_modifier(Modifier::DIM)
            .add_modifier(Modifier::ITALIC)
    } else {
        base_style
    };
    // Cell width budget: 13 cells. With a glyph, that's:
    //   glyph(1) + space(1) + text(11)
    // Without a glyph (Unranked/Private/etc.), the leading 2 cells are
    // blank space so adjacent rank cells still column-align.
    const CELL_WIDTH: usize = 13;
    let mut spans: Vec<Span<'static>> = Vec::with_capacity(3);
    if let Some(t) = tier {
        let (r, g, b) = t.color_rgb();
        spans.push(Span::styled(t.glyph(), style.fg(Color::Rgb(r, g, b))));
        spans.push(Span::raw(" "));
        let text_padded = pad_or_truncate(&text, CELL_WIDTH.saturating_sub(2));
        spans.push(Span::styled(text_padded, style));
    } else {
        // No glyph: pad with 2 leading spaces so the cell still occupies
        // the same width (and rank cells line up across rows that DO
        // have ranks).
        spans.push(Span::raw("  "));
        let text_padded = pad_or_truncate(&text, CELL_WIDTH.saturating_sub(2));
        spans.push(Span::styled(text_padded, style));
    }
    (spans, tier)
}

/// Determine the cell state for one role of one account, given current
/// fetch tracking state and any cached rank data.
fn classify_role(
    snap: Option<&ranks::RankSnapshot>,
    is_past_season: bool,
    has_cache_entry: bool,
    not_found: bool,
    is_fetching: bool,
    fetch_failed: bool,
) -> CellState {
    if let Some(_) = snap {
        if is_past_season {
            CellState::PastSeason
        } else {
            CellState::Current
        }
    } else if not_found {
        CellState::Private
    } else if fetch_failed && !has_cache_entry {
        CellState::FetchError
    } else if is_fetching {
        CellState::Fetching
    } else if has_cache_entry {
        // We fetched and got 200, but no rank for this role. Public but
        // not placed.
        CellState::Unranked
    } else if fetch_failed {
        CellState::FetchError
    } else {
        CellState::NotAttempted
    }
}

fn ui(f: &mut ratatui::Frame, app: &mut App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Title
            Constraint::Min(5),   // Account list
            Constraint::Length(3), // Status bar
            Constraint::Length(2), // Help
        ])
        .split(f.area());

    // Title
    let (active_label, active_style) = match app.accounts.first() {
        Some(email) => (
            app.app_config.display_name(email),
            Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
        ),
        None => (
            "(none — Add New in progress)".to_string(),
            Style::default().fg(Color::Yellow).add_modifier(Modifier::ITALIC),
        ),
    };
    let title = Paragraph::new(Line::from(vec![
        Span::styled("bnetswitch", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
        Span::raw(" | Active: "),
        Span::styled(active_label, active_style),
    ]))
    .block(Block::default().borders(Borders::ALL).title("Battle.net Account Switcher"));
    f.render_widget(title, chunks[0]);

    // Branch: render either the accounts list (default) or the LFG
    // bridge panel. Both use chunks[1] for the body; status bar and help
    // bar below adapt to whichever is active.
    if app.view == View::Lfg {
        render_lfg_view(f, chunks[1], app);
        // Status + help bars still rendered below.
        let status_style = Style::default().fg(Color::Yellow);
        let status = Paragraph::new(Span::styled(&app.status, status_style))
            .block(Block::default().borders(Borders::ALL).title("Status"));
        f.render_widget(status, chunks[2]);

        let help = Paragraph::new(Line::from(vec![
            Span::styled(" ⏎", Style::default().fg(Color::Cyan)),
            Span::raw(" Join  "),
            Span::styled("g", Style::default().fg(Color::Cyan)),
            Span::raw(" Back to accounts  "),
            Span::styled("j/k", Style::default().fg(Color::Cyan)),
            Span::raw(" Navigate  "),
            Span::styled("q", Style::default().fg(Color::Cyan)),
            Span::raw(" Quit"),
        ]));
        f.render_widget(help, chunks[3]);
        return;
    }

    // Account list — unified view across all known account states.
    //
    // Layout (per row):
    //   [3 prefix] [display name padded to ~38] [T col 12] [D col 12] [S col 12] [suffix]
    //
    // Color choices favor readability over transparent terminals (Hyprland +
    // wallpaper). DarkGray + DIM tends to disappear against complex
    // backgrounds; we use Color::Gray (mid-brightness 256-color) and skip
    // DIM modifier for the "Known" state.
    let rows = app.displayed_accounts();
    const NAME_WIDTH: usize = 38;

    // Parallel to `items`: per-row icon positions for the PNG overlay
    // pass. Each row may have 0-3 icons (one per role cell with a
    // ranked snapshot). Tracked so we can render PNG icons on top of
    // the Unicode glyphs in graphics-capable terminals.
    //
    // Column offsets are within the inner area (after left border).
    let mut acct_row_icons: Vec<Vec<(u16, lfg_parse::Tier)>> =
        Vec::with_capacity(rows.len());

    let items: Vec<ListItem> = rows
        .iter()
        .map(|row| {
            let display = app.app_config.display_name(&row.email);
            // Truncate or pad to a fixed width so columns align.
            let display_padded = pad_or_truncate(&display, NAME_WIDTH);

            let (row_style, prefix, suffix, suffix_style) = match row.state {
                AccountState::Active => (
                    Style::default()
                        .fg(Color::Green)
                        .add_modifier(Modifier::BOLD),
                    " * ",
                    "",
                    Style::default(),
                ),
                AccountState::Saved => (
                    Style::default().fg(Color::White),
                    "   ",
                    "",
                    Style::default(),
                ),
                AccountState::Pending => (
                    Style::default()
                        .fg(Color::Yellow)
                        .add_modifier(Modifier::ITALIC),
                    " ~ ",
                    "  (pending)",
                    Style::default().fg(Color::Yellow),
                ),
                AccountState::Known => (
                    Style::default().fg(Color::Gray),
                    " - ",
                    "  (needs login)",
                    Style::default().fg(Color::Blue),
                ),
            };

            // Look up rank data and fetch state for this account.
            let ranks_opt = app.ranks_by_email.get(&row.email);
            let is_fetching = app.fetching_emails.contains(&row.email);
            let fetch_failed = app.failed_emails.contains_key(&row.email);
            let has_cache = ranks_opt.is_some();
            let not_found = ranks_opt.map(|r| r.not_found).unwrap_or(false);

            let make_cell = |role: Role| -> (Vec<Span<'static>>, Option<lfg_parse::Tier>) {
                let snap = ranks_opt.and_then(|r| r.role(role));
                let past = ranks_opt
                    .map(|r| r.is_role_from_past_season(role))
                    .unwrap_or(false);
                let state =
                    classify_role(snap, past, has_cache, not_found, is_fetching, fetch_failed);
                render_role_cell(snap, past, state)
            };
            let (tank_spans, tank_tier) = make_cell(Role::Tank);
            let (dps_spans, dps_tier) = make_cell(Role::Damage);
            let (sup_spans, sup_tier) = make_cell(Role::Support);

            // Compute glyph column positions for the PNG overlay pass.
            //   prefix(3) + display(38) + " "(1) = 42
            // Each role cell starts at:
            //   T: 42, D: 42 + 13 = 55, S: 55 + 13 = 68
            // Glyphs sit at the very start of their cell when present.
            const T_COL: u16 = 42;
            const D_COL: u16 = T_COL + 13;
            const S_COL: u16 = D_COL + 13;
            let mut row_icons: Vec<(u16, lfg_parse::Tier)> = Vec::new();
            if let Some(t) = tank_tier { row_icons.push((T_COL, t)); }
            if let Some(t) = dps_tier  { row_icons.push((D_COL, t)); }
            if let Some(t) = sup_tier  { row_icons.push((S_COL, t)); }
            acct_row_icons.push(row_icons);

            // Assemble line. Each role cell is a Vec<Span> now.
            let mut spans: Vec<Span<'static>> = Vec::with_capacity(2 + 3 + 9 + 1);
            spans.push(Span::styled(prefix, row_style));
            spans.push(Span::styled(display_padded, row_style));
            spans.push(Span::raw(" "));
            spans.extend(tank_spans);
            spans.extend(dps_spans);
            spans.extend(sup_spans);
            spans.push(Span::styled(suffix, suffix_style));

            ListItem::new(Line::from(spans))
        })
        .collect();

    // Title summarizes counts per state
    let active_count = rows.iter().filter(|r| r.state == AccountState::Active).count();
    let saved_count = rows.iter().filter(|r| r.state == AccountState::Saved).count();
    let pending_count = rows.iter().filter(|r| r.state == AccountState::Pending).count();
    let known_count = rows.iter().filter(|r| r.state == AccountState::Known).count();
    let title = if pending_count > 0 || known_count > 0 {
        format!(
            "Accounts ({} switchable, {} pending, {} need login)",
            active_count + saved_count,
            pending_count,
            known_count
        )
    } else {
        format!("Accounts ({})", rows.len())
    };

    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title(title))
        // REVERSED inverts fg/bg automatically. This works regardless of
        // the underlying row colors and stays readable on transparent
        // terminals where a fixed bg color would create dead zones.
        .highlight_style(Style::default().add_modifier(Modifier::REVERSED))
        .highlight_symbol(">> ");

    f.render_stateful_widget(list, chunks[1], &mut app.list_state);

    // -------------------------------------------------------------------------
    // PNG icon overlay for accounts view
    // -------------------------------------------------------------------------
    // Same pattern as the LFG view: the list renders the Unicode tier
    // glyph in each ranked role cell; on graphics-capable terminals we
    // overlay the actual OW rank PNG on top of the glyph.
    //
    // Single-line entries here (vs LFG's two-line), so ROW_HEIGHT = 1.
    if let Some(icons) = app.rank_icons.as_ref() {
        const HIGHLIGHT_PREFIX_W: u16 = 3;
        const ROW_HEIGHT: u16 = 1;

        let area = chunks[1];
        let inner_y = area.y + 1;
        let inner_x = area.x + 1;
        let inner_h = area.height.saturating_sub(2);
        let offset = app.list_state.offset();
        let max_visible = (inner_h / ROW_HEIGHT) as usize;
        let (icon_w, icon_h) = icons.cell_size();

        let buf = f.buffer_mut();
        for (visible_idx, row_idx) in (offset..)
            .take(max_visible)
            .enumerate()
            .take_while(|(_, ri)| *ri < acct_row_icons.len())
        {
            let icon_y = inner_y + (visible_idx as u16 * ROW_HEIGHT);
            if icon_y + icon_h > inner_y + inner_h {
                break;
            }
            for (col_offset, tier) in &acct_row_icons[row_idx] {
                let icon_x = inner_x + HIGHLIGHT_PREFIX_W + col_offset;
                let rect = Rect::new(icon_x, icon_y, icon_w, icon_h);
                icons.render(*tier, rect, buf);
            }
        }
    }

    // Status bar
    let status_style = if app.status.starts_with("Error") {
        Style::default().fg(Color::Red)
    } else if app.status.starts_with("Switched") {
        Style::default().fg(Color::Green)
    } else {
        Style::default().fg(Color::Yellow)
    };
    let status = Paragraph::new(Span::styled(&app.status, status_style))
        .block(Block::default().borders(Borders::ALL).title("Status"));
    f.render_widget(status, chunks[2]);

    // Help bar
    let help = Paragraph::new(Line::from(vec![
        Span::styled(" ⏎", Style::default().fg(Color::Cyan)),
        Span::raw(" Switch  "),
        Span::styled("o", Style::default().fg(Color::Cyan)),
        Span::raw(" OW  "),
        Span::styled("a", Style::default().fg(Color::Cyan)),
        Span::raw("/"),
        Span::styled("s", Style::default().fg(Color::Cyan)),
        Span::raw(" Add/Save  "),
        Span::styled("R", Style::default().fg(Color::Cyan)),
        Span::raw(" Rebuild  "),
        Span::styled("x", Style::default().fg(Color::Cyan)),
        Span::raw("/"),
        Span::styled("X", Style::default().fg(Color::Cyan)),
        Span::raw(" Kill  "),
        Span::styled("y", Style::default().fg(Color::Cyan)),
        Span::raw("/"),
        Span::styled("Y", Style::default().fg(Color::Cyan)),
        Span::raw(" Copy tag/email  "),
        Span::styled("f", Style::default().fg(Color::Cyan)),
        Span::raw(" Ranks  "),
        Span::styled("p", Style::default().fg(Color::Cyan)),
        Span::raw(" Place  "),
        Span::styled("n", Style::default().fg(Color::Cyan)),
        Span::raw(" Nick  "),
        Span::styled("l", Style::default().fg(Color::Cyan)),
        Span::raw(" AutoLaunch  "),
        Span::styled("q", Style::default().fg(Color::Cyan)),
        Span::raw(" Quit"),
    ]));
    f.render_widget(help, chunks[3]);

    // Nickname editing popup
    if app.editing_nickname {
        let area = centered_rect(50, 20, f.area());
        f.render_widget(Clear, area);
        let input = Paragraph::new(Line::from(vec![
            Span::raw(&app.nickname_input),
            Span::styled("_", Style::default().add_modifier(Modifier::SLOW_BLINK)),
        ]))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Set Nickname (Enter to save, Esc to cancel)")
                .border_style(Style::default().fg(Color::Yellow)),
        );
        f.render_widget(input, area);
    }

    // Placement editing popup. Shows input + format hint so the user
    // doesn't need to remember the syntax.
    if app.editing_placement {
        let area = centered_rect(60, 24, f.area());
        f.render_widget(Clear, area);
        let lines = vec![
            Line::from(Span::styled(
                "Format: <T|D|S> <division> <tier 1-5> <season#>",
                Style::default().fg(Color::DarkGray),
            )),
            Line::from(Span::styled(
                "Examples: T Diamond 3 12  |  S GM 2 22  |  D Plat 1 18",
                Style::default().fg(Color::DarkGray),
            )),
            Line::from(""),
            Line::from(vec![
                Span::raw(&app.placement_input),
                Span::styled(
                    "_",
                    Style::default().add_modifier(Modifier::SLOW_BLINK),
                ),
            ]),
        ];
        let input = Paragraph::new(lines).block(
            Block::default()
                .borders(Borders::ALL)
                .title("Manual Placement (Enter to save, Esc to cancel)")
                .border_style(Style::default().fg(Color::Magenta)),
        );
        f.render_widget(input, area);
    }
}

/// Render the LFG bridge view in `area`. Reads the shared LfgState
/// (populated by the userscript over HTTP), parses each message's
/// free-form description, and color-codes rows by whether the parsed
/// rank range overlaps the active account's rank.
///
/// Row layout (per LFG message):
///   [marker] [author 18] [rank-range 14] [roles 14] [voice-channel 14] [age]
///
/// Marker:
///   ★  = rank match (we'd be a fit)
///   ·  = no rank info / can't determine
///   ✗  = rank mismatch (we're outside the requested range)
///
/// Color:
///   Green  = match
///   White  = unknown match status
///   Gray   = mismatch
fn render_lfg_view(f: &mut ratatui::Frame, area: Rect, app: &mut App) {
    let state = match &app.lfg_state {
        Some(s) => s.clone(),
        None => {
            // Should never happen because we gate on lfg_state.is_some()
            // before switching view, but render a placeholder in case.
            let p = Paragraph::new("LFG bridge unavailable.")
                .block(Block::default().borders(Borders::ALL).title("LFG"));
            f.render_widget(p, area);
            return;
        }
    };

    let raw_messages: Vec<lfg::LfgMessage> = match state.lock() {
        Ok(g) => g.messages.iter().cloned().collect(),
        Err(_) => Vec::new(),
    };

    let my_ranks = app.active_account_role_ranks();

    // Pre-compute "now" once for age calculations to avoid drift across
    // the row-render loop.
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);

    // Apply Phase 7 filters in this order:
    //   1. Stale filter: drop messages older than configured threshold
    //      (most LFGs fill within ~10min; older entries are noise)
    //   2. Author dedupe: keep only the most recent message per author
    //      (when enabled; some users post repeatedly to bump visibility)
    let stale_ms = app.app_config.lfg_stale_threshold_secs * 1000;
    let stale_count = raw_messages
        .iter()
        .filter(|m| now_ms.saturating_sub(m.timestamp_ms) > stale_ms)
        .count();
    let mut messages: Vec<lfg::LfgMessage> = raw_messages
        .into_iter()
        .filter(|m| now_ms.saturating_sub(m.timestamp_ms) <= stale_ms)
        .collect();

    // messages is ordered newest-first (LfgState::upsert_message inserts
    // at the front). Author dedupe simply drops older posts by the same
    // author. VC dedupe is more sophisticated: we GROUP all posts for the
    // same VC and merge their parsed metadata so partial / conflicting
    // info from teammates is unioned (e.g. one says "DPS", another adds
    // a rank range).
    let dedup_count = {
        let before = messages.len();
        if app.app_config.lfg_dedupe_by_author {
            let mut seen_authors: std::collections::HashSet<String> =
                std::collections::HashSet::new();
            messages.retain(|m| seen_authors.insert(m.author.clone()));
        }
        before - messages.len()
        // Note: VC merge happens below alongside parsing so we can union
        // ParsedLfg fields, not just drop duplicates.
    };

    // Pre-parse every message's description, then group-by-VC if enabled.
    // After this loop, `entries` is a Vec<(LfgMessage, ParsedLfg)> where
    // ParsedLfg has been merged across all posts targeting the same VC.
    // Canonical LfgMessage per group is the most recent one (front of
    // list), so author/timestamp/url reflect the latest post.
    let mut vc_dedup_count = 0usize;
    // Per-entry list of additional poster descriptions when merged. The
    // canonical entry's own description is in msg.description; this Vec
    // (parallel to entries below) carries the OTHER posters' raw text so
    // the TUI can show them on the description line. Without this, the
    // user sees only one poster's text but a range derived from N
    // posters' merged ranks -- looks like a parser bug when it's just
    // the merge doing its job.
    let mut entries_extra_descs: Vec<Vec<String>> = Vec::new();

    let mut entries: Vec<(lfg::LfgMessage, lfg_parse::ParsedLfg)> = if app
        .app_config
        .lfg_dedupe_by_voice_channel
    {
        let mut by_vc: std::collections::HashMap<String, usize> =
            std::collections::HashMap::new();
        let mut out: Vec<(lfg::LfgMessage, lfg_parse::ParsedLfg)> = Vec::new();
        for msg in messages.iter() {
            let parsed = lfg_parse::parse_description(msg.description.as_deref().unwrap_or(""));
            match &msg.voice_channel_id {
                Some(vc_id) => match by_vc.get(vc_id).copied() {
                    Some(idx) => {
                        // Merge into the canonical entry (the one we kept).
                        out[idx].1.merge_in(&parsed);
                        // Collect this poster's raw description for display.
                        // Only add if it's distinct from what we already
                        // have (avoids visual noise when teammates copy
                        // the same text).
                        let extra = msg.description.as_deref().unwrap_or("").trim().to_string();
                        if !extra.is_empty()
                            && extra != out[idx].0.description.as_deref().unwrap_or("").trim()
                            && !entries_extra_descs[idx].iter().any(|e| e == &extra)
                        {
                            entries_extra_descs[idx].push(extra);
                        }
                        vc_dedup_count += 1;
                    }
                    None => {
                        by_vc.insert(vc_id.clone(), out.len());
                        out.push((msg.clone(), parsed));
                        entries_extra_descs.push(Vec::new());
                    }
                },
                None => {
                    // No VC -- can't group, keep standalone.
                    out.push((msg.clone(), parsed));
                    entries_extra_descs.push(Vec::new());
                }
            }
        }
        out
    } else {
        let mut out: Vec<(lfg::LfgMessage, lfg_parse::ParsedLfg)> = Vec::new();
        for m in messages.iter() {
            let p = lfg_parse::parse_description(m.description.as_deref().unwrap_or(""));
            out.push((m.clone(), p));
            entries_extra_descs.push(Vec::new());
        }
        out
    };
    let total_dedup = dedup_count + vc_dedup_count;

    // ---- Tiered sort: joinability, compatibility, freshness ----
    //
    // Tier 1 (joinability): full VCs at the bottom of the entire list.
    //   You can't join a 5/5 VC -- showing them inline with potential
    //   matches wastes attention. Bury them; they stay visible for
    //   "I see Bob's stack is full, maybe next cycle" awareness, but
    //   they don't block the view of joinable groups.
    //
    // Tier 2 (compatibility): how does this LFG fit your role-ranks?
    //   - Match     → eligible to join
    //   - Unknown   → can't decide (unranked role, unparsed range)
    //   - Mismatch  → out of range
    //
    // Tier 3 (freshness): newest first by embed timestamp_ms. Fresh
    //   LFGs are most likely still recruiting; older ones are more
    //   likely stale or already filled.
    //
    // Stable sort, so VC-merge canonical ordering (most recent post
    // per VC, established earlier) is preserved within ties.
    //
    // Re-orders entries_extra_descs in lockstep so each row's "+ N
    // merged" descriptions stay paired with its canonical message.
    {
        let mut paired: Vec<((lfg::LfgMessage, lfg_parse::ParsedLfg), Vec<String>)> =
            entries.drain(..).zip(entries_extra_descs.drain(..)).collect();
        // Same key as App::lfg_visible_message_ids; see lfg_sort_key doc.
        paired.sort_by_key(|((msg, parsed), _)| lfg_sort_key(msg, parsed, &my_ranks));
        for (mp, extras) in paired.into_iter() {
            entries.push(mp);
            entries_extra_descs.push(extras);
        }
    }

    // ---- Stable cursor: derive list_state index from message_id ----
    //
    // The message_id is the source-of-truth for selection. j/k handlers
    // update it directly (using the same entries view rendered here).
    // Render's only job: find that ID in the sorted entries and set
    // list_state to its visible index. This keeps the cursor parked on
    // the same LFG even as items reorder.
    //
    // Edge cases:
    //   - First entry to view (id is None): select row 0, capture id.
    //   - Selected message vanished (stale-filtered, merged, expired):
    //     fall back to index 0 to avoid a frozen cursor on a row that
    //     no longer exists.
    //   - Empty entries list: clear selection.
    if entries.is_empty() {
        app.lfg_list_state.select(None);
        app.lfg_selected_message_id = None;
    } else {
        let idx = match &app.lfg_selected_message_id {
            Some(id) => entries
                .iter()
                .position(|(m, _)| &m.message_id == id)
                .unwrap_or(0),
            None => 0,
        };
        app.lfg_list_state.select(Some(idx));
        // Re-capture in case selected message was filtered/merged out
        // and we fell back to row 0.
        app.lfg_selected_message_id = Some(entries[idx].0.message_id.clone());
    }

    // Compute the description column width based on the rendered area
    // so we wrap nicely. Subtract borders, the >> indent, and the
    // description prefix (" ↳ ").
    let inner_width = area.width.saturating_sub(2) as usize;
    let desc_indent = "    ↳ ";
    let desc_max = inner_width.saturating_sub(3 + desc_indent.chars().count());

    // Parallel to `items` below: per-row icon positions so we can
    // overlay real PNG icons on top of Unicode glyphs after the list
    // renders (Phase 2 graphics-protocol path). Vec is empty for rows
    // with unparsed ranks; up to 2 entries when the range spans two
    // different tiers (e.g., "Plat - Diamond").
    //
    // (column_offset_within_inner_area, tier_to_render)
    let mut row_icons: Vec<Vec<(u16, lfg_parse::Tier)>> =
        Vec::with_capacity(entries.len());

    let items: Vec<ListItem> = entries
        .iter()
        .enumerate()
        .map(|(entry_idx, (msg, parsed))| {
            // Role-aware match: check our rank for each role the LFG
            // wants (or all 3 if it didn't specify). See ActiveRanks::matches.
            let (marker, row_style) = match my_ranks.matches(parsed) {
                MatchKind::Match => ("★ ", Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)),
                MatchKind::Mismatch => ("✗ ", Style::default().fg(Color::DarkGray)),
                MatchKind::Unknown => ("· ", Style::default().fg(Color::White)),
            };

            // Author column.
            let author_padded = pad_or_truncate(&msg.author, 18);

            // Voice channel name (e.g. "NA-1 • 7"). The field name comes
            // from Discord embeds with an emoji prefix like
            // "🔊 Voice Channel"; substring-match (case-insensitive) so
            // the emoji doesn't matter.
            // Strip any Discord mention markup the userscript may have
            // forwarded (defense-in-depth; userscript already calls
            // resolveMentions before posting). Without this, raw
            // `<#channel_id>` or `<:emoji:id>` syntax leaks into the
            // narrow VC column and overflows it with junk.
            let vc_name_raw = msg
                .fields
                .iter()
                .find(|f| f.name.to_lowercase().contains("voice channel"))
                .map(|f| f.value.clone())
                .unwrap_or_else(|| "?".to_string());
            let vc_name = strip_discord_mentions(&vc_name_raw);
            let vc_padded = pad_or_truncate(&vc_name, 11);
            let vc_style = if msg.voice_channel_full() {
                Style::default().fg(Color::Red)
            } else {
                // Color VC region differently so NA-1 vs NA-2 vs EU
                // groups stand apart at a glance.
                let vc_color = vc_region_color(&vc_name);
                row_style.fg(vc_color).add_modifier(Modifier::DIM)
            };

            // Capacity column ("5/5" or "?/?").
            let cap_str = match (msg.voice_channel_users, msg.voice_channel_capacity) {
                (Some(cur), Some(cap)) => format!("{}/{}", cur, cap),
                (Some(cur), None) => format!("{}/?", cur),
                (None, Some(cap)) => format!("?/{}", cap),
                _ => "?/?".to_string(),
            };
            let cap_padded = pad_or_truncate(&cap_str, 5);

            // Rank range column. Three layouts depending on what we
            // have parsed:
            //   - Single rank or same-tier range: `[g] Pl3` / `[g] Pl3 - Pl5`
            //   - Cross-tier range: `[g1] Pl3 - [g2] Di5`
            //   - Unparsed: bare `?`
            //
            // The cross-tier case is what users care about most --
            // "Plat-Diamond LFG" should clearly show Platinum AND
            // Diamond icons, not just one. Most LFG posts in
            // Diamond-and-up brackets straddle tier boundaries.
            //
            // Phase 2 PNG overlay reads `tier_icons_in_rank` to
            // overlay the actual rank PNGs on top of the Unicode
            // glyphs at the recorded column positions. Multi-tier
            // ranges therefore get TWO PNGs side-by-side.
            //
            // Width budget is 18 cells (was 14) to fit both glyphs
            // for cross-tier ranges. Single-tier rows get padded with
            // trailing spaces so the column edges line up.
            const RANK_COL_WIDTH: usize = 18;
            // Column offset (within the row content) where this rank
            // field begins. Sum of preceding spans:
            //   marker(2) + author(18) + " "(1) + vc(11) + " "(1) +
            //   cap(5) + " "(1) = 39
            const RANK_COL_OFFSET: u16 = 39;

            // Build rank spans, tracking glyph column positions for
            // the PNG overlay pass below.
            let mut rank_spans: Vec<Span<'static>> = Vec::with_capacity(8);
            let mut tier_icons_in_rank: Vec<(u16, lfg_parse::Tier)> = Vec::new();
            let mut consumed: usize = 0;

            let push_glyph = |t: lfg_parse::Tier,
                              spans: &mut Vec<Span<'static>>,
                              icons: &mut Vec<(u16, lfg_parse::Tier)>,
                              consumed: &mut usize,
                              row_style: Style| {
                let (r, g, b) = t.color_rgb();
                let glyph_style = row_style.fg(Color::Rgb(r, g, b));
                let col = RANK_COL_OFFSET + *consumed as u16;
                icons.push((col, t));
                spans.push(Span::styled(t.glyph(), glyph_style));
                spans.push(Span::raw(" "));
                *consumed += 2; // glyph + trailing space
            };

            match (parsed.rank_min, parsed.rank_max) {
                (Some(min), Some(max)) if min.tier == max.tier => {
                    // Same-tier: one icon, then "Pl3" or "Pl3 - Pl5".
                    push_glyph(min.tier, &mut rank_spans, &mut tier_icons_in_rank, &mut consumed, row_style);
                    let text = if min == max {
                        min.label()
                    } else {
                        format!("{} - {}", min.label(), max.label())
                    };
                    let avail = RANK_COL_WIDTH.saturating_sub(consumed);
                    let text_padded = pad_or_truncate(&text, avail);
                    rank_spans.push(Span::styled(text_padded, row_style));
                }
                (Some(min), Some(max)) => {
                    // Cross-tier: `[g1] minLabel - [g2] maxLabel`
                    push_glyph(min.tier, &mut rank_spans, &mut tier_icons_in_rank, &mut consumed, row_style);
                    let min_text = min.label();
                    rank_spans.push(Span::styled(min_text.clone(), row_style));
                    consumed += min_text.chars().count();
                    rank_spans.push(Span::styled(" - ", row_style));
                    consumed += 3;
                    push_glyph(max.tier, &mut rank_spans, &mut tier_icons_in_rank, &mut consumed, row_style);
                    let max_text = max.label();
                    let avail = RANK_COL_WIDTH.saturating_sub(consumed);
                    let max_padded = pad_or_truncate(&max_text, avail);
                    rank_spans.push(Span::styled(max_padded, row_style));
                }
                (Some(only), None) | (None, Some(only)) => {
                    push_glyph(only.tier, &mut rank_spans, &mut tier_icons_in_rank, &mut consumed, row_style);
                    let avail = RANK_COL_WIDTH.saturating_sub(consumed);
                    let text_padded = pad_or_truncate(&only.label(), avail);
                    rank_spans.push(Span::styled(text_padded, row_style));
                }
                (None, None) => {
                    let text_padded = pad_or_truncate("?", RANK_COL_WIDTH);
                    rank_spans.push(Span::styled(text_padded, row_style));
                }
            }

            // Roles column. Widened to 18 chars so a 3-role + slot-count
            // entry (e.g. "1× Tank/DPS/Supp") fits without truncation.
            let roles_str = if parsed.roles_needed.is_empty() {
                if parsed.slots_open > 0 {
                    format!("{} slot(s)", parsed.slots_open)
                } else {
                    "?".to_string()
                }
            } else {
                let labels: Vec<&str> =
                    parsed.roles_needed.iter().map(|r| r.label()).collect();
                if parsed.slots_open > 0 {
                    format!("{}× {}", parsed.slots_open, labels.join("/"))
                } else {
                    labels.join("/")
                }
            };
            let roles_padded = pad_or_truncate(&roles_str, 18);

            // Age (e.g., "3m" / "12s" / "1h").
            let age_str = humanize_age_ms(now_ms.saturating_sub(msg.timestamp_ms));

            // Line 1: parsed-fields summary
            //
            // Span sequence:
            //   marker(2) + author(18) + " " + vc(11) + " " + cap(5) +
            //   " " + RANK_SPANS + " " + roles(18) + " " + age
            //
            // RANK_SPANS is built above and contains 1 or 2 colored
            // tier glyphs (with corresponding entries recorded in
            // tier_icons_in_rank for the PNG overlay pass).
            let mut line1_spans: Vec<Span> = Vec::with_capacity(16);
            line1_spans.push(Span::styled(marker, row_style));
            line1_spans.push(Span::styled(author_padded, row_style));
            line1_spans.push(Span::raw(" "));
            line1_spans.push(Span::styled(vc_padded, vc_style));
            line1_spans.push(Span::raw(" "));
            line1_spans.push(Span::styled(cap_padded, vc_style));
            line1_spans.push(Span::raw(" "));
            line1_spans.extend(rank_spans);
            line1_spans.push(Span::raw(" "));
            line1_spans.push(Span::styled(roles_padded, row_style));
            line1_spans.push(Span::raw(" "));
            line1_spans.push(Span::styled(age_str, Style::default().fg(Color::DarkGray)));
            let line1 = Line::from(line1_spans);

            // Record icon overlay positions for this row (0, 1, or 2
            // entries depending on whether the rank is single-tier,
            // missing, or spans two tiers).
            row_icons.push(tier_icons_in_rank);

            // Line 2: dimmed description so the user can read the
            // poster's own words (vibe, hero pref, queue type, age req,
            // anything the parser couldn't capture).
            //
            // When this entry has been merged with other VC-mates'
            // posts, append their distinct descriptions joined by " + "
            // so the user can see WHY the displayed range may differ
            // from the canonical poster's stated range alone. Without
            // this surfacing, the rank shown looks like a parser bug
            // ("text says 'gold to plat 2' but range is Go2-Pl2 -- why?")
            // when really it's the intersection across all stackmates.
            // Strip Discord mention markup defensively (userscript
            // already does this, but old in-flight messages may still
            // carry raw `<:Silver:127289...>` / `<#chan_id>` syntax
            // which clutters the description line until they age out).
            let raw_desc_owned = strip_discord_mentions(
                msg.description.as_deref().unwrap_or("").trim(),
            ).into_owned();
            let raw_desc = raw_desc_owned.as_str();
            let extras = entries_extra_descs.get(entry_idx).cloned().unwrap_or_default();
            let combined = if extras.is_empty() {
                if raw_desc.is_empty() {
                    "(no description)".to_string()
                } else {
                    raw_desc.to_string()
                }
            } else {
                let mut s = raw_desc.to_string();
                for e in &extras {
                    s.push_str("  +  ");
                    s.push_str(&strip_discord_mentions(e));
                }
                s
            };
            let desc_text = truncate_chars(&combined, desc_max);
            let desc_style = Style::default()
                .fg(Color::Rgb(150, 150, 160))
                .add_modifier(Modifier::ITALIC);
            let line2 = Line::from(vec![
                Span::raw(desc_indent.to_string()),
                Span::styled(desc_text, desc_style),
            ]);

            ListItem::new(vec![line1, line2])
        })
        .collect();

    // Title: framed as live-counts not error-states.
    let mut title_parts = vec![format!("{} shown", entries.len())];
    if stale_count > 0 {
        title_parts.push(format!(
            "{} hidden (>{}m)",
            stale_count,
            app.app_config.lfg_stale_threshold_secs / 60
        ));
    }
    if total_dedup > 0 {
        title_parts.push(format!("{} merged", total_dedup));
    }
    title_parts.push(format!("ranks: {}", my_ranks.label()));
    let title = format!("LFG ({})", title_parts.join(" | "));

    // Selection highlight: use a soft background color rather than
    // Modifier::REVERSED, which renders inconsistently when row spans
    // have mixed FG colors (broken-bar artifacts on terminals that
    // implement REVERSED per-span).
    let list_block = Block::default().borders(Borders::ALL).title(title);

    // Reserve 1 row inside the block for column headers so users can
    // tell what the columns mean. Layout:
    //   row 0: header (column labels in dim text)
    //   row 1+: list rows (each row is 2 terminal lines)
    //
    // Column widths must match the row builder above EXACTLY:
    //   prefix(3 highlight_symbol) + marker(2) + author(18) + 1 +
    //   vc(11) + 1 + cap(5) + 1 + RANK(18) + 1 + roles(18) + 1 + age
    //
    // Render the block first so we can position the header inside it,
    // then render the list into the remaining inner area.
    let inner = list_block.inner(area);
    let header_area = Rect { x: inner.x, y: inner.y, width: inner.width, height: 1 };
    let list_area = Rect {
        x: inner.x,
        y: inner.y + 1,
        width: inner.width,
        height: inner.height.saturating_sub(1),
    };

    f.render_widget(list_block, area);

    // Build the header row. The 3+2=5 leading spaces account for the
    // highlight_symbol gutter (always reserved by ratatui when
    // highlight_symbol is configured) PLUS the row marker (★/✗/·).
    let header_text = format!(
        "{:5}{:<18} {:<11} {:<5} {:<18} {:<18} AGE",
        "", "AUTHOR", "VC", "CAP", "RANK", "ROLES",
    );
    let header = Paragraph::new(Line::from(Span::styled(
        header_text,
        Style::default()
            .fg(Color::Rgb(120, 120, 130))
            .add_modifier(Modifier::BOLD),
    )));
    f.render_widget(header, header_area);

    let list = List::new(items)
        .highlight_style(Style::default().bg(Color::Rgb(40, 50, 80)))
        .highlight_symbol(">> ");

    f.render_stateful_widget(list, list_area, &mut app.lfg_list_state);

    // Stash the geometry so mouse handling can map clicks to row
    // indices without re-running the sort/dedup pipeline. Captured
    // AFTER render_stateful_widget so list_state.offset() reflects
    // the scroll position ratatui chose for this frame.
    {
        const ROW_HEIGHT: u16 = 2;
        // Drawable height in whole rows (truncate any partial bottom
        // row -- mouse clicks in that strip should miss).
        let drawable_rows = (list_area.height / ROW_HEIGHT) * ROW_HEIGHT;
        app.lfg_view_bounds = Some(LfgViewBounds {
            top_y: list_area.y,
            bottom_y: list_area.y + drawable_rows,
            left_x: list_area.x,
            right_x: list_area.x + list_area.width,
            offset: app.lfg_list_state.offset(),
            row_height: ROW_HEIGHT,
        });
    }

    // -------------------------------------------------------------------------
    // Phase 2: graphics-protocol icon overlay
    // -------------------------------------------------------------------------
    // After the list draws (with the Unicode glyph occupying the icon
    // cell), walk visible rows and render the actual OW rank PNG ON TOP
    // of the glyph cell. The PNG covers / replaces the glyph for users
    // whose terminal supports Kitty/Sixel/iTerm2 graphics; users on
    // Alacritty / no-graphics terminals see only the glyph.
    //
    // No-op when:
    //   - terminal lacks graphics support (rank_icons is None)
    //   - row count is 0
    if let Some(icons) = app.rank_icons.as_ref() {
        // ratatui's List shifts every row by highlight_symbol.width()
        // when ANY row is selected (unselected rows get a blank
        // padding of equal width). Our ">> " is 3 cells.
        const HIGHLIGHT_PREFIX_W: u16 = 3;
        // Two-line entries -- one row in the list = 2 terminal rows.
        const ROW_HEIGHT: u16 = 2;

        // List rows live inside the block's inner area, BELOW the
        // 1-row column header. So the first row's first terminal line
        // is at `area.y + 1 (top border) + 1 (header) = area.y + 2`.
        let inner_y = area.y + 2;
        let inner_x = area.x + 1; // skip left border
        // Available height for list rows = total - 2 borders - 1 header.
        let inner_h = area.height.saturating_sub(3);

        let offset = app.lfg_list_state.offset();
        let max_visible = (inner_h / ROW_HEIGHT) as usize;

        let (icon_w, icon_h) = icons.cell_size();

        let buf = f.buffer_mut();
        for (visible_idx, row_idx) in (offset..)
            .take(max_visible)
            .enumerate()
            .take_while(|(_, ri)| *ri < row_icons.len())
        {
            let icon_y = inner_y + (visible_idx as u16 * ROW_HEIGHT);
            // Bail out if even the START of this row would draw past
            // the bottom of the inner area.
            if icon_y + icon_h > inner_y + inner_h {
                break;
            }
            // Each row may have 0 (no rank), 1 (single tier or
            // same-tier range), or 2 icons (cross-tier range like
            // "Plat - Diamond"). Render all of them.
            for (col_offset, tier) in &row_icons[row_idx] {
                let icon_x = inner_x + HIGHLIGHT_PREFIX_W + col_offset;
                let rect = Rect::new(icon_x, icon_y, icon_w, icon_h);
                icons.render(*tier, rect, buf);
            }
        }
    }
}

/// Pick a color for the VC name based on its region prefix, so different
/// regional shards stand apart at a glance. Falls back to a neutral
/// gray for unknown / non-region VCs.
fn vc_region_color(vc_name: &str) -> Color {
    let lower = vc_name.to_ascii_lowercase();
    if lower.starts_with("na-1") {
        Color::Rgb(140, 200, 255) // light blue
    } else if lower.starts_with("na-2") {
        Color::Rgb(200, 160, 255) // purple
    } else if lower.starts_with("na") {
        Color::Rgb(180, 180, 220) // pale lavender (other NA shard)
    } else if lower.starts_with("eu") {
        Color::Rgb(255, 200, 140) // peach
    } else if lower.starts_with("asia") || lower.starts_with("kr") || lower.starts_with("jp") {
        Color::Rgb(160, 220, 160) // pale green
    } else if lower.starts_with("oce") || lower.starts_with("au") {
        Color::Rgb(220, 200, 140) // tan
    } else {
        Color::Gray
    }
}

/// Truncate a string to at most `max_chars` display chars, adding an
/// ellipsis if cut. Treats every char as 1 column wide (good enough
/// for our LFG content which is mostly ASCII + simple emoji).
fn truncate_chars(s: &str, max_chars: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    if chars.len() <= max_chars {
        return s.to_string();
    }
    let take = max_chars.saturating_sub(1).max(1);
    let mut out: String = chars.into_iter().take(take).collect();
    out.push('…');
    out
}

/// Append one entry to the joined-VC history log. Best-effort; failures
/// surface to the caller as Err but don't block the join action itself.
///
/// File: ~/.cache/bnetswitch/joined_vcs.jsonl (one JSON object per line).
/// Format mirrors LfgMessage's identifying fields plus a wallclock timestamp.
/// Append-only is intentional: replays + audits are useful, the file
/// stays small enough at ~200 bytes/entry × maybe 10 entries/day.
fn append_joined_vc_history(msg: &lfg::LfgMessage, vc_name: &str) -> Result<()> {
    use anyhow::Context;
    use std::io::Write;

    let cache = dirs::cache_dir()
        .ok_or_else(|| anyhow::anyhow!("no cache dir"))?
        .join("bnetswitch");
    std::fs::create_dir_all(&cache).context("create cache dir")?;
    let path = cache.join("joined_vcs.jsonl");

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    let entry = serde_json::json!({
        "ts": now,
        "message_id": msg.message_id,
        "channel_id": msg.channel_id,
        "author": msg.author,
        "vc_name": vc_name,
        "description": msg.description,
        "vc_users": msg.voice_channel_users,
        "vc_capacity": msg.voice_channel_capacity,
    });

    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .with_context(|| format!("open {}", path.display()))?;
    writeln!(f, "{}", entry).context("write history line")?;
    Ok(())
}

/// Strip Discord mention markup that the userscript MIGHT have left in
/// embed strings. The userscript already runs `resolveMentions` on
/// fields and description before forwarding, but this is defense in
/// depth so older in-flight messages (already accepted before a
/// userscript fix shipped) don't display raw `<:Silver:127289...>`
/// or `<#1501058773...>` noise.
///
/// Mention forms handled (matches userscript's resolveMentions):
///   <#id>            -> "#unknown"   (we have no channel cache here)
///   <:name:id>       -> ":name:"     (custom emoji shortcode)
///   <a:name:id>      -> ":name:"     (animated emoji)
///   <@id> / <@!id>   -> "@user"
///   <@&id>           -> "@role"
///
/// The userscript path produces nicer output (real channel/user names
/// when cached); this is just a safety net for stragglers.
fn strip_discord_mentions(s: &str) -> std::borrow::Cow<'_, str> {
    // Cheap fast-path: most strings have no mentions.
    if !s.contains('<') {
        return std::borrow::Cow::Borrowed(s);
    }
    let bytes = s.as_bytes();
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'<' {
            // Find matching '>' within a reasonable bound (Discord
            // mentions are < 80 chars; cap to prevent pathological
            // scans on stray '<').
            let end_search = (i + 80).min(bytes.len());
            if let Some(rel_end) = bytes[i + 1..end_search].iter().position(|&b| b == b'>') {
                let end = i + 1 + rel_end;
                // Slice only the inside of <...>, classify, replace.
                let inner = &s[i + 1..end];
                let replacement = classify_mention(inner);
                if let Some(repl) = replacement {
                    out.push_str(repl.as_ref());
                    i = end + 1;
                    continue;
                }
            }
        }
        // Not a recognized mention: copy byte. We're cutting on byte
        // boundaries here, but '<' and '>' are ASCII so this is safe
        // even for multi-byte UTF-8 codepoints (continuation bytes
        // never match either delimiter).
        out.push(bytes[i] as char);
        i += 1;
    }
    std::borrow::Cow::Owned(out)
}

/// Helper for `strip_discord_mentions`: given the inside of `<...>`,
/// return the replacement text (or None if it's not a recognized
/// mention and the original `<...>` should be kept).
fn classify_mention(inner: &str) -> Option<std::borrow::Cow<'static, str>> {
    use std::borrow::Cow;
    if inner.is_empty() { return None; }
    let bytes = inner.as_bytes();
    match bytes[0] {
        b'#' => {
            // <#channel_id> -- inner is "#\d+"
            if bytes[1..].iter().all(|b| b.is_ascii_digit()) && bytes.len() > 1 {
                return Some(Cow::Borrowed("#unknown"));
            }
        }
        b'@' => {
            // <@id>, <@!id>, <@&id>
            let rest = if bytes.len() > 1 && (bytes[1] == b'!' || bytes[1] == b'&') {
                let kind = bytes[1];
                let tail = &bytes[2..];
                if !tail.is_empty() && tail.iter().all(|b| b.is_ascii_digit()) {
                    return Some(Cow::Borrowed(if kind == b'&' { "@role" } else { "@user" }));
                }
                return None;
            } else {
                &bytes[1..]
            };
            if !rest.is_empty() && rest.iter().all(|b| b.is_ascii_digit()) {
                return Some(Cow::Borrowed("@user"));
            }
        }
        b'a' | b':' => {
            // <:name:id> or <a:name:id>
            let after_a = if bytes[0] == b'a' {
                if bytes.len() < 2 || bytes[1] != b':' { return None; }
                &inner[2..]
            } else {
                &inner[1..]
            };
            if let Some(colon) = after_a.find(':') {
                let name = &after_a[..colon];
                let id = &after_a[colon + 1..];
                let name_ok = !name.is_empty()
                    && name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_');
                let id_ok = !id.is_empty() && id.bytes().all(|b| b.is_ascii_digit());
                if name_ok && id_ok {
                    return Some(Cow::Owned(format!(":{}:", name)));
                }
            }
        }
        _ => {}
    }
    None
}

/// Format a duration in ms as a compact "Xs" / "Xm" / "Xh" string.
fn humanize_age_ms(ms: u64) -> String {
    let secs = ms / 1000;
    if secs < 60 {
        format!("  {}s", secs)
    } else if secs < 3600 {
        format!("  {}m", secs / 60)
    } else if secs < 86400 {
        format!("  {}h", secs / 3600)
    } else {
        format!("  {}d", secs / 86400)
    }
}

/// Helper to create a centered rectangle for popups.
fn centered_rect(percent_x: u16, percent_y: u16, area: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(area);

    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}

#[cfg(test)]
mod tests {
    use super::*;
    use lfg::LfgMessage;
    use lfg_parse::ParsedLfg;

    /// Build a minimal LfgMessage for sort-key testing. We only care
    /// about timestamp_ms and the VC count fields here; everything else
    /// gets filler values.
    fn msg(ts: u64, users: Option<u32>, capacity: Option<u32>) -> LfgMessage {
        LfgMessage {
            message_id: format!("m-{}", ts),
            channel_id: "c".into(),
            channel_name: "lfg".into(),
            author: format!("a-{}", ts),
            title: None,
            description: Some(String::new()),
            fields: Vec::new(),
            timestamp_ms: ts,
            voice_channel_users: users,
            voice_channel_capacity: capacity,
            voice_channel_id: None,
            voice_channel_url: None,
            guild_id: None,
        }
    }

    /// `lfg_sort_key` ordering invariants. THIS IS LOAD-BEARING -- both
    /// the renderer and j/k navigation derive their order from this
    /// function. Drift between them is exactly the cursor-jumping bug
    /// we refactored to fix.
    #[test]
    fn full_vcs_sink_below_joinable_regardless_of_compat() {
        let parsed = ParsedLfg::default(); // no rank_min/max -> Unknown for any ranks
        let my = ActiveRanks::default();   // no ranks -> Unknown match
        let full   = msg(1000, Some(5), Some(5));
        let open   = msg(500,  Some(2), Some(5));   // older but joinable
        let unknown= msg(2000, None,    None);      // newest, capacity unknown
        let kf = lfg_sort_key(&full,    &parsed, &my);
        let ko = lfg_sort_key(&open,    &parsed, &my);
        let ku = lfg_sort_key(&unknown, &parsed, &my);
        // Open and unknown-capacity both sort above full, regardless of
        // the full one being newer.
        assert!(ko < kf, "joinable should rank above full: {:?} vs {:?}", ko, kf);
        assert!(ku < kf, "unknown-cap should rank above full: {:?} vs {:?}", ku, kf);
        // Among non-full, newer wins.
        assert!(ku < ko, "newer joinable should rank above older: {:?} vs {:?}", ku, ko);
    }

    #[test]
    fn freshness_breaks_ties_within_same_join_and_compat_tiers() {
        let parsed = ParsedLfg::default();
        let my = ActiveRanks::default();
        let new = msg(2000, Some(1), Some(5));
        let old = msg(1000, Some(1), Some(5));
        let kn = lfg_sort_key(&new, &parsed, &my);
        let ko = lfg_sort_key(&old, &parsed, &my);
        assert!(kn < ko, "newer should sort before older");
    }

    #[test]
    fn full_vc_capacity_at_5_5_classified_as_full() {
        let m = msg(0, Some(5), Some(5));
        assert!(m.voice_channel_full());
    }

    #[test]
    fn vc_at_4_5_not_classified_as_full() {
        let m = msg(0, Some(4), Some(5));
        assert!(!m.voice_channel_full());
    }

    #[test]
    fn unknown_capacity_not_classified_as_full() {
        let m = msg(0, Some(2), None);
        assert!(!m.voice_channel_full());
        let m2 = msg(0, None, Some(5));
        assert!(!m2.voice_channel_full());
    }
}
