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
- 2026-11-07: PR #207 (the fixed draft) merged after CI passed; issue #206
  updated to match and re-planned. The plan followed the issue (two files,
  Done when as written, pre-election years only), so `agent-plan` was
  swapped for `agent-build`.
- 2026-11-07: PR #212 (agent build for #206) merged. CI `test` passed;
  reviewer Approve on 865c48d, no must-fix. Referee R1-R4, R6, R7 OK; R5
  "Not applicable" (no numbers before the run), read as no referee problem,
  as on #203. The reviewer's nice-to-haves (restrict the crosswalk too; run
  the term checks at 0.50%; conflicting codes in the incumbency test) were
  not acted on: none changes the result, and pushing to the agent branch
  would trip the review guard.
- 2026-11-07: explore run 42366460941 started on main (3b0500a).
- 2026-11-07: record PR #219 checked. Pairs per window match the census (run
  41719271978) in every election at 0.25%, 0.50%, 1% and 2%; 0.10% passes
  (omnibus p 0.191), so no stop. The 0.50% power row reproduces decision
  0007 (0.944, 0.797, 0.448). Incumbency counts are about half of the Legal
  Amazon counts profiled before the issue; no candidate lacks a municipality
  match (the record prints an empty list after "per year:"). Years read are
  at most E-1. No 11- or 12-digit run in the record or its JSON except the
  run ID. Rebased onto main (index conflict resolved by regenerating).
- 2026-11-07: lessons entry, idea 0001 status and log lines, and decision
  0008 (0.25%, accepted by rule; Gabriel to review) written on the record
  branch, index regenerated; PR #219 merged on CI. 0.50% is not balanced
  (omnibus p 0.119, incumbency), so task B's result carries that caveat in
  the lessons entry, the idea status and decision 0008.

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
- 2026-11-07 (T4): issue #214's plan read (two files, Done when as the
  issue, pre-election years only; null-outcome races dropped before
  numbering, which changes no result); swapped `agent-plan` for
  `agent-build`.
- 2026-11-07 (T4): PR #216 (agent build for #214) merged. CI `test` passed
  on head 990a0dec; reviewer Approve on that commit, no must-fix; only the
  two planned files. Referee R1-R4, R6, R7 OK; R5 "Not applicable" (no real
  run at build time), read as no referee problem, as on PRs #191 and #196
  that Gabriel merged. Explore run 42367009833 started on main (35f6bffa).
- 2026-11-07 (T4): record PR #217 (run 42367009833) merged on CI. Counts
  match what was expected: 45 / 80 / 157 races at 0.5% / 1% / 2%
  (2008-2020, exploration half), against about 45 / 81 / 155 (half of the
  Legal Amazon scoping counts). Only the record, its JSON and the index.
- 2026-11-07 (T4): lessons entry and idea 0003 status line for run
  42367009833. Drafted kill criterion 1 is met; the idea's status stays
  `proposed` (its kill criteria are unconfirmed drafts), recommended dead.
  Own PR, merged on CI.
- 2026-11-07 (T7): draft pre-analysis plan for idea 0001,
  `harness/drafts/pap-draft.md`, marked "Draft; nothing here is
  registered". Written after decision 0008 (0.25%) merged in #219; window,
  power (0.868 / 0.622 / 0.307) and kill criterion 3's options filled from
  decision 0008 and run 42366460941 only. Nothing under `confirm/` or
  `sealed/` read or touched. Option (v) is closed (the window is narrower);
  recommendation (ii). Open choices A-C left to Gabriel. Own PR, merged on
  CI.
- 2026-11-07 (T5 follow-up): `README.md`'s "What exists" line on task 35
  refreshed now that decision 0008 is merged (0.25%, 0.50% unbalanced on
  incumbency), with idea 0003's power result and the PAP draft. Same PR as
  T7.
- 2026-11-07: PR #220 (T7 draft and README) merged on CI; only its three
  files.
- 2026-11-07: final report `harness/reports/2026-11-07-autonomous-run.md`
  (handoff 5, section 4). Own PR, merged on CI. No hard stop was hit in
  either session's threads.

### Follow-up: Gabriel's choices on the run report (2026-11-07)

Gabriel reviewed `harness/reports/2026-11-07-autonomous-run.md` and asked,
under handoff 5's rules and hard stops, that his choices be recorded and the
next step run without waiting. Each step below is one he named.

- 2026-11-07: decision 0008: his acceptance added under "Accepted" (the
  accepted-by-rule line and the decision's text unchanged).
- 2026-11-07: idea 0003 marked `dead`: he confirmed its three kill criteria
  as drafted (the "(drafted; confirm)" marks removed, texts unchanged);
  kill criterion 1 is met (run 42367009833). Ideas table row updated.
- 2026-11-07: PR #213 labelled "unverified; drafted from memory; do not
  merge" and left open. GitHub rejects commas in label names, so his commas
  became semicolons. A second label, created by mistake while testing
  names, was deleted at once; no other label was touched.
- 2026-11-07: `harness/issue-drafts/README.md`: task 35's row said "task B
  recorded (done; #204)", which reads as if #204 had done it; now "done
  (#212; record #219, decision 0008)". Row 36 updated the same way; rows 37
  and 38 added.
- 2026-11-07: draft 37 (aligned, unaligned and mixed close pairs at 0.25%
  for idea 0004; same election, no lineage table, no outcome) and draft 38
  (kill criterion 1 of idea 0001 recounted at 0.25%, with 0.50% as a
  reproduction check; no outcome), for decision 0009's counts. Own PR,
  merged on CI.
- 2026-11-07: PR #222 merged on CI (only its eight listed files). Issues
  #223 (draft 37) and #224 (draft 38) filed with `explore` and
  `agent-plan`.
- 2026-11-07: plans on #223 and #224 read: each follows its issue (two
  files, Done when as written, no outcome table). The #224 planner's risk
  (0.50% type counts 455 / 1,987 in decision 0008 against 551 / 2,083 in
  run 41839642406, 2008-2020) is the 96 "both" candidates, which kill
  criterion 1 counts on each side; not a conflict. `agent-plan` swapped for
  `agent-build` on both.
- 2026-11-07: PR #225 (agent build for #224) merged. CI `test` passed on
  head 43735a95; reviewer Approve on that commit, no must-fix; only the two
  planned files. Referee R1-R3, R6, R7 OK; R4 and R5 "Not applicable"
  (counts only, no inference or estimate), read as no referee problem, as
  before. Nice-to-haves (test identities, a shared reader) not acted on:
  none changes a count.
- 2026-11-07: PR #226 (agent build for #223) merged. CI `test` passed on
  head 61532257; reviewer Approve on that commit, no must-fix; only the two
  planned files. Referee R1-R3, R5-R7 OK; R4 "Not applicable" (counts and
  an analytic scaling), read as no referee problem. Nice-to-haves (a comment
  on text-order ties, a fake store for `load_candidates`, pooled asserts)
  not acted on: the per-year stop checks already imply the pooled totals.
- 2026-11-07: explore runs started on main (53b783cf):
  0001_kill_criterion_1_window (run 42384056410) and 0004_alignment_counts
  (run 42384059012).
- 2026-11-07: record PR #228 (run 42384056410, kill criterion 1 at 0.25%)
  merged on CI. Counts match what issue #224 said to expect: the 0.50%
  table equals run 41839642406's in every cell, and 0.25% candidates are
  956 / 1,156 / 1,192 / 1,352 / 1,082 (5,738 pooled), twice decision 0008's
  pairs. Only the record, its JSON and the index.
- 2026-11-07: record PR #227 (run 42384059012, alignment counts) **not
  merged**. Its counts match what issue #223 said to expect (pairs per
  election; aligned + unaligned + mixed + left out = pairs; left out under
  5%), but its verdict on drafted kill criterion 1 is inverted ("met" for
  1,414 and 1,446). A mismatch in the notes, so no merge; the record was not
  edited by hand. PR closed with a comment, branch kept. Fix issue #229
  filed (`explore`, `agent-plan`): verdict and its sentence only. This is
  fix round 1 for task 37.
- 2026-11-07: decision 0009 (`research/decisions/0009-pap-kill-criteria.md`)
  written from Gabriel's five points, in his words, and marked accepted by
  him; it supersedes only decision 0007's "How kill criteria 3 and 4 are
  applied" for the confirmation half (0007's file and idea 0001's
  kill-criteria texts unchanged). Kill criterion 1's counts at 0.25% from
  run 42384056410. A separate section, "What follows from it", is Claude
  Code's reading (kill criterion 4 on the direct effect alone, at 5%; the
  fallback triggered by any covariate), for Gabriel to check.
- 2026-11-07: plan draft `harness/drafts/pap-draft.md` revised to match
  decision 0009, still "Draft; nothing here is registered": the
  confirmation framed as a registered test of the direct effect; power
  carried over; balance fallback; an incumbency adjustment proposed (an
  incumbent-side exposure contrast that does not flip under re-flips), for
  Gabriel to confirm. Nothing under `confirm/` or `sealed/` read.
- 2026-11-07: idea 0001 status line (still `exploring`) and log line;
  lessons entry for run 42384056410. Own PR, merged on CI.
- 2026-11-07: plan on #229 read: two files, the verdict flipped, one test
  assertion corrected, boundary tests added, no count or power change;
  `agent-plan` swapped for `agent-build`.
- 2026-11-07: PR #230 (decision 0009, plan draft, idea 0001 status,
  lessons) merged on CI; only its six listed files.
- 2026-11-07: PR #231 (agent fix for #229) merged. CI `test` passed on
  head a759f384; reviewer Approve on that commit, no must-fix; only the two
  planned files; the diff changes only the verdict, its sentence and tests.
  Referee R1-R3, R6, R7 OK; R4 and R5 "Not applicable" (counts only), read
  as no referee problem. Explore run 42384829937 started on main (bb59caa).
- 2026-11-07: record PR #232 (run 42384829937, alignment counts) merged on
  CI. Counts match what issue #223 said to expect (478 / 578 / 596 / 676 /
  541 pairs; every election sums; left out 5 of 478 in 2008, none after),
  and its JSON equals run 42384059012's apart from the corrected verdict
  ("not met"). Only the record, its JSON and the index. Task 37 needed one
  fix round.
- 2026-11-07: idea 0004 status line (still `proposed`, kill criteria still
  drafts) and log line with the counts and implied power of run
  42384829937; lessons entry; harness lesson on the inverted verdict (my
  draft's wording "(200 each) is met" was ambiguous, and its Done when had
  no direction test). Own PR, merged on CI.
- 2026-11-07: PR #233 merged on CI; only its five listed files.
- 2026-11-07: follow-up report `harness/reports/2026-11-07-review-follow-up.md`
  and a filing-checklist item in `harness/issue-drafts/README.md` (a
  kill-criterion verdict states the idea's condition and is tested both
  ways). Own PR, merged on CI. One stop was hit and contained (record #227
  not merged); no hard stop was hit.
