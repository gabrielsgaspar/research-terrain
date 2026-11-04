# Task: figure 5, land without voters (empty cells over undesignated forest)

## Goal

`figures/05_land_without_voters.py`: where the Legal Amazon's undesignated
public forest is, and that almost no one lives on it. Each 1 km cell inside
undesignated forest in 2024 is drawn by whether anyone lived in it in 2022.
This is the land the displacement prediction of idea 0001 is about.

## Idea

`research/ideas/0001-electoral-strongholds.md` ("Displacement"). Read
`figures/README.md`, `data/contracts/grid_cells.md` and
`src/terrain/figures.py` (tasks 18 and 20) first.

## Prerequisites

Task 20 merged (`terrain.figures.population_raster` and the background
helpers); `data/manifests/build/grid_cells.json` and
`data/manifests/build/figure_layers.json` merged.

## The design (checked on the real cells, 2026-11-04)

- **Cells:** `grid_cells` columns `x_km`, `y_km`, `pop_2022`,
  `share_undesignated_2024`. A cell is **undesignated** when
  `share_undesignated_2024` > 0. On the real cells: 762,027 undesignated
  cells, 698,223 of them (91.6%) with `pop_2022` = 0; they hold 502,773 of
  the 522,848 km² of undesignated forest in kept cells.
- **Raster:** one pixel per cell over the cells' Albers bounds, three
  classes, everything else transparent: undesignated and empty `#1b9e77`;
  undesignated and populated `#d95f02`; every other populated cell
  `#bdbdbd` (for orientation). Draw with `imshow` of a `ListedColormap`
  and `interpolation="nearest"`, `origin="lower"`, the same extent rule as
  figure 3.
- **Background and extent:** as figure 3 (Brazil white, other countries
  `#e6e6e6`, ocean `#cfe3f3`, states `#9a9a9a` 0.3 pt, Legal Amazon outline
  black 1.2 pt; extent = the outline's bounds plus 150 km).
- **Legend** of the three classes, with each class's cell count in the
  label, for example "Undesignated forest, no residents (698,223 cells)".
- Size 6.5 × 6 in, saved with `terrain.figures.save`.

## In scope

- `src/terrain/figures.py`: add `tenure_classes(x_km, y_km, pop,
  share_undesignated)` (the class array, its extent and the class counts) and
  `land_without_voters(layers, cells, out_dir)`.
- `figures/05_land_without_voters.py`: thin script like
  `figures/03_population.py`.
- `tests/test_figures.py`: the cases below.

Expected files (three): `src/terrain/figures.py`,
`figures/05_land_without_voters.py`, `tests/test_figures.py`.

## Out of scope

Everything outside those three files; outcome data of any kind.

## Done when

1. `tenure_classes` on four cells, one of each kind (undesignated and empty,
   undesignated and populated, populated elsewhere, empty elsewhere), gives
   the three classes at the right pixels, masks the fourth, and counts 1 of
   each class.
2. `land_without_voters` with synthetic layers and cells writes exactly
   `05_land_without_voters.png` and `05_land_without_voters.pdf`; a second
   run gives a byte-identical PDF.
3. The script contains no URL or GCS path and calls only `terrain.figures`.
4. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
