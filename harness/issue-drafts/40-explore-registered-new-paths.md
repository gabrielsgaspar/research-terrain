# Task: check the registered analysis's new paths on real data, without estimates (explore, idea 0001)

## Goal

Run 42476480500 (issue #241) showed that idea 0001's registered analysis
(`src/terrain/registered/r0001/analysis.py`) reproduces every number of the
explore runs it was frozen from. It did not check the parts that are new in
the plan, because no earlier run has them: the incumbency-adjusted estimates
(`direct_adj`, `ring2_adj`, `ring5_adj`, `direct_pre_adj`, built from Z), the
direct placebo (`direct_pre`), the alignment split (`align`) and the balance
table (`balance`).

**This task checks those paths on the exploration half at the 0.50% window,
once, through `explore-run`, and reports only structural facts: counts of
pairs and cells, and pass or fail for each check. It prints no slope, RI p,
p1, quantile, clustered SE, mean or percentage of any estimate.** It is a
check of the code on real data before registration, not a result.

Drafted by Claude Code (2026-11-08) for Gabriel, who decides whether to file
it (`gh issue create` with label `explore`, then `agent-plan`).

**Outcome data in scope (for referee R2):** `cell_outcomes` of the
exploration half, the years each election reads in run 42298466207 (E-4 ..
E-1 and E+1 .. E+4, never E; for 2024, E-4 .. E-1 only). Outcomes are read
only because the analysis builds its samples from them; no outcome value or
estimate is reported.

## In scope

- `explore/0001_registered_paths_check.py` (new)
- `tests/test_explore_registered_paths_check.py` (new)

Nothing else. In particular `src/terrain/registered/` (owned and frozen),
`explore/0001_registered_check.py` and `tests/world_0001.py` (owned) are not
changed. They may be imported. If a check below cannot be made without
changing them, the planner says so instead of planning around it.

## What runs

`uv run python explore/0001_registered_paths_check.py --out-dir DIR`, through
`gh workflow run explore-run.yml --ref main -f script=0001_registered_paths_check`.
It calls `exploration_municipalities` and `restrict` like every explore
script. It reads through the analysis's own `Reader`, as `run_exploration`
does, at window 0.005, with the real treatment, on the exploration half. It
may call the module's functions (`treatment_year`, `incumbent_sign`,
`z_terms`, `align_components`, `outcome_year`, `balance_differences`) one
election at a time, where `run` does not return the parts a check needs.

## The checks (each "pass" or "fail", with counts where named)

1. **Pairs with exactly one incumbent (Z).** Per election (2008-2020) and
   pooled, the number of close pairs with `s = +1` (only the winner held the
   seat), `s = -1` (only the loser did) and `s = 0` (both, neither or
   unknown). These are treatment-side counts. Pass if `+1` and `-1` sum to
   more than zero in every election.
2. **The same pairs and cells with and without Z.** For `direct`, `ring2`,
   `ring5` and `direct_pre`, the adjusted part uses the same sample cells
   (same rows, same order) as the unadjusted one. Every Z pair term is `s`
   times that pair's D term, and the Z pairs are a subset of the D pairs.
   Report the number of cells with a non-zero Z per election.
3. **Z is fixed under re-flips.** For one re-flip draw (seed 20261106,
   draw 1), swapping every flipped pair's sides leaves every Z term
   unchanged, while the D terms of flipped pairs change sign. Pass or fail
   only.
4. **The alignment split adds up.** Per election, the counts of `aligned`,
   `unaligned`, `mixed` and `left_out` pairs sum to the pairs. Per
   (cell, pair), the alignment components' terms sum to the D term exactly.
   Report the counts per kind, which run 42384829937 already gives at 0.25%.
5. **The direct placebo uses the direct exposure.** `direct_pre`'s terms are
   `direct`'s terms, and its sample cells are the direct cells that have
   every `Ypre` year. Pass or fail, plus the number of cells per election.
6. **No NaN or infinite values.** Every number the analysis returns for
   `direct_adj`, `ring2_adj`, `ring5_adj`, `direct_pre`, `direct_pre_adj`,
   `align` and `balance` is finite, or is an explicit null that the analysis
   documents (a non-estimable slot). Report the dotted paths of any
   non-finite values, never the values.
7. **Balance is computed on every covariate.** Every covariate of
   `fz.BALANCE` has a winner-minus-loser difference for every election, and
   the omnibus p exists. Pass or fail only. The table is not printed.

## What is reported

`summary.md`: the first line is "Structural checks: pass" or "Structural
checks: fail (N of 7)". Then one row per check, with pass or fail and the
counts named above, and then the caveats. `results.json` holds the same,
under `checks.<n>.pass` and `checks.<n>.counts`.

**A test checks that `results.json` holds only booleans, whole numbers,
check names and paths, and no other floating-point number.**

## Expected

- All seven checks pass. A fail is a stop: the record PR is not merged, and
  Gabriel decides. No change is made to the frozen code to force a pass.

## Never

- Any run at 0.25%. The analysis refuses it before registration, and this
  script uses 0.005 only.
- Any estimate, p-value or quantile in `summary.md`, `results.json`, logs or
  exceptions.
- Any read of `sealed/` or `confirm/`.

## Done when

- On the synthetic world (`tests/world_0001.py`, imported), the script's
  checks all pass. A planted fault fails the right check, for each of:
  - a Z term with the wrong sign;
  - an alignment component missing one pair;
  - a NaN in a `direct_adj` slot;
  - a `direct_pre` sample with one cell more.
- The test that `results.json` holds no floating-point number passes.
- The test that the script calls `exploration_municipalities` and `restrict`
  passes (`tests/test_explore.py`).
- `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
  pass.
