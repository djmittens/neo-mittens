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
use axum::{
    extract::{Query, State},
    http::{HeaderMap, Method, StatusCode},
    response::{
        sse::{Event, Sse},
        IntoResponse, Response,
    },
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::convert::Infallible;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::broadcast;
use tower_http::cors::{Any, CorsLayer};

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

// ============================================================================
// Axum app state
// ============================================================================

/// Shared state passed to all axum handlers via State extractor.
#[derive(Clone)]
struct AppState {
    lfg: Arc<Mutex<LfgState>>,
    notify_tx: broadcast::Sender<()>,
}

/// Handle to the running LFG server. Holds the shared state so other
/// modules (TUI, switcher) can read messages and enqueue actions.
pub struct LfgServer {
    pub state: Arc<Mutex<LfgState>>,
    pub notify_tx: broadcast::Sender<()>,
    _runtime: tokio::runtime::Runtime,
}

impl LfgServer {
    /// Start the HTTP server in a background tokio runtime. Returns
    /// immediately; the server runs until the process exits. If the
    /// port is already in use (e.g., another bnetswitch instance),
    /// returns an error and LFG features stay disabled — TUI continues
    /// to work.
    pub fn start() -> Result<Self> {
        let state = Arc::new(Mutex::new(LfgState::new()));
        let (notify_tx, _) = broadcast::channel::<()>(16);

        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .thread_name("lfg-tokio")
            .build()
            .context("failed to build tokio runtime for LFG server")?;

        let app_state = AppState {
            lfg: state.clone(),
            notify_tx: notify_tx.clone(),
        };

        // Try to bind before spawning, so we can report port-in-use immediately.
        let listener = runtime.block_on(async {
            tokio::net::TcpListener::bind(format!("127.0.0.1:{}", LFG_PORT)).await
        })
        .map_err(|e| anyhow::anyhow!("LFG server bind failed on 127.0.0.1:{}: {}", LFG_PORT, e))?;

        let router = build_router(app_state);

        runtime.spawn(async move {
            axum::serve(listener, router).await.ok();
        });

        Ok(Self {
            state,
            notify_tx,
            _runtime: runtime,
        })
    }
}

// ============================================================================
// Router
// ============================================================================

fn build_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers([
            axum::http::header::AUTHORIZATION,
            axum::http::header::CONTENT_TYPE,
            axum::http::HeaderName::from_static("x-bnet-session"),
        ]);

    Router::new()
        .route("/health", get(handle_health))
        .route("/userscript", get(handle_userscript_main))
        .route("/userscript.user.js", get(handle_userscript_main))
        .route("/bnetswitch-lfg.user.js", get(handle_userscript_main))
        .route("/loader", get(handle_userscript_loader))
        .route("/loader.user.js", get(handle_userscript_loader))
        .route("/bnetswitch-lfg-loader.user.js", get(handle_userscript_loader))
        .route("/lfg/message", post(handle_lfg_message))
        .route("/lfg/remove", post(handle_lfg_remove))
        .route("/lfg/active", get(handle_lfg_active))
        .route("/actions", get(handle_actions))
        .route("/actions/ack", post(handle_actions_ack))
        .route("/register", post(handle_register))
        .route("/status", post(handle_status))
        .route("/voice/deleted", post(handle_voice_deleted))
        .route("/voice/state", post(handle_voice_state))
        .route("/events", get(handle_events))
        .layer(cors)
        .with_state(state)
}

// ============================================================================
// Auth helpers
// ============================================================================

fn is_authorized(headers: &HeaderMap) -> bool {
    headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .map(|v| v == format!("Bearer {}", LFG_AUTH_TOKEN))
        .unwrap_or(false)
}

fn extract_session_id(headers: &HeaderMap) -> Option<String> {
    headers
        .get("x-bnet-session")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string())
}

fn extract_user_agent(headers: &HeaderMap) -> String {
    headers
        .get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string()
}

/// Register session from headers if X-Bnet-Session is present.
fn maybe_register_session(state: &Arc<Mutex<LfgState>>, headers: &HeaderMap) {
    if let Some(sid) = extract_session_id(headers) {
        let ua = extract_user_agent(headers);
        state.lock().unwrap().register_session(sid, ua);
    }
}

/// JSON error response helper.
fn json_error(status: StatusCode, msg: &str) -> Response {
    (
        status,
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        format!(r#"{{"error":"{}"}}"#, msg),
    )
        .into_response()
}

/// JSON success response helper.
fn json_ok(body: &str) -> Response {
    (
        StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        body.to_string(),
    )
        .into_response()
}

// ============================================================================
// Handlers
// ============================================================================

async fn handle_health(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    // Health is accessible without auth for basic connectivity checks,
    // but we still register sessions if the header is present.
    maybe_register_session(&state.lfg, &headers);
    let boot_id = process_boot_id();
    json_ok(&format!(r#"{{"ok":true,"boot_id":"{}"}}"#, boot_id))
}

async fn handle_userscript_main() -> Response {
    serve_userscript("bnetswitch-lfg.user.js")
}

async fn handle_userscript_loader() -> Response {
    serve_userscript("bnetswitch-lfg-loader.user.js")
}

async fn handle_lfg_message(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    let msg: LfgMessage = match serde_json::from_str(&body) {
        Ok(m) => m,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad message body: {}", e)),
    };
    state.lfg.lock().unwrap().upsert_message(msg);
    (
        StatusCode::ACCEPTED,
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        r#"{"ok":true}"#.to_string(),
    )
        .into_response()
}

async fn handle_lfg_remove(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    #[derive(Deserialize)]
    struct R {
        message_id: String,
    }
    let r: R = match serde_json::from_str(&body) {
        Ok(r) => r,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad remove body: {}", e)),
    };
    state.lfg.lock().unwrap().remove_message(&r.message_id);
    json_ok(r#"{"ok":true}"#)
}

async fn handle_lfg_active(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    let s = state.lfg.lock().unwrap();
    let body = serde_json::to_string(&s.messages).unwrap_or_else(|_| "[]".to_string());
    json_ok(&body)
}

async fn handle_actions(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    let session_id = extract_session_id(&headers);
    let mut s = state.lfg.lock().unwrap();
    s.prune_expired_actions();
    let allow_drain = if s.sessions.is_empty() {
        true
    } else {
        session_id
            .as_deref()
            .map(|sid| s.is_primary(sid))
            .unwrap_or(false)
    };
    let actions: Vec<_> = if allow_drain {
        s.action_queue.drain(..).collect()
    } else {
        Vec::new()
    };
    let body = serde_json::to_string(&actions).unwrap_or_else(|_| "[]".to_string());
    json_ok(&body)
}

async fn handle_actions_ack(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    #[derive(Deserialize)]
    struct Ack {
        id: String,
        success: bool,
        #[serde(default)]
        error: Option<String>,
    }
    let ack: Ack = match serde_json::from_str(&body) {
        Ok(a) => a,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad ack body: {}", e)),
    };
    if !ack.success {
        eprintln!(
            "[lfg] action {} failed: {}",
            ack.id,
            ack.error.unwrap_or_default()
        );
    }
    json_ok(r#"{"ok":true}"#)
}

async fn handle_register(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    #[derive(Deserialize)]
    struct Reg {
        session_id: String,
        #[serde(default)]
        user_agent: String,
    }
    let reg: Reg = match serde_json::from_str(&body) {
        Ok(r) => r,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad register body: {}", e)),
    };
    let mut s = state.lfg.lock().unwrap();
    s.register_session(reg.session_id.clone(), reg.user_agent);
    let primary_id = s.primary_session().map(|p| p.session_id.clone());
    let count = s.sessions.len();
    drop(s);
    let body = format!(
        r#"{{"ok":true,"is_primary":{},"session_count":{}}}"#,
        primary_id.as_deref() == Some(reg.session_id.as_str()),
        count
    );
    json_ok(&body)
}

async fn handle_status(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    let status: VoiceStatus = match serde_json::from_str(&body) {
        Ok(s) => s,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad status body: {}", e)),
    };
    state.lfg.lock().unwrap().voice_status = status;
    json_ok(r#"{"ok":true}"#)
}

async fn handle_voice_deleted(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    #[derive(Deserialize)]
    struct VoiceDeleted {
        channel_id: String,
    }
    let upd: VoiceDeleted = match serde_json::from_str(&body) {
        Ok(u) => u,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad voice/deleted body: {}", e)),
    };
    let mut s = state.lfg.lock().unwrap();
    let before = s.messages.len();
    s.messages
        .retain(|m| m.voice_channel_id.as_deref() != Some(&upd.channel_id));
    let removed = before - s.messages.len();
    json_ok(&format!(r#"{{"ok":true,"removed":{}}}"#, removed))
}

async fn handle_voice_state(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: String,
) -> Response {
    if !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }
    maybe_register_session(&state.lfg, &headers);
    #[derive(Deserialize)]
    struct VoiceUpdate {
        channel_id: String,
        #[serde(default)]
        users: Option<u32>,
        #[serde(default)]
        capacity: Option<u32>,
    }
    let upd: VoiceUpdate = match serde_json::from_str(&body) {
        Ok(u) => u,
        Err(e) => return json_error(StatusCode::BAD_REQUEST, &format!("bad voice/state body: {}", e)),
    };
    let mut s = state.lfg.lock().unwrap();
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
    json_ok(&format!(r#"{{"ok":true,"updated":{}}}"#, updated))
}

// ============================================================================
// SSE endpoint
// ============================================================================

/// Query parameters for the /events endpoint.
#[derive(Deserialize, Default)]
struct EventsQuery {
    #[serde(default)]
    token: Option<String>,
    #[serde(default)]
    session: Option<String>,
}

async fn handle_events(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<EventsQuery>,
) -> Response {
    // Auth: check query param token OR Authorization header.
    let authed_via_query = query
        .token
        .as_deref()
        .map(|t| t == LFG_AUTH_TOKEN)
        .unwrap_or(false);
    if !authed_via_query && !is_authorized(&headers) {
        return json_error(StatusCode::UNAUTHORIZED, "missing or bad bearer token");
    }

    // Register session from query param or header.
    let session_id = query
        .session
        .clone()
        .or_else(|| extract_session_id(&headers));
    if let Some(ref sid) = session_id {
        let ua = extract_user_agent(&headers);
        state.lfg.lock().unwrap().register_session(sid.clone(), ua);
    }

    let lfg_state = state.lfg.clone();
    let mut notify_rx = state.notify_tx.subscribe();

    let stream = async_stream::stream! {
        // Send initial boot event.
        let boot_id = process_boot_id();
        let boot_data = format!(r#"{{"boot_id":"{}"}}"#, boot_id);
        yield Ok::<_, Infallible>(Event::default().event("boot").data(boot_data));

        let keepalive_interval = Duration::from_secs(15);

        loop {
            // Wait for either a notification or keepalive timeout.
            let _ = tokio::time::timeout(keepalive_interval, notify_rx.recv()).await;

            // Touch session to prevent GC while SSE is live.
            if let Some(ref sid) = session_id {
                if let Ok(mut s) = lfg_state.lock() {
                    if let Some(sess) = s.sessions.get_mut(sid) {
                        sess.last_seen_at = now_ms();
                    }
                }
            }

            // Drain actions for the primary session.
            let actions: Vec<LfgAction> = {
                let mut s = match lfg_state.lock() {
                    Ok(g) => g,
                    Err(_) => break, // Mutex poisoned
                };

                s.prune_expired_actions();

                let is_primary = if s.sessions.is_empty() {
                    true
                } else {
                    session_id
                        .as_deref()
                        .map(|sid| s.is_primary(sid))
                        .unwrap_or(false)
                };

                if is_primary {
                    s.action_queue.drain(..).collect()
                } else {
                    Vec::new()
                }
            };

            // Push each action as an SSE event.
            for action in &actions {
                if let Ok(json) = serde_json::to_string(action) {
                    yield Ok::<_, Infallible>(Event::default().event("action").data(json));
                }
            }

            // If no actions, send a keepalive comment.
            if actions.is_empty() {
                yield Ok::<_, Infallible>(Event::default().comment("keepalive"));
            }
        }
    };

    Sse::new(stream).into_response()
}

// ============================================================================
// Userscript serving
// ============================================================================

/// Locate the userscript file on disk and return it with proper
/// JavaScript content-type. Tries several candidate paths to handle
/// both development (run from source tree) and deployed (binary symlinked
/// into ~/.local/bin) usage.
fn serve_userscript(filename: &str) -> Response {
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
            return (
                StatusCode::OK,
                [
                    (axum::http::header::CONTENT_TYPE, "application/javascript; charset=utf-8"),
                    (axum::http::header::CACHE_CONTROL, "no-store, no-cache, must-revalidate"),
                ],
                content,
            )
                .into_response();
        }
    }

    (
        StatusCode::NOT_FOUND,
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        r#"{"error":"userscript file not found on disk"}"#.to_string(),
    )
        .into_response()
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
