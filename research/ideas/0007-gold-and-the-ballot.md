---
id: "0007"
title: "Gold, crime and the ballot box: does the gold price reshape local democracy where gold lies?"
status: proposed
created: 2026-11-11
updated: 2026-11-11
datasets:
  - mining_panel
  - politics_panel
  - mapbiomas_coverage_national
  - tse_candidates
  - tse_results
  - municipalities
  - ibge_boundaries_2024
  - cnfp_public_forests
kill_criteria:
  - "Too few gold municipalities: fewer than 150 exploration-half municipalities with at least one Geological Survey gold occurrence (stated by Gabriel in his brief; confirmed 2026-11-11)."
  - "Exposure in too few states: fewer than 3 states with at least 10 exposed exploration-half municipalities (stated by Gabriel; confirmed 2026-11-11)."
  - "Title years missing: less than 90% of active ANM gold titles carry a valid request year (stated by Gabriel; confirmed 2026-11-11)."
  - "One state dominates: more than 60% of the exposed exploration-half municipalities are in one state (stated by Gabriel; confirmed 2026-11-11)."
  - "Weak first stage: the municipality-clustered F statistic of gold exposure x log real gold price (t-1) on garimpo area share, 1990-2024, is below 10 (stated by Gabriel; confirmed 2026-11-11)."
  - "Pre-boom trends: the absolute mean event-study coefficient for 1990-2001 (base 2000) is more than half the absolute mean coefficient for 2002-2024 (stated by Gabriel; confirmed 2026-11-11)."
related: ["0001", "0006"]
---

# 0007: Gold, crime and the ballot box: does the gold price reshape local democracy where gold lies?

## Claim

Gold prices are set in London, Shanghai and by central banks, so no
Brazilian municipality controls them, and geology sets where gold lies.
When the world gold price rises, illegal and artisanal gold mining
(*garimpo*) spreads where gold lies, and it reshapes local democracy there:
who runs, who wins, how competitive council and mayoral races are, how
much campaign money comes from mining, and how violent the place becomes.

## Prediction

1. **First stage.** Garimpo area rises with E_m × ln P_{t-1}, where E_m is
   the municipality's gold occurrences per km² (Geological Survey) and P is
   the real LBMA gold price in US dollars. Positive, almost certainly; if
   it is absent, the rest is moot.
2. **Politics.** Two directions are plausible, and the test is two-sided:
   - *capture*, as Carreri and Dube (2017) found for oil in Colombia: fewer
     candidates per seat, wider mayoral margins, fewer effective
     candidates, more mining-linked candidates and councillors, more
     mining money, more homicides;
   - *no effect*, because Brazilian garimpo is less mediated by armed
     groups than Colombian oil.
3. **Legal regimes.** The price response should be larger under the 2013
   "good faith" rule (Law 12.844, art. 39 §4: gold presumed legal on the
   seller's word, July 2013 to April 2023) and smaller after the Supreme
   Court suspended it in 2023. Post-2023 data are short: reported, not
   claimed.

A null first stage, or pre-2002 event-study coefficients half as large as
the post-2002 ones, counts against the design. Null politics with a strong
first stage is a result ("Brazil's local elections withstood the gold
rush").

## Design

- **Scope:** all of Brazil (decision 0011), exploration half only, through
  `terrain.explore.exploration_municipalities(store, national=True)`.
- **Exposure (fixed before any outcome is read; treatment-side, not split):**
  - main: Geological Survey (SGB) gold occurrences per km², and its binary
    version (any occurrence);
  - robustness: share of the municipality's area under ANM gold titles
    requested before 2000. SIGMINE as a script can reach it holds **active
    titles only**, so these are titles that survived to 2026, and survival
    depends on the later gold price. This is why geology is the main
    exposure (Gabriel's choice, 2026-11-11);
  - placebo exposure: pre-2000 titles for sand and gravel;
  - legal-access split: share of the municipality's gold occurrences inside
    Indigenous lands (CNFP), where legal mining is barred.
- **Shock:** annual mean of the World Bank Pink Sheet gold price, deflated
  by US CPI (FRED CPIAUCSL). For elections, the mean log real price over the
  four years before election year e. Placebo price: soybeans.
- **First stage (municipality × year, 1990-2024):**
  Mining_mt = β (E_m × ln P_{t-1}) + α_m + δ_{state,t} + X_m × γ_t + ε.
  Mining is MapBiomas Collection 11 garimpo area of any substance (MapBiomas
  labels garimpo "gold" partly from the same SGB database, so gold-labelled
  garimpo is secondary). X_m: native-vegetation share in 2004, log area and
  Indigenous-land share, each × year.
- **Reduced form for politics (municipality × election, 2000-2024):** the
  same form with E_m × mean ln P over e-4..e-1, nine outcomes,
  Benjamini-Hochberg across them.
- **Inference:** municipality clusters; Conley spatial errors at 50, 100
  and 200 km; randomisation inference permuting E_m within state (1,000
  draws); placebo price and placebo exposure. With one common shock,
  identification rests on exposure being as good as random given the fixed
  effects and controls (Goldsmith-Pinkham, Sorkin and Swift 2020; Borusyak,
  Hull and Jaravel 2022); Moreno-Louzada, Figueira and Picchetti (2025) show
  that clustered errors over-reject in exactly this gold design, so the RI p
  is reported next to every clustered one.

## Data needed

The front matter lists only datasets already in `data/catalog.yaml`; the
others are added to the catalog by the campaign's build tasks.

New (campaign 0007): `anm_sigmine`, `sgb_gold_occurrences`, `gold_price`,
`gold_exposure`, `mapbiomas_mining`, `mining_panel` (sealed),
`sim_homicides`, `ibge_population_annual`, `tse_receipts`, `politics_panel`
(sealed). Existing: `tse_candidates`, `tse_results`, `municipalities`,
`ibge_boundaries_2024`, `cnfp_public_forests`, `mapbiomas_coverage_national`.

## Status

- 2026-11-11: proposed. Campaign 0007 drafted
  (`research/campaigns/0007-gold-and-the-ballot/`).

## Log

- Brief: Gabriel's "Gold, crime and the ballot box" campaign brief,
  2026-11-11 (written in claude.ai; not in the repository).
