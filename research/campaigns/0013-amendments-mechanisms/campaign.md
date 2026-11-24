---
id: "0013"
title: "Amendments: favouritism or more money, Pix, sorting, whose votes move and when the money is paid"
status: done
idea: "0010"
owner: gabrielsgaspar
created: 2026-11-22
end_by: 2026-12-10
budget:
  max_tasks: 3
  max_explore_runs: 3
  max_pipeline_runs: 0
  max_model_jobs: 36
referee_not_applicable_ok: [R5]
self_repair: true
forks:
  max_forks: 3
  per_point: 2
  max_new_datasets: 0
  max_steps_per_fork: 3
  types: [transform, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: [s2, s4, s6]
  budget:
    max_tasks: 3
    max_explore_runs: 3
    max_pipeline_runs: 0
    max_model_jobs: 24
datasets: []
steps:
  # Pair 1: the instrument by payment type, in percent, and sorting
  - id: s1
    kind: task
    type: explore
    draft: drafts/s1.md
    allowed_paths:
      - explore/0010_instrument_sorting.py
      - tests/test_explore_instrument_sorting.py
    after: []
  - id: s2
    kind: explore_run
    script: 0010_instrument_sorting
    after: [s1]
    kill_rules:
      - id: k1
        says: "With controls for sorting, the first stage's municipality-clustered F is below 10"
        field: first_stage.f_cluster
        op: "<"
        value: 10
        confirmed: true
      - id: k2
        says: "The pre-window placebo is larger than half the effect and significant at 5%"
        field: placebo.pre_fail
        op: "=="
        value: 1
        confirmed: true
      - id: k3
        says: "Some estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Pair 2: whose votes move (H3 and H4 of idea 0011's file)
  - id: s3
    kind: task
    type: explore
    draft: drafts/s3.md
    allowed_paths:
      - explore/0010_vote_mechanisms.py
      - tests/test_explore_vote_mechanisms.py
    after: []
  - id: s4
    kind: explore_run
    script: 0010_vote_mechanisms
    after: [s3]
    kill_rules:
      - id: k1
        says: "The t0 placebo (party or state-deputy share) is above 10% of its mean and significant at 5%"
        field: placebo.t0_fail
        op: "=="
        value: 1
        confirmed: true
      - id: k2
        says: "Some estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: skip_dependents
  # Pair 3: when the money is paid (H6 of idea 0011's file)
  - id: s5
    kind: task
    type: explore
    draft: drafts/s5.md
    allowed_paths:
      - explore/0010_payment_timing.py
      - tests/test_explore_payment_timing.py
    after: []
  - id: s6
    kind: explore_run
    script: 0010_payment_timing
    after: [s5]
    kill_rules:
      - id: k1
        says: "The absolute mean pre-period monthly coefficient is more than half the absolute mean post-period coefficient"
        field: placebo.lead_ratio
        op: ">"
        value: 0.5
        confirmed: true
      - id: k2
        says: "Some estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: skip_dependents
---

# 0013: Amendments: favouritism or more money, Pix, sorting, whose votes move and when the money is paid

## Question

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`). Campaign
0011 found, on the exploration half (gate
`research/explore-runs/0010/44484340952.md`, window 7.5%; main run
`research/explore-runs/0010/44538371996.md`), that when a federal
deputy's party narrowly wins a mayoralty, the deputy sends more amendment
money there. In ln(1 + reais per inhabitant) the jump is 0.192 (SE 0.036,
F 28); by cycle 0.03 (A, 2017-18), 0.24 (B, 2021-22) and 0.40 (C,
2025-26). The deputy's vote gain (0.0119, SE 0.0024) is already there in
cycle A and does not grow. (Numbers as Gabriel's brief states them.)

This campaign asks five open questions, all with the panels campaign 0012
built (`amendments_panel` v3 and `amendments_monthly`):

1. **More favouritism, or just more money?** National individual-amendment
   payments in the three post windows were about R$11bn (A), R$19bn (B)
   and R$43bn (C) (public CGU totals), so ln(1 + x) can grow with no
   change in favouritism. A Poisson model gives the premium in percent,
   which can be compared across cycles.
2. **Does the premium run through Pix** (cash to the town hall, from 2020;
   19% of the money in B, 26% in C)?
3. **Sorting.** Campaign 0012's gate
   (`research/explore-runs/0011/44768996266.md`) hinted that parties
   already holding the town hall win close races slightly more often. Does
   the first stage survive controls for that?
4. **Whose votes move:** the sitting deputies', the whole party's, or also
   the party's state deputies', who send no federal amendments? Ventura
   (2021, *Electoral Studies*) found a party-level gain of about 2 points
   for 2000-2014.
5. **When is the money paid?**

**When each question was set.** Questions 4 and 5 are H3, H4 and H6 of
idea 0011's file (`research/ideas/0011-who-gains-from-pix.md`), declared
on 2026-11-20 before campaign 0012's gate. They never ran only because
that campaign's step order made them wait for the mayoral gate, which was
killed (`research/campaigns/0012-who-gains-from-pix/report.md`). H5
(whether the deputy runs again) is not run: `ran_t1` is the same in all of
a deputy's towns, so with deputy-by-cycle fixed effects there is nothing
to estimate. Instead, one reduced form counts a deputy who did not run as
0 votes. Questions 1 to 3 are added now, after campaign 0011's results.

Exploration half only (decision 0011). This is the same exploration half
and window campaign 0011 analysed, so every result here is a further look
at the same data, not an independent test, and the report must say so.
No new data and no build.

## Already known

Repository scan (`novelty_scan.py`, 2026-11-22) and web searches of the
same day. Campaigns 0009-0012 checked the amendments, alignment and
incumbency literature (`research/campaigns/0012-who-gains-from-pix/campaign.md`,
"Already known"); not repeated here.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Mayor's party in close races → deputies' amendments | explored (earlier period); tried on this exploration half | (web, unverified) Baião and Couto, *Opinião Pública* 23(3) 2017; `research/explore-runs/0010/44538371996.md` |
| Allied mayors get more amendments and Pix, descriptive | partly explored | (web, unverified) FGV EAESP "Voto a voto: Prefeito aliado vale um Pix" (column; https://eaesp.fgv.br/node/13878); a CESOP/Unicamp paper that uses a discontinuity on the mayor's party (design not read) |
| Premium in percent by cycle (Poisson), Pix vs non-Pix | new here | Pix and extensive-margin forks of campaign 0011 were refused, never run (`research/campaigns/0011-amendments-share-of-quota/report.md`, "Forks") |
| Sorting checks for this first stage | new here | the hint is in `research/explore-runs/0011/44768996266.md` (mayoral panel, a different design) |
| Party-level vote gain from an allied mayor | explored, 2000-2014 | Ventura (2021), *Electoral Studies*, as Gabriel's brief cites it (not found by the web search; unverified) |
| Party vs sitting deputies vs state deputies, 2018-2026 | new | H3 and H4 of idea 0011, never run |
| Monthly timing of payments to allied towns | new | H6 of idea 0011, never run |
| Supreme Court's Pix rulings | context | (web, unverified) STF news, August 2024 (suspension of mandatory amendments until transparency rules; plenary 11-0) and December 2024 (https://noticias.stf.jus.br/?p=93292) |

What this campaign adds: the premium in percent across cycles, its split
by payment type, the first stage with sorting controls, the party,
sitting-deputy and state-deputy vote changes in the same close races, and
monthly payments in event time.

## Read before this runs

- **Ventura (2021)**, *Electoral Studies* (closest for question 4; cited
  by Gabriel; the web search did not find it, so unverified). Gabriel: not
  stated; his brief asks for `active` and for questions only on merges,
  loosened checks or large data fixes.
- **Baião and Couto (2017)**, "A eficácia do pork barrel", *Opinião
  Pública* 23(3), doi:10.1590/1807-01912017233714 (closest for questions
  1-3; web, unverified). Gabriel (2026-11-15, for campaign 0009): "Not
  yet: active anyway".
- **FGV EAESP, "Voto a voto: Prefeito aliado vale um Pix"**,
  https://eaesp.fgv.br/node/13878 (column; web, unverified). Gabriel: not
  stated.

## Steps and why

Three independent pairs. `after` is `[]` for s1, s3 and s5, so a kill in
one pair cannot skip another pair's steps. One task is in flight per
campaign, so the tick files s1, s3 and s5 one after another, and each run
starts when its own task has merged.

- **s1** (explore task): `explore/0010_instrument_sorting.py`. (a) The
  first stage by instrument (total, Pix in B and C, non-Pix), each in
  ln(1 + reais per inhabitant), as "any payment", and by Poisson in reais
  (premium in percent); pooled, by cycle, C minus A (total, non-Pix) and C
  minus B (Pix). (b) The level decomposition in reais per inhabitant (the
  share of the premium paid as Pix). (c) Sorting: controls, a split by
  `party_held_mayor`, a donut without |margin| below 0.5%, and windows of
  2.5%, 5%, 7.5% and 10%. (d) The placebo on `amend_pre_log_pc`.
- **s2** (run of s1). A fork point.
- **s3** (explore task): `explore/0010_vote_mechanisms.py`. The party
  level: `d_party`, `d_inc` (the party's panel deputies, 0 if they did not
  run) and `d_state`, with state × party × cycle fixed effects, and their
  differences. The deputy level: the main run's reduced form with a deputy
  who did not run counted as 0. A descriptive dose regression among allied
  towns. The t0 placebo.
- **s4** (run of s3). A fork point.
- **s5** (explore task): `explore/0010_payment_timing.py`. Monthly jumps in
  reais per inhabitant from January m-1 to September t1, half-year means,
  the cumulative gap, and the lead ratio.
- **s6** (run of s5). A fork point.

Common design (Gabriel's brief): exploration half only; h read by code
from gate record 44484340952 (7.5%), 5% as a check; the linear estimator
of `explore/0010_amendments_main.py` loaded with importlib (local linear
in the margin, deputy-by-cycle fixed effects, errors clustered by
municipality, randomisation inference re-flipping races, 2,000 draws);
effects in percent by pyfixest `fepois` on reais with the same slopes and
fixed effects, offset ln(`population_m`), clustered by municipality,
reported as exp(b) − 1; cycles A, B, C. Figures through `terrain.style`
and `save_png` into the run's `figures/` (at most 8, each under 400 KB,
binned means, never raw scatters), each marked "exploration half, not a
finding".

**Declared estimates** (five; each summary gives Holm-adjusted p-values
across the ones it holds; everything else is descriptive):

- s1: the first stage with controls; the Poisson total premium, C minus
  A; the Poisson premium of Pix minus non-Pix, cycles B and C pooled.
- s3: `d_party` pooled; `d_party` − `d_state` pooled.

**Reading of s3, declared before the run.** If `d_state` is about as
large as `d_party`, the allied mayor lifts the whole ticket, which points
to the mayor's campaigning. If `d_party` is near 0 while `d_inc` is
positive, votes are reshuffled toward sitting deputies. Either way,
compare with how the money moved across cycles.

## Kill rules and why

All stated by Gabriel (brief, 2026-11-22), so all are confirmed.

s2 (`on_kill: stop`):

- **k1** `first_stage.f_cluster < 10`: with controls for sorting, the
  first stage's municipality-clustered F is below 10 (the library's
  `first_stage_strength`).
- **k2** `placebo.pre_fail == 1`: the pre-window placebo
  (`amend_pre_log_pc`) is larger than half the post-window effect **and**
  its randomisation p is below 0.05. Half a p-value rule: a valid design
  meets it at most 5% of the time, and less, because the size condition
  must also hold.
- **k3** `estimates.finite != true`.

s4 (`on_kill: skip_dependents`):

- **k1** `placebo.t0_fail == 1`: for `party_share_t0` or
  `state_party_share_t0`, |b| is above 10% of its mean **and** its
  randomisation p is below 0.05. Two tests, so a valid design meets it at
  most about 10% of the time (less, with the size condition).
- **k2** `estimates.finite != true`.

s6 (`on_kill: skip_dependents`):

- **k1** `placebo.lead_ratio > 0.5`: the library's `pretrend_ratio`, on
  the pooled monthly `total` coefficients (pre: January m-1 to September
  m; post: January m+1 to September t1).
- **k2** `estimates.finite != true`.

The two placebo rules combine a size and a p-value condition, so the
card counts them as fields equal to 1, not as p-value rules.

**A stop at s2 ends the whole campaign.** `on_kill: stop` is Gabriel's
choice for s2: if the first stage does not survive the sorting controls or
its placebo, the vote and timing steps do not start (or, if a task is in
flight, nothing new starts after it).

## Budget and why

Stated by Gabriel (brief, 2026-11-22):

- `max_tasks` 3: exactly the three task steps.
- `max_explore_runs` 3: exactly the three run steps.
- `max_pipeline_runs` 0: no new data and no build.
- `max_model_jobs` 36: three tasks at about 5 jobs each leave about 21 for
  fix rounds.
- `end_by` 2026-12-10: 18 days.

The forks' own budget is also his: `max_tasks` 3, `max_explore_runs` 3,
`max_pipeline_runs` 0, `max_model_jobs` 24.

When a budget runs out, nothing new starts and the tick files the
close-out.

## New data

None. Inputs, all in the bucket: `amendments_panel` v3 (manifest of
2026-11-20, `data/derived/amendments_panel/dd3d052b58494477/`, built in
campaign 0012, run 44767467382) and `amendments_monthly`
(`data/derived/amendments_monthly/176dd6e75066c209/`, run 44766231397).
Campaign 0011 read the v2 panel; v3 adds the party-share columns.

## Variants in scope for forks (guidance for the ideation job)

Not binding; the envelope and decision 0015 decide what may run.

- **spec**: alignment by the mayor's coalition or federation instead of
  the deputy's own party (Gabriel's brief).

No sample forks (Gabriel's brief). No new datasets (`max_new_datasets`
0). Splitting non-Pix money into health and other is campaign 0015's
work, not a fork here.

## What would change the plan

- s2 killed: the first stage does not survive sorting controls or its
  placebo, and the campaign stops. The report should then say which rule
  was met and that s3-s6 did not run for that reason.
- Poisson fits can drop deputies with no payments at all; the rows used
  are reported. If cycle A's Poisson fit drops most rows, C minus A in
  percent rests on few deputies.
- t1 party shares follow mergers and federations, so in some races the
  two finalist parties are one party at t1 (s3 counts them). Their
  `d_party` cancels, which pulls the party-level estimate toward 0.
- s5's cycle C ends in September 2026; CGU can still revise late
  payments, so the last months of C are the least settled.
- s2, s4 and s6 reuse campaign 0011's exploration half and window. A
  result here is a further look at the same data.

## Provenance

Stated by Gabriel (brief, 2026-11-22). His brief says: "Use this brief as
my answers in the campaign-design skill. Decide anything it leaves open
yourself and list it under 'Decided by Claude Code' in the PR. Every
threshold and kill rule below is set and confirmed by me." From it:

- campaign 0013, slug `amendments-mechanisms`, idea 0010, set to
  `exploring` with one dated Status line; no new data and no build;
- the context (campaign 0011's results, the CGU totals, the Pix shares,
  the sorting hint, Ventura 2021) and the account of when each question
  was set, including why H5 is not run;
- the common design (window from record 44484340952, 5% check, the main
  run's estimator by importlib, pyfixest `fepois` with offset, cycles,
  figure rules);
- the six steps, their contents, file names and `after` (three
  independent pairs), `self_repair: true`;
- every kill rule above and each step's `on_kill`, so all are confirmed;
- the five declared estimates with Holm adjustment within each summary;
- the s3 reading, declared before the run;
- the forks envelope (3 forks, 2 per point, fork points s2, s4 and s6, on
  killed and survived, types transform, spec, measure and question, 1
  question fork, 0 new datasets, 3 steps per fork), its budget, no sample
  forks, the non-binding coalition variant, and that splitting non-Pix
  money is campaign 0015's;
- the budget and `end_by`; opening the PR as `active`.

Decided by Claude Code, not asked (Gabriel approves them with the card):

- **Window by record, not re-derived.** Each script reads
  `window.h_pct` from `research/explore-runs/0010/44484340952.json` and
  raises unless it is 7.5. Unlike the main run, it does not re-run decision
  0008's rule on the v3 panel.
- **Intervals.** 95% (b ± 1.96 × se) everywhere; the main run's 97.5%
  intervals belonged to its two-outcome test.
- **p-values for Holm.** Linear declared estimates use the randomisation
  p; Poisson declared estimates use pyfixest's clustered two-sided p.
- **By-cycle linear fits.** `by_cycle_fit` for A, B and C, and in s1 a
  generalisation to any list of cycles (Pix has only B and C), tested to
  match it. Clustered errors only, no randomisation p, as in the main run.
- **Poisson differences.** C minus A, C minus B and Pix minus non-Pix are
  each one interacted (or stacked, with deputy × type fixed effects) fit,
  so each has its own clustered error; their point estimates equal the
  differences of the separate fits.
- **Non-Pix.** `amend_post_total` − `amend_post_pix`, floored at 0, with
  the floored rows counted; Pix is 0 in cycle A, so A is left out of every
  Pix fit.
- **Sorting variants.** The split, the donut and the four windows all use
  the controls model (the split drops `party_held_mayor` from the
  controls); controls enter as extra regressors demeaned within deputy,
  with randomisation by the same re-flips, controls held fixed; rows with
  a null control are dropped and counted.
- **s2's placebo `b_post`** is the pooled total `log_pc` estimate without
  controls, the same model as the placebo.
- **s3's collapse.** State × party × cycle fixed effects are put in the
  `deputy` column so the main run's functions apply unchanged. `d_inc`
  sums the party's panel deputies in the town. The descriptive dose
  regression uses allied rows within h with `ran_t1` true.
- **s5.** Months j = 0..44 (October of t1 dropped); October-December of m
  are neither pre nor post; monthly, half-year and cumulative fits have
  clustered errors only, no randomisation inference (several hundred
  fits; the kill rule reads coefficients only); the lead ratio uses the
  pooled `total` coefficients. The Supreme Court marks are August 2024
  and December 2024, the months the brief names.
- **Figures.** s1: three (binned money by cycle, coefficients by cycle and
  instrument, the Poisson premium); s3: two; s5: two. Bins 0.5 percentage
  points wide.
- **Seed.** The main run's draws (seed 20261115), drawn once per script
  over that script's races.

Probe: not recommended. Every input is in the bucket and was read by
campaign 0011's runs or built and recorded in campaign 0012.

Closest paper: not asked. The brief asks for `active` and for questions
only on merges, loosened checks or large data fixes.

Builds dry-run: none needed (no `pipeline_run` step). `self_repair: true`
has nothing to repair: it applies only to data-pipeline steps.

Not looked at: no new outcome. Only the numbers Gabriel's brief states,
the window and pre-window fields of record 44484340952, row counts from
the two manifests, and campaign 0012's report.
