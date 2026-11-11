import importlib.util
import json
import sys
from pathlib import Path

import polars as pl

from terrain.explore import write_results

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0007_gold_feasibility.py"
SPEC = importlib.util.spec_from_file_location("gold_feasibility", SCRIPT)
gf = importlib.util.module_from_spec(SPEC)
sys.modules["gold_feasibility"] = gf
SPEC.loader.exec_module(gf)

# --- gold_exposure: 14 municipalities in the half (PA 11, MT 3), 5 outside it

PA = [f"15{i:05d}" for i in range(1, 12)]  # 1500001 .. 1500011
MT = ["5100001", "5100002", "5100003"]
OUTSIDE = [f"15000{i}" for i in range(90, 95)]
HALF = frozenset(PA + MT)

# (title_n_gold, dated, pre2000, garimpo_pre2000) of the municipalities that have titles
TITLES = {
    "1500001": (4, 3, 1, 0),
    "1500002": (6, 6, 2, 1),
    "5100001": (2, 1, 0, 0),
}


def exposure_frame(geo_codes, with_outside=True):
    rows = []
    for code in PA + MT + (OUTSIDE if with_outside else []):
        outside = code in OUTSIDE
        gold, dated, pre, garimpo = (100, 0, 50, 50) if outside else TITLES.get(code, (0, 0, 0, 0))
        rows.append(
            {
                "cd_ibge": code,
                "uf": "PA" if code.startswith("15") else "MT",
                "geo_exposed": code in geo_codes or outside,
                "title_exposed": pre >= 1,
                "title_n_gold": gold,
                "title_n_gold_dated": dated,
                "title_n_gold_pre2000": pre,
                "title_n_garimpo_pre2000": garimpo,
            }
        )
    return pl.DataFrame(rows)


GEO = set(PA[:10]) | {"5100001", "5100002"}  # 12 in the half; PA 10, MT 2

PRICES = pl.DataFrame(
    {
        "year": [1984, 1985, 2000, 2011, 2025, 2026],
        "gold_real": [9999.0, 1000.0, 700.0, 2500.0, 2000.0, 5000.0],
    }
)

# --- Elections: four municipalities, each with one list holding a close or a wide pair

MUNIS = [  # (cd_ibge, sg_ue)
    ("1500001", "10001"),
    ("1500011", "10011"),
    ("5100001", "51001"),
    ("1500090", "10090"),
]
CLOSE_YEARS = (2008, 2012, 2020)  # 1500001 has a close pair only in these elections


def gap(code, year):
    close = code in ("1500011", "1500090") or (code == "1500001" and year in CLOSE_YEARS)
    return 2 if close else 100


def election_tables(year):
    elected, other = (1, 2) if year == 2008 else (2, 4)
    cv, turnout = [], []
    for code, ue in MUNIS:
        base = {
            "cd_cargo": 13,
            "nr_turno": 1,
            "cd_eleicao": 1,
            "sq_coligacao": f"c{ue}",
            "sg_ue": ue,
            "cd_ibge": code,
        }
        cv.append(
            {
                **base,
                "cd_sit_tot_turno": elected,
                "sq_candidato": f"e{ue}",
                "qt_votos_nominais": 200,
            }
        )
        cv.append(
            {
                **base,
                "cd_sit_tot_turno": other,
                "sq_candidato": f"o{ue}",
                "qt_votos_nominais": 200 - gap(code, year),
            }
        )
        turnout.append({**base, "qt_total_votos_validos": 1000})
    turnout = pl.DataFrame(turnout).drop("sq_coligacao")
    return pl.DataFrame(cv), turnout


def all_tables():
    cv, turnout = {}, {}
    for year in gf.CANDIDATE_ELECTIONS:
        if year in gf.PAIR_ELECTIONS:
            cv[year], turnout[year] = election_tables(year)
        else:
            cv[year] = pl.DataFrame(MUNIS, schema=["cd_ibge", "sg_ue"], orient="row")
    return cv, turnout


def candidate(year, ue, cargo, code, text):
    return {
        "ano_eleicao": year,
        "sg_ue": ue,
        "cd_cargo": cargo,
        "cd_ocupacao": code,
        "ds_ocupacao": text,
    }


CANDS = pl.DataFrame(
    [
        candidate(2012, "10001", "13", "605", "GARIMPEIRO"),
        candidate(2012, "10001", "13", "253", "TRABALHADOR DE MINAS E PEDREIRAS"),
        candidate(2012, "10011", "13", "999", "garimpêiro de ouro"),  # accent and case
        candidate(2012, "51001", "13", "111", "AGRICULTOR"),
        candidate(2012, "10001", "11", "605", "GARIMPEIRO"),  # mayor, not council
        candidate(2012, "99999", "13", "605", "GARIMPEIRO"),  # no sg_ue match
        candidate(2012, "10090", "13", "605", "GARIMPEIRO"),  # outside the half
        candidate(2000, "10001", "13", "605", "OUTRO"),  # code 605 with another text
    ]
)


def run(exposure):
    cv, turnout = all_tables()
    return gf.build_results(exposure, PRICES, cv, turnout, CANDS, HALF)


def at(results, path):
    node = results
    for part in path.split("."):
        node = node[part]
    return node


# --- Tests


def test_exposure_counts_drop_rows_outside_the_half():
    results = run(exposure_frame(GEO))
    assert at(results, "exposure.n_munis_exposed") == 12  # the 5 outside rows are exposed too
    assert at(results, "exposure.n_munis_half") == 14
    assert at(results, "exposure.by_state") == {"MT": 2, "PA": 10}
    assert at(results, "exposure.n_states_10plus") == 1
    assert at(results, "exposure.top_state") == "PA"
    assert at(results, "exposure.top_state_share") == 10 / 12
    assert at(results, "exposure.n_munis_title_exposed") == 2
    assert at(results, "exposure.n_munis_both") == 2


def test_title_counts_drop_rows_outside_the_half():
    results = run(exposure_frame(GEO))
    assert at(results, "titles.share_dated") == 10 / 12
    assert at(results, "titles.n_pre2000") == 3
    assert at(results, "titles.n_garimpo_pre2000") == 1


def test_close_pairs_in_exposed_municipalities():
    results = run(exposure_frame(GEO))
    by_year = at(results, "pairs.n_050_exposed_by_year")
    # 1500001 is exposed and close in 2008, 2012, 2020; 1500011 is not exposed; 5100001 is
    # exposed but wide; 1500090 is outside the half
    assert by_year == {"y2008": 1, "y2012": 1, "y2016": 0, "y2020": 1, "y2024": 0}
    assert at(results, "pairs.n_050_exposed") == 3


def test_occupation_counts_are_pooled_and_matched_to_the_half():
    results = run(exposure_frame(GEO))
    mining = at(results, "candidates.n_mining_occupation")
    desc = at(results, "candidates.n_desc_garimpeiro")
    unmatched = at(results, "candidates.n_council_not_in_half")
    assert set(mining) == {f"y{y}" for y in gf.CANDIDATE_ELECTIONS} == set(desc)
    assert mining["y2012"] == 2  # codes 605 and 253; not the mayor, not the unmatched
    assert desc["y2012"] == 2  # "GARIMPEIRO" and the lower-case accented text
    assert (mining["y2000"], desc["y2000"]) == (1, 0)
    assert unmatched["y2012"] == 2  # sg_ue without a row, and a municipality outside the half
    assert unmatched["y2000"] == 0
    assert all(v == 0 for k, v in mining.items() if k not in ("y2000", "y2012"))


def test_occupation_counts_do_not_depend_on_exposure():
    assert (
        run(exposure_frame(GEO))["candidates"]
        == run(exposure_frame(set(), with_outside=False))["candidates"]
    )


def test_price_stats_use_1985_to_2025():
    stats = at(run(exposure_frame(GEO)), "price")
    assert stats == {
        "n_years": 4,
        "first_year": 1985,
        "last_year": 2025,
        "min_real": 700.0,
        "max_real": 2500.0,
        "min_year": 2000,
        "max_year": 2011,
    }


def test_kill_rule_fields_are_numbers(tmp_path):
    results = run(exposure_frame(GEO))
    write_results(tmp_path, gf._summary(results), results)
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    for path in (
        "exposure.n_munis_exposed",
        "exposure.n_states_10plus",
        "titles.share_dated",
        "exposure.top_state_share",
    ):
        value = at(saved, path)
        assert isinstance(value, (int, float)) and not isinstance(value, bool), path
    assert saved["estimates"]["finite"] is True
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "No outcome data was read" in summary
    assert "counts in both" in summary


def test_nothing_exposed():
    exposure = exposure_frame(set(), with_outside=False).with_columns(
        pl.lit(False).alias("geo_exposed"),
        pl.lit(0).alias("title_n_gold"),
        pl.lit(0).alias("title_n_gold_dated"),
    )
    results = run(exposure)
    assert at(results, "exposure.n_munis_exposed") == 0
    assert at(results, "exposure.n_states_10plus") == 0
    assert at(results, "exposure.top_state_share") == 1.0
    assert at(results, "exposure.by_state") == {}
    share = at(results, "titles.share_dated")
    assert isinstance(share, float) and share == 0.0
    assert at(results, "pairs.n_050_exposed") == 0
    assert at(results, "estimates.finite") is True


def test_pairs_in_counts_only_listed_municipalities():
    pairs = pl.DataFrame({"cd_ibge": ["1", "1", "2"]})
    assert gf.pairs_in(pairs, frozenset({"1"})) == 2
    assert gf.pairs_in(pairs, frozenset()) == 0
