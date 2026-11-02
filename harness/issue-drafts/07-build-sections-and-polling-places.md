# Task: build section votes and located polling places (Legal Amazon)

## Goal

The two tables the stronghold design needs: votes by section with each
section's polling place, and every polling place with coordinates and an
error bound, for the Legal Amazon, 2008-2024.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md`. Read "Geography"
and "Keys and joins" in `data/fixtures/tse/README.md`, and
`data/fixtures/hidalgo/README.md`.

## In scope

- `src/terrain/builds/sections.py` and `pipeline/build/sections.py`. Inputs:
  the `tse_votes_by_section`, `tse_polling_places` and
  `polling_stations_geocoded` acquire manifests, and the `tse_results`,
  `tse_candidates` and `municipalities` build manifests.
- Outputs under `data/derived/sections/<hash>/`:
  - `section_votes.parquet`: one row per election, round, section, office
    and number voted for, with `cd_ibge`, `nr_zona`, `nr_secao`,
    `nr_local_votacao`, `qt_votos`, and the candidacy key where the number
    is a candidate. 2024 rows carry `SQ_CANDIDATO`; earlier rows get it by
    matching (`sg_ue`, `cd_cargo`, `nr_turno`, `nr_votavel`) to
    `candidate_votes`, choosing the candidacy with votes when a number has
    several. Numbers 95-97 are blank, null and annulled votes.
  - `polling_places.parquet`: one row per election year, municipality, zone
    and polling place: `lat`, `long`, `coord_source` (`tse` or `hidalgo`),
    `conf_dist_km` (0 for TSE coordinates), Hidalgo's `panel_id` where
    available. TSE coordinates first (2012 onward, where not `-1`), then
    Hidalgo's.
- Years 2004-2024 for `section_votes` (2004 has no coordinates; keep it
  for vote margins). Leave out 2000: no polling-place IDs and incomplete
  coverage. Record that in the manifest notes.
- Checks the build enforces: summing section votes per candidate equals
  `candidate_votes.qt_votos_nominais` for at least 99% of candidates in
  municipalities with section data, per year (it is exact in Pará in 2008
  and 2024), with the share written in the manifest notes; the share of
  sections whose polling place has no coordinate is reported per year and
  must be under 5% from 2008.
- `data/contracts/sections.md`.

## Out of scope

- Strongholds, catchments, grids or any analysis (the feasibility census is
  a separate explore task).
- States outside the Legal Amazon.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`.

## Done when

1. From the 2024 fixtures, every candidate's section votes carry the
   candidacy key, and the 2008 fixture rows get it through the results
   match.
2. Fixture polling places get TSE coordinates where present and Hidalgo
   coordinates otherwise, with `coord_source` set.
3. The vote-sum check passes on a small consistent input built in the test
   and raises when enough section rows are altered to cross the 1%
   threshold. (The fixtures hold two sections per town, so their sums do
   not equal the town's results.)
4. A 2000 input is skipped and noted, not silently dropped.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
