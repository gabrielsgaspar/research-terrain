# Pre-analysis plan for idea 0001: DRAFT

> **Draft; nothing here is registered.** Written by Claude Code in the
> autonomous run of 2026-11-07 (handoff 5, T7), for Gabriel to rewrite. The
> registered plan lives only in `confirm/pap/` and is written by a person.
> This file was written without reading anything under `confirm/` or
> `sealed/`, and it does not use the confirmation half.

## 0. The decision to take first

The exploration half gives no support to idea 0001's predictions (lessons
entry of 2026-11-06, run 42298466207). The direct effect is about zero and
rules out ±3.5% of baseline. The displacement estimate is as large before the
election as after it. The constituency split points the wrong way. No kill
criterion is met, but the confirmation half can be spent only once. Since
then, decision 0008 found the 0.50% window of those runs unbalanced on
incumbency and chose 0.25%, which lowers every power figure below. **Before
this plan is registered, Gabriel decides whether the confirmation half is
spent on this design**, on a revised one, or kept for another idea (0003 or
0004). Sections 1-7 describe the plan as it would stand if he decides to
spend it on idea 0001 unchanged.

## 1. Hypotheses

From `research/ideas/0001-electoral-strongholds.md` (Prediction), fixed
before the confirmation half is read:

- **H1, direct effect.** A narrow council win changes clearing in the 1 km
  cells around the winner's stronghold, relative to the loser's. The
  pooled sign is not predicted (it differs by constituency type), so the
  test is two-sided.
- **H2, displacement.** Unrepresented cells (decision 0005) near a newly
  represented stronghold see more clearing. Tested two-sided, as kill
  criterion 4 reads it.
- **H3, constituency split.** The effect around indigenous-side strongholds
  is below the effect around settlement-side strongholds (5 km, exclusive
  types). Tested one-sided at 5% (δ < 0), two-sided p reported.
- **H0, placebo.** The same exposure has no effect on clearing in the four
  years before the election.

## 2. Outcomes

Decision 0006: MapBiomas Collection 10, loss of primary vegetation (code 4),
as the share of each 1 km cell (`cell_outcomes`).

- **Primary:** Y4, the sum over the four years after the election (E+1 to
  E+4). The election year E is in no window.
- **Secondary:** Y2 (E+1 to E+2).
- **Displacement, secondary:** ΔY = Y4 − Ypre, with Ypre the sum over E-4 to
  E-1 (decision 0007). It has no kill-criterion role.
- **Placebo:** Ypre on the direct exposure.
- Sensitivity: for 2020, Y3 (2021-2023), because 2024 is provisional in
  Collection 10.

Elections 2008, 2012, 2016 and 2020. 2024 waits for its four post-election
years (2025-2028).

## 3. Window

**0.25%** of the municipality's valid council votes (decision 0008,
accepted by rule on 2026-11-07; Gabriel to review). The rule of issue #206
picks the widest window whose covariate-balance omnibus p is at least 0.15,
with every narrower window also at least 0.15. On the exploration half
(run 42366460941, 2008-2024 pooled) the omnibus p is 0.191 at 0.10%, 0.548
at 0.25% and 0.119 at 0.50%, so 0.25% is chosen.

- **Pairs:** 2,869 at 0.25% on the exploration half (2008-2024), 2,328 of
  them in 2008-2020, against 3,684 at 0.50%.
- **The 0.50% results of 2026-11-06** stand as pre-specified, with a caveat:
  at 0.50% narrow winners had held the seat 2.3 points more often than
  narrow losers (RI p 0.014). The plan does not re-run them at 0.25% on the
  exploration half; no merged issue specifies that.
- **Incumbency is still the weak covariate at 0.25%:** +2.0 points (RI p
  0.084), almost the 0.50% gap; 0.25% passes mainly because it has fewer
  pairs. See open choice B (section 4).
- **The registered run reports the balance table** (the ten covariates of
  issue #206, winner minus loser, RI p and the omnibus p) on the
  confirmation half at 0.25%, before any outcome. Whether a failing omnibus
  there stops the run is open choice C.

## 4. Treatment, exposure and estimators

- **Pairs:** within-list close pairs (`terrain.strongholds`): the elected
  candidate with the fewest votes against the non-elected candidate with the
  most, per list, with margin = (elected − other) / valid council votes,
  inside the window of section 3.
- **Direct exposure (decision 0004):** `exp2`, the exp(-d/2 km)-weighted
  vote share of each candidate at the polling places of its municipality
  within 10 km, winner minus loser, summed over the municipality's close
  pairs (D), recentred as D / 2. The 2 and 5 km rings are robustness.
- **Displacement exposure (decision 0005):** `g_exp10` on unrepresented cells
  (empty in 2022 and beyond the direct reach), exp(-d/10 km) to 50 km,
  recentred G / 2. The 10-20 and 20-50 km rings are robustness.
- **Split:** the direct exposure divided into components by the type of each
  side's stronghold (indigenous, settlement, both, neither, untyped; 5 km,
  2 km as robustness), estimated jointly; δ = β_indigenous − β_settlement.
- **Regression:** OLS of the outcome on the recentred exposure, with
  municipality-by-election fixed effects, pooled over elections, exactly as
  `explore/0001_effects.py` at commit `ce10d89` (run 42298466207).
- **Inference:** randomisation inference, 2,000 re-flips of the close pairs
  (each independently with probability 1/2, seed 20261106), one sign vector
  per draw shared by every estimate. p = (1 + #{|b_r| ≥ |b|}) / (1 + 2,000);
  for H3, p1 = (1 + #{δ_r ≤ δ}) / (1 + 2,000). Municipality-clustered
  standard errors are reported as a check.
- **Open choice B: incumbency.** (a) Report incumbency balance only, and
  estimate as above; or (b) also report each estimate with the pair's
  incumbency difference (winner minus loser, held the seat before) as a
  control, as a secondary line. Recommendation: (b), secondary only. The
  primary estimate stays the plain local-randomisation contrast, as
  decisions 0004 and 0005 define it; the control line shows how much the
  0.25% incumbency gap could move it.

## 5. Effect size and power (decision 0007)

- **Effect size:** 8% of baseline four-year clearing, read at the mean
  exposure among exposed cells (the median and 90th-percentile readings
  reported alongside). For the split, a gap of one effect size on the
  indigenous-side cells.
- **Power:** Φ(τ / SD_RI − z), with τ the slope that gives 8% at the mean
  exposure, SD_RI the re-flip spread and z = 1.96 (1.645 for the one-sided
  split).
- On the exploration half at 0.25% (decision 0008, 2,328 pairs, 2008-2020):
  **direct 0.868, displacement 0.622, split 0.307** (5 km, one-sided). At
  0.50% they were 0.944, 0.797 and 0.448 (decision 0007).
- **Open choice A:** where SD_RI comes from on the confirmation half.
  (a) Computed inside the one registered run, on the confirmation half's
  pre-election clearing, before any post-election number is printed; or
  (b) carried over from the exploration half. Recommendation: (a). The
  confirmation half's spread is its own, and it uses only pre-election years.
  The registered run must print the power lines before the estimates.

## 6. Kill criteria, and how each is read on the confirmation half

Texts as in the idea file (unchanged; decision 0007).

1. **Too little constituency variation** (fewer than 200 close-pair
   candidates within 5 km of an indigenous land, or of a settlement).
   Counted first on the confirmation half, from treatment-side data only.
   If met, the run stops before any outcome is read. The criterion's text
   names 0.5% and is not changed; the plan counts at 0.25%, the registered
   window. On the exploration half at 0.25% the counts are 280
   indigenous-side and 1,257 settlement-side in 2008-2020 alone (the
   criterion pools 2008-2024, which can only add), both above 200, though the indigenous count is closer to the bar than at 0.50% (455).
   Gabriel to say whether "0.5%" in its text is read as "the registered
   window".
2. **Non-flat placebo** (Ypre on the direct exposure, RI p below 0.05). If
   met, the idea fails on the confirmation half and the post-election
   estimates are reported as uninterpretable.
3. **Wrong signs by constituency type.** Met if δ is not below zero
   (one-sided p1 ≥ 0.05) **and** the split's power is at least 0.80. If the
   power is below 0.80: "cannot be applied at 80% power on this half".
4. **No effect at all.** Not met if either effect is clearly non-zero (Holm
   across direct and displacement, 5% overall: the smaller p below 0.025),
   whatever the power. Met if neither is non-zero and both powers are at
   least 0.80. Otherwise "cannot be applied at 80% power on this half".
   At 0.25%, displacement's exploration power is 0.622, so the "met"
   branch probably cannot be reached on a half of this size.

### Kill criterion 3's expected power is near 0.31

If the confirmation half has about as many indigenous-side candidates as the
exploration half (280 at 5 km, 2008-2020, at 0.25%), kill criterion 3 will
have power near 0.31 there (0.45 at the 0.50% window used before). As
written, it would then almost surely read "cannot be applied", and the
confirmation half would say nothing about the split.
Options, to be chosen **before** registration:

- **(i) Keep as written** and accept that kill criterion 3 is probably not
  applicable. Honest, but it spends the split's only confirmatory test on a
  likely non-answer.
- **(ii) Make H3 secondary:** report δ, p1 and its power, with no kill
  role. The confirmatory tests are then H1 and H2 (kill criterion 4) and the
  placebo. This is the plainest reading of a test with 0.45 power.
- **(iii) Raise the split's effect size** (for example a gap of two effect
  sizes) to reach 80%. This changes the question, and choosing it after
  seeing the exploration half's δ is a forking path. Not recommended.
- **(iv) Pool both halves for H3 only.** This breaks the split: the
  exploration half's δ has been seen. Not allowed under decision 0001.
- **(v) More pairs:** a wider window would raise power. Checked: decision
  0008's window is narrower, 0.25%, and the expected power falls to 0.307
  (exploration half, run 42366460941). A wider window is not available
  under the balance rule. This option is closed.

Recommendation: **(ii)**. With (v) closed, the split's expected power is
0.31, so a kill role would almost surely read "cannot be applied". Kill
criterion 4 has the same problem in its displacement branch (0.622); the
same choice, (i) or (ii), may be wanted there, for Gabriel to decide.

## 7. What is reported, whatever the result

Every number of sections 4-6, for both windows (Y4 and Y2) and every
robustness kernel; the placebo next to each effect; ΔY next to the
displacement effect; counts of pairs, cells and candidates per type; the
power lines first. Dead ends are results. The run happens once, through
`confirm-run`, and its record is committed as it comes out.

## 8. What this draft does not settle

- Section 0 (whether to spend the confirmation half on this design).
- Decision 0008 itself, accepted by rule; Gabriel to review (section 3).
- Open choice A (where the confirmation half's power comes from).
- Open choice B (incumbency as a secondary control).
- Open choice C: whether a failing omnibus balance test on the confirmation
  half at 0.25% stops the run, or is reported next to the estimates.
  Suggested: reported, not a stop, because the window is fixed before the
  confirmation half is opened and cannot be re-chosen there.
- Kill criterion 1's "0.5%" read as the registered window (section 6).
- Kill criterion 3's option, and whether kill criterion 4's displacement
  branch is treated the same way (section 6).
