import copy
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
SCRIPT = REPO / "explore" / "0006_effects.py"
SPEC = importlib.util.spec_from_file_location("representation_effects", SCRIPT)
fe = importlib.util.module_from_spec(SPEC)
sys.modules["representation_effects"] = fe
SPEC.loader.exec_module(fe)
fs = fe.fs

KEY = ["cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
DRAWS, BATCH = 200, 50


# --- A world built directly: one pair per municipality, planted effects, no noise

MUNIS = 24
PLACES = 5  # places 1-3 are municipal schools, 4-5 state schools
WORLD_YEARS = (2008, 2012, 2016, 2020)


def world(tau=(2.5, 2.5, 2.5), builtup_nan=False):
    """data[year] as `load_election` gives it; tau is the effect for aligned, unaligned, unknown.

    n_fac_post = n_fac + tau_group * D + 0.5 S + 0.3 n_fac + muni effect on municipal schools;
    state schools get the same without D.
    """
    rng = np.random.default_rng(3)
    data = {}
    for year in WORLD_YEARS:
        labels = [fe.GROUPS[i % 3] for i in range(MUNIS)]
        reg_rows, triple_rows = [], []
        effect = rng.normal(size=MUNIS)
        for m in range(MUNIS):
            ibge, ue = f"11{m:05d}", str(10000 + m)
            for p in range(1, PLACES + 1):
                diff = float(rng.normal())
                s = float(rng.uniform(0.2, 0.8))
                municipal = p <= 3
                n0 = float(rng.integers(0, 10))
                tau_m = tau[m % 3] if municipal else 0.0
                lights_pre = float(rng.uniform(1, 5))
                reg_rows.append(
                    {
                        "cd_ibge": ibge,
                        "sg_ue": ue,
                        "nr_zona": 1,
                        "nr_local_votacao": p,
                        "D": diff,
                        "S": s,
                        "located_1km": True,
                        "school_id": f"S{m}{p}",
                        "rede": "3" if municipal else "2",
                        "n_fac": n0,
                        "n_fac_pre": None if year == 2008 else float(rng.integers(0, 10)),
                        "n_fac_post": n0 + tau_m * diff + 0.5 * s + 0.3 * n0 + effect[m],
                        "lights_pre": None if year < 2016 else lights_pre,
                        "lights_post": None if year < 2016 else lights_pre + float(rng.normal()),
                        "builtup0": float(rng.uniform()),
                        "builtup4": float("nan") if builtup_nan else float(rng.uniform()),
                        "native0": float(rng.uniform()),
                        "native4": float(rng.uniform()),
                    }
                )
                triple_rows.append(
                    {
                        "cd_ibge": ibge,
                        "sg_ue": ue,
                        "nr_zona": 1,
                        "nr_local_votacao": p,
                        "pair_id": m,
                        "diff": diff,
                    }
                )
        reg = pl.DataFrame(reg_rows, infer_schema_length=None)
        reg = reg.with_columns(
            pl.col("n_fac_pre").cast(pl.Float64),
            pl.col("lights_pre").cast(pl.Float64),
            pl.col("lights_post").cast(pl.Float64),
        )
        pairs = pl.DataFrame(
            {
                "cd_ibge": [f"11{m:05d}" for m in range(MUNIS)],
                "sg_ue": [str(10000 + m) for m in range(MUNIS)],
            }
        )
        view = {"pairs": pairs, "reg": reg, "triples": pl.DataFrame(triple_rows)}
        data[year] = {
            "year": year,
            "windows": {name: view for name in fe.WINDOWS},
            "align": labels,
        }
    return data


def run(data):
    return fe.compute(data, draws=DRAWS, seed=fe.SEED, batch=BATCH)


def test_primary_recovers_the_planted_effect_and_falsification_is_zero():
    est = run(world())["estimates"]
    for name in fe.WINDOWS:
        assert est["primary"][name]["beta"] == pytest.approx(2.5, abs=1e-8)
    fals = est["falsification"]["w050"]
    assert fals["beta"] == pytest.approx(0.0, abs=1e-8)
    prim = est["primary"]["w050"]
    assert prim["n_places"] == MUNIS * 3 * len(WORLD_YEARS)
    assert fals["n_places"] == MUNIS * 2 * len(WORLD_YEARS)
    assert prim["n_pairs"] == MUNIS * len(WORLD_YEARS)
    assert 0 < prim["ri_p"] <= 1


def test_effect_sd_is_beta_times_mean_abs_d_over_sd_pre():
    data = world()
    est = run(data)["estimates"]["primary"]["w050"]
    changes = []
    for year in (2012, 2016, 2020):
        reg = data[year]["windows"]["w050"]["reg"].filter(pl.col("rede") == "3")
        changes += (reg["n_fac"] - reg["n_fac_pre"]).to_list()
    sd = float(np.std(changes, ddof=1))
    assert est["sd_pre"] == pytest.approx(sd, abs=1e-12)
    assert est["effect_sd"] == pytest.approx(est["beta"] * est["mean_abs_d"] / sd, abs=1e-12)


def test_heterogeneity_recovers_group_effects_and_terms_add_to_d():
    data = world(tau=(3.0, 1.0, 2.0))
    het = run(data)["estimates"]["heterogeneity"]
    assert het["beta_aligned"] == pytest.approx(3.0, abs=1e-8)
    assert het["beta_unaligned"] == pytest.approx(1.0, abs=1e-8)
    assert het["diff"] == pytest.approx(2.0, abs=1e-8)
    for key in ("ri_p_aligned", "ri_p_unaligned", "ri_p_diff"):
        assert 0 < het[key] <= 1
    per = MUNIS // 3 * len(WORLD_YEARS)
    assert (het["n_pairs_aligned"], het["n_pairs_unaligned"], het["n_pairs_unknown"]) == (
        per,
        per,
        per,
    )
    assert het["n_places"] == MUNIS * 3 * len(WORLD_YEARS)

    design = fe.window_design(data, "w050")
    prep = fe.prepare_all(design, ("primary",))["primary"][0]
    labels = [g for y in sorted(data) for g in data[y]["align"]]
    group = np.array([fe.GROUPS.index(g) for g in labels])
    joint = fe.make_joint(prep, group)
    rng = np.random.default_rng(1)
    for sigma in (np.ones(design.n_pairs), rng.integers(0, 2, design.n_pairs) * 2.0 - 1.0):
        assert joint.d_columns(sigma).sum(axis=1) == pytest.approx(prep.d_raw(sigma), abs=1e-12)


def test_joint_with_one_group_gives_the_same_flips_and_slopes_as_the_primary():
    design = fe.window_design(world(), "w050")
    prep = fe.prepare_all(design, ("primary",))["primary"][0]
    joint = fe.make_joint(prep, np.zeros(design.n_pairs, dtype=np.int64))
    single = fs.ri_draws({"p": prep}, design.n_pairs, 60, fe.SEED, 20)["p"]
    triple = fe.joint_draws(joint, design.n_pairs, 60, fe.SEED, 20)
    assert triple[:, 0] == pytest.approx(single, abs=1e-9)
    assert np.isnan(triple[:, 1:]).all()  # empty groups have no variation


# --- Benjamini-Hochberg


def test_bh_matches_hand_values():
    # sorted 0.01, 0.03, 0.04 -> 0.03, 0.045, 0.04 -> monotone 0.03, 0.04, 0.04
    assert fe.bh_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.04, 0.04])
    # sorted 0.01, 0.04, 0.20 -> 0.03, 0.06, 0.20
    assert fe.bh_adjust([0.20, 0.01, 0.04]) == pytest.approx([0.20, 0.03, 0.06])
    assert fe.bh_adjust([0.9, 0.8, 0.7]) == pytest.approx([0.9, 0.9, 0.9])  # capped, monotone
    assert all(np.isnan(fe.bh_adjust([0.01, float("nan"), 0.03])))


def test_secondary_carries_bh_and_rejection_flags():
    sec = run(world())["estimates"]["secondary"]
    assert set(sec) == {"lights", "builtup", "native"}
    adjusted = fe.bh_adjust([sec[k]["ri_p"] for k in ("lights", "builtup", "native")])
    for k, bh in zip(("lights", "builtup", "native"), adjusted, strict=True):
        assert sec[k]["bh_p"] == pytest.approx(bh)
        assert sec[k]["bh_reject_05"] is (bh <= 0.05)
    assert sec["lights"]["n_places"] == MUNIS * 5 * 2  # located, 2016 and 2020 only


# --- Finite flag and keys


def all_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from all_keys(v)


def test_finite_is_false_with_a_nan_and_true_otherwise():
    results = run(world())
    est = results["estimates"]
    assert est["finite"] is True
    planted = copy.deepcopy(est)
    planted["secondary"]["native"]["beta"] = float("nan")
    assert fe.all_finite(planted) is False
    for where in (
        ("primary", "w025", "effect_sd"),
        ("secondary", "lights", "bh_p"),
        ("heterogeneity", "ri_p_diff"),
        ("falsification", "w050", "sd_pre"),
    ):
        broken = copy.deepcopy(est)
        node = broken
        for part in where[:-1]:
            node = node[part]
        node[where[-1]] = None
        assert fe.all_finite(broken) is False
    assert fe.all_finite(est) is True
    # a missing outcome in the data gives a missing estimate, so not finite
    assert run(world(builtup_nan=True))["estimates"]["finite"] is False


def test_results_have_every_key_and_none_has_a_dot(tmp_path):
    results = run(world())
    est = results["estimates"]
    assert set(est) == {"primary", "falsification", "secondary", "heterogeneity", "finite"}
    assert set(est["primary"]) == {"w050", "w025", "w100"}
    assert set(est["falsification"]) == {"w050"}
    block = {"beta", "ri_p", "clustered_se", "effect_sd", "sd_pre", "mean_abs_d"}
    block |= {"n_places", "n_pairs"}
    for e in (*est["primary"].values(), est["falsification"]["w050"]):
        assert set(e) == block
    for e in est["secondary"].values():
        assert set(e) == {"beta", "ri_p", "clustered_se", "bh_p", "bh_reject_05"} | {
            "mean_abs_d",
            "n_places",
            "n_pairs",
        }
    assert set(est["heterogeneity"]) == {
        "beta_aligned",
        "beta_unaligned",
        "diff",
        "ri_p_aligned",
        "ri_p_unaligned",
        "ri_p_diff",
        "n_pairs_aligned",
        "n_pairs_unaligned",
        "n_pairs_unknown",
        "n_places",
    }
    assert set(results["design"]) == {"windows", "draws", "seed", "elections", "outcome_years"}
    assert results["design"]["windows"] == {"w025": 0.0025, "w050": 0.005, "w100": 0.01}
    assert results["design"]["seed"] == 20261110
    assert not any("." in k for k in all_keys(results))

    write_results(tmp_path, fe._summary(results), results)
    on_disk = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert on_disk["estimates"]["finite"] is True
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary.index("Primary") < summary.index("Falsification")
    assert "reason to register, not a finding" in summary


# --- The reader and the small store world

HALF_MUNIS = [f"11{m:05d}" for m in range(6)]
OUTSIDE = "3500001"
EVERY = [*HALF_MUNIS, OUTSIDE]
HALF = frozenset(HALF_MUNIS)
UE = {code: str(10001 + i) for i, code in enumerate(EVERY)}
GAP = {0: 100, 1: 100, 2: 400, 3: 400, 4: 800, 5: 3000, 6: 100}  # margin = gap / 100,000
PLACE_NUMBERS = (1, 2, 3, 4)


def council_and_mayor_votes(year):
    rows = []
    base = dict.fromkeys(
        [
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "sg_ue",
            "cd_ibge",
            "sq_candidato",
            "sq_coligacao",
            "qt_votos_nominais",
            "qt_votos_nominais_validos",
            "nm_tipo_destinacao_votos",
            "cd_sit_tot_turno",
            "ds_sit_tot_turno",
        ]
    )
    for i, code in enumerate(EVERY):
        ue = UE[code]
        common = {**base, "nr_turno": 1, "cd_eleicao": year, "sg_ue": ue, "cd_ibge": code}
        rows.append(
            {
                **common,
                "cd_cargo": 13,
                "sq_candidato": f"{ue}1",
                "sq_coligacao": "7",
                "qt_votos_nominais": 1000 + GAP[i],
                "cd_sit_tot_turno": 2,
            }
        )
        rows.append(
            {
                **common,
                "cd_cargo": 13,
                "sq_candidato": f"{ue}2",
                "sq_coligacao": "7",
                "qt_votos_nominais": 1000,
                "cd_sit_tot_turno": 4,
            }
        )
        rows.append(
            {
                **common,
                "cd_cargo": 11,
                "sq_candidato": f"{ue}M",
                "qt_votos_nominais": 500,
                "qt_votos_nominais_validos": 500,
                "nm_tipo_destinacao_votos": "Válido",
                "ds_sit_tot_turno": "ELEITO",
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def turnout(year):
    return pl.DataFrame(
        [(13, 1, year, UE[c], c, 100_000) for c in EVERY],
        schema=["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "cd_ibge", "qt_total_votos_validos"],
        orient="row",
    )


def candidates(year):
    """Winners' parties: muni 3's winner has no party row; muni 2's mayor coalition is party 20."""
    rows = []
    for i, code in enumerate(EVERY):
        ue = UE[code]
        common = {
            "ano_eleicao": year,
            "cd_eleicao": year,
            "nr_turno": 1,
            "sg_ue": ue,
            "cd_ibge": code,
        }
        cand = {**common, "nr_federacao": None, "sq_coligacao": "7"}
        if i != 3:
            rows.append({**cand, "cd_cargo": 13, "sq_candidato": f"{ue}1", "nr_partido": "10"})
        rows.append({**cand, "cd_cargo": 13, "sq_candidato": f"{ue}2", "nr_partido": "20"})
        rows.append(
            {
                **cand,
                "cd_cargo": 11,
                "sq_candidato": f"{ue}M",
                "nr_partido": "20" if i == 2 else "10",
                "sq_coligacao": "M1",
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def coalitions(year):
    rows = []
    for i, code in enumerate(EVERY):
        parties = ["20"] if i == 2 else ["10", "11"]
        rows += [
            {
                "cd_eleicao": year,
                "cd_cargo": 11,
                "sg_ue": UE[code],
                "cd_ibge": code,
                "sq_coligacao": "M1",
                "nr_partido": party,
                "nr_federacao": None,
            }
            for party in parties
        ]
    return pl.DataFrame(rows, schema_overrides={"nr_federacao": pl.Utf8})


def section_votes(year):
    rows = []
    for i, code in enumerate(EVERY):
        for p in PLACE_NUMBERS:
            for section in (1, 2):
                for side, cand in ((0, "1"), (1, "2"), (2, "3")):
                    v = 2 * (10 + (3 * i + 5 * p + 7 * side + year // 4) % 40)
                    rows.append((f"{UE[code]}{cand}", v // 2, "candidate", code, p, section))
                rows.append((None, 5, "legend", code, p, section))
    return pl.DataFrame(
        [
            {
                "cd_eleicao": year,
                "nr_turno": 1,
                "cd_cargo": 13,
                "sg_ue": UE[code],
                "cd_ibge": code,
                "nr_zona": "1",
                "nr_secao": f"{p}{section}",
                "nr_local_votacao": p,
                "vote_type": vt,
                "annulled_in_results": False,
                "sq_candidato": cand,
                "qt_votos": v,
            }
            for cand, v, vt, code, p, section in rows
        ]
    )


def place_outcomes(election, y):
    rows = []
    for i, code in enumerate(EVERY):
        for p in PLACE_NUMBERS:
            has_school = p < 4
            rows.append(
                {
                    "cd_ibge": code,
                    "sg_ue": UE[code],
                    "nr_zona": 1,
                    "nr_local_votacao": p,
                    "located_1km": p < 4,
                    "school_id": f"S{i}{p}" if has_school else None,
                    "school_rede": ("3" if p < 3 else "2") if has_school else None,
                    "school_n_fac": (3 * i + 5 * p + 2 * y + election % 7) % 10
                    if has_school
                    else None,
                    "lights_1km": float(y - 2000 + i + p),
                    "builtup_1km": ((13 * i + 7 * p + election + y) % 17) / 17,
                    "native_10km": ((5 * i + 3 * p + y) % 11) / 11,
                }
            )
    return pl.DataFrame(rows)


class FakeStore:
    """Serves the world and records every request."""

    def __init__(self):
        self.requests = []
        self.section_requests = []

    def read(self, manifest, pattern, columns=None):
        self.requests.append((manifest, pattern, None if columns is None else tuple(columns)))
        year = int(re.search(r"(\d{4})", pattern).group(1))
        if manifest == "place_outcomes":
            e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
            frame = place_outcomes(e, y)
        elif manifest == "tse_results":
            frame = council_and_mayor_votes(year) if "candidate_votes" in pattern else turnout(year)
        elif manifest == "tse_parties":
            frame = coalitions(year)
        else:
            raise AssertionError(f"unexpected manifest {manifest}")
        if columns is not None:
            frame = frame.select(columns)
        return restrict(frame, HALF)

    def read_sections(self, year, main, vote_munis):
        self.section_requests.append((year, main, vote_munis))
        return [fs.state_piece(section_votes(year).lazy(), main, HALF, vote_munis)]

    def read_candidates(self, year):
        return restrict(candidates(year), HALF)


def place_years(store, election, column=None):
    out = []
    for manifest, pattern, columns in store.requests:
        if manifest != "place_outcomes":
            continue
        e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
        if e == election and (column is None or column in columns):
            out.append(y)
    return sorted(out)


def load(store, year):
    return fe.load_election(store.read, store.read_sections, store.read_candidates, HALF, year)


def test_the_reader_refuses_years_outside_e_minus_4_to_e_plus_4():
    store = FakeStore()
    for use in ("school", "builtup", "lights", "native"):
        with pytest.raises(ValueError, match="outside"):
            fe.place_outcomes_year(store.read, 2016, 2011, use)
        with pytest.raises(ValueError, match="outside"):
            fe.place_outcomes_year(store.read, 2016, 2021, use)
        with pytest.raises(ValueError, match="outside"):
            fe.place_outcomes_year(store.read, 2020, 2025, use)
    with pytest.raises(ValueError, match="not read"):
        fe.place_outcomes_year(store.read, 2016, 2013, "builtup")
    with pytest.raises(ValueError, match="not read"):
        fe.place_outcomes_year(store.read, 2016, 2014, "school")
    with pytest.raises(ValueError, match="not read"):
        fe.place_outcomes_year(store.read, 2016, 2016, "lights")
    with pytest.raises(ValueError, match="unknown"):
        fe.outcome_years(2016, "other")
    assert store.requests == []


def test_outcome_years_by_use():
    assert fe.outcome_years(2008, "school") == [2008, 2012]  # INEP starts in 2007
    assert fe.outcome_years(2016, "school") == [2012, 2016, 2020]
    assert fe.outcome_years(2016, "builtup") == [2016, 2020]
    assert fe.outcome_years(2016, "native") == [2016, 2020]
    assert fe.outcome_years(2016, "lights") == [2013, 2014, 2015, 2017, 2018, 2019, 2020]
    assert fe.outcome_years(2020, "lights") == [2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024]
    assert fe.outcome_years(2012, "lights") == [2013, 2014, 2015, 2016]


def test_the_script_requests_only_the_listed_years_and_columns():
    store = FakeStore()
    for year in (2012, 2016):
        load(store, year)
    assert place_years(store, 2016, "lights_1km") == [2013, 2014, 2015, 2017, 2018, 2019, 2020]
    assert place_years(store, 2016, "school_n_fac") == [2012, 2016, 2020]
    assert place_years(store, 2016, "builtup_1km") == [2016, 2020]
    assert place_years(store, 2016, "native_10km") == [2016, 2020]
    assert place_years(store, 2012, "school_n_fac") == [2008, 2012, 2016]
    assert place_years(store, 2012, "lights_1km") == []  # not a lights election
    for manifest, pattern, columns in store.requests:
        if manifest == "place_outcomes":
            e, y = (int(x) for x in re.search(r"E(\d{4})_y(\d{4})", pattern).groups())
            assert e - 4 <= y <= e + 4
            assert columns is not None
    assert [r[0] for r in store.section_requests] == [2012, 2016]  # sections once per election


def test_windows_nest_and_alignment_follows_the_winner():
    store = FakeStore()
    got = load(store, 2016)
    sizes = {name: v["pairs"].height for name, v in got["windows"].items()}
    assert sizes == {"w025": 2, "w050": 4, "w100": 5}  # the outside municipality is not read
    w050 = got["windows"]["w050"]
    labels = dict(zip(w050["pairs"]["sg_ue"].to_list(), got["align"], strict=True))
    assert labels == {
        UE[HALF_MUNIS[0]]: "aligned",
        UE[HALF_MUNIS[1]]: "aligned",
        UE[HALF_MUNIS[2]]: "unaligned",  # winner's party 10 is not in the mayor's coalition {20}
        UE[HALF_MUNIS[3]]: "unknown",  # the winner has no party
    }
    assert set(w050["reg"]["cd_ibge"].to_list()) == set(HALF_MUNIS[:4])
    for column in ("n_fac", "n_fac_pre", "n_fac_post", "builtup0", "builtup4", "native0"):
        assert column in w050["reg"].columns
    data = {y: load(store, y) for y in (2012, 2016)}
    results = fe.compute(data, draws=40, seed=fe.SEED, batch=20)
    assert set(results["estimates"]) == {
        "primary",
        "falsification",
        "secondary",
        "heterogeneity",
        "finite",
    }


def test_lights_use_the_pre_and_post_means_of_the_years_read():
    store = FakeStore()
    out = fe.outcome_table(store.read, 2016)
    row = out.filter((pl.col("cd_ibge") == HALF_MUNIS[0]) & (pl.col("nr_local_votacao") == 1))
    # lights_1km = y - 2000 + i + p with i = 0, p = 1
    pre = np.mean([y - 2000 + 1 for y in (2013, 2014, 2015)])
    post = np.mean([y - 2000 + 1 for y in (2017, 2018, 2019, 2020)])
    assert row["lights_pre"][0] == pytest.approx(pre)
    assert row["lights_post"][0] == pytest.approx(post)
    early = fe.outcome_table(store.read, 2012)
    assert early["lights_pre"].null_count() == early.height


def test_script_follows_the_explore_rules():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source
    assert "terrain.registered" not in source
    assert fe.SEED == 20261110 and fe.DRAWS == 2000
    assert fe.WINDOWS == {"w025": 0.0025, "w050": 0.005, "w100": 0.01}
