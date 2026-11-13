---
id: "0008"
title: "Gold and the ballot, yes/no: does the gold price move garimpo and politics where any gold lies?"
status: active
idea: "0008"
owner: gabrielsgaspar
created: 2026-11-13
end_by: 2026-11-27
budget:
  max_tasks: 5
  max_explore_runs: 2
  max_pipeline_runs: 6
  max_model_jobs: 40
referee_not_applicable_ok: [R5]
self_repair: true
oversize_reason: "This is the fork of campaign 0007. It continues 0007's skipped politics phase on the yes/no gold measure, using 0007's own drafts, in one campaign so I am not needed in between."
datasets:
  - name: sim_homicides
    source: "DATASUS SIM via Base dos Dados on BigQuery, basedosdados.br_ms_sim.microdados, deaths by assault (CID-10 X85-Y09) counted by year and municipality of occurrence, 1996-2024"
    licence: "Base dos Dados lists 'desconhecida'; DATASUS publishes SIM as public data. Only municipality-level counts are stored."
    max_size_gb: 1
    identifiers: none
  - name: ibge_population_annual
    source: "IBGE municipal population estimates via Base dos Dados on BigQuery, basedosdados.br_ibge_populacao.municipio, 1991-2025"
    licence: "public (IBGE); Base dos Dados lists no licence"
    max_size_gb: 1
    identifiers: none
  - name: tse_receipts
    source: "TSE candidate campaign receipts via Base dos Dados on BigQuery, basedosdados.br_tse_eleicoes.receitas_candidato, 2004-2012, summed by year, municipality, office and donor CNAE; no donor CPF, CNPJ or name is selected"
    licence: "TSE open data: CC BY (dadosabertos.tse.jus.br); Base dos Dados lists no licence"
    max_size_gb: 1
    identifiers: none
  - name: politics_panel
    source: "built from tse_candidates, tse_results, municipalities, sim_homicides, ibge_population_annual and tse_receipts; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
steps:
  # Gate: the yes/no first stage, on data already in the bucket
  - id: s1
    kind: task
    type: explore
    draft: drafts/s1.md
    allowed_paths:
      - explore/0008_gold_yes_no_first_stage.py
      - tests/test_explore_gold_yes_no_first_stage.py
    after: []
  - id: s2
    kind: explore_run
    script: 0008_gold_yes_no_first_stage
    after: [s1]
    kill_rules:
      - id: k1
        says: "The municipality-clustered F statistic of has-gold (yes/no) x log real gold price (t-1) on garimpo area share, 1990-2024, is below 10"
        field: first_stage.f_cluster
        op: "<"
        value: 10
        confirmed: true
      - id: k2
        says: "The absolute mean event-study coefficient for 1990-2001 (base 2000) is more than half the absolute mean coefficient for 2002-2024"
        field: placebo.lead_ratio
        op: ">"
        value: 0.5
        confirmed: true
      - id: k3
        says: "Some first-stage estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Politics and violence (final), campaign 0007's phase C
  - id: s3
    kind: task
    type: build
    draft: drafts/s3.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/bigquery.py
      - tests/test_bigquery.py
      - src/terrain/basedosdados.py
      - tests/test_acquire_basedosdados.py
      - pipeline/acquire/sim_homicides.py
      - pipeline/acquire/ibge_population_annual.py
    after: [s2]
  - id: s4
    kind: pipeline_run
    stage: acquire
    target: sim_homicides
    dataset: sim_homicides
    after: [s3]
  - id: s5
    kind: pipeline_run
    stage: acquire
    target: ibge_population_annual
    dataset: ibge_population_annual
    after: [s3]
  - id: s6
    kind: task
    type: build
    draft: drafts/s6.md
    allowed_paths:
      - data/catalog.yaml
      - pipeline/acquire/tse_receipts.py
      - tests/test_acquire_basedosdados.py
      - src/terrain/builds/politics_panel.py
      - pipeline/build/politics_panel.py
      - data/contracts/politics_panel.md
      - tests/test_build_politics_panel.py
    after: [s3]
  - id: s7
    kind: pipeline_run
    stage: acquire
    target: tse_receipts
    dataset: tse_receipts
    after: [s6]
  - id: s8
    kind: pipeline_run
    stage: build
    target: politics_panel
    dataset: politics_panel
    after: [s4, s5, s6, s7]
  - id: s9
    kind: task
    type: explore
    draft: drafts/s9.md
    allowed_paths:
      - explore/0008_gold_politics.py
      - tests/test_explore_gold_yes_no_politics.py
    after: [s6]
  - id: s10
    kind: explore_run
    script: 0008_gold_politics
    after: [s8, s9]
    kill_rules:
      - id: k1
        says: "Some estimate, standard error or p-value of the politics reduced forms is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0008: Gold and the ballot, yes/no

## Question

When the world gold price rises, does garimpo grow in the municipalities
that have **any** recorded gold, and do their local politics change: who
runs, who wins, how competitive races are, how violent the place is? This
is idea 0008 (`research/ideas/0008-gold-ballot-yes-no.md`), across all of
Brazil (decision 0011), exploration half only. It is the first fork of a
campaign, done by hand: campaign 0007 measured gold as a **density** and
stopped at its first-stage gate (clustered F 2.44, rule at least 10). The
same run showed, as a side result, that the yes/no measure `geo_exposed`
gives F 12.28 (`research/explore-runs/0007/43438404852.md`, key
`robust.binary`). That was seen after the fact, so it cannot rescue idea
0007. This campaign explores it as a new idea, with the measure, the test
and the kill rules written before any run.

**Nothing here can be a finding.** The measure was chosen after seeing the
data. A finding needs one registered test on the sealed half, which is
Gabriel's decision after this campaign.

## Already known

Tier 1 (this repository): `novelty_scan.py` with geo_exposed, binary,
yes/no, garimpo, gold price and 0008 (2026-11-13) finds only campaign 0007:
its idea file (now `dead`), its two run records, its report and the
2026-11-13 lessons entry. No other idea or script uses the yes/no measure
as its main exposure. Tier 2 (Zotero notes): nothing on gold or garimpo, as
in campaign 0007's check of 2026-11-11. Tier 3 (web): not searched again;
the question is campaign 0007's, and its check two days ago stands. Every
web find below is from that check and is **unverified**.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Gold price × yes/no exposure on garimpo, this data | **explored here** | `research/explore-runs/0007/43438404852.md`: F 12.28 (beta 0.0001346, SE 3.841e-05), seen before this idea; event study, placebos and sturdiness not run for this measure |
| Gold price × exposure raises garimpo in Brazil | explored | (web, unverified, from 0007) Amaral, Pantaleão and Rio Tinto, "The Cost of Gold"; Moreno-Louzada, Figueira and Picchetti (2025), arXiv 2512.10076 |
| Gold price × exposure and local politics | **new** | none found in campaign 0007's check; adjacent: Carreri and Dube (2017, JOP 79(2)), oil in Colombia |
| Legal access (where mining is barred) × price | partly explored | (web, unverified) Idrobo, Mejía and Tribín (2014, PEPS 20(1)), gold in Colombia |
| Inference with one common shock | explored (method) | `borusyakNonrandomExposureExogenous2023`; Moreno-Louzada et al. (2025): clustered errors over-reject in this gold design |

What this campaign adds: a pre-trend check (k2) for the yes/no measure,
which has not been run; report-only checks of why the density measure
failed and how sturdy the yes/no result is; and campaign 0007's never-run
politics phase, on the yes/no measure.

## Read before this runs

- **Carreri and Dube (2017)**, "Do Natural Resources Influence Who Comes to
  Power, and How?", JOP 79(2), doi:10.1086/688443 (closest for the
  politics phase; web, unverified). Gabriel (brief, 2026-11-13): starts
  before reading it.
- **Idrobo, Mejía and Tribín (2014)**, "Illegal Gold Mining and Violence in
  Colombia", Peace Econ. Peace Sci. Public Policy 20(1),
  doi:10.1515/peps-2013-0053 (the legal-access split; web, unverified).
  Gabriel: starts before reading it.
- **Moreno-Louzada, Figueira and Picchetti (2025)**, arXiv 2512.10076, the
  paper on clustered errors with one common shock that campaign 0007's run
  record cites (web, unverified). Gabriel: starts before reading it.

## Steps and why

Ten steps: one new gate on data already in the bucket, then campaign
0007's skipped politics phase (its s16-s23), renumbered.

| Here | What | From | Files |
| --- | --- | --- | --- |
| s1 | yes/no first-stage script (explore task) | new | 2 fits |
| s2 | run it: **gate** | new | |
| s3 | Base dos Dados aggregation; SIM and population acquirers (build task) | 0007 s16 | 7 tight |
| s4, s5 | acquire `sim_homicides`, `ibge_population_annual` | 0007 s17, s18 | |
| s6 | receipts acquirer and `politics_panel` build, sealed (build task) | 0007 s19 | 7 tight |
| s7, s8 | acquire `tse_receipts`, build `politics_panel` | 0007 s20, s21 | |
| s9 | politics script, yes/no exposure (explore task) | 0007 s22 | 2 fits |
| s10 | run it: final | 0007 s23 | |

- **s1, s2 (gate), cheapest kill first.** They read only `mining_panel`
  and `gold_exposure`, both already built (`data/manifests/build/`), so
  the gate costs one task and one run before any acquire. The main block
  is the `robust.binary` block of `explore/0007_gold_first_stage.py`,
  copied, with its own randomisation draws (seed 20261113), Conley errors
  and event study. The report-only blocks (secondary outcomes, placebos,
  why density failed, sturdiness) are read by no rule.
- **s3-s8.** Homicides, annual population and mining-sector receipts from
  Base dos Dados on BigQuery, then `politics_panel`, sealed by half.
  Copied from 0007's drafts s16 and s19 with only the campaign, idea and
  step references changed. s4 and s5 run at the same time; s7 waits only
  on s6.
- **s9, s10 (final).** 0007's draft s22 with the main exposure changed to
  `geo_exposed`; the density and pre-2000 titles become robustness
  exposures. The nine outcomes, their order, the money rule,
  Benjamini-Hochberg, randomisation inference (seed 20261111, as there),
  event study, placebos, legal regimes and legal access stay as written.

One task is in flight per campaign, so the tasks run s1, s3, s6, s9. The
politics phase starts only after s2 survives. No other variant runs.

### Definitions fixed in the drafts that the brief left open

Suggested by Claude, listed here for Gabriel's review before merging:

- `density.top1_share` divides the largest |E × (share 2007 − share 2006)|
  by the sum over **all** sample municipalities, not over the top five.
- The density drop rules re-estimate the density first stage (E × ln P,
  otherwise the main design) without those municipalities.
- The 1990-2012 and 2013-2024 F statistics rebuild the fixed effects and
  control × year dummies on those years.
- s9's robustness keys are `robust.density_*` and `robust.titles_*`
  (0007's were `titles_*` and `binary_*`).
- The two test files are named `tests/test_explore_gold_yes_no_first_stage.py`
  and `tests/test_explore_gold_yes_no_politics.py`.

## Kill rules and why

Gabriel stated every rule in his brief (section 7) and confirmed all four
on 2026-11-13 after the plain-words read-back. They are idea 0007's own
rules and thresholds, unchanged. None is a p-value rule, so none stops a
valid design at a fixed rate by chance (the card's false-stop sum is 0).
The brief called them g1-g3; the validator accepts only ids `k1`, `k2`, ...

- **Gate (s2), `on_kill: stop`.**
  - k1 (F below 10): the usual weak-instrument line. **Honest note:** k1 is
    close to a re-check. The yes/no F on this same data is already known
    to be 12.28, so it guards against a coding or data change, not against
    a weak design.
  - k2 (lead ratio above 0.5): **new information**. The pre-trend check has
    not been run for the yes/no measure. Campaign 0007's read-back warned
    that the 1990s real gold price was above its 2000 level, so a valid
    design can have non-zero leads; Gabriel kept 0.5 then and now.
  - k3: catches broken numbers.
- **Final (s10), `on_kill: stop`.** k1 catches broken numbers; the
  politics results themselves are the report.

The real test of the first stage is the sealed half, later.

## Budget and why

`scripts/budget.py` (2026-11-13): median 3 and 90th percentile 5 model
jobs per task; explore runs under an hour. Gabriel stated every number in
his brief:

- **max_tasks 5:** the four task steps, plus one spare.
- **max_pipeline_runs 6:** the four pipeline steps; the tick counts a step
  once however often it retries, so the two spares are unlikely to be used.
- **max_explore_runs 2:** the two explore runs.
- **max_model_jobs 40:** three tasks that read new data (s3, s6, s9) at
  about 7 jobs each and s1 at about 5 = 26, plus two self-repairs at about
  5 each = 10, plus 4 to spare.
- **end_by 2026-11-27:** 14 days from the day this PR opens. Campaign 0007
  took 45.1 hours for 15 steps; budget.py suggests 11 days and errs long.
- **When the budget runs out:** no new step starts, what is in flight
  finishes, and the close-out follows.

## New data

Four datasets, all from campaign 0007's campaign file, with its sources,
fallbacks, licences and identifier rules. A GitHub runner has already
reached Base dos Dados on BigQuery (`data/manifests/acquire/ibama_autos.json`,
`inep_schools.json`), so the host is not new; the three tables are.
`self_repair: true` lets a failing data step get one repair task (for
example, switching to the fallback below).

| Dataset | What | Licence | Size | Identifiers | Fallback |
| --- | --- | --- | --- | --- | --- |
| `sim_homicides` | deaths by assault, year × municipality of occurrence | unknown (BD); public (DATASUS) | < 1 GB | none | `municipio_causa` (by residence, not occurrence); DATASUS FTP `.dbc` files need a decompressor the project lacks |
| `ibge_population_annual` | population by municipality and year | public (IBGE) | < 1 GB | none | `basedosdados.br_ms_populacao.municipio` (2000-2025) |
| `tse_receipts` | receipts summed by year, municipality, office and donor CNAE; no CPF, CNPJ or name | CC BY (TSE) | < 1 GB | none | TSE's own zips (`prestacao_contas_2004.zip`, `_2008.zip`, `prestacao_final_2012.zip`); only 2012 carries a donor sector, as text |
| `politics_panel` | built, municipality × election, sealed by half | public | < 1 GB | none | — |

The `politics_panel` catalog entry (name, derived and sealed paths) exists
from the campaign 0007 PR, and its sealed line is already pinned in
`tests/test_split.py`, so this PR does not add it. SIM stays in raw, which
no exploration account reads.

## What would change the plan

- k1 passes but k2 is close to 0.5: the yes/no measure has pre-trends of
  its own; read the politics phase as weaker.
- `sturdy.loso_min_f` far below 10, or `sturdy.f_drop_top5_garimpo` far
  below 10: the yes/no F rests on one state or a few municipalities.
- `density.top1_share` large: the density measure failed because of one
  municipality's 2006-2007 jump, which says more about the data than about
  gold.
- `sturdy.f_1990_2012` and `sturdy.f_2013_2024` very different: the first
  stage lives in one period.
- The money outcome runs only if at least two of 2004, 2008 and 2012 have
  receipts with a donor CNAE (the s9 rule). If not, the report says why.
- The close-out may recommend **at most one** design for the sealed half.

## Provenance

- **Stated by Gabriel in his brief** ("Campaign 0008 brief: the yes/no gold
  fork of campaign 0007", 2026-11-13, written in claude.ai):
  - idea 0007 closes as `dead` (he approves PR #375 as written; merged,
    campaign 0007 is `done`);
  - the yes/no measure is explored as new idea 0008, with 0007's kill
    rules and thresholds unchanged;
  - the idea file's question, origin and kill criteria; the design of its
    section 4; the ten steps and their order; the s1 draft (section 6);
    s3, s6 and s9 copied from 0007's drafts with only the listed changes;
  - every kill rule and threshold, and `on_kill: stop` at both runs;
  - the budget, `end_by` (14 days), `self_repair: true`,
    `referee_not_applicable_ok: [R5]` and status `active`;
  - `oversize_reason`, in his words: "This is the fork of campaign 0007.
    It continues 0007's skipped politics phase on the yes/no gold measure,
    using 0007's own drafts, in one campaign so I am not needed in
    between."
  - he starts before reading the closest papers (Carreri and Dube 2017;
    Idrobo, Mejía and Tribín 2014; Moreno-Louzada, Figueira and Picchetti
    2025);
  - the close-out may recommend at most one design for the sealed half.
- **Confirmed by Gabriel on 2026-11-13**, in this session, after Claude
  read them back in plain words: the four kill rules ("Confirm all four").
- **Repo rules applied where stricter than the brief:**
  - kill rule ids `k1`-`k3`, not `g1`-`g3` (the validator);
  - idea 0008 joins `NATIONAL_IDEAS` in `src/terrain/explore.py` (as idea
    0007 did in its campaign PR), so `tests/test_explore.py` checks that
    its scripts read both exploration lists; this is an owned file, for
    Gabriel's review;
  - the idea file is `exploring` in this PR (an active campaign's idea
    must be), with a `proposed` line and an `exploring` line under Status.
- **Where the brief and the repo disagree:** the brief asks to copy idea
  0007's "four tests (headline, citation, policy, memory)". Idea 0007's
  file has no such tests; they were in Gabriel's 0007 brief, which is not
  in the repository. The idea file therefore carries 0007's Claim and
  Prediction with the measure changed, and no four tests.
- **Suggested by Claude, not separately confirmed:** the definitions under
  "Definitions fixed in the drafts", the campaign title and slug, and the
  wording of the novelty table.
- **Novelty and probe (skill stages 3 and 4):** the web check was not
  repeated (campaign 0007's, of 2026-11-11, covers the same question). The
  gate s1-s2 is itself a probe on data already in the bucket, placed
  first, so no separate probe campaign is needed.
