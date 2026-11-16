# tse_general

TSE general-election files: votes by candidate and municipality
(`votacao_candidato_munzona`, 2014, 2018, 2022, 2026) and candidacies
(`consulta_cand`, 2010, 2014, 2018, 2022, 2026). Nine zips, stored exactly as
fetched, in a new dated folder under the entry's `gcs:` in
`data/catalog.yaml`. Acquired by `pipeline/acquire/tse_general.py` (logic in
`src/terrain/acquire.py`). Campaign 0009, steps s1 and s2; idea 0009.

## Members

Each zip has 30 members: one CSV per state (27, DF included), `_BR`, `_BRASIL`
(every row again) and `leiame.pdf`. The build reads only `*_BRASIL.csv`. CSVs
are `;`-separated, quoted, Latin-1.

## Columns the build uses

- Munzona: `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO` (TSE code, not
  IBGE), `CD_CARGO`, `SQ_CANDIDATO`, `NR_PARTIDO`, `SG_PARTIDO`,
  `QT_VOTOS_NOMINAIS`, `CD_SIT_TOT_TURNO`. 2018, 2022 and 2026 also have
  `NR_FEDERACAO`, `QT_VOTOS_NOMINAIS_VALIDOS` and `NM_TIPO_DESTINACAO_VOTOS`;
  2014 has neither of the last two.
- `consulta_cand`: `SQ_CANDIDATO`, `CD_CARGO`, `SG_UF`, `NM_URNA_CANDIDATO`,
  `NR_PARTIDO`, `SG_PARTIDO`, `CD_SIT_TOT_TURNO`.

## Identifiers

The raw `consulta_cand` zips hold CPF and voter-ID columns
(`NR_CPF_CANDIDATO`, `NR_TITULO_ELEITORAL_CANDIDATO`) and candidate names, as
TSE publishes them. They stay in the raw zips only. A build may use them in
memory and never writes them to derived data, logs or results (`AGENTS.md`,
"Personal identifiers").

## Manifest

`stage: acquire`; `files`: each zip with its SHA-256 and bytes. The 2026 files
were regenerated on 2026-11-15 and can change with court rulings; the dated
raw folder is the snapshot. The zipped total is about 1.94 GB.
