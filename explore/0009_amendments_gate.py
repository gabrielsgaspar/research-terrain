"""The amendments gate: window, counts, power, placebos, author link (idea 0009, step s6).

Idea 0009 (`research/ideas/0009-amendments-ballot-box.md`), decisions 0003, 0008 (the window rule)
and 0011 (national scope), campaign `research/campaigns/0009-amendments-ballot-box/campaign.md`,
step s6. The national exploration half only: every panel is restricted to it right after it is
read, before anything else.

The script chooses the close-race window h by decision 0008's balance rule, counts close races,
computes the first stage's power on a pre-election outcome, estimates two placebos and reports the
deputy-author link. It reads no post-election outcome: `READ_COLUMNS` holds the only columns taken
from `panel_A`, `panel_B` and `panel_C` of `amendments_panel`. `author_link` has no `cd_ibge` and
is only counts, so it is read without `restrict`. Its `results.json` carries the six fields that the
kill rules of step s7 read (k1 .. k6).

A race is (`cycle`, `cd_ibge`); a unit is a row. Re-flipping a race multiplies `margin` by -1 and
swaps `win` for every unit of the race. The 2,000 sign vectors (seed 20261115) are drawn once and
reused for every covariate, window and estimate. The model is Y = b win + g margin + d win margin
with deputy fixed effects (within-deputy demeaning), on units with |margin| <= w + EDGE, standard
errors clustered by `cd_ibge` with the factor G/(G-1) x (N-1)/(N-K), K = 3 slopes. Deputies with a
single unit in the sample are absorbed by their fixed effect and leave the fit. Nothing on the
exploration half is a finding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "data" / "manifests" / "build"

# The only columns read from the panels: nothing measured after the mayoral election.
READ_COLUMNS = [
    "cycle",
    "m",
    "cd_ibge",
    "uf",
    "deputy",
    "population_m",
    "round",
    "margin",
    "win",
    "fin_female",
    "fin_age",
    "fin_higher_ed",
    "party_held_mayor",
    "amend_pre_total",
    "amend_pre_pix",
    "share_t0",
]
LINK_COLUMNS = ["cycle", "authors", "deputies", "senators", "ambiguous", "unmatched"]
CYCLES = ("A", "B", "C")
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
CHECK_WINDOW = "w5pct"
COVARIATES = ("fin_female", "fin_age", "fin_higher_ed", "party_held_mayor", "ln_population")
DRAWS = 2000
SEED = 20261115
RULE_P = 0.15
MDE_K = 2.8
EDGE = 1e-12
CHUNK = 64
PTOL = 1e-12
RULE_FIELDS = (
    "window.found",
    "counts.races_h",
    "power.mde_share",
    "placebo.amend_share_abs",
    "placebo.vote_share_abs",
    "link.author_share",
)


class GateError(Exception):
    """The inputs cannot support the gate, or a kill-rule field could not be computed."""


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The three panels, each restricted to the exploration half right after it is read.

    `read(name, columns)` returns one file of `amendments_panel` (`panel_A`, `panel_B`,
    `panel_C`, `author_link`). The author link has no `cd_ibge` and is counts only, so it is
    read without `restrict`.
    """
    parts = []
    for cycle in CYCLES:
        frame = restrict(read(f"panel_{cycle}", READ_COLUMNS), half)
        parts.append(frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8)))
    panel = pl.concat(parts, how="vertical_relaxed")
    return panel, read("author_link", LINK_COLUMNS)


# --- Preparing the panel


def prepare(panel: pl.DataFrame) -> pl.DataFrame:
    """`panel` with `race` (0..R-1 over sorted (`cycle`, `cd_ibge`)), `y_pre` and `ln_population`.

    `y_pre` = `amend_pre_total` / `population_m` x 1,000 (reais per 1,000 inhabitants); null if the
    population is null or 0.
    """
    races = (
        panel.select("cycle", "cd_ibge")
        .unique()
        .sort("cycle", "cd_ibge")
        .with_row_index("race")
        .with_columns(pl.col("race").cast(pl.Int64))
    )
    pop = pl.col("population_m").cast(pl.Float64)
    return panel.join(races, on=["cycle", "cd_ibge"], how="left").with_columns(
        pl.when(pop > 0)
        .then(pl.col("amend_pre_total").cast(pl.Float64) / pop * 1000.0)
        .otherwise(None)
        .alias("y_pre"),
        pl.when(pop > 0).then(pop.log()).otherwise(None).alias("ln_population"),
    )


def n_races(panel: pl.DataFrame) -> int:
    return panel.select("cycle", "cd_ibge").unique().height


def sign_draws(races: int, draws: int = DRAWS, seed: int = SEED) -> np.ndarray:
    """One (`draws`, `races`) matrix of +1/-1, the same for every window and estimate."""
    rng = np.random.default_rng(seed)
    return (rng.integers(0, 2, size=(draws, races), dtype=np.int8) * 2 - 1).astype(np.int8)


def in_window(table: pl.DataFrame, w: float) -> pl.DataFrame:
    return table.filter(pl.col("margin").cast(pl.Float64).abs() <= w + EDGE)


def _chunks(total: int):
    for start in range(0, total, CHUNK):
        yield start, min(start + CHUNK, total)


def _check_draws(table: pl.DataFrame, draws: np.ndarray) -> None:
    if draws.ndim != 2 or draws.shape[1] != n_races(table):
        raise GateError(f"draws must have one column per race ({n_races(table)})")


# --- Balance and the window choice (decision 0008)


def _col(table: pl.DataFrame, name: str) -> np.ndarray:
    return table.get_column(name).cast(pl.Float64).fill_null(float("nan")).to_numpy()


def balance(table: pl.DataFrame, draws: np.ndarray, w: float) -> dict[str, Any]:
    """Win-minus-lose differences in covariate means at window `w`, and randomisation p-values.

    Units with a null covariate leave that covariate only. A raw p is
    (1 + #{|d_draw| >= |d|}) / (draws + 1); the omnibus p is (1 + #{draws whose smallest p <= the
    observed smallest p}) / (draws + 1), each draw's p taken from the same draws.
    """
    sub = in_window(table, w)
    n_draws = draws.shape[0]
    rid = sub["race"].to_numpy()
    margin = _col(sub, "margin")
    x = np.column_stack([_col(sub, c) for c in COVARIATES]) if sub.height else np.empty((0, 5))
    k = len(COVARIATES)
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
        flipped = draws[a:b][:, rid].astype(float) * margin
        d_draw[a:b] = diffs((flipped > 0).astype(float))
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

    Returns `grid` (every window's balance), `found` (0 or 1), `h_pct` (None when not found) and
    `h`, the fraction used by the other fields (0.5% when no window is chosen). Step s8 calls it.
    """
    table = prepare(panel)
    _check_draws(table, draws)
    grid = {label: balance(table, draws, w) for label, w in GRID.items()}
    chosen: str | None = None
    for label in GRID:  # smallest first; stop at the first failure
        p = grid[label]["omnibus_p"]
        if not (math.isfinite(p) and p >= RULE_P):
            break
        chosen = label
    if chosen is None:
        return {"grid": grid, "found": 0, "h_pct": None, "h": GRID["w0_5pct"]}
    return {
        "grid": grid,
        "found": 1,
        "h_pct": round(GRID[chosen] * 100, 6),
        "h": GRID[chosen],
    }


# --- Fixed-effects fit and randomisation inference


class Sample:
    """Units of one fit, sorted by deputy, with Y demeaned within deputy."""

    def __init__(
        self,
        y: np.ndarray,
        margin: np.ndarray,
        rid: np.ndarray,
        deputy: np.ndarray,
        cluster: np.ndarray,
    ) -> None:
        _, inv, counts = np.unique(deputy, return_inverse=True, return_counts=True)
        keep = counts[inv] >= 2
        order = np.flatnonzero(keep)[np.argsort(inv[keep], kind="stable")]
        self.y_raw = y[order]
        self.margin = margin[order]
        self.rid = rid[order]
        dep = inv[order]
        self.starts = np.flatnonzero(np.r_[True, dep[1:] != dep[:-1]]) if dep.size else dep
        self.counts = np.diff(np.r_[self.starts, dep.size]) if dep.size else dep
        _, self.cluster = np.unique(cluster[order], return_inverse=True)
        self.n = int(order.size)
        self.g = int(self.cluster.max() + 1) if self.n else 0
        self.y = self.demean(self.y_raw[None, :])[0] if self.n else self.y_raw

    def demean(self, a: np.ndarray) -> np.ndarray:
        """Subtract deputy means along the last axis."""
        sums = np.add.reduceat(a, self.starts, axis=-1)
        means = sums / self.counts
        return a - np.repeat(means, self.counts, axis=-1)

    def design(self, signs: np.ndarray) -> np.ndarray:
        """(draws, n, 3): win, margin and win x margin after re-flipping, demeaned within deputy."""
        m = signs * self.margin
        win = (m > 0).astype(float)
        cols = np.stack([win, m, win * m], axis=-1)
        return np.stack([self.demean(cols[..., i]) for i in range(3)], axis=-1)


def _solve(gram: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Batched normal-equation solve; a singular system gives NaN."""
    try:
        return np.linalg.solve(gram, xy[..., None])[..., 0]
    except np.linalg.LinAlgError:
        out = np.full(xy.shape, np.nan)
        for i in range(xy.shape[0]):
            try:
                out[i] = np.linalg.solve(gram[i], xy[i])
            except np.linalg.LinAlgError:
                pass
        return out


def fe_fit(sample: Sample) -> dict[str, float]:
    """b (coefficient on win) and its SE clustered by `cd_ibge`, factor G/(G-1) (N-1)/(N-K)."""
    nan = {"b": float("nan"), "se": float("nan")}
    if sample.n <= 3:
        return nan
    x = sample.design(np.ones((1, sample.n)))[0]
    gram = x.T @ x
    beta = _solve(gram[None], (x.T @ sample.y)[None])[0]
    if not np.isfinite(beta).all():
        return nan
    resid = sample.y - x @ beta
    scores = x * resid[:, None]
    sums = np.column_stack([np.bincount(sample.cluster, weights=scores[:, i]) for i in range(3)])
    meat = sums.T @ sums
    bread = np.linalg.inv(gram)
    g, n, k = sample.g, sample.n, 3
    if g < 2 or n <= k:
        return {"b": float(beta[0]), "se": float("nan")}
    factor = g / (g - 1) * (n - 1) / (n - k)
    var = factor * (bread @ meat @ bread)[0, 0]
    return {"b": float(beta[0]), "se": float(math.sqrt(var)) if var >= 0 else float("nan")}


def ri_b(sample: Sample, draws: np.ndarray) -> np.ndarray:
    """The win coefficient refitted under every sign vector (NaN where it cannot be fitted)."""
    out = np.full(draws.shape[0], np.nan)
    if sample.n <= 3:
        return out
    for a, b in _chunks(draws.shape[0]):
        s = draws[a:b][:, sample.rid].astype(float)
        x = sample.design(s)
        gram = np.einsum("cni,cnj->cij", x, x)
        xy = np.einsum("cni,n->ci", x, sample.y)
        out[a:b] = _solve(gram, xy)[:, 0]
    return out


def ri_summary(b: float, b_draws: np.ndarray) -> tuple[float, float]:
    """(`ri_p`, `sd_ri`): ri_p = (1 + #{|b_draw| >= |b|}) / (draws + 1); SD of finite draws."""
    if not math.isfinite(b):
        return float("nan"), float("nan")
    with np.errstate(invalid="ignore"):
        hits = int(np.sum(np.abs(b_draws) >= abs(b) - PTOL))
    finite = b_draws[np.isfinite(b_draws)]
    sd = float(np.std(finite, ddof=1)) if finite.size > 1 else float("nan")
    return (1 + hits) / (b_draws.size + 1), sd


def estimate(table: pl.DataFrame, draws: np.ndarray, w: float, outcome: str) -> dict[str, Any]:
    """The model for `outcome` on units at window `w` with a non-null outcome."""
    sub = in_window(table, w).filter(
        pl.col(outcome).is_not_null() & pl.col(outcome).cast(pl.Float64).is_finite()
    )
    nan = float("nan")
    out = {"b": nan, "se": nan, "ri_p": nan, "sd_ri": nan, "mean": nan, "share_abs": nan}
    out["units"] = int(sub.height)
    if sub.height == 0:
        return out
    y = _col(sub, outcome)
    out["mean"] = float(y.mean())
    sample = Sample(
        y,
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    fit = fe_fit(sample)
    out["b"], out["se"] = fit["b"], fit["se"]
    out["ri_p"], out["sd_ri"] = ri_summary(fit["b"], ri_b(sample, draws))
    if out["mean"] > 0:
        out["share_abs"] = abs(fit["b"]) / out["mean"]
    return out


# --- Counts, link, results


def counts_at(table: pl.DataFrame, w: float) -> dict[str, Any]:
    sub = in_window(table, w)
    by_cycle = {}
    for c in CYCLES:
        s = sub.filter(pl.col("cycle") == c)
        by_cycle[c] = {"races_h": n_races(s) if s.height else 0, "units_h": int(s.height)}
    return {
        "races": n_races(sub) if sub.height else 0,
        "units": int(sub.height),
        "deputies": int(sub["deputy"].n_unique()),
        "by_cycle": by_cycle,
    }


def link_stats(link: pl.DataFrame) -> dict[str, Any]:
    """Per cycle: share = deputies / (authors - senators); `author_share` is the smallest."""
    by_cycle: dict[str, Any] = {}
    for c in CYCLES:
        rows = link.filter(pl.col("cycle") == c)
        if rows.height != 1:
            raise GateError(f"author_link must have exactly one row for cycle {c}")
        r = {k: int(rows[k][0]) for k in LINK_COLUMNS[1:]}
        denom = r["authors"] - r["senators"]
        if denom <= 0:
            raise GateError(f"author_link cycle {c}: authors minus senators is {denom}")
        by_cycle[c] = {"share": r["deputies"] / denom, **r}
    return {"author_share": min(v["share"] for v in by_cycle.values()), "by_cycle": by_cycle}


def _all_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_all_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(v) for v in value)
    if isinstance(value, (float, np.floating)):
        return bool(np.isfinite(value))
    return True  # None (h_pct, a covariate name) is not a number that failed


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


def build_results(panel: pl.DataFrame, link: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Everything the gate reports. Raises `GateError` if a kill-rule field is not a number."""
    table = prepare(panel)
    _check_draws(table, draws)
    chosen = choose_window(panel, draws)
    h = chosen["h"]
    at_h = counts_at(table, h)
    at_5 = counts_at(table, GRID[CHECK_WINDOW])
    amend_h = estimate(table, draws, h, "y_pre")
    vote_h = estimate(table, draws, h, "share_t0")
    amend_5 = estimate(table, draws, GRID[CHECK_WINDOW], "y_pre")
    vote_5 = estimate(table, draws, GRID[CHECK_WINDOW], "share_t0")

    def power(e: dict[str, Any]) -> dict[str, float]:
        mde = MDE_K * e["sd_ri"]
        return {"mde": mde, "mde_share": mde / e["mean"] if e["mean"] > 0 else float("nan")}

    link_out = link_stats(link)
    results: dict[str, Any] = {
        "window": {"found": chosen["found"], "h_pct": chosen["h_pct"], "grid": chosen["grid"]},
        "counts": {
            "races_h": at_h["races"],
            "units_h": at_h["units"],
            "deputies_h": at_h["deputies"],
            "min_cycle_races_h": min(v["races_h"] for v in at_h["by_cycle"].values()),
            "by_cycle": at_h["by_cycle"],
            "races_5pct": at_5["races"],
            "units_5pct": at_5["units"],
        },
        "power": {
            **power(amend_h),
            "sd_ri": amend_h["sd_ri"],
            "mean": amend_h["mean"],
            "at_5pct": {"mde_share": power(amend_5)["mde_share"]},
        },
        "placebo": {
            "amend_share_abs": amend_h["share_abs"],
            "amend_b": amend_h["b"],
            "amend_se": amend_h["se"],
            "amend_ri_p": amend_h["ri_p"],
            "amend_mean": amend_h["mean"],
            "vote_share_abs": vote_h["share_abs"],
            "vote_b": vote_h["b"],
            "vote_se": vote_h["se"],
            "vote_ri_p": vote_h["ri_p"],
            "vote_mean": vote_h["mean"],
            "at_5pct": {
                "amend_share_abs": amend_5["share_abs"],
                "vote_share_abs": vote_5["share_abs"],
            },
        },
        "link": link_out,
    }
    results["estimates"] = {"finite": _all_finite(results)}
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
    win, counts, power = results["window"], results["counts"], results["power"]
    placebo, link = results["placebo"], results["link"]
    h = "none (0.5% fails; other fields use 0.5%)" if not win["found"] else f"{win['h_pct']:g}%"
    lines = [
        f"Window h by decision 0008's balance rule: {h}. "
        f"Close races at h: {counts['races_h']} ({counts['units_h']} units, "
        f"{counts['deputies_h']} deputies). First-stage MDE: {_fmt(power['mde_share'])} of the "
        f"pre-election mean. Smallest author-link share: {_fmt(link['author_share'])}.",
        "",
        "## Window table",
        "",
        "| Window | races | units | omnibus p | min p | covariate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, g in win["grid"].items():
        lines.append(
            f"| {label} | {g['races']} | {g['units']} | {_fmt(g['omnibus_p'])} "
            f"| {_fmt(g['min_p'])} | {g['min_p_covariate'] or 'n/a'} |"
        )
    lines += [
        "",
        "## Counts at h",
        "",
        "| Cycle | races | units |",
        "| --- | --- | --- |",
    ]
    for c, v in counts["by_cycle"].items():
        lines.append(f"| {c} | {v['races_h']} | {v['units_h']} |")
    lines += [
        "",
        f"At 5% (reported only): {counts['races_5pct']} races, {counts['units_5pct']} units; "
        f"MDE {_fmt(power['at_5pct']['mde_share'])} of the mean.",
        "",
        "## Power (pre-election amendments, reais per 1,000 inhabitants)",
        "",
        f"SD of b over the draws {_fmt(power['sd_ri'])}; MDE {_fmt(power['mde'])}; "
        f"mean {_fmt(power['mean'])}; MDE share {_fmt(power['mde_share'])}.",
        "",
        "## Placebos at h",
        "",
        "| Outcome | b | SE | ri p | mean | abs b / mean |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| pre-election amendments | {_fmt(placebo['amend_b'])} | {_fmt(placebo['amend_se'])} "
        f"| {_fmt(placebo['amend_ri_p'])} | {_fmt(placebo['amend_mean'])} "
        f"| {_fmt(placebo['amend_share_abs'])} |",
        f"| vote share at t0 | {_fmt(placebo['vote_b'])} | {_fmt(placebo['vote_se'])} "
        f"| {_fmt(placebo['vote_ri_p'])} | {_fmt(placebo['vote_mean'])} "
        f"| {_fmt(placebo['vote_share_abs'])} |",
        "",
        f"At 5% (reported only): amendments {_fmt(placebo['at_5pct']['amend_share_abs'])}, "
        f"vote share {_fmt(placebo['at_5pct']['vote_share_abs'])}.",
        "",
        "## Author link",
        "",
        "| Cycle | share | authors | deputies | senators | ambiguous | unmatched |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c, v in link["by_cycle"].items():
        lines.append(
            f"| {c} | {_fmt(v['share'])} | {v['authors']} | {v['deputies']} | {v['senators']} "
            f"| {v['ambiguous']} | {v['unmatched']} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
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
            remote = _paths("amendments_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = pl.read_parquet(local, columns=columns)
            local.unlink()
            return frame

        panel, link = load_panels(read, half)
    draws = sign_draws(n_races(panel))
    results = build_results(panel, link, draws)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
