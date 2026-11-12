# mining_panel

MapBiomas mining area per Brazilian municipality and year, 1985-2025, and each
municipality's 2004 native-vegetation share (a baseline control). Written split by half
(`research/decisions/0003-confirmation-rows.md`, `research/decisions/0011-national-scope.md`):
exploration-half rows are derived data, all other rows go only to a sealed folder that no
exploration account can read. Built by `src/terrain/builds/mining_panel.py`. Campaign 0007,
step s12; idea `research/ideas/0007-gold-and-the-ballot.md`.

Paths come from the catalog entry `mining_panel`:

- `data/derived/mining_panel/<hash>/mining_panel_<year>.parquet`: exploration half.
- `sealed/outcomes/mining_panel/<hash>/mining_panel_<year>.parquet`: every other row.

One file per year 1985-2025. `<hash>` is the same for both: `content_hash` of the sorted input
SHA-256s, the SHA-256 of both exploration lists, and the source of this build,
`terrain/grid.py`, `terrain/explore.py` and the builds `place_outcomes`, `cell_outcomes`,
`cell_enforcement` and `polling_place_tenure` (their helpers pick, check and read the inputs).
If a sealed object already exists, the build stops after the sealed files uploaded so far
(create-only); a rerun needs a new hash.

## Sources

- `mapbiomas_mining`: `mining_shares_<year>.tif`, 1985-2025. Shape `(rows, columns, 4)`,
  `uint16`, bands `garimpo_gold`, `garimpo_other`, `industrial_gold`, `industrial_other`,
  each the cell's share x 10,000, on the catalog's `grid_km`.
- `mapbiomas_coverage_national`: `coverage_shares_2004.tif`, band `native` only, on the same grid.
- `ibge_boundaries_2024`: `BR_Municipios_2024.zip`. The codes 4300001 and 4300002 (the
  lagoons of Rio Grande do Sul) are dropped.
- `data/derived/split/explore_municipalities.csv` and
  `explore_municipalities_non_amazon.csv`: the exploration municipalities.

## Columns

One row per municipality (5,571) and year, sorted by `cd_ibge`.

| Column | Type | Meaning |
| --- | --- | --- |
| `cd_ibge` | text | 7-digit IBGE code |
| `year` | int | calendar year |
| `n_cells` | int | 1 km cells assigned to the municipality (see the cell rule) |
| `garimpo_gold_ha`, `garimpo_other_ha`, `industrial_gold_ha`, `industrial_other_ha` | float | hectares: the sum over the cells of share / 10,000 x 100 ha |
| `garimpo_ha` | float | `garimpo_gold_ha + garimpo_other_ha` |
| `garimpo_share` | float | `garimpo_ha / (n_cells x 100)`, 0 to 1 |
| `native_share_2004` | float | mean of the 2004 `native` share / 10,000 over the cells, 0 to 1; the same in every year |

## The rules

1. Cell rule: a cell belongs to the municipality whose polygon (projected to Albers km with
   `terrain.grid`) contains the cell centre (x + 0.5, y + 0.5). A cell centre in no polygon
   is dropped. A centre on a shared edge goes to the first code in sorted order.
2. A municipality with no cell centre gets the one cell that holds its polygon's
   representative point; its `n_cells` is 1.
3. A cell is 100 ha, so a municipality's hectares are its summed shares divided by 100.
4. The split: a municipality in either exploration list goes to derived, every other
   municipality in the boundaries goes only to sealed. The build cannot read the confirmation
   list, so the other half is "everything not in the exploration lists".

## Checks that stop the build

Nothing is uploaded after any of these:

- a code in both exploration lists, or an exploration code that is not in the boundaries;
- the catalog bands are not the four above in order, the years are not exactly 1985-2025, or
  the two rasters are on different grids;
- a raster's shape, dtype or band count differs from the catalog, or a share is above its scale;
- a year's file is missing from the manifest;
- in any cell the four bands sum to more than 10,000;
- national `garimpo_ha` in 2022 (all rows) is below 100,000 ha or above 1,000,000 ha.
  Cortinhas Ferreira Neto et al. (2024) report about 263,000 ha of garimpo in 2022.

## Manifest notes

Exploration-half counts only: municipalities, small municipalities (the representative-point
rule), and `garimpo_ha` for 1985, 2000, 2012 and 2024. Never a confirmation-half number.
