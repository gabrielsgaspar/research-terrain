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

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "data" / "manifests" / "build"
YEARS = (2008, 2012, 2016, 2020, 2024)
THRESHOLDS = (0.0025, 0.005, 0.01, 0.02)
HEADLINE = 0.005
MIN_PLACE_VOTES = 50
COUNCIL = 13
LIST_KEY = ["cd_eleicao", "sg_ue", "cd_ibge", "sq_coligacao"]
CAND_KEY = ["cd_eleicao", "sg_ue", "sq_candidato"]
PLACE_KEY = ["cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]

# cd_sit_tot_turno: the codes changed between 2008 and 2012.
ELECTED_CODES = {2008: {1, 5}, 2012: {2, 3}}
NOT_ELECTED_CODES = {2008: {2, 4}, 2012: {4, 5}}


def _codes(table: dict[int, set[int]], year: int) -> list[int]:
    return sorted(table[2008] if year == 2008 else table[2012])


def _council_round1(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
    )


def main_election(candidate_votes: pl.DataFrame) -> int:
    """The council, round-1 `cd_eleicao` with the most rows (the year's main election)."""
    rows = _council_round1(candidate_votes).group_by("cd_eleicao").len()
    return int(rows.sort(["len", "cd_eleicao"], descending=[True, False])["cd_eleicao"][0])


def elected_status(df: pl.DataFrame, year: int) -> pl.DataFrame:
    """Add `elected` (bool) from `cd_sit_tot_turno`; other codes are dropped."""
    code = pl.col("cd_sit_tot_turno").cast(pl.Int64, strict=False)
    elected = code.is_in(_codes(ELECTED_CODES, year))
    not_elected = code.is_in(_codes(NOT_ELECTED_CODES, year))
    return df.filter(elected | not_elected).with_columns(elected.alias("elected"))


def candidacy_votes(candidate_votes: pl.DataFrame, year: int, main: int) -> pl.DataFrame:
    """Counted votes per candidacy in the main council election, summed over zones."""
    df = _council_round1(candidate_votes).filter(pl.col("cd_eleicao") == main)
    df = elected_status(df, year).filter(pl.col("sq_coligacao").is_not_null())
    return df.group_by(CAND_KEY, maintain_order=True).agg(
        pl.col("qt_votos_nominais").sum().alias("votes"),
        pl.col("cd_ibge").first(),
        pl.col("sq_coligacao").first(),
        pl.col("elected").first(),
    )


def within_list_pairs(cands: pl.DataFrame) -> pl.DataFrame:
    """Per list: the elected candidate with the fewest votes vs the non-elected with the most.

    Only candidates with votes above 0 take part; a list needs one of each kind.
    """
    voted = cands.filter(pl.col("votes") > 0)
    low = (
        voted.filter(pl.col("elected"))
        .sort(["votes", "sq_candidato"])
        .group_by(LIST_KEY, maintain_order=True)
        .first()
        .select(
            *LIST_KEY,
            pl.col("sq_candidato").alias("elected_sq"),
            pl.col("votes").alias("elected_votes"),
        )
    )
    high = (
        voted.filter(~pl.col("elected"))
        .sort(["votes", "sq_candidato"], descending=[True, False])
        .group_by(LIST_KEY, maintain_order=True)
        .first()
        .select(
            *LIST_KEY,
            pl.col("sq_candidato").alias("other_sq"),
            pl.col("votes").alias("other_votes"),
        )
    )
    return low.join(high, on=LIST_KEY, how="inner").sort(LIST_KEY)


def valid_votes(turnout: pl.DataFrame, main: int) -> pl.DataFrame:
    """Valid council votes per municipality, round 1, main election, summed over zones."""
    df = _council_round1(turnout).filter(pl.col("cd_eleicao") == main)
    return df.group_by(["cd_eleicao", "sg_ue"]).agg(
        pl.col("qt_total_votos_validos").sum().alias("valid_votes")
    )


def margins(pairs: pl.DataFrame, valid: pl.DataFrame) -> pl.DataFrame:
    """Add `margin` = (elected - other) / valid votes, and `inverted` when it is negative."""
    out = pairs.join(valid, on=["cd_eleicao", "sg_ue"], how="left")
    margin = (pl.col("elected_votes") - pl.col("other_votes")) / pl.col("valid_votes")
    return out.with_columns(margin.alias("margin"), (margin < 0).fill_null(False).alias("inverted"))


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


def place_candidate_votes(section_votes: pl.DataFrame, main: int) -> pl.DataFrame:
    """Counted candidate and legend votes per polling place and candidacy.

    Council, round 1, the main election; annulled rows and other vote types dropped.
    """
    df = _council_round1(section_votes).filter(
        (pl.col("cd_eleicao") == main)
        & pl.col("vote_type").is_in(["candidate", "legend"])
        & ~pl.col("annulled_in_results").fill_null(False)
    )
    return (
        df.with_columns(pl.col("nr_zona").cast(pl.Int64), pl.col("nr_local_votacao").cast(pl.Int64))
        .group_by([*PLACE_KEY, "cd_eleicao", "vote_type", "sq_candidato"])
        .agg(pl.col("qt_votos").sum().alias("votes"))
    )


def strongholds(place_votes: pl.DataFrame, min_place_votes: int = MIN_PLACE_VOTES) -> pl.DataFrame:
    """The place with the highest location quotient among places with V_p >= the minimum.

    `place_votes` comes from `place_candidate_votes`. V_p is the place's candidate
    plus legend votes; the municipal total is the sum of V_p over all its places.
    Ties go to the place with more of the candidate's votes, then the lower place key.
    """
    muni = ["cd_eleicao", "sg_ue"]
    places = place_votes.group_by([*PLACE_KEY, "cd_eleicao"]).agg(pl.col("votes").sum().alias("vp"))
    totals = places.group_by(muni).agg(pl.col("vp").sum().alias("muni_total"))
    cands = place_votes.filter(pl.col("vote_type") == "candidate").filter(
        pl.col("sq_candidato").is_not_null()
    )
    cand_totals = cands.group_by(CAND_KEY).agg(pl.col("votes").sum().alias("cand_total"))
    joined = (
        cands.join(places, on=[*PLACE_KEY, "cd_eleicao"])
        .join(totals, on=muni)
        .join(cand_totals, on=CAND_KEY)
        .filter((pl.col("vp") >= min_place_votes) & (pl.col("cand_total") > 0))
        .with_columns(
            (
                (pl.col("votes") / pl.col("vp")) / (pl.col("cand_total") / pl.col("muni_total"))
            ).alias("quotient")
        )
    )
    return (
        joined.sort(
            ["quotient", "votes", "nr_zona", "nr_local_votacao"],
            descending=[True, True, False, False],
        )
        .group_by(CAND_KEY, maintain_order=True)
        .first()
        .select(
            *CAND_KEY,
            "cd_ibge",
            "nr_zona",
            "nr_local_votacao",
            "quotient",
            pl.col("votes").alias("stronghold_votes"),
        )
    )


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
