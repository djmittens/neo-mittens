# Experiment 002: Local Models

## Question

How far can local-only models get on a complex C systems refactoring spec
with zero cloud dependency? Which local model (or combination) performs
best as an autonomous coding agent?

## Why This Matters

- **Cost**: Zero quota burn on Claude Max. If a local model handles 80%
  of the work, you only need cloud for the hard 20%.
- **Independence**: No API outages, rate limits, or pricing changes.
- **Parallelism**: All 6 runs can execute in sequence overnight with no
  API concurrency concerns. LM Studio auto-loads models on demand.
- **Privacy**: Code never leaves the machine.

## Hardware

- **Machine**: redbox
- **CPU**: AMD Ryzen 9 9900X (12C/24T)
- **RAM**: 64GB DDR5
- **GPU**: NVIDIA RTX 5090 (32GB GDDR7)

## Inference Backend: LM Studio

All local inference runs through **LM Studio** on port 1234, via the
`opencode-lmstudio` plugin. LM Studio handles model loading, context
management, and GPU offloading automatically.

**Why LM Studio over llama-server/vllm:**
- Auto-loads models on demand (no manual server restart between profiles)
- Handles context window management internally
- Already integrated with opencode via plugin
- All test models already downloaded as GGUF

To start before running experiments:
```bash
lms server start
```

## Models Under Test

All models are already downloaded in `~/.lmstudio/models/`:

| Profile | Model ID (opencode) | Architecture | GGUF | Strength |
|---------|-------------------|-------------|------|----------|
| `devstral` | `lmstudio/mistralai/devstral-small-2-2512` | 24B dense | Q4_K_M (13G) + Q8_0 (23G) | Agentic tool-use, Mistral trained |
| `qwen3-coder` | `lmstudio/qwen/qwen3-coder-30b` | 30B MoE (3B active) | Downloaded | SOTA agentic coding, very fast MoE |
| `glm-flash` | `lmstudio/zai-org/glm-4.7-flash` | ~16B | Q4_K_M (17G) + Q8_0 (30G) | Fast general purpose |
| `gpt-oss` | `lmstudio/openai/gpt-oss-20b` | 20B | MXFP4 (11-13G) | Reasoning mode enabled |
| `local-hybrid` | Qwen3-Coder reasoning + Devstral BUILD | Mixed | -- | Best reasoner + proven builder |
| `local-hybrid-inv` | Devstral reasoning + Qwen3-Coder BUILD | Mixed | -- | Test which role matters more |

### Why These Models

- **Devstral Small 2**: Baseline. Already proven as the BUILD model in the
  hybrid cloud profile. Specifically trained for agentic tool-use by Mistral.
- **Qwen3-Coder-Flash**: MoE architecture means it's fast despite 30B total
  params (only 3B active per token). Specifically trained for agentic coding.
  Native 262K context. This is the model most likely to challenge cloud.
- **GLM-4.7-Flash**: Different lineage (GLM/Zhipu). Smaller and faster.
  Tests whether raw speed (more iterations in the time budget) beats quality.
- **GPT-OSS 20B**: OpenAI's open model with reasoning capability.
  Tests whether structured reasoning helps with architectural decisions.
- **local-hybrid / local-hybrid-inv**: The key question for mixed-local
  is whether reasoning quality or BUILD quality matters more for Ralph's
  staged architecture.

## Parameters

| Parameter | Value | vs 001 Cloud | Rationale |
|-----------|-------|-------------|-----------|
| Max iterations | 40 | 25 | Free, can afford more attempts |
| Max wall time | 3 hours | 2 hours | Local inference may be slower per call |
| Max failures | 5 | 3 | More tolerance for weaker models |
| Stage timeout | 15 min | Same | |

## Execution Plan

### Prerequisites

1. LM Studio server running:
   ```bash
   lms server start
   # Verify:
   curl http://localhost:1234/v1/models
   ```

2. Verify models load in opencode:
   ```bash
   opencode models | grep lmstudio
   ```

### Step 1: Setup Worktrees

```bash
cd ~/src/neo-mittens/app/ralph/experiments
bash bench/scripts/setup-worktrees.sh 002-local-models/experiment.conf
```

### Step 2: Generate Plan

Reuse the plan from 001 if available (same spec, same base ref), or
generate fresh. For local-only plan generation, use the strongest local
model:

```bash
cd ~/src/valkyria-experiments/devstral-run1
RALPH_PROFILE=qwen3-coder ralph2 plan system-architecture-refactor.md
git add .tix/ ralph/ && git commit -m "ralph: plan for local models experiment"
PLAN_SHA=$(git rev-parse HEAD)

for profile in qwen3-coder glm-flash gpt-oss local-hybrid local-hybrid-inv; do
  (cd ~/src/valkyria-experiments/${profile}-run1 && git cherry-pick $PLAN_SHA)
done
```

### Step 3: Run Experiments

All local -- run them sequentially overnight. LM Studio handles model
swapping automatically:

```bash
cd ~/src/neo-mittens/app/ralph/experiments
CONF="002-local-models/experiment.conf"

for profile in devstral qwen3-coder glm-flash gpt-oss local-hybrid local-hybrid-inv; do
  echo "=== Starting $profile at $(date) ==="
  bash bench/scripts/run-experiment.sh $CONF $profile
  echo "=== Finished $profile at $(date) ==="
  sleep 15
done
```

### Step 4: Analyze

```bash
python3 bench/scripts/analyze.py 002-local-models/experiment.conf
```

### Step 5: Cross-reference with 001

After both experiments complete, compare the best local model against
cloud profiles:

```bash
# Show all runs from both experiments side by side
python3 bench/scripts/analyze.py 001-profile-showdown/experiment.conf
python3 bench/scripts/analyze.py 002-local-models/experiment.conf
```

## What We Learn

### Between local models

- **MoE vs Dense**: Qwen3-Coder (MoE, fast, huge context) vs Devstral (dense, tool-trained)
- **Speed vs quality**: GLM-Flash (fastest, smallest) vs others
- **Reasoning capability**: Does gpt-oss reasoning mode help with INVESTIGATE/VERIFY?
- **Role assignment**: In local-hybrid profiles, does reasoning quality or BUILD quality drive outcomes?

### Compared to cloud (cross-reference with 001)

- **Quality gap**: Best local completion rate vs best cloud completion rate
- **Speed tradeoff**: Local inference latency vs cloud API latency
- **Failure modes**: More context kills (smaller windows)? More loops (weaker reasoning)?
- **Practical threshold**: At what spec complexity do local models stop being viable?

## Expected Outcomes

1. **Qwen3-Coder-Flash** will be the best single local model (agentic training + MoE speed + large context).
2. **local-hybrid** (Qwen3-Coder reasoning + Devstral BUILD) will match or beat any single-model local profile.
3. **GLM-Flash** will complete the most iterations but fewer tasks (speed without depth).
4. **gpt-oss** reasoning mode may help on VERIFY stage but hurt on BUILD (overthinking).
5. All local models will handle Phase 0 (mechanical renames). Phase 1+ will separate them.
6. Best local will be ~60-70% as effective as cloud Opus on task completion.
