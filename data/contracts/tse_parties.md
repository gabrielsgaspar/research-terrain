# tse_parties

Party votes and coalition membership in the municipal elections 2000-2024,
from the `*_BRASIL.csv` member of each `votacao_partido_munzona_<year>.zip` and
`consulta_coligacao_<year>.zip` in the `tse_results` acquire manifest (state
files repeat the same rows and are never read). Built by
`src/terrain/builds/tse_parties.py`; written to
`data/derived/tse_parties/<hash>/`, one file per year and kind:

- `party_votes_<year>.parquet`: votes per party by municipality, zone, office
  and round.
- `coalitions_<year>.parquet`: one row per party in each coalition, federation
  or isolated-party record.

`<hash>` is `content_hash` of the sorted input SHA-256s (the zips and
`municipalities.parquet`) and the sorted source of this build and of
`src/terrain/builds/tse_candidates.py`, whose helpers it imports. A fix to
either gives a new path.

## Keys

- `party_votes`: (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `nr_zona`, `cd_cargo`,
  `nr_turno`, `nr_partido`, `sq_coligacao`) is unique in every year.
- `coalitions`: (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `cd_cargo`,
  `sq_coligacao`, `nr_partido`) is unique in every year.

A party can appear twice in the same zone, office and round under two
coalition records (one usually with zero votes): 960 such rows in 2016 and 160
in 2024. Both rows are kept; `sq_coligacao` is part of the key for that reason.
Supplementary elections are kept; identify them by `cd_eleicao`.

## Coalition membership

Membership comes from each row's own `nr_partido` and `sg_partido`. The text
`ds_composicao_coligacao` is kept as it is and is never split.

## Missing values

These source values become null in every column except the key columns:
`#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`, `-4`, `NÃO DIVULGÁVEL`, and the
empty string. The key columns keep their text, so `sq_coligacao` can be `-1`
(for example a party running alone in 2000) and still be part of the key.
`sg_ue`, `nr_partido` and `nr_zona` stay text.

## cd_ibge

`cd_ibge` sits after `sg_ue`. It is the IBGE municipality code from
`municipalities.parquet` (the `municipalities` build), joined on
`sg_ue` = `cd_tse`. `sg_ue` is the TSE code, not the IBGE code.

## Types

`ano_eleicao`, `cd_eleicao`, `nr_turno` and `cd_tipo_eleicao` are Int32,
`dt_eleicao` is a date read as `dd/mm/yyyy`, `qt_*` vote counts are Int64, and
everything else is text decoded from Latin-1.

## Columns by year

Each kind has the same columns in every year (the union over years); a column
a year lacks is null for that year.

- Vote columns differ: 2000 has `qt_votos_nominais` and `qt_votos_legenda`;
  2024 has `qt_votos_legenda_validos`, `qt_votos_nom_convr_leg_validos`,
  `qt_total_votos_leg_validos`, `qt_votos_nominais_validos` and the
  annulled and sub judice counts. Do not add counts from different years
  without checking what each means.
- Federation columns (`nr_federacao`, `nm_federacao`, `sg_federacao`,
  `ds_composicao_federacao`) exist in the source from 2024 (they appear in the
  candidate files from 2016). Where a year lacks them they are null.

## Checks the build enforces

For every file, the build stops with an error that carries counts only if:

1. the rows built differ from the records in the `BRASIL` file;
2. the key above repeats;
3. any row has no `cd_ibge`.

It also stops if a vote count is not an integer, if a zip does not match its
manifest SHA-256, if a year has only one of the two kinds of file, or if
`municipalities.parquet` repeats a `cd_tse`.
