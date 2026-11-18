# Campaign 0009 report: What do budget amendments buy at the ballot box? Close mayoral races, deputies' amendments and their votes, 2016-2026

What we tested: whether a federal deputy's party narrowly winning a mayoralty raises the amendments the deputy pays to the municipality, and then the deputy's votes there.
What happened: the data steps and three tasks finished, but the panel build (s5) failed on all four of its runs, so the power gate and the main run never ran and no number was produced.
What it means: the idea was never tested; on the exploration half there is no result, so nothing here is a finding.
Decisions for you: 2 decisions, the first being the idea's status, where the agent recommends `parked`.

## Summary

The campaign stopped at step s5, the build of the amendments panel. It failed in 4 runs (43971218125, 43971365101, 43971509559, 44062022559), each ending in failure, and the repair task #410 ended with no pull request. Steps s7, s8 and s9 were still waiting, so there was no explore run, no kill rule was applied, and `research/explore-runs/` has no 0009 record. The idea was not tested. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0009-amendments-ballot-box/ledger.md`):

- s1 (task, #401, PR #402): merged.
- s2 (pipeline run, PR #406, run 43903226044): recorded.
- s3 (pipeline run, PR #405, run 43903231088): recorded.
- s4 (task, #404, PR #407): merged.
- s5 (pipeline run, repair #410, run 44062022559): blocked. Run 44062022559 ended 'failure'. Retried 2 times.
- s6 (task, #408, PR #409): merged.
- s7 (explore run): waiting.
- s8 (task): waiting.
- s9 (explore run): waiting.

## Results and their limits

These are exploration-half results, and there are none: no explore run produced numbers. Nothing here is a finding. A result from the exploration half is a reason to register a design, not a conclusion, and this campaign has no result at all.

- No explore-run record exists for campaign 0009. The ledger lists no record path for s7 or s9.
- The cause of the s5 failure is not in the repository. The log of run 44062022559 was not available to this task, so this report does not guess it. Whether that run used the owner fix (commit bd336f0, PR #411, "CGU 'Sem informação' recipients count as no municipality") cannot be checked from the repository.

Unexplained differences: None found. There are no two run records to compare.

## Kill rules applied

None. As the ledger says: no kill rule was applied. The rules of s7 (k1 to k6) and s9 (k1, k2) were never applied because those steps did not run to a result; see "Checks not run".

## Forks

### Forks table

None: no fork was declared.

No fork adopted the plan's skipped steps.

### How many were tried

- None: no fork point opened.

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

### Refused and suggested variants

None.

## Budget used

From the tick's ledger: max_explore_runs 0 of 2, max_model_jobs 10 of 34, max_pipeline_runs 3 of 3, max_tasks 3 of 4.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the issues, the plan and review comments, the pull requests and the runs. A fix round is one agent review after the first.

### Blocks

| Step | Cause | Posted | Hours until unblocked |
| --- | --- | --- | --- |
| s5 | the repair task: the planner answered 'Needs clarification - no plan yet' | 2026-11-17T04:53:04Z | 5.3 |
| s5 | run 44062022559 ended 'failure'. Retried 2 times | 2026-11-17T10:11:50Z | never |

### Task steps with more than one plan or a fix round

None.

One plan and no fix round: s1, s4, s6.

### Run steps that took more than one run

| Step | Runs | Run ids and how they ended |
| --- | --- | --- |
| s5 | 4 | 43971218125 failure, 43971365101 failure, 43971509559 failure, 44062022559 failure |

### Repairs

| Step | Repair issue | Pull request | Model jobs | How it ended |
| --- | --- | --- | --- | --- |
| s5 | #410 | none | 1 | blocked: run 44062022559 ended 'failure'. Retried 2 times. |

### Time

Wall-clock time from `started` (2026-11-16T12:00:08Z) to `finished` (2026-11-18T14:32:50Z): 50.5 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 28.4 | `s5:blocked:5ae614d4` (2026-11-17T10:11:50Z) | `finished` (2026-11-18T14:32:50Z) |
| 6.3 | `s2:recorded` (2026-11-16T16:12:57Z) | `s4:merged`, `s5:dispatched` (2026-11-16T22:33:36Z) |
| 6.2 | `s5:retry:2` (2026-11-16T22:35:26Z) | `s5:repair:1`, `s6:merged` (2026-11-17T04:49:47Z) |

11 shorter gaps left out.

## Checks not run

- Step s5 (pipeline_run) did not finish (blocked: run 44062022559 ended 'failure'. Retried 2 times).
- Step s7 (explore_run) did not finish (waiting).
- Step s8 (task) did not finish (waiting).
- Step s9 (explore_run) did not finish (waiting).
- Kill rule k1 of step s7 (No mayoral window, not even 0.5%, passes decision 0008's balance rule) was never applied: step s7 did not run to a result.
- Kill rule k2 of step s7 (Fewer than 200 close mayoral races (cycles A-C pooled, with an eligible deputy) within the chosen window) was never applied: step s7 did not run to a result.
- Kill rule k3 of step s7 (The first stage's minimum detectable effect at 80% power is above 25% of the pre-election mean of amendments per 1,000 inhabitants) was never applied: step s7 did not run to a result.
- Kill rule k4 of step s7 (The placebo slope on amendments paid before the mayoral election exceeds 25% of their mean, in absolute value) was never applied: step s7 did not run to a result.
- Kill rule k5 of step s7 (The placebo slope on the deputy's vote share at the previous general election exceeds 25% of its mean, in absolute value) was never applied: step s7 did not run to a result.
- Kill rule k6 of step s7 (Fewer than 90% of the deputies' individual-amendment authors in some cycle are matched to a TSE federal-deputy candidacy) was never applied: step s7 did not run to a result.
- Kill rule k1 of step s9 (The municipality-clustered first-stage F statistic of Win on amendments per 1,000 inhabitants is below 10) was never applied: step s9 did not run to a result.
- Kill rule k2 of step s9 (Some first-stage or reduced-form estimate, standard error or p-value is not a finite number) was never applied: step s9 did not run to a result.
- Referee R5 was marked Not applicable in the review of step s6 (PR #409).

## Proposed harness changes (at most three)

### Notes added

Two notes were added to `research/agent-notes.md`. No old note was merged or removed.

- [N006] (builder) Before a pipeline build is merged, run it on every fixture year and on the messiest real-file shape the issue describes, because s5 failed all four of its runs. From: campaign 0009, s5 had 4 runs, all failure. Added 2026-11-18.
- [N007] (design) When one build gates several later steps, split it into smaller builds, so one failure does not leave s7, s8 and s9 waiting. From: campaign 0009, s5 blocked and s7 to s9 waiting. Added 2026-11-18.

### Checks in code proposed

These are proposed only, not applied. Gabriel batches them into tasks later.

1. Friction fact: s5 ended 'failure' in 4 runs, and the repair #410 produced no pull request. Check: after each failed run, the tick posts the tail of that run's log on the tracking issue, so the planner and the repair task see the real error. File: `src/terrain/campaigns/tick.py`.
2. Friction fact: the longest gap in the campaign was 28.4 hours, from the s5 block to `finished`. Check: the tick finishes the campaign and files the close-out as soon as no step can go on. File: `src/terrain/campaigns/tick.py`.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign. They are the three variants named in `research/campaigns/0009-amendments-ballot-box/campaign.md`, and none can start before s5 works.

- Spec: alignment by the mayor's coalition or federation instead of the deputy's own party.
- Measure: Pix amendments only, cycles B and C.
- Question: the same close races, with the outcome being the vote change of the mayor's party's state deputies, as a brokerage benchmark.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0009 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option B, `parked`. The idea was never tested: s5 failed in 4 runs, and s7 and s9 never ran. `dead` is not supported, because no plan path or fork failed a test.
2. Whether to open a follow-up campaign?
   - Option A: no.
   - Option B: yes, one that runs the panel build (s5) again, then the gate and the main run (s7 to s9), on the current main, which includes the owner fix bd336f0 (PR #411). Its steps and kill rules would be written before any run.
   - Agent's recommendation: option B. The data steps s2 and s3 and the tasks s1, s4 and s6 are done, so only the build and the explore runs remain. No design is registered for the confirmation half, because nothing ran.
