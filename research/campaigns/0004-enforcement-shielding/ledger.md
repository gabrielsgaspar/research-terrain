# Campaign 0004 ledger

| Step | Kind | Status | Verdict | Links |
| --- | --- | --- | --- | --- |
| s1 | task | done | merged | #272, PR #273 |
| s2 | pipeline_run | done | recorded | PR #274, run 42755238673 |
| s3 | pipeline_run | done | recorded | PR #275, run 42755616189 |
| s4 | task | done | merged | #276, PR #277 |
| s5 | pipeline_run | done | recorded | PR #278, run 42792636592 |
| s6 | task | done | merged | #279, PR #281 |
| s7 | explore_run | done | killed | PR #284, run 42796832006, `research/explore-runs/0005/42796832006.md` |
| s8 | task | skipped | step s7 was killed |  |
| s9 | explore_run | skipped | step s8 was skipped |  |

Budget used: max_explore_runs 1 of 2, max_model_jobs 9 of 28, max_pipeline_runs 3 of 3, max_tasks 3 of 4.

Kill rules, as the tick applied them to the run records:

- s7: k1 (Fewer than 3 of the elections 2008-2020 have at least half of their pre-election flora fines and embargoes located inside their own municipality (too few elections with usable locations)): `coverage.elections_ok < 3`, observed 3, not met
- s7: k2 (Fewer than 400 located pre-election flora fines and embargoes, pooled 2008-2020, in the cells exposed to close pairs at 0.50% (enforcement too rare near strongholds to estimate anything)): `counts.pre_reach_actions < 400`, observed 20296, not met
- s7: k3 (The minimum detectable effect at 80% power (5%, two-sided) at the registered 0.25% window is above 25% of the pre-election baseline mean (could not detect a 25% change)): `power.mde_share_025 > 0.25`, observed 0.770152469390949, met: the step is killed
- s7: k4 (Pre-election placebo at 0.50%: randomisation-inference p below 0.10 (winners' and losers' areas already differed in enforcement before the election)): `placebo.ri_p_050 < 0.1`, observed 0.12443778110944528, not met
