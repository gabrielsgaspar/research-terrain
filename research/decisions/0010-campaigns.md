---
id: "0010"
title: "Campaigns: agent work approved in advance, merged by a gate"
status: proposed
date: 2026-11-08
supersedes: null
---

# 0010: Campaigns: agent work approved in advance, merged by a gate

Date: 2026-11-08. Status: proposed, drafted by Claude for Gabriel. It takes
effect when Gabriel accepts it and merges the pull request that adds it with
the campaign workflows, CODEOWNERS and the `AGENTS.md` changes.

## The question

Every agent task waits for Gabriel at three points: he swaps `agent-plan`
for `agent-build`, he merges the pull request, and he starts the explore run
and merges its record. Handoff 5 (2026-11-07) showed that agents can carry a
series of tasks on their own within stated limits, but only by running
locally with his credentials, which no rule in the repository can bind. How
can work Gabriel approved in advance run on GitHub without him, while every
safeguard of the exploration/confirmation split still holds?

## Decision

1. **A campaign is the unit of approval.** A folder
   `research/campaigns/NNNN-slug/` holds `campaign.md` (steps, kill rules,
   budget, datasets, end date) and one issue draft per task step. Gabriel
   approves all of it at once by merging it with `status: active`. Both are
   owned in `.github/CODEOWNERS`, so they cannot change while the campaign
   runs.
2. **The tick is plain code.** `campaign-tick` runs every three hours. It
   reads the campaign files and GitHub, files drafts word for word, moves a
   plan to `agent-build` only if it stays inside the step's `allowed_paths`,
   merges what the gate passes, starts the listed runs, and writes a ledger
   on the campaign's tracking issue. No model decides anything in the tick;
   the planner, builder and reviewer are the existing harness.
3. **The gate decides what merges.** `campaign-gate` is a required status
   check on main. For an agent pull request in an active campaign it passes
   only when CI passes, the agent review approves the head commit, every
   referee row is OK (the rows the campaign lists, by default R5, may be
   "Not applicable", because magnitudes cannot be checked before a run), the
   issue still matches its draft, and every file is inside the step and
   neither protected nor owned. Agent pull requests outside a campaign wait
   for Gabriel's approving review, as before. People's pull requests are not
   the gate's business.
4. **Owned paths stay Gabriel's.** The ruleset on main requires a code
   owner's review for owned paths; the agent App is not on the bypass list.
   So even a wrong gate cannot merge a change to the rules, the workflows,
   the campaign code, ideas, decisions or `confirm/`.
5. **Kill rules are applied by code.** Each explore step lists rules of the
   form `results.json` field, comparison, value. A met rule kills the step;
   a rule that cannot be applied (missing field, not a number) stops it and
   asks Gabriel; it never passes. Gabriel states or confirms every rule
   before the campaign starts (`confirmed: true`), and the campaign file
   records who set each one.
6. **New data only as listed.** A campaign may acquire or build only the
   datasets in its `datasets` list, each with source, licence, a size limit
   and whether it holds personal identifiers. Approving the campaign is
   approving those datasets; the manifest pull requests their runs make are
   merged by the tick after the gate checks them.
7. **Pacing.** At most two campaigns are active, never on the same idea or
   with shared paths. One task is in flight per campaign, one run across all
   campaigns, and one new step starts per campaign per tick. The budget
   (tasks, explore runs, pipeline runs, model jobs) and the end date (at
   most 31 days) stop new steps; what is in flight finishes.
8. **The close-out is the report.** When nothing more can run, the tick
   files a close-out task. Its pull request holds the report, the ledger,
   one lessons entry and one status line for the idea. It touches owned
   paths, so Gabriel always merges it, after reading it. Agents' suggestions
   for new variants go in that report and are never run in the same
   campaign.
9. **Controls.** `campaign-pause` or `campaign-stop` on the tracking issue,
   or closing it; the repository variable `CAMPAIGNS_ENABLED`. Local Claude
   Code sessions never merge (`gh pr merge` is denied in
   `.claude/settings.json`).

## What does not change

The exploration/confirmation split, `confirm/` and the sealed half; that
accepted decisions and kill criteria in idea files change only by Gabriel;
the builder's allowlists and protected paths; that every explore run is
recorded; that nothing on the exploration half is a finding.

## Risks and how they are handled

- **Forking paths.** A campaign could try many variants on the exploration
  half. Every variant is listed before the campaign starts, every run is
  recorded, and new variants are suggestions only.
- **The agent writes its own exam.** Kill rules are set and confirmed by
  Gabriel in the campaign PR, not by agents during the run.
- **Same-model review.** The reviewer shares the builder's blind spots. The
  gate adds checks that do not depend on it (files, draft match, CI), and
  the close-out puts a person at the end of every campaign.
- **Silent stalls.** A blocked step mentions Gabriel on the tracking issue
  and gets 24 hours before the campaign closes out.
- **Usage limits.** The model jobs run on the subscription token, shared
  with interactive sessions. A job that hits a limit fails and blocks its
  step; Gabriel restarts it by hand. The pacing above keeps jobs few.

## How we will know it works

The pilot campaign replays a check whose answer is known (for example idea
0003's power check, run 42367009833) and must reach the same verdict with
no help, with the gate's calls matching what Gabriel would have done.
