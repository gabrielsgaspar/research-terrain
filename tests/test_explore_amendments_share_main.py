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
    "amendments_share_main", REPO / "explore" / "0010_amendments_main.py"
)
sm = importlib.util.module_from_spec(SPEC)
sys.modules["amendments_share_main"] = sm
SPEC.loader.exec_module(sm)

SHARE_JUMPS = {"A": 0.05, "B": 0.10, "C": 0.15}
LOG_JUMP = 0.3
RF_JUMPS = {"A": 0.01, "B": 0.02, "C": 0.03}
VOTES_JUMP = 100.0
REAIS_JUMP = 5000.0


def make_panel(seed: int = 6, share_jumps: dict | None = None) -> pl.DataFrame:
    """3 cycles x 100 races, 2 to 4 deputies per race, planted post-window jumps for winners.

    About one unit in five has `ran_t1` false; its t1 columns carry a wild value so that a script
    that failed to leave it out would be far off.
    """
    jumps = SHARE_JUMPS if share_jumps is None else share_jumps
    rng = np.random.default_rng(seed)
    rows = []
    for ci, cycle in enumerate(sm.CYCLES):
        for i in range(100):
            code = f"15{i:05d}"
            margin = float(rng.uniform(-0.1, 0.1))
            win = margin > 0
            deputies = rng.choice(30, size=int(rng.integers(2, 5)), replace=False)
            for d in deputies:
                ran = bool(rng.uniform() > 0.2)
                votes_t0 = 200.0 + float(d)
                share_t0 = 0.05 + rng.normal(0, 0.004)
                d_share = (RF_JUMPS[cycle] if win else 0.0) + rng.normal(0, 0.004)
                votes_t1 = votes_t0 + (VOTES_JUMP if win else 0.0) + rng.normal(0, 4)
                rows.append(
                    {
                        "cycle": cycle,
                        "m": 2016 + 4 * ci,
                        "cd_ibge": code,
                        "uf": "PA",
                        "deputy": f"{cycle}{d:03d}",
                        "population_m": 50_000,
                        "round": 1,
                        "margin": margin,
                        "win": win,
                        "fin_female": False,
                        "fin_age": 50.0,
                        "fin_higher_ed": False,
                        "party_held_mayor": False,
                        "amend_pre_total": 5000.0,
                        "amend_pre_pix": 0.0,
                        "share_t0": share_t0,
                        "amend_pre_share": 0.1,
                        "amend_pre_log_pc": 1.0,
                        "amend_post_share": 0.1
                        + 0.001 * float(d)
                        + (jumps[cycle] if win else 0.0)
                        + rng.normal(0, 0.01),
                        "amend_post_log_pc": 1.0
                        + 0.01 * float(d)
                        + (LOG_JUMP if win else 0.0)
                        + rng.normal(0, 0.05),
                        "amend_post_total": 10_000.0
                        + (REAIS_JUMP if win else 0.0)
                        + rng.normal(0, 200),
                        "votes_t0": int(votes_t0),
                        "votes_t1": votes_t1 if ran else 9e6,
                        "d_share": d_share if ran else 99.0,
                        "ran_t1": ran,
                    }
                )
    return pl.DataFrame(rows)


@cache
def cached():
    panel = make_panel()
    draws = sm.sign_draws(sm.n_races(panel))
    h_pct = sm.choose_window(panel, draws)["h_pct"]
    return panel, draws, h_pct


def record(h_pct: float, powered=("share", "log_pc")) -> dict:
    return {"run_id": 7, "h_pct": h_pct, "powered": list(powered)}


@cache
def cached_results():
    panel, draws, h_pct = cached()
    return sm.build_results(panel, record(h_pct), draws)


def write_record(directory: Path, run_id: int, title: str, powered: dict, h_pct=7.5, json_too=True):
    (directory / f"{run_id}.md").write_text(f"{title}{run_id}\n\nbody\n", encoding="utf-8")
    if json_too:
        data = {
            "window": {"h_pct": h_pct},
            "power": {"outcomes": {o: {"powered": p} for o, p in powered.items()}},
        }
        (directory / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")


GATE = "# 0010_amendments_gate, run "
FORK = "# 0010_amendments_gate_f1, run "


# --- Done when 1


def test_planted_jumps_are_recovered():
    r = cached_results()
    mean_share = np.mean(list(SHARE_JUMPS.values()))
    mean_rf = np.mean(list(RF_JUMPS.values()))
    share, log_pc = r["first_stage"]["outcomes"]["share"], r["first_stage"]["outcomes"]["log_pc"]
    assert abs(share["b"] - mean_share) < 0.1 * mean_share
    assert abs(log_pc["b"] - LOG_JUMP) < 0.1 * LOG_JUMP
    assert abs(r["reduced_form"]["b"] - mean_rf) < 0.1 * mean_rf
    assert share["f_cluster"] > 10 and log_pc["f_cluster"] > 10
    assert share["strong"] == 1 and r["first_stage"]["n_strong"] == 2
    assert share["ci_low"] < share["b"] < share["ci_high"]
    assert share["ci_high"] - share["b"] == pytest.approx(2.2414 * share["se"])
    assert share["ri_p"] < 0.01
    assert share["n_races"] <= 300 and share["n_units"] > share["n_races"]
    assert abs(r["wald"]["votes_per_1000_reais"] - 1000 * VOTES_JUMP / REAIS_JUMP) < 2.0


def test_a_null_outcome_has_a_large_ri_p():
    panel, draws, h_pct = cached()
    null = make_panel(share_jumps={"A": 0.0, "B": 0.0, "C": 0.0})
    r = sm.build_results(null, record(h_pct), draws)
    assert r["first_stage"]["outcomes"]["share"]["ri_p"] > 0.05
    assert r["first_stage"]["outcomes"]["share"]["strong"] == 0
    assert r["first_stage"]["n_strong"] == 1


# --- Done when 2


def test_gate_record_takes_the_largest_id(tmp_path):
    write_record(tmp_path, 100, GATE, {"share": 0, "log_pc": 1}, h_pct=5.0)
    write_record(tmp_path, 250, GATE, {"share": 1, "log_pc": 1}, h_pct=7.5)
    got = sm.gate_record(tmp_path)
    assert got == {"run_id": 250, "h_pct": 7.5, "powered": ["share", "log_pc"]}


def test_gate_record_ignores_forks_and_records_without_json(tmp_path):
    write_record(tmp_path, 100, GATE, {"share": 0, "log_pc": 1})
    write_record(tmp_path, 300, FORK, {"share": 1, "log_pc": 1})
    write_record(tmp_path, 400, GATE, {"share": 1, "log_pc": 1}, json_too=False)
    got = sm.gate_record(tmp_path)
    assert got["run_id"] == 100 and got["powered"] == ["log_pc"]


def test_gate_record_raises_with_no_record_and_with_none_powered(tmp_path):
    with pytest.raises(sm.GateError):
        sm.gate_record(tmp_path)
    write_record(tmp_path, 300, FORK, {"share": 1, "log_pc": 1})
    with pytest.raises(sm.GateError):
        sm.gate_record(tmp_path)
    write_record(tmp_path, 5, GATE, {"share": 0, "log_pc": 0})
    with pytest.raises(sm.GateError):
        sm.gate_record(tmp_path)


def test_the_record_on_main_is_readable():
    got = sm.gate_record(sm.RUNS)
    assert got["powered"] and set(got["powered"]) <= set(sm.OUTCOMES)


# --- Done when 3 and 4


def test_an_unpowered_outcome_is_not_estimated():
    panel, draws, h_pct = cached()
    r = sm.build_results(panel, record(h_pct, ["log_pc"]), draws)
    assert set(r["first_stage"]["outcomes"]) == {"log_pc"}
    assert r["first_stage"]["n_strong"] == 1
    assert set(r["by_cycle"]["first_stage"]) == {"log_pc"}
    assert set(r["at_5pct"]["first_stage"]) == {"log_pc"}
    assert r["gate"]["powered"] == ["log_pc"]


def test_a_different_window_in_the_record_raises():
    panel, draws, h_pct = cached()
    with pytest.raises(sm.GateError):
        sm.build_results(panel, record(h_pct + 1.0), draws)


# --- Done when 5


def test_by_cycle_difference_matches_the_planted_one():
    r = cached_results()
    planted = SHARE_JUMPS["C"] - SHARE_JUMPS["A"]
    cyc = r["by_cycle"]["first_stage"]["share"]
    assert abs(cyc["c_minus_a"]["b"] - planted) < 0.1 * planted
    for c in sm.CYCLES:
        assert abs(cyc[c]["b"] - SHARE_JUMPS[c]) < 0.2 * SHARE_JUMPS[c]
    rf = r["by_cycle"]["reduced_form"]
    planted_rf = RF_JUMPS["C"] - RF_JUMPS["A"]
    assert abs(rf["c_minus_a"]["b"] - planted_rf) < 0.1 * planted_rf
    assert cyc["c_minus_a"]["se"] > 0


def test_by_cycle_se_matches_a_direct_sandwich():
    panel, draws, h_pct = cached()
    table = sm.add_columns(sm.prepare(panel))
    h = h_pct / 100
    got = sm.by_cycle_fit(table, h, "amend_post_share")
    sub = sm.in_window(table, h).filter(pl.col("amend_post_share").is_not_null())
    deputy = sub["deputy"].to_numpy()
    keep = np.array([(deputy == d).sum() >= 2 for d in deputy])
    sub = sub.filter(pl.Series(keep))
    cyc = np.array([sm.CYCLES.index(c) for c in sub["cycle"]])
    margin = sub["margin"].to_numpy()
    win = (margin > 0).astype(float)
    cols = [b * (cyc == c) for b in (win, margin, win * margin) for c in range(3)]
    fe = pl.Series(sub["deputy"]).to_dummies().to_numpy().astype(float)
    x = np.column_stack([*cols, fe])
    y = sub["amend_post_share"].to_numpy()
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    resid = y - x @ beta
    clusters = sub["cd_ibge"].to_numpy()
    codes = np.unique(clusters, return_inverse=True)[1]
    scores = x * resid[:, None]
    sums = np.column_stack([np.bincount(codes, weights=scores[:, i]) for i in range(x.shape[1])])
    bread = np.linalg.pinv(x.T @ x)
    g, n, k = codes.max() + 1, len(y), 9
    v = g / (g - 1) * (n - 1) / (n - k) * (bread @ (sums.T @ sums) @ bread)
    assert got["A"]["b"] == pytest.approx(beta[0], rel=1e-6)
    assert got["C"]["b"] == pytest.approx(beta[2], rel=1e-6)
    assert got["A"]["se"] == pytest.approx(math.sqrt(v[0, 0]), rel=1e-6)
    diff = math.sqrt(v[2, 2] + v[0, 0] - 2 * v[0, 2])
    assert got["c_minus_a"]["se"] == pytest.approx(diff, rel=1e-6)


# --- Done when 6


def test_units_that_did_not_run_leave_the_reduced_form_and_are_counted():
    panel, draws, h_pct = cached()
    r = cached_results()
    table = sm.add_columns(sm.prepare(panel))
    inside = sm.in_window(table, h_pct / 100)
    ran = inside.filter(pl.col("ran_t1"))
    assert r["reduced_form"]["n_not_running"] == inside.height - ran.height > 0
    assert r["reduced_form"]["n_units"] == ran.height
    assert abs(r["reduced_form"]["mean"]) < 1.0  # the 99.0 placeholders are not in the fit
    assert table.filter(~pl.col("ran_t1"))["rf_y"].null_count() == (~panel["ran_t1"]).sum()


# --- Done when 7


def test_results_json_is_standard_and_has_the_kill_rule_fields():
    r = cached_results()
    text = json.dumps(r, allow_nan=False)

    def refuse(token: str):
        raise AssertionError(f"non-standard constant {token}")

    parsed = json.loads(text, parse_constant=refuse)
    n_strong = parsed["first_stage"]["n_strong"]
    assert isinstance(n_strong, int) and not isinstance(n_strong, bool)
    assert parsed["estimates"]["finite"] is True
    assert parsed["gate"]["run_id"] == 7
    assert parsed["window"]["h_pct"] == parsed["gate"]["h_pct"]
    for o in ("share", "log_pc"):
        assert set(parsed["first_stage"]["outcomes"][o]) == set(sm.FS_KEYS)
        assert set(parsed["at_5pct"]["first_stage"][o]) == {"f_cluster", "b", "se", "ri_p"}
        assert set(parsed["by_cycle"]["first_stage"][o]) == {"A", "B", "C", "c_minus_a"}
    assert set(parsed["reduced_form"]) == {*sm.RF_KEYS, "n_not_running"}
    assert set(parsed["at_5pct"]["reduced_form"]) == {"b", "se", "ri_p"}
    assert set(parsed["wald"]) == {"votes_per_1000_reais", "rf_votes_b", "fs_reais_b"}


def test_a_non_finite_number_becomes_null_and_flags_estimates():
    panel, draws, h_pct = cached()
    flat = panel.with_columns(amend_post_total=pl.lit(1.0))
    r = sm.build_results(flat, record(h_pct), draws)
    assert r["wald"]["votes_per_1000_reais"] is None or r["estimates"]["finite"] is False
    assert isinstance(r["first_stage"]["n_strong"], int)


def test_summary_has_the_required_lines():
    text = sm.summarize(cached_results())
    assert "run 7" in text
    assert "upper bound" in text
    assert "## By cycle" in text
    assert "per-capita reais" in text
    assert "Nothing on the exploration half is a finding" in text


# --- Done when 8


def test_rows_outside_the_exploration_half_are_gone_after_loading():
    panel = make_panel()
    half = frozenset(f"15{i:05d}" for i in range(0, 100, 2))
    asked = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        asked.append((name, list(columns)))
        return panel.filter(pl.col("cycle") == name[-1]).select(columns)

    loaded = sm.load_panels(read, half)
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == panel.filter(pl.col("cd_ibge").is_in(sorted(half))).height
    assert [a[0] for a in asked] == ["panel_A", "panel_B", "panel_C"]
    assert all(cols == sm.READ_COLUMNS for _, cols in asked)


def test_read_columns_add_only_the_listed_outcomes():
    extra = set(sm.READ_COLUMNS) - set(sm.gate.READ_COLUMNS)
    assert extra == {
        "amend_post_share",
        "amend_post_log_pc",
        "amend_post_total",
        "votes_t0",
        "votes_t1",
        "d_share",
        "ran_t1",
    }
    assert "author_link" not in " ".join(sm.READ_COLUMNS)
