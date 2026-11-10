---
id: "0006"
title: "The geography of representation: do narrow council winners' voters' places get more of the state?"
status: proposed
created: 2026-11-10
updated: 2026-11-10
datasets:
  - tse_votes_by_section
  - tse_polling_places
  - polling_stations_geocoded
  - tse_results
  - tse_candidates
  - tse_parties
  - municipalities
  - polling_places
  - section_votes
  - ibge_boundaries_2024
  - place_outcomes
kill_criteria:
  - "Too few close pairs: fewer than 10,000 close council pairs at the 0.50% window, pooled 2008-2020, in the exploration half (stated by Gabriel, 2026-11-10)."
  - "Polling places too poorly located: less than 85% of sections, pooled, sit at a polling place located within 1 km error (stated by Gabriel, 2026-11-10)."
  - "Too few schools found: less than 50% of polling places are matched to an INEP school at high or medium confidence (stated by Gabriel, 2026-11-10)."
  - "Unbalanced baselines: the joint randomisation-inference test of the baseline school facility count, night lights and built-up share on D_p has p below 0.05 (stated by Gabriel, 2026-11-10)."
  - "A non-flat placebo: D_p predicts the t-4 to t change in the municipal-school facility count with randomisation-inference p below 0.10 (stated by Gabriel, 2026-11-10)."
  - "Underpowered: the minimum detectable effect on the municipal-school facility count at 80% power (5%, two-sided) is above 0.05 standard deviations of the pre-election change (stated by Gabriel, 2026-11-10)."
related: ["0001", "0004"]
---

# 0006: The geography of representation: do narrow council winners' voters' places get more of the state?

## Claim

When a candidate narrowly wins a council seat, the places where their own
voters live get more of the state during the term: better-equipped
municipal schools, more light at night, more built-up area and more cleared
native vegetation. Councillors cannot spend, but they amend budgets, ask the
mayor for works and broker services. If that brokerage goes to their own
voters, it should show up where those voters vote.

## Prediction

At a polling place p, D_p sums, over the municipality's close council pairs,
the narrow winner's share of the place's valid votes minus the narrow
loser's. The claim predicts a positive effect of D_p on the change in the
number of facilities (0 to 9) at the municipal school that is the polling
place, from the election year t to t+4. The test is two-sided. The same
outcome at state schools is a falsification test and should be near zero,
since municipal councils have no say over state schools. Night lights,
built-up area and native-vegetation loss around p are secondary outcomes,
with Benjamini-Hochberg correction across the three. A null on the primary
outcome counts against the idea. So does a clear effect on state schools of
the same size as on municipal schools.

## Design

- **Scope:** all of Brazil (decision 0011). The exploration half is the
  union of the two exploration lists, through
  `terrain.explore.exploration_municipalities(store, national=True)`.
- **Close pairs:** the last elected and the first non-elected candidate on
  the same list (`terrain.strongholds`). The margin is their vote difference
  over the municipality's valid votes. Council elections 2008, 2012, 2016
  and 2020. Main window 0.50%; robustness 0.25% and 1.00%.
- **Unit:** the polling place p, and the INEP school at p where it is
  matched.
- **Treatment:** D_p, the sum over the municipality's close pairs of
  (winner's share of valid votes at p minus the loser's).
- **Controls:** S_p, the sum of both candidates' shares at p (fixed before
  the election), the baseline level of the outcome, and
  municipality-by-election fixed effects.
- **Estimate:** Y_change_p = beta * D_p + gamma * S_p + delta * Y_base_p +
  FE. Inference is by randomisation inference that re-draws the winner of
  each pair (2,000 draws). Municipality-clustered standard errors are
  reported alongside. Re-drawing the winner gives D_p a mean of zero given
  S_p, which is the recentring of Borusyak and Hull
  (`borusyakNonrandomExposureExogenous2023`).
- **Heterogeneity (one, pre-set):** whether the winner's party is in the
  elected mayor's coalition (idea 0004's definition).

## Data needed

- New or extended (campaign 0005): national `tse_votes_by_section`,
  `polling_places` and `section_votes`. Also `inep_schools`,
  `inep_school_catalogue`, `school_polling_match`, `viirs_annual`,
  `mapbiomas_coverage_national` and `place_outcomes` (sealed like
  `cell_outcomes`).
- Existing: `tse_polling_places` (already national), `tse_results`,
  `tse_candidates`, `tse_parties`, `municipalities`,
  `polling_stations_geocoded` and `ibge_boundaries_2024`.

## Status

- 2026-11-10: proposed. Campaign 0005 drafted
  (`research/campaigns/0005-geography-of-representation/`).

## Log

- Decision 0011 (national scope and the split outside the Legal Amazon),
  PRs #280, #282 and #288.
