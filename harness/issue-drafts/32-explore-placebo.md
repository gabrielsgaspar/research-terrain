# Task: the pre-election placebo of kill criterion 2 (explore)

## Goal

Kill criterion 2 of idea 0001: "stronghold exposure in the four years before
the election predicts clearing (randomisation-inference p below 0.05) on the
exploration half". This task computes that test, on the exploration half
only, with the exposure of decision 0004 and the outcome of decision 0006,
and reports it. The decisive number is the pooled `exp2` p-value; everything
else is reported for context.

## Idea

`research/ideas/0001-electoral-strongholds.md`; decisions 0004 and 0006. This
is an explore task (label `explore`): it may change only `explore/` and
`tests/test_explore*`. Read `research/decisions/0004-exposure.md`,
`src/terrain/strongholds.py` (`exposure`), `data/contracts/cell_exposure.md`,
`data/contracts/cell_outcomes.md` and `explore/0001_displacement_options.py`
(how a script finds the latest files, `census._paths`, and restricts every
table) first.

## Definitions

- **Elections** `E` = 2008, 2012, 2016, 2020, 2024. **Pre-election years**:
  `E-4` to `E-1` (2004-2007 for 2008, ..., 2020-2023 for 2024).
- **Outcome** `Y_iE`: the sum over the four pre-election years of `code_4 /
  10,000` from `cell_outcomes` (loss of primary vegetation, as a share of the
  cell). A cell enters election `E` only if `has_data` is true in all four
  years.
- **Exposure**: per cell and close pair `p`, the pair's term of `D_i` under
  `exp2` and the share measure: `t_ip` = Σ_places k (a_w - a_l) / Σ_places k,
  computed exactly as `strongholds.exposure` computes `D_i` but grouped by cell
  and pair, so that Σ_p t_ip = `D_i`. The script checks that Σ_p t_ip equals
  `d_exp2` of `cell_exposure` for every cell (tolerance 1e-9) and stops if it
  does not. The same for `ring2` and `ring5` against `d_ring2`, `d_ring5`.
- **Sample** per `E`: exploration-half cells in `cell_exposure_<E>` (reached)
  whose municipality has at least one close pair (`n_pairs` > 0), with `Y_iE`
  defined.
- **Estimate**: β, the OLS coefficient of `Y_iE` on the recentred exposure
  `D_i / 2` with municipality-by-election fixed effects (demean `Y` and `D`
  within municipality and election, then β = Σ D̃ Ỹ / Σ D̃²). Pooled over the
  five elections, and per election.
- **Randomisation inference**: 2,000 draws; in each, every close pair is
  flipped independently with probability 1/2 (its `t_ip` multiplied by -1),
  `D_i` and β are recomputed with the same sample and demeaning. Seed 20261106.
  p = (1 + #{|β_r| ≥ |β|}) / (1 + 2,000), two-sided. Demeaning is linear, so
  demeaned per-pair terms may be computed once and combined per draw.
- **Check**: the municipality-clustered standard error of β (pooled `exp2`),
  reported next to the RI p-value (decision 0004).

## What to report

Per election and pooled, for `exp2` (decisive), `ring2` and `ring5`:

1. Cells, municipalities and close pairs in the sample; cells with `D_i` ≠ 0;
   cells dropped for missing data.
2. β, its RI p-value, the 2.5% and 97.5% quantiles of the RI draws of β, and
   (pooled `exp2` only) the clustered standard error.
3. The mean of `Y_iE` in the sample, so β can be read as a share of it.

`summary.md`: one table (rows: pooled and each election; columns: cells,
pairs, β, RI p, for `exp2`), the same for the rings below it, and one line
stating whether kill criterion 2 is met (pooled `exp2` p < 0.05).

## In scope

`explore/0001_placebo.py` (calls `exploration_municipalities` and `restrict`
on every table it reads; reuses `terrain.strongholds` and the census helpers
as `0001_displacement_options.py` does) and `tests/test_explore_placebo.py`.

Expected files (two): `explore/0001_placebo.py`,
`tests/test_explore_placebo.py`.

## Out of scope

The displacement placebo (`cell_displacement`), the post-election effect,
any covariate, any other outcome code, `sealed/`.

## Done when

1. On a synthetic municipality with two pairs and three cells, Σ_p t_ip
   equals `strongholds.exposure`'s `D_i` for every kernel.
2. Flipping every pair negates `D_i` and β; with `Y` identical within each
   municipality and election, β is 0 (fixed effects absorb it).
3. With a synthetic `Y` = 0.1 × D̃ plus small noise over many pairs, the RI
   p-value is below 0.01; with `Y` independent of `D`, it is above 0.05 for
   a fixed seed.
4. A cell without data in one of the four years is dropped and counted.
5. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
