# Pipeline

- `acquire/`: one script per source. Downloads into a new dated folder under
  `gs://research-terrain/data/raw/`, records SHA-256 in `data/catalog.yaml`.
  Agents write and test these against fixtures; they run against GCS only
  after merge, in a job bound to the `data-write` environment.
- `build/`: raw to derived. Each output is checked against its contract in
  `data/contracts/` before it is written.

Keep scripts thin: logic goes in `src/terrain/` with tests.
