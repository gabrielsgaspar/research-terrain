# polling_place_types

Each Legal Amazon polling place typed as `seat`, `town`, `indigenous`,
`quilombola`, `settlement`, `rural` or `dispersed`, with its eligible voters. One
Parquet per election year: `polling_place_types_2008.parquet`, `_2012`, `_2016`,
`_2020` and `_2024`. Built by `src/terrain/builds/polling_place_types.py`; written
to `data/derived/polling_place_types/<hash>/`, where `<hash>` is `content_hash` of
the sorted input SHA-256s, the years and the build code. The build imports no other
data-handling `terrain` module.

## Sources

- The built `polling_places` (`polling_places_<year>.parquet`): the key, `lat` and
  `long`. The output has exactly its rows.
- IBGE Localidades do Brasil 2022 (`Localidades_Brasil_gpkg.zip`): the single
  `.gpkg` member, table `BR_localidades_2022`, read with `sqlite3`. Only
  `CD_MUN`, `CT_LOCALIDADE`, `LAT_LOCALIDADE` and `LONG_LOCALIDADE`, for the
  municipalities in `polling_places`. A locality without a coordinate is dropped.
  The seat points are the rows with `CT_LOCALIDADE = Cidade`.
- IBGE Areas Urbanizadas 2022 (`AreasUrbanizadas2022_Brasil.zip`): the single
  `.shp` member, read with `pyshp` (DBF encoding from the `.cpg` member, else
  UTF-8). Kept: polygons whose bounding box meets longitude -74 to -43 and
  latitude -18.5 to 5.5, and whose `Tipo` is not `Loteamento vazio`.
- TSE polling places (`eleitorado_local_votacao_<year>.zip`, 2012 onward). Only
  `aa_eleicao`, `nr_turno`, `cd_municipio`, `nr_zona`, `nr_local_votacao` and
  `qt_eleitor_secao` are read. There is no file for 2008.

## Columns

One row per (`ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), sorted by
that key.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao` | | the `polling_places` key |
| `place_type` | text | see the rule; null when the place has no coordinate |
| `seat_km` | float | distance to the nearest seat point of its municipality |
| `nearest_locality_km` | float | distance to the nearest locality of its municipality |
| `nearest_locality_category` | text | that locality's `CT_LOCALIDADE` |
| `eligible_voters` | int | round-1 `QT_ELEITOR_SECAO` summed over the place; null in 2008 and where the TSE file has no such place |

Distances are great-circle (haversine, Earth radius 6371.0088 km).

## The rule

1. Buffer each kept urbanized-area polygon by 0.001 degrees (about 100 m), take
   the union and split it into clusters.
2. A municipality's seat cluster is a cluster containing one of its `Cidade`
   points (either counts when it has two). If none of its seat points is in a
   cluster, a place within 2 km of a seat point is `seat`.
3. In this order: inside the seat cluster, `seat`; inside any other cluster,
   `town`; otherwise the nearest locality of the same municipality decides. Over
   5 km away, or no locality: `dispersed`. Else by `CT_LOCALIDADE`:
   `Localidade Indígena` is `indigenous`, `Localidade Quilombola` is
   `quilombola`, `Agrovila do PA` is `settlement`, anything else is `rural`.
4. A place without coordinates has no type and is counted.

`indigenous`, `quilombola` and `settlement` mean "outside urban areas and nearest
to such a locality". They are not constituency types.

## Eligible voters

The sum of `QT_ELEITOR_SECAO` over round-1 rows of the year's election, grouped by
(`cd_municipio`, `nr_zona`, `nr_local_votacao`) and joined on (`sg_ue`, `nr_zona`,
`nr_local_votacao`). A count that is not an integer stops the build.

## Checks the build enforces

Each raises `BuildError` before anything is uploaded.

- One output row per `polling_places` row (same key set, each key once).
- Every row with coordinates has a `place_type`.
- Every municipality in `polling_places` has at least one locality and one seat
  point.
- Each downloaded file matches the SHA-256 in its manifest.

## Notes

The manifest `notes` give, per year: rows, places without coordinates, the count
and share of each type, and the municipalities whose seat is in no cluster.
