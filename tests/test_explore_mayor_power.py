import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mayor_power", REPO / "explore" / "0003_mayor_power.py"
)
mp = importlib.util.module_from_spec(SPEC)
sys.modules["mayor_power"] = mp
SPEC.loader.exec_module(mp)

MAIN = 30


def cv_rows(rows):
    """rows: (sg_ue, cd_eleicao, turno, cargo, cand, nominais, validos, dest, status)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [r[1] for r in rows],
            "nr_turno": [r[2] for r in rows],
            "sg_ue": [r[0] for r in rows],
            "cd_ibge": ["1500107"] * len(rows),
            "cd_cargo": [r[3] for r in rows],
            "sq_candidato": [r[4] for r in rows],
            "qt_votos_nominais": [r[5] for r in rows],
            "qt_votos_nominais_validos": [r[6] for r in rows],
            "nm_tipo_destinacao_votos": [r[7] for r in rows],
            "ds_sit_tot_turno": [r[8] for r in rows],
        }
    )


def test_pre_years_never_include_the_election():
    assert mp.pre_years(2008) == [2004, 2005, 2006, 2007]
    asked = []

    def read(year):
        asked.append(year)
        return pl.DataFrame()

    for e in mp.ELECTIONS:
        asked.clear()
        mp.outcome_tables(e, read)
        assert asked == mp.pre_years(e)
        assert e not in asked and max(asked) == e - 1


def test_deciding_round():
    rows = cv_rows(
        [
            ("A", MAIN, 1, 11, "1", 40, 40, "Válido", "2º TURNO"),
            ("A", MAIN, 1, 11, "2", 39, 39, "Válido", "2º TURNO"),
            ("A", MAIN + 1, 2, 11, "1", 50, 50, "Válido", "ELEITO"),
            ("A", MAIN + 1, 2, 11, "2", 49, 49, "Válido", "NÃO ELEITO"),
            ("B", MAIN, 1, 11, "3", 60, 60, "Válido", "ELEITO"),
            ("B", MAIN, 1, 11, "4", 30, 30, "Válido", "NÃO ELEITO"),
            ("C", 445, 2, 11, "5", 10, 10, "Válido", "ELEITO"),  # another id
            ("D", 99, 1, 11, "6", 70, 70, "Válido", "ELEITO"),  # supplementary
            ("B", MAIN, 1, 13, "7", 5, 5, "Válido", "ELEITO"),  # council
        ]
    )
    chosen, other = mp.deciding_round(rows, MAIN)
    assert other == 1
    assert sorted(chosen["sg_ue"].unique().to_list()) == ["A", "B"]
    a = chosen.filter(pl.col("sg_ue") == "A")
    assert set(a["nr_turno"]) == {2} and a["runoff"].all()
    b = chosen.filter(pl.col("sg_ue") == "B")
    assert set(b["nr_turno"]) == {1} and not b["runoff"].any()
    votes, _ = mp.candidacy_votes_mayor(chosen, 2012)
    turnout = pl.DataFrame(
        {
            "cd_eleicao": [MAIN, MAIN + 1, MAIN, MAIN + 1],
            "nr_turno": [1, 2, 1, 2],
            "sg_ue": ["A", "A", "B", "B"],
            "cd_ibge": ["1500107"] * 4,
            "cd_cargo": [11, 11, 11, 11],
            "qt_total_votos_validos": [100, 100, 100, 7],
        }
    )
    valid = mp.valid_votes_mayor(turnout, chosen)
    table, counts = mp.races(votes, valid)
    got = dict(zip(table["sg_ue"], table["margin"], strict=True))
    assert math.isclose(got["A"], 0.01)  # round 2: (50 - 49) / 100
    assert math.isclose(got["B"], 0.30)  # round 1: (60 - 30) / 100
    assert counts["runoff_races"] == 1


def test_votes_come_from_valid_rows_in_2016_and_2020():
    rows = cv_rows(
        [
            ("A", MAIN, 1, 11, "1", 100, 50, "Válido", "ELEITO"),
            ("A", MAIN, 1, 11, "2", 60, 60, "Válido", "NÃO ELEITO"),
            ("A", MAIN, 1, 11, "2", 5, 5, "Válido", "NÃO ELEITO"),
            ("A", MAIN, 1, 11, "2", 99, 99, "Anulado", "NÃO ELEITO"),
            ("A", MAIN, 1, 11, "3", 500, 500, "Anulado", "NÃO ELEITO"),
        ]
    )
    votes, left_out = mp.candidacy_votes_mayor(rows.with_columns(runoff=pl.lit(False)), 2016)
    assert left_out == 2
    by = dict(zip(votes["sq_candidato"], votes["votes"], strict=True))
    assert by == {"1": 50.0, "2": 65.0}  # 3 has no valid row; the annulled row is not counted
    old, left_old = mp.candidacy_votes_mayor(rows.with_columns(runoff=pl.lit(False)), 2012)
    assert left_old == 0
    assert dict(zip(old["sq_candidato"], old["votes"], strict=True))["1"] == 100.0


def _votes(spec):
    return pl.DataFrame(
        {
            "sg_ue": [s[0] for s in spec],
            "sq_candidato": [s[1] for s in spec],
            "votes": [float(s[2]) for s in spec],
            "status": [s[3] for s in spec],
            "cd_ibge": ["1500107"] * len(spec),
            "runoff": [False] * len(spec),
        }
    )


def test_races_margin_one_candidacy_tie_and_status():
    votes = _votes(
        [
            ("A", "1", 55, "ELEITO"),
            ("A", "2", 45, "NÃO ELEITO"),
            ("B", "1", 90, "ELEITO"),
            ("C", "5", 40, "NÃO ELEITO"),
            ("C", "4", 40, "ELEITO"),
            ("C", "9", 10, "NÃO ELEITO"),
            ("D", "1", 30, "NÃO ELEITO"),
            ("D", "2", 20, "ELEITO"),
        ]
    )
    valid = pl.DataFrame({"sg_ue": ["A", "B", "C", "D"], "valid": [100.0, 90.0, 100.0, 50.0]})
    table, counts = mp.races(votes, valid)
    got = dict(zip(table["sg_ue"], table["margin"], strict=True))
    assert set(got) == {"A", "C", "D"}
    assert math.isclose(got["A"], 0.10)
    assert got["C"] == 0.0
    assert math.isclose(got["D"], 0.20)
    assert counts["one_candidacy"] == 1
    assert counts["ties"] == 1
    # the tie is broken by sq_candidato: "4" (ELEITO) is first
    assert counts["first_not_eleito"] == 1  # D, kept in the table


def cells(year, rows):
    """rows: (cell, cd_ibge, has_data, code_2, code_4)."""
    return pl.DataFrame(
        {
            "nome_1KM": [r[0] for r in rows],
            "cd_ibge": [r[1] for r in rows],
            "has_data": [r[2] for r in rows],
            "code_2": [r[3] for r in rows],
            "code_4": [r[4] for r in rows],
        }
    )


def test_outcome_formula_missing_data_and_zero_denominator():
    e = 2008
    by_year = {
        2004: cells(
            2004, [("c1", "M1", True, 6, 4), ("c2", "M1", True, 10, 0), ("c3", "M1", True, 1, 1)]
        ),
        2005: cells(
            2005, [("c1", "M1", True, 0, 2), ("c2", "M1", True, 0, 0), ("c3", "M1", False, 0, 50)]
        ),
        2006: cells(
            2006, [("c1", "M1", True, 0, 1), ("c2", "M1", True, 0, 0), ("c3", "M1", True, 0, 50)]
        ),
        2007: cells(
            2007, [("c1", "M1", True, 0, 3), ("c2", "M1", True, 0, 0), ("c3", "M1", True, 0, 50)]
        ),
    }
    y = mp.outcome(by_year, e)
    # c3 has no data in 2005 and is left out; c1 + c2: (4+2+1+3) / ((6+4) + (10+0))
    assert math.isclose(y.filter(pl.col("cd_ibge") == "M1")["Y"].item(), 10 / 20)
    zero = {yr: cells(yr, [("z", "M2", True, 0, 0)]) for yr in mp.pre_years(e)}
    none = {yr: cells(yr, [("n", "M3", yr != 2006, 1, 1)]) for yr in mp.pre_years(e)}
    both = {yr: pl.concat([zero[yr], none[yr]]) for yr in mp.pre_years(e)}
    y2 = mp.outcome(both, e)
    assert y2.filter(pl.col("cd_ibge") == "M2")["Y"].item() is None
    assert y2.filter(pl.col("cd_ibge") == "M3")["Y"].item() is None
    race_table = pl.DataFrame(
        {
            "sg_ue": ["a", "b"],
            "cd_ibge": ["M2", "M3"],
            "runoff": [False, False],
            "margin": [0.001, 0.002],
        }
    )
    attached = mp.attach_outcome(race_table, y2)
    assert mp.close_races(attached)["Y"].null_count() == 2


def _table():
    rng = np.random.default_rng(1)
    parts = []
    for n in (40, 30):
        parts.append(
            pl.DataFrame(
                {
                    "sg_ue": [f"{i:03d}" for i in range(n)][::-1],
                    "cd_ibge": ["x"] * n,
                    "runoff": [False] * n,
                    "margin": rng.uniform(-0.02, 0.02, n),
                    "Y": rng.uniform(0, 1, n),
                }
            )
        )
    per = {
        2008: parts[0],
        2012: parts[1].with_columns(
            Y=pl.when(pl.col("sg_ue") == "005").then(None).otherwise(pl.col("Y"))
        ),
    }
    return mp.window_ids(per)


def test_window_ids_and_nested_deltas():
    table = _table()
    assert table.height == 69  # the null-Y race is dropped before numbering
    assert table["id"].to_list() == list(range(69))
    assert table.filter(pl.col("election") == 2008)["id"].max() == 39
    signs = mp.sign_draws(table.height, np.random.default_rng(3), draws=50)
    narrow = mp.window_deltas(table, 0.005, signs)
    inner = mp.window_table(table, 0.005)
    assert 0 < inner.height < table.height
    for r in range(50):
        s = signs[r][inner["id"].to_numpy()]
        expected = mp.delta(inner["ytilde"].to_numpy(), s)
        assert (np.isnan(expected) and np.isnan(narrow[r])) or math.isclose(expected, narrow[r])
    # same races, same ids, whichever window selects them
    wide_rows = mp.window_table(table, 0.02).filter(pl.col("id").is_in(inner["id"].implode()))
    assert wide_rows["id"].to_list() == inner["id"].to_list()


def test_power_and_mde_formulas_and_sd_of_flips():
    stats = mp.power_stats(np.array([-1.0, 1.0, -2.0, 2.0]), 0.5)
    sd = float(np.std([-1.0, 1.0, -2.0, 2.0], ddof=1))
    assert math.isclose(stats["sd_ri"], sd)
    assert math.isclose(stats["mde"], 2.8 * sd)
    assert math.isclose(stats["mde_pct_of_ybar"], 100 * 2.8 * sd / 0.5)
    assert math.isclose(stats["power"], NormalDist().cdf(0.08 * 0.5 / sd - 1.96))
    n = 100
    yt = np.array([1.0] * (n // 2) + [-1.0] * (n // 2))
    table = pl.DataFrame(
        {
            "election": [2008] * n,
            "id": list(range(n)),
            "margin": [0.0] * n,
            "Y": yt.tolist(),
            "runoff": [False] * n,
        }
    )
    signs = mp.sign_draws(n, np.random.default_rng(mp.SEED))
    d = mp.window_deltas(table, 0.02, signs)
    assert abs(np.nanstd(d, ddof=1) - 2 / math.sqrt(n)) < 0.02


def test_no_observed_estimate_in_results(tmp_path):
    per = {}
    counts = {}
    rng = np.random.default_rng(5)
    for e in mp.ELECTIONS:
        n = 20
        per[e] = pl.DataFrame(
            {
                "sg_ue": [f"{i:03d}" for i in range(n)],
                "cd_ibge": ["x"] * n,
                "runoff": [i % 5 == 0 for i in range(n)],
                "margin": rng.uniform(-0.03, 0.03, n),
                "Y": rng.uniform(0.1, 1, n),
            }
        )
        counts[e] = {
            "one_candidacy": 0,
            "ties": 0,
            "no_valid_votes": 0,
            "first_not_eleito": 0,
            "runoff_races": 4,
            "races": n,
            "round2_rows_other_ids": 0,
            "annulled_rows_left_out": 0,
        }
    results = mp.build_results(per, counts)
    summary = mp._summary(results)
    mp.write_results(tmp_path, summary, results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert set(data["windows"]) == {"0.5%", "1%", "2%"}
    assert "observed" not in text.lower() and "estimate" not in " ".join(data)
    for r in data["windows"].values():
        assert "delta" not in r and "beta" not in r
    assert summary.startswith("Power at 8%")
