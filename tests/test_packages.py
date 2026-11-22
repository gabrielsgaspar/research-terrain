"""The regression and classifier packages work as the campaigns use them.

pyfixest runs regressions with fixed effects (OLS and Poisson), reading a
polars frame through pyarrow; scikit-learn trains text classifiers inside
builds. Offline and fast: small synthetic data with known coefficients.
"""

import math

import numpy as np
import polars as pl
import pyfixest as pf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

CLUSTERED = {"CRV1": "unit"}


def panel(seed: int = 0, units: int = 30, per_unit: int = 20) -> pl.DataFrame:
    """y = 0.5 x + unit effect + noise; count = Poisson(exposure * exp(0.3 x + unit effect))."""
    rng = np.random.default_rng(seed)
    n = units * per_unit
    unit = np.repeat(np.arange(units), per_unit)
    effect = rng.normal(size=units)[unit]
    x = rng.normal(size=n) + 0.5 * effect
    exposure = rng.uniform(1.0, 5.0, size=n)
    return pl.DataFrame(
        {
            "unit": unit,
            "x": x,
            "y": 1.0 + 0.5 * x + effect + rng.normal(scale=0.2, size=n),
            "w": rng.uniform(0.5, 2.0, size=n),
            "count": rng.poisson(exposure * np.exp(0.3 * x + 0.2 * effect)),
            "log_exposure": np.log(exposure),
        }
    )


def coef_and_se(model) -> tuple[float, float]:
    return float(model.coef()["x"]), float(model.se()["x"])


def test_feols_with_a_fixed_effect_and_clustered_errors():
    beta, se = coef_and_se(pf.feols("y ~ x | unit", data=panel(), vcov=CLUSTERED))
    assert math.isfinite(beta) and math.isfinite(se) and se > 0
    assert abs(beta - 0.5) < 0.05


def test_feols_with_weights():
    model = pf.feols("y ~ x | unit", data=panel(), vcov=CLUSTERED, weights="w")
    beta, se = coef_and_se(model)
    assert math.isfinite(beta) and math.isfinite(se) and se > 0
    assert abs(beta - 0.5) < 0.05


def test_fepois_with_an_offset():
    model = pf.fepois("count ~ x | unit", data=panel(), vcov=CLUSTERED, offset="log_exposure")
    beta, se = coef_and_se(model)
    assert math.isfinite(beta) and math.isfinite(se) and se > 0
    assert abs(beta - 0.3) < 0.1


def test_tfidf_logistic_regression_classifies_strings():
    train = [
        "desmatamento na floresta amazônica",
        "queimada e corte raso na mata",
        "floresta derrubada para pasto",
        "escola municipal reformada",
        "nova escola e creche no bairro",
        "reforma da escola estadual",
    ]
    labels = ["forest", "forest", "forest", "school", "school", "school"]
    model = make_pipeline(TfidfVectorizer(), LogisticRegression(random_state=0))
    model.fit(train, labels)
    assert list(model.predict(["corte na floresta", "creche e escola"])) == ["forest", "school"]
