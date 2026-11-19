---
id: "0011"
title: "What do budget amendments buy at the ballot box? The municipality's share of the deputy's money, and log reais per inhabitant"
status: active
idea: "0010"
owner: gabrielsgaspar
created: 2026-11-19
end_by: 2026-12-04
budget:
  max_tasks: 3
  max_explore_runs: 2
  max_pipeline_runs: 3
  max_model_jobs: 30
referee_not_applicable_ok: [R5]
self_repair: true
forks:
  max_forks: 3
  per_point: 3
  max_new_datasets: 1
  max_steps_per_fork: 4
  types: [transform, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: [s4, s6]
  budget:
    max_tasks: 6
    max_explore_runs: 6
    max_pipeline_runs: 3
    max_model_jobs: 34
datasets:
  - name: camara_deputies
    source: "Câmara dos Deputados open data (dadosabertos.camara.leg.br), arquivos/deputados/csv/deputados.csv: every federal deputy since 1826; raw file as published"
    licence: "Câmara dos Deputados open data portal; licence not stated in the file; accepted by Gabriel on 2026-11-18 for research use (owner fix PR #421)"
    max_size_gb: 0.1
    identifiers: none
  - name: amendments_panel
    source: "built from tse_general, cgu_amendments, camara_deputies, tse_results, tse_candidates, municipalities and ibge_population_annual; one row per deputy, municipality and cycle; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
steps:
  # Data: the Chamber's list (never fetched by a runner before), then the panel v2
  - id: s1
    kind: pipeline_run
    stage: acquire
    target: camara_deputies
    dataset: camara_deputies
    after: []
  - id: s2
    kind: pipeline_run
    stage: build
    target: amendments_panel
    dataset: amendments_panel
    after: [s1]
  # Gate: window, counts, power and placebos for share and log_pc, the link by money; no post-election outcome
  - id: s3
    kind: task
    type: explore
    draft: drafts/s3.md
    allowed_paths:
      - explore/0010_amendments_gate.py
      - tests/test_explore_amendments_share_gate.py
    after: []
  - id: s4
    kind: explore_run
    script: 0010_amendments_gate
    after: [s2, s3]
    kill_rules:
      - id: k1
        says: "No mayoral window, not even 0.5%, passes decision 0008's balance rule"
        field: window.found
        op: "=="
        value: 0
        confirmed: true
      - id: k2
        says: "Fewer than 200 close mayoral races (cycles A-C pooled, with an eligible deputy) within the chosen window"
        field: counts.races_h
        op: "<"
        value: 200
        confirmed: true
      - id: k3
        says: "Neither outcome is powered: share MDE above 25% of its pre-window mean and log_pc MDE above 0.223 (80% power, alpha 0.025)"
        field: power.n_powered
        op: "<"
        value: 1
        confirmed: true
      - id: k4
        says: "Some powered outcome's pre-window placebo is above its threshold (share: |b| above 25% of its mean; log_pc: |b| above 0.223)"
        field: placebo.powered_failing
        op: ">"
        value: 0
        confirmed: true
      - id: k5
        says: "The placebo slope on the deputy's vote share at the previous general election exceeds 25% of its mean, in absolute value"
        field: placebo.vote_share_abs
        op: ">"
        value: 0.25
        confirmed: true
      - id: k6
        says: "In some cycle, deputies linked to authors get less than 90% of the window money of current-legislature authors, senators left out"
        field: link.money_share
        op: "<"
        value: 0.90
        confirmed: true
    on_kill: stop
  # Main run: first stage for the powered outcomes, and the reduced form
  - id: s5
    kind: task
    type: explore
    draft: drafts/s5.md
    allowed_paths:
      - explore/0010_amendments_main.py
      - tests/test_explore_amendments_share_main.py
    after: [s4]
  - id: s6
    kind: explore_run
    script: 0010_amendments_main
    after: [s5]
    kill_rules:
      - id: k1
        says: "No powered outcome has a municipality-clustered first-stage F statistic of at least 10"
        field: first_stage.n_strong
        op: "<"
        value: 1
        confirmed: true
      - id: k2
        says: "Some first-stage or reduced-form estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0011: What do budget amendments buy at the ballot box? Share of the deputy's money, and log reais per inhabitant

## Question

The question of idea 0009, with new measures of the money. When a federal
deputy's party narrowly wins a mayoralty, does the deputy send that
municipality a larger share of the deputy's individual amendment money
(emendas), or more reais per inhabitant in logs, and does it turn into
votes for the deputy at the next general election, across cycles A (mayor
2016), B (2020) and C (2024)? Idea 0010
(`research/ideas/0010-amendments-share-of-quota.md`).

**The two outcomes were chosen after campaign 0010's power gate failed on
per-capita reais.** Idea 0009 died in campaign 0010
(`research/campaigns/0010-amendments-second-attempt/report.md`): its gate
run (`research/explore-runs/0009/44394848609.md`) had a first-stage MDE of
0.526 of the mean (limit 0.25, k3) and an author link of 0.569 in cycle C
(limit 0.90, k6). Rules k1, k2, k4 and k5 passed. Gabriel then chose the
share and log outcomes and rebuilt the link (owner fix, PR #421). Every
threshold is unchanged: 25% of the mean, ln(1.25) = 0.223 for the log, 200
races, F ≥ 10, 90% for the link, decision 0008's window rule. Same design,
cycles A-C, deputy-by-cycle fixed effects, clustering and randomisation
inference as idea 0009. Exploration half only (decision 0011's national
split). Because the outcomes came after a failed gate, the report must
count this as a further analysis of the same question.

## Already known

Not checked again. Campaign 0009's novelty check of 2026-11-15
(`research/campaigns/0009-amendments-ballot-box/campaign.md`, "Already
known"), copied in campaign 0010, covers the same question. Two lines are
added from campaign 0010:

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Mayor's party in close races → deputies' amendments and votes | explored (one earlier period) | (web, unverified) Baião and Couto, "A eficácia do pork barrel", *Opinião Pública* 23(3) 2017, 714-753, doi:10.1590/1807-01912017233714 |
| Amendments and deputies' local votes | explored | (web, unverified) Firpo, Ponczek and Sanfelice, *J. Dev. Econ.* 116 (2015) 186-198: an RD on close *deputy* races |
| Mayors' party and deputies' votes, without money | partly explored | (web, unverified) Avelino, Biderman and Barone, *Dados* (2012) |
| Close mayoral races and federal transfers | explored (the president's coalition) | (web, unverified) Brollo and Nannicini, *APSR* 106(4) 2012 |
| Pix and votes, 2022 to 2026 | descriptive only | (web, unverified) FGV study reported in October 2026, press only |
| Representatives favouring aligned municipalities | explored (Norway) | `fivaLocalFavoritismAtlarge2016` |
| Per-capita reais in this design, 2016-2024 | tried, underpowered | `research/explore-runs/0009/44394848609.md` (MDE 0.526 of the mean) |
| Share of the deputy's money and log reais per inhabitant, in this design | new | no earlier run in this repository |

What this campaign adds: the first test in this repository of the two new
outcomes, with the link rebuilt.

## Read before this runs

- **Baião and Couto (2017)**, "A eficácia do pork barrel", *Opinião Pública*
  23(3), doi:10.1590/1807-01912017233714 (closest; web, unverified).
  Gabriel (2026-11-15): "Not yet: active anyway".
- **Firpo, Ponczek and Sanfelice (2015)**, *J. Dev. Econ.* 116, 186-198
  (web, unverified). Gabriel: not stated.
- **Brollo and Nannicini (2012)**, *APSR* 106(4) (web, unverified).
  Gabriel: not stated.

## Steps and why

- **s1** (acquire run): the Chamber's list of deputies, `camara_deputies`
  (`pipeline/acquire/camara_deputies.py`, merged in PR #421). The panel v2
  needs it for the parliamentary names. No GitHub runner has fetched from
  this host before, so it comes first (cheapest failure first).
- **s2** (build run): the panel v2 (`pipeline/build/amendments_panel.py`,
  PR #421), with the two new outcomes and the link by money. It ran on the
  real files without uploading (PR #421): passed, money_share 0.915,
  0.926 and 0.932 in cycles A, B and C. It writes a new output path, so the
  0009 panel in the bucket is not overwritten.
- **s3** (explore task): the gate script, `explore/0010_amendments_gate.py`,
  built from `explore/0009_amendments_gate.py`. It has no data dependency,
  so it is built while s1 and s2 run.
- **s4** (gate run): window, counts, the power of each outcome, the
  placebos and the link by money. It reads no post-election outcome. Any
  rule met stops the campaign. A fork point.
- **s5** (explore task): the main-run script,
  `explore/0010_amendments_main.py`, from campaign 0009's `drafts/s8.md`.
  It is written only after the gate survives. It estimates only the
  outcomes that s4's run record marks as powered, read from that record by
  code.
- **s6** (main run): first stage of each powered outcome and the reduced
  form, each at alpha 0.025; by cycle, C minus A, and votes per real as an
  upper bound. A fork point.

## Kill rules and why

All stated by Gabriel (brief, 2026-11-18). Thresholds are idea 0009's,
unchanged.

s4 (the gate):

- **k1** `window.found == 0` and **k2** `counts.races_h < 200`: as in 0009.
- **k3** `power.n_powered < 1`: the number of outcomes whose MDE at 80%
  power and alpha 0.025 passes its limit (share: at most 25% of its
  pre-window mean; log_pc: at most 0.223 log points, that is ln 1.25).
  Alpha is 0.025 because two outcomes are tested.
- **k4** `placebo.powered_failing > 0`: the number of powered outcomes
  whose pre-window placebo is above its limit (share: |b| above 25% of the
  mean; log_pc: |b| above 0.223). An unpowered outcome cannot fail it: it
  is never estimated in s6.
- **k5** `placebo.vote_share_abs > 0.25`: as in 0009.
- **k6** `link.money_share < 0.90`: the smallest money share of the three
  cycles. It replaces 0009's head count (`link.author_share`), which is
  still reported.

Size rules, not p-value rules, so the card's false-stop sum is 0.

s6:

- **k1** `first_stage.n_strong < 1`: the number of powered outcomes with a
  clustered first-stage F of at least 10 (library rule
  `first_stage_strength`, per outcome).
- **k2** `estimates.finite != true`: library rule `finite`.

Both runs use `on_kill: stop`. A kill at a fork point does not stop the
forks at that point.

## Budget and why

Stated by Gabriel (brief, 2026-11-18): `max_tasks` 3, `max_explore_runs`
2, `max_pipeline_runs` 3, `max_model_jobs` 30, `end_by` 2026-12-04 (15
days). Two tasks at about 5 model jobs each leave room for fix rounds; the
third task and the third pipeline run are spares.

The forks' own budget is Claude's proposal (Gabriel's brief asked for
one): `max_tasks` 6, `max_explore_runs` 6, `max_pipeline_runs` 3,
`max_model_jobs` 34. Three forks of about two tasks and two runs each (a
gate variant needs its own gate run and main run), about 10 model jobs
each, plus one ideation job at each of the two fork points, and 2 spare.
Three pipeline runs cover one new dataset's acquire and a rebuild.

When a budget runs out, nothing new starts and the tick files the close-out.

## New data

- **`camara_deputies`** (acquire, s1): the Chamber of Deputies' bulk file
  `deputados.csv`, about 1.4 MB, catalogued and contracted in PR #421
  (`data/contracts/camara_deputies.md`). Licence not stated in the file;
  Gabriel accepted it for research use on 2026-11-18. The raw file, stored
  as published, holds names, birth dates and a `cpf` column, which was
  empty for every deputy of legislatures 55-57 on 2026-11-18. As with
  `tse_general`'s raw zips, nothing is written from those columns: the
  build reads only `nome`, `nomeCivil` and the two legislature columns, in
  memory. Fallback: the Chamber's API (`/api/v2/deputados`, same host; it
  answered 504 on 2026-11-18), or Base dos Dados' Chamber tables (not
  checked; web, unverified). If s1 fails, the step blocks and asks
  Gabriel.
- **`amendments_panel`** (build, s2): listed because s2 builds it (the
  validator requires it). The 0009 entry, with `camara_deputies` added to
  its sources. New output path.

Existing inputs: `tse_general`, `cgu_amendments`, `tse_results`,
`tse_candidates`, `municipalities`, `ibge_population_annual`.

## Variants in scope for forks (guidance for the ideation job)

Not binding. Gabriel's brief (2026-11-18) lists these; the envelope and
decision 0015 still decide what may run.

1. **measure**: the extensive margin, any payment above 0 in the window.
2. **spec**: alignment by the mayor's coalition or federation instead of
   the deputy's own party.
3. **measure**: Pix amendments only, cycles B and C.
4. **question**: the same close races, with the vote change of the mayor's
   party's state deputies as the outcome, as a brokerage benchmark.

No sample forks (Gabriel's brief).

## What would change the plan

- s1 fails: the Chamber's host has never served a runner. No repair can be
  filed (see Provenance), so the step blocks and asks Gabriel.
- s2 fails: the same. The fix is an owner fix.
- Cycle A's pre-window share is undefined on 13,841 rows (both halves,
  against 16,533 exploration-half rows in the cycle; the deputies first elected in 2014 have almost no money paid by
  2016-09). Cycle A's share placebo and power rest mostly on re-elected
  deputies. Read the report with that in mind.
- `money_share` was 0.915-0.932 in the dry run, close to the 0.90 limit.
  CGU's unidentified author ("S/I", about 25% of cycle A's window money)
  is outside its denominator.
- A strong first stage with a reduced form near zero, or a votes-per-real
  ratio larger than any campaign could produce: the allied mayor's own
  campaigning. The ratio is an upper bound, as declared.

## Provenance

Stated by Gabriel (brief, 2026-11-18): idea 0010 as a new idea citing idea
0009 and campaign 0010, and stating that the outcomes came after the failed
gate with every threshold unchanged; the same question, design, cycles,
fixed effects, window rule, clustering and randomisation inference;
exploration half only; the steps (the build with an acquire first, the
gate task from `explore/0009_amendments_gate.py`, the gate run, the main
task from 0009's `drafts/s8.md`, the main run); the two outcomes and their
limits (share: MDE at most 25% of the pre-window mean; log_pc: at most
0.223), alpha 0.025; reading the powered outcomes from s4's run record;
every kill rule of s4 (k1-k6) and s6 (k1-k2), so all are confirmed;
`on_kill: stop`; `self_repair: true`; the forks envelope (3 forks, 3 per
point, types transform, spec, measure and question, 1 question fork, 1 new
dataset, 4 steps per fork, on killed and survived, fork points the two
runs, no sample forks) and the four non-binding variants; the budget and
`end_by`; opening the PR as `active`.

Decided by Claude, not asked (Gabriel approves them with the card):

- Step numbers: the acquire is s1, so the brief's s1-s5 are s2-s6 here and
  the fork points are s4 and s6.
- s3 has no `after`: the gate task needs no data, so it is built while s1
  and s2 run.
- MDE at alpha 0.025 is two-sided: (z 0.9875 + z 0.80) × the SD of b over
  the re-flips = 3.083 × SD (0009 used 2.8, alpha 0.05).
- k3 and k4 as counts (`power.n_powered`, `placebo.powered_failing`), so
  each rule reads one field.
- The forks' budget (see "Budget and why").
- Reusing 0009's novelty check of 2026-11-15, with two lines added.
- `camara_deputies` with `identifiers: none`, as `tse_general`'s raw zips
  (see "New data").

Self-repair: `true` as the brief says, but it cannot fire. A repair may
change only the paths of build tasks before the failing step, and this
campaign has no build task: s1 and s2 would block and ask Gabriel instead
(the tick says "no task step it comes after lists a file a repair may
change"). Gabriel chose `false` for the same reason in campaign 0010.

The closest paper: Gabriel on 2026-11-15, for 0009: "Not yet: active
anyway". Not asked again: his brief asks for `active` and for questions
only on merges, loosened checks or large data fixes.

Probe: not recommended. All data but the 1.4 MB Chamber file are in the
bucket, the build passed a real-file dry run, and the plan has six steps.

Not looked at: no amendment amount, payment, vote number or other outcome.
Only the counts and link shares in the dry-run notes of PR #421.
