# Experiment 002: Local Devstral via llama.cpp

## Question

How far can Devstral Small 2 (24B, Q4_K_M) get on a complex C systems
refactoring spec running entirely locally with zero cloud dependency?

## Why This Matters

- **Pipeline validation**: Proves the entire ralph construct pipeline
  works end-to-end before burning cloud quota on experiment 001.
- **Cost**: Zero quota burn. If Devstral handles Phase 0 (mechanical
  renames), the cloud profiles only need to tackle harder phases.
- **Baseline**: Establishes the local-only quality floor for comparison
  against cloud profiles in 001.

## Why llama.cpp, Not LM Studio

LM Studio's tool call parser fails for Devstral. The embedded Jinja
template outputs `[TOOL_CALLS]name[ARGS]{...}` but LM Studio's parser
expects the older Mistral JSON array format. Result: `tool_calls: []`
with raw tool markup in `message.content`.

llama.cpp's `llama-server` with `--jinja` correctly renders Devstral's
native template and parses tool calls back to OpenAI-compatible format.
Verified with smoke test:

```
finish_reason: "tool_calls"
tool_calls: [{ name: "get_weather", arguments: {"location": "San Francisco"} }]
```

## Hardware

- **Machine**: redbox
- **CPU**: AMD Ryzen 9 9900X (12C/24T)
- **RAM**: 64GB DDR5
- **GPU**: NVIDIA RTX 5090 (32GB GDDR7)

## Model

| Detail | Value |
|--------|-------|
| Model | Devstral Small 2 24B Instruct 2512 |
| Quant | Q4_K_M (13GB VRAM) |
| Context | 131072 tokens (128K) |
| KV cache | Q8_0 quantized (10GB vs 20GB FP16) |
| Backend | llama.cpp llama-server, port 8080 |
| Template | Native Jinja via `--jinja` flag |
| opencode ID | `llamacpp/devstral` |
| ralph profile | `devstral` |
| GGUF path | `~/.lmstudio/models/lmstudio-community/Devstral-Small-2-24B-Instruct-2512-GGUF/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf` |

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max iterations | 40 | Free, can afford many attempts |
| Max wall time | 3 hours | Local inference ~90 tok/s generation |
| Max failures | 5 | More tolerance for weaker model |
| Stage timeout | 15 min | From config default |
| Context | 128K | Q8_0 KV cache keeps VRAM at 24GB (see below) |

## VRAM Budget

Devstral 24B Q4_K_M on RTX 5090 (32GB):

| Component | FP16 KV | Q8_0 KV |
|-----------|---------|---------|
| Model weights | 14 GB | 14 GB |
| KV cache (128K ctx) | 20 GB | 10 GB |
| **Total** | **34 GB (won't fit)** | **24 GB** |
| Headroom | -2 GB | 8 GB |

Architecture: 40 layers, 8 KV heads (GQA), 128 head_dim.
KV formula: `2 × layers × kv_heads × head_dim × ctx × bytes_per_param`.

128K with FP16 KV exceeds 32GB. Q8_0 KV quantization halves KV cache
size with negligible quality loss, bringing total to 24GB with 8GB
headroom for scratch buffers and flash attention workspace.

For reference, 65K with FP16 KV also uses 24GB — so 128K + Q8_0 KV
gives double the context for the same VRAM footprint.

## Execution Plan

### Prerequisites

1. Start llama-server:
   ```bash
   llama-server \
     -m ~/.lmstudio/models/lmstudio-community/Devstral-Small-2-24B-Instruct-2512-GGUF/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf \
     --jinja --ctx-size 131072 --flash-attn on --port 8080 -ngl 99 \
     --cache-type-k q8_0 --cache-type-v q8_0
   ```

2. Verify server:
   ```bash
   curl http://localhost:8080/health
   # {"status":"ok"}
   ```

3. Verify opencode sees it:
   ```bash
   opencode models | grep llamacpp
   # llamacpp/devstral
   ```

### Step 1: Setup Worktree

```bash
cd ~/src/neo-mittens/app/ralph/experiments
bash bench/scripts/setup-worktrees.sh 002-local-models/experiment.conf
```

### Step 2: Generate Plan

```bash
cd ~/src/valkyria-experiments/devstral-run1
RALPH_PROFILE=devstral ralph2 plan system-architecture-refactor.md
git add .tix/ ralph/ && git commit -m "ralph: plan for local Devstral experiment"
```

### Step 3: Run Experiment

```bash
cd ~/src/neo-mittens/app/ralph/experiments
bash bench/scripts/run-experiment.sh 002-local-models/experiment.conf devstral
```

### Step 4: Analyze

```bash
python3 bench/scripts/analyze.py 002-local-models/experiment.conf
```

## What We Learn

- **Phase 0 capability**: Can Devstral handle mechanical symbol renames
  across ~30 files? (This is the easiest phase.)
- **Tool calling reliability**: Does llama.cpp + `--jinja` produce
  consistent, parseable tool calls throughout a long session?
- **Context pressure**: Does the 128K context window (Q8_0 KV) hold
   up across long sessions with large C files?
- **Failure modes**: Timeouts? Loops? Bad edits? Compilation errors?
- **Generation speed**: Is ~90 tok/s fast enough for ralph's iteration
  loop, or does the model become a bottleneck?

## Expected Outcomes

1. Devstral completes Phase 0 (mechanical renames) cleanly.
2. Devstral stalls on Phase 1+ (architectural changes requiring
   understanding of C threading primitives and GC internals).
3. Tool calling works reliably via llama.cpp `--jinja`.
4. The experiment validates the full pipeline (worktrees, ralph
   construct, telemetry collection, report generation).

## Cleanup

```bash
# Remove worktree
git -C ~/src/valkyria worktree remove \
  "$HOME/src/valkyria-experiments/devstral-run1" --force

# Delete experiment branch
git -C ~/src/valkyria branch -D "exp/002-local-models/devstral"

# Stop llama-server
kill $(pgrep -f 'llama-server.*8080')
```
