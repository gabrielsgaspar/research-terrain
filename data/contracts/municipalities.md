# municipalities

One row per IBGE municipality (DTB 2024), with its TSE code, both names and a
Legal Amazon flag. Built by `src/terrain/builds/municipalities.py`; written to
`data/derived/municipalities/<hash>/`, where `<hash>` is `content_hash` of the
input SHA-256s, `data/reference/tse_ibge_name_variants.yaml` and the build code.
The folder holds two files: `municipalities.parquet` and `legal_amazon.csv`.

## Sources

- IBGE DTB 2024 (`DTB_2024.zip`, member `*MUNICIPIOS.ods`): the municipalities and
  their names. The header row is found by the cell `Código Município Completo`.
- Legal Amazon list 2024 (`Municipios_da_Amazonia_Legal_2024.ods`, first sheet,
  header `CD_MUN`): the flag.
- Hidalgo geocoded polling stations (v0.16, `geocoded_polling_stations.csv.gz`):
  the TSE-IBGE pairs, from `cd_localidade_tse` (padded to 5 digits) and
  `cod_localidade_ibge`. Distinct pairs only.
- The built `tse_candidates` table: only `ano_eleicao`, `sg_ue`, `sg_uf` and
  `nm_ue` are read. The TSE name of a municipality is its name in its latest
  election year. Values of `sg_ue` that are not five digits are ignored and
  counted in the manifest `notes`.
- `data/reference/tse_ibge_name_variants.yaml`: reviewed name exceptions.

## Columns of `municipalities.parquet`

Sorted by `cd_ibge`.

| Column | Type | Meaning |
| --- | --- | --- |
| `cd_ibge` | text | 7-digit IBGE code; unique |
| `cd_tse` | text | 5-digit TSE code, zero-padded; null if no pair |
| `uf` | text | state letters, from the first two digits of `cd_ibge` |
| `name_ibge` | text | `Nome_Município` in DTB 2024 |
| `name_tse` | text | latest-year `nm_ue`; null if the code has no name in the candidates |
| `legal_amazon` | bool | in the Legal Amazon list |
| `name_check` | text | `exact`, `variant`, `unchecked`, or null when `cd_tse` is null |

Names are compared after upper-casing, removing accents, and treating
apostrophes and hyphens as spaces. `exact` means they match; `variant` means they
do not but the pair is listed in the variants file with the same two codes;
`unchecked` means the TSE code never appears in the candidates, so there is no
TSE name to compare (for example Brasília, which has no municipal election).

## Columns of `legal_amazon.csv`

Exactly `code_ibge,uf`, one row per Legal Amazon municipality, sorted by code,
LF line endings. It is the input to `scripts/seal_split.py` and is read by
`terrain.split.read_municipalities`.

## Checks the build enforces

Each raises `BuildError` before anything is written.

- The pairs are one-to-one: no TSE code has two IBGE codes and no IBGE code two
  TSE codes.
- Every IBGE code in the pairs is in DTB 2024.
- Every TSE code in the candidates has a pair.
- Every Legal Amazon code is in DTB 2024, and its state letters match its code.
- Every name mismatch is a listed variant with the same TSE and IBGE codes.
- DTB and Legal Amazon codes are 7 digits and unique; each downloaded file matches
  the SHA-256 in its manifest.

On the real data the build should find 5,571 municipalities, 773 in the Legal
Amazon, and exactly the 14 listed variants. The tests cannot check these counts;
the manifest `notes` report them.
