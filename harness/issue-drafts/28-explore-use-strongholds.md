# Task: the explore scripts use `terrain.strongholds` instead of their own copies (explore)

## Goal

`terrain.strongholds` holds exact copies of the close-pair, stronghold and
exposure functions of `explore/0001_feasibility_census.py` and
`explore/0001_exposure_options.py`, tested equal to them
(`tests/test_strongholds.py`). Two copies of one definition can drift. Make
the two explore scripts import those functions from `terrain.strongholds`, so
there is one definition, used by the builds, the figures and the explore
scripts alike. Behaviour must not change.

## Idea

Infrastructure for `research/ideas/0001-electoral-strongholds.md`. This is an
explore task (label `explore`): it may change only `explore/` and
`tests/test_explore*`. Read `src/terrain/strongholds.py` and
`tests/test_strongholds.py` first.

## In scope

- `explore/0001_feasibility_census.py`: replace the definitions of every
  function and constant that `terrain.strongholds` also defines (`_council_round1`,
  `main_election`, `elected_status`, `candidacy_votes`, `within_list_pairs`,
  `valid_votes`, `margins`, `place_candidate_votes`, `strongholds`, and their
  constants) with imports from `terrain.strongholds`, keeping the same names
  in the module (so `explore/0001_kill_criterion_1.py`, which loads the
  census with `importlib`, and `tests/test_strongholds.py` keep working).
  Functions the library does not have stay where they are.
- `explore/0001_exposure_options.py`: the same for `close_pairs`,
  `place_totals`, `place_shares`, `locate_places`, `cell_place_distances`,
  `kernel` and `exposure` and their constants.
- No other change to what the scripts compute, read or write.

Expected files (two): `explore/0001_feasibility_census.py`,
`explore/0001_exposure_options.py`.

## Done when

1. Each name listed above is, in the explore module, the very object of
   `terrain.strongholds` (`census.main_election is strongholds.main_election`),
   checked in `tests/test_explore_census.py` or a new `tests/test_explore_*` test.
2. The existing explore tests (`tests/test_explore*.py`) and
   `tests/test_strongholds.py` pass unchanged.
3. Both scripts still call `exploration_municipalities` and `restrict` on
   every table they read (the existing explore test passes).
4. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
