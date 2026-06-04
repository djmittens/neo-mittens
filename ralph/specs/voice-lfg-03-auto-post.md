# Voice LFG: Draft, Confirm & Auto-Post

## Overview

Turn an `Intent::CreateLfgPost` (from `voice-lfg-02-trigger-engine.md`) into a
real LFG post. Posts in `#lfg-pc-na-ranked` are plain chat messages of the
form `!lfg <description>` — a rank range plus the roles needed — so posting is
just sending a message in the authenticated browser session. A draft is built
from the detected roles plus the active account's rank, shown to the user for
**confirmation/edit**, and only on accept is a `CreateLfgPost` action enqueued
for the userscript to send. Nothing is ever posted without explicit
confirmation.

## Dependencies

- Requires `voice-lfg-02-trigger-engine.md` (`Intent`, `IntentSink`,
  `RoleNeed`).
- Extends the existing action queue (`LfgActionKind`) in `src/lfg.rs` and the
  userscript `userscripts/bnetswitch-lfg.user.js`.
- Uses `src/ranks.rs` + `src/accounts.rs` for the active account's rank.

## Requirements

### Post Config Fields

Add to `AppConfig` in `src/accounts.rs` (prefix `voice_`):

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `voice_lfg_post_channel_id` | `String` | `"182420486582435840"` | Channel to post `!lfg` into. |
| `voice_lfg_post_template` | `String` | `"!lfg {range} LF {roles}"` | Draft template. |
| `voice_lfg_rank_band` | `u32` | `1` | Divisions ± active rank when no spoken range. |

`{range}` and `{roles}` are the only supported template placeholders.

### Draft Builder

Add `fn build_lfg_text(cfg, intent, account_rank: Option<&str>) -> String`:
- `{roles}`: format `intent.needs` as a comma list, count + role string,
  e.g. `1 tank, 2 dps` (omit count when 1? no — always show count for
  clarity). Order: tank, dps, support.
- `{range}`: use `intent.rank_range` when present; else derive from
  `account_rank` widened by `voice_lfg_rank_band` (e.g. rank `Plat 3`, band 1
  => `Gold-Diamond`). If `account_rank` is `None` and no spoken range, use the
  literal `any rank`.
- Substitute into `voice_lfg_post_template`; collapse double spaces; trim.

Add `fn account_rank_label(cfg) -> Option<String>` reading the active
account's current competitive rank via `ranks.rs` (best-effort; `None` on
lookup failure).

### Pending-Post State

Add to `src/voice.rs` (or `src/post.rs`) a `PendingPost`:

```rust
pub struct PendingPost {
    pub draft: String,        // editable "!lfg ..." text
    pub intent_evidence: String,
    pub created_at: i64,
}
```

`VoiceManager` drains `IntentSink`; for each intent it builds a draft via
`build_lfg_text` and stores a single current `PendingPost` (newer intents
replace an unconfirmed pending post). Expose:
- `fn pending_post(&self) -> Option<PendingPost>`
- `fn edit_pending(&mut self, new_draft: String)`
- `fn confirm_pending(&mut self) -> Option<LfgAction>` — consumes the pending
  post and returns a `CreateLfgPost` action to enqueue; `None` if none.
- `fn dismiss_pending(&mut self)`

### CreateLfgPost Action

Add a variant to `LfgActionKind` in `src/lfg.rs`:

```rust
CreateLfgPost { channel_id: String, text: String }
```

`confirm_pending` produces this with `channel_id =
voice_lfg_post_channel_id` and `text = draft`. It is enqueued through the
existing action queue so the elected-leader userscript session picks it up via
`/actions` (and the SSE `/events` stream). The userscript must `POST
/actions/ack` after sending, as with existing actions.

### TUI Confirmation

Add a confirmation prompt to `src/main.rs`: when `pending_post()` is `Some`,
show the draft `!lfg ...` text and the triggering evidence with keys:
- `y` / `Enter` — confirm: enqueue the action, clear pending.
- `e` — edit: enter the draft into an input line for modification.
- `n` / `Esc` — dismiss.

The prompt is non-blocking (the rest of the TUI keeps updating) and only
appears while a pending post exists. A pending post older than 120s is
auto-dismissed.

### Userscript Post Flow

Update `userscripts/bnetswitch-lfg.user.js` (bump the version header) to
handle the `CreateLfgPost` action:
- Navigate to the channel via the SPA route
  `/channels/<guild_id>/<channel_id>` (reuse the existing navigation helper
  used by `JoinByMessage`).
- Set the channel message box to the action's `text` and submit it the same
  way a human send does (focus the message textbox, insert text, dispatch the
  Enter keypress), matching the project's "drive the DOM like a human"
  approach — do not call private Discord APIs.
- On success, `POST /actions/ack`; on failure, ack with an error so the action
  is not retried indefinitely.

Document the new action in `userscripts/README.md`.

## Non-Requirements

- No posting without confirmation (`y`/`e`/`n` flow is mandatory).
- No editing of already-sent posts; no deletion.
- No multi-post batching; one pending post at a time.
- No slash-command/modal handling (posts are plain `!lfg` messages).

## Error Handling

| Condition | Response |
|-----------|----------|
| No active account / rank lookup fails | `{range}` falls back to spoken range or `any rank`. |
| Pending post expires (>120s) | Auto-dismiss; no action enqueued. |
| Userscript can't find the message box | Ack with error; surface in TUI status; do not retry. |
| No leader userscript session | Action waits in queue (existing behavior); TUI notes "no Discord session". |

## Acceptance Criteria

- [ ] `LfgActionKind::CreateLfgPost` variant exists: `grep -c 'CreateLfgPost' bnetswitch/src/lfg.rs` returns >= 1
- [ ] `build_lfg_text` formats roles + range into the template: `cargo test -p bnetswitch build_lfg_text` passes
- [ ] Spoken range preferred over derived range: `cargo test -p bnetswitch lfg_range_precedence` passes
- [ ] No-rank fallback yields `any rank`: `cargo test -p bnetswitch lfg_range_fallback` passes
- [ ] `confirm_pending` returns a `CreateLfgPost` action; `dismiss_pending` clears: `cargo test -p bnetswitch pending_post_flow` passes
- [ ] Newer intent replaces an unconfirmed pending post: `cargo test -p bnetswitch pending_post_replace` passes
- [ ] TUI confirmation keys handled: `grep -cE "KeyCode::Char\('y'\)|KeyCode::Char\('e'\)|KeyCode::Char\('n'\)" bnetswitch/src/main.rs` returns >= 1
- [ ] Userscript handles `CreateLfgPost` and bumps version: `grep -c 'CreateLfgPost' userscripts/bnetswitch-lfg.user.js` returns >= 1
- [ ] `userscripts/README.md` documents the post action: `grep -c 'CreateLfgPost' userscripts/README.md` returns >= 1
- [ ] `cargo build -p bnetswitch` succeeds
