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
    "amendments_share_gate", REPO / "explore" / "0010_amendments_gate.py"
)
sg = importlib.util.module_from_spec(SPEC)
sys.modules["amendments_share_gate"] = sg
SPEC.loader.exec_module(sg)

OUTCOME_COLUMNS = {
    "amend_post_total",
    "amend_post_pix",
    "n_pay_post",
    "ran_t1",
    "votes_t1",
    "valid_t1",
    "share_t1",
    "d_share",
}
SHARE_BASE = 0.1
LOG_BASE = 1.0


def make_panel(
    plant: str = "none",
    share_jump: float = 0.0,
    log_jump: float = 0.0,
    share_sd: float = 0.002,
    log_sd: float = 0.02,
    seed: int = 6,
) -> pl.DataFrame:
    """3 cycles x 100 races, 2 to 4 deputies per race, synthetic deputy ids.

    `plant`: "beyond4" shifts `fin_age` of winners with |margin| > 4%; "center" shifts it for
    winners with |margin| <= 0.5%; "none" plants nothing. `share_jump` and `log_jump` are added to
    `amend_pre_share` and `amend_pre_log_pc` of every winning unit.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ci, cycle in enumerate(sg.CYCLES):
        for i in range(100):
            code = f"15{i:05d}"
            margin = float(rng.uniform(-0.1, 0.1))
            win = margin > 0
            n_units = int(rng.integers(2, 5))
            deputies = rng.choice(30, size=n_units, replace=False)
            for d in deputies:
                # covariates are constant unless planted, so chance never picks the window
                age = 50.0
                if win and (
                    (plant == "beyond4" and abs(margin) > 0.04)
                    or (plant == "center" and abs(margin) <= 0.005)
                ):
                    age += 40
                pop = 50_000
                share = SHARE_BASE + 0.001 * float(d) + rng.normal(0, share_sd)
                log_pc = LOG_BASE + 0.01 * float(d) + rng.normal(0, log_sd)
                rows.append(
                    {
                        "cycle": cycle,
                        "m": 2016 + 4 * ci,
                        "cd_ibge": code,
                        "uf": "PA",
                        "deputy": f"{cycle}{d:03d}",
                        "population_m": pop,
                        "round": 1,
                        "margin": margin,
                        "win": win,
                        "fin_female": False,
                        "fin_age": age if rng.uniform() > 0.05 else None,
                        "fin_higher_ed": False,
                        "party_held_mayor": False,
                        "amend_pre_total": 100.0 * pop / 1000.0,
                        "amend_pre_pix": 0.0,
                        "share_t0": float(0.05 + rng.normal(0, 0.005)),
                        "amend_pre_share": share + (share_jump if win else 0.0),
                        "amend_pre_log_pc": log_pc + (log_jump if win else 0.0),
                    }
                )
    return pl.DataFrame(rows)


def make_link() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cycle": ["A", "B", "C"],
            "authors": [100, 120, 110],
            "deputies": [60, 70, 66],
            "senators": [10, 20, 10],
            "ambiguous": [3, 4, 5],
            "unmatched": [20, 25, 28],
            "ties_broken": [1, 2, 3],
            "non_current_authors": [7, 8, 9],
            "chamber_links": [50, 60, 55],
            "money_share": [0.915, 0.926, 0.932],
        }
    )


@cache
def cached_panel(plant: str = "none", share_jump: float = 0.0, log_jump: float = 0.0, noisy=False):
    sd = 0.5 if noisy else 0.002
    panel = make_panel(plant, share_jump, log_jump, share_sd=sd)
    return panel, sg.sign_draws(sg.n_races(panel))


@cache
def cached_results(
    plant: str = "none", share_jump: float = 0.0, log_jump: float = 0.0, noisy=False
):
    panel, draws = cached_panel(plant, share_jump, log_jump, noisy)
    return sg.build_results(panel, make_link(), draws)


def number(results: dict, dotted: str) -> float:
    node = results
    for part in dotted.split("."):
        node = node[part]
    assert isinstance(node, (int, float)) and not isinstance(node, bool), dotted
    return node


def test_window_is_4_when_imbalance_is_planted_beyond_4_percent():
    panel, draws = cached_panel("beyond4")
    chosen = sg.choose_window(panel, draws)
    assert chosen["found"] == 1
    assert chosen["h_pct"] == 4.0
    assert chosen["grid"]["w5pct"]["omnibus_p"] < sg.RULE_P
    for label in ("w0_5pct", "w1pct", "w2pct", "w3pct", "w4pct"):
        assert chosen["grid"][label]["omnibus_p"] >= sg.RULE_P


def test_no_window_when_imbalance_is_at_half_a_percent():
    results = cached_results("center")
    assert results["window"]["found"] == 0
    assert results["window"]["h_pct"] is None
    for field in sg.RULE_FIELDS:
        number(results, field)
    assert results["counts"]["units_h"] == results["window"]["grid"]["w0_5pct"]["units"]


def test_planted_placebo_jumps_are_recovered():
    # share: j / (base + j / 2) = 0.5 for j = 2 base / 3; log_pc: |b| = jump
    results = cached_results("none", SHARE_BASE * 2 / 3, 0.5)
    share = results["placebo"]["outcomes"]["share"]
    log_pc = results["placebo"]["outcomes"]["log_pc"]
    assert abs(share["stat"] - 0.5) < 0.1
    assert abs(log_pc["stat"] - 0.5) < 0.1
    assert share["fails"] == 1 and log_pc["fails"] == 1
    assert share["ri_p"] < 0.01 and log_pc["ri_p"] < 0.01
    assert results["placebo"]["vote_share_abs"] < 0.3  # share_t0 carries no jump
    assert results["placebo"]["at_5pct"]["share"]["stat"] > 0.3


def test_a_world_with_a_noisy_share_has_one_powered_outcome():
    quiet = cached_results("none", noisy=True)
    out = quiet["power"]["outcomes"]
    assert quiet["power"]["n_powered"] == 1
    assert out["share"]["powered"] == 0 and out["share"]["mde_stat"] > out["share"]["limit"]
    assert out["log_pc"]["powered"] == 1 and out["log_pc"]["mde_stat"] <= out["log_pc"]["limit"]
    assert out["log_pc"]["mde"] == pytest.approx(sg.MDE_K * out["log_pc"]["sd_ri"])
    assert out["share"]["mde_stat"] == pytest.approx(
        sg.MDE_K * out["share"]["sd_ri"] / out["share"]["mean"]
    )
    assert quiet["power"]["at_5pct"]["log_pc"]["mde_stat"] > 0
    assert quiet["placebo"]["powered_failing"] == 0
    # a jump planted only in the unpowered outcome leaves powered_failing at 0
    share_only = cached_results("none", 0.5, 0.0, noisy=True)
    assert share_only["power"]["outcomes"]["share"]["powered"] == 0
    assert share_only["placebo"]["outcomes"]["share"]["fails"] == 1
    assert share_only["placebo"]["powered_failing"] == 0
    # the same jump in the powered outcome makes it 1
    log_only = cached_results("none", 0.0, 0.3, noisy=True)
    assert log_only["power"]["n_powered"] == 1
    assert log_only["placebo"]["outcomes"]["log_pc"]["fails"] == 1
    assert log_only["placebo"]["powered_failing"] == 1


def test_null_share_rows_leave_the_share_fit_only():
    panel, draws = cached_panel("none", SHARE_BASE * 2 / 3, 0.5)
    base = cached_results("none", SHARE_BASE * 2 / 3, 0.5)
    holes = panel.with_columns(
        pl.when(pl.int_range(pl.len()) % 5 == 0)
        .then(None)
        .otherwise(pl.col("amend_pre_share"))
        .alias("amend_pre_share")
    )
    results = sg.build_results(holes, make_link(), draws)
    assert (
        results["placebo"]["outcomes"]["share"]["units"]
        < base["placebo"]["outcomes"]["share"]["units"]
    )
    assert results["placebo"]["outcomes"]["log_pc"] == base["placebo"]["outcomes"]["log_pc"]
    assert results["power"]["outcomes"]["log_pc"] == base["power"]["outcomes"]["log_pc"]
    assert results["counts"] == base["counts"]


def test_money_share_is_the_smallest_and_null_raises():
    out = sg.link_stats(make_link())
    assert out["money_share"] == pytest.approx(0.915)
    assert out["by_cycle"]["B"]["money_share"] == pytest.approx(0.926)
    assert out["by_cycle"]["A"]["share"] == pytest.approx(60 / 90)
    assert out["author_share"] == pytest.approx(min(60 / 90, 70 / 100, 66 / 100))
    low_c = make_link().with_columns(money_share=pl.Series([0.95, 0.96, 0.9]))
    assert sg.link_stats(low_c)["money_share"] == pytest.approx(0.9)
    null_b = make_link().with_columns(money_share=pl.Series([0.9, None, 0.9], dtype=pl.Float64))
    with pytest.raises(sg.GateError):
        sg.link_stats(null_b)
    panel, draws = cached_panel("none")
    with pytest.raises(sg.GateError):
        sg.build_results(panel, null_b, draws)
    with pytest.raises(sg.GateError):
        sg.link_stats(make_link().filter(pl.col("cycle") != "C"))
    with pytest.raises(sg.GateError):
        sg.link_stats(pl.concat([make_link(), make_link().head(1)]))


def test_mde_k_is_3_0830():
    assert round(sg.MDE_K, 4) == 3.0830
    assert sg.ALPHA == 0.025
    assert sg.OUTCOMES == ("share", "log_pc")
    assert sg.LIMITS == {"share": 0.25, "log_pc": 0.223}


def test_read_columns_hold_no_post_election_outcome():
    assert not OUTCOME_COLUMNS & set(sg.READ_COLUMNS)
    assert not any(c.startswith("amend_post_") for c in sg.READ_COLUMNS)
    assert {"amend_pre_share", "amend_pre_log_pc"} <= set(sg.READ_COLUMNS)
    assert set(sg.g9.READ_COLUMNS) <= set(sg.READ_COLUMNS)
    assert len(sg.LINK_COLUMNS) == 10
    assert not OUTCOME_COLUMNS & set(sg.LINK_COLUMNS)


def test_rows_outside_the_exploration_half_are_gone_after_loading():
    panel = make_panel()
    link = make_link()
    half = frozenset(f"15{i:05d}" for i in range(0, 100, 2))
    asked = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        asked.append((name, list(columns)))
        if name == "author_link":
            return link.select(columns)
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded, got_link = sg.load_panels(read, half)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == panel.filter(pl.col("cd_ibge").is_in(sorted(half))).height
    assert [a[0] for a in asked] == ["panel_A", "panel_B", "panel_C", "author_link"]
    assert all(cols == sg.READ_COLUMNS for name, cols in asked if name.startswith("panel_"))
    assert asked[-1][1] == sg.LINK_COLUMNS
    assert got_link.height == 3


def test_results_json_has_numbers_and_no_nan():
    results = cached_results("none", noisy=True)
    text = json.dumps(results, allow_nan=False)

    def refuse(token: str):
        raise AssertionError(f"non-standard constant {token}")

    parsed = json.loads(text, parse_constant=refuse)
    for field in sg.RULE_FIELDS:
        number(parsed, field)
    assert parsed["estimates"]["finite"] is True
    assert parsed["power"]["alpha"] == 0.025
    for o in sg.OUTCOMES:
        assert set(parsed["power"]["outcomes"][o]) == {
            "mde",
            "sd_ri",
            "mean",
            "units",
            "mde_stat",
            "limit",
            "powered",
        }
        assert set(parsed["placebo"]["outcomes"][o]) == {
            "b",
            "se",
            "ri_p",
            "mean",
            "units",
            "stat",
            "limit",
            "fails",
        }
        assert set(parsed["power"]["at_5pct"][o]) == {"mde_stat"}
        assert set(parsed["placebo"]["at_5pct"][o]) == {"stat"}
    assert "vote_share_abs" in parsed["placebo"]["at_5pct"]
    assert set(parsed["link"]["by_cycle"]["A"]) == {"money_share", "share", *sg.COUNT_COLUMNS}
    grid = parsed["window"]["grid"]
    assert list(grid) == list(sg.GRID)
    assert all("." not in key for key in grid)
    summary = sg.summarize(parsed)
    assert summary.count("## Window table") == 1
    assert "per-capita reais" in summary
    assert "not proof of balance" in summary
    assert "Nothing on the exploration half is a finding" in summary
