import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.explore import write_results

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0008_gold_politics.py"
SPEC = importlib.util.spec_from_file_location("gold_politics", SCRIPT)
gp = importlib.util.module_from_spec(SPEC)
sys.modules["gold_politics"] = gp
SPEC.loader.exec_module(gp)

ELECTIONS = list(gp.ELECTIONS)
UFS = ["PA", "MT", "RO"]
PLANTED = "cands_per_seat"
NULL = "enc_mayor"
EFFECT = 0.5


def synthetic(
    receipts: dict[int, int] | None = None, outside: int = 0, effect: float = EFFECT, seed: int = 11
):
    """60 municipalities in 3 states (plus `outside` others), seven elections.

    `cands_per_seat` carries the planted effect on D = E x mean ln gold price of e-4..e-1;
    `enc_mayor` is independent noise.
    """
    rng = np.random.default_rng(seed)
    years = list(range(1990, 2026))
    ln_gold = 5.0 + 0.4 * np.sin(np.array(years) / 3.0) + 0.02 * (np.array(years) - 1990)
    ln_soy = 3.0 + 0.3 * np.cos(np.array(years) / 2.0)
    prices = pl.DataFrame(
        {"year": years, "ln_gold_real": ln_gold.tolist(), "ln_soy_real": ln_soy.tolist()}
    )
    n = 60 + outside
    codes = [f"15{i:05d}" for i in range(n)]
    state = [i // 20 if i < 60 else 0 for i in range(n)]
    d = np.array([1.0 if i % 2 == 0 else 0.0 for i in range(n)])
    if outside:
        d[60:] = 1.0
    indigenous = rng.uniform(0, 0.5, n)
    exposure = pl.DataFrame(
        {
            "cd_ibge": codes,
            "uf": [UFS[s] for s in state],
            "area_km2": rng.uniform(500, 5000, n).tolist(),
            "centroid_x_km": rng.uniform(0, 1000, n).tolist(),
            "centroid_y_km": rng.uniform(0, 1000, n).tolist(),
            "indigenous_share": indigenous.tolist(),
            "geo_exposed": [bool(x) for x in d],
            "geo_n_gold": [int(x) * 3 for x in d],
            "geo_gold_per_km2": (rng.uniform(0.1, 5.0, n) * d).tolist(),
            "geo_gold_indigenous_share": [
                float(v) if x else None for v, x in zip(rng.uniform(0, 1, n), d, strict=True)
            ],
            "title_gold_pre2000_share": rng.uniform(0, 1, n).tolist(),
            "title_sand_pre2000_share": rng.uniform(0, 1, n).tolist(),
        }
    )
    lag = {e: float(np.mean([ln_gold[years.index(y)] for y in range(e - 4, e)])) for e in ELECTIONS}
    state_election = rng.normal(0, 0.05, (3, len(ELECTIONS)))
    base = rng.uniform(1, 2, n)
    receipts = receipts or {2004: 5000, 2008: 5000, 2012: 5000}
    politics = {}
    for j, e in enumerate(ELECTIONS):
        columns = {"cd_ibge": codes}
        columns[PLANTED] = [
            effect * d[i] * lag[e] + base[i] + state_election[state[i], j] + rng.normal(0, 0.02)
            for i in range(n)
        ]
        for name in gp.OUTCOMES:
            if name == PLANTED:
                continue
            columns[name] = rng.normal(0, 1, n).tolist()
        if e == 2000:
            columns["seat_turnover"] = [None] * n
            columns["incumbent_reelected"] = [None] * n
        if e not in gp.MONEY_ELECTIONS:
            columns[gp.MONEY] = [None] * n
        columns["n_receipts_with_cnae"] = [receipts.get(e, 0) // n] * n
        politics[e] = pl.DataFrame(columns, strict=False)
    return politics, exposure, prices, frozenset(codes[:60])


def run(n_draws: int = 200, **kwargs):
    politics, exposure, prices, half = synthetic(**kwargs)
    return gp.build_results(politics, exposure, prices, half, n_draws=n_draws)


def reject_constant(name):
    raise ValueError(f"non-standard JSON constant {name}")


# Done when 1


def test_recovers_a_planted_beta_and_a_null_outcome_has_a_large_ri_p():
    results, panel = run()
    outcomes = results["outcomes"]
    planted, null = outcomes[PLANTED], outcomes[NULL]
    assert abs(planted["beta"] - EFFECT) / EFFECT < 0.10
    assert planted["ri_p"] < 0.05
    assert null["ri_p"] > 0.05
    assert planted["n_munis"] == 60 and planted["n_obs"] == 60 * 7
    assert len(panel.codes) == 60
    assert set(planted["event"]["coef"]) == {f"e{e}" for e in ELECTIONS[1:]}


def test_every_block_is_present_and_the_seed_makes_a_run_repeatable():
    first, second = run(n_draws=20)[0], run(n_draws=20)[0]
    assert first == second
    o = first["outcomes"][PLANTED]
    for key in (
        "beta se conley_se_50km conley_se_100km conley_se_200km ri_p q_bh mean sd n_obs n_munis"
    ).split():
        assert key in o
    assert set(o["placebo"]) == {"soy_beta", "soy_se", "sand_beta", "sand_se"}
    assert set(o["robust"]) == {"density_beta", "density_se", "titles_beta", "titles_se"}
    assert set(o["regimes"]) == {
        "pre_beta",
        "pre_se",
        "goodfaith_beta",
        "goodfaith_se",
        "diff_beta",
        "diff_se",
    }
    assert set(o["access"]) == {"beta", "se"}
    assert o["regimes"]["diff_beta"] == pytest.approx(
        o["regimes"]["pre_beta"] - o["regimes"]["goodfaith_beta"]
    )
    assert gp.SEED == 20261111 and gp.N_DRAWS == 1000


def test_outcomes_that_start_in_2004_use_it_as_the_event_base():
    outcomes = run(n_draws=10)[0]["outcomes"]
    for name in ("seat_turnover", "incumbent_reelected"):
        assert set(outcomes[name]["event"]["coef"]) == {f"e{e}" for e in ELECTIONS[2:]}
        assert outcomes[name]["n_obs"] == 60 * 6
        assert "regimes" in outcomes[name]


# Done when 2


def test_a_missing_value_drops_only_its_row_and_the_count_is_reported():
    politics, exposure, prices, half = synthetic()
    for e, rows in ((2008, range(0, 10)), (2016, range(5, 12))):
        values = politics[e]["homicide_rate"].to_list()
        for i in rows:
            values[i] = None
        politics[e] = politics[e].with_columns(pl.Series("homicide_rate", values, dtype=pl.Float64))
    results, panel = gp.build_results(politics, exposure, prices, half, n_draws=10)
    o = results["outcomes"]["homicide_rate"]
    assert o["n_obs"] == 60 * 7 - 17
    assert o["n_munis"] == 60
    assert o["beta"] is not None and o["se"] is not None
    assert gp._dropped(panel, "homicide_rate") == 17
    assert "- `homicide_rate`: 17 of 420 rows" in gp._summary(results, panel)


def test_an_outcome_with_no_data_gets_nulls_and_does_not_stop_the_run():
    politics, exposure, prices, half = synthetic()
    for e in ELECTIONS:
        politics[e] = politics[e].with_columns(pl.lit(None, dtype=pl.Float64).alias("margin_mayor"))
    results, _ = gp.build_results(politics, exposure, prices, half, n_draws=10)
    o = results["outcomes"]["margin_mayor"]
    assert o["beta"] is None and o["ri_p"] is None and o["q_bh"] is None
    assert o["event"]["coef"]["e2024"] is None and o["regimes"]["diff_beta"] is None
    assert results["estimates"]["finite"] is False
    assert results["outcomes"][PLANTED]["beta"] is not None
    json.dumps(results, allow_nan=False)


def _null_in(election: int, name: str = "homicide_rate"):
    politics, exposure, prices, half = synthetic()
    politics[election] = politics[election].with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
    return gp.build_results(politics, exposure, prices, half, n_draws=10)[0]


def test_an_election_on_the_list_with_no_data_gives_null_keys_and_clears_the_flag():
    results = _null_in(2024)
    o = results["outcomes"]["homicide_rate"]
    assert set(o["event"]["coef"]) == {f"e{e}" for e in ELECTIONS[1:]}
    assert set(o["event"]["se"]) == set(o["event"]["coef"])
    assert o["event"]["coef"]["e2024"] is None and o["event"]["se"]["e2024"] is None
    assert o["event"]["coef"]["e2020"] is not None
    assert set(o["regimes"]) == {
        "pre_beta",
        "pre_se",
        "goodfaith_beta",
        "goodfaith_se",
        "diff_beta",
        "diff_se",
    }
    assert o["beta"] is not None
    assert results["estimates"]["finite"] is False


def test_no_data_on_one_side_of_the_split_gives_null_regimes_not_absent_ones():
    politics, exposure, prices, half = synthetic()
    for e in (2016, 2020, 2024):
        politics[e] = politics[e].with_columns(
            pl.lit(None, dtype=pl.Float64).alias("homicide_rate")
        )
    results = gp.build_results(politics, exposure, prices, half, n_draws=10)[0]
    o = results["outcomes"]["homicide_rate"]
    assert o["regimes"]["pre_beta"] is None and o["regimes"]["diff_se"] is None
    assert results["estimates"]["finite"] is False


def test_a_missing_base_election_gives_null_event_keys():
    o = _null_in(2000)["outcomes"]["homicide_rate"]
    assert set(o["event"]["coef"]) == {f"e{e}" for e in ELECTIONS[1:]}
    assert all(v is None for v in o["event"]["coef"].values())


def test_bh_matches_a_hand_computation():
    # sorted: .01 .02 .03 .04 .50; p * 5 / rank = .05 .05 .05 .05 .50
    p = [0.04, 0.01, 0.50, 0.03, 0.02]
    assert gp.bh(p) == pytest.approx([0.05, 0.05, 0.50, 0.05, 0.05])
    # p * m / rank = .005*4/1=.02, .02*4/2=.04, .03*4/3=.04, .60*4/4=.60
    assert gp.bh([0.60, 0.005, 0.03, 0.02]) == pytest.approx([0.60, 0.02, 0.04, 0.04])
    assert np.isnan(gp.bh([0.1, float("nan")])[1])


def test_ri_p_formula_on_known_draws():
    draws = np.array([0.5, -2.0, 1.0, -0.1, 3.0])
    assert gp.ri_p_value(1.0, draws) == pytest.approx(4 / 6)
    assert gp.ri_p_value(-1.0, draws) == pytest.approx(4 / 6)
    assert gp.ri_p_value(10.0, draws) == pytest.approx(1 / 6)
    assert np.isnan(gp.ri_p_value(float("nan"), draws))


def test_window_mean_is_the_four_years_before_the_election():
    prices = pl.DataFrame({"year": list(range(1996, 2001)), "ln_gold_real": [1.0, 2, 3, 4, 100]})
    assert gp.window_mean(prices, "ln_gold_real", 2000) == pytest.approx(2.5)
    with pytest.raises(gp.PoliticsError):
        gp.window_mean(prices, "ln_gold_real", 2008)


# Done when 3


def test_the_money_rule_skips_with_one_qualifying_election():
    assert gp.money_rule({2004: 0, 2008: 1000, 2012: 999}) is True
    results, _ = run(n_draws=10, receipts={2004: 600, 2008: 6000, 2012: 600})
    assert results["money"]["skipped"] is True
    assert results["family"]["n_outcomes"] == 8
    assert gp.MONEY not in results["outcomes"]
    assert results["money"]["n_with_cnae"] == {"e2004": 600, "e2008": 6000, "e2012": 600}
    assert results["estimates"]["finite"] is True


def test_the_money_rule_keeps_the_outcome_with_two_qualifying_elections():
    assert gp.money_rule({2004: 1000, 2008: 1000, 2012: 0}) is False
    results, _ = run(n_draws=10, receipts={2004: 1200, 2008: 6000, 2012: 600})
    assert results["money"]["skipped"] is False
    assert results["family"]["n_outcomes"] == 9
    money = results["outcomes"][gp.MONEY]
    assert set(money["event"]["coef"]) == {"e2008", "e2012"}
    assert "regimes" not in money
    assert money["n_obs"] == 60 * 3
    assert results["estimates"]["finite"] is True


def test_the_summary_lists_absent_blocks():
    results, panel = run(n_draws=10, receipts={2004: 1200, 2008: 6000})
    text = gp._summary(results, panel)
    assert f"`{gp.MONEY}.regimes`" in text
    assert "nothing on the exploration half is a finding" in text.lower()
    assert "Moreno-Louzada" in text
    skipped, panel = run(n_draws=10, receipts={2004: 0})
    assert "skipped" in gp._summary(skipped, panel)


# Done when 4


def test_results_json_is_standard_json_with_the_finite_flag(tmp_path):
    results, panel = run(n_draws=10)
    assert results["estimates"]["finite"] is True
    write_results(tmp_path, gp._summary(results, panel), results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject_constant)
    assert parsed["estimates"]["finite"] is True


def test_a_non_finite_number_becomes_null_and_clears_the_flag():
    clean = gp.finalize({"outcomes": {"x": {"beta": float("nan"), "se": float("inf")}}, "n": 3})
    assert clean["outcomes"]["x"] == {"beta": None, "se": None}
    assert clean["estimates"]["finite"] is False
    json.loads(json.dumps(clean), parse_constant=reject_constant)
    assert gp.finalize({"a": 1.0})["estimates"]["finite"] is True


# Done when 5


def test_rows_outside_the_half_are_dropped_before_estimation():
    results, panel = run(n_draws=10, outside=15)
    assert len(panel.codes) == 60
    assert all(int(c[2:]) < 60 for c in panel.codes)
    assert results["outcomes"][PLANTED]["n_munis"] == 60
    assert abs(results["outcomes"][PLANTED]["beta"] - EFFECT) / EFFECT < 0.10


def test_the_script_reads_the_half_and_nothing_it_should_not():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source
    assert "mining_panel" not in source.replace("`mining_panel`", "")
    assert "sealed/" not in source.replace("`sealed/`", "").replace('startswith("sealed/")', "")
