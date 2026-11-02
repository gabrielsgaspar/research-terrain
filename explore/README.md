# Exploration

One script per idea: `explore/NNNN_slug.py`, run by **Actions → Explore run**
(`gh workflow run explore-run.yml --ref main -f script=NNNN_slug`) after it is
merged. The contract is in `src/terrain/explore.py`:

- `python explore/NNNN_slug.py --out-dir DIR`, with `TERRAIN_BUCKET`,
  `EXPLORE_RUN_ID` and `CODE_COMMIT` in the environment.
- Call `exploration_municipalities(store)` and `restrict(...)` on every table
  before computing anything; `tests/test_explore.py` fails if a script does
  not.
- Write `summary.md` and `results.json` with `write_results`; put larger
  outputs in GCS under `output_prefix(script, run_id)`.
- The workflow opens a PR recording the run in `research/explore-runs/`.
  Before merging it, add a lessons entry and update the idea file, whatever
  the result.
