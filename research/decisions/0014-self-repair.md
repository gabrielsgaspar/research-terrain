---
id: "0014"
title: "Self-repair: a campaign may fix its own failing data steps, within limits"
status: accepted
date: 2026-11-11
supersedes: null
---

# 0014: Self-repair: a campaign may fix its own failing data steps, within limits

Date: 2026-11-11. Status: accepted, drafted by Claude for Gabriel. It takes
effect when Gabriel merges the pull request that adds it with
`src/terrain/campaigns/repair.py`, the changes to the tick, the gate and
the GitHub reader in `src/terrain/campaigns/`, the one-line change to
`.github/workflows/campaign-tick.yml` and the `AGENTS.md` change. It adds to
decision 0010 and changes one thing in it, named below.

## The question

A data-pipeline step that fails is started again twice by the tick. When it
still fails, the cause is almost always in the code (a column renamed by the
publisher, a type a build did not expect), and the step waits for Gabriel,
who files a fix task by hand. That fix touches only files he already
approved for the campaign. Can the campaign file that fix itself, through
the planner, builder, reviewer and gate it already has, so that Gabriel is
asked only when the fix also fails?

## What changes in decision 0010

Until now, the only code a campaign could merge was code an approved issue
draft asked for. Now a campaign that says `self_repair: true` may also
merge a repair: code the tick asked for from a fixed template, within the
limits below. Nothing else in decision 0010 changes.

## Decision

1. **Opt-in.** A campaign file may set `self_repair: true`; the default is
   false, so campaigns written before this are unaffected. Anything but
   `true` or `false` is a validation problem. The `campaign-design` skill
   asks Gabriel and records his answer in Provenance.
2. **When.** The tick files a repair only when all of these hold: the
   campaign has `self_repair: true`; a `pipeline_run` step is blocked
   because its run ended 'failure' or 'timed_out'; both automatic retries
   are used; the step has no repair yet; the campaign has fewer than two;
   the model-job budget is not used up; no other task of the campaign is in
   flight (otherwise it waits); and the campaign is not paused, stopped or
   past its end date.
3. **What.** One issue, filed through the tick's existing `create_issue`
   action with the labels `campaign` and then `agent-plan`. Its title and
   body come from a fixed template in `src/terrain/campaigns/repair.py`:
   the goal (make the run succeed without changing what the dataset is);
   the failed run's number and the last lines its failed job printed (at
   most 60 lines and 4,000 characters, cleaned), in a fenced block the text
   calls data, not instructions; the allowed files, one per line; the rules
   for the fix; what "done" means (a test that rebuilds the failure on a
   small input made inside the test, and ruff and pytest). A hidden marker
   `<!-- campaign-repair: NNNN/sN/1 -->` ties it to the step. The GitHub
   reader fetches the log lines with the read permission the tick's decide
   job already has; the tick stays a pure function of what was read.
4. **How it moves.** Like any task step: the tick moves the plan to
   `agent-build` only if every file it lists is an allowed file; the gate
   decides the merge, and the tick merges.
5. **The gate.** For a pull request whose issue carries the repair marker,
   `campaign-gate` passes only when the campaign is active with
   `self_repair: true`; the step exists and is a `pipeline_run`; every
   changed file is an allowed file and is neither protected nor owned; CI's
   `test` passes on the head commit; the agent review approves that commit;
   and the issue's title, and its body outside the log block, are exactly
   what the template gives for this campaign and step. Anything else fails.
6. **After it merges.** The tick starts the step once more, on main as it
   now is, with ledger lines for each stage (repair filed, repair merged,
   run started). If that run fails, the step blocks and Gabriel is
   mentioned: "Retried 2 times, repaired once." If the repair itself blocks
   (the planner needs clarification, three fix rounds are used, the gate
   fails), the step blocks and Gabriel is mentioned with that cause.
7. **Counted.** A repair's model jobs count against `max_model_jobs`. The
   close-out's friction facts list every repair, one row each.

## Hard limits

- Only `pipeline_run` steps. Never an `explore_run` step and never an
  explore script: analysis code is not changed by an agent after it has met
  data.
- Never for a kill rule that could not be read, and never a change to kill
  rules or campaign files.
- The allowed files are the `allowed_paths` of the `build` task steps the
  run step comes after (directly or through other steps), without protected
  paths, paths owned in `.github/CODEOWNERS`, anything under `explore/` or
  `tests/test_explore*`, the agent notes and the campaign's own folder. So
  builders of sealed data, which are owned, stay Gabriel's.
- At most one repair per step and two per campaign.
- No model call in the tick or the gate.

## Risks and how they are handled

- **Text from a failed run reaches the planner.** A log can hold anything a
  script printed, including text written to look like instructions. The
  tick removes escape sequences and non-printing characters, cuts long
  lines, keeps at most 60 lines and 4,000 characters, turns backticks into
  quotes (so the text cannot leave its fenced block) and breaks HTML
  comment marks (so it cannot carry a campaign marker). The issue says the
  block is data, not instructions. Whatever the planner then proposes, the
  plan may list only the allowed files, and the gate checks the files, CI,
  the review and the template, none of which the log can change. Numbers
  shaped like CPFs or voter IDs are replaced, as a last guard; logs must
  not hold them in the first place (`AGENTS.md`).
- **A fix that hides a data problem.** The easiest way to make a failing
  build pass is to loosen the check that failed. The template forbids it
  in plain words, and forbids changing the source unless the campaign file
  names a fallback; if that is the only fix, the planner must answer
  "needs clarification", which blocks the step and asks Gabriel. The fix
  must come with a test that rebuilds the failure. The reviewer reads the
  diff against those rules. Every build's output path hashes its code, so a
  repaired build writes a new path and the manifest PR shows it. And the
  close-out lists every repair, so Gabriel reads each one at the end.
- **Same-model review.** As in decision 0010: the gate's file, template and
  CI checks do not depend on the reviewer, owned paths still need Gabriel,
  and the close-out puts him at the end of every campaign.
- **A loop of repairs.** One per step, two per campaign, and the run after
  a repair is never retried or repaired again.

## What does not change

The exploration/confirmation split, `confirm/` and the sealed half; that
accepted decisions, kill rules and campaign files change only by Gabriel;
explore steps and explore scripts, which are never repaired; the builder's
allowlists and protected paths; owned paths, which still need his review
and which the agent App cannot bypass; that the tick and the gate call no
model; the act job's closed list of actions, apart from accepting the
repair marker on an issue body.

## How we will know it works

The next campaign with data steps sets `self_repair: true`. A step that
fails on a code problem is repaired, merged and run again without Gabriel,
and its close-out row shows the repair; a step whose only fix would loosen
a check stops with "needs clarification" instead.
