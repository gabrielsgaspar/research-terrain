---
id: "0005"
title: "Enforcement shielding around council winners' strongholds"
status: parked
created: 2026-11-09
updated: 2026-11-11
datasets:
  - cell_enforcement
  - cell_exposure
  - grid_cells
  - tse_votes_by_section
  - tse_polling_places
  - polling_stations_geocoded
  - tse_candidates
  - tse_results
  - ibge_municipalities
  - ibge_boundaries_2024
kill_criteria:
  - "Too few elections with usable locations: fewer than 3 of the elections 2008-2020 have at least half of the pre-election (E-4 to E-1) flora fines and embargoes of exploration-half municipalities located inside their own municipality (stated by Gabriel, 2026-11-09)."
  - "Enforcement too rare near strongholds: fewer than 400 located pre-election flora fines and embargoes, pooled 2008-2020, in the cells exposed to close pairs at the 0.50% window (stated by Gabriel, 2026-11-09)."
  - "Underpowered: the minimum detectable effect at 80% power (5%, two-sided) at the registered 0.25% window is above 25% of the pre-election baseline mean, anchored to Katovich & Moffette's estimates of violations under landholder-financed mayors (15% or 27% depending on the version of the paper; unverified web find) (stated by Gabriel, 2026-11-09)."
  - "A non-flat placebo: at the 0.50% window, stronghold exposure predicts pre-election flora fines and embargoes with randomisation-inference p below 0.10 (stated by Gabriel, 2026-11-09)."
related: ["0001"]
---

# 0005: Enforcement shielding around council winners' strongholds

## Claim

After a close council win, federal environmental enforcement (IBAMA flora
fines and embargoes) falls less often near the winner's polling-station
stronghold than near the loser's: winners shield their voters from
enforcement.

## Prediction

Written before any enforcement data exists in the project.

- The winner-minus-loser exposure of decision 0004 has a **negative** effect
  on flora fines plus embargoes per 1 km cell in the four years after the
  election (t+1 to t+4). The test is two-sided.
- The same exposure has no effect on enforcement in the four years before
  the election (placebo).

Against the idea: a placebo that is not flat, or a post-election effect
that is zero or positive with adequate power.

This idea estimates enforcement only. It does not condition on clearing and
uses no per-hectare ratio, because clearing is itself affected by the
treatment (idea 0001's H1). Reading the two together is later work.

## Design

Idea 0001's direct design, unchanged except for the outcome:

- Close within-list council pairs and their strongholds as in
  `terrain.strongholds`; elections 2008-2020; exploration half only.
- Exposure (decision 0004): exp(-d/2 km) to 10 km, winner minus loser,
  recentred as D / 2.
- Regression on D / 2 with municipality-by-election fixed effects;
  randomisation inference by re-flipping close pairs (decisions 0004, 0005).
- Outcome: IBAMA flora fines plus embargoes per cell, summed over t+1 to
  t+4; fines and embargoes separately as secondary outcomes. A record counts
  only if its point lies inside its own municipality's polygon.
- Effect read as decision 0007 does: slope times mean |D| over the exposed
  cells, as a share of their pre-election (t-4 to t-1) baseline mean.
- Windows: power at 0.25% (the registered window, decision 0008) and 0.50%;
  every estimate on the exploration half at 0.50% only.

## Data needed

New: `ibama_autos` (IBAMA fines, with the coordinates file), `ibama_embargos`
(IBAMA embargoes), and the `cell_enforcement` build, sealed like
`cell_outcomes` (decision 0003). Both IBAMA datasets come from IBAMA's
open-data portal, or, if any download from it fails, from Base dos Dados
on BigQuery (`basedosdados.br_ibama_fiscalizacao.auto_infracao` and
`area_embargada`), in the same schema. No personal identifier is stored. Existing: `cell_exposure`, `grid_cells`,
the TSE tables, `ibge_municipalities` and `ibge_boundaries_2024`.

## Status

- 2026-11-09: proposed. Campaign 0004
  (`research/campaigns/0004-enforcement-shielding/`) acquires the IBAMA data,
  builds `cell_enforcement`, checks coverage, power and the placebo on
  pre-election years, and only then estimates the post-election effect at
  0.50%.
- 2026-11-10: campaign 0004 stopped at its power gate. Kill rule k3 was met:
  the minimum detectable effect at 0.25% is 0.77 of the pre-election baseline,
  against a bar of 0.25 (`research/explore-runs/0005/42796832006.md`). No
  post-election year was read. Status is unchanged; Gabriel decides it.
- 2026-11-10: parked after campaign 0004 (power gate k3: MDE 0.77 vs
  0.25); may return as a secondary outcome of idea 0006.

## Log

- 2026-11-09: idea drafted with campaign 0004.
