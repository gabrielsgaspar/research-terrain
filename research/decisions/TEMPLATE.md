---
id: "NNNN"
title: "A short title that states the decision"
status: accepted
date: YYYY-MM-DD
supersedes: null
---

# NNNN: A short title that states the decision

Date: YYYY-MM-DD. Status: accepted, drafted by Claude for Gabriel from his request of <date>. It takes effect when Gabriel merges the pull request that adds it.

Write `status: accepted` from the start; never `proposed`. Merging the pull
request is the acceptance (`scripts/validate_records.py` refuses `proposed`).
Use `status: superseded` only when a later decision replaces this one, and
set `supersedes` on the later one. Delete these instructions and the
placeholders below when you copy this file.

## The question

What has to be decided, and why now. Name the records and the runs it comes
from.

## Decision

What is decided, in plain sentences with numbers and units. Anything the
code enforces says which file enforces it.

## What stays

The checks, thresholds, kill rules and files that this decision does not
change.

## Risks and how they are handled

Each risk as a bullet: what could go wrong, and what catches it.
