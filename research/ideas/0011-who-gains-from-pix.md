---
id: "0011"
title: "Who gains from emendas Pix, deputies or mayors?"
status: exploring
created: 2026-11-20
updated: 2026-11-20
datasets:
  - mayor_incumbency_panel
  - amendments_panel
  - amendments_monthly
  - tse_general_parties
  - tse_results
  - tse_candidates
  - tse_parties
  - tse_general
  - cgu_amendments
  - municipalities
  - ibge_population_annual
  - camara_deputies
kill_criteria:
  - "No close-race window: decision 0008's balance rule finds no window for the mayoral finalists, 2004-2020 pooled (stated by Gabriel in his brief, 2026-11-20)."
  - "Too few races: fewer than 300 exploration-half races within the chosen window in some election of 2008, 2012, 2016 and 2020 (stated by Gabriel in his brief, 2026-11-20)."
  - "Too little power: the minimum detectable H1 difference (80% power, alpha 0.025) is above 0.10, ten percentage points of the probability that the party wins again (stated by Gabriel in his brief, 2026-11-20)."
  - "Unbalanced design: the placebo jump in party_held_mayor_lag (the party held the mayoralty four years before) is above 0.05 in absolute value at the chosen window (stated by Gabriel in his brief, 2026-11-20)."
related: ["0009", "0010", "0003", "0004"]
---

# 0011: Who gains from emendas Pix, deputies or mayors?

## Claim

Special transfers ("emendas Pix", individual budget amendments paid
straight to a municipality's account since 2020) help the mayor's party
win the town again more than they help the federal deputy who sends them.
If so, the party incumbency effect in close mayoral races rises from the
2008-2016 elections to 2020 (outcome in 2024), more where the party's
federal bench in the state is larger. Meanwhile the deputy's own vote
gain from an allied mayor does not grow.

**This question was formed after seeing results.** Gabriel framed it after
two things:

- the exploration-half results of campaign 0011
  (`research/campaigns/0011-amendments-share-of-quota/report.md`, idea
  0010): a first stage that grows by cycle, while the deputy's
  reduced-form vote gain does not grow;
- the public national trend: mayors' reelection rate is rising (the CNM
  reported a record share re-elected in 2024; press, unverified).

So no result here confirms anything. Campaign 0011's exploration half is
the same exploration half used here (decision 0011), and the report must
count this as a further analysis of the same data, not an independent
test. Ideas 0009 (`research/ideas/0009-amendments-ballot-box.md`, dead
after campaign 0010) and 0010 asked whether amendments buy the deputy
votes; this idea asks who else gains. Campaigns 0009, 0010 and 0011 built
and tested the amendments panel this idea reuses.

## Prediction

Close mayoral races, exploration half only, windows by decision 0008's
balance rule, standard errors clustered by municipality, randomisation
inference by re-flipping races (2,000 draws).

Primary (alpha 0.025 each):

- **H1.** The party incumbency effect (the jump at margin 0 in
  `party_wins_next`, the party winning the mayoralty again at e+4) is
  larger for the election of 2020 (outcome 2024) than for 2008, 2012 and
  2016 pooled (outcomes 2012-2020). Brazil's party incumbency effect was
  negative for 1996-2012 (Klašnja and Titiunik 2017), so "larger" may
  mean less negative. Every cycle 2004→2008 to 2020→2024 is reported, and
  the same for the finalist as a person (eligible finalists only).
- **H2.** In 2020→2024 the effect rises more where the party's federal
  bench in the state (`bench_fed`, the deputies it elected two years
  before e, fixed before the mayoral race) is larger: the win × bench_fed
  coefficient is larger for 2020 than for 2012 and 2016 pooled. Its first
  stage is the same coefficient on ln(1 + Pix reais per inhabitant) paid in
  the term.

Secondary:

- **H3 (within-list zero-sum).** In the amendments panel, the deputy's own
  vote share change gains less from an allied mayor than the deputy's
  party's share change, by cycle.
- **H4 (brokerage benchmark).** The party's state-deputy share change,
  for deputies who send no federal amendments, by cycle.
- **H5 (selection).** The effect of an allied mayor on whether the deputy
  runs again; Lee bounds on H3's own share change if it is nonzero.
- **H6 (timing).** Monthly payments to allied and non-allied towns, in
  event time from the mayor's inauguration and to the general election.

Against the idea: no rise in H1 (or a fall), no H2 gradient, or a
first stage that does not follow the bench.

## Design

- **Mayors** (`mayor_incumbency_panel`): two rows per race, the top two of
  the deciding round, for 2004, 2008, 2012, 2016 and 2020. The treatment
  is `win` (`margin` > 0). The outcomes at e+4 follow the party through
  mergers and federations (`src/terrain/parties.py`).
- **Deputies** (`amendments_panel` v3 and `amendments_monthly`): the panel
  of ideas 0009 and 0010, cycles A (mayor 2016), B (2020) and C (2024),
  at the 7.5% window chosen by campaign 0011's gate
  (`research/explore-runs/0010/44484340952.md`), with deputy-by-cycle
  fixed effects.
- Decisions 0003 (confirmation rows), 0008 (window), 0011 (national
  split). Exploration half only.

The comparison is credible to the extent close races are as good as
random, which decision 0008's balance rule and the lagged-incumbency
placebo check. Bench size is not randomised: H2 is a heterogeneity test
on a predetermined variable, not a second experiment.

## Literature

- Klašnja and Titiunik (2017), "The Incumbency Curse: Weak Parties, Term
  Limits, and Unfulfilled Accountability", *APSR* 111(1), 129-148: a
  negative party incumbency effect for Brazilian mayors, 1996-2012 (web,
  unverified).
- Avelino Filho, Biderman and Desposato (2022), *BPSR* 16(1)
  (`avelinofilhoSourcesIncumbencyDisAdvantage2022`).
- Baião and Couto (2017), "A eficácia do pork barrel", *Opinião Pública*
  23(3), doi:10.1590/1807-01912017233714 (web, unverified).
- Novaes (2018), "Disloyal Brokers and Weak Parties", *AJPS* 62(1):
  mayors as brokers who switch the deputies they work for (web,
  unverified).
- Brollo and Nannicini (2012), *APSR* 106(4): close mayoral races and
  federal transfers (web, unverified).
- Stokes, Dunning, Nazareno and Brusco (2013), *Brokers, Voters, and
  Clientelism*, Cambridge University Press (web, unverified).

## Data needed

`mayor_incumbency_panel`, `amendments_panel` (v3, with party and
state-deputy shares), `amendments_monthly` and `tse_general_parties`, all
catalogued, contracted and dry-run in PR #436. Their inputs are listed
above.

## Status

- 2026-11-20: proposed (Gabriel's brief, 2026-11-20).
- 2026-11-20: exploring. Campaign 0012 (`research/campaigns/0012-who-gains-from-pix/`)
  starts when this pull request merges.

## Variants tried

None yet.

## Log

- PR #436: the three builds and the party-vote acquire.
