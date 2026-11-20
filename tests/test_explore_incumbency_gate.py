import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "incumbency_gate", REPO / "explore" / "0011_incumbency_gate.py"
)
ig = importlib.util.module_from_spec(SPEC)
sys.modules["incumbency_gate"] = ig
SPEC.loader.exec_module(ig)

FORBIDDEN = ("party_next", "amend_after")


def make_panel(
    plant: str = "none",
    races: dict[int, int] | int = 150,
    seed: int = 5,
    margin_cap: float = 0.1,
) -> pl.DataFrame:
    """Two rows per race, five elections; both rows of a race share their covariates.

    `plant`: "band" sets the winner's `party_held_mayor_lag` to 1 and the loser's to 0 only for
    1% < |margin| <= 2%; "all" does it at every margin; "none" plants nothing.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for e in ig.ELECTIONS:
        n = races[e] if isinstance(races, dict) else races
        for i in range(n):
            m = float(rng.uniform(0.0005, margin_cap))
            shared = {
                "election": e,
                "cd_ibge": f"15{i:05d}",
                "uf": "PA",
                "fin_female": bool(rng.integers(0, 2)),
                "fin_age": float(np.round(rng.normal(50, 8))),
                "fin_higher_ed": bool(rng.integers(0, 2)),
                "ln_pop": float(rng.normal(9, 1)),
                "n_mayor_cands": 3,
                "bench_fed": None,
                "finalist_eligible": True,
            }
            lag = bool(rng.integers(0, 2))
            planted = plant == "all" or (plant == "band" and 0.01 < m <= 0.02)
            for sign in (1, -1):
                held = (sign > 0) if planted else lag
                rows.append(
                    {
                        **shared,
                        "party": f"P{sign}",
                        "margin": sign * m,
                        "win": sign > 0,
                        "party_held_mayor_lag": held,
                    }
                )
    return pl.DataFrame(rows)


def small_draws(panel: pl.DataFrame, n: int = 200) -> np.ndarray:
    return ig.sign_draws(ig.n_races(panel), draws=n)


# --- Done when 1: the window rule


def test_balanced_panel_chooses_widest_window():
    panel = make_panel("none")
    chosen = ig.choose_window(panel, ig.sign_draws(ig.n_races(panel)))
    assert chosen["found"] == 1
    assert chosen["h_pct"] == pytest.approx(10.0)
    assert chosen["h"] == pytest.approx(0.10)


def test_imbalance_between_1_and_2_percent_gives_h_1pct():
    panel = make_panel("band")
    chosen = ig.choose_window(panel, ig.sign_draws(ig.n_races(panel)))
    assert chosen["found"] == 1
    assert chosen["h_pct"] == pytest.approx(1.0)
    assert chosen["grid"]["w2pct"]["omnibus_p"] < ig.RULE_P
    assert chosen["grid"]["w10pct"]["omnibus_p"] < ig.RULE_P  # the rule stops at the first failure


def test_imbalance_at_every_margin_finds_no_window():
    panel = make_panel("all")
    chosen = ig.choose_window(panel, ig.sign_draws(ig.n_races(panel)))
    assert chosen["found"] == 0
    assert chosen["h_pct"] is None
    assert chosen["h"] == pytest.approx(0.005)


def test_by_election_balance_is_reported():
    panel = make_panel("none", races=40)
    chosen = ig.choose_window(panel, small_draws(panel))
    for e in ig.ELECTIONS:
        for label in ig.GRID:
            cell = chosen["by_election"][f"e{e}"][label]
            assert set(cell) == {"omnibus_p", "races"}


# --- Done when 2: the re-flip


def test_reflip_swaps_the_winner_of_a_race():
    panel = ig.prepare(make_panel("none", races=10))
    margin = panel["margin"].to_numpy()
    race = panel["race"].to_numpy()
    original_win = panel["win"].to_numpy()
    signs = ig.sign_draws(ig.n_races(panel), draws=1)[0]
    flipped, win = ig.flip(margin, race, signs)
    for r in np.unique(race):
        idx = np.flatnonzero(race == r)
        assert idx.size == 2
        a, b = idx
        assert win[a] == original_win[b] if signs[r] < 0 else win[a] == original_win[a]
        assert win[a] != win[b]
        assert flipped[a] == -flipped[b]


# --- Done when 3: the model


def planted_table(jump: float = 2.0, seed: int = 1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(600):
        m = float(rng.uniform(0.001, 0.1))
        for sign in (1, -1):
            margin = sign * m
            win = margin > 0
            rows.append(
                {
                    "election": 2012,
                    "cd_ibge": f"15{i:05d}",
                    "margin": margin,
                    "win": win,
                    "y": 1.0 + 0.5 * margin + jump * win + rng.normal(0, 0.1),
                }
            )
    return ig.prepare(pl.DataFrame(rows))


def test_fit_recovers_a_planted_jump():
    result = ig.fit(planted_table(2.0), "y", 0.1, [[2012]])
    assert result["b"][0] == pytest.approx(2.0, rel=0.1)
    assert result["n_races"] == 600
    assert result["n_units"] == 1200


def test_fit_cluster_se_matches_a_hand_computed_cr1():
    # Two clusters of six rows, one election, one group: K = 4.
    margin = np.array(
        [0.01, 0.03, -0.02, -0.04, 0.05, -0.01, 0.02, 0.04, -0.03, -0.05, 0.06, -0.02]
    )
    y = np.array([1.0, 2.5, 0.2, -0.3, 3.1, 0.4, 2.2, 2.9, 0.1, -0.6, 3.4, 0.3])
    code = ["a"] * 6 + ["b"] * 6
    table = ig.prepare(
        pl.DataFrame(
            {
                "election": [2012] * 12,
                "cd_ibge": code,
                "margin": margin,
                "win": margin > 0,
                "y": y,
            }
        )
    )
    result = ig.fit(table, "y", 0.1, [[2012]])

    win = (margin > 0).astype(float)
    x = np.column_stack([np.ones(12), margin, win * margin, win])
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    meat = np.zeros((4, 4))
    for c in ("a", "b"):
        idx = [i for i, v in enumerate(code) if v == c]
        s = x[idx].T @ resid[idx]
        meat += np.outer(s, s)
    n, k, gc = 12, 4, 2
    cov = gc / (gc - 1) * (n - 1) / (n - k) * xtx_inv @ meat @ xtx_inv
    assert result["b"][0] == pytest.approx(beta[3])
    assert result["se"][0] == pytest.approx(np.sqrt(cov[3, 3]))


def test_fit_drops_elections_outside_every_group():
    table = ig.prepare(
        pl.concat(
            [
                planted_table(2.0, seed=1),
                planted_table(2.0, seed=2).with_columns(pl.lit(2004).alias("election")),
            ],
            how="diagonal_relaxed",
        ).drop("race")
    )
    result = ig.fit(table, "y", 0.1, [[2012]])
    assert result["n_units"] == 1200


def test_fit_singular_gives_nan():
    table = planted_table().filter(pl.col("margin") < 0)  # nobody wins
    result = ig.fit(table, "y", 0.1, [[2012]])
    assert np.isnan(result["b"][0])
    assert np.isnan(result["se"][0])


def test_ri_draws_centre_on_zero_and_give_p():
    table = planted_table(2.0)
    draws = ig.sign_draws(ig.n_races(table), draws=100)
    b_draws = ig.ri_draws(table, "y", 0.1, [[2012]], draws, (1.0,))
    assert b_draws.shape == (100,)
    assert np.all(np.isfinite(b_draws))
    assert abs(b_draws.mean()) < 0.5
    observed = ig.fit(table, "y", 0.1, [[2012]])["b"][0]
    assert ig.ri_p(observed, b_draws) == pytest.approx(1 / 101)
    assert np.isnan(ig.ri_p(float("nan"), b_draws))


# --- Done when 4: counts


def test_min_cycle_races_ignores_2004():
    panel = make_panel("none", races={2004: 10, 2008: 40, 2012: 50, 2016: 60, 2020: 70})
    table = ig.prepare(panel)
    counts = ig.counts_at(table, 0.1)
    assert counts["races_h"]["e2004"] == 10
    assert counts["min_cycle_races_h"] == 40
    assert counts["rows_h"]["e2008"] == 80
    assert counts["eligible_rows_h"]["e2008"] == 80
    assert counts["ties_h"]["e2008"] == 0


def test_counts_include_ties_and_only_eligible_rows():
    panel = make_panel("none", races=20)
    panel = panel.with_columns(
        pl.when((pl.col("election") == 2008) & (pl.col("cd_ibge") == "1500000"))
        .then(0.0)
        .otherwise(pl.col("margin"))
        .alias("margin"),
        pl.when((pl.col("election") == 2012) & (pl.col("cd_ibge") == "1500001"))
        .then(False)
        .otherwise(pl.col("finalist_eligible"))
        .alias("finalist_eligible"),
    )
    counts = ig.counts_at(ig.prepare(panel), 0.1)
    assert counts["ties_h"]["e2008"] == 2
    assert counts["eligible_rows_h"]["e2012"] == counts["rows_h"]["e2012"] - 2


# --- Done when 5: power


def test_mde_is_3_083_times_the_sd_of_the_draws():
    panel = make_panel("none", races=60)
    table = ig.prepare(panel)
    draws = small_draws(panel, 100)
    power = ig.power_at(table, draws, 0.1)
    b_draws = ig.ri_draws(
        table, ig.STAND_IN, 0.1, [list(ig.PRE), list(ig.POST)], draws, (-1.0, 1.0)
    )
    sd = float(np.std(b_draws, ddof=1))
    assert power["sd_h1"] == pytest.approx(sd)
    assert power["mde_h1"] == pytest.approx(3.083 * sd)
    assert 0.0 < power["mean_stand_in"] < 1.0


# --- Done when 6 and 7: what is read


def test_read_columns_hold_no_outcome():
    for column in ig.READ_COLUMNS:
        assert not column.endswith("_next"), column
        assert not column.startswith(FORBIDDEN), column
    assert "party_next" not in ig.READ_COLUMNS
    assert len(ig.READ_COLUMNS) == len(set(ig.READ_COLUMNS)) == 14


def test_load_panel_restricts_before_anything_else():
    full = make_panel("none", races=6)
    half = frozenset(f"15{i:05d}" for i in range(3))
    calls = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        calls.append((name, columns))
        year = int(name.removeprefix("panel_"))
        return full.filter(pl.col("election") == year).select(columns)

    panel = ig.load_panel(read, half)
    assert [c[0] for c in calls] == [f"panel_{e}" for e in ig.ELECTIONS]
    assert all(c[1] == ig.READ_COLUMNS for c in calls)
    assert set(panel["cd_ibge"].to_list()) == set(half)
    assert panel.height == 5 * 3 * 2
    assert ig.n_races(panel) == 15


# --- Done when 8: results.json


def test_results_carry_every_kill_rule_key_and_parse_as_json(tmp_path):
    panel = make_panel("none", races=60)
    results = ig.build_results(panel, small_draws(panel, 100))
    summary = ig.summarize(results)
    from terrain.explore import write_results

    write_results(tmp_path, summary, results)

    def refuse(token: str):
        raise AssertionError(f"non-standard JSON constant {token}")

    parsed = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8"), parse_constant=refuse
    )
    for field in (*ig.RULE_FIELDS, "estimates.finite"):
        node = parsed
        for part in field.split("."):
            node = node[part]
        assert node is not None
    assert parsed["window"]["found"] == 1
    assert isinstance(parsed["estimates"]["finite"], bool)
    assert parsed["placebo"]["lag_abs"] == pytest.approx(abs(parsed["placebo"]["lag"]["b"]))
    assert set(parsed["counts"]["races_h"]) == {f"e{e}" for e in ig.ELECTIONS}
    assert set(parsed["placebo"]["by_election"]["e2004"]) == {"b", "se"}
    assert "descriptive" in parsed
    assert "stand-in" in summary
    assert "nothing on the exploration half is a finding" in summary.lower()


def test_non_finite_numbers_become_null_and_finite_false():
    # A single-election panel cannot fit the 2008-2020 groups: the k-fields must raise.
    panel = make_panel("none", races=60).filter(pl.col("election") == 2012)
    with pytest.raises(ig.GateError):
        ig.build_results(panel, small_draws(panel, 20))


def test_clean_turns_nan_into_null():
    assert ig._clean({"a": float("nan"), "b": np.float64(1.5), "c": np.int64(3)}) == {
        "a": None,
        "b": 1.5,
        "c": 3,
    }
    assert ig._all_finite({"a": 1.0, "b": [2.0]})
    assert not ig._all_finite({"a": float("inf")})
