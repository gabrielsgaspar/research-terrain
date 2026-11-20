# amendments_panel

One row per cycle, federal deputy and municipality, wherever the deputy's party had one of
the two finalists of the mayoral election. Each row holds the race, the deputy's individual
amendment payments to the municipality before and after it, and the deputy's vote share
there at the general elections before and after, and two outcomes of idea 0010: the
municipality's share of the deputy's money and the log of reais per inhabitant. Ideas 0009 and
0010, decisions 0003 and 0011. Built by `src/terrain/builds/amendments_panel.py` (campaign 0009
step s4; v2, the author link by money and legislature and the two outcomes, by the owner fix
"amendments panel v2"; v3, the party vote shares of idea 0011, by the owner PR "mayoral
incumbency panel").

## Inputs

- `tse_general` (acquire): `votacao_candidato_munzona_<year>.zip` (2014, 2018, 2022, 2026)
  and `consulta_cand_<year>.zip` (2010, 2014, 2018, 2022, 2026); only the `*_BRASIL.csv`
  member (`;`, Latin-1). See `data/contracts/tse_general.md`.
- `cgu_amendments` (acquire): `EmendasParlamentares_PorFavorecido.csv` and, for
  `Código da Emenda` and `Ano da Emenda` only, `EmendasParlamentares.csv`. See
  `data/contracts/cgu_amendments.md`. `Código do Favorecido` and `Favorecido` are never read.
- `tse_general_parties` (acquire): `votacao_partido_munzona_<year>.zip` of t0 and t1 (2014,
  2018, 2022, 2026); only the `*_BRASIL.csv` member. See `data/contracts/tse_general_parties.md`.
- `camara_deputies` (acquire): `deputados.csv`; only `nome`, `nomeCivil`,
  `idLegislaturaInicial` and `idLegislaturaFinal`, in memory. See
  `data/contracts/camara_deputies.md`.
- `tse_results` (build): `candidate_votes_<year>.parquet` and `turnout_<year>.parquet` for 2012,
  2016, 2020, 2024. Mayor is `cd_cargo` 11.
- `tse_candidates` (build): `nr_partido`, `cd_genero`, `dt_nascimento`, `cd_grau_instrucao`,
  `dt_eleicao`, keyed by (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `sq_candidato`).
- `municipalities` (build): `cd_ibge`, `cd_tse`, `uf`, `name_ibge`.
- `ibge_population_annual` (acquire): `ano`, `id_municipio`, `populacao`.
- The two exploration lists (`data/derived/split/`).

## Output and split

- `panel_<cycle>.parquet`, `<cycle>` is `A`, `B` or `C`, sorted by `deputy`, `cd_ibge`.
  Rows of exploration-half municipalities (either list) go to
  `data/derived/amendments_panel/<hash>/`. Every other row goes only to
  `sealed/outcomes/amendments_panel/<hash>/`, which the build creates in and never reads.
- `author_link.parquet` (derived only): one row per cycle with counts, no author code or name.
- `<hash>` is `content_hash` of the sorted input SHA-256s, the SHA-256s of the two lists, the
  cycles table and the source of this build and of the `terrain` modules it imports
  (`explore`, `parties`, `place_outcomes`, `cell_outcomes`, `polling_place_tenure`). The inputs include
  the Chamber's file. The manifest lists
  the derived files in `files` and the sealed files in `sealed_files`.

## Cycles

| cycle | m (mayor) | t0 (base general election) | t1 (next) | pre window | post window |
| --- | --- | --- | --- | --- | --- |
| A | 2016 | 2014 | 2018 | 2015-01 to 2016-09 | 2017-01 to 2018-09 |
| B | 2020 | 2018 | 2022 | 2019-01 to 2020-09 | 2021-01 to 2022-09 |
| C | 2024 | 2022 | 2026 | 2023-01 to 2024-09 | 2025-01 to 2026-09 |

A payment month (`Ano/Mês`, read as `YYYY/MM`, `MM/YYYY` or `YYYYMM`) is inside a window
from its first to its last month, both included.

## Deputies and the author link (in memory)

- **Deputies of a cycle:** t0 federal-deputy candidacies (`CD_CARGO` 6) that were elected
  (`CD_SIT_TOT_TURNO` 1, 2 or 3), plus any other t0 deputy candidacy matched as an author with
  a payment in the cycle's windows (a substitute who served). The key is the t0
  `sq_candidato` (`deputy`).
- **Amendments:** individual only. `Tipo de Emenda`, upper-cased and accent-stripped with
  letters and spaces kept, starts with `EMENDA INDIVIDUAL`. Pix is the same type containing
  `TRANSFERENCIAS ESPECIAIS`. Bench, committee and rapporteur amendments are never read.
- **Authors:** an author is `Código do Autor da Emenda` with the normalised
  `Nome do Autor da Emenda`. Only the payment rows inside the cycle's windows are used.
- **Current-legislature authors:** an author counts only with at least one individual
  amendment (any payment row in the file, through `Código da Emenda`) whose `Ano da Emenda`
  (from `EmendasParlamentares.csv`) is a budget year the legislature elected at t0 voted:
  t0+2 to t0+5 (2016-2019, 2020-2023, 2024-2027). The budget of year Y is voted in year Y-1,
  so budget year t0+1 belongs to the outgoing legislature. (Authors of consecutive budget
  years overlap 93-98% within a legislature and 45-56% across t0+1 and t0+2.) Every other
  author, with all its payments, is left out of the link and the panel and is counted
  (`non_current_*`). CGU's unidentified author (`S/I`, `Sem informação`, with no
  `Código da Emenda`) is one of them and is also counted on its own (`unidentified_author_*`).
  A current author's payments on its own older amendments stay in.
- **Name keys:** a name gives up to two keys (`author_keys`): text in parentheses (CGU's note
  on an amendment taken over from a former member) is dropped, accents are stripped, letters
  are upper-cased, everything else splits words, and the words are joined without spaces;
  the second key also drops leading titles (`DEP`, `DEPUTADO`, `DEPUTADA`, `DR`, `DRA`,
  `DOUTOR`, `DOUTORA`, `PASTOR`, `PASTORA`, `PR`, `DELEGADO`, `DELEGADA`, `CORONEL`, `CEL`,
  `PROFESSOR`, `PROFESSORA`, `PROF`, `PROFA`, `CAPITAO`, `MAJOR`, `SARGENTO`, `SGT`,
  `GENERAL`, `TENENTE`, `SUBTENENTE`). Two names match when any key of one equals any key of
  the other, so a title on one side only does not stop a match.
- **Names of a candidacy:** `NM_URNA_CANDIDATO` and `NM_CANDIDATO` of each t0 deputy
  candidacy, and, from the Chamber's list, the parliamentary name (`nome`) of each deputy of
  the legislature elected at t0 (Chamber legislature 55, 56, 57 for A, B, C) whose civil
  name (`nomeCivil`) matches the `NM_CANDIDATO` of exactly one t0 deputy candidacy. Chamber
  rows matching none or several are left out and counted. The Chamber file has no CPF and
  no state of election, so this bridge is by name only.
- **Matching:** an author matching exactly one t0 deputy candidacy is that deputy. Matching
  several, only those in the author's top state (the `UF Favorecido` that received most of
  the author's money in the windows; empty and `-1` left out) are kept, and exactly one left
  makes a deputy (`ties_broken`). Otherwise the author is ambiguous, so unmatched.
- **Senators:** an author who is not a deputy and matches exactly one senate seat by the same
  rules is a senator. The seats are the elected senate candidacies (`CD_CARGO` 5, codes 1-3)
  at t0 and t0-4 and the substitutes (`CD_CARGO` 9 and 10) on their tickets (same election,
  state and `NR_CANDIDATO`): a substitute who took the seat writes amendments as a senator.
  Senators have no row.
- **Counts** (`author_link.parquet`, per cycle): `authors` (current-legislature authors),
  `deputies`, `senators`, `ambiguous` (several deputy candidacies left after the state rule),
  `unmatched` (neither deputy nor senator; it includes the ambiguous ones that are not
  senators), `ties_broken`, `non_current_authors`, `chamber_links` (Chamber names added to a
  candidacy) and `money_share` = value paid in the windows by the authors linked as deputies
  / (value paid in the windows by current-legislature authors - value of the senators);
  null if that is 0. Values are sums of `Valor Recebido`, every recipient included.
- **t0 to t1:** a deputy's t0 candidacy is linked to a t1 deputy candidacy of the same state
  by CPF, in memory only. A CPF that is empty or not 11 digits is unlinked.

No CPF, voter ID, name or favorecido code, and no hash of one, is written to any column, note
or exception message.

## Recipient municipality

(`UF Favorecido`, normalised `Município Favorecido`) is matched to (`uf`, normalised
`name_ibge`). Rows with no municipality have no row in the panel and are counted per year: an
empty municipality (state or federal recipients), or CGU's placeholder for a recipient it does
not identify, a normalised `Município Favorecido` of exactly `SEM INFORMACAO` with a stripped
`UF Favorecido` of "" or "-1" (mostly Pix transfers of national, state-wide or
multi-municipality amendments). `Sem informação` with a real UF still names a municipality. Of
the rows that name a municipality, those that match nothing have no row either, are counted per
year, and stop the build if they exceed 2% in a year. Only individual payments inside a window
of a cycle are checked.

## Columns

One row per (`cycle`, `deputy`, `cd_ibge`) for municipalities in the deputy's t0 state whose
mayoral deciding round at m (round 2 where there was one, else round 1) had a finalist with the
deputy's t0 `nr_partido`. The finalists are the two candidacies with most votes, ties broken
by `sq_candidato`. Mayoral votes are `qt_votos_nominais_validos` on rows whose destination is
`Válido` (m is 2016 or later), as in `explore/0003_mayor_power.py`.

| Column | Type | Meaning |
| --- | --- | --- |
| `cycle` | text | `A`, `B` or `C` |
| `m`, `t0`, `t1` | int | the years of the cycle |
| `cd_ibge` | text | 7-digit IBGE code |
| `uf` | text | state letters (the deputy's state) |
| `deputy` | text | t0 `sq_candidato` |
| `deputy_party` | text | t0 `nr_partido` (party number, not the acronym) |
| `deputy_elected` | bool | the t0 candidacy was elected |
| `population_m` | int | `populacao` in year m; null if missing |
| `round` | int | 1 or 2: the deciding round |
| `n_mayor_cands` | int | round-1 mayoral candidacies with votes above 0 |
| `margin` | float | (votes of the deputy's party's finalist - the other finalist's) / valid votes of the deciding round |
| `win` | bool | `margin` > 0 |
| `fin_female` | bool | the party's finalist has `cd_genero` "4" |
| `fin_age` | int | whole years from `dt_nascimento` to the election date; null if the date is null |
| `fin_higher_ed` | bool | the party's finalist has `cd_grau_instrucao` "8" |
| `party_held_mayor` | bool | the deputy's party had the top candidacy of the deciding round at m-4; false if no result |
| `amend_pre_total`, `amend_pre_pix` | float | reais, nominal: individual payments (all, and Pix only) in the pre window, net of negative rows; 0 where none or where the net is below 0 |
| `n_pay_pre` | int | payment rows in the pre window |
| `amend_post_total`, `amend_post_pix` | float | the same in the post window |
| `n_pay_post` | int | payment rows in the post window |
| `amend_pre_share`, `amend_post_share` | float | the window's total here (floored at 0) / the sum over every municipality the deputy paid in the window, any state, of its total floored at 0 (payments with an identified municipality only); null where that sum is 0 (counted, the row stays) |
| `amend_pre_log_pc`, `amend_post_log_pc` | float | ln(1 + the window's total here, floored at 0, / `population_m`): reais per inhabitant, with the population the 0009 per-capita measure uses; null if `population_m` is null or 0 |
| `votes_t0` | int | the deputy's votes in the municipality at t0; 0 if none |
| `valid_t0` | int | votes of all deputy candidacies in the municipality at t0 |
| `share_t0` | float | `votes_t0` / `valid_t0` |
| `ran_t1` | bool | linked to a t1 deputy candidacy with statewide votes above 0 |
| `votes_t1`, `valid_t1`, `share_t1` | int, int, float | the same at t1; null if `ran_t1` is false |
| `d_share` | float | `share_t1` - `share_t0`; null if `ran_t1` is false |
| `party_share_t0`, `party_share_t1` | float | valid votes (nominal plus party list) of the deputy's party, or of its federation where it is in one that year, for federal deputies in the municipality at t0 and t1, over the valid votes of every party for federal deputies there; null where the municipality has none |
| `state_party_share_t0`, `state_party_share_t1` | float | the same for state deputies (`CD_CARGO` 7) |

**Party vote shares (v3).** From `tse_general_parties`, round 1, summed over zones and over the
coalition records a party can appear under in one zone. A party's valid votes are
`QT_VOTOS_NOMINAIS_VALIDOS` + `QT_TOTAL_VOTOS_LEG_VALIDOS` (2018 on) or `QT_VOTOS_NOMINAIS` +
`QT_VOTOS_LEGENDA` (2014). The party is the deputy's t0 `nr_partido`, followed to the year's
number through the mergers in `src/terrain/parties.py` (at t1 of cycle B, DEM and PSL are União
Brasil, 44); the deputy's own t1 party is not used, so a deputy who changed party still has
the t0 party's share. A federation is read from `NR_FEDERACAO` of the year's file (2022 and
2026); its parties' votes count together. These shares do not depend on `ran_t1`.

**Negative payments.** CGU lists refunds and reversals as payment rows with a negative
`Valor Recebido`. They stay in the sums, so they reduce a deputy's total in a municipality.
After summing, a row whose `amend_pre_total`, `amend_pre_pix`, `amend_post_total` or
`amend_post_pix` is below 0 has that column set to 0. The rows set to 0 are counted per cycle
and column (both halves) in the notes. `n_pay_pre` and `n_pay_post` count negative rows too.

Votes at t0 and t1 are `QT_VOTOS_NOMINAIS_VALIDOS` where the file has it (2018 and later), else
`QT_VOTOS_NOMINAIS` (2014), round 1, summed over zones. Rows whose TSE municipality is not in
`municipalities` (votes abroad, `SG_UF` `ZZ`) are dropped and counted.

## Checks the build enforces

Each raises `BuildError` with counts only, before anything is uploaded.

1. A duplicate (`cycle`, `deputy`, `cd_ibge`).
2. `margin` outside [-1, 1], or `win` not equal to `margin` > 0.
3. A share (`share_t0`, `share_t1`, `amend_pre_share`, `amend_post_share`, and the four party
   shares) outside [0, 1], a
   payment column below 0 (checked after the floor at 0, as a guard), or `amend_pre_log_pc`
   or `amend_post_log_pc` below 0.
4. Fewer than 5,000 or more than 300,000 rows in a cycle.
5. The earliest payment month of the CGU file after 2015-01, or the latest before 2026-09.
6. No individual Pix payment from 2020-01 on.
7. More than 2% of the rows naming a municipality failing to match, in any year. A row with an
   empty municipality, or with `Sem informação` and a UF of "" or "-1" (CGU's placeholder), names
   no municipality; `Sem informação` with a real UF names one and counts if it fails.
8. No encoding (UTF-8, then Latin-1) that gives the header of either CGU member, or an
   `Ano/Mês` in none of the three formats, or a `Valor Recebido` that is not a Brazilian
   decimal number, or an `Ano da Emenda` that is not a four-digit year on a row whose
   `Código da Emenda` is a number.
9. In a mayoral year, no candidate with `cd_genero` "4" or no candidate with `cd_grau_instrucao`
   "8" (the codes would have changed).

It also stops if an input lacks a column it needs, does not match its manifest SHA-256, if a
municipality is in both exploration lists, if a `cd_tse` repeats in `municipalities`, if two
municipalities share a state and a normalised name, if a t0 candidacy appears twice, or if a
legislature number of the Chamber file is not an integer. It also stops on a party-vote count
that is not an integer, or a party in two federations of one year.

## Manifest notes

Per cycle: rows and deputies (exploration-half rows only); the author link counts; unlinked
CPFs; t0 deputies whose party number has no first-round mayoral candidate at m (mergers); vote
rows dropped (abroad, other); the rows whose payment columns were set to 0, per column (both
halves); `<cycle>_link`: `money_share`, `money_share_with_unidentified` (the same with the
unidentified author's value added to the denominator), the value sums behind them (BRL), and
the rows and value left out with non-current authors and with the unidentified author;
`<cycle>_chamber`: Chamber rows of the legislature, names added, rows matching no candidacy
and rows matching several; `<cycle>_outcome_nulls`: null rows of each share and log outcome
(both halves); `<cycle>_party_shares`: null rows of each party share (both halves) and the
party groups of the cycle's deputies with no federal-deputy votes anywhere at t0 or t1 (a merger
missing from `parties.MERGERS` would show here). Per party-vote year: rows read, rows abroad
or with no municipality, and the federations with their parties. Then the dropped recipient
rows per year (no municipality, placeholders included; no
match); per year, the placeholder rows, their value (BRL, sum of `Valor Recebido`) and its
share of the year's value; per year, the individual payment rows of the whole CGU file with a
negative `Valor Recebido` and their sum (BRL); per year, the 10 most frequent unmatched (UF,
normalised municipality name) pairs with their row counts; the first and last payment
months, and the CGU rows without a payment month; the amendment rows without a
`Código da Emenda`, the codes with several years, and the individual payment rows whose
amendment has no year. Notes name municipalities only, never a
`Favorecido` or `Código do Favorecido`.
