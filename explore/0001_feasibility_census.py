"""Feasibility census for the stronghold design (idea 0001), exploration half.

Per council election 2008-2024: count close within-list pairs (the elected
candidate with the fewest votes against the non-elected one with the most) and,
for the candidates in close pairs and for all candidates, measure how often the
stronghold is outside the municipal seat. No outcome data; no effects.

Definitions are in the functions below; the issue that ordered this script
holds the full text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (  # noqa: F401  (re-exported: other scripts load this module)
    CAND_KEY,
    COUNCIL,
    ELECTED_CODES,
    HEADLINE,
    LIST_KEY,
    MIN_PLACE_VOTES,
    NOT_ELECTED_CODES,
    PLACE_KEY,
    _codes,
    _council_round1,
    candidacy_votes,
    elected_status,
    main_election,
    margins,
    place_candidate_votes,
    strongholds,
    valid_votes,
    within_list_pairs,
)

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "data" / "manifests" / "build"
YEARS = (2008, 2012, 2016, 2020, 2024)
THRESHOLDS = (0.0025, 0.005, 0.01, 0.02)


def close_counts(
    paired: pl.DataFrame, thresholds: tuple[float, ...] = THRESHOLDS
) -> dict[str, Any]:
    """Pairs, inverted pairs and close pairs per threshold; inverted pairs are never close."""
    usable = paired.filter(~pl.col("inverted") & pl.col("margin").is_not_null())
    close = {
        f"{t * 100:g}%": int(usable.filter(pl.col("margin").abs() <= t + 1e-12).height)
        for t in thresholds
    }
    return {
        "pairs": paired.height,
        "inverted": int(paired["inverted"].sum()),
        "without_valid_votes": int(paired["margin"].is_null().sum()),
        "close": close,
    }


def close_candidates(paired: pl.DataFrame, threshold: float = HEADLINE) -> pl.DataFrame:
    """Both candidates of every non-inverted pair within `threshold`."""
    close = paired.filter(~pl.col("inverted") & (pl.col("margin").abs() <= threshold + 1e-12))
    keys = ["cd_eleicao", "sg_ue"]
    first = close.select(*keys, pl.col("elected_sq").alias("sq_candidato"))
    second = close.select(*keys, pl.col("other_sq").alias("sq_candidato"))
    return pl.concat([first, second]).unique().sort([*keys, "sq_candidato"])


def join_place_types(section_votes: pl.DataFrame, place_types: pl.DataFrame) -> pl.DataFrame:
    """Left-join `place_type` after casting `nr_zona` and `nr_local_votacao` to Int64."""
    casts = [pl.col("nr_zona").cast(pl.Int64), pl.col("nr_local_votacao").cast(pl.Int64)]
    left = section_votes.with_columns(casts)
    right = place_types.select(*PLACE_KEY, "place_type").with_columns(casts)
    return left.join(right, on=PLACE_KEY, how="left")


def outside_seat_share(typed_votes: pl.DataFrame) -> pl.DataFrame:
    """Each candidacy's share of votes at typed places whose type is not `seat`.

    `typed_votes` is `place_candidate_votes` joined to `place_type`. Places without
    a type (no coordinates) are left out of numerator and denominator.
    """
    typed = typed_votes.filter(
        (pl.col("vote_type") == "candidate")
        & pl.col("sq_candidato").is_not_null()
        & pl.col("place_type").is_not_null()
    )
    return typed.group_by(CAND_KEY).agg(
        (
            pl.col("votes").filter(pl.col("place_type") != "seat").sum() / pl.col("votes").sum()
        ).alias("outside_share")
    )


def candidate_table(
    cands: pl.DataFrame, strong: pl.DataFrame, place_types: pl.DataFrame, shares: pl.DataFrame
) -> pl.DataFrame:
    """One row per candidacy in `cands` with its stronghold type and outside-seat share."""
    typed = join_place_types(strong, place_types).select(
        *CAND_KEY,
        pl.col("place_type").alias("stronghold_type"),
        pl.lit(True).alias("has_stronghold"),
    )
    return (
        cands.select(CAND_KEY)
        .join(typed, on=CAND_KEY, how="left")
        .join(shares, on=CAND_KEY, how="left")
        .with_columns(pl.col("has_stronghold").fill_null(False))
    )


def summarise(candidates: pl.DataFrame) -> dict[str, Any]:
    """Counts and shares for a candidate table (see `candidate_table`)."""
    n = candidates.height
    with_s = candidates.filter(pl.col("has_stronghold"))
    outside = with_s.filter(
        pl.col("stronghold_type").is_not_null() & (pl.col("stronghold_type") != "seat")
    )
    by_type = with_s.with_columns(pl.col("stronghold_type").fill_null("unknown"))
    counts = by_type.group_by("stronghold_type").len().sort("stronghold_type")
    share = candidates["outside_share"].drop_nulls()
    return {
        "candidates": n,
        "with_stronghold": with_s.height,
        "share_with_stronghold": with_s.height / n if n else None,
        "stronghold_outside_seat": outside.height,
        "share_stronghold_outside_seat": outside.height / with_s.height if with_s.height else None,
        "stronghold_by_place_type": dict(
            zip(counts["stronghold_type"], counts["len"], strict=True)
        ),
        "mean_share_votes_outside_seat": float(share.mean()) if share.len() else None,
    }


def _paths(manifest: str, pattern: str) -> list[str]:
    data = json.loads((MANIFESTS / f"{manifest}.json").read_text(encoding="utf-8"))
    hits = sorted(f["path"] for f in data["files"] if re.search(pattern, f["path"]))
    if not hits:
        raise SystemExit(f"{manifest}: no file matches {pattern}")
    return hits


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _year(store: GCSStore, tmp: Path, half: frozenset[str], year: int) -> dict[str, Any]:
    def read(manifest: str, pattern: str) -> list[pl.DataFrame]:
        frames = []
        for remote in _paths(manifest, pattern):
            local = tmp / Path(remote).name
            store.download(remote, local)
            frames.append(restrict(pl.read_parquet(local), half))
            local.unlink()
        return frames

    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")[0]
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")[0]
    types = read("polling_place_types", rf"polling_place_types_{year}\.parquet$")[0]
    main = main_election(cv)
    cands = candidacy_votes(cv, year, main)
    paired = margins(within_list_pairs(cands), valid_votes(turnout, main))
    counts = close_counts(paired)
    close = close_candidates(paired)

    pieces = []
    for remote in _paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(place_candidate_votes(sv, main))
    place_votes = pl.concat(pieces)
    strong = strongholds(place_votes)
    shares = outside_seat_share(join_place_types(place_votes, types))
    voted = cands.filter(pl.col("votes") > 0)
    close_table = candidate_table(
        close.join(voted.select(CAND_KEY), on=CAND_KEY), strong, types, shares
    )
    all_table = candidate_table(voted, strong, types, shares)
    return {
        **counts,
        "main_election": main,
        "close_pair_candidates": summarise(close_table),
        "all_candidates": summarise(all_table),
    }


def _summary(results: dict[str, dict[str, Any]]) -> str:
    lines = [
        "## Feasibility census: electoral strongholds (exploration half)",
        "",
        "| Year | Pairs | Close at 0.5% | Close at 1% | Close-pair candidates: "
        "stronghold outside the seat | Their votes outside the seat |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for year, r in results.items():
        c = r["close_pair_candidates"]
        lines.append(
            f"| {year} | {r['pairs']:,} | {r['close']['0.5%']:,} | {r['close']['1%']:,} | "
            f"{_pct(c['share_stronghold_outside_seat'])} | "
            f"{_pct(c['mean_share_votes_outside_seat'])} |"
        )
    parts = []
    for year, r in results.items():
        a = r["all_candidates"]
        parts.append(
            f"{year}: {r['pairs']:,} within-list pairs ({r['inverted']:,} inverted, excluded), "
            f"{r['close']['0.5%']:,} close at 0.5% and {r['close']['2%']:,} at 2%; "
            f"{r['close_pair_candidates']['candidates']:,} close-pair candidates, "
            f"{_pct(a['share_stronghold_outside_seat'])} of all candidates have a stronghold "
            f"outside the seat"
        )
    lines += [
        "",
        "Counts by election, exploration half only: " + "; ".join(parts) + ". "
        "Shares are among candidates with a stronghold (a polling place with at least "
        f"{MIN_PLACE_VOTES} votes); votes outside the seat are the mean over candidates.",
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
        for year in YEARS:
            results[str(year)] = _year(store, Path(tmp), half, year)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
