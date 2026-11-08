"""Suggest a campaign budget from this repository's recent agent history.

    uv run python .claude/skills/campaign-design/scripts/budget.py
        --tasks N --explore-runs N [--pipeline-runs N] [--sample 15]

Reads, with the `gh` CLI (already logged in), the most recent closed issues
labelled `explore` or `campaign` that have an agent pull request: plan
comments per task, agent reviews per pull request, and hours from filing to
merge; and recent explore-run durations. Prints medians, the 90th
percentile and suggested budget numbers. Without `gh`, or if a call fails,
it uses the rules of thumb in references/budget.md and says so.
Never prints a token.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
import subprocess
import sys

JOBS_PER_TASK = 5  # rule of thumb: plan, build, review, one fix round
RUN_HOURS = 1.0
TICK_HOURS = 3
TICKS_PER_TASK_AND_RUN = 6


def gh(path: str) -> object:
    out = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return json.loads(out.stdout)


def repo() -> str:
    out = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return out.stdout.strip()


def hours(start: str, end: str) -> float:
    a = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    b = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (b - a).total_seconds() / 3600


def p90(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(0.9 * len(xs)) - 1)]


def history(sample: int) -> dict[str, list[float]]:
    r = repo()
    jobs: list[float] = []
    task_hours: list[float] = []
    for label in ("explore", "campaign"):
        issues = gh(f"repos/{r}/issues?state=closed&labels={label}&per_page={sample}")
        for issue in issues:
            if "pull_request" in issue:
                continue
            n = issue["number"]
            owner = r.split("/")[0]
            prs = gh(f"repos/{r}/pulls?state=closed&head={owner}:agent/issue-{n}")
            merged = [p for p in prs if p.get("merged_at")]
            if not merged:
                continue
            comments = gh(f"repos/{r}/issues/{n}/comments?per_page=100")
            plans = sum(1 for c in comments if (c.get("body") or "").startswith("## Agent plan: "))
            pr = merged[-1]
            pr_comments = gh(f"repos/{r}/issues/{pr['number']}/comments?per_page=100")
            reviews = sum(
                1 for c in pr_comments if (c.get("body") or "").startswith("## Agent review: ")
            )
            jobs.append(plans + 2 * reviews)
            task_hours.append(hours(issue["created_at"], pr["merged_at"]))
    runs = gh(f"repos/{r}/actions/workflows/explore-run.yml/runs?status=success&per_page={sample}")
    run_hours = [
        hours(x["run_started_at"], x["updated_at"])
        for x in runs.get("workflow_runs", [])
        if x.get("run_started_at")
    ]
    return {"jobs": jobs, "task_hours": task_hours, "run_hours": run_hours}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--explore-runs", type=int, required=True)
    parser.add_argument("--pipeline-runs", type=int, default=0)
    parser.add_argument("--sample", type=int, default=15)
    args = parser.parse_args(argv)

    per_task = float(JOBS_PER_TASK)
    run_h = RUN_HOURS
    try:
        h = history(args.sample)
        if h["jobs"]:
            print(
                f"Agent tasks sampled: {len(h['jobs'])}. Model jobs per task: median "
                f"{statistics.median(h['jobs']):.0f}, 90th percentile {p90(h['jobs']):.0f}."
            )
            print(
                f"Hours from filing to merge (by hand, before campaigns): median "
                f"{statistics.median(h['task_hours']):.1f}."
            )
            per_task = max(per_task, p90(h["jobs"]))
        if h["run_hours"]:
            run_h = p90(h["run_hours"])
            print(
                f"Explore runs sampled: {len(h['run_hours'])}. Hours per run: median "
                f"{statistics.median(h['run_hours']):.1f}, 90th percentile {run_h:.1f}."
            )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        print(f"Could not read history with gh ({exc.__class__.__name__}); using rules of thumb.")

    steps = args.tasks + args.explore_runs + args.pipeline_runs
    jobs = math.ceil(args.tasks * per_task)
    pairs = max(args.tasks, args.explore_runs + args.pipeline_runs)
    tick_hours = pairs * TICKS_PER_TASK_AND_RUN * TICK_HOURS + pairs * run_h
    days = math.ceil(tick_hours / 24) + 1 + math.ceil(steps / 3)
    print()
    print("Suggested budget (a starting point to discuss):")
    print(f"  max_tasks: {args.tasks}")
    print(f"  max_explore_runs: {args.explore_runs}")
    print(f"  max_pipeline_runs: {args.pipeline_runs}")
    print(f"  max_model_jobs: {jobs}   ({args.tasks} task(s) x {per_task:.0f} jobs)")
    print(f"  end_by: {days} day(s) from today, at most 31")
    print(f"          (about {tick_hours:.0f} hours of ticks and runs, plus a day for the")
    print("          close-out and a day of slack per three steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
