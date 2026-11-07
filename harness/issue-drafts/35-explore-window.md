# Task: choosing the close-race window by covariate balance (explore)

## Goal

The close-race window (|margin| at most 0.5% of the municipality's valid
council votes) was a judgement. The design is a local randomisation design
(Cattaneo, Frandsen and Titiunik 2015), whose standard window choice uses
only pre-election characteristics: the widest window in which narrow winners
and narrow losers do not differ. This task tests balance in seven windows by
a rule fixed below, and reports each window's power at decision 0007's
effect size. Its result is the basis of a proposed decision 0008 (written by
a person from the record), which fixes the window of the pre-analysis plan.
Task B's 0.5% result (run 42298466207) stands as pre-specified. The script
computes exactly what this issue lists and nothing beyond it (referee R7).

**Outcome data in scope (for referee R2): pre-election years only.** The
script reads `cell_outcomes` for the years E-4 to E-1 of each election E,
and no other year: for the pre-election clearing covariate (all five
elections) and for power, computed as in the power run 42265146230
(2008-2020). No year E or later is read. The years are fixed in code
(`pre_years`), not by an argument. Exploration half only.

## Idea

`research/ideas/0001-electoral-strongholds.md`; decisions 0004, 0005, 0006
and 0007 (`research/decisions/0007-effect-size.md`); runs 41719271978
(census), 41839642406 (kill criterion 1), 42265146230 (power) and
42298466207 (effects). This is an explore task (label `explore`): it may
change only `explore/` and `tests/test_explore*`.

Read first: `explore/0001_power.py` and `explore/0001_effects.py`. **Reuse
them** (loaded with importlib, as `0001_effects.py` loads `0001_power.py`):
pair terms, side terms, candidate types, components, displacement terms and
checks, `make_part` / `assemble` / `estimates` / `run_ri`, `ri_p`, the
exposure and effect-size helpers, and `kc1.candidate_distances`. Do not copy
them and do not change any existing explore script. Also read
`src/terrain/strongholds.py` and the contracts `tse_candidates`,
`polling_place_types`, `polling_place_tenure`, `grid_cells` and
`cell_outcomes` in `data/contracts/`.

## Definitions

- **Elections** E = 2008, 2012, 2016, 2020, 2024 for balance, pooled; power
  uses 2008-2020, as the power run.
- **Windows** (|margin| as a share of valid council votes): 0.10%, 0.25%,
  0.50%, 0.75%, 1.00%, 1.50%, 2.00%. Pairs and margins exactly as
  `terrain.strongholds` (`main_election`, `candidacy_votes`,
  `within_list_pairs`, `valid_votes`, `margins`), with `close_pairs(paired,
  threshold)` at each window.
- **Pair index.** Pair id = row index of the year's `close_pairs` at 2.00%,
  offset across years in election order as `stack` does. A narrower window
  is the subset of those pairs with |margin| ≤ its threshold (+1e-12), with
  the same ids. One sign vector per draw over all 2.00% pairs (2,000 draws,
  seed 20261106) is shared by every covariate and every window.
- **Covariates**, each a value per close-pair candidate, all fixed before
  election E. Rows of `tse_candidates` match a pair side on (`ano_eleicao`,
  `cd_eleicao`, `sg_ue`, `sq_candidato`).
  1. `female`: `cd_genero` = 4. Null when `cd_genero` is null.
  2. `age`: (`dt_eleicao` − `dt_nascimento`) in days / 365.25. Null when
     `dt_nascimento` is null. (The 2020 election was on 15 November.)
  3. `schooling`: `cd_grau_instrucao` as an integer, 1 (cannot read) to 8
     (degree completed), the TSE's ordered codes.
  4. `incumbent`: the candidate's `nr_titulo_eleitoral_candidato` belongs to
     a candidate **elected** to the council (`cd_cargo` 13) of the same
     `sg_ue` in the main election of E-4. Elected is decided by
     `ds_sit_tot_turno` in {`ELEITO`, `MÉDIA`, `ELEITO POR QP`,
     `ELEITO POR MÉDIA`}, never by `cd_sit_tot_turno`: the candidate file's
     codes change meaning between years (`MÉDIA` is 5 in 2004 and 3 in
     2008, where 5 is `SUPLENTE`), and `strongholds.ELECTED_CODES` is for
     the results file. The main election of E-4 is its council round-1
     `cd_eleicao` with the most candidate rows. Null when the voter ID is
     null. The file's `st_reeleicao` is **not** used (see "Covariates
     checked"); report its count of `S` per year next to this one.
  5. `seat_km`: the stronghold's `seat_km` (`polling_place_types`, year E).
  6. `place_seat`, `place_town`: the stronghold's `place_type` is `seat`,
     respectively `town` (every other type is the omitted group).
  7. `dist_indigenous_km`, `dist_settlement_km`: the stronghold's distances
     in `polling_place_tenure` of year E.
  8. `pop22_5km`: the sum of `grid_cells.pop_2022` over cells whose centre
     (corner + 0.5 km) is within 5 km (+1e-9) of the stronghold (Albers km,
     as `locate_places`).
  9. `clearing_pre`: over the same cells, restricted to those present in the
     exploration-half `cell_outcomes` with `has_data` true in all of E-4 to
     E-1: Σ over those years of `code_4` divided by (`code_2` + `code_4`) of
     year E-4, both summed over the cells. Null when the denominator is 0 or
     no cell qualifies.
  Strongholds are those of `strongholds` (place votes of year E), as in
  kill criterion 1; covariates 5-9 are null for a candidate without one.
- **Difference** for window w and covariate k: the mean over the pairs in w
  with both sides non-null of (winner − loser). Pairs with a null side are
  counted and left out of that covariate only.
- **RI.** For draw r, flip each pair's difference by its sign; m_{r,k}. The
  two-sided p_k = (1 + #{r: |m_{r,k}| ≥ |m_k|}) / (1 + 2,000).
- **Omnibus per window:** the observed minimum p over covariates, compared
  with the re-flip distribution of the minimum: for each draw, p_{r,k} =
  #{s: |m_{s,k}| ≥ |m_{r,k}|} / 2,000 over the same 2,000 draws, and min_k
  p_{r,k}; omnibus p = (1 + #{r: min_k p_{r,k} ≤ min_k p_k}) / (1 + 2,000).
  A covariate with fewer than 20 pairs in a window is reported and left out
  of that window's omnibus.
- **Rule (fixed now):** the chosen window is the widest window whose omnibus
  p is at least 0.15, with every smaller window also at least 0.15. If 0.10%
  already fails, the line says "No window passes; Gabriel decides" and no
  window is chosen.
- **Power, reported, never used to choose.** For each window: the power at
  8% of baseline four-year clearing at the mean exposure (decision 0007) for
  the direct effect (`exp2`), the displacement effect (`g_exp10`) and the
  5 km split difference (a gap of one effect size, one-sided), computed as
  in the power run on pre-election clearing (E-4..E-1, 2008-2020): the
  effect-size helpers give τ = 0.08 × `ybar` / mean |x| over the cells with
  a non-zero regressor (the indigenous component's for the split), and power
  = Φ(τ / `sd_ri` − z) with z = 1.96, and 1.645 for the split. Each window
  has its own pair numbering and 2,000 draws (seed 20261106) for power. Run
  one window at a time and free its arrays before the next.

## What to report

`summary.md`:
1. The rule's line first: the chosen window and its omnibus p, or "No window
   passes; Gabriel decides".
2. Pairs per window, per election and pooled; constituency-type counts at
   5 km per window (pooled, the power run's five types).
3. The balance table: rows = covariates, columns = windows, each cell the
   difference and its p; then the omnibus p row; and per covariate the pairs
   left out for nulls.
4. The power table: rows = windows, columns = direct, displacement, split.
   The 0.50% row is labelled "decision 0007: 0.94, 0.797, 0.45" for
   comparison.
5. Incumbency check: per election, the candidates with `st_reeleicao` = `S`
   and those `incumbent` by the voter-ID rule.
6. Caveats: exploration half; `pop22_5km` is measured in 2022, after the
   2008-2020 elections; the clearing disc stops at confirmation-half
   municipalities; power from pre-election clearing.

`results.json`: every number above.

## Covariates checked (TSE raw files, the nine Legal Amazon states, 2026-11-07)

Council candidates (`cd_cargo` 13) in the main election:

| | 2008 | 2012 | 2016 | 2020 | 2024 |
| --- | --- | --- | --- | --- | --- |
| Candidates | 55,598 | 69,827 | 71,817 | 82,927 | 66,714 |
| `cd_genero` missing | 0 | 334 | 38 | 35 | 1 |
| `dt_nascimento` missing | 0 | 334 | 38 | 35 | 1 |
| `cd_grau_instrucao` missing | 0 | 0 | 0 | 0 | 0 |
| `nr_titulo_eleitoral` missing | 0 | 334 | 38 | 35 | 1 |
| `ST_REELEICAO` = S | 6 | 1,594 | 6,514 | 3,568 (complementary file) | 6,467 (complementary file) |
| Incumbent by voter ID (E-4 elected) | 5,582 | 5,325 | 6,220 | 6,429 | 7,163 |

`st_reeleicao` is not recorded consistently (6 in 2008), and the built
`tse_candidates` has it for 2000-2016 only, so it is not used. Where it
looks complete, 92% (2016) and 90% (2024) of `S` are incumbents by voter ID,
and 97% and 82% of those incumbents are `S`. CPF is
masked in 2024 (`-4`), so the voter ID is the link. Party in the mayor's
coalition is not used: it needs a party-lineage table (PMDB to MDB, PR to
PL, DEM and PSL to UNIÃO, ...) that does not exist. Race is not used.

## In scope

`explore/0001_window.py` (calls `exploration_municipalities` and `restrict`
on every table it reads, including `tse_candidates`, `polling_place_types`,
`polling_place_tenure`, `grid_cells` and `cell_outcomes`) and
`tests/test_explore_window.py`.

Expected files (two): `explore/0001_window.py`,
`tests/test_explore_window.py`.

## Out of scope

Any outcome year E or later; outcome-based bandwidth selectors; covariates
not listed (race, coalition, `st_reeleicao` in the rule); choosing by power;
per-election balance tests; changes to other explore scripts; the idea file,
lessons entry and decision 0008 (written by a person from the record);
`sealed/`.

## Done when

1. On synthetic pairs with balanced covariates the omnibus p is high; when
   winners are made 5 years older in every pair with |margin| above 1%, the
   rule picks 1.00%.
2. The omnibus p uses the re-flip distribution of the minimum p, not the
   smallest raw p: on a synthetic case with ten independent balanced
   covariates the omnibus p differs from the smallest raw p and equals the
   formula above.
3. Every covariate and window uses the same sign vectors and pair indices:
   a pair keeps its id in every window, and a narrower window's draw-r
   statistic equals the wider window's computed on the same pairs.
4. No outcome year after E-1 is read: `pre_years(2008)` is exactly
   2004-2007, the years read for each election are exactly `pre_years(E)`,
   and E is never read.
5. The rule: omnibus p (0.50, 0.40, 0.20, 0.10, 0.30, ...) picks 0.25%
   (a later window above 0.15 does not count); 0.10% below 0.15 gives "No
   window passes; Gabriel decides".
6. `incumbent`: on a synthetic candidate table, a 2008 candidate whose voter
   ID was `MÉDIA` (code 5) in 2004 in the same `sg_ue` is an incumbent; one
   elected in another `sg_ue`, or `SUPLENTE` in 2004, is not; a 2012
   candidate whose 2008 row is `MÉDIA` with code 3 is an incumbent.
7. `clearing_pre` and `pop22_5km` on a synthetic disc: a cell centre at 5 km
   counts, one at 5.01 km does not; cells without data in one pre year are
   left out.
8. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
