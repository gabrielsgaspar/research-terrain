import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.explore import write_results

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0008_gold_yes_no_first_stage.py"
SPEC = importlib.util.spec_from_file_location("gold_yes_no_first_stage", SCRIPT)
gyn = importlib.util.module_from_spec(SPEC)
sys.modules["gold_yes_no_first_stage"] = gyn
SPEC.loader.exec_module(gyn)

YEARS = list(range(1990, 2025))
UFS = ["PA", "MT", "RO"]


def synthetic(effect: float, outside: int = 0, seed: int = 7, spikes: dict | None = None):
    """60 municipalities in 3 states (plus `outside` others), 1990-2024, true beta `effect`.

    `spikes` maps a municipality index to extra `garimpo_share` in 2007 (planted jumps).
    """
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
    d = np.array([1.0 if i % 2 == 0 else 0.0 for i in range(n)])
    density = rng.uniform(0.0, 5.0, n) * d
    if outside:
        d[60:] = 1.0
        density[60:] = 100.0
    exposure = pl.DataFrame(
        {
            "cd_ibge": codes,
            "uf": [UFS[s] for s in state],
            "area_km2": rng.uniform(500, 5000, n).tolist(),
            "centroid_x_km": rng.uniform(0, 1000, n).tolist(),
            "centroid_y_km": rng.uniform(0, 1000, n).tolist(),
            "indigenous_share": rng.uniform(0, 0.5, n).tolist(),
            "geo_gold_per_km2": density.tolist(),
            "geo_exposed": [bool(x) for x in d],
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
                effect * d[i] * lag[year - 1]
                + base[i]
                + state_year[state[i], j]
                + rng.normal(0, 0.02)
            )
            if spikes and year == 2007 and i in spikes:
                share += spikes[i]
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


def run(effect: float, n_draws: int = 20, **kwargs):
    mining, exposure, prices, half = synthetic(effect, **kwargs)
    return gyn.build_results(mining, exposure, prices, half, n_draws=n_draws)


def reject_constant(name):
    raise ValueError(f"non-standard JSON constant {name}")


# Done when 1


def test_recovers_a_planted_beta_and_a_null_gives_a_small_f():
    fs = run(0.02)[0]["first_stage"]
    assert abs(fs["beta"] - 0.02) / 0.02 < 0.10
    assert fs["f_cluster"] > 10
    assert fs["n_munis"] == 60 and fs["n_states"] == 3 and fs["n_obs"] == 60 * 35
    assert fs["n_exposed"] == 30
    assert run(0.0)[0]["first_stage"]["f_cluster"] < 10


# Done when 2


def test_ri_p_formula_on_known_draws():
    draws = np.array([0.5, -2.0, 1.0, -0.1, 3.0])
    # |draw| >= 1.0 for 3 of 5 draws: (1 + 3) / (1 + 5)
    assert gyn.ri_p_value(1.0, draws) == pytest.approx(4 / 6)
    assert gyn.ri_p_value(-1.0, draws) == pytest.approx(4 / 6)
    assert gyn.ri_p_value(10.0, draws) == pytest.approx(1 / 6)
    assert gyn.ri_p_value(0.0, draws) == pytest.approx(1.0)
    assert np.isnan(gyn.ri_p_value(float("nan"), draws))
    thousand = np.linspace(0.0, 1.0, 1000)
    assert gyn.ri_p_value(0.5, thousand) == pytest.approx((1 + 500) / 1001)


def test_ri_p_is_large_for_an_independent_outcome():
    assert run(0.0)[0]["first_stage"]["ri_p"] > 0.05


# Done when 3


def test_lead_ratio_matches_a_hand_computation():
    coef = {y: 0.0 for y in YEARS if y != 2000}
    coef[1990], coef[1995], coef[2001] = 0.3, -0.6, 0.6  # lead: 11 years (no 2000), sum 0.3
    coef[2002], coef[2010] = 0.2, 0.4  # tail: 23 years (2002-2024), sum 0.6
    assert gyn.lead_ratio(coef) == pytest.approx((0.3 / 11) / (0.6 / 23))


def test_a_zero_denominator_gives_the_sentinel_and_flags_the_estimates():
    coef = {y: 0.1 if y <= 2001 else 0.0 for y in YEARS if y != 2000}
    ratio = gyn.lead_ratio(coef)
    assert ratio == 1000000000.0
    clean = gyn.finalize({"placebo": {"lead_ratio": ratio}})
    assert clean["estimates"]["finite"] is False


# Done when 4


def test_leave_one_state_out_picks_the_smallest_f_and_its_state():
    state = np.array([0, 0, 1, 1, 2, 2])
    seen = []

    def f_of(keep):
        left_out = int(state[~keep][0])
        assert np.all(state[~keep] == left_out)  # a whole state is out, nothing else
        seen.append(left_out)
        return {0: 30.0, 1: 4.5, 2: 12.0}[left_out]

    assert gyn.leave_one_state_out(state, ["PA", "MT", "RO"], f_of) == (4.5, "MT")
    assert seen == [0, 1, 2]
    assert gyn.leave_one_state_out(state, ["PA", "MT", "RO"], lambda keep: float("nan")) == (
        pytest.approx(float("nan"), nan_ok=True),
        None,
    )


def test_top_and_drop_rules_pick_the_right_municipalities():
    codes = ["a", "b", "c", "d", "e", "f", "g"]
    share_2024 = np.array([0.1, 0.9, 0.5, 0.5, 0.7, 0.8, 0.0])
    top = gyn.top_indices(share_2024, codes, 5)
    assert [codes[i] for i in top] == ["b", "f", "e", "c", "d"]  # tie c/d: smaller code first
    keep = gyn.keep_without(len(codes), top)
    assert [c for c, k in zip(codes, keep, strict=True) if k] == ["a", "g"]

    density = np.array([2.0, 1.0, 0.0, 4.0])
    a = gyn.density_products(
        density, np.array([0.1, 0.1, 0.1, 0.5]), np.array([0.2, 0.4, 0.9, 0.4])
    )
    assert a == pytest.approx([0.2, 0.3, 0.0, 0.4])
    assert gyn.top_share(a) == pytest.approx(0.4 / 0.9)


def test_density_and_sturdy_blocks_on_a_toy_panel():
    spikes = {3: 0.9, 25: 0.8, 41: 0.7, 7: 0.6, 55: 0.5}  # all have density 0 unless i is even
    mining, exposure, prices, half = synthetic(0.02, spikes=spikes)
    # Give every spiked municipality a density, in a known order.
    density = {3: 5.0, 25: 4.0, 41: 3.0, 7: 2.0, 55: 1.0}
    codes = exposure["cd_ibge"].to_list()
    exposure = exposure.with_columns(
        pl.Series(
            "geo_gold_per_km2",
            [density.get(i, 0.01) for i in range(len(codes))],
            dtype=pl.Float64,
        )
    )
    results, panel = gyn.build_results(mining, exposure, prices, half, n_draws=5)
    top5 = results["density"]["top5"]
    want = [3, 25, 41, 7, 55]  # a_m = E x jump: 4.5, 3.2, 2.1, 1.2, 0.5
    assert [t["cd_ibge"] for t in top5] == [codes[i] for i in want]
    assert [t["uf"] for t in top5] == [UFS[i // 20] for i in want]
    assert set(top5[0]) == {"cd_ibge", "uf"}
    assert 0.3 < results["density"]["top1_share"] < 1.0
    assert results["sturdy"]["loso_min_state"] in UFS
    assert results["sturdy"]["loso_min_f"] > 0


def test_every_subset_f_runs_and_whole_sample_f_matches_the_main_f():
    results, panel = run(0.02)
    everyone = np.ones(len(panel.codes), dtype=bool)
    f_all = gyn.first_stage_f(panel, everyone, panel.exposures["binary"])
    assert f_all == pytest.approx(results["first_stage"]["f_cluster"])
    f_early = gyn.first_stage_f(panel, everyone, panel.exposures["binary"], gyn.EARLY)
    assert results["sturdy"]["f_1990_2012"] == pytest.approx(f_early)
    assert np.isnan(gyn.first_stage_f(panel, everyone & False, panel.exposures["binary"]))


# Done when 5


def listed_keys():
    keys = [
        f"first_stage.{k}"
        for k in (
            "beta se f_cluster ri_p conley_se_50km conley_se_100km conley_se_200km "
            "n_obs n_munis n_states n_exposed"
        ).split()
    ]
    keys += [f"placebo.{k}" for k in "lead_ratio soy_beta soy_se sand_beta sand_se".split()]
    keys += [f"event.coef.y{y}" for y in YEARS if y != 2000]
    keys += [f"event.se.y{y}" for y in YEARS if y != 2000]
    for name in ("garimpo_gold_share", "garimpo_other_share", "industrial_gold_share"):
        keys += [f"secondary.{name}.{k}" for k in ("beta", "se", "ri_p")]
    keys += [f"secondary.ln_garimpo_ha.{k}" for k in ("beta", "se", "ri_p")]
    keys += ["density.top5", "density.top1_share", "density.f_drop_top1", "density.f_drop_top5"]
    keys += [
        f"sturdy.{k}"
        for k in "loso_min_f loso_min_state f_drop_top5_garimpo f_1990_2012 f_2013_2024".split()
    ]
    keys += ["estimates.finite"]
    return keys


def dig(tree, dotted):
    node = tree
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"missing key {dotted}"
        node = node[part]
    return node


def all_keys(tree):
    for k, v in tree.items():
        yield k
        if isinstance(v, dict):
            yield from all_keys(v)


def test_results_have_every_listed_key_and_parse_as_standard_json(tmp_path):
    results, panel = run(0.02)
    assert results["estimates"]["finite"] is True
    write_results(tmp_path, gyn._summary(results, panel), results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject_constant)
    for key in listed_keys():
        dig(parsed, key)
    assert not any("." in k for k in all_keys(parsed))
    assert set(parsed) == {
        "first_stage",
        "placebo",
        "event",
        "secondary",
        "density",
        "sturdy",
        "estimates",
    }
    assert parsed["first_stage"]["f_cluster"] > 0
    assert parsed["placebo"]["lead_ratio"] > 0
    assert len(parsed["density"]["top5"]) == 5
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "chosen after seeing campaign 0007" in summary
    assert "Moreno-Louzada" in summary


def test_a_nan_is_written_as_null_and_flags_the_estimates(tmp_path):
    results = gyn.finalize(
        {
            "first_stage": {"beta": float("nan"), "f_cluster": 3.0, "n": np.int64(4)},
            "placebo": {"lead_ratio": 0.5, "other": float("inf")},
            "density": {"top5": [{"cd_ibge": "1", "uf": "PA"}]},
        }
    )
    assert results["first_stage"]["beta"] is None
    assert results["placebo"]["other"] is None
    assert results["density"]["top5"] == [{"cd_ibge": "1", "uf": "PA"}]
    assert results["estimates"]["finite"] is False
    write_results(tmp_path, "x", results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject_constant)
    assert parsed["first_stage"]["beta"] is None


# Done when 6


def test_rows_outside_the_half_are_dropped_before_estimation():
    mining, exposure, prices, half = synthetic(0.02, outside=5)
    assert mining["cd_ibge"].n_unique() == 65
    with_outside, panel = gyn.build_results(mining, exposure, prices, half, n_draws=5)
    inside = pl.col("cd_ibge").is_in(sorted(half))
    clean = gyn.build_results(mining.filter(inside), exposure.filter(inside), prices, half, 5)[0]
    assert with_outside["first_stage"]["n_munis"] == 60
    assert panel.n_half == 60
    assert with_outside["first_stage"]["beta"] == pytest.approx(clean["first_stage"]["beta"])
    assert with_outside["density"]["top5"] == clean["density"]["top5"]


def test_the_script_restricts_and_is_independent_of_0007():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source
    assert "0007_gold_first_stage import" not in source
    assert "gold_first_stage" not in source.replace("gold_yes_no_first_stage", "")
