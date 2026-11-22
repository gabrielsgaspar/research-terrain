"""Whose votes move with an allied mayor: party, deputies or state deputies (idea 0010, step s3).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), hypotheses H3 and H4 of idea 0011
(`research/ideas/0011-who-gains-from-pix.md`), decisions 0003, 0008 and 0011, campaign
`research/campaigns/0013-amendments-mechanisms/campaign.md`, step s3. The national exploration half
only: every panel is restricted to it right after it is read, before anything else.

The window is read from campaign 0011's gate record (`window.h_pct`, which must be 7.5); no window
is chosen here. The linear estimator is the one of `explore/0010_amendments_main.py`, loaded as is.
The panel is collapsed to one row per (cycle, town, party) for the party-level outcomes `d_party`,
`d_inc` and `d_state`; the deputy-level reduced form counts a deputy who did not run as 0. A
descriptive dose regression and a t0 placebo come with it. Its `results.json` carries
`placebo.t0_fail` and `estimates.finite`, the fields step s4's kill rules read. Nothing on the
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
from typing import Any

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
GRID = main0010.GRID
CHECK_WINDOW = main0010.CHECK_WINDOW
sign_draws = main0010.sign_draws
in_window = main0010.in_window
estimate = main0010.estimate
n_races = main0010.n_races
prepare = main0010.prepare
Sample = main0010.Sample
fe_fit = main0010.fe_fit
by_cycle_fit = main0010.by_cycle_fit
ri_b = gate.g9.ri_b
ri_summary = gate.g9.ri_summary
_check_draws = main0010._check_draws
_all_finite = main0010._all_finite
_clean = main0010._clean
_paths = main0010._paths

H_PCT = 7.5
Z95 = 1.96
SHARE_TOL = 1e-9
PLACEBO_RATIO = 0.10
PLACEBO_P = 0.05
BIN_WIDTH = 0.005
NOTE = "exploration half, not a finding"
READ_COLUMNS = [
    "cycle",
    "cd_ibge",
    "uf",
    "deputy",
    "deputy_party",
    "margin",
    "win",
    "population_m",
    "share_t0",
    "share_t1",
    "ran_t1",
    "d_share",
    "amend_post_log_pc",
    "party_share_t0",
    "party_share_t1",
    "state_party_share_t0",
    "state_party_share_t1",
]
PARTY_OUTCOMES = ("d_party", "d_inc", "d_state", "party_minus_inc", "party_minus_state")
SHARE_COLUMNS = ("party_share_t0", "party_share_t1", "state_party_share_t0", "state_party_share_t1")
SCOPES = (*CYCLES, "c_minus_a")
DECLARED = ("d_party", "party_minus_state")
READING = (
    "If `d_state` is about as large as `d_party`, the allied mayor lifts the whole ticket, which "
    "points to the mayor's campaigning. If `d_party` is near 0 while `d_inc` is positive, votes "
    "are reshuffled toward sitting deputies. Either way, compare with how the money moved across "
    "cycles (step s1)."
)


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """The three panels, each restricted to the exploration half right after it is read."""
    parts = []
    for cycle in CYCLES:
        frame = restrict(read(f"panel_{cycle}", READ_COLUMNS), half)
        parts.append(frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8)))
    return pl.concat(parts, how="vertical_relaxed")


def read_window(path: Path = WINDOW_RECORD) -> float:
    """h as a fraction, from the record's `window.h_pct`. Raises unless it is 7.5."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    h_pct = record["window"]["h_pct"]
    if h_pct is None or not math.isclose(float(h_pct), H_PCT, abs_tol=1e-9):
        raise GateError(f"window.h_pct in {Path(path).name} is {h_pct}, not {H_PCT}")
    return float(h_pct) / 100.0


# --- Tables

_NO_PRE = pl.lit(None, dtype=pl.Float64).alias("amend_pre_total")


def collapse(panel: pl.DataFrame) -> pl.DataFrame:
    """One row per (`cycle`, `cd_ibge`, `deputy_party`) with the party-level outcomes.

    Raises `GateError` if `margin`, `win` or `population_m` differ within a group, or a share
    differs by more than 1e-9 (or is null for some rows of a group only). `d_inc` sums the group's
    deputies' `share_t1` (0 for one who did not run) minus their `share_t0`.
    """
    keys = ["cycle", "cd_ibge", "deputy_party"]
    checks = panel.group_by(keys).agg(
        pl.len().alias("n"),
        *[pl.col(c).n_unique().alias(f"u_{c}") for c in ("margin", "win", "population_m")],
        *[(pl.col(c).max() - pl.col(c).min()).alias(f"s_{c}") for c in SHARE_COLUMNS],
        *[pl.col(c).null_count().alias(f"z_{c}") for c in SHARE_COLUMNS],
    )
    for c in ("margin", "win", "population_m"):
        if checks.filter(pl.col(f"u_{c}") > 1).height:
            raise GateError(f"{c} differs within a (cycle, town, party) group")
    for c in SHARE_COLUMNS:
        bad = checks.filter(
            (pl.col(f"s_{c}") > SHARE_TOL)
            | ((pl.col(f"z_{c}") > 0) & (pl.col(f"z_{c}") < pl.col("n")))
        )
        if bad.height:
            raise GateError(f"{c} differs within a (cycle, town, party) group")

    ran = pl.col("ran_t1").fill_null(False).cast(pl.Boolean)
    t1 = pl.when(ran).then(pl.col("share_t1").cast(pl.Float64).fill_null(0.0)).otherwise(0.0)
    t0 = pl.col("share_t0").cast(pl.Float64)
    grouped = (
        panel.group_by(keys)
        .agg(
            pl.col("uf").first(),
            pl.col("margin").first(),
            pl.col("win").first(),
            pl.col("population_m").first(),
            *[pl.col(c).cast(pl.Float64).first() for c in SHARE_COLUMNS],
            pl.when(t0.is_null().any()).then(None).otherwise(t1.sum() - t0.sum()).alias("d_inc"),
        )
        .sort(keys)
    )
    return grouped.with_columns(
        (pl.col("party_share_t1") - pl.col("party_share_t0")).alias("d_party"),
        (pl.col("state_party_share_t1") - pl.col("state_party_share_t0")).alias("d_state"),
        pl.concat_str(
            [pl.col("uf"), pl.col("deputy_party").cast(pl.Utf8), pl.col("cycle")], separator="|"
        ).alias("deputy"),
    ).with_columns(
        (pl.col("d_party") - pl.col("d_inc")).alias("party_minus_inc"),
        (pl.col("d_party") - pl.col("d_state")).alias("party_minus_state"),
    )


def party_table(panel: pl.DataFrame) -> pl.DataFrame:
    """The collapsed panel through `prepare` (`amend_pre_total` is added as null, never read)."""
    return prepare(collapse(panel).with_columns(_NO_PRE))


def deputy_table(panel: pl.DataFrame) -> pl.DataFrame:
    """Every panel row with `rf_zero` = (`share_t1` if `ran_t1` else 0) - `share_t0`."""
    ran = pl.col("ran_t1").fill_null(False).cast(pl.Boolean)
    rf = pl.when(ran).then(pl.col("share_t1").cast(pl.Float64)).otherwise(0.0) - pl.col(
        "share_t0"
    ).cast(pl.Float64)
    return prepare(panel.with_columns(rf.alias("rf_zero"), _NO_PRE))


def races_equal_t1_share(table: pl.DataFrame, w: float) -> int:
    """Races at window `w` with two rows whose `party_share_t1` is exactly equal."""
    sub = in_window(table, w).filter(pl.col("party_share_t1").is_not_null())
    per_race = sub.group_by("race").agg(
        pl.len().alias("n"), pl.col("party_share_t1").n_unique().alias("u")
    )
    return int(per_race.filter((pl.col("n") == 2) & (pl.col("u") == 1)).height)


# --- Estimates


def _usable(table: pl.DataFrame, w: float, column: str) -> pl.DataFrame:
    return in_window(table, w).filter(
        pl.col(column).is_not_null() & pl.col(column).cast(pl.Float64).is_finite()
    )


def fit(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    """`estimate` plus the 95% interval and the races on the fit's rows."""
    e = estimate(table, draws, w, column)
    sub = _usable(table, w, column)
    b, se = e["b"], e["se"]
    return {
        "b": b,
        "se": se,
        "ci_low": b - Z95 * se,
        "ci_high": b + Z95 * se,
        "ri_p": e["ri_p"],
        "mean": e["mean"],
        "n_units": e["units"],
        "n_races": n_races(sub) if sub.height else 0,
    }


def cycle_fits(table: pl.DataFrame, w: float, column: str) -> dict[str, Any]:
    """b, se and 95% interval by cycle and C minus A (no randomisation inference)."""
    raw = by_cycle_fit(table, w, column)
    out = {}
    for scope in SCOPES:
        b, se = raw[scope]["b"], raw[scope]["se"]
        out[scope] = {"b": b, "se": se, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se}
    return out


def outcome_block(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    return {"pooled": fit(table, draws, w, column), **cycle_fits(table, w, column)}


def dose(table: pl.DataFrame, w: float) -> dict[str, Any]:
    """Descriptive only: `d_share` on `amend_post_log_pc`, allied towns in the window, who ran.

    Fixed effects `deputy` and town x party x cycle, clustered by `cd_ibge`. Not causal: the
    money is not randomised.
    """
    import pyfixest as pf

    nan = float("nan")
    sub = (
        in_window(table, w)
        .filter(pl.col("win") & pl.col("ran_t1").fill_null(False).cast(pl.Boolean))
        .filter(
            pl.col("d_share").is_not_null()
            & pl.col("d_share").cast(pl.Float64).is_finite()
            & pl.col("amend_post_log_pc").is_not_null()
            & pl.col("amend_post_log_pc").cast(pl.Float64).is_finite()
        )
        .with_columns(
            pl.concat_str(
                [pl.col("cd_ibge"), pl.col("deputy_party").cast(pl.Utf8), pl.col("cycle")],
                separator="|",
            ).alias("tpc"),
            pl.col("d_share").cast(pl.Float64),
            pl.col("amend_post_log_pc").cast(pl.Float64),
        )
        .select("d_share", "amend_post_log_pc", "deputy", "tpc", "cd_ibge")
    )
    out: dict[str, Any] = {"b": nan, "se": nan, "n_obs": 0, "label": "descriptive"}
    if sub.height < 4:
        return out
    model = pf.feols(
        "d_share ~ amend_post_log_pc | deputy + tpc", data=sub, vcov={"CRV1": "cd_ibge"}
    )
    out["b"] = float(model.coef()["amend_post_log_pc"])
    out["se"] = float(model.se()["amend_post_log_pc"])
    out["n_obs"] = int(getattr(model, "_N", sub.height))
    return out


def holm(p_values: list[float]) -> list[float]:
    """Holm's step-down adjustment; all NaN if any input is not finite."""
    m = len(p_values)
    if not all(math.isfinite(p) for p in p_values):
        return [float("nan")] * m
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p_values[i])
        adjusted[i] = min(1.0, running)
    return adjusted


def placebo_block(party: pl.DataFrame, draws: np.ndarray, w: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fails = 0
    for key, column in (("party_t0", "party_share_t0"), ("state_t0", "state_party_share_t0")):
        e = estimate(party, draws, w, column)
        mean = e["mean"]
        ratio = abs(e["b"]) / mean if math.isfinite(mean) and mean > 0 else float("nan")
        out[key] = {"b": e["b"], "se": e["se"], "ri_p": e["ri_p"], "mean": mean, "ratio": ratio}
        if abs(e["b"]) > PLACEBO_RATIO * mean and e["ri_p"] < PLACEBO_P:
            fails = 1
    out["t0_fail"] = int(fails)
    return out


# --- Results


def build_results(
    panel: pl.DataFrame, h: float, draws: np.ndarray, source: str = WINDOW_SOURCE
) -> dict[str, Any]:
    """Everything the step reports, at window `h`; `draws` has one column per party-level race."""
    party = party_table(panel)
    dep = deputy_table(panel)
    _check_draws(party, draws)
    _check_draws(dep, draws)
    w5 = GRID[CHECK_WINDOW]

    inside = in_window(party, h)
    by_cycle_counts = {}
    for c in CYCLES:
        s = inside.filter(pl.col("cycle") == c)
        by_cycle_counts[c] = {"rows": int(s.height), "races": n_races(s) if s.height else 0}

    party_out = {o: outcome_block(party, draws, h, o) for o in PARTY_OUTCOMES}
    check = {
        o: {k: v for k, v in fit(party, draws, w5, o).items() if k in ("b", "se", "ri_p")}
        for o in PARTY_OUTCOMES
    }
    n_not_running = int(in_window(dep, h).filter(~pl.col("ran_t1").fill_null(False)).height)
    declared_p = [party_out[o]["pooled"]["ri_p"] for o in DECLARED]
    adjusted = holm(declared_p)

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "check_pct": round(w5 * 100, 6), "source": source},
        "counts": {
            "party_rows_h": int(inside.height),
            "races_h": n_races(inside) if inside.height else 0,
            "groups_h": int(inside["deputy"].n_unique()),
            "by_cycle": by_cycle_counts,
            "races_equal_t1_share": races_equal_t1_share(party, h),
        },
        "party": party_out,
        "check_5pct": check,
        "deputy": {
            "rf_zero": outcome_block(dep, draws, h, "rf_zero"),
            "n_not_running": n_not_running,
        },
        "descriptive": {"dose": dose(dep, h)},
        "placebo": placebo_block(party, draws, h),
        "declared": {
            o: {"p": p, "p_holm": a} for o, p, a in zip(DECLARED, declared_p, adjusted, strict=True)
        },
    }
    results["estimates"] = {"finite": _all_finite(results)}
    return _clean(results)


# --- Figures


def binned_means(party: pl.DataFrame, h: float) -> tuple[np.ndarray, np.ndarray]:
    """Mean `d_party` in bins 0.5 percentage points wide of the margin within +-h."""
    sub = in_window(party, h).filter(pl.col("d_party").is_not_null())
    n_bins = max(1, round(2 * h / BIN_WIDTH))
    margin = sub["margin"].cast(pl.Float64).to_numpy()
    y = sub["d_party"].cast(pl.Float64).to_numpy()
    index = np.clip(np.floor((margin + h) / BIN_WIDTH + 1e-9).astype(int), 0, n_bins - 1)
    centres, means = [], []
    for k in range(n_bins):
        take = index == k
        if take.any():
            centres.append(-h + (k + 0.5) * BIN_WIDTH)
            means.append(float(y[take].mean()))
    return np.array(centres), np.array(means)


def write_figures(results: dict[str, Any], party: pl.DataFrame, h: float, out_dir: Path) -> None:
    from terrain.style import configure, save_png

    plt = configure()
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    outcomes = ("d_party", "d_inc", "d_state")
    for j, o in enumerate(outcomes):
        xs, bs, lows, highs = [], [], [], []
        for i, c in enumerate(CYCLES):
            v = results["party"][o][c]
            if v["b"] is None or v["ci_low"] is None:
                continue
            xs.append(i + (j - 1) * 0.2)
            bs.append(v["b"])
            lows.append(v["b"] - v["ci_low"])
            highs.append(v["ci_high"] - v["b"])
        ax.errorbar(xs, bs, yerr=[lows, highs], fmt="o", capsize=3, label=o)
    ax.axhline(0.0, color="grey", linewidth=0.8)
    ax.set_xticks(range(len(CYCLES)), list(CYCLES))
    ax.set_xlabel("Cycle")
    ax.set_ylabel("Effect on vote share (b, 95% interval)")
    ax.legend(frameon=False)
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "effects_by_cycle.png")

    centres, means = binned_means(party, h)
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.plot(centres, means, "o")
    ax.axvline(0.0, color="grey", linewidth=0.8)
    ax.set_xlabel("Margin of the party's finalist")
    ax.set_ylabel("Mean d_party (bins of 0.5 points)")
    fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")
    save_png(fig, out_dir / "figures" / "binned_d_party.png")


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def summarize(results: dict[str, Any]) -> str:
    w, c, d = results["window"], results["counts"], results["declared"]
    lines = [
        f"Window h = {w['h_pct']:g}%, read from `{w['source']}` "
        f"(check window {w['check_pct']:g}%). "
        f"Party rows at h: {c['party_rows_h']} in {c['races_h']} races. "
        f"Races whose two finalist parties have equal t1 share: {c['races_equal_t1_share']}.",
        "",
        "## Declared estimates (Holm over two)",
        "",
        "| Estimate | RI p | Holm p |",
        "| --- | --- | --- |",
    ]
    for o in DECLARED:
        lines.append(f"| {o} pooled | {_fmt(d[o]['p'])} | {_fmt(d[o]['p_holm'])} |")
    lines += [
        "",
        "Everything else below is descriptive. Nothing on the exploration half is a finding.",
        "",
        "## Party level (pooled at h)",
        "",
        "| Outcome | b | SE | 95% interval | RI p | mean | units | races |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    def pooled(label: str, v: dict[str, Any]) -> str:
        return (
            f"| {label} | {_fmt(v['b'])} | {_fmt(v['se'])} | [{_fmt(v['ci_low'])}, "
            f"{_fmt(v['ci_high'])}] | {_fmt(v['ri_p'])} | {_fmt(v['mean'])} | {v['n_units']} "
            f"| {v['n_races']} |"
        )

    for o in PARTY_OUTCOMES:
        lines.append(pooled(o, results["party"][o]["pooled"]))
    lines += [
        "",
        "## Deputy level (non-runners count as 0)",
        "",
        "| Outcome | b | SE | 95% interval | RI p | mean | units | races |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        pooled("rf_zero", results["deputy"]["rf_zero"]["pooled"]),
        "",
        f"Rows at h whose deputy did not run at t1: {results['deputy']['n_not_running']}.",
        "",
        "## By cycle (b (SE); no randomisation inference)",
        "",
        "| Outcome | A | B | C | C minus A |",
        "| --- | --- | --- | --- | --- |",
    ]
    blocks = [(o, results["party"][o]) for o in PARTY_OUTCOMES]
    blocks.append(("rf_zero", results["deputy"]["rf_zero"]))
    for label, block in blocks:
        cells = [f"{_fmt(block[s]['b'])} ({_fmt(block[s]['se'])})" for s in SCOPES]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## At 5% (b, SE, RI p)",
        "",
        "| Outcome | b | SE | RI p |",
        "| --- | --- | --- | --- |",
    ]
    for o in PARTY_OUTCOMES:
        v = results["check_5pct"][o]
        lines.append(f"| {o} | {_fmt(v['b'])} | {_fmt(v['se'])} | {_fmt(v['ri_p'])} |")
    p = results["placebo"]
    lines += [
        "",
        "## Placebo at t0 (t0_fail = " + str(p["t0_fail"]) + ")",
        "",
        "| Outcome | b | SE | RI p | mean | abs b / mean |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in ("party_t0", "state_t0"):
        v = p[key]
        lines.append(
            f"| {key} | {_fmt(v['b'])} | {_fmt(v['se'])} | {_fmt(v['ri_p'])} "
            f"| {_fmt(v['mean'])} | {_fmt(v['ratio'])} |"
        )
    z = results["descriptive"]["dose"]
    lines += [
        "",
        "## Dose (descriptive, not causal: the money is not randomised)",
        "",
        "| b | SE | rows used | label |",
        "| --- | --- | --- | --- |",
        f"| {_fmt(z['b'])} | {_fmt(z['se'])} | {z['n_obs']} | {z['label']} |",
        "",
        "## Reading, declared before the run",
        "",
        READING,
        "",
        "## Caveats",
        "",
        "- The same exploration half and window campaign 0011 analysed, so this is a further look "
        "at the same data.",
        "- The hypotheses were declared in idea 0011's file on 2026-11-20, after campaign 0011's "
        "results.",
        "- t1 party shares follow mergers and federations, so two finalist parties can be one "
        "party at t1 (`counts.races_equal_t1_share`).",
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

        def read(name: str, columns: list[str]) -> pl.DataFrame:
            remote = _paths("amendments_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = pl.read_parquet(local, columns=columns)
            local.unlink()
            return frame

        panel = load_panels(read, half)
    party = party_table(panel)
    draws = sign_draws(n_races(party))
    results = build_results(panel, h, draws)
    write_figures(results, party, h, args.out_dir)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
