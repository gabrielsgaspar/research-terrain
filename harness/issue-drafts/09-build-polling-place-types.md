# Task: type every Legal Amazon polling place (seat, town, rural, ...), 2008-2024

## Goal

For each polling place in `polling_places`, a type that says whether it is in
the municipal seat, another urban area, or the countryside, and if the
latter, near what kind of locality; plus its eligible voters. The census
(task 10) uses this to ask how many candidates' strongholds lie outside the
seat.

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read
`data/fixtures/ibge/README.md` (localities and urbanized areas) first.

## Prerequisites (done by a person before this task)

- `shapely` and `pyshp` are dependencies (`uv add shapely pyshp`).
- `ibge_localities` and `ibge_urbanized_areas` are acquired and their
  manifests are in `data/manifests/acquire/`.

## The rule (checked on the real data, 2026-11-02)

1. **Urban clusters.** Take the urbanized-area polygons whose `Tipo` is not
   `Loteamento vazio` (empty subdivisions). Merge polygons within about 100 m
   of each other into clusters (buffer each by 0.001 degrees, union).
2. **Seat cluster.** For each municipality, the seat cluster is the cluster
   containing its `Cidade` locality point (9 Legal Amazon municipalities have
   two such points: either counts). 4 municipalities' seat points fall in no
   cluster; there, a polling place within 2 km of the seat point is `seat`.
3. **Type**, in this order:
   - inside the municipality's seat cluster: `seat`;
   - inside any other cluster: `town`;
   - otherwise, the nearest locality **of the same municipality** (by
     great-circle distance): if it is farther than 5 km, `dispersed`;
     otherwise by its `CT_LOCALIDADE`: Localidade Indígena → `indigenous`,
     Localidade Quilombola → `quilombola`, Agrovila do PA → `settlement`,
     anything else → `rural`.
4. Places without coordinates get no type and are counted.

Why clusters first: with the nearest locality alone, urban neighbourhoods
of large cities were typed `indigenous` or `quilombola` (for example Cidade
Nova and Jorge Teixeira in Manaus) because some locality point was closer
than the city's single seat point. With clusters first, municipalities with
more than 100,000 voters are 85% `seat` and 14% `town` (2024).

Real-data result for the whole Legal Amazon (use as a sanity check; the
build's own numbers will differ slightly because `polling_places` fills
missing TSE coordinates from Hidalgo):

| Type | 2008, share of places | 2024, share of places | 2024, share of eligible voters |
| --- | --- | --- | --- |
| seat | 49.9% | 47.2% | 75.5% |
| town | 28.6% | 32.9% | 19.5% |
| dispersed | 11.1% | 11.0% | 2.7% |
| rural | 8.1% | 6.5% | 1.7% |
| quilombola | 1.4% | 1.3% | 0.3% |
| indigenous | 0.8% | 1.1% | 0.3% |
| settlement | 0.1% | 0.1% | 0.0% |

`indigenous`, `quilombola` and `settlement` here mean "outside urban areas
and nearest to such a locality". They are not constituency types yet; those
will come from FUNAI and INCRA polygons in a later task.

## In scope

- `src/terrain/builds/polling_place_types.py` and
  `pipeline/build/polling_place_types.py`, following `pipeline/README.md`.
  Inputs: `data/manifests/build/polling_places.json`,
  `data/manifests/acquire/ibge_localities.json`,
  `data/manifests/acquire/ibge_urbanized_areas.json` and
  `data/manifests/acquire/tse_polling_places.json`.
- Read the localities GeoPackage with `sqlite3` (columns `CD_MUN`,
  `CT_LOCALIDADE`, `LAT_LOCALIDADE`, `LONG_LOCALIDADE`), Legal Amazon
  municipalities only. Read the urbanized-areas shapefile from its zip with
  `pyshp`, keeping only polygons whose bounding box meets the Legal Amazon
  box (longitude -74 to -43, latitude -18.5 to 5.5).
- Eligible voters per polling place for 2012-2024: the sum of
  `QT_ELEITOR_SECAO` over round-1 rows of the TSE polling-place file, by
  (`CD_MUNICIPIO`, `NR_ZONA`, `NR_LOCAL_VOTACAO`). Null for 2008 (no TSE file).
- Output `data/derived/polling_place_types/<hash>/polling_place_types_<year>.parquet`
  for 2008, 2012, 2016, 2020, 2024: the `polling_places` key (`ano`,
  `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), `place_type`,
  `seat_km` (distance to the nearest seat point), `nearest_locality_km`,
  `nearest_locality_category`, `eligible_voters`.
- Notes per year: counts and shares by `place_type`, places without
  coordinates, municipalities whose seat is in no cluster.
- Checks the build enforces: one row per `polling_places` row; every row with
  coordinates has a `place_type`; every Legal Amazon municipality in
  `polling_places` has at least one locality and one seat point.
- `data/contracts/polling_place_types.md` and
  `tests/test_build_polling_place_types.py`.

Expected files (four): `src/terrain/builds/polling_place_types.py`,
`pipeline/build/polling_place_types.py`,
`data/contracts/polling_place_types.md`,
`tests/test_build_polling_place_types.py`. The catalog entry
`polling_place_types` already exists; do not change `data/catalog.yaml`.

Follow AGENTS.md: write every output locally and upload only after every
check passes; hash this build's code and every data-handling `terrain`
module it imports, with input SHA-256s sorted; deterministic tests (fixed
zip timestamps); explicit encodings.

## Out of scope

- FUNAI territories, INCRA settlements, the 2005 and 2019 urbanized-area
  editions (robustness), strongholds and the census.
- `pyproject.toml`, `uv.lock`, workflows, `data/catalog.yaml`,
  `data/manifests/`, `data/fixtures/`, `data/reference/`.

## Done when

1. Built from the fixtures (localities CSV written to an SQLite table
   `BR_localidades_2022`; urbanized-area GeoJSON written to a zipped
   shapefile with pyshp), the 2024 fixture's 18 polling places are 5 `seat`,
   3 `town`, 1 `rural`, 9 `dispersed`, and the 2008 stations of town 04367
   are 9 `seat`, 1 `rural`, 4 `dispersed`.
2. A test with a `Loteamento vazio` polygon around a point shows the point is
   not urban.
3. A test with a seat point in no cluster shows a place 1 km from it is
   `seat` and one 3 km away is not.
4. A test where a quilombola locality is closer than the seat point but the
   place is inside the seat cluster shows `seat` (the Manaus case).
5. Eligible voters are the round-1 sum for 2024 fixture places, and null for
   2008.
6. The one-row-per-place, type-present and locality-coverage checks each raise
   on broken input.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
