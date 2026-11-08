# Campaign 0002 report: Check the registered analysis's new paths on real data, without estimates

## Summary

Both steps are done. Step s1 (the checker and its tests) was merged, and step
s2 (the run) survived: all seven structural checks passed at the 0.50% window
on the exploration half, and no kill rule was met. This is a check of code
paths before registration, not research. It ticks one item before registration
and says nothing about any effect.

## What ran

Run 42514591508 of `explore/0001_registered_paths_check.py` at commit
`2b754316f8d38f3fd1f1e245ad8e3acdfc619f7a`, through the `explore-run` workflow,
on the exploration half only. The script came from s1 (issue #255, PR #256) and
the record came from PR #257, as given in the tick's ledger
(`research/campaigns/0002-registered-new-paths/ledger.md`). The record is
`research/explore-runs/0001/42514591508.md` (with
`research/explore-runs/0001/42514591508.json`).

## Results and their limits

These are exploration-half results. Nothing here is a finding: the run writes
no estimate, and reports only counts and pass or fail.

From `research/explore-runs/0001/42514591508.md`, structural checks: pass.
Checks c1 to c7 each read "pass".

Check 1, close pairs by incumbency, pooled 2008-2020: plus 690, minus 604,
zero 2,390, and 1,294 with exactly one incumbent (690 + 604). By election:

| Election | plus | minus | zero |
| --- | --- | --- | --- |
| 2008 | 144 | 144 | 477 |
| 2012 | 170 | 130 | 619 |
| 2016 | 201 | 153 | 586 |
| 2020 | 175 | 177 | 708 |

Check 4, the alignment split, pairs per election: 765 (2008), 919 (2012), 940
(2016), 1,060 (2020) and 891 (2024). In each, aligned, unaligned, mixed and
left-out add up to the pairs. Check 5, direct placebo cells: 435,786 (2008),
494,099 (2012), 492,301 (2016) and 498,638 (2020). Check 6: nonfinite = 0.

Limits, from the run record's caveats:

- Exploration half only.
- 0.50% is not the registered window, which is never run before registration.
- The run checks code paths, not estimates.
- Checks c3 and c7 give pass or fail only, with no counts in the record.

## Kill rules applied

All eight are "not met", matching the ledger's Verdict "survived". The
observed values are from the tick's ledger, which read the run record.

- k1 (Check 1 fails): `checks.c1.pass` observed True. Not met.
- k2 (Check 2 fails): `checks.c2.pass` observed True. Not met.
- k3 (Check 3 fails): `checks.c3.pass` observed True. Not met.
- k4 (Check 4 fails): `checks.c4.pass` observed True. Not met.
- k5 (Check 5 fails): `checks.c5.pass` observed True. Not met.
- k6 (Check 6 fails): `checks.c6.pass` observed True. Not met.
- k7 (Check 7 fails): `checks.c7.pass` observed True. Not met.
- k8 (fewer than 200 pairs with exactly one incumbent, pooled 2008-2020 at
  0.50%): `checks.c1.counts.pooled.one_incumbent` = 1294, not below 200. Not
  met. The threshold of 200 is from the campaign file, not the record.

## Budget used

From the tick's ledger (not from a run record): max_explore_runs 1 of 1,
max_model_jobs 3 of 5, max_pipeline_runs 0 of 0, max_tasks 1 of 1.

## Stops and blocks

None in the ledger. The tracking issue (#254) was not read for this report, so
this rests on the ledger alone.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Count the pairs with exactly one incumbent at 0.25% before registration. The
  campaign file warns that counts shrink there (kill criterion 1's count fell
  to 61% from 0.50% to 0.25% in run 42384056410), and the analysis refuses
  that window before registration, so this needs a decision first.
- Compare the 1,294 count with the 200 threshold per election, to see whether
  one election carries the pooled count.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. Tick the "new paths checked" item before registration?
   - Option A: tick it. All seven checks passed and no kill rule was met.
   - Option B: wait until the paths have also run at the registered window,
     which cannot happen before registration.
   - Agent's recommendation: option A, with the 0.50% caveat written next to
     the tick.
2. Is the margin of k8 at 0.50% enough for decision 0009's point 5 fallback at
   0.25%?
   - Option A: yes; 1,294 is well above 200 (from the record), so the fallback
     is not thin at 0.50%.
   - Option B: not known; the count at 0.25% was not measured and may be
     lower, so ask for a count at 0.25% before registering.
   - Agent's recommendation: option B, because the campaign file says counts
     shrink at the narrower window, and a count of treatments needs no
     outcome data.
