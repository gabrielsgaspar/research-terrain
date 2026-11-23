"""The incumbency-curse gate: counts, validity, placebo and power (idea 0012, s1).

Idea 0012 (`research/ideas/0012-incumbency-curse.md`), decisions 0017 (validity by the estimator),
0008 (its window table, information only), 0003 and 0011 (national scope), campaign
`research/campaigns/0014-incumbency-curse/campaign.md`, step s1. The national exploration half
only: every panel file is restricted to it right after it is read, before anything else.

At the fixed bandwidth h = 0.135 with a triangular kernel the script counts close races per
election, tests the balance of predetermined covariates with the design's own weighted model,
estimates the placebo jump in `party_held_mayor_lag`, and computes the minimum detectable H1
difference. It shows decision 0008's window table as information only. Every field is reported
twice: for all rows, and for the S2 sample (`finalist_eligible` rows). It reads no column measured
at e+4 and no amendment money: `READ_COLUMNS` holds the only columns taken from
`mayor_incumbency_panel`. Step s3 loads this script and reuses its functions.

A race is (`election`, `cd_ibge`) with two rows, one per finalist; the two margins add to 0. A
re-flip multiplies both margins of a race by one sign and recomputes `win` as flipped margin > 0;
|margin| does not change, so the kernel weights do not either. The 2,000 sign vectors (seed
20261122) are drawn once and reused for every estimate. The model is, per cell c, a_c + g_c margin
+ d_c win margin, plus one `win` coefficient b_G per group G of cells, fitted by weighted least
squares with the kernel weights, standard errors clustered by `cd_ibge` (CR1). Nothing on the
exploration half is a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
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
MANIFESTS = REPO / "data" / "manifests" / "build"

# The only columns read from the panel: nothing measured at e+4, no amendment money.
READ_COLUMNS = [
    "election",
    "cd_ibge",
    "uf",
    "party",
    "margin",
    "win",
    "fin_female",
    "fin_age",
    "fin_higher_ed",
    "party_held_mayor_lag",
    "ln_pop",
    "n_mayor_cands",
    "bench_fed",
    "finalist_eligible",
]
ELECTIONS = (2004, 2008, 2012, 2016, 2020)
CYCLE_ELECTIONS = (2008, 2012, 2016, 2020)
PRE = (2008, 2012, 2016)
POST = (2020,)
H = 0.135
KERNEL = "triangular"
DRAWS = 2000
SEED = 20261122
STAND_IN = "party_held_mayor_lag"
MDE_K = 2.80  # z 0.975 + z 0.80: two-sided alpha 0.05, power 80%
PLACEBO_B = 0.05
PLACEBO_P = 0.05
EDGE = 1e-12
PTOL = 1e-12
# covariate -> (column, elections of its one group)
BALANCE: dict[str, tuple[str, tuple[int, ...]]] = {
    "fin_female": ("fin_female", (2008, 2012, 2016, 2020)),
    "fin_age": ("fin_age", (2008, 2012, 2016, 2020)),
    "fin_higher_ed": ("fin_higher_ed", (2008, 2012, 2016, 2020)),
    "finalist_eligible": ("finalist_eligible", (2008, 2012, 2016, 2020)),
    "bench_fed_pos": ("bench_fed_pos", (2012, 2016, 2020)),
}
RULE_FIELDS = (
    "balance.omnibus_p",
    "placebo.fail",
    "power.mde_h1",
    "counts.min_cycle_races_h",
)
WINDOW_FIELDS = ("races", "units", "omnibus_p", "min_p", "min_p_covariate")


class GateError(Exception):
    """The inputs cannot support the gate, or a kill-rule field could not be computed."""


# --- Reading


def load_panel(
    read: Callable[[str, list[str]], pl.DataFrame],
    half: frozenset[str],
    columns: list[str] = READ_COLUMNS,
) -> pl.DataFrame:
    """The five election panels, each restricted to the exploration half right after it is read.

    `read(name, columns)` returns one file of `mayor_incumbency_panel` (`panel_2004` ...).
    """
    parts = []
    for election in ELECTIONS:
        frame = restrict(read(f"panel_{election}", list(columns)), half)
        parts.append(
            frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), pl.col("election").cast(pl.Int64))
        )
    return pl.concat(parts, how="vertical_relaxed")


# --- Preparing the panel


def prepare(panel: pl.DataFrame) -> pl.DataFrame:
    """`panel` with `race` = 0..R-1 over sorted (`election`, `cd_ibge`), every election together."""
    races = (
        panel.select("election", "cd_ibge")
        .unique()
        .sort("election", "cd_ibge")
        .with_row_index("race")
        .with_columns(pl.col("race").cast(pl.Int64))
    )
    return panel.join(races, on=["election", "cd_ibge"], how="left")


def n_races(panel: pl.DataFrame) -> int:
    return panel.select("election", "cd_ibge").unique().height


def sign_draws(races: int, draws: int = DRAWS, seed: int = SEED) -> np.ndarray:
    """One (`draws`, `races`) matrix of +1/-1, the same for every estimate."""
    rng = np.random.default_rng(seed)
    return (rng.integers(0, 2, size=(draws, races), dtype=np.int8) * 2 - 1).astype(np.int8)


def flip(margin: np.ndarray, race: np.ndarray, signs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Re-flip: margin x the sign of its race, and `win` = flipped margin > 0.

    `signs` holds one sign per race, either one vector or a (draws, races) matrix.
    """
    flipped = signs[..., race].astype(float) * margin
    return flipped, flipped > 0


def kernel_weights(margin: Sequence[float] | np.ndarray, h: float, kernel: str) -> np.ndarray:
    """Kernel weight per row; 0 means the row is not in the fit.

    Triangular: 1 - |m| / h where |m| < h. Uniform: 1 where |m| <= h (+ 1e-12).
    """
    m = np.abs(np.asarray(margin, dtype=float))
    if kernel == "triangular":
        return np.where(m < h, 1.0 - m / h, 0.0)
    if kernel == "uniform":
        return np.where(m <= h + EDGE, 1.0, 0.0)
    raise GateError(f"unknown kernel {kernel!r}")


def _col(table: pl.DataFrame, name: str) -> np.ndarray:
    return table.get_column(name).cast(pl.Float64).fill_null(float("nan")).to_numpy()


def _check_draws(table: pl.DataFrame, draws: np.ndarray) -> None:
    if draws.ndim != 2 or draws.shape[1] != n_races(table):
        raise GateError(f"draws must have one column per race ({n_races(table)})")


# --- The model and randomisation inference


class Sample:
    """Rows of one fit: y, margin, kernel weight, race, cluster and cell, with the groups."""

    def __init__(
        self,
        y: np.ndarray,
        margin: np.ndarray,
        weight: np.ndarray,
        rid: np.ndarray,
        cluster: np.ndarray,
        cell: np.ndarray,
        groups: Sequence[Sequence[Any]],
        n_null_y: int = 0,
    ) -> None:
        self.y = y
        self.margin = margin
        self.weight = weight
        self.rid = rid
        _, self.cluster = np.unique(cluster, return_inverse=True)
        self.n = int(y.size)
        self.g = int(self.cluster.max() + 1) if self.n else 0
        used = sorted({c for grp in groups for c in grp})
        self.masks = [(cell == c).astype(float) for c in used]
        self.group_masks = [np.isin(cell, list(grp)).astype(float) for grp in groups]
        self.n_groups = len(groups)
        self.k = 3 * len(used) + self.n_groups
        self.n_null_y = n_null_y

    def design(self, margin: np.ndarray) -> np.ndarray:
        """(n, K): per cell 1, margin and win x margin; then one win column per group."""
        win = (margin > 0).astype(float)
        cols = []
        for mask in self.masks:
            cols += [mask, mask * margin, mask * win * margin]
        cols += [win * mask for mask in self.group_masks]
        return np.column_stack(cols)


def _sample(
    table: pl.DataFrame,
    y: str,
    h: float,
    groups: Sequence[Sequence[Any]],
    kernel: str,
    cell: str,
) -> Sample:
    used = sorted({c for grp in groups for c in grp})
    margin_all = _col(table, "margin")
    inside = (kernel_weights(margin_all, h, kernel) > 0) & np.asarray(
        table.get_column(cell).is_in(used).fill_null(False).to_numpy()
    )
    sub = table.filter(pl.Series(inside))
    ok = sub.get_column(y).cast(pl.Float64).is_finite().fill_null(False)
    n_null = int(sub.height - ok.sum())
    sub = sub.filter(ok)
    margin = _col(sub, "margin")
    return Sample(
        _col(sub, y),
        margin,
        kernel_weights(margin, h, kernel),
        sub["race"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
        sub.get_column(cell).to_numpy(),
        groups,
        n_null,
    )


def _solve(gram: np.ndarray, xy: np.ndarray) -> np.ndarray | None:
    """The normal-equation solution, or None if the system is singular."""
    if np.linalg.matrix_rank(gram) < gram.shape[0]:
        return None
    return np.linalg.solve(gram, xy)


def fit(
    table: pl.DataFrame,
    y: str,
    h: float,
    groups: Sequence[Sequence[Any]],
    kernel: str = KERNEL,
    cell: str = "election",
) -> dict[str, Any]:
    """The weighted model for column `y` on rows inside the kernel at `h` with a non-null `y`.

    `groups` is a list of groups of `cell` values; rows outside every group are dropped. Returns
    `b` and `se` (one per group), `cov` (their covariance matrix), `n_units`, `n_races` and
    `n_null_y` (rows in the kernel and the groups that have no Y). A singular design gives NaN.
    SEs are clustered by `cd_ibge` (CR1), factor G_c/(G_c-1) x (N-1)/(N-K).
    """
    sample = _sample(table, y, h, groups, kernel, cell)
    n_groups = len(groups)
    out: dict[str, Any] = {
        "b": np.full(n_groups, np.nan),
        "se": np.full(n_groups, np.nan),
        "cov": np.full((n_groups, n_groups), np.nan),
        "n_units": sample.n,
        "n_races": int(np.unique(sample.rid).size),
        "n_null_y": sample.n_null_y,
    }
    if sample.n <= sample.k:
        return out
    x = sample.design(sample.margin)
    gram = x.T @ (x * sample.weight[:, None])
    beta = _solve(gram, x.T @ (sample.weight * sample.y))
    if beta is None:
        return out
    out["b"] = beta[-n_groups:].copy()
    if sample.g < 2:
        return out
    resid = sample.y - x @ beta
    scores = x * (sample.weight * resid)[:, None]
    sums = np.column_stack(
        [np.bincount(sample.cluster, weights=scores[:, i]) for i in range(sample.k)]
    )
    bread = np.linalg.inv(gram)
    factor = sample.g / (sample.g - 1) * (sample.n - 1) / (sample.n - sample.k)
    cov = factor * (bread @ (sums.T @ sums) @ bread)
    out["cov"] = cov[-n_groups:, -n_groups:]
    var = np.diag(out["cov"])
    out["se"] = np.sqrt(np.where(var >= 0, var, np.nan))
    return out


def ri_draws(
    table: pl.DataFrame,
    y: str,
    h: float,
    groups: Sequence[Sequence[Any]],
    draws: np.ndarray,
    weights: Sequence[float],
    kernel: str = KERNEL,
    cell: str = "election",
) -> np.ndarray:
    """The draws of `weights` . b: the model refitted under every re-flip (NaN where singular)."""
    sample = _sample(table, y, h, groups, kernel, cell)
    w = np.asarray(weights, dtype=float)
    if w.size != len(groups):
        raise GateError("weights must have one entry per group")
    out = np.full(draws.shape[0], np.nan)
    if sample.n <= sample.k:
        return out
    wy = sample.weight * sample.y
    for i in range(draws.shape[0]):
        flipped, _ = flip(sample.margin, sample.rid, draws[i])
        x = sample.design(flipped)
        beta = _solve(x.T @ (x * sample.weight[:, None]), x.T @ wy)
        if beta is not None:
            out[i] = float(w @ beta[-len(groups) :])
    return out


def ri_p(observed: float, b_draws: np.ndarray) -> float:
    """(1 + #{|draw| >= |observed|}) / (draws + 1); NaN if the observed value is not finite."""
    if not math.isfinite(observed):
        return float("nan")
    with np.errstate(invalid="ignore"):
        hits = int(np.sum(np.abs(b_draws) >= abs(observed) - PTOL))
    return (1 + hits) / (b_draws.size + 1)


def _draw_p(b_draws: np.ndarray) -> np.ndarray:
    """Each draw's own p: #{draws with |b| >= its |b|} / (draws + 1); inf where not finite."""
    abs_draw = np.abs(b_draws)
    out = np.full(b_draws.size, np.inf)
    finite = np.isfinite(abs_draw)
    ordered = np.sort(abs_draw[finite])
    at_least = ordered.size - np.searchsorted(ordered, abs_draw[finite], side="left")
    out[finite] = at_least / (b_draws.size + 1)
    return out


# --- Counts, balance, placebo, power


def in_kernel(table: pl.DataFrame, h: float, kernel: str = KERNEL) -> pl.DataFrame:
    return table.filter(pl.Series(kernel_weights(_col(table, "margin"), h, kernel) > 0))


def counts_at(table: pl.DataFrame, h: float, kernel: str = KERNEL) -> dict[str, Any]:
    """Per election inside the kernel at `h`: races, rows, ties and eligible-finalist rows.

    `min_cycle_races_h` is the smallest race count over 2008, 2012, 2016 and 2020 only.
    """
    sub = in_kernel(table, h, kernel)
    races, rows, ties, eligible = {}, {}, {}, {}
    for e in ELECTIONS:
        s = sub.filter(pl.col("election") == e)
        races[f"e{e}"] = int(s["race"].n_unique()) if s.height else 0
        rows[f"e{e}"] = int(s.height)
        ties[f"e{e}"] = int(s.filter(pl.col("margin").cast(pl.Float64) == 0).height)
        eligible[f"e{e}"] = int(s.filter(pl.col("finalist_eligible").fill_null(False)).height)
    return {
        "min_cycle_races_h": min(races[f"e{e}"] for e in CYCLE_ELECTIONS),
        "races_h": races,
        "rows_h": rows,
        "ties_h": ties,
        "eligible_rows_h": eligible,
    }


def balance_at(
    table: pl.DataFrame,
    draws: np.ndarray,
    h: float,
    kernel: str = KERNEL,
    covariates: Sequence[str] = tuple(BALANCE),
) -> dict[str, Any]:
    """The jump at the cutoff in each predetermined covariate, with randomisation p-values.

    `bench_fed_pos` = 1[`bench_fed` > 0] uses 2012-2020 only. A row with a null covariate leaves
    that covariate only. The omnibus p is (1 + #{draws whose smallest p <= the observed smallest
    p}) / (draws + 1), each draw's p taken from the same draws.
    """
    frame = table.with_columns(
        pl.when(pl.col("bench_fed").is_null())
        .then(None)
        .otherwise((pl.col("bench_fed") > 0).cast(pl.Float64))
        .alias("bench_fed_pos")
    )
    names = list(covariates)
    k = len(names)
    cov_out: dict[str, Any] = {}
    p_obs = np.full(k, np.nan)
    p_draw = np.full((draws.shape[0], k), np.inf)
    for j, name in enumerate(names):
        column, elections = BALANCE[name]
        groups = [list(elections)]
        result = fit(frame, column, h, groups, kernel)
        b, se = float(result["b"][0]), float(result["se"][0])
        b_draws = ri_draws(frame, column, h, groups, draws, (1.0,), kernel)
        p_obs[j] = ri_p(b, b_draws)
        p_draw[:, j] = _draw_p(b_draws)
        cov_out[name] = {
            "b": b,
            "se": se,
            "ri_p": float(p_obs[j]),
            "n_units": result["n_units"],
            "n_races": result["n_races"],
        }
    out: dict[str, Any] = {
        "omnibus_p": float("nan"),
        "min_p": float("nan"),
        "min_p_covariate": None,
        "covariates": cov_out,
    }
    if np.isfinite(p_obs).any():
        j = int(np.nanargmin(p_obs))
        out["min_p"] = float(p_obs[j])
        out["min_p_covariate"] = names[j]
        draw_min = p_draw.min(axis=1)
        out["omnibus_p"] = (1 + int(np.sum(draw_min <= p_obs[j] + PTOL))) / (draws.shape[0] + 1)
    return out


def placebo_fail(b: float, p: float) -> int:
    """1 if |b| > 0.05 and the randomisation p < 0.05, else 0."""
    if not (math.isfinite(b) and math.isfinite(p)):
        raise GateError("the placebo b or its p is not a finite number")
    return int(abs(b) > PLACEBO_B and p < PLACEBO_P)


def placebo_at(
    table: pl.DataFrame, draws: np.ndarray, h: float, kernel: str = KERNEL
) -> dict[str, Any]:
    """The jump in `party_held_mayor_lag`, all five elections as one group; then per election."""
    groups = [list(ELECTIONS)]
    pooled = fit(table, STAND_IN, h, groups, kernel)
    b, se = float(pooled["b"][0]), float(pooled["se"][0])
    p = ri_p(b, ri_draws(table, STAND_IN, h, groups, draws, (1.0,), kernel))
    by_election = {}
    for e in ELECTIONS:
        one = fit(table, STAND_IN, h, [[e]], kernel)
        by_election[f"e{e}"] = {"b": float(one["b"][0]), "se": float(one["se"][0])}
    return {
        "fail": placebo_fail(b, p) if math.isfinite(b) and math.isfinite(p) else None,
        "b": b,
        "se": se,
        "ri_p": p,
        "n_units": pooled["n_units"],
        "n_races": pooled["n_races"],
        "by_election": by_election,
    }


def power_at(
    table: pl.DataFrame, draws: np.ndarray, h: float, kernel: str = KERNEL
) -> dict[str, Any]:
    """The H1 difference b_post - b_pre, with `party_held_mayor_lag` as the stand-in outcome.

    MDE = 2.80 x SD of the re-flip draws x sqrt(0.25 / p(1 - p)), p the stand-in's mean.
    """
    groups = [list(PRE), list(POST)]
    b_draws = ri_draws(table, STAND_IN, h, groups, draws, (-1.0, 1.0), kernel)
    finite = b_draws[np.isfinite(b_draws)]
    sd = float(np.std(finite, ddof=1)) if finite.size > 1 else float("nan")
    rows = in_kernel(table, h, kernel).filter(
        pl.col("election").is_in(list(PRE + POST)) & pl.col(STAND_IN).is_not_null()
    )
    mean = float(_col(rows, STAND_IN).mean()) if rows.height else float("nan")
    var = mean * (1 - mean)
    if math.isfinite(var) and var > 0:
        scale = math.sqrt(0.25 / var)
    else:
        scale = float("nan")
    return {
        "sd_h1": sd,
        "var_stand_in": var,
        "scale": scale,
        "mde_h1": MDE_K * sd * scale,
        "mean_stand_in": mean,
    }


# --- Decision 0008's table (information only)


def _gate_0011() -> Any:
    name = "incumbency_gate_0011"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / "explore" / "0011_incumbency_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def window_table(panel: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Decision 0008's grid by the 0011 gate's `choose_window`. It chooses nothing."""
    chosen = _gate_0011().choose_window(panel, draws)
    return {
        "rule_0008_found": chosen["found"],
        "rule_0008_h_pct": chosen["h_pct"],
        "table": {
            label: {key: cell[key] for key in WINDOW_FIELDS}
            for label, cell in chosen["grid"].items()
        },
    }


# --- Results


def _all_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_all_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(v) for v in value)
    if value is None:
        return False
    if isinstance(value, (float, np.floating)):
        return bool(np.isfinite(value))
    return True


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _get(results: dict[str, Any], dotted: str) -> Any:
    node: Any = results
    for part in dotted.split("."):
        node = node[part]
    return node


def _estimates(table: pl.DataFrame, draws: np.ndarray, covariates: Sequence[str]) -> dict:
    return {
        "counts": counts_at(table, H),
        "balance": balance_at(table, draws, H, KERNEL, covariates),
        "placebo": placebo_at(table, draws, H),
        "power": power_at(table, draws, H),
    }


def s2_rows(table: pl.DataFrame) -> tuple[pl.DataFrame, np.ndarray]:
    """The rows with `finalist_eligible` true, and the sorted ids of the races they belong to."""
    kept = table.filter(pl.col("finalist_eligible").fill_null(False))
    return kept, np.unique(kept["race"].to_numpy())


def build_results(panel: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Everything the gate reports. Raises `GateError` if a k1-k4 field is not a number."""
    table = prepare(panel)
    _check_draws(table, draws)
    results = _estimates(table, draws, tuple(BALANCE))
    results["design"] = {"h": H, "kernel": KERNEL, "seed": SEED, "draws": int(draws.shape[0])}
    results["window"] = window_table(panel, draws)

    kept, race_ids = s2_rows(table)
    s2 = _estimates(kept, draws, [c for c in BALANCE if c != "finalist_eligible"])
    # same races, same signs: keep each kept race's column of the draws
    s2["window"] = window_table(
        panel.filter(pl.col("finalist_eligible").fill_null(False)), draws[:, race_ids]
    )
    results["s2_sample"] = s2

    finite = all(
        _all_finite(node)
        for node in (
            results["balance"],
            results["placebo"],
            results["power"],
            s2["balance"],
            s2["placebo"],
            s2["power"],
        )
    )
    results["estimates"] = {"finite": finite}
    results = _clean(results)
    for field in RULE_FIELDS:
        value = _get(results, field)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateError(f"kill-rule field {field} is not a finite number")
    return results


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _section(label: str, r: dict[str, Any], heading: str) -> list[str]:
    """Counts, balance, placebo, power and window table for one sample."""
    counts, bal, plc, power, win = r["counts"], r["balance"], r["placebo"], r["power"], r["window"]
    lines = [
        f"{heading} Races per election inside h ({label})",
        "",
        "| Election | races | rows | ties | eligible-finalist rows |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in ELECTIONS:
        k = f"e{e}"
        lines.append(
            f"| {e} | {counts['races_h'][k]} | {counts['rows_h'][k]} | {counts['ties_h'][k]} "
            f"| {counts['eligible_rows_h'][k]} |"
        )
    lines += [
        "",
        f"Smallest of the four cycles' races at h: {counts['min_cycle_races_h']}.",
        "",
        f"{heading} Balance ({label})",
        "",
        "| Covariate | b | SE | randomisation p | rows | races |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, v in bal["covariates"].items():
        lines.append(
            f"| {name} | {_fmt(v['b'])} | {_fmt(v['se'])} | {_fmt(v['ri_p'])} "
            f"| {v['n_units']} | {v['n_races']} |"
        )
    lines += [
        "",
        f"Omnibus p {_fmt(bal['omnibus_p'])}; smallest p {_fmt(bal['min_p'])} "
        f"({bal['min_p_covariate'] or 'n/a'}).",
        "",
        f"{heading} Placebo: jump in party_held_mayor_lag ({label})",
        "",
        f"b {_fmt(plc['b'])}, SE {_fmt(plc['se'])}, randomisation p {_fmt(plc['ri_p'])}, "
        f"{plc['n_units']} rows in {plc['n_races']} races. placebo.fail = {plc['fail']}.",
        "",
        "| Election | b | SE |",
        "| --- | --- | --- |",
    ]
    for e in ELECTIONS:
        v = plc["by_election"][f"e{e}"]
        lines.append(f"| {e} | {_fmt(v['b'])} | {_fmt(v['se'])} |")
    lines += [
        "",
        f"{heading} Power ({label})",
        "",
        f"SD of b_post - b_pre over the re-flip draws {_fmt(power['sd_h1'])}; MDE = 2.80 x SD x "
        f"sqrt(0.25 / p(1 - p)) = {_fmt(power['mde_h1'])}. The MDE uses `party_held_mayor_lag` "
        f"as a stand-in (mean {_fmt(power['mean_stand_in'])}), scaled to any 0/1 outcome; the "
        "real outcome is not read here.",
        "",
        f"{heading} Decision 0008's table: information only (decision 0017) ({label})",
        "",
        f"Rule 0008 found a window: {win['rule_0008_found']} (h {win['rule_0008_h_pct']}%). "
        "It chooses nothing and stops nothing.",
        "",
        "| Window | races | rows | omnibus p | min p | covariate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, g in win["table"].items():
        lines.append(
            f"| {name} | {g['races']} | {g['units']} | {_fmt(g['omnibus_p'])} "
            f"| {_fmt(g['min_p'])} | {g['min_p_covariate'] or 'n/a'} |"
        )
    return lines + [""]


def summarize(results: dict[str, Any]) -> str:
    d = results["design"]
    lines = [
        f"Design: h = {d['h']}, {d['kernel']} kernel, seed {d['seed']}, {d['draws']} re-flips "
        "(idea 0012, decision 0017). Fixed before any data was read.",
        f"Omnibus balance p {_fmt(results['balance']['omnibus_p'])}; placebo.fail "
        f"{results['placebo']['fail']}; H1 MDE {_fmt(results['power']['mde_h1'])}; smallest "
        f"cycle's races {results['counts']['min_cycle_races_h']}; all finite: "
        f"{results['estimates']['finite']}.",
        "",
    ]
    lines += _section("all rows", results, "##")
    lines += _section("S2 sample: finalist_eligible rows", results["s2_sample"], "##")
    lines += [
        "## Caveats",
        "",
        "- The idea was formed after campaign 0012's gate and reuses idea 0011's data.",
        "- A balance test that passes is not proof of balance.",
        "- Nothing on the exploration half is a finding.",
    ]
    return "\n".join(lines)


# --- Entry point


def _paths(manifest: str, pattern: str) -> list[str]:
    data = json.loads((MANIFESTS / f"{manifest}.json").read_text(encoding="utf-8"))
    hits = sorted(
        f["path"]
        for f in data["files"]
        if re.search(pattern, f["path"]) and not f["path"].startswith("sealed/")
    )
    if not hits:
        raise SystemExit(f"{manifest}: no file matches {pattern}")
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def read(name: str, columns: list[str]) -> pl.DataFrame:
            remote = _paths("mayor_incumbency_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = pl.read_parquet(local, columns=columns)
            local.unlink()
            return frame

        panel = load_panel(read, half)
    draws = sign_draws(n_races(panel))
    results = build_results(panel, draws)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
