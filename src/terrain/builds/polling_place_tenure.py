"""Distance from every polling place to indigenous land, settlements and undesignated forest.

Contract of the output: data/contracts/polling_place_tenure.md.

The rules (task 14): from the Forest Service's public-forest register (CNFP),
indigenous lands and undesignated forest (`TIPO B`) come from the edition of the
election year; settlements come from the 2025 edition, kept when created by the
election year. Distances are to the nearest polygon of each layer, in km, on a
flat projection of longitude and latitude; inside a polygon the distance is 0.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely
from shapely.strtree import STRtree

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "polling_place_tenure"
YEARS = (2008, 2012, 2016, 2020, 2024)
KEY = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
DISTANCES = ["dist_indigenous_km", "dist_settlement_km", "dist_undesignated_km"]
OUTPUT_COLUMNS = [*KEY, *DISTANCES]
LAYERS = ("indigenous", "settlement", "undesignated")

# Legal Amazon box: (min lon, min lat, max lon, max lat).
LEGAL_AMAZON_BOX = (-74.0, -18.5, -43.0, 5.5)
SETTLEMENT_PREFIXES = frozenset(
    {
        "PA",
        "PA.",
        "PAE",
        "PDS",
        "PAF",
        "PAC",
        "PCA",
        "PIC",
        "PAD",
        "PE",
        "PAM",
        "PAR",
        "PRB",
        "PFP",
        "PCT",
    }
)
UNDESIGNATED_TIPO = "TIPO B"
EDITIONS = {
    2008: "CNFP_2008.zip",
    2012: "CNFP_2012.zip",
    2016: "CNFP_2016.zip",
    2020: "CNFP_2020.zip",
    2024: "CNFP_2024_retificado.zip",
}
SETTLEMENT_EDITION = "CNFP_2025.zip"
KM_PER_DEGREE_LON = 111.32
KM_PER_DEGREE_LAT = 110.574
SHARE_THRESHOLDS_KM = (0, 2, 5)
POLYGON_TYPES = (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM)


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def output_name(year: int) -> str:
    return f"polling_place_tenure_{year}.parquet"


class Feature(NamedTuple):
    geometry: Any
    categoria: str
    tipo: str
    anocriacao: str


# --- Reader


def extract_edition(zip_path: Path, dest: Path) -> Path:
    """Unpack the single `.shp` of an edition and its sibling files into `dest`."""
    with zipfile.ZipFile(zip_path) as zf:
        shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
        if len(shps) != 1:
            raise BuildError(f"expected one .shp member in {zip_path.name}, found {len(shps)}")
        stem = shps[0][: -len(".shp")].lower()
        target = None
        for name in zf.namelist():
            if name.endswith("/") or not name.lower().startswith(stem + "."):
                continue
            out = dest / Path(name).name
            with zf.open(name) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if name == shps[0]:
                target = out
    if target is None:
        raise BuildError(f"could not unpack {shps[0]} from {zip_path.name}")
    return target


def read_cnfp(shp_path: Path) -> list[Feature]:
    """Polygons whose bounding box meets the Legal Amazon box.

    Text is read as UTF-8 with bad bytes replaced (some fields are cut
    mid-character). Null and empty shapes are skipped. Field names are
    lower-cased; the type field is `tipo`, or `tipo_flor` in the 2008 edition.
    """
    min_x, min_y, max_x, max_y = LEGAL_AMAZON_BOX
    features: list[Feature] = []
    with shapefile.Reader(str(shp_path), encoding="utf-8", encodingErrors="replace") as reader:
        for item in reader.iterShapeRecords():
            geom = item.shape
            box = getattr(geom, "bbox", None)
            if geom.shapeType not in POLYGON_TYPES or box is None or not geom.points:
                continue
            if box[2] < min_x or box[0] > max_x or box[3] < min_y or box[1] > max_y:
                continue
            record = {k.lower(): v for k, v in item.record.as_dict().items()}
            tipo = record["tipo"] if "tipo" in record else record.get("tipo_flor")
            features.append(
                Feature(
                    to_shapely(geom.__geo_interface__),
                    str(record.get("categoria") or ""),
                    str(tipo or ""),
                    str(record.get("anocriacao") or ""),
                )
            )
    return features


# --- Group rules


def _parts(categoria: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[/;]", categoria or "")]


def is_indigenous(categoria: str | None) -> bool:
    return any(p == "TI" or "Terra Ind" in p for p in _parts(categoria))


def is_settlement(categoria: str | None) -> bool:
    return _parts(categoria)[0] in SETTLEMENT_PREFIXES


def is_undesignated(tipo: str | None) -> bool:
    return (tipo or "").strip() == UNDESIGNATED_TIPO


def creation_year(text: str | None) -> int | None:
    """The first 4-digit year from 1800 to 2099 in `text`, else None."""
    for found in re.finditer(r"(?<!\d)\d{4}(?!\d)", text or ""):
        year = int(found.group())
        if 1800 <= year <= 2099:
            return year
    return None


def settlement_layer(settlements: list[tuple[Any, int | None]], year: int) -> list[Any]:
    """Settlement polygons created by `year`; those without a creation year are left out."""
    return [g for g, created in settlements if created is not None and created <= year]


# --- Projection and distance


def project_km(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    """Flat kilometres: x = lon * 111.32 * cos(lat), y = lat * 110.574 (about 1% accurate)."""
    lon_a = np.asarray(lon, dtype=float)
    lat_a = np.asarray(lat, dtype=float)
    return lon_a * KM_PER_DEGREE_LON * np.cos(np.radians(lat_a)), lat_a * KM_PER_DEGREE_LAT


def _project_coords(coords: np.ndarray) -> np.ndarray:
    return np.column_stack(project_km(coords[:, 0], coords[:, 1]))


def project_geometries(geometries: list[Any]) -> list[Any]:
    if not geometries:
        return []
    return list(shapely.transform(np.array(geometries, dtype=object), _project_coords))


def nearest_km(lon: Any, lat: Any, polygons: list[Any]) -> np.ndarray:
    """Distance in km from each point to the nearest of the projected `polygons`.

    0 inside a polygon; NaN for a point without coordinates (or when there are no polygons).
    """
    lon_a = np.asarray(lon, dtype=float)
    lat_a = np.asarray(lat, dtype=float)
    out = np.full(len(lon_a), np.nan)
    located = np.flatnonzero(~(np.isnan(lon_a) | np.isnan(lat_a)))
    if not polygons or not len(located):
        return out
    x, y = project_km(lon_a[located], lat_a[located])
    tree = STRtree(np.array(polygons, dtype=object))
    found, dist = tree.query_nearest(shapely.points(x, y), return_distance=True, all_matches=False)
    out[located[found[0]]] = dist
    return out


# --- Checks


def check_one_row_per_place(source: pl.DataFrame, out: pl.DataFrame) -> None:
    """The output has the key set of `polling_places`, each key once."""
    if out.select(KEY).is_duplicated().any():
        raise BuildError("a polling place appears more than once in the output")
    if out.height != source.height:
        raise BuildError(f"{out.height} output rows for {source.height} polling places")
    if source.select(KEY).join(out.select(KEY), on=KEY, how="anti").height:
        raise BuildError("a polling place is missing from the output")


def check_layers_nonempty(year: int, sizes: dict[str, int]) -> None:
    empty = [name for name in LAYERS if not sizes.get(name)]
    if empty:
        raise BuildError(f"{year}: empty layers {empty}")


def check_nonnegative(out: pl.DataFrame) -> None:
    for column in DISTANCES:
        if (out[column] < 0).any():
            raise BuildError(f"negative distance in {column}")


# --- Build


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


# Every module whose code decides what this build writes. Its source is part of
# the output path. This build imports no other data-handling terrain module.
CODE_MODULES = (Path(__file__),)


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


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def _read_edition(store: Store, entry: dict[str, Any], tmp_dir: Path) -> list[Feature]:
    """Download one edition, read it and delete its zip and unpacked files."""
    zip_path = _fetch(store, entry, tmp_dir)
    work = tmp_dir / ("unpacked_" + zip_path.stem)
    work.mkdir(exist_ok=True)
    try:
        return read_cnfp(extract_edition(zip_path, work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        zip_path.unlink(missing_ok=True)


def _shares(column: pl.Series) -> str:
    located = column.drop_nulls()
    if not located.len():
        return "n/a"
    return "/".join(f"{(located <= t).sum() / located.len():.4f}" for t in SHARE_THRESHOLDS_KM)


def _note(year: int, table: pl.DataFrame, sizes: dict[str, int], undated: int) -> str:
    no_coordinates = table.filter(pl.col("dist_indigenous_km").is_null()).height
    parts = [f"{year}: places={table.height}", f"no_coordinates={no_coordinates}"]
    parts += [f"{name}_polygons={sizes[name]}" for name in LAYERS]
    parts.append(f"settlements_without_year={undated}")
    for name, column in zip(LAYERS, DISTANCES, strict=True):
        parts.append(f"share_within_0/2/5km_{name}={_shares(table[column])}")
    return ", ".join(parts)


def build(
    store: Store,
    polling_places_manifest: dict[str, Any],
    cnfp_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one Parquet per year into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    unknown = [y for y in years if y not in EDITIONS]
    if unknown:
        raise BuildError(f"no register edition for years {unknown}")
    place_entries = {
        y: _file(polling_places_manifest, f"polling_places_{y}.parquet") for y in years
    }
    edition_entries = {y: _file(cnfp_manifest, EDITIONS[y]) for y in years}
    settlement_entry = _file(cnfp_manifest, SETTLEMENT_EDITION)
    entries = [*place_entries.values(), *edition_entries.values(), settlement_entry]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    sources = {
        y: pl.read_parquet(
            _fetch(store, place_entries[y], tmp_dir), columns=[*KEY, "lat", "long"]
        ).sort(KEY)
        for y in sorted(years)
    }

    kept = [
        f for f in _read_edition(store, settlement_entry, tmp_dir) if is_settlement(f.categoria)
    ]
    settlements = list(
        zip(
            project_geometries([f.geometry for f in kept]),
            [creation_year(f.anocriacao) for f in kept],
            strict=True,
        )
    )
    undated = sum(1 for _, created in settlements if created is None)

    # Every year is built and checked locally first; nothing reaches the store
    # unless all of them pass, so a failed run leaves no partial output.
    local: list[tuple[int, Path]] = []
    notes: list[str] = []
    for y in sorted(years):
        features = _read_edition(store, edition_entries[y], tmp_dir)
        layers = {
            "indigenous": project_geometries(
                [f.geometry for f in features if is_indigenous(f.categoria)]
            ),
            "settlement": settlement_layer(settlements, y),
            "undesignated": project_geometries(
                [f.geometry for f in features if is_undesignated(f.tipo)]
            ),
        }
        del features
        sizes = {name: len(polygons) for name, polygons in layers.items()}
        check_layers_nonempty(y, sizes)

        source = sources[y]
        lon = source["long"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
        lat = source["lat"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
        table = source.select(KEY).with_columns(
            *(
                pl.Series(column, nearest_km(lon, lat, layers[name]), dtype=pl.Float64).fill_nan(
                    None
                )
                for name, column in zip(LAYERS, DISTANCES, strict=True)
            )
        )
        check_one_row_per_place(source, table)
        check_nonnegative(table)
        path = tmp_dir / output_name(y)
        table.sort(KEY).select(OUTPUT_COLUMNS).write_parquet(path)
        local.append((y, path))
        notes.append(_note(y, table, sizes, undated))

    files: list[dict[str, Any]] = []
    for y, path in local:
        store.create(prefix + output_name(y), path)
        files.append(
            {
                "path": prefix + output_name(y),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[m["gcs_prefix"] + MANIFEST_NAME for m in (polling_places_manifest, cnfp_manifest)],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
