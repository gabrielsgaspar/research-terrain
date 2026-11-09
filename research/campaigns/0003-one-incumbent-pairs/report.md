# Campaign 0003 report: Count close pairs with exactly one incumbent at the registered 0.25% window

## Summary

Both steps are done. Step s1 (the counting script and its tests) was merged, and
step s2 (the run) survived: 813 close pairs at 0.25%, pooled 2008-2020, have
exactly one incumbent. That is above the threshold of 200, so kill rule k1 was
not met and the incumbency-adjusted fallback is not thin at the registered
window. This is a count of treatments on the exploration half. It says nothing
about any effect.

## What ran

Run 42681937536 of `explore/0001_one_incumbent_pairs.py` at commit
`5922517fe627f8cf796420da989971ef0ab6c252`, through the `explore-run` workflow,
on the exploration half only. The script came from s1 (issue #263, PR #264) and
the record came from PR #265, as given in the tick's ledger
(`research/campaigns/0003-one-incumbent-pairs/ledger.md`). The record is
`research/explore-runs/0001/42681937536.md`.

## Results and their limits

These are exploration-half results. Nothing here is a finding: the run writes
no estimate, and reports only counts of treatments.

From `research/explore-runs/0001/42681937536.md`, close pairs at 0.25%, pooled
2008-2020: plus 433, minus 380, zero 1,515, and 813 with exactly one incumbent
(433 + 380), out of 2,328 pairs. The pooled 2,328 equals decision 0008's
2,328, as the record states, so the pair definition matches. By election:

| Election | plus | minus | zero | one_incumbent | pairs |
| --- | --- | --- | --- | --- | --- |
| 2008 | 88 | 96 | 294 | 184 | 478 |
| 2012 | 104 | 76 | 398 | 180 | 578 |
| 2016 | 127 | 91 | 378 | 218 | 596 |
| 2020 | 114 | 117 | 445 | 231 | 676 |

Each election carries few one-incumbent pairs: 180 to 231. The pooled 813 is
about four times the threshold of 200, but no single election reaches it by a
wide margin, and 2008 and 2012 are below 200 on their own. The threshold is
for the pooled count, so this is not a kill rule outcome.

Limits, from the run record's caveats:

- Exploration half only.
- These are counts of treatments, not outcomes.
- No estimate is made.
- The registered analysis was not run.

## Kill rules applied

k1 is "not met", matching the ledger's Verdict "survived".

- k1 (fewer than 200 close pairs at 0.25%, pooled 2008-2020, have exactly one
  incumbent): `counts.pooled.one_incumbent` observed 813 in
  `research/explore-runs/0001/42681937536.md`, not below 200. Not met. The
  threshold of 200 is from the campaign file, not the record.

## Budget used

From the tick's ledger (not from a run record): max_explore_runs 1 of 1,
max_model_jobs 3 of 5, max_pipeline_runs 0 of 0, max_tasks 1 of 1.

## Stops and blocks

None in the ledger. The tracking issue (#262) was not read for this report, so
this rests on the ledger alone.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Count the one-incumbent pairs at 0.25% with the 2024 election included, to
  see whether the extra election raises the per-election counts.
- Look at the one-incumbent pairs per election against a per-election
  threshold, if Gabriel wants one; the campaign has none.
- Count the same pairs at windows between 0.25% and 0.50%, to see how the
  count moves with the window.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. Lift the 0.25% caveat on campaign 0002's tick ("new paths checked")?
   - Option A: lift it. 813 is above 200 at the registered window, so the
     fallback is not thin there.
   - Option B: keep it, because the counts say nothing about whether the new
     paths run correctly at 0.25%, which cannot be checked before
     registration.
   - Agent's recommendation: option A for the count question only, with a note
     that the code paths were checked at 0.50%. The count answers the thinness
     concern that the caveat named.
2. Keep decision 0009, point 5 as written?
   - Option A: keep it. The fallback has 813 pairs pooled.
   - Option B: reopen it because each election has only 180 to 231
     one-incumbent pairs, which may be thin for election-level work.
   - Agent's recommendation: option A, because point 5 rests on the pooled
     count and the per-election numbers are not a stated criterion.
