# Task: power of close mayoral races at the municipality level (explore)

## Goal

Idea 0003 (`research/ideas/0003-mayoral-close-races.md`) compares the turf
of narrowly elected and narrowly defeated mayors. There are few close
mayoral races, so before anyone designs it, this task asks a cheap question:
**with one observation per close race, what effect could the races detect?**
It reports, for windows 0.5%, 1% and 2%, the minimum detectable effect (MDE)
and the power at decision 0007's effect size (8% of baseline clearing,
`research/decisions/0007-effect-size.md`). The script computes exactly what
this issue lists and nothing beyond it (referee R7). No estimate of any
effect is computed: there is no observed statistic, only the spread of the
re-flip distribution.

**Outcome data in scope (for referee R2): pre-election years only.** The
script reads `cell_outcomes` for the years E-4 to E-1 of each election E, and
no other year. No year E or later is read. The years are fixed in code
(`pre_years`), not by an argument. Exploration half only.

## Idea

`research/ideas/0003-mayoral-close-races.md` (kill criterion 1, drafted);
decisions 0001 (split), 0006 (outcome) and 0007 (effect size); the power run
42265146230 (`research/explore-runs/0001/42265146230.md`) for the power
formula. This is an explore task (label `explore`): it may change only
`explore/` and `tests/test_explore*`.

Read first: `src/terrain/strongholds.py` (`main_election`),
`src/terrain/explore.py`, `explore/0001_power.py` (`ri_p`, `_load`, the
power formula) and `explore/0001_feasibility_census.py` (`_paths`), and the
contracts `tse_results` and `cell_outcomes` in `data/contracts/`. Reuse
`main_election` and `_paths` (the latter loaded with importlib, as
`explore/0001_power.py` loads its dependencies). Do not change any existing
explore script.

## Definitions

- **Elections** E = 2008, 2012, 2016, 2020 (as the power run; 2024 has no
  four post-election years and is not needed for power).
- **Tables read**, each through `restrict` on `cd_ibge` right after reading:
  `tse_results` `candidate_votes_<E>` and `turnout_<E>`, and `cell_outcomes`
  of `pre_years(E)`. Read only these `candidate_votes` columns:
  `ano_eleicao`, `cd_eleicao`, `cd_tipo_eleicao`, `nr_turno`, `sg_ue`,
  `cd_ibge`, `cd_cargo`, `sq_candidato`, `nr_zona`, `qt_votos_nominais`,
  `qt_votos_nominais_validos`, `nm_tipo_destinacao_votos`,
  `ds_sit_tot_turno`. For `turnout`: `cd_eleicao`, `nr_turno`, `sg_ue`,
  `cd_ibge`, `cd_cargo`, `qt_total_votos_validos`. For `cell_outcomes`:
  `nome_1KM`, `cd_ibge`, `has_data`, `code_2`, `code_4`.
- **Main election.** `main = strongholds.main_election(candidate_votes)`
  (council round 1, most rows): 30, 47, 220 and 426 for 2008-2020 (profiled
  on the TSE files, 2026-11-07). Supplementary elections have other ids and
  are not used.
- **Run-off.** The run-off of the main election has its own id, `main + 1`
  (31, 48, 221, 427, profiled). A municipality's **deciding round** is round
  2 (`cd_eleicao` = `main + 1`, `nr_turno` 2) when it has mayoral rows
  (`cd_cargo` 11) there, else round 1 (`cd_eleicao` = `main`, `nr_turno` 1).
  Mayoral round-2 rows under any other id are counted per year and not used
  (Macapá's postponed 2020 election, ids 445 and 446, is one such case).
- **Votes per candidacy** in the deciding round, summed over zones: for
  2016 and 2020, `qt_votos_nominais_validos` over rows whose
  `nm_tipo_destinacao_votos` is `Válido` (exact text; rows with any other
  value, such as annulled ones, are left out and counted per year); for
  2008 and 2012, which have no destination column, `qt_votos_nominais`.
  (This differs from the council code, which uses `qt_votos_nominais` in
  every year; for mayors the annulled votes can change who is first.)
- **Valid votes**: `turnout.qt_total_votos_validos`, `cd_cargo` 11, the
  deciding round's `cd_eleicao` and `nr_turno`, summed over zones per
  `sg_ue`.
- **Race.** The first and second candidacies by votes (ties broken by
  `sq_candidato`, ties counted). Margin = (first − second) / valid votes. A
  municipality with one candidacy with votes has no margin and is counted
  per year. The number of races whose first candidacy's `ds_sit_tot_turno`
  is not `ELEITO` is reported per year; those races are kept.
- **Windows**: |margin| ≤ 0.5%, 1%, 2% (+1e-12). Race id = row index of the
  year's 2% races (sorted by `sg_ue`), offset across years in election
  order. A narrower window is the subset of those races, with the same ids.
- **Outcome** (municipality i, election E): over the exploration-half cells
  of i with `has_data` true in every year of `pre_years(E)` = E-4..E-1,
  Y_i = Σ over those years and cells of `code_4`, divided by Σ over the same
  cells of (`code_2` + `code_4`) in year E-4. Y_i is null when no cell
  qualifies or the denominator is 0; those races are counted per year and
  left out of every window.
- **Statistic.** ỹ_i = Y_i minus the mean of Y over the window's races of
  the same election. For a sign vector s over the window's races (s_i = +1:
  a fixed side of the race won), Δ(s) = mean of ỹ over s_i = +1 minus mean
  over s_i = −1. This is the winner-minus-loser contrast of any race-level
  attribute that is as good as random within close races and splits the
  races in half, the best case for power.
- **Re-flips.** 2,000 draws, seed 20261106, each
  `rng.integers(0, 2, size=n_2pct) * 2 - 1` over all 2% races; a window uses
  the entries of its races. A draw where one side is empty gives no Δ and is
  counted.
- **Per window**: n races (per election and pooled), how many decided in a
  run-off, ȳ (mean Y, not demeaned), SD of Y, `sd_ri` (SD of Δ over the
  draws), its 2.5% and 97.5% quantiles, MDE = 2.8 × `sd_ri` and as % of ȳ,
  and **power at 8%**: τ = 0.08 × ȳ, power = Φ(τ / `sd_ri` − 1.96)
  (two-sided 5%, as decision 0007).

## What to report

`summary.md`:
1. First line: the power at 8% for 0.5%, 1% and 2%, and the MDE as % of
   baseline for each.
2. Races per window, per election and pooled; how many decided in a
   run-off; races left out (no margin, null outcome) per year; mayoral
   round-2 rows under other ids; annulled rows left out; first candidacies
   not marked `ELEITO`.
3. The power table: rows = windows, columns = races, ȳ, SD of Y, `sd_ri`,
   q2.5 and q97.5 of Δ, MDE, MDE as % of ȳ, power at 8%.
4. Caveats: exploration half; pre-election clearing stands in for the
   outcome's spread; one observation per race ignores turf geography; Δ is
   the best case (a 50/50 attribute); the municipal outcome stops at
   exploration-half cells.

`results.json`: every number above.

## In scope

`explore/0003_mayor_power.py` (calls `exploration_municipalities` and
`restrict` on every table it reads) and `tests/test_explore_mayor_power.py`.

Expected files (two): `explore/0003_mayor_power.py`,
`tests/test_explore_mayor_power.py`.

## Out of scope

Any outcome year E or later; any observed winner-minus-loser estimate;
stronghold or turf geography; 2024; council races; changes to other explore
scripts; the idea file and lessons entry (written from the record);
`sealed/`. No CPF or voter ID number is read (the columns above exclude
them).

## Done when

1. No outcome year after E-1 is read: `pre_years(2008)` is exactly
   2004-2007, the years read for each election are exactly `pre_years(E)`,
   and E is never read.
2. Deciding round, on a synthetic table: a municipality with mayoral rows
   under `main + 1`, round 2, gets the round-2 margin and is counted as
   decided in a run-off; one without gets the round-1 margin; round-2 rows
   under another id are ignored and counted; a supplementary election's rows
   are ignored.
3. Votes: for 2016 and 2020 only `Válido` rows count, with
   `qt_votos_nominais_validos` (a synthetic annulled row that would make its
   candidate first does not, and is counted); for 2008 and 2012
   `qt_votos_nominais` is used.
4. Races: first minus second over valid votes; a one-candidacy municipality
   has no margin and is counted; a tie is broken by `sq_candidato` and
   counted; a first candidacy not marked `ELEITO` is counted and kept.
5. Windows: a race keeps its id in every window, and a narrower window's
   draw-r Δ equals the wider window's Δ computed on the same races with the
   same signs.
6. Outcome on synthetic cells: a cell without data in one pre year is left
   out; a zero denominator gives null and is counted; Y equals the formula.
7. Power: for given `sd_ri` and ȳ, power equals Φ(0.08 × ȳ / `sd_ri` −
   1.96) and MDE equals 2.8 × `sd_ri`; on synthetic races with ỹ = ±1 in
   equal numbers, `sd_ri` is close to 2 / √n.
8. No observed Δ is computed or written: `results.json` on a synthetic run
   has no key for one.
9. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
