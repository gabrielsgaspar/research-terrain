"""Exposure options for decision 0004 (idea 0001), exploration half.

Per election year, six ways to measure how exposed a 1 km cell is to the close
council races of its municipality: three kernels (`exp2`, `ring2`, `ring5`) times
two measures (`share`, `votes`). Reports reach, the pair contrast `D_i`, its
spread by population and land tenure, and how much the variants agree. No
outcome data; no effects.

Close pairs and place votes come from `0001_feasibility_census.py`, loaded below
and not copied. The close-pair and exposure functions are imported from
`terrain.strongholds`, which holds the one definition. The issue that ordered this
script holds the full definitions.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (  # noqa: F401  (re-exported: tests and figures read these names)
    CELL,
    KERNELS,
    MAX_KM,
    MEASURES,
    TOLERANCE,
    cell_place_distances,
    close_pairs,
    exposure,
    kernel,
    locate_places,
    place_shares,
    place_totals,
)

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "feasibility_census", _REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

YEARS = census.YEARS
PLACE_KEY = census.PLACE_KEY
HEADLINE = census.HEADLINE
PLACE = ["cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
VARIANTS = tuple(f"{k}_{m}" for k in KERNELS for m in MEASURES)
QUANTILES = (0.01, 0.10, 0.50, 0.90, 0.99)
LAYERS = ("indigenous", "settlement", "undesignated")
GRID_COLUMNS = ["cd_ibge", "x_km", "y_km", "pop_2022"]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def _quantiles(values: pl.Series) -> dict[str, float | None] | None:
    if values.len() == 0:
        return None
    return {f"{q * 100:g}%": _num(values.quantile(q, interpolation="linear")) for q in QUANTILES}


def _group(exposed: pl.DataFrame, condition: pl.Expr) -> dict[str, Any]:
    chosen = exposed.filter(condition)
    mean = chosen["abs_D"].mean() if chosen.height else None
    return {"cells": chosen.height, "mean_abs_D": _num(mean)}


def _correlation(left: pl.DataFrame, right: pl.DataFrame) -> dict[str, Any]:
    both = (
        left.filter(pl.col("exposed"))
        .select(*CELL, pl.col("D_i").alias("a"))
        .join(
            right.filter(pl.col("exposed")).select(*CELL, pl.col("D_i").alias("b")),
            on=CELL,
            how="inner",
        )
    )
    if both.height < 2:
        return {"cells": both.height, "pearson": None}
    return {"cells": both.height, "pearson": _num(both.select(pl.corr("a", "b")).item())}


def report(
    cells: pl.DataFrame, results: dict[str, pl.DataFrame], pairs: pl.DataFrame, year: int
) -> dict[str, Any]:
    """Items 1-5 of the issue for one year.

    `cells` are the exploration-half grid cells (`CELL`, `pop_2022`, `share_<layer>_<year>`),
    `results` maps a variant name (`exp2_share`, ...) to `exposure` output.
    """
    per_muni = pairs.group_by("cd_ibge").len()
    out: dict[str, Any] = {
        "cells": cells.height,
        "municipalities_with_pair": per_muni.height,
        "close_pairs": pairs.height,
        "pairs_per_municipality": {
            "mean": _num(per_muni["len"].mean()) if per_muni.height else None,
            "max": int(per_muni["len"].max()) if per_muni.height else None,
        },
    }
    variants: dict[str, Any] = {}
    layer_columns = {layer: f"share_{layer}_{year}" for layer in LAYERS}
    attributes = cells.select(*CELL, "pop_2022", *layer_columns.values())
    for name, frame in results.items():
        exposed = (
            frame.filter(pl.col("exposed"))
            .join(attributes, on=CELL, how="left")
            .with_columns(pl.col("D_i").abs().alias("abs_D"))
        )
        n_exposed = exposed.height
        pop_zero = exposed.filter(pl.col("pop_2022") == 0).height
        groups = {
            "pop_2022_zero": _group(exposed, pl.col("pop_2022") == 0),
            "pop_2022_positive": _group(exposed, pl.col("pop_2022") > 0),
        }
        for layer, column in layer_columns.items():
            groups[f"{layer}_above_0"] = _group(exposed, pl.col(column) > 0)
        variants[name] = {
            "reached": frame.height,
            "exposed": n_exposed,
            "share_exposed_pop_2022_zero": pop_zero / n_exposed if n_exposed else None,
            "quantiles_D": _quantiles(exposed["D_i"]),
            "quantiles_abs_D": _quantiles(exposed["abs_D"]),
            "mean_abs_D_by_group": groups,
        }
    out["variants"] = variants
    agreement: dict[str, Any] = {}
    for measure in MEASURES:
        for ring in ("ring2", "ring5"):
            a, b = f"exp2_{measure}", f"{ring}_{measure}"
            if a in results and b in results:
                agreement[f"{a} vs {b}"] = _correlation(results[a], results[b])
    for kern in KERNELS:
        a, b = f"{kern}_share", f"{kern}_votes"
        if a in results and b in results:
            agreement[f"{a} vs {b}"] = _correlation(results[a], results[b])
    out["agreement"] = agreement
    return out


def _year(
    store: GCSStore, tmp: Path, half: frozenset[str], year: int, grid: pl.DataFrame
) -> dict[str, Any]:
    def read(manifest: str, pattern: str) -> pl.DataFrame:
        remote = census._paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = restrict(pl.read_parquet(local), half)
        local.unlink()
        return frame

    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    places = read("polling_places", rf"polling_places_{year}\.parquet$")
    main = census.main_election(cv)
    cands = census.candidacy_votes(cv, year, main)
    paired = census.margins(census.within_list_pairs(cands), census.valid_votes(turnout, main))
    pairs = close_pairs(paired)

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(census.place_candidate_votes(sv, main))
    place_votes = pl.concat(pieces)
    totals = place_totals(place_votes)
    shares = place_shares(place_votes)

    columns = [*GRID_COLUMNS, *(f"share_{layer}_{year}" for layer in LAYERS)]
    cells = grid.select(columns)
    dist = cell_place_distances(cells.select(CELL), locate_places(places))
    results = {
        f"{k}_{m}": exposure(dist, totals, shares, pairs, k, m) for k in KERNELS for m in MEASURES
    }
    return {"main_election": main, **report(cells, results, pairs, year)}


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4g}"


def _summary(results: dict[str, dict[str, Any]]) -> str:
    lines = ["## Exposure options for decision 0004 (exploration half)"]
    for year, r in results.items():
        pm = r["pairs_per_municipality"]
        lines += [
            "",
            f"### {year}",
            "",
            f"{r['cells']:,} cells; {r['municipalities_with_pair']:,} municipalities with a "
            f"close pair ({r['close_pairs']:,} pairs; mean {_fmt(pm['mean'])}, max {pm['max']}).",
            "",
            "| Variant | Reached | Exposed | Empty share | Median abs D |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, v in r["variants"].items():
            median = v["quantiles_abs_D"]["50%"] if v["quantiles_abs_D"] else None
            lines.append(
                f"| {name} | {v['reached']:,} | {v['exposed']:,} | "
                f"{census._pct(v['share_exposed_pop_2022_zero'])} | {_fmt(median)} |"
            )
    lines += [
        "",
        "D_i sums, over the close pairs of the cell's municipality, the exposure to the "
        "elected candidate minus the exposure to the other; swapping a pair's winner and "
        "loser flips the sign of its term, so E[D_i] over swaps is 0 and the recentred "
        "exposure to the elected (Borusyak and Hull 2023) equals D_i / 2. Empty share is "
        "the share of exposed cells with no one in 2022. No outcome data was read.",
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
