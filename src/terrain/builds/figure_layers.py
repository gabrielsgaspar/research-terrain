"""Simplified map layers for the paper figures (figures 1-3).

Contract of the output: data/contracts/figure_layers.md.

Reads the Natural Earth basemap, the IBGE state and Legal Amazon outlines and the
2024 and 2025 editions of the Forest Service's public-forest register (CNFP), and
writes nine clipped and simplified layers to one Parquet file with WKB geometry.
The tenure layers reuse the readers and rules of `polling_place_tenure`, so they
are the same polygons as the 2024 layers of that build.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl
import shapefile
import shapely
from shapely.geometry import box
from shapely.geometry import shape as to_shapely

from terrain.builds import polling_place_tenure as pt
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "figure_layers"
OUTPUT_NAME = "figure_layers.parquet"
OUTPUT_COLUMNS = ["layer", "code", "name", "scalerank", "geometry"]

BuildError = pt.BuildError

# South America with a margin: (min lon, min lat, max lon, max lat).
FRAME_BOX = (-92.0, -57.0, -26.0, 14.0)
FRAME = box(*FRAME_BOX)
# One Legal Amazon outline must lie inside this box (the one the tenure build uses).
LEGAL_AMAZON_BOX = pt.LEGAL_AMAZON_BOX
STATES = 27
MAX_EMPTY_SHARE = 0.01

NE_ZIPS = {
    "country": "ne_10m_admin_0_countries.zip",
    "ocean": "ne_10m_ocean.zip",
    "lake": "ne_10m_lakes.zip",
    "river": "ne_10m_rivers_lake_centerlines.zip",
}
STATE_ZIP = "BR_UF_2024.zip"
LEGAL_AMAZON_ZIP = "Limites_Amazonia_Legal_2024_shp.zip"
TENURE_2024_ZIP = pt.EDITIONS[2024]
TENURE_2025_ZIP = pt.SETTLEMENT_EDITION


class Layer(NamedTuple):
    name: str
    source: str  # zip file name
    code_field: str | None
    name_field: str | None
    clip: bool
    tolerance: float
    dimension: int  # 2 polygons, 1 lines
    scalerank: bool


SHAPEFILE_LAYERS = (
    Layer("country", NE_ZIPS["country"], "ADM0_A3", "NAME", True, 0.01, 2, False),
    Layer("ocean", NE_ZIPS["ocean"], None, None, True, 0.01, 2, False),
    Layer("lake", NE_ZIPS["lake"], None, "name", True, 0.01, 2, True),
    Layer("river", NE_ZIPS["river"], None, "name", True, 0.01, 1, True),
    Layer("state", STATE_ZIP, "SIGLA_UF", "NM_UF", False, 0.01, 2, False),
    Layer("legal_amazon", LEGAL_AMAZON_ZIP, None, "NOME", False, 0.005, 2, False),
)
TENURE_TOLERANCE = 0.002
TENURE_LAYERS = ("indigenous", "settlement", "undesignated")
LAYER_NAMES = (*(layer.name for layer in SHAPEFILE_LAYERS), *TENURE_LAYERS)

# One output row: (layer, code, name, scalerank, geometry).
Row = tuple[str, str | None, str | None, int | None, Any]


# --- Geometry


def keep_dimension(geometry: Any, dimension: int) -> Any | None:
    """The parts of `geometry` of the given dimension (2 polygons, 1 lines), or None.

    `make_valid` and clipping can return a collection with stray points or lines.
    """
    if geometry is None or shapely.is_empty(geometry):
        return None
    parts = [p for p in shapely.get_parts(geometry) if shapely.get_dimensions(p) == dimension]
    parts = [p for p in parts if not shapely.is_empty(p)]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return shapely.MultiPolygon(parts) if dimension == 2 else shapely.MultiLineString(parts)


def simplify(geometry: Any, tolerance: float, dimension: int = 2) -> Any | None:
    """Simplify keeping topology, repair, keep the layer's own dimension; None if empty."""
    out = shapely.simplify(geometry, tolerance, preserve_topology=True)
    return keep_dimension(shapely.make_valid(out), dimension)


def clip_to_frame(geometry: Any, dimension: int = 2) -> Any | None:
    """The part of `geometry` inside `FRAME`; None when it does not meet the frame."""
    if not shapely.is_valid(geometry):
        geometry = shapely.make_valid(geometry)
    if not shapely.intersects(geometry, FRAME):
        return None
    return keep_dimension(shapely.intersection(geometry, FRAME), dimension)


# --- Reader


def read_shapefile_zip(zip_path: Path, member: str | None = None) -> list[tuple[dict, Any]]:
    """(record, shapely geometry) for each shape of one shapefile in a zip.

    `member` is the `.shp` name; by default the single `.shp` of the zip. Text is
    read as UTF-8 (the shapefiles declare it). Null shapes are skipped.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        shps = [n for n in names if n.lower().endswith(".shp")]
        if member is None:
            if len(shps) != 1:
                raise BuildError(f"expected one .shp member in {zip_path.name}, found {len(shps)}")
            member = shps[0]
        elif member not in names:
            raise BuildError(f"{member} is not in {zip_path.name}")
        stem = member[: -len(".shp")]
        parts = {}
        for ext in ("shp", "shx", "dbf"):
            wanted = f"{stem}.{ext}".lower()
            found = [n for n in names if n.lower() == wanted]
            if not found:
                raise BuildError(f"{stem}.{ext} is not in {zip_path.name}")
            parts[ext] = io.BytesIO(zf.read(found[0]))
    out: list[tuple[dict, Any]] = []
    with shapefile.Reader(
        shp=parts["shp"], shx=parts["shx"], dbf=parts["dbf"], encoding="utf-8"
    ) as reader:
        for item in reader.iterShapeRecords():
            if item.shape.shapeType == shapefile.NULL or not item.shape.points:
                continue
            out.append((item.record.as_dict(), to_shapely(item.shape.__geo_interface__)))
    return out


def _field(record: dict, name: str | None) -> Any:
    if name is None:
        return None
    if name in record:
        return record[name]
    lowered = {k.lower(): v for k, v in record.items()}
    return lowered.get(name.lower())


def _text(value: Any) -> str | None:
    text = None if value is None else str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


# --- Layers


def shapefile_layer(layer: Layer, records: list[tuple[dict, Any]]) -> list[Row]:
    rows: list[Row] = []
    for record, geometry in records:
        if layer.clip:
            geometry = clip_to_frame(geometry, layer.dimension)
            if geometry is None:
                continue
        geometry = simplify(geometry, layer.tolerance, layer.dimension)
        if geometry is None:
            continue
        rows.append(
            (
                layer.name,
                _text(_field(record, layer.code_field)),
                _text(_field(record, layer.name_field)),
                _int(_field(record, "scalerank")) if layer.scalerank else None,
                geometry,
            )
        )
    return rows


def tenure_layer(name: str, geometries: list[Any]) -> tuple[list[Row], int, int]:
    """Rows of one tenure layer, the count before simplifying, and the number dropped as empty."""
    rows: list[Row] = []
    for geometry in geometries:
        simple = simplify(geometry, TENURE_TOLERANCE)
        if simple is not None:
            rows.append((name, None, None, None, simple))
    return rows, len(geometries), len(geometries) - len(rows)


def tenure_layers(
    features_2024: list[pt.Feature], features_2025: list[pt.Feature]
) -> tuple[list[Row], dict[str, tuple[int, int]]]:
    """The three tenure layers of 2024 and, per layer, (count before simplifying, dropped)."""
    chosen = {
        "indigenous": [f.geometry for f in features_2024 if pt.is_indigenous(f.categoria)],
        "settlement": [
            f.geometry
            for f in features_2025
            if pt.is_settlement(f.categoria)
            and (created := pt.creation_year(f.anocriacao)) is not None
            and created <= 2024
        ],
        "undesignated": [f.geometry for f in features_2024 if pt.is_undesignated(f.tipo)],
    }
    rows: list[Row] = []
    counts: dict[str, tuple[int, int]] = {}
    for name in TENURE_LAYERS:
        layer_rows, before, dropped = tenure_layer(name, chosen[name])
        rows += layer_rows
        counts[name] = (before, dropped)
    return rows, counts


# --- Checks


def check_layers(rows: list[Row], counts: dict[str, tuple[int, int]]) -> None:
    """Every check of the contract; raises BuildError."""
    by_layer: dict[str, list[Row]] = {name: [] for name in LAYER_NAMES}
    for row in rows:
        by_layer[row[0]].append(row)
    empty = [name for name, found in by_layer.items() if not found]
    if empty:
        raise BuildError(f"empty layers {empty}")
    if "BRA" not in {r[1] for r in by_layer["country"]}:
        raise BuildError("the country layer has no BRA")
    codes = [r[1] for r in by_layer["state"]]
    if len(by_layer["state"]) != STATES or len(set(codes)) != STATES:
        raise BuildError(
            f"expected {STATES} states with distinct codes, found {len(codes)} rows "
            f"and {len(set(codes))} codes"
        )
    if len(by_layer["legal_amazon"]) != 1:
        raise BuildError(f"expected one legal_amazon row, found {len(by_layer['legal_amazon'])}")
    min_x, min_y, max_x, max_y = shapely.bounds(by_layer["legal_amazon"][0][4])
    lo_x, lo_y, hi_x, hi_y = LEGAL_AMAZON_BOX
    if min_x < lo_x or min_y < lo_y or max_x > hi_x or max_y > hi_y:
        raise BuildError(f"the Legal Amazon outline lies outside {LEGAL_AMAZON_BOX}")
    invalid = [r[0] for r in rows if not shapely.is_valid(r[4])]
    if invalid:
        raise BuildError(f"invalid geometries in {sorted(set(invalid))}")
    for name, (before, dropped) in counts.items():
        if before and dropped / before > MAX_EMPTY_SHARE:
            raise BuildError(f"{name}: {dropped} of {before} polygons were empty after simplifying")


# --- Output path


# Every module whose code decides what this build writes. Its source is part of the
# output path: this file and the tenure build whose readers and rules it reuses.
CODE_MODULES = (Path(__file__), Path(pt.__file__))


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(files: list[dict[str, Any]], code: list[str] | None = None) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, *sources)


# --- Build


def _read_zip(store: Store, entry: dict[str, Any], tmp_dir: Path) -> list[tuple[dict, Any]]:
    """Download one zip, read its shapefile and delete the zip."""
    zip_path = pt._fetch(store, entry, tmp_dir)
    try:
        return read_shapefile_zip(zip_path)
    finally:
        zip_path.unlink(missing_ok=True)


def _note(rows: list[Row], counts: dict[str, tuple[int, int]]) -> str:
    sizes = {name: sum(1 for r in rows if r[0] == name) for name in LAYER_NAMES}
    parts = []
    for name in LAYER_NAMES:
        text = f"{name}={sizes[name]}"
        if name in counts:
            before, dropped = counts[name]
            text += f" (before_simplify={before}, dropped_empty={dropped})"
        parts.append(text)
    return ", ".join(parts)


def build(
    store: Store,
    naturalearth_manifest: dict[str, Any],
    ibge_manifest: dict[str, Any],
    cnfp_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build `figure_layers.parquet` into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    shape_entries = {
        layer.name: pt._file(
            ibge_manifest if layer.name in ("state", "legal_amazon") else naturalearth_manifest,
            layer.source,
        )
        for layer in SHAPEFILE_LAYERS
    }
    entry_2024 = pt._file(cnfp_manifest, TENURE_2024_ZIP)
    entry_2025 = pt._file(cnfp_manifest, TENURE_2025_ZIP)
    entries = [*shape_entries.values(), entry_2024, entry_2025]

    prefix = f"{derived_root}{input_hash(entries)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    # Everything is built and checked locally; nothing reaches the store unless
    # every check passes, so a failed run leaves no partial output.
    rows: list[Row] = []
    for layer in SHAPEFILE_LAYERS:
        rows += shapefile_layer(layer, _read_zip(store, shape_entries[layer.name], tmp_dir))
    features_2024 = pt._read_edition(store, entry_2024, tmp_dir)
    features_2025 = pt._read_edition(store, entry_2025, tmp_dir)
    tenure_rows, counts = tenure_layers(features_2024, features_2025)
    del features_2024, features_2025
    rows += tenure_rows

    check_layers(rows, counts)

    rows.sort(key=lambda r: r[0])  # stable: input order within a layer
    table = pl.DataFrame(
        {
            "layer": [r[0] for r in rows],
            "code": [r[1] for r in rows],
            "name": [r[2] for r in rows],
            "scalerank": [r[3] for r in rows],
            "geometry": [shapely.to_wkb(r[4], output_dimension=2) for r in rows],
        },
        schema={
            "layer": pl.String,
            "code": pl.String,
            "name": pl.String,
            "scalerank": pl.Int64,
            "geometry": pl.Binary,
        },
    )
    path = tmp_dir / OUTPUT_NAME
    table.select(OUTPUT_COLUMNS).write_parquet(path)

    store.create(prefix + OUTPUT_NAME, path)
    files = [
        {"path": prefix + OUTPUT_NAME, "sha256": sha256_file(path), "bytes": path.stat().st_size}
    ]
    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (naturalearth_manifest, ibge_manifest, cnfp_manifest)
        ],
        notes=_note(rows, counts),
        code_commit=code_commit,
        created_at=created_at,
    )
