---
id: "0005"
title: "How unrepresented land's exposure to a close council race is measured (displacement)"
status: accepted
date: 2026-11-05
supersedes: null
---

# 0005: How unrepresented land's exposure to a close council race is measured

Date: 2026-11-05. Status: accepted by Gabriel on 2026-11-05, every proposal
unchanged. A `cell_displacement`
build (like `cell_exposure`) follows from it.

## The question

Idea 0001 predicts that clearing is pushed onto land with no voters near a
newly represented stronghold. Decision 0004 measures exposure only where
people vote (within 10 km of a polling place of the municipality). Which
cells count as unrepresented, and how is their exposure to the winner rather
than the loser of a close pair measured?

## Evidence

`explore/0001_displacement_options.py`, run 41949908031, exploration half,
no outcome data (`research/explore-runs/0001/41949908031.md`, lessons entry of
2026-11-05). Unrepresented: `pop_2022` = 0 and not reached by `cell_exposure`
that year. `G_i` = Σ_pairs (K(d(i, winner's stronghold)) − K(d(i, loser's))),
strongholds of the cell's own municipality.

| 2024, exploration half | exp(-d/10) ≤ 50 km | 10-20 km ring | 20-50 km ring | nearest ≤ 50 km |
| --- | --- | --- | --- | --- |
| Cells with G ≠ 0 (of 1,774,572 unrepresented) | 710,297 | 149,753 | 447,539 | 635,783 |
| Share in undesignated forest | 14% | 16% | 14% | 14% |
| Correlation of G with exp(-d/10) | 1 | 0.91 | 0.03 | 0.64 |

Other years are alike (2008-2020: 683,263 to 733,859 cells under
exp(-d/10)). 76-79% of the cells of municipalities with a close pair are
unrepresented. About 12% of pairs have both strongholds at the same place
and carry no contrast.

## Options and proposal

| Choice | Options | Proposal | Why |
| --- | --- | --- | --- |
| Unrepresented cell | empty and beyond the 10 km reach; any cell beyond it; empty cells anywhere | **Empty in 2022 and not reached by decision 0004's kernel** | Disjoint from the direct exposure, so the two effects are estimated on different cells; "no voters" in both senses. |
| Kernel | exp(-d/10) to 50 km; 10-20 km ring; 20-50 km ring; nearest stronghold | **exp(-d/10), cut at 50 km**; the 10-20 and 20-50 km rings as robustness | Smooth, the same family as decision 0004, and it reaches the most cells; it agrees with the near ring (0.91). The far ring is nearly unrelated (0.03), so it is a separate check of whether displacement reaches far, not a substitute. |
| Contrast and recentring | as decision 0004 | **Winner minus loser over the municipality's close pairs; recentred exposure G / 2** | Swapping a pair negates its term, so the expectation over swaps is 0. |
| Pairs with one stronghold place | keep (term 0); drop | **Keep, with term 0** | They are valid close races; they add nothing to G but stay in the randomisation. |
| Inference | as decision 0004 | **Randomisation inference by re-flipping pairs; municipality-by-year fixed effects** | One design for both exposures. |

## What the build computes (once accepted)

`cell_displacement`, one row per unrepresented cell and election year for
both halves (treatment-side data, decision 0003): `g_exp10`, `g_ring10_20`,
`g_ring20_50`, and the number of close pairs in the municipality.

## Accepted

By Gabriel on 2026-11-05, unchanged.
