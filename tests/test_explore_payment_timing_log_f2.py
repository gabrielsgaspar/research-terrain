import importlib.util
import json
import math
import sys
from functools import cache
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "payment_timing_log_f2", REPO / "explore" / "0010_payment_timing_log_f2.py"
)
pt = importlib.util.module_from_spec(SPEC)
sys.modules["payment_timing_log_f2"] = pt
SPEC.loader.exec_module(pt)

H = 0.075
POP = 50_000
JUMP = 0.5  # on the ln(1 + reais per inhabitant) scale
M = {"A": 2016, "B": 2020, "C": 2024}


def make_data(
    jumps: dict[int, float], seed: int = 5, races: int = 100
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Panel and monthly table: 3 cycles x `races` races, two deputies per race (one allied).

    The log outcome ln(1 + amend / pop) is a base near ln 2 plus `jumps[j]` for the allied deputy
    (margin > 0). The monthly table has the file's 46 months (j = 0..45).
    """
    rng = np.random.default_rng(seed)
    panel, monthly = [], []
    for cycle in pt.CYCLES:
        for i in range(races):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.07))
            sign = 1 if rng.uniform() > 0.5 else -1
            for k in range(2):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                deputy = f"{cycle}-{k}-{int(rng.integers(0, 8))}"
                panel.append(
                    {
                        "cycle": cycle,
                        "m": M[cycle],
                        "cd_ibge": code,
                        "deputy": deputy,
                        "margin": margin,
                        "win": win,
                        "population_m": POP,
                    }
                )
                base = 1.0 + rng.normal(0, 0.05, size=46)
                for j in range(46):
                    log_y = math.log1p(base[j]) + (jumps.get(j, 0.0) if win else 0.0)
                    total = math.expm1(log_y) * POP
                    monthly.append(
                        {
                            "cycle": cycle,
                            "deputy": deputy,
                            "cd_ibge": code,
                            "ym": pt.month_ym(cycle, j),
                            "amend_total": total,
                            "amend_pix": total / 2,
                        }
                    )
    return pl.DataFrame(panel), pl.DataFrame(monthly)


@cache
def cached():
    panel, monthly = make_data({30: JUMP})
    return panel, monthly, pt.build_results(panel, monthly, H)


@cache
def cached_pre_and_post():
    jumps = {j: JUMP for j in (*pt.PRE, *pt.POST)}
    panel, monthly = make_data(jumps, seed=6)
    return pt.build_results(panel, monthly, H)


# --- Done when 1


def test_planted_log_jump_in_one_month_is_recovered():
    results = cached()[2]
    pooled = results["monthly"]["total"]["pooled"]
    assert abs(pooled["j30"]["b"] - JUMP) < 0.1 * JUMP
    assert abs(pooled["j10"]["b"]) < 0.05
    assert pooled["j30"]["n_units"] >= 500
    assert results["monthly"]["pix"]["B"]["j30"]["b"] > 0.1
    assert abs(results["monthly"]["pix"]["B"]["j10"]["b"]) < 0.05
    assert results["counts"]["by_cycle"]["A"]["races"] >= 90


# --- Done when 2


def test_outcome_is_log1p_of_reais_per_inhabitant():
    panel, monthly = make_data({}, races=20)
    row = panel.filter(
        (pl.col("cycle") == "B") & (pl.col("cd_ibge") == "1500000") & (pl.col("margin") > 0)
    ).row(0, named=True)
    target = (pl.col("cycle") == "B") & (pl.col("cd_ibge") == "1500000")
    target &= pl.col("deputy") == row["deputy"]
    j_pay, j_zero = 7, 8
    edited = monthly.with_columns(
        pl.when(target & (pl.col("ym") == pt.month_ym("B", j_pay)))
        .then(25_000.0)
        .when(target & (pl.col("ym") == pt.month_ym("B", j_zero)))
        .then(0.0)
        .otherwise(pl.col("amend_total"))
        .alias("amend_total")
    ).with_columns(
        pl.when(target & (pl.col("ym") == pt.month_ym("B", j_zero)))
        .then(0.0)
        .otherwise(pl.col("amend_pix"))
        .alias("amend_pix")
    )
    units = pt.join_monthly_log(panel, edited, H)
    index = int(
        np.flatnonzero(
            (units.table["cycle"].to_numpy() == "B")
            & (units.table["cd_ibge"].to_numpy() == "1500000")
            & (units.table["deputy"].to_numpy() == row["deputy"])
        )[0]
    )
    assert units.tot[index, j_pay] == pytest.approx(math.log(1.5), abs=1e-12)
    assert units.tot[index, j_zero] == 0.0
    assert units.pix[index, j_zero] == 0.0
    assert np.isfinite(units.tot).all() and np.isfinite(units.pix).all()


# --- Done when 3


def test_half_year_is_the_mean_of_months_and_cumulative_the_running_sum():
    results = cached()[2]
    for instrument in ("total", "pix"):
        for scope in pt.SCOPES[instrument]:
            monthly = results["monthly"][instrument][scope]
            b = [monthly[f"j{j:02d}"]["b"] for j in range(45)]
            for name, a, z in pt.HALVES:
                got = results["halves"][instrument][scope][name]["b"]
                assert got == pytest.approx(float(np.mean(b[a:z])), abs=1e-9)
            running = np.cumsum(b)
            for j in range(45):
                got = results["cumulative"][instrument][scope][f"j{j:02d}"]["b"]
                assert got == pytest.approx(running[j], abs=1e-9)


# --- Done when 4


def test_lead_ratio_is_high_with_a_pre_jump_and_low_without():
    assert cached_pre_and_post()["placebo"]["lead_ratio"] > 0.5
    flat = cached()[2]["placebo"]
    assert flat["lead_ratio"] < 0.1
    assert flat["post_mean"] == pytest.approx(JUMP / 21, rel=0.2)


# --- Done when 5


def test_month_index_and_phase():
    assert pt.month_index("B", 201901) == 0 and pt.phase(0) == "pre"
    assert pt.month_index("B", 202009) == 20 and pt.phase(20) == "pre"
    assert pt.month_index("B", 202012) == 23 and pt.phase(23) == "transition"
    assert pt.month_index("B", 202101) == 24 and pt.phase(24) == "post"
    assert pt.month_index("B", 202209) == 44 and pt.phase(44) == "post"
    assert pt.month_index("B", 202210) == 45
    months = cached()[2]["months"]
    assert len(months) == 45 and "j45" not in months
    assert months["j00"]["ym_A"] == 201501 and months["j44"]["ym_C"] == 202609
    assert months["j23"]["phase"] == "transition"


def test_october_of_t1_is_dropped():
    panel, monthly, _ = cached()
    units = pt.join_monthly_log(panel, monthly, H)
    assert units.tot.shape[1] == 45
    assert units.tot.shape[0] == units.table.height


# --- Done when 6


def test_orphan_monthly_row_raises():
    panel, monthly = make_data({}, races=20)
    extra = monthly.head(1).with_columns(pl.lit("9999999").alias("cd_ibge"))
    with pytest.raises(pt.GateError, match="no panel row"):
        pt.join_monthly_log(panel, pl.concat([monthly, extra]), H)


def test_panel_row_inside_h_with_wrong_month_count_raises():
    panel, monthly = make_data({}, races=20)
    row = monthly.row(0, named=True)
    dropped = monthly.filter(
        ~(
            (pl.col("cycle") == row["cycle"])
            & (pl.col("deputy") == row["deputy"])
            & (pl.col("cd_ibge") == row["cd_ibge"])
            & (pl.col("ym") == row["ym"])
        )
    )
    with pytest.raises(pt.GateError, match="46 months"):
        pt.join_monthly_log(panel, dropped, H)


def test_no_population_rows_are_counted_and_leave_the_fits():
    panel, monthly = make_data({}, races=20)
    panel = panel.with_columns(
        pl.when(pl.col("cd_ibge") == "1500001")
        .then(None)
        .otherwise(pl.col("population_m"))
        .alias("population_m")
    )
    units = pt.join_monthly_log(panel, monthly, H)
    assert units.no_population == 6
    assert units.table.height == panel.height - 6
    assert np.isfinite(units.tot).all()


def test_window_check_raises_unless_h_pct_is_7_5(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert pt.read_window(good) == pytest.approx(0.075)
    for value in (5.0, 10, None):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"window": {"h_pct": value}}), encoding="utf-8")
        with pytest.raises(pt.GateError):
            pt.read_window(bad)


def test_real_window_record_says_7_5():
    assert pt.read_window() == pytest.approx(0.075)


# --- Done when 7


def test_rows_outside_the_exploration_half_are_dropped_on_reading():
    panel, monthly = make_data({}, races=10)
    half = frozenset(f"15{i:05d}" for i in range(5))

    def reader(source: pl.DataFrame):
        def read(name: str, columns: list[str]) -> pl.DataFrame:
            cycle = name.split("_")[1]
            return source.filter(pl.col("cycle") == cycle).select(columns)

        return read

    got_panel = pt.load_panels(reader(panel), half)
    got_monthly = pt.load_monthly(reader(monthly), half)
    assert set(got_panel["cd_ibge"]) == set(half)
    assert set(got_monthly["cd_ibge"]) == set(half)
    assert got_panel.height == 3 * 5 * 2 and got_monthly.height == 3 * 5 * 2 * 46
    units = pt.join_monthly_log(got_panel, got_monthly, H)
    assert set(units.table["cd_ibge"]) <= half


# --- Done when 8


def test_results_and_figures(tmp_path):
    panel, monthly, results = cached()
    assert results["estimates"]["finite"] is True
    assert results["placebo"]["lead_ratio"] is not None
    assert results["window"]["h_pct"] == 7.5
    assert results["counts"]["months"] == 45
    pt.write_figures(results, tmp_path)
    pt.write_results(tmp_path, pt.summarize(results), results)
    parsed = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert "lead_ratio" in parsed["placebo"] and parsed["estimates"]["finite"] is True
    for name in ("monthly_by_cycle.png", "cumulative_gap.png"):
        path = tmp_path / "figures" / name
        assert path.exists() and path.stat().st_size < 400_000
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "survived (fork)" in summary and "killed (fork)" in summary
    assert "ln(1 + reais per inhabitant)" in summary
    assert "nothing on the exploration half is a finding" in summary.lower()


def test_non_finite_numbers_make_finite_false_and_become_null():
    panel, monthly = make_data({}, races=20)
    tiny = panel.filter(pl.col("cycle") == "A")
    results = pt.build_results(tiny, monthly.filter(pl.col("cycle") == "A"), H)
    assert results["estimates"]["finite"] is False
    assert results["monthly"]["pix"]["B"]["j00"]["b"] is None
    json.dumps(results, allow_nan=False)
