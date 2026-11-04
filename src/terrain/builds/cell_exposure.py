"""Each 1 km cell's exposure to the close council races of its municipality.

Contract of the output: data/contracts/cell_exposure.md. Definition: decision 0004.

Per election year, over the close pairs (margin at most 0.5%) of a cell's municipality,
the winner-minus-loser kernel-weighted mean vote share at the municipality's polling
places within 10 km. The functions are those of `terrain.strongholds`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import polars as pl

from terrain import grid
from terrain import strongholds as sh
from terrain.builds.polling_place_tenure import BuildError
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "cell_exposure"
YEARS = (2008, 2012, 2016, 2020, 2024)
KERNELS = sh.KERNELS
BOUND_TOLERANCE = 1e-9
GRID_FILE = "grid_cells.parquet"
OUTPUT_COLUMNS = [
    "nome_1KM",
    "cd_ibge",
    "x_km",
    "y_km",
    "ano",
    "n_pairs",
    *(f"sum_k_{k}" for k in KERNELS),
    *(f"d_{k}" for k in KERNELS),
]


def output_name(year: int) -> str:
    return f"cell_exposure_{year}.parquet"


# --- One year


def sum_k(dist: pl.DataFrame, totals: pl.DataFrame, name: str) -> pl.DataFrame:
    """Σ K(d) over a municipality's places with votes, for the cells the kernel reaches.

    The same reach rule as `terrain.strongholds.exposure`.
    """
    near = (
        dist.join(totals.select(sh.PLACE_KEY).unique(), on=sh.PLACE_KEY, how="semi")
        .with_columns(sh.kernel(name, pl.col("d")).alias("k"))
        .filter(pl.col("k") > 0)
    )
    return near.group_by(sh.CELL).agg(pl.col("k").sum().alias(f"sum_k_{name}"))


def year_table(
    year: int,
    candidate_votes: pl.DataFrame,
    turnout: pl.DataFrame,
    places: pl.DataFrame,
    section_votes: Iterable[pl.DataFrame],
    cells: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The year's output table and its close pairs.

    `cells` has `nome_1KM`, `cd_ibge`, `x_km`, `y_km`; `section_votes` yields one frame
    per state file.
    """
    main = sh.main_election(candidate_votes)
    cands = sh.candidacy_votes(candidate_votes, year, main)
    paired = sh.margins(sh.within_list_pairs(cands), sh.valid_votes(turnout, main))
    pairs = sh.close_pairs(paired)

    place_votes = pl.concat([sh.place_candidate_votes(sv, main) for sv in section_votes])
    totals = sh.place_totals(place_votes)
    shares = sh.place_shares(place_votes)
    text_cells = cells.with_columns(pl.col("cd_ibge").cast(pl.Utf8))
    dist = sh.cell_place_distances(text_cells.select(sh.CELL), sh.locate_places(places))

    table: pl.DataFrame | None = None
    for name in KERNELS:
        d = (
            sh.exposure(dist, totals, shares, pairs, name, "share")
            .select(*sh.CELL, pl.col("D_i").alias(f"d_{name}"))
            .join(sum_k(dist, totals, name), on=sh.CELL, how="left")
        )
        # exp2 comes first and decides which cells are in the output.
        table = d if table is None else table.join(d, on=sh.CELL, how="left")
    assert table is not None
    n_pairs = pairs.group_by("cd_ibge").len().select("cd_ibge", pl.col("len").alias("n_pairs"))
    out = (
        table.join(text_cells.select("nome_1KM", *sh.CELL), on=sh.CELL, how="inner")
        .join(n_pairs, on="cd_ibge", how="left")
        .with_columns(
            pl.col("n_pairs").fill_null(0).cast(pl.Int64),
            pl.lit(year, dtype=pl.Int64).alias("ano"),
            *(pl.col(f"sum_k_{k}").fill_null(0.0) for k in KERNELS),
        )
        .select(OUTPUT_COLUMNS)
        .sort(["cd_ibge", "y_km", "x_km"])
    )
    return out, pairs


# --- Checks


def check_keys(table: pl.DataFrame, cells: pl.DataFrame) -> None:
    """(`nome_1KM`, `ano`) is unique, and every cell is in `grid_cells` with its municipality."""
    if table.select("nome_1KM", "ano").is_duplicated().any():
        raise BuildError("a (nome_1KM, ano) pair appears more than once")
    known = cells.select("nome_1KM", pl.col("cd_ibge").cast(pl.Utf8))
    unknown = table.join(known, on=["nome_1KM", "cd_ibge"], how="anti")
    if unknown.height:
        raise BuildError(
            f"{unknown.height} cells are not in grid_cells with the same cd_ibge, "
            f"such as {unknown['nome_1KM'][0]}"
        )


def check_bounds(table: pl.DataFrame) -> None:
    """Each pair adds a difference of two shares in [0, 1], so |D_i| <= n_pairs."""
    for name in KERNELS:
        bad = table.filter(pl.col(f"d_{name}").abs() > pl.col("n_pairs") + BOUND_TOLERANCE)
        if bad.height:
            raise BuildError(f"d_{name}: {bad.height} cells have |D| above n_pairs")


def check_nested(table: pl.DataFrame) -> None:
    """Smaller rings reach a subset: ring2 within ring5 within exp2."""
    for inner, outer in (("ring2", "ring5"), ("ring5", "exp2")):
        bad = table.filter(pl.col(f"d_{inner}").is_not_null() & pl.col(f"d_{outer}").is_null())
        if bad.height:
            raise BuildError(f"d_{inner} is set for {bad.height} cells where d_{outer} is null")


def check_year(year: int, pairs: pl.DataFrame, table: pl.DataFrame) -> None:
    """The year has at least one close pair and at least one exposed cell."""
    if pairs.height == 0:
        raise BuildError(f"{year}: no close pair")
    if table.filter(pl.col("d_exp2") != 0).height == 0:
        raise BuildError(f"{year}: no exposed cell")


# --- Build

# Every module whose code decides what this build writes. Its source is part of
# the output path: this file, the grid helpers and the definitions it uses.
CODE_MODULES = (Path(__file__), Path(grid.__file__), Path(sh.__file__))


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


def _files(manifest: dict[str, Any], pattern: str, *, one: bool) -> list[dict[str, Any]]:
    found = sorted(
        (f for f in manifest["files"] if re.search(pattern, f["path"])), key=lambda f: f["path"]
    )
    if not found or (one and len(found) != 1):
        raise BuildError(f"{manifest.get('dataset')}: expected a file matching {pattern}")
    return found


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def _read(store: Store, entry: dict[str, Any], tmp_dir: Path, **kwargs: Any) -> pl.DataFrame:
    path = _fetch(store, entry, tmp_dir)
    try:
        return pl.read_parquet(path, **kwargs)
    finally:
        path.unlink(missing_ok=True)


def _count(table: pl.DataFrame, column: str) -> int:
    return int(table.filter(pl.col(column).is_not_null() & (pl.col(column) != 0)).height)


def _note(year: int, pairs: pl.DataFrame, table: pl.DataFrame) -> str:
    nonzero = ", ".join(f"d_{k}={_count(table, f'd_{k}')}" for k in KERNELS)
    return (
        f"{year}: municipalities_with_pair={pairs['cd_ibge'].n_unique()}, "
        f"close_pairs={pairs.height}, rows={table.height}, cells_nonzero: {nonzero}"
    )


def build(
    store: Store,
    grid_cells_manifest: dict[str, Any],
    polling_places_manifest: dict[str, Any],
    section_votes_manifest: dict[str, Any],
    tse_results_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build `cell_exposure_<y>.parquet` into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    grid_entry = _files(grid_cells_manifest, r"grid_cells\.parquet$", one=True)[0]
    per_year: dict[int, dict[str, Any]] = {}
    for y in sorted(years):
        per_year[y] = {
            "cv": _files(tse_results_manifest, rf"candidate_votes_{y}\.parquet$", one=True)[0],
            "turnout": _files(tse_results_manifest, rf"turnout_{y}\.parquet$", one=True)[0],
            "places": _files(polling_places_manifest, rf"polling_places_{y}\.parquet$", one=True)[
                0
            ],
            "sections": _files(
                section_votes_manifest, rf"section_votes_{y}_[A-Z]{{2}}\.parquet$", one=False
            ),
        }
    entries = [grid_entry]
    for found in per_year.values():
        entries += [found["cv"], found["turnout"], found["places"], *found["sections"]]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    cells = _read(
        store, grid_entry, tmp_dir, columns=["nome_1KM", "cd_ibge", "x_km", "y_km"]
    ).with_columns(pl.col("cd_ibge").cast(pl.Utf8))

    # Every check runs on a year before it is written locally; nothing is uploaded
    # until all years have passed.
    notes: list[str] = []
    written: list[Path] = []
    for y in sorted(years):
        found = per_year[y]
        table, pairs = year_table(
            y,
            _read(store, found["cv"], tmp_dir),
            _read(store, found["turnout"], tmp_dir),
            _read(store, found["places"], tmp_dir),
            (_read(store, e, tmp_dir) for e in found["sections"]),
            cells,
        )
        check_year(y, pairs, table)
        check_keys(table, cells)
        check_bounds(table)
        check_nested(table)
        path = tmp_dir / output_name(y)
        table.write_parquet(path)
        written.append(path)
        notes.append(_note(y, pairs, table))
        del table

    files = []
    for path in written:
        store.create(prefix + path.name, path)
        files.append(
            {"path": prefix + path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
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
                grid_cells_manifest,
                polling_places_manifest,
                section_votes_manifest,
                tse_results_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
