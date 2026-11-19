---
id: "0010"
title: "What do budget amendments buy at the ballot box? The municipality's share of the deputy's money"
status: promising
created: 2026-11-19
updated: 2026-11-19
datasets:
  - amendments_panel
  - camara_deputies
  - tse_general
  - cgu_amendments
  - tse_results
  - tse_candidates
  - municipalities
  - ibge_population_annual
kill_criteria:
  - "Too little power: neither outcome is powered. The share outcome is powered if its first-stage minimum detectable effect (80% power, alpha 0.025) is at most 25% of its pre-window mean; log reais per inhabitant is powered if its MDE is at most 0.223 log points (stated by Gabriel in his brief, 2026-11-18)."
  - "Unbalanced design: in the window chosen by decision 0008's balance rule, a powered outcome's placebo slope in the pre window is above its threshold (share: |b| above 25% of its mean; log reais per inhabitant: |b| above 0.223), or the placebo slope on the deputy's vote share at the previous general election is above 25% of its mean (stated by Gabriel in his brief, 2026-11-18)."
  - "Broken author link: in some cycle, the deputies linked to authors receive less than 90% of the window money of current-legislature authors, senators left out (stated by Gabriel in his brief, 2026-11-18)."
  - "Weak first stage: no powered outcome has a municipality-clustered first-stage F statistic of at least 10 (stated by Gabriel in his brief, 2026-11-18, as the kill-rule library's first_stage_strength)."
related: ["0009", "0003", "0004"]
---

# 0010: What do budget amendments buy at the ballot box? The municipality's share of the deputy's money

## Claim

The claim of idea 0009 (`research/ideas/0009-amendments-ballot-box.md`),
unchanged: when a federal deputy's party narrowly wins a mayoralty, the
deputy sends more individual budget amendment money (emendas) to that
municipality, and that money turns into votes for the deputy at the next
general election. Only the measure of the money changes.

**The outcomes were chosen after a failed power gate.** Idea 0009 is dead:
campaign 0010's gate (`research/explore-runs/0009/44394848609.md`) met two
kill rules. The first stage in reais per 1,000 inhabitants had a minimum
detectable effect of 0.526 of its pre-election mean (limit 0.25), and the
author link matched 0.569 of the authors in cycle C (limit 0.90). The other
four rules passed (window 10%, 3,017 close races, both placebos flat). This
idea measures the money in two other ways, chosen by Gabriel *after* he saw
that failure: the municipality's share of all the deputy's amendment money,
and the log of reais per inhabitant. Every threshold is unchanged from idea
0009: 25% of the mean, F ≥ 10, 90% for the link, 200 races, decision 0008's
window rule. The log outcome's 0.223 is ln(1.25), the same 25%. This is a
second look at the same question with new measures, so any result here
counts as one more analysis on the exploration half, and the report must
say so.

The author link was also rebuilt before this idea runs (owner fix,
PR #421): names matched more loosely, ties broken by the state that got
most of the author's money, only authors of the legislature elected at t0,
and the Chamber of Deputies' own list of names. Its test is now by money,
not by head count.

## Prediction

Written before any post-election outcome is read (Gabriel's brief,
2026-11-18):

- First stage: a close win of the deputy's party raises the share of the
  deputy's amendment money that goes to the municipality in the two years
  after the mayoral election, and the log of reais per inhabitant (b > 0).
- Reduced form: the deputy's vote share in the municipality rises from the
  previous to the next general election where the party narrowly won
  (b > 0).
- Placebos: no difference in either outcome in the 21 months before the
  mayoral election, nor in the deputy's vote share at the previous general
  election.

Against the idea: no outcome with enough power, an unbalanced placebo, a
broken author link, or no outcome with a strong first stage.

## Design

The design of idea 0009, unchanged except for the outcomes:

- **Races, cycles, unit.** Mayoral elections 2016, 2020 and 2024 (cycles A,
  B, C), whole country, deciding round. Deputy × municipality × cycle, only
  where the deputy's party had one of the two finalists.
- **Model.** Y = b·Win + g·margin + d·Win·margin + deputy-by-cycle fixed
  effects, |margin| ≤ h; h by decision 0008's balance rule, plus 5% as a
  fixed check; standard errors clustered by municipality; randomisation
  inference re-flipping close races, 2,000 draws.
- **Outcomes (first stage).**
  - `share`: the municipality's share of all the individual amendment money
    the deputy paid to identified municipalities in the window
    (`amend_post_share`; `amend_pre_share` for the placebo and the power).
    Undefined where the deputy paid nothing in the window.
  - `log_pc`: ln(1 + reais per inhabitant) (`amend_post_log_pc`;
    `amend_pre_log_pc`).
- **Power and testing.** Two outcomes, so each is tested at alpha 0.025
  (two-sided). Only outcomes powered at the gate are estimated in the main
  run, as the gate's run record says.
- **Reduced form.** The change in the deputy's vote share in the
  municipality.
- **Secondary, declared now.** b by cycle and the C-minus-A difference;
  votes per real (a Wald ratio), labelled an upper bound, because allied
  mayors also campaign.
- **Sample.** Exploration half only (decision 0011's national split, by
  municipality).

## Data needed

`amendments_panel` (v2, PR #421), built from `tse_general`,
`cgu_amendments`, `camara_deputies` (new: the Chamber's list of deputies,
acquired in the campaign's first step), `tse_results`, `tse_candidates`,
`municipalities` and `ibge_population_annual`. Campaign 0011
(`research/campaigns/0011-amendments-share-of-quota/`).

## Status

- 2026-11-19: proposed, from Gabriel's brief of 2026-11-18, after idea 0009
  died in campaign 0010.
- 2026-11-19: exploring. Campaign 0011 (`research/campaigns/0011-amendments-share-of-quota/`)
  starts when this pull request merges.
- 2026-11-19: promising, the recommendation of campaign 0011's close-out report (`research/campaigns/0011-amendments-share-of-quota/report.md`); Gabriel accepts it by approving this pull request. Both explore runs survived every kill rule; only `log_pc` was powered, with a positive first stage (b 0.192) and reduced form (b 0.0119) on the exploration half.

## Variants tried

None: no fork was declared.

## Log

- Idea 0009 and campaign 0010 (`research/campaigns/0010-amendments-second-attempt/report.md`).
- Owner fix PR #421 (amendments panel v2).
- Campaign 0011 PR (this pull request).
