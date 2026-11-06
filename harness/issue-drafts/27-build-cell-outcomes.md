# Task: build `cell_outcomes`, MapBiomas code shares per 1 km cell, split by half (decisions 0003 and 0006)

## Goal

For every Legal Amazon 1 km cell (`grid_cells`) and year 2004-2024, the share
of the cell in each MapBiomas code, from the acquired GeoTIFFs. The outcome of
decision 0006 (main: code 4, loss of primary vegetation). Written **split**
(decision 0003): exploration-half rows to `data/derived/cell_outcomes/<hash>/`,
confirmation-half rows to `sealed/outcomes/cell_outcomes/<hash>/`, which no
exploration account can read.

## Idea

`research/ideas/0001-electoral-strongholds.md`; decisions 0001, 0003 and
0006. Read the catalog entry `mapbiomas_deforestation` (its `earthengine:`
block: grid bounds, codes, scale, file names), `data/contracts/grid_cells.md`,
`src/terrain/builds/grid_cells.py` (build style), `src/terrain/split.py` and
`src/terrain/explore.py` (the split list) first.

## Prerequisites

`data/manifests/acquire/mapbiomas_deforestation.json` merged (21 files);
`data/manifests/build/grid_cells.json`; the split list
`data/derived/split/explore_municipalities.csv` (readable by the build
account); `terrain-build` can create in `sealed/outcomes/` (granted
2026-11-05).

## The rules

1. **Cells:** `grid_cells` columns `nome_1KM`, `cd_ibge`, `x_km`, `y_km`.
   The pixel of a cell in a GeoTIFF of shape `(rows, cols, 7)` is row
   `y1 - 1 - y_km`, column `x_km - x0` (`x0`, `y1` from the catalog's
   `grid_km`).
2. **Half:** a cell is in the exploration half if its `cd_ibge` is in the
   split list, else in the confirmation half. Every Legal Amazon
   municipality is in exactly one half (decision 0001); a `cd_ibge` of
   `grid_cells` that is in neither (impossible by construction) stops the
   build.
3. **Per year:** read the year's GeoTIFF with `tifffile` (check its SHA-256
   against the acquire manifest first), take each cell's seven values and
   keep them as `code_1` ... `code_7` (`uint16`, shares × 10,000 as
   acquired). `has_data` is false when all seven are 0 (no MapBiomas pixel
   in the cell).
4. **Checks** (each raises `BuildError` before anything is written): the
   file shape equals the grid; every cell of `grid_cells` appears once per
   year, in exactly one half; on every cell the seven values sum to at most
   10,000 + 7; the share of cells with data is at least 99% (the Legal
   Amazon is inside Brazil, which MapBiomas covers). On the real 2004 file,
   5,028,724 of the 5,029,081 cells (99.993%) have data.
   A sum below 10,000 is allowed: some 30 m pixels carry no code 1-7, so
   10,000 minus the sum is the cell's unclassified share (19,958 Legal
   Amazon cells in 2004, about 1% of their area; acquire PR #181).
5. **Output:** one Parquet per year and half:
   `cell_outcomes_<y>.parquet` with `nome_1KM`, `cd_ibge`, `ano`, `has_data`,
   `code_1` ... `code_7`, `unclassified` (`uint16`, 10,000 minus the sum of
   the seven, 0 when the sum is above 10,000 by rounding; 10,000 when there is
   no data), sorted by `cd_ibge`, `nome_1KM`. Exploration files
   under `data/derived/cell_outcomes/<hash>/`, confirmation files under
   `sealed/outcomes/cell_outcomes/<hash>/`, the same `<hash>` (input
   SHA-256s, split-list SHA-256, years, and the source of this module and
   `terrain/grid.py`).
6. **Upload after all checks, sealed first:** write every file locally,
   check everything, then upload the sealed files, then the derived files,
   then the manifest. The build account cannot read `sealed/`: an existing
   sealed object makes the upload fail (create-only), which stops the build.
7. **Manifest:** `gcs_prefix` and `files` are the derived (exploration)
   folder and files, as usual; a field `sealed_files` lists the sealed files
   (path, SHA-256, bytes), so the record shows both halves were written.
   `unchanged` when the derived manifest exists. Notes: per year, cells per
   half, cells without data and cells partly unclassified (`unclassified`
   above 7). **No statistic of any code** in notes, logs
   or errors: these are outcomes, and the confirmation half must stay unseen.

## In scope

`src/terrain/builds/cell_outcomes.py`, `pipeline/build/cell_outcomes.py`,
`data/contracts/cell_outcomes.md`, `tests/test_build_cell_outcomes.py`.

## Out of scope

`data/catalog.yaml` (entry written), `data/manifests/`, `sealed/` reads,
`confirm/`, workflows, `pyproject.toml`, `uv.lock`; any analysis of the outcome.

## Done when

1. With a `MemoryStore`, two synthetic GeoTIFFs (written with `tifffile`), a
   `grid_cells` table of cells in two municipalities and a split list with one
   of them: the exploration files hold only that municipality's cells, the
   sealed files only the other's, both under the same hash, and every cell's
   `code_*` equal the pixel at rule 1's row and column.
2. `sealed_files` lists the sealed files with their SHA-256; `files` holds
   only `data/derived/` paths, and the manifest validates
   (`terrain.manifest.check_manifest`).
3. Each check fails on its own broken input (wrong shape, a cell whose codes
   sum to 11,000, fewer than 99% of cells with data, a SHA-256 mismatch),
   raising `BuildError` with the store unchanged; an existing sealed object
   stops the build before the derived files are written. A cell whose codes
   sum to 9,000 is kept, with `unclassified` 1,000.
4. A second run is `unchanged`; a changed split list changes the hash.
5. The module prints and stores no statistic of any code (a test runs a
   build with distinctive code values and checks they appear in neither the
   notes nor the log).
6. No test uses the network or GCS; ruff and pytest pass.
