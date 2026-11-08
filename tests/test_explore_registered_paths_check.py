"""explore/0001_registered_paths_check.py on the synthetic world (never real data, never 0.25%)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import polars as pl
import pytest
import world_0001 as W

from terrain.explore import write_results
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]
DRAWS = 200


def load_script():
    spec = importlib.util.spec_from_file_location(
        "test_paths_check", REPO / "explore" / "0001_registered_paths_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_paths_check"] = module
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


@pytest.fixture(scope="module")
def gathered(world, tmp_path_factory):
    store, manifests = world
    return S.gather(
        store, W.explore_half(), S.WINDOW, tmp_path_factory.mktemp("run"), DRAWS, manifests
    )


@pytest.fixture(scope="module")
def results(gathered):
    return S.build_results(S.run_checks(gathered))


def test_every_check_passes_on_the_world(results):
    for name in S.CHECKS:
        assert results["checks"][name]["pass"] is True, name
    assert results["all_pass"] is True and results["n_fail"] == 0
    assert results["checks"]["c1"]["counts"]["pooled"]["one_incumbent"] > 0


def test_a_z_term_with_the_wrong_sign_fails_check_2(gathered):
    g = copy.deepcopy(gathered)
    z = g["parts"][2012]["direct_adj"].designs["z"]
    assert z.vals.size
    z.vals[0] = -z.vals[0]
    assert S.check_2(g)["pass"] is False
    assert S.check_2(gathered)["pass"] is True


def test_an_alignment_component_missing_a_pair_fails_check_4(gathered):
    g = copy.deepcopy(gathered)
    design = next(d for d in g["parts"][2012]["align"].designs.values() if d.cols.size)
    keep = design.cols != design.cols[0]
    design.rows, design.cols, design.vals = design.rows[keep], design.cols[keep], design.vals[keep]
    assert S.check_4(g)["pass"] is False
    assert S.check_4(gathered)["pass"] is True


def test_a_nan_in_a_direct_adj_slot_fails_check_6(gathered):
    g = copy.deepcopy(gathered)
    slot = g["results"]["estimates"]["direct_adj"]["slots"]["Y4"]["beta"]
    slot["slope"] = float("nan")
    got = S.check_6(g)
    assert got["pass"] is False and got["counts"]["nonfinite"] == 1
    assert got["paths"] == ["estimates.direct_adj.slots.Y4.beta.slope"]
    assert S.check_6(gathered)["pass"] is True


def test_a_direct_pre_sample_with_one_cell_more_fails_check_5(gathered):
    g = copy.deepcopy(gathered)
    pre = g["pre"][2012]
    extra = pre["sample"].head(1).with_columns(pl.col("x_km") + 10_000_000)
    pre["sample"] = pl.concat([pre["sample"], extra])
    assert S.check_5(g)["pass"] is False
    assert S.check_5(gathered)["pass"] is True


def test_results_hold_only_booleans_whole_numbers_and_text(results):
    def walk(value, path=""):
        assert not isinstance(value, float), path
        if isinstance(value, dict):
            for k, v in value.items():
                assert isinstance(k, str) and "." not in k, path
                walk(v, f"{path}/{k}")
        elif isinstance(value, list):
            assert all(isinstance(v, str) for v in value), path
        else:
            assert isinstance(value, bool | int | str), path

    loaded = json.loads(json.dumps(results))
    walk(loaded)
    assert loaded["window"] == "0.50%" and loaded["n_checks"] == 7


def test_results_have_the_keys_the_kill_rules_read(results):
    loaded = json.loads(json.dumps(results))
    for n in range(1, 8):
        assert isinstance(loaded["checks"][f"c{n}"]["pass"], bool)
    pooled = loaded["checks"]["c1"]["counts"]["pooled"]
    assert type(pooled["one_incumbent"]) is int
    assert type(loaded["checks"]["c6"]["counts"]["nonfinite"]) is int
    assert loaded["checks"]["c6"]["paths"] == []
    assert type(loaded["all_pass"]) is bool and type(loaded["n_fail"]) is int
    assert set(loaded["checks"]["c2"]["counts"]) == set(S.EXPOSURES)
    kinds = {"aligned", "unaligned", "mixed", "left_out", "pairs"}
    assert set(loaded["checks"]["c4"]["counts"]["e2008"]) == kinds


def test_the_registered_window_is_refused_before_any_read(world, tmp_path):
    store, manifests = world
    before = len(store.downloaded)
    with pytest.raises(ValueError, match="before registration"):
        S.gather(store, W.explore_half(), 0.0025, tmp_path, DRAWS, manifests)
    assert len(store.downloaded) == before
    assert S.WINDOW == 0.005


def test_the_summary_leads_with_the_verdict_and_prints_no_estimate(results, tmp_path):
    text = S.summary(results)
    assert text.splitlines()[0] == "Structural checks: pass"
    assert set(re.findall(r"\d+\.\d+", text)) == {"0.50"}
    failing = json.loads(json.dumps(results))
    failing["checks"]["c3"]["pass"] = False
    failing["n_fail"], failing["all_pass"] = 1, False
    assert S.summary(failing).splitlines()[0] == "Structural checks: fail (1 of 7)"
    write_results(tmp_path, text, results)
    assert (tmp_path / "results.json").exists()


def test_a_failing_stage_reports_only_its_name():
    with pytest.raises(SystemExit) as caught:
        with S.stage("analysis"):
            raise SystemExit("direct: differ by 0.123")
    assert str(caught.value) == "analysis failed"
