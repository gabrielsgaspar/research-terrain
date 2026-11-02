# Task: acquire TSE candidate files, 2000-2024

## Goal

Download the TSE candidate files for every municipal election from 2000 to
2024, plus the complementary files for 2020 and 2024, into one dated raw
folder, and never download them again unless the TSE changes them.

## Idea

Data for `research/ideas/0001-electoral-strongholds.md` and
`0002-indigenous-councilors.md`. Read `data/fixtures/tse/README.md` first.

## In scope

- `src/terrain/sources/tse.py`: the list of source URLs
  (`consulta_cand_<year>.zip` for 2000, 2004, ..., 2024 and
  `consulta_cand_complementar_<year>.zip` for 2020 and 2024, URL patterns in
  `data/catalog.yaml`), and the acquire logic, with the HTTP fetch passed in
  as a function so tests can fake it.
- `src/terrain/catalog.py`: read `data/catalog.yaml` with `yaml.safe_load`
  (PyYAML is already a dependency) and return a dataset's entry by name. Every
  later script will use it; do not hand-parse YAML.
- `pipeline/acquire/tse_candidates.py`: a thin script following the contract
  in `pipeline/README.md`, using `GCSStore` and the standard library for HTTP.
- Behaviour:
  - Ask each URL for `Last-Modified`, `ETag` and `Content-Length` first.
  - If the latest manifest under `data/raw/tse/candidates/` has the same
    three values for every source, create nothing and report
    `"status": "unchanged"` with that manifest's prefix and files.
  - Otherwise download every file to a temporary file, streaming, never
    holding a whole file in memory. Check its size against `Content-Length`,
    check it is a valid zip whose members pass `ZipFile.testzip()` and that
    contains a `*_BRASIL.csv`, compute SHA-256, and upload all of them to
    `data/raw/tse/candidates/<YYYY-MM-DD>/`, then write `_MANIFEST.json` last.
    If that dated folder already exists, add a suffix (`-2`, `-3`).
  - Record, per source, the URL, `Last-Modified`, `ETag` and bytes taken from
    the GET response that was actually downloaded. If they differ from what
    HEAD returned, the file changed mid-run: raise, and upload nothing.
  - For an `unchanged` run, write the manifest to `--manifest-out` only (never
    a second `_MANIFEST.json` in the bucket); the workflow opens no PR for it.
- Tests in `tests/test_acquire_tse.py`, using `MemoryStore`, a fake fetch
  function, and zips built in memory from `data/fixtures/tse/`.

## Out of scope

- Cleaning, parsing or converting the CSVs (the next task).
- Results, vote or polling-station data.
- Workflow files, `data/manifests/`, `data/fixtures/`.

## Done when

1. A first run against the fake sources creates nine zips and one
   `_MANIFEST.json` under `data/raw/tse/candidates/<date>/`, and the manifest
   passes the validation in `src/terrain/manifest.py`.
2. A second run with identical headers creates no objects and returns status
   `unchanged` with the first run's prefix.
3. A run where one source's `ETag` changed creates a new dated folder (with
   a suffix if the date is the same) holding all nine files.
4. A download shorter than its `Content-Length`, a zip without a
   `*_BRASIL.csv`, a corrupt zip member, and a GET whose `ETag` differs from
   HEAD each raise and leave no new objects or manifest in the store.
5. `src/terrain/catalog.py` returns the `tse_candidates` entry from the real
   `data/catalog.yaml`, and the script builds its URLs from it.
6. No test touches the network or GCS.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
