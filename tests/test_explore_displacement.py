import importlib.util
import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.grid import km_to_lonlat

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0001_displacement_options.py"
SPEC = importlib.util.spec_from_file_location("displacement_options", SCRIPT)
dp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dp)

X0, Y0 = 4000, 9000  # a cell corner in Albers km; the cell centre is (X0 + 0.5, Y0 + 0.5)
VARIANTS = dp.VARIANTS


def cells_at(dxs, pop=0):
    """Cells whose centres are dx km east of (X0 + 0.5, Y0 + 0.5), in municipality A."""
    return pl.DataFrame(
        {
            "cd_ibge": ["A"] * len(dxs),
            "x_km": [X0 + dx for dx in dxs],
            "y_km": [Y0] * len(dxs),
            "pop_2022": [pop] * len(dxs),
        },
        schema_overrides={"x_km": pl.Int64, "y_km": pl.Int64},
    )


def used_pairs(xw, xl, swap=False):
    """One pair of municipality A, strongholds on the row y = Y0 + 0.5 at x = xw, xl."""
    if swap:
        xw, xl = xl, xw
    return pl.DataFrame(
        {
            "cd_ibge": ["A"],
            "sg_ue": ["01"],
            "cd_eleicao": [1],
            "w": ["w"],
            "l": ["l"],
            "xw": [float(xw)],
            "yw": [Y0 + 0.5],
            "xl": [float(xl)],
            "yl": [Y0 + 0.5],
        }
    )


def test_one_pair_gives_the_hand_computed_value_of_each_variant():
    # the cell centre is at X0 + 0.5; p_w is 15 km away and p_l 30 km away
    out = dp.displacement(cells_at([0]), used_pairs(X0 + 15.5, X0 + 30.5))
    row = out.row(0, named=True)
    assert row["G_ring10_20"] == 1
    assert row["G_ring20_50"] == -1
    assert row["G_exp10"] == pytest.approx(math.exp(-1.5) - math.exp(-3), abs=1e-12)
    assert row["G_nearest"] == 1


def test_a_cell_60_km_from_both_strongholds_has_every_variant_zero():
    out = dp.displacement(cells_at([0]), used_pairs(X0 + 60.5, X0 + 70.5))
    assert [out[f"G_{v}"][0] for v in VARIANTS] == [0, 0, 0, 0]


def test_boundaries_use_the_tolerance():
    d = np.array([10.0, 10.0 + 1e-12, 20.0, 50.0, 50.0 + 1e-12, 50.1])
    far = np.full(d.shape, 90.0)
    assert dp.kernel_g("ring10_20", d, far).tolist() == [0, 0, 1, 0, 0, 0]
    assert dp.kernel_g("ring20_50", d, far).tolist() == [0, 0, 0, 1, 1, 0]


def test_nearest_is_zero_when_equally_far():
    d = np.array([15.0, 15.0, 15.0])
    assert dp.kernel_g("nearest", d, d).tolist() == [0, 0, 0]
    assert dp.kernel_g("nearest", np.array([60.0]), np.array([70.0])).tolist() == [0]
    assert dp.kernel_g("nearest", np.array([70.0]), np.array([20.0])).tolist() == [-1]


def test_unrepresented_leaves_out_populated_and_reached_cells():
    cells = pl.concat(
        [cells_at([0, 1, 2]).with_columns(pl.Series("pop_2022", [0, 5, 0])), cells_at([3])]
    ).with_columns(pl.Series("cd_ibge", ["A", "A", "A", "B"]))
    reached = pl.DataFrame(
        {"cd_ibge": ["A"], "x_km": [X0 + 2], "y_km": [Y0]},
        schema_overrides={"x_km": pl.Int64, "y_km": pl.Int64},
    )
    out = dp.unrepresented(cells, reached, {"A"})
    assert out["x_km"].to_list() == [X0]  # populated (dx 1), reached (dx 2), no pair (B) are out
    assert out.height == 1


def test_swapping_winner_and_loser_negates_every_g():
    cells = cells_at([0, 5, 12, 25, 40])
    a = dp.displacement(cells, used_pairs(X0 + 15.5, X0 + 30.5))
    b = dp.displacement(cells, used_pairs(X0 + 15.5, X0 + 30.5, swap=True))
    for v in VARIANTS:
        assert b[f"G_{v}"].to_list() == pytest.approx([-x for x in a[f"G_{v}"].to_list()])
    assert any(x != 0 for v in VARIANTS for x in a[f"G_{v}"].to_list())


def test_a_municipality_without_a_used_pair_gets_zero():
    cells = cells_at([0]).with_columns(pl.Series("cd_ibge", ["B"]))
    out = dp.displacement(cells, used_pairs(X0 + 15.5, X0 + 30.5))
    assert [out[f"G_{v}"][0] for v in VARIANTS] == [0, 0, 0, 0]


def strong_table(rows):
    """rows: (sg_ue, cand, nr_local_votacao)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "sg_ue": [r[0] for r in rows],
            "sq_candidato": [r[1] for r in rows],
            "cd_ibge": ["A"] * len(rows),
            "nr_zona": [1] * len(rows),
            "nr_local_votacao": [r[2] for r in rows],
        },
        schema_overrides={"nr_zona": pl.Int64, "nr_local_votacao": pl.Int64},
    )


def places_table(rows):
    """rows: (nr_local_votacao, x_km, y_km), with coordinates in Albers km."""
    lon, lat = km_to_lonlat([r[1] for r in rows], [r[2] for r in rows])
    return pl.DataFrame(
        {
            "cd_ibge": ["A"] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "nr_zona": [1] * len(rows),
            "nr_local_votacao": [r[0] for r in rows],
            "lat": lat.tolist(),
            "long": lon.tolist(),
        },
        schema_overrides={"nr_zona": pl.Int64, "nr_local_votacao": pl.Int64},
    )


def raw_pairs(rows):
    """rows: (w, l)."""
    return pl.DataFrame(
        {
            "cd_ibge": ["A"] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "cd_eleicao": [1] * len(rows),
            "w": [r[0] for r in rows],
            "l": [r[1] for r in rows],
        }
    )


def test_a_pair_with_the_same_stronghold_place_is_dropped_and_counted():
    located = dp.locate_places(places_table([(1, X0 + 1.5, Y0 + 0.5), (2, X0 + 20.5, Y0 + 0.5)]))
    strong = strong_table([("01", "a", 1), ("01", "b", 1), ("01", "c", 2), ("01", "d", 1)])
    pairs = raw_pairs([("a", "b"), ("c", "d")])
    used, same, no_coordinates = dp.stronghold_pairs(pairs, strong, located)
    assert same == 1
    assert no_coordinates == 0
    assert used["w"].to_list() == ["c"]
    assert used["xw"].to_list() == [pytest.approx(X0 + 20.5, abs=1e-3)]
    assert used["xl"].to_list() == [pytest.approx(X0 + 1.5, abs=1e-3)]


def test_pairs_without_a_stronghold_or_coordinates_are_dropped_and_counted():
    located = dp.locate_places(places_table([(1, X0 + 1.5, Y0 + 0.5)]))
    strong = strong_table([("01", "a", 1), ("01", "c", 2)])  # c's place 2 has no coordinates
    pairs = raw_pairs([("a", "z"), ("a", "c")])  # z has no stronghold at all
    used, same, no_coordinates = dp.stronghold_pairs(pairs, strong, located)
    assert used.height == 0
    assert same == 0
    assert no_coordinates == 2


def test_report_counts_tenure_and_agreement():
    unrep = cells_at([0, 5, 25]).with_columns(
        pl.Series("share_indigenous_2020", [0.0, 0.0, 0.0]),
        pl.Series("share_settlement_2020", [0.0, 0.5, 0.0]),
        pl.Series("share_undesignated_2020", [0.3, 0.0, 0.0]),
    )
    g = dp.displacement(unrep, used_pairs(X0 + 15.5, X0 + 30.5))
    counts = {
        "pairs_used": 1,
        "dropped_same_place": 0,
        "dropped_no_coordinates": 0,
        "municipalities_with_pair": 1,
        "cells_in_municipalities": 6,
    }
    out = dp.report(unrep, g, counts, 2020)
    assert out["unrepresented_cells"] == 3
    assert out["unrepresented_share_of_cells"] == 0.5
    v = out["variants"]["exp10"]
    assert v["cells_nonzero"] == 3
    assert v["tenure"]["undesignated"]["cells"] == 1
    assert v["tenure"]["settlement"]["cells"] == 1
    assert v["tenure"]["indigenous"]["share"] == 0
    assert set(v["quantiles_G"]) == {"1%", "10%", "50%", "90%", "99%"}
    assert set(out["agreement"]) == {"exp10 vs ring10_20", "exp10 vs ring20_50", "exp10 vs nearest"}
    assert out["agreement"]["exp10 vs nearest"]["cells"] == 3


def test_summary_states_the_recentring_identity():
    unrep = cells_at([0]).with_columns(
        pl.Series("share_indigenous_2020", [0.0]),
        pl.Series("share_settlement_2020", [0.0]),
        pl.Series("share_undesignated_2020", [0.0]),
    )
    g = dp.displacement(unrep, used_pairs(X0 + 15.5, X0 + 30.5))
    counts = {
        "close_pairs": 1,
        "pairs_used": 1,
        "dropped_same_place": 0,
        "dropped_no_coordinates": 0,
        "municipalities_with_pair": 1,
        "cells_in_municipalities": 1,
    }
    text = dp._summary({"2020": dp.report(unrep, g, counts, 2020)})
    assert "G / 2" in text
    assert "| exp10 |" in text


def test_script_calls_the_exploration_helpers():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
