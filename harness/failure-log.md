# Failure log

The repository's record of every campaign stop that needed Gabriel: its
cause, its category and the harness change that fixed it. The categories are
those of `STOP_CAUSES` in `src/terrain/campaigns/closeout.py`:

- plumbing: the harness let the work down (a limit, a timeout, a stall with
  no pull request, a closed-PR stop, a race between ticks, a test broken on
  main, a runner or API failure);
- spec: a contradiction, or an unclear issue, plan or draft;
- design: a kill rule, a budget or the campaign's design stopped the work;
- agent: an agent's own error, such as a failing test it wrote or a fix round;
- handled: the tick resolved it without Gabriel.

Plumbing stops are never turned into agent notes (`research/agent-notes.md`):
they are the harness's fault, so they are recorded here, where a harness
change can answer them.

Sections are only ever appended. From campaign 0015 on, every close-out
appends one dated section, written by the campaign tick from the
categorised friction facts: each plumbing stop, with its cause and the hours
it lost. The close-out agent copies that section unchanged and writes nothing
else here; the campaign gate refuses a close-out that changes anything else
in this file. A fix found later goes in a later section, never into an
earlier one.

## 2026-11-24: the history so far (from Gabriel's notes of 22 November)

Hours lost are the hours until the block was cleared, from the campaign's
report (`research/campaigns/NNNN-*/report.md`), where it shows them.

| Campaign and step | What stopped | Category | Hours lost | Fixed by |
| --- | --- | --- | --- | --- |
| 0014 s1 (#457) | The full test suite took about 123 s and the builder's shell stopped commands at 120 s, so the build could not show the suite passed. | plumbing | 5.6 | #476 (builder commands may run 15 minutes, tests run in parallel) |
| 0013 s1 (#451) | A Poisson fit failed on some synthetic seeds and the script wrote null. | agent | 7.7 | #476 (the robust helper `terrain.poisson.fepois`; synthetic tests pass on 5 seeds) |
| all campaigns | A failed verify or an unfinished build went straight to `needs-human`. | plumbing | - | decision 0019 (#484: one automatic fix round) |
| 0013 s5 (#456, #459) | The step was filed twice: the second tick's issue list did not yet show the issue the first tick had just filed. | plumbing | - | #484 (the tick skips filing when an open issue has the same task marker) |
| all campaigns | A tick's merge was refused while a required check was still in progress. | plumbing | - | #484 (a refused merge with a check in progress waits) |
| all campaigns | Untracked runner files were left in the checkout. | plumbing | - | #484 (checked) |
| records | Decisions were merged but still said `proposed`. | plumbing (records) | - | #509 |
| 0013 s1 (#451), 0014 s1 (#457) | No pull request 12 hours after the plan, and the builds were never started again: the build of #484 skipped its verify and publish jobs without saying so. | plumbing | 0.7 each, after 12 hours without a pull request | #502 (the tick restarts a stalled build) |
| 0014 s1 (#457), 0013 s1 (#451) | The rebuilds failed on a test another pull request had broken on main (`explore/0013_objects_main.py` called `pyfixest.fepois`; #476 and #479 merged against an older main). | plumbing | 21.9 (0014), 21.8 (0013) | #485 (the fix on main), #502 (red-main pause), decision 0021 (waiting for main, #511 and #512) |
| 0015 (#482) | A review must-fix item contradicted a Done-when item. | spec | - | #486, then decision 0021 |
| 0015 (#482) | A closed pull request blocked a newer plan. | plumbing | - | session E1's #514 |
| 0013, 0014 close-outs (#507, #508) | Two close-outs ran at once: both gave new notes the ids N008 to N010, and they conflicted in `research/agent-notes.md` and `research/lessons.md`. | plumbing | - | #515 (one close-out at a time, note ids chosen by the tick) |
| 0008 s9 | The planner asked for clarification on a thin draft. | spec | 16.8 | no harness change; note N004 |
| 0009 s5 | Data edge cases broke the build twice. | agent | - | decision 0016 (#434: the repair sees the failure; bounded data rules) |
| 0010, 0012 | Design choices killed the campaigns. | design | - | none needed |
| 0011 | Fork proposals were refused for citing only a contract. | spec | - | #435 (fork evidence files) |
