"""explore/0001_one_incumbent_pairs.py on the synthetic world (never real data)."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import world_0001 as W

from terrain import strongholds as sh
from terrain.explore import write_results
from terrain.registered.r0001 import analysis
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0001_one_incumbent_pairs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("test_one_incumbent_pairs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_one_incumbent_pairs"] = module
    spec.loader.exec_module(module)
    return module


S = load_script()


class Recording(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.downloaded: list[str] = []

    def download(self, path: str, local_file: Path) -> None:
        self.downloaded.append(path)
        super().download(path, local_file)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    store = Recording()
    manifests = tmp_path_factory.mktemp("manifests")
    W.write_world(store, manifests)
    return store, manifests


@pytest.fixture(autouse=True)
def point_at_world(world, monkeypatch):
    _, manifests = world
    monkeypatch.setattr(S.census, "MANIFESTS", manifests)


@pytest.fixture(scope="module")
def counts(world, tmp_path_factory):
    store, manifests = world
    S.census.MANIFESTS = manifests
    try:
        store.downloaded.clear()
        got = S.gather(store, W.explore_half(), tmp_path_factory.mktemp("run"))
        paths = list(store.downloaded)
    finally:
        S.census.MANIFESTS = REPO / "data" / "manifests" / "build"
    return got, paths


@pytest.fixture(scope="module")
def results(counts):
    return S.build_results(counts[0])


def test_matches_the_registered_incumbent_sign_at_0_005(world, tmp_path):
    store, manifests = world
    got = S.gather(store, W.explore_half(), tmp_path, 0.005)
    half = W.explore_half()
    reader = analysis.Reader(
        store.download, lambda df: S.restrict(df, half), "files", tmp_path, manifests
    )
    cands = analysis.load_candidates(reader)
    for year in S.ELECTIONS:
        t = analysis.treatment_year(reader, cands, year, 0.005)
        s = analysis.incumbent_sign(t["pairs"], t["inc"])["s"].to_list()
        expected = {
            "plus": sum(1 for v in s if v == 1.0),
            "minus": sum(1 for v in s if v == -1.0),
            "zero": sum(1 for v in s if v == 0.0),
            "pairs": t["pairs"].height,
        }
        assert {k: got[year][k] for k in expected} == expected, year
    assert sum(got[y]["one_incumbent"] for y in S.ELECTIONS) > 0


def test_counts_add_up_at_0_0025(world, tmp_path):
    store, _ = world
    got = S.gather(store, W.explore_half(), tmp_path, 0.0025)
    half = W.explore_half()
    read = S.window_script.make_reader(store, tmp_path, half)
    for year in S.ELECTIONS:
        c = got[year]
        assert c["plus"] + c["minus"] + c["zero"] == c["pairs"], year
        assert c["one_incumbent"] == c["plus"] + c["minus"], year
        assert c["pairs"] == S.year_pairs(read, half, year, 0.0025).height, year
        cv = S.restrict(read("tse_results", rf"candidate_votes_{year}\.parquet$"), half)
        assert sh.main_election(cv) is not None


def test_no_outcome_file_is_read(counts):
    _, paths = counts
    assert paths
    for path in paths:
        parts = Path(path).parts
        assert any(p in parts for p in ("tse_candidates", "municipalities", "tse_results")), path
        assert "cell_outcomes" not in parts, path


def test_the_script_does_not_import_the_registered_analysis():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [base] + [f"{base}.{a.name}" for a in node.names]
        for name in names:
            assert "terrain.registered" not in name, name


def test_results_hold_whole_numbers_and_text_only(results, tmp_path):
    write_results(tmp_path, S._summary(results), results)
    loaded = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))

    def walk(value, path=""):
        assert not isinstance(value, float), path
        if isinstance(value, dict):
            for k, v in value.items():
                assert "." not in k, path
                walk(v, f"{path}/{k}")
        elif isinstance(value, list):
            for v in value:
                walk(v, path)
        else:
            assert isinstance(value, int | str) and not isinstance(value, bool), path

    walk(loaded)
    assert type(loaded["counts"]["pooled"]["one_incumbent"]) is int
    assert loaded["window"] == "0.25%" and loaded["elections"] == [2008, 2012, 2016, 2020]
    pooled = loaded["counts"]["pooled"]
    for key in S.KEYS:
        assert pooled[key] == sum(loaded["counts"][f"e{y}"][key] for y in S.ELECTIONS)


def test_no_voter_id_reaches_the_outputs(results, tmp_path):
    write_results(tmp_path, S._summary(results), results)
    text = (tmp_path / "results.json").read_text(encoding="utf-8") + (
        tmp_path / "summary.md"
    ).read_text(encoding="utf-8")
    for year in (2004, *S.ELECTIONS):
        for i in range(W.N_MUNIS):
            for j in range(W.LISTS):
                for side in (0, 1):
                    assert W.person(year, i, j, side) not in text


def test_the_summary_leads_with_the_count_and_compares_with_decision_0008(results):
    lines = S._summary(results).splitlines()
    n = results["counts"]["pooled"]["one_incumbent"]
    assert lines[0] == f"Pairs with exactly one incumbent at 0.25%, pooled 2008-2020: {n:,}"
    assert any("decision 0008" in line and "equal" in line for line in lines)
    assert S.DECISION_0008_PAIRS == 2328 and S.WINDOW == 0.0025
