---
id: "0003"
title: "Count close pairs with exactly one incumbent at the registered 0.25% window"
status: active
idea: "0001"
owner: gabrielsgaspar
created: 2026-11-09
end_by: 2026-11-12
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
      - explore/0001_one_incumbent_pairs.py
      - tests/test_explore_one_incumbent_pairs.py
    after: []
  - id: s2
    kind: explore_run
    script: 0001_one_incumbent_pairs
    after: [s1]
    kill_rules:
      - id: k1
        says: "Fewer than 200 close pairs at 0.25%, pooled 2008-2020, have exactly one incumbent (the incumbency-adjusted fallback looks thin at the registered window)"
        field: counts.pooled.one_incumbent
        op: "<"
        value: 200
        confirmed: true
    on_kill: stop
---

# 0003: Count close pairs with exactly one incumbent at the registered 0.25% window

## Question

Is the incumbency-adjusted fallback thin at the registered window? Decision
0009 (point 5) makes the incumbency-adjusted direct estimate the estimate
that kill criterion 4 is read on if the confirmation half fails its balance
test. Its Z term draws only on close pairs where exactly one side held the
seat before. Campaign 0002 counted those pairs at 0.50% (1,294 pooled
2008-2020, run 42514591508), not at 0.25%, the window the plan registers.
This campaign counts them at 0.25% on the exploration half, by election and
pooled 2008-2020, before Gabriel registers. It reports counts only and reads
no outcome data.

## Already known

The novelty check covered the repository only, as Gabriel asked. Zotero and
the web were not searched, since this is a count on the project's own data.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Pairs with exactly one incumbent at 0.50%, 2008-2020 | explored | run 42514591508 (`research/explore-runs/0001/42514591508.md`), campaign 0002 check 1: 1,294 pooled (690 plus, 604 minus) |
| Pairs with exactly one incumbent at 0.25% | new | asked for in campaign 0002's report (`research/campaigns/0002-registered-new-paths/report.md`, "Suggested next variants" and decision 2, option B) and in `research/lessons.md` (2026-11-08); no run has counted it |
| Close pairs at 0.25% on this half | explored | decision 0008, run 42366460941: 2,328 pairs, 2008-2020 (2,869 with 2024) |
| Incumbency balance at 0.25% | partly explored | decision 0008: winners held the seat 2.0 points more often than losers (RI p 0.084). That is a share difference, not a count of one-incumbent pairs |
| How counts shrink from 0.50% to 0.25% | partly explored | kill criterion 1's count fell to 61% (run 42384056410), pairs to 63% (decision 0008) |

Pairs fell to about 63% from 0.50% to 0.25%. If one-incumbent pairs fall by
the same share, the count would be roughly 800, well above 200. That figure
is a projection, not a result. The run settles it.

**Why this is allowed at 0.25%.** The registered analysis refuses 0.25%
before registration (`run_exploration` in
`src/terrain/registered/r0001/analysis.py`; `harness/drafts/pap-draft.md`,
section 7). What is refused is running the registered estimator at that
window. Counts of pairs at 0.25% on the exploration half are already in
decisions 0008 and 0009 and in the plan draft. None of those numbers came
from the registered code. Campaign 0002 treated a call to the registered
module's functions at 0.25% as a way around the guard, so this campaign's
script does not import `terrain.registered` at all. It rebuilds check 1's
definitions from the explore code the registered core was copied from
(`terrain.strongholds`, and `incumbent` in `explore/0001_window.py`, which
is identical to `frozen.incumbent`). A test shows on the synthetic world, at
0.50%, that the result is the same as the registered `incumbent_sign`.

## Steps and why

- **s1** (task, explore): writes `explore/0001_one_incumbent_pairs.py` and
  its tests from `drafts/s1.md`. The tests check three things on the
  synthetic world (`tests/world_0001.py`, imported, not changed): the
  definitions match campaign 0002's check 1, no outcome file is read, and
  the script never imports the registered code.
- **s2** (explore run): runs the script once on the exploration half at
  0.25%. If k1 is not met, the fallback has enough pairs at the registered
  window, and the 0.25% caveat on campaign 0002's tick can be lifted. If k1
  is met, the fallback is thin, and Gabriel reconsiders decision 0009's
  point 5 before registering.

## Kill rules and why

- **k1** (`counts.pooled.one_incumbent < 200`): stated and confirmed by
  Gabriel. It is campaign 0002's k8 moved to the registered window. 200 comes
  from idea 0001's kill criterion 1, a design count (at least 200 close-pair
  candidates per constituency type). It is not a power result: decision
  0007's power is for D, not Z. The field counts treatments, not outcomes,
  and no run has computed it at 0.25%. At the margin, a count just above 200
  passes the rule, but the report should say how few pairs carry each
  election.
- `on_kill: stop`: s2 is the last step, so this only gives the report the
  clearer reason ("a kill rule stopped it").

## Budget and why

`scripts/budget.py` (15 recent agent tasks: median 3 model jobs, 90th
percentile 4) suggests 1 task, 1 run and 5 model jobs: 3 for a clean task
plus one fix round of 2. Gabriel stated the same: 1 task, 1 explore run, 0
pipeline runs, 5 model jobs, ending three days after creation. A task and
its run take about 4 to 6 ticks, plus a day for the close-out. If a usage
limit blocks a step, it waits 24 hours for Gabriel, which uses most of the
slack. A second fix round or a second block ends the campaign, and the
close-out reports why.

## New data

None. s2 reads the exploration half of three built tables already in
`data/catalog.yaml` and `data/manifests/build/`: `tse_candidates`
(`candidates.parquet`), `municipalities` (`municipalities.parquet`) and
`tse_results` (`candidate_votes_<year>.parquet` and
`turnout_<year>.parquet`, 2008-2020). It reads no `cell_outcomes`, grid,
exposure or other outcome file.

## What would change the plan

- s1 blocks because the definitions cannot be matched without the
  registered module: the answer is Gabriel's, outside the campaign.
- The pooled 2008-2020 pairs differ from decision 0008's 2,328: the pair
  definition does not match, so do not use the count until the cause is
  known.
- k1 fires, or the count is near 200, or one election has very few
  one-incumbent pairs: reconsider decision 0009's point 5 before
  registering.
- The run reads an outcome file, `sealed/` or `confirm/`, imports
  `terrain.registered`, or any estimate appears in the record: stop
  everything.

## Provenance

- The idea, its purpose and both steps (one explore task, one explore run):
  stated by Gabriel on 2026-11-09.
- The script's scope: counts at 0.25% on the exploration half with exactly
  one incumbent, by election and pooled 2008-2020, with campaign 0002's
  check 1 definitions, counts only, no outcome data, and a test that shows
  it. Stated by Gabriel on 2026-11-09.
- Rebuilding those definitions from explore code, with no import of
  `terrain.registered` and a test of equality with `incumbent_sign` at 0.50%
  on the synthetic world: suggested by Claude on 2026-11-09 to respect the
  registered code's guard on 0.25%, and not yet confirmed by Gabriel. He
  checks it in this PR.
- Writing pairs per election next to the one-incumbent counts, as a
  cross-check against decision 0008: suggested by Claude, and not yet
  confirmed by Gabriel. It is not a kill rule.
- Kill rule k1 (pooled one-incumbent pairs below 200) and `on_kill: stop`:
  stated and confirmed by Gabriel on 2026-11-09. No run had computed the
  count at 0.25%.
- Budget (1 task, 1 run, 0 pipeline runs, 5 model jobs), end date
  2026-11-12 and status `active`: stated by Gabriel on 2026-11-09.
- Novelty check, repository only: stated by Gabriel on 2026-11-09.
