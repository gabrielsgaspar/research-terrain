"""Fork f1 of step s2: the incumbency gate with a uniform kernel at |margin| <= 0.10.

Idea 0012 (`research/ideas/0012-incumbency-curse.md`), campaign 0014
(`research/campaigns/0014-incumbency-curse/campaign.md`), fork f1 of step s2, decisions 0015
(forks) and 0017 (validity by the estimator). It loads `explore/0012_incumbency_gate.py` and
re-runs every fit of the gate (counts, balance, placebo, power, for all rows and for the S2
sample) with `h = 0.10` and a uniform kernel in place of the triangular kernel at `h = 0.135`.
Nothing else differs: same panel, `READ_COLUMNS`, seed, re-flips, covariates and clustering. The
exploration half only. s2's kill rules apply unchanged. A fork's result is never a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]


def _load_parent() -> Any:
    name = "incumbency_gate_0012_parent"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / "explore" / "0012_incumbency_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parent = _load_parent()

READ_COLUMNS = parent.READ_COLUMNS
SEED = parent.SEED
DRAWS = parent.DRAWS
BALANCE = parent.BALANCE
RULE_FIELDS = parent.RULE_FIELDS
GateError = parent.GateError

H = 0.10
KERNEL = "uniform"


def _estimates(table: pl.DataFrame, draws: np.ndarray, covariates: Sequence[str]) -> dict:
    """The parent's four blocks, each fitted at this fork's `H` and `KERNEL`."""
    return {
        "counts": parent.counts_at(table, H, KERNEL),
        "balance": parent.balance_at(table, draws, H, KERNEL, covariates),
        "placebo": parent.placebo_at(table, draws, H, KERNEL),
        "power": parent.power_at(table, draws, H, KERNEL),
    }


def build_results(panel: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Everything the gate reports, at the fork's design. Raises `GateError` if a k field fails."""
    table = parent.prepare(panel)
    parent._check_draws(table, draws)
    results = _estimates(table, draws, tuple(BALANCE))
    results["design"] = {"h": H, "kernel": KERNEL, "seed": SEED, "draws": int(draws.shape[0])}
    results["window"] = parent.window_table(panel, draws)

    kept, race_ids = parent.s2_rows(table)
    s2 = _estimates(kept, draws, [c for c in BALANCE if c != "finalist_eligible"])
    s2["window"] = parent.window_table(
        panel.filter(pl.col("finalist_eligible").fill_null(False)), draws[:, race_ids]
    )
    results["s2_sample"] = s2

    finite = all(
        parent._all_finite(node)
        for node in (
            results["balance"],
            results["placebo"],
            results["power"],
            s2["balance"],
            s2["placebo"],
            s2["power"],
        )
    )
    results["estimates"] = {"finite": finite}
    results = parent._clean(results)
    for field in RULE_FIELDS:
        value = parent._get(results, field)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateError(f"kill-rule field {field} is not a finite number")
    return results


def _restrict_half(frame: pl.DataFrame, half: frozenset[str]) -> pl.DataFrame:
    return restrict(frame, half)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def read(name: str, columns: list[str]) -> pl.DataFrame:
            remote = parent._paths("mayor_incumbency_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = pl.read_parquet(local, columns=columns)
            local.unlink()
            return _restrict_half(frame, half)

        panel = parent.load_panel(read, half, columns=READ_COLUMNS)
    draws = parent.sign_draws(parent.n_races(panel))
    results = build_results(panel, draws)
    write_results(args.out_dir, parent.summarize(results), results)


if __name__ == "__main__":
    main()
