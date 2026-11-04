# Task: acquire files whose version comes from an ArcGIS item record (public-forest register)

## Goal

The acquirer can fetch `cnfp_public_forests`: six editions of the national
public-forest register, served by the Forest Service's ArcGIS portal, whose
downloads have no Content-Length and whose URLs all end in `/data`.

## What the real server does (checked 2026-11-04)

- Download: `https://mapas.florestal.gov.br/portal/sharing/rest/content/items/<id>/data`.
  GET returns 200 with an `ETag` but **no `Content-Length`** (chunked);
  HEAD returns neither `ETag` nor `Content-Length` nor `Last-Modified`.
- Item record: the same URL without `/data` plus `?f=json` returns JSON with
  `name` (for example `CNFP_2008.zip`), `size` (bytes, an integer; it equals
  the downloaded file's size: 24,066,750 for 2008) and `modified` (epoch
  milliseconds).
- Long downloads from this portal stall: the 2012 and 2024 files (265 and
  260 MB) stopped at about 78% on every attempt, so restarting from the
  start may never finish. The portal supports resuming: a GET with
  `Range: bytes=N-` returns 206 with `Content-Range: bytes N-M/<total>`, and
  resuming from the partial file completed both downloads at exactly the
  record's `size`.
- The catalog entry is already written (`data/catalog.yaml`,
  `cnfp_public_forests`): six files, each with `url`, `name`, `meta` and
  `check`. Today `expand_urls` rejects it because every URL ends in `data`.

## In scope

- `src/terrain/acquire.py`:
  - A file entry may give `name`, the stored file name; without it, the name
    is the URL's last part, as now. Two files with the same stored name still
    raise.
  - A file entry may give `meta`, the URL of a JSON record. For such files the
    version is taken from that record instead of HEAD: `bytes` = `size`,
    `last_modified` = `modified` as a string, `etag` = "" (recorded in the
    manifest's `sources` with the same fields as today). The record must
    have an integer `size` and a `modified`, or the file raises. After the
    download, the file's size must equal `size`. Content-Length is not
    required for these files.
  - Files without `meta` behave exactly as today (Content-Length required).
  - Unchanged detection compares the same fields as today, so an unchanged
    record gives `unchanged` and writes nothing, and a changed `modified`
    gives a new dated folder.
  - A download that stalls (a socket timeout or a short read) is resumed
    from the bytes already written, with a `Range` request, up to 8 times
    before raising. A resumed response must be 206 with a `Content-Range`
    starting at those bytes; anything else restarts the file from the start
    (counted as an attempt).
- `src/terrain/http.py`: `UrllibFetcher.json(url)`, returning the parsed
  JSON (with the same timeout and headers as HEAD), and a way to download
  from a byte offset with a `Range` header, returning the status and
  `Content-Range`.
- `pipeline/acquire/cnfp_public_forests.py`: the usual thin script.
- `tests/test_acquire.py`: the cases below, with the fake fetcher returning
  JSON for `meta` URLs.

Expected files (four): `src/terrain/acquire.py`, `src/terrain/http.py`,
`pipeline/acquire/cnfp_public_forests.py`, `tests/test_acquire.py`.

## Out of scope

- `data/catalog.yaml` (already has the entry), `data/manifests/`,
  `data/fixtures/`, workflows, `pyproject.toml`, `uv.lock`.
- Reading the shapefiles (a later build task).

## Done when

1. `expand_urls(dataset("cnfp_public_forests"))` gives 6 files with stored
   names `CNFP_2008.zip`, `CNFP_2012.zip`, `CNFP_2016.zip`, `CNFP_2020.zip`,
   `CNFP_2024_retificado.zip`, `CNFP_2025.zip`, and the URL counts for every
   other dataset are unchanged (the existing count test gains cnfp: 6).
2. With `meta`, a download with no Content-Length is accepted and the
   manifest's `sources` record the record's `size` and `modified`.
3. A downloaded size different from the record's `size` raises, and the
   store is unchanged.
4. A record without an integer `size` or without `modified` raises.
5. The same record as the last manifest gives `unchanged` with nothing
   written; a new `modified` gives a new dated folder.
6. A file without `meta` and without Content-Length still raises, and the
   real `tse_candidates` manifest still compares `unchanged`.
7. A download that stalls twice and is resumed (the fake returns 206 with the
   right `Content-Range`) is stored once, byte-identical to the whole file; a
   resume answered with 200 restarts from the start; one that stalls nine
   times raises with the store unchanged.
8. No test uses the network; `uv run ruff check .`, `uv run ruff format
   --check .` and `uv run pytest` pass.
