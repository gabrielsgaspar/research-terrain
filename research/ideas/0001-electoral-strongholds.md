---
id: "0001"
title: "Electoral strongholds and the geography of deforestation"
status: exploring
created: 2026-11-01
updated: 2026-11-08
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

The null on the direct effect is read under a core-voter model; under a
swing-voter model, winners may also protect areas where they lost, which the
winner-minus-loser contrast cannot detect. Unresolved.

## Design

- Strongholds: each candidate's vote share by polling station (TSE section
  results), on geocoded polling stations; grid cells are assigned to
  polling-station catchments.
- Treatment: within-list close races (from 2020, lists are parties; before,
  coalitions). The counterfactual for each close pair swaps winner and loser.
- Exposure (decision 0004): each cell's exposure to the pair, the
  exp(-d/2 km)-weighted mean of the candidate's vote share at the polling
  places of its municipality within 10 km, winner minus loser, recentred by
  its expectation over swaps (Borusyak and Hull 2023), which is D / 2;
  randomisation inference by re-flipping pairs; 2 and 5 km rings as
  robustness.
- Fixed effects: municipality by year, which absorb the mayor, the budget and
  enforcement.
- Outcome (decision 0006): MapBiomas Collection 10 loss of primary
  vegetation, as the share of each 1 km cell, in each of the four term years
  and their sum; loss of secondary vegetation as a secondary outcome.
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
- 2026-11-04: still exploring. Exposure options compared on the exploration
  half (run 41913964880): exp(-d/2) to 10 km exposes about 480,000 cells per
  election, 76% of them empty; decision 0004 proposed.
- 2026-11-04: still exploring. Decision 0004 accepted: exposure is
  exp(-d/2) to 10 km on vote shares, winner minus loser over close pairs,
  recentred as D / 2, with randomisation inference by re-flipping pairs.
- 2026-11-05: still exploring. Displacement-exposure options compared on the
  exploration half (run 41949908031); decision 0005 accepted (2026-11-05).
- 2026-11-06: still exploring. Kill criterion 2 is not met: the pre-election
  placebo on the exploration half gives pooled `exp2` RI p 0.34 (run
  42193625417).
- 2026-11-06: still exploring. Minimum detectable effects measured on
  pre-election clearing (run 42265146230) for decision 0007; 455
  indigenous-side and 1,987 settlement-side close-pair candidates at 5 km
  (2008-2020).
- 2026-11-06: still exploring. Kill criteria 3 and 4 cannot be applied at
  80% power on the exploration half (run 42298466207, decision 0007): the
  direct slope is -1.0% of baseline (RI p 0.59) and the displacement slope
  -4.4% (RI p 0.086), neither non-zero under Holm; the split difference is
  +3.4% (one-sided p1 0.81, power 0.45). The confirmation half stays sealed.
  The exploration does not support the predictions; see the lessons entry
  of the same date.
- 2026-11-07: still exploring. The close-race window is 0.25%, chosen by
  the covariate-balance rule (run 42366460941, decision 0008, accepted by
  rule; Gabriel to review). The 0.50% window of the earlier runs is not
  balanced (omnibus p 0.119; narrow winners were incumbents 2.3 points more
  often, RI p 0.014), so the 2026-11-06 result is reported with that caveat.
  At 0.25%, power at 8% is 0.868 (direct), 0.622 (displacement) and 0.307
  (split).
- 2026-11-07: still exploring. Gabriel accepted decision 0008 (0.25%) and
  decided decision 0009 for the pre-analysis plan: kill criterion 1's
  "0.5%" means the registered window; kill criterion 3 and kill criterion
  4's displacement branch are reported, not used to kill; power is carried
  over from the exploration half; an incumbency-adjusted direct estimate is
  a registered robustness check and the fallback if confirmation-half
  balance fails. The kill-criteria texts are unchanged. Kill criterion 1 at
  0.25% (run 42384056410): 434 indigenous-side and 1,625 settlement-side
  candidates at 5 km, pooled 2008-2024; not met.
- 2026-11-08: still exploring. The registered analysis reproduces the
  explore code on the exploration half at 0.50% (run 42476480500): 875
  numbers compared with runs 42298466207 and 41839642406, 0 differ. The new
  paths (direct_adj, ring2_adj, ring5_adj, direct_pre, direct_pre_adj,
  align, balance) were computed but not compared, as no earlier run has
  them. Nothing ran at 0.25%.
- 2026-11-08: still exploring. Campaign 0002 checked the new paths of the
  registered analysis on the exploration half at 0.50% (run 42514591508):
  all seven structural checks pass, and 1,294 pooled close pairs
  (2008-2020) have exactly one incumbent, against a threshold of 200. Counts
  and pass or fail only; no estimate, and nothing at 0.25%.
- 2026-11-09: still exploring. Campaign 0003 counted close pairs with exactly
  one incumbent at 0.25% on the exploration half (run 42681937536): 813
  pooled 2008-2020 (184, 180, 218 and 231 by election), against a threshold
  of 200. Counts only; no estimate.

## Log

- 2026-11-03: feasibility census: issue #70, PR #71, run 41719271978
  (`research/explore-runs/0001/41719271978.md`); `research/lessons.md` entry of
  the same date.
- 2026-11-04: kill criterion 1: issue #85, PR #86, run 41839642406
  (`research/explore-runs/0001/41839642406.md`), record PR #87;
  `research/lessons.md` entry of the same date.
- 2026-11-04: exposure options: issue #116, PR #118, run 41913964880
  (`research/explore-runs/0001/41913964880.md`), record PR #119;
  `research/lessons.md` entry of the same date.
- 2026-11-05: displacement options: issue #161, PR #163, run 41949908031
  (`research/explore-runs/0001/41949908031.md`), record PR #164;
  `research/lessons.md` entry of the same date.
- 2026-11-06: placebo (kill criterion 2): issue #189, PR #191, run 42193625417
  (`research/explore-runs/0001/42193625417.md`), record PR #192;
  `research/lessons.md` entry of the same date.
- 2026-11-06: minimum detectable effects (for decision 0007): issue #194, PR
  #196, run 42265146230 (`research/explore-runs/0001/42265146230.md`), record
  PR #197; `research/lessons.md` entry of the same date.
- 2026-11-06: main exploration (kill criteria 3 and 4): issue #201, PR #203,
  run 42298466207 (`research/explore-runs/0001/42298466207.md`), record PR
  #204; `research/lessons.md` entry of the same date.
- 2026-11-07: close-race window by covariate balance: issue #206, PR #212,
  run 42366460941 (`research/explore-runs/0001/42366460941.md`), record PR
  #219; decision 0008; `research/lessons.md` entry of the same date.
- 2026-11-07: kill criterion 1 at 0.25%: issue #224, PR #225, run
  42384056410 (`research/explore-runs/0001/42384056410.md`), record PR #228;
  decision 0009; `research/lessons.md` entry of the same date.
- 2026-11-08: registered-analysis check at 0.50%: issue #241, PR #236, run
  42476480500 (`research/explore-runs/0001/42476480500.md`), record PR
  #243; `research/lessons.md` entry of the same date.
