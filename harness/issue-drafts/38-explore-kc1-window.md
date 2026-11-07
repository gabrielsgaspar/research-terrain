# Task: kill criterion 1 at the 0.25% window (explore)

## Goal

Idea 0001's kill criterion 1 counts close-pair candidates whose stronghold
is in or within 5 km of an indigenous land, and of a settlement, at a margin
of at most 0.5% (run 41839642406: 711 and 2,590, pooled 2008-2024). Decision
0008 chose a 0.25% window, and Gabriel decided (decision 0009, being
written) that the criterion's "0.5%" means the registered window. **This
task recounts kill criterion 1 at 0.25%** on the exploration half, and
recounts 0.50% in the same run as a check. It reads no outcome data and
computes no effect. The script computes exactly what this issue lists and
nothing more (referee R7).

**Outcome data in scope (for referee R2): none.** No `cell_outcomes`,
`cell_exposure` or `cell_displacement` file is read.

## Idea

`research/ideas/0001-electoral-strongholds.md` (kill criterion 1);
decisions 0001 (split) and 0008 (window); run 41839642406
(`research/explore-runs/0001/41839642406.md`). This is an explore task
(label `explore`): it may change only `explore/` and `tests/test_explore*`.

Read first: `explore/0001_kill_criterion_1.py` (the whole script) and
`explore/0001_feasibility_census.py` (`close_candidates`, `_paths`).
Load `0001_kill_criterion_1.py` with importlib, as it loads the census, and
reuse its `candidate_distances`, `band_counts`, `pool`, `verdict`, `LAYERS`,
`BANDS` and `MINIMUM`, and the census's `close_candidates` with its
`threshold` argument. Do not change any existing explore script.

## Definitions

- **Everything as in `0001_kill_criterion_1.py`** (years 2008-2024, the
  main election, within-list pairs, margins, inverted pairs never close,
  strongholds, the tenure join, bands 0, 2 and 5 km, "with coordinates",
  the 200 minimum on the pooled 5 km counts), except the window.
- **Windows**: 0.25% (`threshold` 0.0025) and 0.50% (0.005), each through
  `census.close_candidates(paired, threshold)`. Both are computed from the
  same tables in the same pass; nothing is read twice per year.
- **Verdict** per window from `verdict(pool(...))`. The 0.25% verdict is the
  one that decision 0009 uses; the 0.50% verdict is the check.

## What to report

`summary.md`:
1. First line: the 0.25% pooled 5 km counts (indigenous, settlement) and
   whether kill criterion 1 is met at 0.25%.
2. One table per window, in the format of run 41839642406's (year,
   candidates, with coordinates, indigenous 0/2/5 km, settlement 0/2/5 km;
   pooled row), 0.25% first.
3. Caveats: as in `0001_kill_criterion_1.py`; and that the 0.50% table is a
   reproduction check.

`results.json`: every number above, per window, per year and pooled, with
both verdicts.

## Expected (a mismatch is a stop, not a result)

- The 0.50% table equals run 41839642406's in every cell.
- At 0.25%, candidates per year equal twice decision 0008's pairs: 956,
  1,156, 1,192, 1,352 and 1,082 (2008-2024), 5,738 pooled.

## In scope

Expected files (two): `explore/0001_kill_criterion_1_window.py`,
`tests/test_explore_kc1_window.py`.

## Out of scope

Any outcome or exposure table; any estimate; any window other than 0.25%
and 0.50%; changes to other explore scripts; the idea file and decision 0009
(written from the record); `sealed/` and `confirm/`. No CPF or voter ID
number is read.

## Done when

1. On synthetic pairs, a candidate of a pair at margin 0.3% is in the 0.50%
   counts and not in the 0.25% counts; one at exactly 0.25% is in both; an
   inverted pair is in neither.
2. The per-window counts equal `band_counts(candidate_distances(...))` of
   `0001_kill_criterion_1.py` on the same synthetic inputs with that
   window's close candidates (the 0.50% path is the existing script's).
3. Each table is read once per year (a counting fake store sees one
   download per file).
4. No outcome, exposure or displacement file is read: the fake store sees
   no path from those datasets.
5. `results.json` holds both windows and both verdicts.
6. Every table read is restricted to the exploration half (the existing
   explore test passes); `uv run ruff check .`, `uv run ruff format --check .`
   and `uv run pytest` pass.
