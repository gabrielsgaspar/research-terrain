import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.strongholds import displacement, exposure, kernel_g

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("effects", REPO / "explore" / "0001_effects.py")
ef = importlib.util.module_from_spec(SPEC)
sys.modules["effects"] = ef
SPEC.loader.exec_module(ef)
pw = ef.pw
pb = ef.pb

MUNI = "1100001"
UE = "10"
CELLS = [(4000, 9000), (4001, 9000), (4002, 9000)]
DISTANCES = [[1.0, 3.0, 6.0], [2.5, 1.5, 8.0], [4.5, 9.0, 1.0]]
SHARES = {
    1: {"1": 0.6, "2": 0.1, "3": 0.2, "4": 0.05},
    2: {"1": 0.2, "2": 0.5, "4": 0.3},
    3: {"2": 0.1, "3": 0.7, "4": 0.1},
}
PAIRS = pl.DataFrame(
    {
        "cd_ibge": [MUNI, MUNI],
        "sg_ue": [UE, UE],
        "cd_eleicao": [1, 1],
        "w": ["1", "3"],
        "l": ["2", "4"],
    }
)


# --- Outcome years and windows


def outcome(rows):
    return pl.DataFrame(
        rows,
        schema={"nome_1KM": pl.Utf8, "has_data": pl.Boolean, "code_4": pl.UInt16},
        orient="row",
    )


class Tracked(dict):
    """A dict that records the keys read."""

    def __init__(self, *args):
        super().__init__(*args)
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)


def frames_2008():
    code = {2004: 1, 2005: 2, 2006: 3, 2007: 4, 2009: 100, 2010: 200, 2011: 400, 2012: 800}
    by_year = Tracked()
    for year, v in code.items():
        rows = [("a", True, v * 1000 if year < 2008 else v), ("z", True, 0)]
        rows.append(("b", year != 2010, v))  # has_data false in a post year
        if year != 2012:
            rows.append(("c", True, v))  # absent in a post year
        if year != 2005:
            rows.append(("d", True, v))  # absent in a pre year
        rows.append(("e", year != 2006, v))  # has_data false in a pre year
        by_year[year] = outcome(rows)
    by_year[2008] = outcome([("a", True, 7777)])  # the election year is never read
    by_year.read.clear()
    return by_year


def test_outcome_years_skip_the_election_year():
    assert ef.outcome_years(2008) == [2004, 2005, 2006, 2007, 2009, 2010, 2011, 2012]
    assert 2008 not in ef.outcome_years(2008)
    assert ef.outcome_years(2020) == [2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024]
    assert ef.window_years(2008) == {
        "Y4": [2009, 2010, 2011, 2012],
        "Y2": [2009, 2010],
        "Ypre": [2004, 2005, 2006, 2007],
    }
    assert ef.window_years(2020)["Y3"] == [2021, 2022, 2023]
    assert "Y3" not in ef.window_years(2016)


def test_outcome_table_builds_every_window_and_the_drop_rules():
    by_year = frames_2008()
    table, dropped = ef.outcome_table(by_year, 2008)
    assert 2008 not in by_year.read
    assert by_year.read == set(ef.outcome_years(2008))
    assert dropped == {"post_incomplete": 2, "pre_incomplete": 2}
    assert table.columns == ["nome_1KM", "Y4", "Y2", "Ypre", "dY"]
    rows = {r["nome_1KM"]: r for r in table.iter_rows(named=True)}
    # b (post has_data false) and c (post year absent) are dropped from everything.
    assert set(rows) == {"a", "d", "e", "z"}
    assert rows["a"]["Y4"] == pytest.approx(0.15)  # (100+200+400+800) / 10,000
    assert rows["a"]["Y2"] == pytest.approx(0.03)
    assert rows["a"]["Ypre"] == pytest.approx(1.0)
    assert rows["a"]["dY"] == pytest.approx(0.15 - 1.0)
    # d (pre year absent) and e (pre has_data false) stay, without Ypre and dY.
    for name in ("d", "e"):
        assert rows[name]["Y4"] == pytest.approx(0.15)
        assert rows[name]["Ypre"] is None
        assert rows[name]["dY"] is None


def test_y3_exists_for_2020_only_and_never_reads_the_election_year():
    by_year = Tracked()
    values = {2021: 100, 2022: 200, 2023: 400, 2024: 5000}
    for year in ef.outcome_years(2020):
        by_year[year] = outcome([("a", True, values.get(year, 1000))])
    by_year[2020] = outcome([("a", True, 7777)])
    table, dropped = ef.outcome_table(by_year, 2020)
    assert by_year.read == set(ef.outcome_years(2020))
    row = table.row(0, named=True)
    assert row["Y3"] == pytest.approx(0.07)  # 2024 is not in Y3
    assert row["Y4"] == pytest.approx(0.57)
    assert row["Y2"] == pytest.approx(0.03)
    assert row["Ypre"] == pytest.approx(0.4)
    assert dropped == {"post_incomplete": 0, "pre_incomplete": 0}
    assert "Y3" not in ef.outcome_table(frames_2008(), 2008)[0].columns


# --- Pair terms


def tables():
    dist = pl.DataFrame(
        [
            {
                "cd_ibge": MUNI,
                "sg_ue": UE,
                "nr_zona": 1,
                "nr_local_votacao": p,
                "x_km": x,
                "y_km": y,
                "d": d,
            }
            for (x, y), row in zip(CELLS, DISTANCES, strict=True)
            for p, d in zip((1, 2, 3), row, strict=True)
        ]
    )
    key = {"cd_ibge": MUNI, "sg_ue": UE, "nr_zona": 1}
    totals = pl.DataFrame(
        [{**key, "nr_local_votacao": p, "cd_eleicao": 1, "vp": 100} for p in (1, 2, 3)]
    )
    shares = pl.DataFrame(
        [
            {
                **key,
                "nr_local_votacao": p,
                "cd_eleicao": 1,
                "sq_candidato": c,
                "v_cp": 100 * s,
                "s_cp": s,
            }
            for p, row in SHARES.items()
            for c, s in row.items()
        ]
    )
    return dist, totals, shares


def test_direct_ring_terms_add_up_and_a_mismatch_stops():
    dist, totals, shares = tables()
    for name in ef.DIRECT_RINGS:
        d = exposure(dist, totals, shares, PAIRS, name, "share")
        assert d["D_i"].abs().max() > 0
        exposed = d.select(*pb.CELL, pl.col("D_i").alias(f"d_{name}")).with_columns(
            n_pairs=pl.lit(2)
        )
        terms = pb.pair_terms(dist, totals, shares, PAIRS, name)
        pb.check_terms(terms, exposed, name)
        broken = terms.with_columns((pl.col("t") + 1e-6).alias("t"))
        with pytest.raises(SystemExit):
            pb.check_terms(broken, exposed, name)


def displacement_inputs():
    cells = pl.DataFrame(
        {
            "cd_ibge": [MUNI] * 5,
            "x_km": [4000, 4010, 4020, 4060, 4040],
            "y_km": [9000, 9000, 9005, 9000, 9030],
        }
    )
    used = pl.DataFrame(
        {
            "cd_ibge": [MUNI, MUNI],
            "sg_ue": [UE, UE],
            "cd_eleicao": [1, 1],
            "w": ["1", "3"],
            "l": ["2", "4"],
            "xw": [4002.0, 4015.0],
            "yw": [9001.0, 9003.0],
            "xl": [4030.0, 4010.0],
            "yl": [9000.0, 9009.0],
        }
    )
    return cells, used


def test_displacement_ring_terms_add_up_and_exp10_equals_the_power_script():
    cells, used = displacement_inputs()
    g = displacement(cells, used)
    ided = pw.with_pair_ids(used, PAIRS)
    own = cells.select("cd_ibge", "x_km", "y_km")
    for name in ("exp10", *ef.DISPLACEMENT_RINGS):
        terms = ef.displacement_terms_for(own, ided, name)
        assert terms.height > 0
        cells_g = g.select(*pb.CELL, pl.col(f"G_{name}").alias(f"g_{name}"))
        assert cells_g[f"g_{name}"].abs().max() > 0
        pw.check_displacement(terms, cells_g, f"g_{name}")
        broken = terms.with_columns(
            pl.when(pl.col("pair_id") == 0)
            .then(pl.col("t") + 1e-6)
            .otherwise(pl.col("t"))
            .alias("t")
        )
        with pytest.raises(SystemExit):
            pw.check_displacement(broken, cells_g, f"g_{name}")
    assert ef.displacement_terms_for(own, ided, "exp10").equals(pw.displacement_terms(own, ided))


# --- Statistics and verdicts


def test_p1_on_a_known_array():
    draws = np.array([-3.0, -1.0, 0.0, 1.0, 2.0, 5.0])
    assert ef.p1_lower(-1.0, draws) == pytest.approx((1 + 2) / (1 + 6))
    assert ef.p1_lower(-10.0, draws) == pytest.approx(1 / 7)
    assert ef.p1_lower(10.0, draws) == pytest.approx(1.0)
    assert ef.p1_lower(0.5, np.append(draws, np.nan)) == pytest.approx((1 + 3 + 1) / 8)
    assert ef.p1_lower(None, draws) is None


@pytest.mark.parametrize(
    ("p_direct", "p_disp", "expected"),
    [
        (0.02, 0.04, {"direct": True, "displacement": True}),
        (0.03, 0.04, {"direct": False, "displacement": False}),
        (0.01, 0.30, {"direct": True, "displacement": False}),
        (0.30, 0.01, {"direct": False, "displacement": True}),
        (None, 0.01, {"direct": False, "displacement": True}),
    ],
)
def test_holm_rule(p_direct, p_disp, expected):
    assert ef.holm_nonzero(p_direct, p_disp) == expected


def test_kill_criterion_4_verdicts():
    both = ef.holm_nonzero(0.02, 0.04)
    assert ef.verdict_kc4(both, 0.94, 0.797).startswith("Kill criterion 4 is not met")
    assert "direct and displacement" in ef.verdict_kc4(both, 0.94, 0.797)
    only = ef.holm_nonzero(0.01, 0.30)
    line = ef.verdict_kc4(only, 0.94, 0.797)
    assert line.startswith("Kill criterion 4 is not met") and "direct" in line
    assert "displacement" not in line
    none = ef.holm_nonzero(0.03, 0.04)
    line = ef.verdict_kc4(none, 0.94, 0.797)
    assert "cannot be applied at 80% power on this half (displacement power 0.797)" in line
    assert "the criterion is unchanged" in line
    assert ef.verdict_kc4(none, 0.94, 0.80).startswith("Kill criterion 4 is met")
    assert ef.verdict_kc4(none, 0.85, 0.90).startswith("Kill criterion 4 is met")


def test_kill_criterion_3_verdicts():
    line = ef.verdict_kc3(0.45, -0.01, 0.30, 0.6)
    assert "cannot be applied at 80% power on this half (power 0.45)" in line
    assert "the criterion is unchanged" in line
    assert "p1 0.3" in line and "two-sided p 0.6" in line
    assert ef.verdict_kc3(0.80, -0.01, 0.20, 0.4).startswith("Kill criterion 3 is met")
    assert ef.verdict_kc3(0.9, -0.01, 0.01, 0.02).startswith("Kill criterion 3 is not met")
    assert ef.verdict_kc3(0.9, -0.01, 0.05, 0.1).startswith("Kill criterion 3 is met")
    assert "cannot be evaluated" in ef.verdict_kc3(0.9, None, None, None)


# --- Synthetic estimates


def synthetic_direct(n_munis=300, seed=5, effect=0.1):
    """Two pairs and four cells per municipality; Y = effect * D / 2 + noise."""
    rng = np.random.default_rng(seed)
    cells, terms = [], []
    for m in range(n_munis):
        code = f"{1100000 + m}"
        recentred = np.zeros(4)
        for p in range(2):
            for i in range(4):
                v = rng.normal(0, 0.5)
                terms.append((code, 4000 + i, 9000 + m, 2 * m + p, v))
                recentred[i] += v / 2
        for i in range(4):
            y = effect * recentred[i] + rng.normal(0, 0.1)
            cells.append((code, 4000 + i, 9000 + m, 1.0, y, y / 2))
    sample = pl.DataFrame(cells, schema=["cd_ibge", "x_km", "y_km", "D", "Y4", "Y2"], orient="row")
    frame = pl.DataFrame(terms, schema=["cd_ibge", "x_km", "y_km", "pair_id", "t"], orient="row")
    return sample, frame, 2 * n_munis


def test_synthetic_slope_is_recovered_with_a_small_ri_p():
    sample, terms, n_pairs = synthetic_direct()
    spec = pw.assemble("direct", [pw.make_part(sample, {"beta": terms}, n_pairs, 2008)])
    observed, sims = pw.run_ri({"direct": spec}, draws=300, seed=3)
    rep = ef.report_estimate(spec, observed, sims)
    row = rep["slots"]["Y4"]["beta"]
    assert row["slope"] == pytest.approx(0.1, abs=0.03)
    assert row["ri_p"] < 0.01
    assert row["clustered_se"] > 0
    assert rep["slots"]["Y2"]["beta"]["slope"] == pytest.approx(0.05, abs=0.03)


def test_empty_parts_keep_pair_numbering_and_every_estimate_shares_the_draws():
    sample, terms, n_pairs = synthetic_direct(n_munis=40)
    real = pw.make_part(sample, {"beta": terms}, n_pairs, 2020)
    full = pw.assemble("full", [pw.make_part(sample, {"beta": terms}, n_pairs, 2008), real])
    y3 = pw.assemble("y3", [ef.empty_part(n_pairs, 2008), real])
    assert full.designs["beta"].n_pairs == y3.designs["beta"].n_pairs == 2 * n_pairs
    # The 2020 pairs have the same index in both: offset by the 2008 pairs.
    late = full.designs["beta"].cols >= n_pairs
    assert np.array_equal(
        np.sort(full.designs["beta"].cols[late]), np.sort(y3.designs["beta"].cols)
    )
    assert y3.designs["beta"].y_tilde.size == sample.height
    assert y3.slopes == ["beta"]
    observed, sims = pw.run_ri({"full": full, "y3": y3}, draws=5, seed=9)
    rng = np.random.default_rng(9)
    only = pw.assemble("only", [real])
    for r in range(5):
        signs = rng.integers(0, 2, size=2 * n_pairs).astype(float) * 2.0 - 1.0
        expected = pw.estimates(only, signs[n_pairs:])[("Y4", "beta")]
        assert sims[("y3", "Y4", "beta")][r] == pytest.approx(expected)
        assert sims[("full", "Y4", "beta")][r] == pytest.approx(
            pw.estimates(full, signs)[("Y4", "beta")]
        )


def synthetic_displacement(n_munis=30, seed=11):
    """Twelve cells and two located pairs per municipality; Y4 = 0.05 * G / 2 + noise."""
    rng = np.random.default_rng(seed)
    cells, used = [], []
    for m in range(n_munis):
        code = f"{1200000 + m}"
        north = 9000 + 200 * m
        for i in range(12):
            cells.append((code, 5000 + 7 * (i % 4), north + 9 * (i // 4)))
        for p in range(2):
            xw, yw, xl, yl = rng.uniform(-60, 80, size=4)
            used.append((code, 2 * m + p, 5000 + xw, north + yw, 5000 + xl, north + yl))
    cells = pl.DataFrame(cells, schema=["cd_ibge", "x_km", "y_km"], orient="row")
    used = pl.DataFrame(used, schema=["cd_ibge", "pair_id", "xw", "yw", "xl", "yl"], orient="row")
    g = displacement(cells, used)
    y4 = 0.05 * g["G_exp10"].to_numpy() / 2 + rng.normal(0, 0.1, g.height)
    sample = g.select(*pb.CELL, pl.col("G_exp10").alias("D")).with_columns(
        Y4=pl.Series(y4), Y2=pl.Series(y4 / 2)
    )
    return cells, used, g, sample, 2 * n_munis


def test_exp10_is_decay_10_km_cut_at_50_km():
    far = np.full(5, 1e6)  # the loser's stronghold is far away and contributes nothing
    d = np.array([0.0, 10.0, 50.0, 50.0 + 1e-12, 50.1])
    got = kernel_g("exp10", d, far)
    assert np.array_equal(got[:4], np.exp(-d[:4] / 10.0))  # 50 + 1e-12 counts as 50
    assert got[1] == pytest.approx(np.exp(-1.0))
    assert got[4] == 0.0


def test_displacement_helper_with_exp10_gives_exactly_the_power_estimate():
    cells, used, g, sample, n_pairs = synthetic_displacement()
    helper = ef.displacement_terms_for(cells, used, "exp10")
    power = pw.displacement_terms(cells, used)
    assert helper.equals(power)
    # Some (cell, pair) terms are zero because both strongholds lie beyond 50 km.
    assert 0 < helper.height < 2 * cells.height
    pw.check_displacement(helper, g.select(*pb.CELL, pl.col("G_exp10").alias("g_exp10")))
    specs = {
        name: pw.assemble(name, [pw.make_part(sample, {"beta": terms}, n_pairs, 2008)])
        for name, terms in (("helper", helper), ("power", power))
    }
    observed, sims = pw.run_ri(specs, draws=50, seed=4)
    for w in pw.WINDOWS:
        assert not np.isnan(observed[("power", w, "beta")])
        assert observed[("helper", w, "beta")] == observed[("power", w, "beta")]
        assert np.array_equal(sims[("helper", w, "beta")], sims[("power", w, "beta")])
    # A ring kernel gives another estimate on the same input, so the comparison can fail.
    ring = ef.displacement_terms_for(cells, used, "ring10_20")
    other = pw.assemble("ring", [pw.make_part(sample, {"beta": ring}, n_pairs, 2008)])
    assert (
        pw.estimates(other, np.ones(n_pairs))[("Y4", "beta")] != observed[("power", "Y4", "beta")]
    )


def test_y3_with_empty_2008_2016_parts_equals_2020_alone():
    sample, terms, n_2020 = synthetic_direct(n_munis=40, seed=8)
    earlier = {2008: (3, 7), 2012: (5, 11), 2016: (6, 13)}  # (municipalities, pairs)
    offset = sum(n for _, n in earlier.values())
    real = pw.make_part(sample, {"beta": terms}, n_2020, 2020)
    y3 = pw.assemble("y3", [*(ef.empty_part(n, e) for e, (_, n) in earlier.items()), real])
    alone = pw.assemble("alone", [real])
    assert y3.designs["beta"].n_pairs == offset + n_2020
    assert np.array_equal(y3.designs["beta"].cols, alone.designs["beta"].cols + offset)
    # Another estimate in the same run has cells in every election, as the main ones do.
    full_parts = []
    for e, (munis, n) in earlier.items():
        s, t, _ = synthetic_direct(n_munis=munis, seed=e)
        full_parts.append(pw.make_part(s, {"beta": t}, n, e))
    s, t, _ = synthetic_direct(n_munis=40, seed=9)
    full = pw.assemble("full", [*full_parts, pw.make_part(s, {"beta": t}, n_2020, 2020)])
    draws = 20
    observed, sims = pw.run_ri({"full": full, "y3": y3}, draws=draws, seed=12)
    alone_obs, _ = pw.run_ri({"alone": alone}, draws=1, seed=12)
    rng = np.random.default_rng(12)
    for w in pw.WINDOWS:
        assert not np.isnan(observed[("y3", w, "beta")])
        assert observed[("y3", w, "beta")] == alone_obs[("alone", w, "beta")]
    for r in range(draws):
        signs = rng.integers(0, 2, size=offset + n_2020).astype(float) * 2.0 - 1.0
        got = pw.estimates(alone, signs[offset:])
        full_got = pw.estimates(full, signs)
        for w in pw.WINDOWS:
            assert sims[("y3", w, "beta")][r] == got[(w, "beta")]
            assert sims[("full", w, "beta")][r] == full_got[(w, "beta")]


def test_slots_fill_the_two_windows_from_the_named_outcomes():
    cells = pl.DataFrame(
        {"nome_1KM": ["a", "b", "c"], "cd_ibge": [MUNI] * 3, "x_km": [1, 2, 3], "y_km": [1, 1, 1]}
    ).with_columns(g=pl.lit(0.5))
    outcomes = pl.DataFrame(
        {
            "nome_1KM": ["a", "b", "c"],
            "Y4": [1.0, 2.0, 3.0],
            "Y2": [0.5, 1.0, 1.5],
            "Ypre": [0.1, None, 0.3],
            "dY": [0.9, None, 2.7],
        }
    )
    placebo = ef.slot_sample(cells, outcomes, "g", ef.SLOTS["disp_pre"])
    assert placebo["x_km"].to_list() == [1, 3]
    assert placebo["Y4"].to_list() == [0.1, 0.3]
    assert placebo["Y2"].to_list() == [0.9, 2.7]
    main = ef.slot_sample(cells, outcomes, "g", {"Y4": "Y4", "Y2": "Y2"})
    assert main["Y4"].to_list() == [1.0, 2.0, 3.0]


def test_script_restricts_to_the_exploration_half_and_reads_fixed_years():
    source = (REPO / "explore" / "0001_effects.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
    assert "for y in outcome_years(year)" in source
