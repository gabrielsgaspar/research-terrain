"""Exposure of unrepresented 1 km cells to the close council races of their municipality.

Contract of the output: data/contracts/cell_displacement.md. Definition: decision 0005.

Per election year, for every cell that nobody votes on (`pop_2022` = 0) and that
`cell_exposure` does not reach, in a municipality with a close pair (margin at most
0.5%): `G_i`, the sum over the municipality's pairs of K(distance to the winner's
stronghold) minus K(distance to the loser's). The functions are those of
`terrain.strongholds`.
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

DATASET = "cell_displacement"
YEARS = (2008, 2012, 2016, 2020, 2024)
KERNELS = sh.DISPLACEMENT_KERNELS
BOUND_TOLERANCE = 1e-9
GRID_FILE = "grid_cells.parquet"
OUTPUT_COLUMNS = [
    "nome_1KM",
    "cd_ibge",
    "x_km",
    "y_km",
    "ano",
    "n_pairs",
    "n_pairs_located",
    *(f"g_{k}" for k in KERNELS),
]
RINGS = tuple(k for k in KERNELS if k.startswith("ring"))


def output_name(year: int) -> str:
    return f"cell_displacement_{year}.parquet"


# --- One year


def year_table(
    year: int,
    candidate_votes: pl.DataFrame,
    turnout: pl.DataFrame,
    places: pl.DataFrame,
    section_votes: Iterable[pl.DataFrame],
    cells: pl.DataFrame,
    reached: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """The year's output table and its counts.

    `cells` has `nome_1KM`, `cd_ibge`, `x_km`, `y_km`, `pop_2022`; `reached` has
    `cd_ibge`, `x_km`, `y_km` of the year's `cell_exposure`; `section_votes` yields one
    frame per state file. The counts cover the Legal Amazon (the municipalities of
    `cells`) only: the results tables hold all of Brazil.
    """
    main = sh.main_election(candidate_votes)
    cands = sh.candidacy_votes(candidate_votes, year, main)
    paired = sh.margins(sh.within_list_pairs(cands), sh.valid_votes(turnout, main))
    text_cells = cells.with_columns(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    legal = text_cells["cd_ibge"].unique().implode()
    pairs = sh.close_pairs(paired).filter(pl.col("cd_ibge").is_in(legal))

    place_votes = pl.concat([sh.place_candidate_votes(sv, main) for sv in section_votes])
    strong = sh.strongholds(place_votes)
    used, same, no_coordinates = sh.stronghold_pairs(pairs, strong, sh.locate_places(places))

    munis = set(pairs["cd_ibge"].to_list())
    unrep = sh.unrepresented(text_cells, reached, munis)
    g = sh.displacement(unrep, used).rename({f"G_{k}": f"g_{k}" for k in KERNELS})

    n_pairs = pairs.group_by("cd_ibge").len().select("cd_ibge", pl.col("len").alias("n_pairs"))
    n_located = (
        used.group_by("cd_ibge").len().select("cd_ibge", pl.col("len").alias("n_pairs_located"))
    )
    out = (
        g.join(text_cells.select("nome_1KM", *sh.CELL), on=sh.CELL, how="inner")
        .join(n_pairs, on="cd_ibge", how="left")
        .join(n_located, on="cd_ibge", how="left")
        .with_columns(
            pl.col("n_pairs").fill_null(0).cast(pl.Int64),
            pl.col("n_pairs_located").fill_null(0).cast(pl.Int64),
            pl.lit(year, dtype=pl.Int64).alias("ano"),
        )
        .select(OUTPUT_COLUMNS)
        .sort(["cd_ibge", "y_km", "x_km"])
    )
    counts = {
        "municipalities_with_pair": len(munis),
        "close_pairs": pairs.height,
        "pairs_located": used.height,
        "dropped_same_place": same,
        "dropped_no_coordinates": no_coordinates,
    }
    return out, counts


# --- Checks


def check_keys(table: pl.DataFrame, cells: pl.DataFrame, reached: pl.DataFrame) -> None:
    """Unique cells, empty ones from `grid_cells`, and none that `cell_exposure` reaches."""
    if table.select("nome_1KM", "ano").is_duplicated().any():
        raise BuildError("a (nome_1KM, ano) pair appears more than once")
    known = cells.filter(pl.col("pop_2022") == 0).select(
        "nome_1KM", pl.col("cd_ibge").cast(pl.Utf8)
    )
    unknown = table.join(known, on=["nome_1KM", "cd_ibge"], how="anti")
    if unknown.height:
        raise BuildError(
            f"{unknown.height} cells are not in grid_cells with the same cd_ibge and "
            f"pop_2022 = 0, such as {unknown['nome_1KM'][0]}"
        )
    keys = reached.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    ).unique()
    inside = table.join(keys, on=sh.CELL, how="semi")
    if inside.height:
        raise BuildError(
            f"{inside.height} cells are in cell_exposure, such as {inside['nome_1KM'][0]}"
        )


def check_bounds(table: pl.DataFrame) -> None:
    """Each located pair adds a term in [-1, 1], and a ring term is -1, 0 or 1."""
    for name in KERNELS:
        bad = table.filter(pl.col(f"g_{name}").abs() > pl.col("n_pairs_located") + BOUND_TOLERANCE)
        if bad.height:
            raise BuildError(f"g_{name}: {bad.height} cells have |G| above n_pairs_located")
    for name in RINGS:
        column = pl.col(f"g_{name}")
        bad = table.filter((column - column.round(0)).abs() > BOUND_TOLERANCE)
        if bad.height:
            raise BuildError(f"g_{name}: {bad.height} cells have a value that is not whole")


def check_counts(table: pl.DataFrame) -> None:
    """Located pairs are a subset of the pairs, and every row has a pair."""
    if table.filter(pl.col("n_pairs") < 1).height:
        raise BuildError("a row has n_pairs below 1")
    if table.filter(pl.col("n_pairs_located") > pl.col("n_pairs")).height:
        raise BuildError("a row has n_pairs_located above n_pairs")


def check_year(year: int, table: pl.DataFrame) -> None:
    """The year has at least one cell with a displacement exposure other than 0."""
    if table.filter(pl.col("g_exp10") != 0).height == 0:
        raise BuildError(f"{year}: no cell with g_exp10 other than 0")


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


def _note(year: int, counts: dict[str, int], table: pl.DataFrame) -> str:
    nonzero = ", ".join(f"g_{k}={_count(table, f'g_{k}')}" for k in KERNELS)
    return (
        f"{year}: municipalities_with_pair={counts['municipalities_with_pair']}, "
        f"close_pairs={counts['close_pairs']}, pairs_located={counts['pairs_located']}, "
        f"dropped_same_place={counts['dropped_same_place']}, "
        f"dropped_no_coordinates={counts['dropped_no_coordinates']}, "
        f"rows={table.height}, cells_nonzero: {nonzero}"
    )


def build(
    store: Store,
    grid_cells_manifest: dict[str, Any],
    cell_exposure_manifest: dict[str, Any],
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
    """Build `cell_displacement_<y>.parquet` into `<derived_root><hash>/`; return the manifest.

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
            "reached": _files(cell_exposure_manifest, rf"cell_exposure_{y}\.parquet$", one=True)[0],
            "sections": _files(
                section_votes_manifest, rf"section_votes_{y}_[A-Z]{{2}}\.parquet$", one=False
            ),
        }
    entries = [grid_entry]
    for found in per_year.values():
        entries += [
            found["cv"],
            found["turnout"],
            found["places"],
            found["reached"],
            *found["sections"],
        ]

    prefix = f"{derived_root}{input_hash(entries, years)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    cells = _read(
        store, grid_entry, tmp_dir, columns=["nome_1KM", "cd_ibge", "x_km", "y_km", "pop_2022"]
    ).with_columns(pl.col("cd_ibge").cast(pl.Utf8))

    # Every check runs on a year before it is written locally; nothing is uploaded
    # until all years have passed.
    notes: list[str] = []
    written: list[Path] = []
    for y in sorted(years):
        found = per_year[y]
        reached = _read(store, found["reached"], tmp_dir, columns=["cd_ibge", "x_km", "y_km"])
        table, counts = year_table(
            y,
            _read(store, found["cv"], tmp_dir),
            _read(store, found["turnout"], tmp_dir),
            _read(store, found["places"], tmp_dir),
            (_read(store, e, tmp_dir) for e in found["sections"]),
            cells,
            reached,
        )
        check_keys(table, cells, reached)
        check_bounds(table)
        check_counts(table)
        check_year(y, table)
        path = tmp_dir / output_name(y)
        table.write_parquet(path)
        written.append(path)
        notes.append(_note(y, counts, table))
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
                cell_exposure_manifest,
                polling_places_manifest,
                section_votes_manifest,
                tse_results_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
