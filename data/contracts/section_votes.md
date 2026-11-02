# section_votes

Votes by section for the Legal Amazon, linked to candidacies, one Parquet per
state and year: `section_votes_<year>_<uf>.parquet`, 2004 to 2024. Built by
`src/terrain/builds/section_votes.py`; written to
`data/derived/section_votes/<hash>/`, where `<hash>` is `content_hash` of the
sorted input SHA-256s (the section zips, the `candidate_votes` Parquets of
`tse_results` and `municipalities.parquet`), the years and the build code. The
build imports no other data-handling `terrain` module.

**Votes cast, not votes counted.** Section votes include votes for candidacies
that were later annulled (registration refused or cancelled); the results file
shows 0 for them. Those rows are kept and flagged `annulled_in_results`. Any
analysis of vote margins must use counted votes (`tse_results`
`candidate_votes`), never these rows summed.

## Sources

- `votacao_secao_<year>_<uf>.zip` from the `tse_votes_by_section` acquire
  manifest, read one state-year at a time. Only the columns below are read.
  2000 is skipped and named in the manifest notes: it has no polling-place IDs
  and covers 93 of 143 municipalities in Pará.
- `candidate_votes_<year>.parquet` of the `tse_results` build: counted votes per
  candidacy, used to find `sq_candidato` before 2024 and to flag annulled votes.
- The built `municipalities` table: `cd_ibge`, `cd_tse` and `legal_amazon`. Rows
  of municipalities outside the Legal Amazon (parts of MA, MT and TO) are
  dropped and counted in the notes.

## Columns

One row per key below, sorted by it.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano_eleicao`, `cd_eleicao`, `nr_turno` | int | election year, election code, round |
| `sg_ue` | text | 5-digit TSE municipality code |
| `nr_zona`, `nr_secao` | text | zone and section, as in the file |
| `cd_cargo` | text | office code (11 mayor, 13 councillor) |
| `nr_votavel` | int | number voted for |
| `cd_ibge` | text | 7-digit IBGE code, from `sg_ue` = `cd_tse` |
| `nr_local_votacao` | int | polling-place number (join to `polling_places` on `ano`, `cd_ibge`, `nr_zona`, `nr_local_votacao`) |
| `qt_votos` | int | votes cast |
| `vote_type` | text | `candidate`, `legend`, `blank`, `null` or `annulled` |
| `sq_candidato` | text | candidacy; null unless `vote_type` is `candidate`, or when no candidacy matched |
| `annulled_in_results` | bool | true for candidate votes whose candidacy has 0 counted votes in `candidate_votes` but votes in the sections |

Key: (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `nr_zona`, `nr_secao`, `cd_cargo`,
`nr_turno`, `nr_votavel`). Before 2012 `sq_candidato` repeats across
municipalities, so a candidacy is (`cd_eleicao`, `sg_ue`, `sq_candidato`).
`sg_ue`, `nr_zona`, `nr_secao`, `cd_cargo` and `sq_candidato` keep their leading
zeros. Rows whose `ano_eleicao` is not the file's election year (a later
supplementary election) are dropped and counted.

## vote_type

By `nr_votavel`: 95 `blank`, 96 `null`, 97 `annulled`. A two-digit number in a
councillor race (`cd_cargo` 13) is a party and `legend`. Everything else is
`candidate`, including two-digit mayoral numbers: mayors run under their party
number.

## sq_candidato

- 2024: the file's own `SQ_CANDIDATO` (`-1` and other missing codes become null).
- Before 2024 the files have none. Match (`cd_eleicao`, `sg_ue`, `cd_cargo`,
  `nr_turno`, number) to `candidate_votes` (`nr_candidato`), summed over zones.
  When a number has several candidacies (substitutions) take the one with the
  most counted votes; a tie goes to the smallest `sq_candidato`. Numbers with
  more than one voted candidacy are counted in the notes.

## Checks the build enforces

Each raises `BuildError` with counts only, before anything is uploaded.

- The key is unique in every file.
- Per year, among candidacies with counted votes above 0, at least 99% have
  section sums equal to them (parameter `min_agree_share`).
- Per year, candidate numbers left without a candidacy are under 0.5% of
  distinct candidate numbers, not rows (parameter `max_unmatched_share`).
- Every key column is non-empty; years, round, polling-place number, candidate
  number and votes are integers.
- Each downloaded file matches the SHA-256 in its manifest, and
  `municipalities.parquet` does not repeat a `cd_tse`.

A candidacy with 0 counted votes and votes in the sections is not a failure: it
is flagged and counted.

## Notes

The manifest `notes` give, per year: rows, the share of candidacies whose
section sums equal the counted votes (`agree/total`), annulled candidacies,
unmatched candidate numbers over all numbers, numbers with several voted
candidacies, rows outside the Legal Amazon and rows of other election years,
plus the skipped years.
