# school_polling_match

For each polling place, the INEP school it most likely is, with a confidence level.
One Parquet per election year: `school_polling_match_2008.parquet`, `_2012`, `_2016`,
`_2020` and `_2024`. Built by `src/terrain/builds/school_polling_match.py`; written to
`data/derived/school_polling_match/<hash>/`, where `<hash>` is `content_hash` of the
sorted input SHA-256s, the years and the build code. The build imports no other
data-handling `terrain` module. Campaign 0006, step s9; idea 0006, decision 0011.

Matching is not an outcome (decision 0003), so the table holds both halves of the
split sample. It reads no facility field and stores no name or address.

## Sources

- The built `polling_places` (`polling_places_<year>.parquet`): the key,
  `nm_local_votacao`, `ds_endereco`, `nr_cep`, `lat` and `long`. The output has
  exactly its rows.
- `inep_school_catalogue` (`inep_school_catalogue.parquet`, one year, 2024, used for
  every election year): `id_escola`, `nome_escola`, `id_municipio`, `rede`,
  `endereco`, `numero`, `cep`, `latitude` and `longitude`.

## Columns

One row per (`ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), sorted by
that key.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao` | | the `polling_places` key, with the same types |
| `id_escola` | text | INEP code of the best school; null when `confidence` is `none` |
| `rede` | text | administrative dependency of that school, from the catalogue |
| `confidence` | text | `high`, `medium`, `low` or `none` |
| `name_sim` | float | name similarity of the best school; null when `none` |
| `addr_sim` | float | address similarity of the best school; null when `none` |
| `cep_equal` | bool | both postcodes present and equal; null when `none` |
| `dist_km` | float | great-circle distance to the best school; null without both coordinates, or when `none` |
| `n_candidates` | int | schools in the municipality with `name_sim` at least 0.60 (0 when `none`) |

## The rules

Fixed before any real match is run. Changing them needs a new task.

1. Normalising. Upper case, accents removed (NFKD), every character that is not a
   letter or digit becomes a space, single spaces. For names, also drop every
   one-letter token and: ESCOLA ESC EMEF EMEI EMEB EMEIEF EEEF EEEFM EE EM EEM EF
   MUNICIPAL MUN ESTADUAL EST COLEGIO COL UNIDADE ESCOLAR UE CENTRO EDUCACIONAL CE
   INSTITUTO DE DA DO DAS DOS ENSINO FUNDAMENTAL MEDIO INFANTIL BASICA PROF PROFA
   PROFESSOR PROFESSORA DR DRA DONA DOM. An address is `endereco` plus `numero`
   (school) or `ds_endereco` (polling place), normalised with no tokens dropped.
2. Pairs. A polling place is compared only with schools whose `id_municipio` equals
   its `cd_ibge`.
3. Scores. `name_sim` and `addr_sim` are `difflib.SequenceMatcher(None, a, b).ratio()`
   of the normalised texts (a is the school's, b the polling place's); 0 when either
   is empty. `cep_equal`: both postcodes present and equal. `dist_km`: great-circle
   (haversine) distance between the coordinates, when both exist. `near`: `dist_km`
   at most 1. `addr_sim` and `dist_km` are computed only where `name_sim` is at least
   0.60.
4. Confidence of a pair.
   - `high`: `name_sim` at least 0.90 and (`cep_equal` or `addr_sim` at least 0.80 or
     `near`);
   - `medium`: not high, and either `name_sim` at least 0.90, or `name_sim` at least
     0.75 and (`cep_equal` or `near`);
   - `low`: neither, and `name_sim` at least 0.60;
   - otherwise no match.
5. Best school. Ordered by confidence (high, medium, low), then larger `name_sim`,
   then larger `addr_sim`, then smaller `dist_km` (null last), then smaller
   `id_escola`. A place with no pair at `low` or better keeps one row with null
   school fields and `confidence` `none`.

## Checks

The build raises `BuildError` and uploads nothing when:

- the key is repeated in the input or in the output;
- the output does not have exactly one row for each `polling_places` row;
- `id_escola` is missing or repeated in the catalogue.

## Notes in the manifest

Per year: places, the share at each confidence level, the same shares by state
(state is the first two digits of `cd_ibge`, the IBGE state code), the high+medium
match rate by state, and the number of places that share their school with another
place (`places_sharing_a_school`). Values only.
