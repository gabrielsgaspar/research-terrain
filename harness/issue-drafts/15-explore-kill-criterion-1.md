# Task: test kill criterion 1 for idea 0001 (explore)

## Goal

On the exploration half, count the close-pair candidates whose stronghold is
inside or near an indigenous land, and inside or near a settlement, and say
whether kill criterion 1 is met.

## Idea

`research/ideas/0001-electoral-strongholds.md`, kill criterion 1: "fewer than
200 close-pair candidates (margin at most 0.5%, 2008-2024 pooled, exploration
half) have a stronghold in or within 5 km of an indigenous land, or fewer
than 200 in or within 5 km of a settlement". This is an explore task (label
`explore`): it may change only `explore/` and `tests/test_explore*`, and it
reads no outcome data.

## Prerequisites

`polling_place_tenure` built and its manifest merged (task 14).

## Definitions

- **Close pairs and strongholds:** exactly as the feasibility census,
  `explore/0001_feasibility_census.py`. Load that script's functions with
  `importlib` and reuse them; do not copy or change them. Margin at most 0.5%,
  inverted pairs excluded; both candidates of a pair count.
- **Near:** the stronghold polling place's `dist_indigenous_km` and
  `dist_settlement_km` from `polling_place_tenure` for the same year, joined
  on (`cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`) with both
  `nr_zona` and `nr_local_votacao` cast to Int64.
- **Bands:** 0 km (inside), 2 km and 5 km. The criterion uses 5 km.
- **Verdict:** met (the idea fails) if either 5 km count, pooled over 2008,
  2012, 2016, 2020 and 2024, is below 200; otherwise not met. State it in
  one line; the person records the decision.

## What to expect

A preliminary run on the whole Legal Amazon (outside this pipeline, with
approximate distances) found 1,334 close-pair strongholds within 5 km of an
indigenous land (443 inside) and 5,244 within 5 km of a settlement (310
inside), of 18,060 with coordinates. The exploration half should give about
half: roughly 667 and 2,622. A result far from that is a reason to check the
code, not a finding.

## In scope

- `explore/0001_kill_criterion_1.py`: restrict every table to the exploration
  half with `exploration_municipalities` and `restrict` before computing;
  process one year at a time; write `summary.md` and `results.json` with
  `write_results`.
- `results.json`: per year and pooled, the number of close-pair candidates,
  how many have a stronghold with coordinates, and how many are within 0, 2
  and 5 km of an indigenous land and of a settlement; the verdict.
- `summary.md`: one table with those counts, the verdict line, and the
  caveats: 2025 settlement boundaries dated back by creation year; the 5 km
  settlement band includes many strongholds, so 0 and 2 km are reported too;
  no outcome data was read.
- `tests/test_explore_kc1.py`: the counting and the verdict on frames built
  in the test.

Expected files (two): `explore/0001_kill_criterion_1.py`,
`tests/test_explore_kc1.py`.

## Out of scope

- Outcome data; effects; any analysis beyond these counts (referee R7).
- Changing `explore/0001_feasibility_census.py`, `src/`, `pipeline/`, `data/`.

## Done when

1. A test with two close-pair candidates, one with a stronghold 1 km from an
   indigenous land and one 7 km away, counts 1 within 2 km and 1 within 5 km.
2. A test shows the verdict is "met" when a pooled 5 km count is 199 and "not
   met" at 200, for each layer.
3. A test shows a candidate whose stronghold has no coordinates is counted as
   without coordinates, not as far away.
4. The census functions are loaded from `explore/0001_feasibility_census.py`,
   not copied.
5. `tests/test_explore.py` passes (the script restricts to the exploration
   half).
6. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
