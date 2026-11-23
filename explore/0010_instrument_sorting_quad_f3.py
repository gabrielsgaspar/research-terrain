"""Fork f3 of step s2 (idea 0010): the instrument and sorting checks with a local quadratic.

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), decisions 0011 (national scope) and
0015 (forks), campaign `research/campaigns/0013-amendments-mechanisms/`, fork `forks/f3.md`. The
national exploration half only: every panel is restricted to it right after it is read.

It repeats step s1's analysis (`explore/0010_instrument_sorting.py`, loaded as is) with one change:
every fit adds margin^2 (`m2`) and win x margin^2 (`wm2`) to the regressors, a local quadratic
instead of a local linear model. Under each randomisation re-flip `wm2` is recomputed from the
flipped win, as win x margin is, while `m2` and the controls stay fixed. Everything else is s1's
design: window, instruments, measures, controls, draws, fixed effects, clustering, Holm. Its
`results.json` has s1's keys at the same paths, plus `spec.polynomial` and `spec.parent_run`, so the
kill rules of step s2 read it unchanged.

Inside the linear fits the margin is scaled by 10 (so |margin| <= 1) before squaring. That is only
a change of units of the control terms: the coefficient and the clustered error of `win` are
unchanged, and the normal equations stay well conditioned. A fork's result is "survived (fork)" or
"killed (fork)", never a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
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
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


s1 = _load("sorting_s1", "0010_instrument_sorting.py")

GateError = s1.GateError
sign_draws = s1.sign_draws
n_races = s1.n_races
in_window = s1.in_window
prepare = s1.prepare
holm = s1.holm
read_window = s1.read_window
add_measures = s1.add_measures
diff_key = s1.diff_key
_check_draws = s1._check_draws
_all_finite = s1._all_finite
_clean = s1._clean
_paths = s1._paths
_col = s1._col
_solve = s1._solve
_ci = s1._ci
_of = s1._of
_usable = s1._usable
_pois = s1._pois
Sample = s1.Sample
ri_summary = s1.ri_summary
write_figures = s1.write_figures

ALL_CYCLES = s1.ALL_CYCLES
PIX_CYCLES = s1.PIX_CYCLES
INSTRUMENTS = s1.INSTRUMENTS
INST_CYCLES = s1.INST_CYCLES
INST_DIFF = s1.INST_DIFF
CONTROLS = s1.CONTROLS
SORTING_WINDOWS = s1.SORTING_WINDOWS
LINEAR_KEYS = s1.LINEAR_KEYS
SORT_KEYS = s1.SORT_KEYS
DECLARED = s1.DECLARED
P_KIND = s1.P_KIND
PANEL_COLUMNS = s1.PANEL_COLUMNS
CHECK_PCT = s1.CHECK_PCT
DONUT = s1.DONUT
CHUNK = s1.CHUNK
WINDOW_SOURCE = s1.WINDOW_SOURCE
NOTE = s1.NOTE

PARENT_RUN = "45248303745"
PARENT_RECORD = REPO / "research" / "explore-runs" / "0010" / f"{PARENT_RUN}.json"
SCALE = 10.0  # margin units of the linear fits when squared: |margin| <= 0.1 becomes <= 1
_NAN = float("nan")


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """Panels A, B and C, each restricted to the exploration half right after it is read."""
    parts = []
    for cycle in ALL_CYCLES:
        frame = restrict(read(f"panel_{cycle}", PANEL_COLUMNS), half)
        parts.append(
            frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), pl.col("deputy").cast(pl.Utf8))
        )
    return pl.concat(parts, how="vertical_relaxed")


# --- The design


def _k(poly: int) -> int:
    """Regressors of the margin model: win, m, win x m, and with a quadratic m2 and wm2."""
    if poly not in (1, 2):
        raise ValueError("poly must be 1 or 2")
    return 3 + 2 * (poly - 1)


def _scale(poly: int) -> float:
    return SCALE if poly == 2 else 1.0


def design(s: Any, signs: np.ndarray, poly: int = 2) -> np.ndarray:
    """(draws, n, K): win, m, win x m [, m2, win x m2] after re-flipping, demeaned within deputy.

    `signs` is (draws, n). `m` is flipped; `win` comes from the flipped `m`; `m2` does not change
    under a flip; `wm2` is recomputed from the flipped win. With `poly` = 1 this is
    `Sample.design`.
    """
    _k(poly)
    base = s.margin * _scale(poly)
    m = signs * base
    win = (m > 0).astype(float)
    cols = [win, m, win * m]
    if poly == 2:
        m2 = np.array(np.broadcast_to(base**2, m.shape))
        cols += [m2, win * m2]
    return np.stack([s.demean(c) for c in cols], axis=-1)


def _meat(s: Any, x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    scores = x * (s.y - x @ beta)[:, None]
    return np.column_stack(
        [np.bincount(s.cluster, weights=scores[:, i]) for i in range(x.shape[1])]
    )


def fe_fit(s: Any, poly: int = 2) -> dict[str, float]:
    """b of `win` and its error clustered by `cd_ibge`, factor G/(G-1) (N-1)/(N-K)."""
    k = _k(poly)
    nan = {"b": _NAN, "se": _NAN}
    if s.n <= k:
        return nan
    x = design(s, np.ones((1, s.n)), poly)[0]
    gram = x.T @ x
    beta = _solve(gram[None], (x.T @ s.y)[None])[0]
    if not np.isfinite(beta).all():
        return nan
    sums = _meat(s, x, beta)
    if s.g < 2:
        return {"b": float(beta[0]), "se": _NAN}
    bread = np.linalg.inv(gram)
    factor = s.g / (s.g - 1) * (s.n - 1) / (s.n - k)
    var = factor * (bread @ (sums.T @ sums) @ bread)[0, 0]
    return {"b": float(beta[0]), "se": float(math.sqrt(var)) if var >= 0 else _NAN}


def ri_b(s: Any, draws: np.ndarray, poly: int = 2) -> np.ndarray:
    """The win coefficient refitted under every sign vector (NaN where it cannot be fitted)."""
    out = np.full(draws.shape[0], np.nan)
    if s.n <= _k(poly):
        return out
    for a in range(0, draws.shape[0], CHUNK):
        b = min(a + CHUNK, draws.shape[0])
        x = design(s, draws[a:b][:, s.rid].astype(float), poly)
        gram = np.einsum("cni,cnj->cij", x, x)
        xy = np.einsum("cni,n->ci", x, s.y)
        out[a:b] = _solve(gram, xy)[:, 0]
    return out


def _sample(sub: pl.DataFrame, column: str) -> Any:
    return Sample(
        _col(sub, column),
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )


# --- Linear fits


def linear_fit(
    table: pl.DataFrame, draws: np.ndarray, w: float, column: str, poly: int = 2
) -> dict[str, Any]:
    """b, se, interval, randomisation p, mean, units and races of the model for `column` at `w`."""
    sub = _usable(table, w, column)
    out: dict[str, Any] = {k: _NAN for k in LINEAR_KEYS}
    out.update(n_units=int(sub.height), n_races=n_races(sub) if sub.height else 0)
    if sub.height == 0:
        return out
    s = _sample(sub, column)
    fit = fe_fit(s, poly)
    out["mean"] = float(_col(sub, column).mean())
    out["ri_p"], _ = ri_summary(fit["b"], ri_b(s, draws, poly))
    out.update(_ci(fit["b"], fit["se"]))
    return {k: out[k] for k in LINEAR_KEYS}


def plain_fit(table: pl.DataFrame, w: float, column: str, poly: int = 2) -> dict[str, float]:
    """b and the clustered se of the model for `column`, no randomisation inference."""
    sub = _usable(table, w, column)
    if sub.height == 0:
        return _ci(_NAN, _NAN)
    fit = fe_fit(_sample(sub, column), poly)
    return _ci(fit["b"], fit["se"])


def cycle_fit(
    table: pl.DataFrame, w: float, column: str, cycles: Sequence[str], poly: int = 2
) -> dict[str, dict[str, float]]:
    """Win, m, win x m [, m2, win x m2] each times the dummies of `cycles`; deputy fixed effects.

    Returns `b` and the clustered se (K = regressors x cycles) of `win` in each cycle and of each
    later cycle minus each earlier one, under `diff_key`. No randomisation inference.
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
    s = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        index,
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    k = _k(poly) * n_c
    if s.n <= k:
        return empty
    m = s.margin * _scale(poly)
    win = (m > 0).astype(float)
    bases = [win, m, win * m]
    if poly == 2:
        bases += [m**2, win * m**2]
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
    sums = _meat(s, x, beta)
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


def _ri_controls(s: Any, z: np.ndarray, draws: np.ndarray, poly: int = 2) -> np.ndarray:
    """The win coefficient refitted under every sign vector, controls held fixed."""
    out = np.full(draws.shape[0], np.nan)
    if s.n <= _k(poly) + z.shape[1]:
        return out
    for a in range(0, draws.shape[0], CHUNK):
        b = min(a + CHUNK, draws.shape[0])
        x = design(s, draws[a:b][:, s.rid].astype(float), poly)
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
    poly: int = 2,
) -> dict[str, Any]:
    """The margin model plus `controls`, demeaned within deputy like the rest (s1's rules).

    K = regressors of the margin model + the number of controls. `f_cluster` = (b / se)^2.
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
        "ci_low": _NAN,
        "ci_high": _NAN,
        "n_units": int(sub.height),
        "n_races": n_races(sub) if sub.height else 0,
        "n_dropped": n_dropped,
    }
    if sub.height == 0:
        return {k: out[k] for k in SORT_KEYS}
    margin, rid = _col(sub, "margin"), sub["race"].to_numpy()
    dep, cluster = sub["deputy"].to_numpy(), sub["cd_ibge"].to_numpy()
    s = Sample(_col(sub, column), margin, rid, dep, cluster)
    z = (
        np.column_stack([Sample(_col(sub, c), margin, rid, dep, cluster).y for c in controls])
        if controls
        else np.empty((s.n, 0))
    )
    k = _k(poly) + len(controls)
    if s.n <= k:
        return {k_: out[k_] for k_ in SORT_KEYS}
    x = design(s, np.ones((1, s.n)), poly)[0]
    if controls:
        x = np.hstack([x, z])
    gram = x.T @ x
    beta = _solve(gram[None], (x.T @ s.y)[None])[0]
    if not np.isfinite(beta).all():
        return {k_: out[k_] for k_ in SORT_KEYS}
    sums = _meat(s, x, beta)
    b = float(beta[0])
    out["b"] = b
    if s.g >= 2:
        factor = s.g / (s.g - 1) * (s.n - 1) / (s.n - k)
        bread = np.linalg.inv(gram)
        var = factor * (bread @ (sums.T @ sums) @ bread)[0, 0]
        out["se"] = float(math.sqrt(var)) if var >= 0 else _NAN
    out["ri_p"], _ = ri_summary(b, _ri_controls(s, z, draws, poly))
    se = out["se"]
    out.update(_ci(b, se))
    out["f_cluster"] = (b / se) ** 2 if math.isfinite(se) and se > 0 else _NAN
    return {k_: out[k_] for k_ in SORT_KEYS}


# --- Poisson fits (m2 and wm2 enter like margin and wm)

_PLAIN = ["win", "margin", "wm", "m2", "wm2"]
_INTERACTED = [*_PLAIN, "win_d", "margin_d", "wm_d", "m2_d", "wm2_d"]


def _base(table: pl.DataFrame, h: float, column: str) -> pl.DataFrame:
    """s1's rows plus `m2` and `wm2`; the margin terms are in units of 10 points."""
    frame = s1._base(table, h, column)
    margin = pl.col("margin") * SCALE
    return frame.with_columns(
        margin.alias("margin"),
        (pl.col("wm") * SCALE).alias("wm"),
        (margin**2).alias("m2"),
        (pl.col("win") * margin**2).alias("wm2"),
    )


def _with_dummy(frame: pl.DataFrame, d: pl.Expr) -> pl.DataFrame:
    return s1._with_dummy(frame, d).with_columns(
        (pl.col("m2") * d).alias("m2_d"), (pl.col("wm2") * d).alias("wm2_d")
    )


def poisson_fit(table: pl.DataFrame, h: float, column: str) -> dict[str, Any]:
    """Poisson premium of `win` in `column` (reais) at window `h`, with the quadratic."""
    return _pois(_base(table, h, column), _PLAIN, "win")


def poisson_cycles(
    table: pl.DataFrame, h: float, column: str, earlier: str, later: str
) -> dict[str, Any]:
    """Later cycle minus earlier: every regressor, m2 and wm2 too, also times a later dummy."""
    frame = _base(_of(table, (earlier, later)), h, column)
    return _pois(
        _with_dummy(frame, (pl.col("cycle") == later).cast(pl.Float64)), _INTERACTED, "win_d"
    )


def poisson_stacked(table: pl.DataFrame, h: float, first: str, second: str) -> dict[str, Any]:
    """First outcome minus second: stacked, fixed effects deputy x outcome, every regressor
    also times the dummy of the first outcome."""
    one = _with_dummy(_base(table, h, first), pl.lit(1.0))
    two = _with_dummy(_base(table, h, second), pl.lit(0.0))
    one = one.with_columns((pl.col("fe") + "|1").alias("fe"))
    two = two.with_columns((pl.col("fe") + "|0").alias("fe"))
    return _pois(pl.concat([one, two]), _INTERACTED, "win_d")


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
    """The quadratic model, no controls, on `amend_pre_log_pc`.

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
    """Everything s1 reports at window `h`, from the quadratic fits (`table`: `add_measures`)."""
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
    results["spec"] = {"polynomial": 2, "parent_run": PARENT_RUN}
    return _clean(results)


# --- Summary


def parent_sorting(path: Path = PARENT_RECORD) -> dict[str, dict[str, float | None]]:
    """The parent run's sorting rows (b and F), keyed like the sorting table."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    node = record["sorting"]
    rows = {k: v for k, v in node.items() if k != "windows"}
    rows.update({f"windows.{k}": v for k, v in node["windows"].items()})
    return {k: {"b": v["b"], "f_cluster": v["f_cluster"]} for k, v in rows.items()}


def summarize(results: dict[str, Any], parent: dict[str, Any] | None = None) -> str:
    """s1's summary, then the sorting rows next to the parent's, then the fork's caveats."""
    parent = parent if parent is not None else parent_sorting()
    fmt = s1._fmt
    lines = [
        "# Fork f3 of step s2: local quadratic in the margin",
        "",
        s1.summarize(results),
        "",
        f"## Sorting, quadratic against the parent (run {results['spec']['parent_run']}, linear)",
        "",
        "| Model | quadratic b | quadratic F | parent b | parent F |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = {k: v for k, v in results["sorting"].items() if k != "windows"}
    rows.update({f"windows.{k}": v for k, v in results["sorting"]["windows"].items()})
    for name, v in rows.items():
        p = parent.get(name, {"b": None, "f_cluster": None})
        lines.append(
            f"| {name} | {fmt(v['b'])} | {fmt(v['f_cluster'])} | {fmt(p['b'])} "
            f"| {fmt(p['f_cluster'])} |"
        )
    lines += [
        "",
        "## Fork caveats",
        "",
        "- This is fork f3 of step s2, one spec change: a local quadratic in the margin in every "
        "fit (`m2` and `wm2`; `wm2` is re-flipped with the win in the randomisation).",
        '- Its result reads "survived (fork)" or "killed (fork)", next to the number of forks '
        "tried at this point. It is never a finding.",
        "- A quadratic costs precision: a larger error is expected even with no curvature.",
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
