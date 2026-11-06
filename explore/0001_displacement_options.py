"""Displacement-exposure options for decision 0005 (idea 0001), exploration half.

Per election year, four ways to measure how exposed a cell that nobody votes on is
to the close council races of its municipality: `G_i` = sum over close pairs of
K(d(i, p_w)) - K(d(i, p_l)), where `p_w` and `p_l` are the stronghold polling places
of the elected and the other candidate. Variants: `ring10_20`, `ring20_50`, `exp10`
and `nearest`. Cells are the unrepresented ones: `pop_2022` = 0 and missing from the
year's `cell_exposure` (more than 10 km from every polling place), in municipalities
with a close pair. Reports reach, quantiles of `G`, land tenure and agreement. No
outcome data; no effects.

Close pairs and strongholds come from `terrain.strongholds`, which holds the one
definition; the census script `0001_feasibility_census.py` is loaded for its paths.
Dropped pairs are counted: `dropped_same_place` when both candidates have the same
stronghold place, `dropped_no_coordinates` when either candidate has no stronghold
(no place with at least 50 votes) or a stronghold without coordinates.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import tempfile
from collections.abc import Collection
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (  # noqa: F401  (re-exported: tests read these names)
    CELL,
    TOLERANCE,
    candidacy_votes,
    close_pairs,
    locate_places,
    main_election,
    margins,
    place_candidate_votes,
    strongholds,
    valid_votes,
    within_list_pairs,
)

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "feasibility_census", _REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

YEARS = census.YEARS
VARIANTS = ("ring10_20", "ring20_50", "exp10", "nearest")
QUANTILES = (0.01, 0.10, 0.50, 0.90, 0.99)
LAYERS = ("indigenous", "settlement", "undesignated")
GRID_COLUMNS = ["cd_ibge", "x_km", "y_km", "pop_2022"]
OUTER_KM = 50.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def _quantiles(values: pl.Series) -> dict[str, float | None] | None:
    if values.len() == 0:
        return None
    return {f"{q * 100:g}%": _num(values.quantile(q, interpolation="linear")) for q in QUANTILES}


def stronghold_pairs(
    pairs: pl.DataFrame, strong: pl.DataFrame, located: pl.DataFrame
) -> tuple[pl.DataFrame, int, int]:
    """Attach `xw`, `yw`, `xl`, `yl` (Albers km) of each pair's strongholds.

    Returns (pairs used, `dropped_same_place`, `dropped_no_coordinates`). A pair whose
    two candidates share a stronghold place is dropped as same place. Any other pair
    where a candidate has no stronghold (no place with enough votes) or a stronghold
    without coordinates is dropped as no coordinates.
    """
    cand = strong.select(
        "cd_eleicao",
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8).alias("cand"),
        pl.col("cd_ibge").cast(pl.Utf8).alias("cd_place"),
        pl.col("nr_zona").cast(pl.Int64).alias("zona"),
        pl.col("nr_local_votacao").cast(pl.Int64).alias("local"),
    )
    where = located.select(
        pl.col("cd_ibge").alias("cd_place"),
        pl.col("sg_ue"),
        pl.col("nr_zona").alias("zona"),
        pl.col("nr_local_votacao").alias("local"),
        "x_km",
        "y_km",
    )
    out = pairs
    for side in ("w", "l"):
        side_place = cand.select(
            "cd_eleicao",
            "sg_ue",
            pl.col("cand").alias(side),
            *(pl.col(c).alias(f"{c}_{side}") for c in ("cd_place", "zona", "local")),
        )
        side_where = where.select(
            "sg_ue",
            *(pl.col(c).alias(f"{c}_{side}") for c in ("cd_place", "zona", "local")),
            pl.col("x_km").alias(f"x{side}"),
            pl.col("y_km").alias(f"y{side}"),
        )
        out = out.join(side_place, on=["cd_eleicao", "sg_ue", side], how="left").join(
            side_where,
            on=["sg_ue", f"cd_place_{side}", f"zona_{side}", f"local_{side}"],
            how="left",
        )
    both = pl.col("local_w").is_not_null() & pl.col("local_l").is_not_null()
    same = (
        both
        & (pl.col("cd_place_w") == pl.col("cd_place_l"))
        & (pl.col("zona_w") == pl.col("zona_l"))
        & (pl.col("local_w") == pl.col("local_l"))
    ).fill_null(False)
    located_both = pl.col("xw").is_not_null() & pl.col("xl").is_not_null()
    used = out.filter(~same & located_both).select(
        "cd_ibge", "sg_ue", "cd_eleicao", "w", "l", "xw", "yw", "xl", "yl"
    )
    return used, out.filter(same).height, out.filter(~same & ~located_both).height


def unrepresented(
    cells: pl.DataFrame, exposure_year: pl.DataFrame, muni_with_pair: Collection[str]
) -> pl.DataFrame:
    """Cells with `pop_2022` = 0 that `exposure_year` does not reach, where a pair exists."""
    reached = exposure_year.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    ).unique()
    return (
        cells.with_columns(
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("x_km").cast(pl.Int64),
            pl.col("y_km").cast(pl.Int64),
        )
        .filter((pl.col("pop_2022") == 0) & pl.col("cd_ibge").is_in(list(muni_with_pair)))
        .join(reached, on=CELL, how="anti")
    )


def kernel_g(name: str, d_w: np.ndarray, d_l: np.ndarray) -> np.ndarray:
    """One pair's term of `G_i` for each cell, from distances (km) to `p_w` and `p_l`.

    `ring10_20`: 1 for 10 < d <= 20 km; `ring20_50`: 1 for 20 < d <= 50; `exp10`:
    exp(-d / 10) for d <= 50. Each is K(d_w) - K(d_l). `nearest` is +1 when the cell is
    nearer `p_w` and within 50 km of it, -1 for the reverse, and 0 when it is equally
    far (within `TOLERANCE`) from both, so that swapping the pair negates the term.
    Boundaries use `TOLERANCE`: a distance of 10 + 1e-12 counts as 10.
    """
    d_w = np.asarray(d_w, dtype=float)
    d_l = np.asarray(d_l, dtype=float)

    def ring(d: np.ndarray, low: float, high: float) -> np.ndarray:
        return ((d > low + TOLERANCE) & (d <= high + TOLERANCE)).astype(float)

    def expo(d: np.ndarray) -> np.ndarray:
        return np.where(d <= OUTER_KM + TOLERANCE, np.exp(-d / 10.0), 0.0)

    if name == "ring10_20":
        return ring(d_w, 10.0, 20.0) - ring(d_l, 10.0, 20.0)
    if name == "ring20_50":
        return ring(d_w, 20.0, 50.0) - ring(d_l, 20.0, 50.0)
    if name == "exp10":
        return expo(d_w) - expo(d_l)
    if name == "nearest":
        win = (d_w < d_l - TOLERANCE) & (d_w <= OUTER_KM + TOLERANCE)
        lose = (d_l < d_w - TOLERANCE) & (d_l <= OUTER_KM + TOLERANCE)
        return win.astype(float) - lose.astype(float)
    raise ValueError(f"unknown variant {name}")


def displacement(cells: pl.DataFrame, used_pairs: pl.DataFrame) -> pl.DataFrame:
    """`G_<variant>` for each cell: CELL columns plus one column per variant.

    Distances run from the cell centre (corner + 0.5 km) to the strongholds of pairs
    of the cell's own municipality. A municipality without a used pair gets 0.
    """
    cells = cells.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    cx = cells["x_km"].to_numpy().astype(float) + 0.5
    cy = cells["y_km"].to_numpy().astype(float) + 0.5
    muni = cells["cd_ibge"].to_numpy()
    totals = {v: np.zeros(cells.height) for v in VARIANTS}
    pair_muni = used_pairs["cd_ibge"].cast(pl.Utf8).to_numpy()
    rows = used_pairs.select("xw", "yw", "xl", "yl").to_numpy()
    for code in np.unique(pair_muni):
        index = np.flatnonzero(muni == code)
        if index.size == 0:
            continue
        for xw, yw, xl, yl in rows[pair_muni == code]:
            d_w = np.hypot(cx[index] - xw, cy[index] - yw)
            d_l = np.hypot(cx[index] - xl, cy[index] - yl)
            for v in VARIANTS:
                totals[v][index] += kernel_g(v, d_w, d_l)
    return cells.with_columns(*(pl.Series(f"G_{v}", totals[v]) for v in VARIANTS))


def _correlation(frame: pl.DataFrame, other: str) -> dict[str, Any]:
    both = frame.filter((pl.col("G_exp10") != 0) & (pl.col(f"G_{other}") != 0))
    if both.height < 2:
        return {"cells": both.height, "pearson": None}
    value = both.select(pl.corr("G_exp10", f"G_{other}")).item()
    return {"cells": both.height, "pearson": _num(value)}


def report(
    unrep: pl.DataFrame,
    g: pl.DataFrame,
    counts: dict[str, int],
    year: int,
) -> dict[str, Any]:
    """Items 1-5 of the issue for one year.

    `unrep` are the unrepresented cells (CELL, `share_<layer>_<year>`), `g` comes from
    `displacement`, `counts` holds `pairs_used`, `dropped_same_place`,
    `dropped_no_coordinates`, `municipalities_with_pair` and `cells_in_municipalities`.
    """
    layer_columns = {layer: f"share_{layer}_{year}" for layer in LAYERS}
    frame = g.join(unrep.select(*CELL, *layer_columns.values()), on=CELL, how="left")
    total = counts["cells_in_municipalities"]
    out: dict[str, Any] = {
        **counts,
        "unrepresented_cells": unrep.height,
        "unrepresented_share_of_cells": unrep.height / total if total else None,
    }
    variants: dict[str, Any] = {}
    for v in VARIANTS:
        col = pl.col(f"G_{v}")
        nonzero = frame.filter(col != 0)
        tenure = {}
        for layer, column in layer_columns.items():
            n = nonzero.filter(pl.col(column) > 0).height
            tenure[layer] = {"cells": n, "share": n / nonzero.height if nonzero.height else None}
        variants[v] = {
            "cells_nonzero": nonzero.height,
            "quantiles_G": _quantiles(nonzero[f"G_{v}"]),
            "median_abs_G": _num(nonzero[f"G_{v}"].abs().median()) if nonzero.height else None,
            "tenure": tenure,
        }
    out["variants"] = variants
    out["agreement"] = {f"exp10 vs {v}": _correlation(frame, v) for v in VARIANTS if v != "exp10"}
    return out


def _year(
    store: GCSStore, tmp: Path, half: frozenset[str], year: int, grid: pl.DataFrame
) -> dict[str, Any]:
    def read(manifest: str, pattern: str, columns: list[str] | None = None) -> pl.DataFrame:
        remote = census._paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = restrict(pl.read_parquet(local, columns=columns), half)
        local.unlink()
        return frame

    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    places = read("polling_places", rf"polling_places_{year}\.parquet$")
    reached = read("cell_exposure", rf"cell_exposure_{year}\.parquet$", ["cd_ibge", "x_km", "y_km"])
    main = main_election(cv)
    cands = candidacy_votes(cv, year, main)
    paired = margins(within_list_pairs(cands), valid_votes(turnout, main))
    pairs = close_pairs(paired)

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(place_candidate_votes(sv, main))
    strong = strongholds(pl.concat(pieces))

    used, same, no_coordinates = stronghold_pairs(pairs, strong, locate_places(places))
    munis = set(pairs["cd_ibge"].to_list())
    columns = [*GRID_COLUMNS, *(f"share_{layer}_{year}" for layer in LAYERS)]
    cells = grid.select(columns)
    unrep = unrepresented(cells, reached, munis)
    g = displacement(unrep, used)
    counts = {
        "main_election": main,
        "close_pairs": pairs.height,
        "pairs_used": used.height,
        "dropped_same_place": same,
        "dropped_no_coordinates": no_coordinates,
        "municipalities_with_pair": len(munis),
        "cells_in_municipalities": cells.filter(pl.col("cd_ibge").is_in(list(munis))).height,
    }
    return report(unrep, g, counts, year)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4g}"


def _summary(results: dict[str, dict[str, Any]]) -> str:
    lines = ["## Displacement-exposure options for decision 0005 (exploration half)"]
    for year, r in results.items():
        lines += [
            "",
            f"### {year}",
            "",
            f"{r['unrepresented_cells']:,} unrepresented cells in "
            f"{r['municipalities_with_pair']:,} municipalities with a close pair; "
            f"{r['pairs_used']:,} of {r['close_pairs']:,} pairs "
            f"used ({r['dropped_same_place']:,} same place, {r['dropped_no_coordinates']:,} "
            "no coordinates).",
            "",
            "| Variant | Cells non-zero | In undesignated forest | Median abs G |",
            "| --- | --- | --- | --- |",
        ]
        for name, v in r["variants"].items():
            share = v["tenure"]["undesignated"]["share"]
            share_text = "n/a" if share is None else census._pct(share)
            lines.append(
                f"| {name} | {v['cells_nonzero']:,} | {share_text} | {_fmt(v['median_abs_G'])} |"
            )
    lines += [
        "",
        "G_i sums, over the close pairs of the cell's municipality, the kernel at the elected "
        "candidate's stronghold minus the kernel at the other's; swapping a pair's winner and "
        "loser flips the sign of its term, so E[G_i] over swaps is 0 and the recentred exposure "
        "equals G / 2 (decision 0004). No outcome data was read.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        remote = census._paths("grid_cells", r"grid_cells\.parquet$")[0]
        local = Path(tmp) / Path(remote).name
        store.download(remote, local)
        wanted = [*GRID_COLUMNS, *(f"share_{layer}_{y}" for y in YEARS for layer in LAYERS)]
        grid = restrict(pl.read_parquet(local, columns=wanted), half).with_columns(
            pl.col("cd_ibge").cast(pl.Utf8)
        )
        local.unlink()
        for year in YEARS:
            results[str(year)] = _year(store, Path(tmp), half, year, grid)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
