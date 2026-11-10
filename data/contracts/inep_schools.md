# inep_schools

School facilities by school and year, 2007-2024, for all 26 states and the
Federal District. One Parquet, `inep_schools.parquet`, in a new dated folder
under the entry's `gcs:` in `data/catalog.yaml`. Acquired by
`pipeline/acquire/inep_schools.py` (logic in `src/terrain/inep.py` and
`src/terrain/bigquery.py`). Campaign 0006, step s6; idea 0006, decision 0011.

This is outcome data for both halves of the sample. It stays in raw, which no
exploration account reads; only `place_outcomes` (step s14) reads it.

## Source

INEP, Censo Escolar, via Base dos Dados on BigQuery
(`basedosdados.br_inep_censo_escolar.escola`). Only the columns listed below
are selected. Telephone numbers and every column that starts with `nome` are
refused by `terrain.bigquery`. `(ano, id_escola)` is unique at the source.

## Columns

In this order, with polars types. Values are stored as received: no recoding,
nulls kept.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano` | Int64 | census year |
| `id_escola` | Utf8 | INEP school code |
| `id_municipio` | Utf8 | 7-digit IBGE code |
| `sigla_uf` | Utf8 | state |
| `rede` | Utf8 | "1" federal, "2" state, "3" municipal, "4" private |
| `tipo_localizacao` | Utf8 | "1" urban, "2" rural |
| `agua_rede_publica` | Int8 | public water network, 0 no, 1 yes |
| `esgoto_rede_publica` | Int8 | public sewage network |
| `energia_rede_publica` | Int8 | public electricity network |
| `internet` | Int8 | internet |
| `biblioteca_sala_leitura` | Int8 | library or reading room |
| `laboratorio_ciencias` | Int8 | science laboratory |
| `laboratorio_informatica` | Int8 | computer laboratory |
| `quadra_esportes` | Int8 | sports court |
| `dependencia_pne` | Int8 | accessible facilities; collected 2007-2018 only |
| `acessibilidade_inexistente` | Int8 | 1 = none of the accessibility items; collected 2019-2024 only |

The other facility columns are collected 2007-2024. INEP changed its
questionnaire in 2019, so `dependencia_pne` and `acessibilidade_inexistente`
do not cover the same years. Rows are sorted by `ano`, `id_escola`. The file
must stay under 2 GB.

## Manifest

`stage: acquire`; `files`: the Parquet with SHA-256 and bytes.

- `sources`: `fonte: basedosdados`, `url`, `table`, `query` (the exact text
  sent), `location`, `rows`, `total_bytes_processed`, `job_id`.
- `notes`, values only: the row count; rows per year; for each facility
  column, the years in which it is entirely null; the sorted distinct values
  of `rede` and `tipo_localizacao`.
- Unchanged check: the summary query is `COUNT(*)` only. A run whose latest
  manifest has the same query text and the same row count returns
  `unchanged` and uploads nothing.
