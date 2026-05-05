//! LFG (Looking For Group) bridge.
//!
//! Bridges the Overwatch Discord's `#lfg-pc-na-ranked` channel into
//! bnetswitch's TUI via a Tampermonkey userscript that posts message
//! events to a localhost HTTP server hosted by this module.
//!
//! ## Why a userscript instead of a Discord bot or selfbot?
//!
//! - **Bot**: can't be added to the OW Discord (we don't control it).
//! - **Selfbot** (`discord.py-self`): TOS-violating, actively detected
//!   by Discord in 2024-2025, AND would kick our real Discord client
//!   out of voice (single voice session per account). We need our real
//!   client connected to actually talk in the VC after joining.
//! - **Userscript** (Tampermonkey in Discord web): runs in our real
//!   authenticated session, drives DOM clicks the same way a human
//!   would. Voice flows through our real client normally. Lower
//!   detection rate. Still TOS-questionable but practically the only
//!   workable architecture.
//!
//! ## Architecture
//!
//! ```text
//! [Discord web]
//!     │ DOM mutations
//!     ▼
//! [Tampermonkey userscript]
//!     │ HTTP POST localhost:7172/lfg/message
//!     ▼
//! [this module: LfgServer]
//!     │ store + parse + match against active account
//!     ▼
//! [TUI LFG panel]
//!     │ user selects a group
//!     ▼
//! [this module: LfgServer pushes action to queue]
//!     │ HTTP GET localhost:7172/actions  (long-poll)
//!     ▼
//! [userscript pops action, executes DOM click]
//!     ▼
//! [Discord web's `[Join Voice]` button clicked → real client joins]
//! ```
//!
//! ## Endpoints
//!
//! All Bearer-token authenticated (token from `LFG_AUTH_TOKEN` constant
//! below; user picked "no auth" via hardcoded shared value, so this is
//! a constant rather than per-install secret).
//!
//! - `POST /lfg/message` — userscript posts a new LFG embed
//! - `POST /lfg/remove`  — userscript notifies that an embed was deleted
//! - `GET /lfg/active`   — TUI / userscript reads current active LFGs
//! - `GET /actions`      — userscript long-polls for actions to execute
//! - `POST /actions/ack` — userscript reports completion
//! - `POST /status`      — userscript reports voice/account state
//! - `GET /health`       — sanity check

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tiny_http::{Method, Response, Server, StatusCode};

/// Per-process random ID exposed via `/health` so the userscript can
/// detect bnetswitch restarts and re-trigger LFG history backfill.
/// Initialized lazily on first /health request.
fn process_boot_id() -> &'static str {
    static BOOT_ID: OnceLock<String> = OnceLock::new();
    BOOT_ID.get_or_init(|| {
        // Combine the process start nanoseconds with PID for cheap
        // uniqueness without pulling in a UUID dep.
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        format!("{:x}-{:x}", nanos, std::process::id())
    })
}

/// Localhost-only port. Pick something out of the way of common dev tools.
pub const LFG_PORT: u16 = 7172;

/// Hardcoded shared secret. Localhost-only API; `no_auth` per user choice.
/// Userscript sends this in `Authorization: Bearer <token>`. Constant
/// rather than generated so the userscript doesn't need a setup step.
///
/// Any local process running as the user could already access bnetswitch's
/// other state, so adding per-install token generation buys us nothing.
pub const LFG_AUTH_TOKEN: &str = "bnetswitch-lfg-localhost-only-do-not-expose";

/// Maximum LFG messages to keep in memory. Once exceeded, oldest are
/// evicted. The OW LFG channel can produce ~1 message/minute; 256 covers
/// ~4 hours of history which is plenty.
const MAX_LFG_HISTORY: usize = 256;

/// How long an action waits in the queue before being considered stale.
#[allow(dead_code)] // used once TUI panel enqueues actions
const ACTION_TTL_SECS: u64 = 60;

// ============================================================================
// Wire types
// ============================================================================

/// One LFG message as observed by the userscript. Mirrors the embed
/// fields we can extract from Discord's DOM. Fields are intentionally
/// loose (mostly Option<String>) because the Discord LFG bot's embed
/// schema can change without notice; we'd rather store partial data
/// than reject parsing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LfgMessage {
    /// Discord message snowflake (unique per message). Used as the
    /// canonical identifier for join actions and removals.
    pub message_id: String,
    /// Channel ID the embed was posted in.
    pub channel_id: String,
    /// Display name of the channel (e.g., "lfg-pc-na-ranked").
    pub channel_name: String,
    /// Discord username of the LFG poster (the leader). May be the
    /// bot's username if the LFG bot reposted; embed.author often
    /// has the real user.
    pub author: String,
    /// Free-form embed title (e.g., "Looking for tank + support").
    #[serde(default)]
    pub title: Option<String>,
    /// Embed description (may contain rank, region, role hints).
    #[serde(default)]
    pub description: Option<String>,
    /// Structured embed fields, name -> value. The OW LFG bot typically
    /// emits fields like "Rank", "Roles", "Region", "Voice Required".
    #[serde(default)]
    pub fields: Vec<EmbedField>,
    /// Unix epoch ms when the message was posted (or observed).
    pub timestamp_ms: u64,
    /// Current user count of the linked voice channel, when the
    /// channel is visible in Discord's sidebar. None when the channel
    /// is virtualized (scrolled out / collapsed) and we can't read it
    /// without disrupting the user's UI.
    #[serde(default)]
    pub voice_channel_users: Option<u32>,
    /// Maximum capacity of the linked voice channel (e.g., 5 for OW
    /// stack VCs). None when virtualized.
    #[serde(default)]
    pub voice_channel_capacity: Option<u32>,
    /// Discord channel ID of the linked voice channel, derived from
    /// the Join Voice button's URL when possible (canonical), falling
    /// back to a sidebar-cache lookup by name (best-effort).
    #[serde(default)]
    pub voice_channel_id: Option<String>,
    /// Full Discord URL the Join Voice button links to, extracted from
    /// the button's React fiber at parse time. Format:
    /// `https://discord.com/channels/<guild_id>/<voice_channel_id>`.
    ///
    /// CANONICAL JOIN TARGET: this is the cleanest join path. We just
    /// navigate the userscript to this URL via SPA routing and Discord
    /// handles the rest. Doesn't depend on:
    ///   - The original message being in the DOM (Discord virtualizes
    ///     scrolled-out messages, but our captured URL stays valid)
    ///   - Webpack store introspection
    ///   - Sidebar visibility of the VC
    #[serde(default)]
    pub voice_channel_url: Option<String>,
    /// Guild ID for the LFG message. Useful for constructing deep-link
    /// URLs and for resolving channel IDs across guilds.
    #[serde(default)]
    pub guild_id: Option<String>,
}

impl LfgMessage {
    /// True if the linked VC is at capacity (no room to join).
    /// Returns false when capacity is unknown (we don't know if it's
    /// full, so don't refuse joining on that basis).
    pub fn voice_channel_full(&self) -> bool {
        match (self.voice_channel_users, self.voice_channel_capacity) {
            (Some(cur), Some(cap)) => cur >= cap,
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbedField {
    pub name: String,
    pub value: String,
}

/// An action queued by bnetswitch for the userscript to perform on
/// the next `GET /actions` poll.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LfgAction {
    /// Unique action ID. Userscript echoes this back via `/actions/ack`
    /// so we can prune completed actions and surface failures.
    pub id: String,
    #[serde(flatten)]
    pub kind: LfgActionKind,
    /// Unix epoch seconds at which this action expires if not ack'd.
    pub expires_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum LfgActionKind {
    /// Navigate to the VC's URL captured at LFG-parse time. The
    /// userscript stores the Join Voice button's URL during embed
    /// parsing; on join, we just navigate to it via SPA routing.
    /// Doesn't require the original message to still be in the DOM.
    ///
    /// `message_id` and `channel_id` are kept for joined-VC history
    /// log + observability; they don't affect the join path.
    JoinByMessage {
        message_id: String,
        channel_id: String,
        #[serde(default)]
        guild_id: Option<String>,
        #[serde(default)]
        voice_channel_id: Option<String>,
        /// PRIMARY join target: discord.com URL extracted from button.
        /// When present, userscript navigates to this directly.
        #[serde(default)]
        voice_channel_url: Option<String>,
    },
    /// Set our nickname in the given guild (server). Userscript opens
    /// the server profile editor and submits the change.
    SetNickname {
        guild_id: String,
        nickname: String,
    },
    /// Disconnect from current voice channel. Userscript clicks the
    /// disconnect button.
    LeaveVoice,
}

/// What the userscript reports back about its / Discord's current state.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VoiceStatus {
    pub in_voice: bool,
    pub voice_channel_id: Option<String>,
    pub voice_channel_name: Option<String>,
}

/// One registered userscript instance (browser tab). Used for leader
/// election: only the most-recently-active session receives queued
/// actions, so multiple browsers / tabs don't race to execute joins.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionInfo {
    pub session_id: String,
    pub user_agent: String,
    pub registered_at: u64,
    pub last_seen_at: u64,
}

/// Sessions older than this are GC'd from the registry. A browser that
/// hasn't talked to bnetswitch in 60s is considered closed/idle.
const SESSION_STALE_MS: u64 = 60_000;

// ============================================================================
// Server state
// ============================================================================

/// Shared state between the HTTP server thread and the rest of bnetswitch.
/// Wrapped in `Arc<Mutex<>>` for cross-thread access; contention is low
/// (a few requests per minute at most) so a coarse mutex is fine.
#[derive(Default)]
pub struct LfgState {
    /// Recent LFG messages, newest first. Capped at MAX_LFG_HISTORY.
    pub messages: VecDeque<LfgMessage>,
    /// Pending actions for the userscript to execute. FIFO.
    pub action_queue: VecDeque<LfgAction>,
    /// Last-known voice status reported by userscript.
    pub voice_status: VoiceStatus,
    /// Registered userscript sessions (browsers/tabs). Used to elect
    /// the "primary" tab that receives queued actions.
    pub sessions: std::collections::HashMap<String, SessionInfo>,
}

impl LfgState {
    pub fn new() -> Self {
        Self::default()
    }

    /// Insert a new LFG message. Deduplicates by message_id (replaces
    /// existing entry rather than appending). Caps history.
    pub fn upsert_message(&mut self, msg: LfgMessage) {
        // Remove any existing entry with the same message_id.
        self.messages.retain(|m| m.message_id != msg.message_id);
        self.messages.push_front(msg);
        while self.messages.len() > MAX_LFG_HISTORY {
            self.messages.pop_back();
        }
    }

    /// Remove a message by ID (when the LFG bot deletes the embed,
    /// e.g. group filled or expired).
    pub fn remove_message(&mut self, message_id: &str) {
        self.messages.retain(|m| m.message_id != message_id);
    }

    /// Enqueue an action for the userscript to perform.
    #[allow(dead_code)] // used once TUI panel enqueues actions
    pub fn enqueue_action(&mut self, kind: LfgActionKind) -> String {
        let id = format!("act-{}", now_ms());
        let action = LfgAction {
            id: id.clone(),
            kind,
            expires_at: now_secs() + ACTION_TTL_SECS,
        };
        self.action_queue.push_back(action);
        id
    }

    /// Drain expired actions. Called opportunistically before
    /// returning the queue to the userscript.
    pub fn prune_expired_actions(&mut self) {
        let now = now_secs();
        self.action_queue.retain(|a| a.expires_at > now);
    }

    /// Register a new userscript session, or refresh an existing one.
    ///
    /// CRITICAL: `registered_at` is set ONCE when the session_id is
    /// first seen, and NEVER updated afterward. Subsequent calls with
    /// the same session_id only refresh `last_seen_at` (which is used
    /// for stale-session GC, not for leader election).
    ///
    /// This means:
    ///   - Opening a new tab/browser registers a fresh session_id and
    ///     becomes primary because it has the newest `registered_at`.
    ///   - Background polling from existing tabs DOES NOT promote them
    ///     back to primary -- so no ping-ponging while two tabs are
    ///     equally busy.
    ///   - A stale tab is dropped after SESSION_STALE_MS of silence.
    ///   - To make an older tab primary, the user reloads it (which
    ///     generates a new session_id at page-init and re-registers).
    pub fn register_session(&mut self, session_id: String, user_agent: String) {
        let now = now_ms();
        if let Some(existing) = self.sessions.get_mut(&session_id) {
            // Existing session ping; only refresh activity timestamp.
            existing.last_seen_at = now;
        } else {
            // Brand new session -- this is the "initiation" event that
            // makes it primary.
            self.sessions.insert(
                session_id.clone(),
                SessionInfo {
                    session_id,
                    user_agent,
                    registered_at: now,
                    last_seen_at: now,
                },
            );
        }
        self.gc_stale_sessions();
    }

    /// Touch an existing session's last_seen_at. No-op if unknown.
    /// Currently unused (we register-or-refresh on every request); kept
    /// for completeness in case the API gains a non-registering endpoint.
    #[allow(dead_code)]
    pub fn touch_session(&mut self, session_id: &str) {
        let now = now_ms();
        if let Some(s) = self.sessions.get_mut(session_id) {
            s.last_seen_at = now;
        }
    }

    /// Drop sessions not seen in last SESSION_STALE_MS. Called from
    /// register/touch paths so we don't accumulate dead browsers.
    fn gc_stale_sessions(&mut self) {
        let now = now_ms();
        self.sessions
            .retain(|_, s| now.saturating_sub(s.last_seen_at) < SESSION_STALE_MS);
    }

    /// Return the most-recently-INITIATED session (newest registered_at),
    /// or None if empty. Election by initiation timestamp, not activity,
    /// so equally active tabs don't ping-pong.
    pub fn primary_session(&self) -> Option<&SessionInfo> {
        self.sessions.values().max_by_key(|s| s.registered_at)
    }

    /// True if `session_id` is the elected leader. Used to gate /actions.
    pub fn is_primary(&self, session_id: &str) -> bool {
        self.primary_session()
            .map(|s| s.session_id == session_id)
            .unwrap_or(false)
    }
}

/// Handle to the running LFG server. Holds the shared state so other
/// modules (TUI, switcher) can read messages and enqueue actions.
///
/// `#[allow(dead_code)]` until Phase 4 wires this into `main.rs` —
/// during incremental build the type and methods are referenced only
/// from tests, which doesn't satisfy the unused-code lint.
#[allow(dead_code)]
pub struct LfgServer {
    pub state: Arc<Mutex<LfgState>>,
    /// Joined when bnetswitch exits; not used in normal flow because
    /// the server runs forever.
    _server_thread: thread::JoinHandle<()>,
}

impl LfgServer {
    /// Start the HTTP server in a background thread. Returns immediately;
    /// the server runs until the process exits. If the port is already
    /// in use (e.g., another bnetswitch instance), returns an error and
    /// LFG features stay disabled — TUI continues to work.
    pub fn start() -> Result<Self> {
        let state = Arc::new(Mutex::new(LfgState::new()));
        let bind = format!("127.0.0.1:{}", LFG_PORT);

        let server = Server::http(&bind)
            .map_err(|e| anyhow::anyhow!("LFG server bind failed on {}: {}", bind, e))?;

        let state_for_thread = state.clone();
        let handle = thread::Builder::new()
            .name("lfg-http".into())
            .spawn(move || {
                serve_loop(server, state_for_thread);
            })
            .context("failed to spawn LFG HTTP server thread")?;

        Ok(Self {
            state,
            _server_thread: handle,
        })
    }
}

// ============================================================================
// Request loop
// ============================================================================

fn serve_loop(server: Server, state: Arc<Mutex<LfgState>>) {
    for request in server.incoming_requests() {
        // Each request is processed inline. tiny_http spawns one thread
        // per accepted connection internally so we don't block on slow
        // clients. For a localhost loopback API with one client this is
        // overkill but free.
        if let Err(e) = handle_request(request, &state) {
            eprintln!("[lfg] request handling error: {}", e);
        }
    }
}

/// Dispatch a single request to the appropriate handler.
fn handle_request(
    mut request: tiny_http::Request,
    state: &Arc<Mutex<LfgState>>,
) -> Result<()> {
    // ---- auth gate ----
    // Public endpoints (no auth required) are listed here. /userscript
    // is public because Tampermonkey's update-check fetch can't supply
    // custom headers; localhost-only is its actual security boundary.
    let is_public_endpoint = matches!(
        (request.method(), request.url()),
        (Method::Get, "/userscript")
            | (Method::Get, "/userscript.user.js")
            | (Method::Get, "/bnetswitch-lfg.user.js")
            | (Method::Get, "/loader")
            | (Method::Get, "/loader.user.js")
            | (Method::Get, "/bnetswitch-lfg-loader.user.js")
    );
    if !is_public_endpoint && !is_authorized(&request) {
        respond(request, 401, r#"{"error":"missing or bad bearer token"}"#)?;
        return Ok(());
    }

    // Register / refresh session on every authenticated request that
    // carries X-Bnet-Session. Saves an explicit /register handshake
    // and naturally rotates "primary" to whoever's most active.
    if let Some(sid) = request_session_id(&request) {
        let ua = request_user_agent(&request);
        state.lock().unwrap().register_session(sid, ua);
    }

    let url = request.url().to_string();
    let method = request.method().clone();

    match (method, url.as_str()) {
        (Method::Get, "/health") => {
            // Include a boot_id so the userscript can detect bnetswitch
            // restarts and re-trigger the LFG history backfill. The id
            // is generated once per process via OnceLock.
            let boot_id = process_boot_id();
            let body = format!(r#"{{"ok":true,"boot_id":"{}"}}"#, boot_id);
            respond(request, 200, &body)?;
        }
        (Method::Get, "/userscript")
        | (Method::Get, "/userscript.user.js")
        | (Method::Get, "/bnetswitch-lfg.user.js") => {
            // Serve the main userscript code. Two install paths:
            //
            //   1) Direct install (legacy):  user installs this in TM, TM
            //      runs the auto-update check on its own (~daily) cadence.
            //   2) Via loader (preferred): the loader userscript fetches
            //      this URL on every page load, caches via GM_setValue,
            //      eval's at document-start. No TM update prompts ever.
            //
            // Auth gate BYPASSED -- TM update-check fetches can't supply
            // headers; the loader uses GM_xmlhttpRequest which also can't
            // realistically supply custom auth without leaking the token.
            // Localhost-only binding is the security boundary.
            return serve_userscript(request, "bnetswitch-lfg.user.js");
        }
        (Method::Get, "/loader")
        | (Method::Get, "/loader.user.js")
        | (Method::Get, "/bnetswitch-lfg-loader.user.js") => {
            // Tiny loader script: install once in Tampermonkey, then
            // never touch it again. It auto-fetches the main script
            // on every page load and caches it across sessions.
            //
            // The loader's @updateURL points at this same endpoint, so
            // even the loader self-updates -- though the loader changes
            // very rarely (it's ~280 lines of pure plumbing).
            return serve_userscript(request, "bnetswitch-lfg-loader.user.js");
        }
        (Method::Post, "/lfg/message") => {
            let body = read_body(&mut request)?;
            let msg: LfgMessage = serde_json::from_str(&body)
                .map_err(|e| anyhow::anyhow!("bad message body: {}", e))?;
            state.lock().unwrap().upsert_message(msg);
            respond(request, 202, r#"{"ok":true}"#)?;
        }
        (Method::Post, "/lfg/remove") => {
            let body = read_body(&mut request)?;
            #[derive(Deserialize)]
            struct R {
                message_id: String,
            }
            let r: R = serde_json::from_str(&body)
                .map_err(|e| anyhow::anyhow!("bad remove body: {}", e))?;
            state.lock().unwrap().remove_message(&r.message_id);
            respond(request, 200, r#"{"ok":true}"#)?;
        }
        (Method::Get, "/lfg/active") => {
            let s = state.lock().unwrap();
            let body = serde_json::to_string(&s.messages)?;
            respond(request, 200, &body)?;
        }
        (Method::Get, "/actions") => {
            // Multi-browser leader election: the most recently active
            // userscript session is the "primary" tab and it alone
            // receives queued actions. Other tabs get an empty array.
            //
            // If no sessions are registered (older userscript without
            // the X-Bnet-Session header), fall back to first-poller-
            // wins so the system still works for single-browser use.
            let session_id = request_session_id(&request);
            let mut s = state.lock().unwrap();
            s.prune_expired_actions();
            let allow_drain = if s.sessions.is_empty() {
                true
            } else {
                session_id.as_deref().map(|sid| s.is_primary(sid)).unwrap_or(false)
            };
            let actions: Vec<_> = if allow_drain {
                s.action_queue.drain(..).collect()
            } else {
                Vec::new()
            };
            let body = serde_json::to_string(&actions)?;
            respond(request, 200, &body)?;
        }
        (Method::Post, "/register") => {
            // Userscript announces itself on boot + at intervals so we
            // can elect the most-recently-active browser as primary.
            let body = read_body(&mut request)?;
            #[derive(Deserialize)]
            struct Reg {
                session_id: String,
                #[serde(default)]
                user_agent: String,
            }
            let reg: Reg = serde_json::from_str(&body)?;
            let mut s = state.lock().unwrap();
            s.register_session(reg.session_id.clone(), reg.user_agent);
            let primary_id = s.primary_session().map(|p| p.session_id.clone());
            let count = s.sessions.len();
            drop(s);
            let body = format!(
                r#"{{"ok":true,"is_primary":{},"session_count":{}}}"#,
                primary_id.as_deref() == Some(reg.session_id.as_str()),
                count
            );
            respond(request, 200, &body)?;
        }
        (Method::Post, "/actions/ack") => {
            let body = read_body(&mut request)?;
            #[derive(Deserialize)]
            struct Ack {
                id: String,
                success: bool,
                #[serde(default)]
                error: Option<String>,
            }
            let ack: Ack = serde_json::from_str(&body)?;
            if !ack.success {
                eprintln!(
                    "[lfg] action {} failed: {}",
                    ack.id,
                    ack.error.unwrap_or_default()
                );
            }
            respond(request, 200, r#"{"ok":true}"#)?;
        }
        (Method::Post, "/status") => {
            let body = read_body(&mut request)?;
            let status: VoiceStatus = serde_json::from_str(&body)?;
            state.lock().unwrap().voice_status = status;
            respond(request, 200, r#"{"ok":true}"#)?;
        }
        (Method::Post, "/voice/deleted") => {
            // Voice channel was deleted on Discord (CHANNEL_DELETE
            // gateway event). For LFG groups this almost always means
            // "group disbanded" -- Discord auto-cleans empty VCs after
            // the LFG bot's lifecycle ends. The associated LFG
            // messages are no longer joinable; drop them from state
            // so the TUI doesn't show stale rows for VCs that don't
            // exist anymore.
            //
            // We also remove any voice_channel_users counts that the
            // userscript already pushed; without this, a user could
            // see "5/5" forever for a VC that no longer exists.
            let body = read_body(&mut request)?;
            #[derive(Deserialize)]
            struct VoiceDeleted { channel_id: String }
            let upd: VoiceDeleted = serde_json::from_str(&body)?;
            let mut s = state.lock().unwrap();
            let before = s.messages.len();
            s.messages.retain(|m| {
                m.voice_channel_id.as_deref() != Some(&upd.channel_id)
            });
            let removed = before - s.messages.len();
            let body = format!(r#"{{"ok":true,"removed":{}}}"#, removed);
            respond(request, 200, &body)?;
        }
        (Method::Post, "/voice/state") => {
            // Real-time VC member-count updates streamed from the
            // userscript's gateway tap. Keeps `voice_channel_users` /
            // `voice_channel_capacity` on every LFG message that
            // references this channel synced with live joins/leaves.
            //
            // Userscript pushes one of these per VOICE_STATE_UPDATE
            // gateway event (filtered to channels we have outstanding
            // LFG messages for, to keep traffic minimal).
            let body = read_body(&mut request)?;
            #[derive(Deserialize)]
            struct VoiceUpdate {
                channel_id: String,
                #[serde(default)]
                users: Option<u32>,
                #[serde(default)]
                capacity: Option<u32>,
            }
            let upd: VoiceUpdate = serde_json::from_str(&body)?;
            let mut s = state.lock().unwrap();
            let mut updated = 0;
            for msg in s.messages.iter_mut() {
                if msg.voice_channel_id.as_deref() == Some(&upd.channel_id) {
                    msg.voice_channel_users = upd.users;
                    if upd.capacity.is_some() {
                        msg.voice_channel_capacity = upd.capacity;
                    }
                    updated += 1;
                }
            }
            let body = format!(r#"{{"ok":true,"updated":{}}}"#, updated);
            respond(request, 200, &body)?;
        }
        (Method::Options, _) => {
            // CORS preflight from the userscript (tiny_http doesn't set
            // CORS headers automatically). Allow everything localhost.
            cors_respond(request, 204, "")?;
        }
        _ => {
            respond(request, 404, r#"{"error":"not found"}"#)?;
        }
    }
    Ok(())
}

fn is_authorized(req: &tiny_http::Request) -> bool {
    req.headers().iter().any(|h| {
        h.field.as_str().as_str().eq_ignore_ascii_case("authorization")
            && h.value.as_str() == format!("Bearer {}", LFG_AUTH_TOKEN)
    })
}

/// Extract the X-Bnet-Session header (userscript instance ID).
fn request_session_id(req: &tiny_http::Request) -> Option<String> {
    req.headers().iter().find_map(|h| {
        if h.field.as_str().as_str().eq_ignore_ascii_case("x-bnet-session") {
            Some(h.value.as_str().to_string())
        } else {
            None
        }
    })
}

fn request_user_agent(req: &tiny_http::Request) -> String {
    req.headers()
        .iter()
        .find(|h| h.field.as_str().as_str().eq_ignore_ascii_case("user-agent"))
        .map(|h| h.value.as_str().to_string())
        .unwrap_or_default()
}

fn read_body(req: &mut tiny_http::Request) -> Result<String> {
    // tiny_http's Request::as_reader returns a concrete type with its own
    // read_to_string -- no need to bring std::io::Read into scope.
    let mut buf = String::new();
    std::io::Read::read_to_string(req.as_reader(), &mut buf)
        .context("read request body")?;
    Ok(buf)
}

/// Locate the userscript file on disk and return it with proper
/// JavaScript content-type. Tries several candidate paths to handle
/// both development (run from source tree) and deployed (binary symlinked
/// into ~/.local/bin) usage.
fn serve_userscript(request: tiny_http::Request, filename: &str) -> Result<()> {
    let candidates = [
        // When running from the bnetswitch source tree directly:
        //   target/release/bnetswitch -> userscripts/<filename>
        // is at "../userscripts/<filename>" relative to the bnetswitch
        // crate root.
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(|p| p.join("userscripts").join(filename))
            .unwrap_or_default(),
        // Fallback: hard-coded user-home location for the symlinked binary.
        dirs::home_dir()
            .map(|h| h.join("src/neo-mittens/userscripts").join(filename))
            .unwrap_or_default(),
    ];

    for path in &candidates {
        if let Ok(content) = std::fs::read_to_string(path) {
            let response = Response::from_string(content)
                .with_status_code(StatusCode(200))
                .with_header(
                    tiny_http::Header::from_bytes(
                        "Content-Type",
                        "application/javascript; charset=utf-8",
                    )
                    .unwrap(),
                )
                // Tampermonkey checks Content-Type to recognize userscripts.
                // Also expose CORS so other tools can fetch it.
                .with_header(
                    tiny_http::Header::from_bytes("Access-Control-Allow-Origin", "*").unwrap(),
                )
                // Disable caching so Tampermonkey always sees fresh content.
                .with_header(
                    tiny_http::Header::from_bytes(
                        "Cache-Control",
                        "no-store, no-cache, must-revalidate",
                    )
                    .unwrap(),
                );
            request
                .respond(response)
                .context("respond /userscript")?;
            return Ok(());
        }
    }

    let response = Response::from_string(r#"{"error":"userscript file not found on disk"}"#)
        .with_status_code(StatusCode(404))
        .with_header(
            tiny_http::Header::from_bytes("Content-Type", "application/json").unwrap(),
        );
    request.respond(response).context("respond 404")?;
    Ok(())
}

#[allow(dead_code)]  // referenced by handle_request, false-positive without main wire-in
fn respond(req: tiny_http::Request, code: u16, body: &str) -> Result<()> {
    let response = Response::from_string(body)
        .with_status_code(StatusCode(code))
        .with_header(
            tiny_http::Header::from_bytes("Content-Type", "application/json").unwrap(),
        )
        // CORS: userscript runs in discord.com origin; we need to allow it.
        .with_header(
            tiny_http::Header::from_bytes("Access-Control-Allow-Origin", "*").unwrap(),
        )
        .with_header(
            tiny_http::Header::from_bytes(
                "Access-Control-Allow-Headers",
                "authorization, content-type",
            )
            .unwrap(),
        )
        .with_header(
            tiny_http::Header::from_bytes(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS",
            )
            .unwrap(),
        );
    req.respond(response).context("respond")?;
    Ok(())
}

#[allow(dead_code)]
fn cors_respond(req: tiny_http::Request, code: u16, body: &str) -> Result<()> {
    respond(req, code, body)
}

// ============================================================================
// Helpers
// ============================================================================

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

#[allow(dead_code)]
fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[allow(dead_code)] // used by tests + future TUI integration
fn duration_since_ms(epoch_ms: u64) -> Duration {
    let now = now_ms();
    if epoch_ms > now {
        Duration::ZERO
    } else {
        Duration::from_millis(now - epoch_ms)
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_msg(id: &str) -> LfgMessage {
        LfgMessage {
            message_id: id.into(),
            channel_id: "1234".into(),
            channel_name: "lfg-pc-na-ranked".into(),
            author: "tester".into(),
            title: Some("LF tank".into()),
            description: None,
            fields: vec![],
            timestamp_ms: now_ms(),
            voice_channel_users: None,
            voice_channel_capacity: None,
            voice_channel_id: None,
            voice_channel_url: None,
            guild_id: None,
        }
    }

    #[test]
    fn upsert_dedupes_by_message_id() {
        let mut s = LfgState::new();
        s.upsert_message(dummy_msg("a"));
        s.upsert_message(dummy_msg("a"));
        assert_eq!(s.messages.len(), 1);
    }

    #[test]
    fn upsert_caps_history() {
        let mut s = LfgState::new();
        for i in 0..(MAX_LFG_HISTORY + 10) {
            s.upsert_message(dummy_msg(&format!("m{}", i)));
        }
        assert_eq!(s.messages.len(), MAX_LFG_HISTORY);
    }

    #[test]
    fn enqueue_action_returns_id() {
        let mut s = LfgState::new();
        let id = s.enqueue_action(LfgActionKind::LeaveVoice);
        assert!(id.starts_with("act-"));
        assert_eq!(s.action_queue.len(), 1);
    }

    #[test]
    fn prune_drops_expired() {
        let mut s = LfgState::new();
        s.action_queue.push_back(LfgAction {
            id: "old".into(),
            kind: LfgActionKind::LeaveVoice,
            expires_at: 0, // already expired
        });
        s.prune_expired_actions();
        assert!(s.action_queue.is_empty());
    }

    #[test]
    fn remove_message_drops_one() {
        let mut s = LfgState::new();
        s.upsert_message(dummy_msg("a"));
        s.upsert_message(dummy_msg("b"));
        s.remove_message("a");
        assert_eq!(s.messages.len(), 1);
        assert_eq!(s.messages[0].message_id, "b");
    }
}
