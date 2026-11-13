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
from terrain.campaigns import tick
from terrain.catalog import dataset
from terrain.earthengine import (
    EarthEngineError,
    StillExporting,
    acquire_mapbiomas,
    check_file,
    export_params,
)
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
    """Earth Engine with a task list. A task gets the state sequence `states[year]`
    holds when it starts (default: COMPLETED), the last state repeating; its file is
    written at once unless `write_files` is off or the year is in `unwritten`."""

    def __init__(self, store, arrays=None, states=None, update_time="2025-08-09T18:24:56Z"):
        self.store = store
        self.arrays = arrays or {}
        self.states = states or {}  # year -> list of (state, message), last one repeats
        self.update_time = update_time
        self.started = []
        self.descriptions = []
        self.write_files = True
        self.unwritten = set()
        self.later = {}  # task id -> (year, path): the file is written once it completes
        self.task_list = {}  # task id -> [description, list of (state, message)]

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

    def add_task(self, task_id, description, seq):
        self.task_list[task_id] = [description, list(seq)]

    def start_export(self, year, params, bucket_prefix, description):
        self.started.append((year, bucket_prefix))
        self.descriptions.append(description)
        self.params = params
        task_id = f"T{len(self.task_list) + 1}"
        self.add_task(task_id, description, self.states.get(year, [("COMPLETED", "")]))
        path = bucket_prefix + params["files"][year]
        if self.write_files and year not in self.unwritten:
            self.write(year, path)
        elif self.write_files:
            self.later[task_id] = (year, path)
        return task_id

    def write(self, year, path):
        self.store.create(path, tif_bytes(self.arrays.get(year, good_array())))

    def task_state(self, task_id):
        seq = self.task_list[task_id][1]
        state = seq[0]
        if len(seq) > 1:
            seq.pop(0)
        if state[0] == "COMPLETED" and task_id in self.later:
            self.write(*self.later.pop(task_id))
        return state

    def tasks(self, description_prefix):
        return [
            {"id": t, "description": d, "state": seq[0][0], "error": seq[0][1]}
            for t, (d, seq) in self.task_list.items()
            if d.startswith(description_prefix)
        ]


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
    ee.unwritten = {2004}  # written when its task completes
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
    ee.unwritten = {2005}
    with pytest.raises(EarthEngineError, match="quota exceeded"):
        run(store, ee, small_entry(), tmp_path)
    assert not any(p.endswith("_MANIFEST.json") for p in store.list(""))


def test_timeout_raises_still_exporting(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store, states={2004: [("RUNNING", "")]})
    ee.unwritten = {2004}
    with pytest.raises(StillExporting, match="still exporting: 1 of 2 done after 160 minutes"):
        run(store, ee, small_entry(), tmp_path)
    assert not any(p.endswith("_MANIFEST.json") for p in store.list(""))


PREFIX = "data/raw/mapbiomas/2026-11-05/"


def has_manifest(store):
    return any(p.endswith("_MANIFEST.json") for p in store.list(""))


def test_exports_json_is_written_first_and_descriptions_name_the_folder(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store)
    run(store, ee, small_entry(), tmp_path)
    rec = json.loads(store.read_bytes(PREFIX + "exports.json"))
    assert set(rec) == {"sources", "export_code"}
    assert rec["sources"][0]["last_modified"] == "2025-08-09T18:24:56Z"
    assert rec["export_code"] == earthengine.export_code(export_params(small_entry()))
    assert ee.descriptions == [f"{NAME}_2026-11-05_2004", f"{NAME}_2026-11-05_2005"]


def test_timeout_then_resume_on_a_later_day(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    ee = FakeEE(store, states={2004: [("RUNNING", "")]})
    ee.unwritten = {2004}
    with pytest.raises(StillExporting, match=r"1 of 2 done .* resumes " + PREFIX):
        run(store, ee, entry, tmp_path)
    assert not has_manifest(store)
    # Earth Engine still runs 2004: found by its description, so not started again
    with pytest.raises(StillExporting, match="1 of 2 done"):
        run(store, ee, entry, tmp_path, today=date(2026, 11, 6))
    assert len(ee.started) == 2
    # it finishes: the next run, days later, completes the first folder
    ee.write(2004, PREFIX + "mapbiomas_shares_2004.tif")
    m = run(store, ee, entry, tmp_path, today=date(2026, 11, 9))
    assert len(ee.started) == 2
    assert m["status"] == "created" and m["gcs_prefix"] == PREFIX
    assert [f["path"] for f in m["files"]] == [
        PREFIX + "mapbiomas_shares_2004.tif",
        PREFIX + "mapbiomas_shares_2005.tif",
    ]


@pytest.mark.parametrize("state", ["READY", "RUNNING", "COMPLETED"])
def test_a_task_earth_engine_has_is_never_started_again(tmp_path, state):
    store = MemoryStore()
    entry = small_entry()
    store.create(PREFIX + "exports.json", exports_record(entry))
    ee = FakeEE(store)
    ee.add_task("old", f"{NAME}_2026-11-05_2004", [(state, "")])
    ee.write(2005, PREFIX + "mapbiomas_shares_2005.tif")
    with pytest.raises(EarthEngineError, match="still exporting|file is missing"):
        run(store, ee, entry, tmp_path, limit_s=60)
    assert ee.started == []


def exports_record(entry, **extra):
    current = earthengine.source(entry, {"updateTime": "2025-08-09T18:24:56Z", "sizeBytes": 123})
    rec = {"sources": [current], **extra}
    if "tasks" not in extra:
        rec["export_code"] = earthengine.export_code(export_params(entry))
    return json.dumps(rec).encode("utf-8")


def test_campaign_0007_s11_two_folders_with_failed_overwrites(tmp_path):
    """The state run 43234259734 left: the first folder has every file, though some
    tasks failed on the overwrite (no delete on raw) and one still runs; a second
    folder was started beside it. Old records list task ids and no code hash."""
    store = MemoryStore()
    entry = small_entry()
    first, second = PREFIX, PREFIX.replace("05/", "05-2/")
    store.create(first + "exports.json", exports_record(entry, tasks={"2004": "a", "2005": "b"}))
    store.create(second + "exports.json", exports_record(entry, tasks={"2004": "c", "2005": "d"}))
    ee = FakeEE(store)
    denied = "terrain-acquire does not have storage.objects.delete access"
    for task_id, seq in (("a", [("FAILED", denied)]), ("b", [("RUNNING", "")])):
        ee.add_task(task_id, "mapbiomas_2004", seq)
    for task_id in ("c", "d"):
        ee.add_task(task_id, "mapbiomas_2005", [("READY", "")])
    for year in (2004, 2005):
        ee.write(year, first + f"mapbiomas_shares_{year}.tif")
    ee.write(2004, second + "mapbiomas_shares_2004.tif")
    m = run(store, ee, entry, tmp_path, today=date(2026, 11, 13))
    assert ee.started == []
    assert m["status"] == "created" and m["gcs_prefix"] == first


def test_a_failed_export_without_its_file_starts_again_in_the_same_folder(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    ee = FakeEE(store, states={2005: [("FAILED", "quota exceeded")]})
    ee.unwritten = {2005}
    with pytest.raises(EarthEngineError, match="quota exceeded"):
        run(store, ee, entry, tmp_path)
    ee.states, ee.unwritten = {}, set()
    m = run(store, ee, entry, tmp_path, today=date(2026, 11, 6))
    assert ee.started == [(2004, PREFIX), (2005, PREFIX), (2005, PREFIX)]
    assert m["gcs_prefix"] == PREFIX


def test_a_failed_task_whose_file_is_there_counts_as_done(tmp_path):
    store = MemoryStore()
    ee = FakeEE(store, states={2005: [("RUNNING", ""), ("FAILED", "no delete access")]})
    m = run(store, ee, small_entry(), tmp_path)
    assert m["status"] == "created" and m["gcs_prefix"] == PREFIX


def test_new_version_does_not_resume(tmp_path):
    store = MemoryStore()
    entry = small_entry()
    first = FakeEE(store, states={2004: [("RUNNING", "")]})
    first.unwritten = {2004}
    with pytest.raises(StillExporting):
        run(store, first, entry, tmp_path)
    newer = FakeEE(store, update_time="2026-01-01T00:00:00Z")
    m = run(store, newer, entry, tmp_path)
    assert m["gcs_prefix"] == "data/raw/mapbiomas/2026-11-05-2/"
    assert [y for y, _ in newer.started] == [2004, 2005]


def test_new_export_code_does_not_resume(tmp_path, monkeypatch):
    store = MemoryStore()
    entry = small_entry()
    first = FakeEE(store, states={2004: [("RUNNING", "")]})
    first.unwritten = {2004}
    with pytest.raises(StillExporting):
        run(store, first, entry, tmp_path)

    def other_image(self, year, params):  # a changed pixel computation
        return None

    monkeypatch.setattr(earthengine.RealEarthEngine, "_image", other_image)
    m = run(store, FakeEE(store), entry, tmp_path)
    assert m["gcs_prefix"] == "data/raw/mapbiomas/2026-11-05-2/"


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


def test_run_script_prints_still_exporting(monkeypatch, tmp_path):
    def stuck(*args, **kwargs):
        raise StillExporting(30, 41, "data/raw/mapbiomas/mining/2026-11-12/", 160)

    monkeypatch.setattr(earthengine, "GCSStore", lambda bucket: None)
    monkeypatch.setattr(earthengine, "RealEarthEngine", lambda bucket: None)
    monkeypatch.setattr(earthengine, "acquire_mapbiomas", stuck)
    monkeypatch.setenv("TERRAIN_BUCKET", "bucket")
    monkeypatch.setattr("sys.argv", ["x", "--manifest-out", str(tmp_path / "m.json")])
    with pytest.raises(SystemExit) as exit_info:
        earthengine.run_script("mapbiomas_mining")
    text = str(exit_info.value.code)
    assert text.startswith("still exporting: 30 of 41 done after 160 minutes")
    assert tick.STILL_EXPORTING.search("2026-11-13T01:53:38Z " + text).groups() == ("30", "41")


def test_real_tasks_filters_by_description():
    class Data:
        def getTaskList(self):  # noqa: N802 (Earth Engine's name)
            return [
                {"id": "1", "description": "mapbiomas_mining_2026-11-12_1985", "state": "READY"},
                {
                    "id": "2",
                    "description": "mapbiomas_mining_2026-11-12-2_1985",
                    "state": "RUNNING",
                },
                {
                    "id": "3",
                    "description": "mapbiomas_1985",
                    "state": "FAILED",
                    "error_message": "x",
                },
            ]

    real = object.__new__(earthengine.RealEarthEngine)
    real._ee = type("EE", (), {"data": Data()})()
    found = real.tasks("mapbiomas_mining_2026-11-12_")
    assert found == [
        {
            "id": "1",
            "description": "mapbiomas_mining_2026-11-12_1985",
            "state": "READY",
            "error": "",
        }
    ]


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


# --- the unmask key and the mapbiomas_mining entry (campaign 0007, step s10) ----


def test_coverage_national_params_and_source_are_pinned():
    entry = dataset("mapbiomas_coverage_national")
    p = export_params(entry)
    assert p["asset"] == (
        "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
        "mapbiomas_brazil_collection10_coverage_v2"
    )
    assert p["mode"] == "groups"
    assert p["crs_transform"] == [1000, 0, 2813000, 0, -1000, 11912000]
    assert p["dimensions"] == "4587x4312"
    assert p["file_dimensions"] == [4608, 4352]
    assert p["min_share_with_data"] == 0.35
    assert p["groups"] == {"urban": [24], "native": [3, 4, 5, 6, 49, 11, 12, 32, 29, 50]}
    assert p["shape"] == (4312, 4587, 2)
    assert "unmask" not in p and "unmask" not in export_params(dataset(NAME))
    src = earthengine.source(entry, {"updateTime": "t", "sizeBytes": 1})
    assert src["etag"] == "e71cccf9adb0a178"


class Chain:
    """A fake `ee` object that records every call, in order, and returns itself."""

    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.log.append((name, args))
            return self

        return call


class FakeImageModule(Chain):
    """Stands in for the `ee` module: `ee.Image(...)`, `ee.Image.cat`, `ee.Reducer.mean`."""

    def __init__(self, log):
        super().__init__(log)
        chain = Chain(log)

        def image(asset):
            log.append(("Image", (asset,)))
            return chain

        def cat(parts):
            log.append(("cat", (len(parts),)))
            return chain

        image.cat = cat
        self.Image = image
        self.Reducer = Chain(log)


def image_calls(entry):
    log = []
    real = object.__new__(earthengine.RealEarthEngine)
    real._ee = FakeImageModule(log)
    real._bucket = "bucket"
    real._image(2004, export_params(entry))
    return [name for name, _ in log], log


def test_unmask_comes_before_remap_in_groups():
    entry = groups_entry()
    entry["earthengine"]["unmask"] = 0
    names, log = image_calls(entry)
    assert ("unmask", (0,)) in log
    assert names.index("select") < names.index("unmask") < names.index("remap")


def test_unmask_comes_before_eq_in_shares():
    entry = small_entry()
    entry["earthengine"]["unmask"] = 0
    names, _ = image_calls(entry)
    assert names.index("unmask") < names.index("eq")


@pytest.mark.parametrize("make", [small_entry, groups_entry])
def test_no_unmask_when_the_key_is_absent(make):
    names, _ = image_calls(make())
    assert "unmask" not in names


def test_unmask_in_log1p_mean_raises():
    entry = log_entry()
    entry["earthengine"]["unmask"] = 0
    with pytest.raises(EarthEngineError, match="unmask"):
        export_params(entry)


def test_check_file_four_bands_near_the_share_threshold(tmp_path):
    arr = np.zeros((100, 200, 4), dtype=np.uint16)  # 20,000 cells: 0.00005 needs 1 cell
    arr[0, :2, 0] = 5000
    assert check_file(write_tif(tmp_path, arr), arr.shape, 10000, "groups", 0.00005)[0] == 2
    arr = np.zeros((200, 200, 4), dtype=np.uint16)  # 40,000 cells: 0.00005 needs 2 cells
    arr[0, 0, 1] = 5000
    with pytest.raises(EarthEngineError, match="only 1 of 40000"):
        check_file(write_tif(tmp_path, arr), arr.shape, 10000, "groups", 0.00005)


def test_mapbiomas_mining_entry_loads():
    entry = dataset("mapbiomas_mining")
    assert entry["gcs"] == "data/raw/mapbiomas/mining/"
    p = export_params(entry)
    assert p["mode"] == "groups" and p["unmask"] == 0
    assert list(p["groups"]) == [
        "garimpo_gold",
        "garimpo_other",
        "industrial_gold",
        "industrial_other",
    ]
    g = p["groups"]
    assert g["garimpo_gold"] == [1115, 1215] and g["industrial_gold"] == [2115, 2215]
    for name, first in (("garimpo_other", 11), ("industrial_other", 21)):
        codes = g[name]
        assert len(codes) == 104 and len(set(codes)) == 104
        assert all(1000 <= c <= 9999 for c in codes)
        assert all(c // 100 in (first, first + 1) for c in codes)
        assert all(c % 100 != 15 for c in codes)
        assert sorted(codes) == codes
    # the two "other" lists carry the same 52 substances
    assert {c % 1000 for c in g["garimpo_other"]} == {c % 1000 for c in g["industrial_other"]}
    assert len({c % 100 for c in g["garimpo_other"]}) == 52
    assert p["years"] == list(range(1985, 2026)) and p["scale"] == 10000
    assert p["dimensions"] == "4587x4312" and p["shape"] == (4312, 4587, 4)
    assert p["file_dimensions"] == [4608, 4352] and p["min_share_with_data"] == 0.00005
    assert p["bands"][1985] == "classification_1985"
    assert p["files"][2025] == "mining_shares_2025.tif"
