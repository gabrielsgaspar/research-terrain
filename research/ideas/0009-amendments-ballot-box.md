---
id: "0009"
title: "What do budget amendments buy at the ballot box?"
status: dead
created: 2026-11-15
updated: 2026-11-18
datasets:
  - amendments_panel
  - tse_results
  - tse_candidates
  - municipalities
  - ibge_population_annual
kill_criteria:
  - "Weak first stage: in close mayoral races, the municipality-clustered F statistic of the deputy's party winning on the amendments the deputy pays to the municipality (per 1,000 inhabitants) is below 10 (stated by Gabriel in his brief, 2026-11-15, as the kill-rule library's first_stage_strength)."
  - "Unbalanced design: in the window chosen by decision 0008's balance rule, the placebo slope on amendments paid in the 21 months before the mayoral election, or on the deputy's vote share at the previous general election, is larger in absolute value than 25% of its mean (suggested by Claude, confirmed by Gabriel on 2026-11-15)."
  - "Too little power: the first stage's minimum detectable effect at 80% power is above 25% of the pre-election mean of amendments per 1,000 inhabitants (stated by Gabriel in his brief as the library rule power_mde_share; confirmed 2026-11-15)."
related: ["0003", "0004"]
---

# 0009: What do budget amendments buy at the ballot box?

## Claim

When a federal deputy's party narrowly wins a mayoralty, the deputy sends
more individual budget amendment money (emendas) to that municipality, and
that money turns into votes for the deputy at the next general election.
How much money and how many votes changed across three rule regimes:
mandatory individual amendments (from the 2015 budget), special transfers
("Pix", from 2020) and the end of rapporteur amendments (ruled
unconstitutional in December 2022).

## Prediction

Written before any outcome is read (Gabriel's brief, 2026-11-15):

- First stage: a close win of the deputy's party raises the amendments the
  deputy pays to the municipality in the two years after the mayoral
  election (b > 0), more so from 2020, when Pix transfers go straight to
  the municipal treasury.
- Reduced form: the deputy's vote share in the municipality rises from the
  previous to the next general election where the party narrowly won
  (b > 0).
- Placebos: no difference in amendments paid in the two years before the
  mayoral election, nor in the deputy's vote share at the previous general
  election.

Against the idea: a weak first stage, an unbalanced placebo, or a first
stage with too little power to detect a quarter of the baseline.

## Design

- **Races.** Mayoral elections 2016, 2020 and 2024, whole country, deciding
  round. Margin = votes of the deputy's party's finalist minus the other
  finalist's, over valid votes.
- **Cycles.** A: mayor 2016, amendments 2017-18, deputy votes 2018 vs 2014.
  B: 2020, 2021-22, 2022 vs 2018. C: 2024, 2025-26, 2026 vs 2022.
- **Unit.** Deputy × municipality × cycle, only where the deputy's party
  (at the deputy's last general election) had one of the two finalists.
- **Model.** Y = b·Win + g·margin + d·Win·margin + deputy-by-cycle fixed
  effects, |margin| ≤ h; h chosen by decision 0008's balance rule, plus 5%
  as a fixed check; standard errors clustered by municipality;
  randomisation inference re-flipping close races, 2,000 draws.
- **First stage.** Individual amendments paid by the deputy to recipients
  in the municipality, per 1,000 inhabitants (also asinh and any > 0; Pix
  vs other from 2020).
- **Reduced form.** The change in the deputy's vote share in the
  municipality.
- **Secondary, declared now.** b by cycle and the C-minus-A difference;
  the votes-per-real Wald ratio, labelled an upper bound (allied mayors also
  campaign); a split at 10,000 inhabitants.
- **Sample.** Exploration half only (decision 0011's national split, by
  municipality).

## Data needed

New: `tse_general` (TSE general-election votes and candidates),
`cgu_amendments` (CGU Portal da Transparência amendment payments) and the
built `amendments_panel` (the first two get their catalog entries in the
campaign's step s1, so they are not yet in the front matter). Existing: `tse_results`, `tse_candidates`,
`municipalities`, `ibge_population_annual`. Campaign 0009
(`research/campaigns/0009-amendments-ballot-box/`).

## Status

- 2026-11-15: proposed, from Gabriel's brief of the same day.
- 2026-11-15: exploring. Campaign 0009 (`research/campaigns/0009-amendments-ballot-box/`)
  starts when this pull request merges.
- 2026-11-18: parked, the recommendation of campaign 0009's close-out report (`research/campaigns/0009-amendments-ballot-box/report.md`); Gabriel accepts it by approving this pull request. The panel build (s5) failed in 4 runs, so the power gate and the main run never ran and the idea was not tested.
- 2026-11-18: exploring. Campaign 0010 (`research/campaigns/0010-amendments-second-attempt/`)
  starts when this pull request merges.
- 2026-11-18: dead, the recommendation of campaign 0010's close-out report (`research/campaigns/0010-amendments-second-attempt/report.md`); Gabriel accepts it by approving this pull request. The gate run (`research/explore-runs/0009/44394848609.md`) met two kill rules: power (MDE share 0.526, limit 0.25) and the author link (smallest share 0.569, limit 0.9); no fork was declared.

## Variants tried

None: no fork was declared.

## Log

- Campaign 0009 PR (this pull request).
