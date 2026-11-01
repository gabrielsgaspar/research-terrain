# Exploration

One script per idea: `explore/NNNN_slug.py` (marimo or plain Python, so diffs
stay readable). Rules:

- Read only exploration municipalities
  (`data/derived/split/explore_municipalities.csv`).
- Write outputs to `gs://research-terrain/data/explore/NNNN/`.
- Every run updates `research/ideas/NNNN-*.md` and adds an entry to
  `research/lessons.md`, including when nothing works.
