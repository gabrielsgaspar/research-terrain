# Task: figure 3, who lives where (2022 population per 1 km cell, with land tenure)

## Goal

`figures/03_population.py`: the 2022 census population of every Legal
Amazon 1 km cell on a log colour scale, with the 2024 indigenous lands,
settlements and undesignated forest outlined, so a reader sees that most of
the region's land has no one living on it and where tenure sits relative to
people.

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read `figures/README.md`,
`data/contracts/grid_cells.md`, `data/contracts/figure_layers.md` and
`src/terrain/figures.py` (task 18) first.

## Prerequisites

Tasks 18 and 19 merged; `data/manifests/build/grid_cells.json` and
`data/manifests/build/figure_layers.json` merged.

## The design (checked on the real files, 2026-11-04)

- **Raster:** one pixel per cell, from `x_km`, `y_km` of `grid_cells` (read
  only `x_km`, `y_km`, `pop_2022`). The array spans the cells' Albers bounds
  (3,350 × 2,580 km); a pixel with no cell or with `pop_2022` = 0 is
  transparent (masked). Draw with `imshow(..., origin="lower",
  extent=(x_min, x_max + 1, y_min, y_max + 1), interpolation="nearest")` and
  `LogNorm(vmin=1, vmax=<largest pop_2022>)`, colormap `magma_r`, colour bar
  "People per km² (2022)". 92.6% of the 5,029,081 cells are empty, so the
  image is mostly transparent. On the real cells the array is 2,580 × 3,350
  pixels, the largest cell holds 27,239 people, and a test drawing gave a
  262 KB PNG and a 135 KB PDF, far under the workflow's limits.
- **Background:** as figure 1 (`terrain.figures` helpers): Brazil white,
  other countries `#e6e6e6`, ocean `#cfe3f3`, states `#9a9a9a` 0.3 pt, Legal
  Amazon outline black 1.2 pt; extent = the Legal Amazon outline's bounds
  plus 150 km.
- **Tenure outlines (no fill), 0.35 pt:** `indigenous` `#d95f02`,
  `settlement` `#7570b3`, `undesignated` `#1b9e77`, with a legend of the
  three.
- Size 6.5 × 6 in, saved with `terrain.figures.save` (PNG 300 dpi,
  deterministic PDF).

## In scope

- `src/terrain/figures.py`: add `population_raster(x_km, y_km, pop)` (the
  masked array and its extent) and `population(layers, cells, out_dir)`.
- `figures/03_population.py`: thin script like `figures/01_study_area.py`.
- `tests/test_figures.py`: the cases below.

Expected files (three): `src/terrain/figures.py`,
`figures/03_population.py`, `tests/test_figures.py`.

## Out of scope

Everything outside those three files; outcome data of any kind.

## Done when

1. `population_raster` on three cells ((10, 20, 5), (11, 20, 0), (13, 22,
   40)) gives a 3 × 4 array with extent (10, 14, 20, 23), the value 5 at
   row 0 column 0 and 40 at row 2 column 3, and every other pixel masked,
   including the zero-population cell.
2. `population` with synthetic layers and cells writes exactly
   `03_population.png` and `03_population.pdf`; a second run gives a
   byte-identical PDF.
3. The script contains no URL or GCS path and calls only `terrain.figures`.
4. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
