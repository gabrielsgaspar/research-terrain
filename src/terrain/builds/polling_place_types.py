"""Type every Legal Amazon polling place: seat, town, or the countryside.

Contract of the output: data/contracts/polling_place_types.md.

The rule (task 09): merge IBGE urbanized-area polygons within about 100 m into
clusters; a place inside the seat cluster of its municipality is `seat`, inside
any other cluster `town`; otherwise it takes the category of the nearest locality
of its own municipality, or `dispersed` when that locality is over 5 km away.
Eligible voters are the round-1 sum of the TSE section file, 2012 onward.
"""

from __future__ import annotations

import fnmatch
import io
import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely
from shapely.strtree import STRtree

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "polling_place_types"
YEARS = (2008, 2012, 2016, 2020, 2024)
NO_TSE_YEARS = (2008,)
KEY = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
OUTPUT_COLUMNS = [
    *KEY,
    "place_type",
    "seat_km",
    "nearest_locality_km",
    "nearest_locality_category",
    "eligible_voters",
]
TYPES = ("seat", "town", "dispersed", "rural", "quilombola", "indigenous", "settlement")

LOCALITIES_TABLE = "BR_localidades_2022"
SEAT_CATEGORY = "Cidade"
EMPTY_SUBDIVISION = "Loteamento vazio"
# Legal Amazon box: (min lon, min lat, max lon, max lat).
LEGAL_AMAZON_BOX = (-74.0, -18.5, -43.0, 5.5)
CLUSTER_BUFFER_DEG = 0.001
SEAT_FALLBACK_KM = 2.0
DISPERSED_KM = 5.0
EARTH_RADIUS_KM = 6371.0088
CATEGORY_TYPES = {
    "Localidade Indígena": "indigenous",
    "Localidade Quilombola": "quilombola",
    "Agrovila do PA": "settlement",
}
TSE_MEMBER = "eleitorado_local_votacao_*.csv"
TSE_COLUMNS = (
    "aa_eleicao",
    "nr_turno",
    "cd_municipio",
    "nr_zona",
    "nr_local_votacao",
    "qt_eleitor_secao",
)


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def output_name(year: int) -> str:
    return f"polling_place_types_{year}.parquet"


# --- Readers


def _only_member(zf: zipfile.ZipFile, pattern: str) -> str:
    members = [n for n in zf.namelist() if fnmatch.fnmatch(n.lower(), pattern)]
    if len(members) != 1:
        raise BuildError(f"expected one {pattern} member in the zip, found {len(members)}")
    return members[0]


def extract_gpkg(zip_path: Path, tmp_dir: Path) -> Path:
    """Copy the single `.gpkg` member of the localities zip into `tmp_dir`."""
    with zipfile.ZipFile(zip_path) as zf:
        member = _only_member(zf, "*.gpkg")
        target = tmp_dir / Path(member).name
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def read_localities(gpkg_path: Path, codes: set[str]) -> pl.DataFrame:
    """Localities of the given municipalities: `cd_ibge`, `category`, `lat`, `long`.

    Rows without a usable coordinate are dropped (`check_locality_coverage`
    then catches a municipality that loses all of them).
    """
    query = (
        "SELECT CAST(CD_MUN AS TEXT), CT_LOCALIDADE, "
        "CAST(LAT_LOCALIDADE AS REAL), CAST(LONG_LOCALIDADE AS REAL) "
        f'FROM "{LOCALITIES_TABLE}"'
    )
    with closing(sqlite3.connect(gpkg_path)) as con:
        rows = [r for r in con.execute(query) if r[0] in codes and r[2] is not None]
    rows = [r for r in rows if r[3] is not None]
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "category": [r[1] for r in rows],
            "lat": [r[2] for r in rows],
            "long": [r[3] for r in rows],
        },
        schema={
            "cd_ibge": pl.String,
            "category": pl.String,
            "lat": pl.Float64,
            "long": pl.Float64,
        },
    )


def _shapefile_part(zf: zipfile.ZipFile, stem: str, suffix: str) -> bytes | None:
    found = [n for n in zf.namelist() if n.lower() == stem + suffix]
    if len(found) > 1:
        raise BuildError(f"more than one {suffix} member for {stem}")
    return zf.read(found[0]) if found else None


def read_urban_polygons(zip_path: Path) -> list[Any]:
    """Urbanized-area polygons that meet the Legal Amazon box, without empty subdivisions.

    The DBF encoding is the `.cpg` member when there is one, else UTF-8.
    """
    with zipfile.ZipFile(zip_path) as zf:
        shp_name = _only_member(zf, "*.shp")
        stem = shp_name[: -len(".shp")].lower()
        shp = zf.read(shp_name)
        shx = _shapefile_part(zf, stem, ".shx")
        dbf = _shapefile_part(zf, stem, ".dbf")
        cpg = _shapefile_part(zf, stem, ".cpg")
    if dbf is None:
        raise BuildError("the urbanized-areas zip has no .dbf member")
    encoding = cpg.decode("ascii", errors="replace").strip() if cpg else "utf-8"
    min_x, min_y, max_x, max_y = LEGAL_AMAZON_BOX
    polygons = []
    with shapefile.Reader(
        shp=io.BytesIO(shp),
        shx=io.BytesIO(shx) if shx else None,
        dbf=io.BytesIO(dbf),
        encoding=encoding or "utf-8",
    ) as reader:
        for item in reader.iterShapeRecords():
            geom = item.shape
            box = getattr(geom, "bbox", None)
            if box is None:
                continue
            if box[2] < min_x or box[0] > max_x or box[3] < min_y or box[1] > max_y:
                continue
            record = {k.lower(): v for k, v in item.record.as_dict().items()}
            if "tipo" not in record:
                raise BuildError("the urbanized-areas shapefile has no Tipo field")
            if str(record["tipo"]).strip() == EMPTY_SUBDIVISION:
                continue
            polygons.append(to_shapely(geom.__geo_interface__))
    return polygons


def eligible_voters(tse_zip: Path, year: int | None = None) -> pl.DataFrame:
    """Round-1 `QT_ELEITOR_SECAO` summed by polling place.

    Returns `sg_ue`, `nr_zona`, `nr_local_votacao` and `eligible_voters`. Rows of
    another election year are ignored when `year` is given. The count must be an
    integer: a bad value stops the build.
    """
    with zipfile.ZipFile(tse_zip) as zf:
        raw = zf.read(_only_member(zf, TSE_MEMBER)).decode("latin-1")
    df = pl.read_csv(io.BytesIO(raw.encode("utf-8")), separator=";", infer_schema=False)
    df = df.rename({c: c.strip().lower() for c in df.columns})
    missing = [c for c in TSE_COLUMNS if c not in df.columns]
    if missing:
        raise BuildError(f"the TSE file lacks columns {missing}")
    df = df.select(pl.col(c).str.strip_chars() for c in TSE_COLUMNS)
    df = df.filter(pl.col("nr_turno") == "1")
    if year is not None:
        df = df.filter(pl.col("aa_eleicao") == str(year))
    try:
        df = df.select(
            pl.col("cd_municipio").str.zfill(5).alias("sg_ue"),
            pl.col("nr_zona").cast(pl.Int32),
            pl.col("nr_local_votacao").cast(pl.Int32),
            pl.col("qt_eleitor_secao").cast(pl.Int64),
        )
    except pl.exceptions.PolarsError as err:
        raise BuildError(f"a TSE count or key is not an integer: {err}") from err
    return df.group_by("sg_ue", "nr_zona", "nr_local_votacao").agg(
        pl.col("qt_eleitor_secao").sum().alias("eligible_voters")
    )


# --- Clusters and classification


def urban_clusters(polygons: list[Any]) -> list[Any]:
    """Buffer each polygon by `CLUSTER_BUFFER_DEG`, union them and split the result."""
    if not polygons:
        return []
    merged = shapely.union_all(shapely.buffer(np.array(polygons, dtype=object), CLUSTER_BUFFER_DEG))
    return list(getattr(merged, "geoms", [merged]))


def haversine_km(lat1: Any, long1: Any, lat2: Any, long2: Any) -> Any:
    """Great-circle distance in km; arguments broadcast like numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (
        np.sin((p2 - p1) / 2) ** 2
        + np.cos(p1) * np.cos(p2) * np.sin(np.radians(long2 - long1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _containing(tree: STRtree, lat: np.ndarray, long: np.ndarray) -> dict[int, set[int]]:
    """For each point index, the clusters that contain it."""
    out: dict[int, set[int]] = {}
    if len(lat) == 0:
        return out
    hits = tree.query(shapely.points(long, lat), predicate="within")
    for point, cluster in zip(hits[0].tolist(), hits[1].tolist(), strict=True):
        out.setdefault(point, set()).add(cluster)
    return out


def classify(
    places: pl.DataFrame, localities: pl.DataFrame, clusters: list[Any]
) -> tuple[pl.DataFrame, list[str]]:
    """Type each place; also return the municipalities whose seat is in no cluster.

    `places` has `cd_ibge`, `lat` and `long` (null when unlocated). The result has
    the same rows in the same order, with `place_type`, `seat_km`,
    `nearest_locality_km` and `nearest_locality_category`. A place without
    coordinates gets nulls.
    """
    n = places.height
    codes = places["cd_ibge"].to_list()
    lat = places["lat"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
    long = places["long"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
    located = ~(np.isnan(lat) | np.isnan(long))
    tree = STRtree(clusters)

    seats = localities.filter(pl.col("category") == SEAT_CATEGORY)
    seat_lat, seat_long = seats["lat"].to_numpy(), seats["long"].to_numpy()
    seat_codes = seats["cd_ibge"].to_list()
    seat_clusters: dict[str, set[int]] = {}
    for i, found in _containing(tree, seat_lat, seat_long).items():
        seat_clusters.setdefault(seat_codes[i], set()).update(found)
    no_seat_cluster = sorted(set(seat_codes) - set(seat_clusters))

    place_index = np.flatnonzero(located)
    inside = _containing(tree, lat[place_index], long[place_index])

    seat_km: list[float | None] = [None] * n
    near_km: list[float | None] = [None] * n
    near_cat: list[str | None] = [None] * n
    by_code: dict[str, list[int]] = {}
    for i in place_index.tolist():
        by_code.setdefault(codes[i], []).append(i)
    loc_codes = np.array(localities["cd_ibge"].to_list(), dtype=object)
    loc_lat, loc_long = localities["lat"].to_numpy(), localities["long"].to_numpy()
    loc_cat = np.array(localities["category"].to_list(), dtype=object)
    seat_codes_arr = np.array(seat_codes, dtype=object)
    for code, rows in by_code.items():
        idx = np.array(rows)
        mine = loc_codes == code
        if mine.any():
            dist = haversine_km(
                lat[idx][:, None],
                long[idx][:, None],
                loc_lat[mine][None, :],
                loc_long[mine][None, :],
            )
            best = dist.argmin(axis=1)
            for k, i in enumerate(rows):
                near_km[i] = float(dist[k, best[k]])
                near_cat[i] = str(loc_cat[mine][best[k]])
        mine_seat = seat_codes_arr == code
        if mine_seat.any():
            dist = haversine_km(
                lat[idx][:, None],
                long[idx][:, None],
                seat_lat[mine_seat][None, :],
                seat_long[mine_seat][None, :],
            )
            for k, i in enumerate(rows):
                seat_km[i] = float(dist[k].min())

    fallback = set(no_seat_cluster)
    place_type: list[str | None] = [None] * n
    for pos, i in enumerate(place_index.tolist()):
        found = inside.get(pos, set())
        code = codes[i]
        if found & seat_clusters.get(code, set()) or (
            code in fallback and seat_km[i] is not None and seat_km[i] <= SEAT_FALLBACK_KM
        ):
            place_type[i] = "seat"
        elif found:
            place_type[i] = "town"
        elif near_km[i] is None or near_km[i] > DISPERSED_KM:
            place_type[i] = "dispersed"
        else:
            place_type[i] = CATEGORY_TYPES.get(near_cat[i] or "", "rural")

    out = places.with_columns(
        pl.Series("place_type", place_type, dtype=pl.String),
        pl.Series("seat_km", seat_km, dtype=pl.Float64),
        pl.Series("nearest_locality_km", near_km, dtype=pl.Float64),
        pl.Series("nearest_locality_category", near_cat, dtype=pl.String),
    )
    return out, no_seat_cluster


# --- Checks


def check_one_row_per_place(source: pl.DataFrame, out: pl.DataFrame) -> None:
    """The output has the key set of `polling_places`, each key once."""
    if out.select(KEY).is_duplicated().any():
        raise BuildError("a polling place appears more than once in the output")
    if out.height != source.height:
        raise BuildError(f"{out.height} output rows for {source.height} polling places")
    keys = source.select(KEY)
    if keys.join(out.select(KEY), on=KEY, how="anti").height:
        raise BuildError("a polling place is missing from the output")


def check_typed(out: pl.DataFrame) -> None:
    """Every row with coordinates has a `place_type`."""
    located = pl.col("lat").is_not_null() & pl.col("long").is_not_null()
    bad = out.filter(located & pl.col("place_type").is_null()).height
    if bad:
        raise BuildError(f"{bad} polling places with coordinates have no place_type")


def check_locality_coverage(codes: set[str], localities: pl.DataFrame) -> None:
    """Every municipality has at least one locality and one seat point."""
    have = set(localities["cd_ibge"].to_list())
    seats = set(localities.filter(pl.col("category") == SEAT_CATEGORY)["cd_ibge"].to_list())
    no_locality = sorted(codes - have)
    if no_locality:
        raise BuildError(f"{len(no_locality)} municipalities have no locality: {no_locality[:5]}")
    no_seat = sorted(codes - seats)
    if no_seat:
        raise BuildError(f"{len(no_seat)} municipalities have no seat point: {no_seat[:5]}")


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


def _note(year: int, table: pl.DataFrame, no_coordinates: int, no_seat_cluster: list[str]) -> str:
    rows = table.height
    parts = [f"{year}: rows={rows}", f"no_coordinates={no_coordinates}"]
    counts = table.group_by("place_type").len()
    count_of = dict(zip(counts["place_type"].to_list(), counts["len"].to_list(), strict=True))
    for name in TYPES:
        k = count_of.get(name, 0)
        parts.append(f"{name}={k} ({k / rows:.4f})" if rows else f"{name}={k}")
    parts.append(f"seat_in_no_cluster={len(no_seat_cluster)} [{'|'.join(no_seat_cluster)}]")
    return ", ".join(parts)


def build(
    store: Store,
    polling_places_manifest: dict[str, Any],
    localities_manifest: dict[str, Any],
    urban_manifest: dict[str, Any],
    tse_manifest: dict[str, Any],
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
    place_entries = {
        y: _file(polling_places_manifest, f"polling_places_{y}.parquet") for y in years
    }
    localities_entry = _file(localities_manifest, ".zip")
    urban_entry = _file(urban_manifest, ".zip")
    tse_entries = {
        y: _file(tse_manifest, f"eleitorado_local_votacao_{y}.zip")
        for y in years
        if y not in NO_TSE_YEARS
    }
    entries = [localities_entry, urban_entry, *place_entries.values(), *tse_entries.values()]

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
    codes = {c for df in sources.values() for c in df["cd_ibge"].to_list()}
    localities = read_localities(
        extract_gpkg(_fetch(store, localities_entry, tmp_dir), tmp_dir), codes
    )
    check_locality_coverage(codes, localities)
    clusters = urban_clusters(read_urban_polygons(_fetch(store, urban_entry, tmp_dir)))

    # Every year is built and checked locally first; nothing reaches the store
    # unless all of them pass, so a failed run leaves no partial output.
    local: list[tuple[int, Path]] = []
    notes: list[str] = []
    for y in sorted(years):
        source = sources[y]
        typed, no_seat_cluster = classify(source, localities, clusters)
        if y in tse_entries:
            voters = eligible_voters(_fetch(store, tse_entries[y], tmp_dir), y)
            typed = typed.join(
                voters, on=["sg_ue", "nr_zona", "nr_local_votacao"], how="left", validate="m:1"
            )
        else:
            typed = typed.with_columns(pl.lit(None, dtype=pl.Int64).alias("eligible_voters"))
        typed = typed.sort(KEY)
        check_one_row_per_place(source, typed)
        check_typed(typed)
        path = tmp_dir / output_name(y)
        typed.select(OUTPUT_COLUMNS).write_parquet(path)
        local.append((y, path))
        no_coordinates = typed.filter(pl.col("lat").is_null() | pl.col("long").is_null()).height
        notes.append(_note(y, typed, no_coordinates, no_seat_cluster))

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
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (polling_places_manifest, localities_manifest, urban_manifest, tse_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
