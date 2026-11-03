# Task: feasibility census for the stronghold design (explore, idea 0001)

## Goal

On the exploration half, count close within-list council races per election
(2008-2024) and measure how often the candidates in them have their
stronghold outside the municipal seat. This decides whether the stronghold
design has enough variation to go ahead.

## Idea

`research/ideas/0001-electoral-strongholds.md`. This is an explore task: it
uses only the exploration half and no outcome data.

## Definitions (agreed; checked on the real data for the whole Legal Amazon)

- **Election.** Council (`cd_cargo` 13), round 1, the year's main election:
  the `cd_eleicao` with the most `candidate_votes` rows that year (30 in
  2008, 47 in 2012, 220 in 2016, 426 in 2020, 619 in 2024).
- **List.** `sq_coligacao`: a coalition until 2016, a party from 2020, and in
  2024 a federation (its parties share one `sq_coligacao`: 6,555 of 6,556).
- **Elected / not elected.** By `cd_sit_tot_turno`, which changed codes:
  2008 elected = {1, 5}, not elected = {2, 4}; 2012-2024 elected = {2, 3},
  not elected = {4, 5}. Votes are counted votes: `qt_votos_nominais` summed
  over zones per candidacy.
- **Within-list pair.** In each list with at least one elected and one
  non-elected candidate with votes: the elected candidate with the fewest
  votes and the non-elected candidate with the most.
- **Margin.** (votes of that elected candidate - votes of that non-elected
  one) / the municipality's valid council votes (`turnout`
  `qt_total_votos_validos`, council, round 1, main election, summed over
  zones). A negative margin means the non-elected candidate out-polled the
  elected one (from 2021 a councillor needs at least 10% of the quotient):
  count those pairs and exclude them; none occur before 2024, 16 in 2024.
- **Close.** |margin| at most 0.25%, 0.5%, 1% and 2%; 0.5% is the headline.
- **Stronghold.** From `section_votes` (council, round 1, main election,
  `vote_type` candidate or legend, `annulled_in_results` false): for each
  polling place `V_p` = its counted candidate and legend votes; for each
  candidate, location quotient = (votes at the place / `V_p`) / (candidate's
  municipal votes / municipal total). The stronghold is the place with the
  highest quotient among places with `V_p` >= 50; ties go to the place with
  more of the candidate's votes.
- **Outside the seat.** The stronghold's `place_type` (from
  `polling_place_types`) is not `seat`. Also report each candidate's share of
  votes cast at places whose type is not `seat`.
- **Join keys.** `section_votes.nr_zona` is text and
  `polling_place_types.nr_zona` is an integer: cast both `nr_zona` and
  `nr_local_votacao` to Int64 before joining on (`cd_ibge`, `sg_ue`,
  `nr_zona`, `nr_local_votacao`).

## What the whole Legal Amazon gives (sanity check, not a target)

The exploration half is about half of the municipalities, so counts should
be roughly half of these and shares within a few points.

| Year | Pairs | Close at 0.5% | Close at 1% | Close-pair candidates: stronghold outside the seat | Their votes outside the seat |
| --- | --- | --- | --- | --- | --- |
| 2008 | 2,916 | 1,536 | 2,212 | 48% | 26% |
| 2012 | 3,031 | 1,799 | 2,512 | 53% | 28% |
| 2016 | 3,041 | 1,880 | 2,531 | 54% | 28% |
| 2020 | 4,210 | 2,129 | 3,129 | 54% | 28% |
| 2024 | 3,802 | 1,745 | 2,572 | 55% | 28% |

All candidates, for comparison: 42-45% have a stronghold outside the seat,
24-25% of votes outside it. Of close-pair strongholds outside the seat, most
are in other towns (`town`), then `dispersed` and `rural`.

## In scope

- `explore/0001_feasibility_census.py`, following `explore/README.md` and
  `src/terrain/explore.py`: read the paths of `tse_results`, `section_votes`
  and `polling_place_types` from `data/manifests/build/`, download with
  `GCSStore`, call `exploration_municipalities` and `restrict` on every table
  (on `cd_ibge`) before computing anything, process one year at a time, and
  write `summary.md` and `results.json` with `write_results`.
- Put the definitions in small functions (pairs, margins, strongholds,
  outside-seat shares) that take polars frames, so tests can call them.
- `results.json`: per year, the pair counts, inverted pairs, close counts at
  each threshold, and for close-pair candidates (0.5%) and all candidates:
  count, share with a stronghold, share with a stronghold outside the seat,
  stronghold counts by `place_type`, mean share of votes outside the seat.
- `summary.md`: the table above for the exploration half, plus one paragraph
  stating the counts, without interpreting effects.
- `tests/test_explore_census.py`: load the script with `importlib` (explore/
  is not a package) and test each function on frames built in the test.

Expected files (two): `explore/0001_feasibility_census.py`,
`tests/test_explore_census.py`.

## Out of scope

- Outcome data of any kind; effects; regressions.
- Editing `research/ideas/0001-*.md` or `research/lessons.md` (a person does
  that when merging the run's record PR).
- `src/terrain/`, `pipeline/`, `data/`, workflows, `pyproject.toml`,
  `uv.lock`.

## Done when

1. A test list with elected votes 100, 80 and non-elected 79, 50 gives one
   pair (80 vs 79) with margin 1 / municipal valid votes.
2. A test shows the 2008 and 2012 elected codes are read correctly (a 2008
   candidate with code 5 is elected; a 2012 candidate with code 5 is not).
3. A test pair with a negative margin is counted as inverted and excluded
   from the close counts.
4. A test shows the stronghold is the highest-quotient place with `V_p` >= 50,
   that a place with `V_p` < 50 is never chosen, and that annulled rows do
   not count.
5. A test shows the `nr_zona` text/integer join works after casting.
6. `tests/test_explore.py` passes (the script restricts to the exploration
   half).
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
