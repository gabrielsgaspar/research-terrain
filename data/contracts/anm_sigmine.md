# anm_sigmine

Every **active** mining process in ANM's SIGMINE ArcGIS feature service (layer
0, "Processos minerários ativos"), with polygons. One Parquet,
`sigmine_active.parquet`, in a new dated folder under the entry's `gcs:` in
`data/catalog.yaml`. Acquired by `pipeline/acquire/anm_sigmine.py` (logic in
`src/terrain/anm.py`). Campaign 0007, step s1; idea 0007.

## Source

The layer URL, fields and paging settings are in the entry's `arcgis:` block.
Active processes only: the layer has no inactive processes, so titles that
lapsed before the run are missing.

**No holder names.** The holder field `NOME` (some holders are people) is never
requested and never stored. `terrain.anm` refuses any requested field that
starts with `NOME`.

## Columns

One row per process (`objectid` is unique). Names are the service's fields in
lower case. Types are those of the service's answer.

| Column | Type | Meaning |
| --- | --- | --- |
| `objectid` | Int64 | the service's row key |
| `processo` | Utf8 | process number, as text |
| `numero` | as received | number part of the process number |
| `ano` | Int64 | year in the process number (not a full request date); null if missing |
| `fase` | Utf8 | legal phase of the process |
| `subs` | Utf8 | substance |
| `uso` | Utf8 | intended use |
| `area_ha` | Float64 | area in hectares, as given by ANM |
| `uf` | Utf8 | state |
| `geometry_wkb` | Binary | WKB of the polygon or multipolygon, SIRGAS 2000 degrees (EPSG:4674); null if the service sent none |

Invalid geometries are kept as given and counted in the manifest notes. The
build repairs them.

## Values used downstream

- Gold is `subs` in OURO, MINÉRIO DE OURO, OURO NATIVO. OURO PIGMENTO is
  orpiment, not gold.
- Garimpo permits are `fase` LAVRA GARIMPEIRA and REQUERIMENTO DE LAVRA
  GARIMPEIRA.

## Checks and manifest

The run stops, and uploads nothing, if the count of records differs from the
service's count after a second paging, if `objectid` repeats, if a feature
carries a field that was not requested, or if there are fewer records than
`min_records`. The manifest notes list: records; records by `uf`; gold
records; gold records with `ano` < 2000; records without `ano`; invalid
geometries; records without geometry; the SHA-256 of the pinned intermediate
certificate. A run with the same record count and the same counts by `uf` as
the newest folder is `unchanged` and uploads nothing.
