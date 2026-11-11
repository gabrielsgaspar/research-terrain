---
id: "0007"
title: "Gold, crime and the ballot box: does the gold price reshape local democracy where gold lies?"
status: active
idea: "0007"
owner: gabrielsgaspar
created: 2026-11-11
end_by: 2026-12-12
budget:
  max_tasks: 10
  max_explore_runs: 3
  max_pipeline_runs: 10
  max_model_jobs: 75
referee_not_applicable_ok: [R5]
self_repair: true
oversize_reason: "I want one campaign that runs the whole programme without me; the gates stop it early if a phase fails."
datasets:
  - name: anm_sigmine
    source: "ANM SIGMINE, ArcGIS feature service geo.anm.gov.br/arcgis/rest/services/SIGMINE/dados_anm/FeatureServer layer 0 'Processos minerários ativos' (270,353 records on 2026-11-11); active processes only"
    licence: "No dataset licence found; ANM publishes it as open data (gov.br/anm dados abertos); the gov.br site footer states CC BY-ND 3.0. Only municipality-level shares are published."
    max_size_gb: 2
    identifiers: none
  - name: sgb_gold_occurrences
    source: "Serviço Geológico do Brasil (SGB/CPRM), GeoServer WFS geoservicos.sgb.gov.br, layer geosgb:ocorrencias_recursos_minerais, CSV (36,484 points on 2026-11-11), without the geologist-name field"
    licence: "No licence found; the WFS capabilities state AccessConstraints NONE and Fees NONE"
    max_size_gb: 1
    identifiers: none
  - name: gold_price
    source: "World Bank Commodity Price Data (Pink Sheet), CMO-Historical-Data-Monthly.xlsx at thedocs.worldbank.org (Gold and Soybeans, 1960M01 on); US CPI from FRED, fredgraph.csv?id=CPIAUCSL"
    licence: "World Bank: CC BY 4.0. FRED: CPIAUCSL is public domain, citation requested; FRED's terms ask users not to scrape (one file is downloaded once)"
    max_size_gb: 1
    identifiers: none
  - name: gold_exposure
    source: "built from anm_sigmine, sgb_gold_occurrences, gold_price, ibge_boundaries_2024, municipalities and cnfp_public_forests; treatment-side, not split"
    licence: "as its sources"
    max_size_gb: 1
    identifiers: none
  - name: mapbiomas_mining
    source: "MapBiomas Brasil Collection 11, mining by type and mined substance, Earth Engine asset projects/mapbiomas-public/assets/brazil/lulc/collection11/mapbiomas_brazil_collection11_mining_substances_v1, 1985-2025, on the project's national 1 km grid"
    licence: "CC BY 4.0 (MapBiomas, 'uso público, aberto e gratuito mediante referência')"
    max_size_gb: 10
    identifiers: none
  - name: mining_panel
    source: "built from mapbiomas_mining, mapbiomas_coverage_national and ibge_boundaries_2024; split by half like cell_outcomes"
    licence: "CC BY 4.0 (MapBiomas), with attribution"
    max_size_gb: 1
    identifiers: none
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
  # Phase A: exposure and feasibility, no outcome data
  - id: s1
    kind: task
    type: build
    draft: drafts/s1.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/anm.py
      - pipeline/acquire/anm_sigmine.py
      - data/contracts/anm_sigmine.md
      - tests/test_acquire_anm.py
    after: []
  - id: s2
    kind: pipeline_run
    stage: acquire
    target: anm_sigmine
    dataset: anm_sigmine
    after: [s1]
  - id: s3
    kind: task
    type: build
    draft: drafts/s3.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/acquire.py
      - tests/test_acquire.py
      - pipeline/acquire/gold_price.py
      - pipeline/acquire/sgb_gold_occurrences.py
    after: [s1]
  - id: s4
    kind: pipeline_run
    stage: acquire
    target: gold_price
    dataset: gold_price
    after: [s3]
  - id: s5
    kind: pipeline_run
    stage: acquire
    target: sgb_gold_occurrences
    dataset: sgb_gold_occurrences
    after: [s3]
  - id: s6
    kind: task
    type: build
    draft: drafts/s6.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/gold_exposure.py
      - pipeline/build/gold_exposure.py
      - data/contracts/gold_exposure.md
      - tests/test_build_gold_exposure.py
    after: [s3]
  - id: s7
    kind: pipeline_run
    stage: build
    target: gold_exposure
    dataset: gold_exposure
    after: [s2, s4, s5, s6]
  - id: s8
    kind: task
    type: explore
    draft: drafts/s8.md
    allowed_paths:
      - explore/0007_gold_feasibility.py
      - tests/test_explore_gold_feasibility.py
    after: [s6]
  - id: s9
    kind: explore_run
    script: 0007_gold_feasibility
    after: [s7, s8]
    kill_rules:
      - id: k1
        says: "Fewer than 150 exploration-half municipalities have at least one Geological Survey gold occurrence"
        field: exposure.n_munis_exposed
        op: "<"
        value: 150
        confirmed: true
      - id: k2
        says: "Fewer than 3 states each have at least 10 exposed exploration-half municipalities"
        field: exposure.n_states_10plus
        op: "<"
        value: 3
        confirmed: true
      - id: k3
        says: "Less than 90% of the active ANM gold titles in the exploration half carry a valid request year"
        field: titles.share_dated
        op: "<"
        value: 0.90
        confirmed: true
      - id: k4
        says: "More than 60% of the exposed exploration-half municipalities are in one state"
        field: exposure.top_state_share
        op: ">"
        value: 0.60
        confirmed: true
    on_kill: stop
  # Phase B: does gold move mining? (gate 2)
  - id: s10
    kind: task
    type: build
    draft: drafts/s10.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/earthengine.py
      - tests/test_earthengine.py
      - pipeline/acquire/mapbiomas_mining.py
    after: [s9]
  - id: s11
    kind: pipeline_run
    stage: acquire
    target: mapbiomas_mining
    dataset: mapbiomas_mining
    after: [s10]
  - id: s12
    kind: task
    type: build
    draft: drafts/s12.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/builds/mining_panel.py
      - pipeline/build/mining_panel.py
      - data/contracts/mining_panel.md
      - tests/test_build_mining_panel.py
    after: [s10]
  - id: s13
    kind: pipeline_run
    stage: build
    target: mining_panel
    dataset: mining_panel
    after: [s11, s12]
  - id: s14
    kind: task
    type: explore
    draft: drafts/s14.md
    allowed_paths:
      - explore/0007_gold_first_stage.py
      - tests/test_explore_gold_first_stage.py
    after: [s12]
  - id: s15
    kind: explore_run
    script: 0007_gold_first_stage
    after: [s13, s14]
    kill_rules:
      - id: k1
        says: "The municipality-clustered F statistic of gold exposure x log real gold price (t-1) on garimpo area share, 1990-2024, is below 10"
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
  # Phase C: politics and violence (final)
  - id: s16
    kind: task
    type: build
    draft: drafts/s16.md
    allowed_paths:
      - data/catalog.yaml
      - src/terrain/bigquery.py
      - tests/test_bigquery.py
      - src/terrain/basedosdados.py
      - tests/test_acquire_basedosdados.py
      - pipeline/acquire/sim_homicides.py
      - pipeline/acquire/ibge_population_annual.py
    after: [s15]
  - id: s17
    kind: pipeline_run
    stage: acquire
    target: sim_homicides
    dataset: sim_homicides
    after: [s16]
  - id: s18
    kind: pipeline_run
    stage: acquire
    target: ibge_population_annual
    dataset: ibge_population_annual
    after: [s16]
  - id: s19
    kind: task
    type: build
    draft: drafts/s19.md
    allowed_paths:
      - data/catalog.yaml
      - pipeline/acquire/tse_receipts.py
      - tests/test_acquire_basedosdados.py
      - src/terrain/builds/politics_panel.py
      - pipeline/build/politics_panel.py
      - data/contracts/politics_panel.md
      - tests/test_build_politics_panel.py
    after: [s16]
  - id: s20
    kind: pipeline_run
    stage: acquire
    target: tse_receipts
    dataset: tse_receipts
    after: [s19]
  - id: s21
    kind: pipeline_run
    stage: build
    target: politics_panel
    dataset: politics_panel
    after: [s17, s18, s19, s20]
  - id: s22
    kind: task
    type: explore
    draft: drafts/s22.md
    allowed_paths:
      - explore/0007_gold_politics.py
      - tests/test_explore_gold_politics.py
    after: [s19]
  - id: s23
    kind: explore_run
    script: 0007_gold_politics
    after: [s21, s22]
    kill_rules:
      - id: k1
        says: "Some estimate, standard error or p-value of the politics reduced forms is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0007: Gold, crime and the ballot box

## Question

When the world gold price rises, does the gold rush reshape local democracy
where gold lies: who runs, who wins, how competitive races are, how much
campaign money comes from mining, and how violent the place becomes? This is
idea 0007 (`research/ideas/0007-gold-and-the-ballot.md`), across all of
Brazil (decision 0011), exploration half only. One campaign in three phases.
Each phase ends in an explore run whose kill rules stop the whole campaign
(`on_kill: stop`) before the next, more expensive phase starts:

- **Phase A, s1-s9:** exposure and feasibility; no outcome data is read.
- **Phase B, s10-s15:** does gold move mining? (MapBiomas, sealed by half).
- **Phase C, s16-s23:** politics and violence.

Every draft is written now, before anything runs, so no later phase can use
earlier results to change its design. Question 2 of the brief (close races
and mining near strongholds) is not in this campaign; the close-out suggests
it if the first stage is strong.

## Already known

Tier 1 (this repository) and tier 2 (Zotero notes) are authoritative:
`novelty_scan.py` with gold, ouro, garimpo, mining, mineração, commodity
price, homicide and sigmine found **no file** (2026-11-11). Every tier 3
(web) find is **unverified**: found on the web, still to be checked. None
is in `research/references/`.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Gold price × gold exposure raises garimpo area in Brazil (phase B) | **explored** | (web, unverified) Amaral, Pantaleão and Rio Tinto, "The Cost of Gold: Mining Booms, Violence, and Agrarian Conflict in Brazil", working paper, replication code at github.com/brunopantaleao/costof_gold_mining_and_violence: 2000 garimpo and gold shares × gold price, MapBiomas, SIGMINE as robustness. Also Moreno-Louzada, Figueira and Picchetti (2025), arXiv 2512.10076: gold deposits × log gold price on mining area |
| Gold price × exposure raises homicides in Brazil | **explored** | (web, unverified) Amaral et al.: about +36% homicides per SD of exposure; Moreno-Louzada et al.: not significant once their corrected errors are used |
| The 2013 good-faith law raised garimpo and violence | **explored** | (web, unverified) Pereira and Pucci (2024), "A Tale of Gold and Blood", FEA-USP WP 2024_18, ideas.repec.org/p/spa/wpaper/2024wpecon18.html |
| The 2023 suspension reduced garimpo | partly explored | descriptive only (Instituto Escolhas); no causal paper found |
| Gold price × exposure and **local politics** (entry, mining-occupation candidates, competition, incumbency) | **new** | no paper found in English or Portuguese; nearest are journalism and a 2025 undergraduate thesis (unverified). Adjacent: Carreri and Dube (2017, JOP 79(2), doi:10.1086/688443), oil in Colombia; Novaes and Schiumerini (2022, BJPS 52(4)), agricultural prices and Brazilian mayors' incumbency |
| Legal regime × gold price on political outcomes | **new** | nothing found |
| Mining-firm campaign money, municipal level | partly explored | (web, unverified) Guimarães, Milanez and Ribeiro (2019), Minas Gerais state legislature 2014, descriptive |
| Commodity price × location and conflict elsewhere | explored | (web) Dube and Vargas (2013, REStud 80(4)); Idrobo, Mejía and Tribín (2014, Peace Econ. Peace Sci. Public Policy 20(1), doi:10.1515/peps-2013-0053); Berman, Couttenier, Rohner and Thoenig (2017, AER 107(6)); Bazillier and Girard (2020, JDE, doi:10.1016/j.jdeveco.2019.102411) |
| Inference with one common shock | explored (method) | `borusyakNonrandomExposureExogenous2023`; (web) Goldsmith-Pinkham, Sorkin and Swift (2020, AER 110(8)); Borusyak, Hull and Jaravel (2022, REStud 89(1)); Moreno-Louzada et al. (2025): clustered errors over-reject in this gold design |

What this campaign adds: the political outcomes and their legal-regime split,
which no paper found has studied. Phase B replicates a known first stage on
a national panel with geology-based exposure. It is a gate, not a
contribution. Gabriel may want to add Amaral et al., Moreno-Louzada et al.
and Pereira and Pucci to `terrain-inbox`.

## Read before this runs

- **Amaral, Pantaleão and Rio Tinto, "The Cost of Gold"** (closest; web,
  unverified). Gabriel, 2026-11-11: "Not read; active anyway".
- Carreri and Dube (2017), the template for the politics reduced form. Not
  read yet (brief, section 7); he will read it while phase A runs.
- Idrobo, Mejía and Tribín (2014), the template for the legal-access split.
  Not read yet (brief).
- Moreno-Louzada, Figueira and Picchetti (2025), arXiv 2512.10076: the
  inference of this exact design. Not read yet.
- Pereira and Pucci (2024): the 2013 law. Not read yet.

## Steps and why

The brief had 20 steps. Here there are 23, for four reasons:

- **s1 split in two (s1 and s3).** The brief caps s1 at six files. The
  ANM acquirer and the generic acquires together need eight.
- **One more acquire, s5 (`sgb_gold_occurrences`).** The geology source
  can be reached by script, and it is now the main exposure.
- **The brief's s8 split in two (s10 and s12).** MapBiomas mining needs a
  small `unmask` change to the Earth Engine code, so one task would need
  eight files.
- **One more acquire, s18 (`ibge_population_annual`).** Homicides per
  100,000 need annual population, and none is in the bucket.

| Here | What | Files |
| --- | --- | --- |
| s1 | ANM SIGMINE acquirer (task) | 5 fits |
| s2 | acquire `anm_sigmine` | |
| s3 | gold price, CPI and SGB occurrences, a `csv` check (task) | 5 fits |
| s4, s5 | acquire `gold_price`, `sgb_gold_occurrences` | |
| s6 | `gold_exposure` build (task) | 5 fits |
| s7 | build `gold_exposure` | |
| s8, s9 | feasibility script and run: **gate 1** | 2 fits |
| s10 | MapBiomas mining export (task) | 4 fits |
| s11 | acquire `mapbiomas_mining` | |
| s12 | `mining_panel` build, sealed (task) | 5 fits |
| s13 | build `mining_panel` | |
| s14, s15 | first-stage script and run: **gate 2** | 2 fits |
| s16 | Base dos Dados aggregation; SIM and population acquirers (task) | 7 tight |
| s17, s18 | acquire `sim_homicides`, `ibge_population_annual` | |
| s19 | receipts acquirer and `politics_panel` build, sealed (task) | 7 tight |
| s20, s21 | acquire `tse_receipts`, build `politics_panel` | |
| s22, s23 | politics script and run: final | 2 fits |

- **s1, s2.** ANM is the riskiest host, so it goes first. Two things could
  stop it. Its server omits an intermediate certificate, so the acquirer
  pins Sectigo OV R36 by SHA-256 and checks it at run time. And government
  hosts have refused GitHub's servers before (INEP, campaign 0006). No
  runner has reached `geo.anm.gov.br`.
- **s3-s5.** Plain files through the generic acquirer, with a new `csv`
  check: required columns, forbidden columns and a minimum row count. The
  forbidden list keeps the geologist's name out of the SGB file. No runner
  has reached thedocs.worldbank.org, fred.stlouisfed.org or
  geoservicos.sgb.gov.br. All three answered from a local session on
  2026-11-11.
- **s6, s7.** One row per municipality (5,571), with the exposures, the
  title counts the kill rules read, and the centroids for the Conley
  errors. Plus the annual real price series. Treatment-side, so not split.
- **s8, s9 (gate 1).** Counts only. It reads no outcome data: no MapBiomas,
  no SIM, no election outcome compared across exposure. Two numbers are
  informational, not rules: close pairs in exposed municipalities
  (question 2) and mining-occupation candidates, pooled by election and
  never split by exposure.
- **s10-s13.** MapBiomas Collection 11 mining, 1985-2025, on the national
  1 km grid. A table export by municipality would need a municipality
  layer in Earth Engine that the project does not have. The grid also
  gives the per-cell mining question 2 needs. `mining_panel` sums the cells
  by municipality and is sealed by half.
- **s14, s15 (gate 2).** The first stage, event study, placebos and
  legal-regime split for garimpo, with the full inference.
- **s16-s21.** Homicides (SIM microdata, by municipality of occurrence,
  counted in BigQuery), population, and mining-sector receipts (Base dos
  Dados donor CNAE; never a CPF, CNPJ or name). `politics_panel` holds the
  nine outcomes and is sealed by half.
- **s22, s23 (final).** The reduced forms, the event study, the
  legal-regime split and Benjamini-Hochberg across the nine outcomes.

One task is in flight per campaign, so the tasks run in this order: s1, s3,
s6, s8, s10, s12, s14, s16, s19, s22. Phase B starts only after s9 passes,
and phase C only after s15 passes. No other variant runs.

### Definitions fixed in the drafts that the brief left open

Claude suggested these; Gabriel saw the main ones before merging (see
"Provenance").

- **Gold occurrence:** an SGB point whose `substancias` list has the item
  "Ouro", matched case- and accent-insensitively on the comma-separated
  items. Exposure E_m is occurrences per km² of the municipality. Binary
  exposure means at least one occurrence.
- **Gold titles:** SIGMINE `SUBS` in {OURO, MINÉRIO DE OURO, OURO NATIVO}.
  OURO PIGMENTO is orpiment, an arsenic mineral, so it is excluded.
  Garimpo titles: `FASE` in {LAVRA GARIMPEIRA, REQUERIMENTO DE LAVRA
  GARIMPEIRA}. Pre-2000 means `ANO` < 2000. On 2026-11-11 there were 10,810
  active gold titles with `ANO` < 2000, and no title without `ANO`.
- **Placebo titles (sand and gravel):** `SUBS` in {AREIA, AREIA COMUM,
  AREIA LAVADA, CASCALHO, SAIBRO}. CASCALHO DIAMANTÍFERO is diamond
  gravel, so it is excluded.
- **Legal-access split:** the share of a municipality's gold occurrences
  inside Indigenous lands (CNFP 2025, `is_indigenous`). Protected areas
  are left out: the project has no tested rule for CNFP's
  conservation-unit categories, and FUNAI's own server is down (catalog).
- **Mining outcome:** the MapBiomas Collection 11 mining footprint
  (exposed soil plus revegetation). Garimpo codes are 11SS and 12SS,
  industrial 21SS and 22SS, and gold is SS = 15. The main outcome is
  garimpo of any substance. Gold-labelled garimpo is secondary, because
  MapBiomas assigns substances partly from the same SGB database.
- **Baseline forest control:** native-vegetation share in 2004 from
  `mapbiomas_coverage_national`, not 1985 as the brief said. 1985 is not
  in the bucket, and exporting it would add a step.
- **Mining occupations (TSE):** codes 605 (GARIMPEIRO) and 253 (TRABALHADOR
  DE MINAS E PEDREIRAS...). The same codes appear in 2004, 2008 and 2012.
  Mining technicians (245) and geologists (107) are excluded: they are
  professionals, not miners.
- **Mining-sector firms:** donor CNAE 2.0 divisions 07 (metallic minerals)
  and 08 (non-metallic), and class 09.90 (support to mining except oil).
- **ACLED dropped:** it needs a registered account, and the brief lists no
  acquire for it.
- **Legal regimes, annual:** R1 is 1990-2013, R2 (good faith) 2014-2022 and
  R3 (suspension) 2023-2024. For elections, 2016-2024 count as the good-faith
  regime, and no complete post-2023 term exists.

## Kill rules and why

Gabriel stated every rule in his brief and confirmed each on 2026-11-11,
after the plain-words read-back. None is a p-value rule, so none stops a
valid design at a fixed rate by chance.

- **Gate 1 (s9).**
  - k1 (fewer than 150 exposed municipalities) and k2 (fewer than 3 states
    with at least 10): a panel needs enough exposed units, spread so that
    the state-by-year fixed effects do not absorb the exposure.
  - k4 (one state holds more than 60%): the same worry.
  - k3 (less than 90% of titles with a valid year): ANM fills `ANO` for
    every title (0 missing on 2026-11-11), so this almost certainly never
    fires; it catches a parsing bug.
  - The brief set these thresholds for title exposure. They now apply to
    geology exposure, which Gabriel chose as the main one when he
    confirmed the rules.
- **Gate 2 (s15).**
  - k1: F below 10 is the usual weak-instrument line.
  - k2 (lead ratio above 0.5): Claude warned in the read-back that the
    real gold price in the 1990s was above its 2000 level (from memory,
    unverified). Even a valid design then has non-zero leads, about 0.3 if
    mining tracks the price, so 0.5 leaves little room. Gabriel kept 0.5.
  - k3 catches broken numbers.
- **Final (s23).** k1 catches broken numbers; the politics results
  themselves are the report.

## Budget and why

`scripts/budget.py` (2026-11-11): median 3 and 90th percentile 5 model jobs
per task; explore runs under an hour.

- **max_tasks 10:** the ten task steps.
- **max_pipeline_runs 10 and max_explore_runs 3:** one per step. The tick
  counts a step once however often it retries, so spare runs could never
  be used.
- **max_model_jobs 75:**
  - ten tasks at 5 jobs each = 50;
  - one fix round (2 jobs) on each of the six tasks that read new data = 12;
  - two self-repairs, at about 5 jobs each = 10;
  - the brief's 60 was sized for 9 tasks without repair.
- **end_by 2026-12-12:** 31 days, the limit. budget.py suggests 19 days,
  and it errs long.
- **When the budget runs out:** no new step starts, what is in flight
  finishes, and the close-out follows.

## New data

Ten datasets. Every source but MapBiomas is new to the project's runners;
each acquire is its own early step, and a failure is reported with its real
cause. `self_repair: true` lets a failing data step get one repair task.
For example, a repair could switch a catalog URL to the fallback below.

| Dataset | What | Licence | Size | Identifiers | Fallback |
| --- | --- | --- | --- | --- | --- |
| `anm_sigmine` | active mining processes, polygons, no holder names (`NOME` is never requested) | none found; gov.br footer CC BY-ND 3.0 | < 2 GB | none | **none that works**: ANM's national zip (with inactive titles) is behind a firewall that answered 403; Base dos Dados has no table |
| `sgb_gold_occurrences` | 36,484 mineral occurrences, attributes and coordinates, no geologist name | none found (WFS: no constraints) | < 1 GB | none | none known |
| `gold_price` | Pink Sheet monthly xlsx (Gold, Soybeans) and FRED CPI csv | CC BY 4.0; public domain | < 1 GB | none | IMF primary commodity prices, external-data.xlsx (PGOLD, PSOYB); the Pink Sheet URL is tied to the November 2026 release |
| `gold_exposure` | built, one row per municipality, plus `gold_prices` | as sources | < 1 GB | none | — |
| `mapbiomas_mining` | Collection 11 mining by type and substance, 1985-2025, 1 km cell shares | CC BY 4.0 | < 10 GB | none | Collection 10 mining asset (`..._collection10_mining_substances_v3`, still public: unconfirmed); then Collection 10 coverage class 30 (no garimpo or substance split) |
| `mining_panel` | built, municipality × year, sealed | CC BY 4.0 | < 1 GB | none | — |
| `sim_homicides` | deaths by assault, year × municipality of occurrence | unknown (BD); public (DATASUS) | < 1 GB | none | DATASUS FTP `.dbc` files need a decompressor the project lacks; `municipio_causa` (by residence, not occurrence) |
| `ibge_population_annual` | population by municipality and year | public (IBGE) | < 1 GB | none | `basedosdados.br_ms_populacao.municipio` (2000-2025) |
| `tse_receipts` | receipts summed by year, municipality, office and donor CNAE | CC BY (TSE) | < 1 GB | none | TSE's own zips (`prestacao_contas_2004.zip`, `_2008.zip`, `prestacao_final_2012.zip`); only 2012 carries a donor sector, as text |
| `politics_panel` | built, municipality × election, sealed | public | < 1 GB | none | — |

Outcome data (MapBiomas mining, SIM) stay in raw, which no exploration
account reads. `mining_panel` and `politics_panel` are sealed by half; their
sealed lines are pinned in `tests/test_split.py` in this PR. The electoral
inputs are public TSE files that cannot be sealed; the explore scripts
restrict to the exploration half, as always. Exposure and prices are
treatment-side and not split.

## What would change the plan

- Gate 1 shows exposure concentrated in Minas Gerais and Bahia, not the
  Amazon: the "Amazon" framing changes, even if no rule fires.
- `titles.n_pre2000` is far below 10,810 in the exploration half's share,
  or geology and title exposure barely overlap: read the survival problem
  as serious, and in the report weigh the title robustness checks lightly.
- A strong first stage: question 2 (close races and mining near
  strongholds) becomes the next campaign, on `mapbiomas_mining`'s 1 km
  cells.
- `pairs.n_050_exposed` below a few hundred: question 2 is not feasible.
- Candidates with codes 605 or 253 are fewer than about 100 per election:
  the "who runs" and "who wins" mining outcomes are too thin to read.
- The money outcome runs only if at least two of 2004, 2008 and 2012 have
  receipts with a donor CNAE (the s22 rule). If not, the report says why.

## Provenance

- **Stated by Gabriel in his brief** (2026-11-11, written in claude.ai):
  - the idea, the four tests, the design of section 4, and the three-phase
    structure;
  - every kill rule and threshold: s9 k1-k4, s15 k1-k3 (his g1-g3) and
    s23 k1;
  - `on_kill: stop` at every gate;
  - status active, and that he had not read Carreri and Dube or Idrobo et
    al.;
  - `oversize_reason`, in his words: "I want one campaign that runs the
    whole programme without me; the gates stop it early if a phase fails."
  - Budget in the brief: max_tasks 7, max_pipeline_runs 9,
    max_explore_runs 3, max_model_jobs 60, end_by 31 days.
- **Confirmed by Gabriel on 2026-11-11**, in this session, after Claude read
  them back:
  - the eight kill rules ("Confirm all eight");
  - geology as the main exposure, with first-stage outcome garimpo of any
    substance and titles as robustness ("Geology main (Recommended)", over
    "Titles main, as briefed");
  - self-repair on, with the model-job budget raised to 70 ("Yes
    (Recommended)");
  - start now without having read the closest paper ("Not read; active
    anyway", over the skill's recommendation to merge as draft).
- **Suggested by Claude, not separately confirmed** (shown to Gabriel in
  the message with the questions, or listed here and in the PR for his
  review before merging):
  - 23 steps instead of 20;
  - max_tasks 10, not the brief's 7: the validator needs at least the
    number of task steps;
  - max_pipeline_runs 10, without spares;
  - max_model_jobs 75, not 70, after the s10/s12 split;
  - the Collection 11 grid export, and dropping ACLED;
  - every definition under "Definitions fixed in the drafts".
- **Probe (skill stage 4):** no data already in the bucket can answer
  gate 1, since every exposure source is new. The brief accepted a large
  campaign with gates instead of a separate probe.
