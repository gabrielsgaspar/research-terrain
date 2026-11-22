"""The gate for what allied towns get: measure, plan coverage, Pix first stage, placebo.

Idea 0013 (`research/ideas/0013-what-allies-get.md`), decisions 0003, 0008, 0011 and 0018, campaign
`research/campaigns/0015-amendment-objects/campaign.md`, step s2. The national exploration half
only: every file is restricted to it right after it is read, before anything else.

Before any analysis by instrument or plan class it checks four things: the Pix work-plan measure is
reliable (kappa and cross-validated macro-F1 on groups, read from `measurement.parquet`), most Pix
money has a plan, Pix money jumps where the deputy's party narrowly won (cycles B and C pooled),
and in cycle C there is no comparable jump before the mayoral election. The window is read from
campaign 0011's gate record (`window.h_pct`, which must be 7.5); no window is chosen here. The
linear estimator is the one of `explore/0010_amendments_main.py`, loaded as is. Its `results.json`
carries the fields step s3's kill rules read. Nothing on the exploration half is a finding.
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
from typing import Any

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

GateError = main0010.GateError
in_window = main0010.in_window
prepare = main0010.prepare
sign_draws = main0010.sign_draws
n_races = main0010.n_races
full_fit = main0010.full_fit
_all_finite = main0010._all_finite
_clean = main0010._clean
_paths = main0010._paths

H_PCT = 7.5
CHECK_PCT = 5.0
Z95 = 1.96
NOTE = "exploration half, not a finding"
CYCLES = ("B", "C")  # Pix exists from 2020: cycle A is not read
KEYS = ["cycle", "deputy", "cd_ibge"]
WINDOWS = ("pre", "post")
PANEL_COLUMNS = [
    "cycle",
    "cd_ibge",
    "deputy",
    "margin",
    "win",
    "population_m",
    "amend_pre_pix",
    "amend_post_pix",
]
OBJECT_COLUMNS = ["cycle", "deputy", "cd_ibge", "obj_pre_pix", "obj_post_pix"]
MISMATCH_LIMIT = 1.0  # reais
BIN_WIDTH = 0.005  # 0.5 percentage points of the margin
THRESHOLDS = {"kappa": 0.70, "f1": 0.80, "plan": 0.85, "f": 10.0}
_NO_PRE = pl.lit(None, dtype=pl.Float64).alias("amend_pre_total")


# --- Window


def read_window(path: Path = WINDOW_RECORD) -> float:
    """h as a fraction, from the record's `window.h_pct`. Raises unless it is 7.5."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    h_pct = record["window"]["h_pct"]
    if h_pct is None or not math.isclose(float(h_pct), H_PCT, abs_tol=1e-9):
        raise GateError(f"window.h_pct in {Path(path).name} is {h_pct}, not {H_PCT}")
    return float(h_pct) / 100.0


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
        parts.append(
            frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), pl.col("deputy").cast(pl.Utf8))
        )
    return pl.concat(parts, how="vertical_relaxed")


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Panels B and C, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "panel", PANEL_COLUMNS, half)


def load_objects(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Objects tables B and C, each restricted to the exploration half right after it is read."""
    return _load_cycles(read, "objects", OBJECT_COLUMNS, half)


# --- Tables


def join_objects(panel: pl.DataFrame, objects: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Panel rows with their objects columns, and the number of Pix mismatches (always 0).

    Raises `GateError` on repeated keys, on a row without a match on either side, and if any
    `obj_<w>_pix` differs from the panel's `amend_<w>_pix` by more than R$1.
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
    joined = panel.join(objects, on=KEYS, how="inner")
    mismatch = 0
    for w in WINDOWS:
        a, b = pl.col(f"obj_{w}_pix").cast(pl.Float64), pl.col(f"amend_{w}_pix").cast(pl.Float64)
        differs = (a - b).abs() > MISMATCH_LIMIT
        one_null = a.is_null() != b.is_null()
        mismatch += int(joined.filter(differs.fill_null(False) | one_null).height)
    if mismatch:
        raise GateError(f"{mismatch} rows where obj_<w>_pix and amend_<w>_pix differ by > R$1")
    return joined, mismatch


def add_outcomes(table: pl.DataFrame, h: float) -> tuple[pl.DataFrame, int]:
    """Rows with a population only, with the two outcomes; and the rows inside h left out."""
    pop = pl.col("population_m").cast(pl.Float64)
    bad = table.filter(pop.is_null() | (pop <= 0))
    no_population = int(in_window(bad, h).height)
    kept = table.filter(pop > 0).with_columns(
        (1.0 + pl.col("obj_pre_pix").cast(pl.Float64) / pop).log().alias("pix_pre_log_pc"),
        (1.0 + pl.col("obj_post_pix").cast(pl.Float64) / pop).log().alias("pix_post_log_pc"),
    )
    return kept.with_columns(_NO_PRE), no_population


def read_measure(measurement: pl.DataFrame) -> dict[str, Any]:
    """The measure fields. Raises `GateError` if a needed row is missing or appears twice."""

    def one(measure: str, cycle: str | None) -> float:
        cycle_is = pl.col("cycle").is_null() if cycle is None else pl.col("cycle") == cycle
        rows = measurement.filter((pl.col("measure") == measure) & cycle_is)
        if cycle is None:
            rows = rows.filter(pl.col("year").is_null() & pl.col("class").is_null())
        if rows.height != 1:
            raise GateError(
                f"measurement has {rows.height} rows for {measure} (cycle {cycle}), need 1"
            )
        return float(rows["value"][0])

    by_cycle = {c: one("pix_value_with_plan", c) for c in CYCLES}
    return {
        "kappa_groups": one("kappa_groups", None),
        "cv_macro_f1_groups": one("cv_macro_f1_groups", None),
        "pix_value_with_plan_by_cycle": by_cycle,
        "pix_value_with_plan": min(by_cycle.values()),
    }


# --- Estimates


def _fit(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """`full_fit` at window `h` with its own `prepare` and draws; 95% interval."""
    prepared = prepare(table)
    draws = sign_draws(n_races(prepared))
    fit = full_fit(prepared, draws, h, column)
    b, se = fit["b"], fit["se"]
    fit["ci_low"], fit["ci_high"] = b - Z95 * se, b + Z95 * se
    return fit


_FIT_KEYS = ("b", "se", "ci_low", "ci_high", "ri_p", "mean", "n_units", "n_races", "f_cluster")


def build_results(
    table: pl.DataFrame,
    measure: dict[str, Any],
    h: float,
    no_population: int,
    mismatch: int = 0,
    source: str = WINDOW_SOURCE,
) -> dict[str, Any]:
    """Everything the step reports, at window `h`. `table` is from `add_outcomes`."""
    pooled = prepare(table)
    by_cycle = {}
    for c in CYCLES:
        s = in_window(pooled.filter(pl.col("cycle") == c), h)
        by_cycle[c] = {"units": int(s.height), "races": n_races(s) if s.height else 0}
    inside = in_window(pooled, h)

    first = _fit(table, h, "pix_post_log_pc")
    first_5 = _fit(table, CHECK_PCT / 100.0, "pix_post_log_pc")
    c_table = table.filter(pl.col("cycle") == "C")
    pre = _fit(c_table, h, "pix_pre_log_pc")
    post = _fit(c_table, h, "pix_post_log_pc")

    b_pre, b_post = pre["b"], post["b"]
    finite = all(math.isfinite(v) for v in (b_pre, b_post, pre["ri_p"]))
    ratio = abs(b_pre) / abs(b_post) if math.isfinite(b_post) and b_post != 0 else float("nan")
    pre_fail = int(finite and abs(b_pre) > 0.5 * abs(b_post) and pre["ri_p"] < 0.05)

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "check_pct": CHECK_PCT, "source": source},
        "counts": {
            "units_h": int(inside.height),
            "races_h": n_races(inside) if inside.height else 0,
            "by_cycle": by_cycle,
            "no_population": no_population,
        },
        "checks": {"pix_mismatch": mismatch},
        "measure": measure,
        "first_stage": {k: first[k] for k in _FIT_KEYS},
        "check_5pct": {"first_stage": {k: first_5[k] for k in ("b", "se", "ri_p", "f_cluster")}},
        "placebo": {
            "pre": {k: pre[k] for k in ("b", "se", "ri_p", "mean", "n_units")},
            "post": {k: post[k] for k in ("b", "se", "ri_p", "mean", "n_units")},
            "ratio": ratio,
            "pre_fail": pre_fail,
        },
    }
    results["estimates"] = {"finite": _all_finite(results)}
    return _clean(results)


# --- Figure


def binned_means(table: pl.DataFrame, h: float) -> pl.DataFrame:
    """Mean `pix_post_log_pc` by 0.5-point bin of the margin within +-h (bin centre in points)."""
    n_bins = round(2 * h / BIN_WIDTH)
    inside = in_window(table, h).filter(pl.col("pix_post_log_pc").is_not_null())
    bins = (
        ((pl.col("margin").cast(pl.Float64) + h) / BIN_WIDTH)
        .floor()
        .clip(0, n_bins - 1)
        .cast(pl.Int64)
    )
    return (
        inside.with_columns(bins.alias("bin"))
        .group_by("bin")
        .agg(pl.col("pix_post_log_pc").mean().alias("mean"), pl.len().alias("n"))
        .with_columns(((pl.col("bin") + 0.5) * BIN_WIDTH - h).mul(100).alias("centre"))
        .sort("bin")
    )


def write_figure(table: pl.DataFrame, h: float, out_dir: Path) -> None:
    from terrain.style import configure, save_png

    plt = configure()
    fig, axes = plt.subplots(1, len(CYCLES), figsize=(6.5, 3.2), sharey=True)
    for ax, c in zip(axes, CYCLES, strict=True):
        binned = binned_means(table.filter(pl.col("cycle") == c), h)
        ax.plot(binned["centre"].to_numpy(), binned["mean"].to_numpy(), "o", markersize=3)
        ax.axvline(0.0, color="grey", linewidth=0.8, linestyle="--")
        ax.set_title(f"Cycle {c}")
        ax.set_xlabel("Margin of the deputy's party's finalist (percentage points)")
    axes[0].set_ylabel("Mean ln(1 + Pix reais per inhabitant), post window")
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "binned_pix.png")


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def summarize(results: dict[str, Any]) -> str:
    w, c, m = results["window"], results["counts"], results["measure"]
    fs, f5, p = results["first_stage"], results["check_5pct"]["first_stage"], results["placebo"]
    t = THRESHOLDS
    return "\n".join(
        [
            f"Window h = {w['h_pct']:g}%, read from `{w['source']}`; check at {w['check_pct']:g}%. "
            f"Rows at h: {c['units_h']} in {c['races_h']} races (B {c['by_cycle']['B']['units']}, "
            f"C {c['by_cycle']['C']['units']}); rows without a population, left out: "
            f"{c['no_population']}. Pix mismatches: {results['checks']['pix_mismatch']}.",
            "",
            "## The measure (kill thresholds in brackets)",
            "",
            f"- Kappa on groups: {_fmt(m['kappa_groups'])} (kill below {t['kappa']}).",
            f"- Cross-validated macro-F1 on groups: {_fmt(m['cv_macro_f1_groups'])} "
            f"(kill below {t['f1']}).",
            f"- Share of Pix reais with a plan, smaller of B and C: "
            f"{_fmt(m['pix_value_with_plan'])} (B "
            f"{_fmt(m['pix_value_with_plan_by_cycle']['B'])}, C "
            f"{_fmt(m['pix_value_with_plan_by_cycle']['C'])}; kill below {t['plan']}).",
            "",
            "## Pix first stage, cycles B and C pooled (ln(1 + reais per inhabitant))",
            "",
            f"- At h: b {_fmt(fs['b'])} (se {_fmt(fs['se'])}, 95% interval "
            f"{_fmt(fs['ci_low'])} to {_fmt(fs['ci_high'])}), randomisation p {_fmt(fs['ri_p'])}, "
            f"mean {_fmt(fs['mean'])}, {fs['n_units']} units, {fs['n_races']} races, "
            f"F {_fmt(fs['f_cluster'])} (kill below {t['f']:g}).",
            f"- At {w['check_pct']:g}%: b {_fmt(f5['b'])} (se {_fmt(f5['se'])}), randomisation p "
            f"{_fmt(f5['ri_p'])}, F {_fmt(f5['f_cluster'])}.",
            "",
            "## Placebo, cycle C",
            "",
            f"- Pre window: b {_fmt(p['pre']['b'])} (se {_fmt(p['pre']['se'])}), randomisation p "
            f"{_fmt(p['pre']['ri_p'])}.",
            f"- Post window: b {_fmt(p['post']['b'])} (se {_fmt(p['post']['se'])}), "
            f"randomisation p {_fmt(p['post']['ri_p'])}.",
            f"- |pre| / |post| = {_fmt(p['ratio'])}; `placebo.pre_fail` = {p['pre_fail']} "
            f"(kill if 1). `estimates.finite` = {results['estimates']['finite']}.",
            "",
            "## Caveats",
            "",
            "- The same exploration half and window campaign 0011 analysed, so this is a further "
            "look at the same data.",
            "- The work-plan classes are declared use (decision 0018), not spending.",
            "- The cycle C pre window spans the Supreme Court Pix rulings of August and "
            "December 2024.",
            "- Nothing on the exploration half is a finding.",
        ]
    )


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
    joined, mismatch = join_objects(panel, objects)
    table, no_population = add_outcomes(joined, h)
    results = build_results(table, read_measure(measurement), h, no_population, mismatch)
    write_figure(table, h, args.out_dir)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
