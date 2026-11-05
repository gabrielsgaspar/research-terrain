"""Tests for terrain.earthengine with a fake Earth Engine and a MemoryStore."""

import copy
import io
import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import tifffile

from terrain import earthengine
from terrain.catalog import dataset
from terrain.earthengine import EarthEngineError, acquire_mapbiomas, check_file, export_params
from terrain.manifest import validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROWS, COLS, CODES = 3, 4, 7
SHAPE = (ROWS, COLS, CODES)
NAME = "mapbiomas_deforestation"


def small_entry():
    entry = copy.deepcopy(dataset(NAME))
    entry["earthengine"]["years"] = [2004, 2005]
    entry["earthengine"]["grid_km"] = {"x0": 10, "x1": 10 + COLS, "y0": 20, "y1": 20 + ROWS}
    return entry


def good_array(empty_cells=0):
    arr = np.zeros(SHAPE, dtype=np.uint16)
    arr[:, :] = [1429, 1429, 1429, 1429, 1429, 1429, 1426]
    flat = arr.reshape(-1, CODES)
    flat[:empty_cells] = 0
    return arr


def tif_bytes(arr):
    buf = io.BytesIO()
    tifffile.imwrite(buf, arr)
    return buf.getvalue()


class FakeEE:
    def __init__(self, store, arrays=None, states=None, update_time="2025-08-09T18:24:56Z"):
        self.store = store
        self.arrays = arrays or {}
        self.states = states or {}  # year -> list of (state, message), last one repeats
        self.update_time = update_time
        self.started = []
        self.write_files = True

    def asset_info(self, asset):
        return {"updateTime": self.update_time, "sizeBytes": 123}

    def start_export(self, year, params, bucket_prefix):
        self.started.append((year, bucket_prefix))
        if self.write_files:
            arr = self.arrays.get(year, good_array())
            self.store.create(bucket_prefix + params["files"][year], tif_bytes(arr))
        return str(year)

    def task_state(self, task_id):
        seq = self.states.get(int(task_id), [("COMPLETED", "")])
        state = seq[0]
        if len(seq) > 1:
            seq.pop(0)
        return state


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = 0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s
        self.sleeps += 1


def run(store, ee, entry, tmp_path, clock=None, today=date(2026, 11, 5), **kw):
    clock = clock or Clock()
    return acquire_mapbiomas(
        store, ee, entry, today, tmp_path, "abc123", clock.sleep, clock.time, **kw
    )


def test_export_params_from_real_catalog_entry():
    p = export_params(dataset(NAME))
    assert p["crs"].startswith("PROJCS[")
    assert not any(k in p["crs"] for k in ("PROJCRS", "BASEGEOGCRS", "USAGE["))
    assert p["crs_transform"] == [1000, 0, 2823000, 0, -1000, 11902000]
    assert p["dimensions"] == "3350x2580"
    assert p["file_dimensions"] == [3584, 2816]
    assert p["shard_size"] == 128
    assert all(d % p["shard_size"] == 0 for d in p["file_dimensions"])
    assert p["years"] == list(range(2004, 2025))
    assert p["codes"] == [1, 2, 3, 4, 5, 6, 7]
    assert p["scale"] == 10000
    assert p["shape"] == (2580, 3350, 7)
    assert p["bands"][2004] == "classification_2004"
    assert p["files"][2024] == "mapbiomas_shares_2024.tif"


def test_created_run(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store)
    m = run(store, ee, small_entry(), tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == "data/raw/mapbiomas/2026-11-05/"
    assert [f["path"] for f in m["files"]] == [
        "data/raw/mapbiomas/2026-11-05/mapbiomas_shares_2004.tif",
        "data/raw/mapbiomas/2026-11-05/mapbiomas_shares_2005.tif",
    ]
    assert all(f["bytes"] > 0 for f in m["files"])
    src = m["sources"][0]
    assert src["last_modified"] == "2025-08-09T18:24:56Z" and src["bytes"] == 123
    assert validate_manifest(m, stage="acquire", dataset=NAME) == []
    assert m["notes"] == "cells with data per year: 2004=12, 2005=12"
    write_manifest(m, store, tmp_path / "out.json")


def test_polls_until_completed(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store, states={2004: [("RUNNING", ""), ("RUNNING", ""), ("COMPLETED", "")]})
    clock = Clock()
    m = run(store, ee, small_entry(), tmp_path, clock=clock)
    assert m["status"] == "created" and clock.sleeps == 2


def test_unchanged_and_new_versions(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    first = run(store, FakeEE(store), entry, tmp_path)
    write_manifest(first, store, tmp_path / "m.json")

    same = FakeEE(store)
    again = run(store, same, entry, tmp_path)
    assert again["status"] == "unchanged" and same.started == []
    assert again["gcs_prefix"] == first["gcs_prefix"]

    newer = FakeEE(store, update_time="2026-01-01T00:00:00Z")
    assert run(store, newer, entry, tmp_path)["gcs_prefix"] == "data/raw/mapbiomas/2026-11-05-2/"

    changed = copy.deepcopy(entry)
    changed["earthengine"]["years"] = [2004]
    assert run(store, FakeEE(store), changed, tmp_path)["status"] == "created"


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_stopped_task_raises(tmp_path, state):
    store = MemoryStore()
    ee = FakeEE(store, states={2005: [(state, "quota exceeded")]})
    with pytest.raises(EarthEngineError, match="quota exceeded"):
        run(store, ee, small_entry(), tmp_path)
    assert not any(p.endswith("_MANIFEST.json") for p in store.list(""))


def test_timeout_raises(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store, states={2004: [("RUNNING", "")]})
    with pytest.raises(EarthEngineError, match="not finished after 160 minutes"):
        run(store, ee, small_entry(), tmp_path)
    assert not any(p.endswith("_MANIFEST.json") for p in store.list(""))


PREFIX = "data/raw/mapbiomas/2026-11-05/"


def has_manifest(store):
    return any(p.endswith("_MANIFEST.json") for p in store.list(""))


def test_timeout_then_resume(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    first = FakeEE(store, states={2004: [("RUNNING", "")]})
    msg = (
        r"exports not finished after 160 minutes \(1 of 2 completed\); "
        r"run again to resume " + PREFIX
    )
    with pytest.raises(EarthEngineError, match=msg):
        run(store, first, entry, tmp_path)
    rec = json.loads(store.read_bytes(PREFIX + "exports.json"))
    assert rec["tasks"] == {"2004": "2004", "2005": "2005"}
    assert rec["sources"][0]["last_modified"] == "2025-08-09T18:24:56Z"
    assert not has_manifest(store)

    second = FakeEE(store)
    m = run(store, second, entry, tmp_path)
    assert second.started == []
    assert m["status"] == "created" and m["gcs_prefix"] == PREFIX
    assert [f["path"] for f in m["files"]] == [
        PREFIX + "mapbiomas_shares_2004.tif",
        PREFIX + "mapbiomas_shares_2005.tif",
    ]


def test_new_version_does_not_resume(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    with pytest.raises(EarthEngineError):
        run(store, FakeEE(store, states={2004: [("RUNNING", "")]}), entry, tmp_path)
    newer = FakeEE(store, update_time="2026-01-01T00:00:00Z")
    m = run(store, newer, entry, tmp_path)
    assert m["gcs_prefix"] == "data/raw/mapbiomas/2026-11-05-2/"
    assert [y for y, _ in newer.started] == [2004, 2005]


def test_failed_pending_folder_not_resumed(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    with pytest.raises(EarthEngineError, match="quota"):
        run(store, FakeEE(store, states={2005: [("FAILED", "quota exceeded")]}), entry, tmp_path)
    again = FakeEE(store, states={2005: [("FAILED", "quota exceeded")]})
    with pytest.raises(EarthEngineError, match="quota"):
        run(store, again, entry, tmp_path)
    assert [p for _, p in again.started] == [PREFIX.replace("05/", "05-2/")] * 2


def test_folder_with_manifest_not_resumed(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    write_manifest(run(store, FakeEE(store), entry, tmp_path), store, tmp_path / "m.json")
    assert store.exists(PREFIX + "exports.json")
    again = FakeEE(store)
    m = run(store, again, entry, tmp_path)
    assert m["status"] == "unchanged" and again.started == []


def test_missing_file_raises(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store)
    ee.write_files = False
    with pytest.raises(EarthEngineError, match="missing"):
        run(store, ee, small_entry(), tmp_path)
    assert store.list("") == ["data/raw/mapbiomas/2026-11-05/exports.json"]


def bad_arrays():
    wrong_shape = np.zeros((ROWS + 1, COLS, CODES), dtype=np.uint16)
    wrong_shape[:] = good_array()[0, 0]
    bad_sum = good_array()
    bad_sum[0, 0] = [1285, 1285, 1285, 1285, 1285, 1285, 1290]  # sums to 9000
    sparse = good_array(empty_cells=ROWS * COLS // 2 + 1)
    return {
        "dtype": good_array().astype(np.uint8),
        "shape": wrong_shape,
        "sum": bad_sum,
        "sparse": sparse,
    }


@pytest.mark.parametrize("kind", ["dtype", "shape", "sum", "sparse"])
def test_bad_file_raises(tmp_path, kind):
    store = MemoryStore()
    ee = FakeEE(store, arrays={2005: bad_arrays()[kind]})
    with pytest.raises(EarthEngineError):
        run(store, ee, small_entry(), tmp_path)
    assert not any(p.endswith("_MANIFEST.json") for p in store.list(""))


def test_check_file_accepts_rounding_and_half_empty(tmp_path):
    arr = good_array(empty_cells=ROWS * COLS // 2)
    arr[ROWS - 1, COLS - 1, 0] += 7
    path = tmp_path / "a.tif"
    path.write_bytes(tif_bytes(arr))
    assert check_file(path, SHAPE, 10000) == ROWS * COLS - ROWS * COLS // 2


def test_check_file_rejects_unreadable(tmp_path):
    path = tmp_path / "a.tif"
    path.write_bytes(b"not a tiff")
    with pytest.raises(EarthEngineError, match="cannot be read"):
        check_file(path, SHAPE, 10000)


def test_module_source_avoids_forbidden_prefixes():
    text = Path(earthengine.__file__).read_text(encoding="utf-8")
    split = "data/derived/" + "split"
    sealed = "sealed" + "/"
    assert split not in text and sealed not in text
