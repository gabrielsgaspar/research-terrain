# Task: front matter for idea and decision records, and a validator

## Goal

Every idea and decision file starts with a small YAML front matter that a
script can check, so agents (and the index in task 12) can rely on each
record's status, dates and datasets. Build plan items 2.1 and 2.2.

## In scope

- Front matter, between `---` lines at the top of each file:
  - Ideas (`research/ideas/NNNN-slug.md`): `id` (the NNNN), `title`,
    `status` (one of proposed, exploring, promising, dead, registered,
    confirmed, rejected), `created` and `updated` (YYYY-MM-DD), `datasets`
    (a list of `data/catalog.yaml` names), `kill_criteria` (a non-empty list
    of strings: what result would make the idea dead), `related` (a list of
    other record ids, may be empty).
  - Decisions (`research/decisions/NNNN-slug.md`): `id`, `title`, `status`
    (proposed, accepted or superseded), `date` (YYYY-MM-DD), `supersedes`
    (a decision id or null).
- `scripts/validate_records.py`: checks every file in those two folders
  except `README.md` and `TEMPLATE.md`: front matter present and valid; `id`
  equals the file-name number; dates valid and `updated` >= `created`;
  every dataset exists in the catalog; every related id exists; titles
  unique. Exits non-zero with one line per problem.
- Migrate the existing records, taking each field from the file's own text:
  `research/ideas/0001-electoral-strongholds.md` (status proposed),
  `research/ideas/0002-indigenous-councilors.md` (status dead),
  `research/decisions/0001-split-sample.md`,
  `research/decisions/0002-repo-and-storage.md`,
  `research/decisions/0003-confirmation-rows.md` (status accepted). Where a
  file states no kill criteria, write the ones its Prediction section implies
  and mark each with "(drafted by agent; confirm)".
- Update `research/ideas/TEMPLATE.md` with the idea front matter.
- `tests/test_records.py`: runs the validator on the real folders (must
  pass), and on bad records written in the test (each problem above caught).

Expected files (eight): the five records above,
`research/ideas/TEMPLATE.md`, `scripts/validate_records.py`,
`tests/test_records.py`.

## Out of scope

- The index (task 12); changing any record's body text beyond the front
  matter; workflows; `harness/`.

## Done when

1. `uv run python scripts/validate_records.py` exits 0 on the repository.
2. Tests show each problem (missing front matter, bad status, id/file-name
   mismatch, bad date, `updated` before `created`, unknown dataset, unknown
   related id, empty kill criteria, duplicate title) makes it exit non-zero.
3. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
