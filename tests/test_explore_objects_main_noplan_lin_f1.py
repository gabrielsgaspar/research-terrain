import importlib.util
import json
import sys
from functools import cache
from pathlib import Path

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "objects_main_noplan_lin_f1", REPO / "explore" / "0013_objects_main_noplan_lin_f1.py"
)
fk = importlib.util.module_from_spec(SPEC)
sys.modules["objects_main_noplan_lin_f1"] = fk
SPEC.loader.exec_module(fk)
parent = fk.parent

H = 0.075
POP = 50_000
HEALTH_JUMP = 0.6
TIED_PREMIUM = 0.30
RACES = 110
STRONG = (0.8, 0.8, 0.8)
FLAT = (0.0, 0.0, 0.0)


def level(rng: np.random.Generator, jump: float, win: bool) -> float:
    y = 1.0 + rng.normal(0, 0.05) + (jump if win else 0.0)
    return float(POP * (np.exp(y) - 1.0))


def make_data(
    seed: int = 21, jumps: tuple[float, float, float] = STRONG, races: int = RACES
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Panel and objects tables for cycles A, B and C: `races` races each, two deputies per race."""
    rng = np.random.default_rng(seed)
    panel, objects = [], []
    for cycle in parent.ALL_CYCLES:
        for i in range(races):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 8))}"
                health = level(rng, HEALTH_JUMP, win)
                tied = float(rng.poisson(300.0 * ((1.0 + TIED_PREMIUM) if win else 1.0)))
                if cycle == "A":
                    visible = services = fungible = no_plan = 0.0
                else:
                    visible, services, fungible = (level(rng, j, win) for j in jumps)
                    no_plan = float(rng.poisson(50))
                pix = visible + services + fungible + no_plan
                panel.append(
                    {
                        "cycle": cycle,
                        "cd_ibge": code,
                        "deputy": deputy,
                        "margin": margin,
                        "win": win,
                        "population_m": POP,
                        "amend_post_total": pix + health + tied,
                        "amend_post_pix": pix,
                    }
                )
                objects.append(
                    {
                        "cycle": cycle,
                        "deputy": deputy,
                        "cd_ibge": code,
                        "obj_post_pix": pix,
                        "obj_post_health": health,
                        "obj_post_tied": tied,
                        "obj_post_pix_visible": visible,
                        "obj_post_pix_services": services,
                        "obj_post_pix_fungible": fungible + no_plan,
                        "obj_post_pix_no_plan": no_plan,
                    }
                )
    return pl.DataFrame(panel), pl.DataFrame(objects)


def make_measurement() -> pl.DataFrame:
    rows = [
        ("class_value_share", None, 2021, "obra_viaria", 0.3),
        ("class_value_share", None, 2021, "vago", 0.7),
        ("class_value_share", None, None, "obra_viaria", 0.4),
        ("class_value_share", None, None, "vago", None),
        ("group_value_share", None, None, "visible", 0.5),
        ("specificity_value_share", None, None, "0", 0.2),
        ("legacy_share_rows", None, 2021, None, 0.1),
        ("legacy_share_rows", None, None, None, 0.15),
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


def build(
    module,
    seed: int = 21,
    jumps: tuple[float, float, float] = STRONG,
    zero_c_no_plan: bool = False,
):
    panel, objects = make_data(seed, jumps)
    if zero_c_no_plan:
        objects = objects.with_columns(
            pl.when(pl.col("cycle") == "C")
            .then(0.0)
            .otherwise(pl.col("obj_post_pix_no_plan"))
            .alias("obj_post_pix_no_plan")
        )
    joined = parent.join_tables(panel, objects)
    table, no_pop = parent.add_outcomes(joined, H)
    return module.build_results(table, make_measurement(), H, no_pop, parent.sum_gap(joined))


@cache
def cached():
    return build(fk), build(parent)


@cache
def cached_flat():
    return build(fk, seed=22, jumps=FLAT)


def test_results_equal_the_parents_without_the_no_plan_poisson_fits():
    got, base = cached()
    assert set(base["pix_groups"]["no_plan"]) == {"log_pc", "poisson"}
    assert set(got["pix_groups"]["no_plan"]) == {"log_pc"}
    assert set(got["pix_groups"]["no_plan"]["log_pc"]) == {"pooled_bc", "B", "C"}
    expected = json.loads(json.dumps(base))
    del expected["pix_groups"]["no_plan"]["poisson"]
    assert json.loads(json.dumps(got)) == expected


def test_parent_groups_are_restored():
    cached()
    assert "no_plan" in parent.GROUPS
    assert list(parent.GROUPS) == ["visible", "services", "fungible", "no_plan"]


def test_no_plan_zero_in_every_c_row_is_still_finite_and_has_the_c_fit():
    results = build(fk, zero_c_no_plan=True)
    assert results["estimates"]["finite"] is True
    assert "C" in results["pix_groups"]["no_plan"]["log_pc"]
    assert "poisson" not in results["pix_groups"]["no_plan"]


def test_n_strong_is_three_with_strong_jumps_and_zero_with_none():
    strong, _ = cached()
    assert strong["first_stage"]["n_strong"] == 3
    assert isinstance(strong["first_stage"]["n_strong"], int)
    assert strong["estimates"]["finite"] is True
    assert cached_flat()["first_stage"]["n_strong"] == 0


def test_rows_outside_the_exploration_half_are_dropped_first():
    panel, objects = make_data(races=6)
    half = frozenset({"1500000", "1500003"})
    seen = []

    def reader(table):
        def read(name, columns):
            seen.append(name)
            return table.filter(pl.col("cycle") == name[-1]).select(columns)

        return read

    loaded_panel = fk.load_panels(reader(panel), half)
    loaded_objects = fk.load_objects(reader(objects), half)
    assert sorted(set(seen)) == [f"{p}_{c}" for p in ("objects", "panel") for c in "ABC"]
    assert set(loaded_panel["cd_ibge"]) == half
    assert set(loaded_objects["cd_ibge"]) == half
    assert loaded_panel.height == 3 * 2 * 2 == loaded_objects.height


def test_results_json_and_figures_are_written(tmp_path):
    from terrain.explore import write_results

    results, _ = cached()
    fk.write_figures(results, tmp_path)
    write_results(tmp_path, fk.summarize(results), results)

    def reject(constant):
        raise AssertionError(f"not standard JSON: {constant}")

    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject)
    assert parsed["first_stage"]["n_strong"] == 3
    assert parsed["estimates"]["finite"] is True
    assert "poisson" not in parsed["pix_groups"]["no_plan"]
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "linear only" in summary
    for name in ("premium_by_instrument", "premium_by_group", "composition_by_year"):
        png = tmp_path / "figures" / f"{name}.png"
        assert png.is_file() and 0 < png.stat().st_size < 400_000
