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
    "objects_gate", REPO / "explore" / "0013_objects_gate.py"
)
og = importlib.util.module_from_spec(SPEC)
sys.modules["objects_gate"] = og
SPEC.loader.exec_module(og)

H = 0.075
POP = 50_000
JUMP = 0.8  # in ln(1 + reais per inhabitant)
RACES = 160  # per cycle: 320 in all


def make_data(
    post_jump: float = JUMP, pre_jump_c: float = 0.0, seed: int = 11, races: int = RACES
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Panel and objects tables for cycles B and C: `races` races each, two deputies per race.

    The deputy with margin > 0 gets `post_jump` more in ln(1 + Pix reais per inhabitant) in the post
    window, and in cycle C `pre_jump_c` more in the pre window. Each deputy has many towns.
    """
    rng = np.random.default_rng(seed)
    panel, objects = [], []
    for cycle in og.CYCLES:
        for i in range(races):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 8))}"
                y_post = 1.0 + rng.normal(0, 0.05) + (post_jump if win else 0.0)
                y_pre = 1.0 + rng.normal(0, 0.05)
                if cycle == "C" and win:
                    y_pre += pre_jump_c
                post = POP * (np.exp(y_post) - 1.0)
                pre = POP * (np.exp(y_pre) - 1.0)
                panel.append(
                    {
                        "cycle": cycle,
                        "cd_ibge": code,
                        "deputy": deputy,
                        "margin": margin,
                        "win": win,
                        "population_m": POP,
                        "amend_pre_pix": pre,
                        "amend_post_pix": post,
                    }
                )
                objects.append(
                    {
                        "cycle": cycle,
                        "deputy": deputy,
                        "cd_ibge": code,
                        "obj_pre_pix": pre,
                        "obj_post_pix": post,
                    }
                )
    return pl.DataFrame(panel), pl.DataFrame(objects)


def make_measurement(b: float = 0.93, c: float = 0.90) -> pl.DataFrame:
    rows = [
        ("kappa_groups", None, None, None, 0.95),
        ("cv_macro_f1_groups", None, None, None, 0.81),
        ("pix_value_with_plan", "B", None, None, b),
        ("pix_value_with_plan", "C", None, None, c),
        ("other_measure", "B", 2021, "health", 0.5),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "measure": pl.Utf8,
            "cycle": pl.Utf8,
            "year": pl.Int64,
            "class": pl.Utf8,
            "value": pl.Float64,
        },
        orient="row",
    )


def build(panel: pl.DataFrame, objects: pl.DataFrame, measurement: pl.DataFrame | None = None):
    joined, mismatch = og.join_objects(panel, objects)
    table, no_pop = og.add_outcomes(joined, H)
    measure = og.read_measure(measurement if measurement is not None else make_measurement())
    return table, og.build_results(table, measure, H, no_pop, mismatch)


@cache
def cached():
    panel, objects = make_data()
    table, results = build(panel, objects)
    return table, results


@cache
def cached_pre_jump():
    panel, objects = make_data(post_jump=JUMP, pre_jump_c=JUMP, seed=12)
    return build(panel, objects)[1]


# --- Done when 1


def test_planted_pix_jump_is_recovered():
    _, results = cached()
    fs = results["first_stage"]
    assert abs(fs["b"] - JUMP) < 0.1 * JUMP
    assert results["counts"]["races_h"] >= 300
    assert fs["n_races"] >= 300
    assert fs["f_cluster"] > 10
    assert fs["ci_low"] < fs["b"] < fs["ci_high"]
    assert fs["ci_high"] - fs["b"] == pytest.approx(1.96 * fs["se"])
    assert results["check_5pct"]["first_stage"]["b"] == pytest.approx(JUMP, rel=0.15)
    assert results["window"]["h_pct"] == 7.5 and results["window"]["check_pct"] == 5.0


# --- Done when 2


def test_pre_fail_is_one_with_a_planted_pre_jump_and_zero_without():
    flat = cached()[1]["placebo"]
    assert flat["pre_fail"] == 0 and isinstance(flat["pre_fail"], int)
    assert flat["ratio"] < 0.5
    planted = cached_pre_jump()["placebo"]
    assert planted["pre_fail"] == 1 and isinstance(planted["pre_fail"], int)
    assert planted["pre"]["ri_p"] < 0.05
    assert planted["post"]["b"] == pytest.approx(JUMP, rel=0.15)


# --- Done when 3


def test_measure_fields_come_from_the_measurement_table():
    measure = cached()[1]["measure"]
    assert measure["kappa_groups"] == 0.95
    assert measure["cv_macro_f1_groups"] == 0.81
    assert measure["pix_value_with_plan_by_cycle"] == {"B": 0.93, "C": 0.90}
    assert measure["pix_value_with_plan"] == 0.90
    assert og.read_measure(make_measurement(b=0.7, c=0.9))["pix_value_with_plan"] == 0.7


def test_missing_or_repeated_measure_row_raises():
    full = make_measurement()
    for measure, cycle in (
        ("kappa_groups", None),
        ("cv_macro_f1_groups", None),
        ("pix_value_with_plan", "B"),
        ("pix_value_with_plan", "C"),
    ):
        cycle_is = pl.col("cycle").is_null() if cycle is None else pl.col("cycle") == cycle
        match = (pl.col("measure") == measure) & cycle_is
        with pytest.raises(og.GateError, match="need 1"):
            og.read_measure(full.filter(~match))
        with pytest.raises(og.GateError, match="need 1"):
            og.read_measure(pl.concat([full, full.filter(match)]))


# --- Done when 4


def test_pix_mismatch_over_one_real_raises():
    panel, objects = make_data(races=5)
    og.join_objects(panel, objects.with_columns(pl.col("obj_post_pix") + 0.5))
    with pytest.raises(og.GateError, match="differ"):
        og.join_objects(panel, objects.with_columns(pl.col("obj_post_pix") + 1.5))
    with pytest.raises(og.GateError, match="differ"):
        og.join_objects(panel, objects.with_columns(pl.col("obj_pre_pix") - 2.0))


def test_row_without_a_match_raises_in_both_directions():
    panel, objects = make_data(races=5)
    with pytest.raises(og.GateError, match="panel rows have no objects row"):
        og.join_objects(panel, objects.slice(1))
    with pytest.raises(og.GateError, match="objects rows have no panel row"):
        og.join_objects(panel.slice(1), objects)
    with pytest.raises(og.GateError, match="repeated"):
        og.join_objects(panel, pl.concat([objects, objects.head(1)]))


def test_no_population_rows_are_counted_and_leave_the_fits():
    panel, objects = make_data(races=20)
    panel = panel.with_columns(
        pl.when(pl.col("cd_ibge") == "1500001")
        .then(None)
        .otherwise(pl.col("population_m"))
        .alias("population_m")
    )
    joined, _ = og.join_objects(panel, objects)
    table, no_pop = og.add_outcomes(joined, H)
    assert no_pop == 4
    assert table.height == panel.height - 4
    assert table["pix_post_log_pc"].is_finite().all()


# --- Done when 5


def test_window_check_raises_unless_h_pct_is_7_5(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert og.read_window(good) == pytest.approx(0.075)
    for value in (5.0, 10, None):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"window": {"h_pct": value}}), encoding="utf-8")
        with pytest.raises(og.GateError):
            og.read_window(bad)


def test_real_window_record_says_7_5():
    assert og.read_window() == pytest.approx(0.075)


# --- Done when 6


def test_rows_outside_the_exploration_half_are_dropped_on_reading():
    panel, objects = make_data(races=10)
    half = frozenset(f"15{i:05d}" for i in range(5))
    seen = []

    def reader(source: pl.DataFrame):
        def read(name: str, columns: list[str]) -> pl.DataFrame:
            cycle = name.split("_")[1]
            seen.append(name)
            return source.filter(pl.col("cycle") == cycle).select(columns)

        return read

    got_panel = og.load_panels(reader(panel), half)
    got_objects = og.load_objects(reader(objects), half)
    assert set(seen) == {"panel_B", "panel_C", "objects_B", "objects_C"}
    assert set(got_panel["cd_ibge"]) == set(half) == set(got_objects["cd_ibge"])
    assert got_panel.height == got_objects.height == 2 * 5 * 2
    joined, mismatch = og.join_objects(got_panel, got_objects)
    table, no_pop = og.add_outcomes(joined, H)
    assert set(table["cd_ibge"]) <= half
    assert mismatch == 0 and no_pop == 0


# --- Done when 7


def test_results_summary_and_figure(tmp_path):
    table, results = cached()
    assert results["estimates"]["finite"] is True
    for dotted in (
        "measure.kappa_groups",
        "measure.cv_macro_f1_groups",
        "measure.pix_value_with_plan",
        "first_stage.f_cluster",
        "placebo.pre_fail",
        "estimates.finite",
    ):
        node = results
        for part in dotted.split("."):
            node = node[part]
        assert node is not None
    assert results["checks"]["pix_mismatch"] == 0
    assert set(results["counts"]["by_cycle"]) == {"B", "C"}
    og.write_figure(table, H, tmp_path)
    og.write_results(tmp_path, og.summarize(results), results)
    parsed = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert parsed["first_stage"]["f_cluster"] == pytest.approx(results["first_stage"]["f_cluster"])
    assert parsed["placebo"]["pre_fail"] == 0
    png = tmp_path / "figures" / "binned_pix.png"
    assert png.exists() and png.stat().st_size < 400_000
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "nothing on the exploration half is a finding" in summary.lower()


def test_bins_are_half_a_point_wide_and_within_h():
    table, _ = cached()
    binned = og.binned_means(table, H)
    assert binned.height <= 30
    assert binned["centre"].min() > -7.5 and binned["centre"].max() < 7.5
    assert binned["n"].sum() == og.in_window(table, H).height


def test_non_finite_numbers_make_finite_false_and_become_null():
    panel, objects = make_data(races=20)
    only_b = panel.filter(pl.col("cycle") == "B")
    table, results = build(only_b, objects.filter(pl.col("cycle") == "B"))
    assert table["cycle"].unique().to_list() == ["B"]
    assert results["estimates"]["finite"] is False
    json.dumps(results, allow_nan=False)
