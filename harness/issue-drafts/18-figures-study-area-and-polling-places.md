# Task: figures 1 (study area) and 2 (where the polling places are)

## Goal

The first two paper figures, drawn by scripts that `figures-run` runs:

- **Figure 1, study area** (`figures/01_study_area.py`): South America
  zoomed to the Legal Amazon. Other countries light grey, Brazil white,
  ocean, lakes and rivers light blue, state borders thin grey, the Legal
  Amazon outline bold, and a small inset of South America with a rectangle
  showing the main map's extent.
- **Figure 2, polling places** (`figures/02_polling_places.py`): density of
  polling places in hexagons with **one shared colour scale**: 2008 and 2024
  side by side (`02_polling_places.png/.pdf`, the paper), and all five
  years 2008, 2012, 2016, 2020, 2024 (`02_polling_places_appendix.png/.pdf`).

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read `figures/README.md`
(the script contract) and `data/contracts/figure_layers.md` and
`data/contracts/polling_places.md` first.

## Prerequisites

Task 17 merged and `data/manifests/build/figure_layers.json` merged; task 19
merged (`terrain.grid` holds the projection); `data/manifests/build/polling_places.json`
(exists).

## The design

- **Projection:** everything is drawn in IBGE's Albers km
  (`terrain.grid.to_albers_km`), equal-area, so hexagons have equal area.
- **Colours:** ocean, lakes and rivers `#cfe3f3`; other countries `#e6e6e6`;
  Brazil (`country` with code `BRA`) white; state borders `#9a9a9a`, 0.3 pt;
  Legal Amazon outline black, 1.2 pt; rivers with `scalerank` ≤ 6 only,
  0.4 pt. No titles (the paper's captions carry them); panel labels for
  figure 2 are the years.
- **Figure 1:** main map extent = the Legal Amazon outline's Albers bounds
  plus 150 km on each side; inset (about a quarter of the width, lower
  right) shows the whole `FRAME` of `figure_layers` with the main extent as
  a black rectangle. Size 6.5 × 6 in.
- **Figure 2:** polling places with coordinates (`lat`, `long` not null;
  2008: 14,641, 2024: 16,312 rows in `polling_places`, under 0.5% without
  coordinates in any year) projected to Albers km; `matplotlib` `hexbin`
  with hexagons 25 km across (`gridsize` from the Legal Amazon extent),
  `mincnt=1`, counts on a `LogNorm` whose `vmin` = 1 and `vmax` = the
  largest hexagon count over **all five years**, the same for every panel
  of both outputs, colormap `viridis`, one colour bar labelled "Polling
  places per hexagon". Background: Brazil white, states, Legal Amazon
  outline; same extent in every panel. Paper: 1 × 2 panels, 6.5 × 3.6 in;
  appendix: 2 × 3 panels with the colour bar in the sixth, 6.5 × 6 in.
- **Saving:** PNG at 300 dpi and PDF with `metadata={"CreationDate": None}`
  (`figures/README.md`), so the same inputs give the same PDF.

## In scope

- `src/terrain/figures.py`: the logic, tested:
  - `fetch(store, manifest, suffix, tmp_dir)`: download the one file of a
    manifest ending in `suffix` and check its SHA-256 (as the builds do).
  - `read_layers(path)`: `figure_layers.parquet` to a dict from layer name
    to a list of (shapely geometry in Albers km, code, name, scalerank).
  - drawing helpers for polygons and lines on an axis (a
    `PathCollection`/`LineCollection` from shapely geometries).
  - `hex_scale(points_by_year, extent, size_km)`: the shared `vmax`.
  - `study_area(layers, out_dir)` and `polling_places(layers, points_by_year,
    out_dir)`: draw and save the figures.
  - `save(fig, out_dir, name)`: PNG 300 dpi and deterministic PDF.
- `figures/01_study_area.py`, `figures/02_polling_places.py`: thin scripts
  (`--out-dir`, `GCSStore(TERRAIN_BUCKET)`, manifests read from
  `data/manifests/`, call `terrain.figures`).
- `tests/test_figures.py`.

Expected files (four): `src/terrain/figures.py`,
`figures/01_study_area.py`, `figures/02_polling_places.py`,
`tests/test_figures.py`.

## Out of scope

`paper/figures/` (written by the workflow), `data/`, workflows,
`pyproject.toml`, `uv.lock`; figure 3 (task 20).

## Done when

1. With synthetic layers (a few squares and a line, in degrees, written to a
   `figure_layers.parquet` in the test) `study_area` writes exactly
   `01_study_area.png` and `01_study_area.pdf` into the folder; the PNG
   starts with the PNG signature and the PDF with `%PDF-`.
2. With synthetic points for five years, `polling_places` writes exactly
   `02_polling_places.png/.pdf` and `02_polling_places_appendix.png/.pdf`.
3. `hex_scale` returns the largest count over all years, not the largest of
   one year (a test where 2024 has the densest hexagon and 2008 a sparser
   one); both outputs use that `vmax`.
4. Running a figure twice on the same inputs gives byte-identical PDFs.
5. `fetch` raises on a file whose SHA-256 differs from its manifest.
6. The scripts contain no URL or GCS path and call only `terrain.figures`.
7. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
