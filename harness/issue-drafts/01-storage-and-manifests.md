# Task: storage and manifest helpers

## Goal

Add the small library every pipeline script uses to talk to GCS and to record
what it wrote, so acquire and build scripts are idempotent and testable
without GCS.

## Idea

Infrastructure for `research/ideas/0001-electoral-strongholds.md`.

## In scope

- `src/terrain/storage.py`: a `Store` protocol with `exists(path)`,
  `list(prefix)`, `read_bytes(path)`, `create(path, data_or_local_file)` and
  `download(path, local_file)`. `create` never overwrites: it raises if the
  object exists. Two implementations:
  - `MemoryStore`, a dict-backed store for tests;
  - `GCSStore(bucket_name)`, using `google-cloud-storage`, where `create`
    uploads with `if_generation_match=0` so GCS itself refuses an overwrite.
- `src/terrain/manifest.py`: build, validate, write and find manifests
  exactly as specified in `pipeline/README.md` ("The contract every script
  follows"). Validation applies the same structural rules as the "Check
  the manifest" step in `.github/workflows/data-pipeline.yml` (keys,
  dataset, stage, status, prefix, file paths, SHA-256), but not its
  credential scan: the workflow already does that, and token prefixes
  written in code would trip the builder's own secret scan. Also: `sha256_file(path)`,
  `latest_manifest(store, prefix)` (newest `_MANIFEST.json` under a prefix),
  and `content_hash(*parts)` for build output paths.
- Tests in `tests/test_storage.py` and `tests/test_manifest.py`.

## Out of scope

- Any acquire or build script, any TSE-specific code, any workflow file.
- `pyproject.toml` and `uv.lock`: `google-cloud-storage` is already a
  dependency.
- Calling GCS or the network in tests (`GCSStore` is not exercised beyond
  construction with a mocked client).

## Done when

1. `MemoryStore.create` on an existing path raises, and the stored bytes are
   unchanged.
2. `GCSStore.create` passes `if_generation_match=0` to the upload call
   (checked with a mocked client).
3. Manifest validation rejects, each in its own test: a missing key, a
   `dataset` that does not match, a `gcs_prefix` outside `data/raw/` for
   acquire or outside `data/derived/` for build, a prefix without a trailing
   `/` or containing `..`, a file path outside the prefix, and a malformed
   SHA-256; and accepts a valid manifest.
4. `latest_manifest` returns the newest of several manifests under a prefix
   in a `MemoryStore`, and `None` when there are none.
5. `content_hash` is stable for the same inputs and changes when any input
   changes.
6. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
