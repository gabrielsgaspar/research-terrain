# Task: build candidate votes and turnout (Parquet), 2000-2024

## Goal

Clean tables of votes per candidacy and of turnout, by municipality, zone,
office and round, for every municipal election from 2000 to 2024, joined to
the candidates table and the municipalities table.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md` (close races need vote
margins). Read "Keys and joins" in `data/fixtures/tse/README.md` first.

## In scope

- `src/terrain/builds/tse_results.py` and `pipeline/build/tse_results.py`,
  following `pipeline/README.md`. Inputs:
  `data/manifests/acquire/tse_results.json` (only the
  `votacao_candidato_munzona_*` and `detalhe_votacao_munzona_*` zips),
  `data/manifests/build/tse_candidates.json` and
  `data/manifests/build/municipalities.json`.
- Reuse `snake`, `MISSING`, `read_header` and the member-reading helpers by
  importing them from `terrain.builds.tse_candidates`. Do not modify that
  module: its code is part of its output path's hash.
- The output path hashes this build's code and
  `src/terrain/builds/tse_candidates.py` (whose helpers it uses), with input
  SHA-256s sorted.
- Read only each zip's `*_BRASIL.csv`, one year at a time.
- Outputs under `data/derived/tse_results/<hash>/`, one file per year:
  - `candidate_votes_<year>.parquet`: one row per candidacy, round and zone.
    Key (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `sq_candidato`, `nr_turno`,
    `nr_zona`); also `cd_ibge`, `cd_tipo_eleicao`, `cd_cargo`,
    `nr_candidato`, party fields, `qt_votos_nominais`,
    `qt_votos_nominais_validos` (null where a year lacks it, as 2008 does),
    `cd_sit_tot_turno`, and `matched` (whether the key is in the candidates
    table).
  - `turnout_<year>.parquet`: one row per (`ano_eleicao`, `cd_eleicao`,
    `sg_ue`, `nr_zona`, `cd_cargo`, `nr_turno`) with `cd_ibge` and every
    count column the year has (eligible voters, turnout, abstentions, valid,
    blank, null votes).
- Checks the build enforces: rows per file equal the `BRASIL` rows; both
  keys unique (they are, in every year); every row has a `cd_ibge`;
  unmatched candidacies under 0.1% of a year's rows (the real counts are 3
  SQs in 2000, 140 in 2008, 4 in 2012).
- A consistency report in the manifest notes, not a failure: per year, the
  share of municipality-office-rounds where candidates' valid votes equal
  turnout's valid nominal votes (Pará: 287/287 in 2008, 286/290 in 2024).
- Election type from `cd_tipo_eleicao`, office from `cd_cargo`; never from
  labels, which change across years.
- Memory: runners have 16 GB and 14 GB of disk. Read one zip member at a
  time without extracting; hold one year in memory.
- `data/contracts/tse_results.md` and `tests/test_build_tse_results.py`.

Expected files (four): `src/terrain/builds/tse_results.py`,
`pipeline/build/tse_results.py`, `data/contracts/tse_results.md`,
`tests/test_build_tse_results.py`.

## Out of scope

- Party votes and coalitions (task 06b), section votes (07b).
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`, `src/terrain/builds/tse_candidates.py`.

## Done when

1. From the fixtures, 25 of the 27 `candidate_votes` rows per year (2000 and
   2024) match a candidacy, 2 do not, and the unmatched count is in the
   notes.
2. Two 2000 rows with the same `sq_candidato` in different municipalities
   stay distinct.
3. The consistency report counts a match on a small input built in the test
   where votes and turnout agree, and a mismatch when one count changes.
4. A test shows `ELEIÇÃO SUPLEMENTAR` and `ELEIÇÃO EXTRAORDINÁRIA` rows both
   kept, identified by `cd_tipo_eleicao`.
5. The row-count, key, `cd_ibge` and match-share checks each raise on broken
   input built in the test.
6. Test zips use a fixed timestamp; no test touches the network or GCS.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
