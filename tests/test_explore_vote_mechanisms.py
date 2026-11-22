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
    "vote_mechanisms", REPO / "explore" / "0010_vote_mechanisms.py"
)
vm = importlib.util.module_from_spec(SPEC)
sys.modules["vote_mechanisms"] = vm
SPEC.loader.exec_module(vm)

H = 0.075
J_PARTY, J_STATE, J_DEPUTY = 0.04, 0.02, 0.006  # two deputies per party: d_inc jump is 0.012
J_INC = 2 * J_DEPUTY
DRAWS = 300


def make_panel(seed: int = 3, t0_jump: float = 0.0) -> pl.DataFrame:
    """3 cycles x 100 races; two finalist parties per race, two deputies per party, all running.

    Winners' party, state and deputy shares jump at t1. `t0_jump` plants a jump in the winners'
    `party_share_t0` and `state_party_share_t0` (a placebo failure).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for cycle in vm.CYCLES:
        for i in range(100):
            code = f"15{i:05d}"
            m = float(rng.uniform(0.001, 0.1))
            sign = 1 if rng.uniform() > 0.5 else -1
            parties = rng.choice(6, size=2, replace=False)
            for k, party in enumerate(parties):
                margin = sign * m * (1 if k == 0 else -1)
                win = margin > 0
                p0 = 0.10 + (t0_jump if win else 0.0) + rng.normal(0, 0.0015)
                s0 = 0.08 + (t0_jump if win else 0.0) + rng.normal(0, 0.0015)
                p1 = p0 + (J_PARTY if win else 0.0) + rng.normal(0, 0.0015)
                s1 = s0 + (J_STATE if win else 0.0) + rng.normal(0, 0.0015)
                for j in range(2):
                    t0 = 0.04 + rng.normal(0, 0.0015)
                    t1 = t0 + (J_DEPUTY if win else 0.0) + rng.normal(0, 0.0015)
                    rows.append(
                        {
                            "cycle": cycle,
                            "cd_ibge": code,
                            "uf": "PA",
                            "deputy": f"{cycle}-{party}-{j}",
                            "deputy_party": int(party),
                            "margin": margin,
                            "win": win,
                            "population_m": 50_000,
                            "share_t0": t0,
                            "share_t1": t1,
                            "ran_t1": True,
                            "d_share": t1 - t0,
                            "amend_post_log_pc": float(rng.uniform(0, 5)),
                            "party_share_t0": p0,
                            "party_share_t1": p1,
                            "state_party_share_t0": s0,
                            "state_party_share_t1": s1,
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
        "ran_t1": True,
        "d_share": 0.0,
        "amend_post_log_pc": 1.0,
        "party_share_t0": 0.10,
        "party_share_t1": 0.15,
        "state_party_share_t0": 0.08,
        "state_party_share_t1": 0.09,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


@cache
def cached():
    panel = make_panel()
    draws = vm.sign_draws(vm.n_races(vm.party_table(panel)), draws=DRAWS)
    return panel, draws


@cache
def cached_results():
    panel, draws = cached()
    return vm.build_results(panel, H, draws)


# --- Done when 1


def test_planted_jumps_are_recovered():
    r = cached_results()["party"]
    assert abs(r["d_party"]["pooled"]["b"] - J_PARTY) < 0.1 * J_PARTY
    assert abs(r["d_inc"]["pooled"]["b"] - J_INC) < 0.1 * J_INC
    assert abs(r["d_state"]["pooled"]["b"] - J_STATE) < 0.1 * J_STATE
    diff = r["d_party"]["pooled"]["b"] - r["d_state"]["pooled"]["b"]
    assert r["party_minus_state"]["pooled"]["b"] == pytest.approx(diff, abs=1e-9)
    inc = r["d_party"]["pooled"]["b"] - r["d_inc"]["pooled"]["b"]
    assert r["party_minus_inc"]["pooled"]["b"] == pytest.approx(inc, abs=1e-9)
    pooled = r["d_party"]["pooled"]
    assert pooled["ri_p"] < 0.05
    assert pooled["ci_high"] - pooled["b"] == pytest.approx(1.96 * pooled["se"])
    assert pooled["n_races"] >= 150 and pooled["n_units"] >= 2 * pooled["n_races"] - 1


def test_by_cycle_blocks_have_intervals():
    r = cached_results()["party"]["d_party"]
    for scope in ("A", "B", "C", "c_minus_a"):
        assert set(r[scope]) == {"b", "se", "ci_low", "ci_high"}
    assert abs(r["A"]["b"] - J_PARTY) < 0.2 * J_PARTY
    assert abs(r["c_minus_a"]["b"]) < 0.5 * J_PARTY


# --- Done when 2


def test_collapse_sums_deputies_and_counts_a_non_runner_as_zero():
    panel = small_panel(
        [
            {"deputy": "d1", "share_t0": 0.03, "share_t1": 0.05, "ran_t1": True},
            {"deputy": "d2", "share_t0": 0.02, "share_t1": 9.0, "ran_t1": False},
        ]
    )
    out = vm.collapse(panel)
    assert out.height == 1
    assert out["d_inc"][0] == pytest.approx(0.05 - (0.03 + 0.02))
    assert out["d_party"][0] == pytest.approx(0.05)
    assert out["d_state"][0] == pytest.approx(0.01)
    assert out["party_minus_state"][0] == pytest.approx(0.04)
    assert out["deputy"][0] == "PA|11|A"


def test_collapse_raises_when_a_group_value_differs():
    rows = [{"deputy": "d1", "share_t0": 0.03, "share_t1": 0.05}] * 2
    rows[1] = {**rows[1], "deputy": "d2"}
    assert vm.collapse(small_panel(rows)).height == 1
    with pytest.raises(vm.GateError):
        vm.collapse(small_panel([rows[0], {**rows[1], "margin": 0.03}]))
    with pytest.raises(vm.GateError):
        vm.collapse(small_panel([rows[0], {**rows[1], "party_share_t1": 0.16}]))
    with pytest.raises(vm.GateError):
        vm.collapse(small_panel([rows[0], {**rows[1], "party_share_t0": None}]))


def test_races_equal_t1_share_counts_merged_finalists():
    panel = small_panel(
        [
            {"deputy": "d1", "share_t0": 0.03, "share_t1": 0.05},
            {"deputy": "d2", "deputy_party": 22, "margin": -0.02, "win": False, "share_t0": 0.03},
            {"cd_ibge": "1500002", "deputy": "d1", "share_t0": 0.03, "share_t1": 0.05},
            {
                "cd_ibge": "1500002",
                "deputy": "d2",
                "deputy_party": 22,
                "margin": -0.02,
                "win": False,
                "party_share_t1": 0.20,
                "share_t0": 0.03,
            },
        ]
    )
    table = vm.party_table(panel)
    assert vm.races_equal_t1_share(table, H) == 1


# --- Done when 3


def test_deputy_level_counts_a_non_runner_as_zero():
    panel = small_panel(
        [
            {"deputy": "d1", "share_t0": 0.03, "share_t1": 0.05, "ran_t1": True},
            {"deputy": "d2", "share_t0": 0.02, "share_t1": 9.0, "ran_t1": False},
            {"deputy": "d3", "share_t0": 0.04, "share_t1": None, "ran_t1": False},
        ]
    )
    table = vm.deputy_table(panel).sort("deputy")
    assert table["rf_zero"].to_list() == pytest.approx([0.02, -0.02, -0.04])
    assert "amend_pre_total" in table.columns


def test_deputy_block_counts_not_running():
    r = cached_results()["deputy"]
    assert r["n_not_running"] == 0
    assert set(r["rf_zero"]) == {"pooled", "A", "B", "C", "c_minus_a"}
    assert abs(r["rf_zero"]["pooled"]["b"] - J_DEPUTY) < 0.15 * J_DEPUTY


# --- Done when 4


def test_t0_fail_is_one_with_a_planted_jump_and_zero_without():
    panel, draws = cached()
    assert cached_results()["placebo"]["t0_fail"] == 0
    jumped = make_panel(t0_jump=0.02)  # 20% of the 0.10 mean
    r = vm.build_results(jumped, H, draws)["placebo"]
    assert r["t0_fail"] == 1 and isinstance(r["t0_fail"], int)
    assert r["party_t0"]["ratio"] > 0.1 and r["party_t0"]["ri_p"] < 0.05
    assert set(r["party_t0"]) == {"b", "se", "ri_p", "mean", "ratio"}


# --- Done when 5


def test_holm():
    assert vm.holm([0.01, 0.04]) == pytest.approx([0.02, 0.04])
    assert vm.holm([0.04, 0.01]) == pytest.approx([0.04, 0.02])
    assert vm.holm([0.4, 0.3]) == pytest.approx([0.6, 0.6])
    assert all(np.isnan(vm.holm([0.01, float("nan")])))


def test_declared_estimates_carry_raw_and_holm_p():
    d = cached_results()["declared"]
    assert set(d) == {"d_party", "party_minus_state"}
    for v in d.values():
        assert v["p_holm"] >= v["p"]
    assert d["d_party"]["p"] == cached_results()["party"]["d_party"]["pooled"]["ri_p"]


# --- Done when 6


def test_window_check_raises_unless_h_pct_is_7_5(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"window": {"h_pct": 7.5}}), encoding="utf-8")
    assert vm.read_window(good) == pytest.approx(0.075)
    for value in (5.0, 10.0, None):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"window": {"h_pct": value}}), encoding="utf-8")
        with pytest.raises(vm.GateError):
            vm.read_window(bad)


def test_the_record_on_main_gives_7_5():
    assert vm.read_window() == pytest.approx(0.075)


# --- Done when 7


def test_rows_outside_the_exploration_half_are_dropped_on_loading():
    panel = make_panel()
    half = frozenset(f"15{i:05d}" for i in range(0, 100, 2))
    asked = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        asked.append((name, list(columns)))
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded = vm.load_panels(read, half)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == panel.filter(pl.col("cd_ibge").is_in(sorted(half))).height
    assert [a[0] for a in asked] == ["panel_A", "panel_B", "panel_C"]
    assert all(cols == vm.READ_COLUMNS for _, cols in asked)


def test_read_columns_are_the_issue_list():
    assert set(vm.READ_COLUMNS) == set(make_panel().columns)
    assert "amend_pre_total" not in vm.READ_COLUMNS


# --- Done when 8


def test_results_json_is_standard_and_has_the_kill_rule_fields():
    r = cached_results()
    text = json.dumps(r, allow_nan=False)

    def refuse(token: str):
        raise AssertionError(f"non-standard constant {token}")

    parsed = json.loads(text, parse_constant=refuse)
    assert parsed["estimates"]["finite"] is True
    assert parsed["placebo"]["t0_fail"] in (0, 1)
    assert parsed["window"]["h_pct"] == 7.5 and parsed["window"]["check_pct"] == 5
    assert parsed["window"]["source"].endswith("44484340952.json")
    assert set(parsed["counts"]) == {
        "party_rows_h",
        "races_h",
        "groups_h",
        "by_cycle",
        "races_equal_t1_share",
    }
    assert set(parsed["counts"]["by_cycle"]["A"]) == {"rows", "races"}
    assert set(parsed["party"]) == set(vm.PARTY_OUTCOMES)
    assert set(parsed["party"]["d_inc"]["pooled"]) == {
        "b",
        "se",
        "ci_low",
        "ci_high",
        "ri_p",
        "mean",
        "n_units",
        "n_races",
    }
    assert set(parsed["check_5pct"]["d_party"]) == {"b", "se", "ri_p"}
    assert set(parsed["descriptive"]["dose"]) == {"b", "se", "n_obs", "label"}
    assert parsed["descriptive"]["dose"]["label"] == "descriptive"
    assert parsed["descriptive"]["dose"]["n_obs"] > 0


def test_a_non_finite_number_becomes_null_and_flags_estimates():
    panel, draws = cached()
    broken = panel.with_columns(
        pl.when(pl.col("cycle") == "C")
        .then(None)
        .otherwise(pl.col("party_share_t1"))
        .alias("party_share_t1")
    )
    r = vm.build_results(broken, H, draws)
    assert r["party"]["d_party"]["C"]["b"] is None
    assert r["estimates"]["finite"] is False


def test_figures_are_written_and_small(tmp_path):
    panel, draws = cached()
    vm.write_figures(cached_results(), vm.party_table(panel), H, tmp_path)
    for name in ("effects_by_cycle.png", "binned_d_party.png"):
        path = tmp_path / "figures" / name
        assert path.is_file()
        assert path.stat().st_size < 400_000


def test_binned_means_show_the_jump_at_zero():
    panel, _ = cached()
    centres, means = vm.binned_means(vm.party_table(panel), H)
    assert len(centres) == 30
    assert means[centres > 0].mean() - means[centres < 0].mean() == pytest.approx(J_PARTY, rel=0.1)


def test_summary_has_the_reading_and_caveats():
    text = vm.summarize(cached_results())
    assert vm.READING in text
    assert "descriptive" in text
    assert "Holm" in text
    assert "declared in idea 0011's file on 2026-11-20" in text
    assert "Nothing on the exploration half is a finding" in text
