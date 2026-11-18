# Campaign 0010 report: What do budget amendments buy at the ballot box? Second attempt: build, gate and main run

What we tested: whether the first stage of the amendments design (a federal deputy's party narrowly winning a mayoralty, then the amendments the deputy pays there) is strong enough to be worth a main run, using a gate on the exploration half.
What happened: the panel built and the gate ran, but two kill rules were met (power, and the link from amendment authors to deputies), so the campaign stopped and the main run never ran.
What it means: on the exploration half the design cannot detect an effect of the size the idea needs, and nothing here is a finding.
Decisions for you: 3 decisions, the first being the idea's status, where the agent recommends `dead`.

## Summary

Step s1 built the amendments panel (PR #417, run 44393853819). Step s2 ran the gate (PR #418, run 44394848609). The gate chose a 10% window with 3017 close races (21641 units, 1746 deputies). Two kill rules were met. k3: the first stage's minimum detectable effect is 0.526 of the pre-election mean, above the limit of 0.25. k6: the smallest share of amendment authors matched to a deputy is 0.569, below the limit of 0.9. Steps s3 and s4 were skipped. No fork was declared. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0010-amendments-second-attempt/ledger.md`):

- s1 (pipeline run, PR #417, run 44393853819): done, recorded.
- s2 (explore run, PR #418, run 44394848609): done, killed. Record: `research/explore-runs/0009/44394848609.md`.
- s3 (task): skipped, step s2 was killed.
- s4 (explore run): skipped, step s3 was skipped.

## Results and their limits

These are exploration-half results. Nothing here is a finding. A result from the exploration half is a reason to register a design, not a conclusion. Source: `research/explore-runs/0009/44394848609.md`.

- Window by decision 0008's balance rule: 10%. Close races at that window: 3017 (21641 units, 1746 deputies).
- Counts by cycle (races, units): A 1106 and 7314; B 1076 and 6916; C 835 and 7411.
- Power, on pre-election amendments (reais per 1,000 inhabitants): MDE 1.15e+03 against a mean of 2.19e+03, a share of 0.526.
- Placebos at the 10% window: pre-election amendments, absolute slope over mean 0.21; vote share at the previous general election, 0.0372.
- Author link, share of amendment authors matched to a TSE federal-deputy candidacy: A 0.684, B 0.59, C 0.569. In cycle C, 531 of 1305 authors are unmatched.
- Check at 5% (reported only): 1600 races, 11598 units; MDE 0.758 of the mean. Power fails there too.
- The window table shows the balance rule's omnibus p at 10% is 0.171, with the smallest covariate p at 0.0365 (fin_female). The record calls a passing placebo "not proof of balance".

Limits: one run, exploration half only, no outcome after the election was read. The power failure is about the size of the pre-election noise relative to the mean, so it is a feature of the design and not of one script bug. The author-link failure may come from how authors are matched, which is a data problem that could be fixed; the record does not say.

Unexplained differences: None found. There is one run record, and its numbers match the ledger's observed values (k3 0.5256543929365561, k4 0.21038145621731105, k5 0.03723717792411062, k6 0.5686433793663688). The s1 manifest is not a run record, so it was not compared.

## Kill rules applied

As the tick applied them to the run record of s2:

- k1 (no mayoral window passes decision 0008's balance rule): `window.found == 0`, observed 1, not met.
- k2 (fewer than 200 close mayoral races within the chosen window): `counts.races_h < 200`, observed 3017, not met.
- k3 (first-stage MDE above 25% of the pre-election mean): `power.mde_share > 0.25`, observed 0.5256543929365561, met: the step is killed.
- k4 (placebo slope on pre-election amendments above 25% of their mean): `placebo.amend_share_abs > 0.25`, observed 0.21038145621731105, not met.
- k5 (placebo slope on the deputy's previous vote share above 25% of its mean): `placebo.vote_share_abs > 0.25`, observed 0.03723717792411062, not met.
- k6 (fewer than 90% of authors matched in some cycle): `link.author_share < 0.9`, observed 0.5686433793663688, met: the step is killed.

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

From the tick's ledger: max_explore_runs 1 of 2, max_model_jobs 0 of 20, max_pipeline_runs 1 of 2, max_tasks 0 of 2.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the issues, the plan and review comments, the pull requests and the runs. A fix round is one agent review after the first.

### Blocks

None.

No block was posted, so there is no row to list.

### Task steps with more than one plan or a fix round

None.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-18T20:42:34Z) to `finished` (2026-11-18T22:21:53Z): 1.7 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 1.6 | `s1:recorded`, `s2:dispatched` (2026-11-18T20:48:20Z) | `finished`, `s2:verdict`, `s3:skipped`, `s4:skipped` (2026-11-18T22:21:53Z) |
| 0.1 | `s1:dispatched`, `started` (2026-11-18T20:42:34Z) | `s1:recorded`, `s2:dispatched` (2026-11-18T20:48:20Z) |

## Checks not run

- Step s3 (task) did not finish (skipped: step s2 was killed).
- Step s4 (explore_run) did not finish (skipped: step s3 was skipped).
- Kill rule k1 of step s4 (The municipality-clustered first-stage F statistic of Win on amendments per 1,000 inhabitants is below 10) was never applied: step s4 did not run to a result.
- Kill rule k2 of step s4 (Some first-stage or reduced-form estimate, standard error or p-value is not a finite number) was never applied: step s4 did not run to a result.

## Proposed harness changes (at most three)

### Notes added

None. Every friction group says "None.", so no note was added to `research/agent-notes.md`, and no old note was merged or removed. Only the Scoreboard row for campaign 0010 was added.

### Checks in code proposed

None.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- Fix the author link first: find why 0.569 of authors in cycle C match a deputy candidacy, and test a better match before any later gate.
- Measure: a coarser outcome that is less noisy than amendments per 1,000 inhabitants, for example any amendment above zero, to see if power improves. This is a new idea and needs its own campaign.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0009 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option C, `dead`. The plan's path failed two kill rules (k3 and k6), power also fails at the 5% check (MDE 0.758), and no fork was declared, so no variant survived. `parked` is the close alternative, because the author-link failure (k6) may be a fixable data problem; the power failure (k3, also one of the idea's own kill criteria) is not.
2. Whether to open a follow-up task on the author link?
   - Option A: no.
   - Option B: yes, one task to find why only 0.569 of authors in cycle C match a deputy candidacy.
   - Agent's recommendation: option A. Fixing the link would not repair k3, which fails on its own.
3. Whether to register a design for the confirmation half?
   - Option A: no.
   - Option B: yes.
   - Agent's recommendation: option A. The gate was killed, no main run happened, and no fork was tried, so there is no design to register.
