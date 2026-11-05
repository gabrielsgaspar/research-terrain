"""Acquire MapBiomas code shares from Earth Engine, one GeoTIFF per year.

Earth Engine sits behind the small `EarthEngine` protocol, so tests use a fake.
Earth Engine writes each year straight into the dated raw folder; this module
then checks every file and returns the manifest, which `run_script` writes
last. A failed run leaves files without a manifest, and the next run uses a new
dated folder. Nothing here computes a statistic of any code: the files hold
outcome data for both halves.
"""

from __future__ import annotations

import argparse
import json
import os
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


class EarthEngineError(RuntimeError):
    """An export or a file check failed; no manifest is written."""


class EarthEngine(Protocol):
    def asset_info(self, asset: str) -> dict[str, Any]:
        """`{"updateTime": str, "sizeBytes": int}` of the asset."""
        ...

    def start_export(self, year: int, params: dict[str, Any], bucket_prefix: str) -> str:
        """Start the batch export of `year` into `bucket_prefix`; return the task id."""
        ...

    def task_state(self, task_id: str) -> tuple[str, str]:
        """`(state, error_message)` of the task."""
        ...


def export_params(entry: dict[str, Any]) -> dict[str, Any]:
    """Every export parameter, from the entry's `earthengine:` block only."""
    block = entry["earthengine"]
    g = block["grid_km"]
    x0, x1, y0, y1 = g["x0"], g["x1"], g["y0"], g["y1"]
    years = [int(y) for y in block["years"]]
    codes = [int(c) for c in block["codes"]]
    return {
        "asset": block["asset"],
        "crs": pyproj.CRS.from_proj4(ALBERS).to_wkt(version="WKT1_GDAL"),
        "crs_transform": [1000, 0, x0 * 1000, 0, -1000, y1 * 1000],
        "dimensions": f"{x1 - x0}x{y1 - y0}",
        "file_dimensions": list(FILE_DIMENSIONS),
        "shard_size": SHARD_SIZE,
        "years": years,
        "codes": codes,
        "scale": int(block["scale"]),
        "bands": {y: str(block["band"]).replace("<year>", str(y)) for y in years},
        "files": {y: str(block["file"]).replace("<year>", str(y)) for y in years},
        "shape": (y1 - y0, x1 - x0, len(codes)),
    }


def source(entry: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """The manifest source: the asset version plus a hash of the export block."""
    block = json.dumps(entry["earthengine"], sort_keys=True, default=str)
    return {
        "url": entry["earthengine"]["asset"],
        "last_modified": str(info["updateTime"]),
        "etag": content_hash(block),
        "bytes": int(info["sizeBytes"]),
    }


def check_file(path: Path, shape: tuple[int, ...], scale: int) -> int:
    """Raise `EarthEngineError` unless `path` is a valid share file.

    Returns the number of cells with data (any share not zero).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = tifffile.imread(path)
    except Exception as err:  # tifffile raises several types for bad files
        raise EarthEngineError(f"{path.name}: cannot be read as a GeoTIFF ({err})") from err
    if arr.dtype != np.uint16:
        raise EarthEngineError(f"{path.name}: dtype {arr.dtype}, expected uint16")
    if arr.shape != tuple(shape):
        raise EarthEngineError(f"{path.name}: shape {arr.shape}, expected {tuple(shape)}")
    has = arr.any(axis=2)
    sums = arr.sum(axis=2, dtype=np.int64)[has]
    if sums.size and bool((np.abs(sums - scale) > shape[2]).any()):
        raise EarthEngineError(f"{path.name}: shares of some cell do not sum to {scale}")
    n = int(has.sum())
    if n < MIN_SHARE_WITH_DATA * has.size:
        raise EarthEngineError(f"{path.name}: only {n} of {has.size} cells have data")
    return n


def _wait(
    ee: EarthEngine,
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
            raise EarthEngineError(f"exports not finished after {limit_s / 60:.0f} minutes")
        sleep(poll_s)


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
    current = source(entry, ee.asset_info(params["asset"]))

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

    prefix = _free_prefix(store, root, today)
    tasks = {y: ee.start_export(y, params, prefix) for y in params["years"]}
    _wait(ee, tasks, sleep, clock, poll_s, limit_s)

    tmp_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    cells: list[str] = []
    for year in params["years"]:
        remote = prefix + params["files"][year]
        if not store.exists(remote):
            raise EarthEngineError(f"{remote}: export finished but the file is missing")
        local = tmp_dir / params["files"][year]
        store.download(remote, local)
        n = check_file(local, params["shape"], params["scale"])
        files.append({"path": remote, "sha256": sha256_file(local), "bytes": local.stat().st_size})
        cells.append(f"{year}={n}")
    return build_manifest(
        dataset=entry["name"],
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=files,
        sources=[current],
        notes="cells with data per year: " + ", ".join(cells),
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
        return {"updateTime": info["updateTime"], "sizeBytes": int(info["sizeBytes"])}

    def start_export(self, year: int, params: dict[str, Any], bucket_prefix: str) -> str:
        ee = self._ee
        img = ee.Image(params["asset"]).select(params["bands"][year])
        shares = (
            ee.Image.cat([img.eq(c).rename(f"c{c}") for c in params["codes"]])
            .reduceResolution(ee.Reducer.mean(), maxPixels=2048)
            .multiply(params["scale"])
            .round()
            .toUint16()
        )
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
