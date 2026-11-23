import importlib.util
import json
import sys
from functools import cache
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "instrument_sorting", REPO / "explore" / "0010_instrument_sorting.py"
)
es = importlib.util.module_from_spec(SPEC)
sys.modules["instrument_sorting"] = es
SPEC.loader.exec_module(es)

H = 0.075
JUMPS = (0.4, 0.5, 0.6)  # planted jump in ln(1 + non-Pix reais per inhabitant), by cycle
PIX_PREMIUM = 0.30  # Pix reais are 1.3 times higher where the party won
RACES = 110  # per cycle: 330 in all
SEEDS = (1, 2, 3, 4, 5)


def make_panel(seed: int = 1, pre_jump: float = 0.0, races: int = RACES) -> pl.DataFrame:
    """Three cycles, `races` races each, two deputies per race (one wins, one loses).

    Deputies each have several municipalities. Non-Pix money is ln(1 + reais per inhabitant) = 1 +
    noise, plus `JUMPS[cycle]` where the party won. Pix exists in B and C only: Poisson reais, 1.3
    times higher where the party won. `pre_jump` is planted in the pre-window outcome.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ci, cycle in enumerate(es.ALL_CYCLES):
        for i in range(races):
            code = f"15{i:05d}"
            pop = float(rng.uniform(20_000, 100_000))
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 8))}"
                lpc = 1.0 + rng.normal(0, 0.05) + (JUMPS[ci] if win else 0.0)
                nonpix = pop * (np.exp(lpc) - 1.0)
                pre_lpc = 1.0 + rng.normal(0, 0.05) + (pre_jump if win else 0.0)
                if cycle == "A":
                    pix = 0.0
                else:
                    rate = 300.0 * pop / 50_000 * ((1.0 + PIX_PREMIUM) if win else 1.0)
                    pix = float(rng.poisson(rate))
                total = nonpix + pix
                rows.append(
                    {
                        "cycle": cycle,
                        "cd_ibge": code,
                        "deputy": deputy,
                        "margin": margin,
                        "win": win,
                        "population_m": pop,
                        "party_held_mayor": bool(rng.uniform() > 0.5),
                        "fin_female": bool(rng.uniform() > 0.8),
                        "fin_age": float(rng.integers(30, 70)),
                        "fin_higher_ed": bool(rng.uniform() > 0.5),
                        "n_mayor_cands": int(rng.integers(2, 6)),
                        "amend_pre_total": pop * (np.exp(pre_lpc) - 1.0),
                        "amend_pre_log_pc": pre_lpc,
                        "amend_post_total": total,
                        "amend_post_pix": pix,
                        "amend_post_log_pc": float(np.log1p(total / pop)),
                    }
                )
    return pl.DataFrame(rows)


def prepared(panel: pl.DataFrame):
    table, no_pop, floored = es.add_measures(panel, H)
    return es.prepare(table), no_pop, floored


@cache
def cached():
    table, no_pop, floored = es.add_measures(make_panel(1), H)
    return table, es.build_results(table, H, no_pop, floored)


@cache
def cached_pre():
    table, no_pop, floored = es.add_measures(make_panel(2, pre_jump=0.5), H)
    return table, es.build_results(table, H, no_pop, floored)


# --- Done when 1


@pytest.mark.parametrize("seed", SEEDS)
def test_planted_linear_jump_and_poisson_premium_are_recovered(seed):
    table, _, _ = prepared(make_panel(seed))
    draws = es.sign_draws(es.n_races(table))
    mean_jump = float(np.mean(JUMPS))
    linear = es.linear_fit(table, draws, H, "lpc_nonpix")
    assert abs(linear["b"] - mean_jump) < 0.1 * mean_jump
    assert linear["n_races"] >= 300
    bc = es._of(table, es.PIX_CYCLES)
    pix = es.poisson_fit(bc, H, "r_pix")
    assert abs(pix["premium_pct"] - 100 * PIX_PREMIUM) < 5
    assert pix["premium_ci_low"] < pix["premium_pct"] < pix["premium_ci_high"]
    assert pix["n_obs"] > 300


def test_results_have_the_documented_keys():
    _, results = cached()
    assert results["window"] == {"h_pct": 7.5, "check_pct": 5.0, "source": es.WINDOW_SOURCE}
    assert results["counts"]["races_h"] >= 300
    assert set(results["counts"]["by_cycle"]) == {"A", "B", "C"}
    inst = results["instruments"]
    assert set(inst) == {"total", "pix", "nonpix"}
    assert set(inst["total"]["log_pc"]) == {"pooled", "A", "B", "C", "c_minus_a"}
    assert set(inst["nonpix"]["any"]) == {"pooled", "A", "B", "C", "c_minus_a"}
    assert set(inst["pix"]["log_pc"]) == {"pooled", "B", "C", "c_minus_b"}  # no Pix key for A
    assert set(inst["pix"]["poisson"]) == {"pooled", "B", "C", "c_minus_b"}
    assert set(inst["total"]["log_pc"]["pooled"]) == set(es.LINEAR_KEYS)
    assert set(inst["total"]["log_pc"]["A"]) == {"b", "se", "ci_low", "ci_high"}
    assert {"b", "se", "p", "premium_pct", "premium_ci_low", "premium_ci_high", "n_obs"} <= set(
        inst["total"]["poisson"]["pooled"]
    )
    assert set(results["check_5pct"]["pix"]) == {"log_pc", "any", "poisson"}
    assert set(results["check_5pct"]["pix"]["poisson"]) == {"b", "se", "p"}
    assert set(results["check_5pct"]["pix"]["any"]) == {"b", "se", "ri_p"}
    assert set(results["levels"]) == {"total", "pix", "nonpix", "pix_share", "gap"}
    assert set(results["levels"]["pix_share"]) == {"B", "C", "pooled_bc"}
    assert set(results["levels"]["gap"]) == {"A", "B", "C", "pooled_bc"}
    assert set(results["sorting"]) == {"controls", "held_true", "held_false", "donut", "windows"}
    assert set(results["sorting"]["windows"]) == {"w2_5pct", "w5pct", "w7_5pct", "w10pct"}
    assert set(results["sorting"]["controls"]) == set(es.SORT_KEYS)
    assert set(results["first_stage"]) == {"f_cluster", "b", "se"}
    assert set(results["placebo"]) == {"pre", "post_b", "ratio", "pre_fail"}
    assert set(results["declared"]) == set(es.DECLARED)
    assert {v["p_kind"] for v in results["declared"].values()} == {"ri", "cluster"}
    assert set(results["poisson_diff"]["pix_minus_nonpix"]) == {
        "b",
        "se",
        "p",
        "ratio_pct",
        "n_obs",
    }
    assert results["estimates"]["finite"] is True
    assert results["sorting"]["windows"]["w7_5pct"]["b"] == pytest.approx(
        results["sorting"]["controls"]["b"]
    )


def test_total_log_pc_equals_the_panel_column_and_pix_is_null_in_cycle_a():
    panel = make_panel(1, races=10)
    table, _, _ = es.add_measures(panel, H)
    assert table["lpc_total"].to_numpy() == pytest.approx(table["amend_post_log_pc"].to_numpy())
    assert (
        table.filter(pl.col("cycle") == "A")["r_pix"].null_count()
        == table.filter(pl.col("cycle") == "A").height
    )
    assert table.filter(pl.col("cycle") != "A")["r_pix"].null_count() == 0
    assert set(table["any_nonpix"].unique()) <= {0.0, 1.0}
    assert table["lev_total"].to_numpy() == pytest.approx(
        (table["amend_post_total"] / table["population_m"]).to_numpy()
    )


def test_no_population_and_floored_rows_are_counted():
    panel = make_panel(1, races=10)
    panel = panel.with_columns(
        pl.when(pl.col("cd_ibge") == "1500001")
        .then(None)
        .otherwise(pl.col("population_m"))
        .alias("population_m"),
        pl.when((pl.col("cd_ibge") == "1500002") & (pl.col("cycle") == "B"))
        .then(pl.col("amend_post_pix") + 10_000_000.0)
        .otherwise(pl.col("amend_post_pix"))
        .alias("amend_post_pix"),
    )
    table, no_pop, floored = es.add_measures(panel, H)
    assert no_pop == 6  # three cycles, two deputies, all inside the window
    assert table.height == panel.height - 6
    assert floored == 2
    assert table["r_nonpix"].min() == 0.0


# --- Done when 2


def test_cycle_fit_equals_by_cycle_fit():
    table, _, _ = prepared(make_panel(3))
    old = es.by_cycle_fit(table, H, "lpc_total")
    new = es.cycle_fit(table, H, "lpc_total", ("A", "B", "C"))
    for key in ("A", "B", "C", "c_minus_a"):
        assert new[key]["b"] == pytest.approx(old[key]["b"], rel=1e-9)
        assert new[key]["se"] == pytest.approx(old[key]["se"], rel=1e-9)
    assert new["c_minus_b"]["b"] == pytest.approx(new["C"]["b"] - new["B"]["b"])
    two = es.cycle_fit(table, H, "lpc_total", ("B", "C"))
    assert set(two) == {"B", "C", "c_minus_b"}
    assert np.isfinite([v["se"] for v in two.values()]).all()


def test_poisson_differences_equal_the_differences_of_the_separate_fits():
    table, _, _ = prepared(make_panel(1))
    for column, earlier, later in (
        ("r_total", "A", "C"),
        ("r_nonpix", "A", "C"),
        ("r_pix", "B", "C"),
    ):
        diff = es.poisson_cycles(table, H, column, earlier, later)
        a = es.poisson_fit(es._of(table, (earlier,)), H, column)
        b = es.poisson_fit(es._of(table, (later,)), H, column)
        assert diff["b"] == pytest.approx(b["b"] - a["b"], abs=1e-4)
        assert np.isfinite(diff["se"]) and 0 <= diff["p"] <= 1
    bc = es._of(table, es.PIX_CYCLES)
    stacked = es.poisson_stacked(bc, H, "r_pix", "r_nonpix")
    pix = es.poisson_fit(bc, H, "r_pix")
    nonpix = es.poisson_fit(bc, H, "r_nonpix")
    assert stacked["b"] == pytest.approx(pix["b"] - nonpix["b"], abs=1e-4)
    assert stacked["n_obs"] == pix["n_obs"] + nonpix["n_obs"]
    assert np.isfinite(stacked["se"]) and 0 <= stacked["p"] <= 1


def test_levels_add_up_and_the_pix_share_is_a_ratio():
    _, results = cached()
    levels = results["levels"]
    for scope, gap in levels["gap"].items():
        assert gap == pytest.approx(0.0, abs=1e-8), scope
    for scope in ("B", "C", "pooled_bc"):
        assert levels["pix_share"][scope] == pytest.approx(
            levels["pix"][scope]["b"] / levels["total"][scope]["b"]
        )
        assert set(levels["pix"][scope]) == {"b", "se", "ci_low", "ci_high"}
    assert set(levels["pix"]) == {"B", "C", "pooled_bc"}
    assert set(levels["total"]) == {"A", "B", "C", "pooled_bc"}


# --- Done when 3


@pytest.mark.parametrize("seed", SEEDS)
def test_controls_model_with_no_controls_equals_estimate(seed):
    table, _, _ = prepared(make_panel(seed, races=40))
    draws = es.sign_draws(es.n_races(table))
    old = es.estimate(table, draws, H, "lpc_total")
    new = es.controls_fit(table, draws, H, "lpc_total", [])
    assert new["b"] == pytest.approx(old["b"], rel=1e-9)
    assert new["se"] == pytest.approx(old["se"], rel=1e-9)
    assert new["ri_p"] == old["ri_p"]
    assert new["n_dropped"] == 0
    assert new["n_units"] == old["units"]


def test_controls_are_demeaned_and_null_controls_are_dropped_and_counted():
    table, _, _ = prepared(make_panel(4, races=60))
    draws = es.sign_draws(es.n_races(table))
    fit = es.controls_fit(table, draws, H, "lpc_total", es.CONTROLS)
    assert fit["b"] == pytest.approx(np.mean(JUMPS), abs=0.1)
    assert fit["f_cluster"] == pytest.approx((fit["b"] / fit["se"]) ** 2)
    assert fit["ci_high"] - fit["b"] == pytest.approx(1.96 * fit["se"])
    holes = table.with_columns(
        pl.when(pl.col("cd_ibge") == "1500001")
        .then(None)
        .otherwise(pl.col("fin_age"))
        .alias("c_age")
    )
    dropped = es.controls_fit(holes, draws, H, "lpc_total", es.CONTROLS)
    assert dropped["n_dropped"] == 6
    assert dropped["n_units"] == fit["n_units"] - 6
    donut = es.controls_fit(table, draws, H, "lpc_total", es.CONTROLS, es.DONUT)
    inside = es.in_window(table, H).filter(pl.col("margin").abs() >= es.DONUT)
    assert donut["n_units"] == inside.height


# --- Done when 4


def test_pre_fail_is_one_with_a_planted_pre_jump_and_zero_with_none():
    _, flat = cached()
    assert flat["placebo"]["pre_fail"] == 0
    assert isinstance(flat["placebo"]["pre_fail"], int)
    assert abs(flat["placebo"]["pre"]["b"]) < 0.5 * abs(flat["placebo"]["post_b"])
    _, jump = cached_pre()
    assert jump["placebo"]["pre_fail"] == 1
    assert jump["placebo"]["pre"]["ri_p"] < 0.05
    assert jump["placebo"]["ratio"] > 0.5
    assert jump["placebo"]["post_b"] == jump["instruments"]["total"]["log_pc"]["pooled"]["b"]


# --- Done when 5


def test_holm():
    assert es.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert es.holm([0.5, 0.6]) == pytest.approx([1.0, 1.0])
    assert all(np.isnan(es.holm([0.01, float("nan")])))
    _, results = cached()
    declared = results["declared"]
    raw = [declared[n]["p"] for n in es.DECLARED]
    assert [declared[n]["p_holm"] for n in es.DECLARED] == pytest.approx(es.holm(raw))


# --- Done when 6


def test_window_must_be_7_5(tmp_path):
    record = tmp_path / "gate.json"
    record.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert es.read_window(record) == pytest.approx(0.075)
    for bad in (5.0, 7.6, None):
        record.write_text(json.dumps({"window": {"h_pct": bad}}), encoding="utf-8")
        with pytest.raises(es.GateError, match="not 7.5"):
            es.read_window(record)
    assert es.read_window() == pytest.approx(0.075)  # the real record


# --- Done when 7


def test_rows_outside_the_exploration_half_are_dropped_first():
    panel = make_panel(1, races=6)
    half = frozenset({"1500000", "1500003"})
    seen = []

    def read(name, columns):
        seen.append((name, list(columns)))
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded = es.load_panels(read, half)
    assert [n for n, _ in seen] == ["panel_A", "panel_B", "panel_C"]
    assert all(cols == es.PANEL_COLUMNS for _, cols in seen)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == 3 * 2 * 2
    assert set(loaded["cycle"]) == {"A", "B", "C"}

    def no_column(name, columns):
        return panel.select("cycle", "deputy")

    with pytest.raises(Exception, match="cd_ibge"):
        es.load_panels(no_column, half)


# --- Done when 8


def test_results_json_is_standard_json_with_the_kill_fields_and_figures_are_written(tmp_path):
    from terrain.explore import write_results

    table, results = cached()
    es.write_figures(results, table, H, tmp_path)
    write_results(tmp_path, es.summarize(results), results)

    def reject(constant):
        raise AssertionError(f"not standard JSON: {constant}")

    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject)
    assert parsed["first_stage"]["f_cluster"] > 10
    assert parsed["placebo"]["pre_fail"] in (0, 1)
    assert parsed["estimates"]["finite"] is True
    assert len(text.encode("utf-8")) < 200_000
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Nothing on the exploration half is a finding" in summary
    assert "Holm p" in summary
    assert "44484340952" in summary
    assert "further look at the same data" in summary
    assert "grew from cycle A to C" in summary
    assert "clustered errors only" in summary
    for name in ("binned_money", "coef_by_cycle", "poisson_premium"):
        png = tmp_path / "figures" / f"{name}.png"
        assert png.is_file() and 0 < png.stat().st_size < 400_000


def test_a_non_finite_number_is_null_and_makes_finite_false():
    panel = make_panel(1, races=20).with_columns(pl.lit(0.0).alias("amend_post_pix"))
    panel = panel.with_columns(pl.col("amend_post_pix").alias("amend_post_pix"))
    table, no_pop, floored = es.add_measures(panel, H)
    results = es.build_results(table, H, no_pop, floored)
    assert results["instruments"]["pix"]["poisson"]["pooled"]["b"] is None
    assert results["estimates"]["finite"] is False
    json.dumps(results, allow_nan=False)
