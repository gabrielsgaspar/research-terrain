"""Poisson regressions with fixed effects that do not fall over.

Every explore script fits Poisson models with fixed effects through `fepois`
here, never through `pyfixest.fepois` directly (AGENTS.md; a test checks).

Why: pyfixest 0.70 can stop with "Demeaning failed after 1000 iterations" on
data it has in fact already fitted. Once its IWLS loop reaches the optimum,
rounding noise in the deviance (about 1e-15) looks like a step that made the
fit worse. pyfixest then halves the step, and a halved step skips the
convergence check, so the loop goes on. Each extra round its `accelerate`
option also makes the demeaning tolerance ten times tighter, until it is
1e-17, which no computer can meet in double precision, and the demeaner
gives up. Whether that noise appears depends on the machine, so a test can
pass on one computer and fail on another (campaign 0013 s1, run 45023206392).

`fepois` therefore:

1. drops fixed-effect groups that carry no information (every outcome zero,
   or a single row) and counts them;
2. fits with `pyfixest.fepois`;
3. on an error, fits again with `accelerate=False` (the demeaning tolerance
   then stays fixed) and more iterations;
4. if that fails too and there is one fixed effect, fits by Newton's method
   on the likelihood with the fixed effect solved in closed form, which
   needs no demeaning at all;
5. otherwise returns NaN: a fit that cannot be estimated is a null.

Standard errors are clustered (CRV1) when `cluster` is given, otherwise
heteroskedasticity-robust (HC1), with pyfixest's small-sample factors, so
every path gives the same numbers on the same data.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import polars as pl

PATHS = ("pyfixest", "pyfixest_retry", "closed_form_fe", "none")
RETRY_IWLS_MAXITER = 200
NEWTON_MAXITER = 200
NEWTON_TOL = 1e-12
COLLINEAR_TOL = 1e-9
MAX_CONDITION = 1e12


@dataclass(frozen=True)
class PoissonFit:
    """One coefficient of a Poisson fit, and how the fit was made.

    `path` is one of PATHS: "pyfixest" (first try), "pyfixest_retry" (second
    try, accelerate off), "closed_form_fe" (one fixed effect, no demeaning)
    or "none" (could not be estimated; b, se and p are NaN).
    `groups_dropped` counts fixed-effect groups dropped before the fit
    because every outcome in them is zero or they have a single row.
    """

    b: float
    se: float
    p: float
    n_obs: int
    path: str
    groups_dropped: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nan_fit(n_obs: int, groups_dropped: int) -> PoissonFit:
    nan = float("nan")
    return PoissonFit(nan, nan, nan, n_obs, "none", groups_dropped)


def _codes(values: np.ndarray) -> np.ndarray:
    return np.unique(values, return_inverse=True)[1].astype(np.int64)


def _drop_uninformative(y: np.ndarray, groups: list[np.ndarray]) -> tuple[np.ndarray, int]:
    """Rows to keep, and how many groups were dropped (all-zero outcome or one row).

    Repeats until nothing changes, since dropping a group of one fixed effect
    can empty or shrink a group of another.
    """
    keep = np.ones(y.shape[0], dtype=bool)
    dropped = 0
    changed = True
    while changed:
        changed = False
        for g in groups:
            idx = np.flatnonzero(keep)
            if idx.size == 0:
                return keep, dropped
            codes = _codes(g[idx])
            size = np.bincount(codes)
            total = np.bincount(codes, weights=y[idx])
            bad = (size < 2) | (total <= 0)
            if bad.any():
                dropped += int(bad.sum())
                keep[idx[bad[codes]]] = False
                changed = True
    return keep, dropped


def _df_k(k: int, group: np.ndarray, cluster: np.ndarray | None) -> int:
    """Parameters counted by pyfixest's default small-sample factor, for one fixed effect.

    The regressors plus every level of the fixed effect; if the fixed effect is
    nested in the clusters (each group inside one cluster), one instead.
    """
    levels = int(group.max()) + 1
    if cluster is not None:
        clusters_per_group = np.unique(np.column_stack([group, cluster]), axis=0)[:, 0]
        if clusters_per_group.shape[0] == levels:
            return k + 1
    return k + levels


def _small_sample(n: int, df_k: int, n_clusters: int | None) -> float:
    """pyfixest's default factor: (N-1)/(N-df_k) x G/(G-1) if clustered, N/(N-df_k) if not."""
    if n_clusters is None:
        return n / (n - df_k)
    return (n - 1) / (n - df_k) * n_clusters / (n_clusters - 1)


def _p_value(t: float) -> float:
    """Two-sided p-value from the normal distribution, as `pyfixest.fepois` reports it."""
    return math.erfc(abs(t) / math.sqrt(2.0))


def _closed_form_fe(
    y: np.ndarray,
    x: np.ndarray,
    offset: np.ndarray,
    group: np.ndarray,
    cluster: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Poisson with one fixed effect by Newton's method, the effect solved in closed form.

    For fixed `b` the likelihood is maximised by alpha_g = log(sum_g y) -
    log(sum_g exp(x b + offset)), so only `b` is iterated, with the exact
    Hessian. Returns (b, variance) or None if it does not converge.
    `group` holds integer codes 0..G-1; every group has a positive sum of `y`.
    """
    n, k = x.shape
    n_groups = int(group.max()) + 1
    y_sum = np.bincount(group, weights=y, minlength=n_groups)

    def state(b: np.ndarray) -> tuple[float, np.ndarray]:
        eta = x @ b + offset
        top = np.full(n_groups, -np.inf)
        np.maximum.at(top, group, eta)
        scale = np.bincount(group, weights=np.exp(eta - top[group]), minlength=n_groups)
        alpha = np.log(y_sum) - top - np.log(scale)
        eta = eta + alpha[group]
        mu = np.exp(eta)
        loglik = float(np.sum(y * eta - mu))
        return loglik, mu

    def within(mu: np.ndarray) -> np.ndarray:
        mu_sum = np.bincount(group, weights=mu, minlength=n_groups)
        means = (
            np.column_stack(
                [np.bincount(group, weights=mu * x[:, j], minlength=n_groups) for j in range(k)]
            )
            / mu_sum[:, None]
        )
        return x - means[group]

    b = np.zeros(k)
    loglik, mu = state(b)
    # a regressor that is constant within every group is absorbed by the fixed effect
    xt = within(mu)
    if np.any(np.linalg.norm(xt, axis=0) <= COLLINEAR_TOL * (1.0 + np.linalg.norm(x, axis=0))):
        return None
    for _ in range(NEWTON_MAXITER):
        xt = within(mu)
        score = xt.T @ (y - mu)
        info = (xt * mu[:, None]).T @ xt
        scale = np.sqrt(np.diag(info))
        if np.linalg.cond(info / np.outer(scale, scale)) > MAX_CONDITION:
            return None  # regressors collinear with each other
        try:
            step = np.linalg.solve(info, score)
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(step)):
            return None
        alpha = 1.0
        while True:
            b_try = b + alpha * step
            loglik_try, mu_try = state(b_try)
            if math.isfinite(loglik_try) and loglik_try >= loglik - 1e-12 * abs(loglik):
                break
            alpha /= 2.0
            if alpha < 1e-10:
                return None
        b, loglik, mu = b_try, loglik_try, mu_try
        if np.max(np.abs(alpha * step)) < NEWTON_TOL * (1.0 + np.max(np.abs(b))):
            break
    else:
        return None

    xt = within(mu)
    info = (xt * mu[:, None]).T @ xt
    scores = xt * (y - mu)[:, None]
    if cluster is not None:
        n_clusters = int(cluster.max()) + 1
        scores = np.column_stack(
            [np.bincount(cluster, weights=scores[:, j], minlength=n_clusters) for j in range(k)]
        )
    else:
        n_clusters = None
    try:
        bread = np.linalg.inv(info)
    except np.linalg.LinAlgError:
        return None
    df_k = _df_k(k, group, cluster)
    if n - df_k <= 0:
        return None
    variance = bread @ (scores.T @ scores) @ bread * _small_sample(n, df_k, n_clusters)
    return b, variance


def _pyfixest(
    frame: pl.DataFrame,
    formula: str,
    coef: str,
    offset: str | None,
    cluster: str | None,
    retry: bool,
) -> tuple[float, float, float, int]:
    import pyfixest as pf

    options: dict[str, Any] = {"vcov": {"CRV1": cluster} if cluster else "hetero"}
    if offset is not None:
        options["offset"] = offset
    if retry:
        options.update(
            accelerate=False,
            iwls_maxiter=RETRY_IWLS_MAXITER,
            demeaner=pf.LsmrDemeaner(fixef_maxiter=100_000),
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = pf.fepois(formula, data=frame, **options)
    return (
        float(model.coef()[coef]),
        float(model.se()[coef]),
        float(model.pvalue()[coef]),
        int(model._N),
    )


def fepois(
    data: pl.DataFrame,
    *,
    y: str,
    x: Sequence[str],
    fe: str | Sequence[str],
    coef: str,
    offset: str | None = None,
    cluster: str | None = None,
) -> PoissonFit:
    """Poisson regression of `y` on `x` with fixed effects `fe`; the result for `coef`.

    `offset` is a column added to the linear index with coefficient 1 (for
    example log population). `cluster` gives clustered standard errors
    (CRV1); without it they are heteroskedasticity-robust (HC1). Rows with a
    missing or non-finite value in any column used are left out, as pyfixest
    does. Raises ValueError for a missing column, `coef` not in `x`, or a
    negative outcome; returns NaN (path "none") when the fit cannot be
    estimated.
    """
    fes = [fe] if isinstance(fe, str) else list(fe)
    regressors = list(x)
    if not fes:
        raise ValueError("fepois needs at least one fixed effect")
    if coef not in regressors:
        raise ValueError(f"coef {coef!r} is not one of the regressors")
    numeric = [y, *regressors] + ([offset] if offset else [])
    columns = numeric + fes + ([cluster] if cluster else [])
    missing = [c for c in dict.fromkeys(columns) if c not in data.columns]
    if missing:
        raise ValueError(f"fepois: missing columns {missing}")

    frame = data.select(list(dict.fromkeys(columns)))
    frame = frame.drop_nulls()
    finite = pl.all_horizontal(pl.col(c).cast(pl.Float64).is_finite() for c in numeric)
    frame = frame.filter(finite)
    yv = frame[y].cast(pl.Float64).to_numpy()
    if (yv < 0).any():
        raise ValueError("fepois: the outcome has negative values")

    groups = [_codes(frame[f].to_numpy()) for f in fes]
    keep, dropped = _drop_uninformative(yv, groups)
    frame = frame.filter(pl.Series(keep))
    n = frame.height
    if n <= len(regressors) + 1:
        return _nan_fit(n, dropped)

    # integer codes for the fixed effects and the cluster, under fixed names
    fe_names = [f"_fe{i}" for i in range(len(fes))]
    coded = frame.select(
        pl.col(y).cast(pl.Float64).alias("_y"),
        *[pl.col(c).cast(pl.Float64) for c in regressors],
        *([pl.col(offset).cast(pl.Float64).alias("_offset")] if offset else []),
        *[
            pl.Series(name, _codes(frame[f].to_numpy()))
            for name, f in zip(fe_names, fes, strict=True)
        ],
        *([pl.Series("_cluster", _codes(frame[cluster].to_numpy()))] if cluster else []),
    )
    formula = f"_y ~ {' + '.join(regressors)} | {' + '.join(fe_names)}"
    off = "_offset" if offset else None
    clu = "_cluster" if cluster else None

    for path, retry in (("pyfixest", False), ("pyfixest_retry", True)):
        try:
            b, se, p, n_obs = _pyfixest(coded, formula, coef, off, clu, retry)
        except Exception:  # noqa: BLE001  pyfixest raises many types; the next path decides
            continue
        if all(math.isfinite(v) for v in (b, se, p)):
            return PoissonFit(b, se, p, n_obs, path, dropped)

    if len(fes) != 1:
        return _nan_fit(n, dropped)
    xs = coded.select(regressors).to_numpy().astype(np.float64)
    fit = _closed_form_fe(
        coded["_y"].to_numpy(),
        xs,
        coded["_offset"].to_numpy() if offset else np.zeros(n),
        coded["_fe0"].to_numpy(),
        coded["_cluster"].to_numpy() if cluster else None,
    )
    if fit is None:
        return _nan_fit(n, dropped)
    b_all, variance = fit
    j = regressors.index(coef)
    b, var = float(b_all[j]), float(variance[j, j])
    if not (math.isfinite(b) and math.isfinite(var) and var > 0):
        return _nan_fit(n, dropped)
    se = math.sqrt(var)
    return PoissonFit(b, se, _p_value(b / se), n, "closed_form_fe", dropped)
