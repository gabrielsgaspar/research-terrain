# inep_school_catalogue

One recent year (2024) of school names, addresses and postcodes from INEP's
Censo Escolar microdata, with coordinates where INEP's school catalogue gives
them. One Parquet, `inep_school_catalogue.parquet`, in a new dated folder under
the entry's `gcs:` in `data/catalog.yaml`. Acquired by
`pipeline/acquire/inep_school_catalogue.py` (logic in `src/terrain/inep.py`).
Campaign 0006, step s6; idea 0006, decision 0011. Read by the match of polling
places to schools (step s9).

## Sources

1. INEP's `microdados_censo_escolar_2024.zip`, one CSV member, Latin-1,
   `;`-separated. Only the columns listed in the catalog's `microdata.columns`
   are read.
2. Coordinates from Base dos Dados
   (`basedosdados.br_bd_diretorios_brasil.escola`), joined on `id_escola`.
   A failure of this query fails the run.

Phone numbers (`NU_DDD`, `NU_TELEFONE`) and emails are never read into the
output, stored or put in a manifest. The school name (`NO_ENTIDADE`) is the
name of a public building, not of a person.

INEP's server does not send its intermediate certificate. Before any request
to INEP the run downloads that certificate from `extra_ca_url`, requires its
SHA-256 to equal `extra_ca_sha256`, and adds it to the system trust store for
that download. Verification stays on. The certificate is never stored; the
manifest records only its URL and fingerprint.

## Columns

In this order, with polars types. One row per `CO_ENTIDADE`, sorted by
`id_escola`. Empty text is null.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano` | Int64 | census year (`NU_ANO_CENSO`) |
| `id_escola` | Utf8 | INEP school code (`CO_ENTIDADE`) |
| `nome_escola` | Utf8 | school name (`NO_ENTIDADE`) |
| `id_municipio` | Utf8 | 7-digit IBGE code (`CO_MUNICIPIO`) |
| `sigla_uf` | Utf8 | state (`SG_UF`) |
| `rede` | Utf8 | administrative dependency (`TP_DEPENDENCIA`) |
| `tipo_localizacao` | Utf8 | urban or rural (`TP_LOCALIZACAO`) |
| `endereco` | Utf8 | street (`DS_ENDERECO`) |
| `numero` | Utf8 | street number (`NU_ENDERECO`) |
| `complemento` | Utf8 | address complement (`DS_COMPLEMENTO`) |
| `bairro` | Utf8 | neighbourhood (`NO_BAIRRO`) |
| `cep` | Utf8 | postcode, 8 digits with leading zeros; null when not 1-8 digits |
| `latitude` | Float64 | from Base dos Dados |
| `longitude` | Float64 | from Base dos Dados |

`latitude` and `longitude` are both null when the school has no coordinate
row, when either value is null or 0, or when either lies outside latitude
-34 to 6 or longitude -74 to -28. A bad `NU_ANO_CENSO`, a missing or repeated
`CO_ENTIDADE` or a `CO_MUNICIPIO` that is not 7 digits stops the build.

## Manifest

`stage: acquire`; `files`: the Parquet with SHA-256 and bytes.

- `sources`: INEP (`fonte: inep`, `url`, `bytes`, `sha256` of the zip,
  `extra_ca_url`, `extra_ca_sha256`) and Base dos Dados (`fonte: basedosdados`,
  `table`, `query`, `location`, `rows`, `total_bytes_processed`, `job_id`).
- `notes`, values only: rows; rows per state; the share with a `cep`; the
  share with coordinates; the count of `cep` values that were not 1-8 digits;
  microdata rows with no coordinate row; coordinate rows with no microdata
  row; the certificate URL and fingerprint.
