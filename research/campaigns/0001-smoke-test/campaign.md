---
id: "0001"
title: "Smoke test: re-run idea 0003's power check"
status: done
idea: "0003"
owner: gabrielsgaspar
created: 2026-11-08
end_by: 2026-11-15
budget:
  max_tasks: 0
  max_explore_runs: 1
  max_pipeline_runs: 0
  max_model_jobs: 0
referee_not_applicable_ok: [R5]
datasets: []
steps:
  - id: s1
    kind: explore_run
    script: 0003_mayor_power
    after: []
    kill_rules:
      - id: k1
        says: "Power at decision 0007's effect is below 80% at the 1% window"
        field: windows.1%.power
        op: "<"
        value: 0.8
        confirmed: true
    on_kill: skip_dependents
---

# 0001: Smoke test: re-run idea 0003's power check

## Question

Does the campaign machinery work end to end on GitHub without Gabriel? The
pilot re-runs a check whose answer is known, so any difference points at the
machinery, not the research: the tick opens the tracking issue, dispatches
the run, the gate checks the record pull request, the tick merges it, the
kill rule is applied by code, and the close-out task produces a report for
Gabriel (decision 0010, "How we will know it works").

## Already known

`explore/0003_mayor_power.py` ran once, as run 42367009833
(`research/explore-runs/0003/42367009833.md`): power at decision 0007's
effect is 4.4%, 5.2% and 7.2% at the 0.5%, 1% and 2% windows (45, 80 and
157 races). Idea 0003 is dead by its kill criterion 1
(`research/ideas/0003-mayoral-close-races.md`). The script has a fixed seed, so a re-run on
the same inputs must give the same numbers. Nothing here is new research;
the campaign is a repeat by design.

## Steps and why

- **s1** (explore run): re-run `0003_mayor_power` on main through
  `explore-run`, with the campaign and step recorded. It is the only step,
  so the campaign tests dispatch, record, gate, merge, kill rule and
  close-out without a model job before the close-out. Expected: the same
  numbers as run 42367009833, so power about 0.052 at 1% and the kill rule
  met.

## Kill rules and why

- **k1**: `windows.1%.power < 0.8` kills s1. The threshold is the usual 80%
  power and the field is the one the script already writes. Run 42367009833
  had 0.052, far from the margin, so the expected verdict is "killed". A
  verdict of "not killed", or a missing field, means the machinery or the
  script changed, and is a reason to stop and look.

## Budget and why

One explore run, for s1. No tasks, pipeline runs or model jobs: the step
re-runs a merged script. The close-out task is filed by the tick whatever
the budget and uses the harness (about three model jobs). The end date is
seven days after creation; the campaign should finish in a few ticks.

## New data

None. The run reads only what run 42367009833 read.

## What would change the plan

Any difference from run 42367009833 in the race counts or the power, a
record pull request that the gate refuses, a merge that does not happen, or
a ledger entry that does not match the run. Any of these means the campaign
machinery needs a fix before a real campaign starts.

## Provenance

- The campaign, its single step and its budget: the worked example in
  `.claude/skills/campaign-design/references/writing-the-files.md`, chosen
  by Gabriel for the smoke test on 2026-11-08.
- Kill rule k1 (field, comparison and 0.8): the package's example, confirmed
  by Gabriel on 2026-11-08.
- The expected power (about 0.052 at 1%): run 42367009833.
