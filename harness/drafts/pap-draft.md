# Pre-analysis plan for idea 0001: DRAFT

> **Draft; nothing here is registered.** Written by Claude Code (handoff 5,
> T7), revised on 2026-11-07 to match decision 0009 and then Gabriel's
> rulings on the follow-up report. For Gabriel to rewrite. The registered
> plan lives only in `confirm/pap/` and is written by a person (section 9).
> This file was written without reading anything under `confirm/` or
> `sealed/`, and it does not use the confirmation half.

## 0. What the confirmation is

**A registered test of the direct effect** (decision 0009). The
confirmation half answers one question: does a narrow council win change
clearing around the winner's stronghold, relative to the loser's (H1)? The
answer is gated by kill criterion 1 (enough constituency variation) and
checked by the placebo (kill criterion 2). Displacement (H2), the
constituency split (H3) and the alignment split (H4) are estimated and
reported in full, but as secondary results: none of them can kill the idea.

The exploration half points to a null on H1 (2026-11-06: the direct slope is
about zero and rules out ±3.5% of baseline, at the 0.50% window, which
decision 0008 later found unbalanced on incumbency). **When** to spend the
confirmation half is Gabriel's decision; section 9 lists what registration
needs first.

## 1. Hypotheses

From `research/ideas/0001-electoral-strongholds.md` (Prediction), fixed
before the confirmation half is read:

- **H1, direct effect (confirmatory).** A narrow council win changes
  clearing in the 1 km cells around the winner's stronghold, relative to the
  loser's. The pooled sign is not predicted (it differs by constituency
  type), so the test is two-sided.
- **H0, placebo (confirmatory check).** The same exposure has no effect on
  clearing in the four years before the election.
- **H2, displacement (secondary).** Unrepresented cells (decision 0005) near
  a newly represented stronghold see more clearing. Two-sided.
- **H3, constituency split (secondary).** The effect around indigenous-side
  strongholds is below the effect around settlement-side strongholds (5 km,
  exclusive types). One-sided at 5% (δ < 0), two-sided p reported.
- **H4, alignment split (secondary, descriptive, underpowered).** The direct
  slope for close pairs aligned with the elected mayor, and for unaligned
  pairs (idea 0004, dead as a standalone design). Reported with no verdict
  and no kill criterion; its power is about 0.34 (section 5).

## 2. Outcomes

Decision 0006: MapBiomas Collection 10, loss of primary vegetation (code 4),
as the share of each 1 km cell (`cell_outcomes`).

- **Primary:** Y4, the sum over the four years after the election (E+1 to
  E+4). The election year E is in no window.
- **Secondary:** Y2 (E+1 to E+2).
- **Displacement, secondary:** ΔY = Y4 − Ypre, with Ypre the sum over E-4 to
  E-1 (decision 0007).
- **Placebo:** Ypre on the direct exposure.
- Sensitivity: for 2020, Y3 (2021-2023), because 2024 is provisional in
  Collection 10.

Elections 2008, 2012, 2016 and 2020. 2024 waits for its four post-election
years (2025-2028).

## 3. Window and balance

**0.25%** of the municipality's valid council votes (decision 0008, accepted
by Gabriel on 2026-11-07). On the exploration half (run 42366460941,
2008-2024 pooled) the omnibus balance p is 0.191 at 0.10%, 0.548 at 0.25%
and 0.119 at 0.50%. The window was chosen by the rule of issue #206 and is
not re-chosen on the confirmation half.

- **Pairs:** 2,869 at 0.25% on the exploration half (2008-2024), 2,328 of
  them in 2008-2020.
- **Incumbency** is the weak covariate: at 0.25%, narrow winners had held
  the seat 2.0 points more often than narrow losers (RI p 0.084), almost the
  0.50% gap (2.3 points, p 0.014).
- **The registered run prints the balance table first** (issue #206's ten
  covariates, winner minus loser, RI p and omnibus p) on the confirmation
  half at 0.25%, before any outcome.
- **The fallback is triggered by decision 0008's omnibus test only:** the
  minimum RI p across the ten covariates, set against the re-flip
  distribution of that minimum. **If the omnibus p is below 0.15**, the
  table is reported, the window stays 0.25%, and the incumbency-adjusted
  direct estimate (section 4) becomes the estimate that kill criteria 2 and
  4 are read on. A single covariate's p below 0.15 does not trigger it
  (decision 0009, point 5 and Gabriel's ruling of 2026-11-07).

## 4. Treatment, exposure and estimators

- **Pairs:** within-list close pairs (`terrain.strongholds`): the elected
  candidate with the fewest votes against the non-elected candidate with the
  most, per list, with margin = (elected − other) / valid council votes,
  inside the 0.25% window.
- **Direct exposure (decision 0004):** `exp2`, the exp(-d/2 km)-weighted
  vote share of each candidate at the polling places of its municipality
  within 10 km, winner minus loser, summed over the municipality's close
  pairs (D), recentred as D / 2. The 2 and 5 km rings are robustness.
- **Displacement exposure (decision 0005):** `g_exp10` on unrepresented
  cells (empty in 2022 and beyond the direct reach), exp(-d/10 km) to 50 km,
  recentred G / 2. The 10-20 and 20-50 km rings are robustness.
- **Constituency split:** the direct exposure divided into components by the
  type of each side's stronghold (indigenous, settlement, both, neither,
  untyped; 5 km, 2 km as robustness), estimated jointly; δ = β_indigenous −
  β_settlement.
- **Alignment split (H4):** idea 0004's definitions. A side is aligned if
  its party is in the elected mayor's coalition in the same election
  (`tse_parties` coalition rows of the deciding mayoral round; from 2024 a
  federation counts when it is in the coalition). A pair is aligned when
  both sides are, unaligned when neither is; mixed pairs are counted and
  left out. The direct slope is estimated separately on aligned and on
  unaligned pairs, with one set of re-flips shared by both, and the
  difference is reported. Exploration half at 0.25%, 2008-2020: 1,100
  aligned and 1,219 unaligned pairs (run 42384829937).
- **Regression:** OLS of the outcome on the recentred exposure, with
  municipality-by-election fixed effects, pooled over elections, exactly as
  `explore/0001_effects.py` at commit `ce10d89` (run 42298466207).
- **Inference:** randomisation inference, 2,000 re-flips of the close pairs
  (each independently with probability 1/2, seed 20261106), one sign vector
  per draw shared by every estimate. p = (1 + #{|b_r| ≥ |b|}) / (1 + 2,000);
  for H3, p1 = (1 + #{δ_r ≤ δ}) / (1 + 2,000). Municipality-clustered
  standard errors are reported as a check.
- **Incumbency-adjusted direct estimate (registered robustness check,
  decision 0009, point 4; term accepted by Gabriel on 2026-11-07).**
  Reported next to the unadjusted estimate in every run. The term is
  **D^inc**: a cell's exposure to incumbent winners minus incumbent losers,
  built like D, with the same kernel (`exp2`) and the same close pairs. Per
  pair, the winner's exposure counts if the winner held the seat before, and
  the loser's exposure is subtracted if the loser held the seat before;
  D^inc sums this over the municipality's close pairs. **D^inc / 2 is added
  to the direct regression**, next to D / 2, with the same fixed effects.
  Incumbency is as rebuilt in task 35 (the previous election's elected
  councillors). **The re-flips are unchanged:** the same 2,000 sign
  vectors, the same seed, and each re-flip swaps a pair's winner and loser
  in D and D^inc alike. The adjusted direct estimate is the coefficient on
  D / 2, and its RI p is computed as above.
  - *Note (Claude Code), for Gabriel before registration:* this term is not
    the one the previous draft proposed. The earlier term (Z, the
    incumbent side's exposure minus the other side's, over pairs whose
    sides differ in incumbency) does not depend on who won, so it stays
    fixed under re-flips. D^inc depends on who won and flips with the pair.
    With D / 2 and D^inc / 2 both in the regression, the coefficient on
    D / 2 is the effect around non-incumbent sides, and the coefficient on
    D^inc / 2 is how much the effect differs around incumbent sides. The
    RI test of the coefficient on D / 2 is still valid. But a term that
    flips with the pair does not absorb a fixed difference between
    incumbent and non-incumbent sides, which is the balance concern. If
    "adjusted for incumbency" means removing that difference, Z is the
    term; if it means letting the effect differ by incumbency, D^inc is.
    The text above follows Gabriel's wording.

## 5. Effect size and power (decisions 0007 and 0009)

- **Effect size:** 8% of baseline four-year clearing, read at the mean
  exposure among exposed cells (median and 90th-percentile readings
  reported alongside). For the constituency split, a gap of one effect size
  on the indigenous-side cells; for the alignment split, a gap of one effect
  size between aligned and unaligned slopes.
- **Power is carried over from the exploration half** (decision 0009, point
  3): the halves are a stratified random split of the same size, so the
  sealed half is not read before registration, not even its pre-election
  years. At 0.25% (decision 0008, 2,328 pairs, 2008-2020): **direct 0.868**,
  displacement 0.622, constituency split 0.307 (5 km, one-sided).
  Formula: Φ(τ / SD_RI − z), with τ the slope that gives 8% at the mean
  exposure, SD_RI the re-flip spread and z = 1.96 (1.645 for the split).
- **Alignment split: about 0.34, underpowered.** A rough scaling of the
  direct power (run 42384829937), not a computation on outcomes: Φ(K ·
  √((1/2,328) / (1/1,100 + 1/1,219)) − 1.96) with K = 1.96 + Φ⁻¹(0.868),
  giving 0.335 (0.337 for an even split, the best case). 80% would need a
  gap of about 1.8 effect sizes.
- The registered run reports these carried-over figures. It does not
  recompute power on the confirmation half.

## 6. Kill criteria, and how each is read on the confirmation half

Texts as in the idea file (unchanged). Readings from decisions 0007 and
0009, with Gabriel's rulings of 2026-11-07.

1. **Too little constituency variation** (fewer than 200 close-pair
   candidates within 5 km of an indigenous land, or of a settlement). "0.5%"
   in its text means the registered window, 0.25% (decision 0009, point 1).
   Counted first on the confirmation half, from treatment-side data only;
   if met, the run stops before any outcome is read. On the exploration
   half at 0.25%, pooled 2008-2024: 434
   candidates within 5 km of an indigenous land and 1,625 within 5 km of a
   settlement (run 42384056410; 711 and 2,590 at 0.50%), so the criterion
   is not met there. If the confirmation half is about as large, the
   indigenous count would be about twice the 200 bar.
2. **Non-flat placebo** (Ypre on the direct exposure, RI p below 0.05). If
   met, the idea fails on the confirmation half and the post-election
   estimates are reported as uninterpretable. Read on the same estimate as
   kill criterion 4 (unadjusted, or incumbency-adjusted under section 3's
   fallback).
3. **Wrong signs by constituency type: secondary, no kill role** (decision
   0009, point 2). δ, its one-sided p1 and its power (about 0.31) are
   reported, with no verdict.
4. **No effect at all.** Judged on the direct effect alone, at 5% (decision
   0009, accepted by Gabriel on 2026-11-07). Not met if the direct effect
   is clearly non-zero (two-sided RI p below 0.05, the only confirmatory
   test). Met if it is not clearly non-zero and its power (0.868, carried
   over) is at least 0.80, which it is. The displacement branch is
   secondary (decision 0009, point 2): the displacement estimate, its p and
   its power (0.622) are reported, and it cannot make the criterion met. By
   the criterion's text, a clearly non-zero displacement effect would still
   mean "not met".

The alignment split (H4) has no kill criterion.

## 7. What is reported, whatever the result

In this order: the balance table and the omnibus p; kill criterion 1's
counts; the carried-over power lines; the placebo; the direct estimate,
unadjusted and incumbency-adjusted (with the coefficient on D^inc / 2), for
Y4 and Y2 and every robustness kernel; displacement with ΔY; the
constituency split; the alignment split (aligned and unaligned slopes, their
difference and its RI p, labelled underpowered, with no verdict); counts of
pairs, cells and candidates per type, and aligned, unaligned and mixed
pairs. Dead ends are results. The real run happens once, through `unblind`,
after a shuffled run through `confirm-run` (section 9), and its ledger entry
is committed as it comes out.

## 8. What this draft does not settle

- When to spend the confirmation half (section 0).
- Whether the incumbency term is D^inc as written, or the fixed term Z
  (section 4, note).
- The registered specification file in `confirm/specs/` and the analysis
  code it names. The `confirm-run` and `unblind` workflows are built in a
  separate pull request that waits for Gabriel's review; the estimator code
  for this plan is not written yet and would be written, reviewed and
  merged before registration.

## 9. Registration

What Gabriel must do, in this order, before any run on the confirmation
half:

1. **Merge the plan into `confirm/pap/`.** Rewrite this draft in his own
   words and merge it in a pull request that he writes (agents never touch
   `confirm/`).
2. **Record its commit hash.** The merge commit that adds the plan to
   `confirm/pap/` is the registration commit. Its hash goes into the
   registered specification in `confirm/specs/` and into the external
   registration.
3. **Register it externally**, with the plan and the commit hash, before
   `confirm-run` is started. The date of the external registration is the
   date the plan was fixed.

After registration: `confirm-run` on the registered specification
(shuffled treatment; it must give nothing), then `unblind`, once, with
Gabriel's approval.
