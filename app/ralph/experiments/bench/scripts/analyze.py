#!/usr/bin/env python3
"""analyze.py <experiment.conf> [--json] [--profile PROFILE]

Aggregates all telemetry from a completed (or in-progress) experiment
and prints a multi-section comparison report.

Data sources:
  - results/_ledger/runs.jsonl       (run-level telemetry)
  - results/_ledger/iterations.jsonl  (iteration-level telemetry)
  - results/<profile>/               (per-run collected data)

Output sections:
  1. Run comparison table
  2. Per-profile stage breakdown
  3. Quota impact analysis
  4. Efficiency ranking
  5. Correctness matrix
  6. Recommendations
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


# ── Formatting helpers ──────────────────────────────────────────────


def fmt_duration(s: float) -> str:
    m, sec = int(s) // 60, int(s) % 60
    if m >= 60:
        h, m = m // 60, m % 60
        return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_cost(c: float) -> str:
    if c == 0:
        return "$0.0000"
    return f"${c:.4f}"


# ── Config loading ──────────────────────────────────────────────────


def load_conf(path: str) -> dict:
    """Parse a bash-style KEY=VALUE config file."""
    conf = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Expand $HOME
            val = val.replace("$HOME", os.path.expanduser("~"))
            conf[key] = val
    return conf


# ── Data loading ────────────────────────────────────────────────────


def load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# ── Section printers ────────────────────────────────────────────────


def section_header(num: int, title: str):
    print(f"\n{'=' * 90}")
    print(f"SECTION {num}: {title}")
    print(f"{'=' * 90}\n")


def print_run_table(runs: list[dict]):
    section_header(1, "RUN COMPARISON TABLE")
    hdr = (
        f"{'Profile':<16} {'Iter':>4} {'Time':>7} {'Cost':>9} "
        f"{'Tok(in)':>8} {'Tok(out)':>8} {'Done':>4}/{'Tot':<4} "
        f"{'Kill':>4} {'API(R)':>6} {'Exit':<16}"
    )
    print(hdr)
    print("-" * len(hdr))

    for r in sorted(runs, key=lambda x: x.get("profile", "")):
        p = r.get("profile", "?")
        it = r.get("iterations", 0)
        dur = r.get("duration_s", 0)
        cost = r.get("cost", 0)
        tok = r.get("tokens", {})
        tok_in = tok.get("input", 0) + tok.get("cached", 0)
        tok_out = tok.get("output", 0)
        tasks = r.get("tasks", {})
        done = tasks.get("completed", 0)
        total = tasks.get("total", 0)
        kills_d = r.get("kills", {})
        kills = sum(kills_d.values())
        api_r = r.get("api_calls", {}).get("remote", 0)
        exit_r = r.get("exit_reason", "?")

        print(
            f"{p:<16} {it:>4} {fmt_duration(dur):>7} {fmt_cost(cost):>9} "
            f"{fmt_tokens(tok_in):>8} {fmt_tokens(tok_out):>8} "
            f"{done:>4}/{total:<4} {kills:>4} {api_r:>6} {exit_r:<16}"
        )


def print_stage_breakdown(runs: list[dict], iters: list[dict]):
    section_header(2, "PER-PROFILE STAGE BREAKDOWN")

    run_profiles = {r["run_id"]: r.get("profile", "?") for r in runs}

    profile_stages: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "count": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0,
                "duration_s": 0.0, "successes": 0, "failures": 0, "kills": 0,
                "precheck_skips": 0, "validation_retries": 0,
            }
        )
    )

    for it in iters:
        profile = run_profiles.get(it.get("run_id", ""), "?")
        stage = it.get("stage", "?")
        s = profile_stages[profile][stage]
        s["count"] += 1
        s["cost"] += it.get("cost", 0)
        t = it.get("tokens", {})
        s["tokens_in"] += t.get("input", 0) + t.get("cached", 0)
        s["tokens_out"] += t.get("output", 0)
        s["duration_s"] += it.get("duration_s", 0)
        outcome = it.get("outcome", "")
        if outcome == "success":
            s["successes"] += 1
        elif outcome == "failure":
            s["failures"] += 1
        if it.get("kill_reason"):
            s["kills"] += 1
        if it.get("precheck_accepted"):
            s["precheck_skips"] += 1
        s["validation_retries"] += it.get("validation_retries", 0)

    for profile in sorted(profile_stages):
        print(f"  Profile: {profile}")
        hdr = (
            f"  {'Stage':<14} {'#':>4} {'Cost':>8} {'Tok In':>8} "
            f"{'Tok Out':>8} {'Time':>7} {'OK':>3} {'Fail':>4} "
            f"{'Kill':>4} {'AutoAcc':>7} {'VRetry':>6}"
        )
        print(hdr)
        print(f"  {'-' * (len(hdr) - 2)}")
        for stage in ["INVESTIGATE", "BUILD", "VERIFY", "DECOMPOSE"]:
            s = profile_stages[profile].get(stage)
            if not s or s["count"] == 0:
                continue
            print(
                f"  {stage:<14} {s['count']:>4} {fmt_cost(s['cost']):>8} "
                f"{fmt_tokens(s['tokens_in']):>8} {fmt_tokens(s['tokens_out']):>8} "
                f"{fmt_duration(s['duration_s']):>7} {s['successes']:>3} "
                f"{s['failures']:>4} {s['kills']:>4} {s['precheck_skips']:>7} "
                f"{s['validation_retries']:>6}"
            )
        print()


def print_quota_impact(runs: list[dict], iters: list[dict]):
    section_header(3, "QUOTA IMPACT (Claude Max Subscription)")
    hdr = (
        f"{'Profile':<16} {'Remote':>6} {'Local':>5} {'%Local':>6} "
        f"{'CloudTok':>10} {'LocalTok':>10} {'CacheHit%':>9}"
    )
    print(hdr)
    print("-" * len(hdr))

    for run in sorted(runs, key=lambda x: x.get("profile", "")):
        profile = run.get("profile", "?")
        api_remote = run.get("api_calls", {}).get("remote", 0)
        api_local = run.get("api_calls", {}).get("local", 0)
        total_api = api_remote + api_local
        pct_local = (api_local / total_api * 100) if total_api > 0 else 0

        cloud_tokens = 0
        local_tokens = 0
        cache_tokens = 0
        total_input = 0
        for it in iters:
            if it.get("run_id") != run["run_id"]:
                continue
            t = it.get("tokens", {})
            inp = t.get("input", 0)
            cached = t.get("cached", 0)
            out = t.get("output", 0)
            total_input += inp + cached
            cache_tokens += cached
            if it.get("is_local"):
                local_tokens += inp + cached + out
            else:
                cloud_tokens += inp + cached + out

        cache_pct = (cache_tokens / total_input * 100) if total_input > 0 else 0
        print(
            f"{profile:<16} {api_remote:>6} {api_local:>5} {pct_local:>5.0f}% "
            f"{fmt_tokens(cloud_tokens):>10} {fmt_tokens(local_tokens):>10} "
            f"{cache_pct:>8.0f}%"
        )

    print()
    print("  %Local  = fraction of API calls offloaded to local model (free)")
    print("  CacheHit% = fraction of input tokens served from prompt cache")


def compute_scores(runs: list[dict]) -> list[tuple]:
    """Compute efficiency scores. Returns sorted list of tuples."""
    if not runs:
        return []

    max_cost = max((r.get("cost", 0) for r in runs), default=0.001) or 0.001
    max_time = max((r.get("duration_s", 0) for r in runs), default=1) or 1

    scored = []
    for r in runs:
        profile = r.get("profile", "?")
        completed = r.get("tasks", {}).get("completed", 0)
        total = r.get("tasks", {}).get("total", 1) or 1
        rate = completed / total
        cost = r.get("cost", 0)
        duration = r.get("duration_s", 0)
        api_remote = r.get("api_calls", {}).get("remote", 0)

        norm_cost = cost / max_cost
        norm_time = duration / max_time
        # Efficiency: completion rate relative to resource usage
        efficiency = rate / (0.3 * norm_cost + 0.3 * norm_time + 0.01)

        # Kill penalty: -10% per kill, max -50%
        kills_d = r.get("kills", {})
        total_kills = sum(kills_d.values())
        if total_kills > 0:
            efficiency *= 1 - 0.1 * min(total_kills, 5)

        scored.append((
            efficiency, profile, completed, total, rate,
            cost, duration, api_remote, total_kills,
        ))

    scored.sort(key=lambda x: -x[0])
    return scored


def print_efficiency_ranking(runs: list[dict]):
    section_header(4, "EFFICIENCY RANKING")

    scored = compute_scores(runs)
    if not scored:
        print("  No runs to rank.")
        return

    hdr = (
        f"{'Rank':>4} {'Profile':<16} {'Done':>4} {'Total':>5} {'Rate':>6} "
        f"{'Cost':>9} {'Time':>7} {'API(R)':>6} {'Kills':>5} {'Score':>7}"
    )
    print(hdr)
    print("-" * len(hdr))

    for rank, (eff, prof, done, total, rate, cost, dur, api_r, kills) in enumerate(scored, 1):
        print(
            f"{rank:>4} {prof:<16} {done:>4} {total:>5} {rate:>5.0%} "
            f"{fmt_cost(cost):>9} {fmt_duration(dur):>7} {api_r:>6} "
            f"{kills:>5} {eff:>7.2f}"
        )

    print()
    print("  Score = completion_rate / (0.3 * norm_cost + 0.3 * norm_time + 0.01)")
    print("  Kill penalty: -10% per kill (max -50%)")


def print_correctness_matrix(results_dir: Path, profiles: list[str]):
    section_header(5, "CORRECTNESS MATRIX")
    hdr = f"{'Profile':<16} {'Build':>7} {'Test':>7} {'Commits':>7} {'Lines +/-':>12}"

    # Detect gate check names from any profile's results
    gate_names = []
    for profile in profiles:
        report = results_dir / profile
        if not report.exists():
            continue
        for f in report.iterdir():
            if f.name.startswith("gate-") and f.name.endswith("-exit.txt"):
                name = f.name[5:-9]  # strip "gate-" and "-exit.txt"
                if name not in gate_names:
                    gate_names.append(name)

    for name in gate_names:
        hdr += f" {name:>12}"

    print(hdr)
    print("-" * len(hdr))

    for profile in profiles:
        report = results_dir / profile
        if not report.exists():
            cols = [f"{profile:<16}", f"{'N/A':>7}", f"{'N/A':>7}", f"{'N/A':>7}", f"{'N/A':>12}"]
            for _ in gate_names:
                cols.append(f"{'N/A':>12}")
            print(" ".join(cols))
            continue

        # Build
        build_f = report / "build-exit.txt"
        if build_f.exists():
            code = build_f.read_text().strip()
            build_s = "PASS" if code == "0" else f"FAIL({code})"
        else:
            build_s = "N/A"

        # Test
        test_f = report / "test-exit.txt"
        if test_f.exists():
            code = test_f.read_text().strip()
            test_s = "PASS" if code == "0" else f"FAIL({code})"
        else:
            test_s = "N/A"

        # Commits
        git_log_f = report / "git-log.txt"
        if git_log_f.exists():
            commits = len([l for l in git_log_f.read_text().splitlines() if l.strip()])
        else:
            commits = 0

        # Lines changed
        shortstat_f = report / "git-shortstat.txt"
        lines_s = "N/A"
        if shortstat_f.exists():
            text = shortstat_f.read_text().strip()
            if text:
                ins = del_ = 0
                for part in text.split(","):
                    part = part.strip()
                    if "insertion" in part:
                        ins = int(part.split()[0])
                    elif "deletion" in part:
                        del_ = int(part.split()[0])
                if ins or del_:
                    lines_s = f"+{ins}/-{del_}"

        row = f"{profile:<16} {build_s:>7} {test_s:>7} {commits:>7} {lines_s:>12}"

        # Gate checks
        for name in gate_names:
            gate_f = report / f"gate-{name}-exit.txt"
            if gate_f.exists():
                code = gate_f.read_text().strip()
                gate_s = "PASS" if code == "0" else f"FAIL({code})"
            else:
                gate_s = "N/A"
            row += f" {gate_s:>12}"

        print(row)


def print_recommendations(runs: list[dict]):
    section_header(6, "RECOMMENDATIONS")

    scored = compute_scores(runs)
    if not scored:
        print("  No data for recommendations.")
        return

    best_eff = scored[0]
    print(
        f"  Best efficiency:     {best_eff[1]} "
        f"(score: {best_eff[0]:.2f}, {best_eff[2]}/{best_eff[3]} tasks, "
        f"{fmt_cost(best_eff[5])})"
    )

    best_done = max(runs, key=lambda r: r.get("tasks", {}).get("completed", 0))
    print(
        f"  Most tasks done:     {best_done.get('profile')} "
        f"({best_done.get('tasks', {}).get('completed', 0)} tasks)"
    )

    cheapest = min(runs, key=lambda r: r.get("cost", float("inf")))
    print(
        f"  Cheapest:            {cheapest.get('profile')} "
        f"({fmt_cost(cheapest.get('cost', 0))})"
    )

    least_remote = min(
        runs, key=lambda r: r.get("api_calls", {}).get("remote", float("inf"))
    )
    print(
        f"  Lowest quota usage:  {least_remote.get('profile')} "
        f"({least_remote.get('api_calls', {}).get('remote', 0)} remote calls)"
    )

    no_kill_runs = [r for r in runs if sum(r.get("kills", {}).values()) == 0]
    if no_kill_runs:
        best_unattended = max(
            no_kill_runs, key=lambda r: r.get("tasks", {}).get("completed", 0)
        )
        print(
            f"  Best unattended:     {best_unattended.get('profile')} "
            f"({best_unattended.get('tasks', {}).get('completed', 0)} tasks, "
            f"zero kills)"
        )
    else:
        print("  Best unattended:     No zero-kill runs found")

    print()
    print("  Decision framework:")
    print("    Max quality, cost no object  -> highest 'Done' with PASS build/test")
    print("    Best bang for buck           -> highest 'Score' in efficiency ranking")
    print("    Minimal quota burn           -> highest 'Done' with highest '%Local'")
    print("    Overnight unattended         -> highest 'Done' with zero kills")


# ── Main ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a ralph experiment's results."
    )
    parser.add_argument("conf", help="Path to experiment.conf")
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw run data as JSON instead of tables"
    )
    parser.add_argument(
        "--profile", default=None,
        help="Filter to a single profile"
    )
    args = parser.parse_args()

    conf = load_conf(args.conf)
    exp_dir = Path(args.conf).resolve().parent

    profiles = conf.get("PROFILES", "").split()
    results_dir = Path(
        conf.get("RESULTS_DIR", "").replace("$HOME", os.path.expanduser("~"))
        or str(exp_dir / "results")
    )
    ralph_log_dir = Path(
        conf.get("RALPH_LOG_DIR", "").replace("$HOME", os.path.expanduser("~"))
        or "/tmp/ralph-logs"
    )

    # Ensure ledger snapshot exists
    ledger_dir = results_dir / "_ledger"
    if not ledger_dir.exists():
        ledger_dir.mkdir(parents=True, exist_ok=True)
        # Copy from ralph log dir
        for name in ["runs.jsonl", "iterations.jsonl"]:
            src = ralph_log_dir / name
            dst = ledger_dir / name
            if src.exists() and not dst.exists():
                dst.write_text(src.read_text())

    runs = load_jsonl(ledger_dir / "runs.jsonl")
    iters = load_jsonl(ledger_dir / "iterations.jsonl")

    if not runs:
        # Try loading directly from ralph log dir
        runs = load_jsonl(ralph_log_dir / "runs.jsonl")
        iters = load_jsonl(ralph_log_dir / "iterations.jsonl")

    if not runs:
        print("No run data found. Have any experiments been completed?")
        print(f"  Looked in: {ledger_dir}")
        print(f"         and: {ralph_log_dir}")
        sys.exit(1)

    # Filter by profile if requested
    if args.profile:
        runs = [r for r in runs if r.get("profile") == args.profile]
        if not runs:
            print(f"No runs found for profile: {args.profile}")
            sys.exit(1)

    # Filter to only profiles in this experiment
    exp_profiles = set(profiles)
    runs = [r for r in runs if r.get("profile", "") in exp_profiles]
    run_ids = {r["run_id"] for r in runs}
    iters = [i for i in iters if i.get("run_id", "") in run_ids]

    if args.json:
        print(json.dumps(runs, indent=2))
        return

    # Print report header
    print("=" * 90)
    print(f"RALPH EXPERIMENT REPORT: {exp_dir.name}")
    print("=" * 90)
    print(f"  Target:   {conf.get('TARGET_REPO', '?')}")
    print(f"  Spec:     {conf.get('SPEC', '?')}")
    print(f"  Base ref: {conf.get('BASE_REF', '?')}")
    print(f"  Profiles: {' '.join(profiles)}")
    print(f"  Runs:     {len(runs)}")
    print(f"  Iters:    {len(iters)}")

    print_run_table(runs)
    print_stage_breakdown(runs, iters)
    print_quota_impact(runs, iters)
    print_efficiency_ranking(runs)
    print_correctness_matrix(results_dir, profiles)
    print_recommendations(runs)

    print(f"\n{'=' * 90}")
    print(f"Full data: {results_dir}")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    main()
