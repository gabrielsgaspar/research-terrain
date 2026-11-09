# ibama_autos

IBAMA fines (autos de infração) for the nine Legal Amazon states, 2000-2025.
One Parquet, `ibama_autos.parquet`, in a new dated folder under the entry's
`gcs:` in `data/catalog.yaml`. Acquired by `pipeline/acquire/ibama_autos.py`
(logic in `src/terrain/ibama.py` and `src/terrain/bigquery.py`). Campaign 0004,
step s1; idea 0005.

## Sources and the fallback rule

1. IBAMA's open-data portal, tried only when the catalog's `portal.columns`
   mapping is complete (`delimiter`, `encoding`, every file `url` and every
   column name known, except `indicador_coordenada_valida` and `data_extracao`).
   Until someone profiles the files the mapping is incomplete and the notes say
   "portal skipped: mapping incomplete".
2. Base dos Dados on BigQuery (`bigquery:` block). Used in the same run when the
   portal path is skipped or fails for any reason (HTTP error, timeout, bad
   zip, missing column, a value that will not type). Identifiers (names,
   CPF/CNPJ) and geometries are never selected.

Both give the same schema. Values are stored as the source gives them: no
filter by category and no recoding of the indicators; the build (s4) does
that. On the portal path `indicador_coordenada_valida` and `data_extracao` are
null.

## Columns

In this order, with polars types.

| Column | Type | Meaning |
| --- | --- | --- |
| `fonte` | Utf8 | `ibama` or `basedosdados` |
| `formato` | Utf8 | `sicafi` if `data_auto` is before 2019-10-08, `aie` from that day, null if `data_auto` is null |
| `id_auto` | Utf8 | record id (`SEQ_AUTO_INFRACAO`) in both formats |
| `data_auto` | Date | date of the fine |
| `ano` | Int64 | year |
| `id_municipio` | Utf8 | 7-digit IBGE code |
| `sigla_uf` | Utf8 | state |
| `latitude`, `longitude` | Float64 | published point |
| `tipo_infracao`, `tipo_auto`, `situacao_auto`, `indicador_cancelado`, `gravidade` | Utf8 | as the source gives them |
| `indicador_coordenada_valida` | Utf8 | the published point falls inside the declared municipality's polygon (Base dos Dados) |
| `data_extracao` | Date | Base dos Dados extraction date |

The 2019-10-08 change is IBAMA's switch from Sicafi (numeric numbers with a
series) to AIe (alphanumeric, no series). Rows are sorted by `ano`, `id_auto`.

## Manifest

`stage: acquire`; `files`: the Parquet with SHA-256 and bytes.

- `sources` portal: per file `fonte: ibama`, `url`, `last_modified`, `bytes`.
- `sources` BigQuery: `fonte: basedosdados`, `table`, `query` (the exact text
  sent), `location`, `max_data_extracao`, `rows`, `total_bytes_processed`,
  `job_id`.
- `notes`, one line each: the source used; the portal probe status; whether the
  portal was used, skipped or failed (no data value); the row count; the sorted
  distinct values (no counts, null shown as `null`) of `tipo_infracao`,
  `tipo_auto`, `situacao_auto`, `indicador_cancelado` and
  `indicador_coordenada_valida`.

A run whose `MAX(data_extracao)`, row count and query equal those of the latest
BigQuery manifest returns `unchanged` and uploads nothing. The file may not
exceed 2 GB. No credential or token appears in the manifest or a log.
