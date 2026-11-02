# Task: candidates build tolerates invalid birth dates

## Goal

The first real run of the candidates build stopped because 17 birth dates in
the 2000 file are not valid dates (for example 29 February of a non-leap
year). Make the build keep every row, set unusable birth dates to null, keep
the original text, and report how many there were.

## Idea

Fix to the build from task 03 (`src/terrain/builds/tse_candidates.py`).

## What the real files contain (checked 2026-11-02)

Values of `DT_NASCIMENTO` that are not valid `dd/mm/yyyy` dates: 17 in 2000
(such as `29/02/1950`, `00/61/2959`), 26 in 2004 (many with stray spaces,
such as `01/8 /1970`), none in other years. Valid dates that are impossible
for a candidate (born before 1900, or under 18 on election day): 81 in 2000,
269 in 2004, 13 in 2008, 175 in 2012, 10 in 2016, 2 in 2020, 4 in 2024
(such as `01/01/0001`, `02/02/2193`). Every other typed column
(`ano_eleicao`, `cd_tipo_eleicao`, `nr_turno`, `cd_eleicao`, `dt_eleicao`)
parses in every year.

## In scope

- `src/terrain/builds/tse_candidates.py`:
  - add `dt_nascimento_raw` (the original text, after the missing-value
    rule);
  - parse `dt_nascimento` after removing spaces, non-strictly; a value that
    does not parse, or gives a birth date before 1900-01-01 or less than 18
    years before `dt_eleicao`, becomes null;
  - keep `dt_eleicao` strict: a failure there should still stop the build;
  - write per-year counts of unparseable and implausible birth dates in the
    manifest `notes`, and raise if either exceeds 0.1% of a year's rows.
- `data/contracts/tse_candidates.md`: document `dt_nascimento_raw` and the
  rule.
- Tests in `tests/test_build_tse_candidates.py`, using inputs built in the
  test from a fixture with altered birth dates.

## Out of scope

- Any other column's typing. `pyproject.toml`, `uv.lock`, workflows,
  `data/manifests/`, `data/fixtures/`, `data/reference/`.

## Done when

1. An input with birth dates `29/02/1967`, `01/8 /1970`, `01/01/0001` and a
   valid date builds; the first and third become null, the second parses as
   1970-08-01, the valid one is unchanged, and `dt_nascimento_raw` holds all
   four original strings.
2. A birth date less than 18 years before the election becomes null.
3. The manifest notes show the per-year counts, and a year where more than
   0.1% of birth dates fail raises.
4. An invalid `dt_eleicao` still raises.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
