# tse_results

Votes per candidacy and turnout, by municipality, zone, office and round, in the
municipal elections 2000-2024. Source: the `*_BRASIL.csv` member of each
`votacao_candidato_munzona_<year>.zip` and `detalhe_votacao_munzona_<year>.zip`
in the `tse_results` acquire manifest (state files repeat the same rows and are
never read; the party-vote and coalition zips belong to `tse_parties`). Built by
`src/terrain/builds/tse_results.py`; written to
`data/derived/tse_results/<hash>/`, one file per year and kind:

- `candidate_votes_<year>.parquet`: one row per candidacy, round and zone.
- `turnout_<year>.parquet`: one row per zone, office and round.

`<hash>` is `content_hash` of the sorted input SHA-256s (the zips,
`candidates.parquet` and `municipalities.parquet`) and the sorted source of this
build and of `src/terrain/builds/tse_candidates.py`, whose helpers it imports. A
fix to either gives a new path.

## Keys

- `candidate_votes`: (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `sq_candidato`,
  `nr_turno`, `nr_zona`) is unique in every year. Before 2012 `sq_candidato`
  repeats across municipalities, so `sg_ue` is part of the key.
- `turnout`: (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `nr_zona`, `cd_cargo`,
  `nr_turno`) is unique in every year.

Supplementary elections are kept. Identify the election type by
`cd_tipo_eleicao` and the office by `cd_cargo`; labels (`ELEIÇÃO SUPLEMENTAR`
in candidate files, `ELEIÇÃO EXTRAORDINÁRIA` in results files, `Prefeito` vs
`PREFEITO`) change across years and are never used.

## Missing values

These source values become null in every column except the key columns (and
`cd_cargo`): `#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`, `-4`,
`NÃO DIVULGÁVEL`, and the empty string. `sg_ue`, `nr_zona`, `sq_candidato` and
`cd_cargo` stay text with their leading zeros.

## cd_ibge

`cd_ibge` sits after `sg_ue`. It is the IBGE municipality code from
`municipalities.parquet`, joined on `sg_ue` = `cd_tse`. `sg_ue` is the TSE
code, not the IBGE code.

## matched

`candidate_votes.matched` is true when (`ano_eleicao`, `cd_eleicao`, `sg_ue`,
`sq_candidato`) is in `candidates.parquet` (the `tse_candidates` build). It is
false for the few candidacies that appear in the results and not in the
candidate file (3 in 2000, 140 in 2008 and 4 in 2012 on the full files). Rows
are never dropped for being unmatched.

## Types

`ano_eleicao`, `cd_eleicao`, `nr_turno` and `cd_tipo_eleicao` are Int32,
`dt_eleicao` is a date read as `dd/mm/yyyy`, `qt_*` counts are Int64, `matched`
is boolean, and everything else is text decoded from Latin-1.

## Columns by year

Each kind has the same columns in every year (the union over years); a column a
year lacks is null for that year.

- `qt_votos_nominais_validos` is null in `candidate_votes` for a year whose file
  lacks it (2008). The 2000 file has `qt_votos_nominais` equal to 0 and the
  votes in `qt_votos_nominais_validos`; do not add the two.
- `turnout` carries every count column the year has: eligible voters
  (`qt_aptos`), turnout (`qt_comparecimento`), abstentions (`qt_abstencoes`),
  valid, blank and null votes, and the section counts.
- `DT_ULTIMA_TOTALIZACAO` can be after the election (recounts). It is kept as
  text and is not used.

## Checks the build enforces

For every file, the build stops with an error that carries counts only if:

1. the rows built differ from the records in the `BRASIL` file;
2. the key above repeats;
3. any row has no `cd_ibge`;
4. (`candidate_votes` only) unmatched candidacies exceed 1% of a year's candidacies (distinct candidacy keys, not rows).

It also stops if a count is not an integer, if a file does not match its
manifest SHA-256, if a year has only one of the two kinds of file, or if
`municipalities.parquet` repeats a `cd_tse`.

## Consistency report

Not a check. For each year, the manifest `notes` give `agree/total`: the number
of municipality-office-rounds (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `cd_cargo`,
`nr_turno`) where the sum over zones of the candidates' valid votes equals the
sum of turnout's `qt_votos_nominais_validos`. The candidates' column is
`qt_votos_nominais_validos`, or `qt_votos_nominais` for a year whose file lacks
the first. A group present in only one table counts in `total` only. The notes
also give rows per year and the unmatched count per year.
