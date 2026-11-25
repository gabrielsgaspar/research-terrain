"""What allied towns get, with the no-plan Pix line fitted in log_pc only (idea 0013, fork f1).

Idea 0013 (`research/ideas/0013-what-allies-get.md`), campaign
`research/campaigns/0015-amendment-objects/campaign.md`, fork f1 of step s5 (decision 0015). It is
`explore/0013_objects_main.py`, loaded as is, with one difference: the descriptive `no_plan` line
under Pix groups is estimated by the linear `log_pc` fit only. Its three Poisson fits (B, C and
pooled B+C) are not run and not written: run 45061701322 had no rows for the one in cycle C, and
no_plan money is already part of `fungible`.

Everything else is the parent's own code: reading, joining, window, fits, differences, Holm,
composition, figures and the finiteness check. The national exploration half only: every file is
restricted to it right after it is read. Nothing on the exploration half is a finding; the result
of a fork is "survived (fork)" or "killed (fork)", never a finding.
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


parent = _load("main0013", "0013_objects_main.py")

load_panels = parent.load_panels
load_objects = parent.load_objects
join_tables = parent.join_tables
sum_gap = parent.sum_gap
add_outcomes = parent.add_outcomes
read_window = parent.read_window
_paths = parent._paths
GROUPS = parent.GROUPS
NOTE = parent.NOTE
WINDOW_SOURCE = parent.WINDOW_SOURCE
_fmt = parent._fmt
_lin = parent._lin

NO_PLAN = "no_plan"


# --- Results


def _without_no_plan_poisson(results: dict[str, Any]) -> dict[str, Any]:
    """A copy of `results` without `pix_groups.no_plan.poisson`; the input is not changed."""
    out = dict(results)
    groups = dict(out["pix_groups"])
    groups[NO_PLAN] = {k: v for k, v in groups[NO_PLAN].items() if k != "poisson"}
    out["pix_groups"] = groups
    return out


def build_results(
    table: pl.DataFrame,
    measurement: pl.DataFrame,
    h: float,
    no_population: int,
    gap: int = 0,
    source: str = WINDOW_SOURCE,
) -> dict[str, Any]:
    """The parent's `build_results`, without the no_plan Poisson fits.

    Two globals of the parent module are swapped for the call and always put back: `poisson_fit`
    skips the no_plan column, and `_all_finite` checks every value that is written (the no_plan
    `log_pc` fits included) but not the Poisson fits that are never written.
    """
    original_fit = parent.poisson_fit
    original_finite = parent._all_finite

    def fit(frame: pl.DataFrame, window: float, column: str) -> dict[str, Any]:
        if column == GROUPS[NO_PLAN]:
            return {}  # never fitted, never written
        return original_fit(frame, window, column)

    def finite(results: Any) -> bool:
        return original_finite(_without_no_plan_poisson(results))

    parent.poisson_fit = fit
    parent._all_finite = finite
    try:
        results = parent.build_results(table, measurement, h, no_population, gap, source)
    finally:
        parent.poisson_fit = original_fit
        parent._all_finite = original_finite
    results["pix_groups"][NO_PLAN].pop("poisson")
    return results


# --- Figures and summary


def _for_parent(results: dict[str, Any]) -> dict[str, Any]:
    """A deep copy without the no_plan group, which has no Poisson premium to draw or list."""
    out = copy.deepcopy(results)
    del out["pix_groups"][NO_PLAN]
    return out


def write_figures(results: dict[str, Any], out_dir: Path) -> None:
    """The parent's three figures; `premium_by_group.png` shows visible, services, fungible."""
    parent.write_figures(_for_parent(results), out_dir)


def summarize(results: dict[str, Any]) -> str:
    """The parent's summary, plus the no_plan line (linear only) and why it is linear only."""
    node = results["pix_groups"][NO_PLAN]["log_pc"]
    lines = [
        "",
        "## no_plan (linear only)",
        "",
        "The no_plan line is linear only: the cycle C Poisson fit had no rows in run "
        "45061701322, and no_plan money is already inside fungible. Descriptive.",
        "",
        "| Scope | log_pc b (se) | F |",
        "| --- | --- | --- |",
    ]
    for scope, v in node.items():
        lines.append(f"| {scope} | {_lin(v)} | {_fmt(v['f_cluster'])} |")
    return parent.summarize(_for_parent(results)) + "\n" + "\n".join(lines)


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

        # the loaders restrict right after each read; restrict again is a no-op that keeps it plain
        panel = restrict(load_panels(reader("amendments_panel"), half), half)
        objects = restrict(load_objects(reader("amendments_objects"), half), half)
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
