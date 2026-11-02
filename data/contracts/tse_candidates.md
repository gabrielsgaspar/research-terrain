# tse_candidates

One row per candidacy in the municipal elections 2000-2024, from the
`*_BRASIL.csv` member of each `consulta_cand_<year>.zip` (state files repeat
the same rows and are never read). Built by
`src/terrain/builds/tse_candidates.py`; written to
`data/derived/tse_candidates/<hash>/candidates.parquet`, where `<hash>` is
`content_hash` of the input SHA-256s and the build code.

## Key

(`ano_eleicao`, `cd_eleicao`, `sg_ue`, `sq_candidato`) is unique. Before 2012
`sq_candidato` repeats across municipalities, so it is not a key alone.
`sg_ue` is the TSE municipality code, not the IBGE code. Supplementary
elections are kept; identify them by `cd_eleicao` and `cd_tipo_eleicao`, never
by the label.

## Missing values

These source values become null in every column except the four key columns:
`#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`, `-4`, `NÃO DIVULGÁVEL`, and the
empty string. Identifiers (`sq_candidato`, `sg_ue`, `nr_cpf_candidato`,
`nr_titulo_eleitoral_candidato`) stay text with their leading zeros.
A column a year does not have is null for that year.

## Types

`int` is Int32, `date` is a calendar date read as `dd/mm/yyyy`, `text` is a
string. Text is decoded from Latin-1.

## Birth dates

`dt_nascimento_raw` is the original text, after the missing-value rule.
`dt_nascimento` is parsed from it with spaces removed, non-strictly. It is null
when the text does not parse as `dd/mm/yyyy`, when the date is before
1900-01-01, or when the candidate was under 18 on `dt_eleicao`. The build writes
the per-year counts of unparseable and implausible values in the manifest
`notes`, and raises if either exceeds 0.1% of a year's rows. `dt_eleicao` is
strict: a value that does not parse stops the build.

## Columns

Source names are upper case in the files. "Years" lists the candidate files
that have the column; the complementary file exists for 2020 and 2024 only.

| Column | Type | Source column | Years |
| --- | --- | --- | --- |
| `dt_geracao` | text | `DT_GERACAO` | all |
| `hh_geracao` | text | `HH_GERACAO` | all |
| `ano_eleicao` | int | `ANO_ELEICAO` | all |
| `cd_tipo_eleicao` | int | `CD_TIPO_ELEICAO` | all |
| `nm_tipo_eleicao` | text | `NM_TIPO_ELEICAO` | all |
| `nr_turno` | int | `NR_TURNO` | all |
| `cd_eleicao` | int | `CD_ELEICAO` | all |
| `ds_eleicao` | text | `DS_ELEICAO` | all |
| `dt_eleicao` | date | `DT_ELEICAO` | all |
| `tp_abrangencia` | text | `TP_ABRANGENCIA` | all |
| `sg_uf` | text | `SG_UF` | all |
| `sg_ue` | text | `SG_UE` | all |
| `nm_ue` | text | `NM_UE` | all |
| `cd_cargo` | text | `CD_CARGO` | all |
| `ds_cargo` | text | `DS_CARGO` | all |
| `sq_candidato` | text | `SQ_CANDIDATO` | all |
| `nr_candidato` | text | `NR_CANDIDATO` | all |
| `nm_candidato` | text | `NM_CANDIDATO` | all |
| `nm_urna_candidato` | text | `NM_URNA_CANDIDATO` | all |
| `nm_social_candidato` | text | `NM_SOCIAL_CANDIDATO` | all |
| `nr_cpf_candidato` | text | `NR_CPF_CANDIDATO` | all |
| `email` | text | `NM_EMAIL` (2000-2016), `DS_EMAIL` (2020-2024) | all |
| `cd_situacao_candidatura` | text | `CD_SITUACAO_CANDIDATURA` | all |
| `ds_situacao_candidatura` | text | `DS_SITUACAO_CANDIDATURA` | all |
| `cd_detalhe_situacao_cand` | text | `CD_DETALHE_SITUACAO_CAND` | 2000-2016 |
| `ds_detalhe_situacao_cand` | text | `DS_DETALHE_SITUACAO_CAND` | 2000-2016 |
| `tp_agremiacao` | text | `TP_AGREMIACAO` | all |
| `nr_partido` | text | `NR_PARTIDO` | all |
| `sg_partido` | text | `SG_PARTIDO` | all |
| `nm_partido` | text | `NM_PARTIDO` | all |
| `sq_coligacao` | text | `SQ_COLIGACAO` | all |
| `nm_coligacao` | text | `NM_COLIGACAO` | all |
| `ds_composicao_coligacao` | text | `DS_COMPOSICAO_COLIGACAO` | all |
| `cd_nacionalidade` | text | `CD_NACIONALIDADE` | 2000-2016 |
| `ds_nacionalidade` | text | `DS_NACIONALIDADE` | 2000-2016 |
| `sg_uf_nascimento` | text | `SG_UF_NASCIMENTO` | all |
| `cd_municipio_nascimento` | text | `CD_MUNICIPIO_NASCIMENTO` | 2000-2016 |
| `nm_municipio_nascimento` | text | `NM_MUNICIPIO_NASCIMENTO` | 2000-2016 |
| `dt_nascimento` | date | `DT_NASCIMENTO` | all |
| `dt_nascimento_raw` | text | `DT_NASCIMENTO`, as read | all |
| `nr_idade_data_posse` | text | `NR_IDADE_DATA_POSSE` | 2000-2016 |
| `nr_titulo_eleitoral_candidato` | text | `NR_TITULO_ELEITORAL_CANDIDATO` | all |
| `cd_genero` | text | `CD_GENERO` | all |
| `ds_genero` | text | `DS_GENERO` | all |
| `cd_grau_instrucao` | text | `CD_GRAU_INSTRUCAO` | all |
| `ds_grau_instrucao` | text | `DS_GRAU_INSTRUCAO` | all |
| `cd_estado_civil` | text | `CD_ESTADO_CIVIL` | all |
| `ds_estado_civil` | text | `DS_ESTADO_CIVIL` | all |
| `cd_cor_raca` | text | `CD_COR_RACA` | all (recorded from 2016) |
| `ds_cor_raca` | text | `DS_COR_RACA` | all (recorded from 2016) |
| `cd_ocupacao` | text | `CD_OCUPACAO` | all |
| `ds_ocupacao` | text | `DS_OCUPACAO` | all |
| `vr_despesa_max_campanha` | text | `VR_DESPESA_MAX_CAMPANHA` | 2000-2016 |
| `cd_sit_tot_turno` | text | `CD_SIT_TOT_TURNO` | all |
| `ds_sit_tot_turno` | text | `DS_SIT_TOT_TURNO` | all |
| `st_reeleicao` | text | `ST_REELEICAO` | 2000-2016 |
| `st_declarar_bens` | text | `ST_DECLARAR_BENS` | 2000-2016 |
| `nr_protocolo_candidatura` | text | `NR_PROTOCOLO_CANDIDATURA` | 2000-2016 |
| `nr_processo` | text | `NR_PROCESSO` | 2000-2016 |
| `cd_situacao_candidato_pleito` | text | `CD_SITUACAO_CANDIDATO_PLEITO` | 2000-2016 |
| `ds_situacao_candidato_pleito` | text | `DS_SITUACAO_CANDIDATO_PLEITO` | 2000-2016 |
| `cd_situacao_candidato_urna` | text | `CD_SITUACAO_CANDIDATO_URNA` | 2000-2016 |
| `ds_situacao_candidato_urna` | text | `DS_SITUACAO_CANDIDATO_URNA` | 2000-2016 |
| `st_candidato_inserido_urna` | text | `ST_CANDIDATO_INSERIDO_URNA` | 2000-2016 |
| `nm_tipo_destinacao_votos` | text | `NM_TIPO_DESTINACAO_VOTOS` | 2000, 2016 |
| `cd_situacao_candidato_tot` | text | `CD_SITUACAO_CANDIDATO_TOT` | 2000, 2016 |
| `ds_situacao_candidato_tot` | text | `DS_SITUACAO_CANDIDATO_TOT` | 2000, 2016 |
| `st_prest_contas` | text | `ST_PREST_CONTAS` | 2000, 2016 |
| `st_substituido` | text | `ST_SUBSTITUIDO` | 2000, 2016 |
| `sq_substituido` | text | `SQ_SUBSTITUIDO` | 2000, 2016 |
| `sq_ordem_suplencia` | text | `SQ_ORDEM_SUPLENCIA` | 2000, 2016 |
| `dt_aceite_candidatura` | text | `DT_ACEITE_CANDIDATURA` | 2000, 2016 |
| `nr_federacao` | text | `NR_FEDERACAO` | 2016-2024 |
| `nm_federacao` | text | `NM_FEDERACAO` | 2016-2024 |
| `sg_federacao` | text | `SG_FEDERACAO` | 2016-2024 |
| `ds_composicao_federacao` | text | `DS_COMPOSICAO_FEDERACAO` | 2016-2024 |
| `cd_etnia_indigena` | text | `CD_ETNIA_INDIGENA`, complementary file | 2020, 2024 (filled in 2024) |
| `ds_etnia_indigena` | text | `DS_ETNIA_INDIGENA`, complementary file | 2020, 2024 (filled in 2024) |
| `st_quilombola` | text | `ST_QUILOMBOLA`, complementary file | 2020, 2024 (filled in 2024) |

The complementary file is joined on (`ano_eleicao`, `cd_eleicao`,
`sq_candidato`). Candidates without a complementary row, and every candidate
before 2020, have null in its three columns.

## Checks the build enforces

- Rows per year equal the records in that year's `BRASIL` file.
- The candidacy key above is unique within each year.
- Every complementary row joins to a candidacy, and joining adds no rows.
