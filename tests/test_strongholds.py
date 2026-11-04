"""`terrain.strongholds` must equal the explore scripts it was copied from."""

import importlib.util
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from terrain import strongholds as lib
from terrain.grid import km_to_lonlat

REPO = Path(__file__).resolve().parents[1]


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = load("feasibility_census", "0001_feasibility_census.py")
options = load("exposure_options", "0001_exposure_options.py")

X0, Y0 = 4000, 9000


# --- Synthetic tables


def candidate_votes() -> pl.DataFrame:
    rows = [
        # cargo, turno, eleicao, ue, ibge, cand, list, votes, code
        (13, 1, 1, "10", "1100001", 1, 7, 60, 2),
        (13, 1, 1, "10", "1100001", 1, 7, 40, 2),
        (13, 1, 1, "10", "1100001", 2, 7, 80, 3),
        (13, 1, 1, "10", "1100001", 3, 7, 79, 4),
        (13, 1, 1, "10", "1100001", 4, 7, 10, 5),
        (13, 1, 1, "10", "1100001", 5, 8, 50, 2),
        (13, 1, 1, "10", "1100001", 6, 8, 30, 4),
        (13, 1, 1, "20", "1100002", 7, 9, 40, 2),
        (13, 1, 1, "20", "1100002", 8, 9, 39, 4),
        (13, 1, 1, "20", "1100002", 9, 9, 5, 6),
        (13, 1, 1, "20", "1100002", 10, None, 5, 2),
        (13, 1, 1, "20", "1100002", 11, 12, 70, 2),
        (13, 1, 1, "20", "1100002", 12, 12, 90, 4),
        (13, 2, 1, "20", "1100002", 13, 14, 1, 2),
        (11, 1, 1, "20", "1100002", 14, 15, 1, 2),
        (13, 1, 2, "20", "1100002", 15, 16, 1, 2),
    ]
    return pl.DataFrame(
        rows,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "sg_ue",
            "cd_ibge",
            "sq_candidato",
            "sq_coligacao",
            "qt_votos_nominais",
            "cd_sit_tot_turno",
        ],
        orient="row",
    )


def turnout() -> pl.DataFrame:
    rows = [
        (13, 1, 1, "10", 1000),
        (13, 1, 1, "10", 1000),
        (13, 1, 1, "20", 500),
        (13, 2, 1, "20", 9999),
        (11, 1, 1, "20", 9999),
    ]
    return pl.DataFrame(
        rows,
        schema=["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "qt_total_votos_validos"],
        orient="row",
    )


def section_votes() -> pl.DataFrame:
    rows = [
        # cargo, turno, eleicao, type, annulled, zona, local, ibge, ue, cand, votes
        (13, 1, 1, "candidate", False, 1, 1, "1100001", "10", 1, 60),
        (13, 1, 1, "candidate", False, 1, 1, "1100001", "10", 3, 20),
        (13, 1, 1, "legend", False, 1, 1, "1100001", "10", None, 20),
        (13, 1, 1, "candidate", False, 1, 2, "1100001", "10", 1, 10),
        (13, 1, 1, "candidate", False, 1, 2, "1100001", "10", 3, 50),
        (13, 1, 1, "candidate", True, 1, 2, "1100001", "10", 3, 500),
        (13, 1, 1, "blank", False, 1, 2, "1100001", "10", None, 7),
        (13, 1, 1, "candidate", False, 1, 3, "1100001", "10", 2, 5),
        (13, 1, 1, "candidate", False, 2, 1, "1100002", "20", 7, 30),
        (13, 1, 1, "candidate", False, 2, 1, "1100002", "20", 8, 10),
        (13, 1, 1, "candidate", False, 2, 2, "1100002", "20", 8, 0),
        (13, 2, 1, "candidate", False, 2, 1, "1100002", "20", 7, 99),
        (13, 1, 2, "candidate", False, 2, 1, "1100002", "20", 7, 99),
    ]
    return pl.DataFrame(
        rows,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "vote_type",
            "annulled_in_results",
            "nr_zona",
            "nr_local_votacao",
            "cd_ibge",
            "sg_ue",
            "sq_candidato",
            "qt_votos",
        ],
        orient="row",
    )


def places() -> pl.DataFrame:
    xy = [(0.5, 1.5), (2.5, 3.5), (3.5, 5.5), (-1.5, 2.5), (6.5, 6.5), (1.0, 1.0)]
    lon, lat = km_to_lonlat([X0 + x for x, _ in xy], [Y0 + y for _, y in xy])
    rows = [
        ("1100001", "10", 1, 1, lat[0], lon[0]),
        ("1100001", "10", 1, 2, lat[1], lon[1]),
        ("1100001", "10", 1, 3, lat[2], lon[2]),
        ("1100001", "10", 1, 3, lat[2] + 1.0, lon[2]),  # a duplicate key: the first is kept
        ("1100002", "20", 2, 1, lat[3], lon[3]),
        ("1100002", "20", 2, 2, lat[4], lon[4]),
        ("1100002", "20", 2, 9, None, None),  # no coordinates
    ]
    return pl.DataFrame(
        rows,
        schema={
            "cd_ibge": pl.Utf8,
            "sg_ue": pl.Utf8,
            "nr_zona": pl.Int64,
            "nr_local_votacao": pl.Int64,
            "lat": pl.Float64,
            "long": pl.Float64,
        },
        orient="row",
    )


def cells() -> pl.DataFrame:
    rows = [("1100001", X0 + dx, Y0 + dy) for dx in range(-2, 12, 3) for dy in (0, 4, 20)]
    rows += [("1100002", X0 + dx, Y0 + 1) for dx in (-3, 0, 5, 8)]
    return pl.DataFrame(rows, schema=["cd_ibge", "x_km", "y_km"], orient="row")


# --- Census functions


def test_constants_match():
    for name in (
        "HEADLINE",
        "COUNCIL",
        "LIST_KEY",
        "CAND_KEY",
        "PLACE_KEY",
        "ELECTED_CODES",
        "NOT_ELECTED_CODES",
    ):
        assert getattr(lib, name) == getattr(census, name), name
    for name in ("CELL", "MAX_KM", "TOLERANCE", "KERNELS", "MEASURES"):
        assert getattr(lib, name) == getattr(options, name), name


@pytest.mark.parametrize("year", [2008, 2012, 2024])
def test_codes_match(year):
    assert lib._codes(lib.ELECTED_CODES, year) == census._codes(census.ELECTED_CODES, year)
    assert lib._codes(lib.NOT_ELECTED_CODES, year) == census._codes(census.NOT_ELECTED_CODES, year)


def test_council_round1_and_main_election_match():
    cv = candidate_votes()
    assert_frame_equal(lib._council_round1(cv), census._council_round1(cv))
    assert lib.main_election(cv) == census.main_election(cv) == 1


@pytest.mark.parametrize("year", [2008, 2012])
def test_elected_status_matches(year):
    cv = candidate_votes()
    assert_frame_equal(lib.elected_status(cv, year), census.elected_status(cv, year))


@pytest.mark.parametrize("year", [2008, 2012])
def test_pairs_and_margins_match(year):
    cv, tn = candidate_votes(), turnout()
    mine = lib.candidacy_votes(cv, year, 1)
    theirs = census.candidacy_votes(cv, year, 1)
    assert_frame_equal(mine, theirs)
    mine_pairs, their_pairs = lib.within_list_pairs(mine), census.within_list_pairs(theirs)
    assert_frame_equal(mine_pairs, their_pairs)
    assert_frame_equal(lib.valid_votes(tn, 1), census.valid_votes(tn, 1), check_row_order=False)
    mine_margins = lib.margins(mine_pairs, lib.valid_votes(tn, 1))
    their_margins = census.margins(their_pairs, census.valid_votes(tn, 1))
    assert_frame_equal(mine_margins, their_margins, check_row_order=False)


def test_pairs_have_content():
    # Guards against a vacuous comparison: the 2012 table holds real pairs.
    cands = lib.candidacy_votes(candidate_votes(), 2012, 1)
    paired = lib.margins(lib.within_list_pairs(cands), lib.valid_votes(turnout(), 1))
    assert paired.height >= 3
    assert lib.close_pairs(paired).height >= 1


def test_place_candidate_votes_matches():
    sv = section_votes()
    mine = lib.place_candidate_votes(sv, 1)
    assert mine.height > 0
    assert_frame_equal(mine, census.place_candidate_votes(sv, 1), check_row_order=False)


# --- Exposure functions


def world(year=2012):
    cv, tn = candidate_votes(), turnout()
    cands = census.candidacy_votes(cv, year, 1)
    paired = census.margins(census.within_list_pairs(cands), census.valid_votes(tn, 1))
    place_votes = census.place_candidate_votes(section_votes(), 1)
    return paired, place_votes


def test_close_pairs_matches():
    paired, _ = world()
    mine = lib.close_pairs(paired, threshold=0.05)
    assert mine.height >= 2
    assert_frame_equal(mine, options.close_pairs(paired, threshold=0.05))
    assert_frame_equal(lib.close_pairs(paired), options.close_pairs(paired))


def test_place_totals_and_shares_match():
    _, place_votes = world()
    totals = lib.place_totals(place_votes)
    assert totals.height > 0
    assert_frame_equal(totals, options.place_totals(place_votes), check_row_order=False)
    shares = lib.place_shares(place_votes)
    assert shares.height > 0
    assert_frame_equal(shares, options.place_shares(place_votes), check_row_order=False)


def test_locate_places_and_distances_match():
    located = lib.locate_places(places())
    assert located.height == 5  # no coordinates and the duplicate key are gone
    assert_frame_equal(located, options.locate_places(places()))
    mine = lib.cell_place_distances(cells(), located)
    assert mine.height > 0
    theirs = options.cell_place_distances(cells(), located)
    assert_frame_equal(mine, theirs, check_row_order=False)
    smaller = lib.cell_place_distances(cells(), located, max_km=3.0)
    assert smaller.height < mine.height
    assert_frame_equal(
        smaller, options.cell_place_distances(cells(), located, max_km=3.0), check_row_order=False
    )


def test_distances_without_a_hit_match():
    far = pl.DataFrame({"cd_ibge": ["1100001"], "x_km": [X0 + 500], "y_km": [Y0]})
    located = lib.locate_places(places())
    mine = lib.cell_place_distances(far, located)
    assert mine.height == 0
    assert_frame_equal(mine, options.cell_place_distances(far, located))


@pytest.mark.parametrize("name", ["exp2", "ring2", "ring5"])
def test_kernel_matches(name):
    d = pl.DataFrame({"d": [0.0, 1.0, 2.0, 2.0 + 1e-10, 2.5, 5.0, 9.99, 10.0, 10.0 + 1e-10, 10.5]})
    mine = d.select(lib.kernel(name, pl.col("d")).alias("k"))
    assert_frame_equal(mine, d.select(options.kernel(name, pl.col("d")).alias("k")))
    assert mine["k"].max() > 0


def test_kernel_rejects_an_unknown_name():
    with pytest.raises(ValueError):
        lib.kernel("ring9", pl.col("d"))


@pytest.mark.parametrize("name", ["exp2", "ring2", "ring5"])
@pytest.mark.parametrize("measure", ["share", "votes"])
def test_exposure_matches(name, measure):
    paired, place_votes = world()
    pairs = lib.close_pairs(paired, threshold=0.05)
    dist = lib.cell_place_distances(cells(), lib.locate_places(places()))
    totals, shares = lib.place_totals(place_votes), lib.place_shares(place_votes)
    mine = lib.exposure(dist, totals, shares, pairs, name, measure)
    assert mine.height > 0
    theirs = options.exposure(dist, totals, shares, pairs, name, measure)
    assert_frame_equal(mine, theirs)


def test_exposure_rejects_an_unknown_measure():
    empty = pl.DataFrame()
    with pytest.raises(ValueError):
        lib.exposure(empty, empty, empty, empty, "exp2", "mean")
