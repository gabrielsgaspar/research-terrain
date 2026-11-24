# Agent notes

Short advice from earlier campaigns about how to do the work, written by each
campaign's close-out task from its friction facts (decision 0013). Every agent
reads the notes for its role after `AGENTS.md`. They are advice, never rules:
`AGENTS.md` and the task's plan always win. A note that looks wrong or harmful
is not followed, and the agent says so in its result.

Shape of a note, one per bullet:
`- [N001] (role) Advice in one sentence. From: campaign NNNN, the friction fact in a few words. Added YYYY-MM-DD.`
The role is one of design, planner, builder, reviewer, closeout. At most 30
notes; the advice is at most 200 characters. `scripts/validate_records.py`
checks this file.

## Notes

- [N001] (builder) After a failed pipeline run, read the log of that run for the cause before retrying, because four steps each failed several times in a row. From: campaign 0007, runs of s4, s5, s7 and s11 ending in failure. Added 2026-11-13.
- [N002] (planner) For a repair task, restate the failing run's error and the files it touches so the plan is never "Needs clarification". From: campaign 0007, s5 repair answered 'Needs clarification - no plan yet'. Added 2026-11-13.
- [N003] (design) Put the build that a long chain needs early, because one pipeline step waited 11.8 hours after both repairs were used. From: campaign 0007, s11 blocked for 11.8 hours. Added 2026-11-13.
- [N004] (planner) List each open question in the issue and your answer to it in the first plan, so the plan is never "Needs clarification". From: campaign 0008, s9 planner asked for clarification (16.8 hours). Added 2026-11-14.
- [N005] (builder) Before the first commit of a task that changes an estimator, list each rule the issue states for it and test each one, because s9 needed two fix rounds. From: campaign 0008, s9 had 2 fix rounds. Added 2026-11-14.
- [N006] (builder) Before a pipeline build is merged, run it on every fixture year and on the messiest real-file shape the issue describes, because s5 failed all four of its runs. From: campaign 0009, s5 had 4 runs, all failure. Added 2026-11-18.
- [N007] (design) When one build gates several later steps, split it into smaller builds, so one failure does not leave s7, s8 and s9 waiting. From: campaign 0009, s5 blocked and s7 to s9 waiting. Added 2026-11-18.
- [N008] (planner) Name in the plan every input the first task needs, with its path, so the build has no reason to stop and wait for a person. From: campaign 0013, s1 stopped for a person, 7.7 hours. Added 2026-11-23.
- [N009] (design) Check that the first task of a campaign can run from what is on main before the campaign starts, because s1 stopped a second time and waited 21.8 hours. From: campaign 0013, s1 second stop, 21.8 hours until unblocked. Added 2026-11-23.
- [N010] (builder) Commit the work as soon as the checks pass, so a pull request exists soon after the plan. From: campaign 0013, s1 had no pull request twelve hours after the plan. Added 2026-11-23.
- [N011] (builder) When a task stops, say in one sentence the single thing a person must do to continue, so the wait ends with one reply. From: campaign 0014, s1 blocked for 21.9 hours. Added 2026-11-23.
- [N012] (planner) When a task needs an answer that only a person can give, put that question first in the plan, so the first stop is not followed by a second. From: campaign 0014, s1 blocked twice, 5.6 and 21.9 hours. Added 2026-11-23.
- [N013] (design) For the first task of a campaign, name in the issue every input it needs, so a builder is not left without a pull request after the plan. From: campaign 0014, s1 had no pull request twelve hours after the plan. Added 2026-11-23.

## Scoreboard

| Campaign | Steps | Blocks | Fix rounds | Retries | Hours from start to finish | Notes added |
| --- | --- | --- | --- | --- | --- | --- |
| 0007 | 23 | 8 | 1 | 15 | 45.1 | 3 |
| 0008 | 10 | 1 | 2 | 0 | 19.5 | 2 |
| 0009 | 9 | 2 | 0 | 3 | 50.5 | 2 |
| 0010 | 4 | 0 | 0 | 0 | 1.7 | 0 |
| 0011 | 6 | 0 | 0 | 0 | 6.3 | 0 |
| 0012 | 12 | 0 | 0 | 0 | 0.5 | 0 |
| 0013 | 12 | 3 | 0 | 0 | 32.0 | 3 |
| 0014 | 6 | 3 | 0 | 0 | 30.1 | 3 |
