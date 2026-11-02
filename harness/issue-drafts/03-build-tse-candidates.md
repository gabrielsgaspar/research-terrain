# Task: build the candidates table (Parquet), 2000-2024

## Goal

Turn the raw TSE candidate files into one clean Parquet table, one row per
candidacy, that becomes the project's source of truth for candidate
information.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md` and
`0002-indigenous-councilors.md`. Read `data/fixtures/tse/README.md` first; it
lists the pitfalls this task must handle.

## In scope

- `src/terrain/builds/tse_candidates.py` and
  `pipeline/build/tse_candidates.py`, following the contract in
  `pipeline/README.md`. Inputs: the zips listed in
  `data/manifests/acquire/tse_candidates.json`.
- Reading: only the `*_BRASIL.csv` member of each zip; Latin-1, `;`, CRLF.
  Year by year, so memory stays bounded.
- Harmonising across years into one schema:
  - snake_case column names; `nm_email` and `ds_email` become `email`;
  - every column that exists in any year, null where a year lacks it;
  - TSE missing-value codes (`#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`,
    `-4`, `NÃO DIVULGÁVEL`) become null;
  - identifiers (`sq_candidato`, `nr_cpf_candidato`,
    `nr_titulo_eleitoral_candidato`, `sg_ue`) stay strings with leading zeros;
  - dates (`dt_eleicao`, `dt_nascimento`) become dates;
  - supplementary elections kept, identified by `cd_eleicao` and
    `cd_tipo_eleicao`.
- For 2020 and 2024, join the complementary file on (`ano_eleicao`,
  `cd_eleicao`, `sq_candidato`), adding `cd_etnia_indigena`,
  `ds_etnia_indigena` and `st_quilombola`.
- Output: `data/derived/tse_candidates/<hash>/candidates.parquet`, where
  `<hash>` is `content_hash` of the input file SHA-256s and the build code.
  If that path already has a manifest, do nothing and report `unchanged`.
- Checks the build itself enforces before writing: rows per year equal the
  rows of that year's `BRASIL` file; (`ano_eleicao`, `cd_eleicao`,
  `sq_candidato`) is unique; every complementary row joins.
- `data/contracts/tse_candidates.md`: every output column, its type, its
  source column per year, and the missing-value rule.
- Tests in `tests/test_build_tse_candidates.py`, building from zips made in
  memory from `data/fixtures/tse/`, with `MemoryStore`.

## Out of scope

- Any crosswalk to IBGE municipality codes (a separate dataset).
- Vote results, polling stations, any analysis.
- Logging or printing names, CPF, voter-ID numbers or e-mails anywhere,
  including tests and the manifest notes.
- Workflow files, `data/manifests/`, `data/fixtures/`, `pyproject.toml`,
  `uv.lock` (`polars` is already a dependency).

## Done when

1. Building from the fixtures produces one row per fixture data row, summed
   over all seven years, and a zip whose `BRASIL` file is accompanied by state
   files does not double the rows.
2. Accented text decodes correctly (a test finds `ELEIÇÃO SUPLEMENTAR`), and
   identifiers keep leading zeros.
3. Every listed missing-value code is null in the output.
4. The 2024 fixture's `KAINGANG` and `MUNDURUKÚ` rows have those values in
   `ds_etnia_indigena`.
5. Supplementary-election rows are present with their own `cd_eleicao`.
6. Changing one input SHA-256 changes the output path; building twice with
   the same inputs reports `unchanged` and writes nothing.
7. The row-count, uniqueness and join checks raise on deliberately broken
   inputs (one test each).
8. `data/contracts/tse_candidates.md` lists every output column.
9. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
