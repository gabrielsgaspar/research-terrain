# Budget and dates

The budget stops new steps; it never stops one in flight. Size it so that
the planned steps fit, with room for one fix round each, and no more: a
loose budget is how forking paths creep in.

## Fields

- `max_tasks`: issues filed. Usually the number of task steps. It must be
  at least that number (the validator checks).
- `max_explore_runs` and `max_pipeline_runs`: dispatches. Usually the
  number of such steps. A failed run is not retried by the tick, so there
  is no need for spare runs.
- `max_model_jobs`: planner, builder and reviewer jobs, counted from their
  comments (a plan comment is one job; each review counts two, the build
  before it and the review itself). A clean task takes 3 (plan, build,
  review); each fix round adds 2; the harness stops a PR at three fix rounds.
  Rule of thumb: 5 per task, 7 for a task that reads new data. The close-out
  task is not counted against the budget.
- `end_by`: no new step starts after this day. At most 31 days after
  `created`.

## Estimating from this repository's history

```bash
uv run python .claude/skills/campaign-design/scripts/budget.py --tasks 2 --explore-runs 2 --pipeline-runs 0
```

It reads recent agent issues and runs with `gh` (plan and review comments
per task, how long tasks and explore runs took) and prints suggested
numbers. If `gh` is not available it falls back to the rules of thumb above
and says so. Treat its output as a starting point to discuss.

## Pacing

The tick runs after each workflow a step waits on ends (Explore run, Data
pipeline, CI, Agent plan, Agent build and Agent review), with an hourly
backup for a missed event (`.github/workflows/campaign-tick.yml`). It
starts at most one new step per campaign per tick. One task is in flight
per campaign and one run across all campaigns. So, roughly:

| Stage | What starts the next tick |
| --- | --- |
| File the issue; the planner answers | Agent plan ends |
| Move to build; build, CI and review | Agent build, CI, then Agent review end |
| Merge; start the run | CI on main ends after the merge |
| Run, record PR, CI; merge the record | Explore run or Data pipeline ends, then CI |
| Apply the kill rules | same tick as the merge |

A step therefore waits mostly on its own workflows, not on the clock. For
how long those take, use the hours `scripts/budget.py` reports from recent
issues and runs; do not guess. Its `end_by` estimate still counts six
three-hour ticks per task and run, so it errs long: say so when you
propose `end_by`. Add a day for the close-out (Gabriel reads and merges
it) and a day of slack per three steps. Usage limits on the subscription
can block a job; a blocked step waits 24 hours for Gabriel before the
campaign closes out, so leave room for that too.

## Explaining the budget to Gabriel

One line per number, for example: "max_model_jobs 12: two tasks at about 5
jobs each, plus 2 for one fix round." Ask if he wants it tighter.
