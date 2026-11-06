# Task: the design's minimum detectable effects, for decision 0007 (explore)

## Goal

Kill criteria 3 and 4 of idea 0001 need "at least 80% power for the effect
size fixed in the pre-analysis plan", and no effect size has been fixed yet.
This task measures how small an effect the design can detect, on the
exploration half, so that decision 0007 can fix the effect size **before**
anyone looks at post-election clearing. It reports the spread of each
estimate under re-flips of the close pairs and turns it into a minimum
detectable effect, as a slope and as a percentage of baseline clearing.

**Outcome data in scope (for referee R2): pre-election years only.** The
script reads `cell_outcomes` for the years E-4 to E-1 of each election E,
exactly the window of the placebo (kill criterion 2, run 42193625417), and no
other year. No post-election year (E or later) is read. The years read are
fixed by the code, not by an argument.

## Idea

`research/ideas/0001-electoral-strongholds.md` (kill criteria 3 and 4);
decisions 0004 (direct exposure), 0005 (displacement exposure) and 0006
(outcome); run 42193625417 (`research/explore-runs/0001/42193625417.md`) and
run 41839642406 (kill criterion 1, stronghold distances). This is an explore
task (label `explore`): it may change only `explore/` and `tests/test_explore*`.

Read first: `explore/0001_placebo.py` (design, pair terms, RI, clustered SE:
**reuse it**, loaded with importlib as it loads the census script; do not
copy its functions), `explore/0001_kill_criterion_1.py` (`candidate_distances`:
stronghold distances from `polling_place_tenure`; reuse it the same way),
`src/terrain/strongholds.py` (`strongholds`, `stronghold_pairs`, `kernel_g`,
`displacement`, `DISPLACEMENT_KERNELS`), `data/contracts/cell_exposure.md`,
`data/contracts/cell_displacement.md`, `data/contracts/cell_outcomes.md`,
`data/contracts/polling_place_tenure.md`.

## Definitions

- **Elections** `E` = 2008, 2012, 2016, 2020 (not 2024: it has no
  post-election years, so it will not be in the main estimates). Everything
  below is pooled over these four elections; per-election numbers are counts
  only.
- **Windows.** `Y4_iE` = Σ over E-4..E-1 of `code_4 / 10,000`;
  `Y2_iE` = Σ over E-2..E-1. **One sample for both windows:** a cell enters
  election E only if `has_data` is true in all four years E-4..E-1
  (`pre_election_outcome` of the placebo gives `Y4`; compute `Y2` from the
  same rows). Dropped cells are counted.
- **Design** (as the placebo): municipality-by-election fixed effects (demean
  within `cd_ibge` × E), OLS slope(s), randomisation inference with 2,000
  draws, seed 20261106; in each draw every close pair is flipped
  independently with probability 1/2. **One sign vector per draw is shared by
  every estimate and both windows** (pair id = row index of the year's
  `close_pairs`, offset across years as `stack` does), so each draw computes
  every estimate once.
- **Estimate 1, direct.** Sample, exposure and pair terms exactly as the
  placebo's `exp2`: reached cells of municipalities with a close pair,
  regressor `D_i / 2` (`d_exp2`), pair terms checked against `cell_exposure`.
- **Estimate 2, displacement.** Sample: exploration-half cells of
  `cell_displacement_<E>` with `Y` defined. Regressor `G_i / 2` (`g_exp10`).
  Pair terms: for each pair of `stronghold_pairs`, `kernel_g("exp10", d_w,
  d_l)` at each cell of its municipality (distances from the cell centre,
  corner + 0.5 km, as `displacement` does), keeping only non-zero terms. The
  pair id is that of the same pair in `close_pairs` (join on `cd_ibge`,
  `sg_ue`, `cd_eleicao`, `w`, `l`). The script stops (`SystemExit`) unless
  Σ_p of the terms equals `g_exp10` for every sample cell (tolerance 1e-9).
- **Estimate 3, constituency split** (handoff section 4). Each close-pair
  candidate gets a type from its stronghold (`strongholds` on the year's
  place votes, distances from `polling_place_tenure` of that year, via
  `candidate_distances`), at band b = 5 km (main) and b = 2 km (robustness),
  with `≤ b + 1e-9` as in kill criterion 1:
  - `indigenous`: `dist_indigenous_km` ≤ b and `dist_settlement_km` > b;
  - `settlement`: `dist_settlement_km` ≤ b and `dist_indigenous_km` > b;
  - `both`: both ≤ b;
  - `neither`: both > b;
  - `untyped`: no stronghold, or a stronghold without both distances
    (needed so the components add up to `D`; it is a regressor, never
    contrasted).

  Split each pair's direct term into its two sides: `e_w,ip` = Σ k a_w / Σ k
  and `e_l,ip` = Σ k a_l / Σ k (same kernel `exp2`, same denominator as
  `pair_terms`, so `t_ip` = `e_w,ip` − `e_l,ip`). Component `D^T_i` = Σ_p
  [1(type(w_p) = T) e_w,ip − 1(type(l_p) = T) e_l,ip]. Flipping pair p
  negates both of its contributions. The script stops unless Σ_T `D^T_i` =
  `D_i` for every sample cell (tolerance 1e-9). Same sample as estimate 1.
  Regress `Y` jointly on `D^indigenous/2`, `D^settlement/2`, `D^both/2`,
  `D^neither/2`, `D^untyped/2` (FE-demeaned; `X̃'X̃` and `X̃'Ỹ` per draw,
  solve the 5 × 5 system). Report `β^indigenous`, `β^settlement` and the
  **difference** `Δ = β^indigenous − β^settlement` (what kill criterion 3
  tests). If a component has no variance after demeaning, report it as n/a
  and drop it from that regression.
- **Spread and minimum detectable effect**, for each reported slope (1, 2,
  `β^indigenous`, `β^settlement`, `Δ`, at 5 and 2 km) and each window, from
  its 2,000 RI draws `b_r`:
  - `sd_ri` = standard deviation of `b_r`;
  - two-sided 5%, 80% power: `mde_sd` = 2.8 × `sd_ri`;
    `mde_q_pos` = q(0.975) − q(0.20) and `mde_q_neg` = q(0.80) − q(0.025)
    (quantiles of `b_r`; the effect that a shifted RI distribution would
    detect 80% of the time, upward and downward);
  - for `Δ` only, **one-sided 5%** in the direction of kill criterion 3
    (`Δ` < 0): `mde1_sd` = 2.487 × `sd_ri` and `mde1_q` = q(0.80) − q(0.05).
- **Effect sizes people can judge.** Under the swap counterfactual a cell's
  regressor moves from −D/2 to +D/2, so a slope `m` means a change of
  `m × |D|` in `Y`. For each estimate, among sample cells with a non-zero
  regressor (`D` for 1, `G` for 2, `D^T` for β^T; for `Δ`, the cells and
  `|D^indigenous|` of the indigenous component), pooled: the median, mean and 90th percentile of the
  absolute exposure `|x|`; the baseline `ybar` = mean of `Y` (same window)
  over those cells; and `100 × mde × |x| / ybar` for `mde_sd` (and `mde1_sd`
  for `Δ`) at each of the three points. Also report `ybar` over the cells
  with `|x|` ≥ its 90th percentile.
- **Context (pre-election, not used for any verdict):** the observed slope of
  each estimate on the pre-election outcome, its two-sided RI p, and the
  municipality-clustered SE of estimates 1 and 2 (`clustered_se` of the
  placebo).

## What to report

First, before any other table: **candidates per type**, per election
(2008-2020) and pooled, at 5 km and 2 km, as winners and as losers and in
total. If `indigenous` or `settlement` at 5 km has fewer than 200 candidates
pooled, the summary's first line says so.

Then, per estimate (1, 2, split at 5 km, split at 2 km): cells, cells with a
non-zero regressor, municipalities, pairs, cells dropped for missing data;
and one table per window with rows = slopes and columns `sd_ri`, `mde_sd`,
`mde_q_pos`, `mde_q_neg` (and `mde1_sd`, `mde1_q` for `Δ`), median / mean /
p90 `|x|`, `ybar`, and the three percentage effects. Then the context table.

`summary.md`: the type counts, the tables, and a caveat paragraph (spread
measured on pre-election clearing; the 2 km split is robustness; the shifted
RI distribution is an approximation to power). `results.json`: every number.
No verdict on kill criteria 3 or 4: this task only measures the design.

## In scope

`explore/0001_power.py` (calls `exploration_municipalities` and `restrict` on
every table it reads, including `polling_place_tenure`, `cell_displacement`
and `cell_outcomes`) and `tests/test_explore_power.py`.

Expected files (two): `explore/0001_power.py`, `tests/test_explore_power.py`.

## Out of scope

Any outcome year E or later; the 2024 election in the estimates; the rings
(`ring2`, `ring5`, `ring10_20`, `ring20_50`); covariates; other outcome codes;
the effect size itself (decision 0007 is written by a person from this
output); `sealed/`; changes to `0001_placebo.py` or `0001_kill_criterion_1.py`.

## Done when

1. On a synthetic municipality (two pairs, three cells, the placebo test's
   layout), Σ_T `D^T_i` = `D_i` for every cell, and flipping one pair negates
   exactly that pair's contributions to every component.
2. Candidate types: synthetic distances on each side of 2 and 5 km give each
   of the five types (a distance of b + 1e-12 counts as within b).
3. The displacement pair terms add up to `strongholds.displacement`'s
   `G_exp10` on a synthetic municipality, and the check stops on a mismatch.
4. With a synthetic `Y` = 0.1 × D̃ plus noise over many pairs, the joint
   regression recovers a slope near 0.1 on the matching component and near 0
   on the others; `sd_ri` and `mde_sd` = 2.8 × `sd_ri` are computed from the
   draws; `mde_q_pos` equals q(0.975) − q(0.20) on a known array.
5. The read years: a test calls the year-list helper for E = 2008 and gets
   exactly 2004-2007, and `Y2` uses only 2006-2007.
6. The percentage effect equals `100 × mde × |x| / ybar` on a small frame.
7. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
