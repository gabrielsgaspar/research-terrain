import hashlib
import io
import math
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import cell_displacement as cd
from terrain.builds.cell_displacement import BuildError, build, input_hash
from terrain.catalog import dataset
from terrain.grid import km_to_lonlat
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

DERIVED = dataset("cell_displacement")["derived"]
X0, Y0 = 4000, 9000  # cell lower-left corners are (X0 + cx, Y0); the centre is +0.5
YEAR = 2024
ELECTION = 100

GRID_PREFIX = "data/derived/grid_cells/aaaa/"
PLACES_PREFIX = "data/derived/polling_places/bbbb/"
VOTES_PREFIX = "data/derived/section_votes/cccc/"
RESULTS_PREFIX = "data/derived/tse_results/dddd/"
EXPOSURE_PREFIX = "data/derived/cell_exposure/eeee/"


def muni(code, ue, *, close, places, cells, uf="RO", swap=False, dy=0, pop=(), reached=()):
    """places: (local, x_off, w, l, other) votes at a place `x_off` km east of X0.

    `cells` are x offsets of the cells; `pop` those with people, `reached` those in
    `cell_exposure`.
    """
    return {
        "code": code,
        "ue": ue,
        "close": close,
        "places": places,
        "cells": cells,
        "uf": uf,
        "swap": swap,
        "dy": dy,
        "pop": pop,
        "reached": reached,
    }


def parquet(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def candidate_votes(munis) -> pl.DataFrame:
    rows = []
    for i, m in enumerate(munis, start=1):
        w, other = 10 * i + 1, 10 * i + 2
        elected, lost = (other, w) if m["swap"] else (w, other)
        lost_votes = 998 if m["close"] else 500
        for cand, code, votes in ((elected, 2, 1000), (lost, 4, lost_votes)):
            rows.append((13, 1, ELECTION, m["ue"], m["code"], cand, 5, votes, code))
    return pl.DataFrame(
        rows,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "sg_ue",
            "cd_ibge",
            "sq_candidato",
            "sq_coligacao",
            "qt_votos_nominais",
            "cd_sit_tot_turno",
        ],
        orient="row",
    )


def turnout(munis) -> pl.DataFrame:
    rows = [(13, 1, ELECTION, m["ue"], 10000) for m in munis]
    return pl.DataFrame(
        rows,
        schema=["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "qt_total_votos_validos"],
        orient="row",
    )


def section_votes(munis, uf) -> pl.DataFrame:
    rows = []
    for i, m in enumerate(munis, start=1):
        if m["uf"] != uf:
            continue
        for local, _, won, lost, other in m["places"]:
            for cand, votes in ((10 * i + 1, won), (10 * i + 2, lost), (10 * i + 3, other)):
                rows.append(
                    (13, 1, ELECTION, "candidate", False, 1, local, m["code"], m["ue"], cand, votes)
                )
    return pl.DataFrame(
        rows,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "vote_type",
            "annulled_in_results",
            "nr_zona",
            "nr_local_votacao",
            "cd_ibge",
            "sg_ue",
            "sq_candidato",
            "qt_votos",
        ],
        orient="row",
    )


def polling_places(munis) -> pl.DataFrame:
    rows = []
    for m in munis:
        for local, x_off, *_ in m["places"]:
            rows.append((m["code"], m["ue"], 1, local, X0 + x_off, Y0 + m["dy"] + 0.5))
    lon, lat = km_to_lonlat([r[4] for r in rows], [r[5] for r in rows])
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "sg_ue": [r[1] for r in rows],
            "nr_zona": [r[2] for r in rows],
            "nr_local_votacao": [r[3] for r in rows],
            "lat": lat.tolist(),
            "long": lon.tolist(),
        }
    )


def grid_cells(munis, duplicate=False) -> pl.DataFrame:
    rows = [
        (
            f"1KME{X0 + cx}N{Y0 + m['dy']}",
            m["code"],
            X0 + cx,
            Y0 + m["dy"],
            5 if cx in m["pop"] else 0,
        )
        for m in munis
        for cx in m["cells"]
    ]
    if duplicate:
        rows.append(rows[0])
    return pl.DataFrame(
        rows, schema=["nome_1KM", "cd_ibge", "x_km", "y_km", "pop_2022"], orient="row"
    )


def cell_exposure(munis) -> pl.DataFrame:
    rows = [(m["code"], X0 + cx, Y0 + m["dy"]) for m in munis for cx in m["reached"]]
    return pl.DataFrame(rows, schema=["cd_ibge", "x_km", "y_km"], orient="row")


def inputs(munis, store=None, duplicate=False):
    """A store with the synthetic inputs, and the five manifests that describe them."""
    store = MemoryStore() if store is None else store
    ufs = sorted({m["uf"] for m in munis})
    blobs = {
        GRID_PREFIX + "grid_cells.parquet": parquet(grid_cells(munis, duplicate)),
        EXPOSURE_PREFIX + f"cell_exposure_{YEAR}.parquet": parquet(cell_exposure(munis)),
        PLACES_PREFIX + f"polling_places_{YEAR}.parquet": parquet(polling_places(munis)),
        RESULTS_PREFIX + f"candidate_votes_{YEAR}.parquet": parquet(candidate_votes(munis)),
        RESULTS_PREFIX + f"turnout_{YEAR}.parquet": parquet(turnout(munis)),
    }
    for uf in ufs:
        blobs[VOTES_PREFIX + f"section_votes_{YEAR}_{uf}.parquet"] = parquet(
            section_votes(munis, uf)
        )
    manifests = {}
    for name, prefix in (
        ("grid_cells", GRID_PREFIX),
        ("cell_exposure", EXPOSURE_PREFIX),
        ("polling_places", PLACES_PREFIX),
        ("section_votes", VOTES_PREFIX),
        ("tse_results", RESULTS_PREFIX),
    ):
        files = [entry(p, b) for p, b in blobs.items() if p.startswith(prefix)]
        manifests[name] = {"dataset": name, "gcs_prefix": prefix, "files": files}
    for path, blob in blobs.items():
        store.create(path, blob)
    return store, manifests


def run(store, manifests, tmp_path, **kwargs):
    return build(
        store,
        manifests["grid_cells"],
        manifests["cell_exposure"],
        manifests["polling_places"],
        manifests["section_votes"],
        manifests["tse_results"],
        derived_root=DERIVED,
        tmp_dir=tmp_path,
        years=(YEAR,),
        code_commit="abc",
        created_at="2024-01-01T00:00:00+00:00",
        **kwargs,
    )


def output(store, manifest) -> pl.DataFrame:
    blob = store.read_bytes(manifest["gcs_prefix"] + cd.output_name(YEAR))
    return pl.read_parquet(io.BytesIO(blob))


G_COLUMNS = [f"g_{k}" for k in cd.KERNELS]

# Municipality A has a close pair. The winner's stronghold (the place at x = 0.5) and the
# loser's (the place at x = 45.5) are 45 km apart. The cell at cx = 15 has its centre
# 15 km from the winner's place and 30 km from the loser's. The cell at cx = 5 has
# people and the cell at cx = 7 is in cell_exposure, so neither is in the output.
PLACES = [(1, 0.5, 90, 10, 10), (2, 45.5, 10, 90, 10)]
A = muni("1100001", "10", close=True, places=PLACES, cells=[15, 5, 7], pop=(5,), reached=(7,))
# Municipality B has no close pair, so its empty cell is not in the output.
B = muni("1100002", "20", close=False, places=PLACES, cells=[15], uf="AC", dy=200)


def test_two_municipalities(tmp_path):
    store, manifests = inputs([A, B])
    manifest = run(store, manifests, tmp_path)
    assert manifest["status"] == "created"
    assert validate_manifest(manifest, stage="build", dataset="cell_displacement") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    out = output(store, manifest)
    assert out.columns == cd.OUTPUT_COLUMNS
    assert out["cd_ibge"].to_list() == ["1100001"]
    assert out["nome_1KM"].to_list() == [f"1KME{X0 + 15}N{Y0}"]
    assert out["x_km"].to_list() == [X0 + 15]
    assert out["ano"].to_list() == [YEAR]
    assert out["n_pairs"].to_list() == [1]
    assert out["n_pairs_located"].to_list() == [1]
    row = out.row(0, named=True)
    assert row["g_ring10_20"] == 1.0
    assert row["g_ring20_50"] == -1.0
    assert row["g_exp10"] == pytest.approx(math.exp(-1.5) - math.exp(-3.0), abs=1e-9)
    assert "municipalities_with_pair=1" in manifest["notes"]
    assert "close_pairs=1" in manifest["notes"]
    assert "pairs_located=1" in manifest["notes"]
    assert "dropped_same_place=0" in manifest["notes"]
    assert "dropped_no_coordinates=0" in manifest["notes"]
    assert "rows=1" in manifest["notes"]


def test_output_types_and_order(tmp_path):
    c = muni("1100003", "30", close=True, places=PLACES, cells=[25, 15, 16], uf="AC", dy=100)
    store, manifests = inputs([c, A])
    out = output(store, run(store, manifests, tmp_path))
    assert out["cd_ibge"].to_list() == sorted(out["cd_ibge"].to_list())
    assert out.filter(pl.col("cd_ibge") == "1100003")["x_km"].to_list() == [
        X0 + 15,
        X0 + 16,
        X0 + 25,
    ]
    assert out.schema["x_km"] == pl.Int64
    assert out.schema["n_pairs"] == pl.Int64
    assert out.schema["n_pairs_located"] == pl.Int64
    assert out.schema["ano"] == pl.Int64
    assert out.schema["g_exp10"] == pl.Float64
    assert out.schema["cd_ibge"] == pl.Utf8


def test_a_cell_far_from_both_strongholds_is_zero(tmp_path):
    far = {**A, "cells": [15, 110], "pop": (), "reached": ()}
    store, manifests = inputs([far])
    out = output(store, run(store, manifests, tmp_path))
    row = out.filter(pl.col("x_km") == X0 + 110).row(0, named=True)
    assert [row[c] for c in G_COLUMNS] == [0.0, 0.0, 0.0]
    assert out.filter(pl.col("x_km") == X0 + 15)["g_exp10"][0] != 0


def test_swapping_winner_and_loser_negates_g(tmp_path):
    store, manifests = inputs([A])
    out = output(store, run(store, manifests, tmp_path))
    store2, manifests2 = inputs([{**A, "swap": True}])
    out2 = output(store2, run(store2, manifests2, tmp_path))
    for name in G_COLUMNS:
        assert out[name][0] != 0
        assert out2[name][0] == pytest.approx(-out[name][0], abs=1e-9)


def test_a_same_place_pair_counts_but_adds_zero(tmp_path):
    # Two cells so that the year still has a nonzero cell: municipality C is as A, with
    # its pair's strongholds at the same single place.
    same = muni(
        "1100003",
        "30",
        close=True,
        places=[(1, 0.5, 90, 10, 10)],
        cells=[15],
        uf="AC",
        dy=100,
    )
    store, manifests = inputs([A, same])
    manifest = run(store, manifests, tmp_path)
    out = output(store, manifest).filter(pl.col("cd_ibge") == "1100003")
    assert out["n_pairs"].to_list() == [1]
    assert out["n_pairs_located"].to_list() == [0]
    assert [out[c][0] for c in G_COLUMNS] == [0.0, 0.0, 0.0]
    assert "dropped_same_place=1" in manifest["notes"]
    assert "close_pairs=2" in manifest["notes"]
    assert "pairs_located=1," in manifest["notes"]


def unchanged(store, before):
    assert store.list("") == before


def test_a_year_without_a_displaced_cell_stops_the_build(tmp_path):
    same = {**A, "places": [(1, 0.5, 90, 10, 10)]}
    store, manifests = inputs([same])
    before = store.list("")
    with pytest.raises(BuildError, match="no cell with g_exp10"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_a_duplicate_cell_stops_the_build(tmp_path):
    store, manifests = inputs([A], duplicate=True)
    before = store.list("")
    with pytest.raises(BuildError, match="more than once"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def table(**columns) -> pl.DataFrame:
    base = {
        "nome_1KM": ["a"],
        "cd_ibge": ["1"],
        "x_km": [1],
        "y_km": [2],
        "ano": [YEAR],
        "n_pairs": [2],
        "n_pairs_located": [2],
        "g_exp10": [1.5],
        "g_ring10_20": [1.0],
        "g_ring20_50": [-1.0],
    }
    return pl.DataFrame({**base, **{k: [v] for k, v in columns.items()}})


def grid_for(frame: pl.DataFrame, pop=0) -> pl.DataFrame:
    return frame.select("nome_1KM", "cd_ibge", "x_km", "y_km").with_columns(
        pl.lit(pop).alias("pop_2022")
    )


NONE_REACHED = pl.DataFrame(schema={"cd_ibge": pl.Utf8, "x_km": pl.Int64, "y_km": pl.Int64})


def test_keys_check():
    good = table()
    cd.check_keys(good, grid_for(good), NONE_REACHED)
    with pytest.raises(BuildError, match="more than once"):
        cd.check_keys(pl.concat([good, good]), grid_for(good), NONE_REACHED)
    with pytest.raises(BuildError, match="not in grid_cells"):
        cd.check_keys(good, grid_for(good, pop=3), NONE_REACHED)
    other = good.with_columns(pl.lit("9").alias("cd_ibge"))
    with pytest.raises(BuildError, match="not in grid_cells"):
        cd.check_keys(other, grid_for(good), NONE_REACHED)
    reached = pl.DataFrame({"cd_ibge": ["1"], "x_km": [1], "y_km": [2]})
    with pytest.raises(BuildError, match="in cell_exposure"):
        cd.check_keys(good, grid_for(good), reached)


def test_bounds_check():
    cd.check_bounds(table())
    with pytest.raises(BuildError, match="g_exp10"):
        cd.check_bounds(table(g_exp10=2.5))
    with pytest.raises(BuildError, match="g_ring10_20"):
        cd.check_bounds(table(g_ring10_20=3.0))
    with pytest.raises(BuildError, match="not whole"):
        cd.check_bounds(table(g_ring20_50=0.5))


def test_counts_check():
    cd.check_counts(table())
    with pytest.raises(BuildError, match="above n_pairs"):
        cd.check_counts(table(n_pairs_located=3))
    with pytest.raises(BuildError, match="below 1"):
        cd.check_counts(table(n_pairs=0, n_pairs_located=0))


def test_year_check():
    cd.check_year(YEAR, table())
    with pytest.raises(BuildError, match="no cell with g_exp10"):
        cd.check_year(YEAR, table(g_exp10=0.0))


def test_a_check_failure_leaves_the_store_unchanged(tmp_path, monkeypatch):
    def broken(_table):
        raise BuildError("broken")

    monkeypatch.setattr(cd, "check_bounds", broken)
    store, manifests = inputs([A])
    before = store.list("")
    with pytest.raises(BuildError, match="broken"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_a_second_run_is_unchanged(tmp_path):
    store, manifests = inputs([A, B])
    first = run(store, manifests, tmp_path)
    write_manifest(first, store, tmp_path / "manifest.json")
    assert store.exists(first["gcs_prefix"] + MANIFEST_NAME)
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]


def test_the_strongholds_source_changes_the_path(tmp_path, monkeypatch):
    store, manifests = inputs([A, B])
    first = run(store, manifests, tmp_path)
    sources = cd.code_sources()
    assert len(sources) == 3
    assert any("def displacement" in s for s in sources)
    changed = [s + "\n# changed" if "def displacement" in s else s for s in sources]
    monkeypatch.setattr(cd, "code_sources", lambda modules=None: changed)
    second = run(store, manifests, tmp_path)
    assert second["status"] == "created"
    assert second["gcs_prefix"] != first["gcs_prefix"]


def test_input_hash_depends_on_inputs_years_and_code():
    files = [{"sha256": "a" * 64}, {"sha256": "b" * 64}]
    code = ["x", "y"]
    base = input_hash(files, (2008, 2012), code)
    assert base == input_hash(list(reversed(files)), (2012, 2008), code)
    assert base != input_hash(files[:1], (2008, 2012), code)
    assert base != input_hash(files, (2008,), code)
    assert base != input_hash(files, (2008, 2012), ["x", "z"])


def test_an_input_that_differs_from_its_manifest_raises(tmp_path):
    store, manifests = inputs([A, B])
    manifests["cell_exposure"]["files"][0]["sha256"] = "0" * 64
    before = store.list("")
    with pytest.raises(BuildError, match="does not match the sha256"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_a_missing_input_raises(tmp_path):
    store, manifests = inputs([A, B])
    manifests["cell_exposure"]["files"] = []
    with pytest.raises(BuildError, match="expected a file matching"):
        run(store, manifests, tmp_path)


def test_the_pipeline_script_reads_the_five_manifests():
    root = Path(__file__).resolve().parents[1]
    text = (root / "pipeline" / "build" / "cell_displacement.py").read_text(encoding="utf-8")
    for name in ("grid_cells", "cell_exposure", "polling_places", "section_votes", "tse_results"):
        assert f'_load("{name}")' in text
        assert (root / "data" / "manifests" / "build" / f"{name}.json").exists()
