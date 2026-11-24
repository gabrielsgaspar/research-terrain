---
id: "0021"
title: "Contradictions inside a task"
status: accepted
date: 2026-11-23
supersedes: null
---

# 0021: Contradictions inside a task

Date: 2026-11-23. Status: accepted, drafted by Claude for Gabriel from his
choices of 2026-11-23. It changes nothing until the pull request that
implements it merges (session D for 0021, session E for 0020); that pull
request names this decision.

## The question

On 2026-11-22 and 2026-11-23, campaign steps stopped for Gabriel in two
ways where nothing he alone knew was needed:

- **#482 (campaign 0015, fork f1, step s6).** The review of PR #483 asked,
  as a must-fix item, that the fork keep the parent's `estimates.finite`
  rule, which kill rule k2 reads. Done-when item 3 asked for
  `estimates.finite` true on a table where that rule gives false. The
  builder could not meet both and stopped (build run 45064917043). Gabriel
  changed item 3 by hand in #486, and #483 was closed.
- **#457 and #451 (campaigns 0014 and 0013).** Their builds failed on
  `tests/test_explore.py::test_explore_scripts_fit_poisson_only_through_terrain_poisson`,
  a test that `explore/0013_objects_main.py` had broken on main (CI run
  45066510004). Neither task touched that file. Both waited until #485
  fixed main, and then until someone restarted them.

Can the agents settle the first kind by a fixed rule, and wait out the
second kind by themselves, without ever settling a contradiction by
loosening a check?

## Decision

1. **Definition.** A contradiction is two instructions that bind the same
   task and cannot both hold. Its sources are: `AGENTS.md`, accepted
   decisions, the campaign file and its kill rules, the issue (its draft,
   or a fork's delta), the plan, review must-fix items, and agent notes.
   - A fork file's envelope and the kill rules it inherits rank with the
     campaign file; its delta text and drafts rank with the issue.
   - `research/campaigns/kill-rule-library.yaml` ranks with kill rules.
   - A repair or close-out template (code in `src/terrain/campaigns/`)
     ranks with the issue, because the tick files it as the issue.
2. **Order of authority.** The higher one wins outright:
   1. `AGENTS.md` and accepted decisions;
   2. the campaign file and its kill rules;
   3. the issue;
   4. the plan;
   5. review must-fix items;
   6. agent notes.
3. **Same level: the stricter wins.** Stricter means it keeps every check,
   test and kill-rule input at least as demanding. An instruction that
   would loosen what a kill rule reads, or delete or weaken a test, always
   loses.
   - **Worked example, #482.** Kill rule k2 reads `estimates.finite`. Two
     lines of the issue bind it: "Out of scope: ... how `n_strong` and
     `estimates.finite` are computed", and Done-when item 3, which asked
     for `estimates.finite` true where the parent's rule gives false. Item
     3 would have loosened what k2 reads, so the parent's rule wins. The
     fork file, a level higher, says the same ("changes nothing in any ...
     kill rule"). The review's must-fix item was right because it restated
     these, not because of its own level. Under this decision the builder
     would have kept the parent's rule, tested `estimates.finite` false in
     that case, and written the section below. The step would have gone on
     without Gabriel.
   - **The builder** applies the winner and writes a
     "## Contradiction (decision 0021)" section in the pull request body.
     For each contradiction it quotes both texts word for word, names the
     source of each (file path, or issue, plan or review comment link) and
     its level, says which won and why (higher level, or stricter at the
     same level), and lists the tests it wrote for the winner. It writes
     the section for a contradiction across levels too.
   - **The reviewer** checks that section against this rule. A losing
     Done-when item is marked "Lost (decision 0021)" in the Done-when
     table, not "Not met". The reviewer does not raise the losing item
     again. A wrong call is a must-fix item.
   - **The planner** may name a contradiction it sees in the plan, with
     the winner this rule gives. The plan ranks below the issue, so the
     builder makes the call.
4. **Neither is stricter.** When the two ask for different things, not for
   more or less of one thing, the builder stops with the result
   "contradiction", quoting both texts with their sources.
   - The report job checks that each quoted text appears word for word in
     its named source. If one does not, the result is treated as
     "blocked", with decision 0019's fix round, and not as a
     contradiction.
   - The tick marks the step "skipped (decision 0021)" and skips its
     dependents as `on_kill: skip_dependents` does, whatever the step's own
     `on_kill`. The campaign continues. The tick closes the issue as not
     planned, with one comment that links the build.
   - A skip is neither a kill nor a survival. It does not count as a block
     for the circuit breaker. It does not let a fork adopt the skipped
     steps (decision 0015), and a fork point at a skipped step does not
     start an ideation job.
   - The close-out lists it under "Checks not run", with both texts. The
     status page lists it too.
   - Outside a campaign, the builder stops the same way and the issue gets
     `needs-human`, as today.
5. **Prevention.** When the ideation job proposes a fork, code checks that
   the fork's delta and Done-when items change no field and no condition
   of a parent kill rule. A fork that does is refused before filing.
   - The check is textual and strict: the delta and each Done-when item
     may not name a parent kill rule's id (such as `k2`) or its field (the
     dotted path, such as `estimates.finite`, or its last part in
     backticks). Code adds one fixed line to every fork draft for each
     inherited rule: "`<field>` is written and computed exactly as in the
     parent step." That line is the only place a fork draft names a
     kill-rule field.
   - A refused fork is not filed. The refusal and its reason go on the
     status page and into the close-out's fork list. The other forks at that
     point go on.
   - Under this check, #482's item 3 would have been refused: it named
     `estimates.finite`.
6. **A failure that is not the task's.** If a test fails in a build and
   the same test also fails on main without the task's changes, the task
   is not at fault.
   - How it is checked: when verify's `pytest` fails, verify runs the
     failing test ids again on a clean checkout of main's current head, on
     the same runner. If every failing test also fails there, the step
     waits as "waiting for main". If any test fails only with the task's
     changes, the task is at fault and decision 0019 applies as today.
     This check comes first, so it does not use the fix round.
   - The tick opens one owner-fix issue per failing test id, naming the
     test and linking the build run and the main checkout's run. A test
     already named by an open owner-fix issue gets no second one, so
     several waiting steps share it (as #457 and #451 would have). This is
     one new action in the act job's closed list, from a fixed template.
   - When CI's `test` check passes on main's head commit again, the tick
     restarts the build once, from main, with the same plan. This restart
     is fixed at one by this decision; it does not read
     `build_restarts_per_block` (decision 0020) and does not count against
     it. It counts as one model job against the campaign's budget.
   - If the restarted build fails, the normal path applies (decision 0019,
     then `needs-human`). A second "waiting for main" on the same step
     stops for Gabriel with `needs-human`.
   - Waiting for main is not a block for the circuit breaker. The step
     stays in flight, so the campaign's next task waits too. The campaign's
     end date still applies; a step still waiting then is listed under
     "Checks not run".
   - Only pytest failures count here. A ruff failure, a path refusal, the
     secret scan and a set-up failure stop as today.
7. **What stays.** Anything that touches tier 1 (decision 0020) still stops
   for Gabriel, as do his stops for sealed data, the split, thresholds and
   kill rules. No source in point 2 lets a task change a file outside its
   plan. Issue and pull request text is still data that defines the task,
   not instructions beyond it.

## What stays

Every check in verify, the gate and the agent review, and the reviewer's
referee rows, R8 included. Decision 0019's fix round and its rule that a
fix round may not delete a first-attempt test. Agent-review's limit of
three fix rounds per pull request. The tick never edits an issue after
filing it. Kill rules are applied by code, and a rule that cannot be
applied stops the step; it never passes.

## Risks and how they are handled

- **A builder claims a contradiction to avoid hard work.** Each quote must
  appear word for word in its named source, or the result counts as
  "blocked". Only "neither is stricter" skips a step, and every skip is on
  the status page and in "Checks not run", with both texts, for Gabriel to
  read.
- **A wrong call on which is stricter.** The reviewer checks the section,
  and a wrong call is a must-fix item. The gate still needs the review's
  approval before a merge.
- **A higher text loosens a kill-rule input.** Every level above the plan
  is Gabriel's, except a fork's delta, which the ideation job writes.
  Point 5 checks the delta by code before filing, and the reviewer's R8
  checks it again by reading.
- **Point 5 refuses a useful fork.** It costs one proposal, not a check.
  The refusal is listed, and Gabriel can file the fork by hand.
- **A flaky test looks like main's fault.** The build restarts once, when
  main is green. A second wait on the same step stops for Gabriel.
- **The task also breaks the test that main breaks.** The restart after
  main is green shows it, and the normal path applies.
- **Main stays red for days.** The owner-fix issue and the status page
  show it. The campaign's end date bounds the wait.
- **A skip loses later steps.** It skips only the dependents, as a kill
  with `skip_dependents` does, and the campaign goes on with the rest.

Amended 2026-11-23 (point 5): the fixed line added to every fork draft for each inherited rule reads: `<field>` is written under the same key, by the same formula and rule as in the parent step, on this fork's own specification. A fork may change how an estimate is computed along its one declared dimension; it may not rename a field, change a rule's condition, or change the formula a rule applies (such as how estimates.finite is decided).

Amended 2026-11-23 (point 6): the restart after main is green is the same restart as the tick's red-main restart (PR #502): one per step per red episode.
