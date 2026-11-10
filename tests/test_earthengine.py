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

    bands = None  # None: every band exists; else the list of existing bands
    images = None  # year -> list of image ids; None: one image per year

    def asset_info(self, asset):
        return {"updateTime": self.update_time, "sizeBytes": 123}

    def band_names(self, asset):
        if self.bands is None:
            return [f"classification_{y}" for y in range(1985, 2025)] + ["average_masked"]
        return list(self.bands)

    def year_images(self, collection, year):
        if self.images is not None:
            return self.images.get(year, [])
        return [f"{collection}/{year}"]

    def start_export(self, year, params, bucket_prefix):
        self.started.append((year, bucket_prefix))
        self.params = params
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
    assert m["notes"] == "cells with data per year: " + ", ".join(
        f"{y}=12 (0 partly unclassified)" for y in (2004, 2005)
    )
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
    bad_sum[0, 0] = [1571, 1571, 1571, 1571, 1571, 1571, 1574]  # sums to 11000
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
    assert check_file(path, SHAPE, 10000) == (ROWS * COLS - ROWS * COLS // 2, 0)


def test_check_file_counts_partly_unclassified_cells(tmp_path):
    arr = good_array()
    arr[0, 0] = [1285, 1285, 1285, 1285, 1285, 1285, 1290]  # 10% without a code
    path = tmp_path / "a.tif"
    tifffile.imwrite(path, arr)
    assert check_file(path, SHAPE, 10000) == (ROWS * COLS, 1)


@pytest.mark.parametrize("compression", ["lzw", "deflate"])
def test_check_file_reads_compressed_exports(tmp_path, compression):
    # Earth Engine batch exports were LZW (run 42116556978); test tiles were Deflate
    path = tmp_path / "a.tif"
    tifffile.imwrite(path, good_array(), compression=compression)
    assert check_file(path, SHAPE, 10000) == (ROWS * COLS, 0)


def test_check_file_rejects_unreadable(tmp_path):
    path = tmp_path / "a.tif"
    path.write_bytes(b"not a tiff")
    with pytest.raises(EarthEngineError, match="cannot be read"):
        check_file(path, SHAPE, 10000)


def test_deforestation_params_and_source_are_pinned():
    entry = dataset(NAME)
    p = export_params(entry)
    assert p["asset"] == (
        "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
        "mapbiomas_brazil_collection10_deforestation_secondary_vegetation_v2"
    )
    assert p["mode"] == "shares"
    assert p["crs_transform"] == [1000, 0, 2823000, 0, -1000, 11902000]
    assert p["dimensions"] == "3350x2580"
    assert p["file_dimensions"] == [3584, 2816]
    assert p["min_share_with_data"] == 0.5
    assert p["shard_size"] == 128
    assert p["codes"] == [1, 2, 3, 4, 5, 6, 7]
    assert p["scale"] == 10000
    assert p["shape"] == (2580, 3350, 7)
    assert p["bands"][2004] == "classification_2004"
    assert p["files"][2024] == "mapbiomas_shares_2024.tif"
    src = earthengine.source(entry, {"updateTime": "t", "sizeBytes": 1})
    assert src["url"] == p["asset"]
    assert src["etag"] == "995bac2efc56b887"


def groups_entry():
    entry = small_entry()
    block = entry["earthengine"]
    del block["codes"]
    block.update(
        mode="groups",
        groups={"urban": [24], "native": [3, 4, 5]},
        file_dimensions=[256, 128],
        min_share_with_data=0.35,
    )
    return entry


def log_entry():
    entry = copy.deepcopy(dataset("viirs_annual"))
    block = entry["earthengine"]
    block["years"] = [2021, 2022]
    block["grid_km"] = {"x0": 10, "x1": 10 + COLS, "y0": 20, "y1": 20 + ROWS}
    block["collections"] = [
        {"asset": "NOAA/V21", "years": [2021]},
        {"asset": "NOAA/V22", "years": [2022]},
    ]
    return entry


def log_array(value=500, empty_cells=0):
    arr = np.full((ROWS, COLS), value, dtype=np.uint16)
    arr.reshape(-1)[:empty_cells] = 0
    return arr


def test_groups_params_and_run(tmp_path):
    p = export_params(groups_entry())
    assert p["mode"] == "groups" and p["groups"] == {"urban": [24], "native": [3, 4, 5]}
    assert p["shape"] == (ROWS, COLS, 2)
    assert p["file_dimensions"] == [256, 128] and p["min_share_with_data"] == 0.35
    store = MemoryStore()
    arrays = {y: np.full((ROWS, COLS, 2), 3000, dtype=np.uint16) for y in (2004, 2005)}
    ee = FakeEE(store, arrays=arrays)
    m = run(store, ee, groups_entry(), tmp_path)
    assert m["status"] == "created" and [y for y, _ in ee.started] == [2004, 2005]
    assert ee.params["mode"] == "groups"


def test_missing_band_raises_before_any_export(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store)
    ee.bands = ["classification_2004"]
    with pytest.raises(EarthEngineError, match="missing bands"):
        run(store, ee, small_entry(), tmp_path)
    assert ee.started == [] and store.list("") == []


def test_log1p_params():
    p = export_params(log_entry())
    assert p["mode"] == "log1p_mean" and p["shape"] == (ROWS, COLS, 1)
    assert p["year_assets"] == {2021: "NOAA/V21", 2022: "NOAA/V22"}
    assert p["bands"][2021] == "average_masked" and p["scale"] == 1000
    assert p["files"][2022] == "viirs_log1p_2022.tif" and p["min_share_with_data"] == 0.01
    full = export_params(dataset("viirs_annual"))
    assert full["years"] == list(range(2013, 2025))
    assert full["year_assets"][2021] == "NOAA/VIIRS/DNB/ANNUAL_V21"
    assert full["year_assets"][2022] == "NOAA/VIIRS/DNB/ANNUAL_V22"


def test_log1p_run_records_images(tmp_path):
    store = MemoryStore()
    arrays = {2021: log_array(), 2022: log_array()}
    ee = FakeEE(store, arrays=arrays)
    entry = log_entry()
    m = run(store, ee, entry, tmp_path)
    assert m["status"] == "created"
    assert ee.params["images"] == {2021: "NOAA/V21/2021", 2022: "NOAA/V22/2022"}
    assert "2021=NOAA/V21/2021, 2022=NOAA/V22/2022" in m["notes"]
    src = m["sources"][0]
    assert src["url"] == "NOAA/V21, NOAA/V22" and src["bytes"] == 246
    assert validate_manifest(m, stage="acquire", dataset="viirs_annual") == []


@pytest.mark.parametrize("found", [[], ["a", "b"]])
def test_log1p_year_without_exactly_one_image_raises(tmp_path, found):
    store = MemoryStore()
    ee = FakeEE(store)
    ee.images = {2021: ["NOAA/V21/2021"], 2022: found}
    with pytest.raises(EarthEngineError, match="expected 1"):
        run(store, ee, log_entry(), tmp_path)
    assert ee.started == [] and store.list("") == []


def test_log1p_missing_band_raises_before_any_export(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store)
    ee.bands = ["avg_rad"]
    with pytest.raises(EarthEngineError, match="missing band"):
        run(store, ee, log_entry(), tmp_path)
    assert ee.started == [] and store.list("") == []


@pytest.mark.parametrize("collections", ["none", "twice"])
def test_log1p_year_collections_raise(collections):
    entry = log_entry()
    colls = entry["earthengine"]["collections"]
    if collections == "none":
        colls[1]["years"] = []
    else:
        colls[1]["years"] = [2021, 2022]
    with pytest.raises(EarthEngineError, match="no collection|two collections"):
        export_params(entry)


def test_unknown_mode_raises():
    entry = small_entry()
    entry["earthengine"]["mode"] = "mean"
    with pytest.raises(EarthEngineError, match="unknown export mode"):
        export_params(entry)


def write_tif(tmp_path, arr):
    path = tmp_path / "a.tif"
    tifffile.imwrite(path, arr)
    return path


def test_check_file_groups(tmp_path):
    arr = np.full((ROWS, COLS, 2), 3000, dtype=np.uint16)
    assert check_file(write_tif(tmp_path, arr), (ROWS, COLS, 2), 10000, "groups") == (12, 12)
    arr[0, 0] = [6000, 4100]
    with pytest.raises(EarthEngineError, match="sum to more"):
        check_file(write_tif(tmp_path, arr), (ROWS, COLS, 2), 10000, "groups")
    arr = np.zeros((ROWS, COLS, 2), dtype=np.uint16)
    arr[0, :2] = 100  # 2 of 12 cells have data: 17%
    path = write_tif(tmp_path, arr)
    assert check_file(path, (ROWS, COLS, 2), 10000, "groups", 0.15)[0] == 2
    with pytest.raises(EarthEngineError, match="only 2 of 12"):
        check_file(path, (ROWS, COLS, 2), 10000, "groups", 0.35)


def test_check_file_log1p_mean(tmp_path):
    shape = (ROWS, COLS, 1)
    # tifffile returns a one-band file as a 2-D array
    assert check_file(write_tif(tmp_path, log_array()), shape, 1000, "log1p_mean") == (12, 0)
    assert check_file(write_tif(tmp_path, log_array(11000)), shape, 1000, "log1p_mean")[0] == 12
    with pytest.raises(EarthEngineError, match="above 11"):
        check_file(write_tif(tmp_path, log_array(11001)), shape, 1000, "log1p_mean")
    with pytest.raises(EarthEngineError, match="dtype"):
        check_file(write_tif(tmp_path, log_array().astype(np.uint8)), shape, 1000, "log1p_mean")
    with pytest.raises(EarthEngineError, match="shape"):
        check_file(write_tif(tmp_path, log_array()[:2]), shape, 1000, "log1p_mean")
    sparse = write_tif(tmp_path, log_array(empty_cells=11))
    assert check_file(sparse, shape, 1000, "log1p_mean", 0.01)[0] == 1
    with pytest.raises(EarthEngineError, match="only 1 of 12"):
        check_file(sparse, shape, 1000, "log1p_mean", 0.5)


def test_new_catalog_entries_load():
    viirs = dataset("viirs_annual")
    assert viirs["gcs"] == "data/raw/viirs/annual/"
    assert viirs["earthengine"]["band"] == "average_masked"
    cov = dataset("mapbiomas_coverage_national")
    assert cov["gcs"] == "data/raw/mapbiomas/coverage/"
    p = export_params(cov)
    assert p["mode"] == "groups" and list(p["groups"]) == ["urban", "native"]
    assert p["groups"]["native"] == [3, 4, 5, 6, 49, 11, 12, 32, 29, 50]
    assert p["years"] == list(range(2004, 2025)) and p["scale"] == 10000
    assert p["file_dimensions"] == [4608, 4352] and p["min_share_with_data"] == 0.35
    assert p["dimensions"] == "4587x4312" and p["shape"] == (4312, 4587, 2)
    assert all(d % p["shard_size"] == 0 for d in p["file_dimensions"])
    pv = export_params(viirs)
    assert pv["dimensions"] == "4587x4312" and pv["file_dimensions"] == [4608, 4352]


def test_module_source_avoids_forbidden_prefixes():
    text = Path(earthengine.__file__).read_text(encoding="utf-8")
    split = "data/derived/" + "split"
    sealed = "sealed" + "/"
    assert split not in text and sealed not in text


# --- asset info: images have a size, collections do not (run 42862268510) ------


class FakeAssets:
    """Stands in for the `ee` module: only `ee.data.getAsset`."""

    def __init__(self, infos):
        self.infos = infos
        self.data = self

    def getAsset(self, asset):  # noqa: N802 (Earth Engine's name)
        return self.infos[asset]


def real_ee(infos):
    real = object.__new__(earthengine.RealEarthEngine)  # skips ee.Initialize
    real._ee = FakeAssets(infos)
    real._bucket = "bucket"
    return real


def test_real_asset_info_of_an_image_and_a_collection():
    real = real_ee(
        {
            "img": {"type": "IMAGE", "updateTime": "2025-08-09T18:24:56Z", "sizeBytes": "123"},
            # what getAsset gives for NOAA/VIIRS/DNB/ANNUAL_V21: no sizeBytes
            "coll": {"type": "IMAGE_COLLECTION", "updateTime": "2024-03-01T00:00:00Z"},
        }
    )
    assert real.asset_info("img") == {"updateTime": "2025-08-09T18:24:56Z", "sizeBytes": 123}
    assert real.asset_info("coll") == {"updateTime": "2024-03-01T00:00:00Z", "sizeBytes": None}


@pytest.mark.parametrize(
    "info, words",
    [
        ({"type": "IMAGE", "updateTime": "t"}, "no sizeBytes"),
        ({"type": "IMAGE_COLLECTION"}, "no updateTime"),
    ],
)
def test_real_asset_info_missing_fields_raise(info, words):
    with pytest.raises(EarthEngineError, match=words):
        real_ee({"a": info}).asset_info("a")


class CollectionEE(FakeEE):
    """Every asset is a collection: an update time per asset, no size."""

    times = {"NOAA/V21": "2024-03-01T00:00:00Z", "NOAA/V22": "2025-06-01T00:00:00Z"}

    def asset_info(self, asset):
        return {"updateTime": self.times[asset], "sizeBytes": None}


def test_log1p_run_over_collections_records_update_time_and_no_size(tmp_path):
    store = MemoryStore()
    arrays = {2021: log_array(), 2022: log_array()}
    entry = log_entry()
    m = run(store, CollectionEE(store, arrays=arrays), entry, tmp_path)
    assert m["status"] == "created"
    src = m["sources"][0]
    assert src["last_modified"] == "2025-06-01T00:00:00Z" and src["bytes"] is None
    assert validate_manifest(m, stage="acquire", dataset="viirs_annual") == []
    write_manifest(m, store, tmp_path / "m.json")

    same = CollectionEE(store, arrays=arrays)
    again = run(store, same, entry, tmp_path)
    assert again["status"] == "unchanged" and same.started == []

    newer = CollectionEE(store, arrays=arrays)
    newer.times = {**CollectionEE.times, "NOAA/V22": "2026-01-01T00:00:00Z"}
    assert run(store, newer, entry, tmp_path)["status"] == "created"


def test_mapbiomas_image_source_keeps_its_size(tmp_path):
    store = MemoryStore()
    m = run(store, FakeEE(store), small_entry(), tmp_path)
    assert m["sources"][0]["bytes"] == 123
    src = earthengine.source(dataset(NAME), {"updateTime": "t", "sizeBytes": 7})
    assert src["bytes"] == 7 and src["etag"] == "995bac2efc56b887"
