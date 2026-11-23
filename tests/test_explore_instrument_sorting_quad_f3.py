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
    "instrument_sorting_quad_f3", REPO / "explore" / "0010_instrument_sorting_quad_f3.py"
)
fk = importlib.util.module_from_spec(SPEC)
sys.modules["instrument_sorting_quad_f3"] = fk
SPEC.loader.exec_module(fk)
s1 = fk.s1

H = 0.075
JUMP = 0.5  # planted jump in ln(1 + reais per inhabitant)
CURVE = 1.0  # planted curvature: CURVE x (10 x margin)^2 where the party won, no jump at 0
RACES = 110  # per cycle: 330 in all
SEEDS = (1, 2, 3, 4, 5)
FEW_DRAWS = 200


def make_panel(
    seed: int = 1,
    jump: float = 0.0,
    curve: float = 0.0,
    pre_jump: float = 0.0,
    races: int = RACES,
) -> pl.DataFrame:
    """Three cycles, `races` races each, two deputies per race (one wins, one loses).

    Money is ln(1 + reais per inhabitant) = 1 + noise + `jump` where the party won + `curve` x
    (10 x margin)^2 where it won. Pix exists in B and C only. `pre_jump` is planted in the
    pre-window outcome.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for cycle in fk.ALL_CYCLES:
        for i in range(races):
            code = f"15{i:05d}"
            pop = float(rng.uniform(20_000, 100_000))
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 8))}"
                shape = jump + curve * (10 * margin) ** 2 if win else 0.0
                lpc = 1.0 + rng.normal(0, 0.05) + shape
                pre_lpc = 1.0 + rng.normal(0, 0.05) + (pre_jump if win else 0.0)
                nonpix = pop * (np.exp(lpc) - 1.0)
                if cycle == "A":
                    pix = 0.0
                else:
                    pix = float(rng.poisson(300.0 * pop / 50_000 * (1.3 if win else 1.0)))
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
    table, no_pop, floored = fk.add_measures(panel, H)
    return fk.prepare(table), no_pop, floored


@cache
def cached():
    table, no_pop, floored = fk.add_measures(make_panel(1, jump=JUMP), H)
    return table, fk.build_results(table, H, no_pop, floored)


# --- Done when 1


@pytest.mark.parametrize("seed", SEEDS)
def test_quadratic_fit_recovers_a_planted_jump_with_no_curvature(seed):
    table, _, _ = prepared(make_panel(seed, jump=JUMP))
    draws = fk.sign_draws(fk.n_races(table), FEW_DRAWS)
    fit = fk.linear_fit(table, draws, H, "lpc_total")
    assert abs(fit["b"] - JUMP) < 0.1 * JUMP
    assert fit["n_races"] >= 300
    assert fit["ri_p"] < 0.05


# --- Done when 2


@pytest.mark.parametrize("seed", SEEDS)
def test_planted_quadratic_with_no_jump_gives_a_b_near_zero(seed):
    table, _, _ = prepared(make_panel(seed, curve=CURVE))
    draws = fk.sign_draws(fk.n_races(table), FEW_DRAWS)
    quad = fk.linear_fit(table, draws, H, "lpc_total", poly=2)
    assert abs(quad["b"]) < 2 * quad["se"]
    # the local linear model counts that curvature as a jump
    linear = fk.linear_fit(table, draws, H, "lpc_total", poly=1)
    assert abs(linear["b"]) > 4 * linear["se"]


# --- Done when 3


@pytest.mark.parametrize("seed", SEEDS)
def test_with_m2_and_wm2_dropped_the_controls_fit_equals_s1(seed):
    table, _, _ = prepared(make_panel(seed, jump=JUMP, races=60))
    draws = fk.sign_draws(fk.n_races(table), FEW_DRAWS)
    for controls, floor in ((fk.CONTROLS, 0.0), ((), 0.0), (fk.CONTROLS, fk.DONUT)):
        old = s1.controls_fit(table, draws, H, "lpc_total", controls, floor)
        new = fk.controls_fit(table, draws, H, "lpc_total", controls, floor, poly=1)
        assert new["b"] == pytest.approx(old["b"], rel=1e-9)
        assert new["se"] == pytest.approx(old["se"], rel=1e-9)
        assert new["ri_p"] == old["ri_p"]
        assert new["n_units"] == old["n_units"]
    plain_old = s1.linear_fit(table, draws, H, "lpc_total")
    plain_new = fk.linear_fit(table, draws, H, "lpc_total", poly=1)
    assert plain_new["b"] == pytest.approx(plain_old["b"], rel=1e-9)
    assert plain_new["ri_p"] == plain_old["ri_p"]
    old_cycles = s1.cycle_fit(table, H, "lpc_total", fk.ALL_CYCLES)
    new_cycles = fk.cycle_fit(table, H, "lpc_total", fk.ALL_CYCLES, poly=1)
    for key, v in old_cycles.items():
        assert new_cycles[key]["b"] == pytest.approx(v["b"], rel=1e-9)
        assert new_cycles[key]["se"] == pytest.approx(v["se"], rel=1e-9)


def test_the_quadratic_controls_fit_counts_five_plus_the_controls():
    table, _, _ = prepared(make_panel(1, jump=JUMP, races=60))
    draws = fk.sign_draws(fk.n_races(table), FEW_DRAWS)
    fit = fk.controls_fit(table, draws, H, "lpc_total", fk.CONTROLS)
    assert fit["f_cluster"] == pytest.approx((fit["b"] / fit["se"]) ** 2)
    assert fit["ci_high"] - fit["b"] == pytest.approx(1.96 * fit["se"])
    assert fk._k(1) == 3 and fk._k(2) == 5
    with pytest.raises(ValueError):
        fk._k(3)


# --- Done when 4


def test_wm2_is_recomputed_from_the_flipped_win_and_m2_stays_fixed():
    table, _, _ = prepared(make_panel(2, jump=JUMP, races=20))
    sub = fk._usable(table, H, "lpc_total")
    s = fk._sample(sub, "lpc_total")
    rng = np.random.default_rng(7)
    signs = rng.choice([-1.0, 1.0], size=(3, s.n))
    flipped = fk.design(s, signs, 2)
    observed = fk.design(s, np.ones((1, s.n)), 2)[0]
    base = s.margin * fk.SCALE
    for d in range(3):
        m = signs[d] * base
        win = (m > 0).astype(float)
        assert flipped[d][:, 0] == pytest.approx(s.demean(win[None])[0])
        assert flipped[d][:, 3] == pytest.approx(s.demean((base**2)[None])[0])  # m2 fixed
        assert flipped[d][:, 4] == pytest.approx(s.demean((win * base**2)[None])[0])
        # held fixed at the observed win, wm2 would differ
        assert not np.allclose(flipped[d][:, 4], observed[:, 4])
    assert np.allclose(observed[:, 3], flipped[0][:, 3])


# --- Done when 5


def test_pre_fail_is_one_with_a_planted_pre_jump_and_zero_with_none():
    for seed in SEEDS:
        table, _, _ = prepared(make_panel(seed, jump=JUMP))
        draws = fk.sign_draws(fk.n_races(table), FEW_DRAWS)
        post_b = fk.linear_fit(table, draws, H, "lpc_total")["b"]
        flat = fk.placebo_block(table, draws, H, post_b)
        assert flat["pre_fail"] == 0 and isinstance(flat["pre_fail"], int)
        table, _, _ = prepared(make_panel(seed, jump=JUMP, pre_jump=0.4))
        post_b = fk.linear_fit(table, draws, H, "lpc_total")["b"]
        planted = fk.placebo_block(table, draws, H, post_b)
        assert planted["pre_fail"] == 1
        assert planted["ratio"] > 0.5 and planted["pre"]["ri_p"] < 0.05


# --- Done when 6


def test_window_must_be_7_5(tmp_path):
    record = tmp_path / "gate.json"
    record.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert fk.read_window(record) == pytest.approx(0.075)
    for bad in (5.0, 7.6, None):
        record.write_text(json.dumps({"window": {"h_pct": bad}}), encoding="utf-8")
        with pytest.raises(fk.GateError, match="not 7.5"):
            fk.read_window(record)
    assert fk.read_window() == pytest.approx(0.075)  # the real record


# --- Done when 7


def test_rows_outside_the_exploration_half_are_dropped_first():
    panel = make_panel(1, races=6)
    half = frozenset({"1500000", "1500003"})
    seen = []

    def read(name, columns):
        seen.append((name, list(columns)))
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded = fk.load_panels(read, half)
    assert [n for n, _ in seen] == ["panel_A", "panel_B", "panel_C"]
    assert all(cols == fk.PANEL_COLUMNS for _, cols in seen)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == 3 * 2 * 2

    def no_column(name, columns):
        return panel.select("cycle", "deputy")

    with pytest.raises(Exception, match="cd_ibge"):
        fk.load_panels(no_column, half)


# --- Done when 8


def test_results_have_s1_paths_plus_spec_and_json_is_standard(tmp_path):
    from terrain.explore import write_results

    table, results = cached()
    for key in (
        "window",
        "counts",
        "instruments",
        "check_5pct",
        "levels",
        "sorting",
        "first_stage",
        "placebo",
        "poisson_diff",
        "declared",
        "estimates",
    ):
        assert key in results
    assert results["spec"] == {"polynomial": 2, "parent_run": "45248303745"}
    assert set(results["first_stage"]) == {"f_cluster", "b", "se"}
    assert set(results["placebo"]) == {"pre", "post_b", "ratio", "pre_fail"}
    assert set(results["sorting"]["controls"]) == set(fk.SORT_KEYS)
    assert set(results["sorting"]["windows"]) == {"w2_5pct", "w5pct", "w7_5pct", "w10pct"}
    assert set(results["instruments"]["pix"]["poisson"]) == {"pooled", "B", "C", "c_minus_b"}
    assert set(results["declared"]) == set(fk.DECLARED)
    assert results["first_stage"]["b"] == pytest.approx(results["sorting"]["controls"]["b"])
    assert results["placebo"]["post_b"] == results["instruments"]["total"]["log_pc"]["pooled"]["b"]
    assert results["estimates"]["finite"] is True
    assert results["first_stage"]["b"] == pytest.approx(JUMP, abs=0.1)

    fk.write_figures(results, table, H, tmp_path)
    write_results(tmp_path, fk.summarize(results), results)

    def reject(constant):
        raise AssertionError(f"not standard JSON: {constant}")

    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject)
    assert parsed["first_stage"]["f_cluster"] > 10
    assert parsed["placebo"]["pre_fail"] in (0, 1)
    assert parsed["spec"]["polynomial"] == 2
    assert len(text.encode("utf-8")) < 200_000
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "survived (fork)" in summary and "killed (fork)" in summary
    assert "parent b" in summary and "45248303745" in summary
    assert "Nothing on the exploration half is a finding" in summary
    for name in ("binned_money", "coef_by_cycle", "poisson_premium"):
        png = tmp_path / "figures" / f"{name}.png"
        assert png.is_file() and 0 < png.stat().st_size < 400_000


def test_the_parent_record_gives_b_and_f_for_every_sorting_row():
    parent = fk.parent_sorting()
    _, results = cached()
    expected = {k for k in results["sorting"] if k != "windows"} | {
        f"windows.{k}" for k in results["sorting"]["windows"]
    }
    assert set(parent) == expected
    assert parent["controls"]["f_cluster"] > 10


def test_a_non_finite_number_is_null_and_makes_finite_false():
    panel = make_panel(1, races=20).with_columns(pl.lit(0.0).alias("amend_post_pix"))
    table, no_pop, floored = fk.add_measures(panel, H)
    results = fk.build_results(table, H, no_pop, floored)
    assert results["instruments"]["pix"]["poisson"]["pooled"]["b"] is None
    assert results["estimates"]["finite"] is False
    json.dumps(results, allow_nan=False)
