---
id: "0001"
title: "Electoral strongholds and the geography of deforestation"
status: exploring
created: 2026-11-01
updated: 2026-11-04
datasets:
  - tse_votes_by_section
  - tse_polling_places
  - polling_stations_geocoded
  - tse_candidates
  - tse_results
  - ibge_municipalities
  - mapbiomas_deforestation
  - funai_indigenous_lands
  - cnfp_public_forests
  - incra_settlements
kill_criteria:
  - "Too little constituency variation: after typing strongholds with FUNAI indigenous lands and INCRA settlements, fewer than 200 close-pair candidates (margin at most 0.5%, 2008-2024 pooled, exploration half) have a stronghold in or within 5 km of an indigenous land, or fewer than 200 in or within 5 km of a settlement."
  - "A non-flat placebo: stronghold exposure in the four years before the election predicts clearing (randomisation-inference p below 0.05) on the exploration half."
  - "Wrong signs by constituency type: the effect around indigenous-land strongholds is not below the effect around settlement or frontier strongholds, with at least 80% power for the effect size fixed in the pre-analysis plan."
  - "No effect at all: the stronghold and displacement effects are both indistinguishable from zero, with at least 80% power for the effect size fixed in the pre-analysis plan."
related: ["0002"]
---

# 0001: Electoral strongholds and the geography of deforestation

## Claim

Narrowly winning a council seat changes land use around the winner's
electoral stronghold, in a direction set by what that stronghold's voters
value, and clearing is pushed onto land with no voters.

## Prediction

Fixed in the pre-analysis plan before outcomes are merged. Working version:

- Strongholds in or next to indigenous territories: less clearing after a
  close win.
- Strongholds in settlements or on the agrarian frontier: more clearing after
  a close win.
- Unrepresented cells near newly represented strongholds: more clearing
  (displacement).
- The same exposure in the four pre-election years: no effect (placebo).

Against the idea: wrong signs by constituency type, a non-flat placebo, or no
effect at all with adequate power.

## Design

- Strongholds: each candidate's vote share by polling station (TSE section
  results), on geocoded polling stations; grid cells are assigned to
  polling-station catchments.
- Treatment: within-list close races (from 2020, lists are parties; before,
  coalitions). The counterfactual for each close pair swaps winner and loser.
- Exposure: each cell's vote-weighted exposure to the pair, recentred by its
  expectation over swaps (Borusyak and Hull 2023), with randomisation
  inference by re-flipping pairs.
- Fixed effects: municipality by year, which absorb the mayor, the budget and
  enforcement.
- Outcome: MapBiomas annual deforestation over the four term years.
- Displacement: a second exposure for unrepresented cells near newly
  represented strongholds.

## Data needed

`tse_votes_by_section`, `tse_polling_places`, `polling_stations_geocoded`,
`tse_candidates`, `tse_results`, `ibge_municipalities`,
`mapbiomas_deforestation`, `funai_indigenous_lands`, `cnfp_public_forests`,
`incra_settlements`.

Elections with usable geography: 2008, 2012, 2016, 2020 and 2024 (see
`research/lessons.md`, 2026-11-02).

## Status

- 2026-11-01: proposed. First step is the feasibility census: how many close
  pairs exist, and how many candidates have rural strongholds.
- 2026-11-02: still proposed. Data profiling limits the design to the 2008-2024
  elections; polling places can be located for about 98% of sections.
- 2026-11-03: exploring. The feasibility census finds 765-1,060 close
  within-list pairs per election on the exploration half, about half of them
  with the candidate's stronghold outside the municipal seat.
- 2026-11-04: still exploring. Kill criterion 1 is not met: 711
  close-pair strongholds are within 5 km of an indigenous land and 2,590 of a
  settlement on the exploration half (minimum 200 each).

## Log

- 2026-11-03: feasibility census: issue #70, PR #71, run 41719271978
  (`research/explore-runs/0001/41719271978.md`); `research/lessons.md` entry of
  the same date.
- 2026-11-04: kill criterion 1: issue #85, PR #86, run 41839642406
  (`research/explore-runs/0001/41839642406.md`), record PR #87;
  `research/lessons.md` entry of the same date.
