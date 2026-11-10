"""IBAMA flora fines and embargoes per Legal Amazon 1 km cell and year, split by half.

Contract of the output: data/contracts/cell_enforcement.md. Idea 0005, decisions 0001
and 0003; the model is `terrain.builds.cell_outcomes`.

A record counts in a cell only when its point lies inside its own municipality's polygon
and in a `grid_cells` cell of that municipality. Rows of exploration-half municipalities go
to the derived folder; rows of the confirmation half go to a sealed folder that this build
only creates in and never reads. The notes and every message count exploration-half
records only: a pooled count minus the exploration count would reveal the other half.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapefile
import shapely
from shapely.geometry import shape as to_shapely

from terrain import grid, ibama
from terrain.builds import cell_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.cell_outcomes import _upload, parse_split_list
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file, extract_edition
from terrain.explore import EXPLORE_LIST
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "cell_enforcement"
YEARS = tuple(range(2000, 2026))
AUTOS_FILE = "ibama_autos.parquet"
EMBARGOS_FILE = "ibama_embargos.parquet"
BOUNDARIES_FILE = "BR_Municipios_2024.zip"
GRID_FILE = "grid_cells.parquet"

CANCELLED = frozenset({"sim", "s", "1", "true", "verdadeiro", "cancelado"})
NOT_CANCELLED = frozenset({"nao", "n", "0", "false", "falso", ""})
VALID = frozenset({"sim", "s", "1", "true"})
NOT_VALID = frozenset({"nao", "n", "0", "false"})
FLORA = "flora"

AUTOS_COLUMNS = (
    "fonte",
    "id_auto",
    "data_auto",
    "ano",
    "id_municipio",
    "latitude",
    "longitude",
    "tipo_infracao",
    "indicador_cancelado",
    "indicador_coordenada_valida",
)
EMBARGOS_COLUMNS = (
    "fonte",
    "id_embargo",
    "data_embargo",
    "ano",
    "id_municipio",
    "latitude",
    "longitude",
    "indicador_coordenada_valida",
)

# Every module whose code decides what this build writes. Its source is part of the
# output path: this file, the grid helpers, the IBAMA schemas, and the two builds whose
# helpers it reuses (`cell_outcomes`: the split list and the upload; `polling_place_tenure`:
# `_file`, `_fetch` and the edition reader).
CODE_MODULES = (
    Path(__file__),
    Path(grid.__file__),
    Path(ibama.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def cell_name(year: int) -> str:
    return f"cell_enforcement_{year}.parquet"


def muni_name(year: int) -> str:
    return f"muni_enforcement_{year}.parquet"


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


# --- Value rules


def normalise(value: Any) -> str | None:
    """Strip, casefold, remove accents; None stays None."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def classify_cancelled(values: pl.Series) -> pl.Series:
    """True for a cancelled fine. An unknown value stops the build, naming the value."""
    mapping: dict[Any, bool] = {}
    for raw in values.unique().to_list():
        key = normalise(raw)
        if key is None or key in NOT_CANCELLED:
            mapping[raw] = False
        elif key in CANCELLED:
            mapping[raw] = True
        else:
            raise BuildError(f"indicador_cancelado has a value that is not known: {raw!r}")
    return pl.Series("cancelled", [mapping[v] for v in values.to_list()], dtype=pl.Boolean)


def classify_flora(values: pl.Series) -> pl.Series:
    """True for a flora fine. If no value is flora, the build stops."""
    mapping = {raw: normalise(raw) == FLORA for raw in values.unique().to_list()}
    if not any(mapping.values()):
        raise BuildError("no tipo_infracao value is flora")
    return pl.Series("flora", [mapping[v] for v in values.to_list()], dtype=pl.Boolean)


def classify_valid(values: pl.Series) -> pl.Series:
    """True / False for a clear `indicador_coordenada_valida`, null for the rest."""
    mapping: dict[Any, bool | None] = {}
    for raw in values.unique().to_list():
        key = normalise(raw)
        mapping[raw] = True if key in VALID else False if key in NOT_VALID else None
    return pl.Series("claimed_valid", [mapping[v] for v in values.to_list()], dtype=pl.Boolean)


# --- Inputs


def read_input(path: Path, name: str, columns: tuple[str, ...]) -> pl.DataFrame:
    schema = pl.read_parquet_schema(path)
    missing = [c for c in columns if c not in schema or c not in ibama.SCHEMAS[name]]
    if missing:
        raise BuildError(f"{name} lacks the columns {missing}")
    return pl.read_parquet(path, columns=list(columns)).with_columns(
        pl.col("id_municipio").cast(pl.Utf8),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        pl.col("ano").cast(pl.Int64),
    )


def load_cells(path: Path) -> pl.DataFrame:
    cells = pl.read_parquet(path, columns=["nome_1KM", "cd_ibge"])
    bad = cells.filter(pl.col("cd_ibge").is_null() | ~pl.col("cd_ibge").str.contains(r"^\d{7}$"))
    if bad.height:
        raise BuildError(f"{bad.height} cells have a cd_ibge that is not 7 digits")
    if cells["nome_1KM"].is_duplicated().any():
        raise BuildError("a cell appears more than once in grid_cells")
    return cells


def read_polygons(shp_path: Path, legal: frozenset[str]) -> dict[str, Any]:
    """The polygon of each `grid_cells` municipality (SIRGAS 2000 degrees), by `CD_MUN`."""
    parts: dict[str, list[Any]] = {}
    with shapefile.Reader(str(shp_path), encoding="utf-8") as reader:
        for item in reader.iterShapeRecords():
            code = str(item.record.as_dict()["CD_MUN"])
            if code in legal and item.shape.points:
                parts.setdefault(code, []).append(to_shapely(item.shape.__geo_interface__))
    if len(parts) != len(legal):
        raise BuildError("a grid_cells municipality has no polygon in the boundaries")
    polygons = {c: g[0] if len(g) == 1 else shapely.union_all(g) for c, g in parts.items()}
    for polygon in polygons.values():
        shapely.prepare(polygon)
    return polygons


# --- Locating records

NO_COORDINATES, OUTSIDE, OTHER_CELL, LOCATED = (
    "no_coordinates",
    "outside_own_polygon",
    "other_cell_or_not_in_grid",
    "located",
)


def locate(frame: pl.DataFrame, polygons: dict[str, Any], cells: pl.DataFrame) -> pl.DataFrame:
    """`status` and `nome_1KM` (the cell, for located records) of each record, in order."""
    n = frame.height
    lat = frame["latitude"].to_numpy()
    lon = frame["longitude"].to_numpy()
    codes = frame["id_municipio"].to_numpy()
    status = np.full(n, NO_COORDINATES, dtype=object)
    finite = np.isfinite(lat) & np.isfinite(lon)
    inside = np.zeros(n, dtype=bool)
    for code in np.unique(codes[finite]):
        rows = np.flatnonzero(finite & (codes == code))
        inside[rows] = shapely.covers(polygons[code], shapely.points(lon[rows], lat[rows]))
    status[finite & ~inside] = OUTSIDE

    rows = np.flatnonzero(inside)
    status[rows] = OTHER_CELL
    names: list[str | None] = [None] * n
    if len(rows):
        km = grid.to_albers_km(shapely.points(lon[rows], lat[rows]))
        x = np.floor(shapely.get_x(km)).astype(np.int64)
        y = np.floor(shapely.get_y(km)).astype(np.int64)
        found = (
            pl.DataFrame(
                {
                    "row": rows,
                    "nome_1KM": [f"1KME{a}N{b}" for a, b in zip(x, y, strict=True)],
                    "owner": codes[rows],
                },
                schema={"row": pl.Int64, "nome_1KM": pl.Utf8, "owner": pl.Utf8},
            )
            .join(cells, on="nome_1KM", how="left")
            .filter(pl.col("cd_ibge") == pl.col("owner"))
        )
        for row, name in zip(found["row"].to_list(), found["nome_1KM"].to_list(), strict=True):
            status[row] = LOCATED
            names[row] = name
    return frame.with_columns(
        pl.Series("status", status.tolist(), dtype=pl.Utf8),
        pl.Series("nome_1KM", names, dtype=pl.Utf8),
    )


def prepare(
    frame: pl.DataFrame,
    date_col: str,
    *,
    fines: bool,
    legal: frozenset[str],
    explore: frozenset[str],
    years: tuple[int, ...],
    polygons: dict[str, Any],
    cells: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Records of rules 1-4 with their location (rule 5) and the counts of the notes.

    The counts hold exploration-half records, except `not_legal_amazon`, which belongs to
    neither half.
    """
    if fines:
        frame = frame.with_columns(
            classify_cancelled(frame["indicador_cancelado"]),
            classify_flora(frame["tipo_infracao"]),
        )
    frame = frame.with_columns(
        pl.coalesce(pl.col(date_col).dt.year().cast(pl.Int64), pl.col("ano")).alias("year"),
        classify_valid(frame["indicador_coordenada_valida"]),
        pl.col("id_municipio").is_in(sorted(legal)).alias("legal"),
        pl.col("id_municipio").is_in(sorted(explore)).alias("explore"),
    )
    stats = {"not_legal_amazon": int((~frame["legal"]).sum())}
    frame = frame.filter(pl.col("legal"))
    in_explore = frame.filter(pl.col("explore"))
    stats["no_date_no_year"] = int(in_explore["year"].is_null().sum())
    dated = in_explore.filter(pl.col("year").is_not_null())
    stats["outside_years"] = int((~dated["year"].is_in(list(years))).sum())
    frame = frame.filter(pl.col("year").is_in(list(years)))
    if fines:
        frame = frame.filter(~pl.col("cancelled") & pl.col("flora"))
    frame = locate(frame, polygons, cells)
    return frame, stats


# --- Counts


def count_by(frame: pl.DataFrame, keys: list[str], name: str) -> pl.DataFrame:
    return frame.group_by(keys).agg(pl.len().cast(pl.Int64).alias(name))


def cell_counts(fines: pl.DataFrame, embargoes: pl.DataFrame) -> pl.DataFrame:
    """One row per cell and year with a located action; the other count is 0."""
    keys = ["nome_1KM", "id_municipio", "year"]
    a = count_by(fines.filter(pl.col("status") == LOCATED), keys, "n_fines_flora")
    b = count_by(embargoes.filter(pl.col("status") == LOCATED), keys, "n_embargoes")
    return (
        a.join(b, on=keys, how="full", coalesce=True)
        .with_columns(pl.col("n_fines_flora").fill_null(0), pl.col("n_embargoes").fill_null(0))
        .rename({"id_municipio": "cd_ibge", "year": "ano"})
        .select("nome_1KM", "cd_ibge", "ano", "n_fines_flora", "n_embargoes")
    )


def muni_counts(
    munis: list[str], years: tuple[int, ...], fines: pl.DataFrame, embargoes: pl.DataFrame
) -> pl.DataFrame:
    """Every municipality and year, with the counts of all and of located records."""
    keys = ["id_municipio", "year"]
    table = pl.DataFrame({"id_municipio": munis}, schema={"id_municipio": pl.Utf8}).join(
        pl.DataFrame({"year": list(years)}, schema={"year": pl.Int64}), how="cross"
    )
    for source, name in ((fines, "n_fines_flora"), (embargoes, "n_embargoes")):
        everything = count_by(source, keys, f"{name}_all")
        located = count_by(source.filter(pl.col("status") == LOCATED), keys, f"{name}_located")
        table = table.join(everything, on=keys, how="left").join(located, on=keys, how="left")
    columns = [
        "n_fines_flora_all",
        "n_fines_flora_located",
        "n_embargoes_all",
        "n_embargoes_located",
    ]
    return (
        table.with_columns([pl.col(c).fill_null(0) for c in columns])
        .rename({"id_municipio": "cd_ibge", "year": "ano"})
        .select("cd_ibge", "ano", *columns)
    )


def check_outputs(cell: pl.DataFrame, muni: pl.DataFrame, munis: list[str], year: int) -> None:
    """Checks on one year and half, before anything is uploaded."""
    if muni.height != len(munis) or set(muni["cd_ibge"]) != set(munis):
        raise BuildError(f"{year}: the municipality table does not hold every municipality")
    if not cell.is_empty() and not set(cell["cd_ibge"]) <= set(munis):
        raise BuildError(f"{year}: a cell row is outside its half")
    if cell.select(pl.struct("nome_1KM", "ano").is_duplicated().any()).item():
        raise BuildError(f"{year}: a cell appears twice")
    for frame in (cell, muni):
        if set(frame["ano"]) - {year}:
            raise BuildError(f"{year}: a row has another year")
    for kind in ("fines_flora", "embargoes"):
        if muni.filter(pl.col(f"n_{kind}_located") > pl.col(f"n_{kind}_all")).height:
            raise BuildError(f"{year}: located records exceed all records")
        total = int(cell[f"n_{kind}"].sum()) if cell.height else 0
        if total != int(muni[f"n_{kind}_located"].sum()):
            raise BuildError(f"{year}: cell counts and municipality counts differ")


# --- Notes


def source_note(name: str, frame: pl.DataFrame) -> str:
    values = sorted({"null" if v is None else str(v) for v in frame["fonte"].unique().to_list()})
    return f"fonte {name}={'/'.join(values)}"


def reason_notes(
    name: str, located: pl.DataFrame, stats: dict[str, int], years: tuple[int, ...]
) -> list[str]:
    """Exploration-half drops by reason and year; `not_legal_amazon` belongs to no half."""
    notes = [
        f"{name}: not_legal_amazon={stats['not_legal_amazon']}, "
        f"no_date_no_year={stats['no_date_no_year']}, outside_{years[0]}_{years[-1]}="
        f"{stats['outside_years']}"
    ]
    explore = located.filter(pl.col("explore"))
    for y in years:
        counts = explore.filter(pl.col("year") == y)["status"].value_counts()
        by = dict(zip(counts["status"].to_list(), counts["count"].to_list(), strict=True))
        notes.append(
            f"{name} {y}: no_coordinates={by.get(NO_COORDINATES, 0)}, "
            f"outside_own_polygon={by.get(OUTSIDE, 0)}, "
            f"cell_in_another_municipality_or_not_in_grid={by.get(OTHER_CELL, 0)}"
        )
    return notes


def agreement_note(sources: list[pl.DataFrame], raw_fonte: list[pl.Series]) -> str | None:
    """How often our location check agrees with `indicador_coordenada_valida`.

    Exploration-half records with finite coordinates, from the inputs whose `fonte` is
    `basedosdados`. None when no input comes from there.
    """
    if not any(bool((f == "basedosdados").any()) for f in raw_fonte):
        return None
    table = pl.concat(
        [
            s.filter(pl.col("explore") & (pl.col("fonte") == "basedosdados"))
            .filter(pl.col("status") != NO_COORDINATES)
            .select("status", "claimed_valid")
            for s in sources
        ]
    )
    ours = table["status"] == LOCATED
    comparable = table["claimed_valid"].is_not_null()
    agree = int((comparable & (ours == table["claimed_valid"])).sum())
    disagree = int((comparable & (ours != table["claimed_valid"])).sum())
    other = int((~comparable).sum())
    total = table.height

    def share(n: int) -> str:
        return f"{n / total:.4f}" if total else "n/a"

    return (
        "agreement with indicador_coordenada_valida (basedosdados, exploration half, records "
        f"with coordinates): agree={share(agree)} ({agree}), disagree={share(disagree)} "
        f"({disagree}), not_comparable={share(other)} ({other})"
    )


# --- Build


def build(
    store: Store,
    autos_manifest: dict[str, Any],
    embargos_manifest: dict[str, Any],
    boundaries_manifest: dict[str, Any],
    grid_manifest: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-year, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.
    write_manifest`) when `status` is `created`. The build never lists, reads or
    checks the sealed folder: a create-only upload fails if an object is there.
    """
    autos_entry = _file(autos_manifest, AUTOS_FILE)
    embargos_entry = _file(embargos_manifest, EMBARGOS_FILE)
    boundaries_entry = _file(boundaries_manifest, BOUNDARIES_FILE)
    grid_entry = _file(grid_manifest, GRID_FILE)
    split_bytes = store.read_bytes(EXPLORE_LIST)
    split_sha = hashlib.sha256(split_bytes).hexdigest()
    explore = parse_split_list(split_bytes)

    entries = [autos_entry, embargos_entry, boundaries_entry, grid_entry]
    hashed = input_hash(entries, split_sha, years)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    path = _fetch(store, grid_entry, tmp_dir)
    try:
        cells = load_cells(path)
    finally:
        path.unlink(missing_ok=True)
    legal = frozenset(cells["cd_ibge"].unique().to_list())

    path = _fetch(store, boundaries_entry, tmp_dir)
    work = tmp_dir / "unpacked_boundaries"
    work.mkdir(exist_ok=True)
    try:
        polygons = read_polygons(extract_edition(path, work), legal)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        path.unlink(missing_ok=True)

    raw: dict[str, pl.DataFrame] = {}
    for name, entry, columns in (
        ("ibama_autos", autos_entry, AUTOS_COLUMNS),
        ("ibama_embargos", embargos_entry, EMBARGOS_COLUMNS),
    ):
        path = _fetch(store, entry, tmp_dir)
        try:
            raw[name] = read_input(path, name, columns)
        finally:
            path.unlink(missing_ok=True)

    common = {
        "legal": legal,
        "explore": explore,
        "years": years,
        "polygons": polygons,
        "cells": cells,
    }
    fines, fine_stats = prepare(raw["ibama_autos"], "data_auto", fines=True, **common)
    embargoes, embargo_stats = prepare(raw["ibama_embargos"], "data_embargo", fines=False, **common)

    notes = [source_note(n, raw[n]) for n in ("ibama_autos", "ibama_embargos")]
    notes += reason_notes("ibama_autos", fines, fine_stats, years)
    notes += reason_notes("ibama_embargos", embargoes, embargo_stats, years)
    agreement = agreement_note(
        [fines, embargoes], [raw["ibama_autos"]["fonte"], raw["ibama_embargos"]["fonte"]]
    )
    if agreement is not None:
        notes.append(agreement)

    all_munis = sorted(legal)
    halves = {
        True: [m for m in all_munis if m in explore],
        False: [m for m in all_munis if m not in explore],
    }
    cell_all = cell_counts(fines, embargoes)
    muni_all = muni_counts(all_munis, years, fines, embargoes)
    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per year and table
    for y in years:
        pairs = (
            (cell_name(y), cell_all.filter(pl.col("ano") == y).sort("cd_ibge", "nome_1KM")),
            (muni_name(y), muni_all.filter(pl.col("ano") == y).sort("cd_ibge")),
        )
        by_half: dict[bool, dict[str, pl.DataFrame]] = {True: {}, False: {}}
        for name, table in pairs:
            for is_explore in (True, False):
                part = table.filter(pl.col("cd_ibge").is_in(halves[is_explore]))
                by_half[is_explore][name] = part
        for is_explore in (True, False):
            tables = by_half[is_explore]
            check_outputs(tables[cell_name(y)], tables[muni_name(y)], halves[is_explore], y)
        for name, _ in pairs:
            sealed_file, derived_file = sealed_dir / name, derived_dir / name
            by_half[False][name].write_parquet(sealed_file)
            by_half[True][name].write_parquet(derived_file)
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
            for m in (autos_manifest, embargos_manifest, boundaries_manifest, grid_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
