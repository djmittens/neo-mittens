# Voice LFG: Speaker Attribution

## Overview

Label each team transcript line with the specific Discord user who said it.
The team audio is a single mixed stream, so speakers can't be separated from
the audio without a diarization model. Instead, both signals are placed on one
shared timeline and matched by exact interval overlap: spec 01 timestamps
every utterance by its audio-sample position (wall-clock aligned), and the
userscript forwards Discord **Speaking** toggles stamped with `Date.now()`.
Because the browser and bnetswitch run on the same host, and the Speaking
toggle and the voice audio both originate from the same Discord voice
connection, the two timelines share a clock — so attribution is deterministic
interval math with **no lag fudge factor**. Your own mic lines are already
labeled in spec 01; this spec resolves team speakers.

## Dependencies

- Requires `voice-lfg-01-live-transcription.md` (`Utterance` with absolute
  `start_ms`/`end_ms`, `Source::Team`, `RollingTranscript::attribute_team`).
- Extends the userscript `userscripts/bnetswitch-lfg.user.js` (WebSocket tap)
  and the LFG HTTP server in `src/lfg.rs`.

## Requirements

### Attribution Config Field

Add to `AppConfig` in `src/accounts.rs`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `voice_attrib_multi_label` | `String` | `"(multiple)"` | Label when two+ users overlap one utterance. |

No timing-offset knob is needed: utterances and speaking events are already on
the same wall-aligned clock. (An optional small VAD-padding trim may be a
module constant, not user config.)

### Userscript: Capture Speaking Toggles

Update `userscripts/bnetswitch-lfg.user.js` (bump version header):
- From the already-patched WebSocket, capture Discord voice **Speaking**
  frames (op 5: `user_id`, `ssrc`, `speaking` flag) and emit a transition when
  a user starts (`speaking != 0`) or stops (`speaking == 0`).
- Maintain a `user_id -> display_name` map from `VOICE_STATE_UPDATE` / member
  data already seen on the gateway.
- `POST /voice/speaking` (Bearer auth + `X-Bnet-Session` header, like existing
  posts) with `{ user_id, name, speaking: bool, ts_ms }` where `ts_ms =
  Date.now()` at observation — the same wall clock spec 01 anchors capture to.
- Document the new flow in `userscripts/README.md`.

### Server: Speaking Timeline

In `src/lfg.rs`, add:
- Wire type `SpeakingEvent { user_id: String, name: Option<String>, speaking:
  bool, ts_ms: i64 }`.
- Endpoint `POST /voice/speaking` recording events into a bounded
  speaking-history buffer (keep last ~120s) in shared state, using the
  existing `maybe_register_session` helper.
- A `SpeakingHistory` type with `record(&mut self, ev: SpeakingEvent)`,
  `intervals(&self) -> Vec<SpeakInterval>` exposing closed `[start_ms,
  end_ms]` per user (an unmatched start is treated as ongoing through now),
  and a `user_id -> name` map updated as names arrive.

### Attribution Logic

Add `src/attribution.rs` with
`fn attribute(history: &SpeakingHistory, u: &Utterance, multi_label: &str) ->
Option<String>`:
- Only attributes `Source::Team` utterances (return `None` otherwise).
- Compute total overlap between `[u.start_ms, u.end_ms]` and each user's
  speaking intervals.
- Return the single dominant speaker's name; if two+ have comparable overlap
  (within 40% of the max), return `multi_label`; if none overlap, `None`.
- Resolve `user_id` to a name via the history map; fall back to the raw
  `user_id` when unknown.

### Wiring

`VoiceManager` (spec 01) calls `RollingTranscript::attribute_team` with a
closure delegating to `attribute`, using the server's `SpeakingHistory` and
`voice_attrib_multi_label`. Attribution runs on read/refresh (e.g. before the
TUI renders, and before spec 02 reads labeled history) so late-arriving
speaking events can resolve a previously-unattributed line. Already-attributed
team utterances are not relabeled.

## Non-Requirements

- No audio-based diarization model.
- No timing/lag offset config (shared clock makes it unnecessary).
- No attribution of Mic lines (handled in spec 01).
- No cross-channel history; only the current voice channel's speakers.
- No persistence of the speaking timeline (in-memory, bounded).

## Error Handling

| Condition | Response |
|-----------|----------|
| No speaking events overlap an utterance | `speaker` stays `None` (renders as unknown). |
| Overlapping speakers | Return `voice_attrib_multi_label`. |
| Speaking start without matching stop | Treat interval as ongoing through now. |
| Name not yet known for a `user_id` | Use the `user_id` string until a name arrives. |
| `/voice/speaking` malformed body | Return 400; do not mutate history. |

## Acceptance Criteria

- [ ] `voice_attrib_multi_label` exists in `AppConfig`: `grep -c 'voice_attrib_multi_label' bnetswitch/src/accounts.rs` returns >= 2
- [ ] `SpeakingEvent` + `/voice/speaking` route added: `grep -cE 'SpeakingEvent|/voice/speaking' bnetswitch/src/lfg.rs` returns >= 2
- [ ] `SpeakingHistory` records events and yields per-user intervals: `cargo test -p bnetswitch speaking_history` passes
- [ ] `attribute` picks the dominant overlapping speaker by interval overlap: `cargo test -p bnetswitch attribute_dominant` passes
- [ ] Overlapping speakers yield the multi label: `cargo test -p bnetswitch attribute_multiple` passes
- [ ] No overlap yields `None`: `cargo test -p bnetswitch attribute_none` passes
- [ ] `attribute` only labels `Source::Team` utterances: `cargo test -p bnetswitch attribute_skips_mic` passes
- [ ] Unmatched speaking-start is treated as ongoing: `cargo test -p bnetswitch speaking_open_interval` passes
- [ ] Userscript posts speaking toggles and bumps version: `grep -c '/voice/speaking' userscripts/bnetswitch-lfg.user.js` returns >= 1
- [ ] `userscripts/README.md` documents speaking capture: `grep -ci 'speaking' userscripts/README.md` returns >= 1
- [ ] `cargo build -p bnetswitch` succeeds
