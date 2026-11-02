# Task: build located polling places, Legal Amazon, 2008-2024

## Goal

One table of polling places for the Legal Amazon with coordinates, their
source and an error bound, for the elections the stronghold design uses.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md`. Read "Geography" in
`data/fixtures/tse/README.md` and `data/fixtures/hidalgo/README.md` first.

## What the real files contain (checked 2026-11-02)

- TSE polling places (2012 onward): one row per section and round, so a
  polling place repeats. (`nr_turno`, `cd_municipio`, `nr_zona`, `nr_secao`)
  is unique. A polling place (`cd_municipio`, `nr_zona`,
  `nr_local_votacao`) has one coordinate pair, except 14 places in 2024 with
  two. Missing coordinates are `-1`.
- Hidalgo (2006 onward): (`ano`, `cd_localidade_tse`, `nr_zona`,
  `nr_locvot`) is unique over all 944,687 rows. `cd_localidade_tse` is not
  zero-padded; `conf_dist_km` is 0 for the TSE's own coordinates.

## In scope

- `src/terrain/builds/polling_places.py` and
  `pipeline/build/polling_places.py`. Inputs:
  `data/manifests/acquire/tse_polling_places.json`,
  `data/manifests/acquire/polling_stations_geocoded.json` and
  `data/manifests/build/municipalities.json` (to keep Legal Amazon
  municipalities and add `cd_ibge`).
- Output `data/derived/polling_places/<hash>/polling_places_<year>.parquet`
  for 2008, 2012, 2016, 2020 and 2024: one row per (`ano`, `cd_ibge`,
  `sg_ue`, `nr_zona`, `nr_local_votacao`) with `lat`, `long`,
  `coord_source` (`tse` or `hidalgo`), `conf_dist_km` (0 for TSE),
  `panel_id` (Hidalgo's, where present), the place's name and address.
  Never keep phone numbers.
- TSE coordinates first, where not `-1`; otherwise Hidalgo's. For a place
  with two TSE coordinates, take the most frequent and count such places.
  2008 uses Hidalgo only.
- Checks the build enforces: the output key is unique; every row has a
  `cd_ibge` in the Legal Amazon; per year, the share of places without any
  coordinate is in the manifest notes and is under 5%.
- `data/contracts/polling_places.md` and `tests/test_build_polling_places.py`.

Expected files (four): `src/terrain/builds/polling_places.py`,
`pipeline/build/polling_places.py`, `data/contracts/polling_places.md`,
`tests/test_build_polling_places.py`.

The output path hashes this build's code and every data-handling `terrain`
module it imports, with input SHA-256s sorted (AGENTS.md).

## Out of scope

- Section votes (07b); catchments, grids or strongholds.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`.

## Done when

1. From the fixtures, 2024 places with TSE coordinates use them
   (`coord_source = tse`, `conf_dist_km = 0`), and places without use
   Hidalgo's.
2. 2008 places come from Hidalgo only.
3. A place with two TSE coordinate pairs gets the most frequent, and the
   count appears in the notes.
4. No output column holds a phone number.
5. The key, Legal Amazon and coverage checks each raise on broken input.
6. Test inputs are deterministic (fixed zip timestamps, gzip `mtime=0`); no
   test touches the network or GCS.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
