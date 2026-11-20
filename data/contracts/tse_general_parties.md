# tse_general_parties

TSE general-election party votes: `votacao_partido_munzona_<year>.zip` for 2014, 2018, 2022
and 2026. Four zips, stored exactly as fetched, in a new dated folder under the entry's `gcs:`
in `data/catalog.yaml`. Acquired by `pipeline/acquire/tse_general_parties.py` (logic in
`src/terrain/acquire.py`). Idea 0011; read by `amendments_panel` v3.

## Members

Each zip has `*_BRASIL.csv` (every row), `*_BR.csv` and `leiame.pdf`. The build reads only
`*_BRASIL.csv`. CSVs are `;`-separated, quoted, Latin-1.

## Columns the build uses

- All years: `SG_UF`, `CD_MUNICIPIO` (TSE code, not IBGE), `CD_CARGO` (6 federal deputy,
  7 state deputy, 8 district deputy of DF), `NR_TURNO`, `NR_PARTIDO`.
- 2014: `QT_VOTOS_NOMINAIS` (votes for the party's candidates) and `QT_VOTOS_LEGENDA`
  (party-list votes).
- 2018, 2022, 2026: `NR_FEDERACAO` (federations exist in 2022 and 2026; `-1` otherwise),
  `QT_VOTOS_NOMINAIS_VALIDOS` and `QT_TOTAL_VOTOS_LEG_VALIDOS` (valid party-list votes,
  candidates' votes converted to the list included).

One row per zone, office, round, party and coalition record (`SQ_COLIGACAO`). A party can
appear twice in a zone under two coalition records (74 rows in 2018, 3,627 in 2022, 1,889 in
2026 on 2026-11-20; in 2022 and 2026 one of each pair has zero votes). The build sums them.

## Identifiers

None: the files hold party numbers, names and vote counts only.

## Manifest

`stage: acquire`; `files`: each zip with its SHA-256 and bytes. The 2022 and 2026 files were
regenerated on 2026-11-20 and can change with court rulings; the dated raw folder is the
snapshot. The zipped total is about 90 MB.
