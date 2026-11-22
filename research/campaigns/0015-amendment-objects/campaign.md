---
id: "0015"
title: "What allied towns get: amendment money by instrument and by the declared use of Pix"
status: active
idea: "0013"
owner: gabrielsgaspar
created: 2026-11-22
end_by: 2026-12-12
budget:
  max_tasks: 2
  max_explore_runs: 2
  max_pipeline_runs: 2
  max_model_jobs: 30
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
  fork_points: [s3, s5]
  budget:
    max_tasks: 3
    max_explore_runs: 3
    max_pipeline_runs: 0
    max_model_jobs: 24
datasets:
  - name: amendments_objects
    source: "built from tse_general, cgu_amendments, tse_results, tse_candidates, municipalities and camara_deputies, with data/reference/pix_object_labels.yaml; the amendments_panel rows with payments by instrument and Pix by work-plan class; split by half"
    licence: "public, as its sources"
    max_size_gb: 0.1
    identifiers: none
steps:
  # Data: the objects table (owner PR #470, dry-run 2026-11-22)
  - id: s1
    kind: pipeline_run
    stage: build
    target: amendments_objects
    dataset: amendments_objects
    after: []
  # Gate: the measure's quality, plan coverage, the Pix first stage and its placebo
  - id: s2
    kind: task
    type: explore
    draft: drafts/s2.md
    allowed_paths:
      - explore/0013_objects_gate.py
      - tests/test_explore_objects_gate.py
    after: []
  - id: s3
    kind: explore_run
    script: 0013_objects_gate
    after: [s1, s2]
    kill_rules:
      - id: k1
        says: "Cohen's kappa on groups between the two labelling passes is below 0.70"
        field: measure.kappa_groups
        op: "<"
        value: 0.70
        confirmed: true
      - id: k2
        says: "The classifier's cross-validated macro-F1 on groups is below 0.80"
        field: measure.cv_macro_f1_groups
        op: "<"
        value: 0.80
        confirmed: true
      - id: k3
        says: "Less than 85% of exploration-half post-window Pix value has a matched work plan, in cycle B or C (the smaller of the two)"
        field: measure.pix_value_with_plan
        op: "<"
        value: 0.85
        confirmed: true
      - id: k4
        says: "The Pix first stage (ln(1 + reais per inhabitant), post window, cycles B and C pooled, at h) has a municipality-clustered F below 10"
        field: first_stage.f_cluster
        op: "<"
        value: 10
        confirmed: true
      - id: k5
        says: "In cycle C the pre-window Pix jump is more than half the post-window one and its randomisation p is below 0.05"
        field: placebo.pre_fail
        op: "=="
        value: 1
        confirmed: true
      - id: k6
        says: "Some estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Main: instruments, Pix groups and the composition
  - id: s4
    kind: task
    type: explore
    draft: drafts/s4.md
    allowed_paths:
      - explore/0013_objects_main.py
      - tests/test_explore_objects_main.py
    after: [s3]
  - id: s5
    kind: explore_run
    script: 0013_objects_main
    after: [s4]
    kill_rules:
      - id: k1
        says: "None of the three Pix groups (visible, services, fungible) has a municipality-clustered F of at least 10"
        field: first_stage.n_strong
        op: "<"
        value: 1
        confirmed: true
      - id: k2
        says: "Some estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0015: What allied towns get: amendment money by instrument and by the declared use of Pix

## Question

Idea 0013 (`research/ideas/0013-what-allies-get.md`). Campaign 0011 found,
on the exploration half, that a federal deputy sends more individual
amendment money to a town where the deputy's party narrowly won the
mayoralty (idea 0010; gate `research/explore-runs/0010/44484340952.md`,
main run `research/explore-runs/0010/44538371996.md`). This campaign asks
what that money is:

1. **Which instrument carries the premium?** Pix (cash to the town hall),
   health (budget function Saúde) or other tied transfers (agreements for
   a stated object).
2. **What does Pix money declare it buys?** Each Pix payment is split
   over the town's work plans for that amendment, each plan classed by a
   plain classifier trained on model labels (decision 0018). Visible
   (works, machines, events), services (health, education and social) or
   fungible (running costs, vague, mixed, no plan)?

Two readings, declared before any estimate (idea 0013): credit-claiming
(the premium is in visible things) and broker payment (it is in fungible
money).

The classes are what town halls declared, many of them after the Supreme
Court ordered plans to be filed (ADPF 854): the measure is **declared
use**, not spending. Exploration half only (decision 0011). This is the
same exploration half and window campaign 0011 analysed, so a result here
is a further look at the same data, not an independent test.

## Already known

Repository scan (`novelty_scan.py`, 2026-11-22: Pix, special transfers,
work plans, pork barrel) and one web search the same day. Campaigns
0009-0013 checked the amendments, alignment and Pix literature
(`research/campaigns/0013-amendments-mechanisms/campaign.md`, "Already
known"); not repeated here.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Allied towns get more amendment money (this design) | tried on this exploration half | `research/explore-runs/0010/44538371996.md`; (web, unverified) Baião and Couto 2017 for an earlier period |
| Pix against non-Pix money for allied towns | being tried | campaign 0013, s1 (`research/campaigns/0013-amendments-mechanisms/`) |
| Non-Pix money split into health and tied | new | campaign 0013 left it to this campaign ("Variants in scope for forks") |
| Pix by area, whole country | explored, descriptive | Cavalcanti (2026), "Para onde vai o Pix?", Ipea, as Gabriel's brief cites it (web search 2026-11-22 did not find the title; unverified); Transparência Brasil, "Emendas Pix" 2023 and 2024 (web, unverified) |
| Pix by declared use for allied towns | new | nothing in the repository or found on the web |
| Model-labelled text measures in this repository | new | decision 0018 (PR #470) |

What this campaign adds: the premium split by instrument (Pix, health,
tied) and, within Pix, by the declared use of the plans, in the same close
races.

## Read before this runs

- **Cavalcanti (2026)**, "Para onde vai o Pix?", Ipea (closest: Pix by
  area for the whole country; cited by Gabriel; unverified). Gabriel: not
  stated. His brief asks for `active` and for questions only on merges,
  loosened checks or large data fixes.
- **Baião and Couto (2017)**, "A eficácia do pork barrel", *Opinião
  Pública* 23(3) (web, unverified). Gabriel (2026-11-15, for campaign
  0009): "Not yet: active anyway".
- **Ventura (2021)**, *Electoral Studies* (cited by Gabriel; unverified).
  Gabriel: not stated.

## Steps and why

- **s1** (data): builds `amendments_objects` (owner PR #470). Its rows are
  exactly `amendments_panel`'s, with each window's payments by instrument
  and Pix by plan class, group, specificity and filing, plus
  `measurement.parquet`. It was dry-run on the real files on 2026-11-22
  and passed. `after: []`, so it runs while s2 is built.
- **s2** (explore task): `explore/0013_objects_gate.py`. The measure's
  quality and plan coverage, read from `measurement.parquet`; the Pix
  first stage (B and C pooled); the cycle C pre-window placebo. No class
  estimate.
- **s3** (run of s2, after s1 and s2): the gate. Every rule stops the
  campaign. A fork point.
- **s4** (explore task, after s3): `explore/0013_objects_main.py`. (a)
  Instruments, (b) Pix groups, (c) the composition, and the three
  declared estimates. It is written only once the gate has passed.
- **s5** (run of s4): the main run. A fork point.

Common design (Gabriel's brief, idea 0010's design):

- the exploration half only;
- h = 7.5%, read by code from gate record 44484340952, with 5% as a
  check;
- the linear estimator of `explore/0010_amendments_main.py`, loaded with
  importlib: local linear in the margin, deputy-by-cycle fixed effects,
  errors clustered by municipality, randomisation inference re-flipping
  races, 2,000 draws;
- effects in percent from pyfixest `fepois` on reais, with offset
  ln(`population_m`);
- figures through `terrain.style` and `save_png` into the run's
  `figures/`, each under 400 KB, binned means only, each marked
  "exploration half, not a finding".

**Declared estimates** (s4; three, Holm-adjusted together): the Poisson
premium of Pix minus tied (B and C); visible minus fungible within Pix (B
and C); health, C minus A. Everything else is descriptive.

**Non-binding variants** for the fork ideation job (Gabriel's brief):
- specificity 0 against 2 as the measure;
- plans filed before against after the Supreme Court's order;
- each class on its own.

`amendments_objects` already carries the columns for all three
(`obj_<w>_pix_spec0/1/2`, `_legacy`/`_regular`, one per class).

## Kill rules and why

All stated by Gabriel (brief, 2026-11-22), so all are confirmed.

s3 (`on_kill: stop`):

- **k1** `measure.kappa_groups < 0.70`: the two labelling passes must
  agree on groups (decision 0018, point 5). The labels file holds 0.9501
  over 1,000 doubly labelled texts.
- **k2** `measure.cv_macro_f1_groups < 0.80`: the classifier must learn
  the groups. **Thin margin**: the dry run of 2026-11-22 gave 0.8019. The
  build is deterministic (same labels, code and scikit-learn version), so
  s3 should read the same number, but it passes by 0.002. With the
  brief's 3,000 labels it was 0.788. Gabriel asked for 3,000 more
  (PR #470).
- **k3** `measure.pix_value_with_plan < 0.85`: weighted by reais, the
  smaller of cycles B and C, exploration-half panel rows, post window.
  Money without a plan counts as fungible, so a low share would make the
  fungible group mostly "no plan".
- **k4** `first_stage.f_cluster < 10`: the Pix first stage, B and C
  pooled (the library's `first_stage_strength`).
- **k5** `placebo.pre_fail == 1`: in cycle C, |pre-window Pix jump| is
  above half |post-window jump| **and** its randomisation p is below
  0.05. Half a p-value rule: a valid design meets it at most 5% of the
  time, less with the size condition.
- **k6** `estimates.finite != true`.

s5 (`on_kill: stop`):

- **k1** `first_stage.n_strong < 1`: none of the three Pix groups has a
  clustered F of at least 10.
- **k2** `estimates.finite != true`.

## Budget and why

Stated by Gabriel (brief, 2026-11-22):

- `max_tasks` 2: the two task steps.
- `max_explore_runs` 2: the two runs.
- `max_pipeline_runs` 2: the build, and one retry or repair.
- `max_model_jobs` 30: two tasks at about 5 jobs each, a repair if
  needed, and fix rounds.
- `end_by` 2026-12-12: 20 days.

The forks' own budget is also his: `max_tasks` 3, `max_explore_runs` 3,
`max_pipeline_runs` 0, `max_model_jobs` 24. When a budget runs out,
nothing new starts and the tick files the close-out.

## New data

`amendments_objects` (catalog entry, contract
`data/contracts/amendments_objects.md`, owner PR #470). It is built from
data already in the bucket, plus the committed labels
(`data/reference/pix_object_labels.yaml`: 6,000 keys, no text). It holds
no identifier. Expected size under 1 MB (dry run: about 530 KB in all).
It has no outside source, so it needs no fallback publisher. The
`cgu_amendments` zip it reads was fetched by a runner before
(`data/manifests/acquire/cgu_amendments.json`).

## What would change the plan

- s3 killed: the campaign stops. The report should say which rule was
  met. k2 is the one most likely to be met by a hair. If it is, more
  labels (a third sample) would be an owner PR, not a fork.
- If the fungible group is mostly "no plan", its premium says little
  about declared use. s4 reports `pix_no_plan` on its own.
- Plans filed after the Supreme Court's order (Legado) may describe money
  already spent. The Legado share by year is reported, and "before
  against after the order" is a fork variant.
- Poisson fits drop deputies with no payment of an instrument. The rows
  used are reported. Health and tied money are large in every cycle, but
  Pix groups in cycle B are small.
- s3 and s5 reuse campaign 0011's exploration half and window, and
  campaign 0013 asks Pix against non-Pix on the same rows. A result here
  is a further look at the same data.

## Provenance

Stated by Gabriel (brief, 2026-11-22). His brief says: "Use this brief as
my answers in the campaign-design skill. Decide anything it leaves open
yourself and list it under 'Decided by Claude Code' in the PR. Every
threshold and kill rule below is set and confirmed by me." From it:

- campaign 0015, slug `amendment-objects`, idea 0013 with its file name,
  what it cites and the two readings, and that the measure is "declared
  use";
- the common design (idea 0010's; window from record 44484340952, 5%
  check, the main run's estimator by importlib, pyfixest `fepois` with
  offset, figure rules);
- the five steps, their contents, file names and `self_repair: true`;
- every kill rule above and each step's `on_kill`, so all are confirmed;
- the three declared estimates with Holm adjustment;
- the forks envelope (3 forks, 2 per point, fork points s3 and s5, on
  killed and survived, types transform, spec, measure and question, 1
  question fork, 0 new datasets, 3 steps per fork), its budget, and the
  three non-binding variants;
- the budget and `end_by`; opening the PR as `active`;
- 6,000 labels instead of the brief's 3,000: Gabriel, 2026-11-22 ("label
  3,000 more"), after the 3,000-label score of 0.788.

Decided by Claude Code, not asked (Gabriel approves them with the card):
see the pull request's list. In short:

- **Order.** s2 has `after: []`, so it is built while s1 runs. s4 is
  `after: [s3]`, so the main script is written only if the gate passes.
- **Declared estimates are Poisson.** All three, so they read as percent
  premiums comparable across instruments and cycles. Their p-values are
  pyfixest's clustered ones.
- **The Pix first stage and n_strong** use the main run's `full_fit` on
  ln(1 + reais per inhabitant), post window, cycles B and C pooled; F =
  (b / se)².
- **The placebo** is in cycle C only, as the brief says. Both jumps use
  `full_fit` on cycle C's rows, with draws over cycle C's races.
- **A consistency check**: s2 compares `obj_<w>_pix` with the panel's
  `amend_<w>_pix` and raises if any row differs by more than R$1.

Probe: not recommended. The build was dry-run on the real files, and the
gate is cheap.

Closest paper: not asked. The brief asks for `active` and for questions
only on merges, loosened checks or large data fixes.

Builds dry-run: `amendments_objects`, on 2026-11-22. Command 2 was run by
Gabriel twice, with 3,000 and then 6,000 labels. Both passed. The second
run's notes, on the code and labels merged in PR #470:
- per cycle, exploration-half rows A 16,533, B 12,830, C 17,067 (panel
  rows 33,079, 25,667, 34,026);
- Pix payment rows matched to a plan, by year, from 91% (2026) to 98%
  (2022); the build's value check (at least 80% per year) passed;
- kappa on groups 0.9501, cross-validated macro-F1 on groups 0.8019.

Not looked at: no outcome of the new measure, and no class or group share.
The dry run printed only notes, row counts and the measure's quality.
