import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "incumbency_curse_main", REPO / "explore" / "0012_incumbency_main.py"
)
mn = importlib.util.module_from_spec(SPEC)
sys.modules["incumbency_curse_main"] = mn
SPEC.loader.exec_module(mn)

gate = mn.gate
H = mn.H
PRE, POST = list(mn.PRE), list(mn.POST)


def reject_nan(token: str):
    raise ValueError(f"not standard JSON: {token}")


def make_panel(
    tau=None,
    races: int = 150,
    seed: int = 1,
    noise: float = 0.01,
    margin_cap: float = 0.2,
) -> pl.DataFrame:
    """Two rows per race, five elections, outcomes with a planted jump `tau(election, connected)`.

    `party_wins_next` = 0.5 + 0.3 margin + tau x win + noise. Ineligible finalists get the
    poison value 50 in both finalist outcomes, so a fit that uses them shows it.
    """
    tau = tau or (lambda e, c: 0.0)
    rng = np.random.default_rng(seed)
    parts = []
    for e in gate.ELECTIONS:
        m = np.repeat(rng.uniform(0.0005, margin_cap, races), 2)
        sign = np.tile([1, -1], races)
        margin = sign * m
        win = margin > 0
        bench = rng.integers(0, 3, size=2 * races) if e >= 2012 else np.zeros(2 * races, int)
        connected = (bench > 0) if e >= 2012 else np.zeros(2 * races, bool)
        jump = np.array([tau(e, bool(c)) for c in connected])
        eligible = rng.random(2 * races) < 0.8
        index = np.repeat(np.arange(races), 2)
        parts.append(
            pl.DataFrame(
                {
                    "election": np.full(2 * races, e),
                    "cd_ibge": [f"15{i:05d}" for i in index],
                    "uf": ["PA" if i % 2 else "MA" for i in index],
                    "party": [f"P{s}" for s in sign],
                    "margin": margin,
                    "win": win,
                    "fin_female": rng.random(2 * races) < 0.3,
                    "fin_age": np.round(rng.normal(50, 8, 2 * races)),
                    "fin_higher_ed": rng.random(2 * races) < 0.5,
                    "party_held_mayor_lag": rng.random(2 * races) < 0.5,
                    "ln_pop": np.repeat(rng.normal(9, 1, races), 2),
                    "n_mayor_cands": np.full(2 * races, 3),
                    "bench_fed": pl.Series(
                        [int(b) if e >= 2012 else None for b in bench], dtype=pl.Int64
                    ),
                    "finalist_eligible": eligible,
                    "party_wins_next": 0.5
                    + 0.3 * margin
                    + jump * win
                    + rng.normal(0, noise, 2 * races),
                    "party_runs_next": 0.4 + 0.2 * margin + rng.normal(0, noise, 2 * races),
                    "finalist_wins_next": np.where(
                        eligible, 0.3 + 0.1 * margin + rng.normal(0, noise, 2 * races), 50.0
                    ),
                    "finalist_runs_next": np.where(
                        eligible, 0.6 + 0.1 * margin + rng.normal(0, noise, 2 * races), 50.0
                    ),
                    "party_next": ["F1" if (e == 2020 and i % 5 == 0) else "P" for i in index],
                    "amend_after_total": rng.uniform(1e5, 1e6, 2 * races),
                    "amend_after_pix": rng.uniform(1e4, 1e5, 2 * races),
                    "population_e": np.repeat(rng.integers(5000, 50000, races), 2),
                }
            )
        )
    return pl.concat(parts)


def small_draws(panel: pl.DataFrame, n: int = 200) -> np.ndarray:
    return gate.sign_draws(gate.n_races(panel), draws=n)


def in_kernel(panel: pl.DataFrame, elections, eligible: bool = False) -> int:
    rows = panel.filter(pl.col("election").is_in(list(elections)) & (pl.col("margin").abs() < H))
    if eligible:
        rows = rows.filter(pl.col("finalist_eligible"))
    return rows.height


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    panel = make_panel()
    out = tmp_path_factory.mktemp("main_run")
    summary, results = mn.run(panel, small_draws(panel, 8), out)
    return panel, summary, results, out


# --- Done when 1: planted effects are recovered, a null outcome is not rejected


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_planted_h1_difference_is_recovered(seed):
    panel = make_panel(lambda e, c: -0.15 if e < 2020 else 0.0, races=400, seed=seed)
    table = gate.prepare(panel)
    est = mn.estimate(table, "party_wins_next", [PRE, POST], (-1.0, 1.0))
    assert est["b"] == pytest.approx(0.15, rel=0.10)
    assert est["bs"][0] == pytest.approx(-0.15, rel=0.10)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_planted_s4_difference_is_recovered(seed):
    def tau(e, connected):
        if connected:
            return -0.05 if e < 2020 else 0.05
        return -0.10

    panel = make_panel(tau, races=400, seed=seed)
    table = gate.prepare(panel)
    s4 = mn.s4_estimates(table, small_draws(panel, 5))
    assert s4["diff"]["b"] == pytest.approx(0.10, rel=0.10)
    assert s4["b"]["pre_connected"] == pytest.approx(-0.05, rel=0.10)
    assert s4["b"]["post_connected"] == pytest.approx(0.05, rel=0.10)
    assert s4["b"]["pre_unconnected"] == pytest.approx(-0.10, rel=0.10)
    assert s4["b"]["post_unconnected"] == pytest.approx(-0.10, rel=0.10)
    assert set(s4["cells"]) == {"e2012", "e2016", "e2020"}
    assert s4["cells"]["e2020"]["connected"]["b"] == pytest.approx(0.05, rel=0.10)
    assert s4["cells"]["e2016"]["unconnected"]["b"] == pytest.approx(-0.10, rel=0.10)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_null_outcome_is_not_rejected_with_the_fixed_seed(seed):
    panel = make_panel(races=400, seed=seed, noise=0.05)
    table = gate.prepare(panel).with_columns(
        pl.Series("null_y", np.random.default_rng(seed).normal(0, 0.05, panel.height))
    )
    est = mn.estimate(table, "null_y", [PRE, POST], (-1.0, 1.0), draws=small_draws(panel, 300))
    assert est["ri_p"] > 0.05


# --- Done when 2: S2 and finalist_runs_next use eligible rows only


def test_s2_and_finalist_runs_use_only_eligible_rows(full):
    panel, _, results, _ = full
    assert results["s2"]["diff"]["n_units"] == in_kernel(panel, PRE + POST, eligible=True)
    assert results["s3"]["finalist_runs"]["diff"]["n_units"] == in_kernel(
        panel, PRE + POST, eligible=True
    )
    for e in gate.ELECTIONS:
        n = in_kernel(panel, [e], eligible=True)
        assert results["s2"]["by_election"][f"e{e}"]["n_units"] == n
        assert results["s3"]["finalist_runs"]["by_election"][f"e{e}"]["n_units"] == n
    # the poison value 50 on ineligible rows would show in b and in the mean
    assert abs(results["s2"]["diff"]["b"]) < 1
    assert results["s2"]["by_election"]["e2012"]["mean_y"] < 1
    # the party outcomes keep every row
    assert results["s3"]["party_runs"]["diff"]["n_units"] == in_kernel(panel, PRE + POST)
    assert results["h1"]["n_units"] == in_kernel(panel, PRE + POST)
    assert results["s1"]["by_election"]["e2004"]["n_units"] == in_kernel(panel, [2004])


# --- Done when 3: S5


def s5_panel() -> pl.DataFrame:
    rows = []

    def race(rid, election, bench, population, party="A"):
        for sign, b, pop_party in ((1, bench[0], "A"), (-1, bench[1], "B")):
            rows.append(
                {
                    "election": election,
                    "cd_ibge": f"15{rid:05d}",
                    "race": rid,
                    "party": pop_party,
                    "margin": sign * 0.05,
                    "bench_fed": b,
                    "population_e": population,
                    "amend_after_total": 1000.0,
                    "amend_after_pix": 500.0,
                }
            )

    race(0, 2016, (1, 3), 100)  # kept: B, the larger bench_fed
    race(1, 2016, (2, 2), 100)  # equal: dropped
    race(2, 2020, (None, 2), 100)  # null: dropped
    race(3, 2020, (1, 0), 0)  # kept: A, but a zero population
    race(4, 2012, (1, 3), 100)  # not 2016 or 2020: ignored
    return pl.DataFrame(rows, schema_overrides={"bench_fed": pl.Int64})


def test_s5_drops_equal_bench_keeps_larger_and_counts_zero_population():
    rows, dropped = mn.s5_table(s5_panel())
    assert dropped == 2
    assert sorted(rows["race"].to_list()) == [0, 3]
    kept = {r["race"]: r for r in rows.to_dicts()}
    assert kept[0]["party"] == "B" and kept[0]["bench_fed"] == 3
    assert kept[3]["party"] == "A" and kept[3]["bench_fed"] == 1
    assert kept[0]["y_total"] == pytest.approx(np.log(1 + 1000 / 100))
    assert kept[0]["y_pix"] == pytest.approx(np.log(1 + 500 / 100))
    assert kept[3]["y_total"] is None and kept[3]["y_pix"] is None
    est = mn.estimate(rows, "y_total", [[2020]], (1.0,))
    assert est["n_null_y"] == 1


def test_s5_in_the_full_run(full):
    _, _, results, _ = full
    s5 = results["s5"]
    assert set(s5) >= {
        "e2016_total",
        "e2020_total",
        "e2020_pix",
        "diff_total",
        "n_races_dropped_bench",
        "n_null_y",
    }
    assert s5["n_races_dropped_bench"] > 0
    assert s5["n_null_y"] == 0
    # one row per race: half the rows of the all-rows fit
    assert s5["e2016_total"]["n_units"] > 0


# --- Done when 4: controls_fe matches pyfixest


def test_controls_fe_matches_pyfixest():
    import pyfixest as pf

    panel = make_panel(lambda e, c: -0.15 if e < 2020 else 0.0, races=150, seed=7, noise=0.05)
    table = gate.prepare(panel)
    mine = mn.controls_fe(table)
    rows, n_null = mn._controls_sample(table, H)
    assert n_null == 0
    margin = rows["margin"].to_numpy()
    win = (margin > 0).astype(float)
    election = rows["election"].to_numpy()
    w = gate.kernel_weights(margin, H, "triangular")
    data = {"y": rows["party_wins_next"].to_numpy(), "w": w}
    terms = []
    for e in PRE + POST:
        mask = (election == e).astype(float)
        data[f"m{e}"], data[f"wm{e}"] = mask * margin, mask * win * margin
        terms += [f"m{e}", f"wm{e}"]
    for uf in sorted(set(rows["uf"].to_list())):
        for e in PRE + POST:
            data[f"d_{uf}_{e}"] = (rows["uf"].to_numpy() == uf).astype(float) * (
                election == e
            ).astype(float)
            terms.append(f"d_{uf}_{e}")
    for c in mn.CONTROLS:
        data[c] = rows[c].cast(pl.Float64).to_numpy()
        terms.append(c)
    data["g_pre"] = win * np.isin(election, PRE)
    data["g_post"] = win * np.isin(election, POST)
    terms += ["g_pre", "g_post"]
    frame = pl.DataFrame({**data, "cd_ibge": rows["cd_ibge"].to_list()})
    model = pf.feols(
        "y ~ " + " + ".join(terms) + " - 1",
        data=frame,
        weights="w",
        vcov={"CRV1": "cd_ibge"},
    )
    names = list(model.coef().index)
    vec = np.zeros(len(names))
    vec[names.index("g_pre")], vec[names.index("g_post")] = -1.0, 1.0
    b = float(vec @ model.coef().to_numpy())
    se = float(np.sqrt(vec @ np.asarray(model._vcov) @ vec))
    assert mine["b"] == pytest.approx(b, rel=1e-6)
    assert mine["se"] == pytest.approx(se, rel=1e-6)
    assert mine["b"] == pytest.approx(0.15, rel=0.2)


def test_controls_fe_counts_rows_with_a_null_control():
    panel = make_panel(races=100, seed=3)
    table = gate.prepare(panel)
    base = mn.controls_fe(table)
    cut = table.with_columns(
        pl.when((pl.col("election") == 2016) & (pl.col("cd_ibge").str.ends_with("3")))
        .then(None)
        .otherwise(pl.col("fin_age"))
        .alias("fin_age")
    )
    gone = int(
        cut.filter(
            (pl.col("election") == 2016)
            & pl.col("cd_ibge").str.ends_with("3")
            & (pl.col("margin").abs() < H)
        ).height
    )
    got = mn.controls_fe(cut)
    assert gone > 0
    assert got["n_null_controls"] == gone
    assert got["n_units"] == base["n_units"] - gone
    assert base["n_null_controls"] == 0


# --- Done when 5: the robustness list


def test_robustness_labels_kernels_and_bandwidths():
    assert mn.ROBUSTNESS == (
        ("uniform_5pct", "uniform", 0.05),
        ("uniform_7_5pct", "uniform", 0.075),
        ("uniform_10pct", "uniform", 0.10),
        ("triangular_10pct", "triangular", 0.10),
        ("triangular_20pct", "triangular", 0.20),
    )
    assert (mn.H, mn.KERNEL, mn.SEED, mn.DRAWS) == (0.135, "triangular", 20261122, 2000)


def test_robustness_results_carry_the_six_fits(full):
    panel, _, results, _ = full
    rob = results["robustness"]
    assert list(rob) == [
        "uniform_5pct",
        "uniform_7_5pct",
        "uniform_10pct",
        "triangular_10pct",
        "triangular_20pct",
        "controls_fe",
    ]
    table = gate.prepare(panel)
    for label, kernel, h in mn.ROBUSTNESS:
        est = mn.estimate(table, "party_wins_next", [PRE, POST], (-1.0, 1.0), h=h, kernel=kernel)
        assert rob[label]["b"] == pytest.approx(est["b"])
        assert rob[label]["n_units"] == est["n_units"]
        assert "ri_p" not in rob[label]
    assert rob["uniform_5pct"]["n_units"] < rob["uniform_10pct"]["n_units"]
    assert rob["controls_fe"]["n_null_controls"] == 0


def test_federation_rows_are_counted(full):
    panel, _, results, _ = full
    expected = panel.filter(
        (pl.col("election") == 2020) & (pl.col("margin").abs() < H) & (pl.col("party_next") == "F1")
    ).height
    assert expected > 0
    assert results["counts"]["federation_rows_2020"] == expected


# --- Done when 6: null Y rows leave only that fit


def test_null_y_rows_leave_only_their_fit_and_are_counted(full):
    panel, _, base, _ = full
    cut = panel.with_columns(
        pl.when((pl.col("election") == 2016) & (pl.col("cd_ibge").str.ends_with("0")))
        .then(None)
        .otherwise(pl.col("party_wins_next"))
        .alias("party_wins_next")
    )
    gone = cut.filter(
        (pl.col("election") == 2016)
        & pl.col("cd_ibge").str.ends_with("0")
        & (pl.col("margin").abs() < H)
    ).height
    assert gone > 0
    _, results = mn.build_results(cut, small_draws(cut, 3))
    assert results["h1"]["n_null_y"] == gone
    assert results["h1"]["n_units"] == base["h1"]["n_units"] - gone
    assert results["s1"]["by_election"]["e2016"]["n_null_y"] == gone
    assert results["s1"]["by_election"]["e2012"]["n_null_y"] == 0
    # other outcomes keep those rows
    assert (
        results["s3"]["party_runs"]["diff"]["n_units"]
        == base["s3"]["party_runs"]["diff"]["n_units"]
    )
    assert results["s3"]["party_runs"]["diff"]["n_null_y"] == 0
    assert results["s2"]["diff"]["n_units"] == base["s2"]["diff"]["n_units"]


# --- Done when 7: rows outside the exploration half are dropped before estimation


def test_rows_outside_the_half_are_dropped_on_reading():
    panel = make_panel(races=60)
    half = frozenset(f"15{i:05d}" for i in range(0, 40))
    asked = []

    def read(name, columns):
        asked.append((name, list(columns)))
        election = int(name.split("_")[1])
        return panel.filter(pl.col("election") == election).select(columns)

    loaded = mn.load(read, half)
    assert set(loaded["cd_ibge"].unique().to_list()) <= half
    assert loaded.height == 5 * 2 * 40
    assert [name for name, _ in asked] == [f"panel_{e}" for e in gate.ELECTIONS]
    assert all(cols == mn.MAIN_COLUMNS for _, cols in asked)
    # the columns of the gate, plus the outcomes, the money and the population
    assert set(gate.READ_COLUMNS) <= set(mn.MAIN_COLUMNS)
    assert {"party_wins_next", "amend_after_total", "amend_after_pix", "population_e"} <= set(
        mn.MAIN_COLUMNS
    )


# --- Done when 8 and 9: figures and results.json


def test_five_figures_are_written_and_counted(full):
    _, _, results, out = full
    assert results["figures"]["count"] == 5
    for name in mn.FIGURES:
        path = out / "figures" / name
        assert path.exists()
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert path.stat().st_size < 400_000
    assert sorted(p.name for p in (out / "figures").iterdir()) == sorted(mn.FIGURES)


def test_results_json_is_standard_json_with_estimates_finite(full, tmp_path):
    _, summary, results, _ = full
    mn.write_results(tmp_path, summary, results)
    parsed = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8"), parse_constant=reject_nan
    )
    assert parsed["estimates"]["finite"] is True
    assert parsed["design"] == {"h": 0.135, "kernel": "triangular", "seed": 20261122, "draws": 8}
    for key in ("b_pre", "b_post", "n_units", "n_races", "n_null_y"):
        assert key in parsed["h1"]
    for key in ("b", "se", "ci_low", "ci_high", "p_cluster", "ri_p"):
        assert key in parsed["h1"]["diff"]
    assert set(parsed["s4"]["b"]) == set(mn.S4_GROUPS)
    assert "e2004" in parsed["s2"]["by_election"]
    assert "pooled_2004_2012" in parsed["s1"]
    assert parsed["figures"]["count"] == 5
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    for needle in ("positive and its RI p is below 0.05", "figures/binned_party_wins.png"):
        assert needle in text
    assert "nothing on the exploration half is a finding" in text.lower()


def test_a_non_finite_number_becomes_null_and_finite_is_false(tmp_path):
    panel = make_panel(races=60).with_columns(
        pl.when(pl.col("election") == 2004)
        .then(None)
        .otherwise(pl.col("party_wins_next"))
        .cast(pl.Float64)
        .alias("party_wins_next")
    )
    summary, results = mn.run(panel, small_draws(panel, 3), tmp_path)
    assert results["estimates"]["finite"] is False
    assert results["s1"]["by_election"]["e2004"]["b"] is None
    mn.write_results(tmp_path, summary, results)
    parsed = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8"), parse_constant=reject_nan
    )
    assert parsed["s1"]["by_election"]["e2004"]["b"] is None
    assert parsed["estimates"]["finite"] is False


def test_the_difference_uses_one_fit_covariance():
    panel = make_panel(lambda e, c: -0.15 if e < 2020 else 0.0, races=150, seed=2, noise=0.05)
    table = gate.prepare(panel)
    one = gate.fit(table, "party_wins_next", H, [PRE, POST])
    est = mn.estimate(table, "party_wins_next", [PRE, POST], (-1.0, 1.0))
    var = one["cov"][0, 0] + one["cov"][1, 1] - 2 * one["cov"][0, 1]
    assert est["se"] == pytest.approx(np.sqrt(var))
    assert est["b"] == pytest.approx(one["b"][1] - one["b"][0])
    assert est["ci_high"] - est["b"] == pytest.approx(1.96 * est["se"])
