# Campaign 0014 report: Did the incumbency curse of Brazilian mayors' parties lift in 2020? A regression discontinuity fixed in advance (decision 0017)

What we tested: whether, in close mayoral races on the exploration half, the party that narrowly won stood less likely to win again four years later (the incumbency curse), and whether that changed in the 2020 election, using a gate run, a main run and one fork of the gate.
What happened: all six steps finished and no kill rule was met, in the plan's path (s2, s4) and in fork f1 (s6); in the main run the 2020 effect is above the 2008-2016 effect (difference 0.216, RI p 0.0005).
What it means: on the exploration half the design is balanced and powered, and the main run points the way the idea predicted, but nothing here is a finding.
Decisions for you: 2 decisions, the first being the idea's status, where the agent recommends `promising`.

## Summary

Step s1 and s3 were tasks (#457, PR #488 and #491, PR #495). Step s2 ran the gate (PR #490, run 45246860634). It passed every kill rule: omnibus balance p 0.252, no placebo failure, H1 MDE 0.143 against a limit of 0.2, and 1378 races in the smallest cycle against a floor of 300. Step s4 ran the main run (PR #498, run 45252259366). Its H1 contrast (2020 minus 2008-2016 pooled) is 0.216 (SE 0.0425, RI p 0.0005): the effect is -0.0726 before and 0.143 in 2020. Fork f1 (s5 and s6) repeated the gate with a uniform kernel at |margin| <= 0.10 (PR #501 and #505, run 45261184634) and also passed every rule. The plan's path and the fork both survived, so the "only a fork survived" case does not apply. A fork's result is never a finding, and nothing here is a finding.

## What ran

From the tick's ledger (`research/campaigns/0014-incumbency-curse/ledger.md`):

- s1 (task, #457, PR #488): done, merged.
- s2 (explore run, PR #490, run 45246860634): done, survived. Record: `research/explore-runs/0012/45246860634.md`.
- s3 (task, #491, PR #495): done, merged.
- s4 (explore run, PR #498, run 45252259366): done, survived. Record: `research/explore-runs/0012/45252259366.md`.
- s5 (f1, task, #499, PR #501): done, merged.
- s6 (f1, explore run, PR #505, run 45261184634): done, survived (fork). Record: `research/explore-runs/0012/45261184634.md`.

## Results and their limits

These are exploration-half results. Nothing here is a finding. A result from the exploration half is a reason to register a design, not a conclusion. The idea was formed after campaign 0012's gate and reuses idea 0011's data and the same exploration half, so this counts as a further analysis of data already seen at the gate stage (counts and balance only, never an outcome at e+4 before this campaign). A balance test that passes is not proof of balance. Sources: `research/explore-runs/0012/45246860634.md`, `research/explore-runs/0012/45252259366.md` and `research/explore-runs/0012/45261184634.md`.

Gate (s2, `research/explore-runs/0012/45246860634.md`), h = 0.135, triangular kernel:

- Races per election inside h: 2004 1645, 2008 1517, 2012 1600, 2016 1447, 2020 1378. The smallest is 1378.
- Balance, all rows: omnibus p 0.252; smallest p 0.0575 (`bench_fed_pos`).
- Placebo in `party_held_mayor_lag`: b 0.00868, SE 0.0172, randomisation p 0.614.
- Power: the H1 MDE is 0.143. It uses `party_held_mayor_lag` as a stand-in for the outcome; the real outcome was not read in the gate.
- S2 sample (eligible finalists): omnibus p 0.331, MDE 0.159, placebo p 0.073, 1378 races in the smallest cycle.

Main run (s4, `research/explore-runs/0012/45252259366.md`), same design:

- H1 (primary, alpha 0.05), `party_wins_next`, all rows: b_pre -0.0726, b_post 0.143, difference 0.216, SE 0.0425, 95% interval [0.133, 0.299], clustered p 3.83e-07, RI p 0.0005; 11880 rows, 5940 races.
- Each election (S1), b with RI p: 2004 -0.00564 (0.897), 2008 -0.0701 (0.0825), 2012 -0.123 (0.003), 2016 -0.0192 (0.615), 2020 0.143 (0.001). The 2004-2012 pooled replication of Klasnja and Titiunik's -0.15 is -0.0663 (SE 0.0221, RI p 0.003).
- S2, the personal effect (`finalist_wins_next`, eligible rows): 2020 minus 2008-2016 is 0.468 (SE 0.0545, RI p 0.0005).
- S3, party runs again: difference 0.024 (RI p 0.595). Finalist runs again: difference 0.247 (RI p 0.0005).
- S4, connected parties: difference 0.111 (SE 0.0962, RI p 0.235). This does not separate connected from unconnected parties.
- S5, town money: the 2020 minus 2016 total is -0.193 (SE 0.221, RI p 0.395). It does not show a link to the money.
- Robustness, H1 difference: uniform 5% 0.232, uniform 7.5% 0.204, uniform 10% 0.195, triangular 10% 0.215, triangular 20% 0.227, with controls and fixed effects 0.214.

Fork f1 (s6, `research/explore-runs/0012/45261184634.md`), h = 0.1, uniform kernel: omnibus p 0.331, placebo.fail 0, H1 MDE 0.15, smallest cycle 1096 races. It is one of one tried at s2 (see "Forks").

Limits:

- One half of the municipalities, one run per step, errors clustered by municipality, randomisation inference with 2,000 draws.
- Other explanations of a change over time: the 2020 election was held in the pandemic; company donations were banned from 2016 and the public campaign fund began in 2018; council coalitions ended in 2020. A change over time is not by itself the effect of Pix, and S4 and S5 are weak links (`bench_fed` is predetermined, not randomised).
- 2024 federations count as one party; 1299 rows of 2020 inside h are in a party that became a 2024 federation.
- The main run has no pre-fixed rule for how large a 2020 effect must be; k1 of s4 only checks that numbers are finite.
- The fork's kill rule k4 still carries the text "inside h = 0.135", while f1 used |margin| <= 0.10 (copied by code). Its rule reads the observed count, 1096, and was met in neither case.

Unexplained differences (each pair is from the run records; none is resolved here):

- The same uniform 10% window gives different omnibus p values. In `research/explore-runs/0012/45246860634.md`, decision 0008's table (information only), row `w10pct` (all rows, 6060 races) has omnibus p 0.0185 and smallest p 0.0045 (`fin_female`). In `research/explore-runs/0012/45261184634.md`, the design's own model at h = 0.1 on the same 6060 races (2004-2020) has omnibus p 0.331 (4742 races, 2008-2020 pooled) and smallest p 0.076 (`bench_fed_pos`). The two use different models (a difference in means against a local linear fit) and different covariate lists (the 0008 table includes `party_held_mayor_lag`), but the records do not say which part explains the gap.
- The omnibus p of fork f1 on all rows (0.331 in `research/explore-runs/0012/45261184634.md`) is the same to three digits as the omnibus p of the S2 sample in the gate (0.331 in `research/explore-runs/0012/45246860634.md`). They are different fits (uniform at 10% on all rows, triangular at 0.135 on eligible rows). It may be a coincidence; the records do not say.
- Races in the all-rows balance table: 5942 in `research/explore-runs/0012/45246860634.md` against 5940 in the main run's H1 in `research/explore-runs/0012/45252259366.md`, both with 11880 rows. The S2 sample has 5941 races (9143 rows) in the gate against 5939 (9141 rows) in the main run. Only the 2020 cycle differs in the per-election tables: 1378 races (2756 rows) in the gate against 1376 (2752 rows plus 4 null-Y rows) in the main run.
- At the uniform 10% window the main run has 4740 races (9480 rows) in `research/explore-runs/0012/45252259366.md`, and fork f1's balance table has 4742 races (9480 rows) in `research/explore-runs/0012/45261184634.md`.
- Smallest cycle's races inside h: 1378 at s2 (h = 0.135, triangular) in `research/explore-runs/0012/45246860634.md` against 1096 at s6 (h = 0.1, uniform) in `research/explore-runs/0012/45261184634.md`. This is expected from the narrower window, and it is listed for completeness.

## Kill rules applied

As the tick applied them to the run records (all outcomes match the Verdict column of the ledger):

- s2: k1 (The omnibus randomisation p of the design's own model on the five predetermined covariates (2008-2020 pooled) is below 0.05): `balance.omnibus_p < 0.05`, observed 0.25237381309345325, not met
- s2: k2 (The jump in party_held_mayor_lag is larger than 0.05 in absolute value and its randomisation p is below 0.05): `placebo.fail == 1`, observed 0, not met
- s2: k3 (The design cannot detect a swing of 0.20, from Klasnja and Titiunik's -0.15 to +0.05 (H1 MDE, 80% power, alpha 0.05, above 0.20)): `power.mde_h1 > 0.2`, observed 0.1430926594688613, not met
- s2: k4 (Fewer than 300 exploration-half races inside h = 0.135 in some election of 2008, 2012, 2016 and 2020): `counts.min_cycle_races_h < 300`, observed 1378, not met
- s2: k5 (Some gate estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s4: k1 (Some main-run estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met
- s6: k1 (The omnibus randomisation p of the design's own model on the five predetermined covariates (2008-2020 pooled) is below 0.05): `balance.omnibus_p < 0.05`, observed 0.3308345827086457, not met
- s6: k2 (The jump in party_held_mayor_lag is larger than 0.05 in absolute value and its randomisation p is below 0.05): `placebo.fail == 1`, observed 0, not met
- s6: k3 (The design cannot detect a swing of 0.20, from Klasnja and Titiunik's -0.15 to +0.05 (H1 MDE, 80% power, alpha 0.05, above 0.20)): `power.mde_h1 > 0.2`, observed 0.14975992789615591, not met
- s6: k4 (Fewer than 300 exploration-half races inside h = 0.135 in some election of 2008, 2012, 2016 and 2020): `counts.min_cycle_races_h < 300`, observed 1096, not met
- s6: k5 (Some gate estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met

The verdicts are: s2 survived, s4 survived, s6 survived (fork), as in the ledger.

## Forks

The variants this campaign ran inside its envelope (decision 0015), how many
were tried at each fork point, and those refused or only suggested.

### Forks table

| Fork | Parent step | Type | What changed | Why | Steps | Verdict | The numbers its kill rules read |
| --- | --- | --- | --- | --- | --- | --- | --- |
| f1 | s2 | spec | kernel and bandwidth: uniform kernel with \|margin\| <= 0.10 instead of triangular with h = 0.135, in every gate fit (counts, balance, placebo, power, all rows and the S2 sample) | Run 45246860634 passed every s2 rule at the triangular h = 0.135. Its decision-0008 table (information only) gives, for the uniform 10% window on all rows, omnibus p 0.0185 and min p 0.0045 (fin_fema… | s5, s6 | survived (fork) | k1 (The omnibus randomisation p of the design's own model on the five predetermined covariates (2008-2020 pooled) is below 0.05): `balance.omnibus_p < 0.05`, observed 0.3308345827086457, not met; k2 (The jump in party_held_mayor_lag is larger than 0.05 in absolute value and its randomisation p is below 0.05): `placebo.fail == 1`, observed 0, not met; k3 (The design cannot detect a swing of 0.20, from Klasnja and Titiunik's -0.15 to +0.05 (H1 MDE, 80% power, alpha 0.05, above 0.20)): `power.mde_h1 > 0.2`, observed 0.14975992789615591, not met; k4 (Fewer than 300 exploration-half races inside h = 0.135 in some election of 2008, 2012, 2016 and 2020): `counts.min_cycle_races_h < 300`, observed 1096, not met; k5 (Some gate estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met |

No fork adopted the plan's skipped steps.

### How many were tried

- s2: 1 proposed, 0 refused by the envelope check, 1 ran, 1 survived.

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

Fork f1 survived (fork): 1 of 1 tried at s2. A fork's result is never a finding.

### Refused and suggested variants

- s2: The personal effect (S2 sample, eligible finalists) as the primary of the main run: The gate's checks for the S2 sample are already in run 45246860634 (s2_sample: omnibus p 0.331, placebo.fail 0, MDE 0.159, 1378 races), so a gate fork would repeat that run. The variant only makes sense in the main …

## Budget used

From the tick's ledger: max_explore_runs 2 of 2, max_model_jobs 6 of 26, max_pipeline_runs 0 of 0, max_tasks 2 of 2.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the
issues, the plan and review comments, the pull requests and the runs. A fix
round is one agent review after the first.

### Blocks

| Step | Cause | Posted | Hours until unblocked |
| --- | --- | --- | --- |
| s1 | an agent stopped and labelled it needs-human | 2026-11-22T14:50:34Z | 5.6 |
| s1 | an agent stopped and labelled it needs-human | 2026-11-22T20:34:41Z | 21.9 |
| s1 | no pull request twelve hours after the plan | 2026-11-23T18:27:10Z | 0.7 |

### Task steps with more than one plan or a fix round

None.

One plan and no fix round: s1, s3, s5.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-22T14:42:00Z) to `finished` (2026-11-23T20:45:20Z): 30.1 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 21.9 | `s1:blocked:a37e09f4-2` (2026-11-22T20:34:41Z) | `s1:blocked:344f6142`, `s1:unblocked:a37e09f4-2` (2026-11-23T18:27:10Z) |
| 5.6 | `s1:blocked:a37e09f4` (2026-11-22T14:50:34Z) | `s1:unblocked:a37e09f4` (2026-11-22T20:29:04Z) |
| 0.7 | `s4:verdict` (2026-11-23T19:54:56Z) | `s5:merged`, `s6:dispatched` (2026-11-23T20:36:49Z) |

13 shorter gaps left out.

## Checks not run

- Referee R5 was marked Not applicable in the review of step s1 (PR #488).
- Referee R5 was marked Not applicable in the review of step s3 (PR #495).
- Referee R5 was marked Not applicable in the review of step s5 (PR #501).

Every step finished and every kill rule was applied. The tick's list gives no reason beyond the row being marked "Not applicable" in the review of each task step.

## Proposed harness changes (at most three)

### Notes added

Three notes were added to `research/agent-notes.md`. No old note was merged or removed (the file now holds 10 of at most 30).

- [N008] (builder) When a task stops, say in one sentence the single thing a person must do to continue, so the wait ends with one reply. From: campaign 0014, s1 blocked for 21.9 hours. Added 2026-11-23.
- [N009] (planner) When a task needs an answer that only a person can give, put that question first in the plan, so the first stop is not followed by a second. From: campaign 0014, s1 blocked twice, 5.6 and 21.9 hours. Added 2026-11-23.
- [N010] (design) For the first task of a campaign, name in the issue every input it needs, so a builder is not left without a pull request after the plan. From: campaign 0014, s1 had no pull request twelve hours after the plan. Added 2026-11-23.

### Checks in code proposed

None.

## Suggested next variants (not run)

These are suggestions only. None was run, and none is part of this campaign. They are the variants the tick refused or listed (see "Forks"):

- The personal effect (S2 sample, eligible finalists) as the primary of the main run. The tick refused it as a gate fork, because the gate's S2-sample checks are already in run 45246860634. It only makes sense in the main run, so it could be a later campaign's step, chosen after this one.

## Decisions for Gabriel

The recommendations below are the agent's, not Gabriel's.

1. What status should idea 0012 take?
   - Option A: `promising`.
   - Option B: `parked`.
   - Option C: `dead`.
   - Agent's recommendation: option A, `promising`. The plan's path (s2 gate and s4 main run) and fork f1 all survived, and no kill rule was met, so `dead` does not apply. This is a result on the exploration half, formed after campaign 0012's gate, and nothing here is a finding. `parked` is the close alternative if Gabriel wants the two open differences above explained first.
2. Whether to register one design for the confirmation half?
   - Option A: no, not yet.
   - Option B: yes, register the design of the main run (h = 0.135, triangular kernel, H1 as the primary at alpha 0.05).
   - Agent's recommendation: option B, if Gabriel accepts `promising`. It is the design fixed before any outcome was read and the one the plan's path ran. Its registration must list every fork tried (decision 0015, F10): f1, the uniform kernel at |margin| <= 0.10, one of one tried at s2. Registering is Gabriel's step, not an agent's, and this campaign has not touched the confirmation half.
