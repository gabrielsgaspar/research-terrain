# inep_school_catalogue

INEP's school catalogue (Catálogo de Escolas): school names, addresses,
postcodes and coordinates. One Parquet, `inep_school_catalogue.parquet`, in a
new dated folder under the entry's `gcs:` in `data/catalog.yaml`. Acquired by
`pipeline/acquire/inep_school_catalogue.py` (logic in `src/terrain/inep.py`).
Campaign 0006, steps s6 and s8; idea 0006, decision 0011. Read by the match of
polling places to schools (step s9).

## Source

Base dos Dados' copy of INEP's catalogue on BigQuery,
`basedosdados.br_bd_diretorios_brasil.escola`. Only the columns in the
catalog's `bigquery.columns` are selected: `id_escola`, `id_municipio`,
`sigla_uf`, `nome`, `endereco`, `latitude`, `longitude`,
`dependencia_administrativa`, `localizacao`, `situacao_catalogo`. All are
STRING in BigQuery. A failure of the query fails the run.

`telefone` is never selected. `nome` is the name of a school, a public
building, not of a person. The BigQuery builder refuses every column that
starts with `nome`, except this exact column of this table
(`terrain.bigquery.ALLOWED_BY_TABLE`).

The catalogue was first to come from INEP's Censo Escolar 2024 microdata at
download.inep.gov.br. INEP resets every connection from GitHub's servers
(campaign 0006 s8, runs 42861990498 and 42900676058), so it comes from
BigQuery instead.

## Columns

In this order, with polars types. One row per `id_escola`, sorted by
`id_escola`. Empty text is null. No row is dropped: schools that are
`Ausente` from INEP's latest catalogue stay, because the polling places of
2008-2020 may be at schools that have since closed.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano` | Int64 | always null: the catalogue has no census year |
| `id_escola` | Utf8 | INEP school code (`id_escola`) |
| `nome_escola` | Utf8 | school name (`nome`) |
| `id_municipio` | Utf8 | 7-digit IBGE code (`id_municipio`) |
| `sigla_uf` | Utf8 | state (`sigla_uf`) |
| `rede` | Utf8 | administrative dependency as INEP's `TP_DEPENDENCIA` code: "1" federal, "2" state, "3" municipal, "4" private (from `dependencia_administrativa`) |
| `tipo_localizacao` | Utf8 | INEP's `TP_LOCALIZACAO` code: "1" urban, "2" rural (from `localizacao`) |
| `endereco` | Utf8 | street, parsed from `endereco` |
| `numero` | Utf8 | street number, parsed from `endereco`; null when not found |
| `complemento` | Utf8 | always null: the one address field gives no complement |
| `bairro` | Utf8 | neighbourhood, parsed from `endereco`; null when not found |
| `cep` | Utf8 | postcode, 8 digits, parsed from `endereco`; null when not found |
| `latitude` | Float64 | from `latitude` |
| `longitude` | Float64 | from `longitude` |

### Parsing `endereco`

`endereco` is one text field.

- `cep` is its last run of 8 digits, written `76801-000` or `76801000`. The
  text after it (the city) is dropped.
- When the rest has the form `<street>, <number> <neighbourhood>`, it gives
  `endereco`, `numero` and `bairro`. A number is digits with an optional
  letter, or `S/N`.
- Otherwise the rest is kept whole as `endereco`, and `numero` and `bairro`
  are null.

### Labels and coordinates

- `dependencia_administrativa` and `localizacao` are matched ignoring case
  and accents (`Municipal`, `MUNICIPAL`; `Urbana`), and a value that is
  already a code is kept. An unknown label gives null and is counted in the
  notes. If more than 1% of a column's values are unknown, the run stops.
- `latitude` and `longitude` are read as numbers, with a decimal comma read
  as a point. Both are null when either is not a number, is null or 0, or
  lies outside latitude -34 to 6 or longitude -74 to -28.
- A missing or repeated `id_escola`, or an `id_municipio` that is not 7
  digits, stops the run.

## Manifest

`stage: acquire`; `files`: the Parquet with SHA-256 and bytes.

- `sources`: Base dos Dados (`fonte: basedosdados`, `table`, `query`,
  `location`, `rows`, `total_bytes_processed`, `job_id`).
- `status: unchanged`, with nothing uploaded, when the latest manifest has the
  same query and the same row count (`COUNT(*)`).
- `notes`, values only:
  - rows, and rows per state;
  - rows with an `endereco`;
  - the shares with a parsed `cep`, a street number and a neighbourhood;
  - the share with coordinates;
  - coordinates that are not numbers, and coordinates at 0 or outside Brazil;
  - unknown labels of `dependencia_administrativa` and `localizacao`, with
    counts;
  - rows per `situacao_catalogo`.
