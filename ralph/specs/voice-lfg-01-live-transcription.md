# Voice LFG: Live Transcription

## Overview

Live-transcribe the Overwatch Discord voice call into an in-memory rolling
transcript that later specs watch for intent (e.g. auto-drafting an LFG
post). bnetswitch owns the capture clock: it reads **raw PCM from `pw-record`
over a pipe (in-memory, no WAV files)**, tracks the sample position so every
utterance gets an absolute audio-clock timestamp, and transcribes in-process
with `whisper-rs`, which returns per-segment timestamps. Two sources are
captured: the local mic (you) and the **Discord-only** team audio (isolated
from Overwatch game audio via a dedicated null-sink tap). Because every
utterance is positioned on the audio timeline (not by when whisper finished),
speaker attribution in `voice-lfg-04-speaker-attribution.md` is exact
interval math — no lag fudge.

Transcription is **off by default** and only runs when opted in. A visible
indicator must show while audio is being transcribed.

## Dependencies

- Requires the `whisper-rs` crate (links whisper.cpp; build needs cmake +
  clang; optional `cuda` feature for GPU) and a GGUF model.
- Requires `pw-record`, `pactl`, `pw-dump`, `pw-link` (PipeWire).
- Builds on existing `VoiceStatus` voice-edge tracking in `src/lfg.rs`.

## Requirements

### Voice Config Fields

Add to `AppConfig` in `src/accounts.rs` (prefix `voice_`), each with
`#[serde(default = ...)]` and matching `AppConfig::default()` values:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `voice_enabled` | `bool` | `false` | Master opt-in for live transcription. |
| `voice_capture_self` | `bool` | `true` | Transcribe local mic (you). |
| `voice_capture_team` | `bool` | `true` | Transcribe Discord team audio. |
| `voice_self_source` | `String` | `"@DEFAULT_SOURCE@"` | `pw-record` target for mic. |
| `voice_team_source` | `String` | `"@DISCORD@"` | Team audio target (see Discord tap). |
| `voice_discord_app_match` | `String` | `"Firefox"` | Substring identifying the browser node that plays Discord. |
| `voice_self_label` | `Option<String>` | `None` | Display name for your mic lines; falls back to active account BattleTag, else `"Me"`. |
| `voice_whisper_model` | `Option<String>` | `None` | Path to GGUF model loaded by whisper-rs. |
| `voice_vad_silence_ms` | `u64` | `700` | Silence gap that closes an utterance segment. |
| `voice_segment_max_secs` | `u64` | `8` | Hard cap on a single segment's length. |
| `voice_buffer_secs` | `u64` | `90` | Rolling transcript window length. |

### PipeWire Source Resolution

Add `src/voice_capture.rs` with
`resolve_source(cfg, target: &str) -> Result<String>` returning a `pw-record`
`--target` node name:

| Target value | Resolution |
|--------------|-----------|
| `@DEFAULT_SOURCE@` | `pactl get-default-source` output. |
| `@DISCORD@` | Ensure the Discord tap (below), return `"bnetswitch_discord.monitor"`. |
| any other string | Used verbatim as a node name. |

### Discord-Only Capture (null-sink tap)

To capture only Discord (never Overwatch game audio), add to
`src/voice_capture.rs`:

| Function | Signature | Behavior |
|----------|-----------|----------|
| `ensure_discord_tap` | `fn ensure_discord_tap(cfg: &AppConfig) -> Result<String>` | Idempotently create null sink `bnetswitch_discord`; mirror the Discord browser playback node(s) into it; return the monitor name. |
| `teardown_discord_tap` | `fn teardown_discord_tap()` | Remove only the links this process created. |

`ensure_discord_tap` must:
- Create the null sink if absent: `pactl load-module module-null-sink
  sink_name=bnetswitch_discord media.class=Audio/Sink channel_map=stereo`.
- Resolve Discord nodes from `pw-dump`: `media.class = Stream/Output/Audio`
  whose `application.name`/`node.name`/`media.name` contains
  `voice_discord_app_match` (case-insensitive).
- For each match, `pw-link` its output ports to the null sink inputs **in
  addition to** existing links (do NOT unlink the real sink, so Discord still
  plays to the user's headphones). Record created links for teardown.
- Retry resolution a few times over ~3s (the Discord voice stream may appear
  shortly after the voice-join that triggered capture).
- If no node matches after retries, `Err` listing candidate
  `Stream/Output/Audio` node names.

### PCM Capture & Audio Clock

Add `PcmCapture` to `src/voice_capture.rs`. For each enabled source it spawns
`pw-record --target <resolved> --rate 16000 --channels 1 --format s16 -`
(stdout pipe; no file) and a reader thread:

| Method | Signature | Behavior |
|--------|-----------|----------|
| `start` | `fn start(cfg: &AppConfig, seg: SegmentSink) -> Result<PcmCapture>` | Spawn `pw-record` per source; reader threads feed frames to a `VadSegmenter`. |
| `stop` | `fn stop(self)` | Kill children, join threads, `teardown_discord_tap()`. |

The reader records `t0_wall_ms` (wall-clock at the first frame) and a running
sample counter. The absolute time of sample index `n` is
`abs_ms(n) = t0_wall_ms + n * 1000 / 16000`. Anchoring `t0` to wall-clock ms
puts utterances on the same clock as the userscript's `Date.now()` speaking
events (same host), which spec 04 relies on. A child that fails to spawn is
logged and skipped; the other source still runs.

### VAD Segmentation & Transcription

Add `src/voice_transcribe.rs`:
- `VadSegmenter` consumes PCM frames per source and emits a `PcmSegment {
  source, start_ms, end_ms, samples }` whenever it sees `voice_vad_silence_ms`
  of trailing silence (simple energy threshold) or hits `voice_segment_max_secs`.
- A transcription worker loads the `whisper-rs` model once from
  `voice_whisper_model` and, per `PcmSegment`, runs `whisper_full` to get text
  and pushes an `Utterance` (timing copied from the segment's absolute ms).
  Blank/`[BLANK_AUDIO]`/whitespace results are dropped.
- The whisper context is created once and reused; segments are processed on a
  dedicated worker thread so capture is never blocked.

### Transcript Types & Speaker Labels

Add `src/transcript.rs`:

```rust
pub enum Source { Mic, Team }
pub struct Utterance {
    pub source: Source,
    pub speaker: Option<String>, // Some for Mic; None for Team until attributed (spec 04)
    pub start_ms: i64,           // absolute audio-clock ms (wall-aligned)
    pub end_ms: i64,
    pub text: String,
}
pub struct RollingTranscript { /* deque, max age = voice_buffer_secs */ }
```

`RollingTranscript` provides `push`, `recent_text(secs)` (plain text, for
trigger matching in spec 02), `snapshot()` (labeled, for display), and
`attribute_team(f)` (fills `speaker` for `Source::Team` utterances in spec 04).
Mic utterances are pushed with `speaker = voice_self_label` (or active-account
BattleTag, else `"Me"`).

### Lifecycle Manager

Add `src/voice.rs` with `VoiceManager`, owned by the process hosting the LFG
server (TUI-embedded and headless `lfg-server`):

| Method | Signature | Behavior |
|--------|-----------|----------|
| `on_voice_transition` | `fn on_voice_transition(&mut self, status: &VoiceStatus)` | On `false->true` with `voice_enabled`: start `PcmCapture`. On `true->false`: stop it. |
| `is_transcribing` | `fn is_transcribing(&self) -> bool` | For the TUI indicator. |
| `transcript` | `fn transcript(&self) -> TranscriptSink` | Shared handle for specs 02 and 04. |

Wire `on_voice_transition` into the existing voice handlers in `src/lfg.rs`
(`handle_status` / `handle_voice_state`). Re-entrant starts/stops are no-ops.

## Non-Requirements

- No disk WAV/audio files at any point (PCM stays in memory).
- No persistent transcript storage (in-memory rolling buffer only).
- No trigger/intent detection or posting (specs 02-03 cover them).
- Per-speaker name attribution for team audio is `voice-lfg-04`; here team
  utterances carry `source = Team`, `speaker = None`.
- No automatic install of whisper.cpp models.

## Error Handling

| Condition | Response |
|-----------|----------|
| `voice_enabled = false` | `on_voice_transition` does nothing. |
| `voice_whisper_model` unset | Log error, do not start capture. |
| Discord node not matched | `Err` listing candidate nodes; skip team capture; mic still runs. |
| Mic source unresolvable | Skip mic; if team also fails, abort start cleanly. |
| `pw-record` exits early | Log; keep the other source; mark that source stopped. |

## Acceptance Criteria

- [ ] `voice_enabled` + other `voice_` fields exist in `AppConfig`: `grep -c 'voice_enabled' bnetswitch/src/accounts.rs` returns >= 2
- [ ] `whisper-rs` is a dependency: `grep -c 'whisper-rs' bnetswitch/Cargo.toml` returns >= 1
- [ ] Config loads without `voice_` keys (serde defaults): `cargo test -p bnetswitch voice_config_defaults` passes
- [ ] `resolve_source` handles `@DEFAULT_SOURCE@` and `@DISCORD@`: `cargo test -p bnetswitch resolve_source_sentinels` passes
- [ ] `ensure_discord_tap` builds null-sink + pw-link commands and lists candidates on miss: `cargo test -p bnetswitch discord_tap_commands` passes (fixture `pw-dump` JSON)
- [ ] `abs_ms` maps sample index to wall-aligned ms: `cargo test -p bnetswitch audio_clock_abs_ms` passes
- [ ] `VadSegmenter` splits on silence and max length with correct sample ranges: `cargo test -p bnetswitch vad_segmenter` passes
- [ ] `Utterance` carries absolute `start_ms`/`end_ms` and Mic lines are self-labeled: `cargo test -p bnetswitch utterance_self_label` passes
- [ ] `RollingTranscript` evicts by age and `recent_text` works: `cargo test -p bnetswitch rolling_transcript` passes
- [ ] `VoiceManager` defines `on_voice_transition`/`is_transcribing`/`transcript`: `grep -cE 'fn on_voice_transition|fn is_transcribing|fn transcript' bnetswitch/src/voice.rs` returns >= 3
- [ ] `on_voice_transition` invoked from `lfg.rs` voice handlers: `grep -c 'on_voice_transition' bnetswitch/src/lfg.rs` returns >= 1
- [ ] `cargo build -p bnetswitch` succeeds
