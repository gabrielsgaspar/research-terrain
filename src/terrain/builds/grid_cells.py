"""The Legal Amazon's 1 km census cells with population and land tenure.

Contract of the output: data/contracts/grid_cells.md.

One row per IBGE 1 km cell whose centre lies in a Legal Amazon municipality, with its
Albers and SIRGAS coordinates, its municipality, 2010 and 2022 population and
households, and the share of the cell inside indigenous land, settlements and
undesignated forest in each election year. The layer rules are those of
`terrain.builds.polling_place_tenure`.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely
from shapely.strtree import STRtree

from terrain import grid
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.polling_place_tenure import (
    BuildError,
    _fetch,
    _file,
    _read_edition,
    check_layers_nonempty,
    creation_year,
    extract_edition,
    is_indigenous,
    is_settlement,
    is_undesignated,
    settlement_layer,
)
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "grid_cells"
OUTPUT = "grid_cells.parquet"
YEARS = tenure.YEARS
LAYERS = tenure.LAYERS
GRID_2022 = "BR1KM_20251002.zip"
BOUNDARIES = "BR_Municipios_2024.zip"
# Only centres inside this box are tested against the municipalities.
CENTRE_BOX = (-74.5, -19.0, -43.0, 6.0)  # min lon, min lat, max lon, max lat
SUM_TOLERANCE = 1.001
SHARE_TOLERANCE = 1e-9
QUERY_CHUNK = 500_000
CELL_CHUNK = 200_000


def share_columns(years: tuple[int, ...]) -> list[str]:
    return [f"share_{layer}_{y}" for y in sorted(years) for layer in LAYERS]


def output_columns(years: tuple[int, ...]) -> list[str]:
    return [
        "nome_1KM",
        "x_km",
        "y_km",
        "lon",
        "lat",
        "cd_ibge",
        "pop_2010",
        "dom_2010",
        "pop_2022",
        "dom_2022",
        *share_columns(years),
    ]


# --- Checks


def check_names(names: pl.Series) -> None:
    """Every cell name parses, and no name appears twice."""
    bad = names.filter(~names.str.contains(grid.NAME_PATTERN))
    if bad.len():
        raise BuildError(f"{bad.len()} cell names do not parse, such as {bad[0]!r}")
    if names.is_duplicated().any():
        raise BuildError("a cell name appears more than once (duplicate names)")


def check_one_municipality(matches: np.ndarray) -> None:
    """`matches[i]` is the number of municipalities containing centre i."""
    if (matches > 1).any():
        raise BuildError(
            f"{int((matches > 1).sum())} cell centres are in more than one municipality"
        )


def check_municipalities_covered(legal: set[str], present: set[str]) -> None:
    missing = sorted(legal - present)
    if missing:
        raise BuildError(f"{len(missing)} Legal Amazon municipalities have no cells: {missing[:5]}")


def check_parents(cells: pl.DataFrame) -> None:
    missing = cells.filter(pl.col("pop_2010").is_null())
    if missing.height:
        raise BuildError(
            f"{missing.height} kept cells have no 2010 parent, such as {missing['nome_1KM'][0]}"
        )


def check_shares(layer: str, year: int, values: np.ndarray) -> None:
    if np.isnan(values).any():
        raise BuildError(f"{layer} {year}: a share is missing")
    if values.size and (values.min() < 0 or values.max() > 1 + SHARE_TOLERANCE):
        raise BuildError(f"{layer} {year}: a share is outside [0, 1]")


def check_share_sum(layer: str, year: int, total_km2: float, union_km2: float) -> None:
    if total_km2 > union_km2 * SUM_TOLERANCE:
        raise BuildError(
            f"{layer} {year}: shares sum to {total_km2:.1f} km2, "
            f"more than the union's {union_km2:.1f} km2"
        )


# --- Readers


def read_dbf(zip_path: Path, dest: Path, fields: list[str]) -> dict[str, list[Any]]:
    """The named fields of the single `.dbf` in a zip, as columns. No polygons are read."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".dbf")]
        if len(members) != 1:
            raise BuildError(f"expected one .dbf in {zip_path.name}, found {len(members)}")
        target = dest / Path(members[0]).name
        with zf.open(members[0]) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    try:
        with open(target, "rb") as fh, shapefile.Reader(dbf=fh, encoding="utf-8") as reader:
            present = [f[0] for f in reader.fields[1:]]
            missing = [f for f in fields if f not in present]
            if missing:
                raise BuildError(f"{zip_path.name} lacks fields {missing}")
            order = [f for f in present if f in fields]
            columns: dict[str, list[Any]] = {f: [] for f in order}
            for record in reader.iterRecords(fields=fields):
                for name, value in zip(order, record, strict=True):
                    columns[name].append(value)
    finally:
        target.unlink(missing_ok=True)
    return {f: columns[f] for f in fields}


def as_counts(values: list[Any], what: str) -> pl.Series:
    """Whole-number counts as Int64; a missing value is 0, a fractional one stops the build."""
    series = pl.Series(what, values, dtype=pl.Float64, strict=False).fill_null(0.0)
    if (series != series.round()).any():
        raise BuildError(f"{what} holds a value that is not a whole number")
    return series.cast(pl.Int64)


def read_grid_2022(zip_path: Path, dest: Path) -> pl.DataFrame:
    data = read_dbf(zip_path, dest, ["nome_1KM", "TOTAL", "TOTAL_DOM"])
    return pl.DataFrame(
        {
            "nome_1KM": pl.Series("nome_1KM", data["nome_1KM"], dtype=pl.String),
            "pop_2022": as_counts(data["TOTAL"], "TOTAL"),
            "dom_2022": as_counts(data["TOTAL_DOM"], "TOTAL_DOM"),
        }
    )


def read_tile_2010(zip_path: Path, dest: Path) -> pl.DataFrame:
    data = read_dbf(zip_path, dest, ["nome_1KM", "POP", "DOM_OCU"])
    return pl.DataFrame(
        {
            "nome_1KM": pl.Series("nome_1KM", data["nome_1KM"], dtype=pl.String),
            "pop_2010": as_counts(data["POP"], "POP"),
            "dom_2010": as_counts(data["DOM_OCU"], "DOM_OCU"),
        }
    )


def read_municipality_polygons(shp_path: Path, legal: set[str]) -> tuple[list[str], list[Any]]:
    codes: list[str] = []
    polygons: list[Any] = []
    with shapefile.Reader(str(shp_path), encoding="utf-8") as reader:
        for item in reader.iterShapeRecords():
            code = str(item.record.as_dict()["CD_MUN"])
            if code in legal and item.shape.points:
                codes.append(code)
                polygons.append(to_shapely(item.shape.__geo_interface__))
    return codes, polygons


# --- Cells and municipalities


def cell_table(grid_2022: pl.DataFrame) -> pl.DataFrame:
    """Add `x_km`, `y_km`, `lon` and `lat` to the 2022 cells (names must already parse)."""
    parts = grid_2022["nome_1KM"].str.extract_groups(grid.NAME_PATTERN)
    x = parts.struct.field("1").cast(pl.Int64)
    y = parts.struct.field("2").cast(pl.Int64)
    lon, lat = grid.centre_lonlat(x.to_numpy(), y.to_numpy())
    return grid_2022.with_columns(
        x.alias("x_km"), y.alias("y_km"), pl.Series("lon", lon), pl.Series("lat", lat)
    )


def assign_municipalities(
    lon: np.ndarray, lat: np.ndarray, codes: list[str], polygons: list[Any]
) -> np.ndarray:
    """The municipality code of each centre inside the box and inside a polygon, else ''.

    The result is an object array; '' marks a centre in no municipality.
    """
    out = np.full(len(lon), "", dtype=object)
    if not polygons:
        return out
    min_lon, min_lat, max_lon, max_lat = CENTRE_BOX
    inside = np.flatnonzero(
        (lon >= min_lon) & (lon <= max_lon) & (lat >= min_lat) & (lat <= max_lat)
    )
    tree = STRtree(np.array(polygons, dtype=object))
    code_array = np.array(codes, dtype=object)
    for start in range(0, len(inside), QUERY_CHUNK):
        chunk = inside[start : start + QUERY_CHUNK]
        points = shapely.points(lon[chunk], lat[chunk])
        pairs = tree.query(points, predicate="within")
        check_one_municipality(np.bincount(pairs[0], minlength=len(chunk)))
        out[chunk[pairs[0]]] = code_array[pairs[1]]
    return out


# --- Tenure shares


def polygonal_parts(geometry: Any) -> list[Any]:
    """The polygons inside a geometry (which may be a collection with lines and points)."""
    found: list[Any] = []
    stack = [geometry]
    while stack:
        g = stack.pop()
        if g is None or shapely.is_empty(g):
            continue
        type_id = shapely.get_type_id(g)
        if type_id == 3:
            found.append(g)
        elif type_id in (4, 5, 6, 7):
            stack.extend(shapely.get_parts(g))
    return found


def repair(geometries: list[Any]) -> list[list[Any]]:
    """Make each projected geometry valid; keep only its polygonal parts."""
    if not geometries:
        return []
    fixed = shapely.make_valid(np.array(geometries, dtype=object))
    return [polygonal_parts(g) for g in fixed]


def project_and_repair(geometries: list[Any]) -> list[list[Any]]:
    """Degrees to Albers km, then `repair`: the polygonal parts of each geometry."""
    if not geometries:
        return []
    return repair(list(grid.to_albers_km(np.array(geometries, dtype=object))))


def flatten(repaired: list[list[Any]]) -> list[Any]:
    return [part for parts in repaired for part in parts]


def layer_shares(polygons_km: list[Any]) -> tuple[pl.DataFrame, float]:
    """Share of every touched 1 km cell inside the union of `polygons_km` (Albers km).

    Returns a frame of `x_km`, `y_km`, `share` (cells with a share above 0) and the
    area of the union in km2. Overlaps count once, because the union is taken first.
    """
    union = shapely.union_all(np.array(polygons_km, dtype=object))
    parts = [p for p in shapely.get_parts(union) if shapely.get_type_id(p) == 3]
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    shares: list[np.ndarray] = []
    for part in parts:
        min_x, min_y, max_x, max_y = shapely.bounds(part)
        cols = np.arange(int(np.floor(min_x)), int(np.ceil(max_x)))
        rows = np.arange(int(np.floor(min_y)), int(np.ceil(max_y)))
        if not len(cols) or not len(rows):
            continue
        shapely.prepare(part)
        step = max(1, CELL_CHUNK // len(cols))
        for start in range(0, len(rows), step):
            gx, gy = np.meshgrid(cols, rows[start : start + step])
            gx, gy = gx.ravel(), gy.ravel()
            squares = shapely.box(gx, gy, gx + 1.0, gy + 1.0)
            hit = shapely.intersects(part, squares)
            if not hit.any():
                continue
            gx, gy, squares = gx[hit], gy[hit], squares[hit]
            whole = shapely.contains(part, squares)
            share = np.ones(len(squares))
            partial = ~whole
            if partial.any():
                share[partial] = shapely.area(shapely.intersection(squares[partial], part))
            positive = share > 0
            xs.append(gx[positive])
            ys.append(gy[positive])
            shares.append(share[positive])
    if not xs:
        empty = pl.DataFrame(
            {"x_km": [], "y_km": [], "share": []},
            schema={"x_km": pl.Int64, "y_km": pl.Int64, "share": pl.Float64},
        )
        return empty, float(shapely.area(union))
    table = (
        pl.DataFrame(
            {
                "x_km": np.concatenate(xs),
                "y_km": np.concatenate(ys),
                "share": np.concatenate(shares),
            }
        )
        .group_by(["x_km", "y_km"])
        .agg(pl.col("share").sum())
    )
    return table, float(shapely.area(union))


# --- Build

# Every module whose code decides what this build writes. Its source is part of
# the output path: this file, the grid helpers and the layer rules it reuses.
CODE_MODULES = (Path(__file__), Path(grid.__file__), Path(tenure.__file__))


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]], years: tuple[int, ...], code: list[str] | None = None
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, ",".join(str(y) for y in sorted(years)), *sources)


def _states(cells: pl.DataFrame) -> str:
    table = (
        cells.with_columns(pl.col("cd_ibge").str.slice(0, 2).alias("state"))
        .group_by("state")
        .agg(
            pl.len().alias("cells"),
            pl.col("pop_2010").sum().alias("pop_2010"),
            pl.col("pop_2022").sum().alias("pop_2022"),
            (pl.col("pop_2022") == 0).mean().alias("empty"),
        )
        .sort("state")
    )
    return "; ".join(
        f"state {r['state']}: cells={r['cells']}, pop_2010={r['pop_2010']}, "
        f"pop_2022={r['pop_2022']}, share_empty_2022={r['empty']:.4f}"
        for r in table.iter_rows(named=True)
    )


def build(
    store: Store,
    grid_2022_manifest: dict[str, Any],
    grid_2010_manifest: dict[str, Any],
    boundaries_manifest: dict[str, Any],
    cnfp_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build `grid_cells.parquet` into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    unknown = [y for y in years if y not in tenure.EDITIONS]
    if unknown:
        raise BuildError(f"no register edition for years {unknown}")
    entry_2022 = _file(grid_2022_manifest, GRID_2022)
    tiles = [f for f in grid_2010_manifest["files"] if f["path"].endswith(".zip")]
    if not tiles:
        raise BuildError("the 2010 grid manifest lists no tiles")
    entry_boundaries = _file(boundaries_manifest, BOUNDARIES)
    entry_municipalities = _file(municipalities_manifest, ".parquet")
    edition_entries = {y: _file(cnfp_manifest, tenure.EDITIONS[y]) for y in years}
    settlement_entry = _file(cnfp_manifest, tenure.SETTLEMENT_EDITION)
    entries = [
        entry_2022,
        *tiles,
        entry_boundaries,
        entry_municipalities,
        *edition_entries.values(),
        settlement_entry,
    ]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    municipalities = pl.read_parquet(
        _fetch(store, entry_municipalities, tmp_dir), columns=["cd_ibge", "legal_amazon"]
    )
    legal = set(municipalities.filter(pl.col("legal_amazon"))["cd_ibge"].to_list())

    # 2022 cells, and the municipality of each centre.
    zip_path = _fetch(store, entry_2022, tmp_dir)
    try:
        grid_2022 = read_grid_2022(zip_path, tmp_dir)
    finally:
        zip_path.unlink(missing_ok=True)
    check_names(grid_2022["nome_1KM"])
    cells = cell_table(grid_2022)
    del grid_2022

    zip_path = _fetch(store, entry_boundaries, tmp_dir)
    work = tmp_dir / "unpacked_boundaries"
    work.mkdir(exist_ok=True)
    try:
        codes, polygons = read_municipality_polygons(extract_edition(zip_path, work), legal)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
    owner = assign_municipalities(cells["lon"].to_numpy(), cells["lat"].to_numpy(), codes, polygons)
    cells = cells.with_columns(pl.Series("cd_ibge", owner, dtype=pl.String)).filter(
        pl.col("cd_ibge") != ""
    )
    check_municipalities_covered(legal, set(cells["cd_ibge"].unique().to_list()))

    # 2010 population: sum the 1 km parent over all tiles (1 km and 200 m rows alike).
    kept_names = cells.select("nome_1KM")
    parts_2010: list[pl.DataFrame] = []
    for entry in tiles:
        tile = _fetch(store, entry, tmp_dir)
        try:
            table = read_tile_2010(tile, tmp_dir)
        finally:
            tile.unlink(missing_ok=True)
        parts_2010.append(table.join(kept_names, on="nome_1KM", how="semi"))
    pop_2010 = (
        pl.concat(parts_2010)
        .group_by("nome_1KM")
        .agg(pl.col("pop_2010").sum(), pl.col("dom_2010").sum())
    )
    cells = cells.join(pop_2010, on="nome_1KM", how="left").sort(["cd_ibge", "y_km", "x_km"])
    check_parents(cells)
    return _finish(
        store,
        cells,
        edition_entries,
        settlement_entry,
        prefix=prefix,
        manifests=(
            grid_2022_manifest,
            grid_2010_manifest,
            boundaries_manifest,
            cnfp_manifest,
            municipalities_manifest,
        ),
        years=years,
        tmp_dir=tmp_dir,
        code_commit=code_commit,
        created_at=created_at,
    )


def _finish(
    store: Store,
    cells: pl.DataFrame,
    edition_entries: dict[int, dict[str, Any]],
    settlement_entry: dict[str, Any],
    *,
    prefix: str,
    manifests: tuple[dict[str, Any], ...],
    years: tuple[int, ...],
    tmp_dir: Path,
    code_commit: str | None,
    created_at: str | None,
) -> dict[str, Any]:
    """Tenure shares, final checks, local write, then upload."""
    kept = [
        f for f in _read_edition(store, settlement_entry, tmp_dir) if is_settlement(f.categoria)
    ]
    repaired = project_and_repair([f.geometry for f in kept])
    settlements = [
        (part, creation_year(f.anocriacao))
        for f, parts in zip(kept, repaired, strict=True)
        for part in parts
    ]
    del kept

    notes: list[str] = []
    for y in sorted(years):
        features = _read_edition(store, edition_entries[y], tmp_dir)
        layers: dict[str, list[Any]] = {
            "indigenous": flatten(
                project_and_repair([f.geometry for f in features if is_indigenous(f.categoria)])
            ),
            "undesignated": flatten(
                project_and_repair([f.geometry for f in features if is_undesignated(f.tipo)])
            ),
        }
        layers["settlement"] = settlement_layer(settlements, y)
        del features
        check_layers_nonempty(y, {name: len(p) for name, p in layers.items()})
        for name in LAYERS:
            table, union_km2 = layer_shares(layers[name])
            column = f"share_{name}_{y}"
            joined = cells.select("x_km", "y_km").join(table, on=["x_km", "y_km"], how="left")
            values = joined["share"].fill_null(0.0).to_numpy()
            check_shares(name, y, values)
            check_share_sum(name, y, float(table["share"].sum()), union_km2)
            cells = cells.with_columns(pl.Series(column, np.clip(values, 0.0, 1.0)))
            notes.append(
                f"{name} {y}: cells_with_share={int((values > 0).sum())}, "
                f"sum_km2={float(np.clip(values, 0.0, 1.0).sum()):.1f}, union_km2={union_km2:.1f}"
            )
    out = cells.select(output_columns(years))
    path = tmp_dir / OUTPUT
    out.write_parquet(path)

    store.create(prefix + OUTPUT, path)
    files = [{"path": prefix + OUTPUT, "sha256": sha256_file(path), "bytes": path.stat().st_size}]
    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[m["gcs_prefix"] + MANIFEST_NAME for m in manifests],
        notes="; ".join([_states(out), *notes]),
        code_commit=code_commit,
        created_at=created_at,
    )
