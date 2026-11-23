"""The instrument by payment type, in levels and in percent, with checks for sorting (idea 0010).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), decisions 0003, 0008, 0011 and
0001, campaign `research/campaigns/0013-amendments-mechanisms/campaign.md`, step s1. The national
exploration half only: every panel is restricted to it right after it is read, before anything
else.

It asks three things about the first stage (a deputy's party narrowly wins a mayoralty, and the
deputy sends more amendment money there): is the growth by cycle more favouritism or just more
money (a Poisson premium in percent), does it run through Pix, and does it survive controls for
sorting. The window is read from campaign 0011's gate record (h = 7.5%, 5% as a check). The linear
estimator is the one of `explore/0010_amendments_main.py`, loaded as is; the Poisson fits use
`terrain.poisson.fepois` (AGENTS.md). It reads `amendments_panel` (`panel_A`, `panel_B`, `panel_C`)
only. Its `results.json` carries `first_stage.f_cluster`, `placebo.pre_fail` and
`estimates.finite`, the fields step s2's kill rules read. Nothing on the exploration half is a
finding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.poisson import fepois
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
WINDOW_SOURCE = "research/explore-runs/0010/44484340952.json"
WINDOW_RECORD = REPO / "research" / "explore-runs" / "0010" / "44484340952.json"


def _load(name: str, file: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


main0010 = _load("main0010", "0010_amendments_main.py")

GateError = main0010.GateError
GRID = main0010.GRID
prepare = main0010.prepare
sign_draws = main0010.sign_draws
n_races = main0010.n_races
in_window = main0010.in_window
estimate = main0010.estimate
full_fit = main0010.full_fit
by_cycle_fit = main0010.by_cycle_fit
_check_draws = main0010._check_draws
_all_finite = main0010._all_finite
_clean = main0010._clean
_paths = main0010._paths
_col = main0010._col
_solve = main0010._solve
# the 0010 gate does not re-export these: they come from 0009's gate, through `gate.g9`
Sample = main0010.gate.g9.Sample
fe_fit = main0010.gate.g9.fe_fit
ri_b = main0010.gate.g9.ri_b
ri_summary = main0010.gate.g9.ri_summary

H_PCT = 7.5
CHECK_PCT = 5.0
Z95 = 1.96
NOTE = "exploration half, not a finding"
ALL_CYCLES = ("A", "B", "C")
PIX_CYCLES = ("B", "C")  # Pix exists from 2020
CHUNK = 64
BIN_WIDTH = 0.005  # 0.5 percentage points of the margin
DONUT = 0.005
PANEL_COLUMNS = [
    "cycle",
    "cd_ibge",
    "deputy",
    "margin",
    "win",
    "population_m",
    "party_held_mayor",
    "fin_female",
    "fin_age",
    "fin_higher_ed",
    "n_mayor_cands",
    "amend_pre_total",
    "amend_pre_log_pc",
    "amend_post_total",
    "amend_post_pix",
    "amend_post_log_pc",
]
INSTRUMENTS = ("total", "pix", "nonpix")
# cycles of each instrument, and the (earlier, later) pair of its difference between cycles
INST_CYCLES = {"total": ALL_CYCLES, "pix": PIX_CYCLES, "nonpix": ALL_CYCLES}
INST_DIFF = {"total": ("A", "C"), "pix": ("B", "C"), "nonpix": ("A", "C")}
# controls of the sorting check; `party_held_mayor` is first
CONTROLS = [
    "c_held",
    "c_pre",
    "c_female",
    "c_age",
    "c_higher",
    "c_cands",
    "ln_population",
]
SORTING_WINDOWS = {
    "w2_5pct": 0.025,
    "w5pct": GRID["w5pct"],
    "w7_5pct": GRID["w7_5pct"],
    "w10pct": GRID["w10pct"],
}
LINEAR_KEYS = ("b", "se", "ci_low", "ci_high", "ri_p", "mean", "n_units", "n_races")
SORT_KEYS = ("b", "se", "ci_low", "ci_high", "ri_p", "f_cluster", "n_units", "n_races", "n_dropped")
DECLARED = ("first_stage_controls", "poisson_total_c_minus_a", "poisson_pix_minus_nonpix")
P_KIND = {
    "first_stage_controls": "ri",
    "poisson_total_c_minus_a": "cluster",
    "poisson_pix_minus_nonpix": "cluster",
}
_NAN = float("nan")


# --- The window


def read_window(path: Path = WINDOW_RECORD) -> float:
    """h as a fraction, from the record's `window.h_pct`. Raises unless it is 7.5."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    h_pct = record["window"]["h_pct"]
    if h_pct is None or not math.isclose(float(h_pct), H_PCT, abs_tol=1e-9):
        raise GateError(f"window.h_pct in {Path(path).name} is {h_pct}, not {H_PCT}")
    return float(h_pct) / 100.0


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Panels A, B and C, each restricted to the exploration half right after it is read.

    `read(name, columns)` returns one file of `amendments_panel`; only `PANEL_COLUMNS` are asked.
    """
    parts = []
    for cycle in ALL_CYCLES:
        frame = restrict(read(f"panel_{cycle}", PANEL_COLUMNS), half)
        parts.append(
            frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), pl.col("deputy").cast(pl.Utf8))
        )
    return pl.concat(parts, how="vertical_relaxed")


# --- Measures


def add_measures(panel: pl.DataFrame, h: float) -> tuple[pl.DataFrame, int, int]:
    """Rows with a population, with the three instruments and their measures.

    For `<inst>` in total, pix, nonpix: `r_<inst>` (reais), `lpc_<inst>` = ln(1 + reais /
    population), `any_<inst>` (1 if reais > 0) and `lev_<inst>` = reais / population. Pix is null in
    cycle A. Non-Pix is total minus Pix, floored at 0. Also the controls of the sorting check.

    Returns the table, the rows inside h left out for having no population, and the rows inside h
    whose non-Pix money was floored.
    """
    pop = pl.col("population_m").cast(pl.Float64)
    no_population = int(in_window(panel.filter(pop.is_null() | (pop <= 0)), h).height)
    kept = panel.filter(pop > 0)
    total = pl.col("amend_post_total").cast(pl.Float64)
    pix = pl.col("amend_post_pix").cast(pl.Float64)
    diff = total - pix
    kept = kept.with_columns(
        pop.alias("population_m"),
        total.alias("r_total"),
        pl.when(pl.col("cycle") == "A").then(None).otherwise(pix).alias("r_pix"),
        pl.when(diff.is_null())
        .then(None)
        .otherwise(pl.max_horizontal(diff, pl.lit(0.0)))
        .alias("r_nonpix"),
        (diff < 0).fill_null(False).alias("_floored"),
    )
    floored = int(in_window(kept.filter(pl.col("_floored")), h).height)
    cols = []
    for inst in INSTRUMENTS:
        r = pl.col(f"r_{inst}")
        cols += [
            (1.0 + r / pl.col("population_m")).log().alias(f"lpc_{inst}"),
            (r > 0).cast(pl.Float64).alias(f"any_{inst}"),
            (r / pl.col("population_m")).alias(f"lev_{inst}"),
        ]
    kept = kept.with_columns(
        *cols,
        pl.col("party_held_mayor").cast(pl.Float64).alias("c_held"),
        pl.col("amend_pre_log_pc").cast(pl.Float64).alias("c_pre"),
        pl.col("fin_female").cast(pl.Float64).alias("c_female"),
        pl.col("fin_age").cast(pl.Float64).alias("c_age"),
        pl.col("fin_higher_ed").cast(pl.Float64).alias("c_higher"),
        pl.col("n_mayor_cands").cast(pl.Float64).alias("c_cands"),
        pl.col("win").cast(pl.Boolean),
    ).drop("_floored")
    return kept, no_population, floored


def _of(table: pl.DataFrame, cycles: Sequence[str]) -> pl.DataFrame:
    return table.filter(pl.col("cycle").is_in(list(cycles)))


def _usable(table: pl.DataFrame, w: float, column: str) -> pl.DataFrame:
    return in_window(table, w).filter(
        pl.col(column).is_not_null() & pl.col(column).cast(pl.Float64).is_finite()
    )


# --- Linear fits


def _ci(b: float, se: float) -> dict[str, float]:
    return {"b": b, "se": se, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se}


def linear_fit(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    """`estimate` at window `w` with the 95% interval, the mean, the units and the races."""
    fit = full_fit(table, draws, w, column)
    out = {k: fit[k] for k in LINEAR_KEYS if k not in ("ci_low", "ci_high")}
    out.update(_ci(fit["b"], fit["se"]))
    return {k: out[k] for k in LINEAR_KEYS}


def plain_fit(table: pl.DataFrame, w: float, column: str) -> dict[str, float]:
    """b and the clustered se of the model for `column`, no randomisation inference."""
    sub = _usable(table, w, column)
    if sub.height == 0:
        return _ci(_NAN, _NAN)
    sample = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    fit = fe_fit(sample)
    return _ci(fit["b"], fit["se"])


def diff_key(earlier: str, later: str) -> str:
    return f"{later.lower()}_minus_{earlier.lower()}"


def cycle_fit(
    table: pl.DataFrame, w: float, column: str, cycles: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Win, margin and win x margin each times the dummies of `cycles`; deputy fixed effects.

    `by_cycle_fit` for any list of cycles. Returns `b` and the clustered se (by `cd_ibge`, factor
    G/(G-1) (N-1)/(N-K), K = 3 x the number of cycles) of `win` in each cycle, and of the
    difference of each later cycle minus each earlier one, under `diff_key` (`c_minus_a`). No
    randomisation inference.
    """
    cycles = tuple(cycles)
    n_c = len(cycles)
    pairs = [(cycles[i], cycles[j]) for i in range(n_c) for j in range(i + 1, n_c)]
    empty = {c: {"b": _NAN, "se": _NAN} for c in cycles}
    empty.update({diff_key(a, b): {"b": _NAN, "se": _NAN} for a, b in pairs})
    sub = _usable(_of(table, cycles), w, column)
    if sub.height == 0:
        return empty
    index = np.array([cycles.index(c) for c in sub["cycle"]])
    # the cycle index rides in the `rid` slot: Sample keeps it aligned with its own row order
    s = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        index,
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    k = 3 * n_c
    if s.n <= k:
        return empty
    win = (s.margin > 0).astype(float)
    bases = (win, s.margin, win * s.margin)
    cols = [base * (s.rid == c) for base in bases for c in range(n_c)]
    x = np.column_stack([s.demean(col[None, :])[0] for col in cols])
    gram = x.T @ x
    try:
        beta = np.linalg.solve(gram, x.T @ s.y)
        bread = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        return empty
    if not np.isfinite(beta).all() or s.g < 2:
        return empty
    scores = x * (s.y - x @ beta)[:, None]
    sums = np.column_stack([np.bincount(s.cluster, weights=scores[:, i]) for i in range(k)])
    factor = s.g / (s.g - 1) * (s.n - 1) / (s.n - k)
    v = factor * (bread @ (sums.T @ sums) @ bread)

    def root(var: float) -> float:
        return float(math.sqrt(var)) if var >= 0 else _NAN

    out: dict[str, dict[str, float]] = {}
    for i, c in enumerate(cycles):
        out[c] = {"b": float(beta[i]), "se": root(v[i, i])}
    for a, b in pairs:
        i, j = cycles.index(a), cycles.index(b)
        out[diff_key(a, b)] = {
            "b": float(beta[j] - beta[i]),
            "se": root(v[j, j] + v[i, i] - 2 * v[i, j]),
        }
    return out


# --- The model with controls


def _ri_controls(s: Any, z: np.ndarray, draws: np.ndarray) -> np.ndarray:
    """The win coefficient refitted under every sign vector, controls held fixed."""
    out = np.full(draws.shape[0], np.nan)
    k = 3 + z.shape[1]
    if s.n <= k:
        return out
    for a in range(0, draws.shape[0], CHUNK):
        b = min(a + CHUNK, draws.shape[0])
        x = s.design(draws[a:b][:, s.rid].astype(float))
        if z.shape[1]:
            x = np.concatenate([x, np.broadcast_to(z, (x.shape[0], *z.shape))], axis=-1)
        gram = np.einsum("cni,cnj->cij", x, x)
        xy = np.einsum("cni,n->ci", x, s.y)
        out[a:b] = _solve(gram, xy)[:, 0]
    return out


def controls_fit(
    table: pl.DataFrame,
    draws: np.ndarray,
    w: float,
    column: str,
    controls: Sequence[str],
    min_abs_margin: float = 0.0,
) -> dict[str, Any]:
    """The linear model plus `controls`, demeaned within deputy like the rest.

    Rows with |margin| < `min_abs_margin` are left out first (the donut). Rows with a null or
    non-finite control leave the fit and are counted in `n_dropped`. The clustered variance uses
    K = 3 + the number of controls; the randomisation p comes from the same race re-flips with the
    controls held fixed. With no controls it is `estimate`. `f_cluster` = (b / se)^2.
    """
    controls = list(controls)
    sub = _usable(table, w, column)
    if min_abs_margin > 0:
        sub = sub.filter(pl.col("margin").cast(pl.Float64).abs() >= min_abs_margin)
    n_dropped = 0
    if controls:
        ok = pl.all_horizontal(
            [pl.col(c).is_not_null() & pl.col(c).cast(pl.Float64).is_finite() for c in controls]
        )
        n_dropped = int(sub.filter(~ok).height)
        sub = sub.filter(ok)
    out: dict[str, Any] = {
        "b": _NAN,
        "se": _NAN,
        "ri_p": _NAN,
        "f_cluster": _NAN,
        "n_units": int(sub.height),
        "n_races": n_races(sub) if sub.height else 0,
        "n_dropped": n_dropped,
    }
    out.update(ci_low=_NAN, ci_high=_NAN)
    if sub.height == 0:
        return out
    margin, rid = _col(sub, "margin"), sub["race"].to_numpy()
    dep, cluster = sub["deputy"].to_numpy(), sub["cd_ibge"].to_numpy()
    s = Sample(_col(sub, column), margin, rid, dep, cluster)
    # the same deputy ordering as `s`, so each control is demeaned like Y
    z = (
        np.column_stack([Sample(_col(sub, c), margin, rid, dep, cluster).y for c in controls])
        if controls
        else np.empty((s.n, 0))
    )
    k = 3 + len(controls)
    if s.n <= k:
        return out
    x = s.design(np.ones((1, s.n)))[0]
    if controls:
        x = np.hstack([x, z])
    gram = x.T @ x
    beta = _solve(gram[None], (x.T @ s.y)[None])[0]
    if not np.isfinite(beta).all():
        return out
    scores = x * (s.y - x @ beta)[:, None]
    sums = np.column_stack([np.bincount(s.cluster, weights=scores[:, i]) for i in range(k)])
    b = float(beta[0])
    out["b"] = b
    if s.g >= 2:
        factor = s.g / (s.g - 1) * (s.n - 1) / (s.n - k)
        var = factor * (np.linalg.inv(gram) @ (sums.T @ sums) @ np.linalg.inv(gram))[0, 0]
        out["se"] = float(math.sqrt(var)) if var >= 0 else _NAN
    out["ri_p"], _ = ri_summary(b, _ri_controls(s, z, draws))
    se = out["se"]
    out.update(_ci(b, se))
    out["f_cluster"] = (b / se) ** 2 if math.isfinite(se) and se > 0 else _NAN
    return {k: out[k] for k in SORT_KEYS}


# --- Poisson fits


def _poisson_result(
    b: float, se: float, p: float, n_obs: int, path: str = "none", dropped: int = 0
) -> dict[str, Any]:
    ok = math.isfinite(b) and math.isfinite(se)
    return {
        "b": b,
        "se": se,
        "p": p,
        "premium_pct": 100.0 * (math.exp(b) - 1.0) if math.isfinite(b) else _NAN,
        "premium_ci_low": 100.0 * (math.exp(b - Z95 * se) - 1.0) if ok else _NAN,
        "premium_ci_high": 100.0 * (math.exp(b + Z95 * se) - 1.0) if ok else _NAN,
        "n_obs": n_obs,
        "path": path,
        "groups_dropped": dropped,
    }


def _pois(frame: pl.DataFrame, regressors: list[str], target: str) -> dict[str, Any]:
    """`terrain.poisson.fepois` of `y`: fixed effects `fe`, offset `ln_pop`, CRV1 by `cd_ibge`.

    Fixed-effect groups with an all-zero outcome (or a single row) leave the fit; `n_obs` is the
    rows used and `path` says how the fit was made. A fit that cannot be made gives NaN.
    """
    if frame.height == 0:
        return _poisson_result(_NAN, _NAN, _NAN, 0)
    try:
        fit = fepois(
            frame,
            y="y",
            x=regressors,
            fe="fe",
            coef=target,
            offset="ln_pop",
            cluster="cd_ibge",
        )
    except ValueError:  # a negative outcome: reported as NaN, never hidden
        return _poisson_result(_NAN, _NAN, _NAN, 0)
    return _poisson_result(fit.b, fit.se, fit.p, fit.n_obs, fit.path, fit.groups_dropped)


def _base(table: pl.DataFrame, h: float, column: str) -> pl.DataFrame:
    """Rows inside h with a finite outcome: `y`, `win`, `margin`, `wm` and what the fit needs."""
    sub = _usable(table, h, column)
    win = (pl.col("margin").cast(pl.Float64) > 0).cast(pl.Float64)
    margin = pl.col("margin").cast(pl.Float64)
    return sub.select(
        pl.col(column).cast(pl.Float64).alias("y"),
        win.alias("win"),
        margin.alias("margin"),
        (win * margin).alias("wm"),
        pl.col("ln_population").alias("ln_pop"),
        "cd_ibge",
        pl.col("deputy").alias("fe"),
        "cycle",
    )


_PLAIN = ["win", "margin", "wm"]
_INTERACTED = ["win", "margin", "wm", "win_d", "margin_d", "wm_d"]


def _with_dummy(frame: pl.DataFrame, d: pl.Expr) -> pl.DataFrame:
    return frame.with_columns(
        d.alias("d"),
        (pl.col("win") * d).alias("win_d"),
        (pl.col("margin") * d).alias("margin_d"),
        (pl.col("wm") * d).alias("wm_d"),
    )


def poisson_fit(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """Poisson premium of `win` in `column` (reais) at window `h`: deputy fixed effects."""
    return _pois(_base(table, h, column), _PLAIN, "win")


def poisson_cycles(
    table: pl.DataFrame, h: float, column: str, earlier: str, later: str
) -> dict[str, Any]:
    """Later cycle minus earlier: one fit on both cycles' rows, every regressor also interacted
    with a dummy for the later cycle; the difference is the coefficient of `win_d`."""
    frame = _base(_of(table, (earlier, later)), h, column)
    return _pois(
        _with_dummy(frame, (pl.col("cycle") == later).cast(pl.Float64)), _INTERACTED, "win_d"
    )


def poisson_stacked(table: pl.DataFrame, h: float, first: str, second: str) -> dict[str, Any]:
    """First outcome minus second: both stacked, fixed effects deputy x outcome.

    Every regressor is also interacted with the dummy of the first outcome; the difference is the
    coefficient of `win_d`.
    """
    one = _with_dummy(_base(table, h, first), pl.lit(1.0))
    two = _with_dummy(_base(table, h, second), pl.lit(0.0))
    one = one.with_columns((pl.col("fe") + "|1").alias("fe"))
    two = two.with_columns((pl.col("fe") + "|0").alias("fe"))
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


# --- Results


def _sorting(
    table: pl.DataFrame,
    draws: np.ndarray,
    w: float,
    controls: Sequence[str] = CONTROLS,
    min_abs_margin: float = 0.0,
) -> dict[str, Any]:
    return controls_fit(table, draws, w, "lpc_total", controls, min_abs_margin)


def placebo_block(
    table: pl.DataFrame, draws: np.ndarray, h: float, post_b: float
) -> dict[str, Any]:
    """The linear model on `amend_pre_log_pc`.

    `pre_fail` is 1 if |b_pre| > 0.5 |b_post| and the randomisation p is below 0.05.
    """
    pre = linear_fit(table, draws, h, "amend_pre_log_pc")
    ratio = abs(pre["b"]) / abs(post_b) if math.isfinite(post_b) and post_b != 0 else _NAN
    fail = (
        math.isfinite(pre["b"])
        and math.isfinite(post_b)
        and abs(pre["b"]) > 0.5 * abs(post_b)
        and math.isfinite(pre["ri_p"])
        and pre["ri_p"] < 0.05
    )
    return {
        "pre": {k: pre[k] for k in ("b", "se", "ri_p", "mean")},
        "post_b": post_b,
        "ratio": ratio,
        "pre_fail": int(fail),
    }


def build_results(
    table: pl.DataFrame,
    h: float,
    no_population: int,
    nonpix_floored: int,
    source: str = WINDOW_SOURCE,
) -> dict[str, Any]:
    """Everything the step reports at window `h`. `table` is from `add_measures`."""
    prepared = prepare(table)
    draws = sign_draws(n_races(prepared))
    _check_draws(prepared, draws)
    inside = in_window(prepared, h)
    w5 = CHECK_PCT / 100.0
    by_cycle = {}
    for c in ALL_CYCLES:
        s = inside.filter(pl.col("cycle") == c)
        by_cycle[c] = {"units": int(s.height), "races": n_races(s) if s.height else 0}

    instruments: dict[str, Any] = {}
    check_5: dict[str, Any] = {}
    for inst in INSTRUMENTS:
        cycles = INST_CYCLES[inst]
        earlier, later = INST_DIFF[inst]
        scoped = _of(prepared, cycles)
        node: dict[str, Any] = {}
        check: dict[str, Any] = {}
        for measure in ("log_pc", "any"):
            column = f"{'lpc' if measure == 'log_pc' else 'any'}_{inst}"
            scopes: dict[str, Any] = {"pooled": linear_fit(scoped, draws, h, column)}
            by = cycle_fit(prepared, h, column, cycles)
            for key in (*cycles, diff_key(earlier, later)):
                scopes[key] = _ci(by[key]["b"], by[key]["se"])
            node[measure] = scopes
            f5 = linear_fit(scoped, draws, w5, column)
            check[measure] = {k: f5[k] for k in ("b", "se", "ri_p")}
        column = f"r_{inst}"
        pois: dict[str, Any] = {"pooled": poisson_fit(scoped, h, column)}
        for c in cycles:
            pois[c] = poisson_fit(_of(prepared, (c,)), h, column)
        pois[diff_key(earlier, later)] = poisson_cycles(prepared, h, column, earlier, later)
        node["poisson"] = pois
        p5 = poisson_fit(scoped, w5, column)
        check["poisson"] = {k: p5[k] for k in ("b", "se", "p")}
        instruments[inst] = node
        check_5[inst] = check

    levels: dict[str, Any] = {inst: {} for inst in INSTRUMENTS}
    levels["pix_share"], levels["gap"] = {}, {}
    scope_cycles = {"A": ("A",), "B": ("B",), "C": ("C",), "pooled_bc": PIX_CYCLES}
    for scope, cycles in scope_cycles.items():
        # Pix is 0 in cycle A by construction, so there the gap leaves it out
        insts = ("total", "nonpix") if scope == "A" else INSTRUMENTS
        rows = _of(prepared, cycles).filter(
            pl.all_horizontal([pl.col(f"lev_{i}").is_not_null() for i in insts])
        )
        fits = {i: plain_fit(rows, h, f"lev_{i}") for i in insts}
        for i, v in fits.items():
            levels[i][scope] = v
        if scope != "A":
            tb, pb = fits["total"]["b"], fits["pix"]["b"]
            levels["pix_share"][scope] = pb / tb if math.isfinite(tb) and tb != 0 else _NAN
        gap_pix = fits["pix"]["b"] if "pix" in fits else 0.0
        levels["gap"][scope] = fits["total"]["b"] - gap_pix - fits["nonpix"]["b"]

    sorting: dict[str, Any] = {"controls": _sorting(prepared, draws, h)}
    held = pl.col("c_held")
    others = CONTROLS[1:]
    sorting["held_true"] = _sorting(prepared.filter(held == 1.0), draws, h, others)
    sorting["held_false"] = _sorting(prepared.filter(held == 0.0), draws, h, others)
    sorting["donut"] = _sorting(prepared, draws, h, CONTROLS, DONUT)
    sorting["windows"] = {
        label: _sorting(prepared, draws, w) for label, w in SORTING_WINDOWS.items()
    }
    fs = sorting["controls"]

    post_b = instruments["total"]["log_pc"]["pooled"]["b"]
    placebo = placebo_block(prepared, draws, h, post_b)

    bc = _of(prepared, PIX_CYCLES)
    stacked = poisson_stacked(bc, h, "r_pix", "r_nonpix")
    total_ca = instruments["total"]["poisson"][diff_key("A", "C")]
    p_values = {
        "first_stage_controls": fs["ri_p"],
        "poisson_total_c_minus_a": total_ca["p"],
        "poisson_pix_minus_nonpix": stacked["p"],
    }
    adjusted = holm([p_values[n] for n in DECLARED])
    declared = {
        n: {"p": p_values[n], "p_holm": q, "p_kind": P_KIND[n]}
        for n, q in zip(DECLARED, adjusted, strict=True)
    }

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "check_pct": CHECK_PCT, "source": source},
        "counts": {
            "units_h": int(inside.height),
            "races_h": n_races(inside) if inside.height else 0,
            "by_cycle": by_cycle,
            "no_population": no_population,
            "nonpix_floored": nonpix_floored,
        },
        "instruments": instruments,
        "check_5pct": check_5,
        "levels": levels,
        "sorting": sorting,
        "first_stage": {"f_cluster": fs["f_cluster"], "b": fs["b"], "se": fs["se"]},
        "placebo": placebo,
        "poisson_diff": {
            "pix_minus_nonpix": {
                "b": stacked["b"],
                "se": stacked["se"],
                "p": stacked["p"],
                "ratio_pct": stacked["premium_pct"],
                "n_obs": stacked["n_obs"],
            }
        },
        "declared": declared,
    }
    results["estimates"] = {"finite": _all_finite(results)}
    return _clean(results)


# --- Figures


def binned_means(table: pl.DataFrame, h: float) -> pl.DataFrame:
    """Mean `lpc_total` by 0.5-point bin of the margin within +-h, by cycle (centre in points)."""
    n_bins = round(2 * h / BIN_WIDTH)
    inside = _usable(table, h, "lpc_total")
    bins = (
        ((pl.col("margin").cast(pl.Float64) + h) / BIN_WIDTH)
        .floor()
        .clip(0, n_bins - 1)
        .cast(pl.Int64)
    )
    return (
        inside.with_columns(bins.alias("bin"))
        .group_by("cycle", "bin")
        .agg(pl.col("lpc_total").mean().alias("mean"), pl.len().alias("n"))
        .with_columns(((pl.col("bin") + 0.5) * BIN_WIDTH - h).mul(100).alias("centre"))
        .sort("cycle", "bin")
    )


def _num(value: float | None) -> float:
    return _NAN if value is None else float(value)


def write_figures(results: dict[str, Any], table: pl.DataFrame, h: float, out_dir: Path) -> None:
    from terrain.style import configure, save_png

    plt = configure()
    folder = out_dir / "figures"

    def note(fig: Any) -> None:
        fig.text(0.01, 0.0, NOTE, fontsize=7, va="top")

    binned = binned_means(table, h)
    fig, axes = plt.subplots(1, len(ALL_CYCLES), figsize=(8.0, 3.2), sharey=True)
    for ax, c in zip(axes, ALL_CYCLES, strict=True):
        rows = binned.filter(pl.col("cycle") == c)
        ax.plot(rows["centre"].to_numpy(), rows["mean"].to_numpy(), "o", markersize=3)
        ax.axvline(0.0, color="grey", linewidth=0.8, linestyle="--")
        ax.set_title(f"Cycle {c}")
        ax.set_xlabel("Margin of the deputy's party's finalist (percentage points)")
    axes[0].set_ylabel("Mean ln(1 + reais per inhabitant), post window")
    note(fig)
    save_png(fig, folder / "binned_money.png")

    def points(name: str, ylabel: str, measure: str, low: str, high: str, centre: str) -> None:
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        for j, inst in enumerate(INSTRUMENTS):
            node = results["instruments"][inst][measure]
            for i, c in enumerate(ALL_CYCLES):
                if c not in node:
                    continue
                y = _num(node[c][centre])
                if math.isfinite(y):
                    err = [[y - _num(node[c][low])], [_num(node[c][high]) - y]]
                    ax.errorbar(
                        [i + 0.2 * (j - 1)], [y], yerr=err, fmt="o", markersize=4, capsize=2
                    )
        ax.set_xticks(range(len(ALL_CYCLES)), [f"Cycle {c}" for c in ALL_CYCLES])
        ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="--")
        ax.set_ylabel(ylabel)
        ax.set_title("Left to right within a cycle: " + ", ".join(INSTRUMENTS))
        note(fig)
        save_png(fig, folder / name)

    points(
        "coef_by_cycle.png",
        "Linear b on ln(1 + reais per inhabitant), 95% interval",
        "log_pc",
        "ci_low",
        "ci_high",
        "b",
    )
    points(
        "poisson_premium.png",
        "Poisson premium (%), 95% interval",
        "poisson",
        "premium_ci_low",
        "premium_ci_high",
        "premium_pct",
    )


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _lin(v: dict[str, Any]) -> str:
    return f"{_fmt(v['b'])} ({_fmt(v['se'])})"


def _prem(v: dict[str, Any]) -> str:
    return (
        f"{_fmt(v['premium_pct'])} [{_fmt(v['premium_ci_low'])}, {_fmt(v['premium_ci_high'])}] "
        f"(p {_fmt(v['p'])}, n {v['n_obs']})"
    )


def summarize(results: dict[str, Any]) -> str:
    w, c = results["window"], results["counts"]
    fs, pl_ = results["first_stage"], results["placebo"]
    lines = [
        f"Window h = {w['h_pct']:g}%, read from `{w['source']}`; check at {w['check_pct']:g}%. "
        f"Rows at h: {c['units_h']} in {c['races_h']} races (A {c['by_cycle']['A']['units']}, "
        f"B {c['by_cycle']['B']['units']}, C {c['by_cycle']['C']['units']}); rows without a "
        f"population, left out: {c['no_population']}; rows where non-Pix money was floored at 0: "
        f"{c['nonpix_floored']}. `first_stage.f_cluster` = {_fmt(fs['f_cluster'])}; "
        f"`placebo.pre_fail` = {pl_['pre_fail']}; `estimates.finite` = "
        f"{results['estimates']['finite']}.",
        "",
        "Only the three declared estimates below are estimates of this step. Everything else is "
        "descriptive.",
        "",
        "## Declared estimates (Holm over the three)",
        "",
        "| Estimate | raw p | Holm p | kind of p |",
        "| --- | --- | --- | --- |",
    ]
    for name in DECLARED:
        q = results["declared"][name]
        lines.append(f"| {name} | {_fmt(q['p'])} | {_fmt(q['p_holm'])} | {q['p_kind']} |")
    d = results["poisson_diff"]["pix_minus_nonpix"]
    lines += [
        "",
        f"Pix minus non-Pix (Poisson, B and C stacked): b {_lin(d)}, "
        f"ratio {_fmt(d['ratio_pct'])}%, rows {d['n_obs']}.",
        "",
        "## (a) Instruments",
        "",
        "Linear: b (se) on ln(1 + reais per inhabitant) and on the share with any money. "
        "Poisson: premium in %, 95% interval.",
        "",
        "| Instrument | Scope | log_pc | any | Poisson premium |",
        "| --- | --- | --- | --- | --- |",
    ]
    for inst, node in results["instruments"].items():
        for scope, v in node["log_pc"].items():
            lines.append(
                f"| {inst} | {scope} | {_lin(v)} | {_lin(node['any'][scope])} "
                f"| {_prem(node['poisson'][scope])} |"
            )
    lines += ["", "At 5% (pooled):", ""]
    for inst, node in results["check_5pct"].items():
        lines.append(
            f"- {inst}: log_pc b {_fmt(node['log_pc']['b'])} (randomisation p "
            f"{_fmt(node['log_pc']['ri_p'])}); any b {_fmt(node['any']['b'])} (randomisation p "
            f"{_fmt(node['any']['ri_p'])}); Poisson b {_fmt(node['poisson']['b'])} "
            f"(p {_fmt(node['poisson']['p'])})."
        )
    lv = results["levels"]
    lines += [
        "",
        "## (b) Levels (reais per inhabitant, linear b (se))",
        "",
        "| Scope | total | Pix | non-Pix | Pix share | gap |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for scope in lv["gap"]:
        pix = _lin(lv["pix"][scope]) if scope in lv["pix"] else "n/a"
        share = _fmt(lv["pix_share"].get(scope))
        lines.append(
            f"| {scope} | {_lin(lv['total'][scope])} | {pix} | {_lin(lv['nonpix'][scope])} "
            f"| {share} | {_fmt(lv['gap'][scope])} |"
        )
    lines += [
        "",
        "## (c) Sorting (total, log_pc, pooled; controls as listed in the task)",
        "",
        "| Model | b | se | 95% interval | randomisation p | F | rows | races | dropped |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = {k: v for k, v in results["sorting"].items() if k != "windows"}
    rows.update({f"windows.{k}": v for k, v in results["sorting"]["windows"].items()})
    for name, v in rows.items():
        lines.append(
            f"| {name} | {_fmt(v['b'])} | {_fmt(v['se'])} | [{_fmt(v['ci_low'])}, "
            f"{_fmt(v['ci_high'])}] | {_fmt(v['ri_p'])} | {_fmt(v['f_cluster'])} "
            f"| {v['n_units']} | {v['n_races']} | {v['n_dropped']} |"
        )
    pre = pl_["pre"]
    lines += [
        "",
        "## (d) Placebo (pre-window `log_pc`, no controls)",
        "",
        f"Pre-window b {_fmt(pre['b'])} (se {_fmt(pre['se'])}, "
        f"randomisation p {_fmt(pre['ri_p'])}); "
        f"post-window b {_fmt(pl_['post_b'])}; ratio {_fmt(pl_['ratio'])}; "
        f"`pre_fail` = {pl_['pre_fail']}.",
        "",
        "## Caveats",
        "",
        "- The same exploration half and window campaign 0011 analysed, so this is a further look "
        "at the same data, and questions 1 to 3 were added after its results.",
        "- National payment totals grew from cycle A to C, so a growing `log_pc` jump need not "
        "mean growing favouritism; the Poisson premium is the comparison in percent.",
        "- By-cycle linear estimates have clustered errors only.",
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
    table, no_population, floored = add_measures(panel, h)
    results = build_results(table, h, no_population, floored)
    write_figures(results, table, h, args.out_dir)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
