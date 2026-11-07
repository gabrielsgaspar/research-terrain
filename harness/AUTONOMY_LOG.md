# Autonomy log

Steps an agent took without asking Gabriel, because he authorised it for a
named task. One entry per step that would normally need his OK (merges,
filing, agent-build, runs, decisions and research records), newest last.

## Task 35: the close-race window by covariate balance (authorised 2026-11-07)

Gabriel's authorisation, on PR #205: update the draft with his answers, merge
it when CI passes, file the issue (`explore`), plan, build, and merge when CI
passes, the reviewer approves and every referee row is OK; run it, check the
pairs per window against the census counts, write the lessons entry and idea
status, and write decision 0008 from the rule. Stop and tell him only if
0.10% fails, the counts do not match, or a check fails. Never write voter
IDs or CPFs into any committed file, log or result.

His answers on the covariates: incumbency from the voter-ID rebuild, in the
balance rule (`ST_REELEICAO` reported, not used); coalition membership left
out; 2022 population within 5 km reported descriptively, not in the rule;
the pre-election clearing share as drafted.

- 2026-11-07: draft 35 updated with these answers, the ID rule, and the
  `cd_ibge` join for `tse_candidates` (the table has no `cd_ibge`, so
  `restrict` needs it from `municipalities`). PR #205.
