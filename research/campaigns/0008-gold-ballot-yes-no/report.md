# Campaign 0008 report: Gold and the ballot, yes/no: does the gold price move garimpo and politics where any gold lies?

What we tested: whether the gold price, times a yes/no mark for "the Geological Survey records gold here", raises garimpo (artisanal gold mining) area in exploration-half municipalities, and then whether it moves local politics.
What happened: the first stage passed its rules (clustered F 12.28, lead ratio 0.2337), and the eight politics reduced forms showed no result with q below 0.17.
What it means: on the exploration half the yes/no first stage clears the stated test, but the measure was chosen after seeing campaign 0007's results and the politics results are null, so nothing here is a finding.
Decisions for you: 3 decisions, the first being the idea's status, where the agent recommends `parked`.

## Summary

Both explore runs survived their kill rules. Step s2 (first stage) gave beta 0.0001346, clustered F 12.28 and randomisation-inference (RI) p 0.000999 (`research/explore-runs/0008/43493015138.md`). Step s10 (politics reduced forms) gave eight outcomes, none with q below 0.17; the smallest RI p is `homicide_rate` at 0.02198, q 0.1758 (`research/explore-runs/0008/43605456014.md`). The yes/no measure was chosen after campaign 0007's results, so it is a forking path. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0008-gold-ballot-yes-no/ledger.md`):

- s1 (task, #378, PR #380): merged.
- s2 (explore run, PR #381, run 43493015138): survived. Record: `research/explore-runs/0008/43493015138.md`.
- s3 (task, #383, PR #384): merged.
- s4 (pipeline run, PR #386, run 43496045776): recorded.
- s5 (pipeline run, PR #387, run 43496048843): recorded.
- s6 (task, #385, PR #389): merged.
- s7 (pipeline run, PR #392, run 43499570432): recorded.
- s8 (pipeline run, PR #393, run 43500517087): recorded.
- s9 (task, #391, PR #395): merged.
- s10 (explore run, PR #396, run 43605456014): survived. Record: `research/explore-runs/0008/43605456014.md`.

## Results and their limits

These are exploration-half results. Nothing here is a finding: a result from the exploration half is a reason to register a design, not a conclusion.

First stage (`research/explore-runs/0008/43493015138.md`), outcome `garimpo_share`, D = 1 if the Survey records gold (231 of 2,783 municipalities), 26 states, 97,405 municipality-years, 1990-2024:

- beta = 0.0001346 per unit of D x ln(real gold price, t-1).
- Clustered SE = 3.841e-05; F = 12.28.
- RI p = 0.000999 (1,000 draws, D permuted within state).
- Lead ratio (|mean 1990-2001| / |mean 2002-2024|): 0.2337.
- Smallest F leaving one state out: 5.125 (state left out: PA).
- F on 1990-2012: 1.319; F on 2013-2024: 12.75.
- The yes/no measure was chosen after seeing campaign 0007's results (`research/explore-runs/0007/43438404852.md`), so it is a forking path.

Politics reduced forms (`research/explore-runs/0008/43605456014.md`), eight outcomes, RI p and Benjamini-Hochberg q:

- None has q below 0.17.
- The smallest RI p is `homicide_rate`: beta -1.888, clustered SE 0.7382, RI p 0.02198, q 0.1758. The sign is the opposite of the capture prediction (more homicides).
- The next smallest q are `seat_turnover` (RI p 0.1019, q 0.2877) and `incumbent_reelected` (RI p 0.1079, q 0.2877). The other five have q of 0.9248 or 0.9461.
- `mining_money_share` is absent: receipts with a CNAE are 0 in 2004, 0 in 2008 and 1,025,076 in 2012, and at least 2 elections need 1,000.
- Rows dropped for a missing outcome range from 39 to 343 of 19,481 (or 16,698) rows per outcome.

Limits, from the records:

- Exploration half only.
- The first stage depends on the later years: F is 1.319 on 1990-2012 and 12.75 on 2013-2024. Leaving out PA gives F 5.125, below 10.
- The density measure is dominated by one municipality: the top one is 0.9791 of the sum.
- Regime and legal-access terms are secondary: reported, not claimed. No full term after the 2023 suspension exists.

Unexplained differences:

- RI seed: 20261113 in `research/explore-runs/0008/43493015138.md` and 20261111 in `research/explore-runs/0008/43605456014.md`. The two runs are different scripts; no record says why the seeds differ.
- Name of the permuted variable: the first-stage record says "D permuted within state" (`research/explore-runs/0008/43493015138.md`); the politics record says "E permuted within state" while defining the regressor as D = `geo_exposed` (`research/explore-runs/0008/43605456014.md`). Both appear to mean the same yes/no exposure, but the politics record's label E is not defined in that record.
- Both records give 2,783 municipalities in the exploration half. That quantity does not differ.

## Kill rules applied

Verdicts are the tick's, from the ledger; observed values are from the ledger's kill-rule list and the run records.

- s2 k1 (`first_stage.f_cluster < 10`): observed 12.283282398619294. Not met. Verdict: survived.
- s2 k2 (`placebo.lead_ratio > 0.5`): observed 0.23372083884622993. Not met. Verdict: survived.
- s2 k3 (`estimates.finite != True`): observed True. Not met. Verdict: survived.
- s10 k1 (`estimates.finite != True`): observed True. Not met. Verdict: survived.

These match the ledger: s2 "survived", s10 "survived".

## Budget used

From the tick's ledger: max_explore_runs 2 of 2, max_model_jobs 17 of 40, max_pipeline_runs 4 of 6, max_tasks 4 of 5.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the issues, the plan and review comments, the pull requests and the runs. A fix round is one agent review after the first.

### Blocks

| Step | Cause | Posted | Hours until unblocked |
| --- | --- | --- | --- |
| s9 | the planner answered 'Needs clarification - no plan yet' | 2026-11-13T20:16:11Z | 16.8 |

### Task steps with more than one plan or a fix round

| Step | Plans posted | Fix rounds | Model jobs |
| --- | --- | --- | --- |
| s9 | 2 | 2 | 8 |

One plan and no fix round: s1, s3, s6.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-13T19:06:53Z) to `finished` (2026-11-14T14:39:01Z): 19.5 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 16.7 | `s8:recorded` (2026-11-13T20:23:22Z) | `s9:unblocked:b13b6fde` (2026-11-14T13:06:17Z) |
| 1.4 | `s9:unblocked:b13b6fde` (2026-11-14T13:06:17Z) | `s10:dispatched`, `s9:merged` (2026-11-14T14:33:09Z) |
| 0.4 | `s1:filed` (2026-11-13T19:08:33Z) | `s1:merged`, `s2:dispatched` (2026-11-13T19:31:29Z) |

12 shorter gaps left out.

## Checks not run

- Referee R5 was marked Not applicable in the review of step s1 (PR #380).
- Referee R5 was marked Not applicable in the review of step s9 (PR #395).

Every step finished and every kill rule was applied.

## Proposed harness changes (at most three)

### Notes added

Two notes were added to `research/agent-notes.md`. No old note was merged or removed.

- [N004] (planner) List each open question in the issue and your answer to it in the first plan, so the plan is never "Needs clarification". From: campaign 0008, s9 planner asked for clarification (16.8 hours). Added 2026-11-14.
- [N005] (builder) Before the first commit of a task that changes an estimator, list each rule the issue states for it and test each one, because s9 needed two fix rounds. From: campaign 0008, s9 had 2 fix rounds. Added 2026-11-14.

### Checks in code proposed

These are proposed only, not applied. Gabriel batches them into tasks later.

1. Friction fact: the s9 block ("Needs clarification - no plan yet") waited 16.8 hours, and the longest gap in the campaign was 16.7 hours. Check: when a plan is answered "Needs clarification", the tick posts the questions on the tracking issue at once with a link. File: `src/terrain/campaigns/tick.py`.
2. Friction fact: s9 had 2 plans and 2 fix rounds (8 model jobs). Check: the tick lists a step's open review items in the tracking issue after each fix round. File: `src/terrain/campaigns/tick.py`.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign.

- A continuous exposure measure fixed before any outcome is read, for example gold occurrences per km² registered in a new idea, since the yes/no first stage rests on 231 municipalities and one state (PA) moves F to 5.125 when left out.
- Homicides as a separately pre-stated outcome, since `homicide_rate` is the only row with an RI p near the usual cut (0.02198), in the opposite direction from the capture prediction. It would need its own idea and kill rules.
- A power check on the later years only (2013-2024, F 12.75), stated before any run, because F is 1.319 on 1990-2012.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0008 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option B, `parked`. The first stage passed (F 12.28, lead ratio 0.2337), but on a measure chosen after seeing campaign 0007's results, and the politics results are null (no q below 0.17). `dead` is defensible too.
2. Whether to register a design for the confirmation half?
   - Option A: no.
   - Option B: yes, for the first stage only.
   - Agent's recommendation: option A. The first stage rests on a measure chosen after the fact, and F is 1.319 on 1990-2012.
3. Whether to open a follow-up task or campaign?
   - Option A: no.
   - Option B: yes, a new idea with a continuous exposure or homicides as a pre-stated outcome, with the test and kill rules written before any run.
   - Agent's recommendation: option A for now. The only row near a result (`homicide_rate`, q 0.1758) is not significant after correction, and picking it now would be another forking path.
