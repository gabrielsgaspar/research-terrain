"""Validation of idea 0001's registered analysis on the exploration half (issue draft 39).

Runs `terrain.registered.r0001.analysis` (`run_exploration`) with the real treatment on
the exploration half at the **0.50%** window, the window of run 42298466207, and
compares it number by number with:

- run 42298466207 (`explore/0001_effects.py`; `research/explore-runs/0001/42298466207.json`):
  its `estimates` (every slope, RI p, p1, quantile, clustered SE, mean, percentage,
  count and non-estimable list of its eleven estimates), `outcome_cells_dropped` and
  `type_counts`;
- run 41839642406 (`explore/0001_kill_criterion_1.py`; `.../41839642406.json`): kill
  criterion 1's counts per election and pooled.

The rule: whole numbers, text, RI p-values and p1 must be equal; every other number
must agree within a relative 1e-9 (floating-point sums may be taken in another order).
The script reports only the comparison. Nothing else the analysis computes (the
balance table, the direct placebo, the incumbency-adjusted estimates, the alignment
split) is printed: it only says that each was computed. It never runs at 0.25%: the
analysis refuses that window before registration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.registered.r0001 import analysis
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "research" / "explore-runs" / "0001"
WINDOW = 0.005  # run 42298466207's window; never the registered 0.25%
EFFECTS_RUN = "42298466207"
KC1_RUN = "41839642406"
RTOL = 1e-9
EXACT = ("ri_p", "p1")  # RI p-values are counts over the same draws: equal or not
NEW_BLOCKS = ("direct_pre", "direct_adj", "ring2_adj", "ring5_adj", "direct_pre_adj", "align")
MAX_LISTED = 100


def compare(old: Any, new: Any, path: str = "") -> tuple[list[dict[str, Any]], int, float]:
    """(mismatches, numbers compared, largest relative difference) of `new` against `old`."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [{"path": path, "old": "mapping", "new": repr(type(new).__name__)}], 1, 0.0
        out, n, worst = [], 0, 0.0
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                out.append({"path": f"{path}/{key}", "old": key in old, "new": key in new})
                n += 1
                continue
            m, k, w = compare(old[key], new[key], f"{path}/{key}")
            out, n, worst = out + m, n + k, max(worst, w)
        return out, n, worst
    if isinstance(old, list):
        if not isinstance(new, list) or len(old) != len(new):
            return [{"path": path, "old": old, "new": new}], 1, 0.0
        out, n, worst = [], 0, 0.0
        for i, (a, b) in enumerate(zip(old, new, strict=True)):
            m, k, w = compare(a, b, f"{path}/{i}")
            out, n, worst = out + m, n + k, max(worst, w)
        return out, n, worst
    exact = path.rsplit("/", 1)[-1] in EXACT
    if isinstance(old, float) and isinstance(new, (int, float)) and not isinstance(new, bool):
        rel = abs(old - new) / max(abs(old), 1e-300) if old != new else 0.0
        bad = (old != new) if exact else not math.isclose(old, new, rel_tol=RTOL, abs_tol=1e-15)
        return ([{"path": path, "old": old, "new": new}] if bad else []), 1, rel
    bad = old != new or type(old) is not type(new)
    return ([{"path": path, "old": old, "new": new}] if bad else []), 1, 0.0


def check(results: dict[str, Any], effects: dict[str, Any], kc1: dict[str, Any]) -> dict[str, Any]:
    """The comparison, as written to results.json."""
    results = json.loads(json.dumps(results))  # compared as it would be recorded
    parts = {
        "effects": compare(
            {k: effects[k] for k in ("estimates", "outcome_cells_dropped", "type_counts")},
            {
                "estimates": {k: results["estimates"][k] for k in analysis.EFFECT_LABELS},
                "outcome_cells_dropped": results["outcome_cells_dropped"],
                "type_counts": results["type_counts"],
            },
        ),
        "kill_criterion_1": compare(
            {**{y: kc1[y] for y in kc1 if y.isdigit()}, "pooled": kc1["pooled"]},
            {
                **results["kill_criterion_1"]["per_election"],
                "pooled": results["kill_criterion_1"]["pooled"],
            },
        ),
    }
    mismatches = [dict(m, run=name) for name, (ms, _, _) in parts.items() for m in ms]
    return {
        "window": WINDOW,
        "reproduced": not mismatches,
        "numbers_compared": {name: n for name, (_, n, _) in parts.items()},
        "max_relative_difference": max(w for _, _, w in parts.values()),
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:MAX_LISTED],
        "computed_not_reported": [b for b in NEW_BLOCKS if b in results.get("estimates", {})]
        + (["balance"] if "balance" in results else []),
    }


def summary(c: dict[str, Any]) -> str:
    n = c["numbers_compared"]
    head = (
        f"Reproduced: {'yes' if c['reproduced'] else 'no'}. "
        f"{n['effects']:,} numbers of run {EFFECTS_RUN} and {n['kill_criterion_1']:,} of run "
        f"{KC1_RUN} compared at 0.50% on the exploration half; {c['mismatches']:,} differ; "
        f"largest relative difference {c['max_relative_difference']:.3g}."
    )
    lines = [head, ""]
    if c["first_mismatches"]:
        lines += ["| Run | Path | Old | New |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {m['run']} | `{m['path']}` | {m['old']} | {m['new']} |"
            for m in c["first_mismatches"]
        ]
        lines += [""]
    lines += [
        "Rule: whole numbers, text, RI p-values and p1 equal; other numbers within a relative "
        "1e-9. Computed and not reported (by design): "
        + ", ".join(c["computed_not_reported"])
        + ".",
        "",
        "Caveats: exploration half only; 0.50% is not the registered window, which is never run "
        "before registration; this checks the code path, not the plan's estimates.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    with tempfile.TemporaryDirectory() as tmp:
        results = analysis.run_exploration(
            store, half, WINDOW, Path(tmp), restrict_fn=lambda df: restrict(df, half)
        )
    effects = json.loads((RUNS / f"{EFFECTS_RUN}.json").read_text(encoding="utf-8"))
    kc1 = json.loads((RUNS / f"{KC1_RUN}.json").read_text(encoding="utf-8"))
    c = check(results, effects, kc1)
    write_results(args.out_dir, summary(c), c)


if __name__ == "__main__":
    main()
