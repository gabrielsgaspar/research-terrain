"""MapBiomas mining area per municipality and year, with the 2004 native-vegetation share.

Contract of the output: data/contracts/mining_panel.md. Idea 0007, decisions 0003 and 0011;
the model is `terrain.builds.place_outcomes`, whose settings, list and raster readers it reuses.

A cell belongs to the municipality whose polygon contains the cell's centre. A municipality
with no cell centre gets the one cell that holds its polygon's representative point. For each
year the hectares of the four mining groups are summed over the municipality's cells (a cell
is 100 ha). Rows of exploration-half municipalities (both exploration lists) go to the derived
folder; every other row goes to a sealed folder that this build only creates in and never
reads. The notes count exploration-half rows only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely

from terrain import explore as terrain_explore
from terrain import grid
from terrain.builds import cell_enforcement, cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import flat_band, read_lists, read_raster, settings
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file, extract_edition
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "mining_panel"
BOUNDARIES_FILE = "BR_Municipios_2024.zip"
YEARS = tuple(range(1985, 2026))
BASELINE_YEAR = 2004
BANDS = ("garimpo_gold", "garimpo_other", "industrial_gold", "industrial_other")
DROPPED = frozenset({"4300001", "4300002"})  # the lagoons of Rio Grande do Sul
CELL_HA = 100.0
NOTE_YEARS = (1985, 2000, 2012, 2024)
CHECK_YEAR = 2022
CHECK_BOUNDS_HA = (100_000.0, 1_000_000.0)
COLUMNS = (
    "cd_ibge",
    "year",
    "n_cells",
    "garimpo_gold_ha",
    "garimpo_other_ha",
    "industrial_gold_ha",
    "industrial_other_ha",
    "garimpo_ha",
    "garimpo_share",
    "native_share_2004",
)

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, the grid helpers, `place_outcomes` (settings, lists, raster readers),
# `cell_outcomes` (list parser and upload), `cell_enforcement` (imported by `place_outcomes`),
# `polling_place_tenure` (`_file`, `_fetch`, the edition reader) and `terrain.explore`.
CODE_MODULES = (
    Path(__file__),
    Path(grid.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(cell_enforcement.__file__),
    Path(tenure.__file__),
    Path(terrain_explore.__file__),
)


def output_name(year: int) -> str:
    return f"mining_panel_{year}.parquet"


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_shas: list[str],
    code: list[str] | None = None,
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, ",".join(split_shas), *sources)


# --- Boundaries and cells


def read_boundaries(shp_path: Path) -> dict[str, Any]:
    """Every municipality polygon (degrees) by `CD_MUN`, without the two lagoons."""
    parts: dict[str, list[Any]] = {}
    with shapefile.Reader(str(shp_path), encoding="utf-8") as reader:
        for item in reader.iterShapeRecords():
            code = str(item.record.as_dict()["CD_MUN"])
            if code not in DROPPED and item.shape.points:
                parts.setdefault(code, []).append(to_shapely(item.shape.__geo_interface__))
    if not parts:
        raise BuildError("the boundaries hold no municipality")
    return {c: g[0] if len(g) == 1 else shapely.union_all(g) for c, g in sorted(parts.items())}


def assign_cells(
    polygons: dict[str, Any], cfg: dict[str, Any]
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """`(codes, offsets, owner, small)`: the cells of each municipality.

    `offsets` are flat `row * columns + column` indexes into a raster, `owner` indexes `codes`,
    and `small[i]` is true for a municipality that got its representative-point cell.
    """
    rows, cols = cfg["shape"][0], cfg["shape"][1]
    x0, y1 = cfg["x0"], cfg["y1"]
    codes = sorted(polygons)
    taken = np.zeros(rows * cols, dtype=bool)
    offsets: list[np.ndarray] = []
    owners: list[np.ndarray] = []
    small = np.zeros(len(codes), dtype=bool)
    for i, code in enumerate(codes):
        poly = grid.to_albers_km(polygons[code])
        minx, miny, maxx, maxy = poly.bounds
        xs = np.arange(max(int(np.floor(minx)), x0), min(int(np.floor(maxx)), x0 + cols - 1) + 1)
        ys = np.arange(max(int(np.floor(miny)), y1 - rows), min(int(np.floor(maxy)), y1 - 1) + 1)
        found = np.zeros(0, dtype=np.int64)
        if len(xs) and len(ys):
            gx, gy = np.meshgrid(xs, ys)
            gx, gy = gx.ravel(), gy.ravel()
            inside = shapely.contains_xy(poly, gx + 0.5, gy + 0.5)
            flat = (y1 - 1 - gy[inside]) * cols + (gx[inside] - x0)
            found = flat[~taken[flat]]
            taken[found] = True
        if len(found) == 0:
            point = shapely.point_on_surface(poly)
            px, py = int(np.floor(point.x)), int(np.floor(point.y))
            if not (x0 <= px < x0 + cols and y1 - rows <= py < y1):
                raise BuildError("a municipality lies outside the grid of the GeoTIFFs")
            found = np.array([(y1 - 1 - py) * cols + (px - x0)], dtype=np.int64)
            small[i] = True
        offsets.append(found)
        owners.append(np.full(len(found), i, dtype=np.int64))
    return codes, np.concatenate(offsets), np.concatenate(owners), small


# --- Tables


def year_table(
    year: int,
    arr: np.ndarray,
    cfg: dict[str, Any],
    codes: list[str],
    offsets: np.ndarray,
    owner: np.ndarray,
    n_cells: np.ndarray,
    native: np.ndarray,
) -> pl.DataFrame:
    """One row per municipality for `year`; the columns of the contract."""
    n = len(codes)
    ha = {}
    for band in BANDS:
        values = flat_band(arr, cfg, band)[offsets].astype(np.float64)
        # Integer shares sum exactly in float64; /10,000 x 100 ha is /100.
        ha[band] = np.bincount(owner, weights=values, minlength=n) / (cfg["scale"] / CELL_HA)
    garimpo = ha["garimpo_gold"] + ha["garimpo_other"]
    return pl.DataFrame(
        {
            "cd_ibge": codes,
            "year": pl.Series([year] * n, dtype=pl.Int64),
            "n_cells": pl.Series(n_cells, dtype=pl.Int64),
            "garimpo_gold_ha": ha["garimpo_gold"],
            "garimpo_other_ha": ha["garimpo_other"],
            "industrial_gold_ha": ha["industrial_gold"],
            "industrial_other_ha": ha["industrial_other"],
            "garimpo_ha": garimpo,
            "garimpo_share": garimpo / (n_cells * CELL_HA),
            "native_share_2004": native,
        }
    ).select(COLUMNS)


def check_sums(arr: np.ndarray, year: int, scale: int) -> None:
    if int((arr.astype(np.uint32).sum(axis=-1)).max()) > scale:
        raise BuildError(f"{year}: in some cell the four bands sum to more than {scale}")


def check_catalog(cfg: dict[str, Any], cover: dict[str, Any], years: tuple[int, ...]) -> None:
    if tuple(cfg["bands"]) != BANDS:
        raise BuildError(f"the mining bands must be {', '.join(BANDS)} in this order")
    if cfg["years"] != tuple(years):
        raise BuildError("the mining years are not exactly the years of the panel")
    if "native" not in cover["bands"] or BASELINE_YEAR not in cover["years"]:
        raise BuildError(f"the coverage rasters need the band native in {BASELINE_YEAR}")
    if (cfg["x0"], cfg["y1"], cfg["shape"][:2]) != (cover["x0"], cover["y1"], cover["shape"][:2]):
        raise BuildError("the mining and coverage rasters are not on the same grid")


def year_note(frame: pl.DataFrame, year: int) -> str:
    return f"y{year}: garimpo_ha={frame['garimpo_ha'].sum():.2f}"


# --- Build


def build(
    store: Store,
    mining_manifest: dict[str, Any],
    coverage_manifest: dict[str, Any],
    boundaries_manifest: dict[str, Any],
    mining_block: dict[str, Any],
    coverage_block: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
    years: tuple[int, ...] = YEARS,
    check_year: int = CHECK_YEAR,
    check_bounds_ha: tuple[float, float] = CHECK_BOUNDS_HA,
) -> dict[str, Any]:
    """Build the per-year, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, the others to `<sealed_root><hash>/`.
    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status` is
    `created`. The build never lists, reads or checks the sealed folder: a create-only
    upload fails if an object is there. `years`, `check_year` and `check_bounds_ha`
    default to the panel's 1985-2025 and the 2022 national bounds; tests pass others.
    """
    explore, split_shas = read_lists(store)
    cfg, cover = settings(mining_block), settings(coverage_block)
    check_catalog(cfg, cover, years)

    mining_entries = {y: _file(mining_manifest, "/" + cfg["files"][y]) for y in years}
    cover_entry = _file(coverage_manifest, "/" + cover["files"][BASELINE_YEAR])
    boundaries_entry = _file(boundaries_manifest, "/" + BOUNDARIES_FILE)
    entries = [*mining_entries.values(), cover_entry, boundaries_entry]
    hashed = input_hash(entries, split_shas)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    path = _fetch(store, boundaries_entry, tmp_dir)
    work = tmp_dir / "unpacked_boundaries"
    work.mkdir(exist_ok=True)
    try:
        polygons = read_boundaries(extract_edition(path, work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        path.unlink(missing_ok=True)
    if explore - set(polygons):
        raise BuildError("an exploration-list code is not in the boundaries")

    codes, offsets, owner, small = assign_cells(polygons, cfg)
    n_cells = np.bincount(owner, minlength=len(codes))
    is_explore = np.array([c in explore for c in codes])

    path = _fetch(store, cover_entry, tmp_dir)
    try:
        arr = read_raster(path, cover)
    finally:
        path.unlink(missing_ok=True)
    values = flat_band(arr, cover, "native")[offsets].astype(np.float64)
    del arr
    native = np.bincount(owner, weights=values, minlength=len(codes)) / n_cells / cover["scale"]

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    notes = [
        f"municipalities={int(is_explore.sum())}",
        f"small_municipalities={int((small & is_explore).sum())}",
    ]
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per year
    national_2022 = None
    for year in years:
        path = _fetch(store, mining_entries[year], tmp_dir)
        try:
            arr = read_raster(path, cfg)
        finally:
            path.unlink(missing_ok=True)
        check_sums(arr, year, cfg["scale"])
        table = year_table(year, arr, cfg, codes, offsets, owner, n_cells, native)
        del arr
        if year == check_year:
            national_2022 = float(table["garimpo_ha"].sum())
        mask = pl.Series(is_explore)
        if year in NOTE_YEARS:
            notes.append(year_note(table.filter(mask), year))
        sealed_file, derived_file = sealed_dir / output_name(year), derived_dir / output_name(year)
        table.filter(~mask).write_parquet(sealed_file)
        table.filter(mask).write_parquet(derived_file)
        local.append((sealed_file, derived_file))
    if national_2022 is None:
        raise BuildError(f"{check_year} is not among the years of the panel")
    if not (check_bounds_ha[0] <= national_2022 <= check_bounds_ha[1]):
        raise BuildError(
            f"national garimpo_ha in {check_year} is outside "
            f"{check_bounds_ha[0]:,.0f}-{check_bounds_ha[1]:,.0f} ha: check the units"
        )

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
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (mining_manifest, coverage_manifest, boundaries_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
