# Task: figure 6, one close pair: the winner's and the loser's strongholds over their exposure

## Goal

`figures/06_close_pair.py`: one exploration-half municipality, two panels
side by side. Left, the narrowly elected candidate of one close pair; right,
the narrowly defeated one. Each panel shows that candidate's vote share at
every polling place (circles) over the exposure of the 1 km cells around
them (decision 0004's kernel-weighted share), with indigenous lands and
settlements drawn. One candidate's stronghold is near an indigenous land,
the other's near a settlement. Candidates are never named. First handoff,
figure 4; renumbered 6 (Gabriel, 2026-11-04).

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read `figures/STYLE.md`,
`src/terrain/style.py`, `src/terrain/figures.py`, `src/terrain/strongholds.py`,
decision 0004, and `explore/0001_kill_criterion_1.py` (how strongholds are
matched to tenure distances) first.

## Prerequisites

Merged manifests `data/manifests/build/cell_exposure.json` (recorded),
`grid_cells.json`, `polling_places.json`, `polling_place_tenure.json`,
`section_votes.json`, `tse_results.json`, `municipalities.json`,
`figure_layers.json`.

## The selection rule (exploration half only)

The script calls `terrain.explore.exploration_municipalities` and
`restrict` on every table it reads, like the explore scripts (the
`figures-run` account can read the split list). For each year 2008, 2012,
2016, 2020, 2024:

1. Close pairs at 0.5% (not inverted) with `terrain.strongholds`
   (`main_election`, `candidacy_votes`, `within_list_pairs`, `valid_votes`,
   `margins`, `close_pairs`).
2. Each candidate's stronghold with `strongholds` (the census's location
   quotient, at least 50 votes at the place). Copy `strongholds` from
   `explore/0001_feasibility_census.py` into `terrain.strongholds` unchanged,
   with a test that it equals the original (as for the other copies).
3. Join each stronghold to `polling_place_tenure` of the same year on
   (`cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), zone and place cast
   to Int64, as `explore/0001_kill_criterion_1.py` does. **Near** means a
   distance of at most 2 km (0 = inside).
4. **Eligible pair:** one candidate's stronghold is near an indigenous land
   and not near a settlement, and the other's is near a settlement and not
   near an indigenous land (either way round).
5. **Choice:** the eligible pair with the smallest |margin|; ties go to the
   later year, then the lower `cd_ibge`, then the lower elected `sq_candidato`.
   If none is eligible, the script raises with a clear message.
6. The script prints one JSON line to stdout: `year`, `cd_ibge`, the
   municipality's `name_ibge`, `margin` (4 decimals), and which candidate
   (`elected` or `not_elected`) is near which layer. No candidate number or
   name is printed or drawn.

## The figure

- **Exposure per candidate:** `E_ic` with the `exp2` kernel and the share
  measure, from `strongholds.exposure` given a one-row pairs table with the
  candidate as `w` and a null `l` (so `D_i` = `E_ic`), for the
  municipality's cells (`grid_cells`, its `cd_ibge`).
- **Extent:** the Albers bounds of the municipality's reached cells, plus
  10 km on each side, the same in both panels; `figure_layers` base map
  (`terrain.figures.base_map`).
- **Cells:** filled 1 km squares coloured by `E_ic` on the purple scale,
  linear from 0 to the largest `E_ic` of either candidate (one shared
  scale); cells with `E_ic` = 0 unfilled.
- **Tenure:** indigenous lands (orange) and settlements (pink) of 2024 from
  `figure_layers`, drawn as categories (`style.CATEGORIES`) under the cells
  at the category opacity.
- **Polling places:** circles at each place with votes, area proportional to
  the candidate's share `s_cp`, white fill, black 0.4 pt edge; the stronghold
  drawn with a thicker 1 pt edge.
- **Panel titles:** "Narrowly elected" and "Narrowly defeated", each followed
  by "(stronghold near an indigenous land)" or "(stronghold near a
  settlement)".
- **Legends at the bottom across both panels** (`style.bottom_colorbar`,
  `style.bottom_legend`): the exposure colour bar labelled "Exposure:
  kernel-weighted vote share" with percent ticks; a one-row legend for
  indigenous land, settlement, polling place (with sizes 10%, 25%, 50%) and
  stronghold.
- **Percent labels:** add one formatter `percent` to `terrain.style` (`0%`,
  `10%`, `25%`: whole percent, no decimals), document it in
  `figures/STYLE.md` next to `thousands`, and test it in
  `tests/test_figure_style.py`. The style changes first, never only the
  figure.
- Size `style.WIDE`, saved as `06_close_pair.png` through `terrain.figures.save`.

## In scope

Expected files (eight): `src/terrain/strongholds.py`, `src/terrain/style.py`,
`figures/STYLE.md`, `src/terrain/figures.py`, `figures/06_close_pair.py`,
`tests/test_strongholds.py`, `tests/test_figures.py`,
`tests/test_figure_style.py`.

## Out of scope

`explore/`, `data/`, workflows, `pyproject.toml`, `uv.lock`; outcome data of
any kind.

## Done when

1. `strongholds` in `terrain.strongholds` equals the census original on
   synthetic tables.
2. On synthetic tables with three close pairs (one eligible, one with both
   strongholds near settlements, one with a stronghold near both layers),
   the selection returns the eligible pair; with two eligible pairs it
   returns the one with the smaller |margin|, and the tie rules hold; with
   none it raises.
3. Every table the selection reads is restricted to the exploration half (a
   test with a municipality outside the half shows it is never chosen).
4. `E_ic` from the one-sided pairs table equals the hand-computed
   kernel-weighted share for a cell 1 km from one place and 3 km from the
   other.
5. The figure function writes exactly `06_close_pair.png`; both panels share
   one colour norm (0 to the larger maximum); the colour bar spans both
   panels and its tick labels end in `%`; titles contain no candidate number.
6. `style.percent` gives `0%`, `10%`, `25%`, `100%`.
7. The script prints the one JSON line of rule 6 and contains no URL or GCS
   path; the existing script tests pass (imports `terrain.figures` or
   `terrain.style`, no `savefig`, no PDF).
8. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
