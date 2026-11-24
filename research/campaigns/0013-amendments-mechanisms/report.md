# Campaign 0013 report: Amendments: favouritism or more money, Pix, sorting, whose votes move and when the money is paid

What we tested: whether, in close mayoral races on the exploration half, the deputy's amendment money and vote changes behave as favouritism would, with three plan steps (instrument and sorting, whose votes move, when the money is paid) and one variant of each.
What happened: all six explore runs finished and none met a kill rule, so the three plan steps survived and the three forks survived (fork).
What it means: on the exploration half the earlier first stage and vote results hold up under these checks, with one weaker spot (the controlled first stage under a quadratic has an F of 10.3), and nothing here is a finding.
Decisions for you: 3 decisions, the first being the idea's status, where the agent recommends `promising`.

## Summary

Campaign 0013 ran six explore runs on the exploration half, three plan steps and one fork of each, with six tasks to prepare them. No kill rule was met. Run 45248303745 (s2) gives a controlled first stage of b 0.185 (SE 0.0359) with a municipality-clustered F of 26.4 at h = 7.5% (2300 races). Run 45034178304 (s4) gives d_party 0.0268 (SE 0.0093, RI p 0.0045), d_state 0.0322 and d_inc 0.0337, with a flat t0 placebo. Run 45036043356 (s6) gives a lead ratio of 0.0257 in the monthly payment timing. The three forks (f1 controls, f2 log outcome, f3 local quadratic) each survived, and each is one of 1 tried at its point. The f3 run is the weakest: its controlled F is 10.3, only just above 10. The plan's s2 (F 26.4) and f3 (F 10.3) point differently on how firmly the instrument holds. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0013-amendments-mechanisms/ledger.md`):

- s1 (task, #451, PR #489): done, merged.
- s2 (explore run, PR #492, run 45248303745): done, survived. Record: `research/explore-runs/0010/45248303745.md`.
- s3 (task, #452, PR #454): done, merged.
- s4 (explore run, PR #458, run 45034178304): done, survived. Record: `research/explore-runs/0010/45034178304.md`.
- s5 (task, #456, PR #461): done, merged.
- s6 (explore run, PR #462, run 45036043356): done, survived. Record: `research/explore-runs/0010/45036043356.md`.
- s7 (f1, task, #463, PR #465): done, merged.
- s8 (f1, explore run, PR #466, run 45038011532): done, survived (fork). Record: `research/explore-runs/0010/45038011532.md`.
- s9 (f2, task, #467, PR #468): done, merged.
- s10 (f2, explore run, PR #469, run 45040009981): done, survived (fork). Record: `research/explore-runs/0010/45040009981.md`.
- s11 (f3, task, #497, PR #500): done, merged.
- s12 (f3, explore run, PR #503, run 45255609706): done, survived (fork). Record: `research/explore-runs/0010/45255609706.md`.

## Results and their limits

These are exploration-half results. Nothing here is a finding. A result from the exploration half is a reason to register a design, not a conclusion. The window (h = 7.5%) and the half are the same ones campaign 0011 analysed, so this is a further look at the same data, and the questions were added after its results.

s2, instrument and sorting (`research/explore-runs/0010/45248303745.md`):

- Rows at h: 13809 in 2300 races (A 5438, B 3971, C 4400). Controlled first stage: b 0.185 (SE 0.0359), 95% interval [0.114, 0.255], randomisation p 0.0005, F 26.4.
- Pooled `total`, `log_pc`: b 0.192 (SE 0.0362); by cycle A 0.0273, B 0.236, C 0.401. Poisson premium pooled 152% [68.2, 277].
- Declared estimates (Holm over three): first_stage_controls Holm p 0.0015; poisson_total_c_minus_a Holm p 0.162; poisson_pix_minus_nonpix Holm p 0.0256 (b 0.88, SE 0.354, ratio 141%, 10202 rows).
- Sorting: among towns the deputy's party already held (`held_true`), b 0.124, F 4.01, 1023 races. Elsewhere (`held_false`), b 0.207, F 22.3, 2161 races.
- Placebo: pre-window b 0.0142 (SE 0.0218, randomisation p 0.546), ratio 0.0739, `pre_fail` 0.

s4, whose votes move (`research/explore-runs/0010/45034178304.md`):

- Party rows at h: 4029 in 2300 races; 22 races have equal t1 shares for the two finalist parties.
- d_party b 0.0268 (SE 0.0093, RI p 0.0045, Holm p 0.009); d_state 0.0322 (SE 0.00949); d_inc 0.0337 (SE 0.00768). party_minus_state b -0.00544 (RI p 0.647).
- At 5%, d_state is 0.0194 (RI p 0.116).
- Placebo at t0: party_t0 b -0.0045 (RI p 0.598), state_t0 b -0.0103 (RI p 0.229); `t0_fail` 0.
- Reading: d_state is about as large as d_party, which is the pattern the record's declared reading ties to the mayor's campaigning. It is a description, not a test of that reading.

s6, when the money is paid (`research/explore-runs/0010/45036043356.md`):

- Pooled `total`: mean monthly b before the mayoral term's end 0.00602, after the inauguration 0.235, lead ratio 0.0257.
- The half-year y_p1_h2 is the largest pooled estimate in the table: 0.466 (SE 0.12) reais per inhabitant, and 0.559 (SE 0.144) for Pix.

f1, controls added to s4 (`research/explore-runs/0010/45038011532.md`):

- d_party b 0.0279 (SE 0.00923, RI p 0.0035) against 0.0268 without controls; d_state 0.033 against 0.0322; d_inc 0.0348 against 0.0337. t0 placebo flat (`t0_fail` 0). One party row dropped for a null control.

f2, log outcome for s6 (`research/explore-runs/0010/45040009981.md`):

- Pooled `total`: pre mean 0.000948, post mean 0.0174, lead ratio 0.0544. The pooled half-year y_p1_h2 is 0.0385 (SE 0.00575).

f3, local quadratic for s2 (`research/explore-runs/0010/45255609706.md`):

- Controlled first stage b 0.17 (SE 0.053), randomisation p 0.0005, F 10.3, against 0.185 and F 26.4 in the parent. The point estimate moves little; the standard error grows and F falls. The record expects a larger error from a quadratic even with no curvature.
- Subsamples and windows lose power: `held_true` F 2.55 (b 0.152), `held_false` F 6.04, `donut` F 5.6, 2.5% window F 3.27, 5% window F 6.18, 10% window F 13.9.
- Declared estimates: poisson_total_c_minus_a Holm p 0.0841 (0.162 in s2); poisson_pix_minus_nonpix Holm p 0.164 (b 0.994, SE 0.714), against 0.0256 in s2.
- Placebo: pre-window b 0.0384 (SE 0.0321, randomisation p 0.271), ratio 0.205, `pre_fail` 0.

Limits:

- Every kill rule passed, but F 10.3 under the quadratic is close to the limit of 10, and the s2 and f3 runs point differently on how strong the instrument is. This campaign does not say which model is right; f3 must not be read as support for the instrument.
- The Pix against non-Pix contrast (Holm p 0.0256 in s2) is weaker under the quadratic (Holm p 0.164 in f3).
- By-cycle estimates have clustered errors only, and national payment totals grew from cycle A to C, so a growing jump need not mean growing favouritism.
- The money is not randomised: the dose estimate in s4 and f1 (b 0.0044, SE 0.00139, 4751 rows) is descriptive.
- Each fork that survived is one of 1 tried at its point, and a fork's result is never a finding.

Unexplained differences: None found. The same quantities agree across the records: 13809 rows in 2300 races at h in s2, s6, s10 and f3 (`research/explore-runs/0010/45248303745.md`, `research/explore-runs/0010/45036043356.md`, `research/explore-runs/0010/45040009981.md`, `research/explore-runs/0010/45255609706.md`); 4029 party rows in 2300 races in s4 and f1 (`research/explore-runs/0010/45034178304.md`, `research/explore-runs/0010/45038011532.md`); and 2914 deputy rows with no t1 run in both. The monthly fits in s6 and f2 use 13586 units against 13809 panel rows; both records give the same 13586, and the record does not say why the monthly units are fewer, so this is a note for reading, not a contradiction between two records. The differences between s2 and f3 (b 0.185 against 0.17, F 26.4 against 10.3) are the declared change of the fork (the quadratic), so they are not counted.

## Kill rules applied

As the tick applied them to the run records:

- s2: k1 (With controls for sorting, the first stage's municipality-clustered F is below 10): `first_stage.f_cluster < 10`, observed 26.391893287685367, not met
- s2: k2 (The pre-window placebo is larger than half the effect and significant at 5%): `placebo.pre_fail == 1`, observed 0, not met
- s2: k3 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s4: k1 (The t0 placebo (party or state-deputy share) is above 10% of its mean and significant at 5%): `placebo.t0_fail == 1`, observed 0, not met
- s4: k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s6: k1 (The absolute mean pre-period monthly coefficient is more than half the absolute mean post-period coefficient): `placebo.lead_ratio > 0.5`, observed 0.0256525927160558, not met
- s6: k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s8: k1 (The t0 placebo (party or state-deputy share) is above 10% of its mean and significant at 5%): `placebo.t0_fail == 1`, observed 0, not met
- s8: k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s10: k1 (The absolute mean pre-period monthly coefficient is more than half the absolute mean post-period coefficient): `placebo.lead_ratio > 0.5`, observed 0.054358551251348405, not met
- s10: k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s12: k1 (With controls for sorting, the first stage's municipality-clustered F is below 10): `first_stage.f_cluster < 10`, observed 10.315202755283243, not met
- s12: k2 (The pre-window placebo is larger than half the effect and significant at 5%): `placebo.pre_fail == 1`, observed 0, not met
- s12: k3 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met

No rule was met. The verdicts are as in the ledger: s2, s4 and s6 survived; s8, s10 and s12 survived (fork).

## Forks

The variants this campaign ran inside its envelope (decision 0015), how many
were tried at each fork point, and those refused or only suggested.

### Forks table

| Fork | Parent step | Type | What changed | Why | Steps | Verdict | The numbers its kill rules read |
| --- | --- | --- | --- | --- | --- | --- | --- |
| f1 | s4 | spec | controls: add party_held_mayor, ln(population_m), round and n_mayor_cands as regressors in every party-level, deputy-level and placebo fit at h | Run 45034178304 gives d_party 0.0268 (SE 0.0093, RI p 0.0045), d_state 0.0322 (SE 0.0095) and d_inc 0.0337 (SE 0.0077), and the t0 placebo passes. The campaign's question 3 flags sorting: parties tha… | s7, s8 | survived (fork) (1 tried at this point) | k1 (The t0 placebo (party or state-deputy share) is above 10% of its mean and significant at 5%): `placebo.t0_fail == 1`, observed 0, not met; k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met |
| f2 | s6 | transform | outcome functional form: every monthly, half-year and cumulative Y uses ln(1 + that month's reais per inhabitant) instead of reais per inhabitant | Run 45036043356 (s6) passes k1 with a lead ratio of 0.0257: a pooled pre mean of 0.00602 against a post mean of 0.235 reais per inhabitant. On the level scale the estimates are lumpy and noisy. Poole… | s9, s10 | survived (fork) (1 tried at this point) | k1 (The absolute mean pre-period monthly coefficient is more than half the absolute mean post-period coefficient): `placebo.lead_ratio > 0.5`, observed 0.054358551251348405, not met; k2 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met |
| f3 | s2 | spec | polynomial in the margin: every linear, Poisson, controls and placebo fit adds margin^2 and win x margin^2 to win, margin and win x margin (local quadratic instead of local linear) | Run 45248303745 (s2) passes k1 with a municipality-clustered F of 26.4 at h = 7.5% (b 0.185, SE 0.0359, 2300 races). Its sorting table, a side result the plan could not act on, shows the controlled j… | s11, s12 | survived (fork) (1 tried at this point) | k1 (With controls for sorting, the first stage's municipality-clustered F is below 10): `first_stage.f_cluster < 10`, observed 10.315202755283243, not met; k2 (The pre-window placebo is larger than half the effect and significant at 5%): `placebo.pre_fail == 1`, observed 0, not met; k3 (Some estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met |

No fork adopted the plan's skipped steps.

### How many were tried

- s2: 1 proposed, 0 refused by the envelope check, 1 ran, 1 survived.
- s4: 1 proposed, 0 refused by the envelope check, 1 ran, 1 survived.
- s6: 1 proposed, 0 refused by the envelope check, 1 ran, 1 survived.

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

### Refused and suggested variants

- s2: Alignment by the mayor's coalition or federation instead of the deputy's own party (the campaign file's non-binding spec: amendments_panel v3 defines the finalist by the deputy's t0 party number and has no coalition column. A new build is needed, and the envelope allows 0 pipeline runs and 0 new da…
- s2: The controlled first stage with a triangular kernel at h = 7.5%: The envelope leaves room for only one more fork at this point and in total. The local quadratic tests the growth of b with the window more directly.
- s2: The first stage among towns the deputy's party already held (held_true: F 4.01, 1023 races in run 45248303745): This is a sample split. Gabriel's brief allows no sample forks, and the split is already in the s2 record.
- s4: Alignment by the mayor's coalition or federation instead of the deputy's own party (Gabriel's suggested spec): amendments_panel has rows only where the deputy's own party had a finalist. Coalition alignment adds new deputy-town rows, which need margins and party vote shares built from tse_candidate…
- s4: Party-level vote changes weighted by t0 valid votes (valid_t0), so the estimate is in votes rather than towns: It is possible with the panel, but the main run's fe_fit, ri_b and by_cycle_fit take no weights, so it needs a new estimator. It is less decision-relevant than the sorting controls. It is …
- s4: Party and state-deputy vote changes at other windows (2.5%, 10%), given d_state 0.0194 (RI p 0.116) at the 5% check: The window is fixed by decision record 44484340952, and the 5% check is already reported. More windows add forking paths with little chance of changing the reading.
- s4: Party vote share split into nominal and party-list votes: The panel stores only the combined share. The split needs a rebuild from tse_general_parties, and the envelope allows 0 pipeline runs.
- s6: Extensive-margin measure of payment timing: a monthly indicator of any payment (amend_total > 0; amend_pix > 0), with th: Within the envelope, but it would use the last fork, task and run of the campaign's fork budget. Step s2, the campaign's stop gate and the most decision-relevant fork point, has…
- s6: Alignment by the mayor's coalition or federation instead of the deputy's own party (Gabriel's non-binding spec variant): amendments_panel v3 has no mayoral coalition column (data/contracts/amendments_panel.md), so it needs a build. The envelope allows 0 pipeline runs and 0 new datasets.
- s6: Payment timing at the 5% check window: s5's draft excludes any other window, and with a lead ratio of 0.0257 against the inherited threshold, a window change is unlikely to change a decision. It is lower priority than the scale check, and the budget is kept for s2.

A fork's result is never a finding. f1, f2 and f3 are each "survived (fork)", one of 1 tried at its point.

## Budget used

Budget used: max_explore_runs 3 of 3, max_model_jobs 9 of 36, max_pipeline_runs 0 of 0, max_tasks 3 of 3.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the
issues, the plan and review comments, the pull requests and the runs. A fix
round is one agent review after the first.

### Blocks

| Step | Cause | Posted | Hours until unblocked |
| --- | --- | --- | --- |
| s1 | an agent stopped and labelled it needs-human | 2026-11-22T12:48:30Z | 7.7 |
| s1 | an agent stopped and labelled it needs-human | 2026-11-22T20:37:12Z | 21.8 |
| s1 | no pull request twelve hours after the plan | 2026-11-23T18:27:09Z | 0.7 |

### Task steps with more than one plan or a fix round

None.

One plan and no fix round: s1, s3, s5, s7, s9, s11.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-22T12:35:03Z) to `finished` (2026-11-23T20:34:48Z): 32.0 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 21.8 | `s1:blocked:30e01c58-2` (2026-11-22T20:37:12Z) | `s1:blocked:16eaf48d`, `s1:unblocked:30e01c58-2` (2026-11-23T18:27:09Z) |
| 4.6 | `s10:verdict` (2026-11-22T15:54:25Z) | `s1:unblocked:30e01c58` (2026-11-22T20:29:03Z) |
| 1.9 | `s3:filed` (2026-11-22T12:49:04Z) | `s3:merged`, `s4:dispatched` (2026-11-22T14:41:25Z) |

27 shorter gaps left out.

## Checks not run

- Referee R5 was marked Not applicable in the review of step s1 (PR #489).
- Referee R5 was marked Not applicable in the review of step s3 (PR #454).
- Referee R5 was marked Not applicable in the review of step s5 (PR #461).
- Referee R5 was marked Not applicable in the review of step s7 (PR #465).
- Referee R5 was marked Not applicable in the review of step s9 (PR #468).
- Referee R5 was marked Not applicable in the review of step s11 (PR #500).

Every step finished and every kill rule was applied.

## Proposed harness changes (at most three)

### Notes added

Three notes were added to `research/agent-notes.md`, one for each row of the Blocks table. No old note was merged or removed (10 notes now, limit 30).

- [N008] (planner) Name in the plan every input the first task needs, with its path, so the build has no reason to stop and wait for a person. From: campaign 0013, s1 stopped for a person, 7.7 hours. Added 2026-11-23.
- [N009] (design) Check that the first task of a campaign can run from what is on main before the campaign starts, because s1 stopped a second time and waited 21.8 hours. From: campaign 0013, s1 second stop, 21.8 hours until unblocked. Added 2026-11-23.
- [N010] (builder) Commit the work as soon as the checks pass, so a pull request exists soon after the plan. From: campaign 0013, s1 had no pull request twelve hours after the plan. Added 2026-11-23.

### Checks in code proposed

None.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign. They are the variants the tick refused or listed (see "Forks"):

- Alignment by the mayor's coalition or federation instead of the deputy's own party. It needs a new build: `amendments_panel` v3 has no coalition column, and this campaign's envelope allowed 0 pipeline runs.
- A triangular kernel at h = 7.5% for the controlled first stage, as a further check of how the instrument holds when f3 gives F 10.3.
- Party-level vote changes weighted by t0 valid votes, which needs a new estimator.
- An extensive-margin measure of payment timing (a monthly indicator of any payment).
- Not recommended: other windows for the vote changes, a split of party votes into nominal and party-list votes without a rebuild, and a sample split by held towns. The envelope or the brief rules these out, and each adds forking paths.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0010 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option A, `promising`. The plan's path (s2, s4, s6) survived and no step was killed, so the wording for "only a fork survived" does not apply. f1, f2 and f3 each survived as well, each one of 1 tried at its point. The weak spot is f3's controlled F of 10.3, so `parked` is the close alternative if Gabriel reads that as a sign the instrument is fragile.
2. Whether to register one design for the confirmation half?
   - Option A: no, wait for a follow-up campaign.
   - Option B: yes, at most one design.
   - Agent's recommendation: option A. The plan's s2 (F 26.4) and f3 (F 10.3) point differently on how firm the first stage is, and this campaign does not settle which model to register. If Gabriel chooses B, its registration must list every fork tried (f1, f2 and f3; decision 0015, F10).
3. Whether to open a follow-up task or campaign, for example a build of the coalition alignment?
   - Option A: no.
   - Option B: yes, a build task for the mayor's coalition column, then a new campaign with its own kill rules.
   - Agent's recommendation: option A for now. Coalition alignment needs a data build and a new question formed after these results. Option B is reasonable if Gabriel wants to test it before registering a design.
