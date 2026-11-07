# Task: validate the registered analysis against run 42298466207 (explore, idea 0001)

## Goal

Idea 0001's registered analysis (`src/terrain/registered/r0001/analysis.py`,
PR #236) must give the numbers of the explore code it was frozen from. **This
task runs it once, through `explore-run`, on the exploration half at the
0.50% window** (the window of run 42298466207), and compares its numbers with
run 42298466207 and run 41839642406. It reports only the comparison. It is
run only after PR #236 is merged, by Gabriel or with his go-ahead. The script
is already written (`explore/0001_registered_check.py`, in PR #236); this
issue fixes, word for word, what the run computes and reports (handoff 5,
hard stop 2).

**Outcome data in scope (for referee R2):** `cell_outcomes` of the
exploration half, the years each election reads in run 42298466207 (E-4 ..
E-1 and E+1 .. E+4, never E; for 2024, E-4 .. E-1 only), as in that run.

## What runs

`uv run python explore/0001_registered_check.py --out-dir DIR`, through
`gh workflow run explore-run.yml --ref main -f script=0001_registered_check`.
It calls `analysis.run_exploration(store, half, 0.005, tmp)` with the real
treatment, 2,000 re-flips and seed 20261106, on the exploration half, and
compares:

1. Run 42298466207 (`research/explore-runs/0001/42298466207.json`): its
   `estimates` (all eleven: direct, ring2, ring5, displacement, disp_pre,
   disp_ring10_20, disp_ring20_50, split5, split2, direct_y3,
   displacement_y3), `outcome_cells_dropped` and `type_counts`, every
   number in them.
2. Run 41839642406 (`research/explore-runs/0001/41839642406.json`): kill
   criterion 1's counts per election (2008-2024) and pooled.

**Rule:** whole numbers, text, RI p-values and `p1` must be equal; every
other number must agree within a relative 1e-9 (floating-point sums may be
taken in another order).

## What is reported

`summary.md`: the first line is "Reproduced: yes" or "Reproduced: no", with
how many numbers were compared, how many differ, and the largest relative
difference. Then a table of the first 100 differences (run, path, old, new),
if any. Then the rule, the list of blocks computed but not reported, and the
caveats. `results.json` holds the same.

**Not reported, by design:** the balance table, the direct placebo, the
incumbency-adjusted estimates (Z) and the alignment split at 0.50%. They are
computed, because they are part of the analysis, but none of their numbers
is printed: this is a check of the code, not a new result.

## Expected (a mismatch is a stop, not a result)

- "Reproduced: yes", with 0 differences.
- If any number differs, the record PR is not merged, and Gabriel decides.
  No change is made to the frozen code to force a match.

## Never

- Any run at 0.25% (the analysis refuses it before registration).
- Any read of `sealed/` or `confirm/` (the exploration half only, through
  `explore-run`, whose account cannot read `sealed/`).

## Done when

The record PR of the run is merged with "Reproduced: yes", or Gabriel has
decided what a difference means.
