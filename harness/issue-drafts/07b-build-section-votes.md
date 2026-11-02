# Task: build section votes linked to candidacies, Legal Amazon, 2004-2024

## Goal

Votes by section for the Legal Amazon, with each section's polling place and,
for votes cast for a candidate, the candidacy key, so strongholds can be
built from them.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md`. Read "Keys and
joins" and "Geography" in `data/fixtures/tse/README.md` first.

## What the real files contain (checked 2026-11-02)

- (`cd_eleicao`, `sg_ue`, `nr_zona`, `nr_secao`, `cd_cargo`, `nr_turno`,
  `nr_votavel`) is unique (Pará: 1,049,310 rows in 2008, 1,555,659 in 2024).
- `sq_candidato` is present only from 2024. Numbers 95, 96 and 97 are blank,
  null and annulled votes; two-digit numbers are party (legend) votes.
- Section votes are votes cast; the results file's `qt_votos_nominais` are
  votes counted. For candidates whose votes were annulled (registration
  refused or cancelled), the results file shows 0 while the sections show
  the votes cast: 256 such candidates in Pará in 2012, none in 2004.
- For candidates with votes in the results file, section sums equal them in
  Pará for 11,861 of 11,902 in 2004 (99.7%), 11,488 of 11,488 in 2008, 14,689
  of 14,689 in 2012, 18,036 of 18,036 in 2016, 20,582 of 20,582 in 2020 and
  15,763 of 15,763 in 2024.
- No candidate number belongs to more than one candidacy in a municipality,
  office and round in Pará in any of these years, but keep the rule below
  for other states.
- 2000 has no polling-place IDs and covers 93 of 143 municipalities in Pará.

## In scope

- `src/terrain/builds/section_votes.py` and
  `pipeline/build/section_votes.py`. Inputs:
  `data/manifests/acquire/tse_votes_by_section.json`,
  `data/manifests/build/tse_results.json` (candidate votes) and
  `data/manifests/build/municipalities.json`.
- Years 2004-2024. Skip 2000 and say so in the manifest notes.
- Output `data/derived/section_votes/<hash>/section_votes_<year>_<uf>.parquet`,
  one file per state and year: the key above plus `cd_ibge`,
  `nr_local_votacao`, `qt_votos`, `vote_type` (`candidate`, `legend`,
  `blank`, `null`, `annulled`), and the candidacy key (`sq_candidato`) for
  candidate votes. Before 2024, get it by matching (`sg_ue`, `cd_cargo`,
  `nr_turno`, `nr_votavel`) to `candidate_votes`, choosing the candidacy
  with votes when a number has several; count numbers left unmatched.
- Add `annulled_in_results` (boolean): true for candidate votes whose
  candidacy has 0 nominal votes in `candidate_votes` but votes in the
  sections. Keep those rows; analyses of vote margins must use counted votes.
- Checks the build enforces: the key is unique; per year, among candidates
  with `qt_votos_nominais` > 0 in `candidate_votes`, at least 99% have
  section sums equal to it, with the share in the notes; candidates with 0
  in the results but votes in the sections are counted in the notes, never a
  failure; unmatched candidate numbers under 0.5% of candidate numbers (not
  rows).
- Memory: read one state-year file at a time (Pará 2024 alone is 1.6
  million rows); never hold more than one in memory.
- `data/contracts/section_votes.md` and `tests/test_build_section_votes.py`.

Expected files (four): `src/terrain/builds/section_votes.py`,
`pipeline/build/section_votes.py`, `data/contracts/section_votes.md`,
`tests/test_build_section_votes.py`.

The output path hashes this build's code and every data-handling `terrain`
module it imports, with input SHA-256s sorted (AGENTS.md).

## Out of scope

- Coordinates (they are in `polling_places`, task 07a; join later on
  `ano`, `cd_ibge`, `nr_zona`, `nr_local_votacao`); strongholds.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`.

## Done when

1. From the 2024 fixtures, every candidate vote carries `sq_candidato`; in
   the 2008 fixtures it comes from the results match.
2. `vote_type` is set correctly for 95, 96, 97, a two-digit number and a
   candidate number.
3. A test where one number has two candidacies picks the one with votes.
4. The vote-sum check passes on a small consistent input built in the test
   and raises once more than 1% of candidates with results votes disagree;
   a candidate with 0 in the results and votes in the sections is flagged
   `annulled_in_results`, counted, and does not count as a disagreement. (Fixtures hold two
   sections per town, so their sums do not equal the town's results.)
5. A 2000 input is skipped and noted, not dropped silently.
6. Test inputs are deterministic; no test touches the network or GCS.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
