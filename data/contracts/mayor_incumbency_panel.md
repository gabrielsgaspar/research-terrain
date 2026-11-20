# mayor_incumbency_panel

One row per municipality, mayoral election e (2004, 2008, 2012, 2016, 2020) and finalist party:
the race, what happened four years later, the party's federal bench in the state and the
individual amendment money the municipality received in the term. Idea 0011, decisions 0003
and 0011. Built by `src/terrain/builds/mayor_incumbency_panel.py` (owner PR "mayoral
incumbency panel"; run in campaign 0012 step s1).

## Inputs

- `tse_results` (build): `candidate_votes_<year>.parquet` and `turnout_<year>.parquet` for
  2000-2024 (e-4, e and e+4). Mayor is `cd_cargo` 11.
- `tse_candidates` (build): `nr_partido`, `cd_genero`, `dt_nascimento`, `cd_grau_instrucao`,
  `dt_eleicao`, `nr_cpf_candidato`, `nr_titulo_eleitoral_candidato`, keyed by (`ano_eleicao`, `cd_eleicao`, `sg_ue`,
  `sq_candidato`).
- `tse_parties` (build): `coalitions_<year>.parquet` of each e+4, `nr_partido` and
  `nr_federacao` only (federations at e+4; only 2024 has any).
- `municipalities` (build): `cd_ibge`, `cd_tse`, `uf`, `name_ibge`.
- `ibge_population_annual` (acquire): `ano`, `id_municipio`, `populacao`.
- `tse_general` (acquire): `consulta_cand_<year>.zip` for 2010, 2014 and 2018 (the bench);
  only `SG_UF`, `CD_CARGO`, `NR_PARTIDO`, `CD_SIT_TOT_TURNO` and `NR_FEDERACAO`.
- `cgu_amendments` (acquire): `EmendasParlamentares_PorFavorecido.csv`, read as
  `amendments_panel` reads it (`data/contracts/amendments_panel.md`). `Código do Favorecido`
  and `Favorecido` are never read.
- The two exploration lists (`data/derived/split/`).

## Output and split

`panel_<election>.parquet`, sorted by `cd_ibge` and `party`. Rows of exploration-half
municipalities (either list) go to `data/derived/mayor_incumbency_panel/<hash>/`. Every other
row goes only to `sealed/outcomes/mayor_incumbency_panel/<hash>/`, which the build creates in
and never reads. `<hash>` is `content_hash` of the sorted input SHA-256s, the SHA-256s of the
two lists, the elections and the source of this build and of the `terrain` modules it imports
(`amendments_panel`, `parties`, `explore`, `place_outcomes`, `cell_outcomes`,
`polling_place_tenure`). The manifest lists the derived files in `files` and the sealed files
in `sealed_files`.

## Races

The main election of a year is the round-1 `cd_eleicao` with the most mayoral rows. The
deciding round is round 2 (`nr_turno` 2 under the main `cd_eleicao` or the next one, as
different years code it) where the municipality had one, else round 1. Supplementary
elections are left out.

A candidacy's votes are summed over zones from rows whose `nm_tipo_destinacao_votos` is null
(2000-2012) or exactly `Válido` (2016 on; annulled votes are left out). The count is
`qt_votos_nominais_validos`, or `qt_votos_nominais` where that is null (the 2000 file holds the
votes in the valid column and 0 in the other; 2004-2012 have no valid column).

The finalists are the two candidacies with most votes in the deciding round (ties broken by
`sq_candidato`), in municipalities with at least two candidacies with votes and valid votes
above 0 (`qt_total_votos_validos` of the deciding round). A race whose finalists lack a party
(the candidacy is not in `tse_candidates`) or share one has no rows; both are counted. The
winner of a year is the top candidacy of the deciding round, in every municipality (also with
one candidate).

## Parties across elections

Party numbers are followed from one election to a later one through the mergers in
`src/terrain/parties.py` (`successor`): for example PHS (31) is Podemos (19) from 2019, DEM
(25) and PSL (17) are União Brasil (44) from 2022, PTB (14) and Patriota (51) are PRD (25) from
2023, and Podemos takes PSC's number (20) when it absorbs PSC in 2023. Renames keep the number
and need nothing. Where the e+4 coalition file shows a federation (2024), its parties count as
one (`F` and the federation number).

## Linking a finalist across elections

A finalist is the same person as a candidacy of e-4 or e+4 in the same municipality if their
CPF (`nr_cpf_candidato`, exactly 11 digits after trimming spaces) or their título eleitoral
(`nr_titulo_eleitoral_candidato`, exactly 12 digits) is the same. Neither is padded or
otherwise recoded. Both are needed: the 2024 file holds no CPF at all (TSE withholds it), and
the 2012 file holds some CPFs without their leading zeros, while the título is complete in
both. The keys exist in memory only: they are never written to a column, note or message, and
no hash of one is kept.

## Columns

| Column | Type | Meaning |
| --- | --- | --- |
| `election` | int | e |
| `cd_ibge` | text | 7-digit IBGE code |
| `uf` | text | state letters |
| `party` | text | the finalist's `nr_partido` at e |
| `round` | int | 1 or 2: the deciding round |
| `margin` | float | (the finalist's votes - the other finalist's) / valid votes of the deciding round |
| `win` | bool | `margin` > 0 |
| `fin_female` | bool | `cd_genero` "4" |
| `fin_age` | int | whole years from `dt_nascimento` to the election date; null if either is null |
| `fin_higher_ed` | bool | `cd_grau_instrucao` "8" |
| `party_held_mayor_lag` | bool | the party (followed through mergers) had the winner at e-4; false where there was no e-4 result |
| `population_e` | int | `populacao` in year e; null if missing |
| `ln_pop` | float | ln(`population_e`); null if it is null or 0 |
| `n_mayor_cands` | int | round-1 mayoral candidacies with votes above 0 |
| `bench_fed` | int | federal deputies elected for the party in the state at the general election two years before e (2010 for 2012, 2014 for 2016, 2018 for 2020), each deputy's party followed through mergers to e, a federation's parties counted together where the file shows one; 0 if none; null for 2004 and 2008 |
| `party_next` | text | the party at e+4 (its number after mergers, or `F<number>` for its federation) |
| `party_runs_next` | bool | `party_next` (any party of the federation) had a round-1 mayoral candidacy with votes at e+4 |
| `party_wins_next` | bool | it had the winner at e+4 |
| `finalist_runs_next` | bool | the finalist (by CPF or título) had a round-1 mayoral candidacy with votes at e+4 |
| `finalist_wins_next` | bool | the finalist (by CPF or título) was the winner at e+4 |
| `finalist_eligible` | bool | the finalist (by CPF or título) did not win at e-4 (so no term limit at e+4) |
| `amend_after_total`, `amend_after_pix` | float | reais, nominal: individual amendment payments (every author, Pix only for the second) to the municipality from January of e+1 to September of e+4; null where the CGU file does not cover that whole window (2004, 2008 and 2012) |

### Null rules

- The four `*_next` columns are null where the municipality had no round-1 mayoral election
  at e+4. The finalist ones are also null where the finalist has neither an 11-digit CPF nor
  a 12-digit título; `finalist_eligible` is null then too.
- Amendments follow `amendments_panel`: individual amendments only (`Tipo de Emenda` starting
  with `EMENDA INDIVIDUAL`; Pix contains `TRANSFERENCIAS ESPECIAIS`), by payment month, the
  recipient matched to a municipality by state and normalised name, CGU's placeholder for an
  unidentified recipient left out. Negative rows are summed with the rest; a municipality
  whose total is below 0 is set to 0 and counted. Every author counts: there is no author
  link, so the legislature rule of `amendments_panel` (which decides which authors are
  linked to deputies) does not apply.

## Checks the build enforces

Each raises `BuildError` with counts only, before anything is uploaded. The checks marked
with a profile write their row counts with `terrain.profile.write_profile` first.

1. A race without exactly two rows, whose margins do not add to 0, or with other than one
   winner (none for a tie) (profile `two_rows_per_race`).
2. `margin` outside [-1, 1], or `win` not equal to `margin` > 0.
3. Fewer than 5,000 or more than 5,600 races in an election (both halves; profile
   `races_per_election`).
4. A general election with other than 513 elected federal deputies (`CD_SIT_TOT_TURNO` 1 or 5
   in 2010; 1, 2 or 3 from 2014; profile `federal_bench`).
5. `party_wins_next` without `party_runs_next`, or `finalist_wins_next` without
   `finalist_runs_next`.
6. A payment column below 0 (after the floor, as a guard).
7. A text column holding an 11- or 12-digit number (a CPF or título never leaves memory), or
   columns that differ from the table above.
8. In an election year, no mayoral candidate with `cd_genero` "4" or `cd_grau_instrucao` "8".
9. Fewer than 98% of a year's round-1 mayoral candidacies with votes (2000-2024, both halves)
   having a CPF or a título to link by: a year published without identifiers would otherwise
   read as "the finalist did not run" (profile `linkable_candidacies`).
10. The CGU rules of `amendments_panel`: the payment-month range and the Pix check, an
   `Ano/Mês` or `Valor Recebido` that cannot be read, and more than 2% of the rows naming a
   municipality failing to match in a year.

It also stops if an input lacks a column it needs or does not match its manifest SHA-256, if
a municipality is in both exploration lists, if a `cd_tse` repeats in `municipalities`, if two
municipalities share a state and a normalised name, or if a party is in two federations of
one election.

## Manifest notes

Per election (`E<e>`): races and rows of the exploration half, races of both halves, races left
out (a finalist without party; both finalists of one party), municipalities with one candidate,
ties, exploration-half finalists with neither key (`unlinkable_finalists`), rows with no
election at e+4 and with no population, the bench year and the amendment window (or `none`);
`E<e>_floored_to_zero` (both halves); `E<e>_parties_without_candidates_next`, the finalist
parties of e, followed to e+4, with no mayoral candidacy anywhere at e+4 (a merger missing from
`parties.MERGERS` would show here); `E<e>_federations_next`. Then the elected federal deputies
of each bench year; `keys_<year>`, the round-1 mayoral candidacies of each year read (both
halves) with a CPF, with a título and with neither; and the recipient notes of
`amendments_panel` (rows with no municipality, unmatched rows, placeholders, the top unmatched
names, the first and last payment months).
Counts and party numbers only; never a statistic of an outcome.
