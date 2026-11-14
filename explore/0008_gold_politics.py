"""Politics reduced forms of idea 0008: does the gold price reshape local politics? (step s9).

The national exploration half (decision 0011), municipality x election 2000-2024. The regressor is
D_me = `geo_exposed` x P_e, with P_e the mean of `ln_gold_real` over the four years before the
election (e-4..e-1). `geo_exposed` is 1 if the Geological Survey records any gold occurrence in the
municipality, else 0. Fixed effects: municipality and state x election. Controls: ln `area_km2` and
`indigenous_share`, each times election dummies. See `research/ideas/0008-gold-ballot-yes-no.md` and
the campaign file `research/campaigns/0008-gold-ballot-yes-no/campaign.md`, step s9.

Nine outcomes of `politics_panel`, each on its own elections. Each outcome is estimated on the
municipalities that have a non-missing value at every one of its elections (a balanced panel);
`n_munis` says how many. Outcome 8, `mining_money_share`, is estimated only if at least two of the
elections 2004, 2008 and 2012 have at least 1,000 exploration-half receipts with a CNAE (a rule
fixed before any run); otherwise `money.skipped` is true and it leaves the family.

For each outcome: beta and municipality-clustered SE (small-sample factor G/(G-1) x (N-1)/(N-K)),
Conley SEs at 50, 100 and 200 km (uniform kernel), randomisation inference (1,000 draws, seed
20261111, E permuted within state), Benjamini-Hochberg q across the family, an event study, two
placebos, two robustness exposures, a legal-regime split and a legal-access interaction.

The estimation code is copied from `explore/0007_gold_first_stage.py` and
`explore/0008_gold_yes_no_first_stage.py`, not imported. It reads `politics_panel` (derived) and
`gold_exposure` (`gold_exposure.parquet` and `gold_prices.parquet`) and nothing else: no MapBiomas,
no `mining_panel`, nothing in `sealed/`. `gold_prices` is national and has no `cd_ibge`, so it is
read without `restrict`. It writes `estimates.finite`, the field kill rule k1 of step s10 reads. A
non-finite number is written as null, never as NaN or Infinity.

The yes/no measure was chosen after seeing earlier results, so nothing here is a finding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
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

ELECTIONS = (2000, 2004, 2008, 2012, 2016, 2020, 2024)
CUTOFFS_KM = (50, 100, 200)
N_DRAWS = 1000
SEED = 20261111
TOL = 1e-10
MAX_ROUNDS = 1000
RANK_TOL = 1e-9
MONEY = "mining_money_share"
MONEY_ELECTIONS = (2004, 2008, 2012)
MONEY_MIN_RECEIPTS = 1000
MONEY_MIN_ELECTIONS = 2
PRE_LAST = 2012  # regimes: e <= 2012 against e >= 2016 (the "good faith" period)
GOODFAITH_FIRST = 2016

LATE = tuple(e for e in ELECTIONS if e >= 2004)
# The nine outcomes, in the issue's order, with their own elections.
OUTCOMES: dict[str, tuple[int, ...]] = {
    "cands_per_seat": ELECTIONS,
    "mining_cand_share": ELECTIONS,
    "enc_mayor": ELECTIONS,
    "margin_mayor": ELECTIONS,
    "seat_turnover": LATE,
    "mining_councillor_share": ELECTIONS,
    "incumbent_reelected": LATE,
    MONEY: MONEY_ELECTIONS,
    "homicide_rate": ELECTIONS,
}

POLITICS_COLUMNS = ["cd_ibge", *OUTCOMES, "n_receipts_with_cnae"]
EXPOSURE_COLUMNS = [
    "cd_ibge",
    "uf",
    "area_km2",
    "centroid_x_km",
    "centroid_y_km",
    "indigenous_share",
    "geo_exposed",
    "geo_n_gold",
    "geo_gold_per_km2",
    "geo_gold_indigenous_share",
    "title_gold_pre2000_share",
    "title_sand_pre2000_share",
]
PRICE_COLUMNS = ["year", "ln_gold_real", "ln_soy_real"]
EXPOSURE_NEEDED = [
    "uf",
    "area_km2",
    "centroid_x_km",
    "centroid_y_km",
    "indigenous_share",
    "geo_exposed",
    "geo_n_gold",
    "geo_gold_per_km2",
    "geo_gold_indigenous_share",
    "title_gold_pre2000_share",
    "title_sand_pre2000_share",
]


class PoliticsError(Exception):
    """The inputs cannot support the design."""


# --- Linear algebra (copied from the 0008 s1 script)


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
    """Alternating projections: demean by municipality, then by state x election, until stable."""
    out = np.array(x, dtype=float).reshape(len(muni.code), -1)
    for _ in range(max_rounds):
        change = max(muni.subtract_means(out), state_year.subtract_means(out))
        if change < tol:
            break
    return out


def control_matrix(controls: np.ndarray, n_periods: int) -> np.ndarray:
    """Municipality controls (M x c) times period dummies, first dropped: (M*T) x c(T-1)."""
    dummies = np.eye(n_periods)[:, 1:]
    full = controls[:, None, :, None] * dummies[None, :, None, :]
    return full.reshape(controls.shape[0] * n_periods, -1)


class Design:
    """The fixed part of every regression: fixed effects and partialled controls."""

    def __init__(self, state: np.ndarray, n_periods: int, controls: np.ndarray) -> None:
        self.n_muni = len(state)
        self.n_periods = n_periods
        self.n_obs = self.n_muni * n_periods
        muni = np.repeat(np.arange(self.n_muni), n_periods)
        raw = np.repeat(state, n_periods) * n_periods + np.tile(np.arange(n_periods), self.n_muni)
        _, sy = np.unique(raw, return_inverse=True)
        self.muni = Grouper(muni)
        self.state_year = Grouper(sy.reshape(-1))
        c_t = self.demean(control_matrix(controls, n_periods))
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
        return Fit(nan_k, nan_kk, dtd, np.full((design.n_muni, k), np.nan))
    beta = np.linalg.lstsq(dtd, d_res.T @ y_res, rcond=None)[0]
    inv = np.linalg.pinv(dtd)
    resid = y_res - d_res @ beta
    scores = (d_res * resid[:, None]).reshape(design.n_muni, design.n_periods, k).sum(axis=1)
    cov_raw = inv @ (scores.T @ scores) @ inv
    g, n = design.n_muni, design.n_obs
    dof = n - (k + design.rank)
    factor = (g / (g - 1)) * ((n - 1) / dof) if g > 1 and dof > 0 else np.nan
    return Fit(beta, cov_raw * factor, dtd, scores)


def conley_se(scores: np.ndarray, dtd: float, xy: np.ndarray, cutoff_km: float) -> float:
    """sqrt(sum over pairs within the cutoff of s_m s_m') / dtd, uniform kernel, no factor."""
    total = 0.0
    for lo in range(0, len(scores), 500):
        near = ((xy[lo : lo + 500, None, :] - xy[None, :, :]) ** 2).sum(axis=2) <= cutoff_km**2
        total += float(scores[lo : lo + 500] @ (near @ scores))
    return math.sqrt(total) / dtd if total >= 0 and dtd > 0 else float("nan")


def shock(exposure: np.ndarray, price: np.ndarray) -> np.ndarray:
    """D_me = E_m x price_e as an (M*T) x 1 column, municipality-major."""
    return (exposure[:, None] * price[None, :]).reshape(-1, 1)


def event_matrix(exposure: np.ndarray, elections: tuple[int, ...], base: int) -> np.ndarray:
    """E_m x 1[election = e] for every election but `base`: (M*T) x (T-1)."""
    cols = [j for j, e in enumerate(elections) if e != base]
    out = np.zeros((len(exposure), len(elections), len(cols)))
    for k, j in enumerate(cols):
        out[:, j, k] = exposure
    return out.reshape(len(exposure) * len(elections), -1)


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
    y_res: np.ndarray,
    observed: float,
    n_draws: int = N_DRAWS,
    seed: int = SEED,
) -> float:
    """Randomisation p: permute `exposure` within state, re-estimate beta."""
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(state == s) for s in np.unique(state)]
    draws = np.full(n_draws, np.nan)
    for i in range(n_draws):
        permuted = exposure.copy()
        for idx in groups:
            permuted[idx] = exposure[rng.permutation(idx)]
        d_res = design.residualise(shock(permuted, price))[:, 0]
        den = float(d_res @ d_res)
        if den > 1e-12:
            draws[i] = float(d_res @ y_res) / den
    return ri_p_value(observed, draws)


def bh(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg q-values for the finite p-values; NaN stays NaN and is not counted."""
    finite = [i for i, p in enumerate(pvals) if math.isfinite(p)]
    m = len(finite)
    out = [float("nan")] * len(pvals)
    order = sorted(finite, key=lambda i: pvals[i])
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        out[i] = running
    return out


# --- Prices and the money rule


def window_mean(prices: pl.DataFrame, column: str, election: int) -> float:
    """Mean of `column` over the years election-4 .. election-1."""
    by_year = dict(zip(prices["year"].to_list(), prices[column].to_list(), strict=True))
    values = [by_year.get(y) for y in range(election - 4, election)]
    if any(v is None or not math.isfinite(float(v)) for v in values):
        raise PoliticsError(
            f"gold_prices has no complete {column} for {election - 4}..{election - 1}"
        )
    return float(np.mean([float(v) for v in values]))


def money_counts(politics: dict[int, pl.DataFrame]) -> dict[int, int]:
    """`n_receipts_with_cnae` summed over the exploration-half rows of each money election."""
    counts: dict[int, int] = {}
    for e in MONEY_ELECTIONS:
        frame = politics.get(e)
        counts[e] = 0 if frame is None else int(frame["n_receipts_with_cnae"].fill_null(0).sum())
    return counts


def money_rule(counts: dict[int, int]) -> bool:
    """True if outcome 8 is skipped: fewer than two elections reach 1,000 receipts with a CNAE."""
    reached = sum(1 for n in counts.values() if n >= MONEY_MIN_RECEIPTS)
    return reached < MONEY_MIN_ELECTIONS


# --- The panel


@dataclass
class Panel:
    codes: list[str]
    state: np.ndarray  # state index of each municipality
    xy: np.ndarray  # M x 2, Albers km
    controls: np.ndarray  # M x 2: ln area, indigenous share
    exposures: dict[str, np.ndarray]  # each M: binary, density, titles, sand, indigenous
    outcomes: dict[str, np.ndarray]  # each M x 7 (ELECTIONS), NaN where missing
    ln_gold: np.ndarray  # 7: mean ln_gold_real over e-4..e-1
    ln_soy: np.ndarray  # 7
    n_half: int
    dropped: dict[str, int]


def build_panel(
    politics: dict[int, pl.DataFrame], exposure: pl.DataFrame, prices: pl.DataFrame
) -> Panel:
    """The municipality x election panel; every table is already restricted to the half."""
    exposure = exposure.with_columns(pl.col("cd_ibge").cast(pl.Utf8), cs.float().fill_nan(None))
    # The indigenous share of gold is 0 where the Survey records no gold.
    exposure = exposure.with_columns(
        pl.when(pl.col("geo_n_gold") == 0)
        .then(pl.col("geo_gold_indigenous_share").fill_null(0.0))
        .otherwise(pl.col("geo_gold_indigenous_share"))
        .alias("geo_gold_indigenous_share")
    )
    bad = pl.any_horizontal(*[pl.col(c).is_null() for c in EXPOSURE_NEEDED]) | (
        pl.col("area_km2").fill_null(0) <= 0
    )
    exposure = exposure.unique(subset="cd_ibge", keep="first").sort("cd_ibge")
    bad_rows = exposure.select(bad.alias("bad"))["bad"]
    dropped = {"null_exposure_or_controls": int(bad_rows.sum())}
    kept = exposure.filter(~bad_rows)
    if kept.is_empty():
        raise PoliticsError("no municipality is left after the sample rules")
    codes = kept["cd_ibge"].to_list()
    ufs = kept["uf"].to_list()
    state_names = sorted(set(ufs))

    def col(name: str) -> np.ndarray:
        return kept[name].cast(pl.Float64).to_numpy()

    outcomes = {name: np.full((len(codes), len(ELECTIONS)), np.nan) for name in OUTCOMES}
    base = kept.select("cd_ibge")
    for j, e in enumerate(ELECTIONS):
        frame = politics.get(e)
        if frame is None:
            continue
        frame = frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8), cs.float().fill_nan(None))
        joined = base.join(frame.unique(subset="cd_ibge", keep="first"), on="cd_ibge", how="left")
        for name in OUTCOMES:
            if name in joined.columns:
                outcomes[name][:, j] = joined[name].cast(pl.Float64).fill_null(np.nan).to_numpy()
    return Panel(
        codes=codes,
        state=np.array([state_names.index(u) for u in ufs]),
        xy=np.column_stack([col("centroid_x_km"), col("centroid_y_km")]),
        controls=np.column_stack([np.log(col("area_km2")), col("indigenous_share")]),
        exposures={
            "binary": col("geo_exposed"),
            "density": col("geo_gold_per_km2"),
            "titles": col("title_gold_pre2000_share"),
            "sand": col("title_sand_pre2000_share"),
            "indigenous": col("geo_gold_indigenous_share"),
        },
        outcomes=outcomes,
        ln_gold=np.array([window_mean(prices, "ln_gold_real", e) for e in ELECTIONS]),
        ln_soy=np.array([window_mean(prices, "ln_soy_real", e) for e in ELECTIONS]),
        n_half=exposure.height,
        dropped=dropped,
    )


# --- Estimates


def _diff(f: Fit) -> tuple[float, float]:
    """b0 - b1 and its clustered SE from the joint covariance."""
    beta = float(f.beta[0] - f.beta[1])
    var = float(f.cov[0, 0] + f.cov[1, 1] - 2 * f.cov[0, 1])
    se = math.sqrt(var) if var >= 0 else float("nan")
    return beta, se


def estimate_outcome(
    panel: Panel,
    name: str,
    elections: tuple[int, ...],
    n_draws: int = N_DRAWS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Every block of one outcome, on the municipalities observed at all its elections."""
    cols = [ELECTIONS.index(e) for e in elections]
    y_all = panel.outcomes[name][:, cols]
    keep = np.isfinite(y_all).all(axis=1)
    if int(keep.sum()) < 2:
        raise PoliticsError(f"{name}: fewer than two municipalities have every election")
    n_t = len(elections)
    state, xy = panel.state[keep], panel.xy[keep]
    exp = {k: v[keep] for k, v in panel.exposures.items()}
    price, soy = panel.ln_gold[cols], panel.ln_soy[cols]
    design = Design(state, n_t, panel.controls[keep])
    y_res = design.residualise(y_all[keep].reshape(-1, 1))[:, 0]

    def one(exposure: np.ndarray, p: np.ndarray) -> Fit:
        return fit(design, design.residualise(shock(exposure, p)), y_res)

    main = one(exp["binary"], price)
    observed = float(main.beta[0])
    values = y_all[keep]
    block: dict[str, Any] = {
        "beta": observed,
        "se": float(main.se[0]),
        "ri_p": ri_p(design, state, exp["binary"], price, y_res, observed, n_draws, seed),
        "mean": float(values.mean()),
        "sd": float(values.std(ddof=1)),
        "n_obs": design.n_obs,
        "n_munis": design.n_muni,
    }
    for km in CUTOFFS_KM:
        block[f"conley_se_{km}km"] = conley_se(main.scores[:, 0], float(main.dtd[0, 0]), xy, km)

    base = elections[0]
    d_event = design.residualise(event_matrix(exp["binary"], elections, base))
    event = fit(design, d_event, y_res)
    later = [e for e in elections if e != base]
    block["event"] = {
        "coef": {f"e{e}": float(b) for e, b in zip(later, event.beta, strict=True)},
        "se": {f"e{e}": float(s) for e, s in zip(later, event.se, strict=True)},
    }

    soy_fit, sand_fit = one(exp["binary"], soy), one(exp["sand"], price)
    block["placebo"] = {
        "soy_beta": float(soy_fit.beta[0]),
        "soy_se": float(soy_fit.se[0]),
        "sand_beta": float(sand_fit.beta[0]),
        "sand_se": float(sand_fit.se[0]),
    }
    density_fit, titles_fit = one(exp["density"], price), one(exp["titles"], price)
    block["robust"] = {
        "density_beta": float(density_fit.beta[0]),
        "density_se": float(density_fit.se[0]),
        "titles_beta": float(titles_fit.beta[0]),
        "titles_se": float(titles_fit.se[0]),
    }

    pre = np.array([1.0 if e <= PRE_LAST else 0.0 for e in elections])
    post = np.array([1.0 if e >= GOODFAITH_FIRST else 0.0 for e in elections])
    if pre.any() and post.any():
        d_reg = np.hstack([shock(exp["binary"], price * pre), shock(exp["binary"], price * post)])
        reg = fit(design, design.residualise(d_reg), y_res)
        diff_beta, diff_se = _diff(reg)
        block["regimes"] = {
            "pre_beta": float(reg.beta[0]),
            "pre_se": float(reg.se[0]),
            "goodfaith_beta": float(reg.beta[1]),
            "goodfaith_se": float(reg.se[1]),
            "diff_beta": diff_beta,
            "diff_se": diff_se,
        }

    d_access = np.hstack(
        [shock(exp["binary"], price), shock(exp["binary"] * exp["indigenous"], price)]
    )
    access = fit(design, design.residualise(d_access), y_res)
    block["access"] = {"beta": float(access.beta[1]), "se": float(access.se[1])}
    return block


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
    """Standard-JSON results: non-finite numbers become null and `estimates.finite` is set."""
    bad: list[int] = []
    clean = _clean(results, bad)
    clean["estimates"] = {"finite": not bad}
    return clean


def estimate(
    panel: Panel, skipped: bool, counts: dict[int, int], n_draws: int = N_DRAWS, seed: int = SEED
) -> dict[str, Any]:
    """Every block of `results.json`, before `finalize`."""
    family = {n: es for n, es in OUTCOMES.items() if not (n == MONEY and skipped)}
    outcomes = {n: estimate_outcome(panel, n, es, n_draws, seed) for n, es in family.items()}
    q = bh([outcomes[n]["ri_p"] for n in family])
    for n, value in zip(family, q, strict=True):
        outcomes[n]["q_bh"] = value
    return {
        "outcomes": outcomes,
        "money": {"skipped": skipped, "n_with_cnae": {f"e{e}": c for e, c in counts.items()}},
        "family": {"n_outcomes": len(family)},
    }


def build_results(
    politics: dict[int, pl.DataFrame],
    exposure: pl.DataFrame,
    prices: pl.DataFrame,
    half: frozenset[str],
    n_draws: int = N_DRAWS,
) -> tuple[dict[str, Any], Panel]:
    """Restrict every table with a `cd_ibge` to the half, then build the panel and estimate.

    `prices` is national and has no `cd_ibge`, so it is not restricted.
    """
    politics = {e: restrict(frame, half) for e, frame in politics.items()}
    exposure = restrict(exposure, half)
    counts = money_counts(politics)
    panel = build_panel(politics, exposure, prices)
    return finalize(estimate(panel, money_rule(counts), counts, n_draws)), panel


# --- Summary


def _f(x: Any, digits: int = 4) -> str:
    return "n/a" if x is None else f"{x:.{digits}g}"


def _summary(results: dict[str, Any], panel: Panel) -> str:
    outcomes, money = results["outcomes"], results["money"]
    lines = [
        "## Politics reduced forms of idea 0008: gold price x gold recorded (yes/no)",
        "",
        "Each row is beta on D = `geo_exposed` x mean ln(real gold price) over the four years "
        "before the election, with municipality and state x election fixed effects.",
        "",
        "Clustered errors can over-reject with one common shock (Moreno-Louzada, Figueira and "
        "Picchetti 2025), so the randomisation p (RI p) and q come first.",
        "",
        "Nothing on the exploration half is a finding.",
        "",
        "| Outcome | beta | clustered SE | RI p | q (BH) | mean |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, o in outcomes.items():
        lines.append(
            f"| `{name}` | {_f(o['beta'])} | {_f(o['se'])} | {_f(o['ri_p'])} | "
            f"{_f(o['q_bh'])} | {_f(o['mean'])} |"
        )
    lines += [
        "",
        f"- {results['family']['n_outcomes']} outcomes in the family; RI: 1,000 draws, "
        f"seed {SEED}, E permuted within state; q is Benjamini-Hochberg on the RI p.",
        f"- {len(panel.codes):,} of {panel.n_half:,} exploration-half municipalities have the "
        "exposure and controls; each outcome uses those observed at all its elections "
        "(`n_munis` in `results.json`).",
        "",
        "### Money rule (fixed before any run)",
        "",
        "Receipts with a CNAE, exploration half: "
        + ", ".join(f"{k[1:]}: {v:,}" for k, v in money["n_with_cnae"].items())
        + f". At least {MONEY_MIN_ELECTIONS} elections need {MONEY_MIN_RECEIPTS:,}.",
        "",
        "### Blocks that are absent, and why",
        "",
    ]
    absent = []
    if money["skipped"]:
        absent.append(f"- `{MONEY}`: skipped, fewer than two elections reach the receipts rule.")
    for name, o in outcomes.items():
        if "regimes" not in o:
            absent.append(
                f"- `{name}.regimes`: no election on one side of the 2012/2016 split "
                f"(elections {OUTCOMES[name][0]}-{OUTCOMES[name][-1]})."
            )
    lines += absent or ["- none"]
    lines += [
        "",
        "No full term after the 2023 suspension exists, so no coefficient is estimated for it. "
        "The 2016-2024 terms fall in the 2013-2023 good-faith period. Regime and legal-access "
        "terms are secondary: reported, not claimed.",
        "",
        "Event studies use each outcome's first election as the base (2000, or 2004 for "
        "outcomes 5, 7 and 8).",
    ]
    if panel.dropped.get("null_exposure_or_controls"):
        lines += [
            "",
            f"- dropped for missing exposure or controls: "
            f"{panel.dropped['null_exposure_or_controls']:,}",
        ]
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
        politics = {
            e: restrict(
                read_one(
                    store,
                    where,
                    "politics_panel",
                    rf"politics_panel_{e}\.parquet$",
                    POLITICS_COLUMNS,
                ),
                half,
            )
            for e in ELECTIONS
        }
    results, panel = build_results(politics, exposure, prices, half)
    write_results(args.out_dir, _summary(results, panel), results)


if __name__ == "__main__":
    main()
