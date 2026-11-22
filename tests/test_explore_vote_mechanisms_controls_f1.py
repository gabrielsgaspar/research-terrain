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
    "vote_mechanisms_controls_f1", REPO / "explore" / "0010_vote_mechanisms_controls_f1.py"
)
f1 = importlib.util.module_from_spec(SPEC)
sys.modules["vote_mechanisms_controls_f1"] = f1
SPEC.loader.exec_module(f1)
parent = f1.votes0010

H = 0.075
J_PARTY = 0.04
HELD_EFFECT = 0.03
DRAWS = 300


def make_panel(seed: int = 3, sorting: bool = True, t0_jump: float = 0.0) -> pl.DataFrame:
    """3 cycles x 100 races; two finalist parties per race, two deputies per party.

    With `sorting`, a party that held the town hall wins more often and `party_held_mayor` lifts
    `party_share_t1` by 0.03. Without it, every control is pure noise. Winners' `party_share_t1`
    jumps by 0.04. `t0_jump` plants a jump in winners' t0 shares (a placebo failure).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for cycle in f1.CYCLES:
        for i in range(100):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.1))
            sign = 1 if rng.uniform() > 0.5 else -1
            parties = rng.choice(6, size=2, replace=False)
            pop = int(rng.integers(5_000, 500_000))
            rnd = int(rng.integers(1, 3))
            cands = int(rng.integers(2, 7))
            for k, party in enumerate(parties):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                held = (
                    int(rng.uniform() < (0.7 if win else 0.3))
                    if sorting
                    else int(rng.uniform() < 0.5)
                )
                p0 = 0.10 + (t0_jump if win else 0.0) + rng.normal(0, 0.0015)
                s0 = 0.08 + (t0_jump if win else 0.0) + rng.normal(0, 0.0015)
                p1 = p0 + (J_PARTY if win else 0.0) + rng.normal(0, 0.0015)
                p1 += HELD_EFFECT * held if sorting else 0.0
                s1 = s0 + 0.02 * win + rng.normal(0, 0.0015)
                for j in range(2):
                    t0 = 0.04 + rng.normal(0, 0.0015)
                    t1 = t0 + (0.006 if win else 0.0) + rng.normal(0, 0.0015)
                    rows.append(
                        {
                            "cycle": cycle,
                            "cd_ibge": code,
                            "uf": "PA",
                            "deputy": f"{cycle}-{party}-{j}",
                            "deputy_party": int(party),
                            "margin": margin,
                            "win": win,
                            "population_m": pop,
                            "share_t0": t0,
                            "share_t1": t1,
                            "ran_t1": True,
                            "d_share": t1 - t0,
                            "amend_post_log_pc": float(rng.uniform(0, 5)),
                            "party_share_t0": p0,
                            "party_share_t1": p1,
                            "state_party_share_t0": s0,
                            "state_party_share_t1": s1,
                            "party_held_mayor": bool(held),
                            "round": rnd,
                            "n_mayor_cands": cands,
                        }
                    )
    return pl.DataFrame(rows)


def small_panel(rows: list[dict]) -> pl.DataFrame:
    base = {
        "cycle": "A",
        "cd_ibge": "1500001",
        "uf": "PA",
        "deputy_party": 11,
        "margin": 0.02,
        "win": True,
        "population_m": 1000,
        "share_t0": 0.03,
        "share_t1": 0.05,
        "ran_t1": True,
        "d_share": 0.02,
        "amend_post_log_pc": 1.0,
        "party_share_t0": 0.10,
        "party_share_t1": 0.15,
        "state_party_share_t0": 0.08,
        "state_party_share_t1": 0.09,
        "party_held_mayor": True,
        "round": 1,
        "n_mayor_cands": 3,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


@cache
def cached(sorting: bool = True):
    panel = make_panel(sorting=sorting)
    draws = f1.sign_draws(f1.n_races(f1.party_table(panel)), draws=DRAWS)
    return panel, draws


@cache
def cached_results():
    panel, draws = cached()
    return f1.build_results(panel, H, draws)


def pooled_b(panel: pl.DataFrame, draws: np.ndarray, controls: bool) -> float:
    table = f1.party_table(panel)
    if controls:
        return f1.estimate_c(table, draws, H, "d_party")["b"]
    return parent.estimate(table, draws, H, "d_party")["b"]


# --- Done when 1 and 2


def test_controls_recover_the_jump_and_no_controls_miss_it():
    panel, draws = cached()
    assert abs(pooled_b(panel, draws, True) - J_PARTY) < 0.1 * J_PARTY
    assert abs(pooled_b(panel, draws, False) - J_PARTY) > 0.1 * J_PARTY
    assert f1.n_races(f1.party_table(panel)) >= 300


def test_pure_noise_controls_leave_b_where_the_parent_has_it():
    panel, draws = cached(False)
    with_c, without = pooled_b(panel, draws, True), pooled_b(panel, draws, False)
    assert abs(with_c - without) < 0.1 * abs(without)
    assert abs(with_c - J_PARTY) < 0.1 * J_PARTY


def test_by_cycle_fit_with_controls_has_every_scope():
    panel, _ = cached()
    r = cached_results()["party"]["d_party"]
    for scope in ("A", "B", "C", "c_minus_a"):
        assert set(r[scope]) == {"b", "se", "ci_low", "ci_high"}
    assert abs(r["A"]["b"] - J_PARTY) < 0.25 * J_PARTY
    assert abs(r["c_minus_a"]["b"]) < 0.5 * J_PARTY
    assert set(r["pooled"]) == {
        "b",
        "se",
        "ci_low",
        "ci_high",
        "ri_p",
        "mean",
        "n_units",
        "n_races",
    }
    assert r["pooled"]["ri_p"] < 0.05
    assert panel.height > 0


# --- Done when 3


def test_a_control_that_differs_within_a_group_raises():
    rows = [{"deputy": "d1"}, {"deputy": "d2"}]
    f1.check_controls(small_panel(rows))
    for column, value in (
        ("party_held_mayor", False),
        ("round", 2),
        ("n_mayor_cands", 4),
        ("population_m", 2000),
    ):
        bad = small_panel([rows[0], {**rows[1], column: value}])
        with pytest.raises(f1.GateError):
            f1.check_controls(bad)
    panel, draws = cached()
    broken = panel.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(9)
        .otherwise(pl.col("n_mayor_cands"))
        .alias("n_mayor_cands")
    )
    with pytest.raises(f1.GateError):
        f1.build_results(broken, H, draws)


def test_null_control_rows_are_dropped_and_counted_pooled_and_by_cycle():
    panel, draws = cached()
    # whole (cycle, town, party) groups: a null round in A, a null count in B, population 0 in C
    towns = {"A": "1500001", "B": "1500002", "C": "1500003"}
    broken = panel.with_columns(
        pl.when((pl.col("cycle") == "A") & (pl.col("cd_ibge") == towns["A"]))
        .then(None)
        .otherwise(pl.col("round"))
        .alias("round"),
        pl.when((pl.col("cycle") == "B") & (pl.col("cd_ibge") == towns["B"]))
        .then(None)
        .otherwise(pl.col("n_mayor_cands"))
        .alias("n_mayor_cands"),
        pl.when((pl.col("cycle") == "C") & (pl.col("cd_ibge") == towns["C"]))
        .then(0)
        .otherwise(pl.col("population_m"))
        .alias("population_m"),
    )
    table = f1.party_table(broken)
    kept, counts = f1.drop_null_controls(table)
    assert counts == {"pooled": 6, "A": 2, "B": 2, "C": 2}
    assert kept.height == table.height - 6
    assert kept["race"].n_unique() == table["race"].n_unique() - 3
    r = f1.build_results(broken, H, draws)
    assert r["counts"]["dropped_null_controls"] == counts


def test_add_controls_builds_the_four_columns():
    out = f1.add_controls(
        small_panel(
            [
                {"deputy": "d1", "round": 2, "party_held_mayor": False},
                {"deputy": "d2", "population_m": 0},
                {"deputy": "d3", "population_m": None},
            ]
        )
    )
    assert out["ctl_held"].to_list() == [0.0, 1.0, 1.0]
    assert out["ctl_round2"].to_list() == [1.0, 0.0, 0.0]
    assert out["ctl_ncands"].to_list() == [3.0, 3.0, 3.0]
    assert out["ctl_lnpop"][0] == pytest.approx(np.log(1000))
    assert out["ctl_lnpop"][1] is None and out["ctl_lnpop"][2] is None


# --- Done when 4


def test_t0_fail_is_one_with_a_planted_jump_and_zero_without():
    _, draws = cached()
    assert cached_results()["placebo"]["t0_fail"] == 0
    r = f1.build_results(make_panel(t0_jump=0.02), H, draws)["placebo"]  # 20% of the 0.10 mean
    assert r["t0_fail"] == 1 and isinstance(r["t0_fail"], int)
    assert r["party_t0"]["ratio"] > 0.1 and r["party_t0"]["ri_p"] < 0.05
    assert set(r["party_t0"]) == {"b", "se", "ri_p", "mean", "ratio"}


# --- Done when 5


def test_window_check_raises_unless_h_pct_is_7_5(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert f1.read_window(good) == pytest.approx(0.075)
    for value in (5.0, 10.0, None):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"window": {"h_pct": value}}), encoding="utf-8")
        with pytest.raises(f1.GateError):
            f1.read_window(bad)
    assert f1.read_window() == pytest.approx(0.075)


# --- Done when 6


def test_rows_outside_the_exploration_half_are_dropped_on_loading():
    panel = make_panel()
    half = frozenset(f"15{i:05d}" for i in range(0, 100, 2))
    asked = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        asked.append((name, list(columns)))
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded = f1.load_panels(read, half)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == panel.filter(pl.col("cd_ibge").is_in(sorted(half))).height
    assert [a[0] for a in asked] == ["panel_A", "panel_B", "panel_C"]
    assert all(cols == f1.READ_COLUMNS for _, cols in asked)
    assert set(f1.READ_COLUMNS) == set(panel.columns)


# --- Done when 7


def test_results_json_is_standard_and_has_the_kill_rule_fields():
    r = cached_results()
    text = json.dumps(r, allow_nan=False)

    def refuse(token: str):
        raise AssertionError(f"non-standard constant {token}")

    parsed = json.loads(text, parse_constant=refuse)
    assert parsed["estimates"]["finite"] is True
    assert parsed["placebo"]["t0_fail"] in (0, 1)
    assert parsed["controls"]["names"] == list(f1.CONTROLS) and len(f1.CONTROLS) == 4
    assert set(parsed["counts"]["dropped_null_controls"]) == {"pooled", "A", "B", "C"}
    assert parsed["counts"]["dropped_null_controls"]["pooled"] == 0
    assert parsed["window"]["h_pct"] == 7.5 and parsed["window"]["check_pct"] == 5
    assert set(parsed["party"]) == set(f1.PARTY_OUTCOMES)
    assert set(parsed["check_5pct"]["d_party"]) == {"b", "se", "ri_p"}
    assert set(parsed["declared"]) == {"d_party", "party_minus_state"}
    assert set(parsed["deputy"]["rf_zero"]) == {"pooled", "A", "B", "C", "c_minus_a"}
    assert parsed["descriptive"]["dose"]["label"] == "descriptive"


def test_dose_is_the_parents_without_controls():
    panel, h = cached()[0], H
    expected = parent.dose(parent.deputy_table(panel), h)
    got = cached_results()["descriptive"]["dose"]
    assert got["b"] == pytest.approx(expected["b"])
    assert got["n_obs"] == expected["n_obs"]


def test_a_non_finite_number_becomes_null_and_flags_estimates():
    panel, draws = cached()
    broken = panel.with_columns(
        pl.when(pl.col("cycle") == "C")
        .then(None)
        .otherwise(pl.col("party_share_t1"))
        .alias("party_share_t1")
    )
    r = f1.build_results(broken, H, draws)
    assert r["party"]["d_party"]["C"]["b"] is None
    assert r["estimates"]["finite"] is False


def test_figures_are_written_and_small(tmp_path):
    panel, _ = cached()
    party, _ = f1.drop_null_controls(f1.party_table(panel))
    f1.write_figures(cached_results(), party, H, tmp_path)
    for name in ("effects_by_cycle.png", "binned_d_party.png"):
        path = tmp_path / "figures" / name
        assert path.is_file()
        assert path.stat().st_size < 400_000


def test_summary_keeps_the_reading_and_shows_the_parent_number():
    parent_b = f1.read_parent()
    assert set(parent_b) == set(f1.PARTY_OUTCOMES)
    text = f1.summarize(cached_results(), parent_b)
    assert f1.FORK_LINE in text
    assert parent.READING in text
    assert "declared in idea 0011's file on 2026-11-20" in text
    assert "parent b (no controls)" in text
    assert f"{parent_b['d_party']:.3g}" in text
    assert "n/a" in f1.summarize(cached_results()).split("## Deputy level")[0]
