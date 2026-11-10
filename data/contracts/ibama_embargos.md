# ibama_embargos

IBAMA embargoes (termos de embargo) for the nine Legal Amazon states,
2000-2025. One Parquet, `ibama_embargos.parquet`, in a new dated folder under
the entry's `gcs:` in `data/catalog.yaml`. Acquired by
`pipeline/acquire/ibama_embargos.py` (logic in `src/terrain/ibama.py` and
`src/terrain/bigquery.py`). Campaign 0004, step s1; idea 0005.

## Sources and the fallback rule

1. IBAMA's open-data portal, tried only when the catalog's `portal.columns`
   mapping is complete. The portal download URL is not known, so the mapping is
   incomplete and the notes say "portal skipped: mapping incomplete".
2. Base dos Dados on BigQuery (`bigquery:` block), in the same run whenever the
   portal path is skipped or fails. Names, CPF/CNPJ, property names and
   geometries are never selected.

Both give the same schema. Values are stored as the source gives them: no
filter and no recoding; the build (s4) does that. On the portal path
`indicador_coordenada_valida` and `data_extracao` are null.

## Columns

In this order, with polars types.

| Column | Type | Meaning |
| --- | --- | --- |
| `fonte` | Utf8 | `ibama` or `basedosdados` |
| `id_embargo` | Utf8 | embargo id |
| `id_auto` | Utf8 | the fine the embargo came from |
| `data_embargo` | Date | date of the embargo |
| `ano` | Int64 | year |
| `id_municipio` | Utf8 | 7-digit IBGE code |
| `sigla_uf` | Utf8 | state |
| `latitude`, `longitude` | Float64 | published point |
| `area_ha` | Float64 | embargoed area in hectares |
| `tipo_area`, `indicador_desembargado` | Utf8 | as the source gives them |
| `indicador_coordenada_valida` | Utf8 | the published point falls inside the declared municipality's polygon (Base dos Dados) |
| `data_extracao` | Date | Base dos Dados extraction date |

Rows are sorted by `ano`, `id_embargo`.

## Manifest

`stage: acquire`; `files`: the Parquet with SHA-256 and bytes.

- `sources` portal: per file `fonte: ibama`, `url`, `last_modified`, `bytes`.
- `sources` BigQuery: `fonte: basedosdados`, `table`, `query` (the exact text
  sent), `location`, `max_data_extracao`, `rows`, `total_bytes_processed`,
  `job_id`.
- `notes`, one line each: the source used; the portal probe status; whether the
  portal was used, skipped or failed (no data value); the row count; the sorted
  distinct values (no counts, null shown as `null`) of `tipo_area`,
  `indicador_desembargado` and `indicador_coordenada_valida`.

A run whose `MAX(data_extracao)`, row count and query equal those of the latest
BigQuery manifest returns `unchanged` and uploads nothing. The file may not
exceed 2 GB. No credential or token appears in the manifest or a log.
