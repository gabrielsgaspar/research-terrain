---
id: "0005"
title: "Do narrow council winners' voters' places get more of the state?"
status: stopped
idea: "0006"
owner: gabrielsgaspar
created: 2026-11-10
end_by: 2026-12-11
budget:
  max_tasks: 7
  max_explore_runs: 2
  max_pipeline_runs: 12
  max_model_jobs: 45
referee_not_applicable_ok: [R5]
datasets:
  - name: tse_votes_by_section
    source: "TSE, votacao_secao_<year>_<uf>.zip at cdn.tse.jus.br (URL in data/catalog.yaml), extended from 9 to the 26 states that elect councils"
    licence: "public (TSE electoral data repository), as data/catalog.yaml already states it"
    max_size_gb: 20
    identifiers: none
  - name: tse_polling_places
    source: "TSE, eleitorado_local_votacao_<year>.zip at cdn.tse.jus.br; already one national file per year"
    licence: "public (TSE electoral data repository), as data/catalog.yaml already states it"
    max_size_gb: 1
    identifiers: none
  - name: polling_places
    source: "built from tse_polling_places, polling_stations_geocoded and municipalities; national"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
  - name: section_votes
    source: "built from tse_votes_by_section, tse_results and municipalities; national"
    licence: "public, as its sources"
    max_size_gb: 10
    identifiers: none
  - name: inep_schools
    source: "INEP Censo Escolar via Base dos Dados on BigQuery, table basedosdados.br_inep_censo_escolar.escola, 2007-2024 (table id and columns in data/catalog.yaml)"
    licence: "INEP publishes its open data under CC BY-ND 3.0 (a site-wide statement at gov.br/inep); Base dos Dados states no licence for the table and refers to the source's terms. Estimates can be published; school-level derived tables may not be shareable."
    max_size_gb: 2
    identifiers: none
  - name: inep_school_catalogue
    source: "INEP, Microdados do Censo Escolar 2024 (download.inep.gov.br), with coordinates from INEP's Catálogo de Escolas via Base dos Dados, table basedosdados.br_bd_diretorios_brasil.escola"
    licence: "INEP publishes its open data under CC BY-ND 3.0 (a site-wide statement at gov.br/inep); Base dos Dados states no licence for the table and refers to the source's terms. Estimates can be published; school-level derived tables may not be shareable."
    max_size_gb: 1
    identifiers: none
  - name: school_polling_match
    source: "built from polling_places and inep_school_catalogue"
    licence: "as inep_school_catalogue"
    max_size_gb: 1
    identifiers: none
  - name: viirs_annual
    source: "NOAA/EOG VIIRS Nighttime Lights annual composites, Earth Engine NOAA/VIIRS/DNB/ANNUAL_V21 (2013-2021) and NOAA/VIIRS/DNB/ANNUAL_V22 (2022-2024), band average_masked"
    licence: "Public domain per the Earth Engine catalog; EOG states that many of its VIIRS Nighttime Lights data are under CC BY 4.0. Cite Elvidge et al. (2021) and EOG."
    max_size_gb: 2
    identifiers: none
  - name: mapbiomas_coverage_national
    source: "MapBiomas Brasil Collection 10 coverage, Earth Engine projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_coverage_v2"
    licence: "CC BY 4.0, with MapBiomas' required citation (MapBiomas states CC BY 4.0 on the Earth Engine catalog, its site and its Dataverse)"
    max_size_gb: 5
    identifiers: none
  - name: place_outcomes
    source: "built from polling_places, school_polling_match, inep_schools, viirs_annual, mapbiomas_coverage_national and ibge_boundaries_2024; split by half like cell_outcomes"
    licence: "as inep_schools, viirs_annual and mapbiomas_coverage_national"
    max_size_gb: 5
    identifiers: none
steps:
  - id: s1
    kind: task
    type: build
    draft: drafts/s1.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/polling_places.py
      - src/terrain/builds/section_votes.py
      - pipeline/build/polling_places.py
      - pipeline/build/section_votes.py
      - data/contracts/polling_places.md
      - data/contracts/section_votes.md
      - tests/test_build_polling_places.py
      - tests/test_build_section_votes.py
    after: []
  - id: s2
    kind: pipeline_run
    stage: acquire
    target: tse_votes_by_section
    dataset: tse_votes_by_section
    after: [s1]
  - id: s3
    kind: pipeline_run
    stage: acquire
    target: tse_polling_places
    dataset: tse_polling_places
    after: [s1]
  - id: s4
    kind: pipeline_run
    stage: build
    target: polling_places
    dataset: polling_places
    after: [s3]
  - id: s5
    kind: pipeline_run
    stage: build
    target: section_votes
    dataset: section_votes
    after: [s2]
  - id: s6
    kind: task
    type: build
    draft: drafts/s6.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/bigquery.py
      - src/terrain/inep.py
      - pipeline/acquire/inep_schools.py
      - pipeline/acquire/inep_school_catalogue.py
      - data/contracts/inep_schools.md
      - data/contracts/inep_school_catalogue.md
      - tests/test_acquire_inep.py
    after: [s1]
  - id: s7
    kind: pipeline_run
    stage: acquire
    target: inep_schools
    dataset: inep_schools
    after: [s6]
  - id: s8
    kind: pipeline_run
    stage: acquire
    target: inep_school_catalogue
    dataset: inep_school_catalogue
    after: [s6]
  - id: s9
    kind: task
    type: build
    draft: drafts/s9.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/school_polling_match.py
      - pipeline/build/school_polling_match.py
      - data/contracts/school_polling_match.md
      - tests/test_build_school_polling_match.py
    after: [s6]
  - id: s10
    kind: pipeline_run
    stage: build
    target: school_polling_match
    dataset: school_polling_match
    after: [s4, s8, s9]
  - id: s11
    kind: task
    type: build
    draft: drafts/s11.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/earthengine.py
      - tests/test_earthengine.py
      - pipeline/acquire/viirs_annual.py
      - pipeline/acquire/mapbiomas_coverage_national.py
    after: [s9]
  - id: s12
    kind: pipeline_run
    stage: acquire
    target: viirs_annual
    dataset: viirs_annual
    after: [s11]
  - id: s13
    kind: pipeline_run
    stage: acquire
    target: mapbiomas_coverage_national
    dataset: mapbiomas_coverage_national
    after: [s11]
  - id: s14
    kind: task
    type: build
    draft: drafts/s14.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/place_outcomes.py
      - pipeline/build/place_outcomes.py
      - data/contracts/place_outcomes.md
      - tests/test_build_place_outcomes.py
    after: [s11]
  - id: s15
    kind: pipeline_run
    stage: build
    target: place_outcomes
    dataset: place_outcomes
    after: [s4, s7, s10, s12, s13, s14]
  - id: s16
    kind: task
    type: explore
    draft: drafts/s16.md
    allowed_paths:
      - explore/0006_feasibility.py
      - tests/test_explore_representation_feasibility.py
    after: [s5, s15]
  - id: s17
    kind: explore_run
    script: 0006_feasibility
    after: [s16]
    kill_rules:
      - id: k1
        says: "Fewer than 10,000 close council pairs at the 0.50% window, pooled 2008-2020, in the exploration half"
        field: counts.pairs_050
        op: "<"
        value: 10000
        confirmed: true
      - id: k2
        says: "Less than 85% of the exploration half's sections, pooled 2008-2020, sit at a polling place located within 1 km error"
        field: coverage.located_share
        op: "<"
        value: 0.85
        confirmed: true
      - id: k3
        says: "Less than 50% of the exploration half's polling places, pooled 2008-2020, are matched to an INEP school at high or medium confidence"
        field: schools.match_share
        op: "<"
        value: 0.50
        confirmed: true
      - id: k4
        says: "The joint randomisation-inference test of the baseline school facility count, night lights and built-up share on D_p has p below 0.05 (unbalanced baselines)"
        field: balance.ri_p_joint
        op: "<"
        value: 0.05
        confirmed: true
      - id: k5
        says: "Pre-election placebo: D_p predicts the t-4 to t change in the municipal-school facility count with randomisation-inference p below 0.10"
        field: placebo.ri_p_school
        op: "<"
        value: 0.10
        confirmed: true
      - id: k6
        says: "The minimum detectable effect on the municipal-school facility count at 80% power (5%, two-sided) is above 0.10 standard deviations of the pre-election change"
        field: power.mde_sd_school
        op: ">"
        value: 0.10
        confirmed: true
    on_kill: stop
  - id: s18
    kind: task
    type: explore
    draft: drafts/s18.md
    allowed_paths:
      - explore/0006_effects.py
      - tests/test_explore_representation_effects.py
    after: [s17]
  - id: s19
    kind: explore_run
    script: 0006_effects
    after: [s18]
    kill_rules:
      - id: k1
        says: "Some estimate, standard error, effect in SD or adjusted p-value of the post-election effects is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0005: Do narrow council winners' voters' places get more of the state?

## Question

When a candidate narrowly wins a council seat, do their own voters' places
get more of the state during the term? This is idea 0006
(`research/ideas/0006-geography-of-representation.md`), across all of
Brazil (decision 0011). The unit is the polling place, and the school at
it where one is matched.

- **Treatment:** D_p, the narrow winners' share of the place's valid votes
  minus the narrow losers', summed over the municipality's close pairs.
- **Primary outcome:** the change from t to t+4 in the number of nine
  facilities at the municipal school that is the polling place.
- **Falsification:** the same outcome at state schools, which councils do
  not control.
- **Secondary outcomes:** night lights, built-up area and native-vegetation
  loss around the place.

Only the exploration half is used. The campaign stops before any
post-election year is read if the pre-election checks fail.

## Already known

Tier 1 (this repository) and tier 2 (Zotero notes) are authoritative.
Every tier 3 (web) find is **unverified**: it was found on the web and is
still to be checked. None of the web papers is in `research/references/`.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Close same-list council pairs, margins over valid votes | explored | `terrain.strongholds` (idea 0001; decisions 0004 and 0008); every explore run of idea 0001 |
| Public works steered to strongholds | named, not studied | `research/questions.md`, question 4 ("Mechanism"); no idea, run or lesson on schools, lights or built-up area (`novelty_scan.py`, 2026-11-10) |
| Schools, lights, INEP, VIIRS in this project | new | no dataset, run or decision mentions them |
| Exposure built from a known formula with random shocks | explored (method) | `borusyakNonrandomExposureExogenous2023`: recentre by the expected treatment. Here re-drawing each pair's winner makes E[D_p] = 0 given S_p, and S_p is controlled |
| Representatives favouring their home areas | explored (Norway) | `fivaLocalFavoritismAtlarge2016`: an aligned regional representative raises investment funding to their home municipality by about 600 NOK per capita (about 0.56 SD), in an RD on bloc majorities, with municipality as the unit |
| Open-list vote geography | explored (theory) | (web, unverified) Ames, "Electoral Strategy under Open-List Proportional Representation", AJPS 39(2) 1995, doi:10.2307/2111619; Ames, *The Deadlock of Democracy in Brazil*, 2001. Concentrated and scattered vote bases; deputies' amendments go where their votes are |
| Polling-station geocoding | explored (data) | (web, unverified for citation) Hidalgo, geocode_br_polling_stations, GitHub (already `polling_stations_geocoded`, v0.16); the README gives no citation yet ("Citation format to be added") |
| Councillors targeting their voters' neighbourhoods | partly explored | (web, unverified) Cooperman, Junqueira, Moreira and Muñoz, "Local Distributive Politics: Municipal Legislative Behavior and Neighborhood Service Provision in Brazil", SSRN 7376538 (2025): councillors with concentrated vote bases make more location-targeted requests (paving, traffic). These are requests, not delivered goods, and there is no close-race design. **Read in full before claiming novelty** |
| Within-municipality council vote geography | partly explored | (web, unverified) Gelape, Luz and Thomé, *Estudos Avançados* 38(111) 2024 (São Paulo 2020, descriptive); "Electoral Alliances and Spatial Patterns of Vote: Evidence from Brazilian Local Elections", *Political Behavior* (2026), no public-goods outcome |
| Deputies' amendments and vote bases | explored (federal) | (web, unverified) Firpo, Ponczek and Sanfelice, *J. Dev. Econ.* 116 (2015); Baião and Couto, *Opinião Pública* 23(3) 2017; Samuels, *JOP* 64(3) 2002; Pereira and Mueller, *Dados* 45(2) 2002; Mattos, Politi and Morata, *EJPE* 68 (2021) |
| School resources as an outcome of electoral rules | partly explored (mayors) | (web, unverified) Chin, "When Do Politicians Appeal Broadly?", IMF WP 21/227 (2021): two-round mayoral winners have more dispersed voters, and schools get more resources; lights do not differ |
| Night lights as an outcome | explored (method) | (web, unverified) Henderson, Storeygard and Weil, "Measuring Economic Growth from Outer Space", AER 102(2) 2012, doi:10.1257/aer.102.2.994; Hodler and Raschky, "Regional Favoritism", QJE 129(2) 2014 (leaders' birth regions) |
| Close council pairs × polling-place vote shares × Censo Escolar, VIIRS and MapBiomas outcomes | **new** | no paper found on this combination; the search would miss recent job-market papers |

What this campaign adds: delivered goods (not requests) at the voters' own
places, identified by close same-list pairs inside the municipality.
Gabriel may want to add Cooperman et al. (2025) and Chin (2021) to
`terrain-inbox`.

## Steps and why

The steps are Gabriel's. On 2026-11-10 he split his s6 and s10 into two
tasks each, so that no task changes more than about 8 files. The steps
are numbered so that ids do not repeat.

| Brief | Here | What | Files |
| --- | --- | --- | --- |
| s1 | s1 | national TSE tables (task) | 9 (two pipeline scripts are docstring-only) |
| s2-s5 | s2-s5 | acquire votes, acquire polling places, build polling places, build section votes | |
| s6 | s6 | INEP acquires (task) | 8 |
| | s9 | school match (task) | 5 |
| s7-s9 | s7, s8, s10 | the two INEP acquires, then the match build | |
| s10 | s11 | Earth Engine exports (task) | 5 |
| | s14 | `place_outcomes` (task) | 5 |
| s11-s13 | s12, s13, s15 | the two exports, then `place_outcomes` | |
| s14 + run | s16, s17 | feasibility task and run | 2 |
| task + run | s18, s19 | effects task and run | 2 |

- **s1** (build task, `drafts/s1.md`). Makes the four TSE tables national.
  - The votes catalog lists **26 states, not 27**: DF elects no council, and
    the TSE answers `votacao_secao_<year>_DF.zip` with a 1-byte file, which
    would fail the whole acquire (checked 2026-11-10).
  - The 182 zips are about 6.35 GB. SP 2020 alone is a 527 MB zip of
    roughly 6-8 GB of CSV, so the section reader is made to stream.
  - Polling places gain `nr_cep` for the school match.
  - Legal Amazon rows must come out unchanged.
- **s2-s5** (pipeline runs).
  - s2 acquires the votes. It re-downloads the nine Amazon states into the
    new folder, because the generic acquirer stores every listed file in
    one folder.
  - s3 acquires polling places. The TSE file is already national, so s3 is
    expected to report "unchanged" and finish an hour later, at no cost but
    one run.
  - s4 and s5 are the two national builds.
- **s6** (build task, `drafts/s6.md`): the acquirers of `inep_schools` (Base
  dos Dados, nine facility columns, 2007-2024) and `inep_school_catalogue`.
  - The catalogue's names, addresses and postcodes come from INEP's official
    2024 microdata.
  - Its coordinates come from INEP's school catalogue as copied by Base dos
    Dados. INEP's own catalogue is an interactive app, and its microdata
    have no coordinates.
  - INEP's server omits its intermediate certificate. **No certificate is
    stored.** At run time the acquirer downloads it from its issuer's public
    address, checks its SHA-256 against the fingerprint in the catalog, and
    only then adds it to the system trust store. TLS verification stays on.
- **s7, s8** (pipeline runs): the two acquires.
- **s9** (build task, `drafts/s9.md`): `school_polling_match`, with fixed
  rules and thresholds.
- **s10** (pipeline run): the match, on the national polling places (after
  s4) and the catalogue (after s8).
- **s11** (build task, `drafts/s11.md`): `viirs_annual` and
  `mapbiomas_coverage_national`. These are national Earth Engine exports on
  the project's 1 km grid, needing two new export modes and per-dataset
  file sizes.
- **s12, s13** (pipeline runs): the two exports.
- **s14** (build task, `drafts/s14.md`): `place_outcomes`, sealed like
  `cell_outcomes`. Its 1 km and 10 km rings use only cells inside the
  place's own municipality, so a ring can never read a cell of a
  municipality in the other half.
- **s15** (pipeline run): `place_outcomes`.
- **s16, s17** (explore task and run, `drafts/s16.md`): feasibility on
  **pre-election years only** (schools at t-4 and t, built-up at t, lights
  at t-4..t-1). This is the gate. If any of k1-k6 fires, the campaign stops
  before any post-election year is read.
- **s18, s19** (explore task and run, `drafts/s18.md`), written only after
  s17 survives:
  - the primary at 0.50% (main), 0.25% and 1.00%;
  - at 0.50% only: the falsification on state schools, the three
    secondaries with Benjamini-Hochberg, and the alignment heterogeneity.

One task is in flight per campaign, so the tasks run in this order: s1,
s6, s9, s11, s14, s16, s18. Each task's runs can go while the next task is
planned. No other variant runs. Ideas for variants go in the close-out
report.

### Definitions fixed in the drafts that Gabriel's brief left open

Claude suggested these; they are listed in "Provenance". Gabriel accepted
them as drafted on 2026-11-10. Once merged, the drafts are frozen.

- **Accessibility.** INEP changed the question in 2019. The count uses
  `dependencia_pne` up to 2018, then `1 - acessibilidade_inexistente` (any
  of the new items). The break falls inside the 2016 election's t to t+4.
  It is common to all schools, so the municipality-by-election fixed
  effects absorb its mean.
- **Lights years.** VIIRS V2.1 starts in 2013, and there is no 2012 image,
  so the 2016 election's pre-window is 2013-2015. V2.2 (2022-2024) has a
  documented method change from V2.1, also common to all places in a year.
- **Rings stay inside the municipality**, as `cell_exposure` does
  (decision 0004), for the split.
- **The match** uses the rules and thresholds in `drafts/s9.md`. No
  distance is used where INEP gives no coordinates.
- **The joint balance test** is the sum of three squared RI-studentised
  slopes, with p from the same draws.
- **The MDE** follows decision 0007's method: 2.8 × the RI SD of the
  placebo slope, times mean |D_p|, over the SD of the pre-election change.
  So "0.10 SD" means the effect of a mean-sized D.
- **The placebo** uses elections 2012-2020. INEP's data start in 2007, so
  2008 has no t-4.
- **Robustness windows** apply to the primary outcome only.
- **2004 section coverage** is reported, not enforced, in the national
  build. 2004 is not used.

## Kill rules and why

All stated by Gabriel on 2026-11-10 ("I confirm all; on_kill: stop"), with
k6 changed by him to 0.10 the same day. The thresholds come from his
brief. None was set after seeing any number of this campaign's data: none
exists yet.

- **s17 k1** (`counts.pairs_050 < 10000`): too few close pairs. A design
  count. The Legal Amazon alone gave 813 one-incumbent pairs at 0.25%
  (lessons, 2026-11-09); national counts are unknown.
- **s17 k2** (`coverage.located_share < 0.85`): polling places too poorly
  located for 1 km rings. A data count.
- **s17 k3** (`schools.match_share < 0.50`): too few polling places
  matched to a school. Polling places that are not schools (churches,
  clubs) count against it. That is intended: the share is of all places.
- **s17 k4** (`balance.ri_p_joint < 0.05`): baselines unbalanced on D.
- **s17 k5** (`placebo.ri_p_school < 0.10`): a non-flat placebo, with idea
  0001's bar for placebos (as in campaign 0004).
- **s17 k6** (`power.mde_sd_school > 0.10`): underpowered. Gabriel set 0.10
  on 2026-11-10, in place of the 0.05 of his first brief, before any data
  of this campaign existed or had been seen. 0.10 SD is about a fifth of
  Fiva and Halse's 0.56 SD (`fivaLocalFavoritismAtlarge2016`), which is at
  municipality level.
- **s19 k1** (`estimates.finite != true`): plausibility only. A sign or a
  size kills nothing; the estimates are reported.

Every field is written by the script its draft describes, at that dotted
path, and no key contains a dot. A missing field stops the step as
"unreadable"; it never passes.

## Budget and why

`budget.py` (23 recent agent tasks: median 3 model jobs, 90th percentile 4)
suggested 5 tasks, 2 explore runs, 10 pipeline runs, 25 model jobs and 17
days for the first draft. After the split:

- **max_tasks 7:** s1, s6, s9, s11, s14, s16 and s18.
- **max_pipeline_runs 12** (unchanged): the ten runs s2-s5, s7, s8, s10,
  s12, s13 and s15, plus two spare. A failed run is not retried by the
  tick. The spares let Gabriel restart one by hand, for example a national
  Earth Engine export that outlasts the 160-minute wait and must be
  resumed.
- **max_explore_runs 2** (unchanged): s17 and s19.
- **max_model_jobs 45:** the seven tasks at about 6 each (3 for a clean
  task plus a fix round or so; the split tasks are smaller than the old
  ones), plus 3 for one extra fix round.
- **end_by 2026-12-11** (unchanged): 31 days, the maximum. The 19 steps take
  about 13 to 16 days at 4 to 6 ticks per task and run, plus the close-out
  and room for two 24-hour blocks.

When a number runs out, no new step starts and the close-out reports why.

## New data

- **tse_votes_by_section** (extended): 26 states × 7 years, about 6.35 GB.
  Public. No identifiers: the section files hold no CPF or voter ID.
- **tse_polling_places** (unchanged; already national): about 170 MB for
  four years. It holds school phone numbers, which are never read
  (`polling_places` does not select the column).
- **polling_places, section_votes** (national builds): treatment-side,
  whole sample (decision 0003).
- **inep_schools:** about 4 million school-years and 16 columns, from Base
  dos Dados. The table is 7.06 GB uncompressed for all 455 columns, and
  billing is capped at 50 GB. Facilities are outcomes for both halves:
  they stay in raw and only `place_outcomes` reads them. No personal
  identifiers.
- **inep_school_catalogue:** 215,545 schools (2024).
  - School names and addresses belong to public buildings.
  - Phone (`NU_DDD`, `NU_TELEFONE`) is never read, and the 2024 file has no
    email column.
  - Coordinates come from Base dos Dados' copy of INEP's catalogue,
    selecting only id, municipality, state, latitude and longitude.
  - The intermediate certificate INEP omits is fetched at run time from
    its issuer and checked against its SHA-256 fingerprint
    (`e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd`, in
    the catalog). Only the fingerprint is in the repository.
- **school_polling_match:** one row per polling place and year, with no
  names or addresses.
- **viirs_annual, mapbiomas_coverage_national:** national rasters on the
  1 km grid. Both raw and both halves; no exploration account reads raw.
- **place_outcomes:** sealed like `cell_outcomes`. This PR adds its
  catalog entry (`derived` and `sealed`) and pins
  `"place_outcomes": "sealed/outcomes/place_outcomes/"` in
  `tests/test_split.py`. No GCP change is needed: `terrain-build` already
  creates in all of `sealed/outcomes/`.
- **Licences, as each source states them:**
  - TSE: "public", the catalog's existing statement, not re-checked here.
  - Base dos Dados: none stated.
  - VIIRS: public domain per Earth Engine, CC BY 4.0 per EOG.
  - MapBiomas: **CC BY 4.0**, not CC BY-SA. The brief said CC BY-SA, and so
    does the older `mapbiomas_deforestation` entry; MapBiomas today states
    CC BY 4.0.
- **INEP's licence: CC BY-ND 3.0** (Creative Commons
  Atribuição-SemDerivações, a site-wide statement at gov.br/inep). Gabriel's
  reading, 2026-11-10:
  - **estimates can be published**: regression coefficients, p-values and
    other aggregate statistics computed from INEP data;
  - **school-level derived tables may not be shareable**: `inep_schools`,
    `inep_school_catalogue`, `school_polling_match` and the school columns
    of `place_outcomes` stay in the bucket. They are not published or
    shared outside the project without a check of INEP's terms.
  
  The close-out report and any summary state only aggregates.
- **Also in this PR (owned):** `terrain.explore.exploration_municipalities(store,
  national=True)` reads both exploration lists (decision 0011). A test
  checks that every `explore/0006_*.py` uses it.

## What would change the plan

- s2 or s5 runs out of memory or disk on SP: the streaming reader needs
  another look before s5 is restarted.
- s8 fails the fingerprint check: INEP or its issuer has changed the
  certificate. A person checks the new chain and updates `extra_ca_url` and
  `extra_ca_sha256` in the catalog.
- The s10 notes show a high+medium match rate below 0.5 in most states: k3
  will likely fire. The match rules (frozen in `drafts/s9.md`) are then the
  thing to revisit, in a new campaign rather than this one.
- VIIRS 2023 or 2024 is missing (s12 fails by design): lights for the 2020
  election lose post years, and Gabriel decides whether to drop those years
  in a new campaign.
- Any of k1-k6 fires: the campaign stops before a post-election year is
  read. The close-out says which rule fired and by how much.
- s19 gives a clear primary effect with a near-zero falsification. That is
  not a finding on this half; it argues for registering the design, after
  Gabriel's review.
- Any run reads `sealed/`, `confirm/` or a post-election year before s18,
  or imports `terrain.registered`: stop everything.

## Provenance

- 2026-11-10: **stopped** by Gabriel before any work: step s1's
  `allowed_paths` missed `tests/test_acquire.py`, whose URL count for
  `tse_votes_by_section` (63) s1 must change to 182, so s1 could not be
  planned (#292). No step merged and no run started. Replaced by campaign
  0006 (`research/campaigns/0006-geography-of-representation/`).

Stated by Gabriel on 2026-11-10:

- The idea, the question, the new idea file (status proposed), and its kill
  criteria (the s17 rules, his).
- The design:
  - close pairs from `terrain.strongholds`;
  - council elections 2008-2020; windows 0.50%, 0.25% and 1.00%;
  - unit p; D_p, S_p and the baseline control;
  - the estimating equation and fixed effects;
  - RI over winner re-draws, 2,000 draws, with clustered SEs alongside;
  - exploration half only.
- The outcomes:
  - the primary outcome and its nine facilities (count 0-9, in SD of the
    pre-election change);
  - the falsification on state schools;
  - the three secondaries with Benjamini-Hochberg, and their windows;
  - the one heterogeneity.
- The datasets and their sources:
  - BigQuery with a 50 GB cap and the table in the catalog;
  - `place_outcomes` sealed, with its line pinned in this PR;
  - `max_size_gb` 20 for votes; identifiers none;
  - licences as each source states them.
- All steps and their order; no other variants.
- Every kill rule, threshold and `on_kill: stop`, confirmed.
- **k6 at 0.10** (`power.mde_sd_school > 0.10`). Gabriel changed it from
  0.05 and confirmed it on 2026-11-10, before #290 was merged. He set it
  before any data of this campaign existed or had been seen: no acquire,
  build or run of the campaign had started.
- **The split of his s6 and s10 into two tasks each** (s6/s9 and s11/s14),
  so that no task changes more than about 8 files, and the budget updated
  to match (`max_tasks` 7, `max_model_jobs` 45; the rest unchanged).
- **No stored certificate.** Only the SHA-256 fingerprint is kept; the
  intermediate is downloaded at run time from its issuer's public URL and
  checked against it, with TLS verification on.
- **INEP's CC BY-ND 3.0:** estimates can be published; school-level derived
  tables may not be shareable.
- The budget, `end_by` 31 days from 2026-11-10, and
  `referee_not_applicable_ok: [R5]`.
- Status: `active` if no campaign listing `data/catalog.yaml` is active.
  Campaign 0004 closed as `done` on main (PR #286) before this PR, so the
  status is `active`.
- The novelty check: repo, Zotero and web, with the citations he named.
- The `terrain.explore` change in this PR.

Suggested by Claude in this PR; Gabriel accepted all of them as drafted on
2026-11-10 ("Accept everything else as drafted"):

- **26 states for the votes**, not 27 (DF has no council election and no
  valid file).
- **Coordinates from Base dos Dados' copy of INEP's catalogue** (id,
  municipality, state, latitude, longitude only). INEP's own catalogue is
  not downloadable by script, and its microdata have no coordinates.
- **Fetching INEP's intermediate certificate at run time** from the issuer
  address in INEP's certificate, with the fingerprint taken on 2026-11-10.
- **`nr_cep` added to `polling_places`** for the postcode criterion.
- **Streaming the section reader** for SP's file size, and **2004 coverage
  reported, not enforced**.
- **The match rules and thresholds** (`drafts/s9.md`).
- **Accessibility across INEP's 2019 change**, the **2013 start of
  VIIRS**, and the **V2.1/V2.2 join**.
- **Rings inside the place's own municipality.**
- **The native-vegetation classes** {3, 4, 5, 6, 49, 11, 12, 32, 29, 50} and
  urban = 24 (Collection 10 legend; MapBiomas gives no list labelled
  "vegetação nativa").
- **The national extent** of the 1 km grid and the per-dataset file size and
  data-share check.
- **The joint balance statistic, the MDE scaling (mean |D|) and the placebo
  elections** (2012-2020).
- **Robustness windows for the primary only**, and **unknown alignment** as
  a third D term.
- **Step dependencies:** s6 after s1, s9 after s6, s11 after s9, s14 after
  s11 (one task in flight per campaign anyway).
