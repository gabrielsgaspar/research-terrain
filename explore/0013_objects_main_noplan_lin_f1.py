"""What allied towns get, with the no-plan Pix line fitted in log_pc only (idea 0013, fork f1).

Idea 0013 (`research/ideas/0013-what-allies-get.md`), campaign
`research/campaigns/0015-amendment-objects/campaign.md`, fork f1 of step s5
(`research/decisions/0015-forks.md`). It repeats step s4's `explore/0013_objects_main.py` (loaded as
is and never edited) with one change: the descriptive `pix_groups.no_plan` line gets its linear
`log_pc` fits and no Poisson fits. The parent run's cycle C Poisson fit for no_plan had no rows,
which made `estimates.finite` false. The national exploration half only: every file is restricted
to it right after it is read. `results.json` carries `first_stage.n_strong` and `estimates.finite`
at the paths of the parent, the fields step s5's kill rules read. A fork's result is "survived
(fork)" or "killed (fork)", never a finding.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parent = _load("objects_main_0013_parent_f1", "0013_objects_main.py")

GateError = parent.GateError
read_window = parent.read_window
join_tables = parent.join_tables
sum_gap = parent.sum_gap
add_outcomes = parent.add_outcomes
_fit = parent._fit
_of = parent._of
_lpc = parent._lpc
_fmt = parent._fmt
_lin = parent._lin
_all_finite = parent._all_finite
_clean = parent._clean
_paths = parent._paths

WINDOW_SOURCE = parent.WINDOW_SOURCE
ALL_CYCLES = parent.ALL_CYCLES
PIX_CYCLES = parent.PIX_CYCLES
PANEL_COLUMNS = parent.PANEL_COLUMNS
OBJECT_COLUMNS = parent.OBJECT_COLUMNS
GROUPS = parent.GROUPS
NOTE = parent.NOTE
NO_PLAN = "no_plan"


# --- Reading


def _load_cycles(
    read: Callable[[str, list[str]], pl.DataFrame],
    prefix: str,
    columns: list[str],
    half: frozenset[str],
) -> pl.DataFrame:
    parts = []
    for cycle in ALL_CYCLES:
        frame = restrict(read(f"{prefix}_{cycle}", columns), half)
        parts.append(
            frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), pl.col("deputy").cast(pl.Utf8))
        )
    return pl.concat(parts, how="vertical_relaxed")


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Panels A, B and C, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "panel", PANEL_COLUMNS, half)


def load_objects(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Objects tables A, B and C, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "objects", OBJECT_COLUMNS, half)


# --- Estimates: the one change


def build_results(
    table: pl.DataFrame,
    measurement: pl.DataFrame,
    h: float,
    no_population: int,
    gap: int = 0,
    source: str = WINDOW_SOURCE,
) -> dict[str, Any]:
    """The parent's results, with no_plan fitted in log_pc only and no Poisson fits for it.

    The parent runs with `GROUPS` lacking no_plan (restored afterwards), so none of its Poisson fits
    runs. Nothing else in the parent's `build_results` reads no_plan.
    """
    full = parent.GROUPS
    parent.GROUPS = {k: v for k, v in full.items() if k != NO_PLAN}
    try:
        results = parent.build_results(table, measurement, h, no_population, gap, source)
    finally:
        parent.GROUPS = full

    bc = _of(table, PIX_CYCLES)
    lpc = _lpc(full[NO_PLAN])
    raw = {"pooled_bc": _fit(bc, h, lpc)}
    for c in PIX_CYCLES:
        raw[c] = _fit(_of(table, (c,)), h, lpc)
    results["pix_groups"][NO_PLAN] = {"log_pc": _clean(raw)}
    # The F of a line that is zero in every row is 0 / 0: no estimate, and no_plan is outside
    # `n_strong`, so it is left out of the finiteness check (it is still written, as null).
    estimates = {c: {k: v for k, v in fit.items() if k != "f_cluster"} for c, fit in raw.items()}
    results["estimates"]["finite"] = bool(results["estimates"]["finite"] and _all_finite(estimates))
    return results


# --- Figures


def _without_no_plan(results: dict[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(results)
    copied["pix_groups"].pop(NO_PLAN, None)
    return copied


def write_figures(results: dict[str, Any], out_dir: Path) -> None:
    """The parent's three figures; `premium_by_group.png` shows no_plan nowhere (no Poisson)."""
    parent.write_figures(_without_no_plan(results), out_dir)


# --- Summary


def summarize(results: dict[str, Any]) -> str:
    text = parent.summarize(_without_no_plan(results))
    lines = [
        "",
        "## (b2) Pix with no plan (linear only)",
        "",
        "| Group | Scope | Linear | F | Poisson |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scope, v in results["pix_groups"][NO_PLAN]["log_pc"].items():
        lines.append(f"| {NO_PLAN} | {scope} | {_lin(v)} | {_fmt(v['f_cluster'])} | n/a |")
    lines += [
        "",
        "- Fork f1: the no_plan line is linear only, because the parent run's cycle C Poisson fit "
        "had no rows (n 0). Its money is already part of `fungible`. The result of a fork reads "
        '"survived (fork)" or "killed (fork)", never a finding.',
    ]
    return text + "\n" + "\n".join(lines)


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    h = read_window()
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def fetch(remote: str) -> Path:
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            return local

        def reader(manifest: str) -> Callable[[str, list[str]], pl.DataFrame]:
            def read(name: str, columns: list[str]) -> pl.DataFrame:
                local = fetch(_paths(manifest, rf"{name}\.parquet$")[0])
                frame = pl.read_parquet(local, columns=columns)
                local.unlink()
                return frame

            return read

        panel = load_panels(reader("amendments_panel"), half)
        objects = load_objects(reader("amendments_objects"), half)
        local = fetch(_paths("amendments_objects", r"measurement\.parquet$")[0])
        measurement = pl.read_parquet(local)
        local.unlink()
    joined = join_tables(panel, objects)
    gap = sum_gap(joined)
    table, no_population = add_outcomes(joined, h)
    results = build_results(table, measurement, h, no_population, gap)
    write_figures(results, args.out_dir)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
