---
# Copy this file to research/campaigns/NNNN-slug/campaign.md (the next free
# number; slug in lowercase with hyphens) and put one draft per task step in
# drafts/<step id>.md, following DRAFT_TEMPLATE.md. The `campaign-design`
# skill (.claude/skills/campaign-design/) walks you through every field.
# `uv run python scripts/campaign.py validate` checks the file; CI runs the
# same check. Merging the campaign PR with `status: active` starts it.
id: "NNNN"
title: "What this campaign finds out, in a few words"
status: draft            # draft, then active (starts it), done or stopped (set by the close-out)
idea: "0001"             # the idea file this serves, research/ideas/<idea>-*.md
owner: gabrielsgaspar    # who is told when it is blocked or finished
created: YYYY-MM-DD
end_by: YYYY-MM-DD       # no new step starts after this day (at most 31 days)
budget:
  max_tasks: 2           # issues filed (each one plan, build, review, merge)
  max_explore_runs: 2    # explore-run dispatches
  max_pipeline_runs: 0   # data-pipeline dispatches (acquire or build)
  max_model_jobs: 16     # planner + builder + reviewer jobs, counted from their comments
referee_not_applicable_ok: [R5]   # referee rows that may be "Not applicable" (R5 cannot be checked before a run)
# oversize_reason: "..."  # needed when there are more than 8 steps: why it cannot be split, in the owner's words
datasets: []             # new data this campaign may acquire or build; nothing else may be added
#  - name: some_dataset          # its data/catalog.yaml name
#    source: https://...         # where it comes from
#    licence: public             # terms of use, as the publisher states them
#    max_size_gb: 2              # a run that would store more is a reason to stop
#    identifiers: none           # none, or hashed (CPF or voter IDs, salted hash only)
steps:
  - id: s1
    kind: task                   # files drafts/s1.md as an issue; plan, build, review, merge
    type: explore                # explore (explore/ and tests/test_explore* only) or build
    draft: drafts/s1.md
    allowed_paths:               # every file the task may change; one * per name at most
      - explore/0001_example.py
      - tests/test_explore_example.py
    after: []
  - id: s2
    kind: explore_run            # runs explore/<script>.py on the exploration half
    script: 0001_example
    after: [s1]
    kill_rules:                  # any rule met kills the step; a missing field stops it
      - id: k1
        says: "Fewer than 200 close pairs at the 1% window"
        field: pairs.1pct        # dotted path into the run's results.json
        op: "<"
        value: 200
        confirmed: false         # true only once the owner has stated this rule
    on_kill: skip_dependents     # skip_dependents, stop (the whole campaign) or continue
---

# NNNN: Title

## Question

What this campaign finds out, and why it matters for the idea. One paragraph.

## Already known

What the repository, the Zotero notes and the literature already say, with
paths and citation keys (the skill's novelty check). Say what is explored,
partly explored or new, and why this campaign is not a repeat.

## Read before this runs

The papers closest to the idea, from the novelty check (citation key, or
authors, year and link for a web find). For each: whether Gabriel has read
it, in his words ("read it; their design differs because ...", "not yet").

## Steps and why

One short paragraph per step: what it does, why it comes in this order, and
what each result would mean.

## Kill rules and why

For every rule: the threshold, where it comes from (a power calculation,
decision 0007, a count the design needs), and what would happen at the
margin. Say who set it.

## Budget and why

How the numbers above were sized (`scripts/budget.py` in the skill), and what
happens when they run out.

## New data

For each dataset in `datasets`: what it is, its licence, its size, whether it
holds personal identifiers, and why the campaign needs it. "None" if none.

## What would change the plan

Results that should make the owner stop the campaign early or start a
different one. The agents do not act on this section; it is for the report.

## Provenance

Who decided what: each kill rule, threshold and step is either "stated by
Gabriel" or "suggested by the skill, confirmed by Gabriel on YYYY-MM-DD".
