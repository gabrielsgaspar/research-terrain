# place_outcomes

The outcomes of idea 0006 per polling place, election and outcome year: the facilities of
the matched school, night lights and built-up share within 1 km, and native-vegetation
share within 10 km. Written split by half
(`research/decisions/0003-confirmation-rows.md`, `research/decisions/0011-national-scope.md`):
exploration-half rows are derived data, all other rows go only to a sealed folder that no
exploration account can read. Built by `src/terrain/builds/place_outcomes.py`. Campaign 0006,
step s14; idea `research/ideas/0006-geography-of-representation.md`.

Paths come from the catalog entry `place_outcomes`:

- `data/derived/place_outcomes/<hash>/place_outcomes_E<E>_y<y>.parquet`: exploration half.
- `sealed/outcomes/place_outcomes/<hash>/place_outcomes_E<E>_y<y>.parquet`: every other row.

One file per election `E` (2008, 2012, 2016, 2020) and outcome year `y` in E-4 .. E+4 that has
a raster (VIIRS 2013-2024, MapBiomas 2004-2024), so a script can read exactly the years it
states. `<hash>` is the same for both: `content_hash` of the sorted input SHA-256s, the
SHA-256 of both exploration lists, the raster years, the elections, and the source of this
build, `terrain/grid.py`, `terrain/explore.py` and the builds `cell_outcomes`,
`cell_enforcement` and `polling_place_tenure` (their helpers pick, check and read the inputs).
If a sealed object already exists, the build stops after the sealed files uploaded so far
(create-only); a rerun needs a new hash.

## Sources

- `polling_places` (`polling_places_<E>.parquet`): the key, `lat`, `long`, `conf_dist_km`.
- `school_polling_match` (`school_polling_match_<E>.parquet`): `id_escola` and `confidence`.
- `inep_schools` (`inep_schools.parquet`): `ano`, `id_escola`, `rede`, the eight facility
  columns, `dependencia_pne` and `acessibilidade_inexistente`. Outcome data for both halves.
- `mapbiomas_coverage_national`: one GeoTIFF per year, shape `(rows, columns, 2)`, `uint16`,
  bands `urban` and `native` (shares x 10,000, as in the catalog's `groups`).
- `viirs_annual`: one GeoTIFF per year, shape `(rows, columns)`, `uint16`, `log(1 + radiance)`
  x 1,000. Both rasters are on the catalog's `grid_km`, which must be the same.
- `ibge_boundaries_2024`: `BR_Municipios_2024.zip`, read as `cell_enforcement` does.
- `data/derived/split/explore_municipalities.csv` and
  `explore_municipalities_non_amazon.csv`: the exploration municipalities.

## Columns

One row per polling place of E and year `y`, sorted by the key.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao` | | the `polling_places` key; `ano` is E |
| `y` | int | outcome year |
| `located_1km` | bool | the place has a coordinate with `conf_dist_km` at most 1 |
| `school_id` | text | `id_escola` of the match of year E at `high` or `medium` confidence; else null |
| `school_rede` | text | the school's `rede` in `inep_schools` at year E |
| `school_n_fac` | int | facilities the school has in year `y`, 0-9; null if no school, no row in `y`, or any of the nine is null |
| `lights_1km` | float | mean of the VIIRS value / 1000 over the 1 km ring; null for years without a file |
| `builtup_1km` | float | mean of `urban` / 10,000 over the 1 km ring |
| `native_10km` | float | mean of `native` / 10,000 over the 10 km ring |
| `ring_cells_1km`, `ring_cells_10km` | int | cells in the rings; null if not located |

## The rules

1. Facilities: `agua_rede_publica`, `esgoto_rede_publica`, `energia_rede_publica`,
   `internet`, `biblioteca_sala_leitura`, `laboratorio_ciencias`, `laboratorio_informatica`,
   `quadra_esportes`, and accessibility: `dependencia_pne` for `y` up to 2018,
   `1 - acessibilidade_inexistente` from 2019 (INEP changed the question in 2019).
2. Ring: a cell is in a place's ring when its centre (x + 0.5, y + 0.5, Albers km) lies within
   the radius of the place's point **and** inside the polygon of the place's own `cd_ibge`.
   A ring never reads a cell of a neighbouring municipality, which may be in the other half.
   Only places with `located_1km` get rings; the rest are null. A ring with no cell gives a
   null mean and is counted. Values are averaged as stored, so a 0 may be no data.
3. Pixel of a cell: row `y1 - 1 - y_km`, column `x_km - x0`.
4. Half: a row is in the exploration half if its `cd_ibge` is in either list. Municipalities
   in neither list go to the sealed folder.

## Checks

The build raises `BuildError` before anything is uploaded when:

- an exploration list is missing or unreadable, or a code is in both lists;
- a file's SHA-256 differs from its manifest, or a raster is not `uint16` of the grid's shape
  or has a share above its scale;
- a key repeats in `polling_places` or the match, or `(ano, id_escola)` in `inep_schools`;
- a facility column holds a value other than 0 or 1;
- a place's municipality has no polygon, or a ring cell lies outside the grid.

Error messages never hold an outcome value.

## Notes

Per election and year, exploration-half rows only: places; places with a school, by
`school_rede`; places with a school and a null `school_n_fac`; located places; located places
with an empty 1 km ring and with an empty 10 km ring. Never a pooled count, a mean or any
other statistic of an outcome.
