---
id: "0012"
title: "Who gains from emendas Pix, deputies or mayors? Party incumbency in close mayoral races, 2004-2024, and the deputy's own and party vote"
status: done
idea: "0011"
owner: gabrielsgaspar
created: 2026-11-20
end_by: 2026-12-08
budget:
  max_tasks: 4
  max_explore_runs: 4
  max_pipeline_runs: 4
  max_model_jobs: 50
referee_not_applicable_ok: [R5]
self_repair: true
oversize_reason: "one question with two panels; the builds, gate, three analyses and the figures are one chain"
forks:
  max_forks: 3
  per_point: 3
  max_new_datasets: 1
  max_steps_per_fork: 4
  types: [transform, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: [s6]
  budget:
    max_tasks: 4
    max_explore_runs: 4
    max_pipeline_runs: 1
    max_model_jobs: 30
datasets:
  - name: tse_general_parties
    source: "TSE open data (cdn.tse.jus.br), votacao_partido_munzona 2014, 2018, 2022 and 2026: party votes by zone, nominal and party-list; raw zips as published"
    licence: "TSE open data: CC BY (dadosabertos.tse.jus.br)"
    max_size_gb: 0.2
    identifiers: none
  - name: mayor_incumbency_panel
    source: "built from tse_results, tse_candidates, tse_parties, municipalities, ibge_population_annual, tse_general and cgu_amendments; two rows per close mayoral race, 2004-2020; split by half"
    licence: "public, as its sources"
    max_size_gb: 0.5
    identifiers: none
  - name: amendments_panel
    source: "built from tse_general, tse_general_parties, cgu_amendments, tse_results, tse_candidates, municipalities, ibge_population_annual and camara_deputies; v3 with party and state-deputy shares; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
  - name: amendments_monthly
    source: "built from tse_general, cgu_amendments, tse_results, tse_candidates, municipalities and camara_deputies; one row per amendments_panel row and month; split by half"
    licence: "public, as its sources"
    max_size_gb: 1
    identifiers: none
steps:
  # Data: the party-vote acquire first (amendments_panel v3 needs it), then the three builds
  - id: s1
    kind: pipeline_run
    stage: acquire
    target: tse_general_parties
    dataset: tse_general_parties
    after: []
  - id: s2
    kind: pipeline_run
    stage: build
    target: mayor_incumbency_panel
    dataset: mayor_incumbency_panel
    after: []
  - id: s3
    kind: pipeline_run
    stage: build
    target: amendments_panel
    dataset: amendments_panel
    after: [s1]
  - id: s4
    kind: pipeline_run
    stage: build
    target: amendments_monthly
    dataset: amendments_monthly
    after: []
  # Gate on the mayoral panel: window, races, power and the lagged placebo; no outcome at e+4
  - id: s5
    kind: task
    type: explore
    draft: drafts/s5.md
    allowed_paths:
      - explore/0011_incumbency_gate.py
      - tests/test_explore_incumbency_gate.py
    after: []
  - id: s6
    kind: explore_run
    script: 0011_incumbency_gate
    after: [s2, s5]
    kill_rules:
      - id: k1
        says: "No mayoral window, not even 0.5%, passes decision 0008's balance rule (2004-2020 pooled)"
        field: window.found
        op: "=="
        value: 0
        confirmed: true
      - id: k2
        says: "Fewer than 300 close mayoral races within the chosen window in some election of 2008, 2012, 2016 and 2020"
        field: counts.min_cycle_races_h
        op: "<"
        value: 300
        confirmed: true
      - id: k3
        says: "The minimum detectable H1 difference (80% power, alpha 0.025) is above 0.10, ten points of the probability of winning again"
        field: power.mde_h1
        op: ">"
        value: 0.10
        confirmed: true
      - id: k4
        says: "The placebo jump in party_held_mayor_lag at the chosen window is above 0.05 in absolute value"
        field: placebo.lag_abs
        op: ">"
        value: 0.05
        confirmed: true
      - id: k5
        says: "Some gate estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Main run on the mayors: H1 and H2 at the gate's window
  - id: s7
    kind: task
    type: explore
    draft: drafts/s7.md
    allowed_paths:
      - explore/0011_incumbency_main.py
      - tests/test_explore_incumbency_main.py
    after: [s6]
  - id: s8
    kind: explore_run
    script: 0011_incumbency_main
    after: [s7]
    kill_rules:
      - id: k1
        says: "Some H1 or H2 estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Mechanisms on the deputies' panels: H3-H6 at campaign 0011's 7.5% window
  - id: s9
    kind: task
    type: explore
    draft: drafts/s9.md
    allowed_paths:
      - explore/0011_amendments_mechanisms.py
      - tests/test_explore_amendments_mechanisms.py
    after: [s6]
  - id: s10
    kind: explore_run
    script: 0011_amendments_mechanisms
    after: [s3, s4, s9]
    kill_rules:
      - id: k1
        says: "Some H3-H6 estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # Figures from the two records and the exploration half
  - id: s11
    kind: task
    type: explore
    draft: drafts/s11.md
    allowed_paths:
      - explore/0011_figures.py
      - tests/test_explore_figures_0011.py
    after: [s8, s10]
  - id: s12
    kind: explore_run
    script: 0011_figures
    after: [s11]
    kill_rules:
      - id: k1
        says: "Fewer than 7 figures were written"
        field: figures.count
        op: "<"
        value: 7
        confirmed: true
    on_kill: stop
---

# 0012: Who gains from emendas Pix, deputies or mayors?

## Question

Do individual budget amendments, and since 2020 the special transfers
("emendas Pix") paid straight into a municipality's account, help the
mayor's party win the town again more than they help the federal deputy
who sends them? Idea 0011 (`research/ideas/0011-who-gains-from-pix.md`).
Two panels answer two halves of the question:

- close mayoral races 2004-2020 and what happened four years later
  (`mayor_incumbency_panel`);
- the deputies' panel of ideas 0009 and 0010, with the deputy's party and
  state-deputy shares (`amendments_panel` v3) and payments by month
  (`amendments_monthly`).

Exploration half only (decision 0011).

**The question was formed after seeing results.** Gabriel framed it after:

- campaign 0011's exploration-half results
  (`research/campaigns/0011-amendments-share-of-quota/report.md`): a
  first stage that grows by cycle, while the deputy's reduced-form vote
  gain does not grow;
- the public national trend of rising mayoral reelection.

The amendments analyses (s9, s10) reuse the exploration half campaign
0011 already analysed. The report must say so and must count them as
further analyses of the same data.

## Already known

Repository scan (`novelty_scan.py`, 2026-11-20) and web searches of the
same day. Campaigns 0009-0011 checked the amendments-and-votes side
(`research/campaigns/0009-amendments-ballot-box/campaign.md`, "Already
known"); not checked again.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Party incumbency effect of Brazilian mayors, close races | explored, 1996-2012 (negative) | (web, unverified) Klašnja and Titiunik, *APSR* 111(1) 2017, 129-148 |
| Sources of the mayoral incumbency (dis)advantage | explored, 2000s-2010s | `avelinofilhoSourcesIncumbencyDisAdvantage2022` |
| Mayors' party in close races → deputies' amendments and votes | explored (one earlier period) | (web, unverified) Baião and Couto, *Opinião Pública* 23(3) 2017 |
| Mayors as brokers for deputies, switching allies | explored | (web, unverified) Novaes, *AJPS* 62(1) 2018 |
| Close mayoral races and federal transfers | explored (the president's coalition) | (web, unverified) Brollo and Nannicini, *APSR* 106(4) 2012 |
| Amendments and mayoral reelection in 2024 | descriptive or unclear design | (web, unverified) Insper policy paper (Casais and Wang) and press counts; Leal and Lima on health amendments and 2024 reelection (design not seen) |
| Deputy's own vs party vs state-deputy share, the party incumbency effect 2020→2024 by bench size, payments in event time | new | no earlier run in this repository; the incumbency and state-deputy pieces were listed as variants in campaigns 0009-0011 |
| Deputy's vote gain from an allied mayor, 2016-2024 | tried, this exploration half | `research/campaigns/0011-amendments-share-of-quota/report.md` |

What this campaign adds:

- the party incumbency effect through 2024, by cycle, with the federal
  bench as a dose;
- the deputy's own share against the party's and the state deputies' in
  the same close races;
- the monthly timing of payments.

## Read before this runs

- **Klašnja and Titiunik (2017)**, "The Incumbency Curse: Weak Parties,
  Term Limits, and Unfulfilled Accountability", *APSR* 111(1), 129-148,
  https://titiunik.github.io/papers/KlasnjaTitiunik2017-APSR.pdf (closest
  for H1; web, unverified). Gabriel: not stated; his brief asks for
  `active` and for questions only on merges, loosened checks or large data
  fixes.
- **Baião and Couto (2017)**, "A eficácia do pork barrel", *Opinião
  Pública* 23(3), doi:10.1590/1807-01912017233714 (closest for H3; web,
  unverified). Gabriel (2026-11-15, for campaign 0009): "Not yet: active
  anyway".
- **Novaes (2018)**, "Disloyal Brokers and Weak Parties", *AJPS* 62(1)
  (web, unverified). Gabriel: not stated.
- **Brollo and Nannicini (2012)**, *APSR* 106(4) (web, unverified).
  Gabriel: not stated.
- **Stokes, Dunning, Nazareno and Brusco (2013)**, *Brokers, Voters, and
  Clientelism*, Cambridge University Press (web, unverified). Gabriel: not
  stated.

## Steps and why

- **s1** (acquire run): `tse_general_parties`, the party-vote zips of
  2014-2026 (`pipeline/acquire/tse_general_parties.py`, PR #436). The
  `amendments_panel` v3 build reads its manifest, so it must come first.
  The host, `cdn.tse.jus.br`, has served runners before (`tse_general`'s
  manifest).
- **s2, s3, s4** (build runs): `mayor_incumbency_panel`, `amendments_panel`
  v3 (after s1) and `amendments_monthly`, all from PR #436. All three
  passed a real-file dry run there. s2 and s4 need nothing earlier, so
  they start with s1, and the builds run at the same time (the
  agent note N007: no single build gates the rest).
- **s5** (explore task): the gate script `explore/0011_incumbency_gate.py`.
  It reads no outcome at e+4, so it is built while the data runs.
- **s6** (gate run): the window by decision 0008's rule, races per
  election at h, the minimum detectable H1 difference, and the lagged
  placebo. Any rule met stops the campaign. A fork point.
- **s7** (explore task) and **s8** (main run): H1 and H2 at s6's window,
  which the script reads from s6's run record by code.
- **s9** (explore task) and **s10** (mechanisms run): H3-H6 on
  `amendments_panel` v3 and `amendments_monthly`, at the 7.5% window of
  campaign 0011's gate run (`research/explore-runs/0010/44484340952.md`).
  s9 waits for the gate (s6) so no code is written for a campaign the gate
  stops. It does not wait for s8.
- **s11** (explore task) and **s12** (figures run): seven figures from
  s8's and s10's records and the exploration half, each labelled
  "exploration half, not a finding".

## Kill rules and why

All stated by Gabriel (brief, 2026-11-20), so all are confirmed.

s6 (the gate):

- **k1** `window.found == 0`: decision 0008's rule finds no window.
- **k2** `counts.min_cycle_races_h < 300`: the fewest exploration-half
  races within h among the elections of 2008, 2012, 2016 and 2020 (the
  elections H1 and H2 compare).
- **k3** `power.mde_h1 > 0.10`: the H1 difference must be detectable at
  ten percentage points of `party_wins_next` (80% power, alpha 0.025).
- **k4** `placebo.lag_abs > 0.05`: the jump in a predetermined outcome
  (the party held the mayoralty at e-4) must be at most five points.
- **k5** `estimates.finite != true`: library rule `finite`.

s8, s10: `estimates.finite != true`. s12: `figures.count < 7`.

Size rules, not p-value rules, so the card's false-stop sum is 0. Every
step uses `on_kill: stop`.

## Budget and why

Stated by Gabriel (brief, 2026-11-20):

- `max_tasks` 4: exactly the four task steps.
- `max_explore_runs` 4: exactly the four run steps.
- `max_pipeline_runs` 4: the acquire and the three builds.
- `max_model_jobs` 50: four tasks at about 7 jobs each (they read new
  data) leave about 22 for fix rounds and repairs.
- `end_by` 2026-12-08: 18 days.

The forks' own budget is also his: `max_tasks` 4, `max_explore_runs` 4,
`max_pipeline_runs` 1, `max_model_jobs` 30.

When a budget runs out, nothing new starts and the tick files the close-out.

## New data

- **`tse_general_parties`** (acquire, s1). TSE's `votacao_partido_munzona`
  zips for 2014, 2018, 2022 and 2026, about 90 MB in all
  (`data/contracts/tse_general_parties.md`). TSE open data, CC BY. Party
  numbers and vote counts only, no personal identifiers. The 2022 and 2026
  files were regenerated by TSE on 2026-11-20 and can change with court
  rulings; the dated raw folder is the snapshot. Fallback: the same files
  from TSE's open-data portal (dadosabertos.tse.jus.br) or Base dos Dados'
  TSE party-vote tables (not checked; web, unverified).
- **`mayor_incumbency_panel`** (build, s2)
  (`data/contracts/mayor_incumbency_panel.md`). It holds no identifier:
  CPF and título link a finalist across elections in memory only, and
  never leave it (2024 publishes no CPF, so the título is needed).
- **`amendments_panel`** (build, s3): v3 adds the four party-share columns.
  New output path, so the v2 panel campaign 0011 read is not overwritten.
- **`amendments_monthly`** (build, s4) (`data/contracts/amendments_monthly.md`).

Existing inputs: `tse_results`, `tse_candidates`, `tse_parties`,
`tse_general`, `cgu_amendments`, `municipalities`,
`ibge_population_annual`, `camara_deputies`.

## Variants in scope for forks (guidance for the ideation job)

Not binding. Gabriel's brief (2026-11-20) lists these; the envelope and
decision 0015 still decide what may run.

1. **spec**: the person-level incumbency effect, eligible finalists only.
2. **measure**: amendment money per inhabitant instead of `bench_fed` in
   H2.
3. **spec**: H3 with federations treated as one party.
4. **measure**: the extensive margin and Pix-only measures for the first
   stage.

No sample forks (Gabriel's brief).

## What would change the plan

- s1-s4 fail: the builds met the real files once (PR #436), but the
  acquire has never run on a runner. A failing data step gets one repair
  task only if a task step before it lists a file the repair may change;
  none does, so it blocks and asks Gabriel.
- The H1 power stand-in: s6 computes the MDE with the predetermined
  `party_held_mayor_lag` in place of `party_wins_next`, so the gate reads
  no outcome. If the two binary outcomes have very different means, the
  true MDE differs.
- s10 reuses campaign 0011's exploration half and window. Its results
  are a further look at the same data, not new evidence.
- The 2024 federations count their parties as one, so "the party wins
  again" in 2020→2024 is slightly easier for a party in a federation
  than in earlier cycles. The report should say how many 2020 rows have
  an `F` party at e+4.
- The figures task (s11) makes no estimate of its own. If the referee
  marks R4 "Not applicable", the task blocks. Its draft says every
  interval it draws is read from s8's and s10's clustered records.

## Provenance

Stated by Gabriel (brief, 2026-11-20). His brief says: "Treat this brief
as my answers; ask only under rules (b) or (c)." From it:

- the idea file, its citations and the statement that the question came
  after campaign 0011's exploration-half results and the public reelection
  trend;
- exploration half only; windows by decision 0008; clustering by
  municipality; randomisation inference by race re-flips, 2,000 draws;
- H1 and H2 primary at alpha 0.025 each, H3-H6 secondary, as worded in
  the drafts;
- the steps (three builds, the gate and its contents, the main run at the
  gate's window read from the record, the mechanisms run at 0011's 7.5%
  window with ln(1 + reais per inhabitant), the seven figures, matplotlib
  only, each labelled "exploration half, not a finding");
- every kill rule above, so all are confirmed; `on_kill: stop`;
  `self_repair: true`; the `oversize_reason`, in his words;
- the forks envelope (3 forks, 3 per point, types transform, spec,
  measure and question, 1 question fork, 1 new dataset, 4 steps per fork,
  on killed and survived), its budget, no sample forks, and the four
  non-binding variants;
- the budget and `end_by`; opening the PR as `active`.

Decided by Claude Code, not asked (Gabriel approves them with the card):

- **The acquire as s1.** The brief has no acquire step, but the
  `amendments_panel` build needs `tse_general_parties` (PR #436). So the
  brief's s1-s11 are s2-s12 here, and its fork point s5 is s6. It fits
  the brief's `max_pipeline_runs` 4 exactly; the tick does not retry a
  failed run, so no spare is needed.
- **Fork points `[s6]` only.** The brief names s5, s7 and s9, which are
  s6, s8 and s10 here. s8 and s10 have only the "finite" rule, and decision
  0015 (F4) refuses a fork point whose only rule is "finite", so the
  validator rejects them. No kill rule was added to make them eligible:
  that would change the brief's rules.
- **`after`.** s2 and s4 have no `after` and s3 waits for s1, so the
  builds run in parallel. s5 has none (it needs no data to be written). s9
  waits for s6, not s8. s11 waits for s8 and s10.
- **Gate details.**
  - The balance covariates are the four that differ between a race's two
    finalists: `fin_female`, `fin_age`, `fin_higher_ed` and
    `party_held_mayor_lag`. `ln_pop` and `n_mayor_cands` are the same for
    both rows of a race, so they cannot be unbalanced; they are reported,
    not tested.
  - The window is chosen on 2004-2020 pooled; balance by election is
    reported, not used.
  - The grid is 0009's (0.5% to 10%), and the seed is 20261120.
- **H1 power stand-in.** The MDE uses `party_held_mayor_lag` as Y, so the
  gate reads no outcome at e+4. MDE = (z 0.9875 + z 0.80) × the SD of the
  H1 difference over the re-flips = 3.083 × SD, two-sided at 0.025, as in
  campaign 0011.
- **The model.**
  - Uniform kernel, local linear with election-specific intercepts and
    slopes on each side, `b` shared within a group of elections.
  - Clustered by `cd_ibge` (CR1); race re-flips swap the winner of a
    race.
  - The primary p-value is the randomisation p, two-sided.
- **H2.** `bench_fed` enters as a count, not transformed. Pre group 2012
  and 2016. The first stage compares 2020 with 2016 only, because
  `amend_after_*` is null for 2012 (the CGU file starts in 2014).
- **Terciles for figure 7.** Cut points from the 1/3 and 2/3 quantiles of
  `bench_fed` over 2016 and 2020 rows within h. A tercile with fewer than
  20 races is written null and left out of `estimates.finite`.
- **H3 difference.** Estimated as the jump in `d_share` minus the party's
  change, on units with `ran_t1`, so its SE is that of one fit.
- **H5.** "Nonzero" means the pooled 95% interval of the effect on
  `ran_t1` excludes 0. Lee bounds then trim the side with the higher
  running rate.
- **H6.** One set of 46 monthly jumps, labelled twice: months from the
  inauguration (January m+1) and to the general election (October t1).
  Every cycle has the same calendar, so the two axes are shifts of each
  other. Clustered SE only: no randomisation inference across 92 fits.
- **Figure 1's years.** January-October of each year, because
  `amendments_monthly` stops in October of t1. Its reelection line is
  the share of winners who won again, among eligible winners.
- **Reusing campaign 0009's novelty check** for the amendments side, with
  the incumbency lines added here.

Probe: not recommended. Every input is in the bucket or is a 90 MB TSE
download from a host runners have used, and the three builds passed a
real-file dry run (PR #436, 2026-11-20; notes there).

Closest paper: not asked. The brief asks for `active` and for questions
only on merges, loosened checks or large data fixes.

Builds dry-run (PR #436, 2026-11-20): `mayor_incumbency_panel`,
`amendments_panel` v3 and `amendments_monthly` all passed and their
manifests validated. Three data problems were found and fixed before that
PR: 2024 has no CPF, 2012 CPFs are missing leading zeros, and Podemos took
number 20 in 2023.

Not looked at: no outcome at e+4, payment amount, vote number or other
outcome of this campaign. Only counts and coverage shares from PR #436's
dry run, and the window field and covariate balance of record
44484340952.
