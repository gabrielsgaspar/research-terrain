# Task: one catalog-driven acquirer, and five new acquisitions

## Goal

Replace the TSE-specific acquire logic with one generic acquirer that reads
what to download from `data/catalog.yaml`, so each new dataset is a catalog
entry plus a three-line script. Use it for the existing `tse_candidates` and
for five new datasets.

## Idea

Infrastructure for `research/ideas/0001-electoral-strongholds.md`. Read the
`acquire:` block documented at the top of `data/catalog.yaml`, and
`pipeline/README.md`.

## In scope

- `src/terrain/acquire.py`: move the logic of `src/terrain/sources/tse.py`
  here and generalise it. Given a catalog entry:
  - expand each `acquire.files` item: `<year>` over `years`, `<uf>` over
    `ufs` (both optional);
  - HEAD every URL; if the latest manifest under the entry's `gcs` has the
    same URL, `Last-Modified`, `ETag` and bytes for every source, report
    `unchanged` and create nothing;
  - otherwise stream every file to disk, check size against
    `Content-Length`, check that GET headers equal HEAD's, run the file's
    `check` (`zip`: `testzip()` passes and, if `member` is given, a member
    matches that glob; `ods`: a valid zip with `content.xml`; `gzip`: the
    whole stream decompresses), compute SHA-256 — all before any upload —
    then upload to `<gcs><YYYY-MM-DD>/` (suffix `-2`, `-3` if taken) and let
    the script write `_MANIFEST.json` last.
  - Keep the manifest's `sources` fields exactly as now (`url`,
    `last_modified`, `etag`, `bytes`), so existing manifests still compare.
- `src/terrain/http.py`: the `urllib` fetcher now inside
  `pipeline/acquire/tse_candidates.py` (timeouts, `Accept-Encoding:
  identity`), moved so every script shares it.
- `data/catalog.yaml`: give `tse_candidates` an `acquire:` block listing both
  its own seven files and the two complementary files (same folder). Leave
  `tse_candidates_complementar` as a description without an `acquire:` block.
  Do not change any other entry's `acquire:` block.
- `pipeline/acquire/tse_candidates.py` becomes a thin call to the generic
  acquirer, and new thin scripts: `ibge_municipalities.py`,
  `polling_stations_geocoded.py`, `tse_results.py`,
  `tse_votes_by_section.py`, `tse_polling_places.py`.
- Remove `src/terrain/sources/tse.py` once nothing imports it; move or update
  its tests (`tests/test_acquire_tse.py`, `tests/test_catalog.py`).
- `tests/test_acquire.py`: generic tests with `MemoryStore` and a fake
  fetcher, using fixture-built zips, an ODS built from
  `data/fixtures/ibge/*.content.xml`, and a gzip built from
  `data/fixtures/hidalgo/geocoded_polling_stations_sample.csv`.

## Out of scope

- Any build (parsing CSVs, Parquet).
- Running anything against GCS or the network.
- `pyproject.toml`, `uv.lock`, workflows, `data/manifests/`,
  `data/fixtures/`, `data/reference/`.

## Done when

1. Expanding the real catalog gives these URL counts: `tse_candidates` 9,
   `ibge_municipalities` 2, `polling_stations_geocoded` 3, `tse_results` 28,
   `tse_votes_by_section` 63, `tse_polling_places` 4.
2. With the real `data/manifests/acquire/tse_candidates.json` loaded into a
   `MemoryStore` as the latest manifest, and a fake fetcher returning the
   same headers, acquiring `tse_candidates` returns `unchanged` and creates
   no objects. (This proves the next real run will not download again.)
3. For each check type there is a passing case and a failing case (missing
   member, corrupt member, not an ODS, truncated gzip); every failing case
   leaves the store unchanged.
4. A changed `ETag` creates a suffixed dated folder; a short download and a
   GET/HEAD mismatch raise and leave the store unchanged.
5. No pipeline script or module under `src/terrain/` contains a source URL
   or a dataset's GCS folder (such as `data/raw/tse/`); they come from the
   catalog. The two root prefixes `data/raw/` and `data/derived/` in
   `src/terrain/manifest.py`'s validation are allowed.
6. No test touches the network or GCS.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
