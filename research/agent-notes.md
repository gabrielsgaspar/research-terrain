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

## Scoreboard

| Campaign | Steps | Blocks | Fix rounds | Retries | Hours from start to finish | Notes added |
| --- | --- | --- | --- | --- | --- | --- |
| 0007 | 23 | 8 | 1 | 15 | 45.1 | 3 |
