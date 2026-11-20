"""The incumbency gate: window, races per election, H1 power and the lagged placebo (idea 0011, s5).

Idea 0011 (`research/ideas/0011-who-gains-from-pix.md`), decisions 0003, 0008 (the window rule) and
0011 (national scope), campaign `research/campaigns/0012-who-gains-from-pix/campaign.md`, step s5.
The national exploration half only: every panel file is restricted to it right after it is read,
before anything else.

The script chooses the close-race window h by decision 0008's balance rule, counts close races per
election, computes the minimum detectable H1 difference and estimates the placebo jump in
`party_held_mayor_lag`. It reads no outcome at e+4 and no amendment money: `READ_COLUMNS` holds the
only columns taken from `mayor_incumbency_panel`. Its `results.json` carries the five fields that
the kill rules of step s6 read (k1 .. k5). Step s7 reuses `choose_window`, `sign_draws`, `fit` and
`ri_draws`.

A race is (`election`, `cd_ibge`) with two rows, one per finalist; the two margins add to 0. A
re-flip multiplies both margins of a race by one sign and recomputes `win` as flipped margin > 0.
The 2,000 sign vectors (seed 20261120) are drawn once and reused for every window and estimate. The
model is, per election e, a_e + g_e margin + d_e win margin, plus one `win` coefficient b_G per
group G of elections, fitted by OLS on rows with |margin| <= h, standard errors clustered by
`cd_ibge` with the factor G_c/(G_c-1) x (N-1)/(N-K). Nothing on the exploration half is a finding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
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
GRID: dict[str, float] = {
    "w0_5pct": 0.005,
    "w1pct": 0.01,
    "w2pct": 0.02,
    "w3pct": 0.03,
    "w4pct": 0.04,
    "w5pct": 0.05,
    "w7_5pct": 0.075,
    "w10pct": 0.10,
}
COVARIATES = ("fin_female", "fin_age", "fin_higher_ed", "party_held_mayor_lag")
STAND_IN = "party_held_mayor_lag"
DRAWS = 2000
SEED = 20261120
RULE_P = 0.15
MDE_K = 3.083  # z 0.9875 + z 0.80: two-sided alpha 0.025, power 80%
EDGE = 1e-12
CHUNK = 64
PTOL = 1e-12
RULE_FIELDS = (
    "window.found",
    "counts.min_cycle_races_h",
    "power.mde_h1",
    "placebo.lag_abs",
)


class GateError(Exception):
    """The inputs cannot support the gate, or a kill-rule field could not be computed."""


# --- Reading


def load_panel(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """The five election panels, each restricted to the exploration half right after it is read.

    `read(name, columns)` returns one file of `mayor_incumbency_panel` (`panel_2004` ...).
    """
    parts = []
    for election in ELECTIONS:
        frame = restrict(read(f"panel_{election}", READ_COLUMNS), half)
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
    """One (`draws`, `races`) matrix of +1/-1, the same for every window and estimate."""
    rng = np.random.default_rng(seed)
    return (rng.integers(0, 2, size=(draws, races), dtype=np.int8) * 2 - 1).astype(np.int8)


def flip(margin: np.ndarray, race: np.ndarray, signs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Re-flip: margin x the sign of its race, and `win` = flipped margin > 0.

    `signs` holds one sign per race, either one vector or a (draws, races) matrix.
    """
    flipped = signs[..., race].astype(float) * margin
    return flipped, flipped > 0


def in_window(table: pl.DataFrame, w: float) -> pl.DataFrame:
    return table.filter(pl.col("margin").cast(pl.Float64).abs() <= w + EDGE)


def _chunks(total: int):
    for start in range(0, total, CHUNK):
        yield start, min(start + CHUNK, total)


def _check_draws(table: pl.DataFrame, draws: np.ndarray) -> None:
    if draws.ndim != 2 or draws.shape[1] != n_races(table):
        raise GateError(f"draws must have one column per race ({n_races(table)})")


def _col(table: pl.DataFrame, name: str) -> np.ndarray:
    return table.get_column(name).cast(pl.Float64).fill_null(float("nan")).to_numpy()


# --- Balance and the window choice (decision 0008)


def balance(table: pl.DataFrame, draws: np.ndarray, w: float) -> dict[str, Any]:
    """Win-minus-lose differences in covariate means at window `w`, and randomisation p-values.

    A row with a null covariate leaves that covariate only. A raw p is
    (1 + #{|d_draw| >= |d|}) / (draws + 1); the omnibus p is (1 + #{draws whose smallest p <= the
    observed smallest p}) / (draws + 1), each draw's p taken from the same draws. A tie (margin 0)
    counts as a loser and stays one under any flip.
    """
    sub = in_window(table, w)
    n_draws = draws.shape[0]
    k = len(COVARIATES)
    rid = sub["race"].to_numpy()
    margin = _col(sub, "margin")
    x = np.column_stack([_col(sub, c) for c in COVARIATES]) if sub.height else np.empty((0, k))
    ok = ~np.isnan(x)
    mat = np.hstack([np.where(ok, x, 0.0), ok.astype(float)])
    total = mat.sum(axis=0)

    def diffs(win: np.ndarray) -> np.ndarray:
        s = win @ mat
        n_win = s[..., k:]
        n_lose = total[k:] - n_win
        with np.errstate(divide="ignore", invalid="ignore"):
            return s[..., :k] / n_win - (total[:k] - s[..., :k]) / n_lose

    d_obs = diffs((margin > 0).astype(float))
    d_draw = np.empty((n_draws, k))
    for a, b in _chunks(n_draws):
        _, win = flip(margin, rid, draws[a:b])
        d_draw[a:b] = diffs(win.astype(float))
    abs_draw = np.abs(d_draw)
    p_obs = np.full(k, np.nan)
    p_draw = np.full((n_draws, k), np.inf)
    for j in range(k):
        if np.isnan(d_obs[j]):
            continue
        with np.errstate(invalid="ignore"):
            hits = int(np.sum(abs_draw[:, j] >= abs(d_obs[j]) - PTOL))
        p_obs[j] = (1 + hits) / (n_draws + 1)
        finite = np.isfinite(abs_draw[:, j])
        ordered = np.sort(abs_draw[finite, j])
        at_least = ordered.size - np.searchsorted(ordered, abs_draw[finite, j], side="left")
        p_draw[finite, j] = at_least / (n_draws + 1)
    out: dict[str, Any] = {
        "races": int(np.unique(rid).size),
        "units": int(sub.height),
        "diff": {c: float(d_obs[j]) for j, c in enumerate(COVARIATES)},
        "p": {c: float(p_obs[j]) for j, c in enumerate(COVARIATES)},
        "omnibus_p": float("nan"),
        "min_p": float("nan"),
        "min_p_covariate": None,
    }
    if np.isfinite(p_obs).any():
        j = int(np.nanargmin(p_obs))
        out["min_p"] = float(p_obs[j])
        out["min_p_covariate"] = COVARIATES[j]
        draw_min = p_draw.min(axis=1)
        out["omnibus_p"] = (1 + int(np.sum(draw_min <= p_obs[j] + PTOL))) / (n_draws + 1)
    return out


def choose_window(panel: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Decision 0008's rule: h is the widest window with omnibus p >= 0.15, smaller ones passing.

    All five elections are pooled. Returns `grid` (every window's balance), `by_election` (the
    same table per election, reported only), `found` (0 or 1), `h_pct` (None when not found) and
    `h`, the fraction used by the other fields (0.5% when no window is chosen). Step s7 calls it.
    """
    table = prepare(panel)
    _check_draws(table, draws)
    grid = {label: balance(table, draws, w) for label, w in GRID.items()}
    by_election: dict[str, Any] = {}
    for e in ELECTIONS:
        part = table.filter(pl.col("election") == e)
        by_election[f"e{e}"] = {}
        for label, w in GRID.items():
            b = balance(part, draws, w)
            by_election[f"e{e}"][label] = {"omnibus_p": b["omnibus_p"], "races": b["races"]}
    chosen: str | None = None
    for label in GRID:  # smallest first; stop at the first failure
        p = grid[label]["omnibus_p"]
        if not (math.isfinite(p) and p >= RULE_P):
            break
        chosen = label
    if chosen is None:
        return {
            "grid": grid,
            "by_election": by_election,
            "found": 0,
            "h_pct": None,
            "h": GRID["w0_5pct"],
        }
    return {
        "grid": grid,
        "by_election": by_election,
        "found": 1,
        "h_pct": round(GRID[chosen] * 100, 6),
        "h": GRID[chosen],
    }


# --- The model and randomisation inference


class Sample:
    """Rows of one fit: election, margin, race, cluster and Y, with the group structure."""

    def __init__(
        self,
        y: np.ndarray,
        margin: np.ndarray,
        rid: np.ndarray,
        cluster: np.ndarray,
        election: np.ndarray,
        groups: Sequence[Sequence[int]],
    ) -> None:
        self.y = y
        self.margin = margin
        self.rid = rid
        _, self.cluster = np.unique(cluster, return_inverse=True)
        self.n = int(y.size)
        self.g = int(self.cluster.max() + 1) if self.n else 0
        used = sorted({e for grp in groups for e in grp})
        self.masks = [(election == e).astype(float) for e in used]
        self.group_masks = [np.isin(election, list(grp)).astype(float) for grp in groups]
        self.n_groups = len(groups)
        self.k = 3 * len(used) + self.n_groups

    def design(self, margin: np.ndarray) -> np.ndarray:
        """(n, K): per election 1, margin and win x margin; then one win column per group."""
        win = (margin > 0).astype(float)
        cols = []
        for mask in self.masks:
            cols += [mask, mask * margin, mask * win * margin]
        cols += [win * mask for mask in self.group_masks]
        return np.column_stack(cols)


def _sample(table: pl.DataFrame, y: str, h: float, groups: Sequence[Sequence[int]]) -> Sample:
    used = sorted({e for grp in groups for e in grp})
    sub = in_window(table, h).filter(
        pl.col("election").is_in(used)
        & pl.col(y).is_not_null()
        & pl.col(y).cast(pl.Float64).is_finite()
    )
    return Sample(
        _col(sub, y),
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
        sub["election"].to_numpy(),
        groups,
    )


def _solve(gram: np.ndarray, xy: np.ndarray) -> np.ndarray | None:
    """The normal-equation solution, or None if the system is singular."""
    if np.linalg.matrix_rank(gram) < gram.shape[0]:
        return None
    return np.linalg.solve(gram, xy)


def fit(table: pl.DataFrame, y: str, h: float, groups: Sequence[Sequence[int]]) -> dict[str, Any]:
    """The model for column `y` on rows with |margin| <= h and a non-null `y`.

    `groups` is a list of groups of elections; elections outside every group are dropped. Returns
    `b` and `se` (one per group), `cov` (their covariance matrix), `n_units` and `n_races`. A
    singular design gives NaN. SEs are clustered by `cd_ibge`, factor G_c/(G_c-1) x (N-1)/(N-K).
    """
    sample = _sample(table, y, h, groups)
    n_groups = len(groups)
    out: dict[str, Any] = {
        "b": np.full(n_groups, np.nan),
        "se": np.full(n_groups, np.nan),
        "cov": np.full((n_groups, n_groups), np.nan),
        "n_units": sample.n,
        "n_races": int(np.unique(sample.rid).size),
    }
    if sample.n <= sample.k:
        return out
    x = sample.design(sample.margin)
    gram = x.T @ x
    beta = _solve(gram, x.T @ sample.y)
    if beta is None:
        return out
    out["b"] = beta[-n_groups:].copy()
    if sample.g < 2:
        return out
    resid = sample.y - x @ beta
    scores = x * resid[:, None]
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
    groups: Sequence[Sequence[int]],
    draws: np.ndarray,
    weights: Sequence[float],
) -> np.ndarray:
    """The draws of `weights` . b: the model refitted under every re-flip (NaN where singular)."""
    sample = _sample(table, y, h, groups)
    w = np.asarray(weights, dtype=float)
    if w.size != len(groups):
        raise GateError("weights must have one entry per group")
    out = np.full(draws.shape[0], np.nan)
    if sample.n <= sample.k:
        return out
    for i in range(draws.shape[0]):
        flipped, _ = flip(sample.margin, sample.rid, draws[i])
        x = sample.design(flipped)
        beta = _solve(x.T @ x, x.T @ sample.y)
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


# --- Counts, power, placebo, results


def counts_at(table: pl.DataFrame, w: float) -> dict[str, Any]:
    """Per election at window `w`: races, rows, ties and eligible-finalist rows.

    `min_cycle_races_h` is the smallest race count over 2008, 2012, 2016 and 2020 only.
    """
    sub = in_window(table, w)
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


def power_at(table: pl.DataFrame, draws: np.ndarray, h: float) -> dict[str, Any]:
    """The H1 difference b_post - b_pre with `party_held_mayor_lag` as the stand-in outcome."""
    groups = [list(PRE), list(POST)]
    b_draws = ri_draws(table, STAND_IN, h, groups, draws, (-1.0, 1.0))
    finite = b_draws[np.isfinite(b_draws)]
    sd = float(np.std(finite, ddof=1)) if finite.size > 1 else float("nan")
    rows = in_window(table, h).filter(
        pl.col("election").is_in(list(PRE + POST)) & pl.col(STAND_IN).is_not_null()
    )
    mean = float(_col(rows, STAND_IN).mean()) if rows.height else float("nan")
    return {"sd_h1": sd, "mde_h1": MDE_K * sd, "mean_stand_in": mean}


def placebo_at(table: pl.DataFrame, draws: np.ndarray, h: float) -> dict[str, Any]:
    """The jump in `party_held_mayor_lag`, all five elections as one group; then per election."""
    pooled = fit(table, STAND_IN, h, [list(ELECTIONS)])
    b, se = float(pooled["b"][0]), float(pooled["se"][0])
    p = ri_p(b, ri_draws(table, STAND_IN, h, [list(ELECTIONS)], draws, (1.0,)))
    by_election = {}
    for e in ELECTIONS:
        one = fit(table, STAND_IN, h, [[e]])
        by_election[f"e{e}"] = {"b": float(one["b"][0]), "se": float(one["se"][0])}
    return {
        "lag": {
            "b": b,
            "se": se,
            "ri_p": p,
            "n_units": pooled["n_units"],
            "n_races": pooled["n_races"],
        },
        "lag_abs": abs(b),
        "by_election": by_election,
    }


def _all_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_all_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(v) for v in value)
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


def build_results(panel: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Everything the gate reports. Raises `GateError` if a k1-k4 field is not a number."""
    table = prepare(panel)
    _check_draws(table, draws)
    chosen = choose_window(panel, draws)
    h = chosen["h"]
    at_h = counts_at(table, h)
    at_rows = in_window(table, h)

    def mean_of(name: str) -> float:
        values = _col(at_rows, name)
        values = values[np.isfinite(values)]
        return float(values.mean()) if values.size else float("nan")

    results: dict[str, Any] = {
        "window": {
            "found": chosen["found"],
            "h_pct": chosen["h_pct"],
            "grid": chosen["grid"],
            "by_election": chosen["by_election"],
        },
        "counts": at_h,
        "power": power_at(table, draws, h),
        "placebo": placebo_at(table, draws, h),
        "descriptive": {
            "ln_pop_mean_h": mean_of("ln_pop"),
            "n_mayor_cands_mean_h": mean_of("n_mayor_cands"),
        },
    }
    finite = _all_finite(results["power"]) and _all_finite(results["placebo"])
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


def summarize(results: dict[str, Any]) -> str:
    win, counts = results["window"], results["counts"]
    power, placebo = results["power"], results["placebo"]
    h = "none (0.5% fails; other fields use 0.5%)" if not win["found"] else f"{win['h_pct']:g}%"
    lag = placebo["lag"]
    lines = [
        f"Window h by decision 0008's balance rule: {h}. Smallest of the four cycles' close "
        f"races at h: {counts['min_cycle_races_h']}. H1 MDE: {_fmt(power['mde_h1'])}. "
        f"Placebo |b| in party_held_mayor_lag: {_fmt(placebo['lag_abs'])}.",
        "",
        "## Window table",
        "",
        "| Window | races | rows | omnibus p | min p | covariate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, g in win["grid"].items():
        lines.append(
            f"| {label} | {g['races']} | {g['units']} | {_fmt(g['omnibus_p'])} "
            f"| {_fmt(g['min_p'])} | {g['min_p_covariate'] or 'n/a'} |"
        )
    lines += [
        "",
        "## Races per election at h",
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
        "## Power",
        "",
        f"SD of b_post - b_pre over the re-flip draws {_fmt(power['sd_h1'])}; "
        f"MDE = 3.083 x SD = {_fmt(power['mde_h1'])}. The MDE uses `party_held_mayor_lag` as a "
        f"stand-in for the outcome (its mean on these rows is {_fmt(power['mean_stand_in'])}); "
        "the real outcome is not read here.",
        "",
        "## Placebo: jump in party_held_mayor_lag at h",
        "",
        f"b {_fmt(lag['b'])}, SE {_fmt(lag['se'])}, randomisation p {_fmt(lag['ri_p'])}, "
        f"{lag['n_units']} rows in {lag['n_races']} races.",
        "",
        "| Election | b | SE |",
        "| --- | --- | --- |",
    ]
    for e in ELECTIONS:
        v = placebo["by_election"][f"e{e}"]
        lines.append(f"| {e} | {_fmt(v['b'])} | {_fmt(v['se'])} |")
    lines += [
        "",
        "## Caveats",
        "",
        "- The question was formed after campaign 0011's exploration-half results.",
        "- A placebo that passes is not proof of balance.",
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
