"""MapBiomas code shares of every Legal Amazon 1 km cell, split by half.

Contract of the output: data/contracts/cell_outcomes.md. Decisions 0001, 0003, 0006.

For each year, the seven code shares (x 10,000) of every cell of `grid_cells`, read from
the acquired GeoTIFFs. Rows of exploration-half municipalities go to the derived folder;
rows of the confirmation half go to a sealed folder that this build only creates in and
never reads. Nothing here computes, prints or stores a statistic of any code: the notes
count cells (by half, without data, partly unclassified), never shares.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import tifffile

from terrain import grid
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.explore import EXPLORE_LIST
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import ObjectExistsError, Store

__all__ = ["BuildError", "build"]

DATASET = "cell_outcomes"
GRID_FILE = ".parquet"
MIN_SHARE_WITH_DATA = 0.99
# A cell's shares are rounded per code, so they may exceed the scale by up to one per code.
UNCLASSIFIED_NOTE_ABOVE = 7

# Every module whose code decides what this build writes. Its source is part of the
# output path: this file, the grid helpers, and polling_place_tenure (for `_file`, which
# picks the inputs, and `_fetch`, which checks their SHA-256).
CODE_MODULES = (Path(__file__), Path(grid.__file__), Path(tenure.__file__))


def output_name(year: int) -> str:
    return f"cell_outcomes_{year}.parquet"


def code_columns(codes: list[int]) -> list[str]:
    return [f"code_{c}" for c in codes]


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_sha: str,
    years: tuple[int, ...],
    code: list[str] | None = None,
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, split_sha, ",".join(str(y) for y in sorted(years)), *sources)


# --- Settings from the catalog's earthengine block


def settings(block: dict[str, Any]) -> dict[str, Any]:
    g = block["grid_km"]
    x0, x1, y0, y1 = int(g["x0"]), int(g["x1"]), int(g["y0"]), int(g["y1"])
    codes = [int(c) for c in block["codes"]]
    years = tuple(sorted(int(y) for y in block["years"]))
    return {
        "x0": x0,
        "y1": y1,
        "shape": (y1 - y0, x1 - x0, len(codes)),
        "codes": codes,
        "scale": int(block["scale"]),
        "years": years,
        "files": {y: str(block["file"]).replace("<year>", str(y)) for y in years},
    }


# --- The split list


def parse_split_list(data: bytes) -> frozenset[str]:
    """The exploration municipalities: one column `code_ibge` of 7-digit codes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise BuildError("the split list is not UTF-8 text") from err
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["code_ibge"]:
        raise BuildError("the split list must have exactly one column, code_ibge")
    codes = frozenset((row["code_ibge"] or "").strip() for row in reader)
    if not codes or not all(len(c) == 7 and c.isdigit() for c in codes):
        raise BuildError("the split list is empty or holds codes that are not 7 digits")
    return codes


# --- Cells


def load_cells(path: Path, explore: frozenset[str], cfg: dict[str, Any]) -> pl.DataFrame:
    """`grid_cells` keys with a `pixel row`, `pixel col` and `exploration` flag."""
    cells = pl.read_parquet(path, columns=["nome_1KM", "cd_ibge", "x_km", "y_km"])
    if cells["cd_ibge"].null_count():
        raise BuildError(f"{cells['cd_ibge'].null_count()} cells have no municipality")
    bad = cells.filter(~pl.col("cd_ibge").str.contains(r"^\d{7}$"))
    if bad.height:
        raise BuildError(f"{bad.height} cells have a cd_ibge that is not 7 digits")
    if cells["nome_1KM"].is_duplicated().any():
        raise BuildError("a cell appears more than once in grid_cells")
    rows, cols, _ = cfg["shape"]
    cells = cells.with_columns(
        (cfg["y1"] - 1 - pl.col("y_km")).alias("pixel_row"),
        (pl.col("x_km") - cfg["x0"]).alias("pixel_col"),
        pl.col("cd_ibge").is_in(sorted(explore)).alias("exploration"),
    )
    outside = cells.filter(
        (pl.col("pixel_row") < 0)
        | (pl.col("pixel_row") >= rows)
        | (pl.col("pixel_col") < 0)
        | (pl.col("pixel_col") >= cols)
    )
    if outside.height:
        raise BuildError(f"{outside.height} cells lie outside the grid of the GeoTIFFs")
    return cells


# --- One year


def read_year(path: Path, cfg: dict[str, Any]) -> np.ndarray:
    """The year's array, after the dtype and shape checks."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = tifffile.imread(path)
    except Exception as err:  # tifffile raises several types for bad files
        raise BuildError(f"{path.name}: cannot be read as a GeoTIFF") from err
    if arr.dtype != np.uint16:
        raise BuildError(f"{path.name}: dtype {arr.dtype}, expected uint16")
    if arr.shape != tuple(cfg["shape"]):
        raise BuildError(f"{path.name}: shape {arr.shape}, expected {tuple(cfg['shape'])}")
    return arr


def year_table(
    arr: np.ndarray, cells: pl.DataFrame, year: int, cfg: dict[str, Any]
) -> pl.DataFrame:
    """One row per cell with its seven values, `has_data` and `unclassified`."""
    scale, n_codes = cfg["scale"], len(cfg["codes"])
    values = arr[cells["pixel_row"].to_numpy(), cells["pixel_col"].to_numpy(), :]
    sums = values.sum(axis=1, dtype=np.int64)
    has = values.any(axis=1)
    if bool((sums > scale + n_codes).any()):
        raise BuildError(
            f"{year}: {int((sums > scale + n_codes).sum())} cells sum to more than 10,000"
        )
    if has.sum() < MIN_SHARE_WITH_DATA * len(has):
        raise BuildError(
            f"{year}: only {int(has.sum())} of {len(has)} cells have data, "
            f"below {MIN_SHARE_WITH_DATA:.0%}"
        )
    unclassified = np.where(has, np.clip(scale - sums, 0, scale), scale).astype(np.uint16)
    columns: dict[str, Any] = {
        "nome_1KM": cells["nome_1KM"],
        "cd_ibge": cells["cd_ibge"],
        "ano": pl.Series("ano", np.full(len(has), year, dtype=np.int32)),
        "has_data": pl.Series("has_data", has),
    }
    for i, name in enumerate(code_columns(cfg["codes"])):
        columns[name] = pl.Series(name, values[:, i].astype(np.uint16))
    columns["unclassified"] = pl.Series("unclassified", unclassified)
    return pl.DataFrame(columns).with_columns(cells["exploration"])


def year_note(table: pl.DataFrame, year: int) -> str:
    """Cell counts only: never a share of any code."""
    n_explore = int(table["exploration"].sum())
    partly = table.filter(pl.col("has_data") & (pl.col("unclassified") > UNCLASSIFIED_NOTE_ABOVE))
    return (
        f"{year}: cells_exploration={n_explore}, cells_confirmation={table.height - n_explore}, "
        f"cells_without_data={int((~table['has_data']).sum())}, "
        f"cells_partly_unclassified={partly.height}"
    )


# --- Build


def _upload(store: Store, destination: str, path: Path) -> dict[str, Any]:
    try:
        store.create(destination, path)
    except ObjectExistsError as err:
        raise BuildError(f"{destination} already exists; nothing more was written") from err
    return {"path": destination, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def build(
    store: Store,
    acquire_manifest: dict[str, Any],
    grid_manifest: dict[str, Any],
    earthengine: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-year, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.
    write_manifest`) when `status` is `created`. The build never lists, reads or
    checks the sealed folder: a create-only upload fails if an object is there.
    """
    cfg = settings(earthengine)
    years = cfg["years"]
    tif_entries = {y: _file(acquire_manifest, "/" + cfg["files"][y]) for y in years}
    grid_entry = _file(grid_manifest, GRID_FILE)
    split_bytes = store.read_bytes(EXPLORE_LIST)
    split_sha = hashlib.sha256(split_bytes).hexdigest()
    explore = parse_split_list(split_bytes)

    entries = [*tif_entries.values(), grid_entry]
    hashed = input_hash(entries, split_sha, years)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    cells_path = _fetch(store, grid_entry, tmp_dir)
    try:
        cells = load_cells(cells_path, explore, cfg)
    finally:
        cells_path.unlink(missing_ok=True)

    derived_dir = tmp_dir / "derived"
    sealed_dir = tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    sort_by = ["cd_ibge", "nome_1KM"]
    notes: list[str] = []
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per year
    for y in years:
        tif = _fetch(store, tif_entries[y], tmp_dir)
        try:
            arr = read_year(tif, cfg)
            table = year_table(arr, cells, y, cfg)
            del arr
        finally:
            tif.unlink(missing_ok=True)
        notes.append(year_note(table, y))
        out = table.sort(sort_by)
        sealed_file, derived_file = sealed_dir / output_name(y), derived_dir / output_name(y)
        out.filter(~pl.col("exploration")).drop("exploration").write_parquet(sealed_file)
        out.filter(pl.col("exploration")).drop("exploration").write_parquet(derived_file)
        local.append((sealed_file, derived_file))

    # Every check has passed. Sealed first; the manifest is the caller's last step.
    sealed_files = [_upload(store, sealed_prefix + p.name, p) for p, _ in local]
    files = [_upload(store, derived_prefix + p.name, p) for _, p in local]
    manifest = build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=derived_prefix,
        files=files,
        inputs=[
            acquire_manifest["gcs_prefix"] + MANIFEST_NAME,
            grid_manifest["gcs_prefix"] + MANIFEST_NAME,
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
