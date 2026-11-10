"""Acquire MapBiomas code shares from Earth Engine, one GeoTIFF per year.

Earth Engine sits behind the small `EarthEngine` protocol, so tests use a fake.
Earth Engine writes each year straight into the dated raw folder; this module
then checks every file and returns the manifest, which `run_script` writes
last. Right after starting its exports a run writes `exports.json` (the source and
a year-to-task map) beside them. A run that times out leaves it, and the next run
with the same source resumes that folder's tasks instead of starting new ones. A
folder with a failed or cancelled task is not resumed: the next run uses a new
dated folder. Nothing here computes a statistic of any code: the files hold
outcome data for both halves.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import warnings
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pyproj
import tifffile

from terrain.acquire import _free_prefix, _unchanged
from terrain.catalog import dataset
from terrain.grid import ALBERS
from terrain.manifest import (
    MANIFEST_NAME,
    build_manifest,
    content_hash,
    latest_manifest,
    sha256_file,
    write_manifest,
)
from terrain.storage import GCSStore, Store

# OAuth scope names, not data URLs; built from parts because a test keeps the
# literal scheme out of code (data URLs belong in the catalog).
_SCOPE_BASE = "https" + "://www.googleapis.com/auth/"
SCOPES = (_SCOPE_BASE + "earthengine", _SCOPE_BASE + "cloud-platform")
# Earth Engine computes each shard of SHARD_SIZE 1 km cells from 30 m input: 256 needs
# about 9,000 input pixels a side, over its reprojection limit (run 41991239477); 128 fits.
SHARD_SIZE = 128
FILE_DIMENSIONS = [3584, 2816]  # multiples of SHARD_SIZE: one file per year
MIN_SHARE_WITH_DATA = 0.5
DONE = "COMPLETED"
STOPPED = ("FAILED", "CANCELLED")
EXPORTS_NAME = "exports.json"
_FOLDER = re.compile(r"(\d{4}-\d{2}-\d{2})(?:-(\d+))?")


class EarthEngineError(RuntimeError):
    """An export or a file check failed; no manifest is written."""


class EarthEngine(Protocol):
    def asset_info(self, asset: str) -> dict[str, Any]:
        """`{"updateTime": str, "sizeBytes": int | None}` of the asset.

        `sizeBytes` is None for an image collection: Earth Engine reports no size
        for one, only its update time.
        """
        ...

    def band_names(self, asset: str) -> list[str]:
        """Band names of the image `asset` (or of the first image of a collection)."""
        ...

    def year_images(self, collection: str, year: int) -> list[str]:
        """Ids of the images of `collection` whose start date is in `year`."""
        ...

    def start_export(self, year: int, params: dict[str, Any], bucket_prefix: str) -> str:
        """Start the batch export of `year` into `bucket_prefix`; return the task id.

        For `log1p_mean`, `params["images"][year]` is the year's single image id.
        """
        ...

    def task_state(self, task_id: str) -> tuple[str, str]:
        """`(state, error_message)` of the task."""
        ...


def _collections(block: dict[str, Any], years: list[int]) -> dict[int, str]:
    """Year -> collection asset for `log1p_mean`; each year in exactly one collection."""
    owner: dict[int, str] = {}
    for coll in block["collections"]:
        for y in coll["years"]:
            y = int(y)
            if y in owner:
                raise EarthEngineError(f"year {y} is in two collections")
            owner[y] = str(coll["asset"])
    missing = [y for y in years if y not in owner]
    if missing:
        raise EarthEngineError(f"years {missing} are in no collection")
    return {y: owner[y] for y in years}


def export_params(entry: dict[str, Any]) -> dict[str, Any]:
    """Every export parameter, from the entry's `earthengine:` block only."""
    block = entry["earthengine"]
    g = block["grid_km"]
    x0, x1, y0, y1 = g["x0"], g["x1"], g["y0"], g["y1"]
    years = [int(y) for y in block["years"]]
    mode = str(block.get("mode", "shares"))
    params: dict[str, Any] = {
        "mode": mode,
        "crs": pyproj.CRS.from_proj4(ALBERS).to_wkt(version="WKT1_GDAL"),
        "crs_transform": [1000, 0, x0 * 1000, 0, -1000, y1 * 1000],
        "dimensions": f"{x1 - x0}x{y1 - y0}",
        "file_dimensions": [int(d) for d in block.get("file_dimensions", FILE_DIMENSIONS)],
        "min_share_with_data": float(block.get("min_share_with_data", MIN_SHARE_WITH_DATA)),
        "shard_size": SHARD_SIZE,
        "years": years,
        "scale": int(block["scale"]),
        "bands": {y: str(block["band"]).replace("<year>", str(y)) for y in years},
        "files": {y: str(block["file"]).replace("<year>", str(y)) for y in years},
    }
    if mode == "shares":
        codes = [int(c) for c in block["codes"]]
        params.update(asset=block["asset"], codes=codes, shape=(y1 - y0, x1 - x0, len(codes)))
    elif mode == "groups":
        groups = {str(k): [int(c) for c in v] for k, v in block["groups"].items()}
        params.update(asset=block["asset"], groups=groups)
        params["shape"] = (y1 - y0, x1 - x0, len(groups))
    elif mode == "log1p_mean":
        params.update(year_assets=_collections(block, years), shape=(y1 - y0, x1 - x0, 1))
    else:
        raise EarthEngineError(f"unknown export mode {mode!r}")
    return params


def _assets(params: dict[str, Any]) -> list[str]:
    """The assets a run reads, in a stable order without repeats."""
    if params["mode"] == "log1p_mean":
        return list(dict.fromkeys(params["year_assets"].values()))
    return [params["asset"]]


def source(entry: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """The manifest source: the asset version plus a hash of the export block.

    `info` is the asset's info; for `log1p_mean` it is one combined info over the
    collections (newest update time; size None, since collections have none).
    """
    block = json.dumps(entry["earthengine"], sort_keys=True, default=str)
    eb = entry["earthengine"]
    if "asset" in eb:
        url = eb["asset"]
    else:
        url = ", ".join(str(c["asset"]) for c in eb["collections"])
    return {
        "url": url,
        "last_modified": str(info["updateTime"]),
        "etag": content_hash(block),
        "bytes": None if info["sizeBytes"] is None else int(info["sizeBytes"]),
    }


def check_file(
    path: Path,
    shape: tuple[int, ...],
    scale: int,
    mode: str = "shares",
    min_share_with_data: float = MIN_SHARE_WITH_DATA,
) -> tuple[int, int]:
    """Raise `EarthEngineError` unless `path` is a valid export file.

    Returns (cells with data, of them cells whose shares sum to less than `scale`).
    For `shares` and `groups`, some 30 m pixels carry no listed code, so a cell's
    shares may sum to less than `scale` (the rest is unclassified; 0.4% of cells
    in 2004), never to more. For `log1p_mean` there is no sum; every value must
    be at most `11 * scale` and the second count is 0.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = tifffile.imread(path)
    except Exception as err:  # tifffile raises several types for bad files
        raise EarthEngineError(f"{path.name}: cannot be read as a GeoTIFF ({err})") from err
    if arr.dtype != np.uint16:
        raise EarthEngineError(f"{path.name}: dtype {arr.dtype}, expected uint16")
    if arr.ndim == 2 and len(shape) == 3 and shape[2] == 1:
        arr = arr[:, :, np.newaxis]  # tifffile drops a single band's axis
    if arr.shape != tuple(shape):
        raise EarthEngineError(f"{path.name}: shape {arr.shape}, expected {tuple(shape)}")
    has = arr.any(axis=2)
    n = int(has.sum())
    short = 0
    if mode == "log1p_mean":
        if int(arr.max(initial=0)) > 11 * scale:
            raise EarthEngineError(f"{path.name}: a value is above 11 * {scale}")
    else:
        sums = arr.sum(axis=2, dtype=np.int64)[has]
        if sums.size and bool((sums > scale + shape[2]).any()):
            raise EarthEngineError(f"{path.name}: shares of some cell sum to more than {scale}")
        short = int((sums < scale - shape[2]).sum())
    if n < min_share_with_data * has.size:
        raise EarthEngineError(f"{path.name}: only {n} of {has.size} cells have data")
    return n, short


def _write_pending(
    store: Store, prefix: str, current: dict[str, Any], tasks: dict[int, str]
) -> None:
    record = {"sources": [current], "tasks": {str(y): t for y, t in tasks.items()}}
    store.create(prefix + EXPORTS_NAME, json.dumps(record, sort_keys=True).encode("utf-8"))


def _folder_order(folder: str) -> tuple[str, int]:
    match = _FOLDER.fullmatch(folder)
    assert match is not None
    return match.group(1), int(match.group(2) or 1)


def _pending(
    store: Store, ee: EarthEngine, root: str, current: dict[str, Any]
) -> tuple[str, dict[int, str]] | None:
    """The newest resumable folder under `root`, or None.

    A folder qualifies if it has `exports.json`, no manifest, no failed or
    cancelled task, and the same source as `current`.
    """
    names: dict[str, set[str]] = {}
    for path in store.list(root):
        folder, _, name = path.removeprefix(root).partition("/")
        if name and _FOLDER.fullmatch(folder):
            names.setdefault(folder, set()).add(name)
    open_folders = [f for f, n in names.items() if EXPORTS_NAME in n and MANIFEST_NAME not in n]
    for folder in sorted(open_folders, key=_folder_order, reverse=True):
        prefix = f"{root}{folder}/"
        rec = json.loads(store.read_bytes(prefix + EXPORTS_NAME).decode("utf-8"))
        tasks = {int(y): str(t) for y, t in rec["tasks"].items()}
        if any(ee.task_state(t)[0] in STOPPED for t in tasks.values()):
            continue
        if _unchanged({"sources": rec["sources"]}, [current]):
            return prefix, tasks
        return None
    return None


def _wait(
    ee: EarthEngine,
    prefix: str,
    tasks: dict[int, str],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    poll_s: float,
    limit_s: float,
) -> None:
    start = clock()
    while True:
        done = 0
        for year, task_id in tasks.items():
            state, message = ee.task_state(task_id)
            if state in STOPPED:
                raise EarthEngineError(f"export {year} {state}: {message}")
            done += state == DONE
        if done == len(tasks):
            return
        if clock() - start >= limit_s:
            raise EarthEngineError(
                f"exports not finished after {limit_s / 60:.0f} minutes "
                f"({done} of {len(tasks)} completed); run again to resume {prefix}"
            )
        sleep(poll_s)


def _check_inputs(ee: EarthEngine, params: dict[str, Any]) -> dict[int, str]:
    """Check bands and images exist; return year -> image id (`log1p_mean` only).

    Raises before any export starts.
    """
    if params["mode"] != "log1p_mean":
        have = set(ee.band_names(params["asset"]))
        missing = sorted({b for b in params["bands"].values() if b not in have})
        if missing:
            raise EarthEngineError(f"{params['asset']}: missing bands {missing}")
        return {}
    images: dict[int, str] = {}
    for year in params["years"]:
        found = ee.year_images(params["year_assets"][year], year)
        if len(found) != 1:
            raise EarthEngineError(
                f"{params['year_assets'][year]}: {len(found)} images for {year}, expected 1"
            )
        images[year] = found[0]
    for year, image in images.items():
        if params["bands"][year] not in ee.band_names(image):
            raise EarthEngineError(f"{image}: missing band {params['bands'][year]}")
    return images


def acquire_mapbiomas(
    store: Store,
    ee: EarthEngine,
    entry: dict[str, Any],
    today: date,
    tmp_dir: Path,
    code_commit: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    poll_s: float = 60,
    limit_s: float = 160 * 60,
) -> dict[str, Any]:
    """Run one acquire. Returns the manifest; the caller writes it when `created`."""
    root = entry["gcs"]
    params = export_params(entry)
    infos = [ee.asset_info(a) for a in _assets(params)]
    sizes = [i["sizeBytes"] for i in infos]
    current = source(
        entry,
        {
            "updateTime": max(str(i["updateTime"]) for i in infos),
            # a collection has no size, so a run over one records none
            "sizeBytes": None if None in sizes else sum(int(s) for s in sizes),
        },
    )

    old = latest_manifest(store, root)
    if old is not None and _unchanged(old, [current]):
        return build_manifest(
            dataset=entry["name"],
            stage="acquire",
            status="unchanged",
            gcs_prefix=old["gcs_prefix"],
            files=old["files"],
            sources=old["sources"],
            notes=old.get("notes", ""),
            code_commit=code_commit,
        )

    resumed = _pending(store, ee, root, current)
    images = _check_inputs(ee, params)  # before any export starts
    params["images"] = images
    if resumed is not None:
        prefix, tasks = resumed
    else:
        prefix = _free_prefix(store, root, today)
        tasks = {y: ee.start_export(y, params, prefix) for y in params["years"]}
        _write_pending(store, prefix, current, tasks)
    _wait(ee, prefix, tasks, sleep, clock, poll_s, limit_s)

    tmp_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    cells: list[str] = []
    for year in params["years"]:
        remote = prefix + params["files"][year]
        if not store.exists(remote):
            raise EarthEngineError(f"{remote}: export finished but the file is missing")
        local = tmp_dir / params["files"][year]
        store.download(remote, local)
        n, short = check_file(
            local,
            params["shape"],
            params["scale"],
            params["mode"],
            params["min_share_with_data"],
        )
        files.append({"path": remote, "sha256": sha256_file(local), "bytes": local.stat().st_size})
        if params["mode"] == "log1p_mean":
            cells.append(f"{year}={n}")
        else:
            cells.append(f"{year}={n} ({short} partly unclassified)")
    notes = "cells with data per year: " + ", ".join(cells)
    if params["mode"] == "log1p_mean":
        notes += "; image per year: " + ", ".join(f"{y}={i}" for y, i in images.items())
    return build_manifest(
        dataset=entry["name"],
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=files,
        sources=[current],
        notes=notes,
        code_commit=code_commit,
    )


class RealEarthEngine:
    """Earth Engine through `earthengine-api`; imports are lazy so tests need none."""

    def __init__(self, bucket: str, project: str | None = None) -> None:
        import ee
        import google.auth

        credentials, _ = google.auth.default(scopes=list(SCOPES))
        ee.Initialize(credentials, project=project or os.environ["GOOGLE_CLOUD_PROJECT"])
        self._ee = ee
        self._bucket = bucket

    def asset_info(self, asset: str) -> dict[str, Any]:
        info = self._ee.data.getAsset(asset)
        if "updateTime" not in info:
            raise EarthEngineError(f"{asset}: Earth Engine gave no updateTime")
        if str(info.get("type", "")) == "IMAGE_COLLECTION":
            # Collections have no sizeBytes; the update time tracks their version.
            return {"updateTime": info["updateTime"], "sizeBytes": None}
        if "sizeBytes" not in info:
            raise EarthEngineError(f"{asset}: Earth Engine gave no sizeBytes for an image")
        return {"updateTime": info["updateTime"], "sizeBytes": int(info["sizeBytes"])}

    def band_names(self, asset: str) -> list[str]:
        ee = self._ee
        if self._is_collection(asset):
            return list(ee.ImageCollection(asset).first().bandNames().getInfo())
        return list(ee.Image(asset).bandNames().getInfo())

    def _is_collection(self, asset: str) -> bool:
        return str(self._ee.data.getAsset(asset).get("type", "")) == "IMAGE_COLLECTION"

    def year_images(self, collection: str, year: int) -> list[str]:
        ee = self._ee
        coll = ee.ImageCollection(collection).filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        return [str(i) for i in coll.aggregate_array("system:id").getInfo()]

    def _image(self, year: int, params: dict[str, Any]) -> Any:
        ee = self._ee
        band = params["bands"][year]
        if params["mode"] == "log1p_mean":
            img = ee.Image(params["images"][year]).select(band)
            # log(1 + max(radiance, 0)), then the mean over the 1 km cell
            return (
                img.max(0)
                .add(1)
                .log()
                .reduceResolution(ee.Reducer.mean(), maxPixels=2048)
                .multiply(params["scale"])
                .round()
                .toUint16()
            )
        img = ee.Image(params["asset"]).select(band)
        if params["mode"] == "groups":
            parts = [
                img.remap(codes, [1] * len(codes), 0).rename(name)
                for name, codes in params["groups"].items()
            ]
        else:
            parts = [img.eq(c).rename(f"c{c}") for c in params["codes"]]
        return (
            ee.Image.cat(parts)
            .reduceResolution(ee.Reducer.mean(), maxPixels=2048)
            .multiply(params["scale"])
            .round()
            .toUint16()
        )

    def start_export(self, year: int, params: dict[str, Any], bucket_prefix: str) -> str:
        ee = self._ee
        shares = self._image(year, params)
        name = params["files"][year].removesuffix(".tif")
        task = ee.batch.Export.image.toCloudStorage(
            image=shares,
            description=f"mapbiomas_{year}",
            bucket=self._bucket,
            fileNamePrefix=bucket_prefix + name,
            crs=params["crs"],
            crsTransform=params["crs_transform"],
            dimensions=params["dimensions"],
            maxPixels=1e10,
            fileFormat="GeoTIFF",
            fileDimensions=params["file_dimensions"],
            shardSize=params["shard_size"],
        )
        task.start()
        return str(task.id)

    def task_state(self, task_id: str) -> tuple[str, str]:
        status = self._ee.data.getTaskStatus(task_id)[0]
        return str(status.get("state", "")), str(status.get("error_message", ""))


def run_script(name: str) -> None:
    """Entry point for `pipeline/acquire/<name>.py`. Contract: pipeline/README.md."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    bucket = os.environ["TERRAIN_BUCKET"]
    store = GCSStore(bucket)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = acquire_mapbiomas(
                store,
                RealEarthEngine(bucket),
                dataset(name),
                datetime.now(UTC).date(),
                Path(tmp),
                os.environ.get("CODE_COMMIT", ""),
                time.sleep,
                time.monotonic,
            )
            if manifest["status"] == "created":
                write_manifest(manifest, store, args.manifest_out)
            else:
                args.manifest_out.write_text(
                    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
                )
    except EarthEngineError as err:
        raise SystemExit(f"acquire failed: {err}") from err
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))
