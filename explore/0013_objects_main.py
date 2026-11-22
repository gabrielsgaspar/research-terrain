"""What allied towns get, by instrument and by the declared use of Pix (idea 0013, step s4).

Idea 0013 (`research/ideas/0013-what-allies-get.md`), decisions 0003, 0008, 0011 and 0018, campaign
`research/campaigns/0015-amendment-objects/campaign.md`, step s4. The national exploration half
only: every file is restricted to it right after it is read, before anything else.

It splits the amendment premium of towns where the deputy's party narrowly won the mayoralty by
instrument (Pix, health, tied) and, within Pix, by the declared use of the work plans (visible,
services, fungible), at the window of campaign 0011's gate record (h = 7.5%, 5% as a check). The
linear estimator is the one of `explore/0010_amendments_main.py`, loaded as is; the Poisson fits
use `pyfixest.fepois`. Its `results.json` carries `first_stage.n_strong` and `estimates.finite`,
the fields step s5's kill rules read. Nothing on the exploration half is a finding.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pyfixest as pf

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate0013 = _load("gate0013", "0013_objects_gate.py")
main0010 = gate0013.main0010  # one module, so one GateError class

GateError = gate0013.GateError
in_window = gate0013.in_window
prepare = gate0013.prepare
sign_draws = gate0013.sign_draws
n_races = gate0013.n_races
full_fit = gate0013.full_fit
read_window = gate0013.read_window
_all_finite = gate0013._all_finite
_clean = gate0013._clean
_paths = gate0013._paths
by_cycle_fit = main0010.by_cycle_fit

WINDOW_SOURCE = gate0013.WINDOW_SOURCE
CHECK_PCT = gate0013.CHECK_PCT
Z95 = gate0013.Z95
NOTE = gate0013.NOTE
KEYS = gate0013.KEYS
STRONG_F = 10.0
ALL_CYCLES = ("A", "B", "C")
PIX_CYCLES = ("B", "C")  # Pix exists from 2020
SUM_LIMIT = 1.0  # reais
PANEL_COLUMNS = [
    "cycle",
    "cd_ibge",
    "deputy",
    "margin",
    "win",
    "population_m",
    "amend_post_total",
    "amend_post_pix",
]
INSTRUMENTS = {
    "pix": "obj_post_pix",
    "health": "obj_post_health",
    "tied": "obj_post_tied",
}
GROUPS = {
    "visible": "obj_post_pix_visible",
    "services": "obj_post_pix_services",
    "fungible": "obj_post_pix_fungible",
    "no_plan": "obj_post_pix_no_plan",
}
STRONG_GROUPS = ("visible", "services", "fungible")
OBJECT_COLUMNS = ["cycle", "deputy", "cd_ibge", *INSTRUMENTS.values(), *GROUPS.values()]
OUTCOMES = {**INSTRUMENTS, **GROUPS}
MEASUREMENT_MEASURES = ("class_value_share", "group_value_share", "specificity_value_share")
LEGACY_MEASURE = "legacy_share_rows"
FIT_KEYS = gate0013._FIT_KEYS
DECLARED = ("pix_minus_tied", "visible_minus_fungible", "health_c_minus_a")


def _lpc(source: str) -> str:
    return f"ln_{source}"


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


# --- Tables


def join_tables(panel: pl.DataFrame, objects: pl.DataFrame) -> pl.DataFrame:
    """Panel rows with their objects columns.

    Raises `GateError` on repeated keys and on a row without a match on either side.
    """
    for name, table in (("panel", panel), ("objects", objects)):
        if table.select(KEYS).unique().height != table.height:
            raise GateError(f"{name} has repeated (cycle, deputy, cd_ibge) rows")
    lonely_panel = panel.select(KEYS).join(objects.select(KEYS), on=KEYS, how="anti")
    if lonely_panel.height:
        raise GateError(f"{lonely_panel.height} panel rows have no objects row")
    lonely_objects = objects.select(KEYS).join(panel.select(KEYS), on=KEYS, how="anti")
    if lonely_objects.height:
        raise GateError(f"{lonely_objects.height} objects rows have no panel row")
    return panel.join(objects, on=KEYS, how="inner")


def sum_gap(joined: pl.DataFrame) -> int:
    """Rows where pix + health + tied differs from the panel's post-window total by > R$1."""
    parts = sum(pl.col(c).cast(pl.Float64) for c in INSTRUMENTS.values())
    gap = (parts - pl.col("amend_post_total").cast(pl.Float64)).abs() > SUM_LIMIT
    return int(joined.filter(gap.fill_null(False)).height)


def add_outcomes(table: pl.DataFrame, h: float) -> tuple[pl.DataFrame, int]:
    """Rows with a population only, with `ln_<column>` = ln(1 + reais / population) per outcome.

    Also returns the rows inside h left out for having no population. A null `amend_pre_total`
    column lets `prepare` run: no pre-window value is read.
    """
    pop = pl.col("population_m").cast(pl.Float64)
    bad = table.filter(pop.is_null() | (pop <= 0))
    no_population = int(in_window(bad, h).height)
    kept = table.filter(pop > 0).with_columns(
        *(pl.col(src).cast(pl.Float64) for src in OUTCOMES.values()),
        pop.alias("population_m"),
    )
    kept = kept.with_columns(
        *(
            (1.0 + pl.col(src) / pl.col("population_m")).log().alias(_lpc(src))
            for src in OUTCOMES.values()
        ),
        pl.col("population_m").log().alias("ln_pop"),
        pl.col("win").cast(pl.Boolean),
        gate0013._NO_PRE,
    )
    return kept, no_population


# --- Estimates: linear


def _fit(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """`full_fit` at window `h` with its own `prepare` and draws; 95% interval."""
    prepared = prepare(table)
    draws = sign_draws(n_races(prepared))
    fit = full_fit(prepared, draws, h, column)
    b, se = fit["b"], fit["se"]
    out = {k: fit[k] for k in FIT_KEYS}
    out["ci_low"], out["ci_high"] = b - Z95 * se, b + Z95 * se
    return out


def _cycle_fits(table: pl.DataFrame, h: float, column: str) -> dict[str, dict[str, float]]:
    """`by_cycle_fit`: A, B, C and C minus A with b, se and the 95% interval."""
    out = {}
    for scope, v in by_cycle_fit(prepare(table), h, column).items():
        b, se = v["b"], v["se"]
        out[scope] = {"b": b, "se": se, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se}
    return out


def _of(table: pl.DataFrame, cycles: tuple[str, ...]) -> pl.DataFrame:
    return table.filter(pl.col("cycle").is_in(list(cycles)))


# --- Estimates: Poisson

_NAN = float("nan")


def _poisson_result(b: float, se: float, p: float, n_obs: int) -> dict[str, Any]:
    ok = math.isfinite(b) and math.isfinite(se)
    return {
        "b": b,
        "se": se,
        "p": p,
        "premium_pct": 100.0 * (math.exp(b) - 1.0) if math.isfinite(b) else _NAN,
        "premium_ci_low": 100.0 * (math.exp(b - Z95 * se) - 1.0) if ok else _NAN,
        "premium_ci_high": 100.0 * (math.exp(b + Z95 * se) - 1.0) if ok else _NAN,
        "n_obs": n_obs,
    }


def _pois(frame: pl.DataFrame, regressors: list[str], target: str) -> dict[str, Any]:
    """`fepois` of `y` on the regressors, fixed effects `fe`, offset `ln_pop`, CRV1 by `cd_ibge`.

    Fixed-effect groups pyfixest drops (all-zero outcome) leave the fit; `n_obs` is the rows used.
    A fit that cannot be made gives NaN (and `estimates.finite` false).
    """
    if frame.height == 0:
        return _poisson_result(_NAN, _NAN, _NAN, 0)
    formula = f"y ~ {' + '.join(regressors)} | fe"
    try:
        fit = pf.fepois(
            formula,
            data=frame,
            offset="ln_pop",
            vcov={"CRV1": "cd_ibge"},
        )
        return _poisson_result(
            float(fit.coef()[target]),
            float(fit.se()[target]),
            float(fit.pvalue()[target]),
            int(fit.sample_info.n_obs),
        )
    except Exception:  # noqa: BLE001 - separation, singular fits: reported as NaN, never hidden
        return _poisson_result(_NAN, _NAN, _NAN, 0)


def _base(table: pl.DataFrame, h: float, column: str) -> pl.DataFrame:
    """Rows inside h with a finite outcome: `y`, `win`, `margin`, `wm` and what the fit needs."""
    sub = in_window(table, h).filter(
        pl.col(column).is_not_null() & pl.col(column).cast(pl.Float64).is_finite()
    )
    win = (pl.col("margin").cast(pl.Float64) > 0).cast(pl.Float64)
    margin = pl.col("margin").cast(pl.Float64)
    return sub.select(
        pl.col(column).cast(pl.Float64).alias("y"),
        win.alias("win"),
        margin.alias("margin"),
        (win * margin).alias("wm"),
        "ln_pop",
        "cd_ibge",
        pl.col("deputy").alias("fe"),
        "cycle",
    )


_PLAIN = ["win", "margin", "wm"]
_INTERACTED = ["win", "margin", "wm", "win_d", "margin_d", "wm_d"]


def _with_dummy(frame: pl.DataFrame, d: float) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(d).alias("d"),
        (pl.col("win") * d).alias("win_d"),
        (pl.col("margin") * d).alias("margin_d"),
        (pl.col("wm") * d).alias("wm_d"),
    )


def poisson_fit(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """Poisson premium of `win` in `column` (reais) at window `h`: deputy fixed effects."""
    return _pois(_base(table, h, column), _PLAIN, "win")


def poisson_c_minus_a(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """One fit on A and C rows, every regressor also interacted with `isC`; target `win_d`."""
    frame = _base(_of(table, ("A", "C")), h, column)
    d = (pl.col("cycle") == "C").cast(pl.Float64)
    frame = frame.with_columns(
        d.alias("d"),
        (pl.col("win") * d).alias("win_d"),
        (pl.col("margin") * d).alias("margin_d"),
        (pl.col("wm") * d).alias("wm_d"),
    )
    return _pois(frame, _INTERACTED, "win_d")


def poisson_stacked(table: pl.DataFrame, h: float, first: str, second: str) -> dict[str, Any]:
    """First outcome minus second, one fit on both stacked: deputy x outcome fixed effects.

    Every regressor is also interacted with the dummy of the first outcome; the difference is the
    coefficient of `win_d`.
    """
    one = _with_dummy(_base(table, h, first), 1.0).with_columns((pl.col("fe") + "|1").alias("fe"))
    two = _with_dummy(_base(table, h, second), 0.0).with_columns((pl.col("fe") + "|0").alias("fe"))
    return _pois(pl.concat([one, two]), _INTERACTED, "win_d")


def holm(p_values: list[float]) -> list[float]:
    """Holm's step-down adjustment, monotone and capped at 1. NaN in, NaN out."""
    if not all(math.isfinite(p) for p in p_values):
        return [_NAN] * len(p_values)
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


# --- Composition


def composition_from_measurement(measurement: pl.DataFrame) -> dict[str, Any]:
    """Shares copied from `measurement.parquet`: by amendment year (`all` for a null year)."""

    def label(year: Any) -> str:
        return "all" if year is None else str(int(year))

    out: dict[str, Any] = {"measurement": {}, "legacy_share_rows": {}}
    for measure in MEASUREMENT_MEASURES:
        rows = measurement.filter(pl.col("measure") == measure)
        if rows.select("year", "class").unique().height != rows.height:
            raise GateError(f"measurement has repeated (year, class) rows for {measure}")
        node = out["measurement"].setdefault(measure, {})
        for year, klass, value in rows.select("year", "class", "value").iter_rows():
            node.setdefault(label(year), {})[str(klass)] = None if value is None else float(value)
    rows = measurement.filter(pl.col("measure") == LEGACY_MEASURE)
    if rows["year"].n_unique() != rows.height:
        raise GateError(f"measurement has repeated year rows for {LEGACY_MEASURE}")
    for year, value in rows.select("year", "value").iter_rows():
        out["legacy_share_rows"][label(year)] = None if value is None else float(value)
    return out


def within_h_composition(table: pl.DataFrame, h: float) -> dict[str, Any]:
    """Share of each group in the post-window Pix reais, by cycle and win / lose. Plain sums."""
    out: dict[str, Any] = {}
    for c in PIX_CYCLES:
        inside = in_window(table.filter(pl.col("cycle") == c), h)
        out[c] = {}
        for key, flag in (("win", True), ("lose", False)):
            rows = inside.filter(pl.col("win") == flag)
            total = float(rows[INSTRUMENTS["pix"]].sum()) if rows.height else 0.0
            out[c][key] = {
                g: (float(rows[GROUPS[g]].sum()) / total if total > 0 else None)
                for g in STRONG_GROUPS
            }
    return out


# --- Results


def build_results(
    table: pl.DataFrame,
    measurement: pl.DataFrame,
    h: float,
    no_population: int,
    gap: int = 0,
    source: str = WINDOW_SOURCE,
) -> dict[str, Any]:
    """Everything the step reports, at window `h`. `table` is from `add_outcomes`."""
    prepared = prepare(table)
    by_cycle = {}
    for c in ALL_CYCLES:
        s = in_window(prepared.filter(pl.col("cycle") == c), h)
        by_cycle[c] = {"units": int(s.height), "races": n_races(s) if s.height else 0}
    inside = in_window(prepared, h)
    w5 = CHECK_PCT / 100.0

    instruments: dict[str, Any] = {}
    check_5: dict[str, Any] = {}
    for name, src in INSTRUMENTS.items():
        cycles = PIX_CYCLES if name == "pix" else ALL_CYCLES
        scoped = _of(table, cycles)
        lpc = _lpc(src)
        linear: dict[str, Any] = {"pooled": _fit(scoped, h, lpc)}
        pois: dict[str, Any] = {"pooled": poisson_fit(scoped, h, src)}
        if name == "pix":
            for c in PIX_CYCLES:
                linear[c] = _fit(_of(table, (c,)), h, lpc)
        else:
            linear.update(_cycle_fits(scoped, h, lpc))
            pois["c_minus_a"] = poisson_c_minus_a(table, h, src)
        for c in cycles:
            pois[c] = poisson_fit(_of(table, (c,)), h, src)
        instruments[name] = {"log_pc": linear, "poisson": pois}
        f5 = _fit(scoped, w5, lpc)
        p5 = poisson_fit(scoped, w5, src)
        check_5[name] = {
            "log_pc": {k: f5[k] for k in ("b", "se", "ri_p")},
            "poisson": {k: p5[k] for k in ("b", "se", "p")},
        }

    groups: dict[str, Any] = {}
    for name, src in GROUPS.items():
        bc = _of(table, PIX_CYCLES)
        lpc = _lpc(src)
        linear = {"pooled_bc": _fit(bc, h, lpc)}
        pois = {"pooled_bc": poisson_fit(bc, h, src)}
        for c in PIX_CYCLES:
            linear[c] = _fit(_of(table, (c,)), h, lpc)
            pois[c] = poisson_fit(_of(table, (c,)), h, src)
        groups[name] = {"log_pc": linear, "poisson": pois}

    bc = _of(table, PIX_CYCLES)
    health_ca = instruments["health"]["poisson"]["c_minus_a"]
    fits = {
        "pix_minus_tied": poisson_stacked(bc, h, INSTRUMENTS["pix"], INSTRUMENTS["tied"]),
        "visible_minus_fungible": poisson_stacked(bc, h, GROUPS["visible"], GROUPS["fungible"]),
        "health_c_minus_a": health_ca,
    }
    differences = {
        name: {
            "b": v["b"],
            "se": v["se"],
            "p": v["p"],
            "ratio_pct": v["premium_pct"],
            "n_obs": v["n_obs"],
        }
        for name, v in fits.items()
    }
    adjusted = holm([differences[n]["p"] for n in DECLARED])
    declared = {
        n: {"p": differences[n]["p"], "p_holm": q} for n, q in zip(DECLARED, adjusted, strict=True)
    }

    f_by_group = {g: groups[g]["log_pc"]["pooled_bc"]["f_cluster"] for g in STRONG_GROUPS}
    n_strong = sum(int(math.isfinite(f) and f >= STRONG_F) for f in f_by_group.values())

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "check_pct": CHECK_PCT, "source": source},
        "counts": {
            "units_h": int(inside.height),
            "races_h": n_races(inside) if inside.height else 0,
            "by_cycle": by_cycle,
            "no_population": no_population,
            "sum_gap": gap,
        },
        "instruments": instruments,
        "check_5pct": check_5,
        "pix_groups": groups,
        "differences": differences,
        "declared": declared,
        "first_stage": {"n_strong": n_strong, "f_cluster": f_by_group},
    }
    results["estimates"] = {"finite": _all_finite(results)}  # composition shares may be null
    composition = composition_from_measurement(measurement)
    composition["within_h"] = within_h_composition(table, h)
    results["composition"] = composition
    return _clean(results)


# --- Figures


def _num(value: float | None) -> float:
    return _NAN if value is None else float(value)


def write_figures(results: dict[str, Any], out_dir: Path) -> None:
    from terrain.style import configure, save_png

    plt = configure()
    folder = out_dir / "figures"

    def note(fig: Any) -> None:
        fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")

    def points(ax: Any, x: float, v: dict[str, Any]) -> None:
        y = _num(v["premium_pct"])
        if math.isfinite(y):
            err = [[y - _num(v["premium_ci_low"])], [_num(v["premium_ci_high"]) - y]]
            ax.errorbar([x], [y], yerr=err, fmt="o", markersize=4, capsize=2)

    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    for j, node in enumerate(results["instruments"].values()):
        for i, c in enumerate(ALL_CYCLES):
            if c in node["poisson"]:
                points(ax, i + 0.2 * (j - 1), node["poisson"][c])
    ax.set_xticks(range(len(ALL_CYCLES)), [f"Cycle {c}" for c in ALL_CYCLES])
    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Poisson premium (%), 95% interval")
    ax.set_title("Left to right within a cycle: " + ", ".join(INSTRUMENTS))
    note(fig)
    save_png(fig, folder / "premium_by_instrument.png")

    scopes = ("B", "C", "pooled_bc")
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    for i, node in enumerate(results["pix_groups"].values()):
        for j, scope in enumerate(scopes):
            points(ax, i + 0.2 * (j - 1), node["poisson"][scope])
    labels = [n.replace("_", " ") for n in results["pix_groups"]]
    ax.set_xticks(range(len(labels)), labels)
    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Poisson premium (%), 95% interval")
    ax.set_title("Left to right within a group: B, C, B+C")
    note(fig)
    save_png(fig, folder / "premium_by_group.png")

    shares = results["composition"]["measurement"].get("class_value_share", {})
    years = sorted(shares, key=lambda y: (y == "all", y))
    classes = sorted({k for node in shares.values() for k in node})
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    bottom = np.zeros(len(years))
    for klass in classes:
        values = np.array([_num(shares[y].get(klass)) for y in years])
        values = np.nan_to_num(values)
        ax.bar(range(len(years)), values, bottom=bottom, label=klass)
        bottom += values
    ax.set_xticks(range(len(years)), years)
    ax.set_ylabel("Share of plan value")
    ax.set_xlabel("Amendment year")
    if classes:
        ax.legend(fontsize=6, ncol=3)
    note(fig)
    save_png(fig, folder / "composition_by_year.png")


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _prem(v: dict[str, Any]) -> str:
    return (
        f"{_fmt(v['premium_pct'], 3)} [{_fmt(v['premium_ci_low'], 3)}, "
        f"{_fmt(v['premium_ci_high'], 3)}] (p {_fmt(v['p'])}, n {v['n_obs']})"
    )


def _lin(v: dict[str, Any]) -> str:
    return f"{_fmt(v['b'])} ({_fmt(v['se'])})"


def reading(results: dict[str, Any]) -> str:
    """Which reading the declared estimates lean toward, with the interval widths."""
    d = results["differences"]
    vf, pt = d["visible_minus_fungible"], d["pix_minus_tied"]
    if vf["b"] is None or pt["b"] is None:
        return "No reading: an estimate is not finite."

    def width(v: dict[str, Any]) -> float | None:
        return 2 * Z95 * v["se"] if v["se"] is not None else None

    if vf["b"] > 0:
        lean = "credit-claiming (visible minus fungible above 0)"
    elif pt["b"] > 0:
        lean = "broker payment (visible minus fungible below 0 and Pix minus tied above 0)"
    else:
        lean = "neither reading (visible minus fungible below 0 and Pix minus tied below 0)"
    return (
        f"The point estimates lean toward {lean}. Width of the 95% intervals, in log points: "
        f"visible minus fungible {_fmt(width(vf))}, Pix minus tied {_fmt(width(pt))}."
    )


def summarize(results: dict[str, Any]) -> str:
    w, c = results["window"], results["counts"]
    lines = [
        f"Window h = {w['h_pct']:g}%, read from `{w['source']}`; check at {w['check_pct']:g}%. "
        f"Rows at h: {c['units_h']} in {c['races_h']} races (A {c['by_cycle']['A']['units']}, "
        f"B {c['by_cycle']['B']['units']}, C {c['by_cycle']['C']['units']}); rows without a "
        f"population, left out: {c['no_population']}; rows where the instruments do not add up to "
        f"the total (R$1): {c['sum_gap']}. `first_stage.n_strong` = "
        f"{results['first_stage']['n_strong']}; `estimates.finite` = "
        f"{results['estimates']['finite']}.",
        "",
        "Only the three declared estimates below are estimates of this step. Everything else is "
        "descriptive.",
        "",
        "## Declared estimates (Poisson, B and C pooled unless stated; Holm over the three)",
        "",
        "| Estimate | b (se) | ratio, % | raw p | Holm p | rows |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in DECLARED:
        d, q = results["differences"][name], results["declared"][name]
        lines.append(
            f"| {name} | {_lin(d)} | {_fmt(d['ratio_pct'])} | {_fmt(q['p'])} "
            f"| {_fmt(q['p_holm'])} | {d['n_obs']} |"
        )
    lines += ["", reading(results), "", "## (a) Instruments", ""]
    lines += [
        "Linear: ln(1 + reais per inhabitant), b (se). Poisson: premium in %, 95% interval.",
        "",
        "| Instrument | Scope | Linear | Poisson |",
        "| --- | --- | --- | --- |",
    ]
    for name, node in results["instruments"].items():
        for scope, v in node["log_pc"].items():
            lines.append(f"| {name} | {scope} | {_lin(v)} | {_prem(node['poisson'][scope])} |")
        if "c_minus_a" in node["poisson"] and "c_minus_a" not in node["log_pc"]:
            lines.append(f"| {name} | c_minus_a | n/a | {_prem(node['poisson']['c_minus_a'])} |")
    lines += ["", "At 5% (pooled):", ""]
    for name, v in results["check_5pct"].items():
        lines.append(
            f"- {name}: linear b {_fmt(v['log_pc']['b'])} (se {_fmt(v['log_pc']['se'])}, "
            f"randomisation p {_fmt(v['log_pc']['ri_p'])}); Poisson b {_fmt(v['poisson']['b'])} "
            f"(se {_fmt(v['poisson']['se'])}, p {_fmt(v['poisson']['p'])})."
        )
    lines += ["", "## (b) Pix by declared use", "", "| Group | Scope | Linear | F | Poisson |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for name, node in results["pix_groups"].items():
        for scope, v in node["log_pc"].items():
            lines.append(
                f"| {name} | {scope} | {_lin(v)} | {_fmt(v['f_cluster'])} "
                f"| {_prem(node['poisson'][scope])} |"
            )
    lines += [
        "",
        f"Groups with a pooled B+C F of at least {STRONG_F:g}: "
        f"{results['first_stage']['n_strong']}.",
        "",
        "## (c) Composition (descriptive)",
        "",
        "Share of each group in the post-window Pix reais within h, by cycle and win / lose "
        "(visible, services, fungible):",
        "",
    ]
    for cycle, node in results["composition"]["within_h"].items():
        for key, shares in node.items():
            cells = ", ".join(f"{g} {_fmt(s)}" for g, s in shares.items())
            lines.append(f"- {cycle}, {key}: {cells}")
    lines += [
        "",
        "Plan value by class and amendment year, and the Legado row shares, are in "
        "`results.json` (`composition`) and in `figures/composition_by_year.png`.",
        "",
        "## Caveats",
        "",
        "- The classes are declared use (decision 0018), many filed after the Supreme Court's "
        "order.",
        "- The classifier is imperfect (cross-validated macro-F1 on groups 0.80), and its errors "
        "are not corrected on the exploration half (decision 0018, point 7, applies before "
        "confirmation).",
        "- The same exploration half and window as campaigns 0011 and 0013.",
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
