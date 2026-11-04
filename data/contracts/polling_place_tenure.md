# polling_place_tenure

For each Legal Amazon polling place, the distance in km to the nearest indigenous
land, agrarian-reform settlement and undesignated public forest. One Parquet per
election year: `polling_place_tenure_2008.parquet`, `_2012`, `_2016`, `_2020` and
`_2024`. Built by `src/terrain/builds/polling_place_tenure.py`; written to
`data/derived/polling_place_tenure/<hash>/`, where `<hash>` is `content_hash` of the
sorted input SHA-256s, the years and the build code. The build imports no other
data-handling `terrain` module.

## Sources

- The built `polling_places` (`polling_places_<year>.parquet`): the key, `lat` and
  `long`. The output has exactly its rows.
- The Forest Service's public-forest register, CNFP (`cnfp_public_forests`): the
  editions `CNFP_2008.zip`, `CNFP_2012.zip`, `CNFP_2016.zip`, `CNFP_2020.zip`,
  `CNFP_2024_retificado.zip` and `CNFP_2025.zip`. Each is read with `pyshp`, one
  edition at a time (unpacked, read, deleted). Text is UTF-8 with bad bytes
  replaced, because some fields are cut mid-character. Empty shapes are skipped;
  kept are polygons whose bounding box meets longitude -74 to -43 and latitude
  -18.5 to 5.5.

## Columns

One row per (`ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), sorted by
that key.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao` | | the `polling_places` key, with the same types |
| `dist_indigenous_km` | float | distance to the nearest indigenous land; 0 inside |
| `dist_settlement_km` | float | distance to the nearest settlement created by the election year; 0 inside |
| `dist_undesignated_km` | float | distance to the nearest undesignated public forest; 0 inside |

A place without coordinates has null distances.

## The rules

1. Groups. Split `categoria` on `/` or `;` and strip each part. Indigenous: a part
   equals `TI` or contains `Terra Ind`. Settlement: the first part is one of PA,
   PA., PAE, PDS, PAF, PAC, PCA, PIC, PAD, PE, PAM, PAR, PRB, PFP, PCT.
   Undesignated: `tipo` (2008: `tipo_flor`) equals `TIPO B`. A polygon can be in
   more than one group. Quilombola territories (`TRQ`) and protected areas are not
   used.
2. Layers for election year y. Indigenous and undesignated: the edition of year y
   (2024: the retificado file). Settlements: the 2025 edition, kept when the
   creation year (the first 4-digit year from 1800 to 2099 in `anocriacao`, which
   mixes `dd/mm/yyyy`, `dd-mm-yyyy` and compound values) is at most y. Earlier
   editions lack conventional settlements (PA), so they are not used for this
   layer. A settlement with no readable year is left out and counted in the notes.
3. Distance. Polygons and points are projected to km with x = longitude * 111.32 *
   cos(latitude) and y = latitude * 110.574, accurate within about 1% at these
   distances (no new dependency). The distance is to the nearest polygon of the
   layer, by a shapely `STRtree`; inside a polygon it is 0.

## Checks

The build raises `BuildError` and uploads nothing when:

- the output does not have exactly one row for each `polling_places` row;
- any layer is empty in any year;
- any distance is negative.

## Notes in the manifest

Per year: places, places without coordinates, polygons per layer, settlements
without a creation year, and the share of places with coordinates within 0, 2 and
5 km of each layer.

## Caveat: the 2008 undesignated layer

The 2008 edition records far less undesignated land than later ones (496 polygons
in the box, against 10,548 in 2012). That is a change in the register's coverage,
not in the land. Do not read the rise in undesignated land near polling places
between 2008 and 2012 as a real change.
