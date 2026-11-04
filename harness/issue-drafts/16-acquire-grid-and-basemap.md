# Task: acquire the census grids (2010, 2022), the basemap and the 2024 boundaries

## Goal

Four acquire scripts, so the `data-pipeline` workflow can download IBGE's
1 km census grid for 2022 and 2010, the Natural Earth basemap layers and
IBGE's 2024 state, municipal and Legal Amazon boundaries. They feed the
`grid_cells` build, the exposure measure and figures 1-5.

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read the four catalog
entries first: `ibge_grid_2022`, `ibge_grid_2010`, `naturalearth_basemap`,
`ibge_boundaries_2024` (`data/catalog.yaml`, already written), and the
newest entry in `research/lessons.md`.

## What the real servers do (checked 2026-11-04)

All 46 URLs were checked with `terrain.http.UrllibFetcher`: HEAD gives
`Content-Length`, `ETag` and `Last-Modified`, and GET's headers equal HEAD's,
so the existing acquirer works unchanged (no `meta`, no `name`). Every file
was downloaded in full: each size equals its Content-Length, `testzip()`
passes and the member named in its `check` exists.

| Dataset | Files | Size | Member checked |
| --- | --- | --- | --- |
| `ibge_grid_2022` | 1 | 416.4 MB | `BR1KM.shp` |
| `ibge_grid_2010` | 38 (`grade_id33.zip` ... `grade_id93.zip`) | 578.7 MB | `*.shp` (one per zip) |
| `naturalearth_basemap` | 4 | 12.5 MB | `ne_10m_<layer>.shp` |
| `ibge_boundaries_2024` | 3 | 226.8 MB | `BR_UF_2024.shp`, `BR_Municipios_2024.shp`, `Limites_Amazonia_Legal_2024.shp` |

## In scope

- `pipeline/acquire/ibge_grid_2022.py`, `pipeline/acquire/ibge_grid_2010.py`,
  `pipeline/acquire/naturalearth_basemap.py`,
  `pipeline/acquire/ibge_boundaries_2024.py`: the usual thin script, the same
  as `pipeline/acquire/ibge_municipalities.py` with the dataset name changed.
- `tests/test_acquire.py`: add the four datasets to
  `test_real_catalog_url_counts`, and one test that the stored names of
  `ibge_grid_2010` are `grade_id<NN>.zip` for exactly these 38 tiles: 33-36,
  42-46, 50-56, 60-66, 70-76, 80-85, 92, 93.

Expected files (five): the four scripts and `tests/test_acquire.py`.

## Out of scope

- `data/catalog.yaml` (already has the entries), `data/manifests/`,
  `data/fixtures/`, workflows, `pyproject.toml`, `uv.lock`,
  `src/terrain/acquire.py` (no change needed).
- Reading the shapefiles (the `grid_cells` build is a later task).

## Done when

1. `expand_urls` on the real catalog gives `ibge_grid_2022` 1,
   `ibge_grid_2010` 38, `naturalearth_basemap` 4 and `ibge_boundaries_2024`
   3 files, and the counts for every other dataset are unchanged.
2. The stored names of `ibge_grid_2010` are exactly the 38 `grade_id<NN>.zip`
   above.
3. Each of the four scripts calls `run_script` with its own dataset name and
   contains no URL or GCS path (the existing `test_no_url_or_dataset_folder_in_code`
   passes).
4. No test uses the network; `uv run ruff check .`, `uv run ruff format
   --check .` and `uv run pytest` pass.
