# Task: compare exposure formulas for decision 0004 (explore)

## Goal

Decision 0004 fixes how a 1 km cell's exposure to a close council race is
measured. Before Gabriel decides, compute the candidate formulas on the
exploration half and report, per election year, how many cells each one
reaches, how exposure is spread by population and land tenure, and how much
the variants agree. No outcome data; no effects.

## Idea

`research/ideas/0001-electoral-strongholds.md` ("Exposure" in the design).
This is an explore task (label `explore`): it may change only `explore/` and
`tests/test_explore*`, and it reads no outcome data. Read
`explore/0001_feasibility_census.py`, `data/contracts/grid_cells.md` and
`data/contracts/polling_places.md` first.

## Prerequisites

`grid_cells` built and its manifest merged (task 19).

## Definitions

- **Close pairs, places and votes:** exactly as the feasibility census. Load
  `explore/0001_feasibility_census.py` with `importlib` and reuse
  `main_election`, `candidacy_votes`, `within_list_pairs`, `valid_votes`,
  `margins` and `place_candidate_votes`; do not copy or change them. Close
  means margin at most 0.5%, inverted pairs excluded. For each pair, `w` is
  the elected candidate and `l` the other.
- **Place vote share:** `s_cp` = candidate `c`'s votes at place `p` divided
  by `V_p`, the place's candidate plus legend votes (as in `strongholds`);
  places with `V_p` = 0 are dropped. **Place votes:** `v_cp`, the votes.
- **Locations:** places from `polling_places` of the same year with `lat` and
  `long`, joined on (`cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`) with
  zone and place cast to Int64, projected to Albers km with
  `terrain.grid.to_albers_km`. Cells from `grid_cells`: centre (`x_km` +
  0.5, `y_km` + 0.5). A cell is matched only to places of its own
  municipality (`cd_ibge`). Distances `d_ip` in km; find pairs within 10 km
  with a shapely `STRtree` (`query(..., predicate="dwithin", distance=10)`).
- **Kernels** `K(d)`: `exp2` = exp(-d / 2) for d ≤ 10 km, else 0; `ring2` =
  1 if d ≤ 2; `ring5` = 1 if d ≤ 5.
- **Measures:** `share` = Σ_p K(d_ip) s_cp / Σ_p K(d_ip) (a kernel-weighted
  mean of the candidate's share; undefined when Σ_p K = 0); `votes` = Σ_p
  K(d_ip) v_cp.
- **Pair contrast:** `D_i` = Σ over the close pairs of the cell's municipality
  of (E_iw − E_il). Swapping a pair's winner and loser flips the sign of its
  term, so the expectation of `D_i` over swaps is 0, and the recentred
  exposure to the elected (Borusyak and Hull 2023) equals `D_i` / 2. Say
  this in the summary.
- A cell is **reached** under a kernel when Σ_p K(d_ip) > 0 for some place of
  its municipality, and **exposed** when, in addition, its municipality has a
  close pair and |D_i| > 0.

## What to report

Per year (2008-2024) and for each kernel × measure (six variants):

1. Cells in exploration-half municipalities; municipalities with at least one
   close pair; close pairs per such municipality (mean, max).
2. Cells reached; cells exposed; and the share of exposed cells with
   `pop_2022` = 0.
3. Quantiles of `D_i` over exposed cells (1%, 10%, 50%, 90%, 99%), and of
   |D_i|.
4. Mean |D_i| over exposed cells by group: `pop_2022` = 0 or > 0; and
   `share_indigenous_<y>`, `share_settlement_<y>`, `share_undesignated_<y>`
   above 0 (each group with its cell count).
5. Agreement: Pearson correlation of `D_i` between `exp2` and each ring
   (same measure), and between `share` and `votes` (same kernel), over cells
   exposed in both.

`results.json` holds every number; `summary.md` holds one table per year
(variants as rows: reached, exposed, empty share, median |D|) and one line on
the recentring identity.

## In scope

- `explore/0001_exposure_options.py`: calls `exploration_municipalities` and
  `restrict` on every table it reads, like the census.
- `tests/test_explore_exposure.py`: synthetic tables (two municipalities, a
  few places and cells).

## Done when

1. On a synthetic municipality with one pair and two places, `share` under
   `exp2` equals the hand-computed weighted mean, and `votes` the weighted
   sum, for a cell 1 km from one place and 3 km from the other.
2. A cell 12 km from every place is not reached under any kernel; a cell
   3 km away is reached under `exp2` and `ring5` but not `ring2`.
3. Swapping the winner and loser of every pair negates every `D_i`.
4. A cell is never matched to a place of another municipality.
5. Every table the script reads is restricted to the exploration half (the
   existing explore test passes).
6. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
