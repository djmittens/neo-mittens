# Ralph Experiments

Benchmarking and experimentation framework for optimizing Ralph's autonomous
execution across different model configurations, guardrail settings, and
target projects.

## Directory Layout

```
experiments/
  README.md                  # This file
  bench/                     # Reusable benchmarking framework
    scripts/                 # Generic scripts (not experiment-specific)
      setup-worktrees.sh     # Create isolated git worktrees per profile
      run-experiment.sh      # Execute one ralph construct run
      collect-report.sh      # Gather telemetry + correctness data post-run
      analyze.py             # Aggregate all runs into a comparison report
    experiment.conf.example  # Example experiment config
  001-profile-showdown/      # First experiment
    experiment.conf          # Experiment-specific config
    PLAN.md                  # Experiment design, rationale, how to run
    results/                 # Created at runtime, gitignored
```

## Adding a New Experiment

1. Create a new numbered directory: `002-timeout-tuning/`
2. Copy `bench/experiment.conf.example` to `002-timeout-tuning/experiment.conf`
3. Edit the conf to point at your target repo, spec, profiles
4. Write a `PLAN.md` explaining what you're testing and why
5. Run: `bash bench/scripts/setup-worktrees.sh 002-timeout-tuning/experiment.conf`
6. Run: `bash bench/scripts/run-experiment.sh 002-timeout-tuning/experiment.conf <profile>`
7. Analyze: `python3 bench/scripts/analyze.py 002-timeout-tuning/experiment.conf`

## Conventions

- Experiment directories are numbered (`NNN-short-name`) to preserve order.
- `experiment.conf` is a bash-sourceable key=value file.
- `results/` inside each experiment is gitignored (telemetry can be large).
- Scripts never mutate the target repo's main/default branch.
- Each profile run gets its own git worktree for full isolation.
