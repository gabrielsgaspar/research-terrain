# Task: compare displacement-exposure formulas for decision 0005 (explore)

## Goal

Idea 0001 predicts that clearing is pushed onto land with no voters near a
newly represented stronghold ("Displacement" in the design). Decision 0004
measures exposure where people vote (within 10 km of a polling place). This
task computes candidate measures of the **second** exposure, for land nobody
votes on, on the exploration half, and reports how many cells each reaches,
where they are (tenure), and how they overlap with decision 0004's exposure.
No outcome data; no effects.

## Idea

`research/ideas/0001-electoral-strongholds.md`; decision 0004. This is an
explore task (label `explore`): it may change only `explore/` and
`tests/test_explore*`, and reads no outcome data. Read
`research/decisions/0004-exposure.md`, `src/terrain/strongholds.py`,
`data/contracts/grid_cells.md` and `data/contracts/cell_exposure.md` first.

## Definitions

- **Close pairs and strongholds:** `terrain.strongholds` (`close_pairs` at
  0.5%, not inverted; `strongholds`, the location-quotient place with at
  least 50 votes). For each pair, `w` and `l` are the elected and the other
  candidate, and `p_w`, `p_l` their stronghold polling places, located with
  `strongholds.locate_places` (Albers km). Pairs whose two strongholds are
  the same place, or either has no coordinates, are dropped and counted.
- **Unrepresented cell:** a cell of `grid_cells` with `pop_2022` = 0 that
  `cell_exposure` of the same year does not reach (not in the year's file:
  more than 10 km from every polling place of its municipality). Only cells
  of municipalities with a close pair; distances only to strongholds of the
  cell's own municipality.
- **Variants** of `G_i` = Σ_pairs (K(d(i, p_w)) − K(d(i, p_l))):
  - `ring10_20`: K = 1 for 10 < d ≤ 20 km; `ring20_50`: 1 for 20 < d ≤ 50;
  - `exp10`: K = exp(-d / 10) for d ≤ 50 km;
  - `nearest`: K = 1 if the cell is nearer `p_w` than `p_l` and within 50 km
    of it, −1 the reverse (so G counts pairs whose winner is the nearer
    stronghold, minus the reverse).
  Swapping a pair's winner and loser negates its term, so the expectation
  over swaps is 0 and the recentred exposure is G / 2, as in decision 0004.

## What to report

Per year 2008-2024 and per variant:

1. Unrepresented cells in exploration-half municipalities with a close pair;
   cells with `G` ≠ 0; pairs used and dropped (same place, no coordinates).
2. Quantiles of `G` over cells with `G` ≠ 0 (1%, 10%, 50%, 90%, 99%).
3. Cells with `G` ≠ 0 by tenure: `share_undesignated_<y>`,
   `share_indigenous_<y>`, `share_settlement_<y>` above 0 (counts and
   shares).
4. Agreement: Pearson correlation of `G` between `exp10` and each other
   variant, over cells non-zero in both.
5. For context, from `grid_cells` alone: unrepresented cells as a share of
   all cells of those municipalities.

`summary.md`: one table per year (variants as rows: cells non-zero, share in
undesignated forest, median |G|) and one line on the recentring identity.

## In scope

`explore/0001_displacement_options.py` (calls `exploration_municipalities`
and `restrict` on every table it reads) and
`tests/test_explore_displacement.py`.

## Done when

1. On a synthetic municipality with one pair, a cell 15 km from `p_w` and
   30 km from `p_l` gets `ring10_20` = 1, `ring20_50` = −1, `exp10` =
   exp(-1.5) − exp(-3), `nearest` = 1.
2. A populated cell, and a cell that `cell_exposure` reaches, are never in
   the output; a cell 60 km from both strongholds has every variant 0.
3. Swapping every pair's winner and loser negates every `G`.
4. A pair whose strongholds are the same place is dropped and counted.
5. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
