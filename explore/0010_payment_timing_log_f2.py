"""When allied towns are paid, in ln(1 + reais per inhabitant) (idea 0010, fork f2, campaign 0013).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), campaign
`research/campaigns/0013-amendments-mechanisms/campaign.md`, fork f2 of fork point s6
(`research/decisions/0015-forks.md`). It repeats step s5's monthly payment-timing design
(`explore/0010_payment_timing.py`, loaded as is and never edited) with one change: each month's
outcome is ln(1 + reais per inhabitant) instead of reais per inhabitant. Half-year Y is the mean of
the monthly log outcomes, and cumulative Y is their running sum. The national exploration half only:
every file is restricted to it right after it is read. `results.json` carries
`placebo.lead_ratio` and `estimates.finite` at the paths of s5, the fields step s6's kill rules
read. A fork's result is "survived (fork)" or "killed (fork)", never a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
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


parent = _load("payment_timing_0010_parent_f2", "0010_payment_timing.py")

GateError = parent.GateError
CYCLES = parent.CYCLES
Units = parent.Units
read_window = parent.read_window
month_index = parent.month_index
month_ym = parent.month_ym
phase = parent.phase
fit = parent.fit
lead_ratio = parent.lead_ratio
_mask = parent._mask
_paths = parent._paths
_all_finite = parent._all_finite
_clean = parent._clean
_series = parent._series
_marks = parent._marks
_fmt = parent._fmt

WINDOW_SOURCE = parent.WINDOW_SOURCE
PANEL_COLUMNS = parent.PANEL_COLUMNS
MONTHLY_COLUMNS = parent.MONTHLY_COLUMNS
N_MONTHS = parent.N_MONTHS
PRE = parent.PRE
POST = parent.POST
HALVES = parent.HALVES
SCOPES = parent.SCOPES
MARKS = parent.MARKS
RULINGS = parent.RULINGS
Z95 = parent.Z95
NOTE = parent.NOTE
YLABEL = "ln(1 + reais per inhabitant)"


# --- Reading


def _load_cycles(
    read: Callable[[str, list[str]], pl.DataFrame],
    prefix: str,
    columns: list[str],
    half: frozenset[str],
) -> pl.DataFrame:
    parts = []
    for cycle in CYCLES:
        frame = restrict(read(f"{prefix}_{cycle}", columns), half)
        parts.append(frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8)))
    return pl.concat(parts, how="vertical_relaxed")


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """The three panels, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "panel", PANEL_COLUMNS, half)


def load_monthly(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """The three monthly tables, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "monthly", MONTHLY_COLUMNS, half)


# --- Outcome: the one change


def join_monthly_log(panel: pl.DataFrame, monthly: pl.DataFrame, h: float) -> Units:
    """The parent's join (every check and the no-population count), with y = ln(1 + reais / pop)."""
    units = parent.join_monthly(panel, monthly, h)
    return units._replace(tot=np.log1p(units.tot), pix=np.log1p(units.pix))


# --- Estimates


def build_results(
    panel: pl.DataFrame, monthly: pl.DataFrame, h: float, source: str = WINDOW_SOURCE
) -> dict[str, Any]:
    """Everything the step reports, at window `h`, on the log outcome."""
    units = join_monthly_log(panel, monthly, h)
    by_cycle = {}
    for c in CYCLES:
        s = units.table.filter(pl.col("cycle") == c)
        by_cycle[c] = {"rows": int(s.height), "races": int(s["race"].n_unique())}

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "source": source},
        "counts": {
            "rows_h": int(units.table.height),
            "by_cycle": by_cycle,
            "no_population": units.no_population,
            "months": N_MONTHS,
        },
        "months": {
            f"j{j:02d}": {
                **{f"ym_{c}": month_ym(c, j) for c in CYCLES},
                "phase": phase(j),
            }
            for j in range(N_MONTHS)
        },
        "monthly": {},
        "halves": {},
        "cumulative": {},
    }
    pooled_total: list[float] = []
    for instrument, data in (("total", units.tot), ("pix", units.pix)):
        results["monthly"][instrument] = {}
        results["halves"][instrument] = {}
        results["cumulative"][instrument] = {}
        for scope in SCOPES[instrument]:
            mask = _mask(units, scope, instrument)
            block = {}
            for j in range(N_MONTHS):
                b, se, n = fit(units, data[:, j], mask)
                block[f"j{j:02d}"] = {"b": b, "se": se, "n_units": n}
            results["monthly"][instrument][scope] = block
            if instrument == "total" and scope == "pooled":
                pooled_total = [block[f"j{j:02d}"]["b"] for j in range(N_MONTHS)]
            results["halves"][instrument][scope] = {
                name: dict(
                    zip(("b", "se"), fit(units, data[:, a:z].mean(axis=1), mask)[:2], strict=True)
                )
                for name, a, z in HALVES
            }
            running = np.cumsum(data, axis=1)
            results["cumulative"][instrument][scope] = {
                f"j{j:02d}": dict(
                    zip(("b", "se"), fit(units, running[:, j], mask)[:2], strict=True)
                )
                for j in range(N_MONTHS)
            }
    results["placebo"] = lead_ratio(pooled_total)
    results["estimates"] = {"finite": _all_finite(results)}
    return _clean(results)


# --- Figures


def write_figures(results: dict[str, Any], out_dir: Path) -> None:
    from terrain.style import configure, save_png

    plt = configure()
    months = np.arange(N_MONTHS)
    fig, axes = plt.subplots(len(CYCLES), 1, figsize=(6.0, 7.0), sharex=True)
    for ax, c in zip(axes, CYCLES, strict=True):
        block = results["monthly"]["total"][c]
        b, se = _series(block, "b"), _series(block, "se")
        ax.errorbar(months, b, yerr=Z95 * se, fmt="o", markersize=3, capsize=2, linewidth=0.8)
        ax.axhline(0.0, color="black", linewidth=0.5)
        _marks(ax, c)
        ax.set_ylabel(f"Cycle {c}: b ({YLABEL})", fontsize=7)
    axes[-1].set_xlabel("Month j (0 = January of the year before the mayoral election)")
    axes[0].legend(frameon=False, fontsize=6)
    axes[-1].legend(frameon=False, fontsize=6)
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "monthly_by_cycle.png")

    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    for c in CYCLES:
        ax.plot(months, _series(results["cumulative"]["total"][c], "b"), label=f"Cycle {c}")
    ax.axhline(0.0, color="black", linewidth=0.5)
    for j, _ in MARKS:
        ax.axvline(j, color="grey", linewidth=0.8, linestyle="--")
    for j, _ in RULINGS:
        ax.axvline(j, color="tab:red", linewidth=0.8, linestyle=":")
    ax.set_xlabel("Month j (0 = January of the year before the mayoral election)")
    ax.set_ylabel(f"Cumulative b ({YLABEL})")
    ax.legend(frameon=False)
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "cumulative_gap.png")


# --- Summary


def summarize(results: dict[str, Any]) -> str:
    w, c, p = results["window"], results["counts"], results["placebo"]
    lines = [
        f"Window h = {w['h_pct']:g}%, read from `{w['source']}`. Panel rows at h used in the fits: "
        f"{c['rows_h']} (A {c['by_cycle']['A']['rows']}, B {c['by_cycle']['B']['rows']}, "
        f"C {c['by_cycle']['C']['rows']}); rows without a population, left out: "
        f"{c['no_population']}. Months j = 0..{c['months'] - 1}. Outcome: {YLABEL}.",
        "",
        "## Lead ratio (kill rule input)",
        "",
        f"Pooled `total`: mean monthly b before the mayoral term's end (j 0-20) "
        f"{_fmt(p['pre_mean'])}, after the inauguration (j 24-44) {_fmt(p['post_mean'])}, "
        f"lead ratio {_fmt(p['lead_ratio'])}. "
        f"`estimates.finite` = {results['estimates']['finite']}.",
    ]
    for instrument in ("total", "pix"):
        scopes = SCOPES[instrument]
        lines += [
            "",
            f"## Half-years, `{instrument}` (b (SE), {YLABEL})",
            "",
            "| Half-year | " + " | ".join(scopes) + " |",
            "| --- | " + " | ".join("---" for _ in scopes) + " |",
        ]
        for name, _, _ in HALVES:
            cells = []
            for s in scopes:
                v = results["halves"][instrument][s][name]
                cells.append(f"{_fmt(v['b'])} ({_fmt(v['se'])})")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Months, pooled `total` (every third month)",
        "",
        "| j | phase | b | SE | units |",
        "| --- | --- | --- | --- | --- |",
    ]
    block = results["monthly"]["total"]["pooled"]
    for j in [*range(0, N_MONTHS, 3), N_MONTHS - 1]:
        key = f"j{j:02d}"
        v = block[key]
        lines.append(
            f"| {j} | {results['months'][key]['phase']} | {_fmt(v['b'])} | {_fmt(v['se'])} "
            f"| {v['n_units']} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- This is fork f2 at fork point s6 of campaign 0013, a transform of the outcome: "
        "ln(1 + reais per inhabitant) instead of reais per inhabitant. Its result reads "
        '"survived (fork)" or "killed (fork)", never a finding.',
        "- The same exploration half and window as step s5 and campaign 0011.",
        "- The mean of logs is not the log of the mean: the cumulative gap in logs is a sum of "
        "monthly log gaps, not ln of the cumulative reais.",
        "- No declared estimate in this step: everything is descriptive, and no Holm adjustment "
        "applies.",
        "- Monthly fits have clustered errors only (no randomisation inference).",
        "- Nominal reais.",
        "- Nothing on the exploration half is a finding.",
    ]
    return "\n".join(lines)


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    h = read_window()
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def reader(manifest: str) -> Callable[[str, list[str]], pl.DataFrame]:
            def read(name: str, columns: list[str]) -> pl.DataFrame:
                remote = _paths(manifest, rf"{name}\.parquet$")[0]
                local = Path(tmp) / Path(remote).name
                store.download(remote, local)
                frame = pl.read_parquet(local, columns=columns)
                local.unlink()
                return frame

            return read

        panel = load_panels(reader("amendments_panel"), half)
        monthly = load_monthly(reader("amendments_monthly"), half)
    results = build_results(panel, monthly, h)
    write_figures(results, args.out_dir)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
