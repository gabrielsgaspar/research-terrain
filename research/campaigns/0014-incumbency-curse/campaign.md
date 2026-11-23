---
id: "0014"
title: "Did the incumbency curse of Brazilian mayors' parties lift in 2020? A regression discontinuity fixed in advance (decision 0017)"
status: done
idea: "0012"
owner: gabrielsgaspar
created: 2026-11-22
end_by: 2026-12-10
budget:
  max_tasks: 2
  max_explore_runs: 2
  max_pipeline_runs: 0
  max_model_jobs: 26
referee_not_applicable_ok: [R5]
self_repair: true
forks:
  max_forks: 2
  per_point: 2
  max_new_datasets: 0
  max_steps_per_fork: 3
  types: [spec, measure]
  max_question_forks: 0
  on: [killed, survived]
  fork_points: [s2]
  budget:
    max_tasks: 2
    max_explore_runs: 2
    max_pipeline_runs: 0
    max_model_jobs: 16
datasets: []
steps:
  # The gate: counts, validity by the estimator itself, the lagged placebo and power; no outcome at e+4
  - id: s1
    kind: task
    type: explore
    draft: drafts/s1.md
    allowed_paths:
      - explore/0012_incumbency_gate.py
      - tests/test_explore_incumbency_curse_gate.py
    after: []
  - id: s2
    kind: explore_run
    script: 0012_incumbency_gate
    after: [s1]
    kill_rules:
      - id: k1
        says: "The omnibus randomisation p of the design's own model on the five predetermined covariates (2008-2020 pooled) is below 0.05"
        field: balance.omnibus_p
        op: "<"
        value: 0.05
        confirmed: true
      - id: k2
        says: "The jump in party_held_mayor_lag is larger than 0.05 in absolute value and its randomisation p is below 0.05"
        field: placebo.fail
        op: "=="
        value: 1
        confirmed: true
      - id: k3
        says: "The design cannot detect a swing of 0.20, from Klasnja and Titiunik's -0.15 to +0.05 (H1 MDE, 80% power, alpha 0.05, above 0.20)"
        field: power.mde_h1
        op: ">"
        value: 0.20
        confirmed: true
      - id: k4
        says: "Fewer than 300 exploration-half races inside h = 0.135 in some election of 2008, 2012, 2016 and 2020"
        field: counts.min_cycle_races_h
        op: "<"
        value: 300
        confirmed: true
      - id: k5
        says: "Some gate estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
  # The main run: H1, S1-S5, the robustness list and five figures, with the gate's design
  - id: s3
    kind: task
    type: explore
    draft: drafts/s3.md
    allowed_paths:
      - explore/0012_incumbency_main.py
      - tests/test_explore_incumbency_curse_main.py
    after: [s2]
  - id: s4
    kind: explore_run
    script: 0012_incumbency_main
    after: [s3]
    kill_rules:
      - id: k1
        says: "Some main-run estimate, standard error or p-value is not a finite number"
        field: estimates.finite
        op: "!="
        value: true
        confirmed: true
    on_kill: stop
---

# 0014: Did the incumbency curse of Brazilian mayors' parties lift in 2020?

## Question

Klašnja and Titiunik (2017) found that a party that narrowly wins a
Brazilian mayoralty is less likely to win it again four years later
(-0.15, elections 2000-2012). Since 2020, much more federal money reaches
town halls directly (individual amendments, and "emendas Pix" among
them), and the re-election rate of mayors who ran rose from 49% (2016) to
64% (2020) to 82% (2024) (CNM and TSE, as stated in Gabriel's brief). Did
the party incumbency effect for the 2020 election (outcome 2024) rise
against 2008-2016? Idea 0012 (`research/ideas/0012-incumbency-curse.md`),
with a design fixed before any outcome is read, under decision 0017
(`research/decisions/0017-rd-validity.md`). Exploration half only
(decision 0011).

**Formed after campaign 0012's gate.** Idea 0011 died at that gate
(`research/explore-runs/0011/44768996266.md`) before any outcome at e+4
was read. This idea reuses idea 0011's data (`mayor_incumbency_panel`, as
campaign 0012 built it) and its first question. What changed: the
bandwidth and kernel come from the literature (triangular, h = 0.135),
validity is tested with the estimator itself, and power is judged against
a published effect. The report must count any result as a further
analysis of the same exploration half.

## Already known

Repository scan (`novelty_scan.py`, 2026-11-22: incumbency, Klasnja,
Titiunik, mayor, `party_wins_next`, triangular, bandwidth) and two web
searches of the same day. The amendments side was checked for campaigns
0009-0013 and is not checked again.

| Part of the idea | Verdict | Evidence |
| --- | --- | --- |
| Party incumbency effect of Brazilian mayors, close races, 2000-2012 | explored (negative, -0.15) | (web, unverified) Klašnja and Titiunik, *APSR* 111(1) 2017, 129-148 |
| Sources of the mayoral incumbency (dis)advantage | explored, 2000s-2010s | `avelinofilhoSourcesIncumbencyDisAdvantage2022` |
| Negative mayoral incumbency effect, 2000 and 2004 | explored | (web, unverified) Moreira, "Are incumbents advantaged?", working paper |
| The same question, 2020 against 2008-2016, on this exploration half | tried, stopped at the gate before any outcome | idea 0011, `research/explore-runs/0011/44768996266.md` (expected: this idea re-asks it) |
| Record re-election of mayors in 2024 | descriptive | (web, unverified) CNN Brasil and Congresso em Foco on the CNM study (82% of 3,006 who ran in 2024; 64% in 2020; 49% in 2016) |
| The effect through 2024 by election, the personal effect, the bench gradient and town money at a pre-stated bandwidth | new | no earlier run reached an outcome |

What this campaign adds: the party and personal incumbency effects for
every election through 2020 (outcome 2024), at a bandwidth fixed from the
literature, with the federal bench and the town's amendment money as weak
links to the mechanism.

## Read before this runs

- **Klašnja and Titiunik (2017)**, "The Incumbency Curse: Weak Parties,
  Term Limits, and Unfulfilled Accountability", *APSR* 111(1), 129-148,
  https://doi.org/10.1017/S0003055416000575 (closest; web, unverified:
  the -0.15, its interval and the 13.55-point bandwidth are from
  Gabriel's brief; the author's PDF link returned 404 on 2026-11-22).
  Gabriel: not asked (the brief allows questions only on merges, loosened
  checks and large data fixes; the campaign has four steps).
- **Avelino Filho, Biderman and Desposato (2022)**
  (`avelinofilhoSourcesIncumbencyDisAdvantage2022`). Gabriel: not asked.

## Steps and why

- **s1** (explore task): the gate script `explore/0012_incumbency_gate.py`.
  It reads no column measured at e+4 and no amendment money (the
  `READ_COLUMNS` of the 0011 gate). It holds the weighted model and the
  re-flips that s3 reuses.
- **s2** (gate run): counts inside h, validity by the design's own model
  (decision 0017), the lagged placebo, the H1 minimum detectable
  difference, and decision 0008's table as information. Every field is
  also reported for the S2 sample (eligible finalists). Any rule met
  stops the campaign. The fork point.
- **s3** (explore task): the main script `explore/0012_incumbency_main.py`:
  H1, S1 to S5, the robustness list and five figures, with the gate's
  design. It waits for s2, so no code is written for a design the gate
  stops.
- **s4** (main run): the only step that reads outcomes at e+4.

## Kill rules and why

All stated by Gabriel (brief, 2026-11-22), so all are confirmed.

s2 (`on_kill: stop`):

- **k1** `balance.omnibus_p < 0.05` (decision 0017, point 3): the design's
  own model with `fin_female`, `fin_age`, `fin_higher_ed`,
  `finalist_eligible` and (2012-2020) `bench_fed` > 0 as outcomes, all
  rows, 2008-2020 pooled. A p-value rule: it stops a valid design 1 time
  in 20.
- **k2** `placebo.fail == 1`: the jump in `party_held_mayor_lag` is larger
  than 0.05 in absolute value **and** its randomisation p is below 0.05
  (decision 0017, point 3, with the size 0.05 stated here). A valid design
  meets it less than 1 time in 20, because the size condition must also
  hold.
- **k3** `power.mde_h1 > 0.20` (decision 0017, point 4): the design cannot
  detect a swing of 0.20, from Klašnja and Titiunik's -0.15 to +0.05.
  MDE = 2.80 × the SD of the re-flip draws of the H1 difference with
  `party_held_mayor_lag` as a stand-in, scaled by sqrt(0.25 / the
  stand-in's variance), so it holds for any 0/1 outcome (0.25 is the
  largest variance a 0/1 outcome can have).
- **k4** `counts.min_cycle_races_h < 300`: races inside h, the smallest of
  2008, 2012, 2016 and 2020.
- **k5** `estimates.finite != true`.

s4 (`on_kill: stop`): `estimates.finite != true`.

Feasibility, worked out by Gabriel from campaign 0012's gate record
outside the repository and recomputed by the gate: about 6,000
exploration-half races inside 10% over the five elections; expected
`power.mde_h1` about 0.17.

## Budget and why

Stated by Gabriel (brief, 2026-11-22):

- `max_tasks` 2: exactly the two task steps.
- `max_explore_runs` 2: exactly the two run steps.
- `max_pipeline_runs` 0: no new data and no build.
- `max_model_jobs` 26: two tasks at about 5 jobs each leave about 16 for
  fix rounds.
- `end_by` 2026-12-10: 18 days.

The forks' own budget is also his: `max_tasks` 2, `max_explore_runs` 2,
`max_pipeline_runs` 0, `max_model_jobs` 16.

When a budget runs out, nothing new starts and the tick files the
close-out.

## New data

None. Input: `mayor_incumbency_panel` as campaign 0012 built it (run
44766227487, `data/derived/mayor_incumbency_panel/ca9d009aa3ce9e02/`,
`data/manifests/build/mayor_incumbency_panel.json`).

## Variants in scope for forks (guidance for the ideation job)

Not binding; the envelope and decision 0015 decide what may run. From
Gabriel's brief:

1. **spec**: the personal effect (S2) as the primary.
2. **spec**: a uniform kernel at 10%.

No sample, transform or question forks; no new datasets.

## What would change the plan

- **A change over time is not by itself the effect of Pix.** The 2020
  election was held in the pandemic; campaign finance changed (company
  donations banned from 2016, the public campaign fund from 2018);
  coalitions in council elections ended in 2020. S4 and S5 are the link
  to the money, and they are weak: the bench is predetermined but not
  randomised, and the money is known only after e.
- **The borrowed bandwidth.** h = 0.135 is Klašnja and Titiunik's,
  estimated on 2000-2012 and both halves of the country. The robustness
  list (uniform 5%, 7.5%, 10%; triangular 10%, 20%) is all reported.
- **2024 federations** count their parties as one, so "the party wins
  again" in 2020→2024 is slightly easier for a party in a federation. s4
  reports how many 2020 rows inside h have a federation at e+4.
- **Same exploration half.** Campaign 0012's gate already looked at this
  half's balance and counts (never an outcome at e+4). Any result is a
  further analysis of the same data.

## Provenance

Stated by Gabriel (brief, 2026-11-22). His brief says: "Use this brief as
my answers in the campaign-design skill. Decide anything it leaves open
yourself and list it under 'Decided by Claude Code' in the PR. Every
threshold and kill rule below is set and confirmed by me: do not ask me to
confirm them." From it:

- campaign 0014, slug `incumbency-curse`, new idea 0012 and new decision
  0017 (its six points, its title, and the pointer lines in the
  `campaign-design` skill and `references/kill-rules.md`), all in one PR;
  no new data and no build;
- the context: idea 0011's gate, the two flaws, Klašnja and Titiunik's
  estimate and design, the re-election rates; that the idea file says
  when and why it was formed;
- the design: the 0011 gate's model with a triangular kernel at h =
  0.135, clustered by municipality, 2,000 race re-flips, the pyfixest
  check in tests; H1 at alpha 0.05; S1 to S5; the robustness list; the
  other explanations;
- the four steps and their contents (gate fields, the S2-sample fields,
  the figures), `self_repair: true`;
- every kill rule above and each step's `on_kill`, so all are confirmed;
- the forks envelope (2 forks, 2 per point, fork point s2, on killed and
  survived, types spec and measure, 0 new datasets, 3 steps per fork),
  its budget and the two non-binding variants;
- the budget and `end_by`; the feasibility figures; opening the PR as
  `active`.

Decided by Claude Code, not asked (Gabriel approves them with the card):

- **Rows inside h.** The triangular kernel uses rows with |margin| < h (a
  row at exactly h has weight 0, and would break the pyfixest check); the
  uniform kernel uses |margin| ≤ w, as the 0011 gate did.
- **The omnibus p covers the five predetermined covariates only**; the
  lagged outcome is gated by k2 alone, as decision 0017 point 3 says. One
  `win` coefficient over 2008-2020 (2012-2020 for `bench_fed` > 0).
- **The placebo pools 2004-2020**, as the 0011 gate's did, and is also
  reported by election.
- **The stand-in's variance** is p(1 - p) of `party_held_mayor_lag` over
  the rows of the H1 fit (unweighted).
- **Decision 0008's table** is computed by loading
  `explore/0011_incumbency_gate.py` and calling its `choose_window` with
  this gate's draws (four covariates, five elections pooled, as before).
- **The S2 sample's balance** drops `finalist_eligible` (true on every
  row there). `estimates.finite` covers the S2-sample numbers too.
- **Seed** 20261122, one sign matrix over every race of the panel.
- **H1's test** is the two-sided randomisation p below 0.05 with a
  positive difference; all intervals are 95% (b ± 1.96 × se). The
  robustness fits report clustered errors only, no randomisation p.
- **"Adding fin_female, fin_age, fin_higher_ed and state-by-election
  fixed effects"** is read as one robustness fit with all four; rows with
  a null covariate leave that fit and are counted.
- **S3** reports, like S1 and S2, each election and the H1 contrast;
  `finalist_runs_next` on eligible rows only.
- **S4** gives each election × connected cell its own intercept and
  slopes, with four `win` coefficients (2012-2016 and 2020, connected and
  not).
- **S5's selection.** "Differ in `bench_fed`" means two non-null, unequal
  values; the row kept is the one with the larger `bench_fed`. Rows with a
  null or zero `population_e` or null money leave the fit and are
  counted.
- **Figures**: five PNGs (bins h/10 wide in figure 1).
- **Test file names** `tests/test_explore_incumbency_curse_gate.py` and
  `..._main.py` (`tests/test_explore_incumbency_gate.py` is idea 0011's).
- **`max_question_forks` 0**, because question is not among the brief's
  fork types.

Probe: not recommended separately. The campaign is already probe-sized
(four steps, no new data), and its gate is the probe.

Closest paper: not asked, for the reason under "Read before this runs".

Builds dry-run: none needed; no build runs.

Not looked at: no outcome at e+4, no amendment money and no other outcome
of this campaign. Only counts from the build manifest and campaign 0012's
gate record (balance and counts at the 0011 windows).
