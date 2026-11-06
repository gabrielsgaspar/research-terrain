# Task: the main exploration, kill criteria 3 and 4 (explore)

## Goal

Kill criteria 3 and 4 of idea 0001, on the exploration half, against the
effect size and power fixed in decision 0007
(`research/decisions/0007-effect-size.md`, accepted 2026-11-06). The script
estimates the direct effect, the displacement effect and the constituency
split on post-election clearing, and prints one verdict line for each
criterion by the rules below. It computes exactly what this issue lists and
nothing beyond it (referee R7). No effect is interpreted beyond the
verdicts.

**Outcome data in scope (for referee R2):** `cell_outcomes` for the four
years after each election E (E+1 to E+4) and the four years before (E-4 to
E-1, for the displacement placebo and the change outcome). The election year
E is never read. The years are fixed in code (`outcome_years`), not by an
argument. Exploration half only; the confirmation half stays sealed.

## Idea

`research/ideas/0001-electoral-strongholds.md` (kill criteria 3 and 4);
decisions 0004 (direct exposure), 0005 (displacement exposure), 0006
(outcome) and 0007 (effect size, power, how the criteria are applied); runs
42193625417 (placebo) and 42265146230 (power). This is an explore task (label
`explore`): it may change only `explore/` and `tests/test_explore*`.

Read first: `explore/0001_power.py`. **Reuse it** (loaded with importlib, as
it loads `0001_placebo.py` and `0001_kill_criterion_1.py`): its pair terms,
side terms, candidate types, components, displacement terms and checks,
`make_part` / `assemble` / `estimates` / `run_ri`, `ri_p` and the placebo's
`clustered_se`. Do not copy them, and do not change `0001_power.py`,
`0001_placebo.py` or `0001_kill_criterion_1.py`. Also read
`data/contracts/cell_exposure.md`, `data/contracts/cell_displacement.md` and
`data/contracts/cell_outcomes.md`.

## Definitions

- **Elections** E = 2008, 2012, 2016, 2020 (2024 has no post-election years).
  Estimates are pooled over the four; per-election numbers are counts only.
- **Outcomes** (all `code_4 / 10,000` summed over the years named):
  - `Y4` (primary): E+1 to E+4.
  - `Y2` (secondary): E+1 to E+2.
  - `Y3` (sensitivity, **2020 election only**, labelled as such): 2021-2023.
    2024 is provisional in MapBiomas Collection 10. Report it as a separate
    estimate on the 2020 cells only. The 2020-only Y3 sensitivity keeps the
    pooled numbering of pairs, so each of its draws uses the 2020 part of the
    same sign vector as every other estimate.
  - `Ypre`: E-4 to E-1 (the placebo window).
  - `dY` = `Y4` − `Ypre` (secondary displacement outcome, decision 0007).
- **Samples.** A cell enters election E if `has_data` is true in all of
  E+1 to E+4. For `Ypre` and `dY`, it must also have `has_data` true in all
  of E-4 to E-1. Dropped cells are counted per election and reason.
- **Design** (as the power run): municipality-by-election fixed effects
  (demean within `cd_ibge` × E); OLS slope(s); randomisation inference with
  2,000 draws, seed 20261106, each flipping every close pair independently
  with probability 1/2; **one sign vector per draw shared by every
  estimate**. Two-sided RI p = (1 + #{|b_r| ≥ |b|}) / (1 + 2,000), as
  `ri_p`. The municipality-clustered SE (`clustered_se`) is reported next to
  every single-slope estimate.
- **Direct effect.** `Y` on `D/2` (decision 0004, `exp2`) in reached cells of
  municipalities with a close pair; the pair terms are checked against
  `cell_exposure` as in the power run. Robustness: `ring2` and `ring5`, each on
  its own reached sample (`d_ring*` not null), pair terms checked against
  `d_ring2` and `d_ring5`.
- **Displacement effect.** `Y` on `G/2` (decision 0005, `g_exp10`) in the
  unrepresented cells of `cell_displacement`; pair terms checked against
  `g_exp10` as in the power run. Robustness: `ring10_20` and `ring20_50`
  (`kernel_g` with those names), pair terms checked against `g_ring10_20` and
  `g_ring20_50`.
- **Displacement placebo** (reported next to the displacement results, no
  verdict): `Ypre` on `G/2` (`g_exp10`), the same cells and design.
- **Secondary displacement outcome** (decision 0007, no kill-criterion role):
  `dY` on `G/2` (`g_exp10`), the same cells and design.
- **Constituency split** (handoff 3, section 4, as in the power run): `Y` on
  `D^indigenous/2`, `D^settlement/2`, `D^both/2`, `D^neither/2`,
  `D^untyped/2` jointly, `exp2`, at 5 km (main) and 2 km (robustness).
  `delta` = β^indigenous − β^settlement. For `delta`, also the one-sided RI p
  in the direction of kill criterion 3: p1 = (1 + #{delta_r ≤ delta}) /
  (1 + 2,000).

## Verdicts (decision 0007), on `Y4`, pooled

Constants from decision 0007, written in the script with a comment citing
it: effect size 8% of baseline four-year clearing at the mean exposure;
power at that size: direct 0.94, displacement 0.797, split difference (5 km,
gap of one effect size, one-sided) 0.45; bar 0.80.

- **Kill criterion 3** (5 km split, `delta`). Test: one-sided at 5%
  (`delta` < 0), two-sided p reported alongside. Because its power (0.45) is
  below 0.80, the verdict line is: "Kill criterion 3 cannot be applied at 80%
  power on this half (power 0.45); the criterion is unchanged", followed by
  `delta`, p1 and the two-sided p. If the power constant were ≥ 0.80, the
  criterion would be "met" when p1 ≥ 0.05 and "not met" otherwise; the code
  implements both branches, and the test checks both.
- **Kill criterion 4** (direct `exp2` and displacement `g_exp10`).
  "Clearly non-zero" is the Holm rule at 5% overall on the two two-sided RI
  p-values: order them; the effect with the smaller p is non-zero if that p is
  below 0.025; only then is the other non-zero if its p is below 0.05.
  - If at least one effect is non-zero under this rule: "Kill criterion 4 is
    not met", naming the non-zero effect(s), whatever the power.
  - Otherwise, both are indistinguishable from zero. If both power constants
    are ≥ 0.80, the criterion is "met". If either is below (the displacement
    effect, 0.797), the line is "Kill criterion 4 cannot be applied at 80%
    power on this half (displacement power 0.797); the criterion is
    unchanged".
  - The 80% bar is applied as written. Nothing is rerun to change the power.

The verdicts use only `Y4`, `exp2`, `g_exp10` and the 5 km split. Everything
else (Y2, Y3, rings, 2 km, placebo, dY) is reported, never used for a verdict.

## What to report

`summary.md`:
1. The two verdict lines, first.
2. Candidates per type (5 km and 2 km), pooled, as in the power run.
3. Per estimate: cells, cells with a non-zero regressor, municipalities,
   pairs, cells dropped; then a table with rows = slopes and windows, and
   columns: slope, two-sided RI p (and p1 for `delta`), RI 2.5% and 97.5%
   quantiles, clustered SE (single slopes), mean of `Y` over the sample, and
   the slope as a percentage of baseline at the mean exposure (100 × slope ×
   mean |x| / mean Y over the cells with a non-zero regressor, as in the
   power run).
4. The displacement table has three blocks side by side: the effect (`Y4`,
   `Y2`), the placebo (`Ypre`) and the change outcome (`dY`), each labelled.
5. The 2020-only `Y3` sensitivity, labelled "sensitivity: 2024 is
   provisional".
6. Caveats: exploration half; power from decision 0007 measured on
   pre-election clearing; the 2 km split and the rings are robustness; `dY`
   and the placebo have no kill-criterion role.

`results.json`: every number above.

## In scope

`explore/0001_effects.py` (calls `exploration_municipalities` and `restrict`
on every table it reads) and `tests/test_explore_effects.py`.

Expected files (two): `explore/0001_effects.py`,
`tests/test_explore_effects.py`.

## Out of scope

The 2024 election; the year E of any election; any year outside E-4..E-1 and
E+1..E+4; covariates; other outcome codes; per-election estimates;
heterogeneity beyond the constituency split; anything in `sealed/` or the
confirmation half; changes to other explore scripts; the idea file and
lessons entry (written by a person when the run is recorded).

## Done when

1. `outcome_years(2008)` is exactly 2004-2007 and 2009-2012 (2008 is not in
   it), and the outcome helper builds `Y4`, `Y2`, `Ypre`, `dY` and the 2020
   `Y3` from the right years on a synthetic frame. A cell missing one post
   year is dropped from everything; a cell missing one pre year is dropped
   only from `Ypre` and `dY`.
2. The ring pair terms (direct `ring2`, `ring5`; displacement `ring10_20`,
   `ring20_50`) add up to the stored columns on a synthetic municipality, and
   the check stops on a mismatch.
3. The one-sided p1 equals (1 + #{delta_r ≤ delta}) / (1 + draws) on a known
   array.
4. Holm: (p_direct, p_disp) = (0.02, 0.04) gives both non-zero, so "not
   met"; (0.03, 0.04) gives neither non-zero; (0.01, 0.30) gives only the
   direct effect non-zero, so "not met"; (0.30, 0.01) gives only
   displacement. With neither non-zero, displacement power 0.797 gives
   "cannot be applied at 80% power on this half", and both powers ≥ 0.80
   give "met".
5. Kill criterion 3: power 0.45 gives "cannot be applied at 80% power on
   this half"; with a power ≥ 0.80, p1 = 0.20 gives "met" and p1 = 0.01 gives
   "not met".
6. With a synthetic `Y` = 0.1 × D̃ plus noise over many pairs, the direct
   slope is near 0.1 with RI p below 0.01.
7. For each outcome, the years read are exactly: `Y4` = t+1 to t+4, `Y2` =
   t+1 to t+2, `Y3` (2020) = 2021 to 2023, `Ypre` = t-4 to t-1; and the
   election year t is never read.
8. All estimates (direct, displacement, split, rings, `Y2`, `dY`, `Y3`) use
   the same 2,000 sign vectors from the same seed, and a pair has the same
   index in every estimate.
9. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
