# Task: build `grid_cells`, the Legal Amazon's 1 km census cells with population and land tenure

## Goal

One row per 1 km IBGE grid cell in the Legal Amazon: where it is, which
municipality it belongs to, how many people lived in it in 2010 and 2022,
and how much of it lies inside indigenous land, settlements and
undesignated forest in each election year. It is the base of the exposure
measure (decision 0004, to come) and of figures 3-5.

## Idea

`research/ideas/0001-electoral-strongholds.md`. Read first: the catalog
entries `ibge_grid_2022`, `ibge_grid_2010`, `ibge_boundaries_2024`,
`cnfp_public_forests`, `municipalities` and `grid_cells`;
`data/fixtures/ibge/README.md` ("Census grid and municipal boundaries");
the two newest entries of `research/lessons.md`; and
`src/terrain/builds/polling_place_tenure.py`, whose layer rules this build
reuses.

## Prerequisites

Merged manifests `data/manifests/acquire/ibge_grid_2022.json`,
`ibge_grid_2010.json`, `ibge_boundaries_2024.json`,
`cnfp_public_forests.json`, and `data/manifests/build/municipalities.json`.

## The rules (checked on the real files, 2026-11-04)

1. **Projection.** IBGE's Albers equal-area:
   `+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000
   +y_0=10000000 +ellps=GRS80 +units=m +no_defs`, with pyproj. A 1 km name
   `1KME<e>N<n>` is the cell whose **lower-left** corner is at easting `e`
   km and northing `n` km (`1KME4717N11118`: x 4717, y 11118). Its centre is
   (`e` + 0.5, `n` + 0.5) km; its square is `box(e, n, e + 1, n + 1)` in km.
   Every fixture cell's polygon matches its name this way within 5 m.
2. **2022 cells.** Read only the `.dbf` of `BR1KM.shp` in
   `BR1KM_20251002.zip` (fields `nome_1KM`, `TOTAL`, `TOTAL_DOM`; 8,860,553
   records, about 30 s with `pyshp` `iterRecords(fields=...)`). Polygons are
   not needed: the cell comes from its name. A name that does not parse
   stops the build.
3. **Municipality.** A cell belongs to the Legal Amazon municipality (the
   `legal_amazon` rows of the built `municipalities` table, 773) whose
   polygon in `BR_Municipios_2024.zip` (`CD_MUN`) contains the cell's centre
   in SIRGAS 2000 degrees. Test only centres inside longitude -74.5 to -43,
   latitude -19 to 6, with a shapely `STRtree` (`query(points,
   predicate="within")`). Cells whose centre is in no Legal Amazon
   municipality are dropped. Real result: **5,029,081 cells**, each in exactly
   one municipality, every one of the 773 municipalities with at least 81
   cells; 92.6% have no one in 2022. The query takes about 6 minutes.
4. **2010 population.** Read the `.dbf` of each of the 38 tiles (`ID_UNICO`,
   `nome_1KM`, `POP`, `DOM_OCU`; 8,834,513 records in all) and sum `POP` and
   `DOM_OCU` by `nome_1KM`, whether the row is a 1 km cell or a 200 m cell
   (no parent has both kinds of row). Never parse `ID_UNICO`. Every kept cell
   has a 2010 parent on the real files; a kept cell without one stops the
   build.
5. **Tenure shares.** For each election year `y` in 2008, 2012, 2016, 2020,
   2024, the layers of `polling_place_tenure` (same functions:
   `extract_edition`, `read_cnfp`, `is_indigenous`, `is_settlement`,
   `is_undesignated`, `creation_year`): indigenous and undesignated from
   edition `y` (2024: `CNFP_2024_retificado.zip`), settlements from
   `CNFP_2025.zip` created by `y`. For each layer and year:
   - project the polygons to the Albers km of rule 1
     (`shapely.transform` with the pyproj transformer, divided by 1000) and
     take their union (`shapely.union_all`), so overlaps count once;
   - for each part of the union, the candidate cells are the integer cells of
     its bounding box; a cell's share is the area of its square inside the
     part (1 if the part contains the square, else the intersection area;
     use `shapely.prepare`), summed over parts;
   - keep shares of kept cells only; 0 for every other kept cell.

   Columns `share_<layer>_<y>`, 15 in all.

   - **Repair first:** apply `shapely.make_valid` to the projected polygons
     before the union, and keep only the polygonal parts of the result. On
     the real files 5 of 1,205 indigenous, 725 of 3,663 settlement and 380 of
     2,832 undesignated 2024 polygons are invalid after projection, and
     `union_all` fails without the repair (`TopologyException`).

   Real result for 2024, before restricting to kept cells: indigenous union
   1,156,181 km² in 527 parts, 1,195,995 cells touched; settlements 194,795
   km² in 29,937 parts, 325,318 cells; undesignated 523,419 km² in 46,791
   parts, 764,015 cells. The sum of shares equals the union's area, and no
   share exceeds 1. The three layers of one year take about 10 minutes, so
   five years take about an hour, inside the pipeline's 180-minute limit.
6. **Order and types.** Sorted by `cd_ibge`, `y_km`, `x_km`. Populations and
   households are integers.

## Output

`<derived>/<hash>/grid_cells.parquet`, where `<hash>` is `content_hash` of
the input SHA-256s (sorted), the years, and the source of
`terrain/grid.py`, `terrain/builds/grid_cells.py` and
`terrain/builds/polling_place_tenure.py`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | IBGE cell name; unique |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `lon`, `lat` | float | centre, SIRGAS 2000 degrees |
| `cd_ibge` | text | municipality containing the centre |
| `pop_2010`, `dom_2010` | int | 2010 grid people and occupied households |
| `pop_2022`, `dom_2022` | int | 2022 grid people (`TOTAL`) and occupied households (`TOTAL_DOM`) |
| `share_indigenous_<y>`, `share_settlement_<y>`, `share_undesignated_<y>` | float | share of the cell in the layer of year `y`, 0 to 1 |

## Checks (each raises `BuildError` before anything is written)

- Names are unique and all parse; each kept cell has one municipality.
- Every Legal Amazon municipality has at least one cell.
- Every kept cell has a 2010 parent.
- Every share is in [0, 1 + 1e-9] (store it clipped to 1).
- For each layer and year, the sum of shares (km²) is at most the area of
  the projected union (km²) × 1.001.
- Each layer of each year is non-empty.

Manifest notes: per state (first two digits of `cd_ibge`), cells, `pop_2010`,
`pop_2022`, share of cells with `pop_2022` = 0; and per layer and year, cells
with a share above 0 and the sum of shares in km².

## In scope

- `src/terrain/grid.py`: the projection string, `parse_name` (name to
  `x_km`, `y_km`), `centre_lonlat` (vectorised, km to degrees) and
  `to_albers_km` (shapely geometries in degrees to Albers km). Small and
  reused by later tasks (exposure, figures).
- `src/terrain/builds/grid_cells.py`: the build, in the style of
  `polling_place_tenure.py` (check each input's SHA-256, build and check
  everything locally, upload after every check passes, `unchanged` when the
  output path has a manifest, a `years` parameter for tests).
- `pipeline/build/grid_cells.py`: thin script reading the five manifests.
- `data/contracts/grid_cells.md`: the contract (columns, rules, checks).
- `tests/test_grid.py` and `tests/test_build_grid_cells.py`.

Expected files (six): `src/terrain/grid.py`,
`src/terrain/builds/grid_cells.py`, `pipeline/build/grid_cells.py`,
`data/contracts/grid_cells.md`, `tests/test_grid.py`,
`tests/test_build_grid_cells.py`.

## Out of scope

`data/catalog.yaml`, `data/manifests/`, `data/fixtures/`, workflows,
`pyproject.toml`, `uv.lock`; exposure (decision 0004 and a later task).

## Done when

1. `parse_name("1KME4717N11118") == (4717, 11118)`; a malformed name raises.
   `centre_lonlat` of every cell in `data/fixtures/ibge/BR1KM_2022_sample.geojson`
   lies inside that cell's polygon.
2. With a `MemoryStore` holding zips written in the test with pyshp from the
   fixtures (`BR1KM_2022_sample.geojson` as `BR1KM.shp` in
   `BR1KM_20251002.zip`; `grade_2010_sample.geojson` as one tile,
   `grade_id73.zip`; `BR_Municipios_2024_sample.geojson` as
   `BR_Municipios_2024.shp` in `BR_Municipios_2024.zip`; CNFP zips from
   `data/fixtures/cnfp/`, each with one synthetic `TI` polygon added as in
   `tests/test_build_polling_place_tenure.py`, since the fixtures hold no
   indigenous land), a municipalities Parquet with both towns in the
   Legal Amazon, and `years=(2008, 2024)`: the output has **240 cells** (165 in
   1507706, 75 in 1507979; the other 23 fixture cells have centres outside
   both simplified outlines), `pop_2022` sums to 15,117 and 16,989,
   `dom_2022` to 3,917 and 4,451, `pop_2010` to 12,266 and 13,804, and
   `dom_2010` to 2,625 and 2,896.
3. Shares on synthetic polygons: a polygon covering a cell exactly gives 1; one
   covering the left half gives 0.5; two overlapping polygons each covering
   the whole cell give 1, not 2; a cell the layer misses gives 0; a
   settlement created after the year is not counted.
4. Each check fails on its own broken input (a malformed name, a kept cell
   without a 2010 parent, a Legal Amazon municipality without cells, an
   empty layer), raising `BuildError` with the store unchanged.
5. A second run is `unchanged` with nothing written; changing the source of
   `terrain/grid.py` or `terrain/builds/polling_place_tenure.py` changes the
   output path; an input whose SHA-256 differs from its manifest raises.
6. No test uses the network or GCS; `uv run ruff check .`, `uv run ruff
   format --check .` and `uv run pytest` pass.
