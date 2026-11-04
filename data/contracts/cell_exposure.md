# cell_exposure

Each Legal Amazon 1 km cell's exposure to the close city-council races of its
municipality, for the election years 2008, 2012, 2016, 2020 and 2024: winner minus
loser of the kernel-weighted mean vote share at the municipality's polling places
within 10 km (`research/decisions/0004-exposure.md`). Both halves of the sample, as
treatment-side data (`research/decisions/0003-confirmation-rows.md`). Built by
`src/terrain/builds/cell_exposure.py`; the definitions are in `src/terrain/strongholds.py`.
Written to `data/derived/cell_exposure/<hash>/cell_exposure_<y>.parquet`, one file per
year, where `<hash>` is `content_hash` of the sorted input SHA-256s, the years and the
source of `terrain/strongholds.py`, `terrain/grid.py` and `terrain/builds/cell_exposure.py`.

## Sources

- `grid_cells`: `nome_1KM`, `cd_ibge`, `x_km`, `y_km`.
- `polling_places`: `polling_places_<y>`, the places with coordinates.
- `section_votes`: every `section_votes_<y>_<UF>`, reduced to candidate and legend votes
  per place (`place_candidate_votes`).
- `tse_results`: `candidate_votes_<y>` and `turnout_<y>`, for the close pairs.

## Columns

One row per cell and year. Sorted by `cd_ibge`, `y_km`, `x_km`. Decision 0004 speaks of
one row per cell, year and kernel; this file is wide instead, with a column per kernel.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `ano` | int | election year |
| `n_pairs` | int | close pairs (margin at most 0.5%) in the municipality |
| `sum_k_exp2`, `sum_k_ring2`, `sum_k_ring5` | float | Σ_p K(d) over the municipality's places with votes; 0 when the kernel does not reach the cell |
| `d_exp2`, `d_ring2`, `d_ring5` | float | `D_i` (share measure); 0 when `n_pairs` is 0; null when that kernel does not reach the cell |

The recentred exposure to the elected candidate is `d_* / 2` (decision 0004). The file
stores `D_i` itself. Swapping the winner and loser of every pair negates every `d_*`.

## The rules

1. Close pairs. `main_election`, then `candidacy_votes`, `within_list_pairs`,
   `valid_votes` and `margins`; a pair is close when it is not inverted and its margin
   is at most 0.5% (`close_pairs`). `w` is the elected candidate, `l` the other.
2. Places. Votes come from `place_candidate_votes` over every state file of the year.
   A place counts when its candidate plus legend votes are above 0. Places come from
   `polling_places_<y>` and need coordinates (`locate_places`).
3. Distances. From the cell centre (lower-left corner + 0.5 km) to places of the same
   municipality within 10 km (`cell_place_distances`).
4. Kernels. `exp2`: exp(-d / 2 km) up to 10 km. `ring2`, `ring5`: 1 up to 2 and 5 km.
5. `D_i` (`exposure`, share measure). The sum over the municipality's close pairs of the
   kernel-weighted mean place share of the winner minus that of the loser (a candidate
   without votes at a reached place counts 0).
6. Reach. A cell is in a year's file when `exp2` reaches it: the kernel weights of the
   municipality's places with votes add up to more than 0, whether or not the
   municipality has a close pair. Cells that are not in the file are not reached. The
   rings reach a subset, so `d_ring2` and `d_ring5` are null where they do not reach.

## Checks

The build raises `BuildError` and uploads nothing when:

- (`nome_1KM`, `ano`) is not unique, or a cell is not in `grid_cells` with the same `cd_ibge`;
- some `|d_*|` exceeds `n_pairs` + 1e-9;
- `d_ring2` is set where `d_ring5` is null, or `d_ring5` where `d_exp2` is null;
- a year has no close pair, or no cell with `d_exp2` other than 0;
- an input's SHA-256 differs from its manifest.

## Notes in the manifest

Per year: municipalities with a close pair, close pairs, rows, and the cells with `d_*`
not 0 for each kernel.
