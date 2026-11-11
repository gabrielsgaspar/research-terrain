"""Gold exposure per municipality and the real gold and soybean price series.

Contract of the output: data/contracts/gold_exposure.md. Idea 0007, campaign 0007 step s6;
decisions 0003 and 0011. Both tables are treatment-side data, so they are not split by half.

Geology: SGB mineral-occurrence points that name gold, assigned to the municipality polygon
that contains them. Titles: active ANM gold, garimpo and sand-and-gravel titles, whose
polygons are repaired and projected to the project's Albers km. Prices: the World Bank's
monthly gold and soybean prices, deflated with US CPI to 2024 dollars.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely
from shapely.strtree import STRtree

from terrain import grid
from terrain.builds import cell_enforcement as enforcement
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

__all__ = ["BuildError", "Limits", "build"]

DATASET = "gold_exposure"
EXPOSURE_FILE = "gold_exposure.parquet"
PRICES_FILE = "gold_prices.parquet"
ANM_FILE = "sigmine_active.parquet"
SGB_FILE = "sgb_ocorrencias.csv"
PRICE_XLSX = "CMO-Historical-Data-Monthly.xlsx"
CPI_FILE = "CPIAUCSL.csv"
BOUNDARIES_FILE = "BR_Municipios_2024.zip"
MUNICIPALITIES_FILE = "municipalities.parquet"
CNFP_FILE = tenure.SETTLEMENT_EDITION  # the 2025 edition, which holds the Indigenous lands

SHEET = "Monthly Prices"
HEADER_ROW = 5
GOLD_HEADER, SOY_HEADER = "Gold", "Soybeans"
BASE_YEAR = 2024
TOLERANCE = 1e-9

GOLD_SUBS = frozenset({"OURO", "MINÉRIO DE OURO", "OURO NATIVO"})
GARIMPO_FASE = frozenset({"LAVRA GARIMPEIRA", "REQUERIMENTO DE LAVRA GARIMPEIRA"})
SAND_SUBS = frozenset({"AREIA", "AREIA COMUM", "AREIA LAVADA", "CASCALHO", "SAIBRO"})
YEAR_RANGE = (1900, 2026)
PRE_YEAR = 2000

SGB_COLUMNS = ("substancias", "status_economico", "longitude", "latitude")
ANM_COLUMNS = ("subs", "fase", "ano", "uf", "geometry_wkb")
SHARE_COLUMNS = (
    "title_gold_pre2000_share",
    "title_garimpo_pre2000_share",
    "title_sand_pre2000_share",
    "indigenous_share",
    "geo_gold_indigenous_share",
)


@dataclass(frozen=True)
class Limits:
    """The volume checks that stop the build. Tests lower them; production keeps these."""

    min_municipalities: int = 5571
    min_sgb: int = 30000
    min_gold_occurrences: int = 4000
    min_anm: int = 250000
    min_gold_pre2000: int = 9000
    min_price_years: int = 60
    required_years: tuple[int, ...] = tuple(range(1985, 2026))
    base_year: int = BASE_YEAR


DEFAULT_LIMITS = Limits()


# Every module whose code decides what this build writes: this file, the Albers projection,
# and the two builds whose helpers it reuses (`read_polygons`; `_file`, `_fetch` and the
# edition reader).
CODE_MODULES = (
    Path(__file__),
    Path(enforcement.__file__),
    Path(tenure.__file__),
    Path(grid.__file__),
)


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(files: list[dict[str, Any]], code: list[str] | None = None) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, *sources)


# --- Value rules


def normalise(value: Any) -> str:
    """Strip, casefold, remove accents; None becomes the empty string."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def is_gold_occurrence(substancias: Any) -> bool:
    """True when a comma-separated item equals "Ouro" ("Ouro Preto" does not count)."""
    return any(normalise(item) == "ouro" for item in str(substancias or "").split(","))


def is_garimpo_status(status: Any) -> bool:
    return normalise(status) == "garimpo"


def title_flags(titles: pl.DataFrame) -> pl.DataFrame:
    """Booleans per active title: gold, garimpo, sand, a valid year, and pre-2000."""
    subs = titles["subs"].str.strip_chars()
    fase = titles["fase"].str.strip_chars()
    ano = titles["ano"]
    valid = ano.is_not_null() & (ano >= YEAR_RANGE[0]) & (ano <= YEAR_RANGE[1])
    gold = subs.is_in(sorted(GOLD_SUBS)).fill_null(False)
    return pl.DataFrame(
        {
            "gold": gold,
            "garimpo": gold & fase.is_in(sorted(GARIMPO_FASE)).fill_null(False),
            "sand": subs.is_in(sorted(SAND_SUBS)).fill_null(False),
            "dated": valid.fill_null(False),
            "pre2000": (valid & (ano < PRE_YEAR)).fill_null(False),
        }
    )


# --- Geometry


def polygonal(geometry: Any) -> Any | None:
    """The polygonal part of a geometry, or None when it has none."""
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    if geometry.geom_type == "GeometryCollection":
        parts = [
            p
            for p in shapely.get_parts(geometry)
            if p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty
        ]
        return shapely.union_all(parts) if parts else None
    return None


def repair(geometries: list[Any]) -> tuple[list[Any | None], int]:
    """Valid polygonal geometries in order (None where nothing polygonal is left), and the
    number that `shapely.make_valid` had to repair."""
    out: list[Any | None] = []
    repaired = 0
    for geometry in geometries:
        if geometry is not None and not geometry.is_empty and not shapely.is_valid(geometry):
            geometry = shapely.make_valid(geometry)
            repaired += 1
        out.append(polygonal(geometry))
    return out, repaired


def to_km(geometries: list[Any]) -> list[Any]:
    if not geometries:
        return []
    return list(grid.to_albers_km(np.array(geometries, dtype=object)))


def assign_points(
    lon: np.ndarray, lat: np.ndarray, polygons: list[Any], codes: list[str]
) -> tuple[np.ndarray, int]:
    """The code of the polygon that contains each point (None outside every polygon), and the
    number of points outside. A point on a boundary is contained by neither side and counts
    as outside; a point in two polygons goes to the smaller code."""
    owner = np.full(len(lon), None, dtype=object)
    if len(lon):
        tree = STRtree(np.array(polygons, dtype=object))
        point, polygon = tree.query(shapely.points(lon, lat), predicate="within")
        # Reverse order, so that for a point in two polygons the smaller index (code) wins.
        for p, q in sorted(zip(point.tolist(), polygon.tolist(), strict=True), reverse=True):
            owner[p] = codes[q]
    return owner, int(sum(1 for o in owner if o is None))


def count_intersecting(munis: list[Any], titles: list[Any]) -> np.ndarray:
    """For each municipality, the number of titles whose polygon intersects it."""
    if not titles:
        return np.zeros(len(munis), dtype=np.int64)
    tree = STRtree(np.array(munis, dtype=object))
    _, muni_index = tree.query(np.array(titles, dtype=object), predicate="intersects")
    return np.bincount(muni_index, minlength=len(munis)).astype(np.int64)


def union_share(munis: list[Any], polygons: list[Any]) -> np.ndarray:
    """Area of the union of `polygons` inside each municipality, over the municipality's area.

    Overlaps are counted once. All geometries are in Albers km.
    """
    share = np.zeros(len(munis), dtype=float)
    if not polygons:
        return share
    tree = STRtree(np.array(polygons, dtype=object))
    for i, muni in enumerate(munis):
        hits = tree.query(muni, predicate="intersects")
        if len(hits):
            union = shapely.union_all([polygons[j] for j in hits])
            share[i] = shapely.area(shapely.intersection(union, muni)) / shapely.area(muni)
    return share


# --- Inputs


def read_sgb(path: Path) -> tuple[pl.DataFrame, int]:
    """The SGB points with float `lon` and `lat`, and how many have no usable coordinates.

    Missing, non-numeric and non-finite coordinates become null.
    """
    frame = pl.read_csv(path, infer_schema=False, encoding="utf8")
    missing = [c for c in SGB_COLUMNS if c not in frame.columns]
    if missing:
        raise BuildError(f"{SGB_FILE} lacks the columns {missing}")

    def number(name: str) -> pl.Expr:
        value = pl.col(name).str.strip_chars().cast(pl.Float64, strict=False)
        return pl.when(value.is_finite()).then(value).otherwise(None)

    frame = frame.with_columns(number("longitude").alias("lon"), number("latitude").alias("lat"))
    unusable = frame.filter(pl.col("lon").is_null() | pl.col("lat").is_null()).height
    return frame, unusable


def read_anm(path: Path) -> pl.DataFrame:
    schema = pl.read_parquet_schema(path)
    missing = [c for c in ANM_COLUMNS if c not in schema]
    if missing:
        raise BuildError(f"{ANM_FILE} lacks the columns {missing}")
    return pl.read_parquet(path, columns=list(ANM_COLUMNS)).with_columns(
        pl.col("ano").cast(pl.Int64, strict=False)
    )


# --- The price workbook

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_MONTH = re.compile(r"^(\d{4})M(\d{2})$")
_CELL = re.compile(r"^([A-Z]+)(\d+)$")

Monthly = dict[tuple[int, int], float | None]


def _sheet_path(zf: zipfile.ZipFile, sheet: str) -> str:
    """The member that holds the sheet called `sheet`, through workbook.xml and its rels."""
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    wanted = [s for s in workbook.iter(f"{_MAIN}sheet") if s.get("name") == sheet]
    if len(wanted) != 1 or wanted[0].get(_RID) is None:
        raise BuildError(f"the workbook has no single sheet called {sheet!r}")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(f"{_REL}Relationship"):
        if rel.get("Id") == wanted[0].get(_RID):
            target = rel.get("Target") or ""
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    raise BuildError(f"the workbook has no relationship for the sheet {sheet!r}")


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{_MAIN}t")) for si in root.iter(f"{_MAIN}si")]


def _column(letters: str) -> int:
    n = 0
    for c in letters:
        n = n * 26 + ord(c) - ord("A") + 1
    return n


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{_MAIN}t"))
    value = cell.find(f"{_MAIN}v")
    text = (value.text or "") if value is not None else ""
    return strings[int(text)] if kind == "s" and text != "" else text


def _number(text: str) -> float | None:
    """A finite number, or None for "…", an empty cell or anything else."""
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_prices_xlsx(path: Path, sheet: str = SHEET) -> tuple[Monthly, Monthly]:
    """Monthly nominal gold and soybean prices, by (year, month); None when missing.

    The sheet is found by name. The columns are the ones whose header in row 5 is "Gold" and
    "Soybeans". Months are in column A as `YYYYMmm`.
    """
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        root = ET.fromstring(zf.read(_sheet_path(zf, sheet)))
    rows: dict[int, dict[int, str]] = {}
    for cell in root.iter(f"{_MAIN}c"):
        found = _CELL.match(cell.get("r") or "")
        if found:
            rows.setdefault(int(found.group(2)), {})[_column(found.group(1))] = _cell_text(
                cell, strings
            )
    header = {text.strip(): col for col, text in rows.get(HEADER_ROW, {}).items()}
    for name in (GOLD_HEADER, SOY_HEADER):
        if name not in header:
            raise BuildError(f"row {HEADER_ROW} of {sheet!r} has no column {name!r}")
    gold: Monthly = {}
    soy: Monthly = {}
    for row_number in sorted(rows):
        month = _MONTH.match(rows[row_number].get(1, "").strip())
        if row_number <= HEADER_ROW or month is None:
            continue
        key = (int(month.group(1)), int(month.group(2)))
        gold[key] = _number(rows[row_number].get(header[GOLD_HEADER], ""))
        soy[key] = _number(rows[row_number].get(header[SOY_HEADER], ""))
    if not gold:
        raise BuildError(f"{sheet!r} has no month rows")
    return gold, soy


def read_cpi(path: Path) -> Monthly:
    """Monthly CPI by (year, month); None for a missing value (FRED writes ".")."""
    out: Monthly = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                date, value = row["observation_date"], row["CPIAUCSL"]
            except KeyError as err:
                raise BuildError(f"{CPI_FILE} lacks the column {err}") from err
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
                raise BuildError(f"{CPI_FILE} has a date that is not YYYY-MM-DD: {date!r}")
            out[(int(date[:4]), int(date[5:7]))] = _number(value or "")
    return out


def fill_cpi_gap(cpi: Monthly) -> tuple[Monthly, list[tuple[int, int]]]:
    """Fill a year's single missing CPI month with the geometric mean of its neighbours.

    The BLS never published the October 2025 CPI (the 2025 US government shutdown), so
    FRED leaves that month empty. A month is filled only when it is the only one missing
    in its year and the months on each side (across a year end too) both have values;
    otherwise the year stays incomplete. Returns the filled series and the filled months.
    """
    out = dict(cpi)
    filled: list[tuple[int, int]] = []
    for year in sorted({y for y, _ in cpi}):
        missing = [m for m in range(1, 13) if cpi.get((year, m)) is None]
        if len(missing) != 1:
            continue
        month = missing[0]
        before = cpi.get((year, month - 1) if month > 1 else (year - 1, 12))
        after = cpi.get((year, month + 1) if month < 12 else (year + 1, 1))
        if before is None or after is None or before <= 0 or after <= 0:
            continue
        out[(year, month)] = math.sqrt(before * after)
        filled.append((year, month))
    return out, filled


def annual_prices(
    gold: Monthly,
    soy: Monthly,
    cpi: Monthly,
    base_year: int,
    cpi_filled: Iterable[tuple[int, int]] = (),
) -> pl.DataFrame:
    """One row per year in which gold, soybeans and CPI all have 12 months.

    Annual means of the monthly values; real prices are `price * cpi[base_year] / cpi`.
    `cpi_filled` lists the CPI months `fill_cpi_gap` filled; each year counts its own.
    """
    filled_by_year = Counter(year for year, _ in cpi_filled)

    def by_year(series: Monthly) -> dict[int, list[float]]:
        values: dict[int, list[float]] = defaultdict(list)
        for (year, month), value in series.items():
            if value is not None and 1 <= month <= 12:
                values[year].append(value)
        return values

    g, s, c = by_year(gold), by_year(soy), by_year(cpi)
    years = sorted(
        y for y in set(g) & set(s) & set(c) if min(len(g[y]), len(s[y]), len(c[y])) == 12
    )
    if base_year not in years:
        raise BuildError(f"{base_year} is not a complete year, so prices cannot be deflated")
    rows = []
    for y in years:
        rows.append(
            {
                "year": y,
                "gold_usd": sum(g[y]) / len(g[y]),
                "soy_usd": sum(s[y]) / len(s[y]),
                "cpi": sum(c[y]) / len(c[y]),
                "n_months_gold": len(g[y]),
                "n_months_soy": len(s[y]),
                "n_months_cpi": len(c[y]),
                "n_months_cpi_filled": filled_by_year[y],
            }
        )
    cpi_base = next(r["cpi"] for r in rows if r["year"] == base_year)
    for r in rows:
        if min(r["gold_usd"], r["soy_usd"], r["cpi"]) <= 0:
            raise BuildError(f"{r['year']}: a price or the CPI is not positive")
        r["gold_real"] = r["gold_usd"] * cpi_base / r["cpi"]
        r["soy_real"] = r["soy_usd"] * cpi_base / r["cpi"]
        r["ln_gold_real"] = math.log(r["gold_real"])
        r["ln_soy_real"] = math.log(r["soy_real"])
    schema = {
        "year": pl.Int64,
        "gold_usd": pl.Float64,
        "soy_usd": pl.Float64,
        "cpi": pl.Float64,
        "gold_real": pl.Float64,
        "soy_real": pl.Float64,
        "ln_gold_real": pl.Float64,
        "ln_soy_real": pl.Float64,
        "n_months_gold": pl.Int64,
        "n_months_soy": pl.Int64,
        "n_months_cpi": pl.Int64,
        "n_months_cpi_filled": pl.Int64,
    }
    return pl.DataFrame(rows, schema=schema).select(list(schema))


# --- Checks


def check_minimum(what: str, n: int, minimum: int) -> None:
    if n < minimum:
        raise BuildError(f"{what}: {n}, fewer than {minimum}")


def check_shares(table: pl.DataFrame) -> pl.DataFrame:
    """Stop when a share is outside [0, 1] by more than 1e-9; clip the rounding noise."""
    for name in SHARE_COLUMNS:
        values = table[name].drop_nulls()
        if len(values) and (values.min() < -TOLERANCE or values.max() > 1 + TOLERANCE):
            raise BuildError(f"{name} is outside [0, 1]")
    return table.with_columns(*(pl.col(n).clip(0.0, 1.0) for n in SHARE_COLUMNS))


def check_prices(prices: pl.DataFrame, limits: Limits) -> None:
    check_minimum("gold price years", prices.height, limits.min_price_years)
    absent = sorted(set(limits.required_years) - set(prices["year"].to_list()))
    if absent:
        raise BuildError(f"gold price years missing: {absent}")


# --- Build


def _polygons(store: Store, entry: dict[str, Any], tmp_dir: Path, codes: list[str]) -> list[Any]:
    """The municipality polygons (SIRGAS 2000 degrees) in the order of `codes`."""
    path = _fetch(store, entry, tmp_dir)
    work = tmp_dir / "unpacked_boundaries"
    work.mkdir(exist_ok=True)
    try:
        found = enforcement.read_polygons(tenure.extract_edition(path, work), frozenset(codes))
    except BuildError as err:
        raise BuildError("a municipality has no polygon in the boundaries") from err
    finally:
        shutil.rmtree(work, ignore_errors=True)
        path.unlink(missing_ok=True)
    repaired, _ = repair([found[c] for c in codes])
    if any(g is None for g in repaired):
        raise BuildError("a municipality polygon is empty")
    return repaired


def _counts_by_uf(table: pl.DataFrame, column: str) -> str:
    rows = table.filter(pl.col(column)).group_by("uf").len().sort("uf")
    return "/".join(f"{uf}={n}" for uf, n in rows.iter_rows())


def read_indigenous(shp_path: Path) -> list[Any]:
    """Every Indigenous-land polygon of a CNFP edition, with no regional limit.

    `tenure.read_cnfp` keeps only polygons that meet the Legal Amazon box, which would drop the
    Indigenous lands of the South and the Southeast. This table covers the whole country.
    """
    lands: list[Any] = []
    with shapefile.Reader(str(shp_path), encoding="utf-8", encodingErrors="replace") as reader:
        for item in reader.iterShapeRecords():
            geom = item.shape
            if geom.shapeType not in tenure.POLYGON_TYPES or not geom.points:
                continue
            record = {k.lower(): v for k, v in item.record.as_dict().items()}
            if tenure.is_indigenous(str(record.get("categoria") or "")):
                lands.append(to_shapely(geom.__geo_interface__))
    return lands


def read_indigenous_lands(store: Store, entry: dict[str, Any], tmp_dir: Path) -> list[Any]:
    """Download the CNFP 2025 edition, read its Indigenous lands and delete the files."""
    zip_path = _fetch(store, entry, tmp_dir)
    work = tmp_dir / ("unpacked_" + zip_path.stem)
    work.mkdir(exist_ok=True)
    try:
        return read_indigenous(tenure.extract_edition(zip_path, work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        zip_path.unlink(missing_ok=True)


def build(
    store: Store,
    anm_manifest: dict[str, Any],
    sgb_manifest: dict[str, Any],
    price_manifest: dict[str, Any],
    boundaries_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    cnfp_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    limits: Limits = DEFAULT_LIMITS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the two Parquet files into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status` is
    `created`. When the output path already has a manifest, nothing is read or written and
    the status is `unchanged`. Everything is built and checked locally before any upload.
    """
    anm_entry = _file(anm_manifest, ANM_FILE)
    sgb_entry = _file(sgb_manifest, SGB_FILE)
    xlsx_entry = _file(price_manifest, PRICE_XLSX)
    cpi_entry = _file(price_manifest, CPI_FILE)
    boundaries_entry = _file(boundaries_manifest, BOUNDARIES_FILE)
    municipalities_entry = _file(municipalities_manifest, MUNICIPALITIES_FILE)
    cnfp_entry = _file(cnfp_manifest, CNFP_FILE)
    entries = [
        anm_entry,
        sgb_entry,
        xlsx_entry,
        cpi_entry,
        boundaries_entry,
        municipalities_entry,
        cnfp_entry,
    ]
    prefix = f"{derived_root}{input_hash(entries)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    # Prices first: they are small and have their own checks.
    xlsx_path = _fetch(store, xlsx_entry, tmp_dir)
    cpi_path = _fetch(store, cpi_entry, tmp_dir)
    gold, soy = read_prices_xlsx(xlsx_path)
    cpi, cpi_filled = fill_cpi_gap(read_cpi(cpi_path))
    prices = annual_prices(gold, soy, cpi, limits.base_year, cpi_filled)
    check_prices(prices, limits)

    path = _fetch(store, municipalities_entry, tmp_dir)
    munis = pl.read_parquet(path, columns=["cd_ibge", "uf", "legal_amazon"]).sort("cd_ibge")
    path.unlink(missing_ok=True)
    check_minimum("municipalities", munis.height, limits.min_municipalities)
    if munis["cd_ibge"].is_duplicated().any():
        raise BuildError("a municipality appears twice in the municipalities table")
    codes = munis["cd_ibge"].to_list()
    degrees = _polygons(store, boundaries_entry, tmp_dir, codes)
    polygons = to_km(degrees)
    area = np.array([shapely.area(p) for p in polygons])
    if not (area > 0).all():
        raise BuildError("a municipality polygon has no area")
    centroids = shapely.centroid(np.array(polygons, dtype=object))

    # Geology.
    path = _fetch(store, sgb_entry, tmp_dir)
    points, unusable = read_sgb(path)
    path.unlink(missing_ok=True)
    check_minimum("SGB rows", points.height, limits.min_sgb)
    points = points.with_columns(
        pl.Series("gold", [is_gold_occurrence(v) for v in points["substancias"]], dtype=pl.Boolean),
        pl.Series(
            "garimpo", [is_garimpo_status(v) for v in points["status_economico"]], dtype=pl.Boolean
        ),
    )
    check_minimum("SGB gold occurrences", int(points["gold"].sum()), limits.min_gold_occurrences)
    dropped_gold = int((points["gold"] & (points["lon"].is_null() | points["lat"].is_null())).sum())
    located = points.filter(pl.col("lon").is_not_null() & pl.col("lat").is_not_null())
    owner, outside = assign_points(
        located["lon"].to_numpy(), located["lat"].to_numpy(), degrees, codes
    )
    unowned = np.array([o is None for o in owner], dtype=bool)
    outside_gold = int((unowned & located["gold"].to_numpy()).sum())
    located = located.with_columns(pl.Series("cd_ibge", owner.tolist(), dtype=pl.Utf8))
    gold_points = located.filter(pl.col("gold") & pl.col("cd_ibge").is_not_null())

    # Indigenous lands (CNFP 2025), in degrees for the points and in km for the shares.
    indigenous_deg, indigenous_repaired = repair(read_indigenous_lands(store, cnfp_entry, tmp_dir))
    indigenous_deg = [g for g in indigenous_deg if g is not None]
    if not indigenous_deg:
        raise BuildError("no Indigenous land polygons in the CNFP edition")
    inside = np.zeros(gold_points.height, dtype=bool)
    if gold_points.height:
        tree = STRtree(np.array(indigenous_deg, dtype=object))
        hit, _ = tree.query(
            shapely.points(gold_points["lon"].to_numpy(), gold_points["lat"].to_numpy()),
            predicate="within",
        )
        inside[np.unique(hit)] = True
    gold_points = gold_points.with_columns(pl.Series("indigenous", inside, dtype=pl.Boolean))

    by_muni = gold_points.group_by("cd_ibge").agg(
        pl.len().cast(pl.Int64).alias("geo_n_gold"),
        pl.col("garimpo").sum().cast(pl.Int64).alias("geo_n_gold_garimpo"),
        pl.col("indigenous").sum().cast(pl.Int64).alias("geo_n_gold_indigenous"),
    )

    # Titles.
    path = _fetch(store, anm_entry, tmp_dir)
    anm = read_anm(path)
    path.unlink(missing_ok=True)
    check_minimum("ANM rows", anm.height, limits.min_anm)
    flags = title_flags(anm)
    check_minimum(
        "gold titles with a year before 2000",
        int((flags["pre2000"] & flags["gold"]).sum()),
        limits.min_gold_pre2000,
    )
    wanted = flags["gold"] | flags["sand"]
    kept = anm.filter(wanted).select("geometry_wkb")
    kept_flags = flags.filter(wanted)
    no_geometry = int(kept["geometry_wkb"].is_null().sum())
    raw = [None if b is None else shapely.from_wkb(b) for b in kept["geometry_wkb"].to_list()]
    title_deg, title_repaired = repair(raw)
    del raw
    present = np.array([g is not None for g in title_deg], dtype=bool)
    title_km = np.empty(len(title_deg), dtype=object)
    title_km[present] = to_km([g for g in title_deg if g is not None])

    def select(*columns: str) -> list[Any]:
        mask = present.copy()
        for column in columns:
            mask &= kept_flags[column].to_numpy()
        return list(title_km[mask])

    exposure = munis.with_columns(
        pl.Series("area_km2", area, dtype=pl.Float64),
        pl.Series("centroid_x_km", shapely.get_x(centroids), dtype=pl.Float64),
        pl.Series("centroid_y_km", shapely.get_y(centroids), dtype=pl.Float64),
    )
    exposure = (
        exposure.join(by_muni, on="cd_ibge", how="left")
        .with_columns(
            pl.col("geo_n_gold", "geo_n_gold_garimpo", "geo_n_gold_indigenous")
            .fill_null(0)
            .cast(pl.Int64)
        )
        .with_columns(
            (pl.col("geo_n_gold") / pl.col("area_km2")).alias("geo_gold_per_km2"),
            (pl.col("geo_n_gold") >= 1).alias("geo_exposed"),
            pl.when(pl.col("geo_n_gold") > 0)
            .then(pl.col("geo_n_gold_indigenous") / pl.col("geo_n_gold"))
            .otherwise(None)
            .alias("geo_gold_indigenous_share"),
        )
    )
    counts = {
        "title_n_gold": count_intersecting(polygons, select("gold")),
        "title_n_gold_dated": count_intersecting(polygons, select("gold", "dated")),
        "title_n_gold_pre2000": count_intersecting(polygons, select("gold", "pre2000")),
        "title_n_garimpo_pre2000": count_intersecting(polygons, select("garimpo", "pre2000")),
    }
    shares = {
        "title_gold_pre2000_share": union_share(polygons, select("gold", "pre2000")),
        "title_garimpo_pre2000_share": union_share(polygons, select("garimpo", "pre2000")),
        "title_sand_pre2000_share": union_share(polygons, select("sand", "pre2000")),
        "indigenous_share": union_share(polygons, to_km(indigenous_deg)),
    }
    exposure = exposure.with_columns(
        *(pl.Series(k, v, dtype=pl.Int64) for k, v in counts.items()),
        *(pl.Series(k, v, dtype=pl.Float64) for k, v in shares.items()),
    ).with_columns((pl.col("title_n_gold_pre2000") >= 1).alias("title_exposed"))
    exposure = check_shares(exposure).select(
        "cd_ibge",
        "uf",
        "legal_amazon",
        "area_km2",
        "centroid_x_km",
        "centroid_y_km",
        "geo_n_gold",
        "geo_gold_per_km2",
        "geo_exposed",
        "geo_n_gold_garimpo",
        "geo_n_gold_indigenous",
        "geo_gold_indigenous_share",
        *counts,
        "title_gold_pre2000_share",
        "title_garimpo_pre2000_share",
        "title_sand_pre2000_share",
        "title_exposed",
        "indigenous_share",
    )

    notes = [
        f"municipalities={exposure.height}",
        f"geo_exposed by uf: {_counts_by_uf(exposure, 'geo_exposed')}",
        f"title_exposed by uf: {_counts_by_uf(exposure, 'title_exposed')}",
        f"sgb_rows={points.height}, sgb_gold_occurrences={int(points['gold'].sum())}",
        f"sgb_dropped_no_usable_coordinates={unusable} (gold: {dropped_gold})",
        f"sgb_outside_every_polygon={outside} (gold: {outside_gold})",
        f"anm_rows={anm.height}, gold_titles={int(flags['gold'].sum())}, "
        f"gold_and_sand_titles_without_geometry={no_geometry}",
        f"repaired_polygons: anm_gold_and_sand_titles={title_repaired}, "
        f"indigenous_lands={indigenous_repaired}",
        f"price_years={prices['year'].min()}-{prices['year'].max()} ({prices.height} years)",
        "cpi_months_filled="
        + (", ".join(f"{y}-{m:02d}" for y, m in cpi_filled) or "none")
        + " (geometric mean of the months on each side)",
    ]

    exposure_path, prices_path = tmp_dir / EXPOSURE_FILE, tmp_dir / PRICES_FILE
    exposure.sort("cd_ibge").write_parquet(exposure_path)
    prices.sort("year").write_parquet(prices_path)

    # Every check has passed: upload, then the manifest is the caller's last step.
    files = []
    for name, local in ((EXPOSURE_FILE, exposure_path), (PRICES_FILE, prices_path)):
        store.create(prefix + name, local)
        files.append(
            {"path": prefix + name, "sha256": sha256_file(local), "bytes": local.stat().st_size}
        )
    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (
                anm_manifest,
                sgb_manifest,
                price_manifest,
                boundaries_manifest,
                municipalities_manifest,
                cnfp_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
