---
name: Agent task
about: A task the planner can plan and the builder can build.
title: "Task: "
# No labels here on purpose. Adding the `agent-plan` label is a deliberate
# step by someone with write access; it is what starts the planner.
labels: []
---

<!--
Write it as if a stranger will read it: the planner sees this issue text and
the repository, nothing else. Read AGENTS.md first; work on confirm/, the
paper, legacy/ or sealed/ in GCS will be sent back.
-->

## Goal

One or two sentences: what should be true when this is done, and why.

## Idea

The idea file this serves, e.g. `research/ideas/0001-electoral-strongholds.md`,
or "infrastructure".

## In scope

- Files or modules that may change.
- Behaviour to add or change.
- Datasets used, by their `data/catalog.yaml` names.

## Out of scope

- What must not be touched, even if it looks related.

## Done when

Numbered, each one checkable by reading code or running a command, with no
network, GCS, model or paid API calls. Data checks run against fixtures in
`data/fixtures/`.

1. ...
2. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
