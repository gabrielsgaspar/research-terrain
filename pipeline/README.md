# Pipeline

Scripts here run against GCS only through the `data-pipeline` workflow, after
they are merged: **Actions → Data pipeline → Run workflow**, choosing a stage
and a target (the script name without `.py`).

- `acquire/<target>.py`: downloads into `gs://research-terrain/data/raw/`.
  Runs as `terrain-acquire`, which can create objects in `data/raw/` but never
  overwrite or delete them.
- `build/<target>.py`: turns raw data into tables in `data/derived/`. Runs as
  `terrain-build`, which reads `data/raw/` and `data/derived/` and can only
  create in `data/derived/`.

## The contract every script follows

1. Command line: `python pipeline/<stage>/<target>.py --manifest-out PATH`.
   The bucket name comes from the `TERRAIN_BUCKET` environment variable; GCP
   credentials come from the environment (Application Default Credentials).
2. Idempotent: running twice with nothing changed at the source creates
   nothing new and reports `"status": "unchanged"`.
3. Writes a manifest (JSON) to `PATH` and the same manifest to
   `<gcs_prefix>_MANIFEST.json` in the bucket:

   ```json
   {
     "dataset": "<target>",
     "stage": "acquire | build",
     "status": "created | unchanged",
     "gcs_prefix": "data/raw/<source>/<YYYY-MM-DD>/",
     "created_at": "ISO 8601, UTC",
     "code_commit": "value of the CODE_COMMIT environment variable",
     "sources": [{"url": "...", "last_modified": "...", "etag": "...", "bytes": 0}],
     "inputs": ["manifests this build read (build only)"],
     "files": [{"path": "<gcs_prefix>...", "sha256": "...", "bytes": 0}],
     "notes": "anything a reader needs, e.g. row counts per year"
   }
   ```
   `gcs_prefix` ends in `/`; every file path starts with it. The workflow
   rejects a manifest that breaks these rules.
4. When `status` is `created`, the workflow opens a PR adding the manifest
   as `data/manifests/<stage>/<target>.json`. Merging it is how later tasks
   learn the data exists. An `unchanged` run opens no PR, unless main has no
   manifest for that output (an earlier run created it but failed to
   record it): then it records it.

Keep scripts thin: logic lives in `src/terrain/` with tests that use fixtures
and an in-memory store, never the network or GCS.
