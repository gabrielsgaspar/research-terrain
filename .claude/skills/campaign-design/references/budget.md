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

The tick runs every three hours and moves each campaign at most one step
per tick. One task is in flight per campaign and one run across all
campaigns. So, roughly:

| Stage | Ticks |
| --- | --- |
| File the issue; the planner answers | 1 |
| Move to build; build, CI and review | 1 to 2 |
| Merge; start the run | 1 |
| Run, record PR, CI; merge the record | 1 to 2 |
| Apply the kill rules | same tick as the merge |

A task and its run take about 4 to 6 ticks, so 12 to 18 hours. Add a day for
the close-out, and a day of slack per three steps. Usage limits on the
subscription can block a job; a blocked step waits 24 hours for Gabriel
before the campaign closes out, so leave room for that too.

## Explaining the budget to Gabriel

One line per number, for example: "max_model_jobs 12: two tasks at about 5
jobs each, plus 2 for one fix round." Ask if he wants it tighter.
