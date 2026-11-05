"""The explore scripts use the `terrain.strongholds` objects, not their own copies."""

import importlib.util
from pathlib import Path

import pytest

from terrain import strongholds

REPO = Path(__file__).resolve().parents[1]


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = load("feasibility_census_shared", "0001_feasibility_census.py")
options = load("exposure_options_shared", "0001_exposure_options.py")

CENSUS_NAMES = [
    "_codes",
    "_council_round1",
    "main_election",
    "elected_status",
    "candidacy_votes",
    "within_list_pairs",
    "valid_votes",
    "margins",
    "place_candidate_votes",
    "strongholds",
    "HEADLINE",
    "MIN_PLACE_VOTES",
    "COUNCIL",
    "LIST_KEY",
    "CAND_KEY",
    "PLACE_KEY",
    "ELECTED_CODES",
    "NOT_ELECTED_CODES",
]

OPTIONS_NAMES = [
    "close_pairs",
    "place_totals",
    "place_shares",
    "locate_places",
    "cell_place_distances",
    "kernel",
    "exposure",
    "CELL",
    "MAX_KM",
    "TOLERANCE",
    "KERNELS",
    "MEASURES",
]


@pytest.mark.parametrize("name", CENSUS_NAMES)
def test_census_uses_library_object(name):
    assert getattr(census, name) is getattr(strongholds, name)


@pytest.mark.parametrize("name", OPTIONS_NAMES)
def test_options_uses_library_object(name):
    assert getattr(options, name) is getattr(strongholds, name)
