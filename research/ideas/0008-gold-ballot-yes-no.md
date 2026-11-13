---
id: "0008"
title: "Gold and the ballot, yes/no: does the gold price move garimpo and local politics in municipalities that have gold?"
status: exploring
created: 2026-11-13
updated: 2026-11-13
datasets:
  - mining_panel
  - gold_exposure
  - politics_panel
  - tse_candidates
  - tse_results
  - municipalities
kill_criteria:
  - "Weak first stage: the municipality-clustered F statistic of (has gold) x log real gold price (t-1) on garimpo area share, 1990-2024, is below 10 (stated by Gabriel in his brief, idea 0007's rule and threshold unchanged; confirmed 2026-11-13)."
  - "Pre-boom trends: the absolute mean event-study coefficient for 1990-2001 (base 2000) is more than half the absolute mean coefficient for 2002-2024 (stated by Gabriel, idea 0007's rule and threshold unchanged; confirmed 2026-11-13)."
related: ["0007"]
---

# 0008: Gold and the ballot, yes/no

## Claim

When the world gold price rises, garimpo (illegal and artisanal gold
mining) grows in the municipalities that have gold, and their local
politics change: who runs, who wins, how competitive races are, and how
violent the place is. "Has gold" is a yes/no measure: 1 if the Geological
Survey (SGB) records any gold occurrence in the municipality, else 0
(`geo_exposed` in `gold_exposure`).

## Where it comes from

This idea was born from campaign 0007's exploration results, and it is
exploration only.

- Idea 0007 (`research/ideas/0007-gold-and-the-ballot.md`, now `dead`)
  measured gold as the **density** of SGB gold occurrences per km². Its
  pre-stated first stage failed: clustered F 2.44, rule at least 10.
- The same run tried three exposures
  (`research/explore-runs/0007/43438404852.md`):
  - density (`geo_gold_per_km2`, the stated one): F 2.44;
  - pre-2000 gold titles (`title_gold_pre2000_share`): F 4.58;
  - yes/no (`geo_exposed`, key `robust.binary`): F 12.28.
- The yes/no F of 12.28 was **seen before this idea was written**. That is
  a forking path: the measure was chosen because it looked stronger. So
  nothing explored under this idea can be a finding. Only one registered
  test on the sealed (confirmation) half could be, and that is Gabriel's
  decision after campaign 0008.
- Gabriel chose this route in campaign 0007's report, decision 2, option B
  (`research/campaigns/0007-gold-and-the-ballot/report.md`): a new idea for
  the yes/no measure, with the measure, the test and the kill rules
  written before any run.

## Prediction

1. **First stage.** Garimpo area share rises with D_m × ln P_{t-1}, where
   D_m is the yes/no gold measure and P the real gold price (World Bank
   Pink Sheet, deflated by US CPI). Positive; if absent, the rest is moot.
2. **Politics.** Two directions are plausible, and the test is two-sided:
   - *capture*, as Carreri and Dube (2017) found for oil in Colombia:
     fewer candidates per seat, wider mayoral margins, fewer effective
     candidates, more mining-linked candidates and councillors, more
     mining money, more homicides;
   - *no effect*, because Brazilian garimpo is less mediated by armed
     groups than Colombian oil.
3. **Legal regimes.** The price response should be larger under the 2013
   "good faith" rule (Law 12.844, art. 39 §4, July 2013 to April 2023).
   Reported, not claimed.

A clustered F below 10, or pre-2002 event-study coefficients more than half
as large as the post-2002 ones, counts against the design (the kill
criteria above, idea 0007's own rules and thresholds). Null politics with a
strong first stage is a result.

## Design

- **Scope:** all of Brazil (decision 0011), exploration half only, through
  `terrain.explore.exploration_municipalities(store, national=True)`.
- **Exposure (fixed now):** D_m = `geo_exposed`. Robustness exposures in the
  politics step: the density `geo_gold_per_km2` and
  `title_gold_pre2000_share`. Placebo exposure: pre-2000 sand-and-gravel
  titles. Legal-access split: share of the municipality's gold occurrences
  inside Indigenous lands.
- **First stage (municipality × year, 1990-2024):**
  garimpo_share_mt = b (D_m × ln P_{t-1}) + a_m + d_{state,t} + controls + e,
  with the fixed effects, controls (`native_share_2004`, ln area and
  Indigenous-land share, each × year), sample and estimation of the
  `robust.binary` block of `explore/0007_gold_first_stage.py`.
- **Inference:** municipality clusters (same small-sample factor);
  F = (b / se)²; randomisation p from 1,000 within-state permutations of D
  (seed 20261113); Conley errors at 50, 100 and 200 km. With one common
  shock, clustered errors can over-reject (Moreno-Louzada, Figueira and
  Picchetti 2025), so the randomisation p is reported next to them.
- **Event study:** D × year dummies, base 2000; `placebo.lead_ratio` as in
  campaign 0007 step s14.
- **Politics reduced forms (municipality × election, 2000-2024):** campaign
  0007's `drafts/s22.md`, with D_m × mean ln P over e-4..e-1 as the main
  regressor: nine outcomes in a fixed order, the money rule,
  Benjamini-Hochberg, randomisation inference, event study, placebos,
  legal regimes and legal access, as written there.

## Data needed

The front matter lists only datasets already in `data/catalog.yaml`. New,
added by campaign 0008's build tasks: `sim_homicides`,
`ibge_population_annual`, `tse_receipts` (and the build of `politics_panel`,
whose catalog entry exists, sealed by half).

## Status

- 2026-11-13: proposed. Campaign 0008 drafted
  (`research/campaigns/0008-gold-ballot-yes-no/`).
- 2026-11-13: exploring. Campaign 0008 (`research/campaigns/0008-gold-ballot-yes-no/`)
  starts when this pull request merges.

## Log

- Brief: Gabriel's "Campaign 0008 brief: the yes/no gold fork of campaign
  0007", 2026-11-13 (written in claude.ai; not in the repository).
- Born from: campaign 0007's report, decision 2, option B, and run record
  `research/explore-runs/0007/43438404852.md`.
