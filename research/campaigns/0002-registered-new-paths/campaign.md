---
id: "0002"
title: "Check the registered analysis's new paths on real data, without estimates"
status: active
idea: "0001"
owner: gabrielsgaspar
created: 2026-11-08
end_by: 2026-11-11
budget:
  max_tasks: 1
  max_explore_runs: 1
  max_pipeline_runs: 0
  max_model_jobs: 5
referee_not_applicable_ok: [R5]
datasets: []
steps:
  - id: s1
    kind: task
    type: explore
    draft: drafts/s1.md
    allowed_paths:
      - explore/0001_registered_paths_check.py
      - tests/test_explore_registered_paths_check.py
    after: []
  - id: s2
    kind: explore_run
    script: 0001_registered_paths_check
    after: [s1]
    kill_rules:
      - id: k1
        says: "Check 1 fails: in some election 2008-2020 no close pair has exactly one incumbent"
        field: checks.c1.pass
        op: "!="
        value: true
        confirmed: true
      - id: k2
        says: "Check 2 fails: an adjusted estimate does not use the unadjusted cells, or a Z term is not s times its D term, or the Z pairs are not a subset of the D pairs"
        field: checks.c2.pass
        op: "!="
        value: true
        confirmed: true
      - id: k3
        says: "Check 3 fails: under re-flip draw 1 (seed 20261106) a Z term changes, or a flipped pair's D term does not change sign"
        field: checks.c3.pass
        op: "!="
        value: true
        confirmed: true
      - id: k4
        says: "Check 4 fails: the alignment kinds do not add up to the pairs, or the alignment components do not add up to the D term exactly"
        field: checks.c4.pass
        op: "!="
        value: true
        confirmed: true
      - id: k5
        says: "Check 5 fails: direct_pre's terms are not direct's, or its cells are not exactly the direct cells with every pre-election year"
        field: checks.c5.pass
        op: "!="
        value: true
        confirmed: true
      - id: k6
        says: "Check 6 fails: a value of the new paths is NaN or infinite without being a documented null"
        field: checks.c6.pass
        op: "!="
        value: true
        confirmed: true
      - id: k7
        says: "Check 7 fails: a balance covariate has no winner-minus-loser difference in some election, or the omnibus p is missing"
        field: checks.c7.pass
        op: "!="
        value: true
        confirmed: true
      - id: k8
        says: "Fewer than 200 close pairs at 0.50%, pooled 2008-2020, have exactly one incumbent (not a code fault: the incumbency-adjusted fallback looks thin)"
        field: checks.c1.counts.pooled.one_incumbent
        op: "<"
        value: 200
        confirmed: true
    on_kill: stop
---

# 0002: Check the registered analysis's new paths on real data, without estimates

## Question

Do the parts of idea 0001's registered analysis
(`src/terrain/registered/r0001/analysis.py`) that no earlier run has behave
correctly on real data? Those parts are the incumbency-adjusted estimates
(`direct_adj`, `ring2_adj`, `ring5_adj`, `direct_pre_adj`, built from Z), the
direct placebo (`direct_pre`), the alignment split (`align`) and the balance
table (`balance`). The campaign checks them on the exploration half at the
0.50% window against identities they must satisfy, and reports only counts
and pass or fail, never an estimate. It is a check of frozen code before
registration, not a result. A fail blocks registration until Gabriel fixes the
frozen code outside any campaign.

## Already known

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Registered core reproduces the explore numbers at 0.50% | explored | run 42476480500 (`research/explore-runs/0001/42476480500.md`): 875 numbers compared, 0 differ |
| Z-adjusted estimates on real data | new | computed but not compared in run 42476480500 (`research/lessons.md`, 2026-11-08) |
| Direct placebo through the registered path | partly explored | the placebo itself: run 42193625417; the registered path is not checked |
| Alignment split adds up | partly explored | pair counts by kind at 0.25%: run 42384829937 (idea 0004); the components summing to D is new |
| Balance through the registered path | partly explored | balance by window: run 42366460941 (decision 0008); the registered path is not checked |
| Real data has pairs with exactly one incumbent in every election | new | needed because `direct_adj` is decision 0009's fallback (point 5) |

The check is about code, not a research question, so the Zotero notes and the
web were not searched. Task 40 (`harness/issue-drafts/40-explore-registered-new-paths.md`)
was never filed as an issue; `drafts/s1.md` replaces it.

## Steps and why

- **s1** (task, explore): writes `explore/0001_registered_paths_check.py` and
  its tests from `drafts/s1.md`. The tests run the seven checks on the
  synthetic world (`tests/world_0001.py`, imported, not changed) and plant
  four faults, so the checker is checked before it reads real data. If the
  planner finds that a check cannot be made without changing the frozen code,
  the step blocks and the answer is Gabriel's, outside the campaign.
- **s2** (explore run): runs the script once on the exploration half at
  0.50%. All seven checks passing ticks one item before registration. Any
  fail means the frozen code or the checker is wrong, and Gabriel looks before
  anything else happens. 0.25%, the registered window, is never run: the
  analysis refuses it before registration and the script refuses it too.

## Kill rules and why

- **k1-k7** (`checks.cN.pass != true`): one rule per check, so the ledger
  shows which check fired; the record does not say why. Written as `!= true`
  rather than `== false`, so that `false`, `null` or text all kill the step;
  a missing key makes it unreadable, so a script that skips a check cannot
  pass. Each threshold is the check's own pass or fail, so no rule is stricter
  than the check. Expected: none fires.
- **k8** (`checks.c1.counts.pooled.one_incumbent < 200`): the one rule about
  the research rather than the code. Z, and with it the incumbency-adjusted
  fallback of decision 0009 (point 5), rests only on pairs with exactly one
  incumbent. 200 is borrowed from idea 0001's kill criterion 1 (at least 200
  close-pair candidates per constituency type); it is a design count, not a
  power result, as decision 0007's power is for D, not Z. The count is of
  treatments, not outcomes, and no run had computed it when the rule was set.
  At the margin: the registered 0.25% window keeps fewer pairs (kill criterion
  1's count fell to 61% from 0.50% to 0.25% in run 42384056410), so a pass
  near 200 at 0.50% is a warning for 0.25%.
- `on_kill: stop`: s2 is the last step, so this only gives the report the
  clearer reason ("a kill rule stopped it").

## Budget and why

`scripts/budget.py` (12 recent agent tasks: median 3 model jobs, 90th
percentile 4) suggested one task, one run and 5 model jobs: 3 for a clean
task plus one fix round of 2. Gabriel chose that over a looser 7 jobs and 7
days. The end date is three days after creation: a task and its run take
about 4 to 6 ticks, plus a day for the close-out. A step blocked by a usage
limit waits 24 hours for Gabriel, which uses most of the slack; a second
fix round or a second block ends the campaign, and the close-out reports why.

## New data

None. s2 reads what run 42476480500 read, through the analysis's own
`Reader`: the exploration half of the candidate, result, polling-place,
tenure, coalition, grid, exposure and `cell_outcomes` tables in
`data/catalog.yaml`.

## What would change the plan

- s1 blocks because a check needs a change to `src/terrain/registered/`:
  the fix is Gabriel's, and the check comes back as a new campaign after it.
- Any of k1-k7 fires: look at the frozen code and the checker before
  registration; do not re-run until the cause is known.
- k8 fires, or the count is near 200: reconsider whether the
  incumbency-adjusted estimate can be the fallback at 0.25% before
  registering decision 0009's point 5 as written.
- The run touches the registered window, `sealed/` or `confirm/`, or any
  estimate appears in the record: stop everything.

## Provenance

- The idea and both steps: stated by Gabriel (task 40, drafted by Claude Code
  for him on 2026-11-08), confirmed as one task and one run on 2026-11-08.
- Leaving out other windows and a separate step for check 1: suggested by
  Claude, accepted by Gabriel on 2026-11-08.
- `on_kill: stop`: chosen by Gabriel on 2026-11-08.
- Kill rules k1-k7 (one per check, `!= true`): suggested by Claude, chosen by
  Gabriel (option 3 with k8) and confirmed on 2026-11-08.
- Kill rule k8 and its value 200: the rule chosen by Gabriel; the value
  suggested by Claude from idea 0001's kill criterion 1, chosen by Gabriel
  over 400 and 6 and confirmed on 2026-11-08. No run had computed the count.
- Budget (1 task, 1 run, 0 pipeline runs, 5 model jobs) and end date
  2026-11-11: stated by Gabriel on 2026-11-08, tighter than Claude's
  suggestion of 7 jobs and 7 days.
- The change from task 40 that a fail is caught by the kill rules, not by
  leaving the record unmerged: suggested by Claude, accepted by Gabriel on
  2026-11-08.
