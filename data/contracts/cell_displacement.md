# cell_displacement

Each Legal Amazon 1 km cell that nobody votes on, and its exposure to the close
city-council races of its municipality, for the election years 2008, 2012, 2016, 2020
and 2024 (`research/decisions/0005-displacement-exposure.md`). Both halves of the sample,
as treatment-side data (`research/decisions/0003-confirmation-rows.md`). Built by
`src/terrain/builds/cell_displacement.py`; the definitions are in
`src/terrain/strongholds.py` and equal those of `explore/0001_displacement_options.py`
for the three kernels below.
Written to `data/derived/cell_displacement/<hash>/cell_displacement_<y>.parquet`, one file
per year, where `<hash>` is `content_hash` of the sorted input SHA-256s, the years and the
source of `terrain/strongholds.py`, `terrain/grid.py` and
`terrain/builds/cell_displacement.py`.

## Sources

- `grid_cells`: `nome_1KM`, `cd_ibge`, `x_km`, `y_km`, `pop_2022`.
- `cell_exposure`: `cell_exposure_<y>`, the cells the 10 km kernel reaches.
- `polling_places`: `polling_places_<y>`, the places with coordinates.
- `section_votes`: every `section_votes_<y>_<UF>`, reduced to candidate and legend votes
  per place (`place_candidate_votes`).
- `tse_results`: `candidate_votes_<y>` and `turnout_<y>`, for the close pairs.

## Columns

One row per cell and year. Sorted by `cd_ibge`, `y_km`, `x_km`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `ano` | int | election year |
| `n_pairs` | int | close pairs (margin at most 0.5%) in the municipality, same-place pairs included |
| `n_pairs_located` | int | of those, pairs whose two strongholds have coordinates and differ |
| `g_exp10`, `g_ring10_20`, `g_ring20_50` | float | `G_i` for that kernel |

The recentred exposure to the elected candidate is `g_* / 2` (decision 0005). The file
stores `G_i` itself. Swapping the winner and loser of every pair negates every `g_*`.

## The rules

1. Close pairs. `main_election`, then `candidacy_votes`, `within_list_pairs`,
   `valid_votes` and `margins`; a pair is close when it is not inverted and its margin
   is at most 0.5% (`close_pairs`). `w` is the elected candidate, `l` the other.
2. Strongholds. `strongholds` on the place votes (`place_candidate_votes` over every
   state file of the year); `stronghold_pairs` gives each pair the coordinates of its two
   strongholds (`locate_places`).
3. Pairs with one stronghold place stay in `n_pairs` and add 0 to `G`. Pairs where a
   candidate has no stronghold, or a stronghold without coordinates, are dropped from
   `G`. Both counts are in the notes.
4. Cells. `pop_2022` = 0, not in the year's `cell_exposure`, in a municipality with a
   close pair (`unrepresented`). Cells of municipalities without a close pair are not in
   the file. No exploration-half restriction.
5. `G_i` (`displacement`). Distances run from the cell centre (corner + 0.5 km) to the
   two strongholds of each located pair of the cell's municipality. `g_exp10` is the sum
   of exp(-d / 10 km) at the winner's stronghold minus that at the loser's, up to 50 km.
   `g_ring10_20` and `g_ring20_50` use 1 for 10 < d <= 20 km and 20 < d <= 50 km.

## Checks

The build raises `BuildError` and uploads nothing when:

- (`nome_1KM`, `ano`) is not unique; a cell is not in `grid_cells` with the same `cd_ibge`
  and `pop_2022` = 0; or a cell is in that year's `cell_exposure`;
- `|g_*|` exceeds `n_pairs_located` + 1e-9, or a ring is not a whole number;
- `n_pairs_located` is above `n_pairs`, or `n_pairs` is below 1;
- a year has no cell with `g_exp10` other than 0;
- an input's SHA-256 differs from its manifest.

## Notes in the manifest

Per year, for the Legal Amazon only: municipalities with a close pair, close pairs, pairs
located, dropped same place, dropped no coordinates, rows, and the cells with `g_*` not 0
for each kernel. Counts only; no tenure or outcome.
