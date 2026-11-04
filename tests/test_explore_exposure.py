import importlib.util
import math
from pathlib import Path

import polars as pl
import pytest

from terrain.grid import km_to_lonlat

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0001_exposure_options.py"
SPEC = importlib.util.spec_from_file_location("exposure_options", SCRIPT)
ex = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ex)

X0, Y0 = 4000, 9000  # a cell corner in Albers km; the cell centre is (X0 + 0.5, Y0 + 0.5)


def places_table(rows):
    """rows: (cd_ibge, sg_ue, nr_local_votacao, x_km, y_km), placed in Albers km."""
    lon, lat = km_to_lonlat([r[3] for r in rows], [r[4] for r in rows])
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "sg_ue": [r[1] for r in rows],
            "nr_zona": [1] * len(rows),
            "nr_local_votacao": [r[2] for r in rows],
            "lat": lat.tolist(),
            "long": lon.tolist(),
        }
    )


def votes_table(rows):
    """rows: (cd_ibge, sg_ue, nr_local_votacao, vote_type, sq_candidato, votes)."""
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "sg_ue": [r[1] for r in rows],
            "nr_zona": [1] * len(rows),
            "nr_local_votacao": [r[2] for r in rows],
            "cd_eleicao": [1] * len(rows),
            "vote_type": [r[3] for r in rows],
            "sq_candidato": [r[4] for r in rows],
            "votes": [r[5] for r in rows],
        },
        schema_overrides={"nr_zona": pl.Int64, "nr_local_votacao": pl.Int64},
    )


def pair_table(rows):
    """rows: (cd_ibge, sg_ue, w, l)."""
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "sg_ue": [r[1] for r in rows],
            "cd_eleicao": [1] * len(rows),
            "w": [r[2] for r in rows],
            "l": [r[3] for r in rows],
        }
    )


def cell_table(rows):
    """rows: (cd_ibge, dx): a cell whose centre is dx km east of X0 + 0.5."""
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "x_km": [X0 + r[1] for r in rows],
            "y_km": [Y0] * len(rows),
        },
        schema_overrides={"x_km": pl.Int64, "y_km": pl.Int64},
    )


def run(cells, place_rows, vote_rows, pairs, kernel, measure):
    located = ex.locate_places(places_table(place_rows))
    dist = ex.cell_place_distances(cells, located)
    votes = votes_table(vote_rows)
    return ex.exposure(dist, ex.place_totals(votes), ex.place_shares(votes), pairs, kernel, measure)


# One municipality "A": place 1 at 1 km and place 2 at 3 km from the cell at dx = 0.
PLACES = [("A", "01", 1, X0 + 1.5, Y0 + 0.5), ("A", "01", 2, X0 + 3.5, Y0 + 0.5)]
VOTES = [
    ("A", "01", 1, "candidate", "w", 30),
    ("A", "01", 1, "candidate", "l", 10),
    ("A", "01", 1, "candidate", "x", 50),
    ("A", "01", 1, "legend", None, 10),
    ("A", "01", 2, "candidate", "w", 5),
    ("A", "01", 2, "candidate", "l", 15),
    ("A", "01", 2, "candidate", "x", 70),
    ("A", "01", 2, "legend", None, 10),
]
PAIR = pair_table([("A", "01", "w", "l")])


def test_place_shares_use_candidate_plus_legend_votes_and_drop_empty_places():
    votes = votes_table(
        [
            ("A", "01", 1, "candidate", "w", 30),
            ("A", "01", 1, "legend", None, 70),
            ("A", "01", 2, "candidate", "w", 0),
        ]
    )
    out = ex.place_shares(votes)
    assert out.height == 1
    assert out["s_cp"].to_list() == [0.3]
    assert out["v_cp"].to_list() == [30]


def test_exp2_share_and_votes_match_the_hand_computed_values():
    cells = cell_table([("A", 0)])
    e1, e2 = math.exp(-0.5), math.exp(-1.5)
    share = run(cells, PLACES, VOTES, PAIR, "exp2", "share")
    ew = (e1 * 0.30 + e2 * 0.05) / (e1 + e2)
    el = (e1 * 0.10 + e2 * 0.15) / (e1 + e2)
    assert share["D_i"].to_list() == [pytest.approx(ew - el)]
    assert share["exposed"].to_list() == [True]
    votes = run(cells, PLACES, VOTES, PAIR, "exp2", "votes")
    assert votes["D_i"].to_list() == [pytest.approx((e1 * 30 + e2 * 5) - (e1 * 10 + e2 * 15))]


def test_candidate_without_votes_at_a_reached_place_counts_as_zero_share():
    votes = [r for r in VOTES if not (r[2] == 2 and r[4] == "l")]
    cells = cell_table([("A", 0)])
    e1, e2 = math.exp(-0.5), math.exp(-1.5)
    out = run(cells, PLACES, votes, PAIR, "exp2", "share")
    # place 2 now has V_p = 85, since the other candidate's 15 votes are gone
    expected = (e1 * 0.30 + e2 * 5 / 85) / (e1 + e2) - (e1 * 0.10 + e2 * 0.0) / (e1 + e2)
    assert out["D_i"].to_list() == [pytest.approx(expected)]


def test_reach_by_kernel():
    cells = cell_table([("A", 0), ("A", 2), ("A", 11)])
    place = [("A", "01", 1, X0 + 0.5, Y0 + 0.5 + 0.0)]
    one = [r for r in VOTES if r[2] == 1]
    far = {}
    for kern in ex.KERNELS:
        out = run(cells, place, one, PAIR, kern, "votes")
        far[kern] = set(out["x_km"].to_list())
    # distances: 0 km, 2 km, 11 km
    assert far["ring2"] == {X0, X0 + 2}
    assert far["ring5"] == {X0, X0 + 2}
    assert far["exp2"] == {X0, X0 + 2}
    assert X0 + 11 not in far["exp2"] | far["ring2"] | far["ring5"]


def test_a_cell_3_km_away_is_reached_by_exp2_and_ring5_only_and_12_km_by_none():
    cells = cell_table([("A", 0), ("A", 15)])  # 3 km and 12 km from the one place
    place = [("A", "01", 1, X0 + 3.5, Y0 + 0.5)]
    one = [r for r in VOTES if r[2] == 1]
    reached = {k: set(run(cells, place, one, PAIR, k, "votes")["x_km"]) for k in ex.KERNELS}
    assert reached["exp2"] == {X0}
    assert reached["ring5"] == {X0}
    assert reached["ring2"] == set()


def test_swapping_winner_and_loser_negates_every_contrast():
    cells = cell_table([("A", 0), ("A", 1), ("A", 4)])
    swapped = pair_table([("A", "01", "l", "w")])
    for kern in ex.KERNELS:
        for measure in ex.MEASURES:
            a = run(cells, PLACES, VOTES, PAIR, kern, measure)
            b = run(cells, PLACES, VOTES, swapped, kern, measure)
            assert a.height == b.height > 0
            assert b["D_i"].to_list() == pytest.approx([-v for v in a["D_i"].to_list()])


def test_a_cell_is_never_matched_to_a_place_of_another_municipality():
    cells = cell_table([("A", 0)])
    places = [
        ("A", "01", 1, X0 + 4.5, Y0 + 0.5),  # own municipality, 4 km
        ("B", "02", 1, X0 + 1.5, Y0 + 0.5),  # other municipality, 1 km
    ]
    dist = ex.cell_place_distances(cells, ex.locate_places(places_table(places)))
    assert dist["sg_ue"].to_list() == ["01"]
    assert dist["d"].to_list() == [pytest.approx(4.0, abs=1e-3)]
    only_b = ex.cell_place_distances(cells, ex.locate_places(places_table(places[1:])))
    assert only_b.height == 0


def test_places_without_coordinates_are_left_out():
    table = places_table(PLACES).with_columns(
        pl.when(pl.col("nr_local_votacao") == 2).then(None).otherwise(pl.col("lat")).alias("lat")
    )
    assert ex.locate_places(table)["nr_local_votacao"].to_list() == [1]


def test_close_pairs_keep_close_non_inverted_pairs():
    paired = pl.DataFrame(
        {
            "cd_ibge": ["A", "A", "A"],
            "sg_ue": ["01", "01", "01"],
            "cd_eleicao": [1, 1, 1],
            "elected_sq": ["a", "c", "e"],
            "other_sq": ["b", "d", "f"],
            "margin": [0.005, 0.006, -0.001],
            "inverted": [False, False, True],
        }
    )
    out = ex.close_pairs(paired)
    assert out["w"].to_list() == ["a"]
    assert out["l"].to_list() == ["b"]


def test_report_counts_groups_and_agreement():
    cells = cell_table([("A", 0), ("A", 1), ("A", 4), ("A", 40)]).with_columns(
        pl.Series("pop_2022", [0, 5, 0, 7]),
        pl.Series("share_indigenous_2020", [0.0, 0.5, 0.0, 0.0]),
        pl.Series("share_settlement_2020", [0.0, 0.0, 0.0, 0.0]),
        pl.Series("share_undesignated_2020", [0.0, 0.0, 0.2, 0.0]),
    )
    results = {
        f"{k}_{m}": run(cells, PLACES, VOTES, PAIR, k, m) for k in ex.KERNELS for m in ex.MEASURES
    }
    out = ex.report(cells, results, PAIR, 2020)
    assert out["cells"] == 4
    assert out["municipalities_with_pair"] == 1
    assert out["pairs_per_municipality"] == {"mean": 1.0, "max": 1}
    v = out["variants"]["exp2_share"]
    assert v["reached"] == 3  # the cell at dx = 40 is out of reach
    assert v["exposed"] == 3
    assert v["share_exposed_pop_2022_zero"] == pytest.approx(2 / 3)
    groups = v["mean_abs_D_by_group"]
    assert groups["pop_2022_zero"]["cells"] == 2
    assert groups["pop_2022_positive"]["cells"] == 1
    assert groups["indigenous_above_0"]["cells"] == 1
    assert groups["settlement_above_0"]["cells"] == 0
    assert groups["settlement_above_0"]["mean_abs_D"] is None
    assert set(v["quantiles_D"]) == {"1%", "10%", "50%", "90%", "99%"}
    assert out["agreement"]["exp2_share vs ring2_share"]["cells"] == 3
    assert out["agreement"]["exp2_share vs exp2_votes"]["pearson"] is not None
    assert len(out["variants"]) == 6


def test_summary_states_the_recentring_identity():
    cells = cell_table([("A", 0)]).with_columns(
        pl.Series("pop_2022", [0]),
        pl.Series("share_indigenous_2020", [0.0]),
        pl.Series("share_settlement_2020", [0.0]),
        pl.Series("share_undesignated_2020", [0.0]),
    )
    results = {"exp2_share": run(cells, PLACES, VOTES, PAIR, "exp2", "share")}
    text = ex._summary({"2020": ex.report(cells, results, PAIR, 2020)})
    assert "D_i / 2" in text
    assert "| exp2_share |" in text


def test_script_reuses_the_census():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "spec_from_file_location" in source
    assert "0001_feasibility_census.py" in source
    assert "def within_list_pairs" not in source
    assert "def place_candidate_votes" not in source
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
