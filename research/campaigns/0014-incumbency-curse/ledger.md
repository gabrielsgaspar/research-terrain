# Campaign 0014 ledger

| Step | Kind | Status | Verdict | Links |
| --- | --- | --- | --- | --- |
| s1 | task | done | merged | #457, PR #488 |
| s2 | explore_run | done | survived | PR #490, run 45246860634, `research/explore-runs/0012/45246860634.md` |
| s3 | task | done | merged | #491, PR #495 |
| s4 | explore_run | done | survived | PR #498, run 45252259366, `research/explore-runs/0012/45252259366.md` |
| s5 (f1) | task | done | merged | #499, PR #501 |
| s6 (f1) | explore_run | done | survived (fork) | PR #505, run 45261184634, `research/explore-runs/0012/45261184634.md` |

Budget used: max_explore_runs 2 of 2, max_model_jobs 6 of 26, max_pipeline_runs 0 of 0, max_tasks 2 of 2.

Kill rules, as the tick applied them to the run records:

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
