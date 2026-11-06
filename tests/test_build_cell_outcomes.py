import hashlib
import io
import json
import logging
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import tifffile

from terrain.builds import cell_outcomes as co
from terrain.builds.cell_outcomes import BuildError, build, input_hash
from terrain.explore import EXPLORE_LIST
from terrain.manifest import MANIFEST_NAME, check_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/cell_outcomes/"
SEALED = "sealed/outcomes/cell_outcomes/"
ACQUIRE_PREFIX = "data/raw/mapbiomas/2026-01-01/"
GRID_PREFIX = "data/derived/grid_cells/aaaa/"
X0, X1, Y0, Y1 = 10, 14, 20, 23
YEARS = [2004, 2005]
BLOCK = {
    "years": YEARS,
    "codes": [1, 2, 3, 4, 5, 6, 7],
    "scale": 10000,
    "grid_km": {"x0": X0, "x1": X1, "y0": Y0, "y1": Y1},
    "file": "shares_<year>.tif",
}
EXPLORE_MUNI, CONFIRM_MUNI = "1100015", "1100023"
# (name, municipality, x_km, y_km)
CELLS = [
    ("A1", EXPLORE_MUNI, 10, 20),
    ("A2", EXPLORE_MUNI, 11, 21),
    ("B1", CONFIRM_MUNI, 12, 22),
    ("B2", CONFIRM_MUNI, 13, 20),
]


def pixels(year: int) -> np.ndarray:
    """A distinctive array: each pixel holds seven values that sum to at most 10,000."""
    rows, cols = Y1 - Y0, X1 - X0
    arr = np.zeros((rows, cols, 7), dtype=np.uint16)
    for r in range(rows):
        for c in range(cols):
            arr[r, c] = [1000 + 37 * r + 11 * c + (year - 2000) + k for k in range(7)]
    return arr


def tif_bytes(arr: np.ndarray, tmp_path: Path) -> bytes:
    path = tmp_path / "scratch.tif"
    tifffile.imwrite(path, arr, photometric="minisblack")
    return path.read_bytes()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def grid_parquet(cells=CELLS) -> bytes:
    buf = io.BytesIO()
    pl.DataFrame(
        {
            "nome_1KM": [c[0] for c in cells],
            "cd_ibge": [c[1] for c in cells],
            "x_km": [c[2] for c in cells],
            "y_km": [c[3] for c in cells],
        }
    ).write_parquet(buf)
    return buf.getvalue()


def split_csv(codes=(EXPLORE_MUNI,)) -> bytes:
    return ("code_ibge\n" + "".join(f"{c}\n" for c in codes)).encode("utf-8")


def setup(tmp_path: Path, arrays=None, cells=CELLS, split=None, entries_sha=None):
    """A store with the inputs, and the two manifests."""
    store = MemoryStore()
    files = []
    for y in YEARS:
        arr = (arrays or {}).get(y, pixels(y))
        blob = tif_bytes(arr, tmp_path)
        path = f"{ACQUIRE_PREFIX}shares_{y}.tif"
        store.create(path, blob)
        files.append(entry(path, blob))
    if entries_sha:
        files[0]["sha256"] = entries_sha
    grid_blob = grid_parquet(cells)
    store.create(GRID_PREFIX + "grid_cells.parquet", grid_blob)
    store.create(EXPLORE_LIST, split or split_csv())
    acquire = {"gcs_prefix": ACQUIRE_PREFIX, "files": files}
    grid = {
        "gcs_prefix": GRID_PREFIX,
        "files": [entry(GRID_PREFIX + "grid_cells.parquet", grid_blob)],
    }
    return store, acquire, grid


def run(store, acquire, grid, tmp_path, block=BLOCK):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(
        store,
        acquire,
        grid,
        block,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=work,
        code_commit="abc",
        created_at="2026-01-01T00:00:00+00:00",
    )


def read(store, path) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


def test_halves_hold_only_their_municipality_under_one_hash(tmp_path):
    store, acquire, grid = setup(tmp_path)
    manifest = run(store, acquire, grid, tmp_path)
    prefix = manifest["gcs_prefix"]
    hashed = prefix.removeprefix(DERIVED)
    for y in YEARS:
        derived = read(store, f"{prefix}cell_outcomes_{y}.parquet")
        sealed = read(store, f"{SEALED}{hashed}cell_outcomes_{y}.parquet")
        assert set(derived["cd_ibge"]) == {EXPLORE_MUNI}
        assert set(sealed["cd_ibge"]) == {CONFIRM_MUNI}
        assert sorted(derived["nome_1KM"]) == ["A1", "A2"]
        assert sorted(sealed["nome_1KM"]) == ["B1", "B2"]
        arr = pixels(y)
        for frame in (derived, sealed):
            assert set(frame["ano"]) == {y}
            for row in frame.iter_rows(named=True):
                _, _, x, yk = next(c for c in CELLS if c[0] == row["nome_1KM"])
                pixel = arr[Y1 - 1 - yk, x - X0]
                assert [row[f"code_{k}"] for k in range(1, 8)] == pixel.tolist()
                assert row["has_data"]
                assert row["unclassified"] == max(0, 10000 - int(pixel.sum()))
        assert derived.schema["code_4"] == pl.UInt16
        assert derived["cd_ibge"].to_list() == sorted(derived["cd_ibge"].to_list())


def test_manifest_lists_sealed_files(tmp_path):
    store, acquire, grid = setup(tmp_path)
    manifest = run(store, acquire, grid, tmp_path)
    check_manifest(manifest, stage="build", dataset="cell_outcomes")
    assert all(f["path"].startswith("data/derived/") for f in manifest["files"])
    assert len(manifest["files"]) == len(manifest["sealed_files"]) == len(YEARS)
    for f in manifest["sealed_files"]:
        assert f["path"].startswith(SEALED)
        assert hashlib.sha256(store.read_bytes(f["path"])).hexdigest() == f["sha256"]
        assert f["bytes"] == len(store.read_bytes(f["path"]))
    assert manifest["gcs_prefix"].removeprefix(DERIVED) == manifest["sealed_files"][0][
        "path"
    ].removeprefix(SEALED).removesuffix("cell_outcomes_2004.parquet")


def objects(store) -> list[str]:
    return store.list("")


def test_wrong_shape_stops_the_build(tmp_path):
    bad = np.zeros((Y1 - Y0 + 1, X1 - X0, 7), dtype=np.uint16)
    bad[...] = 1000
    store, acquire, grid = setup(tmp_path, arrays={2005: bad})
    before = objects(store)
    with pytest.raises(BuildError, match="shape"):
        run(store, acquire, grid, tmp_path)
    assert objects(store) == before


def test_sum_above_ten_thousand_stops_the_build(tmp_path):
    arr = pixels(2004)
    arr[Y1 - 1 - 20, 0] = [1500, 1500, 1500, 1500, 1500, 1500, 2000]  # cell A1: 11,000
    store, acquire, grid = setup(tmp_path, arrays={2004: arr})
    before = objects(store)
    with pytest.raises(BuildError, match="more than 10,000"):
        run(store, acquire, grid, tmp_path)
    assert objects(store) == before


def test_too_few_cells_with_data_stops_the_build(tmp_path):
    arr = pixels(2004)
    arr[Y1 - 1 - 20, 0] = 0  # one of four cells has no data
    store, acquire, grid = setup(tmp_path, arrays={2004: arr})
    before = objects(store)
    with pytest.raises(BuildError, match="have data"):
        run(store, acquire, grid, tmp_path)
    assert objects(store) == before


def test_sha_mismatch_stops_the_build(tmp_path):
    store, acquire, grid = setup(tmp_path, entries_sha="0" * 64)
    before = objects(store)
    with pytest.raises(BuildError, match="sha256"):
        run(store, acquire, grid, tmp_path)
    assert objects(store) == before


def test_bad_grid_cells_stop_the_build(tmp_path):
    cells = [*CELLS, ("C1", None, 12, 21)]
    store, acquire, grid = setup(tmp_path, cells=cells)
    with pytest.raises(BuildError, match="no municipality"):
        run(store, acquire, grid, tmp_path)
    cells = [*CELLS, ("C1", EXPLORE_MUNI, 99, 21)]
    store, acquire, grid = setup(tmp_path, cells=cells)
    with pytest.raises(BuildError, match="outside the grid"):
        run(store, acquire, grid, tmp_path)


def test_existing_sealed_object_stops_before_derived_files(tmp_path):
    store, acquire, grid = setup(tmp_path)
    hashed = run(store, acquire, grid, tmp_path)["gcs_prefix"].removeprefix(DERIVED)
    fresh, acquire, grid = setup(tmp_path)
    fresh.create(f"{SEALED}{hashed}cell_outcomes_2004.parquet", b"already here")
    with pytest.raises(BuildError, match="already exists"):
        run(fresh, acquire, grid, tmp_path)
    assert fresh.list(DERIVED) == []


def test_partly_unclassified_cell_is_kept(tmp_path):
    arr = pixels(2004)
    arr[Y1 - 1 - 20, 0] = [3000, 2000, 1000, 1000, 1000, 500, 500]  # sum 9,000
    store, acquire, grid = setup(tmp_path, arrays={2004: arr})
    manifest = run(store, acquire, grid, tmp_path)
    frame = read(store, manifest["gcs_prefix"] + "cell_outcomes_2004.parquet")
    row = frame.filter(pl.col("nome_1KM") == "A1").row(0, named=True)
    assert row["unclassified"] == 1000
    # The synthetic pixels all sum to well under 10,000, so every cell is partly unclassified.
    assert (
        "2004: cells_exploration=2, cells_confirmation=2, cells_without_data=0, "
        in (manifest["notes"])
    )
    assert "cells_partly_unclassified=4" in manifest["notes"]


def test_notes_count_cells_by_half(tmp_path):
    store, acquire, grid = setup(tmp_path)
    notes = run(store, acquire, grid, tmp_path)["notes"]
    assert "2004: cells_exploration=2, cells_confirmation=2, cells_without_data=0" in notes


def test_second_run_is_unchanged_and_split_change_changes_hash(tmp_path):
    store, acquire, grid = setup(tmp_path)
    first = run(store, acquire, grid, tmp_path)
    store.create(first["gcs_prefix"] + MANIFEST_NAME, json.dumps(first).encode("utf-8"))
    before = objects(store)
    second = run(store, acquire, grid, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert objects(store) == before

    other, acquire, grid = setup(tmp_path, split=split_csv((EXPLORE_MUNI, CONFIRM_MUNI)))
    changed = run(other, acquire, grid, tmp_path)
    assert changed["status"] == "created"
    assert changed["gcs_prefix"] != first["gcs_prefix"]


def test_hash_depends_on_split_list_and_years():
    files = [{"sha256": "a" * 64}]
    base = input_hash(files, "s1", (2004,), code=["x"])
    assert input_hash(files, "s2", (2004,), code=["x"]) != base
    assert input_hash(files, "s1", (2004, 2005), code=["x"]) != base
    assert input_hash(files, "s1", (2004,), code=["y"]) != base


def test_malformed_split_list_stops_the_build(tmp_path):
    for bad in (b"municipio\n1100015\n", b"code_ibge\n123\n", b"code_ibge\n"):
        store, acquire, grid = setup(tmp_path, split=bad)
        with pytest.raises(BuildError):
            run(store, acquire, grid, tmp_path)


def test_no_code_statistic_in_notes_log_or_output(tmp_path, capsys, caplog):
    arr = np.full((Y1 - Y0, X1 - X0, 7), 1111, dtype=np.uint16)
    arr[..., 3] = 1234
    arr[..., 5] = 1357
    store, acquire, grid = setup(tmp_path, arrays={2004: arr, 2005: arr})
    with caplog.at_level(logging.DEBUG):
        manifest = run(store, acquire, grid, tmp_path)
    seen = manifest["notes"] + capsys.readouterr().out + caplog.text
    for value in ("1111", "1234", "1357"):
        assert value not in seen


def test_module_names_its_code_modules():
    assert {p.name for p in co.CODE_MODULES} == {
        "cell_outcomes.py",
        "grid.py",
        "polling_place_tenure.py",
    }
