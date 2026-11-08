# Campaign 0001 report: Smoke test, re-run idea 0003's power check

## Summary

Step s1 ran, kill rule k1 was met, and s1 was killed. That is the outcome the
campaign file expected (`research/campaigns/0001-smoke-test/campaign.md`,
"Steps and why"). The re-run gave the same race counts and the same power as
the first run, so the numbers show no sign of a fault in the machinery. This is
a smoke test of the campaign machinery, not research.

## What ran

Run 42494552921 of `explore/0003_mayor_power.py` at commit `0a1ce9b`, through
the `explore-run` workflow, on the exploration half only. The record is
`research/explore-runs/0003/42494552921.md` (with
`research/explore-runs/0003/42494552921.json`). The record pull request is
#246, as given in the tick's ledger
(`research/campaigns/0001-smoke-test/ledger.md`).

## Results and their limits

These are exploration-half results. Nothing here is a finding: the run
estimates no effect and has no observed contrast.

From `research/explore-runs/0003/42494552921.md`, at decision 0007's effect
(8% of baseline clearing):

| Window | Races | Power | MDE, % of baseline |
| --- | --- | --- | --- |
| 0.5% | 45 | 4.4% | 89.4 |
| 1% | 80 | 5.2% | 67.1 |
| 2% | 157 | 7.2% | 44.6 |

These match the first run, 42367009833
(`research/explore-runs/0003/42367009833.md`): the same counts, power and MDE.
The unrounded power at the 1% window, 0.05197143596133924, is in
`research/explore-runs/0003/42494552921.json`.

Limits, from the run record's caveats:

- Exploration half only.
- Pre-election clearing (E-4 .. E-1) stands in for the outcome's spread.
- One observation per race ignores turf geography.
- Delta is the best case: a race-level attribute that splits the races 50/50.
- The municipal outcome stops at exploration-half cells.
- No effect is estimated; there is no observed contrast.

## Kill rules applied

- k1 (power at decision 0007's effect is below 80% at the 1% window):
  `windows.1%.power` = 0.05197143596133924 < 0.8. Met, so s1 is killed. This
  matches the Verdict column of the ledger ("killed").

## Budget used

From the tick's ledger (not from a run record): max_explore_runs 1 of 1,
max_model_jobs 0 of 0, max_pipeline_runs 0 of 0, max_tasks 0 of 0.

## Stops and blocks

None in the ledger. The tracking issue (#245) was not read for this report, so
this rests on the ledger alone.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- A smoke test with two steps, one depending on the other, to exercise
  `on_kill: skip_dependents`.
- A smoke test with a step that includes a pipeline run, to exercise the
  data-pipeline path and its manifest pull request.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. Did the machinery pass the smoke test?
   - Option A: yes, the run record, the verdict and the ledger agree with the
     expected result, so a real campaign may start.
   - Option B: not yet, because the paths in the suggestions above were not
     exercised.
   - Agent's recommendation: option A for the single-step path that ran;
     treat the untested paths as risks to watch in the first real campaign.
2. Does anything need fixing first?
   - Option A: nothing; the run, the record, the kill rule and the ledger
     agreed.
   - Option B: check the tracking issue #245 and the merged pull request #246
     for anything the ledger does not show.
   - Agent's recommendation: option B, a quick look, because this report could
     not read the tracking issue.
