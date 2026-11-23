import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "incumbency_curse_gate", REPO / "explore" / "0012_incumbency_gate.py"
)
ic = importlib.util.module_from_spec(SPEC)
sys.modules["incumbency_curse_gate"] = ic
SPEC.loader.exec_module(ic)

H = ic.H


def make_panel(
    plant: str = "none",
    races: dict[int, int] | int = 100,
    seed: int = 5,
    margin_cap: float = 0.2,
    bench_all_years: bool = False,
) -> pl.DataFrame:
    """Two rows per race, five elections; both rows of a race share ln_pop and n_mayor_cands.

    `plant`: "female" makes the winner's `fin_female` true and the loser's false at every margin.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for e in ic.ELECTIONS:
        n = races[e] if isinstance(races, dict) else races
        for i in range(n):
            m = float(rng.uniform(0.0005, margin_cap))
            shared = {
                "election": e,
                "cd_ibge": f"15{i:05d}",
                "uf": "PA",
                "ln_pop": float(rng.normal(9, 1)),
                "n_mayor_cands": 3,
            }
            for sign in (1, -1):
                female = (sign > 0) if plant == "female" else bool(rng.integers(0, 2))
                bench = int(rng.integers(0, 3)) if (e >= 2012 or bench_all_years) else None
                rows.append(
                    {
                        **shared,
                        "party": f"P{sign}",
                        "margin": sign * m,
                        "win": sign > 0,
                        "fin_female": female,
                        "fin_age": float(np.round(rng.normal(50, 8))),
                        "fin_higher_ed": bool(rng.integers(0, 2)),
                        "party_held_mayor_lag": bool(rng.integers(0, 2)),
                        "bench_fed": bench,
                        "finalist_eligible": bool(rng.random() < 0.9),
                    }
                )
    return pl.DataFrame(rows, infer_schema_length=None)


def small_draws(panel: pl.DataFrame, n: int = 200) -> np.ndarray:
    return ic.sign_draws(ic.n_races(panel), draws=n)


def planted_table(jump: float = 2.0, seed: int = 1, elections=(2012, 2016)) -> pl.DataFrame:
    """Two rows per race over 200 municipalities per election, y with a planted jump."""
    rng = np.random.default_rng(seed)
    rows = []
    for e in elections:
        for i in range(200):
            m = float(rng.uniform(0.001, 0.2))
            for sign in (1, -1):
                margin = sign * m
                win = margin > 0
                rows.append(
                    {
                        "election": e,
                        "cd_ibge": f"15{i:05d}",
                        "margin": margin,
                        "win": win,
                        "connected": int(rng.integers(0, 2)),
                        "y": 1.0 + 0.5 * margin + jump * win + rng.normal(0, 0.1),
                    }
                )
    return ic.prepare(pl.DataFrame(rows))


# --- Done when 1: the model matches pyfixest


def pyfixest_fit(table: pl.DataFrame, h: float, kernel: str, cell: str, groups):
    import pyfixest as pf

    w = ic.kernel_weights(table["margin"].to_numpy(), h, kernel)
    rows = table.filter(pl.Series(w > 0)).with_columns(pl.Series("w", w[w > 0]))
    margin = rows["margin"].to_numpy()
    win = (margin > 0).astype(float)
    cells = sorted({c for grp in groups for c in grp})
    data: dict[str, np.ndarray] = {"y": rows["y"].to_numpy(), "w": rows["w"].to_numpy()}
    terms = []
    for i, c in enumerate(cells):
        mask = (rows[cell].to_numpy() == c).astype(float)
        data[f"d{i}"], data[f"m{i}"], data[f"wm{i}"] = mask, mask * margin, mask * win * margin
        terms += [f"d{i}", f"m{i}", f"wm{i}"]
    for j, grp in enumerate(groups):
        data[f"g{j}"] = win * np.isin(rows[cell].to_numpy(), list(grp)).astype(float)
        terms.append(f"g{j}")
    frame = pl.DataFrame({**data, "cd_ibge": rows["cd_ibge"].to_list()})
    model = pf.feols(
        "y ~ " + " + ".join(terms) + " - 1",
        data=frame,
        weights="w",
        vcov={"CRV1": "cd_ibge"},
    )
    names = [f"g{j}" for j in range(len(groups))]
    return model.coef()[names].to_numpy(), model.se()[names].to_numpy()


@pytest.mark.parametrize("kernel", ["triangular", "uniform"])
def test_fit_matches_pyfixest_weighted_clustered(kernel):
    table = planted_table(2.0)
    mine = ic.fit(table, "y", H, [[2012, 2016]], kernel)
    b, se = pyfixest_fit(table, H, kernel, "election", [[2012, 2016]])
    assert mine["b"] == pytest.approx(b, rel=1e-6)
    assert mine["se"] == pytest.approx(se, rel=1e-6)


@pytest.mark.parametrize("kernel", ["triangular", "uniform"])
def test_fit_matches_pyfixest_with_another_cell_column(kernel):
    table = planted_table(2.0, seed=3).with_columns(
        (pl.col("election").cast(pl.Utf8) + "_" + pl.col("connected").cast(pl.Utf8)).alias("cx")
    )
    groups = [["2012_0", "2016_0"], ["2012_1", "2016_1"]]
    mine = ic.fit(table, "y", H, groups, kernel, cell="cx")
    b, se = pyfixest_fit(table, H, kernel, "cx", groups)
    assert mine["b"] == pytest.approx(b, rel=1e-6)
    assert mine["se"] == pytest.approx(se, rel=1e-6)
    assert mine["cov"].shape == (2, 2)


# --- Done when 2: the kernel


def test_kernel_weights():
    m = np.array([0.0, 0.0675, -0.0675, 0.134, 0.135, -0.135, 0.2])
    tri = ic.kernel_weights(m, 0.135, "triangular")
    assert tri[:4] == pytest.approx([1.0, 0.5, 0.5, 1 - 0.134 / 0.135])
    assert list(tri[4:]) == [0.0, 0.0, 0.0]
    uni = ic.kernel_weights(m, 0.135, "uniform")
    assert list(uni) == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
    with pytest.raises(ic.GateError):
        ic.kernel_weights(m, 0.135, "gaussian")


# --- Done when 3: the re-flip


def test_reflip_swaps_the_winner_and_keeps_the_weights():
    panel = ic.prepare(make_panel("none", races=10))
    margin = panel["margin"].to_numpy()
    race = panel["race"].to_numpy()
    original_win = panel["win"].to_numpy()
    signs = ic.sign_draws(ic.n_races(panel), draws=1)[0]
    assert (signs < 0).any() and (signs > 0).any()
    flipped, win = ic.flip(margin, race, signs)
    for r in np.unique(race):
        a, b = np.flatnonzero(race == r)
        if signs[r] < 0:
            assert win[a] == original_win[b] and win[b] == original_win[a]
        else:
            assert win[a] == original_win[a] and win[b] == original_win[b]
        assert win[a] != win[b]
    for kernel in ("triangular", "uniform"):
        assert np.array_equal(
            ic.kernel_weights(flipped, H, kernel), ic.kernel_weights(margin, H, kernel)
        )


def test_sign_draws_use_the_fixed_seed():
    assert ic.SEED == 20261122 and ic.DRAWS == 2000 and H == 0.135
    a, b = ic.sign_draws(30, draws=10), ic.sign_draws(30, draws=10)
    assert np.array_equal(a, b)
    assert set(np.unique(a)) == {-1, 1}


# --- Done when 4: a planted jump


@pytest.mark.parametrize("kernel", ["triangular", "uniform"])
def test_fit_recovers_a_planted_jump(kernel):
    result = ic.fit(planted_table(2.0), "y", H, [[2012, 2016]], kernel)
    assert result["b"][0] == pytest.approx(2.0, rel=0.1)
    assert result["n_null_y"] == 0
    assert result["n_races"] <= 400
    assert result["n_units"] == 2 * result["n_races"]


def test_fit_counts_null_y_and_drops_cells_outside_every_group():
    table = planted_table(2.0).with_columns(
        pl.when(pl.col("race") % 10 == 0).then(None).otherwise(pl.col("y")).alias("y")
    )
    full = ic.fit(table, "y", H, [[2012, 2016]])
    assert full["n_null_y"] > 0
    only = ic.fit(table, "y", H, [[2012]])
    assert only["n_units"] < full["n_units"]


def test_ri_draws_centre_on_zero_and_give_p():
    table = planted_table(2.0)
    draws = ic.sign_draws(ic.n_races(table), draws=100)
    b_draws = ic.ri_draws(table, "y", H, [[2012, 2016]], draws, (1.0,))
    assert b_draws.shape == (100,)
    assert np.all(np.isfinite(b_draws))
    observed = ic.fit(table, "y", H, [[2012, 2016]])["b"][0]
    assert ic.ri_p(observed, b_draws) == pytest.approx(1 / 101)
    assert math.isnan(ic.ri_p(float("nan"), b_draws))


# --- Done when 5: balance


def omnibus(panel: pl.DataFrame) -> float:
    table = ic.prepare(panel)
    return ic.balance_at(table, small_draws(panel), H)["omnibus_p"]


def test_balance_flags_a_planted_jump():
    for seed in range(5):
        assert omnibus(make_panel("female", races=60, seed=seed)) < 0.05


def test_balance_without_a_jump_is_not_flagged():
    for seed in (1, 3, 4, 5, 6):
        assert omnibus(make_panel("none", races=60, seed=seed)) >= 0.05


def test_bench_fed_pos_uses_only_2012_to_2020():
    panel = make_panel("none", races=40, bench_all_years=True)
    table = ic.prepare(panel)
    out = ic.balance_at(table, small_draws(panel, 20), H)
    inside = ic.in_kernel(table, H)
    expected = inside.filter(pl.col("election") >= 2012).height
    assert out["covariates"]["bench_fed_pos"]["n_units"] == expected
    cycles = inside.filter(pl.col("election") >= 2008).height
    assert out["covariates"]["fin_female"]["n_units"] == cycles
    assert set(out["covariates"]) == set(ic.BALANCE)


def test_a_null_covariate_leaves_that_covariate_only():
    panel = make_panel("none", races=40).with_columns(
        pl.when(pl.col("cd_ibge") == "1500000")
        .then(None)
        .otherwise(pl.col("fin_age"))
        .alias("fin_age")
    )
    table = ic.prepare(panel)
    out = ic.balance_at(table, small_draws(panel, 20), H)
    assert out["covariates"]["fin_age"]["n_units"] < out["covariates"]["fin_female"]["n_units"]


# --- Done when 6: the placebo rule


@pytest.mark.parametrize(
    ("b", "p", "fail"),
    [(0.06, 0.01, 1), (-0.06, 0.01, 1), (0.04, 0.01, 0), (0.06, 0.2, 0), (0.04, 0.2, 0)],
)
def test_placebo_fail_needs_both(b, p, fail):
    assert ic.placebo_fail(b, p) == fail
    assert isinstance(ic.placebo_fail(b, p), int)


def test_placebo_fail_edges_and_non_finite():
    assert ic.placebo_fail(0.05, 0.01) == 0
    assert ic.placebo_fail(0.06, 0.05) == 0
    with pytest.raises(ic.GateError):
        ic.placebo_fail(float("nan"), 0.01)


# --- Done when 7: power


def test_mde_formula():
    panel = make_panel("none", races=60)
    table = ic.prepare(panel)
    draws = small_draws(panel, 100)
    power = ic.power_at(table, draws, H)
    b_draws = ic.ri_draws(table, ic.STAND_IN, H, [list(ic.PRE), list(ic.POST)], draws, (-1.0, 1.0))
    sd = float(np.std(b_draws[np.isfinite(b_draws)], ddof=1))
    assert power["sd_h1"] == pytest.approx(sd)
    p = power["mean_stand_in"]
    assert 0.0 < p < 1.0
    assert power["var_stand_in"] == pytest.approx(p * (1 - p))
    assert power["scale"] == pytest.approx(math.sqrt(0.25 / power["var_stand_in"]))
    assert power["mde_h1"] == pytest.approx(
        2.80 * power["sd_h1"] * math.sqrt(0.25 / power["var_stand_in"])
    )


# --- Done when 8: counts


def test_min_cycle_races_ignores_2004():
    panel = make_panel(
        "none", races={2004: 10, 2008: 40, 2012: 50, 2016: 60, 2020: 70}, margin_cap=0.1
    )
    counts = ic.counts_at(ic.prepare(panel), H)
    assert counts["races_h"]["e2004"] == 10
    assert counts["min_cycle_races_h"] == 40
    assert counts["rows_h"]["e2008"] == 80
    assert counts["ties_h"]["e2008"] == 0
    assert counts["eligible_rows_h"]["e2008"] <= 80


def test_counts_use_the_triangular_edge_and_count_ties():
    panel = (
        make_panel("none", races=20, margin_cap=0.1)
        .with_columns(
            pl.when((pl.col("election") == 2008) & (pl.col("cd_ibge") == "1500000"))
            .then(0.0)
            .otherwise(pl.col("margin"))
            .alias("margin")
        )
        .with_columns(
            pl.when((pl.col("election") == 2012) & (pl.col("cd_ibge") == "1500001"))
            .then(pl.col("margin").sign() * 0.135)
            .otherwise(pl.col("margin"))
            .alias("margin")
        )
    )
    counts = ic.counts_at(ic.prepare(panel), H)
    assert counts["ties_h"]["e2008"] == 2
    assert counts["races_h"]["e2012"] == 19  # |margin| = h is outside the triangular kernel
    assert ic.counts_at(ic.prepare(panel), H, "uniform")["races_h"]["e2012"] == 20


# --- Done when 9: what is read


def test_read_columns_hold_no_outcome():
    for column in ic.READ_COLUMNS:
        assert not column.endswith("_next"), column
        assert not column.startswith("amend_after"), column
    assert "party_next" not in ic.READ_COLUMNS
    assert len(ic.READ_COLUMNS) == len(set(ic.READ_COLUMNS)) == 14


# --- Done when 10: the exploration half


def test_load_panel_restricts_before_anything_else():
    full = make_panel("none", races=6)
    half = frozenset(f"15{i:05d}" for i in range(3))
    calls = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        calls.append((name, columns))
        year = int(name.removeprefix("panel_"))
        return full.filter(pl.col("election") == year).select(columns)

    panel = ic.load_panel(read, half)
    assert [c[0] for c in calls] == [f"panel_{e}" for e in ic.ELECTIONS]
    assert all(c[1] == ic.READ_COLUMNS for c in calls)
    assert set(panel["cd_ibge"].to_list()) == set(half)
    assert panel.height == 5 * 3 * 2
    assert ic.n_races(panel) == 15


def test_main_restricts_with_the_national_half():
    source = (REPO / "explore" / "0012_incumbency_gate.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source


# --- Done when 11: the S2 sample


def test_s2_sample_uses_only_eligible_rows():
    panel = make_panel("none", races=40)
    results = ic.build_results(panel, small_draws(panel, 50))
    table = ic.prepare(panel)
    eligible = table.filter(pl.col("finalist_eligible"))
    inside = ic.in_kernel(eligible, H)
    s2 = results["s2_sample"]
    for e in ic.ELECTIONS:
        assert s2["counts"]["rows_h"][f"e{e}"] == inside.filter(pl.col("election") == e).height
        assert s2["counts"]["eligible_rows_h"][f"e{e}"] == s2["counts"]["rows_h"][f"e{e}"]
    assert s2["placebo"]["n_units"] == inside.height
    assert "finalist_eligible" not in s2["balance"]["covariates"]
    assert set(s2["balance"]["covariates"]) == set(ic.BALANCE) - {"finalist_eligible"}
    assert (
        s2["window"]["table"]["w10pct"]["units"]
        == eligible.filter(pl.col("margin").abs() <= 0.10 + 1e-12).height
    )
    assert results["placebo"]["n_units"] == ic.in_kernel(table, H).height
    assert results["placebo"]["n_units"] > s2["placebo"]["n_units"]


def test_s2_draws_keep_each_races_sign_column():
    table = ic.prepare(make_panel("none", races=30))
    draws = small_draws(table, 5)
    kept, ids = ic.s2_rows(table)
    assert draws[:, ids].shape[1] == ic.n_races(kept)
    # the kept race with the k-th sorted id is the k-th race of the subset's own numbering
    again = ic.prepare(kept.drop("race"))
    assert np.array_equal(np.unique(again["race"].to_numpy()), np.arange(ids.size))


# --- Done when 12: results.json


def test_results_carry_every_kill_rule_key_and_parse_as_json(tmp_path):
    panel = make_panel("none", races=40)
    results = ic.build_results(panel, small_draws(panel, 50))
    summary = ic.summarize(results)
    from terrain.explore import write_results

    write_results(tmp_path, summary, results)

    def refuse(token: str):
        raise AssertionError(f"non-standard JSON constant {token}")

    parsed = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8"), parse_constant=refuse
    )
    for field in (*ic.RULE_FIELDS, "estimates.finite", "design.h", "design.kernel"):
        assert ic._get(parsed, field) is not None
    assert parsed["design"] == {"h": 0.135, "kernel": "triangular", "seed": 20261122, "draws": 50}
    assert parsed["placebo"]["fail"] in (0, 1)
    assert isinstance(parsed["estimates"]["finite"], bool)
    assert set(parsed["counts"]["races_h"]) == {f"e{e}" for e in ic.ELECTIONS}
    assert set(parsed["placebo"]["by_election"]["e2004"]) == {"b", "se"}
    assert set(parsed["balance"]["covariates"]) == set(ic.BALANCE)
    assert set(parsed["balance"]["covariates"]["fin_age"]) == {
        "b",
        "se",
        "ri_p",
        "n_units",
        "n_races",
    }
    assert set(parsed["window"]["table"]["w10pct"]) == set(ic.WINDOW_FIELDS)
    assert "rule_0008_found" in parsed["window"] and "rule_0008_h_pct" in parsed["window"]
    for key in ("counts", "balance", "placebo", "power", "window"):
        assert key in parsed["s2_sample"]
    assert "stand-in" in summary
    assert "information only (decision 0017)" in summary
    assert "nothing on the exploration half is a finding" in summary.lower()


def test_k_fields_raise_when_they_cannot_be_computed():
    panel = make_panel("none", races=40).filter(pl.col("election") == 2012)
    with pytest.raises(ic.GateError):
        ic.build_results(panel, small_draws(panel, 20))


def test_clean_turns_nan_into_null():
    assert ic._clean({"a": float("nan"), "b": np.float64(1.5), "c": np.int64(3)}) == {
        "a": None,
        "b": 1.5,
        "c": 3,
    }
    assert ic._all_finite({"a": 1.0, "b": [2.0]})
    assert not ic._all_finite({"a": float("inf")})
    assert not ic._all_finite({"a": None})


# --- The functions step s3 reuses


def test_functions_s3_reuses_exist():
    for name in (
        "load_panel",
        "prepare",
        "n_races",
        "sign_draws",
        "flip",
        "kernel_weights",
        "fit",
        "ri_draws",
        "ri_p",
    ):
        assert callable(getattr(ic, name))
    for name in ("H", "SEED", "DRAWS", "ELECTIONS", "READ_COLUMNS"):
        assert hasattr(ic, name)
