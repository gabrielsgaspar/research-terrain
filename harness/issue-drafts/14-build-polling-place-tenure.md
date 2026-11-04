# Task: distance from every polling place to indigenous land, settlements and undesignated forest, 2008-2024

## Goal

For each Legal Amazon polling place in each election year, the distance in
kilometres to the nearest indigenous land, agrarian-reform settlement and
undesignated public forest, so strongholds can be typed by who lives there
and by the land nobody votes on.

## Idea

`research/ideas/0001-electoral-strongholds.md` (kill criterion 1, and the
"land with no voters" outcome). Read `data/fixtures/cnfp/README.md` and the
`cnfp_public_forests` catalog entry first.

## Prerequisites

Task 13 merged, and `data/manifests/acquire/cnfp_public_forests.json` merged
(six editions: 2008, 2012, 2016, 2020, 2024 retificado, 2025).

## The rules (checked on the real data, 2026-11-04)

1. **Read** each edition's shapefile from its zip with pyshp, encoding
   `utf-8` with errors replaced (some text fields are cut mid-character),
   skipping empty shapes and keeping only polygons whose bounding box meets
   the Legal Amazon box (longitude -74 to -43, latitude -18.5 to 5.5).
2. **Groups.** Split `categoria` on `/` or `;` and strip each part:
   - indigenous: a part equals `TI` or contains `Terra Ind`;
   - settlement: the first part is one of PA, PA., PAE, PDS, PAF, PAC, PCA,
     PIC, PAD, PE, PAM, PAR, PRB, PFP, PCT;
   - undesignated: `tipo` (2008: `tipo_flor`) equals `TIPO B`.
   A polygon can be in more than one group.
3. **Layers for election year y:**
   - indigenous and undesignated from edition y's own file (2024: the
     retificado file);
   - settlements from the 2025 edition, kept if their creation year (the
     first 4-digit year from 1800 to 2099 in `anocriacao`) is at most y. In
     2025 every settlement has a creation date. Earlier editions lack
     conventional settlements (PA), so they are not used for this layer.
4. **Distance.** Project polygons and points to kilometres with
   x = longitude × 111.32 × cos(latitude), y = latitude × 110.574 (accurate
   within about 1% at these distances; no new dependency), and take the
   distance to the nearest polygon of each layer with a shapely `STRtree`.
   Inside a polygon, the distance is 0.
5. Polling places without coordinates get null distances and are counted.

Whole-Legal-Amazon result with these rules (sanity check for the notes):

| Share of polling places | 2008 | 2012 | 2016 | 2020 | 2024 |
| --- | --- | --- | --- | --- | --- |
| Inside an indigenous land | 1.2% | 1.8% | 2.0% | 2.2% | 2.4% |
| Within 5 km of one | 4.8% | 5.3% | 5.8% | 6.0% | 6.3% |
| Inside a settlement | 1.6% | 1.8% | 1.9% | 2.0% | 2.1% |
| Within 5 km of one | 25.1% | 28.1% | 28.6% | 28.6% | 28.7% |
| Within 5 km of undesignated forest | 9.1% | 34.3% | 37.1% | 36.3% | 35.5% |

Layer sizes in the box: indigenous 411 / 861 / 588 / 649 / 1,205 polygons;
settlements 3,218 / 3,538 / 3,642 / 3,660 / 3,663; undesignated 496 / 10,548 /
1,624 / 1,696 / 2,832. The 2008 edition records far less undesignated land
than later ones: a change in the register's coverage, not in the land. The
contract must say so.

## In scope

- `src/terrain/builds/polling_place_tenure.py` and
  `pipeline/build/polling_place_tenure.py`. Inputs:
  `data/manifests/acquire/cnfp_public_forests.json` and
  `data/manifests/build/polling_places.json`.
- Output `data/derived/polling_place_tenure/<hash>/polling_place_tenure_<year>.parquet`
  for 2008, 2012, 2016, 2020, 2024: the `polling_places` key (`ano`,
  `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), `dist_indigenous_km`,
  `dist_settlement_km`, `dist_undesignated_km`. Keep `nr_zona` and
  `nr_local_votacao` the same types as in `polling_places`.
- Notes per year: places, places without coordinates, layer sizes, and the
  share of places within 0, 2 and 5 km of each layer.
- Checks the build enforces: one row per `polling_places` row; every layer
  non-empty in every year; distances non-negative.
- Extract one edition at a time into the temporary directory and delete it
  before the next (the unpacked 2025 and 2024 files are about 900 MB each).
  Follow AGENTS.md: upload only after every check passes; hash this build's
  code and every data-handling module it imports, input SHA-256s sorted.
- `data/contracts/polling_place_tenure.md` and
  `tests/test_build_polling_place_tenure.py`.

Expected files (four): `src/terrain/builds/polling_place_tenure.py`,
`pipeline/build/polling_place_tenure.py`,
`data/contracts/polling_place_tenure.md`,
`tests/test_build_polling_place_tenure.py`. The catalog entry already exists.

## Out of scope

- Typing strongholds or candidates (task 15); outcomes; quilombola
  territories (`TRQ`), protected areas.
- `data/catalog.yaml`, `data/fixtures/`, `data/manifests/`, workflows,
  `pyproject.toml`, `uv.lock`.

## Done when

1. From the fixtures (each GeoJSON written to a zipped shapefile in the
   test, with a 2012-style schema for 2024 and 2025 and the 2008 schema for
   2008), the 2024 fixture's 18 polling places have 5 with
   `dist_settlement_km` = 0 and 15 within 2 km, and none within 5 km of
   undesignated land.
2. The 2008 stations of town 04367 (14) have 0 inside a settlement, 3 within
   2 km and 12 within 5 km of one, and 2 inside, 12 within 2 km and 14 within
   5 km of undesignated land.
3. A test adds an indigenous polygon (category `TI`, and in the 2008 schema
   `Terra Indígena`) containing one fixture place: that place's
   `dist_indigenous_km` is 0 and a place about 3 km away has a value between
   2.9 and 3.1.
4. A settlement created after the election year is not in that year's layer
   (a 2025 polygon dated `01/01/2020` counts for 2020 and 2024, not 2016).
5. A text field cut mid-character does not stop the build.
6. The one-row-per-place, non-empty-layer and non-negative checks each raise
   on broken input built in the test.
7. Changing the build's code changes the output path; a second build with the
   same inputs is `unchanged`.
8. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
