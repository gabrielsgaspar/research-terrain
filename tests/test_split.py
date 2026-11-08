import random

import pytest

from terrain.catalog import load_catalog
from terrain.split import (
    CONFIRM,
    EXPLORE,
    read_municipalities,
    serialize,
    sha256_hex,
    stratified_split,
)

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


# Every `sealed:` line in data/catalog.yaml, written out. CODEOWNERS cannot own
# one line of the catalog (coordination report 2026-11-08, Phase 1), and this
# file is code-owned, so adding, removing or changing a sealed folder means
# editing this constant too, which needs code-owner review.
SEALED = {
    "cell_outcomes": "sealed/outcomes/cell_outcomes/",
}


def test_catalog_sealed_lines_are_the_known_ones():
    sealed = {e["name"]: e["sealed"] for e in load_catalog() if "sealed" in e}
    assert sealed == SEALED
