import json
import re
from pathlib import Path

import polars as pl
import pytest

from terrain.explore import (
    EXPLORE_LIST,
    EXPLORE_LIST_NON_AMAZON,
    NATIONAL_IDEAS,
    ExploreError,
    exploration_municipalities,
    idea_of,
    output_prefix,
    restrict,
    write_results,
)
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]


def store_with(text: str) -> MemoryStore:
    store = MemoryStore()
    store.create(EXPLORE_LIST, text.encode("utf-8"))
    return store


def test_exploration_list_is_read_and_checked():
    codes = exploration_municipalities(store_with("code_ibge\n1500107\n1500131\n"))
    assert codes == {"1500107", "1500131"}
    for bad in ("code_ibge\n", "code,uf\n1500107,PA\n", "code_ibge\n150\n"):
        with pytest.raises(ExploreError):
            exploration_municipalities(store_with(bad))


def test_a_missing_list_stops_the_run():
    with pytest.raises(ExploreError, match="sealed"):
        exploration_municipalities(MemoryStore())


def test_national_list_is_the_union_of_both_lists():
    store = store_with("code_ibge\n1500107\n1500131\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code_ibge\n3550308\n")
    assert exploration_municipalities(store) == {"1500107", "1500131"}
    assert exploration_municipalities(store, national=True) == {"1500107", "1500131", "3550308"}


def test_national_list_needs_both_lists_and_no_overlap():
    with pytest.raises(ExploreError, match="explore_municipalities_non_amazon"):
        exploration_municipalities(store_with("code_ibge\n1500107\n"), national=True)
    store = store_with("code_ibge\n1500107\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code_ibge\n1500107\n3550308\n")
    with pytest.raises(ExploreError, match="in both"):
        exploration_municipalities(store, national=True)
    store = store_with("code_ibge\n1500107\n")
    store.create(EXPLORE_LIST_NON_AMAZON, b"code\n3550308\n")
    with pytest.raises(ExploreError, match="exactly one column"):
        exploration_municipalities(store, national=True)


def test_restrict_keeps_only_the_exploration_half():
    df = pl.DataFrame({"cd_ibge": ["1500107", "1500131", "1500206"], "x": [1, 2, 3]})
    kept = restrict(df, frozenset({"1500107", "1500206"}))
    assert kept["cd_ibge"].to_list() == ["1500107", "1500206"]
    with pytest.raises(ExploreError):
        restrict(df.rename({"cd_ibge": "code"}), frozenset({"1500107"}))


def test_names_and_prefixes():
    assert idea_of("0001_feasibility_census") == "0001"
    prefix = output_prefix("0001_feasibility_census", "123")
    assert prefix == "data/explore/0001/0001_feasibility_census/123/"
    for bad in ("feasibility", "1_census", "0001-census", "0001_Census"):
        with pytest.raises(ExploreError):
            idea_of(bad)
    with pytest.raises(ExploreError):
        output_prefix("0001_feasibility_census", "../x")


def test_write_results_enforces_limits(tmp_path):
    write_results(tmp_path, "# Result\nfine", {"n": 1})
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["n"] == 1
    with pytest.raises(ExploreError):
        write_results(tmp_path, "x" * 20_001, {})
    with pytest.raises(ExploreError):
        write_results(tmp_path, "ok", {"big": "y" * 200_001})


def test_every_explore_script_restricts_to_the_exploration_half():
    for script in sorted((REPO / "explore").glob("*.py")):
        source = script.read_text(encoding="utf-8")
        assert re.fullmatch(r"\d{4}_[a-z0-9_]{1,60}\.py", script.name), f"{script.name}: bad name"
        for needed in ("exploration_municipalities(", "restrict("):
            assert needed in source, f"{script.name} must call {needed[:-1]}"


def test_national_idea_scripts_read_both_exploration_lists():
    for idea in NATIONAL_IDEAS:
        for script in sorted((REPO / "explore").glob(f"{idea}_*.py")):
            source = script.read_text(encoding="utf-8")
            assert "national=True" in source, (
                f"{script.name}: idea {idea} is national (decision 0011); call "
                "exploration_municipalities(store, national=True)"
            )
