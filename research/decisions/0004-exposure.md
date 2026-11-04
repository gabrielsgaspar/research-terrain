---
id: "0004"
title: "How a cell's exposure to a close council race is measured"
status: accepted
date: 2026-11-04
supersedes: null
---

# 0004: How a cell's exposure to a close council race is measured

Date: 2026-11-04. Status: accepted by Gabriel on 2026-11-04, with every
proposal below unchanged. The `cell_exposure` build (handoff task 8) and
figure 4 follow from it.

## The question

Idea 0001 compares land around the strongholds of narrowly elected and
narrowly defeated council candidates. Each 1 km cell (`grid_cells`) needs a
number saying how strongly it sits in the winner's rather than the loser's
electoral territory. Five choices make that number: the distance decay, the
vote measure, how a pair is turned into one number, the recentring, and the
unit of inference.

## Evidence

`explore/0001_exposure_options.py`, run 41913964880, exploration half only,
no outcome data (`research/explore-runs/0001/41913964880.md`, lessons entry of
2026-11-04). For each cell, over the close pairs (margin at most 0.5%) of its
municipality and the polling places of that municipality within 10 km:
`D_i` = Σ_pairs (E_i,winner − E_i,loser).

| 2024, exploration half (2,530,638 cells; 338 municipalities, 891 pairs) | exp(-d/2) ≤ 10 km | 5 km ring | 2 km ring |
| --- | --- | --- | --- |
| Cells exposed (share measure) | 483,734 | 198,042 | 46,209 |
| Share of exposed cells with no residents | 76% | 67% | 44% |
| Correlation of `D` with exp(-d/2) (share measure) | 1 | 0.98 | 0.97 |
| Median \|D\| (share measure) | 0.032 | 0.035 | 0.036 |

Other years give the same picture (2008: 412,042 cells exposed under
exp(-d/2); 2012-2020: 469,199 to 473,678).

Share against votes, exp(-d/2), 2024: correlation 0.15. Mean |D| in cells
with residents against empty cells: share 0.067 against 0.078; votes 21.9
against 5.4. Share exposure is highest in cells touching indigenous land
(0.106).

## Options and decision

| Choice | Options | Decision | Why |
| --- | --- | --- | --- |
| Distance decay | exp(-d/2 km) cut at 10 km; 2 km ring; 5 km ring | **exp(-d/2), cut at 10 km**; the 2 and 5 km rings as robustness | Reaches 2.4 and 10 times as many cells as the rings, and ranks them the same way (correlation 0.97-0.98), so the rings are honest robustness checks rather than different measures. |
| Vote measure | candidate's share of the place's valid votes (kernel-weighted mean); candidate's votes (kernel-weighted sum) | **Share** | Votes exposure tracks population density (four times larger in populated cells) and correlates only 0.15 with share. A stronghold is about relative strength, which share measures; density enters later as a control, not inside the treatment. |
| Pair contrast | winner minus loser per pair, summed over the municipality's close pairs; per-pair cells kept separate | **Winner minus loser, summed** (`D_i`) | One number per cell and year; municipalities have 2.6 close pairs on average (at most 21). |
| Recentring | Borusyak and Hull (2023): subtract the expected exposure over swaps of each pair | **Recentred exposure = `D_i` / 2** | With the exposure linear in assignment, swapping a pair flips the sign of its term, so the expectation over swaps is exactly half the sum of both candidates' exposure; subtracting it leaves `D_i` / 2. Recentring matters again only if a nonlinear exposure is chosen later. |
| Inference | municipality-clustered standard errors; randomisation inference re-flipping each close pair | **Randomisation inference by re-flipping pairs** (independently, each with probability 1/2), with municipality clusters as the reported check | The design's randomness is the coin flip of each close race; re-flipping uses exactly that. Fixed effects: municipality by year. |

Cells beyond 10 km of every polling place of their municipality have no
exposure under this decision (about 79% of exploration-half cells in 2024).
They are the unrepresented land of the displacement prediction.

## What the build computes

`cell_exposure`, one row per cell, election year and kernel (`exp2`, `ring2`,
`ring5`): `D` (share measure), the number of close pairs in the
municipality, and Σ_p K(d) (so reach can be checked), for both halves of the
sample (treatment-side data, decision 0003).
