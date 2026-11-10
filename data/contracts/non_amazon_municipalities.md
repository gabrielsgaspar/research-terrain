# non_amazon_municipalities

The municipalities outside the Legal Amazon, each with its state and
population: the input to `scripts/seal_split.py --non-amazon`
(`research/decisions/0011-national-scope.md`). Built by
`src/terrain/builds/non_amazon_municipalities.py`; written to
`data/derived/non_amazon_municipalities/<hash>/non_amazon.csv`, where `<hash>`
is `content_hash` of the input SHA-256s and the code of the build,
`terrain.ods` and `terrain.builds.municipalities`.

## Sources

- The built `municipalities` table (`municipalities.parquet`): only `cd_ibge`,
  `uf` and `legal_amazon` are read. A municipality is outside the Legal Amazon
  when `legal_amazon` is false.
- IBGE, Censo Demográfico 2022, `CD2022_Populacao_2010_Compatibilizada_20231222.ods`
  (`ibge_population_2022`), first sheet. The header row is the one holding
  `COD. MUNIC`. The code is `COD. UF` (2 digits) followed by `COD. MUNIC`
  (5 digits); rows without both (titles, notes) are skipped. The population is
  the column whose header starts with `População 2010 (Alterações de Limites
  até 2022)`: the 2010 census count on 2022 boundaries. Spaces (any kind) and
  dots in it are thousands separators.

## Columns of `non_amazon.csv`

Exactly `code_ibge,uf,population`, one row per municipality outside the Legal
Amazon, sorted by code, LF line endings. It is read by
`terrain.split.read_population_municipalities`.

| Column | Type | Meaning |
| --- | --- | --- |
| `code_ibge` | text | 7-digit IBGE code; unique |
| `uf` | text | state letters, from the `municipalities` table |
| `population` | whole number > 0 | 2010 population on 2022 boundaries |

## Checks the build enforces

Each raises `BuildError` before anything is written.

- The population table has the header and exactly one population column.
- Its codes are unique, each listed under the state its first two digits
  name, each with a positive whole-number population.
- Every code in the population table is a municipality in the table.
- Every municipality outside the Legal Amazon has a population, and its state
  agrees in both inputs.
- Each input file matches the SHA-256 in its manifest.

Legal Amazon municipalities with no population are allowed and listed in the
manifest `notes` (expected: Boa Esperança do Norte, 5101837, created after the
census). On the real data the build should find 4,798 municipalities; the
tests cannot check this count, the `notes` report it with the count per state.
