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
- 2026-11-07: PR #205 merged after CI passed (draft only). Issue #206 filed
  with `explore` and `agent-plan`.
- 2026-11-07: the planner withheld a plan: my Done-when 5 example
  contradicted the rule (the sequence picks 0.50%, not 0.25%). Draft fixed
  (two examples, one per case), "once any window fails, no wider window can
  be chosen" stated, 2020-2023 outcomes confirmed from the manifest. The rule
  itself is unchanged.
- 2026-11-07: coordination with a second session running handoff 5: it takes
  T2-T7; this session keeps T1 (task 35, issue #206).

## Handoff 5: the autonomous run (Claude Code session projects-4c, 2026-11-07)

Authorised by `research-terrain-handoff-5.md` (sections 1-3): merges,
`agent-build` and decisions accepted by rule, within its limits and hard
stops. Task 35 (T1) was already under way in another session (projects-3e)
under the authorisation above; this session took T2-T7 and asked that
session to keep T1.

- 2026-11-07 (T2): scanned every tracked file under `data/fixtures/`,
  `research/`, `explore/` and `paper/` for CPF and voter ID numbers (CPF and
  voter-ID check digits on every 11- and 12-digit run; the CPF and voter-ID
  columns of the seven TSE candidate fixtures). None found: the fixture
  columns hold zero-padded row numbers (CPF is `-4` in 2024), and the only
  11-digit runs that pass the CPF check are run ID 42193625417, by chance.
  No stop (2.6).
- 2026-11-07 (T2): the identifier rule in `AGENTS.md` (protected; handoff 5
  section 1 allows this rule only), own PR, merged on CI.
- 2026-11-07 (T3): idea files 0003 (mayoral close races) and 0004
  (alignment with the elected mayor), both `proposed`, kill criteria marked
  "(drafted; confirm)"; the swing-voter line in idea 0001's body (status
  untouched); the ideas table (0001's row corrected from "proposed" to
  "exploring (2026-11-03)", as its status has said since then). Own PR,
  merged on CI. Idea 0003's close-race counts are the scoping counts of
  session projects-3e (first-round margins; 34 run-off municipalities).
- 2026-11-07 (T5): `harness/LESSONS.md` entry (requested tests go in "Done
  when" before `agent-build`); the 2026-11-06 lessons Implication tidied
  (first, duplicated "no kill criterion is met on this half" removed, no
  other word changed); `README.md`'s "What exists" refreshed in plain
  words. Own PR, merged on CI.
- 2026-11-07 (T4): draft 36 (municipality-level power of close mayoral
  races, idea 0003; pre-election outcome years only), own PR, merged on CI.
  Run-off ids, vote columns and the `ELEITO` check come from session
  projects-3e's profiling of the raw TSE files.
- 2026-11-07 (T3): party-lineage proposal `data/reference/party_lineage.yaml`
  opened as a draft PR, **not merged** (protected path; handoff 5 says
  proposal only). Drafted from memory, unverified.
- 2026-11-07 (T4): issue #214 filed from draft 36 (`explore`, `agent-plan`).
- 2026-11-07 (T6): drafts of "What it doesn't do" and "Relevance to us" in
  the six core literature notes, each headed "(drafted by Claude Code;
  Gabriel to rewrite)". Own PR, merged on CI. They are not Gabriel's text.
