import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("window", REPO / "explore" / "0001_window.py")
wn = importlib.util.module_from_spec(SPEC)
sys.modules["window"] = wn
SPEC.loader.exec_module(wn)

DRAWS = 400


def normal_diffs(n_pairs, names=wn.COVARIATES, seed=1):
    return np.random.default_rng(seed).normal(size=(n_pairs, len(names)))


def spread_margins(n_pairs):
    return np.linspace(0.00005, 0.02, n_pairs)


# --- 1. The omnibus on balanced and unbalanced pairs


def test_balanced_covariates_give_a_high_omnibus_and_an_age_gap_stops_the_rule():
    n = 4000
    # Pairs come in twins with the same margin and opposite differences: every window
    # holds both twins or neither, so the covariates are exactly balanced.
    margin = np.repeat(spread_margins(n // 2), 2)
    diff = normal_diffs(n, seed=12)
    diff[1::2] = -diff[::2]
    signs = wn.sign_matrix(n, DRAWS, wn.SEED)
    balanced = wn.balance_by_window(diff, margin, signs)
    shown = [b["omnibus_p"] for b in balanced]
    assert all(p > 0.15 for p in shown), shown
    assert wn.choose_window([b["omnibus_p"] for b in balanced]) == "2.00%"

    older = diff.copy()
    age = wn.COVARIATES.index("age")
    older[:, age] = 8 * older[:, age] + 5 * (margin > 0.01)  # winners 5 years older above 1%
    shifted = wn.balance_by_window(older, margin, signs)
    ps = [b["omnibus_p"] for b in shifted]
    assert ps[wn.LABELS.index("1.00%")] > 0.15
    assert ps[wn.LABELS.index("1.50%")] < 0.15
    assert wn.choose_window(ps) == "1.00%"


# --- 2. The re-flip distribution of the minimum p


def reference_omnibus(diff, signs):
    r, n = signs.shape
    k = diff.shape[1]
    draws = np.array([[np.mean(signs[i] * diff[:, j]) for j in range(k)] for i in range(r)])
    observed = diff.mean(axis=0)
    p_obs = [
        (1 + sum(abs(draws[i, j]) >= abs(observed[j]) - 1e-12 for i in range(r))) / (1 + r)
        for j in range(k)
    ]
    smallest = min(p_obs)
    minimum = []
    for i in range(r):
        ps = [
            sum(abs(draws[s, j]) >= abs(draws[i, j]) - 1e-12 for s in range(r)) / r
            for j in range(k)
        ]
        minimum.append(min(ps))
    return (1 + sum(m <= smallest + 1e-12 for m in minimum)) / (1 + r), smallest


def test_omnibus_is_the_reflip_distribution_of_the_minimum_p():
    n, r = 300, 150
    diff = normal_diffs(n, wn.BALANCE, seed=8)
    signs = wn.sign_matrix(n, r, 5)
    got = wn.balance_by_window(diff, np.full(n, 0.001), signs, wn.BALANCE, (0.01,), ("w",))[0]
    expected, smallest = reference_omnibus(diff, signs)
    raw = [c["p"] for c in got["covariates"].values()]
    assert np.isclose(min(raw), smallest)
    assert np.isclose(got["omnibus_p"], expected)
    assert not np.isclose(got["omnibus_p"], min(raw))


# --- 3. One sign matrix and one numbering for every window


def test_pairs_keep_their_ids_and_draws_are_shared_across_windows():
    n = 500
    margin = spread_margins(n)
    wide = wn.window_pair_ids(margin, 0.02)
    narrow = wn.window_pair_ids(margin, 0.005)
    assert wide.tolist() == list(range(n))
    assert set(narrow) < set(wide)
    assert np.all(margin[narrow] <= 0.005 + 1e-12) and np.all(narrow == np.arange(narrow.size))
    diff = normal_diffs(n, seed=3)
    signs = wn.sign_matrix(n, 120, wn.SEED)
    _, in_narrow, _ = wn.flip_means(diff, signs, wn.window_mask(margin, 0.005))
    _, in_wide, _ = wn.flip_means(diff[narrow], signs[:, narrow], np.ones(narrow.size, dtype=bool))
    assert np.allclose(in_narrow, in_wide)
    again = wn.sign_matrix(n, 120, wn.SEED)
    assert np.array_equal(signs, again)


# --- 4. Outcome years


class Tracked(dict):
    def __init__(self, *args):
        super().__init__(*args)
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)


def outcome(rows):
    return pl.DataFrame(
        rows,
        schema={
            "nome_1KM": pl.Utf8,
            "has_data": pl.Boolean,
            "code_2": pl.UInt16,
            "code_4": pl.UInt16,
        },
        orient="row",
    )


def test_only_pre_election_years_are_read():
    assert wn.pre_years(2008) == [2004, 2005, 2006, 2007]
    asked = []

    def read_year(year):
        asked.append(year)
        return outcome([("a", True, 1, 1)])

    for election in wn.ELECTIONS:
        asked.clear()
        got = wn.read_pre_outcomes(read_year, election)
        assert asked == wn.pre_years(election) == sorted(got)
        assert election not in asked
    by_year = Tracked({y: outcome([("a", True, 1, 1)]) for y in range(2004, 2012)})
    wn.pre_clearing_cells(by_year, 2008)
    assert by_year.read == set(wn.pre_years(2008))


# --- 5. The rule


def test_rule_cases():
    assert wn.choose_window((0.50, 0.40, 0.20, 0.10, 0.30, 0.40, 0.50)) == "0.50%"
    assert wn.choose_window((0.50, 0.40, 0.10, 0.30, 0.20, 0.40, 0.50)) == "0.25%"
    assert wn.choose_window((0.10, 0.40, 0.50, 0.30, 0.20, 0.40, 0.50)) == wn.NO_WINDOW
    assert wn.rule_line((0.10, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9)) == "No window passes; Gabriel decides"
    assert wn.choose_window((0.9, None, 0.9, 0.9, 0.9, 0.9, 0.9)) == "0.10%"
    assert wn.rule_line((0.5, 0.4, 0.2, 0.1, 0.3, 0.4, 0.5)).startswith("Chosen window: 0.50%")


# --- 6. Incumbents


def candidates(rows):
    return pl.DataFrame(
        [
            (year, cd, 1, "13", ue, sq, voter, status, "S" if year == 2008 and sq == "9" else None)
            for year, cd, ue, sq, voter, status in rows
        ],
        schema={
            "ano_eleicao": pl.Int32,
            "cd_eleicao": pl.Int32,
            "nr_turno": pl.Int32,
            "cd_cargo": pl.Utf8,
            "sg_ue": pl.Utf8,
            "sq_candidato": pl.Utf8,
            "nr_titulo_eleitoral_candidato": pl.Utf8,
            "ds_sit_tot_turno": pl.Utf8,
            "st_reeleicao": pl.Utf8,
        },
        orient="row",
    )


def test_incumbent_uses_labels_voter_ids_and_the_same_municipality():
    cands = candidates(
        [
            (2004, 11, "A", "1", "V-MEDIA", "MÉDIA"),  # code 5 in 2004
            (2004, 11, "B", "2", "V-OTHER", "ELEITO"),  # elected, but in B
            (2004, 11, "A", "3", "V-SUPL", "SUPLENTE"),  # code 5 is SUPLENTE in 2008
            (2004, 11, "A", "4", "V-LOSER", "NÃO ELEITO"),
            (2008, 21, "A", "5", "V-MEDIA", "ELEITO POR QP"),
            (2008, 21, "A", "6", "V-OTHER", "NÃO ELEITO"),
            (2008, 21, "A", "7", "V-SUPL", "NÃO ELEITO"),
            (2008, 21, "A", "8", "V-LOSER", "ELEITO"),
            (2008, 21, "A", "9", None, "MÉDIA"),  # code 3 in 2008, no voter ID
            (2008, 21, "C", "10", "V-NEW", "MÉDIA"),
            (2012, 31, "C", "11", "V-NEW", "ELEITO"),
            (2012, 31, "A", "12", "V-SUPL", "ELEITO"),
        ]
    )
    in_2008 = dict(wn.incumbent(cands, 2008).select("sq_candidato", "incumbent").iter_rows())
    assert in_2008["5"] == 1.0  # MÉDIA in 2004, same sg_ue
    assert in_2008["6"] == 0.0  # elected in another sg_ue
    assert in_2008["7"] == 0.0  # SUPLENTE in 2004
    assert in_2008["8"] == 0.0 and in_2008["9"] is None
    in_2012 = dict(wn.incumbent(cands, 2012).select("sq_candidato", "incumbent").iter_rows())
    assert in_2012["11"] == 1.0  # MÉDIA (code 3) in 2008
    assert in_2012["12"] == 0.0
    assert set(wn.incumbent(cands, 2008).columns) == {
        "cd_eleicao",
        "sg_ue",
        "sq_candidato",
        "incumbent",
    }
    assert wn.incumbent(cands, 2000)["incumbent"].null_count() == 0  # no rows for 2000


def test_candidate_covariates():
    cands = pl.DataFrame(
        {
            "cd_eleicao": [1, 1, 1],
            "sg_ue": ["A", "A", "A"],
            "sq_candidato": ["1", "2", "3"],
            "cd_genero": ["4", "2", None],
            "dt_eleicao": [dt.date(2020, 11, 15)] * 3,
            "dt_nascimento": [dt.date(1980, 11, 15), None, dt.date(1990, 1, 1)],
            "cd_grau_instrucao": ["8", "1", "4"],
        }
    )
    got = wn.candidate_covariates(cands)
    assert got["female"].to_list() == [1.0, 0.0, None]
    assert got["schooling"].to_list() == [8.0, 1.0, 4.0]
    assert abs(got["age"][0] - 40.0) < 0.01 and got["age"][1] is None


# --- 7. The disc and the clearing


def test_disc_edge_and_cells_missing_a_pre_year():
    cells = pl.DataFrame(
        {
            "nome_1KM": ["c1", "c2", "c3"],
            "x_km": [5, 0, 5],
            "y_km": [0, 0, 100],
            "pop_2022": [7, 3, 1000],
        }
    )
    by_year = {}
    for year, c4 in zip(range(2004, 2008), (10, 20, 30, 40), strict=True):
        rows = [("c1", year != 2006, 100, c4), ("c2", True, 100, c4), ("c3", True, 100, c4)]
        if year == 2005:
            rows = [r for r in rows if r[0] != "c3"]  # absent in one pre year
        by_year[year] = outcome(rows)
    clearing = wn.pre_clearing_cells(by_year, 2008)
    assert clearing["nome_1KM"].to_list() == ["c2"]  # c1 has no data in 2006, c3 is absent in 2005
    pop, ratio = wn.disc_covariates(
        cells, clearing, np.array([0.5, 0.49, 50.0]), np.array([0.5, 0.5, 50.0])
    )
    # c1's centre is exactly 5 km from the first stronghold and 5.01 km from the second.
    assert pop.tolist() == [10.0, 3.0, 0.0]
    assert np.isclose(ratio[0], 100 / 110) and np.isclose(ratio[1], 100 / 110)
    assert np.isnan(ratio[2])


def test_disc_matches_a_direct_search():
    rng = np.random.default_rng(2)
    x = rng.integers(0, 40, 800)
    y = rng.integers(0, 40, 800)
    keep = np.unique(x * 100 + y, return_index=True)[1]
    x, y = x[keep], y[keep]
    value = rng.integers(1, 9, x.size).astype(float)
    index = wn.disc_index(x, y, {"v": value})
    sx, sy = rng.uniform(-3, 43, 60), rng.uniform(-3, 43, 60)
    got = wn.disc_sums(index, sx, sy)["v"]
    for i in range(sx.size):
        inside = np.hypot(x + 0.5 - sx[i], y + 0.5 - sy[i]) <= 5 + 1e-9
        assert got[i] == value[inside].sum()


# --- 8. The descriptive covariate and the voter IDs


def test_pop22_never_enters_the_omnibus():
    n = 600
    margin = spread_margins(n)
    diff = normal_diffs(n, seed=4)
    signs = wn.sign_matrix(n, 100, wn.SEED)
    before = wn.balance_by_window(diff, margin, signs)
    moved = diff.copy()
    moved[:, wn.COVARIATES.index("pop22_5km")] = 1000 + 500 * np.arange(n)
    after = wn.balance_by_window(moved, margin, signs)
    assert [b["omnibus_p"] for b in before] == [b["omnibus_p"] for b in after]
    pop = wn.COVARIATES.index("pop22_5km")
    assert before[-1]["covariates"]["pop22_5km"]["p"] != after[-1]["covariates"]["pop22_5km"]["p"]
    assert not wn.DESCRIPTIVE or all(name not in wn.BALANCE for name in wn.DESCRIPTIVE)
    assert pop == len(wn.BALANCE)


def test_covariates_with_few_pairs_are_left_out():
    n = 300
    margin = spread_margins(n)
    diff = normal_diffs(n, seed=5)
    diff[:, 0] = np.nan  # female is missing for every pair
    signs = wn.sign_matrix(n, 60, wn.SEED)
    got = wn.balance_by_window(diff, margin, signs)
    assert all("female" in b["left_out"] for b in got)
    assert got[-1]["covariates"]["female"]["null_pairs"] == got[-1]["pairs"]
    assert got[-1]["omnibus_p"] is not None


def test_no_voter_id_reaches_the_outputs(tmp_path):
    ids = ["V-MEDIA", "V-OTHER", "V-SUPL", "V-LOSER", "V-NEW"]
    cands = candidates(
        [
            (2004, 11, "A", "1", ids[0], "MÉDIA"),
            (2008, 21, "A", "5", ids[0], "ELEITO"),
            (2008, 21, "A", "6", ids[1], "NÃO ELEITO"),
            (2008, 21, "A", "9", ids[2], "ELEITO"),
        ]
    )
    check = wn.incumbency_check(cands, 2008)
    assert check == {"candidates": 3, "st_reeleicao_S": 1, "incumbent": 1}
    n = 200
    margin = spread_margins(n)
    balance = wn.balance_by_window(normal_diffs(n), margin, wn.sign_matrix(n, 50, wn.SEED))
    power = {label: {"direct": None, "displacement": None, "split5": None} for label in wn.LABELS}
    pairs = wn.pair_counts({2008: margin})
    results = wn.build_results(balance, pairs, power, {"2008": check}, {"2008": 2})
    summary = wn._summary(results)
    from terrain.explore import write_results

    write_results(tmp_path, summary, results)
    written = (tmp_path / "summary.md").read_text(encoding="utf-8") + (
        tmp_path / "results.json"
    ).read_text(encoding="utf-8")
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["rule"]["line"]
    assert not any(i in written for i in ids)
    assert summary.splitlines()[0] == results["rule"]["line"]
    assert "decision 0007: 0.94, 0.797, 0.45" in summary
    # The script never formats a voter ID into a message.
    for line in (REPO / "explore" / "0001_window.py").read_text(encoding="utf-8").splitlines():
        if "voter" in line:
            assert not re.search(r"print\(|raise |f\"|f'|logging", line), line


# --- 9. Power


def test_power_formula():
    draws = np.random.default_rng(0).normal(0, 0.5, 2000)
    x_abs = np.full(10, 0.1)
    y = np.full(10, 0.02)
    got = wn.power_at(draws, x_abs, y, 1.96, 8.0)
    tau = 0.08 * 0.02 / 0.1
    sd = float(np.std(draws, ddof=1))
    assert np.isclose(got["tau"], tau)
    assert np.isclose(got["power"], NormalDist().cdf(tau / sd - 1.96))
    assert wn.power_at(np.array([np.nan, np.nan]), x_abs, y, 1.96, 8.0) is None
    assert wn.power_at(draws, np.zeros(0), y, 1.96, 8.0) is None


def test_pair_differences_and_unmatched_rows():
    pairs = pl.DataFrame(
        {
            "cd_ibge": ["1", "1"],
            "sg_ue": ["A", "A"],
            "cd_eleicao": [1, 1],
            "w": ["1", "3"],
            "l": ["2", "4"],
        }
    )
    cov = pl.DataFrame(
        {
            "cd_eleicao": [1, 1, 1, 1],
            "sg_ue": ["A"] * 4,
            "sq_candidato": ["1", "2", "3", "4"],
            "age": [50.0, 40.0, 30.0, None],
        }
    )
    got = wn.pair_differences(pairs, cov, ["age"])
    assert got[0, 0] == 10.0 and np.isnan(got[1, 0])
    cands = pl.DataFrame({"ano_eleicao": [2008, 2008, 2012], "sg_ue": ["A", "Z", "Z"]})
    munis = pl.DataFrame({"cd_ibge": ["1100001"], "cd_tse": ["A"]})
    joined, lost = wn.with_ibge(cands, munis)
    assert joined.height == 1 and lost == {"2008": 1, "2012": 1}
