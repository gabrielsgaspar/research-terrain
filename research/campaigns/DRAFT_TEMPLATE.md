# Task: short title of the task (explore)

## Goal

One or two sentences: what should be true when this is done, and why. Name
the campaign (`research/campaigns/NNNN-slug/campaign.md`, step sN).

## Idea

The idea file this serves, the decisions and run records it rests on (by
path), and whether it is an explore task (label `explore`: it may change only
`explore/` and `tests/test_explore*`) or a build task.

## In scope

- Exactly the files listed in the step's `allowed_paths`.
- The behaviour to add, and the datasets read, by their catalog names.
- For an explore script: the exact keys it writes to `results.json`, with
  the ones the kill rules read (for example `pairs.1pct`), so the rules can
  be applied by code.

## Out of scope

- Anything else, even if it looks related.

## Done when

1. Each item checkable by reading code or running a free local command
   against fixtures or data built inside the test.
2. For an explore script: a test builds a small input, runs the script's
   logic and checks that `results.json` has every key the kill rules read.
3. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
