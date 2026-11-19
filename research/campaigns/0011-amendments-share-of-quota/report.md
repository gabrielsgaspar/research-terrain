# Campaign 0011 report: What do budget amendments buy at the ballot box? The municipality's share of the deputy's money, and log reais per inhabitant

What we tested: whether a close mayoral win by a federal deputy's party raises the amendment money the deputy sends to that municipality (first stage), and the deputy's vote share there at the next general election (reduced form), on the exploration half only.
What happened: both explore runs survived every kill rule; only the log reais per inhabitant outcome was powered, and its first stage (b 0.192, SE 0.0362) and reduced form (b 0.0119, SE 0.00242) are positive.
What it means: the idea as written passed its gate and its main run, but these are exploration-half results on outcomes chosen after an earlier gate failed, so nothing here is a finding.
Decisions for you: 3 decisions are listed below, the first being the idea's status.

## Summary

Campaign 0011 re-asked the question of idea 0009 with two new measures of the money: the municipality's share of the deputy's amendment money (`share`) and ln(1 + reais per inhabitant) (`log_pc`). Gabriel chose them after campaign 0010's gate failed.

The gate (`research/explore-runs/0010/44484340952.md`) chose a 7.5% window with 2300 close races. `share` was not powered. `log_pc` was powered and its placebo was flat. The main run (`research/explore-runs/0010/44538371996.md`) found a positive first stage and a positive reduced form for `log_pc`. All eight kill rules were "not met". Every step finished, with no block, fix round, retry or repair.

## What ran

- s1: pipeline run, PR #425, run 44482106450. Recorded.
- s2: pipeline run, PR #426, run 44482603437. Recorded.
- s3: task #424, PR #427 (the gate script). Merged.
- s4: explore run, PR #428, run 44484340952 (the gate). Survived.
- s5: task #429, PR #430 (the main script). Merged.
- s6: explore run, PR #431, run 44538371996 (the main run). Survived.

Tracking issue: #423.

## Results and their limits

These are exploration-half results. Nothing here is a finding. The confirmation half was not touched.

This is one more analysis of idea 0009's question. The outcomes were chosen after campaign 0010's gate failed on per-capita reais (caveat in both run records). A pass here is weaker evidence than a test fixed in advance.

Gate (`research/explore-runs/0010/44484340952.md`):

- Window h by decision 0008's balance rule: 7.5%. Close races at h: 2300 (13809 units, 1370 deputies). Cycles: A 871 races, B 806, C 623.
- `share`: mean 0.00222, MDE statistic 1.04 against a limit of 0.25, so not powered. Its pre-window placebo statistic was 0.684 (limit 0.25), but the rule only reads powered outcomes.
- `log_pc`: MDE 0.0736 against a limit of 0.223, so powered. Pre-window placebo b 0.0142 (SE 0.0218), statistic 0.0142 against 0.223, so it does not fail.
- Vote placebo at h: abs b / mean 0.0245 (limit 0.25).
- Smallest money share of the author link: 0.915 (limit 0.9), in cycle A. Cycle B 0.926, cycle C 0.932.

Main run (`research/explore-runs/0010/44538371996.md`), `log_pc` only, alpha 0.025:

- First stage at h: b 0.192 (SE 0.0362), 97.5% interval [0.111, 0.274], randomisation p 0.0005, 13809 units, 2300 races. At 5%: b 0.194 (SE 0.0442).
- Reduced form at h: b 0.0119 (SE 0.00242), 97.5% interval [0.0065, 0.0173], randomisation p 0.0005, 10895 units. At 5%: b 0.011 (SE 0.00295).
- By cycle, first stage: A 0.0273 (SE 0.0369), B 0.236 (SE 0.0633), C 0.401 (SE 0.0899); C minus A 0.374 (SE 0.0959). The cycle A first stage is close to zero.
- By cycle, reduced form: A 0.00788 (SE 0.00391), B 0.0179 (SE 0.00471), C 0.0115 (SE 0.00378); C minus A 0.00359 (SE 0.00545).
- Votes per 1,000 reais: 1.86. This is an upper bound, because allied mayors also campaign. The record gives no standard error and no test.
- Strong first stages (F at least 10): 1 outcome. The record does not print the F statistic itself.

Limits:

- The outcomes were picked after a failed gate (above).
- `share` could not be tested: it was not powered.
- A placebo that passes is not proof of balance (gate record caveat).
- The first stage differs a lot across cycles: it is 0.0273 in cycle A and 0.401 in cycle C. A pooled estimate hides this.
- The reduced form leaves out 2914 units whose deputy did not run at t1.
- Randomisation p of 0.0005 is the floor of the draws, so it is not an exact p value.

### Unexplained differences

None found. Differences between the two records that were checked, all explained:

- Close races: 2300 in `research/explore-runs/0010/44484340952.md` and 2300 in `research/explore-runs/0010/44538371996.md`. Same.
- Units: 13809 in the gate and 13809 in the first stage of the main run. Same. The reduced form has 10895 units, and the main record says 2914 units were left out because the deputy did not run at t1 (13809 minus 2914 is 10895).
- Mean of `log_pc`: 0.174 in the gate (pre-window, for the placebo and power) and 0.447 in the main run (post-window, for the first stage). These are different windows, so they differ by design.
- `share` units: 11044 in the gate, against 13809 for `log_pc`. `share` is undefined where the deputy paid nothing in the window (idea file, Design).

## Kill rules applied

As the tick applied them to the run records. Both steps' verdict is "survived", as the ledger says.

- s4: k1 (No mayoral window, not even 0.5%, passes decision 0008's balance rule): `window.found == 0`, observed 1, not met
- s4: k2 (Fewer than 200 close mayoral races (cycles A-C pooled, with an eligible deputy) within the chosen window): `counts.races_h < 200`, observed 2300, not met
- s4: k3 (Neither outcome is powered: share MDE above 25% of its pre-window mean and log_pc MDE above 0.223 (80% power, alpha 0.025)): `power.n_powered < 1`, observed 1, not met
- s4: k4 (Some powered outcome's pre-window placebo is above its threshold (share: |b| above 25% of its mean; log_pc: |b| above 0.223)): `placebo.powered_failing > 0`, observed 0, not met
- s4: k5 (The placebo slope on the deputy's vote share at the previous general election exceeds 25% of its mean, in absolute value): `placebo.vote_share_abs > 0.25`, observed 0.02446244772082185, not met
- s4: k6 (In some cycle, deputies linked to authors get less than 90% of the window money of current-legislature authors, senators left out): `link.money_share < 0.9`, observed 0.9153867685439887, not met
- s6: k1 (No powered outcome has a municipality-clustered first-stage F statistic of at least 10): `first_stage.n_strong < 1`, observed 1, not met
- s6: k2 (Some first-stage or reduced-form estimate, standard error or p-value is not a finite number): `estimates.finite != True`, observed True, not met

## Forks

The variants this campaign ran inside its envelope (decision 0015), how many
were tried at each fork point, and those refused or only suggested.

### Forks table

None: no fork was declared.

No fork adopted the plan's skipped steps.

### How many were tried

- s4: 0 proposed, 0 refused by the envelope check, 0 ran, 0 survived.
- s6: 2 proposed, 2 refused by the envelope check, 0 ran, 0 survived.

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

### Refused and suggested variants

- s6: First stage on log Pix reais per inhabitant (special transfers only): research/campaigns/0011-amendments-share-of-quota/forks/f1.md: evidence 'data/contracts/amendments_panel.md' is not a run record
- s6: First stage on the extensive margin: any individual-amendment payment in the post window: research/campaigns/0011-amendments-share-of-quota/forks/f1.md: evidence 'data/contracts/amendments_panel.md' is not a run record
- s4: measure: the extensive margin (any individual payment above 0 in the window, from amend_pre_total / amend_post_total) in: At s4 it would need its own gate task and run plus a main task and run (4 steps) to affect anything, since s5 never reads fork gate records. As a variant of s6 it needs only 1 t…
- s4: spec: alignment by the mayor's coalition or federation instead of the deputy's own party: It changes who is treated. That means rebuilding the panel (a build task and a pipeline run under new *_fK names) and then a new gate task and run: the whole per-fork step cap, with no main run left. Better as…
- s4: measure: Pix amendments only (amend_pre_pix / amend_post_pix), cycles B and C: Pix transfers barely exist in the pre windows, so a gate-level power or placebo check says little. If at all, it belongs at s6 as a first-stage measure.
- s4: question: the vote change of the mayor's party's state deputies in the same close races (a brokerage benchmark): It needs state-deputy outcomes the panel does not hold (a new build from tse_general/tse_results), and the gate's rules cannot read it. It uses the only question-fork slot, so weigh it a…
- s6: spec: alignment by the mayor's coalition or federation instead of the deputy's own party (Gabriel's variant 2): The panel holds only rows where the deputy's own party had a finalist. A coalition spec needs a new panel build in new *_fK files (build task, pipeline run, explore task, explore run: all…
- s6: question: vote change of the mayor's party's state deputies in the same close races, as a brokerage benchmark (Gabriel's: It needs a new state-deputy vote panel built from tse_general (a build task and a pipeline run before the explore task and run). Its results would need library rules, and the on…
- s6: transform: log of reais per 1,000 inhabitants (or another unit) to check that the ln(1+x) jump does not depend on units: Within the envelope, but the extensive-margin fork (f2) answers the same concern more directly and for the same cost. Adding it would raise the number of forks tried without like…
- s6: Pre-window placebo for the Pix-only and extensive-margin measures: The parent step s6 estimates no placebo (the gate s4 did). Adding one inside a fork of s6 would make it differ from its parent in a second way. A gate-type fork of s4 is no longer possible here, because s4's fork point has passed an…

No fork survived, so there is no count of forks tried next to a surviving fork.

## Budget used

max_explore_runs 2 of 2, max_model_jobs 6 of 30, max_pipeline_runs 2 of 3, max_tasks 2 of 3.

## Stops and blocks

What slowed the campaign down, counted by the tick from the ledger, the
issues, the plan and review comments, the pull requests and the runs. A fix
round is one agent review after the first.

### Blocks

None.

Blocks table rows: none. The table says "None.", so there was no block.

### Task steps with more than one plan or a fix round

None.

One plan and no fix round: s3, s5.

### Run steps that took more than one run

None.

### Repairs

None.

### Time

Wall-clock time from `started` (2026-11-19T07:45:45Z) to `finished` (2026-11-19T14:06:39Z): 6.3 hours.

The three longest gaps between two ledger events:

| Hours | After | Before |
| --- | --- | --- |
| 5.7 | `s4:ideate:none` (2026-11-19T08:13:02Z) | `s5:merged`, `s6:dispatched` (2026-11-19T13:55:51Z) |
| 0.1 | `s5:merged`, `s6:dispatched` (2026-11-19T13:55:51Z) | `s6:ideate`, `s6:verdict` (2026-11-19T14:03:13Z) |
| 0.1 | `s2:recorded` (2026-11-19T07:55:56Z) | `s3:merged`, `s4:dispatched` (2026-11-19T08:02:56Z) |

7 shorter gaps left out.

## Checks not run

- Referee R5 was marked Not applicable in the review of step s3 (PR #427).
- Referee R5 was marked Not applicable in the review of step s5 (PR #430).

The campaign file allows R5 to be "Not applicable" (`referee_not_applicable_ok: [R5]`). Every step finished and every kill rule was applied.

## Proposed harness changes (at most three)

### Notes added

None. Blocks, fix rounds, retries and repairs are all "None.", so no friction fact calls for a note. The Scoreboard row was added.

### Checks in code proposed

- Friction fact: s6 had 2 forks proposed and 2 refused by the envelope check, because their evidence `data/contracts/amendments_panel.md` is not a run record. Check: let the ideation step see, before it proposes a fork, which evidence paths the envelope check accepts. File it would touch: `src/terrain/campaigns/` (the fork envelope check).

## Suggested next variants (not run)

Not run. These come from the refused and suggested variants in "Forks".

- The extensive margin: any individual payment in the post window, as a first-stage measure (a variant of s6).
- Pix amendments only, as a first-stage measure, cycles B and C.
- Alignment by the mayor's coalition or federation instead of the deputy's own party. It needs a new panel build.
- The vote change of the mayor's party's state deputies in the same close races, as a brokerage benchmark. It needs a new state-deputy vote panel.
- A pre-window placebo for the Pix-only and extensive-margin measures.

## Decisions for Gabriel

The recommendations below are the agent's, not his.

1. **The idea's status (idea 0010).** Options: `promising`, `parked`, `dead`. Recommended: `promising`. The plan's path passed all eight kill rules, and no fork was tried. Be careful with it: the outcomes were chosen after a failed gate, the result is on the exploration half only, and the cycle A first stage is close to zero (0.0273, SE 0.0369).
2. **Register one design for the confirmation half?** Options: register the `log_pc` first stage and reduced form at the 7.5% window; wait for a follow-up campaign first; do not register. Recommended: register, but only after Gabriel has read the by-cycle spread. Whatever is registered, its registration must list every fork tried (decision 0015, F10): none ran, and 2 were refused at s6.
3. **Open a follow-up campaign for the variants in "Suggested next variants"?** Options: open one for the extensive margin and the Pix-only measures; open none. Recommended: open one, limited to those two measures, because they need no new build.
