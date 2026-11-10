import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.explore import restrict, write_results

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0006_feasibility.py"
SPEC = importlib.util.spec_from_file_location("representation_feasibility", SCRIPT)
rf = importlib.util.module_from_spec(SPEC)
sys.modules["representation_feasibility"] = rf
SPEC.loader.exec_module(rf)

KEY = ["cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]


# --- Hand-computed treatment: two municipalities, a close pair each, three places


def votes_frame(rows):
    """(ibge, ue, place, candidate, votes) -> the table of `place_candidate_votes`."""
    return pl.DataFrame(
        [
            {
                "cd_ibge": ibge,
                "sg_ue": ue,
                "nr_zona": 1,
                "nr_local_votacao": place,
                "cd_eleicao": 1,
                "vote_type": "candidate",
                "sq_candidato": cand,
                "votes": v,
            }
            for ibge, ue, place, cand, v in rows
        ]
    )


# Municipality A has two pairs (a1 beat b1; o1 beat b1); B has one (a2 beat b2).
# Votes at each place: a1, b1, o1 (not in a pair as the winner of pair 1), c (everyone else).
A, B = ("1100001", "10001"), ("1100002", "10002")
HAND = votes_frame(
    [
        # A place 1: a1 .6, b1 .2, o1 .2 (total 100)
        (*A, 1, "a1", 60),
        (*A, 1, "b1", 20),
        (*A, 1, "o1", 20),
        # A place 2: a1 .1, b1 .5, o1 .4
        (*A, 2, "a1", 10),
        (*A, 2, "b1", 50),
        (*A, 2, "o1", 40),
        # A place 3: a1 .3, b1 has no row, o1 .7
        (*A, 3, "a1", 30),
        (*A, 3, "o1", 70),
        # B place 1: a2 .25, b2 .25, other .5
        (*B, 1, "a2", 25),
        (*B, 1, "b2", 25),
        (*B, 1, "z2", 50),
        # B place 2: a2 has no row, b2 .4
        (*B, 2, "b2", 40),
        (*B, 2, "z2", 60),
        # B place 3: a2 .5, b2 .1
        (*B, 3, "a2", 50),
        (*B, 3, "b2", 10),
        (*B, 3, "z2", 40),
    ]
)
PAIRS = pl.DataFrame(
    {
        "cd_ibge": [A[0], A[0], B[0]],
        "sg_ue": [A[1], A[1], B[1]],
        "cd_eleicao": [1, 1, 1],
        "w": ["a1", "o1", "a2"],
        "l": ["b1", "b1", "b2"],
    }
)
# D = sum over the municipality's pairs of (s_w - s_l); S = sum of (s_w + s_l).
D_HAND = {
    (A[0], 1): (0.6 - 0.2) + (0.2 - 0.2),
    (A[0], 2): (0.1 - 0.5) + (0.4 - 0.5),
    (A[0], 3): (0.3 - 0.0) + (0.7 - 0.0),
    (B[0], 1): 0.0,
    (B[0], 2): -0.4,
    (B[0], 3): 0.4,
}
S_HAND = {
    (A[0], 1): (0.6 + 0.2) + (0.2 + 0.2),
    (A[0], 2): (0.1 + 0.5) + (0.4 + 0.5),
    (A[0], 3): (0.3 + 0.0) + (0.7 + 0.0),
    (B[0], 1): 0.5,
    (B[0], 2): 0.4,
    (B[0], 3): 0.6,
}


def hand_sample():
    reg, triples = rf.pair_place_rows(PAIRS, HAND)
    t = triples.join(reg.with_row_index("loc").select(*KEY, "loc"), on=KEY)
    places = reg.with_columns(pl.col("cd_ibge").alias("group"))
    return reg, places, t


def test_d_and_s_match_hand_values():
    reg, _, _ = hand_sample()
    got_d = {(r["cd_ibge"], r["nr_local_votacao"]): r["D"] for r in reg.iter_rows(named=True)}
    got_s = {(r["cd_ibge"], r["nr_local_votacao"]): r["S"] for r in reg.iter_rows(named=True)}
    assert got_d.keys() == D_HAND.keys()
    for k, v in D_HAND.items():
        assert got_d[k] == pytest.approx(v, abs=1e-12)
        assert got_s[k] == pytest.approx(S_HAND[k], abs=1e-12)


def test_flipping_a_pair_flips_its_contribution():
    reg, places, t = hand_sample()
    prep = rf.prepare(
        places,
        np.ones(places.height, dtype=bool),
        np.zeros(places.height),
        np.zeros((places.height, 1)),
        t["loc"].to_numpy(),
        t["pair_id"].to_numpy(),
        t["diff"].to_numpy(),
        PAIRS.height,
    )
    assert prep is not None
    assert prep.n_pairs == 3
    observed = prep.d_raw(np.ones(3))
    flipped = prep.d_raw(np.array([-1.0, 1.0, 1.0]))  # pair 0: a1 over b1
    contribution = np.array([0.4, -0.4, 0.3, 0.0, 0.0, 0.0])  # a1 - b1 at A's three places
    assert np.allclose(observed - flipped, 2 * contribution, atol=1e-12)
    assert np.allclose(prep.d_raw(-np.ones(3)), -observed, atol=1e-12)
    assert np.allclose(
        observed,
        [D_HAND[(r["cd_ibge"], r["nr_local_votacao"])] for r in reg.iter_rows(named=True)],
        atol=1e-12,
    )


# --- Frisch-Waugh against dense dummies


def dense_beta(y, d, controls, groups):
    levels = np.unique(groups)
    dummies = (groups[:, None] == levels[None, :]).astype(float)
    x = np.column_stack([d, controls, dummies])
    return np.linalg.lstsq(x, y, rcond=None)[0][0]


def test_fwl_beta_equals_the_dense_dummy_fit():
    rng = np.random.default_rng(5)
    n = 60
    groups = rng.integers(0, 7, size=n)
    controls = rng.normal(size=(n, 2))
    d = rng.normal(size=n) + 0.5 * controls[:, 0] + groups * 0.1
    y = 1.5 * d - controls[:, 1] + rng.normal(size=n) + groups
    assert rf.fwl_beta(y, d, controls, groups) == pytest.approx(
        dense_beta(y, d, controls, groups), abs=1e-10
    )
    one = controls[:, :1]
    assert rf.fwl_beta(y, d, one, groups) == pytest.approx(dense_beta(y, d, one, groups), abs=1e-10)


def test_prepared_slope_equals_fwl_beta():
    rng = np.random.default_rng(8)
    n_groups, per = 12, 4
    n = n_groups * per
    group = np.repeat(np.arange(n_groups), per)
    places = pl.DataFrame({"cd_ibge": [f"m{g}" for g in group], "group": group.astype(str)})
    t_place = np.repeat(np.arange(n), 2)
    t_pair = np.repeat(group, 2) * 2 + np.tile([0, 1], n)
    t_diff = rng.normal(size=t_place.size)
    y = rng.normal(size=n) + group
    controls = rng.normal(size=(n, 2))
    prep = rf.prepare(
        places, np.ones(n, dtype=bool), y, controls, t_place, t_pair, t_diff, 2 * n_groups
    )
    d_obs = np.bincount(t_place, weights=t_diff, minlength=n)
    assert rf.observed_beta(prep) == pytest.approx(
        rf.fwl_beta(y, d_obs, controls, group), abs=1e-10
    )
    sigma = rng.integers(0, 2, size=2 * n_groups) * 2.0 - 1.0
    d_flip = np.bincount(t_place, weights=sigma[t_pair] * t_diff, minlength=n)
    assert prep.beta(sigma) == pytest.approx(rf.fwl_beta(y, d_flip, controls, group), abs=1e-10)


# --- Balance: a planted violation and an unrelated baseline


def balance_world(planted):
    rng = np.random.default_rng(11)
    pairs, per = 30, 4
    n = pairs * per
    group = np.repeat(np.arange(pairs), per)
    places = pl.DataFrame({"cd_ibge": [f"m{g}" for g in group], "group": group.astype(str)})
    t_place = np.arange(n)
    t_pair = group
    t_diff = rng.normal(size=n)
    s = rng.uniform(0.2, 0.8, size=n)
    d_obs = t_diff.copy()  # one pair per municipality: D is the place's diff
    preps = {}
    for name in rf.BASELINES:
        y = d_obs + 0.1 * rng.normal(size=n) if planted and name == "school" else rng.normal(size=n)
        preps[name] = rf.prepare(
            places, np.ones(n, dtype=bool), y, s, t_place, t_pair, t_diff, pairs
        )
    sims = rf.ri_draws(preps, pairs, draws=rf.DRAWS, seed=rf.SEED, batch=rf.BATCH)
    return rf.joint_balance(preps, sims)


def test_planted_imbalance_gives_a_small_joint_p_and_noise_does_not():
    assert balance_world(planted=True) < 0.01
    assert balance_world(planted=False) > 0.1


# --- The year guard


def test_outcome_years_by_use():
    assert rf.outcome_years(2016, "school") == [2012, 2016]
    assert rf.outcome_years(2016, "builtup") == [2016]
    assert rf.outcome_years(2016, "lights") == [2012, 2013, 2014, 2015]
    with pytest.raises(ValueError):
        rf.outcome_years(2016, "native")


# --- A small world, every table the script reads

RO = [f"11{m:05d}" for m in range(8)]
AC = [f"12{m:05d}" for m in range(6)]
OUTSIDE = "3500001"
EVERY = [*RO, *AC, OUTSIDE]
HALF = frozenset([*RO, *AC])
UE = {code: str(10001 + i) for i, code in enumerate(EVERY)}
NOT_CLOSE = RO[7]  # margin 2%: not a close pair
PLACES = (1, 2, 3, 4)
YEARS = (2008, 2012, 2016, 2020)
POISON_NATIVE = 0.987


def gap(i):
    return 2000 if EVERY[i] == NOT_CLOSE else 100 + 50 * (i % 3)


def votes_at(year, i, p, side):
    return 2 * (10 + (3 * i + 5 * p + 7 * side + year // 4) % 40)


def candidate_votes(year):
    elected, other = (1, 2) if year == 2008 else (2, 4)
    rows = []
    for i, code in enumerate(EVERY):
        rows.append((13, 1, year, UE[code], code, f"{UE[code]}1", 7, 1000 + gap(i), elected))
        rows.append((13, 1, year, UE[code], code, f"{UE[code]}2", 7, 1000, other))
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


def turnout(year):
    return pl.DataFrame(
        [(13, 1, year, UE[c], c, 100_000) for c in EVERY],
        schema=["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "cd_ibge", "qt_total_votos_validos"],
        orient="row",
    )


def section_votes(year):
    rows = []
    for i, code in enumerate(EVERY):
        for p in PLACES:
            for side, cand in ((0, "1"), (1, "2"), (2, "3")):
                if side == 1 and i == 1 and p == 3:
                    continue  # the loser has no row at this place: share 0
                v = votes_at(year, i, p, side)
                for section in (1, 2):
                    rows.append((cand, v // 2, "candidate", code, p, section))
            for section in (1, 2):
                rows.append((None, 5, "legend", code, p, section))
                rows.append((None, 2, "blank", code, p, section))
    frame = pl.DataFrame(
        [
            {
                "ano_eleicao": year,
                "cd_eleicao": year,
                "nr_turno": 1,
                "cd_cargo": 13,
                "sg_ue": UE[code],
                "cd_ibge": code,
                "nr_zona": "1",
                "nr_secao": f"{p}{section}",  # unique within the zone, as in real data
                "nr_local_votacao": p,
                "vote_type": vt,
                "annulled_in_results": False,
                "sq_candidato": None if cand is None else f"{UE[code]}{cand}",
                "qt_votos": v,
            }
            for cand, v, vt, code, p, section in rows
        ]
    )
    ac = frame.filter(pl.col("cd_ibge").str.starts_with("12"))
    return [frame.filter(~pl.col("cd_ibge").str.starts_with("12")), ac]


def polling_places(year):
    conf = {1: 0.0, 2: 0.0, 3: 0.8, 4: 5.0}
    return pl.DataFrame(
        [(year, c, UE[c], 1, p, -10.0, -50.0, conf[p]) for c in EVERY for p in PLACES],
        schema=["ano", *KEY, "lat", "long", "conf_dist_km"],
        orient="row",
    )


def school_match(year):
    conf = {1: "high", 2: "high", 3: "medium", 4: "low"}
    return pl.DataFrame(
        [(year, c, UE[c], 1, p, conf[p]) for c in EVERY for p in PLACES],
        schema=["ano", *KEY, "confidence"],
        orient="row",
    )


def place_outcomes(election, y):
    rows = []
    for i, code in enumerate(EVERY):
        for p in PLACES:
            has_school = p < 4
            rows.append(
                {
                    "ano": election,
                    "cd_ibge": code,
                    "sg_ue": UE[code],
                    "nr_zona": 1,
                    "nr_local_votacao": p,
                    "y": y,
                    "located_1km": p < 4,
                    "school_id": f"S{i}{p}" if has_school else None,
                    "school_rede": ("3" if p < 3 else "2") if has_school else None,
                    "school_n_fac": (3 * i + 5 * p + 2 * y + election % 7) % 10
                    if has_school
                    else None,
                    "lights_1km": 1.0 + ((7 * i + 3 * p + 5 * y) % 11) / 3 if y >= 2013 else None,
                    "builtup_1km": ((13 * i + 7 * p + election) % 17) / 17,
                    "native_10km": POISON_NATIVE,
                }
            )
    return pl.DataFrame(rows)


class FakeSource:
    """Serves the world and records every request."""

    def __init__(self):
        self.requests = []
        self.section_requests = []

    def read(self, manifest, pattern, columns=None):
        self.requests.append((manifest, pattern, None if columns is None else tuple(columns)))
        if manifest == "place_outcomes":
            e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
            frame = place_outcomes(e, y)
        else:
            year = int(re.search(r"(\d{4})", pattern).group(1))
            if manifest == "tse_results":
                frame = candidate_votes(year) if "candidate_votes" in pattern else turnout(year)
            elif manifest == "polling_places":
                frame = polling_places(year)
            elif manifest == "school_polling_match":
                frame = school_match(year)
            else:
                raise AssertionError(f"unexpected manifest {manifest}")
        if columns is not None:
            frame = frame.select(columns)
        return restrict(frame, HALF)

    def read_sections(self, year, main, vote_munis):
        self.section_requests.append((year, main, vote_munis))
        return [rf.state_piece(f.lazy(), main, HALF, vote_munis) for f in section_votes(year)]


def requested_years(source, election):
    out = []
    for manifest, pattern, _ in source.requests:
        if manifest == "place_outcomes":
            e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
            if e == election:
                out.append(y)
    return sorted(set(out))


def test_the_reader_refuses_any_year_after_the_election():
    source = FakeSource()
    for use in ("school", "builtup", "lights"):
        with pytest.raises(ValueError, match="after election"):
            rf.place_outcomes_year(source.read, 2012, 2013, use)
        with pytest.raises(ValueError, match="after election"):
            rf.place_outcomes_year(source.read, 2020, 2024, use)
    with pytest.raises(ValueError, match="not read"):
        rf.place_outcomes_year(source.read, 2016, 2011, "school")
    with pytest.raises(ValueError, match="not read"):
        rf.place_outcomes_year(source.read, 2016, 2016, "lights")  # lights stop at E-1
    assert source.requests == []


def test_the_script_requests_only_the_allowed_years_and_columns():
    source = FakeSource()
    for year in YEARS:
        rf.load_election(source.read, source.read_sections, year)
    assert requested_years(source, 2008) == [2008]
    assert requested_years(source, 2012) == [2008, 2012]
    assert requested_years(source, 2016) == [2012, 2013, 2014, 2015, 2016]
    assert requested_years(source, 2020) == [2016, 2017, 2018, 2019, 2020]
    for manifest, pattern, columns in source.requests:
        if manifest == "place_outcomes":
            e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
            assert y <= e
            assert columns is not None and "native_10km" not in columns
    assert {m for m, _, _ in source.requests} == {
        "tse_results",
        "polling_places",
        "school_polling_match",
        "place_outcomes",
    }
    treatment_years = {
        int(re.search(r"(\d{4})", p).group(1))
        for m, p, _ in source.requests
        if m != "place_outcomes"
    }
    assert treatment_years == set(YEARS)


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def all_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from all_keys(v)


def test_the_whole_pipeline_on_the_small_world(tmp_path):
    source = FakeSource()
    data = {y: rf.load_election(source.read, source.read_sections, y) for y in YEARS}
    results = rf.compute(data, draws=300, seed=rf.SEED, batch=64)

    assert set(results) == {
        "counts",
        "coverage",
        "schools",
        "balance",
        "placebo",
        "power",
        "by_state",
        "design",
    }
    assert results["counts"]["pairs_050"] == 13 * 4  # the outside municipality is not read
    assert results["counts"]["pairs_by_election"] == {str(y): 13 for y in YEARS}
    assert results["counts"]["places_with_pairs"] == 13 * 4 * 4
    assert results["coverage"]["located_share"] == pytest.approx(0.75)
    assert results["schools"]["match_share"] == pytest.approx(0.75)
    assert results["schools"]["municipal_places"] == 14 * 2 * 4
    assert results["schools"]["state_places"] == 14 * 1 * 4
    assert set(results["balance"]) == {"ri_p_joint", "beta", "ri_p"}
    assert set(results["balance"]["beta"]) == {"school", "lights", "builtup"}
    assert set(results["balance"]["ri_p"]) == {"school", "lights", "builtup"}
    assert set(results["placebo"]) == {"ri_p_school", "beta", "clustered_se", "n_places"}
    assert set(results["power"]) == {"mde_sd_school", "sd_ri", "mean_abs_d", "sd_pre_change"}
    assert results["design"] == {
        "window": 0.005,
        "draws": 300,
        "seed": 20261110,
        "elections": [2008, 2012, 2016, 2020],
        "outcome_years": "see the issue",
    }
    assert set(results["by_state"]) == {"RO", "AC"}
    for v in results["by_state"].values():
        assert set(v) == {
            "pairs_050",
            "located_share",
            "match_share",
            "ri_p_joint",
            "ri_p_school",
            "mde_sd_school",
        }
    assert results["by_state"]["RO"]["pairs_050"] == 7 * 4
    assert results["by_state"]["AC"]["pairs_050"] == 6 * 4

    for value in (
        results["counts"]["pairs_050"],
        results["coverage"]["located_share"],
        results["schools"]["match_share"],
        results["balance"]["ri_p_joint"],
        results["placebo"]["ri_p_school"],
        results["power"]["mde_sd_school"],
    ):
        assert number(value)
    assert 0 < results["balance"]["ri_p_joint"] <= 1
    assert 0 < results["placebo"]["ri_p_school"] <= 1
    assert results["power"]["mde_sd_school"] > 0
    assert results["placebo"]["n_places"] == 13 * 2 * 3  # municipal places, 2012-2020
    assert not any("." in k for k in all_keys(results))

    write_results(tmp_path, rf._summary(results), results)
    on_disk = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert on_disk["counts"]["pairs_050"] == 52
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| RO |" in summary and "| AC |" in summary


def test_script_follows_the_explore_rules():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source
    assert "terrain.registered" not in source
    assert "native_10km" not in source
    assert all("native" not in c for cols in rf.USE_COLUMNS.values() for c in cols)
    assert rf.SEED == 20261110 and rf.DRAWS == 2000 and rf.WINDOW == 0.005
