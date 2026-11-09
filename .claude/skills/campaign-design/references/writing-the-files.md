# Writing the campaign files

## Layout

```
research/campaigns/NNNN-slug/
  campaign.md       front matter + the prose sections of TEMPLATE.md
  drafts/s1.md      one draft per task step, named after the step id
```

`NNNN` is the next free number in `research/campaigns/`; the slug is short,
lowercase, hyphenated. Copy `research/campaigns/TEMPLATE.md`; keep its
comments out of the final file once each field is filled.

## Front matter, field by field

- `id`: the folder number, quoted (`"0002"`).
- `title`: what the campaign finds out, in a few words.
- `status`: `draft` or `active`; Gabriel chooses. The close-out sets `done`
  or `stopped`.
- `idea`: the idea id, quoted. Its file must exist (or be added in the same
  PR).
- `owner`: `gabrielsgaspar`.
- `created`: today. `end_by`: from the budget, at most 31 days later.
- `budget`: see `budget.md`.
- `referee_not_applicable_ok`: leave `[R5]` unless Gabriel decides
  otherwise. When the explore scripts make no estimate (counts or
  structural checks only), propose `[R4, R5]` and say why: R4 "Level and
  inference" checks the level and clustering of an estimate, so with none
  the referee rightly marks it "Not applicable", and the gate stops on any
  "Not applicable" row not listed here (campaign 0003, PR #264). The field
  covers the whole campaign: if any script makes an estimate, keep `[R5]`.
- `datasets`: one entry per dataset the campaign may acquire or build.
  Existing datasets are not listed.
- `steps`: in order; a step's `after` may name only earlier steps.

### Step kinds

```yaml
- id: s1
  kind: task
  type: explore              # or build
  draft: drafts/s1.md        # always drafts/<id>.md
  allowed_paths:             # full paths, one * per file name at most
    - explore/0003_mayor_window.py
    - tests/test_explore_mayor_window.py
  after: []

- id: s2
  kind: explore_run
  script: 0003_mayor_window  # explore/<script>.py; idea prefix = campaign idea
  after: [s1]
  kill_rules: [...]          # see kill-rules.md
  on_kill: skip_dependents   # or stop, or continue

- id: s3
  kind: pipeline_run
  stage: acquire             # or build
  target: inpe_fires         # pipeline/<stage>/<target>.py
  dataset: inpe_fires        # must be in datasets
  after: [s1]
```

An explore task may change only `explore/` and `tests/test_explore*`. A
build task may not list protected paths (`AGENTS.md`, "Scope"), anything
owned in `.github/CODEOWNERS`, `pyproject.toml` or `uv.lock`. The validator
refuses all of these.

## Drafts

Follow `research/campaigns/DRAFT_TEMPLATE.md` and the checklist in
`harness/issue-drafts/README.md` ("Before filing a task"): the planner sees
only the issue text and the repository, so write for a stranger.

- First line `# Task: <title>`; no HTML comments (the tick adds the marker).
- Name the campaign and step in the Goal.
- "In scope" lists exactly the step's `allowed_paths`.
- For an explore script: name every key it writes to `results.json`,
  including every field a kill rule reads, at that exact dotted path. Keys
  must not contain dots (write `w0_5pct`, not `0.5%`), because a dot
  separates the path. Say which outcome years it reads (referee R2) and that
  it computes nothing beyond what the issue lists (referee R7).
- "Done when": every item checkable on fixtures or inputs built inside the
  test, with no network, GCS or model. Include a test that the results
  carry every key the kill rules read.
- At most about ten files. Only what the builder can do (AGENTS.md, "What
  the builder can do").
- Once the campaign is merged, the draft is frozen: the tick files it word
  for word, and the gate checks the issue still matches it.

### Facts about real data

Drafts that read data must state the facts the builder needs (columns,
types, keys, row counts, known bad values). Take them from
`data/contracts/<dataset>.md`, `data/manifests/`, `data/fixtures/*/README.md`
and earlier run records. Local sessions cannot read the bucket (the sandbox
denies GCP credentials), so if a fact can only come from the real files,
either add an earlier explore step that profiles them (and writes the facts
to its `results.json`), or ask Gabriel to profile them before the campaign.
Never guess a column name.

## Prose sections

Fill every section of the template. Keep them short; they are what the
close-out and Gabriel read later. "Already known" holds the novelty table.
"Provenance" lists, for every step, rule and number, "stated by Gabriel" or
"suggested by Claude, confirmed by Gabriel on <date>".

## Checks before the PR

```bash
uv run python scripts/campaign.py validate
uv run python scripts/campaign.py status
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/test_campaigns.py tests/test_records.py
```

## A worked example: the smoke-test pilot

The smallest useful campaign re-runs a script that already exists, so no
model job is needed and every other part of the loop is tested: dispatch,
record PR, gate, merge, kill rule, close-out. Idea 0003's power check
(`explore/0003_mayor_power.py`, run 42367009833) is deterministic (fixed
seed), so the re-run must give the same numbers. Its results hold
`windows.<window>.power`; at 1% the earlier run had power about 0.05.

```yaml
---
id: "0001"
title: "Smoke test: re-run idea 0003's power check"
status: active
idea: "0003"
owner: gabrielsgaspar
created: 2026-11-08
end_by: 2026-11-15
budget:
  max_tasks: 0
  max_explore_runs: 1
  max_pipeline_runs: 0
  max_model_jobs: 0
referee_not_applicable_ok: [R5]
datasets: []
steps:
  - id: s1
    kind: explore_run
    script: 0003_mayor_power
    after: []
    kill_rules:
      - id: k1
        says: "Power at decision 0007's effect is below 80% at the 1% window"
        field: windows.1%.power
        op: "<"
        value: 0.8
        confirmed: true
    on_kill: skip_dependents
---
```

Expected: the tick opens the tracking issue, then dispatches the run, merges
the record, posts "Verdict: killed" with the observed power, and files the
close-out task, which produces the report PR for Gabriel. The close-out
uses the harness (about 3 model jobs).
