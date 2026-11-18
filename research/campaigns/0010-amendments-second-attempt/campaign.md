---
id: "0010"
title: "What do budget amendments buy at the ballot box? Second attempt: build, gate and main run"
status: done
idea: "0009"
owner: gabrielsgaspar
created: 2026-11-18
end_by: 2026-12-02
budget:
  max_tasks: 2
  max_explore_runs: 2
  max_pipeline_runs: 2
  max_model_jobs: 20
referee_not_applicable_ok: [R5]
self_repair: false
forks:
  max_forks: 3
  per_point: 3
  max_new_datasets: 1
  max_steps_per_fork: 4
  types: [transform, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: [s4]
  budget:
    max_tasks: 6
    max_explore_runs: 3
    max_pipeline_runs: 4
    max_model_jobs: 32
datasets:
  - name: amendments_panel
    source: "built from tse_general, cgu_amendments, tse_results, tse_candidates, municipalities and ibge_population_annual; one row per deputy, municipality and cycle; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
steps:
  # The panel build, on main with owner fixes #411 and #414
  - id: s1
    kind: pipeline_run
    stage: build
    target: amendments_panel
    dataset: amendments_panel
    after: []
  # Gate: window, counts, power, placebos and the deputy link, with no post-election outcome
  - id: s2
    kind: explore_run
    script: 0009_amendments_gate
    after: [s1]
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
        says: "The first stage's minimum detectable effect at 80% power is above 25% of the pre-election mean of amendments per 1,000 inhabitants"
        field: power.mde_share
        op: ">"
        value: 0.25
        confirmed: true
      - id: k4
        says: "The placebo slope on amendments paid before the mayoral election exceeds 25% of their mean, in absolute value"
        field: placebo.amend_share_abs
        op: ">"
        value: 0.25
        confirmed: true
      - id: k5
        says: "The placebo slope on the deputy's vote share at the previous general election exceeds 25% of its mean, in absolute value"
        field: placebo.vote_share_abs
        op: ">"
        value: 0.25
        confirmed: true
      - id: k6
        says: "Fewer than 90% of the deputies' individual-amendment authors in some cycle are matched to a TSE federal-deputy candidacy"
        field: link.author_share
        op: "<"
        value: 0.90
        confirmed: true
    on_kill: stop
  # Main run: first stage and reduced form
  - id: s3
    kind: task
    type: explore
    draft: drafts/s3.md
    allowed_paths:
      - explore/0009_amendments_effects.py
      - tests/test_explore_amendments_effects.py
    after: [s2]
  - id: s4
    kind: explore_run
    script: 0009_amendments_effects
    after: [s3]
    kill_rules:
      - id: k1
        says: "The municipality-clustered first-stage F statistic of Win on amendments per 1,000 inhabitants is below 10"
        field: first_stage.f_cluster
        op: "<"
        value: 10
        confirmed: true
      - id: k2
        says: "Some first-stage or reduced-form estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0010: What do budget amendments buy at the ballot box? Second attempt

## Question

The question of campaign 0009, unchanged. When a federal deputy's party
narrowly wins a mayoralty, does that deputy send more individual amendment
money (emendas) to the municipality, and does it turn into votes for the
deputy at the next general election, across cycles A (mayor 2016), B (2020)
and C (2024)? Idea 0009 (`research/ideas/0009-amendments-ballot-box.md`).
Campaign 0009 ended without a result: its panel build (s5) failed on all
four runs (`research/campaigns/0009-amendments-ballot-box/report.md`), so
the gate and the main run never ran. This campaign runs what is left: the
build, the gate and the main run, with the same design, thresholds, window
rule and variants. Exploration half only (decision 0011's national split).

## Already known

Not checked again. Campaign 0009's novelty check of 2026-11-15
(`research/campaigns/0009-amendments-ballot-box/campaign.md`, "Already
known") is three days old and covers the same question:

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Mayor's party in close races → deputies' amendments and votes | explored (one earlier period) | (web, unverified) Baião and Couto, "A eficácia do pork barrel: a importância de emendas orçamentárias e prefeitos aliados na eleição de deputados", *Opinião Pública* 23(3) 2017, 714-753, doi:10.1590/1807-01912017233714: a regression discontinuity on the mayor's party, for amendment proposal and execution and the deputy's election. Only the abstract and introduction were read |
| Amendments and deputies' local votes | explored | (web, unverified) Firpo, Ponczek and Sanfelice, "The relationship between federal budget amendments and local electoral power", *J. Dev. Econ.* 116 (2015) 186-198: an RD on close *deputy* races |
| Mayors' party and deputies' votes, without money | partly explored | (web, unverified) Avelino, Biderman and Barone, *Dados* (2012), "Articulações intrapartidárias e desempenho eleitoral no Brasil": an RD of mayors on their party's deputy votes |
| Close mayoral races and federal transfers | explored (the president's coalition) | (web, unverified) Brollo and Nannicini, "Tying Your Enemy's Hands in Close Races", *APSR* 106(4) 2012 |
| Pix and votes, 2022 to 2026 | descriptive only | (web, unverified) FGV study reported in October 2026 (press only, e.g. Brasil 61, "Emendas parlamentares ajudam a conquistar votos, mas não garantem reeleição"): about +1 pp for Pix amendments, no clear link to reelection; correlation, the original report was not found |
| Amendments, deputies, the regimes, in this repository | new | no idea, run or lesson; nearest: mayoral close-race code in `explore/0003_mayor_power.py` (idea 0003, run 42367009833, Legal Amazon only) and decision 0008's window rule |
| Representatives favouring aligned municipalities | explored (Norway) | `fivaLocalFavoritismAtlarge2016` |

What this campaign adds over 0009: a result. 0009 produced no number.

## Read before this runs

- **Baião and Couto (2017)**, "A eficácia do pork barrel", *Opinião Pública*
  23(3), doi:10.1590/1807-01912017233714 (closest; web, unverified).
  Gabriel (2026-11-15): "Not yet: active anyway".
- **Firpo, Ponczek and Sanfelice (2015)**, *J. Dev. Econ.* 116, 186-198
  (web, unverified). Gabriel: not stated.
- **Brollo and Nannicini (2012)**, *APSR* 106(4) (web, unverified).
  Gabriel: not stated.
- **FGV note on amendments and reelection (October 2026)**, press reports
  only (web, unverified). Gabriel: not stated.

## Steps and why

- **s1** (build run): the deputy × municipality × cycle panel
  (`pipeline/build/amendments_panel.py`), on main with both owner fixes:
  #411 (CGU's "Sem informação" recipients count as no municipality) and
  #414 (net-negative amendment totals floored at zero). #414 was run on
  the real files first, without uploading: the build passed and set 1 row
  to zero (cycle B, `amend_pre_total`). The inputs (`tse_general`,
  `cgu_amendments` and the four existing datasets) are already acquired,
  so this is the first step and nothing waits for an acquire (note N003).
  It is a single build, as in 0009 (note N007 advises splitting builds);
  the dry run is the reason it stays whole.
- **s2** (gate run): `explore/0009_amendments_gate.py`, merged in campaign
  0009 (s6, PR #409). Window choice, race counts, power, the two placebos
  and the author link. It reads no post-election outcome. Any rule met
  stops the campaign.
- **s3** (explore task): the main-run script,
  `explore/0009_amendments_effects.py`, written only after the gate
  survives (cheapest kill first). Its draft is 0009's `drafts/s8.md`, word
  for word but for its step numbers.
- **s4** (main run): first stage and reduced form. The first stage must be
  strong (F ≥ 10). It is the only fork point.

The definitions fixed in 0009 ("Definitions fixed in the drafts that the
brief left open") hold unchanged; they live in the merged code (s1, s2)
and in the s3 draft.

## Kill rules and why

All copied word for word from campaign 0009 (s7 to s2, s9 to s4), with the
same ids, fields and thresholds. Their reasons are in 0009's "Kill rules and
why".

s2 (the gate; no post-election outcome is read):

- **k1** `window.found == 0`: no window passes decision 0008's balance rule.
- **k2** `counts.races_h < 200`: too few close races for the by-cycle
  estimates and randomisation inference.
- **k3** `power.mde_share > 0.25`: the library's `power_mde_share`.
- **k4, k5** placebo size rules at 25% of the placebo outcome's mean. Size
  rules, not p-value rules, so the card's false-stop sum is 0.
- **k6** `link.author_share < 0.90`: a broken name link would make the first
  stage an artefact.

s4:

- **k1** `first_stage.f_cluster < 10`: library rule `first_stage_strength`.
- **k2** `estimates.finite != true`: library rule `finite`.

Both runs use `on_kill: stop`. A kill at s4 does not stop the forks: s4 is
the fork point.

## Budget and why

Stated by Gabriel (2026-11-18): `max_tasks` 2, `max_explore_runs` 2,
`max_pipeline_runs` 2, `max_model_jobs` 20, `end_by` 2026-12-02 (14 days).
`budget.py --tasks 1 --explore-runs 2 --pipeline-runs 1` suggested 1, 2, 1,
5 model jobs and 6 days; the larger numbers leave room for one more task, one
more build run and a fix round.

- One task (s3) and the close-out use model jobs; s1, s2 and s4 use none.
- Forks have their own budget, copied from 0009: `max_tasks` 6,
  `max_explore_runs` 3, `max_pipeline_runs` 4, `max_model_jobs` 32.

When a budget runs out, nothing new starts and the tick files the close-out.

## New data

None. `tse_general` and `cgu_amendments` were acquired in campaign 0009 (s2
and s3). `amendments_panel` is listed in `datasets` only because s1 builds
it (the validator requires a build step's dataset there). The entry is the
one approved in 0009. The new code gives the build a new output path, so
nothing already in the bucket is overwritten. Existing inputs:
`tse_results`, `tse_candidates`, `municipalities`, `ibge_population_annual`.

## Variants in scope for forks (guidance for the ideation job)

Not binding. Gabriel considers these in scope (2026-11-15); the envelope
and the rules of decision 0015 still decide what may run.

1. **spec**: alignment by the mayor's coalition or federation instead of
   the deputy's own party.
2. **measure**: Pix amendments only, cycles B and C.
3. **question**: the same close races, with the outcome being the vote
   change of the mayor's party's state deputies, as a brokerage benchmark.

No sample forks: the library rule `min_clusters` is unconfirmed.

## What would change the plan

- s1 fails again: no repair task can be filed (there is no build task
  before it), so the step blocks and asks Gabriel. The fix is an owner
  fix, as with #411 and #414.
- `link.author_share` just above 0.90 but very different by cycle: read the
  report before any confirmation-half step.
- A strong first stage with a reduced form near zero, or a Wald ratio
  larger than any campaign could produce, is likely the allied mayor's own
  campaigning. The ratio is an upper bound, as declared.
- Cycle C's 2026 TSE files changing after the acquire: the raw snapshot is
  dated; a re-run would need a new acquire.

## Provenance

Stated by Gabriel (brief, 2026-11-18): the title; no new datasets; the four
steps and their kinds; s2's kill rules k1-k6 copied word for word from 0009's
s7, and s4's copied word for word from 0009's s9; the s3 draft copied word
for word from 0009's `drafts/s8.md` with its step references updated;
`on_kill: stop`; the forks block copied from 0009 with `fork_points` [s4],
and the section listing the three non-binding variants; the budget and
`end_by`; the same design, thresholds, window rule and variants; idea 0009
from `parked` to `exploring`; opening the PR as `active`. The kill rules are
confirmed by that brief (first confirmed for 0009 on 2026-11-15).

Self-repair: Gabriel's brief said `self_repair: true`. Claude pointed out
that a repair may change only the files of build tasks before the failing
step, and s1 has none, so a repair could never be filed. Gabriel chose
"false (Recommended)" on 2026-11-18.

Suggested by Claude, not asked separately (Gabriel approves them with the
card):

- Listing `amendments_panel` in `datasets`, with 0009's entry (the validator
  needs a build step's dataset listed).
- Reusing 0009's novelty check of 2026-11-15 instead of running a new one.
- The step references changed in the s3 draft: s8 to s3, s9 to s4, s6's
  script and s7's window to s2, and the campaign path.

The closest paper: Gabriel on 2026-11-15, for 0009: "Not yet: active
anyway". Not asked again: the skill asks only for campaigns of more than
four steps.

Probe: not recommended. The data are acquired, the build passed a real-file
dry run, and the campaign has four steps.

Forks: the envelope of 0009 (Gabriel's brief, 2026-11-15), with
`fork_points` [s4], stated by Gabriel on 2026-11-18.

Not looked at: no amendment amount, payment, vote number or other outcome.
Only the counts in the build's dry-run notes (2026-11-18, PR #414).
