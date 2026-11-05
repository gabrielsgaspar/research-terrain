# Task: MapBiomas acquisition resumes exports started by an earlier run

## Goal

`terrain.earthengine.acquire_mapbiomas` starts 21 Earth Engine exports and
waits up to 160 minutes inside a 180-minute job. On the real service that
can never finish: the project's exports run about one at a time, 8 to 37
minutes each, so 21 years take 5 to 6 hours. Make the acquisition
resumable: a run records the exports it starts, and a later run with the
same asset version picks them up instead of starting new ones, then checks
the files and writes the manifest once all have completed.

## Idea

Decision 0006; task 26 (`harness/issue-drafts/26-acquire-mapbiomas.md`, the
rules this task keeps). Read `src/terrain/earthengine.py`,
`src/terrain/acquire.py` (`_free_prefix`), `src/terrain/manifest.py`
(`latest_manifest`) and `tests/test_earthengine.py` first.

## What the real service did (checked 2026-11-05)

- Run 41992445702 started 21 exports at 08:11 UTC and stopped at its
  160-minute limit with `exports not finished after 160 minutes`; no
  manifest was written. Its tasks waited queued (`READY`) behind an earlier
  run's tasks, then ran one or two at a time and all reached `COMPLETED`
  by 16:48 UTC; the 21 files (493 MiB) are in
  `data/raw/mapbiomas/2026-11-05/`.
- `ee.data.getTaskStatus(id)` still answers for a task after the run that
  started it has ended.

## The rules

1. **Pending record.** Right after starting the exports, the run uploads
   `<prefix>exports.json`: `{"sources": [<the source entry>], "tasks":
   {"<year>": "<task id>", ...}}` (the `source` dict that goes into the
   manifest). The acquire account can create objects in `data/raw/`, so
   this is a new object, never an overwrite.
2. **Resume.** After the `unchanged` check, before starting exports: find
   the dated folders under the root that hold an `exports.json` and no
   manifest (`MANIFEST_NAME`). If the newest of them has `sources` equal to
   the current source (`_unchanged` on the same keys), use its prefix and
   task ids; start nothing. Otherwise start new exports in
   `_free_prefix` as now.
3. **Waiting.** As now (`_wait`, the same limit), for the new or the
   resumed tasks; a `FAILED` or `CANCELLED` task still raises with its
   message. Rule 2 skips a pending folder in which `task_state` reports any
   task `FAILED` or `CANCELLED`, so the run after a failure starts new
   exports in a new folder.
4. **Timeout message:** `exports not finished after <n> minutes (<k> of
   <21> completed); run again to resume <prefix>`.
5. Checks, files, notes and manifest as now; `exports.json` is not listed in
   the manifest's `files`.
6. The run never reads `data/derived/split/` or anything in `sealed/`, and
   prints no statistic of any code.

## In scope

`src/terrain/earthengine.py`, `tests/test_earthengine.py`. Expected files
(two), exactly those.

## Out of scope

Workflows, `data/catalog.yaml`, `data/manifests/`, `pipeline/`, anything
under `sealed/`.

## Done when

1. With the fake Earth Engine and a `MemoryStore`: a first run whose tasks
   are still `RUNNING` at the limit raises with the rule 4 message, leaves
   `exports.json` with the year-to-task map and the source, and writes no
   manifest; a second run with the tasks now `COMPLETED` starts no export,
   uses the same prefix, and returns a `created` manifest whose `files` are
   the 21 year files only.
2. A second run after the asset's `updateTime` changed starts new exports in
   a new folder.
3. A pending folder whose tasks include a `FAILED` one is not resumed: the
   next run starts new exports in a new folder.
4. A folder with both `exports.json` and a manifest is never resumed (the
   `unchanged` path covers it).
5. The existing tests still pass (parameters, checks, failures, no
   `split/` or `sealed/` reads); `uv run ruff check .`, `uv run ruff format
   --check .` and `uv run pytest` pass; no test uses the network, GCS or
   Earth Engine.
