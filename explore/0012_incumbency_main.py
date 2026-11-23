"""The incumbency curse, main run: H1, S1-S5, robustness and five figures (idea 0012, s3).

Idea 0012 (`research/ideas/0012-incumbency-curse.md`), decisions 0017, 0003 and 0011, campaign
`research/campaigns/0014-incumbency-curse/campaign.md`, step s3; step s4 runs it through
`explore-run`. The design is fixed by the gate (`0012_incumbency_gate.py`, loaded, not copied):
triangular kernel, h = 0.135, standard errors clustered by municipality, 2,000 race re-flips
(seed 20261122). The gate's `load_panel`, `prepare`, `sign_draws`, `fit`, `ri_draws` and `ri_p`
are used unchanged. The national exploration half only: every panel file is restricted to it
right after it is read. Reads `mayor_incumbency_panel` only (never `sealed/`).

Estimates (nothing else is computed, referee R7): H1 (Y = `party_wins_next`, pre = 2008-2016,
post = 2020), S1 (each election, and 2004-2012 pooled), S2 (finalist wins, eligible rows), S3
(party and finalist run again), S4 (connected parties), S5 (town money), six robustness fits
and the number of 2020 rows whose party became a 2024 federation. Nothing on the exploration
half is a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
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

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("incumbency_curse_gate_s3", "0012_incumbency_gate.py")

H = gate.H
KERNEL = gate.KERNEL
SEED = gate.SEED
DRAWS = gate.DRAWS
ELECTIONS = gate.ELECTIONS
PRE = gate.PRE
POST = gate.POST
OUTCOMES = (
    "party_wins_next",
    "party_runs_next",
    "finalist_wins_next",
    "finalist_runs_next",
    "party_next",
)
MAIN_COLUMNS = [
    *gate.READ_COLUMNS,
    *OUTCOMES,
    "amend_after_total",
    "amend_after_pix",
    "population_e",
]
NOTE = "exploration half, not a finding"
KT_LABEL = "Klašnja and Titiunik (2017)"
KT_VALUE = -0.15
Z = 1.96
FIGURES = (
    "binned_party_wins.png",
    "effect_by_election.png",
    "personal_by_election.png",
    "connected_by_election.png",
    "town_money_by_election.png",
)
# label, kernel, bandwidth: the five kernel fits of the robustness list
ROBUSTNESS = (
    ("uniform_5pct", "uniform", 0.05),
    ("uniform_7_5pct", "uniform", 0.075),
    ("uniform_10pct", "uniform", 0.10),
    ("triangular_10pct", "triangular", 0.10),
    ("triangular_20pct", "triangular", 0.20),
)
CONTROLS = ("fin_female", "fin_age", "fin_higher_ed")
S4_ELECTIONS = (2012, 2016, 2020)
S4_GROUPS = ("pre_unconnected", "post_unconnected", "pre_connected", "post_connected")
S4_WEIGHTS = (1.0, -1.0, -1.0, 1.0)  # (post,conn - pre,conn) - (post,unconn - pre,unconn)
CELL_STATES = ("unconnected", "connected")


# --- Reading


def load(read: Any, half: frozenset[str]) -> pl.DataFrame:
    """The five panels with the main run's columns, each restricted to the exploration half."""
    return gate.load_panel(read, half, MAIN_COLUMNS)


# --- One estimate


def _normal_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0)) if math.isfinite(z) else float("nan")


def _num(x: Any) -> float:
    return float(x)


def estimate(
    table: pl.DataFrame,
    y: str,
    groups: Sequence[Sequence[Any]],
    weights: Sequence[float],
    cell: str = "election",
    draws: np.ndarray | None = None,
    h: float = H,
    kernel: str = KERNEL,
) -> dict[str, Any]:
    """`weights` . b from one fit: b, se, 95% interval, clustered p (normal), RI p (if `draws`).

    For a difference the weights are (-1, 1) and se = sqrt(w' cov w) from the one fit.
    Also the group b's (`bs`) and the row counts.
    """
    result = gate.fit(table, y, h, groups, kernel, cell)
    w = np.asarray(weights, dtype=float)
    bs = [float(v) for v in result["b"]]
    b = float(w @ result["b"])
    var = float(w @ result["cov"] @ w)
    se = math.sqrt(var) if math.isfinite(var) and var >= 0 else float("nan")
    out: dict[str, Any] = {
        "b": b,
        "se": se,
        "ci_low": b - Z * se,
        "ci_high": b + Z * se,
        "p_cluster": _normal_p(b / se) if se > 0 else float("nan"),
        "bs": bs,
        "n_units": int(result["n_units"]),
        "n_races": int(result["n_races"]),
        "n_null_y": int(result["n_null_y"]),
    }
    if draws is not None:
        out["ri_p"] = gate.ri_p(b, gate.ri_draws(table, y, h, groups, draws, weights, kernel, cell))
    return out


def _fields(est: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {k: est[k] for k in keys}


INTERVAL = ("b", "se", "ci_low", "ci_high")
DIFF_FIELDS = (*INTERVAL, "p_cluster", "ri_p", "n_units", "n_races", "n_null_y")


def mean_y(table: pl.DataFrame, y: str, election: int, h: float = H) -> float:
    """Mean of `y` over the rows of `election` inside the triangular kernel with a non-null y."""
    rows = table.filter(pl.col("election") == election)
    rows = rows.filter(pl.Series(gate.kernel_weights(gate._col(rows, "margin"), h, KERNEL) > 0))
    values = gate._col(rows, y)
    values = values[np.isfinite(values)]
    return float(values.mean()) if values.size else float("nan")


def by_election(table: pl.DataFrame, y: str, draws: np.ndarray) -> dict[str, Any]:
    """Each election 2004-2020 as its own group."""
    out = {}
    for e in ELECTIONS:
        est = estimate(table, y, [[e]], (1.0,), draws=draws)
        out[f"e{e}"] = {
            **_fields(est, (*INTERVAL, "ri_p")),
            "mean_y": mean_y(table, y, e),
            **_fields(est, ("n_units", "n_races", "n_null_y")),
        }
    return out


def h1_difference(table: pl.DataFrame, y: str, draws: np.ndarray) -> dict[str, Any]:
    """b_post - b_pre for `y` (pre 2008-2016, post 2020), with b_pre and b_post."""
    est = estimate(table, y, [list(PRE), list(POST)], (-1.0, 1.0), draws=draws)
    return {"b_pre": est["bs"][0], "b_post": est["bs"][1], **_fields(est, DIFF_FIELDS)}


def eligible_rows(table: pl.DataFrame) -> pl.DataFrame:
    """The rows whose finalist could run again (`finalist_eligible` true)."""
    return table.filter(pl.col("finalist_eligible").fill_null(False))


def _diff_and_elections(table: pl.DataFrame, y: str, draws: np.ndarray) -> dict[str, Any]:
    d = h1_difference(table, y, draws)
    return {"diff": _fields(d, DIFF_FIELDS), "by_election": by_election(table, y, draws)}


# --- S4: connected parties


def connected_table(table: pl.DataFrame) -> pl.DataFrame:
    """2012, 2016 and 2020 rows with `cell` = "<election>_<0|1>", 1 where `bench_fed` > 0.

    A row with a null `bench_fed` has a null cell, so it leaves the fit.
    """
    rows = table.filter(pl.col("election").is_in(list(S4_ELECTIONS)))
    connected = (pl.col("bench_fed") > 0).cast(pl.Int8).cast(pl.Utf8)
    return rows.with_columns(
        pl.when(pl.col("bench_fed").is_null())
        .then(None)
        .otherwise(pl.col("election").cast(pl.Utf8) + "_" + connected)
        .alias("cell")
    )


def s4_estimates(table: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    rows = connected_table(table)
    pre, post = (2012, 2016), (2020,)
    groups = [
        [f"{e}_0" for e in pre],
        [f"{e}_0" for e in post],
        [f"{e}_1" for e in pre],
        [f"{e}_1" for e in post],
    ]
    est = estimate(rows, "party_wins_next", groups, S4_WEIGHTS, cell="cell", draws=draws)
    cells: dict[str, Any] = {}
    for e in S4_ELECTIONS:
        cells[f"e{e}"] = {}
        for flag, state in enumerate(CELL_STATES):
            one = estimate(rows, "party_wins_next", [[f"{e}_{flag}"]], (1.0,), cell="cell")
            cells[f"e{e}"][state] = {**_fields(one, INTERVAL), "n_units": one["n_units"]}
    return {
        "diff": _fields(est, (*INTERVAL, "p_cluster", "ri_p")),
        "b": dict(zip(S4_GROUPS, est["bs"], strict=True)),
        "cells": cells,
        "n_units": est["n_units"],
        "n_races": est["n_races"],
    }


# --- S5: town money


def s5_table(table: pl.DataFrame, h: float = H) -> tuple[pl.DataFrame, int]:
    """One row per race of 2016 and 2020: the row of the better-connected party.

    Races inside the kernel whose two `bench_fed` are null or equal (or that lack two rows) are
    dropped and counted. Adds `y_total` and `y_pix` = ln(1 + money / population), null where the
    money or the population is null or the population is not above 0.
    """
    rows = table.filter(pl.col("election").is_in([2016, 2020]))
    rows = rows.filter(pl.Series(gate.kernel_weights(gate._col(rows, "margin"), h, KERNEL) > 0))
    races = rows["race"].n_unique() if rows.height else 0
    top = pl.col("bench_fed").max().over("race")
    low = pl.col("bench_fed").min().over("race")
    usable = (
        (pl.len().over("race") == 2)
        & (pl.col("bench_fed").null_count().over("race") == 0)
        & (top > low)
    )
    kept = rows.filter(usable & (pl.col("bench_fed") == top))
    dropped = int(races - (kept["race"].n_unique() if kept.height else 0))
    population = pl.col("population_e").cast(pl.Float64)
    valid = population.is_not_null() & (population > 0)

    def ratio(column: str) -> pl.Expr:
        return (
            pl.when(valid & pl.col(column).is_not_null())
            .then((1.0 + pl.col(column).cast(pl.Float64) / population).log())
            .otherwise(None)
        )

    return (
        kept.with_columns(
            ratio("amend_after_total").alias("y_total"),
            ratio("amend_after_pix").alias("y_pix"),
        ),
        dropped,
    )


def s5_estimates(table: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    rows, dropped = s5_table(table)
    keys = (*INTERVAL, "ri_p", "n_units")
    one = {
        "e2016_total": estimate(rows, "y_total", [[2016]], (1.0,), draws=draws),
        "e2020_total": estimate(rows, "y_total", [[2020]], (1.0,), draws=draws),
        "e2020_pix": estimate(rows, "y_pix", [[2020]], (1.0,), draws=draws),
    }
    diff = estimate(rows, "y_total", [[2016], [2020]], (-1.0, 1.0), draws=draws)
    out: dict[str, Any] = {name: _fields(est, keys) for name, est in one.items()}
    out["diff_total"] = _fields(diff, keys)
    out["n_races_dropped_bench"] = dropped
    out["n_null_y"] = diff["n_null_y"]
    out["n_null_y_pix"] = one["e2020_pix"]["n_null_y"]
    return out


# --- Robustness


def _controls_sample(table: pl.DataFrame, h: float) -> tuple[pl.DataFrame, int]:
    """H1 rows inside the triangular kernel with a Y; those with a null control are counted."""
    rows = table.filter(pl.col("election").is_in(list(PRE + POST)))
    rows = rows.filter(pl.Series(gate.kernel_weights(gate._col(rows, "margin"), h, KERNEL) > 0))
    rows = rows.filter(pl.col("party_wins_next").cast(pl.Float64).is_finite().fill_null(False))
    complete = pl.all_horizontal(
        *[pl.col(c).cast(pl.Float64).is_finite().fill_null(False) for c in CONTROLS]
    )
    n_null = int(rows.filter(~complete).height)
    return rows.filter(complete), n_null


def controls_fe(table: pl.DataFrame, h: float = H) -> dict[str, Any]:
    """The H1 difference with the three controls and `uf` x election dummies (CR1 by `cd_ibge`).

    Weighted least squares with the triangular weights. Per election: a slope in margin and in
    win x margin; the `uf` x election dummies replace the per-election intercepts; one `win`
    coefficient for pre and one for post. The standard error is clustered like the gate's `fit`:
    G/(G-1) x (N-1)/(N-K).
    """
    rows, n_null = _controls_sample(table, h)
    out: dict[str, Any] = {
        "b": float("nan"),
        "se": float("nan"),
        "ci_low": float("nan"),
        "ci_high": float("nan"),
        "p_cluster": float("nan"),
        "n_units": int(rows.height),
        "n_races": int(rows["race"].n_unique()) if rows.height else 0,
        "n_null_controls": n_null,
    }
    if rows.height == 0:
        return out
    margin = gate._col(rows, "margin")
    weight = gate.kernel_weights(margin, h, KERNEL)
    election = rows["election"].to_numpy()
    win = (margin > 0).astype(float)
    y = gate._col(rows, "party_wins_next")
    cols = []
    for e in PRE + POST:
        mask = (election == e).astype(float)
        cols += [mask * margin, mask * win * margin]
    keys = np.array([f"{u}_{e}" for u, e in zip(rows["uf"].to_list(), election, strict=True)])
    levels, index = np.unique(keys, return_inverse=True)
    dummies = np.zeros((rows.height, levels.size))
    dummies[np.arange(rows.height), index] = 1.0
    cols += [gate._col(rows, c) for c in CONTROLS]
    cols += [win * np.isin(election, list(PRE)), win * np.isin(election, list(POST))]
    x = np.column_stack([dummies, *cols])
    n, k = x.shape
    cluster = np.unique(rows["cd_ibge"].to_numpy(), return_inverse=True)[1]
    g = int(cluster.max() + 1)
    gram = x.T @ (x * weight[:, None])
    if n <= k or g < 2 or np.linalg.matrix_rank(gram) < k:
        return out
    beta = np.linalg.solve(gram, x.T @ (weight * y))
    scores = x * (weight * (y - x @ beta))[:, None]
    sums = np.column_stack([np.bincount(cluster, weights=scores[:, i]) for i in range(k)])
    bread = np.linalg.inv(gram)
    factor = g / (g - 1) * (n - 1) / (n - k)
    cov = factor * (bread @ (sums.T @ sums) @ bread)
    w = np.zeros(k)
    w[-2], w[-1] = -1.0, 1.0
    b = float(w @ beta)
    var = float(w @ cov @ w)
    se = math.sqrt(var) if var >= 0 else float("nan")
    out.update(
        b=b,
        se=se,
        ci_low=b - Z * se,
        ci_high=b + Z * se,
        p_cluster=_normal_p(b / se) if se > 0 else float("nan"),
    )
    return out


def robustness(table: pl.DataFrame) -> dict[str, Any]:
    keys = (*INTERVAL, "p_cluster", "n_units", "n_races")
    out: dict[str, Any] = {}
    for label, kernel, h in ROBUSTNESS:
        est = estimate(
            table, "party_wins_next", [list(PRE), list(POST)], (-1.0, 1.0), h=h, kernel=kernel
        )
        out[label] = _fields(est, keys)
    out["controls_fe"] = _fields(controls_fe(table), (*keys, "n_null_controls"))
    return out


def federation_rows_2020(table: pl.DataFrame, h: float = H) -> int:
    """2020 rows inside the kernel whose `party_next` starts with "F" (a 2024 federation)."""
    rows = table.filter(pl.col("election") == 2020)
    rows = rows.filter(pl.Series(gate.kernel_weights(gate._col(rows, "margin"), h, KERNEL) > 0))
    return int(rows.filter(pl.col("party_next").cast(pl.Utf8).str.starts_with("F")).height)


# --- Results


def build_results(panel: pl.DataFrame, draws: np.ndarray) -> tuple[pl.DataFrame, dict[str, Any]]:
    """The prepared table and every estimate. `estimates.finite` is true if all are finite."""
    table = gate.prepare(panel)
    gate._check_draws(table, draws)
    h1 = h1_difference(table, "party_wins_next", draws)
    eligible = eligible_rows(table)
    results: dict[str, Any] = {
        "design": {"h": H, "kernel": KERNEL, "seed": SEED, "draws": int(draws.shape[0])},
        "h1": {
            "b_pre": h1["b_pre"],
            "b_post": h1["b_post"],
            "diff": _fields(h1, (*INTERVAL, "p_cluster", "ri_p")),
            **_fields(h1, ("n_units", "n_races", "n_null_y")),
        },
        "s1": {"by_election": by_election(table, "party_wins_next", draws)},
        "s2": _diff_and_elections(eligible, "finalist_wins_next", draws),
        "s3": {
            "party_runs": _diff_and_elections(table, "party_runs_next", draws),
            "finalist_runs": _diff_and_elections(eligible, "finalist_runs_next", draws),
        },
        "s4": s4_estimates(table, draws),
        "s5": s5_estimates(table, draws),
        "robustness": robustness(table),
        "counts": {"federation_rows_2020": federation_rows_2020(table)},
    }
    pooled = estimate(table, "party_wins_next", [[2004, 2008, 2012]], (1.0,), draws=draws)
    results["s1"]["pooled_2004_2012"] = _fields(pooled, (*INTERVAL, "ri_p", "n_units", "n_races"))
    finite = gate._all_finite(results)
    results["estimates"] = {"finite": finite}
    return table, gate._clean(results)


# --- Figures


def _note(fig: Any) -> None:
    fig.text(0.99, 0.005, NOTE, ha="right", va="bottom", fontsize=7, style="italic")


def binned_means(table: pl.DataFrame, election: int, h: float = H) -> tuple[np.ndarray, np.ndarray]:
    """Centres of the bins h/10 wide inside +-h, and the mean `party_wins_next` of each bin."""
    rows = table.filter(pl.col("election") == election)
    margin = gate._col(rows, "margin")
    y = gate._col(rows, "party_wins_next")
    keep = np.isfinite(y) & (np.abs(margin) < h)
    edges = np.linspace(-h, h, 21)
    which = np.clip(np.digitize(margin[keep], edges) - 1, 0, 19)
    centres, means = [], []
    for i in range(20):
        sel = which == i
        if sel.any():
            centres.append(float((edges[i] + edges[i + 1]) / 2))
            means.append(float(y[keep][sel].mean()))
    return np.array(centres), np.array(means)


def _figure_binned(table: pl.DataFrame, path: Path) -> Path:
    from terrain import style

    plt = style.configure()
    fig, axes = plt.subplots(1, 4, figsize=(style.WIDE[0], 2.6), sharey=True)
    for ax, e in zip(axes, gate.CYCLE_ELECTIONS, strict=True):
        x, m = binned_means(table, e)
        ax.plot(x, m, "o", markersize=3, color=style.TEXT)
        ax.axvline(0, color="grey", linewidth=0.7)
        ax.set_title(str(e))
        ax.set_xlabel("margin")
    axes[0].set_ylabel("mean party_wins_next")
    _note(fig)
    return style.save_png(fig, path)


def _figure_intervals(
    path: Path,
    labels: Sequence[str],
    series: dict[str, list[tuple[Any, Any, Any]]],
    ylabel: str,
    reference: bool = False,
) -> Path:
    """Estimates with 95% intervals; `series` maps a name to (b, low, high) per label."""
    from terrain import style

    plt = style.configure()
    fig, ax = plt.subplots(figsize=style.WIDE)
    names = list(series)
    for j, name in enumerate(names):
        offset = (j - (len(names) - 1) / 2) * 0.18
        points = [(i + offset, *vals) for i, vals in enumerate(series[name])]
        points = [p for p in points if all(v is not None and math.isfinite(v) for v in p)]
        if not points:
            continue
        xs, bs, lo, hi = (np.array(col, dtype=float) for col in zip(*points, strict=True))
        ax.errorbar(
            xs,
            bs,
            yerr=[bs - lo, hi - bs],
            fmt="o",
            markersize=4,
            capsize=2,
            label=name if len(names) > 1 else None,
        )
    ax.axhline(0, color="grey", linewidth=0.7)
    if reference:
        ax.axhline(KT_VALUE, color="grey", linewidth=0.9, linestyle="--")
        ax.text(len(labels) - 0.5, KT_VALUE, KT_LABEL, ha="right", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)), list(labels))
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ax.set_ylabel(ylabel)
    if len(names) > 1:
        ax.legend(frameon=False)
    _note(fig)
    return style.save_png(fig, path)


def _triples(block: dict[str, Any], keys: Sequence[str]) -> list[tuple[Any, Any, Any]]:
    return [(block[k]["b"], block[k]["ci_low"], block[k]["ci_high"]) for k in keys]


def write_figures(table: pl.DataFrame, results: dict[str, Any], out_dir: Path) -> int:
    """The five PNGs in `out_dir/figures/`; returns how many were written."""
    folder = out_dir / "figures"
    years = [str(e) for e in ELECTIONS]
    keys = [f"e{e}" for e in ELECTIONS]
    _figure_binned(table, folder / FIGURES[0])
    _figure_intervals(
        folder / FIGURES[1],
        years,
        {"S1": _triples(results["s1"]["by_election"], keys)},
        "jump in party_wins_next (b)",
        reference=True,
    )
    _figure_intervals(
        folder / FIGURES[2],
        years,
        {"S2": _triples(results["s2"]["by_election"], keys)},
        "jump in finalist_wins_next (b)",
        reference=True,
    )
    cells = results["s4"]["cells"]
    _figure_intervals(
        folder / FIGURES[3],
        [str(e) for e in S4_ELECTIONS],
        {
            state: _triples({k: cells[k][state] for k in cells}, list(cells))
            for state in CELL_STATES[::-1]
        },
        "jump in party_wins_next (b)",
    )
    s5 = results["s5"]
    names = ["e2016_total", "e2020_total", "e2020_pix"]
    _figure_intervals(
        folder / FIGURES[4],
        ["2016 total", "2020 total", "2020 Pix"],
        {"S5": _triples(s5, names)},
        "jump in ln(1 + money per head) (b)",
    )
    return sum((folder / name).exists() for name in FIGURES)


# --- Summary


def _f(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _row(name: str, v: dict[str, Any], extra: Sequence[str] = ()) -> str:
    cells = [name, _f(v["b"]), _f(v["se"]), f"[{_f(v['ci_low'])}, {_f(v['ci_high'])}]"]
    cells += [_f(v.get(k)) if k in v else "" for k in extra]
    return "| " + " | ".join(cells) + " |"


def _election_table(title: str, block: dict[str, Any]) -> list[str]:
    lines = [
        title,
        "",
        "| Election | b | SE | 95% interval | RI p | mean Y | rows | races | null-Y rows |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, v in block["by_election"].items():
        lines.append(
            f"{_row(key[1:], v, ('ri_p', 'mean_y'))[:-2]} | {v['n_units']} | {v['n_races']} "
            f"| {v['n_null_y']} |"
        )
    d = block["diff"]
    lines += [
        "",
        f"Difference (2020 minus 2008-2016): b {_f(d['b'])}, SE {_f(d['se'])}, interval "
        f"[{_f(d['ci_low'])}, {_f(d['ci_high'])}], clustered p {_f(d['p_cluster'])}, RI p "
        f"{_f(d['ri_p'])}; {d['n_units']} rows, {d['n_races']} races, {d['n_null_y']} null-Y rows.",
        "",
    ]
    return lines


def summarize(results: dict[str, Any]) -> str:
    d, h1 = results["design"], results["h1"]
    diff = h1["diff"]
    lines = [
        f"Design: h = {d['h']}, {d['kernel']} kernel, seed {d['seed']}, {d['draws']} re-flips "
        "(idea 0012, decision 0017), fixed by `0012_incumbency_gate.py` before any data was "
        "read. Standard errors are clustered by municipality. All numbers finite: "
        f"{results['estimates']['finite']}.",
        "",
        "## H1 (primary, alpha 0.05)",
        "",
        "Y = party_wins_next, all rows. Pre = 2008, 2012, 2016; post = 2020.",
        "",
        "| b_pre | b_post | difference | SE | 95% interval | clustered p | RI p |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        f"| {_f(h1['b_pre'])} | {_f(h1['b_post'])} | {_f(diff['b'])} | {_f(diff['se'])} "
        f"| [{_f(diff['ci_low'])}, {_f(diff['ci_high'])}] | {_f(diff['p_cluster'])} "
        f"| {_f(diff['ri_p'])} |",
        "",
        f"{h1['n_units']} rows, {h1['n_races']} races, {h1['n_null_y']} null-Y rows.",
        "",
        "Rule: H1 holds on this half if the difference is positive and its RI p is below 0.05.",
        "",
        "## S1: each election",
        "",
        "| Election | b | SE | 95% interval | RI p | mean Y | rows | races | null-Y rows |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, v in results["s1"]["by_election"].items():
        lines.append(
            f"{_row(key[1:], v, ('ri_p', 'mean_y'))[:-2]} | {v['n_units']} | {v['n_races']} "
            f"| {v['n_null_y']} |"
        )
    p = results["s1"]["pooled_2004_2012"]
    lines += [
        "",
        f"2004-2012 pooled (replication of {KT_LABEL}, -0.15): b {_f(p['b'])}, SE {_f(p['se'])}, "
        f"interval [{_f(p['ci_low'])}, {_f(p['ci_high'])}], RI p {_f(p['ri_p'])}; "
        f"{p['n_units']} rows, {p['n_races']} races.",
        "",
    ]
    lines += _election_table(
        "## S2: the personal effect (finalist wins, eligible rows)",
        {
            "by_election": results["s2"]["by_election"],
            "diff": results["s2"]["diff"],
        },
    )
    lines += _election_table("## S3: party runs again", results["s3"]["party_runs"])
    lines += _election_table(
        "## S3: finalist runs again (eligible rows)", results["s3"]["finalist_runs"]
    )
    s4 = results["s4"]
    lines += [
        "## S4: connected parties (2012, 2016, 2020)",
        "",
        "Connected = the party elected a federal deputy in the state (`bench_fed` > 0).",
        "",
        "| Group | b |",
        "| --- | --- |",
    ]
    lines += [f"| {name} | {_f(v)} |" for name, v in s4["b"].items()]
    sd = s4["diff"]
    lines += [
        "",
        f"S4 (post - pre, connected minus unconnected): b {_f(sd['b'])}, SE {_f(sd['se'])}, "
        f"interval [{_f(sd['ci_low'])}, {_f(sd['ci_high'])}], clustered p {_f(sd['p_cluster'])}, "
        f"RI p {_f(sd['ri_p'])}; {s4['n_units']} rows, {s4['n_races']} races.",
        "",
        "| Election | state | b | SE | 95% interval | rows |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key, states in s4["cells"].items():
        for state, v in states.items():
            lines.append(f"{_row(f'{key[1:]} | {state}', v)[:-2]} | {v['n_units']} |")
    s5 = results["s5"]
    lines += [
        "",
        "## S5: town money (one row per race, the better-connected party's)",
        "",
        "| Estimate | b | SE | 95% interval | RI p | rows |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in ("e2016_total", "e2020_total", "e2020_pix", "diff_total"):
        v = s5[key]
        lines.append(f"{_row(key, v, ('ri_p',))[:-2]} | {v['n_units']} |")
    lines += [
        "",
        f"Races dropped for equal or null `bench_fed` (inside h): {s5['n_races_dropped_bench']}. "
        f"Rows with a null Y (money or population missing, population 0): {s5['n_null_y']} "
        f"(total), {s5['n_null_y_pix']} (Pix).",
        "",
        "## Robustness (H1 difference; no randomisation p)",
        "",
        "| Fit | b | SE | 95% interval | clustered p | rows | races |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, v in results["robustness"].items():
        lines.append(f"{_row(label, v, ('p_cluster',))[:-2]} | {v['n_units']} | {v['n_races']} |")
    lines += [
        "",
        f"`controls_fe` leaves out {results['robustness']['controls_fe']['n_null_controls']} "
        "rows with a null control.",
        "",
        "## Federations",
        "",
        f"2020 rows inside h whose party became a 2024 federation: "
        f"{results['counts']['federation_rows_2020']}.",
        "",
        "## Figures",
        "",
    ]
    lines += [f"- [{name}](figures/{name})" for name in FIGURES]
    lines += [
        "",
        "## Caveats",
        "",
        "- The idea was formed after campaign 0012's gate and reuses idea 0011's data and this "
        "exploration half.",
        "- The 2020 election was held in the pandemic; company donations were banned from 2016 "
        "and the public campaign fund began in 2018; coalitions in council elections ended in "
        "2020. A change over time is not by itself the effect of Pix, and S4 and S5 are weak "
        "links.",
        "- `bench_fed` is predetermined, not randomised.",
        "- 2024 federations count as one party.",
        "- Nothing on the exploration half is a finding.",
    ]
    return "\n".join(lines)


def run(panel: pl.DataFrame, draws: np.ndarray, out_dir: Path) -> tuple[str, dict[str, Any]]:
    """Estimates, the five figures in `out_dir/figures/`, and the summary text."""
    table, results = build_results(panel, draws)
    results["figures"] = {"count": write_figures(table, results, out_dir)}
    return summarize(results), results


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def read(name: str, columns: list[str]) -> pl.DataFrame:
            remote = gate._paths("mayor_incumbency_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = restrict(pl.read_parquet(local, columns=columns), half)
            local.unlink()
            return frame

        panel = load(read, half)
    draws = gate.sign_draws(gate.n_races(panel))
    summary, results = run(panel, draws, args.out_dir)
    write_results(args.out_dir, summary, results)


if __name__ == "__main__":
    main()
