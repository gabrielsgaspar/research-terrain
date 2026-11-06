import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.strongholds import KERNELS, exposure

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("placebo", REPO / "explore" / "0001_placebo.py")
pb = importlib.util.module_from_spec(SPEC)
sys.modules["placebo"] = pb  # dataclasses look the module up by name
SPEC.loader.exec_module(pb)

MUNI = "1100001"
UE = "10"
CELLS = [(4000, 9000), (4001, 9000), (4002, 9000)]
# distance (km) from each cell to places 1, 2, 3 of the municipality
DISTANCES = [[1.0, 3.0, 6.0], [2.5, 1.5, 8.0], [4.5, 9.0, 1.0]]
# vote share of candidates 1..4 at places 1..3 (a missing candidate has no row)
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


def swapped(pairs):
    return pairs.rename({"w": "l", "l": "w"}).select(pairs.columns)


def place_key(place):
    return {"cd_ibge": MUNI, "sg_ue": UE, "nr_zona": 1, "nr_local_votacao": place}


def tables():
    dist = pl.DataFrame(
        [
            {
                "cd_ibge": MUNI,
                "x_km": x,
                "y_km": y,
                "sg_ue": UE,
                "nr_zona": 1,
                "nr_local_votacao": p,
                "d": d,
            }
            for (x, y), row in zip(CELLS, DISTANCES, strict=True)
            for p, d in zip((1, 2, 3), row, strict=True)
        ]
    )
    totals = pl.DataFrame([{**place_key(p), "cd_eleicao": 1, "vp": 100} for p in (1, 2, 3)])
    shares = pl.DataFrame(
        [
            {**place_key(p), "cd_eleicao": 1, "sq_candidato": c, "v_cp": 100 * s, "s_cp": s}
            for p, row in SHARES.items()
            for c, s in row.items()
        ]
    )
    return dist, totals, shares


def test_pair_terms_add_up_to_the_exposure_for_every_kernel():
    dist, totals, shares = tables()
    for name in KERNELS:
        terms = pb.pair_terms(dist, totals, shares, PAIRS, name)
        by_cell = terms.group_by(pb.CELL).agg(pl.col("t").sum())
        d = exposure(dist, totals, shares, PAIRS, name, "share")
        joined = d.join(by_cell, on=pb.CELL, how="left").with_columns(pl.col("t").fill_null(0.0))
        assert joined.height >= 1
        assert (joined["t"] - joined["D_i"]).abs().max() < 1e-12
        assert terms["pair_id"].n_unique() == 2 or name != "exp2"
        exposed = pl.DataFrame(
            {
                "cd_ibge": [MUNI] * 3,
                "x_km": [c[0] for c in CELLS],
                "y_km": [c[1] for c in CELLS],
                "n_pairs": [2] * 3,
            }
        ).join(d.select(*pb.CELL, pl.col("D_i").alias(f"d_{name}")), on=pb.CELL, how="left")
        pb.check_terms(terms, exposed, name)


def test_check_terms_stops_on_a_mismatch():
    dist, totals, shares = tables()
    terms = pb.pair_terms(dist, totals, shares, PAIRS, "exp2")
    d = exposure(dist, totals, shares, PAIRS, "exp2", "share")
    exposed = d.select(*pb.CELL, pl.col("D_i").alias("d_exp2")).with_columns(n_pairs=pl.lit(2))
    pb.check_terms(terms, exposed, "exp2")
    broken = terms.with_columns(
        pl.when(pl.col("pair_id") == 0).then(pl.col("t") + 1e-6).otherwise(pl.col("t")).alias("t")
    )
    with pytest.raises(SystemExit):
        pb.check_terms(broken, exposed, "exp2")
    with pytest.raises(SystemExit):
        pb.check_terms(terms.head(len(terms) - 1), exposed, "exp2")


def synthetic_design(y_of_d, n_munis=60, seed=3, by_muni=False):
    """One pair per municipality, four cells each; Y = y_of_d(D, noise) with D = sum(t) / 2.

    With `by_muni`, every cell of a municipality gets y_of_d(mean D of the municipality, m).
    """
    rng = np.random.default_rng(seed)
    cells, terms = [], []
    for m in range(n_munis):
        code = f"{1100000 + m}"
        t = rng.normal(0, 0.5, size=4)
        noise = rng.normal(0, 1, size=4)
        for i in range(4):
            y = y_of_d(t.mean() / 2, m) if by_muni else y_of_d(t[i] / 2, noise[i])
            cells.append((code, 4000 + i, 9000 + m, y))
            terms.append((code, 4000 + i, 9000 + m, m, t[i]))
    sample = pl.DataFrame(cells, schema=["cd_ibge", "x_km", "y_km", "Y"], orient="row")
    term_frame = pl.DataFrame(
        terms, schema=["cd_ibge", "x_km", "y_km", "pair_id", "t"], orient="row"
    )
    return pb.make_design(sample, term_frame, n_munis, 2008)


def test_flipping_every_pair_negates_exposure_and_beta():
    dist, totals, shares = tables()
    plus = exposure(dist, totals, shares, PAIRS, "exp2", "share")
    minus = exposure(dist, totals, shares, swapped(PAIRS), "exp2", "share")
    assert np.allclose(plus["D_i"].to_numpy(), -minus["D_i"].to_numpy())

    design = synthetic_design(lambda d, e: 0.3 * d + 0.1 * e)
    ones = np.ones(design.n_pairs)
    assert np.allclose(pb.exposure_for(design, -ones), -pb.exposure_for(design, ones))
    b = pb.beta(pb.demeaned_exposure(design, ones), design.y_tilde)
    b_flipped = pb.beta(pb.demeaned_exposure(design, -ones), design.y_tilde)
    assert b == pytest.approx(-b_flipped)
    assert b == pytest.approx(0.3, abs=0.1)
    assert pb.ri(design, (2008,), draws=50)["pooled"]["beta"] == pytest.approx(b)


def test_beta_is_zero_when_y_is_constant_within_the_municipality():
    # Y is constant within each municipality but tracks its mean exposure across them, so
    # only the fixed effects make beta 0.
    design = synthetic_design(lambda d, m: 5.0 * d, by_muni=True)
    ones = np.ones(design.n_pairs)
    raw = pb.exposure_for(design, ones)
    y_raw = np.repeat(5.0 * np.bincount(design.group, weights=raw) / 4, 4)
    assert abs(pb.beta(raw - raw.mean(), y_raw - y_raw.mean())) > 1
    assert np.allclose(design.y_tilde, 0.0, atol=1e-9)
    b = pb.beta(pb.demeaned_exposure(design, ones), design.y_tilde)
    assert b == pytest.approx(0.0, abs=1e-9)
    assert pb.ri(design, (2008,), draws=20)["pooled"]["beta"] == pytest.approx(0.0, abs=1e-9)


def test_ri_detects_a_real_effect_and_not_noise():
    # The independent-Y case depends on SEED and on the fixture seed (5): it passes for these.
    effect = pb.ri(synthetic_design(lambda d, e: 0.1 * d + 0.001 * e), (2008,))
    assert effect["pooled"]["p"] < 0.01
    assert effect["2008"]["p"] == effect["pooled"]["p"]
    noise = pb.ri(synthetic_design(lambda d, e: e, seed=5), (2008,))
    assert noise["pooled"]["p"] > 0.05
    lo, hi = noise["pooled"]["q025"], noise["pooled"]["q975"]
    assert lo < 0 < hi


def test_ri_is_reproducible_and_the_clustered_se_is_positive():
    design = synthetic_design(lambda d, e: 0.1 * d + e)
    assert pb.ri(design, (2008,), draws=100) == pb.ri(design, (2008,), draws=100)
    d_tilde = pb.demeaned_exposure(design, np.ones(design.n_pairs))
    assert pb.clustered_se(d_tilde, design.y_tilde, design.muni) > 0


def test_stack_keeps_elections_apart():
    a = synthetic_design(lambda d, e: 0.2 * d + 0.1 * e, n_munis=20, seed=1)
    b = synthetic_design(lambda d, e: 0.2 * d + 0.1 * e, n_munis=20, seed=2)
    b.election[:] = 2012
    both = pb.stack([a, b])
    assert both.n_pairs == 40
    assert both.y_tilde.size == 160
    assert both.group.max() == 39
    out = pb.ri(both, (2008, 2012), draws=30)
    assert out["2008"]["beta"] == pytest.approx(pb.ri(a, (2008,), draws=30)["2008"]["beta"])
    assert out["pooled"]["beta"] is not None


def outcome(rows):
    return pl.DataFrame(
        rows,
        schema={"nome_1KM": pl.Utf8, "has_data": pl.Boolean, "code_4": pl.UInt16},
        orient="row",
    )


def test_a_cell_missing_data_in_a_pre_election_year_is_dropped_and_counted():
    by_year = {
        2004: outcome([("a", True, 1000), ("b", True, 0), ("c", True, 0)]),
        2005: outcome([("a", True, 500), ("b", True, 0), ("c", True, 0)]),
        2006: outcome([("a", True, 0), ("b", False, 0), ("c", True, 0)]),
        2007: outcome([("a", True, 500), ("b", True, 0)]),
        2008: outcome([("a", True, 9999)]),
    }
    y, dropped = pb.pre_election_outcome(by_year, 2008)
    assert y["nome_1KM"].to_list() == ["a"]
    assert y["Y"].to_list() == [pytest.approx(0.2)]
    assert dropped == 2
    with pytest.raises(ValueError):
        pb.pre_election_outcome(by_year, 2012)


def test_script_restricts_to_the_exploration_half():
    source = (REPO / "explore" / "0001_placebo.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
