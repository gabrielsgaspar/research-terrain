# Task: build `cell_exposure`, each cell's exposure to close council races (decision 0004)

## Goal

For every Legal Amazon 1 km cell and election year 2008-2024, the exposure
fixed in `research/decisions/0004-exposure.md`: over the close pairs of the
cell's municipality, winner minus loser of the kernel-weighted mean vote
share at the municipality's polling places within 10 km. Main kernel
exp(-d/2 km); the 2 and 5 km rings as robustness. Both halves of the sample
(treatment-side data, decision 0003).

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read first: decision 0004,
`explore/0001_feasibility_census.py`, `explore/0001_exposure_options.py`
(run 41913964880 computed exactly this on the exploration half), and the
contracts of `grid_cells`, `polling_places`, `section_votes` and
`tse_results`.

## Prerequisites

Merged manifests `data/manifests/build/grid_cells.json`, `polling_places.json`,
`section_votes.json`, `tse_results.json`.

## The rules

1. **Same definitions as the exploration, from one place.** Builds must not
   import `explore/` scripts, so put the functions in a library module,
   `src/terrain/strongholds.py`, copied without changes in behaviour from
   the two scripts: from the census `_council_round1`, `main_election`,
   `elected_status`, `candidacy_votes`, `within_list_pairs`, `valid_votes`,
   `margins` and `place_candidate_votes` (with their constants); from the
   exposure script `close_pairs`, `place_totals`, `place_shares`,
   `locate_places`, `cell_place_distances`, `kernel` and `exposure`. Do not
   change the explore scripts (they are the record of what was run). A test
   proves the copies match: on the same synthetic tables, each library
   function returns a frame equal to the explore script's function
   (`polars.testing.assert_frame_equal`), loading the scripts with
   `importlib` as `explore/0001_kill_criterion_1.py` does.
2. **Per year:** `main_election` from `candidate_votes_<y>`; close pairs at
   0.5% from `candidacy_votes`, `within_list_pairs`, `valid_votes(turnout_<y>)`
   and `margins`; place votes from every `section_votes_<y>_<UF>` file with
   `place_candidate_votes`; places from `polling_places_<y>`; cells from
   `grid_cells` (`cd_ibge`, `x_km`, `y_km`, `nome_1KM`). No exploration-half
   restriction: every Legal Amazon municipality.
3. **Exposure:** `exposure(..., measure="share")` for each kernel `exp2`,
   `ring2`, `ring5`. A cell is in the year's output when the `exp2` kernel
   reaches it (Σ K > 0, so within 10 km of a place with votes in its
   municipality), whether or not its municipality has a close pair. Cells
   not in the output are not reached.

## Output

`<derived>/<hash>/cell_exposure_<y>.parquet` for y in 2008, 2012, 2016, 2020,
2024; `<hash>` is `content_hash` of the input SHA-256s (sorted), the years and
the source of `terrain/strongholds.py`, `terrain/grid.py` and
`terrain/builds/cell_exposure.py`. Sorted by `cd_ibge`, `y_km`, `x_km`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `ano` | int | election year |
| `n_pairs` | int | close pairs (margin ≤ 0.5%) in the municipality |
| `sum_k_exp2`, `sum_k_ring2`, `sum_k_ring5` | float | Σ_p K(d) over the municipality's places with votes |
| `d_exp2`, `d_ring2`, `d_ring5` | float | `D_i` (share measure); 0 when `n_pairs` = 0; null when that kernel does not reach the cell |

The recentred exposure to the elected is `d_* / 2` (decision 0004); the
build stores `D_i` itself.

## Checks (each raises `BuildError` before anything is written)

- (`nome_1KM`, `ano`) is unique; every `nome_1KM` is in `grid_cells` with the
  same `cd_ibge`.
- |`d_*`| ≤ `n_pairs` + 1e-9 (each pair's term is a difference of two shares
  in [0, 1]).
- `d_ring2` is not null only where `d_ring5` is not null, and `d_ring5` only
  where `d_exp2` is not null (smaller rings reach a subset).
- Every year has at least one close pair and at least one exposed cell.

Manifest notes per year: municipalities with a close pair, close pairs, rows,
and cells with `d_*` ≠ 0 per kernel.

## In scope

- `src/terrain/strongholds.py`, `src/terrain/builds/cell_exposure.py`,
  `pipeline/build/cell_exposure.py` (thin, reads the four manifests),
  `data/contracts/cell_exposure.md`, `tests/test_strongholds.py`,
  `tests/test_build_cell_exposure.py`.

Expected files (six), exactly those.

## Out of scope

`explore/`, `data/catalog.yaml` (entry written), `data/manifests/`,
`data/fixtures/`, workflows, `pyproject.toml`, `uv.lock`.

## Done when

1. Every copied function equals its explore original on synthetic tables
   (`tests/test_strongholds.py`).
2. With a `MemoryStore` holding synthetic Parquet inputs for two
   municipalities (one with a close pair, one without) and `years=(2024,)`:
   the output has the reached cells of both, `n_pairs` 1 and 0, `d_*` = 0 in
   the second, and in the first `d_exp2` equals the hand-computed value for
   a cell 1 km from one place and 3 km from the other.
3. Swapping the pair's winner and loser in the inputs negates every `d_*`.
4. A cell 3 km from every place has `d_ring2` null and `d_ring5`, `d_exp2`
   not null; a cell 12 km away is absent.
5. Each check fails on its own broken input, raising `BuildError` with the
   store unchanged; a second run is `unchanged`; changing the source of
   `terrain/strongholds.py` changes the output path; an input whose
   SHA-256 differs from its manifest raises.
6. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
