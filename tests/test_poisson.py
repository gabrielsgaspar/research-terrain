"""terrain.poisson.fepois: finite on every seed, and equal to pyfixest where pyfixest converges.

The panel mirrors the one in campaign 0013 s1's test (amendment reais by
deputy and town, a 30% premium for winners, an offset of log population),
on which `pyfixest.fepois` stopped with "Demeaning failed after 1000
iterations" for some seeds on some machines (run 45023206392).
"""

import math
import warnings

import numpy as np
import polars as pl
import pyfixest as pf
import pytest

from terrain import poisson
from terrain.poisson import PoissonFit, fepois

SEEDS = range(24)
X = ["win", "margin", "wm"]
VCOVS = ("town", None, "deputy")  # clustered by town, robust, clustered by the fixed effect
TOL = 1e-6


def make_panel(seed: int, premium: float = 1.3, deputies: int = 30, races: int = 110):
    """Races with 2 to 4 deputies each; reais = 1000 x Poisson, a premium for winners."""
    rng = np.random.default_rng(seed)
    effect = rng.normal(0, 0.3, size=deputies)
    rows = []
    for i in range(races):
        margin = float(rng.uniform(-0.1, 0.1))
        win = float(margin > 0)
        pop = float(rng.uniform(20_000, 200_000))
        for d in rng.choice(deputies, size=int(rng.integers(2, 5)), replace=False):
            mean = pop / 1e5 * 400 * math.exp(effect[d]) * (premium if win else 1.0)
            rows.append(
                {
                    "y": 1000.0 * rng.poisson(mean),
                    "win": win,
                    "margin": margin,
                    "wm": win * margin,
                    "ln_pop": math.log(pop),
                    "deputy": f"d{d:02d}",
                    "town": f"t{i:03d}",
                }
            )
    return pl.DataFrame(rows)


def fit(frame: pl.DataFrame, cluster: str | None = "town", **kw) -> PoissonFit:
    return fepois(
        frame, y="y", x=X, fe="deputy", coef="win", offset="ln_pop", cluster=cluster, **kw
    )


def pyfixest_fit(frame: pl.DataFrame, cluster: str | None, **kw):
    """pyfixest itself, or None where it does not converge."""
    vcov = {"CRV1": cluster} if cluster else "hetero"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = pf.fepois(
                "y ~ win + margin + wm | deputy", data=frame, vcov=vcov, offset="ln_pop", **kw
            )
        return float(m.coef()["win"]), float(m.se()["win"]), float(m.pvalue()["win"]), m._N
    except Exception:  # noqa: BLE001
        return None


def assert_same(got: PoissonFit, ref) -> None:
    b, se, p, n = ref
    assert got.b == pytest.approx(b, abs=TOL)
    assert got.se == pytest.approx(se, rel=TOL)
    assert got.p == pytest.approx(p, abs=TOL)
    assert got.n_obs == n


@pytest.fixture
def pyfixest_fails(monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("Demeaning failed after 1000 iterations.")

    monkeypatch.setattr(poisson, "_pyfixest", refuse)


def test_finite_and_close_to_the_planted_premium_on_every_seed():
    for seed in SEEDS:
        got = fit(make_panel(seed))
        assert got.path in poisson.PATHS and got.path != "none", seed
        assert all(math.isfinite(v) for v in (got.b, got.se, got.p)), seed
        assert got.se > 0 and got.n_obs > 300 and got.groups_dropped == 0, seed
        assert abs(math.exp(got.b) - 1.3) < 0.05, seed


def test_same_as_pyfixest_wherever_pyfixest_converges():
    compared = 0
    for seed in SEEDS:
        frame = make_panel(seed)
        for cluster in VCOVS:
            ref = pyfixest_fit(frame, cluster)
            if ref is None:
                continue
            assert_same(fit(frame, cluster), ref)
            compared += 1
    assert compared >= 5 * len(VCOVS)


def test_the_fit_without_demeaning_is_the_same_as_pyfixest(pyfixest_fails):
    # a small premium, so the p-values are not all zero
    compared = 0
    for seed in SEEDS:
        frame = make_panel(seed, premium=1.02)
        for cluster in VCOVS:
            ref = pyfixest_fit(frame, cluster, accelerate=False, iwls_tol=1e-12, iwls_maxiter=200)
            if ref is None:
                continue
            got = fit(frame, cluster)
            assert got.path == "closed_form_fe"
            assert_same(got, ref)
            compared += 1
    assert compared >= 5 * len(VCOVS)


def test_the_retry_is_used_when_the_first_try_fails(monkeypatch):
    real = poisson._pyfixest

    def first_fails(frame, formula, coef, offset, cluster, retry):
        if not retry:
            raise ValueError("Demeaning failed after 1000 iterations.")
        return real(frame, formula, coef, offset, cluster, retry)

    monkeypatch.setattr(poisson, "_pyfixest", first_fails)
    for seed in range(5):
        frame = make_panel(seed)
        got = fit(frame)
        assert got.path == "pyfixest_retry"
        assert_same(got, pyfixest_fit(frame, "town", accelerate=False, iwls_tol=1e-12))


def test_groups_with_no_information_are_dropped_and_counted():
    base = make_panel(1)
    extra = pl.DataFrame(
        {
            "y": [0.0, 0.0, 0.0, 5000.0],
            "win": [1.0, 0.0, 1.0, 1.0],
            "margin": [0.01, -0.02, 0.03, 0.04],
            "wm": [0.01, 0.0, 0.03, 0.04],
            "ln_pop": [10.0, 10.5, 11.0, 11.5],
            "deputy": ["zero", "zero", "zero", "single"],
            "town": ["t000", "t001", "t002", "t003"],
        }
    )
    frame = pl.concat([base, extra])
    got = fit(frame)
    assert got.groups_dropped == 2
    assert got.n_obs == base.height
    # pyfixest drops the same rows itself, so the numbers do not change
    assert_same(got, pyfixest_fit(base, "town", accelerate=False, iwls_tol=1e-12))


def test_rows_with_missing_values_are_left_out():
    base = make_panel(2)
    holes = base.with_columns(
        pl.when(pl.int_range(pl.len()) % 50 == 0).then(None).otherwise(pl.col("y")).alias("y")
    )
    got = fit(holes)
    assert got.n_obs == holes.drop_nulls().height
    assert math.isfinite(got.b)


def test_a_fit_that_cannot_be_estimated_is_nan(pyfixest_fails):
    frame = make_panel(3)
    for bad in (
        frame.with_columns(pl.lit(0.0).alias("y")),  # no outcome anywhere
        frame.head(3),  # fewer rows than parameters
        frame.with_columns(pl.col("deputy").str.contains("0").cast(pl.Float64).alias("win")),
    ):
        got = fit(bad)
        assert got.path == "none"
        assert math.isnan(got.b) and math.isnan(got.se) and math.isnan(got.p)


def test_two_fixed_effects_have_no_fallback(pyfixest_fails):
    got = fepois(make_panel(4), y="y", x=X, fe=["deputy", "town"], coef="win", cluster="town")
    assert got.path == "none" and math.isnan(got.b)


def test_two_fixed_effects_go_through_pyfixest():
    frame = make_panel(4).with_columns((pl.col("ln_pop") * 2).floor().alias("band"))
    got = fepois(frame, y="y", x=X, fe=["deputy", "band"], coef="win", cluster="town")
    assert got.path in ("pyfixest", "pyfixest_retry")
    assert math.isfinite(got.se) and abs(got.b - math.log(1.3)) < 3 * got.se


def test_bad_calls_raise():
    frame = make_panel(5)
    with pytest.raises(ValueError, match="missing columns"):
        fepois(frame, y="y", x=["nope"], fe="deputy", coef="nope")
    with pytest.raises(ValueError, match="not one of the regressors"):
        fepois(frame, y="y", x=X, fe="deputy", coef="margin_sq")
    with pytest.raises(ValueError, match="negative"):
        fit(frame.with_columns(-pl.col("y")))


def test_as_dict_has_every_field():
    got = fit(make_panel(6)).as_dict()
    assert set(got) == {"b", "se", "p", "n_obs", "path", "groups_dropped"}
