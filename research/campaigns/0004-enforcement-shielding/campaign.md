---
id: "0004"
title: "Does IBAMA enforcement fall less near a close council winner's stronghold?"
status: active
idea: "0005"
owner: gabrielsgaspar
created: 2026-11-09
end_by: 2026-11-20
budget:
  max_tasks: 4
  max_explore_runs: 2
  max_pipeline_runs: 3
  max_model_jobs: 28
referee_not_applicable_ok: [R5]
datasets:
  - name: ibama_autos
    source: "IBAMA open-data portal, dataset fiscalizacao-auto-de-infracao, with its coordinates file; fallback in the same run: Base dos Dados on BigQuery, table basedosdados.br_ibama_fiscalizacao.auto_infracao (URLs and table ids in data/catalog.yaml)"
    licence: "IBAMA enforcement records published under Brazil's federal open-data policy; IBAMA's portal lists 'Outra (Aberta)', Base dos Dados lists 'Desconhecida'. Accepted by Gabriel on 2026-11-09 for research use; only cell-level counts are published."
    max_size_gb: 2
    identifiers: none
  - name: ibama_embargos
    source: "IBAMA open-data portal, dataset fiscalizacao-termo-de-embargo; fallback in the same run: Base dos Dados on BigQuery, table basedosdados.br_ibama_fiscalizacao.area_embargada (URLs and table ids in data/catalog.yaml)"
    licence: "IBAMA enforcement records published under Brazil's federal open-data policy; IBAMA's portal lists 'Outra (Aberta)', Base dos Dados lists 'Desconhecida'. Accepted by Gabriel on 2026-11-09 for research use; only cell-level counts are published."
    max_size_gb: 2
    identifiers: none
  - name: cell_enforcement
    source: "built from ibama_autos, ibama_embargos, ibge_boundaries_2024 and grid_cells; split by half like cell_outcomes"
    licence: "as ibama_autos and ibama_embargos"
    max_size_gb: 2
    identifiers: none
steps:
  - id: s1
    kind: task
    type: build
    draft: drafts/s1.md
    allowed_paths:
      - src/terrain/bigquery.py
      - src/terrain/ibama.py
      - pipeline/acquire/ibama_autos.py
      - pipeline/acquire/ibama_embargos.py
      - data/catalog.yaml
      - data/contracts/ibama_autos.md
      - data/contracts/ibama_embargos.md
      - tests/test_bigquery.py
      - tests/test_acquire_ibama.py
    after: []
  - id: s2
    kind: pipeline_run
    stage: acquire
    target: ibama_autos
    dataset: ibama_autos
    after: [s1]
  - id: s3
    kind: pipeline_run
    stage: acquire
    target: ibama_embargos
    dataset: ibama_embargos
    after: [s1]
  - id: s4
    kind: task
    type: build
    draft: drafts/s4.md
    allowed_paths:
      - src/terrain/builds/cell_enforcement.py
      - pipeline/build/cell_enforcement.py
      - data/catalog.yaml
      - data/contracts/cell_enforcement.md
      - tests/test_build_cell_enforcement.py
    after: [s2, s3]
  - id: s5
    kind: pipeline_run
    stage: build
    target: cell_enforcement
    dataset: cell_enforcement
    after: [s4]
  - id: s6
    kind: task
    type: explore
    draft: drafts/s6.md
    allowed_paths:
      - explore/0005_enforcement_power.py
      - tests/test_explore_enforcement_power.py
    after: [s5]
  - id: s7
    kind: explore_run
    script: 0005_enforcement_power
    after: [s6]
    kill_rules:
      - id: k1
        says: "Fewer than 3 of the elections 2008-2020 have at least half of their pre-election flora fines and embargoes located inside their own municipality (too few elections with usable locations)"
        field: coverage.elections_ok
        op: "<"
        value: 3
        confirmed: true
      - id: k2
        says: "Fewer than 400 located pre-election flora fines and embargoes, pooled 2008-2020, in the cells exposed to close pairs at 0.50% (enforcement too rare near strongholds to estimate anything)"
        field: counts.pre_reach_actions
        op: "<"
        value: 400
        confirmed: true
      - id: k3
        says: "The minimum detectable effect at 80% power (5%, two-sided) at the registered 0.25% window is above 25% of the pre-election baseline mean (could not detect a 25% change)"
        field: power.mde_share_025
        op: ">"
        value: 0.25
        confirmed: true
      - id: k4
        says: "Pre-election placebo at 0.50%: randomisation-inference p below 0.10 (winners' and losers' areas already differed in enforcement before the election)"
        field: placebo.ri_p_050
        op: "<"
        value: 0.10
        confirmed: true
    on_kill: stop
  - id: s8
    kind: task
    type: explore
    draft: drafts/s8.md
    allowed_paths:
      - explore/0005_enforcement_effects.py
      - tests/test_explore_enforcement_effects.py
    after: [s7]
  - id: s9
    kind: explore_run
    script: 0005_enforcement_effects
    after: [s8]
    kill_rules:
      - id: k1
        says: "Some estimate, share or RI p-value of the post-election effects is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0004: Does IBAMA enforcement fall less near a close council winner's stronghold?

## Question

After a close council win, does federal environmental enforcement fall less
often near the winner's polling-station stronghold than near the loser's?
Enforcement here means IBAMA flora fines and embargoes. This is idea 0005
(`research/ideas/0005-enforcement-shielding.md`), linked to idea 0001. It
keeps idea 0001's direct design (decisions 0004 and 0005) and swaps the
outcome: flora fines plus embargoes per 1 km cell in the four years after
the election (t+1 to t+4). Elections are 2008-2020 and only the exploration
half is used. The effect is a share of the pre-election baseline mean, read
as decision 0007 reads it. The test is two-sided; shielding predicts a
negative sign.

The campaign estimates enforcement only. It does not condition on clearing
and uses no per-hectare ratio, because clearing is itself affected by the
treatment. Reading this estimate together with idea 0001's clearing result
comes later and is not a step here.

## Already known

Tier 1 (this repository) and tier 2 (Zotero notes) are authoritative.
Every tier 3 (web) find is **unverified**: it was found on the web and is
still to be checked. None of the web papers is in `research/references/`.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| IBAMA fines or embargoes in this project | new | no idea, dataset, run, decision or lesson mentions IBAMA, fines or embargoes (`novelty_scan.py`, 2026-11-09) |
| Electoral effects on deforestation in Brazil (8-10%) | explored | Pailler (2018), via `balboniEconomicsTropicalDeforestation2023` (p. 746); decision 0007 uses it as an anchor |
| Jurisdictions and deforestation, with election timing | explored (Indonesia) | `burgessPoliticalEconomyDeforestation2012`: 8.2% per extra district; the pre-election logging result is in the NBER working paper, not the QJE paper (decision 0007) |
| Mayors, landholder donors and enforcement on their own land | partly explored | (web, unverified) Katovich and Moffette, "Does Local Politics Drive Tropical Land-Use Change? Property-Level Evidence from the Amazon", manuscript of 2025-10-30 (the file is still named "Local Politics of Land Use"). Close mayoral races; "violations" are IBAMA embargoes, 2005-2020. Violations rise 15% under mayors with at least 25% of donations from landholders. The **27% in the paper is rural credit**, not violations. On candidates' own properties, violations "weakly decrease" ("political cover"). <https://ekatovich.github.io/files/Katovich_Moffette_Local_Politics_of_Land_Use.pdf> |
| Farmer mayors, deforestation and PPCDAm | partly explored | (web, unverified) Bragança and Dahis, "Cutting Special Interests by the Roots: Evidence from the Brazilian Amazon", CPI Working Paper 004 (2021); J. Public Econ. 215 (2022) 104753. In close races, farmer mayors raised deforestation before PPCDAm and not after |
| Strategic redistribution of enforcement and electoral backlash | partly explored | (web, unverified) Beramendi and Goncalves, "The Political Logic of Persistent Deforestation: Electoral Incentives and Public Goods in the Brazilian Amazon", working paper (2026-01-26). Leniency for core supporters; in a local-randomisation RD on narrow municipal PT presidential wins, aligned municipalities get 4.5 fewer fines and 6.5 fewer embargoes than expected. Presidential level, municipality unit |
| Electoral cycles in deforestation | explored | Pailler (2018), JEEM 88:345-365 (as above; enforcement not studied) |
| Close local races and enforcement elsewhere | partly explored | (web, unverified) Harding, Prem, Ruiz and Vargas, "Buying a Blind Eye", APSR 118(2) 2024 (Colombia, mayors, donors); Innes and Mitra, Econ. Inquiry 53(1) 2015 (US, inspections); Holland, "Forbearance", APSR 110(2) 2016 (concept) |
| Enforcement near a council winner's vote base against the loser's | **new** | no paper found on council members (vereadores) and IBAMA enforcement, nor on a close-race contrast of enforcement inside a municipality |

The within-municipality contrast is new. Idea 0001's fixed effects absorb
municipal-level enforcement (its Design section). This campaign asks
whether enforcement moves *inside* the municipality, between the winner's
and the loser's areas. The nearest result is Beramendi and Goncalves, at
presidential level and across municipalities. Gabriel may want to add the
web finds to `terrain-inbox`.

## Steps and why

The step numbers differ from Gabriel's brief, because step ids cannot
repeat: his "s6 task + explore_run" is s6 and s7 here, and his "s7" is s8
and s9.

- **s1** (build task, `drafts/s1.md`): the two acquire scripts. Each tries
  IBAMA's portal first and falls back in the same run to Base dos Dados on
  BigQuery. It also adds the catalog entries, the data contracts and tests
  on data built inside the tests. Nothing with a personal identifier is
  ever stored, and on the BigQuery path it is never downloaded.
- **s2, s3** (acquire runs): `ibama_autos`, then `ibama_embargos`. The
  manifests record the source used, the query, `max(data_extracao)`, and
  the distinct `tipo_infracao` and `tipo_area` values that s4's filter is
  checked against. s4 comes after both, so its planner can read those
  manifests.
- **s4** (build task, `drafts/s4.md`): `cell_enforcement`. Per cell and
  year, it counts flora fines (cancelled ones excluded) and embargoes whose
  point lies inside their own municipality's polygon. It also writes a
  municipality-by-year table of all and located records for the coverage
  check. Exploration rows go to derived, confirmation rows only to
  `sealed/outcomes/cell_enforcement/`.
- **s5** (build run): builds it.
- **s6, s7** (explore task and run, `drafts/s6.md`): pre-election years
  only. They measure location coverage, the number of actions near
  close-pair strongholds, power at 0.25% and 0.50%, and the 0.50% placebo.
  This is the gate: if any of k1-k4 fires, the campaign stops before any
  post-election year is read.
- **s8, s9** (explore task and run, `drafts/s8.md`): the post-election
  effect at 0.50%, for fines plus embargoes pooled (primary) and for each
  separately (secondary), with RI p-values. It is written only after s7
  survives.

No other variant runs. Ideas for variants go in the close-out report.

### Windows (decision 0008 checked)

Decision 0008 does **not** forbid pre-election outcome work at 0.25% on the
exploration half. Its own power table is exactly that (pre-election
clearing at 0.25%). What it rules out is re-running a post-election
estimate at 0.25% (section "What it means for task B's 0.50% result"). So
s6 computes power at 0.25% and 0.50% on pre-election years, as Gabriel
asked. s6's placebo and every estimate in s8 use 0.50% only. Neither
script imports `terrain.registered`, which refuses 0.25% before
registration (campaign 0003's precedent).

A caveat Gabriel already knows: decision 0008 found 0.50% unbalanced on
incumbency (omnibus p 0.119). s8's estimates carry decision 0008's caveat,
as task B's did. The s7 placebo (k4) is the enforcement-specific check of
that balance.

## Kill rules and why

All stated and confirmed by Gabriel on 2026-11-09; `on_kill: stop` for s7
and for s9.

- **s7 k1** (`coverage.elections_ok < 3`). Too few elections with usable
  locations. For each election, coverage is the share of pre-election flora
  fines and embargoes, in exploration-half Legal Amazon municipalities,
  whose point passes *our* own-polygon check. An election is "ok" at 0.5
  or above. It is a data count, not an outcome result.
- **s7 k2** (`counts.pre_reach_actions < 400`). Enforcement too rare near
  strongholds. These are located pre-election actions, pooled 2008-2020, in
  the cells exposed at 0.50%: the cells with D ≠ 0, which also give the
  baseline of the effect share. The "exposed cells" reading of "the 10 km
  reach of close-pair strongholds" was suggested by Claude and confirmed
  by Gabriel on 2026-11-09 (see Provenance).
- **s7 k3** (`power.mde_share_025 > 0.25`). Underpowered at the registered
  window. Decision 0007's method gives the MDE: 2.8 × the re-flip SD of the
  pre-election slope, times mean |D|, over the baseline mean. The 0.25 is
  anchored to Katovich & Moffette's estimates of violations under landholder-financed mayors (15% or 27% depending on the version of the paper; unverified web find). Gabriel kept 0.25 on 2026-11-09.
- **s7 k4** (`placebo.ri_p_050 < 0.10`). A non-flat placebo at 0.50%. This
  is idea 0001's kill criterion 2 with a looser bar (0.10 rather than
  0.05), as `kill-rules.md` suggests for placebos.
- **s9 k1** (`estimates.finite != true`). Plausibility. Any non-finite
  estimate, share or p stops the campaign. It cannot be met by a sign or a
  size, so the post-election estimate itself kills nothing: it is reported.

The rules read only fields the drafts make the scripts write, and every key
is free of dots. If a field is missing, the step stops as "unreadable"; it
never passes.

## Budget and why

`budget.py` (18 recent agent tasks: median 3 model jobs, 90th percentile 4)
suggests 4 tasks, 2 explore runs, 3 pipeline runs, 20 model jobs and 8
days. Gabriel stated:

- **max_tasks 4:** s1, s4, s6 and s8.
- **max_pipeline_runs 3:** s2, s3 and s5. A failed run is not retried, so
  an acquire that fails on both sources blocks its step for Gabriel.
- **max_explore_runs 2:** s7 and s9.
- **max_model_jobs 28:** four tasks at about 7 each (the rule of thumb for
  a task that reads new data): 3 for a clean task plus two fix rounds.
- **end_by 2026-11-20:** eleven days. The nine steps take about five to six
  days at 4 to 6 ticks per task and run. That leaves room for one 24-hour
  block and the close-out.

When a number runs out, no new step starts and the close-out reports why.

## New data

- **ibama_autos:** IBAMA infraction notices (autos de infração).
  - The portal is tried first. If any download or check fails, the whole
    dataset comes from Base dos Dados (`basedosdados.br_ibama_fiscalizacao.auto_infracao`:
    711,140 rows and 141 MB uncompressed for all of Brazil, per its
    metadata API on 2026-11-09).
  - The query selects only `ano`, `data_auto`, `id_auto`, `id_municipio`,
    `sigla_uf`, `latitude`, `longitude`, `tipo_infracao`, `tipo_auto`,
    `situacao_auto`, `indicador_cancelado`, `gravidade`,
    `indicador_coordenada_valida` and `data_extracao`. `data_extracao` is
    added so that `max(data_extracao)` comes from the result, as Gabriel
    asked; it is a date, not an identifier.
  - Rows: Legal Amazon states, `ano` 2000-2025. Stored as one Parquet in a
    new dated raw folder.
- **ibama_embargos:** IBAMA embargo terms.
  - Same order of sources (`area_embargada`: 116,332 rows, 18 MB).
  - Columns: `ano`, `data_embargo`, `id_embargo`, `id_auto`,
    `id_municipio`, `sigla_uf`, `latitude`, `longitude`, `area_ha`,
    `tipo_area`, `indicador_desembargado`, `indicador_coordenada_valida`
    and `data_extracao`.
- **cell_enforcement:** the build of s4, sealed like `cell_outcomes`
  (decision 0003).
- **Licences:** "IBAMA enforcement records published under Brazil's federal open-data policy; IBAMA's portal lists 'Outra (Aberta)', Base dos Dados lists 'Desconhecida'. Accepted by Gabriel on 2026-11-09 for research use; only cell-level counts are published."
- **Identifiers:** none.
  - The BigQuery query never selects `cpf_cnpj_*`, `nome_*`, `nome_imovel`
    or `geometria`, and the query builder refuses those names.
  - The portal path downloads files that hold names and CPF/CNPJ. It drops
    them in memory, before anything is stored.
  - Polygons are not used.
- **Gabriel's open question 2:** no repo rule requires raw files to be
  stored unchanged; `data/raw/` must only be write-once. These are the
  first acquirers that store a filtered file rather than the publisher's
  bytes. The manifest records the source and query, so the raw folder can
  be re-derived.

### What the portal path can do today

IBAMA's portal answered every automated request with HTTP 403 (a Cloudflare
firewall) on 2026-11-09. So its column names, delimiter and encoding could
not be profiled, and `AGENTS.md` says not to guess them. s1 therefore puts
the portal's column mapping in the catalog. Each field is either filled
from IBAMA's dictionary as search snippets report it or left `null`. A
`null` field, a missing column or any failed request makes the portal
check fail, and the run moves to Base dos Dados in the same run. The
portal is still probed with one header-only request, so the manifest says
whether it was reachable. Until someone profiles the files and fills the
mapping (a person's catalog edit), **Base dos Dados will be the source**.

### Sealing (Gabriel's open question 1)

This PR drafts the owned change for Gabriel's review:

- `tests/test_split.py`: `SEALED` gains
  `"cell_enforcement": "sealed/outcomes/cell_enforcement/"`.
- `data/catalog.yaml`: a planned `cell_enforcement` entry with its `derived`
  and `sealed` lines. It must land with the test change, or
  `test_catalog_sealed_lines_are_the_known_ones` fails. s4 adds the
  contract and the notes but never changes those lines.

No GCP change is needed. `scripts/gcp/setup_gcs.sh` already gives
`terrain-build` create-only on all of `sealed/outcomes/`, and gives
`terrain-analysis` nothing there. Unlike `cell_outcomes`, the new build's
files are not owned in `CODEOWNERS`; if they were, the gate could not
merge s4. Gabriel may want to own them after the campaign.

## What would change the plan

- The acquire manifests show no `tipo_infracao` value that normalises to
  "flora": s4 stops by design. The flora filter needs Gabriel.
- Both sources fail for a dataset (s2 or s3 blocked): fix the access, for
  example a missing BigQuery role or a quota, and restart the run.
- Our own-polygon check and `indicador_coordenada_valida` disagree often
  (s5 notes): the location rule needs a look before s7's coverage is
  trusted.
- s7 coverage is fine before 2012 only, or after 2016 only: the pooled
  estimate leans on a few elections.
- Any of k1-k4 fires: the campaign stops before a post-election year is
  read. The close-out says which rule fired and by how much.
- s9 gives a negative pooled estimate with RI p < 0.05. That is not a
  finding on this half; it would argue for registering the outcome next to
  idea 0001's plan, after Gabriel's review.
- Any run reads `sealed/`, `confirm/` or a post-election year before s8,
  or imports `terrain.registered`: stop everything.

## Provenance

Stated by Gabriel on 2026-11-09:

- The idea, the question, the design (idea 0001's direct exposure and
  estimator, elections 2008-2020, t+1 to t+4, effect as a share of the
  pre-election baseline, two-sided), and the bar on conditioning on
  clearing.
- The windows: power at 0.25% and 0.50%, estimates at 0.50% only.
- Idea file 0005 (status proposed, linked to 0001, the s7 rules as its kill
  criteria).
- The three datasets, their URLs, `max_size_gb` 2, `identifiers: none`,
  dropping names, CPF/CNPJ and free text before storing, both record
  formats, and sealing `cell_enforcement` like `cell_outcomes`.
- From the amendment of the same day:
  - the source order and automatic fallback;
  - the Base dos Dados tables, columns and filters;
  - the REST API through `AuthorizedSession`, with a 20 GB billing cap and
    location US;
  - excluding cancelled fines and keeping flora only at build;
  - listing the distinct values in the manifest;
  - our own-polygon check for both sources, with agreement against
    `indicador_coordenada_valida` reported;
  - recording each source's licence; the licence text and its acceptance
    for research use (2026-11-09).
- All steps and their order; no other variants.
- Every kill rule, threshold and `on_kill`, confirmed:
  - k3 kept at 0.25 and its reason reworded by him on 2026-11-09:
    "anchored to Katovich & Moffette's estimates of violations under landholder-financed mayors (15% or 27% depending on the version of the paper; unverified web find)";
  - no enforcement data had been seen by anyone in the project.
- The budget, `end_by` eleven days from 2026-11-09, `status: active` and
  `referee_not_applicable_ok: [R5]`.
- The novelty check across the repo, Zotero and the web, with the five
  required citations.

Suggested by Claude, confirmed by Gabriel on 2026-11-09:

- **Renumbering:** Gabriel's s6 and s7 become s6/s7 and s8/s9, because step
  ids cannot repeat.
- **Portal column mapping in the catalog** with `null` for unknown fields,
  and a header-only probe of the portal. The portal path stays dormant
  until the mapping is filled.
- **Reading GCP_PROJECT_ID:** the data-pipeline job does not export it, so
  the code reads `GOOGLE_CLOUD_PROJECT`. The auth step sets it to the same
  project, as `terrain.earthengine` already relies on.
- **Catalog holds the endpoint and scope:** `tests/test_acquire.py` forbids
  `https://` in code, so the BigQuery endpoint and OAuth scope also go in
  the catalog.
- **`data_extracao` in the select list,** for `max(data_extracao)`.
- **"Reach" read as exposed cells:** "within the 10 km reach of close-pair
  strongholds" (k2) means cells with D ≠ 0 at 0.50%.
- **Coverage population:** coverage uses every exploration-half Legal
  Amazon municipality.
- **Located:** a located record's 1 km cell must also belong to the same
  municipality in `grid_cells`, so a border point cannot leak across
  halves.
- **Normalised value sets** for the flora and cancelled filters, and for
  the agreement check: any value outside the sets stops the build.
- **Notes for the exploration half only:** manifest notes and error
  messages give counts for the exploration half only, so no
  confirmation-half count can be recovered by subtraction.
- **One file per year** for `cell_enforcement`, so each explore script
  reads only its years (referee R2).
- **No `harness/issue-drafts/README.md` change:** this campaign moves no
  harness draft, unlike campaign 0002, which moved draft 40.
