# Voice LFG: Trigger Engine

## Overview

Watch the live rolling transcript for spoken intent and emit structured
events. The hot path is a cheap keyword/regex gate so we never run an LLM on
every utterance; only after a gate fires do we (optionally) call Ollama to
parse messy phrasing into structured fields. The first and only trigger this
spec ships is **LFG-post intent**: detect that the group is talking about
making an LFG post and extract the roles/counts being requested. Emitted
intents are surfaced for confirmation and posting in
`voice-lfg-03-auto-post.md`.

## Dependencies

- Requires `voice-lfg-01-live-transcription.md` (`RollingTranscript`,
  `TranscriptSink`, `VoiceManager`).
- Optional Ollama (existing `ureq` dep) for fuzzy extraction; config
  `voice_intent_use_llm` gates it.

## Requirements

### Trigger Config Fields

Add to `AppConfig` in `src/accounts.rs` (prefix `voice_`):

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `voice_intent_use_llm` | `bool` | `false` | After gate fires, use Ollama to parse roles. |
| `voice_intent_ollama_host` | `String` | `"http://127.0.0.1:11434"` | Ollama endpoint. |
| `voice_intent_ollama_model` | `String` | `"llama3.1:8b"` | Ollama model. |
| `voice_intent_debounce_secs` | `u64` | `45` | Min gap between emitted LFG intents. |

### Intent Types

Add `src/intent.rs`:

```rust
pub enum Role { Tank, Dps, Support }

pub struct RoleNeed { pub role: Role, pub count: u32 }

pub enum Intent {
    CreateLfgPost {
        needs: Vec<RoleNeed>,   // roles/counts requested
        rank_range: Option<String>, // spoken range if detected, else None
        evidence: String,       // transcript window that triggered it
    },
}
```

`Role` must provide `as_str` (`"tank"|"dps"|"support"`) and `parse` accepting
common synonyms: tank=`tank`; dps=`dps`/`damage`/`dee pee ess`; support=
`support`/`sup`/`heal`/`healer`/`flex support`/`main support`.

### Gate Matching

Add `fn lfg_gate(window: &str) -> bool` returning true when the recent
transcript window indicates LFG-post intent. The gate is case-insensitive and
requires BOTH:
- an action cue: one of `make a post`, `post lfg`, `lfg post`, `let's lfg`,
  `should we post`, `looking for`, `need a`, `need one`, `who do we need`; AND
- at least one role synonym (per `Role::parse`).

The action-cue and role lists are module constants so they are easy to audit
and extend.

### Role Extraction

Add `fn extract_needs(window: &str) -> Vec<RoleNeed>`:
- Scan for role synonyms; for each, look for an immediately-preceding count
  token (`a`/`one`/`1` => 1, `two`/`2` => 2, `three`/`3` => 3); default 1 when
  absent.
- Deduplicate by role, summing counts, capped at 3 per role.
- Return empty when no role is found (caller suppresses the intent).

Add `fn extract_rank_range(window: &str) -> Option<String>` matching common
spoken ranges (e.g. `plat to diamond`, `gold-plat`, `diamond and up`) into a
normalized string like `"Plat-Diamond"`. Return `None` when absent.

### Optional LLM Extraction

When `voice_intent_use_llm` is true, add `fn llm_extract(cfg, window) ->
Result<(Vec<RoleNeed>, Option<String>)>` that POSTs the window to Ollama
`/api/generate` (`stream=false`) with a prompt instructing it to return JSON
`{"needs":[{"role":"tank","count":1}],"rank_range":"Plat-Diamond"}`, then
parses that JSON. On any error, the caller falls back to the regex extractors;
the LLM never blocks the gate.

### Trigger Engine

Add `src/triggers.rs` with `TriggerEngine`:

| Method | Signature | Behavior |
|--------|-----------|----------|
| `new` | `fn new(cfg: AppConfig, out: IntentSink) -> TriggerEngine` | Construct with an output sink for emitted intents. |
| `evaluate` | `fn evaluate(&mut self, transcript: &TranscriptSink)` | Read `recent_text(window)`, run the gate, and on a non-debounced match build + emit an `Intent::CreateLfgPost`. |

`evaluate` is called by `VoiceManager` whenever new transcript text arrives
(e.g. after each pushed utterance, or on a short timer). On a gate match:
- Build needs via `extract_needs` (or `llm_extract` when enabled, with regex
  fallback) and `rank_range` via the matching extractor.
- If `needs` is empty, do not emit.
- Enforce `voice_intent_debounce_secs` since the last emitted intent.
- Push the `Intent` to `IntentSink` (a thread-safe queue spec 03 drains).

`IntentSink` is a thread-safe handle (`Arc<Mutex<VecDeque<Intent>>>`).

## Non-Requirements

- No triggers other than LFG-post intent.
- No auto-posting or draft UI here (spec 03 consumes `IntentSink`).
- No multi-language intent; English cues only.
- No speaker-aware logic (intent may come from "you" or "team" lines).

## Error Handling

| Condition | Response |
|-----------|----------|
| Empty/short window | Gate returns false; no intent. |
| Gate fires but no role extracted | Suppress (no empty-needs intent). |
| Within debounce window | Skip emit; keep most recent context. |
| Ollama error (LLM mode) | Log; fall back to regex extractors. |
| Ollama returns non-JSON | Log; fall back to regex extractors. |

## Acceptance Criteria

- [ ] `Role`/`RoleNeed`/`Intent` defined in `src/intent.rs`: `grep -cE 'enum Role|struct RoleNeed|enum Intent' bnetswitch/src/intent.rs` returns >= 3
- [ ] `Role::parse` handles synonyms incl. `heal`/`damage`: `cargo test -p bnetswitch role_synonyms` passes
- [ ] `lfg_gate` requires action cue AND role: `cargo test -p bnetswitch lfg_gate` passes (positive + negative cases)
- [ ] `extract_needs` parses counts and caps at 3: `cargo test -p bnetswitch extract_needs` passes
- [ ] `extract_rank_range` normalizes spoken ranges: `cargo test -p bnetswitch extract_rank_range` passes
- [ ] Debounce suppresses repeat intents: `cargo test -p bnetswitch trigger_debounce` passes
- [ ] Gate match with no role emits nothing: `cargo test -p bnetswitch gate_without_role_suppressed` passes
- [ ] `TriggerEngine::evaluate` pushes intents to the sink: `cargo test -p bnetswitch trigger_emits_intent` passes
- [ ] `VoiceManager` calls `TriggerEngine::evaluate` on new transcript: `grep -c 'evaluate' bnetswitch/src/voice.rs` returns >= 1
- [ ] `cargo build -p bnetswitch` succeeds
