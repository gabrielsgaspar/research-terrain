---
id: "0003"
title: "Mayoral close races and the geography of deforestation"
status: proposed
created: 2026-11-07
updated: 2026-11-07
datasets:
  - tse_results
  - tse_candidates
  - municipalities
  - section_votes
  - polling_places
  - polling_place_types
  - grid_cells
  - cell_outcomes
kill_criteria:
  - "(drafted; confirm) Too little power: at the municipality level, on the exploration half (elections 2008-2020), the close mayoral races at 0.5%, 1% and 2% all give power below 0.50 for decision 0007's effect size (8% of baseline clearing), measured on pre-election clearing. Then no design on these races, municipal or stronghold, is pursued."
  - "(drafted; confirm) A non-flat placebo: in the four years before the election, the winner's turf and the runner-up's turf differ in clearing (randomisation-inference p below 0.05) on the exploration half, at the window chosen by covariate balance."
  - "(drafted; confirm) No effect at all: the winner-minus-runner-up turf contrast is indistinguishable from zero, with at least 80% power for the effect size fixed in the pre-analysis plan."
related: ["0001"]
---

# 0003: Mayoral close races and the geography of deforestation

## Claim

The mayor, not a councillor, controls most of what a municipality does to land
(licensing, roads, enforcement support, land regularisation). If electoral
geography matters, a narrowly elected mayor should change clearing around the
places that voted for them, relative to the places that voted for the
runner-up.

## Prediction

Working version, to be fixed in a pre-analysis plan before any post-election
outcome is read:

- Land near the winner's strongholds is cleared at a different rate after a
  close win than land near the runner-up's strongholds; the sign follows the
  strongholds' type, as in idea 0001 (less clearing near indigenous lands,
  more near settlements and the frontier).
- The same contrast in the four pre-election years: no difference (placebo).

Against the idea: a non-flat placebo, or no effect with adequate power.

## Design

- **Races.** Mayoral elections (`cd_cargo` 11), 2008-2024, Legal Amazon. The
  margin is the winner's votes minus the runner-up's, over valid votes. Where
  there is a run-off (state capitals and other municipalities with more than
  200,000 voters), the deciding round is used, so the margin is the second
  round's.
- **Sides.** The winner's turf and the runner-up's turf, from section votes at
  polling places, as idea 0001's strongholds. Third and later candidates'
  turf is neither side's: it is not treated and not a control.
- **Comparison.** Within close races, which of the two finalists won is as
  good as random (a local randomisation design, as idea 0001); inference by
  re-flipping which side won.
- **Outcome.** Decision 0006's loss of primary vegetation (MapBiomas code 4)
  per 1 km cell; at the municipality level, the municipal share of primary
  vegetation lost.

**Counts already found** (TSE files, whole Legal Amazon, scoping in another
session on 2026-11-07, nothing committed): pooled 2008-2024, **102 races at
0.5%, 180 at 1% and 353 at 2%**. Per election at 0.5% / 1% / 2%: 2008 18 / 38
/ 71; 2012 31 / 52 / 88; 2016 20 / 34 / 81; 2020 22 / 38 / 70; 2024 11 / 18 /
43. About half are on the exploration half (the council counts' whole-to-half
ratio was 1.95-2.04). Those counts use first-round margins: 34 municipalities
had a run-off (pooled), so the deciding-round counts can differ slightly.
Maranhão is limited to its 181 Legal Amazon municipalities; Macapá 2020
(election postponed) is left out.

**Power is the first problem.** Idea 0001 has about 765-1,060 close council
pairs per election on the exploration half; this idea has about 50 close
mayoral races at 0.5% across all five elections on that half, and about 175
at 2%. A stronghold-geography design on so few races is probably
underpowered. So the first step is a cheap power check at the municipality
level (one observation per race), on pre-election clearing only. If even
that cannot reach reasonable power at 2%, the idea is not worth a design.

## Data needed

`tse_results` (candidate votes and turnout by round), `tse_candidates`,
`municipalities`, `section_votes`, `polling_places`, `polling_place_types`,
`grid_cells`, `cell_outcomes`. All exist.

## Status

- 2026-11-07: proposed. Counts of close races recorded above; the first step
  is a municipality-level power check (handoff 5, T4), on pre-election
  clearing only.
- 2026-11-07: still proposed. The municipality-level power check (run
  42367009833) gives power 4.4%, 5.2% and 7.2% at 8% of baseline for 45, 80
  and 157 races (0.5%, 1%, 2%; exploration half, 2008-2020). The MDE is 89%,
  67% and 45% of baseline. Drafted kill criterion 1 is met. The idea is not
  worth a design unless Gabriel sees a reason to keep it. Proposed: dead,
  once he confirms the kill criteria.

## Log

- 2026-11-07: idea file written (Claude Code, autonomous run; Gabriel to
  review). Kill criteria are drafts until Gabriel confirms them.
- 2026-11-07: municipality-level power check: issue #214, PR #216, run
  42367009833 (`research/explore-runs/0003/42367009833.md`), record PR #217;
  `research/lessons.md` entry of the same date.
