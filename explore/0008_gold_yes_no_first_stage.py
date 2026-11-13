"""First stage of idea 0008: does the gold price move garimpo where gold is recorded? (step s1).

The national exploration half (decision 0011), municipality-years 1990-2024. The main estimate is
beta on D_mt = `geo_exposed` x ln_gold_real (year t-1), with `garimpo_share` as the outcome,
municipality and state x year fixed effects, and three controls (`native_share_2004`, ln
`area_km2`, `indigenous_share`) each interacted with a full set of year dummies (one dropped).
`geo_exposed` is 1 if the Geological Survey records any gold occurrence in the municipality, else
0. See `research/ideas/0008-gold-ballot-yes-no.md` and the campaign file
`research/campaigns/0008-gold-ballot-yes-no/campaign.md`, step s1.

The yes/no measure was chosen after seeing campaign 0007's results
(`research/explore-runs/0007/43438404852.md`), so nothing here is a finding.

Inference: municipality-clustered errors (small-sample factor G/(G-1) x (N-1)/(N-K)), Conley errors
at 50, 100 and 200 km (uniform kernel over municipality scores), and randomisation inference
(1,000 draws, seed 20261113, D permuted within state). The clustered errors can over-reject with
one common shock (Moreno-Louzada, Figueira and Picchetti 2025), so the RI p comes first.

It reads `mining_panel` (derived, 1990-2024) and `gold_exposure` (`gold_exposure.parquet` and
`gold_prices.parquet`) and nothing else: no election data, no SIM data, nothing in `sealed/`.
`gold_prices` is national and has no `cd_ibge`, so it is read without `restrict`. It writes the
three fields the kill rules of step s2 read: `first_stage.f_cluster`, `placebo.lead_ratio` and
`estimates.finite`. A non-finite number is written as null, never as NaN or Infinity.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import polars.selectors as cs

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "data" / "manifests" / "build"

YEARS = tuple(range(1990, 2025))
BASE_YEAR = 2000
CUTOFFS_KM = (50, 100, 200)
N_DRAWS = 1000
SEED = 20261113
SENTINEL = 1_000_000_000.0
TOL = 1e-10
MAX_ROUNDS = 1000
RANK_TOL = 1e-9
MAIN = "garimpo_share"
SECONDARY = ("garimpo_gold_share", "garimpo_other_share", "industrial_gold_share", "ln_garimpo_ha")
EARLY = (1990, 2012)
LATE = (2013, 2024)

MINING_COLUMNS = [
    "cd_ibge",
    "year",
    "n_cells",
    "garimpo_gold_ha",
    "garimpo_other_ha",
    "industrial_gold_ha",
    "garimpo_ha",
    "garimpo_share",
    "native_share_2004",
]
EXPOSURE_COLUMNS = [
    "cd_ibge",
    "uf",
    "area_km2",
    "centroid_x_km",
    "centroid_y_km",
    "indigenous_share",
    "geo_gold_per_km2",
    "geo_exposed",
    "title_gold_pre2000_share",
    "title_sand_pre2000_share",
]
PRICE_COLUMNS = ["year", "ln_gold_real", "ln_soy_real"]
EXPOSURE_NEEDED = [
    "geo_gold_per_km2",
    "geo_exposed",
    "title_gold_pre2000_share",
    "title_sand_pre2000_share",
    "centroid_x_km",
    "centroid_y_km",
]


class FirstStageError(Exception):
    """The inputs cannot support the design."""


# --- Linear algebra


class Grouper:
    """Group means for dense group codes 0..G-1."""

    def __init__(self, code: np.ndarray) -> None:
        self.code = code
        self.order = np.argsort(code, kind="stable")
        sorted_code = code[self.order]
        self.starts = np.flatnonzero(np.r_[True, sorted_code[1:] != sorted_code[:-1]])
        self.counts = np.diff(np.r_[self.starts, len(code)]).astype(float)

    def subtract_means(self, x: np.ndarray) -> float:
        """Subtract each group's column means from `x` in place; return the largest mean."""
        sums = np.add.reduceat(x[self.order], self.starts, axis=0)
        means = sums / self.counts[:, None]
        x -= means[self.code]
        return float(np.abs(means).max()) if means.size else 0.0


def demean_two_way(
    x: np.ndarray,
    muni: Grouper,
    state_year: Grouper,
    tol: float = TOL,
    max_rounds: int = MAX_ROUNDS,
) -> np.ndarray:
    """Alternating projections: demean by municipality, then by state x year, until stable.

    Stops when the largest mean subtracted in a round is below `tol`, or after `max_rounds`.
    """
    out = np.array(x, dtype=float).reshape(len(muni.code), -1)
    for _ in range(max_rounds):
        change = max(muni.subtract_means(out), state_year.subtract_means(out))
        if change < tol:
            break
    return out


def control_matrix(controls: np.ndarray, n_years: int) -> np.ndarray:
    """Municipality controls (M x c) times year dummies, first year dropped: (M*T) x c(T-1)."""
    dummies = np.eye(n_years)[:, 1:]
    full = controls[:, None, :, None] * dummies[None, :, None, :]
    return full.reshape(controls.shape[0] * n_years, -1)


class Design:
    """The fixed part of every regression: fixed effects and partialled controls."""

    def __init__(self, state: np.ndarray, n_years: int, controls: np.ndarray) -> None:
        self.n_muni = len(state)
        self.n_years = n_years
        self.n_obs = self.n_muni * n_years
        muni = np.repeat(np.arange(self.n_muni), n_years)
        raw = np.repeat(state, n_years) * n_years + np.tile(np.arange(n_years), self.n_muni)
        _, sy = np.unique(raw, return_inverse=True)
        self.muni = Grouper(muni)
        self.state_year = Grouper(sy.reshape(-1))
        c_t = self.demean(control_matrix(controls, n_years))
        if c_t.shape[1] == 0:
            self.basis, self.rank = np.zeros((self.n_obs, 0)), 0
        else:
            u, s, _ = np.linalg.svd(c_t, full_matrices=False)
            self.rank = int(np.sum(s > s[0] * RANK_TOL)) if s[0] > 0 else 0
            self.basis = u[:, : self.rank]

    def demean(self, x: np.ndarray) -> np.ndarray:
        return demean_two_way(x, self.muni, self.state_year)

    def residualise(self, x: np.ndarray) -> np.ndarray:
        """Remove the fixed effects, then the controls, from each column (N x k)."""
        out = self.demean(x)
        return out - self.basis @ (self.basis.T @ out)


@dataclass
class Fit:
    beta: np.ndarray  # k
    cov: np.ndarray  # k x k, with the small-sample factor
    cov_raw: np.ndarray  # k x k, without it
    dtd: np.ndarray  # k x k
    scores: np.ndarray  # M x k

    @property
    def se(self) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return np.sqrt(np.diag(self.cov))


def fit(design: Design, d_res: np.ndarray, y_res: np.ndarray) -> Fit:
    """OLS of residualised `y_res` (N) on `d_res` (N x k), clustered by municipality."""
    k = d_res.shape[1]
    dtd = d_res.T @ d_res
    if not np.all(np.isfinite(dtd)) or np.trace(dtd) <= 1e-12:
        nan_k, nan_kk = np.full(k, np.nan), np.full((k, k), np.nan)
        return Fit(nan_k, nan_kk, nan_kk, dtd, np.full((design.n_muni, k), np.nan))
    beta = np.linalg.lstsq(dtd, d_res.T @ y_res, rcond=None)[0]
    inv = np.linalg.pinv(dtd)
    resid = y_res - d_res @ beta
    scores = (d_res * resid[:, None]).reshape(design.n_muni, design.n_years, k).sum(axis=1)
    cov_raw = inv @ (scores.T @ scores) @ inv
    g, n = design.n_muni, design.n_obs
    dof = n - (k + design.rank)
    factor = (g / (g - 1)) * ((n - 1) / dof) if g > 1 and dof > 0 else np.nan
    return Fit(beta, cov_raw * factor, cov_raw, dtd, scores)


def conley_se(scores: np.ndarray, dtd: float, xy: np.ndarray, cutoff_km: float) -> float:
    """sqrt(sum over pairs within the cutoff of s_m s_m') / dtd, uniform kernel, no factor."""
    total = 0.0
    for lo in range(0, len(scores), 500):
        near = ((xy[lo : lo + 500, None, :] - xy[None, :, :]) ** 2).sum(axis=2) <= cutoff_km**2
        total += float(scores[lo : lo + 500] @ (near @ scores))
    return math.sqrt(total) / dtd if total >= 0 and dtd > 0 else float("nan")


def shock(exposure: np.ndarray, price: np.ndarray) -> np.ndarray:
    """D_mt = D_m x price_t as an (M*T) x 1 column, municipality-major."""
    return (exposure[:, None] * price[None, :]).reshape(-1, 1)


def ri_p_value(observed: float, draws: np.ndarray) -> float:
    """(1 + #{|b_draw| >= |b|}) / (1 + number of draws); NaN if `observed` is not finite."""
    if not math.isfinite(observed):
        return float("nan")
    draws = np.asarray(draws, dtype=float)
    extreme = int(np.sum(np.abs(draws) >= abs(observed) * (1 - 1e-9)))
    return (1 + extreme) / (1 + len(draws))


def ri_p(
    design: Design,
    state: np.ndarray,
    exposure: np.ndarray,
    price: np.ndarray,
    y_res: dict[str, np.ndarray],
    observed: dict[str, float],
    n_draws: int = N_DRAWS,
    seed: int = SEED,
) -> dict[str, float]:
    """Randomisation p for each outcome: permute `exposure` within state, re-estimate beta."""
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(state == s) for s in np.unique(state)]
    draws = {name: np.full(n_draws, np.nan) for name in y_res}
    for i in range(n_draws):
        permuted = exposure.copy()
        for idx in groups:
            permuted[idx] = exposure[rng.permutation(idx)]
        d_res = design.residualise(shock(permuted, price))[:, 0]
        den = float(d_res @ d_res)
        if den <= 1e-12:
            continue
        for name, y in y_res.items():
            draws[name][i] = float(d_res @ y) / den
    return {name: ri_p_value(observed[name], draws[name]) for name in y_res}


# --- The panel


@dataclass
class Panel:
    codes: list[str]
    uf: list[str]  # state name of each municipality
    state: np.ndarray  # state index of each municipality
    n_states: int
    years: np.ndarray
    xy: np.ndarray  # M x 2, Albers km
    controls: np.ndarray  # M x 3
    exposures: dict[str, np.ndarray]  # each M: binary, density, sand
    outcomes: dict[str, np.ndarray]  # each M x T
    ln_gold: np.ndarray  # T: ln_gold_real of year t-1
    ln_soy: np.ndarray  # T
    n_half: int
    dropped: dict[str, int]


def _lagged(prices: pl.DataFrame, column: str) -> np.ndarray:
    by_year = dict(zip(prices["year"].to_list(), prices[column].to_list(), strict=True))
    missing = [y - 1 for y in YEARS if by_year.get(y - 1) is None]
    if missing:
        raise FirstStageError(f"gold_prices has no {column} for years {missing}")
    return np.array([float(by_year[y - 1]) for y in YEARS])


def build_panel(mining: pl.DataFrame, exposure: pl.DataFrame, prices: pl.DataFrame) -> Panel:
    """The balanced municipality-year panel; both tables are already restricted to the half."""
    n_years = len(YEARS)
    mining = (
        mining.with_columns(pl.col("cd_ibge").cast(pl.Utf8), cs.float().fill_nan(None))
        .filter(pl.col("year").is_between(YEARS[0], YEARS[-1]))
        .with_columns(
            (pl.col("garimpo_gold_ha") / (pl.col("n_cells") * 100)).alias("garimpo_gold_share"),
            (pl.col("garimpo_other_ha") / (pl.col("n_cells") * 100)).alias("garimpo_other_share"),
            (pl.col("industrial_gold_ha") / (pl.col("n_cells") * 100)).alias(
                "industrial_gold_share"
            ),
            (1 + pl.col("garimpo_ha")).log().alias("ln_garimpo_ha"),
        )
    )
    outcome_names = [MAIN, *SECONDARY]
    exposure = exposure.with_columns(pl.col("cd_ibge").cast(pl.Utf8), cs.float().fill_nan(None))
    per_muni = mining.group_by("cd_ibge").agg(
        pl.len().alias("n_rows"),
        pl.col("n_cells").min().alias("min_cells"),
        pl.col("n_cells").null_count().alias("null_cells"),
        pl.col("native_share_2004").mean().alias("native_share_2004"),
        pl.col("native_share_2004").null_count().alias("null_native"),
        pl.sum_horizontal(*[pl.col(c).is_null().sum() for c in outcome_names]).alias(
            "null_outcome"
        ),
    )
    codes = pl.concat([mining.select("cd_ibge"), exposure.select("cd_ibge")]).unique()
    info = (
        codes.join(
            exposure.with_columns(pl.lit(True).alias("_in_exposure")), on="cd_ibge", how="left"
        )
        .join(per_muni, on="cd_ibge", how="left")
        .sort("cd_ibge")
    )
    null_control = (
        pl.col("native_share_2004").is_null()
        | (pl.col("null_native") > 0)
        | pl.col("area_km2").is_null()
        | (pl.col("area_km2") <= 0)
        | pl.col("indigenous_share").is_null()
    )
    null_exposure = pl.any_horizontal(*[pl.col(c).is_null() for c in EXPOSURE_NEEDED]) | (
        pl.col("uf").is_null()
    )
    info = info.with_columns(
        pl.when(pl.col("_in_exposure").is_null())
        .then(pl.lit("no_exposure_row"))
        .when(pl.col("n_rows").is_null())
        .then(pl.lit("no_panel_rows"))
        .when((pl.col("min_cells") < 1).fill_null(True) | (pl.col("null_cells") > 0))
        .then(pl.lit("no_cells"))
        .when(null_control.fill_null(True))
        .then(pl.lit("null_controls"))
        .when(null_exposure.fill_null(True))
        .then(pl.lit("null_exposure"))
        .when((pl.col("n_rows") != n_years) | (pl.col("null_outcome") > 0))
        .then(pl.lit("unbalanced"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("_reason")
    )
    dropped_rows = info.filter(pl.col("_reason").is_not_null()).group_by("_reason").len()
    dropped = {r: int(n) for r, n in dropped_rows.iter_rows()}
    kept = info.filter(pl.col("_reason").is_null())
    if kept.is_empty():
        raise FirstStageError("no municipality is left after the sample rules")
    kept_codes = kept["cd_ibge"].to_list()
    rows = mining.filter(pl.col("cd_ibge").is_in(kept_codes)).sort(["cd_ibge", "year"])
    if rows.height != len(kept_codes) * n_years:
        raise FirstStageError("the panel is not balanced after the sample rules")
    if rows["year"].to_list()[:n_years] != list(YEARS):
        raise FirstStageError("the panel years are not 1990..2024")
    ufs = kept["uf"].to_list()
    state_names = sorted(set(ufs))
    state = np.array([state_names.index(u) for u in ufs])

    def col(name: str) -> np.ndarray:
        return kept[name].cast(pl.Float64).to_numpy()

    return Panel(
        codes=kept_codes,
        uf=ufs,
        state=state,
        n_states=len(state_names),
        years=np.array(YEARS),
        xy=np.column_stack([col("centroid_x_km"), col("centroid_y_km")]),
        controls=np.column_stack(
            [col("native_share_2004"), np.log(col("area_km2")), col("indigenous_share")]
        ),
        exposures={
            "binary": col("geo_exposed"),
            "density": col("geo_gold_per_km2"),
            "sand": col("title_sand_pre2000_share"),
        },
        outcomes={
            name: rows[name].cast(pl.Float64).to_numpy().reshape(len(kept_codes), n_years)
            for name in outcome_names
        },
        ln_gold=_lagged(prices, "ln_gold_real"),
        ln_soy=_lagged(prices, "ln_soy_real"),
        n_half=codes.height,
        dropped=dropped,
    )


# --- Pure helpers for the report-only blocks


def _ratio2(beta: float, se: float) -> float:
    return (beta / se) ** 2 if se > 0 and math.isfinite(se) else float("nan")


def _bse(f: Fit, j: int = 0) -> dict[str, float]:
    return {"beta": float(f.beta[j]), "se": float(f.se[j])}


def event_matrix(exposure: np.ndarray, years: np.ndarray, base: int) -> np.ndarray:
    """D_m x 1[year = y] for every year but `base`: (M*T) x (T-1)."""
    cols = [j for j, y in enumerate(years) if y != base]
    out = np.zeros((len(exposure), len(years), len(cols)))
    for k, j in enumerate(cols):
        out[:, j, k] = exposure
    return out.reshape(len(exposure) * len(years), -1)


def lead_ratio(coef: dict[int, float]) -> float:
    """|mean of b_y, y <= 2001| / |mean of b_y, y >= 2002|; SENTINEL if the denominator is 0."""
    lead = [b for y, b in coef.items() if y <= 2001]
    tail = [b for y, b in coef.items() if y >= 2002]
    num, den = abs(float(np.mean(lead))), abs(float(np.mean(tail)))
    if not math.isfinite(num) or not math.isfinite(den):
        return float("nan")
    return SENTINEL if den == 0 else num / den


def top_indices(values: np.ndarray, codes: list[str], k: int) -> list[int]:
    """Indices of the `k` largest values, largest first; ties go to the smaller code."""
    order = sorted(range(len(values)), key=lambda i: (-float(values[i]), codes[i]))
    return order[:k]


def keep_without(n: int, drop: list[int]) -> np.ndarray:
    keep = np.ones(n, dtype=bool)
    keep[drop] = False
    return keep


def density_products(
    density: np.ndarray, share_2006: np.ndarray, share_2007: np.ndarray
) -> np.ndarray:
    """a_m = |E_m x (garimpo_share_2007 - garimpo_share_2006)|."""
    return np.abs(density * (share_2007 - share_2006))


def top_share(values: np.ndarray) -> float:
    """The largest value over the sum of all values."""
    total = float(np.sum(values))
    return float(np.max(values)) / total if total > 0 else float("nan")


def leave_one_state_out(
    state: np.ndarray, state_names: list[str], f_of: Callable[[np.ndarray], float]
) -> tuple[float, str | None]:
    """The smallest F over the fits that leave out each state in turn, and that state's `uf`.

    `f_of` takes a boolean keep-mask over municipalities. Non-finite Fs are skipped; if all are
    non-finite the result is (nan, None). Ties go to the first state in `state_names`.
    """
    best, best_name = float("nan"), None
    for s, name in enumerate(state_names):
        f = f_of(state != s)
        if math.isfinite(f) and (best_name is None or f < best):
            best, best_name = f, name
    return best, best_name


def first_stage_f(
    panel: Panel,
    keep: np.ndarray,
    exposure: np.ndarray,
    year_range: tuple[int, int] | None = None,
) -> float:
    """Clustered F of `exposure` x ln_gold_real(t-1) on `garimpo_share`, on a subset.

    `keep` selects municipalities; `year_range` (inclusive) selects years. The fixed effects and
    the control x year dummies are rebuilt on the subset.
    """
    if int(np.sum(keep)) < 2:
        return float("nan")
    lo, hi = year_range if year_range else (YEARS[0], YEARS[-1])
    cols = np.flatnonzero((panel.years >= lo) & (panel.years <= hi))
    design = Design(panel.state[keep], len(cols), panel.controls[keep])
    y = panel.outcomes[MAIN][keep][:, cols].reshape(-1, 1)
    d_res = design.residualise(shock(exposure[keep], panel.ln_gold[cols]))
    f = fit(design, d_res, design.residualise(y)[:, 0])
    return _ratio2(float(f.beta[0]), float(f.se[0]))


# --- Estimates


def estimate(panel: Panel, n_draws: int = N_DRAWS, seed: int = SEED) -> dict[str, Any]:
    """Every block of `results.json`, before `finalize`."""
    n_munis = len(panel.codes)
    design = Design(panel.state, len(panel.years), panel.controls)
    y_res = {
        name: design.residualise(panel.outcomes[name].reshape(-1)[:, None])[:, 0]
        for name in (MAIN, *SECONDARY)
    }
    exp = panel.exposures
    d_main = design.residualise(shock(exp["binary"], panel.ln_gold))
    main = fit(design, d_main, y_res[MAIN])
    betas = {name: float(fit(design, d_main, y).beta[0]) for name, y in y_res.items()}
    ri = ri_p(design, panel.state, exp["binary"], panel.ln_gold, y_res, betas, n_draws, seed)

    first_stage: dict[str, Any] = {
        **_bse(main),
        "f_cluster": _ratio2(float(main.beta[0]), float(main.se[0])),
        "ri_p": ri[MAIN],
    }
    for km in CUTOFFS_KM:
        first_stage[f"conley_se_{km}km"] = conley_se(
            main.scores[:, 0], float(main.dtd[0, 0]), panel.xy, km
        )
    first_stage.update(
        n_obs=design.n_obs,
        n_munis=design.n_muni,
        n_states=panel.n_states,
        n_exposed=int(np.sum(exp["binary"] == 1.0)),
    )

    d_event = design.residualise(event_matrix(exp["binary"], panel.years, BASE_YEAR))
    event_fit = fit(design, d_event, y_res[MAIN])
    event_years = [int(y) for y in panel.years if y != BASE_YEAR]
    coef = {y: float(b) for y, b in zip(event_years, event_fit.beta, strict=True)}
    event_se = {y: float(s) for y, s in zip(event_years, event_fit.se, strict=True)}

    secondary = {
        name: {**_bse(fit(design, d_main, y_res[name])), "ri_p": ri[name]} for name in SECONDARY
    }

    def one(exposure: np.ndarray, price: np.ndarray) -> Fit:
        return fit(design, design.residualise(shock(exposure, price)), y_res[MAIN])

    placebo_soy, placebo_sand = one(exp["binary"], panel.ln_soy), one(exp["sand"], panel.ln_gold)
    placebo = {
        "lead_ratio": lead_ratio(coef),
        "soy_beta": float(placebo_soy.beta[0]),
        "soy_se": float(placebo_soy.se[0]),
        "sand_beta": float(placebo_sand.beta[0]),
        "sand_se": float(placebo_sand.se[0]),
    }

    # Why the density measure failed: which municipalities carry its 2006 -> 2007 jump.
    share = panel.outcomes[MAIN]
    j06, j07 = YEARS.index(2006), YEARS.index(2007)
    a = density_products(exp["density"], share[:, j06], share[:, j07])
    top5 = top_indices(a, panel.codes, 5)
    everyone = np.ones(n_munis, dtype=bool)
    density = {
        "top5": [{"cd_ibge": panel.codes[i], "uf": panel.uf[i]} for i in top5],
        "top1_share": top_share(a),
        "f_drop_top1": first_stage_f(panel, keep_without(n_munis, top5[:1]), exp["density"]),
        "f_drop_top5": first_stage_f(panel, keep_without(n_munis, top5), exp["density"]),
    }

    # How sturdy the yes/no result is.
    state_names = sorted(set(panel.uf))
    loso_f, loso_state = leave_one_state_out(
        panel.state, state_names, lambda keep: first_stage_f(panel, keep, exp["binary"])
    )
    top_2024 = top_indices(share[:, -1], panel.codes, 5)
    sturdy = {
        "loso_min_f": loso_f,
        "loso_min_state": loso_state,
        "f_drop_top5_garimpo": first_stage_f(panel, keep_without(n_munis, top_2024), exp["binary"]),
        "f_1990_2012": first_stage_f(panel, everyone, exp["binary"], EARLY),
        "f_2013_2024": first_stage_f(panel, everyone, exp["binary"], LATE),
    }

    return {
        "first_stage": first_stage,
        "event": {
            "coef": {f"y{y}": b for y, b in coef.items()},
            "se": {f"y{y}": s for y, s in event_se.items()},
        },
        "placebo": placebo,
        "secondary": secondary,
        "density": density,
        "sturdy": sturdy,
    }


def _clean(value: Any, bad: list[int]) -> Any:
    """Nested dicts and lists with every non-finite float turned into None (counted in `bad`)."""
    if isinstance(value, dict):
        return {str(k): _clean(v, bad) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, bad) for v in value]
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    if not math.isfinite(number):
        bad.append(1)
        return None
    return number


def finalize(results: dict[str, Any]) -> dict[str, Any]:
    """Standard-JSON results: non-finite numbers become null and `estimates.finite` is set.

    `estimates.finite` is false if any number was non-finite or the lead-ratio sentinel fired.
    """
    bad: list[int] = []
    clean = _clean(results, bad)
    lead = clean.get("placebo", {}).get("lead_ratio")
    sentinel = lead is not None and lead == SENTINEL
    clean["estimates"] = {"finite": not bad and not sentinel}
    return clean


def build_results(
    mining: pl.DataFrame,
    exposure: pl.DataFrame,
    prices: pl.DataFrame,
    half: frozenset[str],
    n_draws: int = N_DRAWS,
) -> tuple[dict[str, Any], Panel]:
    """Restrict every table with a `cd_ibge` to the half, then build the panel and estimate.

    `prices` is national and has no `cd_ibge`, so it is not restricted.
    """
    mining = restrict(mining, half)
    exposure = restrict(exposure, half)
    panel = build_panel(mining, exposure, prices)
    return finalize(estimate(panel, n_draws)), panel


# --- Summary


def _f(x: Any, digits: int = 4) -> str:
    return "n/a" if x is None else f"{x:.{digits}g}"


def _summary(results: dict[str, Any], panel: Panel) -> str:
    fs, ev, pl_, sec = (
        results["first_stage"],
        results["event"],
        results["placebo"],
        results["secondary"],
    )
    de, st = results["density"], results["sturdy"]
    lines = [
        "## First stage of idea 0008: gold price x gold recorded (yes/no) on garimpo",
        "",
        f"The main estimate is beta = {_f(fs['beta'])} (RI p = {_f(fs['ri_p'])}, "
        f"F = {_f(fs['f_cluster'])}) for `garimpo_share` (0 to 1) on D x ln(real gold price, t-1), "
        f"D = 1 if the Survey records gold ({fs['n_exposed']:,} of {fs['n_munis']:,} "
        "municipalities).",
        "",
        "The yes/no measure was chosen after seeing campaign 0007's results "
        "(`research/explore-runs/0007/43438404852.md`), so nothing here is a finding.",
        "",
        "Clustered errors can over-reject with one common shock (Moreno-Louzada, Figueira and "
        "Picchetti 2025), so the randomisation p comes first.",
        "",
        f"- {fs['n_munis']:,} municipalities, {fs['n_states']} states, {fs['n_obs']:,} "
        "municipality-years, 1990-2024",
        f"- RI p = {_f(fs['ri_p'])} (1,000 draws, seed {SEED}, D permuted within state)",
        f"- clustered SE = {_f(fs['se'])}, F = {_f(fs['f_cluster'])}",
        f"- Conley SE: 50 km {_f(fs['conley_se_50km'])}, 100 km {_f(fs['conley_se_100km'])}, "
        f"200 km {_f(fs['conley_se_200km'])}",
        "",
        "### Event study (base year 2000; clustered SE)",
        "",
        "| Year | b | SE | ln real gold price, year-1 |",
        "| --- | --- | --- | --- |",
    ]
    for j, y in enumerate(panel.years):
        if y == BASE_YEAR:
            continue
        lines.append(
            f"| {y} | {_f(ev['coef'][f'y{y}'])} | {_f(ev['se'][f'y{y}'])} | "
            f"{_f(float(panel.ln_gold[j]))} |"
        )
    top5 = ", ".join(f"{t['cd_ibge']} ({t['uf']})" for t in de["top5"])
    lines += [
        "",
        f"Lead ratio (|mean 1990-2001| / |mean 2002-2024|): {_f(pl_['lead_ratio'])}.",
        "",
        "### Report-only blocks",
        "",
    ]
    for name, block in sec.items():
        lines.append(
            f"- Outcome `{name}`: beta {_f(block['beta'])}, SE {_f(block['se'])}, "
            f"RI p {_f(block['ri_p'])}"
        )
    lines += [
        f"- Placebo price (soy): beta {_f(pl_['soy_beta'])}, SE {_f(pl_['soy_se'])}",
        f"- Placebo exposure (sand titles): beta {_f(pl_['sand_beta'])}, SE {_f(pl_['sand_se'])}",
        f"- Density measure: top five by |E x change in garimpo_share 2006-2007|: {top5}; "
        f"top one is {_f(de['top1_share'])} of the sum; density F without the top one "
        f"{_f(de['f_drop_top1'])}, without the top five {_f(de['f_drop_top5'])}",
        f"- Leave one state out: smallest F {_f(st['loso_min_f'])} "
        f"(state left out: {st['loso_min_state'] or 'n/a'})",
        f"- F without the five largest 2024 `garimpo_share` municipalities: "
        f"{_f(st['f_drop_top5_garimpo'])}",
        f"- F on 1990-2012 {_f(st['f_1990_2012'])}; F on 2013-2024 {_f(st['f_2013_2024'])}",
        "",
        f"### Sample: {len(panel.codes):,} of {panel.n_half:,} municipalities kept",
        "",
    ]
    if panel.dropped:
        lines += [f"- dropped, {reason}: {n:,}" for reason, n in sorted(panel.dropped.items())]
    else:
        lines.append("- none dropped")
    lines += ["", f"All numbers finite: {results['estimates']['finite']}."]
    return "\n".join(lines)


# --- Reading from GCS


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


def read_one(
    store: GCSStore, tmp: Path, manifest: str, pattern: str, columns: list[str]
) -> pl.DataFrame:
    """One built file with named columns; the caller restricts."""
    remote = _paths(manifest, pattern)[0]
    local = tmp / Path(remote).name
    store.download(remote, local)
    frame = pl.read_parquet(local, columns=columns)
    local.unlink()
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:
        where = Path(tmp)
        exposure = read_one(
            store, where, "gold_exposure", r"gold_exposure\.parquet$", EXPOSURE_COLUMNS
        )
        prices = read_one(store, where, "gold_exposure", r"gold_prices\.parquet$", PRICE_COLUMNS)
        mining = pl.concat(
            [
                restrict(
                    read_one(
                        store, where, "mining_panel", rf"mining_panel_{y}\.parquet$", MINING_COLUMNS
                    ),
                    half,
                )
                for y in YEARS
            ]
        )
    results, panel = build_results(mining, exposure, prices, half)
    write_results(args.out_dir, _summary(results, panel), results)


if __name__ == "__main__":
    main()
