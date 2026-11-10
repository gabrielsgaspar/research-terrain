# cell_enforcement

IBAMA flora fines (cancelled ones excluded) and embargoes per Legal Amazon 1 km cell and
year 2000-2025 (idea `research/ideas/0005-enforcement-shielding.md`, campaign 0004 step s4),
plus a municipality-by-year table of all and located records for the coverage check.
Written split by half (`research/decisions/0001-split-sample.md`,
`research/decisions/0003-confirmation-rows.md`): exploration-half rows are derived data,
confirmation-half rows go only to a sealed folder that no exploration account can read.
Built by `src/terrain/builds/cell_enforcement.py`.

Paths come from the catalog entry `cell_enforcement`, for each year `<y>` 2000-2025:

- `data/derived/cell_enforcement/<hash>/cell_enforcement_<y>.parquet` and
  `.../muni_enforcement_<y>.parquet`: exploration half.
- `sealed/outcomes/cell_enforcement/<hash>/cell_enforcement_<y>.parquet` and
  `.../muni_enforcement_<y>.parquet`: confirmation half.

`<hash>` is the same for both: `content_hash` of the sorted input SHA-256s (the two acquire
Parquets, the boundaries zip and the `grid_cells` Parquet), the SHA-256 of the split list,
the years, and the source of `terrain/builds/cell_enforcement.py`, `terrain/grid.py`,
`terrain/ibama.py`, `terrain/builds/cell_outcomes.py` (split list, upload) and
`terrain/builds/polling_place_tenure.py` (`_file`, `_fetch`, the edition reader).

If a sealed object already exists, the build stops after the sealed files before it are
uploaded (create-only) and uploads no derived file; a rerun needs a new hash, so change an
input or the code, or ask the owner to remove the partial folder.

## Sources

- `ibama_autos` (`data/contracts/ibama_autos.md`): `fonte`, `id_auto`, `data_auto`, `ano`,
  `id_municipio`, `latitude`, `longitude`, `tipo_infracao`, `indicador_cancelado`,
  `indicador_coordenada_valida`.
- `ibama_embargos` (`data/contracts/ibama_embargos.md`): `fonte`, `id_embargo`,
  `data_embargo`, `ano`, `id_municipio`, `latitude`, `longitude`,
  `indicador_coordenada_valida`.
- `ibge_boundaries_2024`: `BR_Municipios_2024.zip`, polygons keyed by `CD_MUN`, SIRGAS 2000
  degrees, read as `grid_cells` reads it.
- `grid_cells`: `nome_1KM`, `cd_ibge`.
- `data/derived/split/explore_municipalities.csv`: the exploration municipalities (one
  column, `code_ibge`).

## Columns

`cell_enforcement_<y>`: one row per cell with at least one located action in the year; absent
cells have zero. Sorted by `cd_ibge`, `nome_1KM`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | cell, as in `grid_cells` |
| `cd_ibge` | text | its municipality |
| `ano` | int64 | year |
| `n_fines_flora` | int64 | located, uncancelled flora fines in the cell and year |
| `n_embargoes` | int64 | located embargoes in the cell and year |

`muni_enforcement_<y>`: one row per Legal Amazon municipality of the half, every municipality
present even with zeros. Sorted by `cd_ibge`.

| Column | Type | Meaning |
| --- | --- | --- |
| `cd_ibge` | text | municipality |
| `ano` | int64 | year |
| `n_fines_flora_all` | int64 | flora fines of rules 1-4, whatever their coordinates |
| `n_fines_flora_located` | int64 | the same, also meeting rule 5 |
| `n_embargoes_all` | int64 | embargoes of rules 1-4, whatever their coordinates |
| `n_embargoes_located` | int64 | the same, also meeting rule 5 |

## The rules

1. Year: the calendar year of `data_auto` or `data_embargo`; if the date is null, the stored
   `ano`. Only 2000-2025 are kept.
2. Legal Amazon: a record counts only if `id_municipio` is a 7-digit code of a `grid_cells`
   municipality. Others are dropped; this is expected (the states include parts of MA outside
   the Legal Amazon) and not an error.
3. Cancelled fines are excluded. `indicador_cancelado` is normalised (strip, casefold, accents
   removed). Cancelled: `sim`, `s`, `1`, `true`, `verdadeiro`, `cancelado`. Not cancelled:
   `nao`, `n`, `0`, `false`, `falso`, the empty string and null. Any other value stops the
   build.
4. Flora fines only: `tipo_infracao`, normalised the same way, equals `flora`. If no value
   normalises to `flora`, the build stops. Embargoes are not filtered by type.
5. Located: `latitude` and `longitude` are finite; the point lies inside or on the boundary
   (`shapely.covers`) of the `BR_Municipios_2024` polygon whose `CD_MUN` equals the record's
   `id_municipio`; and the 1 km cell containing the point (Albers km of `terrain.grid`, floor
   of x and y, named `1KME<x>N<y>`) is a `grid_cells` cell whose `cd_ibge` equals
   `id_municipio`. The check is ours and the same for both sources;
   `indicador_coordenada_valida` never decides.
6. Half: a row is in the exploration half if its `cd_ibge` is in the split list, else in the
   confirmation half. A located record's cell has the record's own municipality, so the cell
   table and the municipality table split the same way.

## Checks

The build raises `BuildError` before anything is uploaded when:

- a file's SHA-256 differs from its manifest, or an IBAMA input lacks a column it uses;
- the split list is malformed;
- `grid_cells` has a duplicate cell or a `cd_ibge` that is not 7 digits;
- a `grid_cells` municipality has no polygon in the boundaries;
- `indicador_cancelado` holds a value outside rule 3's two sets;
- no `tipo_infracao` value is `flora`;
- for a year and half: the municipality table lacks a municipality of the half; a cell row is
  outside the half, repeats, or has another year; located exceeds all; or the cell counts do
  not add up to the municipality table's located counts.

## Upload and manifest

All files are written locally and checked first. Sealed files are uploaded first, create-only
(the build account cannot read `sealed/`; an existing object stops the build), then the derived
files, then the manifest. `files` lists the derived files; `sealed_files` lists the sealed files
(path, SHA-256, bytes). A run whose derived manifest exists is `unchanged`.

## Notes

The notes and every exception message give counts for the exploration half only: a pooled count
minus the exploration count would reveal the confirmation half's enforcement. The notes hold:

- the `fonte` of each input;
- per input, the records of the exploration half dropped because they have no date and no year,
  or a year outside 2000-2025; and per year, those with no coordinates, outside their own
  polygon, or in a cell of another municipality or not in the grid;
- per input, the records whose municipality is not in the Legal Amazon. They belong to neither
  half, so this count reveals nothing about the confirmation half;
- when an input's `fonte` is `basedosdados`, one line for the exploration half, records with
  coordinates only, from the `basedosdados` inputs together: how often rule 5 agrees with
  `indicador_coordenada_valida` (normalised as in rule 3: `sim`, `s`, `1`, `true` valid;
  `nao`, `n`, `0`, `false` not valid; null and other values not comparable), as the shares and
  counts agree, disagree and not comparable. It is not a kill rule.
