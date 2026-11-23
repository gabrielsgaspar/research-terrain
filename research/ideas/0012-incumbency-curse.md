---
id: "0012"
title: "Did the incumbency curse of Brazilian mayors' parties lift in 2020?"
status: promising
created: 2026-11-22
updated: 2026-11-23
datasets:
  - mayor_incumbency_panel
kill_criteria:
  - "Unbalanced design: the omnibus randomisation p of the design's own model, fitted with fin_female, fin_age, fin_higher_ed, finalist_eligible and (2012-2020) bench_fed > 0 as outcomes, 2008-2020 pooled, is below 0.05 (decision 0017; stated by Gabriel in his brief, 2026-11-22)."
  - "Lagged-outcome jump: the jump in party_held_mayor_lag is larger than 0.05 in absolute value and its randomisation p is below 0.05 (stated by Gabriel in his brief, 2026-11-22)."
  - "Too little power: the minimum detectable H1 difference (80% power, alpha 0.05, scaled to any 0/1 outcome) is above 0.20, a swing from Klasnja and Titiunik's -0.15 to +0.05 (stated by Gabriel in his brief, 2026-11-22)."
  - "Too few races: fewer than 300 exploration-half races inside h in some election of 2008, 2012, 2016 and 2020 (stated by Gabriel in his brief, 2026-11-22)."
related: ["0011", "0010", "0009", "0003"]
---

# 0012: Did the incumbency curse of Brazilian mayors' parties lift in 2020?

## Claim

Brazilian mayors' parties used to be cursed: a party that narrowly won a
mayoralty was less likely to win it again four years later than one that
narrowly lost (Klašnja and Titiunik 2017). If money paid straight to town
halls since 2020 (individual amendments, and the "emendas Pix" among them)
helps whoever holds the office, the curse should weaken or turn into an
advantage for the 2020 election (outcome 2024), against 2008-2016.

## When and why this idea was formed

**This idea was formed after campaign 0012's gate**
(`research/explore-runs/0011/44768996266.md`), which stopped idea 0011
before any outcome at e+4 was read. It reuses idea 0011's data
(`mayor_incumbency_panel`, as campaign 0012 built it) and asks the same
first question as idea 0011's H1, on the same exploration half. What
changed, and why:

- **The design is fixed now, before any outcome is read**, under decision
  0017 (`research/decisions/0017-rd-validity.md`), not decision 0008.
  Decision 0008's rule is a local-randomisation rule (differences in
  means in nested windows), while the estimator is a local linear
  regression discontinuity. In wide windows a difference in means picks
  up slopes, and at its first window the rule stops a valid design 15% of
  the time by construction. Idea 0011's gate found no window because its
  smallest, 0.5%, failed narrowly (omnibus p 0.07 against 0.15; the 1%,
  2% and 3% windows passed), and its count, power and placebo rules were
  then computed at 0.5%, with 58 to 71 races per election.
- **The bandwidth and kernel come from the literature, not from balance**:
  Klašnja and Titiunik's triangular kernel and bandwidth, h = 0.135.
- **The power limit is set against a published effect**: their -0.15.
  Idea 0011's limit (0.10) was stricter than the hypothesis. A curse of
  that size turning into even a small advantage is a swing of 0.20 or
  more, and the re-election rate of mayors who ran went from 49% (2016) to
  64% (2020) to 82% (2024) (CNM and TSE, as stated in Gabriel's brief;
  press reports, unverified here).
- **Primary alpha 0.05**, one primary hypothesis (idea 0011 had two at
  0.025).

Idea 0011 stays dead. Idea 0012 is a new question with a new design on
data already seen at the gate stage (counts and balance only, never an
outcome at e+4); the report must say so, and count any result as a
further analysis of the same exploration half.

## Prediction

Close mayoral races, exploration half only (decision 0011), elections e
= 2004 to 2020, outcomes at e+4 (2008 to 2024).

**Estimator** (the model of `explore/0011_incumbency_gate.py`, now
weighted):

- per election an intercept, a slope in the margin and a win × margin
  slope; one `win` coefficient per group of elections;
- weighted by a triangular kernel, 1 - |margin|/h, with h = 0.135, on
  rows with |margin| < h;
- errors clustered by municipality (`cd_ibge`);
- randomisation inference re-flipping races, 2,000 draws.

**H1 (primary, alpha 0.05).** Outcome `party_wins_next` (the party wins
the mayoralty at e+4; 0 if it does not), all rows (their measure). The
effect at e = 2020 minus the effect at e in {2008, 2012, 2016} pooled is
positive.

Against the idea: a difference that is not positive, or not significant
at 0.05.

**Secondary, all declared now:**

- **S1.** Each election 2004-2020 on its own, and 2004-2012 pooled as a
  replication of Klašnja and Titiunik's -0.15.
- **S2. The personal effect.** `finalist_wins_next` (0 when the person
  does not run) on rows with `finalist_eligible` true: the H1 contrast and
  each election.
- **S3.** `party_runs_next` and `finalist_runs_next`.
- **S4. Connected parties.** The H1 contrast for `bench_fed` > 0 minus
  `bench_fed` = 0, 2020 against 2012 and 2016.
- **S5. Town money**, one row per race: races of 2016 and 2020 whose two
  finalists' parties differ in `bench_fed`, the row of the
  better-connected party. Outcomes ln(1 + `amend_after_total` /
  `population_e`) and, for 2020, the same with `amend_after_pix`; 2020
  minus 2016 for the total.

**Robustness, all reported:** uniform kernel at 5%, 7.5% and 10%;
triangular at 10% and 20%; adding `fin_female`, `fin_age`,
`fin_higher_ed` and state-by-election fixed effects.

## Design

`mayor_incumbency_panel`: two rows per race, the top two finalists of the
deciding round, elections 2004-2020. Treatment `win` (`margin` > 0).
Outcomes at e+4 follow the party through mergers and federations
(`src/terrain/parties.py`).

**Validity (decision 0017).** The design's own model with each
predetermined covariate as the outcome (`fin_female`, `fin_age`,
`fin_higher_ed`, `finalist_eligible`, and for 2012-2020 `bench_fed` > 0),
2008-2020 pooled, with an omnibus randomisation p; the lagged outcome
`party_held_mayor_lag` as a placebo. Decision 0008's table is computed
and shown, as information only.

**Bandwidth and kernel, with their source (decision 0017, point 1).**
Klašnja and Titiunik (2017) estimate the party incumbency effect for
Brazilian mayors at -0.15 (95% CI -0.21 to -0.10; elections 2000-2012;
local linear, triangular kernel, MSE-optimal bandwidth 13.55 points of
margin, with covariate and density checks), as stated in Gabriel's brief
(web, unverified here). This idea uses their kernel and h = 0.135.

**Other explanations** a change over time must face:

- the 2020 election was held in the pandemic;
- campaign finance changed: company donations were banned from 2016, and
  the public campaign fund began in 2018;
- coalitions in council elections ended in 2020.

So a change over time is not by itself the effect of Pix. S4 and S5 are
the link to the money, and they are weak: the federal bench is
predetermined but not randomised, and the money is only known after e.

## Literature

- Klašnja and Titiunik (2017), "The Incumbency Curse: Weak Parties, Term
  Limits, and Unfulfilled Accountability", *APSR* 111(1), 129-148 (web,
  unverified; the numbers above are from Gabriel's brief).
- Avelino Filho, Biderman and Desposato (2022), *BPSR* 16(1)
  (`avelinofilhoSourcesIncumbencyDisAdvantage2022`).
- Calonico, Cattaneo and Titiunik (2014), *Econometrica* 82(6): the
  MSE-optimal bandwidth behind Klašnja and Titiunik's choice (web,
  unverified).
- Idea 0011 (`research/ideas/0011-who-gains-from-pix.md`) and its
  literature.

## Data needed

`mayor_incumbency_panel` only, as campaign 0012 built it (run
44766227487; `data/manifests/build/mayor_incumbency_panel.json`). No new
data and no build.

## Status

- 2026-11-22: proposed (Gabriel's brief, 2026-11-22).
- 2026-11-22: exploring. Campaign 0014 (`research/campaigns/0014-incumbency-curse/`)
  starts when this pull request merges.
- 2026-11-23: promising, the recommendation of campaign 0014's close-out report (`research/campaigns/0014-incumbency-curse/report.md`); Gabriel accepts it by approving this pull request. The gate, the main run and fork f1 passed every kill rule on the exploration half; the main run's H1 difference is 0.216 (RI p 0.0005), and nothing here is a finding.

## Variants tried

- f1 (parent step s2): uniform kernel with |margin| <= 0.10 instead of triangular with h = 0.135, in every gate fit; survived (fork), 1 of 1 tried at s2.

## Log

- Campaign 0014's pull request: this file, decision 0017 and the campaign.
