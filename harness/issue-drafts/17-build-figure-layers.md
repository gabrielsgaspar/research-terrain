# Task: build `figure_layers`, the simplified map layers the paper figures draw

## Goal

The `figures-run` workflow runs as `terrain-analysis`, which reads only
`data/derived/` and `data/explore/`. Figures 1-3 need the basemap, the
boundaries and the 2024 tenure polygons, which are raw. This build writes
them, clipped and simplified, to one Parquet file in `data/derived/`.

## Idea

`research/ideas/0001-electoral-strongholds.md` (figures 1-3). Read the
catalog entries `naturalearth_basemap`, `ibge_boundaries_2024`,
`cnfp_public_forests` and `figure_layers`, `data/contracts/polling_place_tenure.md`
and `src/terrain/builds/polling_place_tenure.py` first.

## Prerequisites

Merged manifests `data/manifests/acquire/naturalearth_basemap.json`,
`data/manifests/acquire/ibge_boundaries_2024.json`,
`data/manifests/acquire/cnfp_public_forests.json`.

## The layers (checked on the real files, 2026-11-04)

`FRAME` = longitude -92 to -26, latitude -57 to 14 (South America with a
margin). `simplify` means `shapely.simplify(g, tol, preserve_topology=True)`
then `shapely.make_valid`; drop a geometry that ends up empty.

| `layer` | Source (zip, member) | Rows | `code`, `name` | Clip | Tolerance (degrees) | Real count |
| --- | --- | --- | --- | --- | --- | --- |
| `country` | `ne_10m_admin_0_countries.zip` | those meeting `FRAME` | `ADM0_A3`, `NAME` | `FRAME` | 0.01 | 31 (includes `BRA`; `FRA` holds French Guiana) |
| `ocean` | `ne_10m_ocean.zip` | all | null, null | `FRAME` | 0.01 | 1 |
| `lake` | `ne_10m_lakes.zip` | those meeting `FRAME` | null, `name` | `FRAME` | 0.01 | 63 |
| `river` | `ne_10m_rivers_lake_centerlines.zip` | those meeting `FRAME` (lines) | null, `name` | `FRAME` | 0.01 | 173 |
| `state` | `BR_UF_2024.zip` | all | `SIGLA_UF`, `NM_UF` | none | 0.01 | 27 |
| `legal_amazon` | `Limites_Amazonia_Legal_2024_shp.zip` | all | null, `NOME` | none | 0.005 | 1 |
| `indigenous` | `CNFP_2024_retificado.zip` | `is_indigenous(categoria)` | null, null | none | 0.002 | 1,205 before simplifying |
| `settlement` | `CNFP_2025.zip` | `is_settlement(categoria)` and `creation_year(anocriacao) <= 2024` | null, null | none | 0.002 | 3,663 before simplifying |
| `undesignated` | `CNFP_2024_retificado.zip` | `is_undesignated(tipo)` | null, null | none | 0.002 | 2,832 before simplifying |

- Natural Earth `scalerank` is kept for `lake` and `river` (figures draw
  only the larger rivers); null elsewhere.
- Tenure layers use the functions of `terrain.builds.polling_place_tenure`
  (`extract_edition`, `read_cnfp`, `is_indigenous`, `is_settlement`,
  `is_undesignated`, `creation_year`), so they are the same polygons as the
  2024 layers of that build (its manifest notes: 1,205 / 3,663 / 2,832).
- All shapefiles declare UTF-8 (`.cpg`); read the Natural Earth and IBGE ones
  with pyshp from the zip (`zipfile` + `io.BytesIO`), encoding `utf-8`.
- After clipping and simplifying, every non-tenure layer is under 0.31 MB
  of WKB on the real files.

## In scope

- `src/terrain/builds/figure_layers.py`: the build, in the style of
  `polling_place_tenure.py` (download each input file and check its SHA-256
  against its manifest, build and check everything locally, upload only
  after every check passes, `unchanged` when the output path has a
  manifest). Output `<derived>/<hash>/figure_layers.parquet`, columns
  `layer` (text), `code` (text), `name` (text), `scalerank` (int), `geometry`
  (binary, WKB, longitude/latitude degrees), sorted by `layer` then input
  order. The hash covers the input SHA-256s (sorted) and the source of this
  module and of `terrain/builds/polling_place_tenure.py`.
- Manifest notes: rows per layer, and for the tenure layers the count before
  simplifying and the number dropped as empty.
- Checks (each raises `BuildError` before anything is written): every layer
  non-empty; `country` contains `BRA`; exactly 27 `state` rows with
  distinct codes; one `legal_amazon` row whose bounds lie within longitude
  -74 to -43 and latitude -18.5 to 5.5; every geometry valid; no tenure
  layer loses more than 1% of its polygons as empty.
- `pipeline/build/figure_layers.py`: the usual thin script (like
  `pipeline/build/polling_place_tenure.py`), reading the three manifests.
- `data/contracts/figure_layers.md`: the contract (columns, layers, rules,
  checks).
- `tests/test_build_figure_layers.py`.

Expected files (four): `src/terrain/builds/figure_layers.py`,
`pipeline/build/figure_layers.py`, `data/contracts/figure_layers.md`,
`tests/test_build_figure_layers.py`.

## Out of scope

`data/catalog.yaml` (entry already written), `data/manifests/`,
`data/fixtures/`, workflows, `pyproject.toml`, `uv.lock`; the figures
themselves (task 18).

## Done when

1. With a `MemoryStore` holding small zipped shapefiles written in the test
   with pyshp (a few synthetic countries including `BRA` and one outside
   `FRAME`, an ocean polygon larger than `FRAME`, one lake, one river line,
   27 states, one Legal Amazon outline) and CNFP zips written from
   `data/fixtures/cnfp/cnfp_2024_sample.geojson` and
   `cnfp_2025_sample.geojson` plus one synthetic `TI` polygon: the build
   writes `figure_layers.parquet` with the expected rows per layer, the
   country outside `FRAME` is absent, and the ocean is clipped to `FRAME`.
2. The settlement layer keeps a fixture settlement created by 2024 and drops
   one whose `anocriacao` is after 2024 (added in the test).
3. Every geometry in the output reads back with `shapely.from_wkb` and is
   valid.
4. Each check fails on its own broken input (no `BRA`, 26 states, an empty
   tenure layer, a Legal Amazon outline outside the box), raising
   `BuildError` with the store unchanged.
5. A second run returns `unchanged` and writes nothing; changing the source
   of `terrain/builds/polling_place_tenure.py` (passed as code to the hash
   function, as in `tests/test_build_polling_place_tenure.py`) changes the
   output path.
6. A file whose SHA-256 differs from its manifest raises.
7. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
