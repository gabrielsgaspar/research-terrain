# Campaign 0007 report: Gold, crime and the ballot box: does the gold price reshape local democracy where gold lies?

What we tested: whether the gold price, times where gold lies in the ground, raises garimpo (artisanal gold mining) area in exploration-half municipalities, as the first step before looking at local politics.
What happened: the first-stage kill rule was met (clustered F 2.436, below 10), so step s15 was killed and steps s16 to s23 were skipped.
What it means: on the exploration half the first stage is too weak by the design's own test, so the politics step never ran and nothing here is a finding.
Decisions for you: 3 decisions, the first being the idea's status, where the agent recommends `dead`.

## Summary

Step s9 (feasibility) survived all four of its kill rules. Step s15 (first stage) was killed by k1: the municipality-clustered F statistic is 2.436, below 10 (`research/explore-runs/0007/43438404852.md`). The estimate itself is positive (beta 0.00439) and the randomisation-inference p is 0.000999, but with one common price shock the clustered errors are the stated test, and it failed. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0007-gold-and-the-ballot/ledger.md`):

- s1 (task, #337, PR #338): merged.
- s2 (pipeline run, PR #339, run 43067424648): recorded.
- s3 (task, #340, PR #341): merged.
- s4 (pipeline run, repair #344, PR #359, run 43121111036): recorded.
- s5 (pipeline run, repair #346, PR #357, run 43117767583): recorded.
- s6 (task, #342, PR #343): merged.
- s7 (pipeline run, PR #362, run 43180577125): recorded.
- s8 (task, #348, PR #356): merged.
- s9 (explore run, PR #363, run 43181711849): survived. Record: `research/explore-runs/0007/43181711849.md`.
- s10 (task, #364, PR #365): merged.
- s11 (pipeline run, PR #371, run 43435600642): recorded.
- s12 (task, #366, PR #367): merged.
- s13 (pipeline run, PR #372, run 43436935000): recorded.
- s14 (task, #368, PR #369): merged.
- s15 (explore run, PR #373, run 43438404852): killed. Record: `research/explore-runs/0007/43438404852.md`.
- s16 (task): skipped, step s15 was killed.
- s17 (pipeline run): skipped, step s16 was skipped.
- s18 (pipeline run): skipped, step s16 was skipped.
- s19 (task): skipped, step s16 was skipped.
- s20 (pipeline run): skipped, step s19 was skipped.
- s21 (pipeline run): skipped, step s20 was skipped.
- s22 (task): skipped, step s19 was skipped.
- s23 (explore run): skipped, step s22 was skipped.

## Results and their limits

These are exploration-half results. Nothing here is a finding: a result from the exploration half is a reason to register a design, not a conclusion.

Feasibility (`research/explore-runs/0007/43181711849.md`):

- Municipalities with gold in the geology: 231, in 6 states with at least 10 of them.
- Share in the largest state (MG): 0.2121.
- Share of gold titles with a request year: 1.
- Municipalities with a pre-2000 gold title: 191; with both kinds of exposure: 108.
- Close council pairs (margin at most 0.50%) in exposed municipalities: 2,862 in all.

First stage (`research/explore-runs/0007/43438404852.md`), outcome `garimpo_share`, 2,783 municipalities, 26 states, 97,405 municipality-years, 1990-2024:

- beta = 0.00439 per unit of E x ln(real gold price, t-1).
- Clustered SE = 0.002812; F = 2.436.
- Randomisation-inference p = 0.000999 (1,000 draws, E permuted within state).
- Lead ratio (|mean 1990-2001| / |mean 2002-2024|): 0.04995.

Limits, from the records:

- Exploration half only.
- The binary exposure `geo_exposed` has F 12.28 (beta 0.0001346, SE 3.841e-05). It is a different exposure from the one the kill rule names. It is reported as one of several forking paths, not as a rescue of the design.
- The other exposure, `title_gold_pre2000_share`, has F 4.579. Titles are active ones that survived to 2026 (idea file), which is why geology is the main exposure.
- The regime splits and the Indigenous-land access split are secondary: reported, not claimed. R3 covers two years only.
- The politics reduced forms (step s23) never ran. This campaign says nothing about elections.

Unexplained differences: None found. Both records give 2,783 municipalities in the exploration half and in `gold_exposure` / the first-stage sample (`research/explore-runs/0007/43181711849.md`, `research/explore-runs/0007/43438404852.md`). The real gold price in the feasibility record spans 1985 to 2025, wider than the 1990-2024 estimation window of the first stage. That is a difference in what each record covers by design, not a difference in a shared quantity.

## Kill rules applied

Verdicts are the tick's, from the ledger; observed values are from the run records.

- s9 k1 (`exposure.n_munis_exposed < 150`): observed 231. Not met.
- s9 k2 (`exposure.n_states_10plus < 3`): observed 6. Not met.
- s9 k3 (`titles.share_dated < 0.9`): observed 1.0. Not met.
- s9 k4 (`exposure.top_state_share > 0.6`): observed 0.21212121212121213. Not met.
- s15 k1 (`first_stage.f_cluster < 10`): observed 2.43629095441103. Met: the step is killed.
- s15 k2 (`placebo.lead_ratio > 0.5`): observed 0.04994976728614599. Not met.
- s15 k3 (`estimates.finite != True`): observed True. Not met.

These match the ledger: s9 "survived", s15 "killed".

## Budget used

From the tick's ledger: max_explore_runs 2 of 3, max_model_jobs 25 of 75, max_pipeline_runs 6 of 10, max_tasks 7 of 10.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the issues, the plan and review comments, the pull requests and the runs. A fix round is one agent review after the first.

### Blocks

| Step | Cause | Posted | Hours until unblocked |
| --- | --- | --- | --- |
| s4 | run 43098821873 ended 'failure'. Retried 2 times | 2026-11-11T21:07:05Z | 2.5 |
| s5 | the repair task: the planner answered 'Needs clarification - no plan yet' | 2026-11-11T21:10:19Z | 1.4 |
| s8 | an agent stopped and labelled it needs-human | 2026-11-11T21:26:10Z | 1.6 |
| s5 | run 43113036449 ended 'failure'. Retried 2 times | 2026-11-11T22:36:41Z | 0.6 |
| s7 | run 43122021429 ended 'failure'. Retried 2 times. Not repaired: the campaign's 2 repairs are used | 2026-11-11T23:45:36Z | 0.2 |
| s7 | run 43123467616 ended 'failure'. Retried 2 times. Not repaired: the campaign's 2 repairs are used | 2026-11-11T23:58:04Z | 8.2 |
| s11 | run 43234259734 ended 'failure'. Retried 2 times. Not repaired: the campaign's 2 repairs are used | 2026-11-12T16:52:40Z | 6.4 |
| s11 | run 43234259734 ended 'failure'. Retried 2 times. Not repaired: the campaign's 2 repairs are used | 2026-11-13T01:55:44Z | 11.8 |

### Task steps with more than one plan or a fix round

| Step | Plans posted | Fix rounds | Model jobs |
| --- | --- | --- | --- |
| s6 | 1 | 1 | 5 |

One plan and no fix round: s1, s3, s8, s10, s12, s14.

### Run steps that took more than one run

| Step | Runs | Run ids and how they ended |
| --- | --- | --- |
| s4 | 5 | 43071992487 failure, 43072265856 failure, 43072553787 failure, 43098821873 failure, 43121111036 success |
| s5 | 5 | 43072883535 failure, 43073126118 failure, 43073393727 failure, 43113036449 failure, 43117767583 success |
| s7 | 5 | 43121651542 failure, 43121854481 failure, 43122021429 failure, 43123467616 failure, 43180577125 success |
| s11 | 4 | 43185081032 failure, 43209032467 failure, 43234259734 failure, 43435600642 success |

### Repairs

| Step | Repair issue | Pull request | Model jobs | How it ended |
| --- | --- | --- | --- | --- |
| s4 | #344 | none | 1 | done |
| s5 | #346 | none | 1 | done |

### Time

Wall-clock time from `started` (2026-11-11T17:02:41Z) to `finished` (2026-11-13T14:05:56Z): 45.1 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 11.8 | `s11:blocked:f3fdfafb-2` (2026-11-13T01:55:44Z) | `s11:unblocked:f3fdfafb-2` (2026-11-13T13:41:50Z) |
| 8.2 | `s7:blocked:c739b8e2` (2026-11-11T23:58:04Z) | `s7:unblocked:c739b8e2` (2026-11-12T08:10:35Z) |
| 6.4 | `s11:blocked:f3fdfafb` (2026-11-12T16:52:40Z) | `s11:unblocked:f3fdfafb` (2026-11-12T23:16:33Z) |

43 shorter gaps left out.

## Checks not run

- Step s16 (task) did not finish (skipped: step s15 was killed).
- Step s17 (pipeline_run) did not finish (skipped: step s16 was skipped).
- Step s18 (pipeline_run) did not finish (skipped: step s16 was skipped).
- Step s19 (task) did not finish (skipped: step s16 was skipped).
- Step s20 (pipeline_run) did not finish (skipped: step s19 was skipped).
- Step s21 (pipeline_run) did not finish (skipped: step s20 was skipped).
- Step s22 (task) did not finish (skipped: step s19 was skipped).
- Step s23 (explore_run) did not finish (skipped: step s22 was skipped).
- Kill rule k1 of step s23 (Some estimate, standard error or p-value of the politics reduced forms is not a finite number) was never applied: step s23 did not run to a result.
- Referee R5 was marked Not applicable in the review of step s14 (PR #369).

## Proposed harness changes (at most three)

### Notes added

Three notes were added to `research/agent-notes.md`. No old note was merged or removed.

- [N001] (builder) After a failed pipeline run, read the log of that run for the cause before retrying, because four steps each failed several times in a row. From: campaign 0007, runs of s4, s5, s7 and s11 ending in failure. Added 2026-11-13.
- [N002] (planner) For a repair task, restate the failing run's error and the files it touches so the plan is never "Needs clarification". From: campaign 0007, s5 repair answered 'Needs clarification - no plan yet'. Added 2026-11-13.
- [N003] (design) Put the build that a long chain needs early, because one pipeline step waited 11.8 hours after both repairs were used. From: campaign 0007, s11 blocked for 11.8 hours. Added 2026-11-13.

### Checks in code proposed

These are proposed only, not applied. Gabriel batches them into tasks later.

1. Friction fact: s4, s5, s7 and s11 each took four or five runs (rows of "Run steps that took more than one run"). Check: before a retry, the tick posts the last error lines of the failed run on the tracking issue. File: `src/terrain/campaigns/tick.py`.
2. Friction fact: the s5 repair was answered "Needs clarification - no plan yet". Check: the repair template carries the failing run's error text in the issue body. File: `src/terrain/campaigns/repair.py`.
3. Friction fact: s7 and s11 blocks ("Not repaired: the campaign's 2 repairs are used") waited 8.2 and 11.8 hours. Check: the tick tells Gabriel at the first block when no repair is left, with a link to the run. File: `src/terrain/campaigns/tick.py`.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Use the binary exposure `geo_exposed` as the main exposure, registered before any outcome is read, since its F is 12.28 in the first-stage record. This is a forking path here, so it would need a new idea and its own kill rules.
- Use a different shock that moves faster than the world gold price, for example a price in local currency, after checking its first stage.
- Study only the states where exposure is concentrated (MG, GO, BA, PA), after a power check on close pairs; the feasibility record counts 2,862 close pairs in all exposed municipalities.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0007 take?
   - Option A: `promising`.
   - Option B: `parked`, keeping the built data for later use.
   - Option C: `dead`.
   - Agent's recommendation: option C, `dead`. The idea's own criterion "Weak first stage" was met (F 2.436, below 10). The pre-stated test failed; reaching for the binary exposure afterwards would be a forking path.
2. Whether to open a new idea on binary gold exposure?
   - Option A: no.
   - Option B: yes, with the exposure, the test and the kill rules written before any run.
   - Agent's recommendation: option A for now. The F of 12.28 comes from a choice made after seeing the result, so it is a forking path.
3. Whether to register a design for the confirmation half?
   - Option A: no; nothing in this campaign supports one.
   - Option B: yes, for the first stage.
   - Agent's recommendation: option A, because the first stage failed on the exploration half.
