import importlib.util
from pathlib import Path

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "census", REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(census)


def cands(rows):
    """rows: (sq_candidato, votes, elected) in one list of one municipality."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "cd_ibge": ["1500107"] * len(rows),
            "sq_coligacao": ["L1"] * len(rows),
            "sq_candidato": [r[0] for r in rows],
            "votes": [r[1] for r in rows],
            "elected": [r[2] for r in rows],
        }
    )


def valid(n):
    return pl.DataFrame({"cd_eleicao": [1], "sg_ue": ["01"], "valid_votes": [n]})


def test_pair_is_lowest_elected_against_highest_not_elected():
    df = cands([("a", 100, True), ("b", 80, True), ("c", 79, False), ("d", 50, False)])
    pairs = census.within_list_pairs(df)
    assert pairs.height == 1
    row = pairs.row(0, named=True)
    assert (row["elected_votes"], row["other_votes"]) == (80, 79)
    paired = census.margins(pairs, valid(1000))
    assert paired["margin"][0] == pytest.approx(1 / 1000)
    assert not paired["inverted"][0]


def test_lists_without_both_kinds_or_votes_give_no_pair():
    assert census.within_list_pairs(cands([("a", 10, True), ("b", 5, True)])).height == 0
    assert census.within_list_pairs(cands([("a", 10, True), ("b", 0, False)])).height == 0


def test_elected_codes_changed_between_2008_and_2012():
    df = pl.DataFrame({"cd_sit_tot_turno": ["5", "4", "1", "3", "9"]})
    old = census.elected_status(df, 2008)
    assert old["cd_sit_tot_turno"].to_list() == ["5", "4", "1"]
    assert old["elected"].to_list() == [True, False, True]
    new = census.elected_status(df, 2012)
    assert new["cd_sit_tot_turno"].to_list() == ["5", "4", "3"]
    assert new["elected"].to_list() == [False, False, True]


def test_negative_margin_is_inverted_and_not_close():
    df = cands([("a", 100, True), ("b", 90, True), ("c", 95, False)])
    # second list: a close, ordinary pair
    other = cands([("d", 50, True), ("e", 49, False)]).with_columns(
        pl.lit("L2").alias("sq_coligacao")
    )
    paired = census.margins(census.within_list_pairs(pl.concat([df, other])), valid(1000))
    assert paired["inverted"].sum() == 1
    counts = census.close_counts(paired)
    assert counts["pairs"] == 2
    assert counts["inverted"] == 1
    assert counts["close"] == {"0.25%": 1, "0.5%": 1, "1%": 1, "2%": 1}
    assert census.close_candidates(paired)["sq_candidato"].to_list() == ["d", "e"]


def sv_rows(rows):
    """rows: (place, sq_candidato or None, vote_type, votes, annulled)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "cd_cargo": ["13"] * len(rows),
            "nr_turno": [1] * len(rows),
            "cd_ibge": ["1500107"] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "nr_zona": ["0007"] * len(rows),
            "nr_local_votacao": [r[0] for r in rows],
            "sq_candidato": [r[1] for r in rows],
            "vote_type": [r[2] for r in rows],
            "qt_votos": [r[3] for r in rows],
            "annulled_in_results": [r[4] for r in rows],
        }
    )


def test_stronghold_is_best_quotient_among_big_places():
    rows = [
        # place 1: V_p = 100, candidate x has 10 -> share 0.10
        (1, "x", "candidate", 10, False),
        (1, "y", "candidate", 90, False),
        # place 2: V_p = 100, x has 30 -> share 0.30 (best of the big places)
        (2, "x", "candidate", 30, False),
        (2, None, "legend", 70, False),
        # place 3: V_p = 20 (< 50), x has 20 -> share 1.0 but never chosen
        (3, "x", "candidate", 20, False),
        # annulled votes do not count: place 4 would win if they did
        (4, "x", "candidate", 60, True),
        (4, "y", "candidate", 60, False),
        (4, None, "legend", 5, False),
        # blank votes are not counted
        (2, None, "blank", 500, False),
    ]
    pv = census.place_candidate_votes(sv_rows(rows), main=1)
    assert pv.filter(pl.col("nr_local_votacao") == 4)["votes"].sum() == 65
    strong = census.strongholds(pv)
    x = strong.filter(pl.col("sq_candidato") == "x").row(0, named=True)
    assert x["nr_local_votacao"] == 2
    assert x["quotient"] == pytest.approx((30 / 100) / (60 / 285))
    y = strong.filter(pl.col("sq_candidato") == "y").row(0, named=True)
    assert y["nr_local_votacao"] == 4  # place 4 has V_p = 65 >= 50 and y has 60 of it


def test_stronghold_ties_go_to_the_place_with_more_votes():
    rows = [
        (1, "x", "candidate", 10, False),
        (1, "y", "candidate", 90, False),
        (2, "x", "candidate", 20, False),
        (2, "y", "candidate", 180, False),
    ]
    strong = census.strongholds(census.place_candidate_votes(sv_rows(rows), main=1))
    x = strong.filter(pl.col("sq_candidato") == "x").row(0, named=True)
    assert x["nr_local_votacao"] == 2


def test_join_works_after_casting_text_zone_to_integer():
    sv = sv_rows([(1, "x", "candidate", 10, False)]).with_columns(
        pl.col("nr_local_votacao").cast(pl.Int32)
    )
    types = pl.DataFrame(
        {
            "ano": [2020],
            "cd_ibge": ["1500107"],
            "sg_ue": ["01"],
            "nr_zona": [7],
            "nr_local_votacao": [1],
            "place_type": ["rural"],
        }
    )
    out = census.join_place_types(sv, types)
    assert out["place_type"].to_list() == ["rural"]


def test_outside_seat_share_and_summary():
    types = pl.DataFrame(
        {
            "ano": [2020, 2020],
            "cd_ibge": ["1500107"] * 2,
            "sg_ue": ["01"] * 2,
            "nr_zona": [7, 7],
            "nr_local_votacao": [1, 2],
            "place_type": ["seat", "rural"],
        }
    )
    rows = [
        (1, "x", "candidate", 25, False),
        (2, "x", "candidate", 75, False),
        (1, "y", "candidate", 100, False),
    ]
    pv = census.place_candidate_votes(sv_rows(rows), main=1)
    shares = census.outside_seat_share(census.join_place_types(pv, types))
    got = {r["sq_candidato"]: r["outside_share"] for r in shares.iter_rows(named=True)}
    assert got == {"x": pytest.approx(0.75), "y": 0.0}

    strong = census.strongholds(pv)
    table = census.candidate_table(
        pl.DataFrame({"cd_eleicao": [1, 1], "sg_ue": ["01"] * 2, "sq_candidato": ["x", "y"]}),
        strong,
        types,
        shares,
    )
    out = census.summarise(table)
    assert out["candidates"] == 2
    assert out["with_stronghold"] == 2
    assert out["stronghold_outside_seat"] == 1
    assert out["stronghold_by_place_type"] == {"rural": 1, "seat": 1}
    assert out["mean_share_votes_outside_seat"] == pytest.approx(0.375)


def test_main_election_is_the_largest_council_round_one():
    df = pl.DataFrame(
        {
            "cd_eleicao": [1, 1, 1, 2, 2, 3, 3, 3, 3],
            "cd_cargo": ["13", "13", "13", "13", "13", "11", "11", "11", "11"],
            "nr_turno": [1] * 9,
        }
    )
    assert census.main_election(df) == 1
