import importlib.util
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0001_kill_criterion_1.py"
SPEC = importlib.util.spec_from_file_location("kc1", SCRIPT)
kc1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kc1)


def close(sqs):
    return pl.DataFrame(
        {"cd_eleicao": [1] * len(sqs), "sg_ue": ["01"] * len(sqs), "sq_candidato": sqs}
    )


def strong(rows):
    """rows: (sq_candidato, nr_local_votacao)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "sq_candidato": [r[0] for r in rows],
            "cd_ibge": ["1500107"] * len(rows),
            "nr_zona": [7] * len(rows),
            "nr_local_votacao": [r[1] for r in rows],
        }
    )


def tenure(rows):
    """rows: (nr_local_votacao, dist_indigenous_km, dist_settlement_km)."""
    return pl.DataFrame(
        {
            "ano": [2020] * len(rows),
            "cd_ibge": ["1500107"] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "nr_zona": [7] * len(rows),
            "nr_local_votacao": [r[0] for r in rows],
            "dist_indigenous_km": [r[1] for r in rows],
            "dist_settlement_km": [r[2] for r in rows],
        },
        schema_overrides={"dist_indigenous_km": pl.Float64, "dist_settlement_km": pl.Float64},
    )


def test_bands_for_a_near_and_a_far_stronghold():
    table = kc1.candidate_distances(
        close(["a", "b"]),
        strong([("a", 1), ("b", 2)]),
        tenure([(1, 1.0, 0.5), (2, 7.0, 9.0)]),
    )
    counts = kc1.band_counts(table)
    assert counts["candidates"] == 2
    assert counts["with_coordinates"] == 2
    assert counts["indigenous"] == {"0km": 0, "2km": 1, "5km": 1}
    assert counts["settlement"] == {"0km": 0, "2km": 1, "5km": 1}


def test_inside_counts_at_zero_km():
    table = kc1.candidate_distances(close(["a"]), strong([("a", 1)]), tenure([(1, 0.0, 0.0)]))
    assert kc1.band_counts(table)["indigenous"] == {"0km": 1, "2km": 1, "5km": 1}


def test_missing_or_null_coordinates_are_not_far_away():
    table = kc1.candidate_distances(
        close(["a", "b", "c"]),
        strong([("a", 1), ("b", 2)]),  # c has no stronghold
        tenure([(1, None, None)]),  # b has no tenure row, a has null distances
    )
    counts = kc1.band_counts(table)
    assert counts["candidates"] == 3
    assert counts["with_stronghold"] == 2
    assert counts["with_coordinates"] == 0
    assert counts["indigenous"] == {"0km": 0, "2km": 0, "5km": 0}
    assert counts["settlement"] == {"0km": 0, "2km": 0, "5km": 0}


def test_join_works_when_keys_arrive_as_strings_on_one_side():
    left = strong([("a", 1)]).with_columns(
        pl.col("nr_zona").cast(pl.Utf8), pl.col("nr_local_votacao").cast(pl.Utf8)
    )
    out = kc1.join_tenure(left, tenure([(1, 1.0, 2.0)]))
    assert out["dist_indigenous_km"].to_list() == [1.0]
    assert out["dist_settlement_km"].to_list() == [2.0]


def pooled(indigenous, settlement):
    return {"indigenous": {"5km": indigenous}, "settlement": {"5km": settlement}}


def test_verdict_at_199_and_200_for_each_layer():
    assert kc1.verdict(pooled(199, 5000))["kill_criterion_1"] == "met"
    assert kc1.verdict(pooled(5000, 199))["kill_criterion_1"] == "met"
    assert kc1.verdict(pooled(200, 200))["kill_criterion_1"] == "not met"
    assert kc1.verdict(pooled(200, 5000))["kill_criterion_1"] == "not met"
    assert kc1.verdict(pooled(5000, 200))["kill_criterion_1"] == "not met"


def test_pool_sums_years():
    one = {
        "candidates": 2,
        "with_stronghold": 2,
        "with_coordinates": 1,
        "indigenous": {"0km": 0, "2km": 1, "5km": 1},
        "settlement": {"0km": 1, "2km": 1, "5km": 1},
    }
    total = kc1.pool({"2020": one, "2024": one})
    assert total["candidates"] == 4
    assert total["indigenous"] == {"0km": 0, "2km": 2, "5km": 2}


def test_script_reuses_the_census():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "spec_from_file_location" in source
    assert "0001_feasibility_census.py" in source
    assert "def strongholds" not in source
    assert "def within_list_pairs" not in source
