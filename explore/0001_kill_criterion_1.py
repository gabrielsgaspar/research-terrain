"""Kill criterion 1 for the stronghold design (idea 0001), exploration half.

Counts the close-pair candidates (margin at most 0.5%, inverted pairs excluded)
whose stronghold polling place lies inside or within 2 and 5 km of an
indigenous land and of a settlement, per year and pooled, and says whether
kill criterion 1 is met. No outcome data; no effects.

Close pairs and strongholds come from `0001_feasibility_census.py`, loaded
below and not copied.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "feasibility_census", _REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

YEARS = census.YEARS
PLACE_KEY = census.PLACE_KEY
CAND_KEY = census.CAND_KEY
BANDS = (0, 2, 5)
MINIMUM = 200
TOLERANCE = 1e-9
LAYERS = {"indigenous": "dist_indigenous_km", "settlement": "dist_settlement_km"}


def join_tenure(strong: pl.DataFrame, tenure: pl.DataFrame) -> pl.DataFrame:
    """Left-join the two distances on the place key, after casting zone and place to Int64."""
    casts = [pl.col("nr_zona").cast(pl.Int64), pl.col("nr_local_votacao").cast(pl.Int64)]
    left = strong.with_columns(casts)
    right = tenure.select(*PLACE_KEY, *LAYERS.values()).with_columns(casts)
    return left.join(right.unique(PLACE_KEY), on=PLACE_KEY, how="left")


def candidate_distances(
    close: pl.DataFrame, strong: pl.DataFrame, tenure: pl.DataFrame
) -> pl.DataFrame:
    """One row per close-pair candidate with `has_stronghold` and `has_coordinates`.

    `has_coordinates` is true only when the stronghold matched a tenure row with
    both distances. Anything else is "without coordinates", never "far away".
    """
    joined = join_tenure(strong, tenure).select(
        *CAND_KEY,
        *LAYERS.values(),
        pl.lit(True).alias("has_stronghold"),
    )
    out = (
        close.select(CAND_KEY)
        .unique()
        .join(joined, on=CAND_KEY, how="left")
        .with_columns(pl.col("has_stronghold").fill_null(False))
    )
    has_coordinates = pl.all_horizontal([pl.col(c).is_not_null() for c in LAYERS.values()])
    return out.with_columns(has_coordinates.alias("has_coordinates"))


def band_counts(table: pl.DataFrame, bands: tuple[int, ...] = BANDS) -> dict[str, Any]:
    """Candidates, strongholds, strongholds with coordinates and counts within each band."""
    with_coords = table.filter(pl.col("has_coordinates"))
    out: dict[str, Any] = {
        "candidates": table.height,
        "with_stronghold": int(table["has_stronghold"].sum()),
        "with_coordinates": with_coords.height,
    }
    for layer, column in LAYERS.items():
        out[layer] = {
            f"{band}km": int(with_coords.filter(pl.col(column) <= band + TOLERANCE).height)
            for band in bands
        }
    return out


def pool(per_year: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Sum the counts of `band_counts` over years."""
    rows = list(per_year.values())
    pooled: dict[str, Any] = {
        key: sum(r[key] for r in rows)
        for key in ("candidates", "with_stronghold", "with_coordinates")
    }
    for layer in LAYERS:
        pooled[layer] = {band: sum(r[layer][band] for r in rows) for band in rows[0][layer]}
    return pooled


def verdict(pooled: dict[str, Any], minimum: int = MINIMUM) -> dict[str, Any]:
    """Kill criterion 1 is "met" if either pooled 5 km count is below the minimum."""
    deciding = {layer: pooled[layer]["5km"] for layer in LAYERS}
    met = any(count < minimum for count in deciding.values())
    return {"kill_criterion_1": "met" if met else "not met", "minimum": minimum, "5km": deciding}


def _year(store: GCSStore, tmp: Path, half: frozenset[str], year: int) -> dict[str, Any]:
    def read(manifest: str, pattern: str) -> pl.DataFrame:
        remote = census._paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = restrict(pl.read_parquet(local), half)
        local.unlink()
        return frame

    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    tenure = read("polling_place_tenure", rf"polling_place_tenure_{year}\.parquet$")
    if "ano" in tenure.columns:
        tenure = tenure.filter(pl.col("ano") == year)
    main = census.main_election(cv)
    cands = census.candidacy_votes(cv, year, main)
    paired = census.margins(census.within_list_pairs(cands), census.valid_votes(turnout, main))
    close = census.close_candidates(paired)

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(census.place_candidate_votes(sv, main))
    strong = census.strongholds(pl.concat(pieces))
    return band_counts(candidate_distances(close, strong, tenure))


def _summary(results: dict[str, dict[str, Any]], decision: dict[str, Any]) -> str:
    head = (
        "| Year | Candidates | With coordinates | Indigenous 0 km | 2 km | 5 km "
        "| Settlement 0 km | 2 km | 5 km |"
    )
    lines = ["## Kill criterion 1: idea 0001 (exploration half)", "", head]
    lines.append("| " + " | ".join(["---"] * 9) + " |")
    for name, r in results.items():
        ind, sett = r["indigenous"], r["settlement"]
        lines.append(
            f"| {name} | {r['candidates']:,} | {r['with_coordinates']:,} | "
            f"{ind['0km']:,} | {ind['2km']:,} | {ind['5km']:,} | "
            f"{sett['0km']:,} | {sett['2km']:,} | {sett['5km']:,} |"
        )
    lines += [
        "",
        f"Verdict: kill criterion 1 is **{decision['kill_criterion_1']}** "
        f"(pooled 5 km: indigenous {decision['5km']['indigenous']:,}, "
        f"settlement {decision['5km']['settlement']:,}; minimum {decision['minimum']}).",
        "",
        "Caveats: settlement boundaries are the 2025 edition, dated back by creation year; "
        "the 5 km settlement band takes in many strongholds, so 0 and 2 km are reported too; "
        "candidates without a stronghold or without coordinates are in the first columns "
        "only, never counted as far away; no outcome data was read.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    per_year: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for year in YEARS:
            per_year[str(year)] = _year(store, Path(tmp), half, year)
    pooled = pool(per_year)
    decision = verdict(pooled)
    shown = {**per_year, "pooled": pooled}
    write_results(args.out_dir, _summary(shown, decision), {**shown, "verdict": decision})


if __name__ == "__main__":
    main()
