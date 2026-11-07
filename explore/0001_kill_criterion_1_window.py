"""Kill criterion 1 for idea 0001 at the 0.25% window, exploration half.

Recounts the close-pair candidates whose stronghold lies inside or within 2 and
5 km of an indigenous land and of a settlement, at margins of at most 0.25%
(decision 0008) and, as a reproduction check of run 41839642406, at 0.50%.
Both windows come from the same tables in one pass. No outcome data; no effects.

The counting is `0001_kill_criterion_1.py`, loaded below and not copied.
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
    "kill_criterion_1", _REPO / "explore" / "0001_kill_criterion_1.py"
)
kc1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kc1)
census = kc1.census

YEARS = census.YEARS
WINDOWS = {"0.25%": 0.0025, "0.50%": 0.005}


def window_counts(
    paired: pl.DataFrame,
    strong: pl.DataFrame,
    tenure: pl.DataFrame,
    windows: dict[str, float] = WINDOWS,
) -> dict[str, dict[str, Any]]:
    """Band counts of each window's close candidates, from the same tables."""
    return {
        name: kc1.band_counts(
            kc1.candidate_distances(census.close_candidates(paired, threshold), strong, tenure)
        )
        for name, threshold in windows.items()
    }


def _year(store: GCSStore, tmp: Path, half: frozenset[str], year: int) -> dict[str, dict[str, Any]]:
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

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(census.place_candidate_votes(sv, main))
    strong = census.strongholds(pl.concat(pieces))
    return window_counts(paired, strong, tenure)


def _results(
    per_year: dict[str, dict[str, dict[str, Any]]],
    windows: dict[str, float] = WINDOWS,
) -> dict[str, dict[str, Any]]:
    """`{window: {year..., "pooled", "verdict"}}` from `{year: {window: counts}}`."""
    out: dict[str, dict[str, Any]] = {}
    for name in windows:
        years = {year: counts[name] for year, counts in per_year.items()}
        pooled = kc1.pool(years)
        out[name] = {**years, "pooled": pooled, "verdict": kc1.verdict(pooled)}
    return out


def _table(rows: dict[str, dict[str, Any]]) -> list[str]:
    head = (
        "| Year | Candidates | With coordinates | Indigenous 0 km | 2 km | 5 km "
        "| Settlement 0 km | 2 km | 5 km |"
    )
    lines = [head, "| " + " | ".join(["---"] * 9) + " |"]
    for name, r in rows.items():
        ind, sett = r["indigenous"], r["settlement"]
        lines.append(
            f"| {name} | {r['candidates']:,} | {r['with_coordinates']:,} | "
            f"{ind['0km']:,} | {ind['2km']:,} | {ind['5km']:,} | "
            f"{sett['0km']:,} | {sett['2km']:,} | {sett['5km']:,} |"
        )
    return lines


def _summary(results: dict[str, dict[str, Any]]) -> str:
    first = results["0.25%"]["verdict"]
    lines = [
        f"Kill criterion 1 at 0.25% is **{first['kill_criterion_1']}**: pooled 5 km "
        f"indigenous {first['5km']['indigenous']:,}, settlement "
        f"{first['5km']['settlement']:,} (minimum {first['minimum']}).",
        "",
    ]
    for name, block in results.items():
        verdict = block["verdict"]
        rows = {k: v for k, v in block.items() if k != "verdict"}
        lines += [f"## Kill criterion 1 at {name}: idea 0001 (exploration half)", ""]
        lines += _table(rows)
        lines += [
            "",
            f"Verdict at {name}: kill criterion 1 is **{verdict['kill_criterion_1']}** "
            f"(pooled 5 km: indigenous {verdict['5km']['indigenous']:,}, "
            f"settlement {verdict['5km']['settlement']:,}; minimum {verdict['minimum']}).",
            "",
        ]
    lines += [
        "Caveats: settlement boundaries are the 2025 edition, dated back by creation year; "
        "the 5 km settlement band takes in many strongholds, so 0 and 2 km are reported too; "
        "candidates without a stronghold or without coordinates are in the first columns "
        "only, never counted as far away; no outcome data was read. The 0.50% table is a "
        "reproduction check of run 41839642406.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    per_year: dict[str, dict[str, dict[str, Any]]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for year in YEARS:
            per_year[str(year)] = _year(store, Path(tmp), half, year)
    results = _results(per_year)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
