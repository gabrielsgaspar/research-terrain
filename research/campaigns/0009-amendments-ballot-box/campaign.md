---
id: "0009"
title: "What do budget amendments buy at the ballot box? Close mayoral races, deputies' amendments and their votes, 2016-2026"
status: active
idea: "0009"
owner: gabrielsgaspar
created: 2026-11-15
end_by: 2026-11-29
budget:
  max_tasks: 4
  max_explore_runs: 2
  max_pipeline_runs: 3
  max_model_jobs: 34
referee_not_applicable_ok: [R5]
self_repair: true
oversize_reason: "data, build, power gate and main run are one chain and splitting it would mean two approvals for one question"
forks:
  max_forks: 3
  per_point: 3
  max_new_datasets: 1
  max_steps_per_fork: 4
  types: [transform, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: [s9]
  budget:
    max_tasks: 6
    max_explore_runs: 3
    max_pipeline_runs: 4
    max_model_jobs: 32
datasets:
  - name: tse_general
    source: "TSE open data (cdn.tse.jus.br), general elections: votacao_candidato_munzona 2014, 2018, 2022 and 2026, and consulta_cand 2010, 2014, 2018, 2022 and 2026; raw zips as published"
    licence: "TSE open data: CC BY (dadosabertos.tse.jus.br)"
    max_size_gb: 3
    identifiers: none
  - name: cgu_amendments
    source: "CGU Portal da Transparência (dadosabertos-download.cgu.gov.br), EmendasParlamentares.zip: amendments, and payments by recipient and month; raw zip as published"
    licence: "Portal da Transparência open data (federal open-data policy); licence not stated by the publisher, accepted by Gabriel on 2026-11-15 for research use"
    max_size_gb: 1
    identifiers: none
  - name: amendments_panel
    source: "built from tse_general, cgu_amendments, tse_results, tse_candidates, municipalities and ibge_population_annual; one row per deputy, municipality and cycle; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
steps:
  # Data: the two acquires and the panel build
  - id: s1
    kind: task
    type: build
    draft: drafts/s1.md
    allowed_paths:
      - data/catalog.yaml
      - data/contracts/tse_general.md
      - data/contracts/cgu_amendments.md
      - pipeline/acquire/tse_general.py
      - pipeline/acquire/cgu_amendments.py
      - tests/test_acquire.py
    after: []
  - id: s2
    kind: pipeline_run
    stage: acquire
    target: tse_general
    dataset: tse_general
    after: [s1]
  - id: s3
    kind: pipeline_run
    stage: acquire
    target: cgu_amendments
    dataset: cgu_amendments
    after: [s1]
  - id: s4
    kind: task
    type: build
    draft: drafts/s4.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/amendments_panel.py
      - pipeline/build/amendments_panel.py
      - data/contracts/amendments_panel.md
      - tests/test_build_amendments_panel.py
    after: [s1]
  - id: s5
    kind: pipeline_run
    stage: build
    target: amendments_panel
    dataset: amendments_panel
    after: [s2, s3, s4]
  # Gate: window, counts, power, placebos and the deputy link, with no post-election outcome
  - id: s6
    kind: task
    type: explore
    draft: drafts/s6.md
    allowed_paths:
      - explore/0009_amendments_gate.py
      - tests/test_explore_amendments_gate.py
    after: [s4]
  - id: s7
    kind: explore_run
    script: 0009_amendments_gate
    after: [s5, s6]
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
  - id: s8
    kind: task
    type: explore
    draft: drafts/s8.md
    allowed_paths:
      - explore/0009_amendments_effects.py
      - tests/test_explore_amendments_effects.py
    after: [s7]
  - id: s9
    kind: explore_run
    script: 0009_amendments_effects
    after: [s8]
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

# 0009: What do budget amendments buy at the ballot box?

## Question

When a federal deputy's party narrowly wins a mayoralty, does that deputy
send more individual amendment money (emendas) to the municipality, does it
turn into votes for the deputy at the next general election, and did that
change across the rule regimes: mandatory individual amendments (from the
2015 budget), special transfers ("Pix", from 2020) and the end of rapporteur
amendments (ruled unconstitutional in December 2022)? Idea 0009
(`research/ideas/0009-amendments-ballot-box.md`). Close mayoral races in the
whole country, three cycles: A (mayor 2016, amendments 2017-18, deputy votes
2018 vs 2014), B (2020, 2021-22, 2022 vs 2018) and C (2024, 2025-26, 2026 vs
2022). Exploration half only (decision 0011's national split).

## Already known

Novelty check of 2026-11-15 (`novelty_scan.py` with emenda, amendment,
"federal deputy", deputado, pork, "budget amendment", alignment, brokerage;
`research/references/`; six web searches).

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Mayor's party in close races → deputies' amendments and votes | explored (one earlier period) | (web, unverified) Baião and Couto, "A eficácia do pork barrel: a importância de emendas orçamentárias e prefeitos aliados na eleição de deputados", *Opinião Pública* 23(3) 2017, 714-753, doi:10.1590/1807-01912017233714: a regression discontinuity on the mayor's party, for amendment proposal and execution and the deputy's election. Only the abstract and introduction were read |
| Amendments and deputies' local votes | explored | (web, unverified) Firpo, Ponczek and Sanfelice, "The relationship between federal budget amendments and local electoral power", *J. Dev. Econ.* 116 (2015) 186-198: an RD on close *deputy* races |
| Mayors' party and deputies' votes, without money | partly explored | (web, unverified) Avelino, Biderman and Barone, *Dados* (2012), "Articulações intrapartidárias e desempenho eleitoral no Brasil": an RD of mayors on their party's deputy votes |
| Close mayoral races and federal transfers | explored (the president's coalition) | (web, unverified) Brollo and Nannicini, "Tying Your Enemy's Hands in Close Races", *APSR* 106(4) 2012 |
| Pix and votes, 2022 to 2026 | descriptive only | (web, unverified) FGV study reported in October 2026 (press only, e.g. Brasil 61, "Emendas parlamentares ajudam a conquistar votos, mas não garantem reeleição"): about +1 pp for Pix amendments, no clear link to reelection; correlation, the original report was not found |
| Amendments, deputies, the regimes, in this repository | new | no idea, run or lesson; nearest: mayoral close-race code in `explore/0003_mayor_power.py` (idea 0003, run 42367009833, Legal Amazon only) and decision 0008's window rule |
| Representatives favouring aligned municipalities | explored (Norway) | `fivaLocalFavoritismAtlarge2016` |

What this campaign adds: the three regimes (2016, 2020 and 2024 mayors),
the whole country, a deputy × municipality unit with deputy-by-cycle fixed
effects, and a first stage dated by payment month, before the general
election. Baião and Couto may already answer cycle A's question; that is
why they head the list below.

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

- **s1** (build task): catalog entries, contracts and thin acquire scripts
  for `tse_general` and `cgu_amendments`, both through the generic acquirer
  (`terrain.acquire`). First, because every later step needs these entries.
- **s2, s3** (acquires): run in parallel. s3 is the riskier one: no runner
  has fetched from `dadosabertos-download.cgu.gov.br` yet, so it goes first,
  before any work that reads the data. If it fails for good, the fallback is
  Base dos Dados (`basedosdados.br_cgu_emendas_parlamentares.microdados`),
  by budget year instead of payment month. That would need a change to
  `terrain.bigquery` and so a new campaign.
- **s4** (build task): the deputy × municipality × cycle panel. It needs
  only s1's catalog entries, so it is written while the acquires run
  (note N003).
- **s5** (build run): the panel, split by half.
- **s6** (explore task): the gate script. It reads no post-election
  outcome.
- **s7** (gate run): window choice, race counts, power, the two placebos and
  the author link. Any rule met stops the campaign: with too few races, no
  power or an unbalanced design, the main run would mean nothing.
- **s8** (explore task): first stage and reduced form, written only after
  the gate survives (cheapest kill first).
- **s9** (main run): the first stage must be strong (F ≥ 10). It is the only
  fork point.

### Definitions fixed in the drafts that the brief left open

Suggested by Claude, confirmed by Gabriel on 2026-11-15:

- Amendments are individual amendments (Tipo de Emenda starts with "Emenda
  Individual") paid to recipients located in the municipality, by payment
  month, from the CGU file `EmendasParlamentares_PorFavorecido.csv`. The
  post window is January of m+1 to September of m+2, before the October
  general election (m is the mayoral election year).
- The window grid is 0.5, 1, 2, 3, 4, 5, 7.5 and 10% (deciding-round
  margin over valid votes). Decision 0008's rule picks h: the widest window
  with omnibus p at least 0.15 whose smaller windows all pass, from 2,000
  race re-flips, seed 20261115. The covariates are the deputy's-party
  finalist's sex, age and higher education, whether the deputy's party held
  the mayoralty before, and log population. The placebos are not
  covariates.

Suggested by Claude in the drafts, not asked separately (Gabriel approves
them with the card):

- The placebo's pre window is January of m-1 to September of m: the 21
  months before the mayoral vote, as long as the post window. Pix is a Tipo
  de Emenda containing "Transferências Especiais".
- Senators are left out of the author link: they are matched to TSE senate
  candidacies (2010-2022) and not counted in `link.author_share`.
- Deputies are matched to amendment authors by normalised name, in memory;
  the panel keys a deputy by the TSE `SQ_CANDIDATO` of the base election and
  stores no CPF, voter ID or name.
- Parties are matched across elections by `NR_PARTIDO`.
- A deputy who did not run for federal deputy at the next general election
  has a null vote change.

## Kill rules and why

s7 (the gate; no post-election outcome is read):

- **k1** `window.found == 0`: decision 0008 leaves a failed smallest window
  to Gabriel; inside a campaign it is a stop. Suggested by Claude, confirmed
  by Gabriel on 2026-11-15.
- **k2** `counts.races_h < 200`: about 60 races per cycle are needed for b by
  cycle and the C-minus-A difference, and randomisation inference needs many
  clusters. A design count; suggested by Claude, confirmed by Gabriel on
  2026-11-15.
- **k3** `power.mde_share > 0.25`: the kill-rule library's `power_mde_share`
  (campaign 0004's threshold), named in Gabriel's brief. The outcome stand-in
  is the pre-window amendments per 1,000 inhabitants. Read back and
  confirmed by Gabriel on 2026-11-15.
- **k4, k5** placebo size rules at 25% of the placebo outcome's mean: an
  imbalance as large as the smallest effect the design can detect is fatal.
  Size rules rather than p-value rules (Gabriel's choice, 2026-11-15), so no
  p-value rule adds false stops: the card's false-stop sum is 0. With few
  races a large imbalance can still pass k4 and k5; passing is not "balanced".
- **k6** `link.author_share < 0.90`: a broken name link would make the first
  stage an artefact. The share counts authors, never amounts, so no outcome
  is read. Suggested by Claude, confirmed by Gabriel on 2026-11-15.

s9:

- **k1** `first_stage.f_cluster < 10`: library rule `first_stage_strength`,
  stated by Gabriel in his brief.
- **k2** `estimates.finite != true`: library rule `finite`, stated by
  Gabriel in his brief.

Both steps use `on_kill: stop` (Gabriel's brief). A kill at s9 does not stop
the forks: s9 is the fork point.

## Budget and why

`scripts/budget.py --tasks 4 --explore-runs 2 --pipeline-runs 3` suggested 20
model jobs (5 per task) and 8 days. Proposed by Claude, confirmed by Gabriel
on 2026-11-15:

- `max_tasks` 4: s1, s4, s6, s8.
- `max_explore_runs` 2 and `max_pipeline_runs` 3: one per step; retries are
  the tick's own.
- `max_model_jobs` 34: 7 + 7 for the two data tasks, 5 + 5 for the two
  scripts, 4 for two fix rounds, 6 for up to two self-repairs.
- `end_by` 2026-11-29, 14 days: campaign 0008 took 19.5 hours for 10 steps,
  0007 45.1 hours for 23 (`research/agent-notes.md`, Scoreboard). The extra
  days cover the 24-hour wait of a blocked step and the close-out.
- Forks' own budget: `max_tasks` 6, `max_explore_runs` 3, `max_pipeline_runs`
  4, `max_model_jobs` 32 (three forks at about 10 jobs each, plus one
  ideation job at s9).

When a budget runs out, nothing new starts and the tick files the close-out.

## New data

- **tse_general**: TSE general-election votes by candidate and municipality
  (`votacao_candidato_munzona` 2014, 2018, 2022, 2026: 494, 395, 577 and
  454 MB zipped, 7.4-8.6 GB unzipped) and candidacies (`consulta_cand`
  2010-2026, 3-5 MB each; 2010 for the senators among amendment authors). All
  27 states published; the 2026 files were regenerated on 2026-11-15 and can
  still change with court rulings. CC BY. The `consulta_cand` zips carry CPF
  and voter-ID numbers, as TSE publishes them. They stay in raw as fetched,
  like the municipal raw zips; the build uses them in memory only to link a
  deputy across elections, and no derived file holds them. Hence
  `identifiers: none`, and `ID_SALT` (which does not exist) is not needed.
  Fetched from `cdn.tse.jus.br` by runners before. Fallback: Base dos Dados
  `br_tse_eleicoes`.
- **cgu_amendments**: the CGU Portal da Transparência amendment zip (47 MB,
  six CSVs; updated 2026-11-13). The build reads
  `EmendasParlamentares_PorFavorecido.csv` (author code and name, type,
  payment month, recipient's state and municipality, legal nature, value)
  and `EmendasParlamentares.csv`. Recipient codes and names (which can be
  people) are never read into derived output. The publisher states no
  licence; Gabriel accepted it for research use on 2026-11-15. **No runner
  has fetched this host before.** Fallback: Base dos Dados, budget years
  2013-2026, with no payment date; or Tesouro Transparente's
  `emendas-parlamentares.csv` (payment orders with dates and a Pix flag but
  no author code).
- **amendments_panel**: the built panel, exploration-half rows in derived,
  all others only in sealed (`sealed/outcomes/amendments_panel/`, pinned in
  `tests/test_split.py` by this PR).

Existing: `tse_results`, `tse_candidates`, `municipalities`,
`ibge_population_annual` (to 2025; m = 2024 is covered).

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

- s3 cannot reach the CGU host after its retries and the repair: stop, and
  design a campaign on Base dos Dados with the budget-year measure.
- `link.author_share` just above 0.90 but very different by cycle: read the
  report before any confirmation-half step.
- A strong first stage with a reduced form near zero, or a Wald ratio
  larger than any campaign could produce, is likely the allied mayor's
  own campaigning. The ratio is an upper bound, as declared.
- Cycle C's 2026 TSE files changing after the acquire: the raw snapshot is
  dated; a re-run would need a new acquire.

## Provenance

Stated by Gabriel (brief, 2026-11-15): the question; the design (close
mayoral races, the whole country, cycles A-C, the deputy × municipality ×
cycle unit with the top-two party condition, the model, the 5% fixed check,
clustering, 2,000-draw randomisation inference); the first stage (per 1,000,
asinh, any > 0, Pix vs other); the reduced form; both placebos; the
secondary analyses; exploration half by decision 0011; the nine steps and
their kinds; `on_kill: stop`; s9's rules (`first_stage_strength`, `finite`);
s7's power rule as the library's `power_mde_share`; the forks envelope
(`max_forks` 3, `per_point` 3, `fork_points` [s9], `on` [killed,
survived], types [transform, spec, measure, question],
`max_question_forks` 1, `max_new_datasets` 1, `max_steps_per_fork` 4, no
sample forks); the three variants for the ideation job; `status: active`.

`oversize_reason`, in his words: "data, build, power gate and main run are
one chain and splitting it would mean two approvals for one question".

Suggested by Claude, confirmed by Gabriel on 2026-11-15:

- Data source and timing: "CGU, Jan t+1–Sep t+2 (Recommended)".
- Licences and identifiers: "Yes, as proposed" (TSE CC BY; CGU accepted for
  research use; both `identifiers: none`; no `ID_SALT`).
- Self-repair: "Yes (Recommended)".
- The window rule and covariates: "Yes, as proposed".
- s7 rules k1, k2 and k6, ticked one by one; k3 read back and confirmed
  ("Confirm k3 as written"); k4 and k5: "Size: |b| > 25% of mean
  (Recommended)".
- The plan and fork budgets and `end_by`: "Yes, as proposed".
- Keeping cycle C: the 2026 TSE files are published (checked 2026-11-15).

The closest paper: Claude recommended `draft` until Baião and Couto (2017)
is read; Gabriel: "Not yet: active anyway".

Probe: not recommended, because no listed dataset can measure power or
either placebo (both need the two new datasets). Gabriel's brief has no probe.

Forks: the envelope above, set by Gabriel on 2026-11-15 (brief), with the
budget suggested by Claude and confirmed ("Yes, as proposed"). Decision
0015 is still `proposed` in its front matter. No code reads its status, and
its text says it took effect when merged (commit 304dded).

Not looked at: no amendment amount, payment, vote number or other outcome.
Only file existence, sizes, member names and column headers (2026-11-15).
