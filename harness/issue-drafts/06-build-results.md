# Task: build election results tables (votes, party votes, turnout, coalitions)

## Goal

Clean Parquet tables of municipal election results for 2000-2024 that join
to the candidates table and to the municipalities table.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md` (close races need
vote margins within lists). Read "Keys and joins" in
`data/fixtures/tse/README.md` first.

## In scope

- `src/terrain/builds/tse_results.py` and `pipeline/build/tse_results.py`.
  Inputs: `data/manifests/acquire/tse_results.json`, plus the latest
  `tse_candidates` and `municipalities` build manifests in
  `data/manifests/build/`.
- Read only the `*_BRASIL.csv` member of each zip, year by year, with the
  same missing-value rules as the candidates build (reuse its helpers).
- Outputs under `data/derived/tse_results/<hash>/`:
  - `candidate_votes.parquet`: one row per candidacy, round and zone, with
    the candidacy key (`ano_eleicao`, `cd_eleicao`, `sg_ue`,
    `sq_candidato`), `cd_ibge`, `nr_turno`, `nr_zona`, `cd_cargo`,
    `nr_candidato`, party and coalition fields, `qt_votos_nominais`,
    `qt_votos_nominais_validos` (null where a year lacks it),
    `cd_sit_tot_turno`;
  - `party_votes.parquet`: one row per party, round and zone, with legend
    and nominal valid votes;
  - `turnout.parquet`: one row per municipality, zone, office and round
    (eligible voters, turnout, abstentions, valid, blank, null votes);
  - `coalitions.parquet`: one row per party in each coalition or
    federation, per election and office.
- Checks the build enforces: rows per file equal the `BRASIL` rows; every
  row maps to a `cd_ibge`; the share of `candidate_votes` rows without a
  matching candidacy is under 0.1% per year (it is about 0.02% in 2008),
  and the count is written in the manifest notes.
- A consistency report, not a failure: per year, the share of
  municipality-office-rounds where candidates' valid votes equal the
  turnout file's valid nominal votes (in Pará: 287/287 in 2008, 286/290 in
  2024), written in the manifest notes.
- `data/contracts/tse_results.md`.
- Memory and disk: GitHub runners have 16 GB of memory and 14 GB of disk.
  Read one zip member at a time without extracting to disk, and never hold
  more than one year in memory; write Parquet partitioned by year.

## Out of scope

- Section-level votes and polling places (task 07).
- Any analysis, including vote margins.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`.

## Done when

1. From the fixtures, 25 of the 27 `candidate_votes` rows per year match a
   candidacy and 2 do not, and the unmatched count appears in the notes.
2. The consistency report counts a match on a small input built in the
   test where votes and turnout agree, and a mismatch when one vote count
   is changed. (The fixtures hold only part of each town's candidates, so
   their totals do not agree.)
3. 2000 rows with the same `sq_candidato` in different municipalities stay
   distinct.
4. Election type comes from `cd_tipo_eleicao`; a test shows `ELEIÇÃO
   SUPLEMENTAR` and `ELEIÇÃO EXTRAORDINÁRIA` rows are both kept.
5. Coalition rows are one per party, parsed from the files' own party
   columns, not by splitting `DS_COMPOSICAO_COLIGACAO`.
6. The row-count, mapping and match-share checks raise on broken input.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
