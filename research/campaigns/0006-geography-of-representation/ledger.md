# Campaign 0006 ledger

| Step | Kind | Status | Verdict | Links |
| --- | --- | --- | --- | --- |
| s1 | task | done | merged | #295, PR #297 |
| s2 | pipeline_run | done | recorded | PR #298, run 42833397527 |
| s3 | pipeline_run | done | recorded | run 42846168945 |
| s4 | pipeline_run | done | recorded | PR #303, run 42856914932 |
| s5 | pipeline_run | done | recorded | PR #306, run 42857864152 |
| s6 | task | done | merged | #299, PR #300 |
| s7 | pipeline_run | done | recorded | PR #308, run 42860225743 |
| s8 | pipeline_run | done | recorded | PR #312, run 42905171706 |
| s9 | task | done | merged | #301, PR #302 |
| s10 | pipeline_run | done | recorded | PR #315, run 42919122289 |
| s11 | task | done | merged | #304, PR #305 |
| s12 | pipeline_run | done | recorded | PR #314, run 42900668531 |
| s13 | pipeline_run | done | recorded | PR #313, run 42862601462 |
| s14 | task | done | merged | #307, PR #309 |
| s15 | pipeline_run | done | recorded | PR #316, run 42924200076 |
| s16 | task | done | merged | #317, PR #318 |
| s17 | explore_run | done | survived | PR #319, run 42935501189, `research/explore-runs/0006/42935501189.md` |
| s18 | task | done | merged | #320, PR #321 |
| s19 | explore_run | done | survived | PR #322, run 42939196149, `research/explore-runs/0006/42939196149.md` |

Budget used: max_explore_runs 2 of 2, max_model_jobs 25 of 45, max_pipeline_runs 10 of 12, max_tasks 7 of 7.

Kill rules, as the tick applied them to the run records:

- s17: k1 (Fewer than 10,000 close council pairs at the 0.50% window, pooled 2008-2020, in the exploration half): `counts.pairs_050 < 10000`, observed 23132, not met
- s17: k2 (Less than 85% of the exploration half's sections, pooled 2008-2020, sit at a polling place located within 1 km error): `coverage.located_share < 0.85`, observed 0.9392411485282006, not met
- s17: k3 (Less than 50% of the exploration half's polling places, pooled 2008-2020, are matched to an INEP school at high or medium confidence): `schools.match_share < 0.5`, observed 0.6051341367470602, not met
- s17: k4 (The joint randomisation-inference test of the baseline school facility count, night lights and built-up share on D_p has p below 0.05 (unbalanced baselines)): `balance.ri_p_joint < 0.05`, observed 0.3148425787106447, not met
- s17: k5 (Pre-election placebo: D_p predicts the t-4 to t change in the municipal-school facility count with randomisation-inference p below 0.10): `placebo.ri_p_school < 0.1`, observed 0.4407796101949025, not met
- s17: k6 (The minimum detectable effect on the municipal-school facility count at 80% power (5%, two-sided) is above 0.10 standard deviations of the pre-election change): `power.mde_sd_school > 0.1`, observed 0.006592409839469982, not met
- s19: k1 (Some estimate, standard error, effect in SD or adjusted p-value of the post-election effects is not a finite number): `estimates.finite != True`, observed True, not met
