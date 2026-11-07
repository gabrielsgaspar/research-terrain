import importlib.util
import json
import sys
from pathlib import Path
from statistics import NormalDist

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "alignment_counts", REPO / "explore" / "0004_alignment_counts.py"
)
ac = importlib.util.module_from_spec(SPEC)
sys.modules["alignment_counts"] = ac
SPEC.loader.exec_module(ac)

MAIN = 47
YEAR = 2012


def frame(rows, defaults):
    return pl.DataFrame([{**defaults, **row} for row in rows])


CV_DEFAULTS = {
    "ano_eleicao": YEAR,
    "cd_eleicao": MAIN,
    "cd_tipo_eleicao": 2,
    "nr_turno": 1,
    "sg_ue": "A",
    "cd_ibge": "1500107",
    "cd_cargo": 13,
    "sq_candidato": "0",
    "nr_zona": 1,
    "qt_votos_nominais": 0,
    "qt_votos_nominais_validos": 0,
    "nm_tipo_destinacao_votos": None,
    "ds_sit_tot_turno": "ELEITO",
    "cd_sit_tot_turno": None,
    "sq_coligacao": None,
}


def council(lst, sq, votes, elected, ue="A"):
    return {
        "sg_ue": ue,
        "sq_coligacao": lst,
        "sq_candidato": sq,
        "qt_votos_nominais": votes,
        "cd_sit_tot_turno": 2 if elected else 4,
    }


def mayor(sq, votes, turn=1, ue="A", status="ELEITO", election=MAIN):
    return {
        "cd_cargo": 11,
        "cd_eleicao": election,
        "nr_turno": turn,
        "sg_ue": ue,
        "sq_candidato": sq,
        "qt_votos_nominais": votes,
        "qt_votos_nominais_validos": votes,
        "ds_sit_tot_turno": status,
    }


def turnout(valid=10000, ue="A"):
    return pl.DataFrame(
        {
            "cd_eleicao": [MAIN],
            "nr_turno": [1],
            "sg_ue": [ue],
            "cd_ibge": ["1500107"],
            "cd_cargo": [13],
            "qt_total_votos_validos": [valid],
        }
    )


# --- 1. Pairs


def test_close_pairs_include_exactly_025_and_exclude_026_and_inverted():
    cv = frame(
        [
            council("L1", "1", 100, True),  # margin 0.25%: in
            council("L1", "2", 75, False),
            council("L2", "3", 100, True),  # margin 0.26%: out
            council("L2", "4", 74, False),
            council("L3", "5", 50, True),  # inverted: out
            council("L3", "6", 80, False),
            council("L4", "7", 100, True),  # margin 0: in
            council("L4", "8", 100, False),
        ],
        CV_DEFAULTS,
    )
    pairs, main = ac.close_pairs_025(cv, turnout(), YEAR)
    assert main == MAIN
    assert sorted(pairs["elected_sq"].to_list()) == ["1", "7"]


# --- 2. The mayor


def test_mayor_takes_the_deciding_round_and_breaks_ties_by_candidate_id():
    cv = frame(
        [
            mayor("1", 40, ue="R", status="2º TURNO"),  # run-off municipality
            mayor("2", 39, ue="R", status="2º TURNO"),
            mayor("2", 52, turn=2, ue="R", election=MAIN + 1),
            mayor("1", 50, turn=2, ue="R", election=MAIN + 1, status="NÃO ELEITO"),
            mayor("3", 70, ue="S"),  # round 1 only
            mayor("4", 30, ue="S", status="NÃO ELEITO"),
            mayor("5", 90, ue="O"),  # one candidacy
            mayor("9", 50, ue="T"),  # tie: lower sq_candidato first
            mayor("8", 50, ue="T"),
        ],
        CV_DEFAULTS,
    )
    mayors, counts = ac.elected_mayor(cv, MAIN, YEAR)
    won = dict(zip(mayors["sg_ue"], mayors["sq_candidato"], strict=True))
    assert won == {"R": "2", "S": "3", "O": "5", "T": "8"}
    assert counts["runoff"] == 1
    assert counts["ties"] == 1
    assert counts["mayors"] == 4
    assert counts["not_eleito"] == 0


def test_a_mayor_who_is_not_eleito_is_counted_and_kept():
    cv = frame([mayor("1", 60, status="NÃO ELEITO"), mayor("2", 40)], CV_DEFAULTS)
    mayors, counts = ac.elected_mayor(cv, MAIN, YEAR)
    assert mayors["sq_candidato"].to_list() == ["1"]
    assert counts["not_eleito"] == 1


# --- 3. The coalition

CAND_DEFAULTS = {
    "ano_eleicao": YEAR,
    "cd_eleicao": MAIN,
    "nr_turno": 1,
    "cd_cargo": 13,
    "sg_ue": "A",
    "sq_candidato": "0",
    "nr_partido": "10",
    "sq_coligacao": None,
    "nr_federacao": None,
}
COAL_DEFAULTS = {
    "cd_eleicao": MAIN,
    "cd_cargo": 11,
    "sg_ue": "A",
    "cd_ibge": "1500107",
    "sq_coligacao": "5",
    "nr_partido": "10",
    "nr_federacao": None,
}


def mayors_of(**by_ue):
    return pl.DataFrame({"sg_ue": list(by_ue), "sq_candidato": list(by_ue.values())})


def test_coalition_uses_only_mayoral_rows_and_falls_back_to_the_mayors_party():
    cands = frame(
        [
            {"cd_cargo": 11, "sg_ue": "A", "sq_candidato": "m", "nr_partido": "10"}
            | {"sq_coligacao": 5},
            {"cd_cargo": 11, "sg_ue": "B", "sq_candidato": "n", "nr_partido": "70"}
            | {"sq_coligacao": 9},
        ],
        CAND_DEFAULTS,
    )
    coalitions = frame(
        [
            {"nr_partido": "10"},
            {"nr_partido": "20"},
            {"cd_cargo": 13, "nr_partido": "30"},  # a council row with the same text: ignored
        ],
        COAL_DEFAULTS,
    )
    sets, counts = ac.mayor_coalition(mayors_of(A="m", B="n"), cands, coalitions, MAIN)
    assert sets["A"][0] == {"10", "20"}
    assert sets["B"][0] == {"70"}  # coalition "9" has no rows
    assert counts == {"mayors_without_main_row": 0, "coalitions_without_rows": 1}


def test_a_mayor_without_a_main_election_row_is_counted_and_left_out():
    cands = frame([{"cd_cargo": 13, "sg_ue": "A", "sq_candidato": "m"}], CAND_DEFAULTS)
    sets, counts = ac.mayor_coalition(mayors_of(A="m"), cands, frame([{}], COAL_DEFAULTS), MAIN)
    assert sets == {}
    assert counts["mayors_without_main_row"] == 1


# --- 4. Alignment and 5. unmatched sides

COALITION = {"A": (frozenset({"10", "20"}), frozenset({"F1"}))}


def sides_of(*rows):
    return pl.DataFrame(
        rows, schema=["sg_ue", "sq_candidato", "nr_partido", "nr_federacao"], orient="row"
    )


def pairs_of(*rows):
    return pl.DataFrame(rows, schema=["sg_ue", "elected_sq", "other_sq"], orient="row")


def test_pair_types_before_2024():
    sides = sides_of(
        ("A", "1", "10", None),
        ("A", "2", "20", None),
        ("A", "3", "30", None),
        ("A", "4", "40", None),
        ("A", "5", "30", "F1"),  # federation is ignored before 2024
    )
    pairs = pairs_of(("A", "1", "2"), ("A", "3", "4"), ("A", "1", "3"), ("A", "1", "5"))
    got = ac.pair_types(pairs, sides, COALITION, 2016)
    assert (got["aligned"], got["unaligned"], got["mixed"]) == (1, 1, 2)


def test_in_2024_a_federation_in_the_coalition_makes_a_side_aligned():
    sides = sides_of(("A", "1", "10", None), ("A", "5", "30", "F1"), ("A", "6", "30", "F2"))
    got = ac.pair_types(pairs_of(("A", "1", "5")), sides, COALITION, 2024)
    assert got["aligned"] == 1
    got = ac.pair_types(pairs_of(("A", "1", "6")), sides, COALITION, 2024)
    assert got["mixed"] == 1


def test_unmatched_sides_and_mayors_are_counted_and_never_unaligned():
    sides = sides_of(
        ("A", "1", "10", None),
        ("A", "2", None, None),  # null party
        ("A", "3", "30", None),
        ("A", "4", "40", None),
        ("B", "5", "30", None),
        ("B", "6", "40", None),
    )
    pairs = pairs_of(
        ("A", "1", "9"),  # side with no row
        ("A", "1", "2"),  # side with a null party
        ("A", "3", "4"),  # unaligned
        ("B", "5", "6"),  # municipality without a matched mayor
    )
    got = ac.pair_types(pairs, sides, COALITION, 2016)
    assert got["left_out_side"] == 2
    assert got["sides_not_matched"] == 2
    assert got["left_out_mayor"] == 1
    assert got["unaligned"] == 1
    assert got["aligned"] == got["mixed"] == 0


# --- 6. Implied power


def test_implied_power():
    k = 1.96 + NormalDist().inv_cdf(0.868)
    assert ac.implied_power(1164, 1164) == pytest.approx(NormalDist().cdf(k / 2 - 1.96))
    assert ac.implied_power(1164, 1164) == pytest.approx(0.34, abs=0.01)
    assert ac.implied_power(2328, 2328) > ac.implied_power(1164, 1164)
    assert ac.implied_power(1000, 1164) < ac.implied_power(1164, 1164)
    assert ac.implied_power(1164, 1000) < ac.implied_power(1164, 1164)
    assert ac.implied_power(100, 1164) < ac.implied_power(1000, 1164)
    assert ac.implied_power(0, 1164) == pytest.approx(NormalDist().cdf(-1.96))


# --- 7. No outcome read, no estimate


def fake_read():
    asked = []
    cv = frame(
        [
            council("L1", "1", 100, True),
            council("L1", "2", 90, False),
            council("L2", "3", 100, True),
            council("L2", "4", 95, False),
            council("L3", "5", 100, True),
            council("L3", "6", 98, False),
            mayor("m", 60),
            mayor("x", 40, status="NÃO ELEITO"),
        ],
        CV_DEFAULTS,
    )
    coalitions = frame(
        [{"nr_partido": "10"}, {"nr_partido": "20"}, {"cd_cargo": 13, "nr_partido": "30"}],
        COAL_DEFAULTS,
    )

    def read(manifest, pattern, columns=None):
        asked.append((manifest, pattern))
        if manifest == "tse_results" and pattern.startswith("candidate_votes"):
            return cv
        if manifest == "tse_results" and pattern.startswith("turnout"):
            return turnout()
        if manifest == "tse_parties":
            return coalitions
        raise AssertionError(f"unexpected read of {manifest} {pattern}")

    return read, asked


def synthetic_candidates():
    council_rows = [
        {"sq_candidato": "1", "nr_partido": "10"},
        {"sq_candidato": "2", "nr_partido": "20"},  # L1: aligned
        {"sq_candidato": "3", "nr_partido": "30"},
        {"sq_candidato": "4", "nr_partido": "40"},  # L2: unaligned
        {"sq_candidato": "5", "nr_partido": "10"},
        {"sq_candidato": "6", "nr_partido": "30"},  # L3: mixed
    ]
    rows = [*council_rows, {"cd_cargo": 11, "sq_candidato": "m", "sq_coligacao": 5}]
    return frame(rows, CAND_DEFAULTS)


def test_election_counts_end_to_end_reads_no_outcome_table(monkeypatch):
    monkeypatch.setitem(ac.EXPECTED_PAIRS, YEAR, 3)
    read, asked = fake_read()
    got = ac.election_counts(read, synthetic_candidates(), YEAR)
    assert (got["aligned"], got["unaligned"], got["mixed"]) == (1, 1, 1)
    assert got["close_pairs"] == 3
    assert got["left_out_side"] == got["left_out_mayor"] == 0
    assert got["coalitions_without_rows"] == 0
    assert {m for m, _ in asked} == {"tse_results", "tse_parties"}
    for manifest, pattern in asked:
        assert not manifest.startswith("cell_")
        assert "cell_" not in pattern


def test_a_wrong_pair_count_or_too_many_left_out_stops_the_run(monkeypatch):
    read, _ = fake_read()
    with pytest.raises(SystemExit):
        ac.election_counts(read, synthetic_candidates(), YEAR)  # 3 pairs, 478 expected
    ok = dict.fromkeys(ac.KINDS, 0) | {"aligned": 100}
    with pytest.raises(SystemExit):
        ac.check_year(2008, 478, ok)  # does not add up
    ok["aligned"] = 478
    ac.check_year(2008, 478, ok)
    bad = dict.fromkeys(ac.KINDS, 0) | {"aligned": 450, "left_out_side": 28}
    with pytest.raises(SystemExit):
        ac.check_year(2008, 478, bad)  # 5.9% left out


def keys_of(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from keys_of(v)


def test_results_have_no_estimate_key_and_serialise(tmp_path):
    year_counts = {
        "close_pairs": 100,
        "aligned": 40,
        "unaligned": 30,
        "mixed": 20,
        "left_out_side": 6,
        "left_out_mayor": 4,
        "sides_not_matched": 8,
        "mayors": 50,
        "runoff": 3,
        "ties": 1,
        "not_eleito": 2,
        "mayors_without_main_row": 1,
        "coalitions_without_rows": 2,
    }
    per = {str(y): dict(year_counts) for y in ac.ELECTIONS}
    results = ac.build_results(per)
    assert results["pooled_2008_2024"]["aligned"] == 200
    assert results["pooled_2008_2020"]["aligned"] == 160
    assert results["kill_criterion_1"]["met"] is True  # 150 unaligned pairs, under 200
    banned = ("estimate", "coef", "beta", "tau", "effect", "diff", "slope", "stderr")
    for key in keys_of(results):
        assert not any(b in key.lower() for b in banned), key
    summary = ac._summary(results)
    assert summary.splitlines()[0].startswith("Pooled 2008-2024: 200 aligned")
    ac.write_results(tmp_path, summary, results)
    json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("aligned", "unaligned", "met"),
    [(1414, 1446, False), (199, 1446, True), (1414, 199, True), (200, 200, False)],
)
def test_kill_criterion_1_is_met_when_either_side_has_under_200(aligned, unaligned, met):
    zero = dict.fromkeys(ac.SUM_KEYS, 0)
    per = {str(y): dict(zero) for y in ac.ELECTIONS}
    per[str(ac.ELECTIONS[0])] |= {"aligned": aligned, "unaligned": unaligned}
    results = ac.build_results(per)
    assert results["kill_criterion_1"]["met"] is met
    first = ac._summary(results).splitlines()[0]
    phrase = "drafted kill criterion 1 (fewer than 200 aligned or unaligned)"
    if met:
        assert f"{phrase} met;" in first
        assert "not met" not in first
    else:
        assert f"{phrase} not met" in first
