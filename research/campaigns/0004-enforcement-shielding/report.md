# Campaign 0004 report: Does IBAMA enforcement fall less near a close council winner's stronghold?

## Summary

Kill rule k3 was met at step s7, so the campaign stopped before any
post-election year was read. The minimum detectable effect at the registered
0.25% window is 0.77 of the pre-election baseline mean, against a bar of 0.25
(`research/explore-runs/0005/42796832006.md`). The design could not detect a
25% change in enforcement. Steps s8 and s9 were skipped. The campaign
produced no estimate of any effect.

## What ran

From the tick's ledger (`research/campaigns/0004-enforcement-shielding/ledger.md`):

- s1 (task, issue #272, PR #273): the two IBAMA acquire scripts. Merged.
- s2 (pipeline run, PR #274, run 42755238673): `ibama_autos` acquired. Recorded.
- s3 (pipeline run, PR #275, run 42755616189): `ibama_embargos` acquired. Recorded.
- s4 (task, issue #276, PR #277): the `cell_enforcement` build. Merged.
- s5 (pipeline run, PR #278, run 42792636592): `cell_enforcement` built. Recorded.
- s6 (task, issue #279, PR #281): `explore/0005_enforcement_power.py`. Merged.
- s7 (explore run, PR #284, run 42796832006): the power gate on pre-election
  years, exploration half. Killed by k3. Record:
  `research/explore-runs/0005/42796832006.md`.
- s8 (task) and s9 (explore run): skipped, because s7 was killed.

## Results and their limits

These are exploration-half results. Nothing here is a finding: the run
reads pre-election years only and writes no post-election estimate.

From `research/explore-runs/0005/42796832006.md`:

| Election | Share of pre-election actions located |
| --- | --- |
| 2008 | 0.339 |
| 2012 | 0.6 |
| 2016 | 0.867 |
| 2020 | 0.885 |

- Elections with at least half located: 3 of 4. Only 2008 falls short, at
  0.339, and k1 passes by the narrowest margin (see the rules below).
- Located pre-election actions in the cells exposed at 0.50%: 20,296.
- Minimum detectable effect as a share of the baseline: 0.77 at the 0.25%
  window and 0.67 at the 0.50% window.
- Pre-election placebo at 0.50%, randomisation-inference p: 0.124.

Limits, from the record's caveats: exploration half only; the outcome is flora
fines plus embargoes in the four years before the election; a cell absent from
the enforcement table counts 0; the MDE is 2.8 SD of the direct slope over
2,000 re-flips. The record gives no verdict on the kill rules; the verdicts
below are the tick's, from the ledger.

Decision 0008 found that the 0.50% window is unbalanced on incumbency
(`research/decisions/0008-close-race-window.md`). The 0.50% placebo above is
the enforcement-specific check of that, and it did not fire (p 0.124 against
a bar of 0.10), but a p-value that close to the bar is not reassurance.

## Kill rules applied

Thresholds are from the campaign file; observed values are from the run
record (and the ledger, which gives them with more digits). The verdicts match
the ledger.

- k1 (`coverage.elections_ok < 3`): observed 3 of 4 elections. Not met. It
  passes by the smallest possible margin.
- k2 (`counts.pre_reach_actions < 400`): observed 20,296. Not met.
- k3 (`power.mde_share_025 > 0.25`): observed 0.77. **Met**: the step is
  killed. The ledger's Verdict for s7 is "killed".
- k4 (`placebo.ri_p_050 < 0.1`): observed 0.124. Not met.

## Budget used

From the tick's ledger (not from a run record): max_explore_runs 1 of 2,
max_model_jobs 9 of 28, max_pipeline_runs 3 of 3, max_tasks 3 of 4.

## Stops and blocks

- s7 was stopped by k3 (`on_kill: stop`). The tick skipped s8 ("step s7 was
  killed") and then s9 ("step s8 was skipped").
- No step was blocked. The tracking issue (#271) was not read for this
  report, so this rests on the ledger alone.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Pool the outcome over more years than the four after the election, or use a
  coarser outcome such as any enforcement action in a cell, to cut the variance
  that drives the MDE. This needs a new power check first.
- Aggregate to larger units than 1 km cells, to see whether the MDE falls.
- Read the 0.50% MDE (0.67) as a guide to how much wider a window would have
  to be; it is also far above the 0.25 bar, so a window change alone is
  unlikely to be enough.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0005 take? The front-matter `status` and
   `kill_criteria` were left unchanged by this task.
   - Option A: mark it dead, because the registered window cannot detect a 25%
     change.
   - Option B: keep it proposed, pending a redesigned outcome.
   - Option C: rework it into a new idea with a coarser outcome.
   - Agent's recommendation: option B. The power gate did what it was built to
     do, but the data are in place and the redesign options above are cheap to
     power-check.
2. Re-scope kill rule k3?
   - Option A: keep 0.25. It was anchored on Gabriel's reading of Katovich and
     Moffette (unverified web find) and confirmed on 2026-11-09.
   - Option B: raise the bar. At 0.77 the observed MDE is about three times
     the bar, so a modest rise would not change the verdict.
   - Agent's recommendation: option A. A bar chosen after seeing the result
     would be a forking path.
3. Own `cell_enforcement` in `.github/CODEOWNERS`? The campaign file left this
   open ("Gabriel may want to own them after the campaign").
   - Option A: own it now, like `cell_outcomes`.
   - Option B: leave it unowned until an estimate depends on it.
   - Agent's recommendation: option A, because the confirmation-half rows are
     sealed and the build is already merged.
