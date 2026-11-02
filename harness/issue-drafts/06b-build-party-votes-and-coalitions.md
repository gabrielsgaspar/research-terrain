# Task: build party votes and coalition membership (Parquet), 2000-2024

## Goal

Votes per party (legend and nominal) by municipality, zone, office and round,
and one row per party in each coalition or federation, so that within-list
competition can be measured.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md`: close races are
decided within lists (coalitions until 2016, parties and federations from
2020). Read `data/fixtures/tse/README.md` first.

## What the real files contain (checked 2026-11-02)

- In `votacao_partido_munzona`, a party can appear twice in the same zone,
  office and round under two coalition records (one usually with zero
  votes): 960 such rows in 2016 and 160 in 2024. The key is (`ano_eleicao`,
  `cd_eleicao`, `sg_ue`, `nr_zona`, `cd_cargo`, `nr_turno`, `nr_partido`,
  `sq_coligacao`), unique in every year.
- `consulta_coligacao` has one row per party in each coalition: key
  (`ano_eleicao`, `cd_eleicao`, `sg_ue`, `cd_cargo`, `sq_coligacao`,
  `nr_partido`), unique in every year. Federation columns (`nr_federacao`,
  `sg_federacao`, `ds_composicao_federacao`) exist from 2024.

## In scope

- `src/terrain/builds/tse_parties.py` and `pipeline/build/tse_parties.py`.
  Inputs: `data/manifests/acquire/tse_results.json` (only the
  `votacao_partido_munzona_*` and `consulta_coligacao_*` zips) and
  `data/manifests/build/municipalities.json`.
- Reuse the helpers in `terrain.builds.tse_candidates` by importing them; do
  not modify that module.
- The output path hashes this build's code and
  `src/terrain/builds/tse_candidates.py`, with input SHA-256s sorted.
- Outputs under `data/derived/tse_parties/<hash>/`, one file per year:
  `party_votes_<year>.parquet` and `coalitions_<year>.parquet`, with
  `cd_ibge` on both.
- Coalition membership comes from each row's own party columns, never from
  splitting `ds_composicao_coligacao`.
- Checks the build enforces: rows per file equal the `BRASIL` rows; both
  keys unique; every row has a `cd_ibge`.
- `data/contracts/tse_parties.md` and `tests/test_build_tse_parties.py`.

Expected files (four): `src/terrain/builds/tse_parties.py`,
`pipeline/build/tse_parties.py`, `data/contracts/tse_parties.md`,
`tests/test_build_tse_parties.py`.

## Out of scope

- Candidate votes and turnout (06a); computing margins or list ranks.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`, `src/terrain/builds/tse_candidates.py`.

## Done when

1. From the fixtures, every party-vote and coalition row for 2000 and 2024
   has a `cd_ibge`, and the row counts equal the fixture rows.
2. A test input with one party under two coalition records in the same zone
   keeps both rows, and the key check passes; a true duplicate raises.
3. 2024 coalition rows carry the federation columns; 2000 rows have them
   null.
4. The row-count, key and `cd_ibge` checks each raise on broken input.
5. Test zips use a fixed timestamp; no test touches the network or GCS.
6. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
