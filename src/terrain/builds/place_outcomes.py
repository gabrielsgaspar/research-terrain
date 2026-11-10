"""School facilities, night lights, built-up and native-vegetation shares per polling place.

Contract of the output: data/contracts/place_outcomes.md. Idea 0006, decisions 0003 and
0011; the models are `terrain.builds.cell_outcomes` and `terrain.builds.cell_enforcement`.

For each polling place of an election E (2008, 2012, 2016, 2020) and each outcome year y in
E-4 .. E+4 that has a raster, the facility count of the matched school and the means of the
rasters over the cells within 1 km (lights, built-up) and 10 km (native vegetation) of the
place. A ring holds only cells inside the polygon of the place's own municipality, so it
never reads a cell of a neighbour, which may be in the other half. Rows of exploration-half
municipalities (both exploration lists) go to the derived folder; every other row goes to a
sealed folder that this build only creates in and never reads. The notes count
exploration-half rows only and hold no statistic of any outcome.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapely
import tifffile

from terrain import explore as terrain_explore
from terrain import grid
from terrain.builds import cell_enforcement, cell_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.cell_enforcement import read_polygons
from terrain.builds.cell_outcomes import _upload, parse_split_list
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file, extract_edition
from terrain.explore import EXPLORE_LISTS_NATIONAL
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "place_outcomes"
ELECTIONS = (2008, 2012, 2016, 2020)
WINDOW = 4
BOUNDARIES_FILE = "BR_Municipios_2024.zip"
INEP_FILE = "inep_schools.parquet"
KEY = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
CONFIDENT = ("high", "medium")
FACILITIES = (
    "agua_rede_publica",
    "esgoto_rede_publica",
    "energia_rede_publica",
    "internet",
    "biblioteca_sala_leitura",
    "laboratorio_ciencias",
    "laboratorio_informatica",
    "quadra_esportes",
)
LAST_PNE_YEAR = 2018  # INEP's accessibility question changed in 2019
SCHOOL_COLUMNS = (
    "ano",
    "id_escola",
    "rede",
    *FACILITIES,
    "dependencia_pne",
    "acessibilidade_inexistente",
)
SMALL_KM, LARGE_KM = 1.0, 10.0
HALF_WIDTH = 11  # cells either side of the place's own cell: covers every centre within 10 km
CELL_KEY = 1_000_000
# A cell exactly one radius away (the cell next to a place at a cell centre) must stay in the
# ring whatever the rounding of the projection: squared distances get this slack (km^2).
SLACK = 1e-6

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, the grid helpers, the two builds whose helpers it reuses
# (`cell_outcomes`: the split list and the upload; `cell_enforcement`: the polygons),
# `polling_place_tenure` (`_file`, `_fetch` and the edition reader) and `terrain.explore`
# (the exploration lists).
CODE_MODULES = (
    Path(__file__),
    Path(grid.__file__),
    Path(cell_outcomes.__file__),
    Path(cell_enforcement.__file__),
    Path(tenure.__file__),
    Path(terrain_explore.__file__),
)


def output_name(election: int, year: int) -> str:
    return f"place_outcomes_E{election}_y{year}.parquet"


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_shas: list[str],
    years: tuple[int, ...],
    code: list[str] | None = None,
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(
        shas,
        ",".join(split_shas),
        ",".join(str(y) for y in sorted(years)),
        ",".join(str(e) for e in ELECTIONS),
        *sources,
    )


# --- Settings from the catalog's earthengine block


def settings(block: dict[str, Any]) -> dict[str, Any]:
    """A raster source: grid, years, file names and, for `groups` mode, the band order."""
    g = block["grid_km"]
    x0, x1, y0, y1 = int(g["x0"]), int(g["x1"]), int(g["y0"]), int(g["y1"])
    years = tuple(sorted(int(y) for y in block["years"]))
    bands = list(block.get("groups") or [])
    shape = (y1 - y0, x1 - x0) + ((len(bands),) if bands else ())
    widest = max((len(v) for v in (block.get("groups") or {}).values()), default=1)
    return {
        "x0": x0,
        "y1": y1,
        "shape": shape,
        "bands": bands,
        "scale": int(block["scale"]),
        # Shares are rounded per code, so they may exceed the scale by one per code.
        "max_value": None if not bands else int(block["scale"]) + widest,
        "years": years,
        "files": {y: str(block["file"]).replace("<year>", str(y)) for y in years},
    }


# --- Inputs


def read_lists(store: Store) -> tuple[frozenset[str], list[str]]:
    """Both exploration lists: their union and their SHA-256s. Stops on a gap or overlap."""
    parsed: list[frozenset[str]] = []
    shas: list[str] = []
    for path in EXPLORE_LISTS_NATIONAL:
        try:
            data = store.read_bytes(path)
        except Exception as err:  # each store raises its own not-found type
            raise BuildError(f"an exploration list cannot be read: {path}") from err
        shas.append(hashlib.sha256(data).hexdigest())
        parsed.append(parse_split_list(data))
    if parsed[0] & parsed[1]:
        raise BuildError("a municipality is in both exploration lists")
    return parsed[0] | parsed[1], shas


def read_places(path: Path, election: int) -> pl.DataFrame:
    schema = pl.read_parquet_schema(path)
    wanted = [*KEY, "lat", "long", "conf_dist_km"]
    if [c for c in wanted if c not in schema]:
        raise BuildError(f"{path.name} lacks a column the build needs")
    places = pl.read_parquet(path, columns=wanted).with_columns(
        pl.col("lat").cast(pl.Float64),
        pl.col("long").cast(pl.Float64),
        pl.col("conf_dist_km").cast(pl.Float64),
    )
    if set(places["ano"].unique().to_list()) - {election}:
        raise BuildError(f"{path.name} holds another election year")
    if places.select(pl.struct(KEY).is_duplicated().any()).item():
        raise BuildError(f"{path.name}: a polling place appears twice")
    located = (
        pl.col("lat").is_not_null()
        & pl.col("long").is_not_null()
        & pl.col("lat").is_finite()
        & pl.col("long").is_finite()
        & (pl.col("conf_dist_km") <= SMALL_KM)
    ).fill_null(False)
    return places.with_columns(located.alias("located_1km")).sort(KEY)


def read_matches(path: Path, election: int) -> pl.DataFrame:
    """`id_escola` as `school_id` for the high and medium matches only."""
    schema = pl.read_parquet_schema(path)
    wanted = [*KEY, "id_escola", "confidence"]
    if [c for c in wanted if c not in schema]:
        raise BuildError(f"{path.name} lacks a column the build needs")
    matches = pl.read_parquet(path, columns=wanted)
    if set(matches["ano"].unique().to_list()) - {election}:
        raise BuildError(f"{path.name} holds another election year")
    if matches.select(pl.struct(KEY).is_duplicated().any()).item():
        raise BuildError(f"{path.name}: a polling place appears twice")
    return matches.filter(pl.col("confidence").is_in(CONFIDENT)).select(
        *KEY, pl.col("id_escola").alias("school_id")
    )


def read_schools(path: Path, years: set[int]) -> pl.DataFrame:
    """`ano`, `id_escola`, `rede` and `n_fac` (null when any of the nine values is null)."""
    schema = pl.read_parquet_schema(path)
    if [c for c in SCHOOL_COLUMNS if c not in schema]:
        raise BuildError(f"{path.name} lacks a column the build needs")
    frame = pl.read_parquet(path, columns=list(SCHOOL_COLUMNS))
    frame = frame.filter(pl.col("ano").is_in(sorted(years))).with_columns(
        pl.col("ano").cast(pl.Int64),
        *[pl.col(c).cast(pl.Int64) for c in (*FACILITIES, "dependencia_pne")],
        pl.col("acessibilidade_inexistente").cast(pl.Int64),
    )
    if frame.select(pl.struct("ano", "id_escola").is_duplicated().any()).item():
        raise BuildError(f"{path.name}: a school appears twice in a year")
    flags = [*FACILITIES, "dependencia_pne", "acessibilidade_inexistente"]
    if any(
        frame.select(pl.col(c).is_not_null() & ~pl.col(c).is_in([0, 1])).to_series().any()
        for c in flags
    ):
        raise BuildError(f"{path.name}: a facility column holds a value other than 0 or 1")
    access = (
        pl.when(pl.col("ano") <= LAST_PNE_YEAR)
        .then(pl.col("dependencia_pne"))
        .otherwise(1 - pl.col("acessibilidade_inexistente"))
    )
    nine = [pl.col(c) for c in FACILITIES] + [access]
    any_null = pl.any_horizontal([c.is_null() for c in nine])
    n_fac = pl.when(any_null).then(None).otherwise(pl.sum_horizontal(nine)).cast(pl.Int8)
    return frame.select("ano", "id_escola", "rede", n_fac.alias("n_fac"))


# --- Rasters


def read_raster(path: Path, cfg: dict[str, Any]) -> np.ndarray:
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
    if cfg["max_value"] is not None and int(arr.max()) > cfg["max_value"]:
        raise BuildError(f"{path.name}: a share is above its scale")
    return arr


def flat_band(arr: np.ndarray, cfg: dict[str, Any], band: str | None) -> np.ndarray:
    """One band as a flat array, indexed by `row * columns + column`."""
    if band is None:
        return np.ascontiguousarray(arr).ravel()
    return np.ascontiguousarray(arr[..., cfg["bands"].index(band)]).ravel()


# --- Rings


@dataclass
class Rings:
    """Cells of every located place's 10 km ring as flat offsets into a raster array."""

    offsets: np.ndarray  # int32, row * columns + column
    owner: np.ndarray  # int32, index of the place in the election's table
    small: np.ndarray  # bool, the cell is also in the 1 km ring
    cells_1km: np.ndarray  # int, per place
    cells_10km: np.ndarray  # int, per place


def project(places: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Albers km of each place; NaN where there is no coordinate."""
    lon, lat = places["long"].to_numpy(), places["lat"].to_numpy()
    x = np.full(len(lon), np.nan)
    y = np.full(len(lon), np.nan)
    ok = np.isfinite(lon) & np.isfinite(lat)
    if ok.any():
        km = grid.to_albers_km(shapely.points(lon[ok], lat[ok]))
        x[ok], y[ok] = shapely.get_x(km), shapely.get_y(km)
    return x, y


def make_rings(places: pl.DataFrame, polygons: dict[str, Any], cfg: dict[str, Any]) -> Rings:
    """The rings of the located places, from cell centres (x + 0.5, y + 0.5) in Albers km."""
    n = places.height
    px, py = project(places)
    codes = places["cd_ibge"].to_numpy()
    located = places["located_1km"].to_numpy()
    rows, cols = cfg["shape"][0], cfg["shape"][1]
    span = np.arange(-HALF_WIDTH, HALF_WIDTH + 1)
    dx, dy = (a.ravel() for a in np.meshgrid(span, span))
    parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for code in np.unique(codes[located]):
        if code not in polygons:
            raise BuildError("a polling place's municipality has no polygon in the boundaries")
        idx = np.flatnonzero(located & (codes == code))
        gx = np.floor(px[idx])[:, None].astype(np.int64) + dx[None, :]
        gy = np.floor(py[idx])[:, None].astype(np.int64) + dy[None, :]
        d2 = (gx + 0.5 - px[idx][:, None]) ** 2 + (gy + 0.5 - py[idx][:, None]) ** 2
        near = d2 <= LARGE_KM**2 + SLACK
        owner = np.broadcast_to(idx[:, None], gx.shape)[near]
        cx, cy, dist2 = gx[near], gy[near], d2[near]
        keys, inverse = np.unique(cx * CELL_KEY + cy, return_inverse=True)
        lon, lat = grid.centre_lonlat(keys // CELL_KEY, keys % CELL_KEY)
        inside = shapely.covers(polygons[code], shapely.points(lon, lat))[inverse]
        cx, cy, owner, dist2 = cx[inside], cy[inside], owner[inside], dist2[inside]
        row, col = cfg["y1"] - 1 - cy, cx - cfg["x0"]
        if ((row < 0) | (row >= rows) | (col < 0) | (col >= cols)).any():
            raise BuildError("a ring cell lies outside the grid of the GeoTIFFs")
        parts.append(((row * cols + col).astype(np.int32), owner, dist2 <= SMALL_KM**2 + SLACK))
    if parts:
        offsets = np.concatenate([p[0] for p in parts])
        owner = np.concatenate([p[1] for p in parts]).astype(np.int32)
        small = np.concatenate([p[2] for p in parts])
    else:
        offsets = np.zeros(0, dtype=np.int32)
        owner = np.zeros(0, dtype=np.int32)
        small = np.zeros(0, dtype=bool)
    return Rings(
        offsets=offsets,
        owner=owner,
        small=small,
        cells_1km=np.bincount(owner[small], minlength=n),
        cells_10km=np.bincount(owner, minlength=n),
    )


def ring_mean(flat: np.ndarray, rings: Rings, radius_km: float, divisor: float) -> pl.Series:
    """Mean of the values over a ring, per place; null for an empty ring."""
    n = len(rings.cells_10km)
    if radius_km == SMALL_KM:
        values = flat[rings.offsets[rings.small]].astype(np.float64)
        sums = np.bincount(rings.owner[rings.small], weights=values, minlength=n)
        counts = rings.cells_1km
    else:
        values = flat[rings.offsets].astype(np.float64)
        sums = np.bincount(rings.owner, weights=values, minlength=n)
        counts = rings.cells_10km
    means = np.where(counts > 0, sums / np.maximum(counts, 1) / divisor, np.nan)
    return pl.Series(means).fill_nan(None)


# --- Tables and notes


def year_table(
    places: pl.DataFrame,
    schools_e: pl.DataFrame,
    schools_y: pl.DataFrame,
    rings: Rings,
    year: int,
    lights: np.ndarray | None,
    coverage: tuple[np.ndarray, np.ndarray] | None,
) -> pl.DataFrame:
    """One row per place for the outcome year `year`; the columns of the contract.

    A place that is not located has no ring cells, so its means are null already.
    """
    table = (
        places.select(*KEY, "located_1km", "school_id")
        .join(schools_e, left_on="school_id", right_on="id_escola", how="left")
        .join(schools_y, left_on="school_id", right_on="id_escola", how="left")
    )
    empty = pl.Series([None] * places.height, dtype=pl.Float64)
    located = places["located_1km"]

    def counts(cells: np.ndarray) -> pl.Series:
        return pl.select(pl.when(located).then(pl.Series(cells, dtype=pl.Int32))).to_series()

    return table.select(
        *KEY,
        pl.lit(year, dtype=pl.Int64).alias("y"),
        "located_1km",
        "school_id",
        "school_rede",
        "school_n_fac",
        (empty if lights is None else ring_mean(lights, rings, SMALL_KM, 1000.0)).alias(
            "lights_1km"
        ),
        (empty if coverage is None else ring_mean(coverage[0], rings, SMALL_KM, 10000.0)).alias(
            "builtup_1km"
        ),
        (empty if coverage is None else ring_mean(coverage[1], rings, LARGE_KM, 10000.0)).alias(
            "native_10km"
        ),
        counts(rings.cells_1km).alias("ring_cells_1km"),
        counts(rings.cells_10km).alias("ring_cells_10km"),
    )


def year_note(explore_rows: pl.DataFrame, election: int, year: int) -> str:
    """Counts of exploration-half rows only: never a statistic of an outcome."""
    with_school = explore_rows.filter(pl.col("school_id").is_not_null())
    by_rede = with_school.group_by("school_rede").len().sort("school_rede")
    rede_text = "/".join(
        f"{'null' if r is None else r}={n}"
        for r, n in zip(by_rede["school_rede"].to_list(), by_rede["len"].to_list(), strict=True)
    )
    located = explore_rows.filter(pl.col("located_1km"))
    return (
        f"E{election} y{year}: places={explore_rows.height}, "
        f"places_with_school={with_school.height} (by rede {rede_text or 'none'}), "
        f"school_n_fac_null={int(with_school['school_n_fac'].is_null().sum())}, "
        f"located_places={located.height}, "
        f"empty_rings_1km={int((located['ring_cells_1km'] == 0).sum())}, "
        f"empty_rings_10km={int((located['ring_cells_10km'] == 0).sum())}"
    )


def check_table(table: pl.DataFrame, election: int, year: int) -> None:
    if table.select(pl.struct(KEY).is_duplicated().any()).item():
        raise BuildError(f"E{election} y{year}: a polling place appears twice")
    if set(table["ano"]) - {election} or set(table["y"]) - {year}:
        raise BuildError(f"E{election} y{year}: a row has another year")
    if table.filter(pl.col("school_n_fac").is_not_null() & pl.col("school_id").is_null()).height:
        raise BuildError(f"E{election} y{year}: a count without a school")
    if table.filter(~pl.col("located_1km") & pl.col("ring_cells_1km").is_not_null()).height:
        raise BuildError(f"E{election} y{year}: a ring for a place that is not located")


# --- Build


def build(
    store: Store,
    places_manifest: dict[str, Any],
    match_manifest: dict[str, Any],
    schools_manifest: dict[str, Any],
    boundaries_manifest: dict[str, Any],
    viirs_manifest: dict[str, Any],
    coverage_manifest: dict[str, Any],
    viirs_block: dict[str, Any],
    coverage_block: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-election, per-year, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.
    write_manifest`) when `status` is `created`. The build never lists, reads or
    checks the sealed folder: a create-only upload fails if an object is there.
    """
    explore, split_shas = read_lists(store)
    lights_cfg, cover_cfg = settings(viirs_block), settings(coverage_block)
    if any(lights_cfg[k] != cover_cfg[k] for k in ("x0", "y1")) or (
        lights_cfg["shape"][:2] != cover_cfg["shape"][:2]
    ):
        raise BuildError("the lights and coverage rasters are not on the same grid")
    if "urban" not in cover_cfg["bands"] or "native" not in cover_cfg["bands"]:
        raise BuildError("the coverage rasters need the bands urban and native")
    place_entries = {e: _file(places_manifest, f"/polling_places_{e}.parquet") for e in ELECTIONS}
    match_entries = {
        e: _file(match_manifest, f"/school_polling_match_{e}.parquet") for e in ELECTIONS
    }
    schools_entry = _file(schools_manifest, "/" + INEP_FILE)
    boundaries_entry = _file(boundaries_manifest, "/" + BOUNDARIES_FILE)
    light_entries = {
        y: _file(viirs_manifest, "/" + lights_cfg["files"][y]) for y in lights_cfg["years"]
    }
    cover_entries = {
        y: _file(coverage_manifest, "/" + cover_cfg["files"][y]) for y in cover_cfg["years"]
    }

    raster_years = tuple(sorted(set(lights_cfg["years"]) | set(cover_cfg["years"])))
    entries = [
        *place_entries.values(),
        *match_entries.values(),
        schools_entry,
        boundaries_entry,
        *light_entries.values(),
        *cover_entries.values(),
    ]
    hashed = input_hash(entries, split_shas, raster_years)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    outcome_years = {
        e: [y for y in range(e - WINDOW, e + WINDOW + 1) if y in raster_years] for e in ELECTIONS
    }
    school_years = {y for ys in outcome_years.values() for y in ys} | set(ELECTIONS)

    path = _fetch(store, schools_entry, tmp_dir)
    try:
        schools = read_schools(path, school_years)
    finally:
        path.unlink(missing_ok=True)

    # The polygons of every municipality that has a polling place.
    places: dict[int, pl.DataFrame] = {}
    for e in ELECTIONS:
        path = _fetch(store, place_entries[e], tmp_dir)
        try:
            frame = read_places(path, e)
        finally:
            path.unlink(missing_ok=True)
        path = _fetch(store, match_entries[e], tmp_dir)
        try:
            matches = read_matches(path, e)
        finally:
            path.unlink(missing_ok=True)
        places[e] = frame.join(matches, on=KEY, how="left")
    legal = frozenset(c for f in places.values() for c in f["cd_ibge"].unique().to_list())

    path = _fetch(store, boundaries_entry, tmp_dir)
    work = tmp_dir / "unpacked_boundaries"
    work.mkdir(exist_ok=True)
    try:
        polygons = read_polygons(extract_edition(path, work), legal)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        path.unlink(missing_ok=True)

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    notes: list[str] = []
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per election and year
    for e in ELECTIONS:
        frame = places[e]
        rings = make_rings(frame, polygons, cover_cfg)
        schools_e = schools.filter(pl.col("ano") == e).select(
            "id_escola", pl.col("rede").alias("school_rede")
        )
        is_explore = frame["cd_ibge"].is_in(sorted(explore))
        for y in outcome_years[e]:
            lights = coverage = None
            if y in light_entries:
                arr = _read_array(store, light_entries[y], tmp_dir, lights_cfg)
                lights = flat_band(arr, lights_cfg, None)
                del arr
            if y in cover_entries:
                arr = _read_array(store, cover_entries[y], tmp_dir, cover_cfg)
                coverage = (flat_band(arr, cover_cfg, "urban"), flat_band(arr, cover_cfg, "native"))
                del arr
            schools_y = schools.filter(pl.col("ano") == y).select(
                "id_escola", pl.col("n_fac").alias("school_n_fac")
            )
            table = year_table(frame, schools_e, schools_y, rings, y, lights, coverage)
            check_table(table, e, y)
            notes.append(year_note(table.filter(is_explore), e, y))
            sealed_file, derived_file = (
                sealed_dir / output_name(e, y),
                derived_dir / output_name(e, y),
            )
            table.filter(~is_explore).write_parquet(sealed_file)
            table.filter(is_explore).write_parquet(derived_file)
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
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (
                places_manifest,
                match_manifest,
                schools_manifest,
                boundaries_manifest,
                viirs_manifest,
                coverage_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest


def _read_array(
    store: Store, entry: dict[str, Any], tmp_dir: Path, cfg: dict[str, Any]
) -> np.ndarray:
    """Download one raster year, check it and return its array."""
    tif = _fetch(store, entry, tmp_dir)
    try:
        return read_raster(tif, cfg)
    finally:
        tif.unlink(missing_ok=True)
