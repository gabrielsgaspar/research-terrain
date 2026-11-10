import importlib.util
import random
from collections import Counter
from pathlib import Path

import pytest

from terrain.catalog import load_catalog
from terrain.split import (
    CONFIRM,
    EXPLORE,
    population_strata,
    read_municipalities,
    read_population_municipalities,
    serialize,
    sha256_hex,
    stratified_split,
)

REPO = Path(__file__).resolve().parents[1]

CSV = "code_ibge,uf\n" + "\n".join(
    [f"15{i:05d},PA" for i in range(11)] + [f"13{i:05d},AM" for i in range(6)]
)


def test_read_municipalities_parses_and_uppercases():
    rows = read_municipalities(CSV.replace(",PA", ",pa"))
    assert len(rows) == 17
    assert {uf for _, uf in rows} == {"PA", "AM"}


@pytest.mark.parametrize(
    "text",
    [
        "code,uf\n1500000,PA\n",  # wrong column
        "code_ibge,uf\n150,PA\n",  # not 7 digits
        "code_ibge,uf\n1500000,PA\n1500000,PA\n",  # duplicate
        "code_ibge,uf\n",  # empty
    ],
)
def test_read_municipalities_rejects_bad_input(text):
    with pytest.raises(ValueError):
        read_municipalities(text)


def test_split_is_balanced_within_each_state():
    rows = read_municipalities(CSV)
    for seed in range(50):
        assignment = stratified_split(rows, random.Random(seed))
        assert set(assignment) == {code for code, _ in rows}
        for uf, n in (("PA", 11), ("AM", 6)):
            codes = [code for code, s in rows if s == uf]
            n_confirm = sum(assignment[c] == CONFIRM for c in codes)
            assert n_confirm in (n // 2, (n + 1) // 2)
            assert set(assignment[c] for c in codes) <= {CONFIRM, EXPLORE}


def test_split_varies_with_the_random_source():
    rows = read_municipalities(CSV)
    draws = {serialize(stratified_split(rows, random.Random(seed))) for seed in range(20)}
    assert len(draws) > 1


def test_serialize_is_deterministic_and_hash_is_stable():
    assignment = {"1500002": CONFIRM, "1500001": EXPLORE}
    data = serialize(assignment)
    assert data == b"code_ibge,half\n1500001,explore\n1500002,confirm\n"
    assert sha256_hex(data) == sha256_hex(serialize(dict(reversed(assignment.items()))))
    assert len(sha256_hex(data)) == 64


# --- The split outside the Legal Amazon (decision 0011)

POP_CSV = "code_ibge,uf,population\n" + "\n".join(
    [f"22{i:05d},PI,{1000 + 37 * i}" for i in range(14)]
    + [f"31{i:05d},MG,{5000 - i}" for i in range(9)]
    + ["5300108,DF,2570160"]
)


def test_read_population_municipalities():
    rows = read_population_municipalities(POP_CSV)
    assert len(rows) == 24
    assert rows[0] == ("2200000", "PI", 1000)


@pytest.mark.parametrize(
    "text",
    [
        "code_ibge,uf\n2200000,PI\n",  # no population column
        "code_ibge,uf,population\n2200000,PI,\n",  # empty
        "code_ibge,uf,population\n2200000,PI,0\n",  # not positive
        "code_ibge,uf,population\n2200000,PI,12.5\n",  # not whole
        "code_ibge,uf,population\n220,PI,10\n",  # bad code
    ],
)
def test_read_population_municipalities_rejects_bad_input(text):
    with pytest.raises(ValueError):
        read_population_municipalities(text)


def test_population_strata_are_terciles_within_each_state():
    strata = dict(population_strata(read_population_municipalities(POP_CSV)))
    sizes = Counter(strata.values())
    assert sizes == {
        "PI-T1": 5, "PI-T2": 5, "PI-T3": 4, "MG-T1": 3, "MG-T2": 3, "MG-T3": 3, "DF-T1": 1,
    }  # fmt: skip
    # PI populations rise with the code, MG populations fall with it.
    assert strata["2200000"] == "PI-T1" and strata["2200013"] == "PI-T3"
    assert strata["3100000"] == "MG-T3" and strata["3100008"] == "MG-T1"


def test_population_strata_break_ties_by_code():
    rows = [(f"35{i:05d}", "SP", 100) for i in range(6)]
    strata = dict(population_strata(rows))
    assert [strata[f"35{i:05d}"] for i in range(6)] == ["SP-T1"] * 2 + ["SP-T2"] * 2 + ["SP-T3"] * 2


def test_population_split_is_balanced_within_each_stratum():
    strata = population_strata(read_population_municipalities(POP_CSV))
    sizes = Counter(s for _, s in strata)
    for seed in range(50):
        assignment = stratified_split(strata, random.Random(seed))
        confirmed = Counter(s for code, s in strata if assignment[code] == CONFIRM)
        for stratum, n in sizes.items():
            assert confirmed[stratum] in (n // 2, (n + 1) // 2)


def _seal_split():
    spec = importlib.util.spec_from_file_location("seal_split", REPO / "scripts" / "seal_split.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def sealing(tmp_path, monkeypatch):
    """The script run against a fake repository whose Legal Amazon split is sealed."""
    script = _seal_split()
    repo = tmp_path / "repo"
    (repo / "confirm").mkdir(parents=True)
    (repo / "confirm" / "split.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr(script, "REPO", repo)
    (tmp_path / "non_amazon.csv").write_text(POP_CSV + "\n", encoding="utf-8")
    (tmp_path / "legal_amazon.csv").write_text(
        "code_ibge,uf\n1500000,PA\n1500001,PA\n", encoding="utf-8"
    )

    def run(*extra: str) -> int:
        return script.main(
            [
                str(tmp_path / "non_amazon.csv"),
                "--non-amazon",
                str(tmp_path / "legal_amazon.csv"),
                "--out",
                str(tmp_path / "sealed"),
                *extra,
            ]
        )

    return run, repo, tmp_path


def test_seal_split_non_amazon_writes_the_split_and_its_hash(sealing, capsys):
    run, _, tmp_path = sealing
    assert run() == 0
    data = (tmp_path / "sealed" / "split_non_amazon.csv").read_bytes()
    lines = data.decode("utf-8").splitlines()
    assert lines[0] == "code_ibge,half" and len(lines) == 25
    explore = (tmp_path / "sealed" / "explore_municipalities_non_amazon.csv").read_text(
        encoding="utf-8"
    )
    explored = explore.splitlines()
    assert explored[0] == "code_ibge"
    assert explored[1:] == [line.split(",")[0] for line in lines[1:] if line.endswith(",explore")]
    printed = capsys.readouterr().out.splitlines()
    assert printed[-1] == sha256_hex(data)
    assert any(line.startswith("PI-T2: ") for line in printed)


def test_seal_split_non_amazon_refuses_once_sealed(sealing):
    run, repo, tmp_path = sealing
    (repo / "confirm" / "split_non_amazon.sha256").write_text("1" * 64, encoding="utf-8")
    assert run() == 1
    assert not (tmp_path / "sealed").exists()


def test_seal_split_non_amazon_needs_the_legal_amazon_split_first(sealing):
    run, repo, tmp_path = sealing
    (repo / "confirm" / "split.sha256").unlink()
    assert run() == 1
    assert not (tmp_path / "sealed").exists()


def test_seal_split_non_amazon_refuses_a_legal_amazon_code(sealing):
    run, _, tmp_path = sealing
    (tmp_path / "legal_amazon.csv").write_text("code_ibge,uf\n2200003,PI\n", encoding="utf-8")
    assert run() == 1
    assert not (tmp_path / "sealed").exists()


def test_seal_split_refuses_an_output_inside_the_repository(sealing):
    run, repo, _ = sealing
    assert run("--out", str(repo / "out")) == 1


def test_seal_split_legal_amazon_mode_still_refuses_once_sealed(sealing):
    _, _, tmp_path = sealing
    script = _seal_split()
    script.REPO = tmp_path / "repo"
    args = [str(tmp_path / "legal_amazon.csv"), "--out", str(tmp_path / "sealed")]
    assert script.main(args) == 1
    assert not (tmp_path / "sealed").exists()


# Every `sealed:` line in data/catalog.yaml, written out. CODEOWNERS cannot own
# one line of the catalog (coordination report 2026-11-08, Phase 1), and this
# file is code-owned, so adding, removing or changing a sealed folder means
# editing this constant too, which needs code-owner review.
SEALED = {
    "cell_outcomes": "sealed/outcomes/cell_outcomes/",
    "cell_enforcement": "sealed/outcomes/cell_enforcement/",
}


def test_catalog_sealed_lines_are_the_known_ones():
    sealed = {e["name"]: e["sealed"] for e in load_catalog() if "sealed" in e}
    assert sealed == SEALED
