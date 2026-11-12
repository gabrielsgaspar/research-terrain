import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.explore import write_results

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0007_gold_first_stage.py"
SPEC = importlib.util.spec_from_file_location("gold_first_stage", SCRIPT)
gfs = importlib.util.module_from_spec(SPEC)
sys.modules["gold_first_stage"] = gfs
SPEC.loader.exec_module(gfs)

YEARS = list(range(1990, 2025))
UFS = ["PA", "MT", "RO"]


def synthetic(effect: float, outside: int = 0, seed: int = 7):
    """60 municipalities in 3 states (plus `outside` others), 1990-2024, true beta `effect`."""
    rng = np.random.default_rng(seed)
    price_years = list(range(1985, 2026))
    ln_gold = (
        5.0 + 0.4 * np.sin(np.array(price_years) / 3.0) + 0.02 * (np.array(price_years) - 1985)
    )
    ln_soy = 3.0 + 0.3 * np.cos(np.array(price_years) / 2.0)
    prices = pl.DataFrame(
        {"year": price_years, "ln_gold_real": ln_gold.tolist(), "ln_soy_real": ln_soy.tolist()}
    )
    lag = dict(zip(price_years, ln_gold, strict=True))
    n = 60 + outside
    codes = [f"15{i:05d}" for i in range(n)]
    state = [i // 20 if i < 60 else 0 for i in range(n)]
    e = rng.uniform(0.0, 5.0, n)
    if outside:
        e[60:] = 100.0
    exposure = pl.DataFrame(
        {
            "cd_ibge": codes,
            "uf": [UFS[s] for s in state],
            "area_km2": rng.uniform(500, 5000, n).tolist(),
            "centroid_x_km": rng.uniform(0, 1000, n).tolist(),
            "centroid_y_km": rng.uniform(0, 1000, n).tolist(),
            "indigenous_share": rng.uniform(0, 0.5, n).tolist(),
            "geo_gold_per_km2": e.tolist(),
            "geo_exposed": (e > 0.5).tolist(),
            "geo_gold_indigenous_share": [None if i % 7 == 0 else 0.2 for i in range(n)],
            "title_gold_pre2000_share": rng.uniform(0, 1, n).tolist(),
            "title_sand_pre2000_share": rng.uniform(0, 1, n).tolist(),
        }
    )
    native = rng.uniform(0, 1, n)
    base = rng.uniform(0.5, 1.0, n)
    state_year = rng.normal(0, 0.05, (3, len(YEARS)))
    rows = []
    for i in range(n):
        for j, year in enumerate(YEARS):
            share = (
                effect * e[i] * lag[year - 1]
                + base[i]
                + state_year[state[i], j]
                + rng.normal(0, 0.02)
            )
            ha = share * 100 * 100
            rows.append(
                {
                    "cd_ibge": codes[i],
                    "year": year,
                    "n_cells": 100,
                    "garimpo_gold_ha": 0.6 * ha,
                    "garimpo_other_ha": 0.4 * ha,
                    "industrial_gold_ha": 1.0,
                    "garimpo_ha": ha,
                    "garimpo_share": share,
                    "native_share_2004": float(native[i]),
                }
            )
    return pl.DataFrame(rows), exposure, prices, frozenset(codes[:60])


def run(effect: float, **kwargs):
    mining, exposure, prices, half = synthetic(effect, **kwargs)
    return gfs.build_results(mining, exposure, prices, half)[0]


def test_recovers_beta_with_a_large_f():
    fs = run(0.02)["first_stage"]
    assert abs(fs["beta"] - 0.02) / 0.02 < 0.10
    assert fs["f_cluster"] > 10
    assert fs["n_munis"] == 60 and fs["n_states"] == 3 and fs["n_obs"] == 60 * 35


def test_ri_p_is_large_for_an_independent_outcome():
    assert run(0.0)["first_stage"]["ri_p"] > 0.05


def small_design(n_munis=12, n_years=6, seed=3):
    rng = np.random.default_rng(seed)
    state = np.repeat(np.arange(3), n_munis // 3)
    controls = rng.normal(size=(n_munis, 3))
    design = gfs.Design(state, n_years, controls)
    e = rng.uniform(0, 2, n_munis)
    price = rng.normal(size=n_years)
    y = (
        0.5 * (e[:, None] * price[None, :])
        + rng.normal(size=(n_munis, 1))
        + rng.normal(size=(3, n_years))[state]
        + rng.normal(0, 0.3, (n_munis, n_years))
    ).reshape(-1)
    return design, state, controls, e, price, y


def test_alternating_projections_match_dummy_regression():
    design, state, controls, e, price, y = small_design()
    n_munis, n_years = len(state), len(price)
    d = gfs.shock(e, price)
    got = gfs.fit(design, design.residualise(d), design.residualise(y[:, None])[:, 0]).beta[0]

    muni = np.repeat(np.arange(n_munis), n_years)
    sy = np.repeat(state, n_years) * n_years + np.tile(np.arange(n_years), n_munis)
    muni_dummies = np.eye(n_munis)[muni]
    sy_dummies = np.eye(3 * n_years)[sy]
    x = np.hstack([d, muni_dummies, sy_dummies, gfs.control_matrix(controls, n_years)])
    want = np.linalg.lstsq(x, y, rcond=None)[0][0]
    assert got == pytest.approx(want, abs=1e-8)


def test_conley_below_the_smallest_distance_is_the_clustered_se():
    design, state, controls, e, price, y = small_design()
    d_res = design.residualise(gfs.shock(e, price))
    f = gfs.fit(design, d_res, design.residualise(y[:, None])[:, 0])
    xy = np.random.default_rng(5).uniform(0, 1000, (len(state), 2))
    conley = gfs.conley_se(f.scores[:, 0], float(f.dtd[0, 0]), xy, 1e-6)
    assert conley == pytest.approx(float(np.sqrt(f.cov_raw[0, 0])), rel=1e-10)
    assert gfs.conley_se(f.scores[:, 0], float(f.dtd[0, 0]), xy, 5000) != pytest.approx(conley)


def reject_constant(name):
    raise ValueError(f"non-standard JSON constant {name}")


def test_results_have_the_kill_rule_keys_and_parse_as_standard_json(tmp_path):
    mining, exposure, prices, half = synthetic(0.02)
    results, panel = gfs.build_results(mining, exposure, prices, half, n_draws=20)
    assert results["estimates"]["finite"] is True
    assert results["first_stage"]["f_cluster"] > 0
    assert results["placebo"]["lead_ratio"] > 0
    assert set(results["event"]["coef"]) == {f"y{y}" for y in YEARS if y != 2000}
    for block in ("secondary", "robust", "regimes", "access", "price", "exposure"):
        assert block in results
    assert set(results["secondary"]) == set(gfs.SECONDARY)
    assert set(results["regimes"]) == {"r1", "r2", "r3", "r2_minus_r1"}
    write_results(tmp_path, gfs._summary(results, panel), results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject_constant)
    assert parsed["estimates"]["finite"] is True
    assert "Moreno-Louzada" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_a_nan_is_written_as_null_and_flags_the_estimates(tmp_path):
    results = gfs.finalize(
        {
            "first_stage": {"beta": float("nan"), "f_cluster": 3.0, "n": np.int64(4)},
            "placebo": {"lead_ratio": 0.5, "other": float("inf")},
        }
    )
    assert results["first_stage"]["beta"] is None
    assert results["placebo"]["other"] is None
    assert results["estimates"]["finite"] is False
    write_results(tmp_path, "x", results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject_constant)
    assert parsed["first_stage"]["beta"] is None


def test_the_lead_ratio_sentinel_sets_the_flag():
    coef = {y: 0.1 if y <= 2001 else 0.0 for y in YEARS if y != 2000}
    ratio = gfs._lead_ratio(coef)
    assert ratio == gfs.SENTINEL
    clean = gfs.finalize({"placebo": {"lead_ratio": ratio}})
    assert clean["estimates"]["finite"] is False


def test_rows_outside_the_half_are_dropped_before_estimation():
    mining, exposure, prices, half = synthetic(0.02, outside=5)
    assert mining["cd_ibge"].n_unique() == 65
    with_outside = gfs.build_results(mining, exposure, prices, half)[0]
    inside = pl.col("cd_ibge").is_in(sorted(half))
    clean = gfs.build_results(mining.filter(inside), exposure.filter(inside), prices, half)[0]
    assert with_outside["first_stage"]["n_munis"] == 60
    assert with_outside["sample"]["n_half"] == 60
    assert with_outside["first_stage"]["beta"] == pytest.approx(clean["first_stage"]["beta"])
    assert with_outside["exposure"]["mean_geo_gold_per_km2"] == pytest.approx(
        clean["exposure"]["mean_geo_gold_per_km2"]
    )


def test_dropped_municipalities_are_counted_by_reason():
    mining, exposure, prices, half = synthetic(0.02)
    mining = mining.with_columns(
        pl.when(pl.col("cd_ibge") == "1500003")
        .then(None)
        .otherwise(pl.col("native_share_2004"))
        .alias("native_share_2004")
    ).filter(~((pl.col("cd_ibge") == "1500004") & (pl.col("year") == 1995)))
    results = gfs.build_results(mining, exposure, prices, half, n_draws=5)[0]
    assert results["first_stage"]["n_munis"] == 58
    assert results["sample"]["dropped"] == {"null_controls": 1, "unbalanced": 1}
