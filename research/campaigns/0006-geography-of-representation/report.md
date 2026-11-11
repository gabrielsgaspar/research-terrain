# Campaign 0006 report: Do narrow council winners' voters' places get more of the state?

## Summary

Both explore runs survived their kill rules (s17 k1-k6, s19 k1; none met). On
the exploration half, the primary estimate is a null: for municipal schools at
the 0.50% window the slope is -0.022 (clustered SE 0.0389, randomisation-inference
p 0.568), which is -0.00115 SD (`research/explore-runs/0006/42939196149.md`).
The feasibility run found the design well powered: 23,132 close pairs and a
minimum detectable effect of 0.00659 SD
(`research/explore-runs/0006/42935501189.md`). Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0006-geography-of-representation/ledger.md`):

- s1 (task, issue #295, PR #297): merged.
- s2 (pipeline run, PR #298, run 42833397527): recorded.
- s3 (pipeline run, run 42846168945): recorded.
- s4 (pipeline run, PR #303, run 42856914932): recorded.
- s5 (pipeline run, PR #306, run 42857864152): recorded.
- s6 (task, issue #299, PR #300): merged.
- s7 (pipeline run, PR #308, run 42860225743): recorded.
- s8 (pipeline run, PR #312, run 42905171706): recorded.
- s9 (task, issue #301, PR #302): merged.
- s10 (pipeline run, PR #315, run 42919122289): recorded.
- s11 (task, issue #304, PR #305): merged.
- s12 (pipeline run, PR #314, run 42900668531): recorded.
- s13 (pipeline run, PR #313, run 42862601462): recorded.
- s14 (task, issue #307, PR #309): merged.
- s15 (pipeline run, PR #316, run 42924200076): recorded.
- s16 (task, issue #317, PR #318): merged.
- s17 (explore run, PR #319, run 42935501189): feasibility before the
  election, survived. Record: `research/explore-runs/0006/42935501189.md`.
- s18 (task, issue #320, PR #321): merged.
- s19 (explore run, PR #322, run 42939196149): post-election effects,
  survived. Record: `research/explore-runs/0006/42939196149.md`.

## Results and their limits

These are exploration-half results. Nothing here is a finding: a result from
the exploration half is a reason to register a design, not a conclusion.

Feasibility, pre-election years (`research/explore-runs/0006/42935501189.md`):

- Close pairs at 0.50%: 23,132 (2008: 4939, 2012: 5731, 2016: 5912, 2020: 6550).
- Share of sections at a place located within 1 km: 0.939.
- Share of places matched to a school (high or medium): 0.605.
- Balance on D, joint randomisation-inference p: 0.315.
- Placebo (change in school facilities), randomisation-inference p: 0.441.
- Minimum detectable shift, in SD of the pre-election change: 0.00659.

Post-election effects (`research/explore-runs/0006/42939196149.md`), change in
municipal-school facilities, E to E+4:

| Window | Slope | Clustered SE | RI p | Effect (SD) | Pairs |
| --- | --- | --- | --- | --- | --- |
| 0.25% | 0.0249 | 0.0478 | 0.609 | 0.00106 | 13188 |
| 0.50% | -0.022 | 0.0389 | 0.568 | -0.00115 | 20916 |
| 1.00% | -0.00872 | 0.0337 | 0.792 | -0.000547 | 29722 |

- Falsification, state schools at 0.50%: slope 0.0522, RI p 0.529. It is
  near zero, as expected.
- Secondary outcomes at 0.50% after Benjamini-Hochberg: night lights BH p
  0.36, built-up BH p 0.36, native loss BH p 0.487. None rejected at 5%.
- Heterogeneity at 0.50%, winner aligned with the elected mayor's coalition or
  not: aligned minus unaligned 0.101, RI p 0.192. Aligned 0.0263 (p 0.65),
  unaligned -0.0748 (p 0.169).

Limits, from the records: exploration half only; 2,000 flips of every pair
(seed 20261110). The 0.50% primary uses 20,916 pairs, against 23,132 in the
feasibility run; the records do not say why and this report does not guess.
The matched-school share is 0.605, so the school outcome covers only the
matched places. INEP data are CC BY-ND, so only aggregates are shown (as the
campaign file states). The feasibility run gives no verdict on the kill rules;
the verdicts below are the tick's, from the ledger.

## Kill rules applied

Thresholds are from the campaign file; observed values are from the run
records. All verdicts match the ledger (s17 and s19 both "survived").

- s17 k1 (`counts.pairs_050 < 10000`): observed 23,132. Not met.
- s17 k2 (`coverage.located_share < 0.85`): observed 0.939. Not met.
- s17 k3 (`schools.match_share < 0.5`): observed 0.605. Not met.
- s17 k4 (`balance.ri_p_joint < 0.05`): observed 0.315. Not met.
- s17 k5 (`placebo.ri_p_school < 0.1`): observed 0.441. Not met.
- s17 k6 (`power.mde_sd_school > 0.1`): observed 0.00659. Not met.
- s19 k1 (`estimates.finite != True`): all estimates finite, True. Not met.

## Budget used

From the tick's ledger (not from a run record): max_explore_runs 2 of 2,
max_model_jobs 25 of 45, max_pipeline_runs 10 of 12, max_tasks 7 of 7.

## Stops and blocks

None recorded in the ledger: every step is done and no kill rule was met. The
tracking issue (#294) was not read for this report, so this rests on the
ledger alone.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Split the facility count by type of facility (for example classrooms or
  other school facilities), in case a total hides a shift.
- Try other outcome sources for public goods near polling places, after a
  power check.
- State the mayor-aligned split as a pre-stated test; here it is exploratory
  and its difference has RI p 0.192.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0006 take? The front-matter `status` and
   `kill_criteria` were left unchanged by this task.
   - Option A: mark it rejected, because the primary estimate is a null with
     a very small minimum detectable effect.
   - Option B: park it, keeping the built data and scripts for later use.
   - Option C: register it for confirmation as a pre-stated null design.
   - Agent's recommendation: option B. The null is precise, so there is
     little to gain from spending the confirmation half on it, but the data
     are built and cheap to keep.
2. Whether to test on the confirmation half?
   - Option A: no; the confirmation half stays sealed for stronger candidates.
   - Option B: yes, with the 0.50% design registered as it ran.
   - Agent's recommendation: option A, for the same reason as above.
3. What happens to the unused budget (two pipeline runs, 20 model jobs) and
   the datasets now built?
   - Option A: let them lapse with the campaign.
   - Option B: open a new campaign on one of the variants above.
   - Agent's recommendation: option A until a variant has been power-checked.
