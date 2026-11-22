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
    "objects_main", REPO / "explore" / "0013_objects_main.py"
)
em = importlib.util.module_from_spec(SPEC)
sys.modules["objects_main"] = em
SPEC.loader.exec_module(em)

H = 0.075
POP = 50_000
HEALTH_JUMP = 0.6  # in ln(1 + reais per inhabitant)
TIED_PREMIUM = 0.30  # Poisson: tied reais are 1.3 times higher where the party won
RACES = 110  # per cycle: 330 in all
STRONG = (0.8, 0.8, 0.8)
FLAT = (0.0, 0.0, 0.0)


def level(rng: np.random.Generator, jump: float, win: bool) -> float:
    """Reais with ln(1 + reais per inhabitant) = 1 + noise, plus `jump` where the party won."""
    y = 1.0 + rng.normal(0, 0.05) + (jump if win else 0.0)
    return float(POP * (np.exp(y) - 1.0))


def make_data(
    seed: int = 21, jumps: tuple[float, float, float] = STRONG, races: int = RACES
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Panel and objects tables for cycles A, B and C: `races` races each, two deputies per race.

    The deputy with margin > 0 gets `HEALTH_JUMP` more in ln(1 + health reais per inhabitant), tied
    reais that are 1.3 times higher (Poisson counts) and, in B and C only (Pix exists from 2020),
    the `jumps` in ln(1 + reais per inhabitant) of the visible, services and fungible groups.
    """
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
        ("class_value_share", None, None, "vago", None),  # 0 / 0
        ("group_value_share", None, None, "visible", 0.5),
        ("specificity_value_share", None, None, "0", 0.2),
        ("legacy_share_rows", None, 2021, None, 0.1),
        ("legacy_share_rows", None, None, None, 0.15),
        ("kappa_groups", None, None, None, 0.95),
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


def build(seed: int = 21, jumps: tuple[float, float, float] = STRONG):
    panel, objects = make_data(seed, jumps)
    joined = em.join_tables(panel, objects)
    table, no_pop = em.add_outcomes(joined, H)
    results = em.build_results(table, make_measurement(), H, no_pop, em.sum_gap(joined))
    return table, results


@cache
def cached():
    return build()


@cache
def cached_flat():
    return build(seed=22, jumps=FLAT)


# --- Done when 1


def test_planted_health_jump_and_tied_premium_are_recovered():
    _, results = cached()
    health = results["instruments"]["health"]["log_pc"]["pooled"]
    assert abs(health["b"] - HEALTH_JUMP) < 0.1 * HEALTH_JUMP
    assert health["n_races"] >= 300
    assert results["counts"]["races_h"] >= 300
    assert health["ci_low"] < health["b"] < health["ci_high"]
    assert health["ci_high"] - health["b"] == pytest.approx(1.96 * health["se"])
    tied = results["instruments"]["tied"]["poisson"]["pooled"]
    assert abs(tied["premium_pct"] - 100 * TIED_PREMIUM) < 5
    assert tied["premium_ci_low"] < tied["premium_pct"] < tied["premium_ci_high"]
    assert tied["n_obs"] > 600
    by_cycle = results["instruments"]["health"]["log_pc"]
    for scope in ("A", "B", "C", "c_minus_a"):
        assert set(by_cycle[scope]) == {"b", "se", "ci_low", "ci_high"}
    assert results["window"] == {
        "h_pct": 7.5,
        "check_pct": 5.0,
        "source": em.WINDOW_SOURCE,
    }
    assert set(results["instruments"]["pix"]["poisson"]) == {"pooled", "B", "C"}
    assert set(results["check_5pct"]["pix"]["log_pc"]) == {"b", "se", "ri_p"}
    assert set(results["check_5pct"]["tied"]["poisson"]) == {"b", "se", "p"}


# --- Done when 2


def test_differences_equal_the_differences_of_the_separate_fits():
    table, results = cached()
    health = results["instruments"]["health"]["poisson"]
    diff = results["differences"]["health_c_minus_a"]
    assert diff["b"] == pytest.approx(health["C"]["b"] - health["A"]["b"], abs=1e-4)
    assert diff["ratio_pct"] == pytest.approx(100 * (np.exp(diff["b"]) - 1))
    assert health["c_minus_a"]["b"] == diff["b"]

    bc = em._of(table, em.PIX_CYCLES)
    pix = em.poisson_fit(bc, H, em.INSTRUMENTS["pix"])
    tied = em.poisson_fit(bc, H, em.INSTRUMENTS["tied"])
    assert results["differences"]["pix_minus_tied"]["b"] == pytest.approx(
        pix["b"] - tied["b"], abs=1e-4
    )
    visible = em.poisson_fit(bc, H, em.GROUPS["visible"])
    fungible = em.poisson_fit(bc, H, em.GROUPS["fungible"])
    got = results["differences"]["visible_minus_fungible"]
    assert got["b"] == pytest.approx(visible["b"] - fungible["b"], abs=1e-4)
    assert got["n_obs"] > 0 and np.isfinite(got["se"]) and 0 <= got["p"] <= 1
    assert results["declared"]["health_c_minus_a"]["p"] == diff["p"]


# --- Done when 3


def test_n_strong_is_three_with_strong_jumps_and_zero_with_none():
    _, strong = cached()
    assert strong["first_stage"]["n_strong"] == 3
    assert isinstance(strong["first_stage"]["n_strong"], int)
    assert all(v >= 10 for v in strong["first_stage"]["f_cluster"].values())
    assert strong["estimates"]["finite"] is True
    _, flat = cached_flat()
    assert flat["first_stage"]["n_strong"] == 0
    assert all(v < 10 for v in flat["first_stage"]["f_cluster"].values())


# --- Done when 4


def test_holm():
    assert em.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert em.holm([0.5, 0.6]) == pytest.approx([1.0, 1.0])
    assert all(np.isnan(em.holm([0.01, float("nan")])))


# --- Done when 5


def test_window_must_be_7_5(tmp_path):
    record = tmp_path / "gate.json"
    record.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert em.read_window(record) == pytest.approx(0.075)
    for bad in (5.0, 7.6, None):
        record.write_text(json.dumps({"window": {"h_pct": bad}}), encoding="utf-8")
        with pytest.raises(em.GateError, match="not 7.5"):
            em.read_window(record)


def test_row_without_a_match_raises_in_both_directions():
    panel, objects = make_data(races=5)
    with pytest.raises(em.GateError, match="panel rows have no objects row"):
        em.join_tables(panel, objects.slice(1))
    with pytest.raises(em.GateError, match="objects rows have no panel row"):
        em.join_tables(panel.slice(1), objects)
    with pytest.raises(em.GateError, match="repeated"):
        em.join_tables(panel, pl.concat([objects, objects.head(1)]))
    assert em.join_tables(panel, objects).height == panel.height


def test_no_population_and_sum_gap_are_counted():
    panel, objects = make_data(races=10)
    panel = panel.with_columns(
        pl.when(pl.col("cd_ibge") == "1500001")
        .then(None)
        .otherwise(pl.col("population_m"))
        .alias("population_m")
    )
    joined = em.join_tables(panel, objects)
    assert em.sum_gap(joined) == 0
    table, no_pop = em.add_outcomes(joined, H)
    assert no_pop == 6  # three cycles, two deputies, all inside the window
    assert table.height == joined.height - 6
    gap = joined.with_columns(
        pl.when(pl.col("cd_ibge") == "1500002")
        .then(pl.col("amend_post_total") + 5.0)
        .otherwise(pl.col("amend_post_total"))
        .alias("amend_post_total")
    )
    assert em.sum_gap(gap) == 6


# --- Done when 6


def test_rows_outside_the_exploration_half_are_dropped_first():
    panel, objects = make_data(races=6)
    half = frozenset({"1500000", "1500003"})
    seen = []

    def reader(table):
        def read(name, columns):
            seen.append(name)
            cycle = name[-1]
            return table.filter(pl.col("cycle") == cycle).select(columns)

        return read

    loaded_panel = em.load_panels(reader(panel), half)
    loaded_objects = em.load_objects(reader(objects), half)
    assert sorted(set(seen)) == [f"{p}_{c}" for p in ("objects", "panel") for c in "ABC"]
    assert set(loaded_panel["cd_ibge"]) == half
    assert set(loaded_objects["cd_ibge"]) == half
    assert loaded_panel.height == 3 * 2 * 2 == loaded_objects.height
    assert set(loaded_panel["cycle"]) == {"A", "B", "C"}
    assert "population_m" in loaded_panel.columns

    def no_column(name, columns):
        return panel.select("cycle", "deputy")

    with pytest.raises(Exception, match="cd_ibge"):
        em.load_panels(no_column, half)


# --- Done when 7


def test_results_json_is_standard_json_with_the_kill_fields_and_figures_are_written(tmp_path):
    from terrain.explore import write_results

    _, results = cached()
    em.write_figures(results, tmp_path)
    write_results(tmp_path, em.summarize(results), results)

    def reject(constant):
        raise AssertionError(f"not standard JSON: {constant}")

    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=reject)
    assert parsed["first_stage"]["n_strong"] == 3
    assert parsed["estimates"]["finite"] is True
    assert len(text.encode("utf-8")) < 200_000
    assert set(parsed["declared"]["pix_minus_tied"]) == {"p", "p_holm"}
    assert set(parsed["differences"]["pix_minus_tied"]) == {
        "b",
        "se",
        "p",
        "ratio_pct",
        "n_obs",
    }
    assert set(parsed["counts"]) == {
        "units_h",
        "races_h",
        "by_cycle",
        "no_population",
        "sum_gap",
    }
    assert set(parsed["pix_groups"]) == {"visible", "services", "fungible", "no_plan"}
    assert set(parsed["pix_groups"]["visible"]["log_pc"]["pooled_bc"]) == set(em.FIT_KEYS) | {
        "ci_low",
        "ci_high",
    }
    assert set(parsed["composition"]["within_h"]["B"]["win"]) == set(em.STRONG_GROUPS)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Nothing on the exploration half is a finding" in summary
    assert "Holm p" in summary
    for name in ("premium_by_instrument", "premium_by_group", "composition_by_year"):
        png = tmp_path / "figures" / f"{name}.png"
        assert png.is_file() and 0 < png.stat().st_size < 400_000


def test_composition_is_copied_and_a_null_share_does_not_count_against_finite():
    comp = em.composition_from_measurement(make_measurement())
    shares = comp["measurement"]["class_value_share"]
    assert shares["2021"] == {"obra_viaria": 0.3, "vago": 0.7}
    assert shares["all"]["vago"] is None
    assert comp["measurement"]["group_value_share"]["all"] == {"visible": 0.5}
    assert comp["legacy_share_rows"] == {"2021": 0.1, "all": 0.15}
    assert "kappa_groups" not in comp["measurement"]
    _, results = cached()
    assert results["composition"]["measurement"]["class_value_share"]["all"]["vago"] is None
    assert results["estimates"]["finite"] is True
    repeated = pl.concat([make_measurement(), make_measurement().head(1)])
    with pytest.raises(em.GateError, match="repeated"):
        em.composition_from_measurement(repeated)


def test_within_h_shares_are_plain_sums_and_null_without_money():
    table, results = cached()
    shares = results["composition"]["within_h"]
    inside = em.in_window(table.filter((pl.col("cycle") == "B") & pl.col("win")), H)
    expected = inside["obj_post_pix_visible"].sum() / inside["obj_post_pix"].sum()
    assert shares["B"]["win"]["visible"] == pytest.approx(expected)
    empty = table.with_columns(pl.lit(0.0).alias("obj_post_pix"))
    assert em.within_h_composition(empty, H)["C"]["lose"]["visible"] is None
