# cell_outcomes

The share of every Legal Amazon 1 km cell in each MapBiomas code, per year 2004-2024
(`research/decisions/0006-outcome-deforestation.md`; main outcome code 4, loss of
primary vegetation). Written split by half (`research/decisions/0003-confirmation-rows.md`):
exploration-half rows are derived data, confirmation-half rows go only to a sealed folder
that no exploration account can read. Built by `src/terrain/builds/cell_outcomes.py`.

Paths come from the catalog entry `cell_outcomes`:

- `data/derived/cell_outcomes/<hash>/cell_outcomes_<y>.parquet`: exploration half.
- `sealed/outcomes/cell_outcomes/<hash>/cell_outcomes_<y>.parquet`: confirmation half.

`<hash>` is the same for both: `content_hash` of the sorted input SHA-256s (the GeoTIFFs
and the `grid_cells` Parquet), the SHA-256 of the split list, the years, and the source
of `terrain/builds/cell_outcomes.py` and `terrain/grid.py`.

## Sources

- `mapbiomas_deforestation`: one GeoTIFF per year, shape `(rows, cols, 7)`, `uint16`, each
  code's share of the cell x 10,000. Grid, codes, scale and file names come from the
  catalog's `earthengine:` block.
- `grid_cells`: `nome_1KM`, `cd_ibge`, `x_km`, `y_km`.
- `data/derived/split/explore_municipalities.csv`: the exploration municipalities
  (one column, `code_ibge`).

## Columns

One file per year and half; sorted by `cd_ibge`, `nome_1KM`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `ano` | int | year |
| `has_data` | bool | false when all seven values are 0 (no MapBiomas pixel in the cell) |
| `code_1` ... `code_7` | uint16 | share of the cell in the code, x 10,000, as acquired |
| `unclassified` | uint16 | 10,000 minus the seven values; 0 when the sum is above 10,000 by rounding; 10,000 when there is no data |

## The rules

1. Pixel of a cell: row `y1 - 1 - y_km`, column `x_km - x0` (`x0`, `y1` from the
   catalog's `grid_km`).
2. Half: a cell is in the exploration half if its `cd_ibge` is in the split list, else in
   the confirmation half. A null or non-7-digit `cd_ibge` stops the build.
3. A sum below 10,000 is allowed: some 30 m pixels carry no code 1-7.

## Checks

The build raises `BuildError` before anything is uploaded when:

- a file's SHA-256 differs from the acquire manifest, or it is not `uint16` of the grid's shape;
- `grid_cells` has a duplicate cell, a bad `cd_ibge`, or a cell outside the grid;
- the seven values of a cell sum to more than 10,000 + 7;
- fewer than 99% of the cells of a year have data.

## Upload and manifest

All files are written locally and checked first. Sealed files are uploaded first, create-only
(the build account cannot read `sealed/`; an existing object stops the build), then the
derived files, then the manifest. `files` lists the derived files; `sealed_files` lists the
sealed files (path, SHA-256, bytes). A run whose derived manifest exists is `unchanged`.
Notes give, per year, the cells per half, the cells without data and the cells partly
unclassified (`unclassified` above 7). They hold no statistic of any code.
