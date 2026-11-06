---
id: "0007"
title: "The effect size for kill criteria 3 and 4, and the design's power at it"
status: accepted
date: 2026-11-06
supersedes: null
---

# 0007: The effect size for kill criteria 3 and 4, and the design's power at it

Date: 2026-11-06. Status: accepted by Gabriel on 2026-11-06, with the
changes recorded under "Decision" below. The main exploration (kill criteria
3 and 4, `explore/0001_effects.py`) follows from it.

## The question

Kill criteria 3 and 4 of idea 0001 need "at least 80% power for the effect
size fixed in the pre-analysis plan". Which effect size, fixed before anyone
looks at post-election clearing, and does the design reach 80% power at it?

Already decided by Gabriel on 2026-11-06: the effect size is anchored in the
literature and then checked against the design's minimum detectable effect;
the primary outcome window is the four years after the election (t+1 to t+4),
the secondary t+1 and t+2; constituency types use 5 km, exclusive (2 km as
robustness); kill criterion 3 is tested one-sided at 5% (two-sided p
reported); if the split is underpowered, kill criterion 3 stays as written
and is reported as "cannot be applied at 80% power on this half".

## Evidence: what the design can detect

`explore/0001_power.py`, run 42265146230
(`research/explore-runs/0001/42265146230.md`, lessons entry of 2026-11-06),
exploration half, elections 2008-2020. **Only pre-election clearing was read**
(E-4..E-1), the window of the placebo, so no post-election year has been seen.
The spread of each slope over 2,000 re-flips of the close pairs (seed
20261106) gives its minimum detectable effect (MDE) at 80% power: 2.8 × the
re-flip SD (two-sided 5%), and 2.487 × for the one-sided split difference.
The re-flip quantiles give the same MDEs within a few percent.

A slope is read as an effect people can judge: under the swap
counterfactual a cell's exposure moves by D, so the effect is slope × |D|, as
a percentage of the baseline clearing of the exposed cells (mean Y over the
same window). Exposure is skewed (direct: median |D| 0.032, mean 0.071, 90th
percentile 0.19), so the reading depends on the exposure point.

Candidates per type at 5 km, 2008-2020 pooled: 455 indigenous-side, 1,987
settlement-side, 96 both, 4,791 neither, 39 untyped (no typed stronghold).
At 2 km: 337 and 1,211. Both main types are above 200.

**MDE as % of baseline clearing** (four-year window; two-year in brackets):

| Estimate | MDE slope | at median exposure | at mean exposure | at 90th percentile |
| --- | --- | --- | --- | --- |
| 1. Direct, `exp2` (baseline 0.027) | 0.024 (0.012) | 2.8% (3.0%) | 6.3% (6.7%) | 17% (18%) |
| 2. Displacement, `g_exp10` (baseline 0.017) | 0.018 (0.009) | 3.7% (4.1%) | 8.0% (8.8%) | 22% (24%) |
| 3. Split 5 km, β indigenous | 0.036 (0.018) | 3.9% (4.0%) | 10.0% (10.3%) | 26% (27%) |
| 3. Split 5 km, β settlement | 0.041 (0.020) | 3.1% (3.3%) | 7.2% (7.6%) | 19% (20%) |
| 3. Split 5 km, difference, one-sided | 0.047 (0.024) | 5.1% (5.3%) | 13.1% (13.6%) | 34% (36%) |
| 3. Split 2 km, difference, one-sided | 0.054 (0.027) | 6.7% (6.9%) | 17.7% (18.0%) | 48% (49%) |

For the difference, the percentage uses the indigenous-side cells' exposure
and baseline (0.021).

## Literature anchors

- Burgess, Hansen, Olken, Potapov and Sieber (2012), QJE 127(4):1707-1754
  (note: `research/references/burgessPoliticalEconomyDeforestation2012.md`).
  One more district in a province raises the province's deforestation by
  **8.2%** three years after the split (Table IV, Panel B, col. 1: 0.0822, SE
  0.0204; p. 1735, and p. 1709 without the qualifier); the same-year effect
  is 3.85% (Panel A). Province × forest-zone units, MODIS pixels, 2001-2008.
- **Correction to the handoff:** the "42% more illegal logging in the year
  before local elections" figure is **not in the published QJE paper**
  (checked in the full text; its only election variable is a dummy for
  whether the direct district-head election has happened, Table VII). It is
  attributed to the 2011 working paper, which is not in Zotero. It is not used
  here; if Gabriel wants it, the working paper must be added and checked
  first.
- Balboni, Berman, Burgess and Olken (2023), Annual Review of Economics
  15:723-754 (note: `research/references/balboniEconomicsTropicalDeforestation2023.md`).
  The figure taken from it: **deforestation 8-10% higher in election years
  where the incumbent mayor runs again, Brazil 2002-2012** (Pailler 2018;
  section 4.4.2.3, p. 746), the only Brazilian electoral magnitude in the
  review. For scale, it also reports much larger policy effects: Brazil's
  Priority List -43% (p. 745), a 50% rise in DETER enforcement -25% (p. 746).
  Those are national enforcement programmes, much larger treatments than one
  council seat.

The political-economy effects closest to ours (who holds local office, at the
time of an election) are therefore 8-10% of baseline deforestation. Both are
averages over the treated units. **The Burgess anchor is a province-level
effect of a district split**, a different unit and treatment from a 1 km
cell's exposure to one close council race, so it sets the order of magnitude
of the effect size, not an exact equivalent.

## Decision

| Choice | Options | Decision | Why |
| --- | --- | --- | --- |
| Effect size | 5%; 8%; 10%; 15% of baseline clearing | **8% of baseline four-year clearing** | The lower end of the anchors (Burgess 8.2%, three-year cumulative, the closest match to a four-year window; Pailler 8-10%), the conservative choice for power. The anchors set the order of magnitude, not an exact equivalent (above). |
| Exposure point at which it is read | median; mean; 90th percentile of \|D\| (\|G\|) among exposed cells | **The mean; the median and 90th-percentile readings are reported alongside** | Under a linear effect, the mean effect over exposed cells is slope × mean \|D\| / baseline, which matches the literature's figures (averages over treated units). |
| Effect size for kill criterion 3 (the split) | (A) the gap β^indigenous − β^settlement equals one effect size, on the indigenous-side cells; (B) each type moves by the effect size in its predicted direction | **(A), a gap of one effect size** | The weakest version of the claim (only one side moves) still predicts a gap of one effect size. |
| Window | as decided on 2026-11-06 | four-year primary, two-year secondary | Power is reported for both; the verdicts use the four-year window. |
| Idea 0001's kill-criteria text | change; keep | **Unchanged** | The decision fixes the effect size the text refers to; the text itself needs no change. |

**Power at 8%**, four-year window (two-year in brackets). Effect read at the
mean exposure (decisive), with the median and 90th-percentile readings
alongside:

| Estimate | Test | At the mean (decisive) | At the median | At the 90th percentile | 80% reached? |
| --- | --- | --- | --- | --- | --- |
| 1. Direct | two-sided 5% | 0.94 (0.92) | 1.00 (1.00) | 0.26 (0.23) | yes |
| 2. Displacement | two-sided 5% | **0.797** (0.72) | 1.00 (1.00) | 0.17 (0.15) | **no** |
| 3. Split 5 km, gap of one effect size | one-sided 5% | **0.45** (0.43) | 0.99 (0.98) | 0.14 (0.14) | **no** |
| 3. Split 2 km (robustness), same | one-sided 5% | 0.30 (0.29) | 0.90 (0.89) | 0.11 (0.11) | no |

For comparison, at 10% (mean exposure): direct 0.99, displacement 0.94,
split 5 km 0.60. Power is Φ(τ / SD_RI − z), with τ the slope that gives the
effect size at the chosen exposure point. It treats the re-flip distribution
of pre-election slopes as the sampling distribution under the alternative.

### How kill criteria 3 and 4 are applied on this half

- **Kill criterion 3** is read as a gap of one effect size between
  indigenous-side and settlement-side strongholds. Its power is 0.45, so on
  this half it **cannot be applied at 80% power**. The criterion is unchanged
  (Gabriel's decision of 2026-11-06); the test is still run, one-sided at 5%
  with the two-sided p alongside, and reported with that label.
- **Kill criterion 4**, the parallel rule. The displacement effect is under
  80% power (0.797), so the branch "both effects indistinguishable from zero,
  so the idea dies" is reported as **"cannot be applied at 80% power on this
  half"**. If either effect is clearly non-zero, kill criterion 4 is **not
  met, whatever the power**. The 80% bar is applied as written: no rerun or
  change of design to tighten 0.797.
- **"Clearly non-zero"** (kill criterion 4) means the two-sided
  randomisation-inference p, with a Holm correction across the two effects
  (direct and displacement) at 5% overall: order the two p-values; the
  smaller must be below 0.025 for that effect to be non-zero, and only then
  is the other non-zero if its p is below 0.05. Kill criterion 4 is not met
  if at least one effect is non-zero under this rule (that is, if the smaller
  p is below 0.025).

### Secondary displacement outcome (fixed before task B runs)

The change in clearing on the unrepresented cells:

ΔY_it = Y4_it − Ypre_it,

with Y4 the sum of loss of primary vegetation (code 4 / 10,000) over the four
years after the election (t+1 to t+4) and Ypre the same sum over the four
years before (t−4 to t−1); the election year t is in neither. Same cells as
the displacement effect (decision 0005's unrepresented cells), the same G / 2
regression, municipality-by-election fixed effects and 2,000 re-flips of the
close pairs. **It has no kill-criterion role**: kill criteria 3 and 4 use Y4
only.

Why: the displacement placebo (G / 2 on pre-election clearing) has RI p 0.06
(four-year window, run 42265146230). Kill criterion 2 covers the direct
exposure only, so this does not fail it. But it means unrepresented cells
with more exposure to the winner's stronghold may already differ before the
election, and a change outcome nets out a cell's own pre-election level.

## Caveats

- Spread is measured on pre-election clearing; post-election clearing may
  vary more or less. The 2020 term's last year (2024) is provisional in
  MapBiomas Collection 10.
- The displacement placebo (RI p 0.06) is reported next to the displacement
  results in the main exploration.
- The 2 km split rests on 337 indigenous-side candidates and is robustness
  only.

## Accepted

By Gabriel on 2026-11-06: 8% at the mean exposure, the gap reading of kill
criterion 3, the parallel rule for kill criterion 4, no change to idea 0001's
kill-criteria text, the secondary displacement outcome ΔY, and (same day)
the Holm rule for "clearly non-zero" in kill criterion 4.
