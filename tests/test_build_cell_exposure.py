import hashlib
import io
import math
from pathlib import Path

import polars as pl
import pytest

from terrain import strongholds as sh
from terrain.builds import cell_exposure as ce
from terrain.builds.cell_exposure import BuildError, build, input_hash
from terrain.catalog import dataset
from terrain.grid import km_to_lonlat
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

DERIVED = dataset("cell_exposure")["derived"]
X0, Y0 = 4000, 9000  # cell lower-left corners are (X0 + cx, Y0); the centre is +0.5
YEAR = 2024
ELECTION = 100

GRID_PREFIX = "data/derived/grid_cells/aaaa/"
PLACES_PREFIX = "data/derived/polling_places/bbbb/"
VOTES_PREFIX = "data/derived/section_votes/cccc/"
RESULTS_PREFIX = "data/derived/tse_results/dddd/"


def muni(code, ue, *, close, places, cells, uf="RO", swap=False, dy=0):
    """places: (local, x_off, w, l, other) votes at a place `x_off` km east of X0."""
    return {
        "code": code,
        "ue": ue,
        "close": close,
        "places": places,
        "cells": cells,
        "uf": uf,
        "swap": swap,
        "dy": dy,
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
        (f"1KME{X0 + cx}N{Y0 + m['dy']}", m["code"], X0 + cx, Y0 + m["dy"])
        for m in munis
        for cx in m["cells"]
    ]
    if duplicate:
        rows.append(rows[0])
    return pl.DataFrame(rows, schema=["nome_1KM", "cd_ibge", "x_km", "y_km"], orient="row")


def inputs(munis, store=None, duplicate=False):
    """A store with the synthetic inputs, and the four manifests that describe them."""
    store = MemoryStore() if store is None else store
    ufs = sorted({m["uf"] for m in munis})
    blobs = {
        GRID_PREFIX + "grid_cells.parquet": parquet(grid_cells(munis, duplicate)),
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
    blob = store.read_bytes(manifest["gcs_prefix"] + ce.output_name(YEAR))
    return pl.read_parquet(io.BytesIO(blob))


# Municipality A: a close pair, places 1 km and 3 km from the cell at cx = 0.
A = muni(
    "1100001",
    "10",
    close=True,
    places=[(1, 1.5, 60, 20, 20), (2, 3.5, 10, 50, 40)],
    cells=[0],
)
# Municipality B: no close pair; one cell is 1 km from its place, one is 30 km away.
B = muni(
    "1100002", "20", close=False, places=[(1, 1.5, 50, 30, 20)], cells=[0, 30], uf="AC", dy=100
)


def expected_exp2():
    k1, k2 = math.exp(-0.5), math.exp(-1.5)
    return (k1 * (0.6 - 0.2) + k2 * (0.1 - 0.5)) / (k1 + k2)


def test_two_municipalities(tmp_path):
    store, manifests = inputs([A, B])
    manifest = run(store, manifests, tmp_path)
    assert manifest["status"] == "created"
    assert validate_manifest(manifest, stage="build", dataset="cell_exposure") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    out = output(store, manifest)
    assert out.columns == ce.OUTPUT_COLUMNS
    assert out["cd_ibge"].to_list() == ["1100001", "1100002"]  # the far cell is not reached
    assert out["nome_1KM"].to_list() == [f"1KME{X0}N{Y0}", f"1KME{X0}N{Y0 + 100}"]
    assert out["n_pairs"].to_list() == [1, 0]
    assert out["ano"].to_list() == [YEAR, YEAR]
    first, second = out.row(0, named=True), out.row(1, named=True)
    assert first["d_exp2"] == pytest.approx(expected_exp2(), abs=1e-6)
    assert first["d_ring2"] == pytest.approx(0.4, abs=1e-6)  # only the place 1 km away
    assert first["d_ring5"] == pytest.approx(0.0, abs=1e-6)
    assert first["sum_k_exp2"] == pytest.approx(math.exp(-0.5) + math.exp(-1.5), abs=1e-6)
    assert first["sum_k_ring2"] == pytest.approx(1.0)
    assert first["sum_k_ring5"] == pytest.approx(2.0)
    assert [second["d_exp2"], second["d_ring2"], second["d_ring5"]] == [0.0, 0.0, 0.0]
    assert "municipalities_with_pair=1" in manifest["notes"]
    assert "close_pairs=1" in manifest["notes"]
    assert "rows=2" in manifest["notes"]


def test_output_types_and_order(tmp_path):
    second = muni(
        "1100003", "30", close=True, places=[(1, 1.5, 60, 20, 20)], cells=[5, 0, 1], uf="AC", dy=200
    )
    store, manifests = inputs([second, A])
    out = output(store, run(store, manifests, tmp_path))
    assert out["cd_ibge"].to_list() == sorted(out["cd_ibge"].to_list())
    assert out.filter(pl.col("cd_ibge") == "1100003")["x_km"].to_list() == [X0, X0 + 1, X0 + 5]
    assert out.schema["x_km"] == pl.Int64
    assert out.schema["n_pairs"] == pl.Int64
    assert out.schema["ano"] == pl.Int64
    assert out.schema["d_exp2"] == pl.Float64
    assert out.schema["cd_ibge"] == pl.Utf8


def test_swapping_winner_and_loser_negates_exposure(tmp_path):
    swapped = {**A, "swap": True}
    store, manifests = inputs([A, B])
    out = output(store, run(store, manifests, tmp_path))
    store2, manifests2 = inputs([swapped, B])
    out2 = output(store2, run(store2, manifests2, tmp_path))
    for name in ("d_exp2", "d_ring2", "d_ring5"):
        a, b = out[name].to_list(), out2[name].to_list()
        assert a[0] != 0
        assert b[0] == pytest.approx(-a[0], abs=1e-9)
        assert b[1] == a[1] == 0.0


def test_reach_rules(tmp_path):
    # Two places 3 km either side of the cell at cx = 0; a cell at cx = 15 is 12 km from
    # the nearest place.
    c = muni(
        "1100003",
        "30",
        close=True,
        places=[(1, -2.5, 60, 20, 20), (2, 3.5, 50, 30, 20)],
        cells=[0, 15],
    )
    store, manifests = inputs([c])
    out = output(store, run(store, manifests, tmp_path))
    assert out["x_km"].to_list() == [X0]
    row = out.row(0, named=True)
    assert row["d_ring2"] is None
    assert row["d_ring5"] == pytest.approx(0.3, abs=1e-6)
    assert row["d_exp2"] == pytest.approx(0.3, abs=1e-6)
    assert row["sum_k_ring2"] == 0.0


def unchanged(store, before):
    assert store.list("") == before


def test_no_close_pair_stops_the_build(tmp_path):
    store, manifests = inputs([B])
    before = store.list("")
    with pytest.raises(BuildError, match="no close pair"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_no_exposed_cell_stops_the_build(tmp_path):
    flat = muni("1100003", "30", close=True, places=[(1, 1.5, 0, 0, 100)], cells=[0])
    store, manifests = inputs([flat])
    before = store.list("")
    with pytest.raises(BuildError, match="no exposed cell"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_a_duplicate_cell_stops_the_build(tmp_path):
    store, manifests = inputs([A], duplicate=True)
    before = store.list("")
    with pytest.raises(BuildError, match="more than once"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_cell_outside_grid_cells_is_caught():
    table = pl.DataFrame({"nome_1KM": [f"1KME{X0}N{Y0}"], "cd_ibge": ["1100009"], "ano": [YEAR]})
    cells = pl.DataFrame({"nome_1KM": [f"1KME{X0}N{Y0}"], "cd_ibge": ["1100001"]})
    with pytest.raises(BuildError, match="not in grid_cells"):
        ce.check_keys(table, cells)
    ce.check_keys(table.with_columns(pl.lit("1100001").alias("cd_ibge")), cells)


def test_a_duplicate_key_is_caught():
    table = pl.DataFrame({"nome_1KM": ["a", "a"], "cd_ibge": ["1", "1"], "ano": [YEAR, YEAR]})
    with pytest.raises(BuildError, match="more than once"):
        ce.check_keys(table, table.select("nome_1KM", "cd_ibge"))


def test_exposure_above_n_pairs_stops_the_build(tmp_path, monkeypatch):
    real = sh.exposure

    def inflated(*args, **kwargs):
        return real(*args, **kwargs).with_columns(pl.col("D_i") + 5.0)

    monkeypatch.setattr(ce.sh, "exposure", inflated)
    store, manifests = inputs([A])
    before = store.list("")
    with pytest.raises(BuildError, match="above n_pairs"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_rings_must_be_nested(tmp_path, monkeypatch):
    real = sh.exposure

    def broken(dist, totals, shares, pairs, name, measure):
        out = real(dist, totals, shares, pairs, name, measure)
        return out.head(0) if name == "ring5" else out

    monkeypatch.setattr(ce.sh, "exposure", broken)
    store, manifests = inputs([A])
    before = store.list("")
    with pytest.raises(BuildError, match="where d_ring5 is null"):
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
    sources = ce.code_sources()
    assert len(sources) == 3
    assert any("def exposure" in s for s in sources)
    changed = [s + "\n# changed" if "def exposure" in s else s for s in sources]
    monkeypatch.setattr(ce, "code_sources", lambda modules=None: changed)
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
    manifests["tse_results"]["files"][0]["sha256"] = "0" * 64
    before = store.list("")
    with pytest.raises(BuildError, match="does not match the sha256"):
        run(store, manifests, tmp_path)
    unchanged(store, before)


def test_a_missing_input_raises(tmp_path):
    store, manifests = inputs([A, B])
    manifests["polling_places"]["files"] = []
    with pytest.raises(BuildError, match="expected a file matching"):
        run(store, manifests, tmp_path)


def test_the_pipeline_script_reads_the_four_manifests():
    root = Path(__file__).resolve().parents[1]
    text = (root / "pipeline" / "build" / "cell_exposure.py").read_text(encoding="utf-8")
    for name in ("grid_cells", "polling_places", "section_votes", "tse_results"):
        assert f'_load("{name}")' in text
        assert (root / "data" / "manifests" / "build" / f"{name}.json").exists()
