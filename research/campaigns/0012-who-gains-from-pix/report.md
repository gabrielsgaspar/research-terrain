# Campaign 0012 report: Who gains from emendas Pix, deputies or mayors? Party incumbency in close mayoral races, 2004-2024, and the deputy's own and party vote

What we tested: whether close mayoral races on the exploration half give a balanced, large and powerful enough design to ask if the mayor's party wins again more after emendas Pix, using one gate run.
What happened: the four builds and one task finished and the gate ran, but four of its five kill rules were met (no balanced window, too few races, too little power, an unbalanced placebo), so the campaign stopped.
What it means: on the exploration half this design cannot detect an effect of the size the idea needs, and nothing here is a finding.
Decisions for you: 2 decisions, the first being the idea's status, where the agent recommends `dead`.

## Summary

Steps s1 to s4 built the data (runs 44766224424, 44766227487, 44767467382 and 44766231397). Step s5 was a task (#439, PR #443). Step s6 ran the gate (PR #445, run 44768996266). Decision 0008's balance rule found no window: even 0.5% fails, on `fin_higher_ed` (p 0.019). Four kill rules were met. k2: the smallest cycle had 58 close races at the window, below 300. k3: the minimum detectable H1 difference is 0.735, above 0.10. k4: the placebo jump in `party_held_mayor_lag` is 0.0852, above 0.05. Steps s7 to s12 were skipped. No fork ran. Nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0012-who-gains-from-pix/ledger.md`):

- s1 (pipeline run, PR #442, run 44766224424): done, recorded.
- s2 (pipeline run, PR #441, run 44766227487): done, recorded.
- s3 (pipeline run, PR #444, run 44767467382): done, recorded.
- s4 (pipeline run, PR #440, run 44766231397): done, recorded.
- s5 (task, #439, PR #443): done, merged.
- s6 (explore run, PR #445, run 44768996266): done, killed. Record: `research/explore-runs/0011/44768996266.md`.
- s7 (task): skipped, step s6 was killed.
- s8 (explore run): skipped, step s7 was skipped.
- s9 (task): skipped, step s6 was killed.
- s10 (explore run): skipped, step s9 was skipped.
- s11 (task): skipped, step s10 was skipped.
- s12 (explore run): skipped, step s11 was skipped.

## Results and their limits

These are exploration-half results. Nothing here is a finding. A result from the exploration half is a reason to register a design, not a conclusion. The question was formed after campaign 0011's exploration-half results, so this counts as a further analysis of the same data. Source: `research/explore-runs/0011/44768996266.md`.

- Window by decision 0008's balance rule: none. At 0.5% there are 331 races (662 rows), omnibus p 0.07, smallest covariate p 0.019 (`fin_higher_ed`). Other windows pass or fail on other covariates: 1% has omnibus p 0.281 and smallest p 0.0795; 10% has omnibus p 0.0145 and smallest p 0.0035 (`fin_female`).
- Races per election at the 0.5% window (rows): 2004 68 (136), 2008 58 (116), 2012 65 (130), 2016 69 (138), 2020 71 (142). The smallest is 58.
- Power: the standard deviation of b_post - b_pre over the re-flip draws is 0.238, so the MDE is 3.083 x 0.238 = 0.735. It uses `party_held_mayor_lag` (mean 0.264 on these rows) as a stand-in for the outcome. The real outcome was not read.
- Placebo in `party_held_mayor_lag` at the window: b 0.0852, SE 0.0875, randomisation p 0.342, 662 rows in 331 races. By election: 2004 0.103 (SE 0.179), 2008 0.00779 (SE 0.197), 2012 0.0192 (SE 0.25), 2016 0.2 (SE 0.171), 2020 0.0679 (SE 0.211).

Limits: one run, exploration half only, no outcome after the election was read. The record says that a placebo that passes is not proof of balance. The MDE of 0.735 is against a limit of 0.10, so the shortfall comes from the small number of close races, not from one cycle.

Unexplained differences: None found. There is one explore run record (`research/explore-runs/0011/44768996266.md`), and its numbers match the observed values in the ledger's kill rule lines (0, 58, 0.7348520197035615 and 0.08515208880041673). The pipeline runs s1 to s4 are not explore records, so they were not compared.

## Kill rules applied

As the tick applied them to the run record of s6:

- k1 (no mayoral window, not even 0.5%, passes decision 0008's balance rule (2004-2020 pooled)): `window.found == 0`, observed 0, met: the step is killed.
- k2 (fewer than 300 close mayoral races within the chosen window in some election of 2008, 2012, 2016 and 2020): `counts.min_cycle_races_h < 300`, observed 58, met: the step is killed.
- k3 (the minimum detectable H1 difference (80% power, alpha 0.025) is above 0.10): `power.mde_h1 > 0.1`, observed 0.7348520197035615, met: the step is killed.
- k4 (the placebo jump in party_held_mayor_lag at the chosen window is above 0.05 in absolute value): `placebo.lag_abs > 0.05`, observed 0.08515208880041673, met: the step is killed.
- k5 (some gate estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met.

The verdict of s6 is killed, as in the ledger.

## Forks

The variants this campaign ran inside its envelope (decision 0015), how many
were tried at each fork point, and those refused or only suggested.

### Forks table

None: no fork was declared.

No fork adopted the plan's skipped steps.

### How many were tried

- s6: 1 proposed, 1 refused by the envelope check, 0 ran, 0 survived.

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

### Refused and suggested variants

- s6: Own vs party share of an allied mayor's deputy at the fixed 7.5% window (H3 only): research/campaigns/0012-who-gains-from-pix/forks/f1.md step s14: needs a kill rule other than 'finite' (F4); this variant can only be a suggestion
- s6: spec: local-constant fit (difference in means within the window) for the H1 gate: k1 does not depend on the model, so window.found stays 0. k3 is also out of reach: a rough estimate from the record gives an MDE near 0.13 even at 3%, above the inherited rule.
- s6: spec: window grid starting at 1% (1%-3% pass balance, so h would be 3%, with 370 races in the smallest cycle): It changes decision 0008's rule after seeing the 0.5% balance failure, which is choosing on a seen result. k3 would still kill it (an MDE of about 0.30 by scaling).
- s6: spec: person-level incumbency, eligible finalists only (Gabriel's variant 1): Same balance table, so k1 still fails. It has fewer rows (86-108 eligible rows per election at h), so k2 and k3 fail by more.
- s6: measure: amendment money per inhabitant instead of bench_fed in H2 (variant 2); federations as one party in H3 (variant : Variant 2 needs the mayoral window that the gate did not find. Variants 3 and 4 vary s9 or s10, which are not fork points. Each could be a later campaign's step, chosen after th…
- s6: Full H3-H6 mechanisms run (s9 and s10) as a separate campaign: A fork may change one thing and has only one question slot here. The full mechanisms set is the plan's skipped step, and it cannot be adopted, because its chain (s11 and s12) needs s8, which needs the missing mayoral window.

No fork survived, so there is no fork result to report.

## Budget used

From the tick's ledger: max_explore_runs 1 of 4, max_model_jobs 3 of 50, max_pipeline_runs 4 of 4, max_tasks 1 of 4.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the
issues, the plan and review comments, the pull requests and the runs. A fix
round is one agent review after the first.

### Blocks

None.

No block was posted, so there is no row to list.

### Task steps with more than one plan or a fix round

None.

One plan and no fix round: s5.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-20T15:44:00Z) to `finished` (2026-11-20T16:11:08Z): 0.5 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 0.1 | `s5:merged`, `s6:dispatched` (2026-11-20T16:00:40Z) | `s10:skipped`, `s11:skipped`, `s12:skipped`, `s6:ideate`, `s6:verdict`, `s7:skipped`, `s8:skipped`, `s9:skipped` (2026-11-20T16:07:31Z) |
| 0.1 | `s1:recorded`, `s3:dispatched` (2026-11-20T15:51:27Z) | `s3:recorded` (2026-11-20T15:58:01Z) |
| 0.1 | `s5:filed` (2026-11-20T15:44:39Z) | `s4:recorded` (2026-11-20T15:48:55Z) |

5 shorter gaps left out.

## Checks not run

- Step s7 (task) did not finish (skipped: step s6 was killed).
- Step s8 (explore_run) did not finish (skipped: step s7 was skipped).
- Step s9 (task) did not finish (skipped: step s6 was killed).
- Step s10 (explore_run) did not finish (skipped: step s9 was skipped).
- Step s11 (task) did not finish (skipped: step s10 was skipped).
- Step s12 (explore_run) did not finish (skipped: step s11 was skipped).
- Kill rule k1 of step s8 (Some H1 or H2 estimate, standard error or p-value is not a finite number) was never applied: step s8 did not run to a result.
- Kill rule k1 of step s10 (Some H3-H6 estimate, standard error or p-value is not a finite number) was never applied: step s10 did not run to a result.
- Kill rule k1 of step s12 (Fewer than 7 figures were written) was never applied: step s12 did not run to a result.

## Proposed harness changes (at most three)

### Notes added

None. Every friction group says "None.", so no note was added to `research/agent-notes.md`, and no old note was merged or removed. Only the Scoreboard row for campaign 0012 was added.

### Checks in code proposed

None.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign. They are the variants the tick refused or listed (see "Forks"):

- H3 only: own versus party vote share of an allied mayor's deputy at the fixed 7.5% window. It needs a kill rule other than "finite", so it could only be a later campaign's step.
- Measure: amendment money per inhabitant instead of `bench_fed` in H2, and federations as one party in H3. Each could be a later campaign's step, chosen after this one.
- The full H3-H6 mechanisms run (s9 and s10) as a separate campaign.
- Not recommended: a local-constant fit, a window grid starting at 1%, or person-level incumbency. Each leaves a kill rule met (see the notes above), and the 1% grid changes decision 0008's rule after a seen result.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0011 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option C, `dead`. The plan's path met four kill rules (k1 to k4), no fork ran, and none survived. The MDE of 0.735 is far above the limit of 0.10, and even the tick's rough estimate at 3% is near 0.13. `parked` is the close alternative if Gabriel wants to wait for a data source with more close races.
2. Whether to open a follow-up campaign on H3 (own versus party vote share of an allied mayor's deputy at the fixed 7.5% window)?
   - Option A: no.
   - Option B: yes, as a new campaign with its own kill rules.
   - Agent's recommendation: option A. H3 was set up after the mayoral gate failed, and it would be a new question formed after seeing results. No design for the confirmation half is recommended, and so there is none to register (decision 0015, F10).
