---
id: "0013"
title: "Agent notes: campaigns write what slowed them down, agents read it"
status: accepted
date: 2026-11-11
supersedes: null
---

# 0013: Agent notes: campaigns write what slowed them down, agents read it

Date: 2026-11-11. Status: accepted, drafted by Claude for Gabriel. It takes
effect when Gabriel merges the pull request that adds it with
`research/agent-notes.md`, the close-out change in
`src/terrain/campaigns/closeout.py` and `gate.py`, the check in
`scripts/validate_records.py`, CODEOWNERS and the `AGENTS.md` change. It
adds to decisions 0010 and 0012 and changes nothing else in them.

## The question

Each close-out report carries friction facts (blocks, extra plans, fix
rounds, repeated runs, long gaps) and proposes harness changes. Until now
nothing happened with a proposal unless Gabriel picked it and filed a task,
so the next campaign made the same mistakes. How can what one campaign
learned reach the agents of the next one, without a person choosing and
applying it, and without loosening any rule?

## Decision

1. **The notes file.** `research/agent-notes.md` holds short notes of
   advice, one bullet each, in a fixed shape:
   `- [N001] (role) Advice in one sentence. From: campaign NNNN, the friction fact in a few words. Added YYYY-MM-DD.`
   The role is one of design, planner, builder, reviewer, closeout. Below
   the notes, a Scoreboard table has one row per closed campaign: steps,
   blocks, fix rounds, retries, hours from start to finish, notes added. It
   starts empty.
2. **The close-out writes it.** Every close-out task adds at most three
   notes, each answering one row of its friction facts and each for one
   role, and exactly one Scoreboard row copied from the facts. With no
   friction it adds no note and still adds the row. The report's "Proposed
   harness changes" section has two parts: "Notes added" (ids and text) and
   "Checks in code proposed" (not applied; Gabriel batches them later).
3. **Every agent reads it.** `AGENTS.md` tells every agent to read the notes
   for its role right after `AGENTS.md`; the `campaign-design` skill reads
   the notes for role design.
4. **Notes are advice, never rules.** `AGENTS.md` and the task's plan always
   win. A note must be advice about how to do the work: it must not restate
   or soften a rule, and must not tell an agent to change what a task may
   touch. An agent that finds a note wrong or harmful does not follow it and
   says so in its result.
5. **Limits, checked in code** (`scripts/validate_records.py`, run by the
   tests): the file parses in the shape above; at most 30 notes; the advice
   is at most 200 characters; ids are unique; each note's campaign has a
   Scoreboard row. A note is refused if it contains, in any letter case,
   any of: skip, ignore, disable, bypass, sealed, confirm/, kill rule,
   threshold, needs-human, CODEOWNERS, .github. When the file would pass 30
   notes, the close-out first merges or removes the oldest and says which.
6. **Who may change it.** The file is owned in `.github/CODEOWNERS`, so it
   changes only in pull requests Gabriel approves. The close-out already is
   one (decision 0012): `closeout_paths` in `src/terrain/campaigns/gate.py`
   lists it. No campaign step may list it in `allowed_paths`
   (`src/terrain/campaigns/spec.py` refuses it).

## What does not change

- The gate (`campaign-gate`) and its checks, apart from the close-out file
  list gaining this one file.
- Owned paths: they still need Gabriel's review, and the agent App still
  cannot bypass it.
- Kill rules: still applied by code to `results.json`; no note can change
  one.
- The exploration/confirmation split, `confirm/` and the sealed half.
- The tick and the gate call no model. No workflow changes.

## Risks and how they are handled

- **A note that loosens a rule by its wording.** The banned words catch the
  common ways; `AGENTS.md` and the plan win over any note; Gabriel reads
  every note in the close-out pull request before approving it.
- **Notes pile up or go stale.** At most 30; the oldest are merged or
  removed first, and the report says which.
- **A note that is plainly wrong.** Agents are told not to follow it and to
  say so, which puts it in front of Gabriel in the next result.

## How we will know it works

Over the next campaigns, the Scoreboard's blocks, fix rounds and retries per
step go down, and the notes added each time cite new friction rather than
the same fact again.
