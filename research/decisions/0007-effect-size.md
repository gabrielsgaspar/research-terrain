---
id: "0007"
title: "The effect size for kill criteria 3 and 4, and the design's power at it"
status: proposed
date: 2026-11-06
supersedes: null
---

# 0007: The effect size for kill criteria 3 and 4, and the design's power at it

Date: 2026-11-06. Status: proposed; the effect size is Gabriel's decision.
The main exploration (kill criteria 3 and 4, `explore/0001_effects.py`) waits
for it.

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
averages over the treated units.

## Proposal

| Choice | Options | Proposal | Why |
| --- | --- | --- | --- |
| Effect size | 5%; 8%; 10%; 15% of baseline clearing | **8% of baseline four-year clearing** | The lower end of the anchors (Burgess 8.2%, three-year cumulative, the closest match to a four-year window; Pailler 8-10%). The lower end is the conservative choice for power. |
| Exposure point at which it is read | median; mean; 90th percentile of \|D\| (\|G\|) among exposed cells | **The mean** | Under a linear effect, the mean effect over exposed cells is slope × mean \|D\| / baseline, which matches the literature's figures (averages over treated units). The median makes power look easy; the 90th percentile asks a cell at the edge of the distribution to carry the literature's average. |
| Effect size for kill criterion 3 (the split) | (A) the difference β^indigenous − β^settlement equals the effect size, on the indigenous-side cells; (B) each type moves by the effect size in its predicted direction, so the difference is twice as large | **(A)** | The weakest version of the claim (only one side moves) still predicts a gap of one effect size; (B) assumes both predictions hold at full size. |
| Window | as decided | four-year primary, two-year secondary | Power is reported for both; the verdicts use the four-year window. |

**Power at the proposal** (8% at mean exposure; 10% for comparison),
four-year window (two-year in brackets):

| Estimate | Test | Power at 8% | Power at 10% | 80% reached at 8%? |
| --- | --- | --- | --- | --- |
| 1. Direct | two-sided 5% | 0.94 (0.92) | 0.99 (0.99) | yes |
| 2. Displacement | two-sided 5% | **0.797** (0.72) | 0.94 (0.89) | **no, by 0.3 points** |
| 3. Split 5 km, difference, reading (A) | one-sided 5% | 0.45 (0.43) | 0.60 (0.57) | no |
| 3. Split 5 km, difference, reading (B) | one-sided 5% | 0.99 (0.98) | 1.00 (1.00) | yes |
| 3. Split 2 km, difference, reading (A) | one-sided 5% | 0.30 (0.29) | 0.41 (0.40) | no |

Power is computed as Φ(τ / SD_RI − z), with τ the slope that gives the effect
size at the mean exposure. It treats the re-flip distribution of
pre-election slopes as the sampling distribution under the alternative.

What follows at the proposal:

- **Kill criterion 3** (reading A) cannot be applied at 80% power on this
  half: by Gabriel's decision of 2026-11-06, it stays as written and the
  result is reported as "cannot be applied at 80% power on this half".
- **Kill criterion 4** needs both effects to be powered. At 8% the direct
  effect is (0.94); the displacement effect is just short (0.797). Strictly,
  kill criterion 4 cannot be applied at 8% either. Moving to 10% would clear
  it, but choosing the size because it clears the bar is the forking path
  this decision exists to close, so that is not proposed.

## For Gabriel to decide

1. The effect size: 8% as proposed, or another figure (10% is the top of the
   anchored range).
2. The exposure point: the mean as proposed, or the median or 90th
   percentile.
3. Kill criterion 3's reading: (A) as proposed, or (B).
4. **New, not covered on 2026-11-06:** what to report if kill criterion 4 is
   underpowered for one of its two effects (as the displacement effect is at
   8%). The natural parallel to kill criterion 3 is "cannot be applied at 80%
   power on this half", with the criterion unchanged.
5. Whether idea 0001's kill-criteria text changes. Nothing here requires it.
   If accepted, the effect size goes into the pre-analysis plan as fixed
   here.

## Caveats

- Spread is measured on pre-election clearing; post-election clearing may
  vary more or less. The 2020 term's last year (2024) is provisional in
  MapBiomas Collection 10.
- Context, not a test: the pre-election displacement slope has RI p 0.06
  (four-year window; run 42265146230). Kill criterion 2 covers the direct
  exposure only; the pre-analysis plan should report the displacement
  placebo.
- The 2 km split rests on 337 indigenous-side candidates and is robustness
  only.
