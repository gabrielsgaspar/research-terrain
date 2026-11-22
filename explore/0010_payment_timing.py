"""When allied towns are paid: monthly amendment payments around the mayoral term (idea 0010, s5).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), hypothesis H6 of idea 0011
(`research/ideas/0011-who-gains-from-pix.md`), decisions 0003, 0008 and 0011, campaign
`research/campaigns/0013-amendments-mechanisms/campaign.md`, step s5. The national exploration half
only: every file is restricted to it right after it is read, before anything else.

The window is read from campaign 0011's gate record (`window.h_pct`, which must be 7.5); no window
is chosen here. For each month from January of the year before the mayoral election (j = 0) to
September of the next general election (j = 44) it estimates, with the linear estimator of
`explore/0010_amendments_main.py` loaded as is (deputy-by-cycle fixed effects, errors clustered by
town), how many more reais per inhabitant a deputy pays to a town where the deputy's party narrowly
won. Half-year and cumulative versions come with it. Its `results.json` carries
`placebo.lead_ratio` and `estimates.finite`, the fields step s6's kill rules read. Nothing on the
exploration half is a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
WINDOW_RECORD = REPO / "research" / "explore-runs" / "0010" / "44484340952.json"
WINDOW_SOURCE = "research/explore-runs/0010/44484340952.json"


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


main0010 = _load("main0010", "0010_amendments_main.py")
gate = main0010.gate

GateError = main0010.GateError
CYCLES = main0010.CYCLES
in_window = main0010.in_window
prepare = main0010.prepare
Sample = main0010.Sample
fe_fit = main0010.fe_fit
_col = gate.g9._col
_all_finite = main0010._all_finite
_clean = main0010._clean
_paths = main0010._paths

H_PCT = 7.5
Z95 = 1.96
NOTE = "exploration half, not a finding"
PANEL_COLUMNS = ["cycle", "m", "cd_ibge", "deputy", "margin", "win", "population_m"]
MONTHLY_COLUMNS = ["cycle", "deputy", "cd_ibge", "ym", "amend_total", "amend_pix"]
KEYS = ["cycle", "deputy", "cd_ibge"]
MAYORAL_YEAR = {"A": 2016, "B": 2020, "C": 2024}
FILE_MONTHS = 46  # January of m-1 to October of t1, as the file has them
N_MONTHS = 45  # j = 0..44: October of t1 is dropped
PRE = range(0, 21)  # January m-1 to September m
POST = range(24, 45)  # January m+1 to September t1
HALVES = (
    ("y_m1_h1", 0, 6),
    ("y_m1_h2", 6, 12),
    ("y_m_h1", 12, 18),
    ("y_m_h2", 18, 24),
    ("y_p1_h1", 24, 30),
    ("y_p1_h2", 30, 36),
    ("y_t1_h1", 36, 42),
    ("y_t1_q3", 42, 45),
)
SCOPES = {"total": (*CYCLES, "pooled"), "pix": ("B", "C", "pooled")}
MARKS = ((21, "Mayoral election"), (24, "Inauguration"), (45, "General election"))
RULINGS = ((19, "Supreme Court Pix ruling, Aug 2024"), (23, "Supreme Court Pix ruling, Dec 2024"))
_NO_PRE = pl.lit(None, dtype=pl.Float64).alias("amend_pre_total")


# --- Window and months


def read_window(path: Path = WINDOW_RECORD) -> float:
    """h as a fraction, from the record's `window.h_pct`. Raises unless it is 7.5."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    h_pct = record["window"]["h_pct"]
    if h_pct is None or not math.isclose(float(h_pct), H_PCT, abs_tol=1e-9):
        raise GateError(f"window.h_pct in {Path(path).name} is {h_pct}, not {H_PCT}")
    return float(h_pct) / 100.0


def month_index(cycle: str, ym: int) -> int:
    """j = 12 x (year - (m - 1)) + (month - 1); 0 is January of m-1."""
    return 12 * (ym // 100 - (MAYORAL_YEAR[cycle] - 1)) + ym % 100 - 1


def month_ym(cycle: str, j: int) -> int:
    year = MAYORAL_YEAR[cycle] - 1 + j // 12
    return year * 100 + j % 12 + 1


def phase(j: int) -> str:
    if j <= 20:
        return "pre"
    return "transition" if j <= 23 else "post"


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


# --- Tables


class Units(NamedTuple):
    """One row per panel row inside h with a population; `tot` and `pix` are (n, 45) arrays."""

    table: pl.DataFrame
    tot: np.ndarray
    pix: np.ndarray
    margin: np.ndarray
    race: np.ndarray
    deputy: np.ndarray
    cluster: np.ndarray
    cycle: np.ndarray
    no_population: int


def join_monthly(panel: pl.DataFrame, monthly: pl.DataFrame, h: float) -> Units:
    """Panel rows inside h joined to their months j = 0..44, in reais per inhabitant.

    Raises `GateError` if a monthly row has no panel row, a month is outside January m-1 to October
    t1, or a panel row inside h does not have exactly 46 distinct months. Rows whose
    `population_m` is null or 0 are counted and dropped.
    """
    if panel.select(KEYS).unique().height != panel.height:
        raise GateError("panel has repeated (cycle, deputy, cd_ibge) rows")
    wrong_m = panel.filter(
        pl.col("m") != pl.col("cycle").replace_strict(MAYORAL_YEAR, return_dtype=pl.Int64)
    )
    if wrong_m.height:
        raise GateError(f"{wrong_m.height} panel rows have an m that does not match their cycle")
    orphan = monthly.select(KEYS).unique().join(panel.select(KEYS), on=KEYS, how="anti")
    if orphan.height:
        raise GateError(f"{orphan.height} monthly (cycle, deputy, cd_ibge) have no panel row")

    monthly = monthly.with_columns(
        pl.col("ym").cast(pl.Int64),
        (
            12
            * (
                pl.col("ym").cast(pl.Int64) // 100
                - pl.col("cycle").replace_strict(
                    {c: y - 1 for c, y in MAYORAL_YEAR.items()}, return_dtype=pl.Int64
                )
            )
            + pl.col("ym").cast(pl.Int64) % 100
            - 1
        ).alias("j"),
    )
    if monthly.filter((pl.col("j") < 0) | (pl.col("j") >= FILE_MONTHS)).height:
        raise GateError("a month is outside January of m-1 to October of t1")

    inside = in_window(panel, h)
    per_unit = monthly.group_by(KEYS).agg(
        pl.len().alias("n_rows"), pl.col("j").n_unique().alias("n_months")
    )
    bad = inside.join(per_unit, on=KEYS, how="left").filter(
        pl.col("n_rows").is_null()
        | (pl.col("n_rows") != FILE_MONTHS)
        | (pl.col("n_months") != FILE_MONTHS)
    )
    if bad.height:
        raise GateError(
            f"{bad.height} panel rows inside the window do not have {FILE_MONTHS} months"
        )

    pop = pl.col("population_m").cast(pl.Float64)
    no_pop = int(inside.filter(pop.is_null() | (pop <= 0)).height)
    units = inside.filter(pop > 0)
    table = prepare(units.with_columns(_NO_PRE)).sort(KEYS)
    rows = (
        monthly.filter(pl.col("j") < N_MONTHS)
        .join(table.select(*KEYS, "population_m"), on=KEYS, how="inner")
        .sort([*KEYS, "j"])
    )
    pop_rows = rows["population_m"].cast(pl.Float64)
    tot = (rows["amend_total"].cast(pl.Float64) / pop_rows).to_numpy().reshape(-1, N_MONTHS)
    pix = (rows["amend_pix"].cast(pl.Float64) / pop_rows).to_numpy().reshape(-1, N_MONTHS)
    deputy = table.select(
        pl.concat_str([pl.col("cycle"), pl.col("deputy").cast(pl.Utf8)], separator="|")
    )
    return Units(
        table=table,
        tot=tot,
        pix=pix,
        margin=_col(table, "margin"),
        race=table["race"].to_numpy(),
        deputy=deputy.to_series().to_numpy(),
        cluster=table["cd_ibge"].to_numpy(),
        cycle=table["cycle"].to_numpy(),
        no_population=no_pop,
    )


# --- Estimates


def _mask(units: Units, scope: str, instrument: str) -> np.ndarray:
    if scope == "pooled":
        cycles = CYCLES if instrument == "total" else ("B", "C")
        return np.isin(units.cycle, cycles)
    return units.cycle == scope


def fit(units: Units, y: np.ndarray, mask: np.ndarray) -> tuple[float, float, int]:
    """b and se of `win` (deputy fixed effects, clustered by town) and the units on the fit."""
    sample = Sample(
        y[mask], units.margin[mask], units.race[mask], units.deputy[mask], units.cluster[mask]
    )
    out = fe_fit(sample)
    return out["b"], out["se"], sample.n


def lead_ratio(monthly_total_pooled: list[float]) -> dict[str, float]:
    """Mean of the monthly b over the pre months and the post months, and |pre| / |post|."""
    pre = float(np.mean([monthly_total_pooled[j] for j in PRE]))
    post = float(np.mean([monthly_total_pooled[j] for j in POST]))
    ratio = abs(pre) / abs(post) if math.isfinite(post) and post != 0 else float("nan")
    return {"pre_mean": pre, "post_mean": post, "lead_ratio": ratio}


def build_results(
    panel: pl.DataFrame, monthly: pl.DataFrame, h: float, source: str = WINDOW_SOURCE
) -> dict[str, Any]:
    """Everything the step reports, at window `h`."""
    units = join_monthly(panel, monthly, h)
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


def _series(block: dict[str, Any], key: str) -> np.ndarray:
    nan = float("nan")
    return np.array(
        [
            nan if block[f"j{j:02d}"][key] is None else block[f"j{j:02d}"][key]
            for j in range(N_MONTHS)
        ],
        dtype=float,
    )


def _marks(ax: Any, cycle: str) -> None:
    for j, label in MARKS:
        ax.axvline(j, color="grey", linewidth=0.8, linestyle="--", label=label)
    if cycle == "C":
        for j, label in RULINGS:
            ax.axvline(j, color="tab:red", linewidth=0.8, linestyle=":", label=label)


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
        ax.set_ylabel(f"Cycle {c}: b (reais per inhabitant)")
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
    ax.set_ylabel("Cumulative b (reais per inhabitant)")
    ax.legend(frameon=False)
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "cumulative_gap.png")


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def summarize(results: dict[str, Any]) -> str:
    w, c, p = results["window"], results["counts"], results["placebo"]
    lines = [
        f"Window h = {w['h_pct']:g}%, read from `{w['source']}`. Panel rows at h used in the fits: "
        f"{c['rows_h']} (A {c['by_cycle']['A']['rows']}, B {c['by_cycle']['B']['rows']}, "
        f"C {c['by_cycle']['C']['rows']}); rows without a population, left out: "
        f"{c['no_population']}. Months j = 0..{c['months'] - 1}.",
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
            f"## Half-years, `{instrument}` (b (SE), reais per inhabitant)",
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
        "- No declared estimate in this step: everything is descriptive, and no Holm adjustment "
        "applies.",
        "- The same exploration half and window campaign 0011 analysed; H6 was declared in idea "
        "0011's file on 2026-11-20, after campaign 0011's results.",
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
