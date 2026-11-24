import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "objects_main_noplan_f1", REPO / "explore" / "0013_objects_main_noplan_lin_f1.py"
)
fk = importlib.util.module_from_spec(SPEC)
sys.modules["objects_main_noplan_f1"] = fk
SPEC.loader.exec_module(fk)
em = fk.parent

H = 0.075
POP = 50_000
RACES = 50  # per cycle
SEEDS = (3, 11, 21, 34, 55)
STRONG = (0.8, 0.8, 0.8)
FLAT = (0.0, 0.0, 0.0)


def level(rng: np.random.Generator, jump: float, win: bool) -> float:
    y = 1.0 + rng.normal(0, 0.05) + (jump if win else 0.0)
    return float(POP * (np.exp(y) - 1.0))


def make_data(
    seed: int, jumps=STRONG, races: int = RACES, no_plan_zero_in_c: bool = False
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Panel and objects tables for cycles A, B and C, two deputies per race."""
    rng = np.random.default_rng(seed)
    panel, objects = [], []
    for cycle in em.ALL_CYCLES:
        for i in range(races):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 6))}"
                health = level(rng, 0.6, win)
                tied = float(rng.poisson(300.0 * (1.3 if win else 1.0)))
                if cycle == "A":
                    visible = services = fungible = no_plan = 0.0
                else:
                    visible, services, fungible = (level(rng, j, win) for j in jumps)
                    no_plan = float(rng.poisson(50))
                    if no_plan_zero_in_c and cycle == "C":
                        no_plan = 0.0
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


def prepare(seed: int, **kwargs):
    panel, objects = make_data(seed, **kwargs)
    joined = em.join_tables(panel, objects)
    table, no_pop = em.add_outcomes(joined, H)
    return table, no_pop, em.sum_gap(joined)


def run(module, seed: int, **kwargs):
    table, no_pop, gap = prepare(seed, **kwargs)
    return module.build_results(table, make_measurement(), H, no_pop, gap)


# --- Done when 2


@pytest.mark.parametrize("seed", SEEDS)
def test_fork_equals_the_parent_minus_the_no_plan_poisson_fits(seed):
    parent_results = run(em, seed)
    assert all(
        parent_results["pix_groups"]["no_plan"]["poisson"][s]["n_obs"] > 0
        for s in ("B", "C", "pooled_bc")
    )
    assert parent_results["estimates"]["finite"] is True
    fork_results = run(fk, seed)
    assert "poisson" not in fork_results["pix_groups"]["no_plan"]
    assert set(fork_results["pix_groups"]["no_plan"]["log_pc"]) == {"pooled_bc", "B", "C"}
    expected = json.loads(json.dumps(parent_results))
    del expected["pix_groups"]["no_plan"]["poisson"]
    assert json.loads(json.dumps(fork_results)) == expected


def test_no_plan_poisson_is_never_fitted_and_the_parent_globals_are_restored(monkeypatch):
    columns, fits = [], []
    real_fit, real_fepois, real_finite = em.poisson_fit, em.fepois, em._all_finite

    def spy_fit(table, h, column):
        columns.append(column)
        return real_fit(table, h, column)

    def spy_fepois(*args, **kwargs):
        fits.append(1)
        return real_fepois(*args, **kwargs)

    monkeypatch.setattr(em, "poisson_fit", spy_fit)
    monkeypatch.setattr(em, "fepois", spy_fepois)
    table, no_pop, gap = prepare(SEEDS[0], races=30)
    em.build_results(table, make_measurement(), H, no_pop, gap)
    parent_columns, parent_fits = list(columns), len(fits)
    assert em.GROUPS["no_plan"] in parent_columns
    columns.clear()
    fits.clear()
    fk.build_results(table, make_measurement(), H, no_pop, gap)
    assert em.GROUPS["no_plan"] not in columns
    assert len(columns) == len(parent_columns) - 3
    assert len(fits) == parent_fits - 3
    assert em.poisson_fit is spy_fit
    assert em._all_finite is real_finite


def test_parent_globals_are_restored_after_an_exception(monkeypatch):
    fit, finite = em.poisson_fit, em._all_finite

    def boom(*args, **kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(em, "build_results", boom)
    with pytest.raises(RuntimeError, match="stop"):
        fk.build_results(pl.DataFrame(), pl.DataFrame(), H, 0)
    assert em.poisson_fit is fit
    assert em._all_finite is finite


# --- Done when 3


def test_no_plan_zero_in_every_c_row_writes_the_linear_fit_and_is_not_finite():
    results = run(fk, SEEDS[0], no_plan_zero_in_c=True)
    node = results["pix_groups"]["no_plan"]["log_pc"]
    assert "C" in node
    assert node["C"]["f_cluster"] is None
    assert results["estimates"]["finite"] is False


# --- Done when 4


@pytest.mark.parametrize("seed", SEEDS)
def test_n_strong_is_three_with_strong_jumps_and_zero_with_none(seed):
    strong = run(fk, seed)
    assert strong["first_stage"]["n_strong"] == 3
    assert strong["estimates"]["finite"] is True
    flat = run(fk, seed, jumps=FLAT)
    assert flat["first_stage"]["n_strong"] == 0


# --- Done when 5


def test_rows_outside_the_exploration_half_are_dropped_first():
    panel, objects = make_data(SEEDS[0], races=6)
    half = frozenset({"1500000", "1500003"})

    def reader(table):
        def read(name, columns):
            return table.filter(pl.col("cycle") == name[-1]).select(columns)

        return read

    loaded_panel = fk.load_panels(reader(panel), half)
    loaded_objects = fk.load_objects(reader(objects), half)
    assert set(loaded_panel["cd_ibge"]) == half == set(loaded_objects["cd_ibge"])
    assert loaded_panel.height == 12 == loaded_objects.height
    source = (REPO / "explore" / "0013_objects_main_noplan_lin_f1.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source


# --- Done when 6


def test_results_json_is_standard_json_figures_are_written_and_summary_says_linear_only(
    tmp_path,
):
    results = run(fk, SEEDS[0])
    fk.write_figures(results, tmp_path)
    fk.write_results(tmp_path, fk.summarize(results), results)

    def reject(constant):
        raise AssertionError(f"not standard JSON: {constant}")

    parsed = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8"), parse_constant=reject
    )
    assert parsed["first_stage"]["n_strong"] == 3
    assert parsed["estimates"]["finite"] is True
    assert set(parsed["pix_groups"]) == {"visible", "services", "fungible", "no_plan"}
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "no_plan (linear only)" in summary
    assert "had no rows" in summary
    assert "Nothing on the exploration half is a finding" in summary
    for name in ("premium_by_instrument", "premium_by_group", "composition_by_year"):
        png = tmp_path / "figures" / f"{name}.png"
        assert png.is_file() and 0 < png.stat().st_size < 400_000
