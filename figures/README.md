# Figures

One script per paper figure, `figures/NN_name.py`. Scripts run against GCS
only through the `figures-run` workflow, after they are merged: **Actions →
Figures run → Run workflow**, giving the script name without `.py`. The
workflow opens a PR adding the files under `paper/figures/` with a record
(`paper/figures/NN_name.md`: script, commit, run, SHA-256 of each file).

## The contract every script follows

1. Command line: `python figures/NN_name.py --out-dir DIR`. The bucket name
   comes from `TERRAIN_BUCKET`; GCP credentials from the environment. Read
   GCS paths from `data/catalog.yaml`, never hard-code them.
2. Writes `DIR/NN_name.png`, and optionally more PNGs named
   `NN_name_<part>.png` (for example `_appendix`). **PNG only**, through
   `terrain.style.save_png`; the workflow refuses any other file and PNGs over
   10 MB.
3. Treatment-side data only (decision 0003): candidates, results, polling
   places, tenure, census grid, boundaries. Never an outcome table. The run
   account (`terrain-analysis`) reads `data/derived/` and `data/explore/`
   only, so raw inputs reach a figure through a build.
4. Deterministic: the same inputs and code give the same files; set every
   random seed.
5. Logic (projections, binning, colour scales) lives in `src/terrain/` with
   tests; the script stays thin, like `pipeline/` and `explore/` scripts.
6. Style: every figure follows `figures/STYLE.md`, implemented in
   `terrain.style` (fonts, sizes, base map layers, colours, bottom legends,
   comma-separated numbers).

`00_smoke.py` draws a fixed test image from no data. Run it to check the
workflow end to end; close its PR without merging.
