# Task: acquire MapBiomas deforestation as code shares of every 1 km cell (Earth Engine)

## Goal

`pipeline/acquire/mapbiomas_deforestation.py`: for each year 2004-2024,
export from Earth Engine the share of each MapBiomas code (1-7) in every
IBGE 1 km cell of the `grid_cells` grid, as one GeoTIFF per year in
`data/raw/mapbiomas/<date>/`, check every file, and write the manifest. The
outcome of decision 0006; the build that splits it by half is a later task.

## Idea

`research/ideas/0001-electoral-strongholds.md`; decisions 0003 and 0006. Read
the catalog entry `mapbiomas_deforestation` (its `earthengine:` block holds
every parameter), `src/terrain/acquire.py` (manifest, dated folders,
`unchanged`), `src/terrain/grid.py` (the projection) and `pipeline/README.md`.

## What the real service does (checked 2026-11-04)

- `earthengine-api` initialises with `google.auth.default(scopes=[".../auth/earthengine",
  ".../auth/cloud-platform"])` and `ee.Initialize(credentials, project=<project>)`.
  In `data-pipeline` the project is in `GOOGLE_CLOUD_PROJECT` (set by the
  auth action); the account is `terrain-acquire`, which has
  `roles/earthengine.viewer` and `roles/serviceusage.serviceUsageConsumer`.
- The asset (catalog `earthengine.asset`) is readable; `ee.data.getAsset(...)`
  gives `updateTime` `2025-08-09T18:24:56.356319Z` and `sizeBytes`
  `22401554377`: these are the version, like an ETag.
- Per year, `img = ee.Image(asset).select(f"classification_{y}")`, then
  `ee.Image.cat([img.eq(c).rename(f"c{c}") for c in codes])
  .reduceResolution(ee.Reducer.mean(), maxPixels=2048).multiply(scale).round().toUint16()`
  on the grid `crs = pyproj.CRS.from_proj4(terrain.grid.ALBERS).to_wkt(version="WKT1_GDAL")`
  (Earth Engine rejects WKT2), `crsTransform = [1000, 0, x0*1000, 0, -1000,
  y1*1000]`, `dimensions = (x1-x0) x (y1-y0)` = 3350 x 2580 (the bounds of
  `grid_cells`). On real test tiles this gives, in every cell with data,
  shares summing to 10,000 ± 1 (rounding of 7 codes), and the cell at
  column `i`, row `j` is the `grid_cells` cell `x_km = x0 + i`,
  `y_km = y1 - 1 - j`.
- A whole year must be a **batch export** (`ee.batch.Export.image.toCloudStorage`,
  `fileFormat="GeoTIFF"`, `maxPixels=1e10`, `fileDimensions=[3584, 2816]` so
  each year is one file, multiples of the 256 shard size): interactive
  `computePixels` takes 132 s per 200 km tile, about 5.5 h per year.
- The exported GeoTIFF is Deflate-compressed (`compression` 32946), one page,
  `uint16`, shape `(rows, cols, 7)`; `tifffile` reads it without extra codecs
  (it warns about the `GDAL_NODATA` tag `0.0`; ignore that).
- Not checked, so the first run settles it: the time a full-year export
  takes, and whether writing to the bucket needs more than the acquire
  account's create-only grant on `data/raw/` (if Earth Engine also needs to
  read the bucket's metadata, Gabriel adds `roles/storage.legacyBucketReader`).

## The rules

1. **Version and `unchanged`:** the manifest's `sources` hold one entry: `url`
   = the asset id, `last_modified` = its `updateTime`, `etag` = a hash of the
   catalog's `earthengine:` block (so changing years, codes, scale or grid is
   a new version), `bytes` = `sizeBytes`. If the latest manifest under
   `data/raw/mapbiomas/` has the same, the result is `unchanged` and nothing
   is exported.
2. **Folder:** the next free dated folder, as `acquire._free_prefix` gives.
3. **Exports:** start all years' tasks (`description` `mapbiomas_<y>`,
   `fileNamePrefix` the folder plus the catalog `file` name without `.tif`),
   then poll every 60 s until each is `COMPLETED`, up to 160 minutes in all.
   A `FAILED` or `CANCELLED` task, or the time limit, stops the run with the
   task's error message (no manifest is written; the next run uses a new
   dated folder).
4. **Checks**, after all tasks finish, on every file (downloaded to a
   temporary folder): it exists under the folder with the expected name; it
   reads with `tifffile` as `uint16` of shape `(2580, 3350, 7)`; in every
   cell whose shares are not all 0, they sum to 10,000 ± 7; at least 50% of
   cells have data (the Legal Amazon is about 60% of its bounding box);
   SHA-256 and bytes go into the manifest's `files`. Any failure raises.
5. **Notes:** per year, the cells with data. No statistic of any code is
   computed or printed: these are outcomes, and both halves are in the file.
6. The run never reads `data/derived/split/` or anything in `sealed/`.

## In scope

- `src/terrain/earthengine.py`: the logic above, with Earth Engine and the
  store injected (a small protocol: `asset_info`, `start_export`,
  `task_state`), so tests use a fake; `run_script` like `terrain.acquire`.
- `pipeline/acquire/mapbiomas_deforestation.py`: thin script.
- `tests/test_earthengine.py`.

Expected files (three): `src/terrain/earthengine.py`,
`pipeline/acquire/mapbiomas_deforestation.py`, `tests/test_earthengine.py`.

## Out of scope

`data/catalog.yaml` (entry written), workflows, `data/manifests/`, the
outcome build, any statistic of the outcome.

## Done when

1. The export parameters built from the real catalog entry are exactly the
   ones above (WKT1 Albers, transform `[1000, 0, 2823000, 0, -1000,
   11902000]`, dimensions `3350x2580`, file dimensions `[3584, 2816]`, 21
   years 2004-2024, codes 1-7, scale 10,000).
2. With a fake Earth Engine that "exports" small synthetic GeoTIFFs (written
   with `tifffile` in the test) into a `MemoryStore`, a run creates one file
   per year, checks them and returns a `created` manifest whose `sources`
   hold the asset's `updateTime` and `sizeBytes`.
3. The same asset version gives `unchanged` with no export started; a new
   `updateTime` or a changed `earthengine:` block gives a new folder.
4. A failed task, a timeout, a missing file, a wrong shape or a cell whose
   shares sum to 9,000 each raise, and no manifest is written.
5. The code reads nothing under `data/derived/split/` or `sealed/` and prints
   no statistic of any code (a test greps the module for both prefixes).
6. No test uses the network, GCS or Earth Engine; `uv run ruff check .`,
   `uv run ruff format --check .` and `uv run pytest` pass.
