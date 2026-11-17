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
    "amendments_gate", REPO / "explore" / "0009_amendments_gate.py"
)
ag = importlib.util.module_from_spec(SPEC)
sys.modules["amendments_gate"] = ag
SPEC.loader.exec_module(ag)

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
POSITIVE_RULE_FIELDS = ag.RULE_FIELDS


def make_panel(plant: str = "none", jump: float = 0.0, seed: int = 3) -> pl.DataFrame:
    """3 cycles x 100 races, 2 to 4 deputies per race, synthetic deputy ids.

    `plant`: "beyond4" shifts `fin_age` of winners with |margin| > 4%; "center" shifts it for
    winners with |margin| <= 0.5%; "none" plants nothing. `jump` is added to the pre-election
    amendments per 1,000 inhabitants of every winning unit.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ci, cycle in enumerate(ag.CYCLES):
        for i in range(100):
            code = f"15{i:05d}"
            margin = float(rng.uniform(-0.1, 0.1))
            win = margin > 0
            n_units = int(rng.integers(2, 5))
            deputies = rng.choice(30, size=n_units, replace=False)
            for d in deputies:
                age = float(np.round(rng.normal(50, 8)))
                if win and (
                    (plant == "beyond4" and abs(margin) > 0.04)
                    or (plant == "center" and abs(margin) <= 0.005)
                ):
                    age += 40
                pop = int(rng.integers(5_000, 200_000))
                y = 100.0 + rng.normal(0, 3) + 0.2 * float(d) + (jump if win else 0.0)
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
                        "fin_female": bool(rng.integers(0, 2)),
                        "fin_age": age if rng.uniform() > 0.05 else None,
                        "fin_higher_ed": bool(rng.integers(0, 2)),
                        "party_held_mayor": bool(rng.integers(0, 2)),
                        "amend_pre_total": y * pop / 1000.0,
                        "amend_pre_pix": 0.0,
                        "share_t0": float(0.05 + rng.normal(0, 0.005)),
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
        }
    )


@cache
def cached(plant: str, jump: float = 0.0) -> tuple[pl.DataFrame, np.ndarray]:
    panel = make_panel(plant, jump)
    return panel, ag.sign_draws(ag.n_races(panel))


def test_window_is_4_when_imbalance_is_planted_beyond_4_percent():
    panel, draws = cached("beyond4")
    chosen = ag.choose_window(panel, draws)
    assert chosen["found"] == 1
    assert chosen["h_pct"] == 4.0
    assert chosen["grid"]["w5pct"]["omnibus_p"] < ag.RULE_P
    for label in ("w0_5pct", "w1pct", "w2pct", "w3pct", "w4pct"):
        assert chosen["grid"][label]["omnibus_p"] >= ag.RULE_P


def test_no_window_when_imbalance_is_at_half_a_percent():
    panel, draws = cached("center")
    results = ag.build_results(panel, make_link(), draws)
    assert results["window"]["found"] == 0
    assert results["window"]["h_pct"] is None
    for field in ag.RULE_FIELDS:
        node = results
        for part in field.split("."):
            node = node[part]
        assert isinstance(node, (int, float)) and not isinstance(node, bool)
    # the rule fields are computed at 0.5%
    assert results["counts"]["units_h"] == results["window"]["grid"]["w0_5pct"]["units"]


def test_planted_placebo_jump_of_half_the_mean_is_recovered():
    # y = 100 + jump on winners: |b| / mean = j / (100 + j/2) = 0.5 for j = 200/3
    panel, draws = cached("none", 200 / 3)
    results = ag.build_results(panel, make_link(), draws)
    assert abs(results["placebo"]["amend_share_abs"] - 0.5) < 0.1
    assert results["placebo"]["amend_ri_p"] < 0.01
    assert results["placebo"]["vote_share_abs"] < 0.3  # share_t0 carries no jump


def test_read_columns_hold_no_post_election_outcome():
    assert len(ag.READ_COLUMNS) == 16
    assert not OUTCOME_COLUMNS & set(ag.READ_COLUMNS)
    assert not any(c.startswith("amend_post_") for c in ag.READ_COLUMNS)


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

    loaded, got_link = ag.load_panels(read, half)
    assert set(loaded["cd_ibge"]) <= half
    assert set(loaded["cd_ibge"]) == half
    assert loaded.height == panel.filter(pl.col("cd_ibge").is_in(sorted(half))).height
    assert [a[0] for a in asked] == ["panel_A", "panel_B", "panel_C", "author_link"]
    assert all(cols == ag.READ_COLUMNS for name, cols in asked if name.startswith("panel_"))
    assert got_link.height == 3


def test_results_json_has_numbers_and_no_nan():
    panel, draws = cached("none")
    results = ag.build_results(panel, make_link(), draws)
    text = json.dumps(results, allow_nan=False)

    def refuse(token: str):
        raise AssertionError(f"non-standard constant {token}")

    parsed = json.loads(text, parse_constant=refuse)
    for field in ag.RULE_FIELDS:
        node = parsed
        for part in field.split("."):
            node = node[part]
        assert isinstance(node, (int, float)) and not isinstance(node, bool)
    assert parsed["estimates"]["finite"] is True
    grid = parsed["window"]["grid"]
    assert list(grid) == list(ag.GRID)
    assert set(grid["w1pct"]["diff"]) == set(ag.COVARIATES)
    assert set(grid["w1pct"]["p"]) == set(ag.COVARIATES)
    assert set(parsed["counts"]["by_cycle"]) == {"A", "B", "C"}
    assert set(parsed["link"]["by_cycle"]["A"]) == {
        "share",
        "authors",
        "deputies",
        "senators",
        "ambiguous",
        "unmatched",
    }
    assert all("." not in key for key in grid)
    assert ag.summarize(parsed).count("## Window table") == 1


def test_a_missing_rule_field_stops_the_run():
    panel, draws = cached("none")
    bad = make_link().filter(pl.col("cycle") != "C")
    with pytest.raises(ag.GateError):
        ag.build_results(panel, bad, draws)
    zero = make_link().with_columns(senators=pl.lit(1000))
    with pytest.raises(ag.GateError):
        ag.link_stats(zero)
    tiny = panel.filter(pl.col("cycle") == "A")  # no units in B and C: still numbers, no raise
    assert ag.counts_at(ag.prepare(tiny), 0.1)["by_cycle"]["B"]["races_h"] == 0


def test_author_share_is_the_smallest_cycle():
    out = ag.link_stats(make_link())
    assert out["by_cycle"]["A"]["share"] == pytest.approx(60 / 90)
    assert out["author_share"] == pytest.approx(min(60 / 90, 70 / 100, 66 / 100))


def test_fit_matches_deputy_dummies_and_cr1_formula():
    panel, _ = cached("none")
    table = ag.in_window(ag.prepare(panel), 0.05).filter(pl.col("y_pre").is_not_null())
    y = table["y_pre"].to_numpy()
    margin = table["margin"].to_numpy()
    sample = ag.Sample(
        y, margin, table["race"].to_numpy(), table["deputy"].to_numpy(), table["cd_ibge"].to_numpy()
    )
    fit = ag.fe_fit(sample)
    # reference: explicit dummies on the units kept (deputies with 2+ units)
    deputy = table["deputy"].to_numpy()
    names, inv, counts = np.unique(deputy, return_inverse=True, return_counts=True)
    keep = counts[inv] >= 2
    win = (margin > 0).astype(float)
    dummies = (inv[:, None] == np.arange(names.size)[None, :]).astype(float)
    dummies = dummies[:, counts >= 2]
    x = np.column_stack([win, margin, win * margin, dummies])[keep]
    beta, *_ = np.linalg.lstsq(x, y[keep], rcond=None)
    assert fit["b"] == pytest.approx(beta[0], rel=1e-8)
    resid = y[keep] - x @ beta
    cl = table["cd_ibge"].to_numpy()[keep]
    _, c_inv = np.unique(cl, return_inverse=True)
    g, n = c_inv.max() + 1, keep.sum()
    scores = np.zeros((g, x.shape[1]))
    np.add.at(scores, c_inv, x * resid[:, None])
    bread = np.linalg.pinv(x.T @ x)
    meat = scores.T @ scores
    var = g / (g - 1) * (n - 1) / (n - 3) * (bread @ meat @ bread)[0, 0]
    assert fit["se"] == pytest.approx(np.sqrt(var), rel=1e-6)


def test_draws_of_ones_reproduce_the_observed_estimate():
    panel, _ = cached("none")
    table = ag.in_window(ag.prepare(panel), 0.05).filter(pl.col("y_pre").is_not_null())
    sample = ag.Sample(
        table["y_pre"].to_numpy(),
        table["margin"].to_numpy(),
        table["race"].to_numpy(),
        table["deputy"].to_numpy(),
        table["cd_ibge"].to_numpy(),
    )
    ones = np.ones((3, ag.n_races(panel)), dtype=np.int8)
    assert ag.ri_b(sample, ones) == pytest.approx([ag.fe_fit(sample)["b"]] * 3)


def test_ri_p_and_power_follow_the_stated_formulas():
    b_draws = np.array([0.5, -2.0, 1.0, np.nan, -3.0])
    p, sd = ag.ri_summary(-2.0, b_draws)
    assert p == pytest.approx((1 + 2) / 6)  # |-2| and |-3| reach |b|
    assert sd == pytest.approx(np.std([0.5, -2.0, 1.0, -3.0], ddof=1))
    panel, draws = cached("none")
    results = ag.build_results(panel, make_link(), draws)
    power = results["power"]
    assert power["mde"] == pytest.approx(2.8 * power["sd_ri"])
    assert power["mde_share"] == pytest.approx(power["mde"] / power["mean"])
    assert results["placebo"]["amend_ri_p"] >= 1 / 2001 - 1e-12


def test_window_edge_is_included_and_draws_are_shared():
    panel = make_panel().with_columns(
        pl.when(pl.col("cd_ibge") == "1500000")
        .then(0.01)
        .otherwise(pl.col("margin"))
        .alias("margin")
    )
    table = ag.prepare(panel)
    assert (ag.in_window(table, 0.01)["cd_ibge"] == "1500000").any()
    assert ag.sign_draws(50).tolist() == ag.sign_draws(50).tolist()
    assert set(np.unique(ag.sign_draws(50))) == {-1, 1}
    assert ag.sign_draws(50).shape == (ag.DRAWS, 50)


def test_balance_p_values_use_the_plus_one_convention():
    panel, draws = cached("none")
    grid = ag.choose_window(panel, draws)["grid"]
    for g in grid.values():
        assert g["omnibus_p"] >= 1 / (ag.DRAWS + 1)
        for p in g["p"].values():
            assert p >= 1 / (ag.DRAWS + 1)
            assert abs(p * (ag.DRAWS + 1) - round(p * (ag.DRAWS + 1))) < 1e-9
        assert g["min_p"] == pytest.approx(min(g["p"].values()))
