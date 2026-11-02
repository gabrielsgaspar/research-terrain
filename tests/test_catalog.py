import pytest

from terrain.catalog import dataset, load_catalog


def test_gets_tse_candidates_from_the_real_catalog():
    entry = dataset("tse_candidates")
    assert entry["gcs"] == "data/raw/tse/candidates/"
    assert "<year>" in entry["source"]


def test_gets_complementar_entry():
    entry = dataset("tse_candidates_complementar")
    assert entry["gcs"] == dataset("tse_candidates")["gcs"]


def test_tse_candidates_has_an_acquire_block():
    assert dataset("tse_candidates")["acquire"]["files"]
    assert "acquire" not in dataset("tse_candidates_complementar")


def test_unknown_name_raises():
    with pytest.raises(KeyError):
        dataset("no_such_dataset")


def test_names_are_unique():
    names = [e["name"] for e in load_catalog()]
    assert len(names) == len(set(names))
