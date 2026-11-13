# politics_panel

One row per municipality and municipal election 2000-2024: council entry, competition,
who wins, seat turnover, incumbent re-election, mining-sector campaign money and homicides
per 100,000. Idea 0008, decisions 0003 and 0011. Built by
`src/terrain/builds/politics_panel.py` (campaign 0008 step s6; run in step s8).

## Inputs

- `tse_candidates` (build): `candidates.parquet`; `cd_ocupacao`, `sg_partido` and
  `nr_cpf_candidato`, joined on (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `sq_candidato`).
- `tse_results` (build): `candidate_votes_<year>.parquet` and `turnout_<year>.parquet`
  (`data/contracts/tse_results.md`).
- `municipalities` (build): `cd_ibge`, `cd_tse`, `uf`. `sg_ue` of the TSE files is
  `cd_tse`.
- `sim_homicides` (acquire): `ano`, `id_municipio_ocorrencia`, `n_obitos`.
- `ibge_population_annual` (acquire): `ano`, `id_municipio`, `populacao`.
- `tse_receipts` (acquire): `ano`, `id_municipio`, `cargo`, `cnae_2_doador`,
  `n_receitas`, `sum_valor_receita`.
- The two exploration lists (`data/derived/split/`).

## Output and split

One Parquet per election, `politics_panel_<election>.parquet`, sorted by `cd_ibge`.
Rows of exploration-half municipalities (either exploration list) go to
`data/derived/politics_panel/<hash>/`. Every other row goes only to
`sealed/outcomes/politics_panel/<hash>/`, which the build creates in and never reads.
`<hash>` is `content_hash` of the sorted input SHA-256s, the SHA-256s of the two lists,
the elections, and the source of this build and of the `terrain` modules it imports
(`strongholds`, `explore`, `place_outcomes`, `cell_outcomes`, `polling_place_tenure`). The
manifest lists the derived files in `files` and the sealed files in `sealed_files`.

A municipality that has no results row at an election has no row for it. The rows of an
election are the municipalities with first-round council or mayoral rows in its main
election.

## Columns

Council is `cd_cargo` 13 and mayor `cd_cargo` 11. The main election (`cd_eleicao`) is the
one with the most first-round rows of the office. A candidate **ran** if the first-round
votes of the candidacy, summed over zones, are above 0. Votes are the valid nominal votes
(`qt_votos_nominais_validos`), or the nominal votes where that is null (the 2000 file holds
the votes in the first and 0 in the second; the 2008 file has no first).

| Column | Type | Meaning |
| --- | --- | --- |
| `cd_ibge` | text | 7-digit IBGE code; unique within an election |
| `uf` | text | state letters |
| `election` | int | 2000, 2004, ..., 2024 |
| `n_council_cands` | int | council candidates who ran |
| `n_seats` | int | council candidates with an elected status |
| `cands_per_seat` | float | `n_council_cands / n_seats`; null if no seat |
| `n_mining_cands` | int | candidates who ran with `cd_ocupacao` 605 or 253 |
| `mining_cand_share` | float | `n_mining_cands / n_council_cands` |
| `n_mayor_cands` | int | mayoral candidates who ran |
| `valid_votes_mayor` | int | valid mayoral votes, round 1, summed over zones |
| `enc_mayor` | float | 1 / sum of s_i squared, s_i the share of the candidates' votes |
| `margin_mayor` | float | (first - second) / `valid_votes_mayor`; 1.0 with one candidate |
| `seat_turnover` | float | 1 - sum over parties of min(seats now, seats 4 years ago) / seats now |
| `mining_councillor_share` | float | elected councillors with code 605 or 253, over `n_seats` |
| `incumbent_reelected` | float | share of the councillors elected 4 years ago elected again |
| `mining_money_share` | float | receipts of a mining donor sector / all receipts |
| `receipts_total` | float | receipts of "vereador" and "prefeito" (BRL) |
| `receipts_with_cnae` | float | the part of it with a non-null donor CNAE (BRL) |
| `n_receipts_with_cnae` | int | number of receipts with a non-null donor CNAE |
| `homicide_rate` | float | homicides in e-4..e-1 per 100,000 of the same years' population |
| `homicides_sum` | int | homicides in e-4..e-1 (municipality of occurrence) |

### Elected status

`strongholds.elected_status` reads `cd_sit_tot_turno`. It knows the 2008 codes (elected 1
and 5) and, for every other year, the 2012 codes. The build gives it 2008 for 2000, 2004
and 2008, and the election year for later ones, so 2004 is read with the 2008 codes. The
2000 codes are **unconfirmed**; if they differ, `n_seats` of 2000 is wrong. A candidate
with any other code is not elected, but still counts as having run if the votes are above
0.

### Null rules

- `seat_turnover` and `incumbent_reelected`: null for 2000, or when the election four years
  earlier is not in the run, and for a municipality that has no elected councillor (or, for
  the incumbent share, no linkable one) at the earlier election.
- `incumbent_reelected`: councillors are linked by `nr_cpf_candidato` within the
  municipality, **in memory only**. A CPF that is empty or not 11 digits is unlinked and
  left out of the share. No CPF, name or hash of either is written to a column, a note or
  an exception message.
- Mining money (outcome 8) is read for 2004, 2008 and 2012 only; it is null for the other
  elections, and null for a municipality with no receipt row of the two offices that year.
  Offices are compared lower-cased and accent-stripped ("vereador", "prefeito"). A mining
  CNAE is the digits of `cnae_2_doador`, left-padded to 7: division 07 or 08, or the first
  four digits 0990. `mining_money_share` is null when `receipts_total` is 0. A receipt
  without a CNAE counts in `receipts_total` and not in `receipts_with_cnae`, so the share
  is read together with `receipts_with_cnae / receipts_total`.
- `homicide_rate` is null unless all four years e-4..e-1 have a non-null population.
  SIM has no row for a municipality-year without a death, so a missing year counts as 0 in
  `homicides_sum`.
- A first-round margin needs `valid_votes_mayor` above 0, unless there was one candidate.

## Checks the build enforces

Each raises `BuildError` with counts only, before anything is uploaded.

1. A `cd_tse` in the results with no `cd_ibge`.
2. `cands_per_seat` below 1 in any row.
3. A share (`mining_cand_share`, `margin_mayor`, `seat_turnover`,
   `mining_councillor_share`, `incumbent_reelected`, `mining_money_share`) outside [0, 1].
4. Fewer than 5,000 municipalities in any election from 2004 on.
5. `homicide_rate` above 1,000 per 100,000.
6. National candidates with code 605 or 253, summed over 2004, 2008 and 2012, below 100.
   (The full files have 605 alone at 122, 108 and 65.)
7. A money year (2004, 2008, 2012) in which neither "vereador" nor "prefeito" appears in
   the receipts.

It also stops if an input lacks a column it needs, does not match its manifest SHA-256, if
a municipality is in both exploration lists, if a `cd_tse` repeats in `municipalities`, or if a
candidacy repeats in the candidates.

## Manifest notes

Exploration-half rows only, counts only, no statistic of any outcome: rows per election
(`E2004: rows=...`), elected councillors whose CPF could not be linked per election
(`unlinked_cpfs=...`), and `years_with_receipt_cnae=` (the years in which any
exploration-half row has a receipt with a CNAE, or `none`).
