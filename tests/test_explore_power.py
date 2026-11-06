import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.strongholds import displacement, exposure

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("power", REPO / "explore" / "0001_power.py")
pw = importlib.util.module_from_spec(SPEC)
sys.modules["power"] = pw
SPEC.loader.exec_module(pw)
pb = pw.pb

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


def place_key(place):
    return {"cd_ibge": MUNI, "sg_ue": UE, "nr_zona": 1, "nr_local_votacao": place}


def tables():
    dist = pl.DataFrame(
        [
            {**place_key(p), "x_km": x, "y_km": y, "d": d}
            for (x, y), row in zip(CELLS, DISTANCES, strict=True)
            for p, d in zip((1, 2, 3), row, strict=True)
        ]
    ).select("cd_ibge", "x_km", "y_km", "sg_ue", "nr_zona", "nr_local_votacao", "d")
    totals = pl.DataFrame([{**place_key(p), "cd_eleicao": 1, "vp": 100} for p in (1, 2, 3)])
    shares = pl.DataFrame(
        [
            {**place_key(p), "cd_eleicao": 1, "sq_candidato": c, "v_cp": 100 * s, "s_cp": s}
            for p, row in SHARES.items()
            for c, s in row.items()
        ]
    )
    return dist, totals, shares


def cand_distances(rows):
    """rows: (candidate, dist_indigenous_km, dist_settlement_km)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "sg_ue": [UE] * len(rows),
            "sq_candidato": [r[0] for r in rows],
            "dist_indigenous_km": [r[1] for r in rows],
            "dist_settlement_km": [r[2] for r in rows],
        },
        schema_overrides={"dist_indigenous_km": pl.Float64, "dist_settlement_km": pl.Float64},
    )


# Candidates 1..4: indigenous only, settlement only, both, no distances.
CAND = cand_distances([("1", 1.0, 9.0), ("2", 9.0, 1.0), ("3", 1.0, 1.0), ("4", None, None)])


def test_components_add_up_to_the_exposure_and_flips_are_per_pair():
    dist, totals, shares = tables()
    side = pw.side_terms(dist, totals, shares, PAIRS)
    ptypes = pw.pair_types(PAIRS, CAND, 5)
    assert ptypes["type_w"].to_list() == ["indigenous", "both"]
    assert ptypes["type_l"].to_list() == ["settlement", "untyped"]
    comps = pw.components(side, ptypes)
    assert set(comps) == set(pw.TYPES)

    d = exposure(dist, totals, shares, PAIRS, "exp2", "share")
    exposed = d.select(*pb.CELL, pl.col("D_i").alias("d_exp2")).with_columns(n_pairs=pl.lit(2))
    pw.check_components(comps, exposed)  # Sum over types equals D_i
    with pytest.raises(SystemExit):
        pw.check_components({**comps, "neither": comps["indigenous"]}, exposed)

    sample = d.select(*pb.CELL, pl.lit(1.0).alias("Y4"), pl.lit(1.0).alias("Y2"))
    part = pw.make_part(sample, comps, 2, 2008)
    ones = np.ones(2)
    flip0 = np.array([-1.0, 1.0])
    for name, design in part.designs.items():
        base = pb.exposure_for(design, ones)
        flipped = pb.exposure_for(design, flip0)
        own = comps[name].filter(pl.col("pair_id") == 0)
        contribution = np.zeros(len(CELLS))
        for row in own.iter_rows(named=True):
            contribution[CELLS.index((row["x_km"], row["y_km"]))] += row["t"] / 2
        assert np.allclose(flipped - base, -2 * contribution)
    total = sum(pb.exposure_for(p, flip0) for p in part.designs.values())
    assert np.allclose(total * 2, d["D_i"].to_numpy() - 2 * _pair_term(comps, 0))


def _pair_term(comps, pair):
    out = np.zeros(len(CELLS))
    for frame in comps.values():
        for row in frame.filter(pl.col("pair_id") == pair).iter_rows(named=True):
            out[CELLS.index((row["x_km"], row["y_km"]))] += row["t"]
    return out


@pytest.mark.parametrize("b", [5, 2])
def test_five_types_and_the_band_boundary(b):
    near, far = b - 1.0, b + 1.0
    table = cand_distances(
        [
            ("a", near, far),
            ("b", far, near),
            ("c", near, near),
            ("d", far, far),
            ("e", None, near),
            ("f", b + 1e-12, far),
            ("g", far, b + 1e-12),
            ("h", b + 1e-12, b + 1e-12),
        ]
    )
    typed = table.with_columns(
        pw.candidate_type(pl.col("dist_indigenous_km"), pl.col("dist_settlement_km"), b).alias("t")
    )
    assert typed["t"].to_list() == [
        "indigenous",
        "settlement",
        "both",
        "neither",
        "untyped",
        "indigenous",
        "settlement",
        "both",
    ]


def test_type_counts_split_winners_and_losers():
    counts = pw.type_counts(pw.pair_types(PAIRS, CAND, 5))
    assert counts["indigenous"] == {"winners": 1, "losers": 0, "total": 1}
    assert counts["untyped"] == {"winners": 0, "losers": 1, "total": 1}
    pooled = pw.pool_type_counts({"2008": counts, "2012": counts})
    assert pooled["both"]["total"] == 2


def displacement_inputs():
    cells = pl.DataFrame(
        {
            "cd_ibge": [MUNI] * 4,
            "x_km": [4000, 4010, 4020, 4060],
            "y_km": [9000, 9000, 9005, 9000],
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


def test_displacement_terms_add_up_to_g_exp10_and_a_mismatch_stops():
    cells, used = displacement_inputs()
    g = displacement(cells, used).select(*pb.CELL, "G_exp10")
    assert g["G_exp10"].abs().max() > 0
    ided = pw.with_pair_ids(used, PAIRS)
    assert ided["pair_id"].to_list() == [0, 1]
    terms = pw.displacement_terms(cells, ided)
    assert (terms["t"] != 0).all()
    cells_g = g.rename({"G_exp10": "g_exp10"})
    pw.check_displacement(terms, cells_g)
    broken = terms.with_columns(
        pl.when(pl.col("pair_id") == 0).then(pl.col("t") + 1e-6).otherwise(pl.col("t")).alias("t")
    )
    with pytest.raises(SystemExit):
        pw.check_displacement(broken, cells_g)
    with pytest.raises(SystemExit):
        pw.check_displacement(terms.head(len(terms) - 1), cells_g)


def synthetic_split(n_munis=150, seed=11, effect=0.1, window_noise=0.5):
    """Two pairs and four cells per municipality; Y = effect * D^indigenous / 2 + noise."""
    rng = np.random.default_rng(seed)
    cells, terms = [], {t: [] for t in pw.TYPES}
    for m in range(n_munis):
        code = f"{1100000 + m}"
        recentred = np.zeros(4)
        for t in pw.TYPES:
            for p in range(2):
                for i in range(4):
                    v = rng.normal(0, 0.5)
                    terms[t].append((code, 4000 + i, 9000 + m, 2 * m + p, v))
                    if t == "indigenous":
                        recentred[i] += v / 2
        for i in range(4):
            y = effect * recentred[i] + rng.normal(0, window_noise)
            cells.append((code, 4000 + i, 9000 + m, y, y / 2 + rng.normal(0, 0.1)))
    schema = ["cd_ibge", "x_km", "y_km", "Y4", "Y2"]
    sample = pl.DataFrame(cells, schema=schema, orient="row")
    comp_terms = {
        t: pl.DataFrame(rows, schema=["cd_ibge", "x_km", "y_km", "pair_id", "t"], orient="row")
        for t, rows in terms.items()
    }
    return pw.assemble("split5", [pw.make_part(sample, comp_terms, 2 * n_munis, 2008)])


def test_joint_regression_recovers_the_matching_component():
    spec = synthetic_split()
    assert spec.slopes == [*pw.TYPES, "delta"]
    out = pw.estimates(spec, np.ones(spec.designs["indigenous"].n_pairs))
    assert out[("Y4", "indigenous")] == pytest.approx(0.1, abs=0.06)
    for other in ("settlement", "both", "neither", "untyped"):
        assert out[("Y4", other)] == pytest.approx(0.0, abs=0.06)
    assert out[("Y4", "delta")] == pytest.approx(
        out[("Y4", "indigenous")] - out[("Y4", "settlement")]
    )
    observed, sims = pw.run_ri({"split5": spec}, draws=60, seed=1)
    assert sims[("split5", "Y4", "indigenous")].shape == (60,)
    assert not np.isnan(sims[("split5", "Y2", "delta")]).any()
    again = pw.run_ri({"split5": spec}, draws=60, seed=1)[1]
    assert np.array_equal(sims[("split5", "Y4", "delta")], again[("split5", "Y4", "delta")])
    rep = pw.report_spec(spec, observed, sims, clustered=True)
    row = rep["windows"]["Y4"]["indigenous"]
    assert row["mde_sd"] == pytest.approx(2.8 * row["sd_ri"])
    assert "mde1_sd" in rep["windows"]["Y4"]["delta"]


def test_a_component_without_variance_is_dropped():
    spec = synthetic_split(n_munis=20)
    part_terms = {
        t: pl.DataFrame(
            schema={
                "cd_ibge": pl.Utf8,
                "x_km": pl.Int64,
                "y_km": pl.Int64,
                "pair_id": pl.Int64,
                "t": pl.Float64,
            }
        )
        for t in pw.TYPES
    }
    sample = pl.DataFrame(
        {
            "cd_ibge": ["a", "a"],
            "x_km": [1, 2],
            "y_km": [1, 1],
            "Y4": [1.0, 2.0],
            "Y2": [1.0, 2.0],
        }
    )
    empty = pw.assemble("split5", [pw.make_part(sample, part_terms, 0, 2008)])
    assert empty.kept == []
    assert empty.slopes == []
    assert pw.estimates(empty, np.ones(0)) == {}
    assert spec.slopes  # the full one still reports


def test_mde_statistics_on_a_known_array():
    draws = np.linspace(-1.0, 1.0, 1001)
    s = pw.mde_stats(draws)
    sd = float(np.std(draws, ddof=1))
    assert s["sd_ri"] == pytest.approx(sd)
    assert s["mde_sd"] == pytest.approx(2.8 * sd)
    assert s["mde_q_pos"] == pytest.approx(np.quantile(draws, 0.975) - np.quantile(draws, 0.20))
    assert s["mde_q_neg"] == pytest.approx(np.quantile(draws, 0.80) - np.quantile(draws, 0.025))
    assert "mde1_sd" not in s
    one = pw.mde_stats(np.append(draws, np.nan), one_sided=True)
    assert one["mde1_sd"] == pytest.approx(2.487 * sd, rel=1e-3)
    assert one["mde1_q"] == pytest.approx(
        np.quantile(draws, 0.80) - np.quantile(draws, 0.05), rel=1e-3
    )
    assert pw.mde_stats(np.array([np.nan]))["mde_sd"] is None


def outcome(rows):
    return pl.DataFrame(
        rows,
        schema={"nome_1KM": pl.Utf8, "has_data": pl.Boolean, "code_4": pl.UInt16},
        orient="row",
    )


def test_outcome_years_and_the_two_year_window():
    assert pw.outcome_years(2008) == [2004, 2005, 2006, 2007]
    assert pw.outcome_years(2020) == [2016, 2017, 2018, 2019]
    by_year = {
        2004: outcome([("a", True, 9000), ("b", True, 0)]),
        2005: outcome([("a", True, 9000), ("b", True, 0)]),
        2006: outcome([("a", True, 1000), ("b", True, 0)]),
        2007: outcome([("a", True, 500), ("b", False, 0)]),
        2008: outcome([("a", True, 7777)]),  # the election year is never read
    }
    table, dropped = pw.windows(by_year, 2008)
    assert dropped == 1
    row = table.row(0, named=True)
    assert row["nome_1KM"] == "a"
    assert row["Y2"] == pytest.approx(0.15)
    assert row["Y4"] == pytest.approx(1.95)
    del by_year[2008]
    assert pw.windows(by_year, 2008)[0].equals(table)


def test_percentage_effect():
    assert pw.pct_effect(0.2, -0.5, 4.0) == pytest.approx(100 * 0.2 * 0.5 / 4.0)
    assert pw.pct_effect(0.2, 0.5, 0.0) is None
    x = np.array([0.1, 0.2, 0.3, 0.4, 1.0])
    y = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    e = pw.effect_size(0.5, x, y)
    assert e["x"]["median"] == pytest.approx(0.3)
    assert e["x"]["mean"] == pytest.approx(0.4)
    assert e["ybar"] == pytest.approx(4.0)
    assert e["pct"]["median"] == pytest.approx(100 * 0.5 * 0.3 / 4.0)
    assert e["pct"]["p90"] == pytest.approx(100 * 0.5 * e["x"]["p90"] / 4.0)
    assert e["ybar_at_p90"] == pytest.approx(10.0)


def test_script_restricts_to_the_exploration_half_and_reads_no_late_years():
    source = (REPO / "explore" / "0001_power.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
    assert "outcome_years(year)" in source
