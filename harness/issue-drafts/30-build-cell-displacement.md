# Task: build `cell_displacement`, unrepresented cells' exposure to close council races (decision 0005)

## Goal

For every Legal Amazon 1 km cell that nobody votes on and election year
2008-2024, the displacement exposure fixed in
`research/decisions/0005-displacement-exposure.md`: over the close pairs of
the cell's municipality, K(distance to the winner's stronghold) minus
K(distance to the loser's). Main kernel exp(-d/10 km) to 50 km; the 10-20 and
20-50 km rings as robustness. Both halves of the sample (treatment-side data,
decision 0003).

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read first: decision 0005,
`explore/0001_displacement_options.py` (run 41949908031 computed exactly this
on the exploration half), `src/terrain/strongholds.py`,
`src/terrain/builds/cell_exposure.py` (the pattern to follow) and the
contracts of `grid_cells`, `cell_exposure`, `polling_places`, `section_votes`
and `tse_results`.

## Prerequisites

Merged manifests `data/manifests/build/grid_cells.json`, `cell_exposure.json`,
`polling_places.json`, `section_votes.json`, `tse_results.json`.

## The rules

1. **Same definitions as the exploration, from one place.** Copy
   `stronghold_pairs`, `unrepresented`, `kernel_g` and `displacement` (with
   `OUTER_KM` and `TOLERANCE`) from `explore/0001_displacement_options.py`
   into `src/terrain/strongholds.py` without changes in behaviour, except
   that `displacement` and `kernel_g` cover only the three kernels of
   decision 0005 (`exp10`, `ring10_20`, `ring20_50`; not `nearest`). Do not
   change the explore script. A test proves the copies match the explore
   originals on the same synthetic tables (`polars.testing.assert_frame_equal`,
   loading the script with `importlib` as `tests/test_strongholds.py` does).
2. **Per year:** close pairs at 0.5% (`main_election`, `candidacy_votes`,
   `within_list_pairs`, `valid_votes`, `margins`, `close_pairs`); place votes
   from every `section_votes_<y>_<UF>` with `place_candidate_votes`;
   `strongholds` on them; `stronghold_pairs` with `locate_places(polling_places_<y>)`;
   cells from `grid_cells` (`nome_1KM`, `cd_ibge`, `x_km`, `y_km`, `pop_2022`);
   reached cells from `cell_exposure_<y>` (`cd_ibge`, `x_km`, `y_km`). No
   exploration-half restriction: every Legal Amazon municipality.
3. **Unrepresented cells:** `unrepresented(cells, cell_exposure_<y>,
   municipalities with a close pair)`: `pop_2022` = 0 and not in that year's
   `cell_exposure`. Cells of municipalities without a close pair are not in
   the output.
4. **Pairs with one stronghold place** (decision 0005) stay in `n_pairs` and
   add 0 to `G`; pairs with a stronghold without coordinates are dropped from
   `G` and counted in the notes.

## Output

`data/derived/cell_displacement/<hash>/cell_displacement_<y>.parquet` for y in
2008, 2012, 2016, 2020, 2024; `<hash>` is `content_hash` of the input SHA-256s
(sorted), the years and the source of `terrain/strongholds.py`,
`terrain/grid.py` and `terrain/builds/cell_displacement.py`. Sorted by
`cd_ibge`, `y_km`, `x_km`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `ano` | int | election year |
| `n_pairs` | int | close pairs (margin ≤ 0.5%) in the municipality, same-place pairs included |
| `n_pairs_located` | int | of those, pairs whose two strongholds have coordinates and differ |
| `g_exp10`, `g_ring10_20`, `g_ring20_50` | float | `G_i` for that kernel |

The recentred exposure to the elected is `g_* / 2` (decision 0005); the build
stores `G_i` itself.

## Checks (each raises `BuildError` before anything is written)

- (`nome_1KM`, `ano`) is unique; every `nome_1KM` is in `grid_cells` with the
  same `cd_ibge` and `pop_2022` = 0; no (`cd_ibge`, `x_km`, `y_km`) is in that
  year's `cell_exposure`.
- |`g_exp10`| ≤ `n_pairs_located` + 1e-9; |`g_ring*`| ≤ `n_pairs_located`;
  rings are whole numbers.
- `n_pairs_located` ≤ `n_pairs`, and `n_pairs` ≥ 1 in every row.
- Every year has at least one row with `g_exp10` ≠ 0.

Manifest notes per year: municipalities with a close pair, close pairs, pairs
located, dropped same place, dropped no coordinates, rows, and cells with
`g_*` ≠ 0 per kernel (counts only; no tenure or outcome).

## In scope

- `src/terrain/strongholds.py`, `src/terrain/builds/cell_displacement.py`,
  `pipeline/build/cell_displacement.py` (thin, reads the five manifests),
  `data/contracts/cell_displacement.md`, `tests/test_strongholds.py`,
  `tests/test_build_cell_displacement.py`.

Expected files (six), exactly those.

## Out of scope

`explore/`, `data/catalog.yaml` (entry written), `data/manifests/`,
`data/fixtures/`, workflows, `pyproject.toml`, `uv.lock`.

## Done when

1. Every copied function equals its explore original on synthetic tables
   (`tests/test_strongholds.py`).
2. With a `MemoryStore` holding synthetic Parquet inputs for two
   municipalities (one with a close pair, one without) and `years=(2024,)`:
   only the first municipality's empty, unreached cells are in the output; a
   cell 15 km from `p_w` and 30 km from `p_l` has `g_ring10_20` = 1,
   `g_ring20_50` = −1, `g_exp10` = exp(-1.5) − exp(-3).
3. A populated cell and a cell in `cell_exposure` are absent; a cell 60 km
   from both strongholds has every `g_*` 0; swapping the pair's winner and
   loser in the inputs negates every `g_*`.
4. A pair whose strongholds are the same place counts in `n_pairs`, not in
   `n_pairs_located`, and adds 0.
5. Each check fails on its own broken input, raising `BuildError` with the
   store unchanged; a second run is `unchanged`; changing the source of
   `terrain/strongholds.py` changes the output path; an input whose SHA-256
   differs from its manifest raises.
6. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
