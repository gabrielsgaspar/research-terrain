"""Aligned, unaligned and mixed close council pairs at 0.25% (idea 0004, kill criterion 1).

For each council election 2008-2024 this counts the close pairs of decision 0008's window
(|margin| of at most 0.25% of valid council votes) by alignment with the mayor elected in the
same election: aligned (both sides in the mayor's coalition), unaligned (neither) and mixed
(one). It also prints a rough implied power for the moderation test, scaled from decision
0008's direct power (0.868 on 2,328 pairs). It reads no outcome, exposure or displacement
table and estimates no effect. Exploration half only.

The council pairs, the deciding mayoral round and the mayor's votes are those of
`terrain.strongholds`, `0003_mayor_power.py` and `0001_window.py`, loaded, not copied.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from statistics import NormalDist
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    candidacy_votes,
    main_election,
    margins,
    valid_votes,
    within_list_pairs,
)

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wn = _load("alignment_window", "0001_window.py")
mp = _load("alignment_mayor_power", "0003_mayor_power.py")
census = _load("alignment_census", "0001_feasibility_census.py")

ELECTIONS = (2008, 2012, 2016, 2020, 2024)
POWER_ELECTIONS = (2008, 2012, 2016, 2020)
WINDOW = 0.0025
EDGE = 1e-12
COUNCIL = 13
MAYOR = 11
FEDERATION_YEAR = 2024
EXPECTED_PAIRS = {2008: 478, 2012: 578, 2016: 596, 2020: 676, 2024: 541}
EXPECTED_POOLED_2008_2020 = 2328
MAX_LEFT_OUT = 0.05
MIN_EACH = 200  # drafted kill criterion 1
BASE_POWER = 0.868  # decision 0008, direct effect at 8%, 2,328 pairs at 0.25%
Z_TWO_SIDED = 1.96
K = Z_TWO_SIDED + NormalDist().inv_cdf(BASE_POWER)

CV_COLUMNS = [*mp.CV_COLUMNS, "cd_sit_tot_turno", "sq_coligacao"]
TURNOUT_COLUMNS = mp.TURNOUT_COLUMNS
CAND_COLUMNS = [
    "ano_eleicao",
    "cd_eleicao",
    "nr_turno",
    "cd_cargo",
    "sg_ue",
    "sq_candidato",
    "nr_partido",
    "sq_coligacao",
    "nr_federacao",
]
COALITION_COLUMNS = [
    "cd_eleicao",
    "cd_cargo",
    "sg_ue",
    "cd_ibge",
    "sq_coligacao",
    "nr_partido",
    "nr_federacao",
]
KINDS = ("aligned", "unaligned", "mixed", "left_out_side", "left_out_mayor")

Read = Callable[..., pl.DataFrame]


# --- Close pairs and council sides


def close_pairs_025(cv: pl.DataFrame, turnout: pl.DataFrame, year: int) -> tuple[pl.DataFrame, int]:
    """The year's non-inverted pairs with |margin| <= 0.25% (+ 1e-12), and the main election."""
    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    keep = ~pl.col("inverted") & (pl.col("margin").abs() <= WINDOW + EDGE)
    pairs = paired.filter(keep).select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("elected_sq").cast(pl.Utf8),
        pl.col("other_sq").cast(pl.Utf8),
        "margin",
    )
    return pairs, main


def _cargo(office: int) -> pl.Expr:
    return pl.col("cd_cargo").cast(pl.Int64, strict=False) == office


def council_parties(cands: pl.DataFrame, main: int) -> pl.DataFrame:
    """(`sg_ue`, `sq_candidato`, `nr_partido`, `nr_federacao`) of the main election's council."""
    return (
        cands.filter(_cargo(COUNCIL) & (pl.col("cd_eleicao").cast(pl.Int64, strict=False) == main))
        .select(
            pl.col("sg_ue").cast(pl.Utf8),
            pl.col("sq_candidato").cast(pl.Utf8),
            pl.col("nr_partido").cast(pl.Utf8),
            pl.col("nr_federacao").cast(pl.Utf8),
        )
        .unique(["sg_ue", "sq_candidato"], keep="first", maintain_order=True)
    )


# --- The elected mayor and its coalition


def elected_mayor(cv: pl.DataFrame, main: int, year: int) -> tuple[pl.DataFrame, dict[str, int]]:
    """(`sg_ue`, `sq_candidato`, `runoff`, `status`) of each municipality's mayor, and counts.

    The first candidacy by votes of the deciding round, ties broken by `sq_candidato`.
    """
    rows, _ = mp.deciding_round(cv, main)
    votes, _ = mp.candidacy_votes_mayor(rows, year)
    ordered = votes.with_columns(pl.col("sq_candidato").cast(pl.Utf8)).sort(
        ["sg_ue", "votes", "sq_candidato"], descending=[False, True, False]
    )
    grouped = ordered.group_by("sg_ue", maintain_order=True).agg(
        pl.col("sq_candidato").first(),
        pl.col("runoff").first(),
        pl.col("status").first(),
        pl.col("votes").first().alias("v1"),
        pl.col("votes").slice(1, 1).first().alias("v2"),
    )
    mayors = grouped.select("sg_ue", "sq_candidato", "runoff", "status")
    counts = {
        "mayors": mayors.height,
        "runoff": int(mayors["runoff"].sum() or 0),
        "ties": grouped.filter(pl.col("v2").is_not_null() & (pl.col("v1") == pl.col("v2"))).height,
        "not_eleito": mayors.filter(pl.col("status").fill_null("") != "ELEITO").height,
    }
    return mayors, counts


def mayor_coalition(
    mayors: pl.DataFrame, cands: pl.DataFrame, coalitions: pl.DataFrame, main: int
) -> tuple[dict[str, tuple[frozenset[str], frozenset[str]]], dict[str, int]]:
    """Per matched mayor: (coalition parties, coalition federations), and counts.

    The mayor's `cd_cargo` 11 main-election row gives `sq_coligacao` and `nr_partido`; the
    coalition parties are the `cd_cargo` 11 coalition rows of the same `sg_ue` and
    `sq_coligacao` (as text) plus the mayor's own party. A mayor without a main-election row
    is left out of the result; a coalition without rows is replaced by the mayor's party.
    """
    rows = (
        cands.filter(_cargo(MAYOR) & (pl.col("cd_eleicao").cast(pl.Int64, strict=False) == main))
        .select(
            pl.col("sg_ue").cast(pl.Utf8),
            pl.col("sq_candidato").cast(pl.Utf8),
            pl.col("nr_partido").cast(pl.Utf8).alias("own_party"),
            pl.col("nr_federacao").cast(pl.Utf8).alias("own_fed"),
            pl.col("sq_coligacao").cast(pl.Utf8),
        )
        .unique(["sg_ue", "sq_candidato"], keep="first", maintain_order=True)
    )
    matched = mayors.select("sg_ue", pl.col("sq_candidato").cast(pl.Utf8)).join(
        rows, on=["sg_ue", "sq_candidato"], how="inner"
    )
    members = coalitions.filter(
        _cargo(MAYOR) & (pl.col("cd_eleicao").cast(pl.Int64, strict=False) == main)
    ).select(
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_coligacao").cast(pl.Utf8),
        pl.col("nr_partido").cast(pl.Utf8),
        pl.col("nr_federacao").cast(pl.Utf8),
    )
    by_list: dict[tuple[str, str], list[tuple[str | None, str | None]]] = {}
    for ue, coalition, party, fed in members.iter_rows():
        by_list.setdefault((ue, coalition), []).append((party, fed))

    out: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    no_rows = 0
    for ue, _, own_party, own_fed, coalition in matched.iter_rows():
        found = by_list.get((ue, coalition)) if coalition is not None else None
        if not found:
            no_rows += 1
            found = []
        parties = {p for p, _ in found if p is not None}
        feds = {f for _, f in found if f is not None}
        if own_party is not None:
            parties.add(own_party)
        if own_fed is not None:
            feds.add(own_fed)
        out[ue] = (frozenset(parties), frozenset(feds))
    counts = {
        "mayors_without_main_row": mayors.height - matched.height,
        "coalitions_without_rows": no_rows,
    }
    return out, counts


# --- Pair types


def is_aligned(
    party: str, fed: str | None, coalition: tuple[frozenset[str], frozenset[str]], year: int
) -> bool:
    """A side is aligned if its party is a coalition party or, in 2024, its federation is."""
    parties, feds = coalition
    return party in parties or (year == FEDERATION_YEAR and fed is not None and fed in feds)


def pair_types(
    pairs: pl.DataFrame,
    sides: pl.DataFrame,
    mayors: dict[str, tuple[frozenset[str], frozenset[str]]],
    year: int,
) -> dict[str, int]:
    """Pairs by `KINDS`, and the council sides that did not match.

    A pair with a side that has no row or no party is `left_out_side`; otherwise one whose
    municipality has no matched mayor is `left_out_mayor`; the rest are aligned (both sides),
    unaligned (neither) or mixed. A side that does not match is never counted as unaligned.
    """
    known = {
        (ue, sq): (party, fed) for ue, sq, party, fed in sides.iter_rows() if party is not None
    }
    counts = dict.fromkeys(KINDS, 0)
    counts["sides_not_matched"] = 0
    for ue, elected_sq, other_sq in pairs.select("sg_ue", "elected_sq", "other_sq").iter_rows():
        two = [known.get((ue, elected_sq)), known.get((ue, other_sq))]
        counts["sides_not_matched"] += sum(side is None for side in two)
        if any(side is None for side in two):
            counts["left_out_side"] += 1
        elif ue not in mayors:
            counts["left_out_mayor"] += 1
        else:
            flags = [is_aligned(side[0], side[1], mayors[ue], year) for side in two]
            counts["aligned" if all(flags) else "unaligned" if not any(flags) else "mixed"] += 1
    return counts


# --- Implied power


def implied_power(n_a: int, n_u: int, total: int = EXPECTED_POOLED_2008_2020) -> float:
    """Phi(K * sqrt((1/total) / (1/n_a + 1/n_u)) - 1.96); rough scaling of decision 0008."""
    if n_a <= 0 or n_u <= 0:
        return NormalDist().cdf(-Z_TWO_SIDED)
    ratio = (1 / total) / (1 / n_a + 1 / n_u)
    return NormalDist().cdf(K * ratio**0.5 - Z_TWO_SIDED)


# --- One election and the stop checks


def check_year(year: int, close: int, counts: dict[str, int]) -> None:
    """Stop (counts only) if the year's pairs differ from decision 0008 or do not add up."""
    if close != EXPECTED_PAIRS[year]:
        raise SystemExit(f"{year}: {close} close pairs, decision 0008 has {EXPECTED_PAIRS[year]}")
    total = sum(counts[k] for k in KINDS)
    if total != close:
        raise SystemExit(f"{year}: types add to {total}, close pairs are {close}")
    for kind in ("left_out_side", "left_out_mayor"):
        if counts[kind] > MAX_LEFT_OUT * close:
            raise SystemExit(f"{year}: {counts[kind]} of {close} pairs left out ({kind})")


def election_counts(read: Read, cands: pl.DataFrame, year: int) -> dict[str, Any]:
    """Every count of one election. `read(manifest, pattern, columns)` restricts to the half."""
    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$", CV_COLUMNS)
    turnout = read("tse_results", rf"turnout_{year}\.parquet$", TURNOUT_COLUMNS)
    coalitions = read("tse_parties", rf"coalitions_{year}\.parquet$", COALITION_COLUMNS)
    now = cands.filter(pl.col("ano_eleicao") == year)
    pairs, main = close_pairs_025(cv, turnout, year)
    mayors, mayor_counts = elected_mayor(cv, main, year)
    coalition, coalition_counts = mayor_coalition(mayors, now, coalitions, main)
    counts = pair_types(pairs, council_parties(now, main), coalition, year)
    check_year(year, pairs.height, counts)
    return {"close_pairs": pairs.height, **counts, **mayor_counts, **coalition_counts}


# --- Loading candidates

SUM_KEYS = (*KINDS, "close_pairs", "sides_not_matched", "mayors", "runoff", "ties", "not_eleito")
SUM_KEYS += ("mayors_without_main_row", "coalitions_without_rows")


def load_candidates(store: GCSStore, tmp: Path, half: frozenset[str]) -> pl.DataFrame:
    """Council and mayoral candidacies 2008-2024 of the exploration half; only `CAND_COLUMNS`."""
    files = {}
    for name, pattern in (
        ("tse_candidates", r"candidates\.parquet$"),
        ("municipalities", r"municipalities\.parquet$"),
    ):
        remote = census._paths(name, pattern)[0]
        files[name] = tmp / Path(remote).name
        store.download(remote, files[name])
    cands = pl.read_parquet(files["tse_candidates"], columns=CAND_COLUMNS).filter(
        pl.col("ano_eleicao").is_in(list(ELECTIONS)) & (_cargo(COUNCIL) | _cargo(MAYOR))
    )
    munis = pl.read_parquet(files["municipalities"], columns=["cd_ibge", "cd_tse"])
    files["tse_candidates"].unlink()
    files["municipalities"].unlink()
    joined, _ = wn.with_ibge(cands, munis)
    return restrict(joined, half)


# --- Report


def pooled(per_election: dict[str, dict[str, Any]], years: tuple[int, ...]) -> dict[str, int]:
    return {k: sum(int(per_election[str(y)][k]) for y in years) for k in SUM_KEYS}


def build_results(per_election: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every number of the report. There is no estimate of any kind in it."""
    all_years = pooled(per_election, ELECTIONS)
    to_2020 = pooled(per_election, POWER_ELECTIONS)
    n_a, n_u = to_2020["aligned"], to_2020["unaligned"]
    half = EXPECTED_POOLED_2008_2020 // 2
    return {
        "elections": list(ELECTIONS),
        "window": WINDOW,
        "per_election": per_election,
        "pooled_2008_2024": all_years,
        "pooled_2008_2020": to_2020,
        "kill_criterion_1": {
            "minimum_each": MIN_EACH,
            "met": all_years["aligned"] >= MIN_EACH and all_years["unaligned"] >= MIN_EACH,
        },
        "implied_power": {
            "formula": "Phi(K * sqrt((1/2328) / (1/n_a + 1/n_u)) - 1.96)",
            "K": K,
            "base_power": BASE_POWER,
            "base_pairs": EXPECTED_POOLED_2008_2020,
            "n_aligned_2008_2020": n_a,
            "n_unaligned_2008_2020": n_u,
            "power": implied_power(n_a, n_u),
            "even_split_best_case": implied_power(half, half),
        },
    }


def _summary(r: dict[str, Any]) -> str:
    p = r["pooled_2008_2024"]
    power = r["implied_power"]
    met = "met" if r["kill_criterion_1"]["met"] else "not met"
    lines = [
        f"Pooled 2008-2024: {p['aligned']:,} aligned, {p['unaligned']:,} unaligned, "
        f"{p['mixed']:,} mixed close pairs at 0.25%; kill criterion 1 (200 each) {met}; "
        f"implied power {power['power']:.3f}.",
        "",
        "## Close pairs at 0.25% by alignment with the elected mayor",
        "",
        "| Election | Close pairs | Aligned | Unaligned | Mixed | Left out (side) "
        "| Left out (mayor) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = {
        **r["per_election"],
        "2008-2024": r["pooled_2008_2024"],
        "2008-2020": r["pooled_2008_2020"],
    }
    for name, c in rows.items():
        lines.append(
            f"| {name} | {c['close_pairs']:,} | {c['aligned']:,} | {c['unaligned']:,} "
            f"| {c['mixed']:,} | {c['left_out_side']:,} | {c['left_out_mayor']:,} |"
        )
    lines += [
        "",
        "## Counts, per election",
        "",
        "| Election | Run-off rounds | Mayoral ties | Mayors not ELEITO | Mayors without a "
        "main-election row | Coalitions with no rows | Sides not matched |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, c in {**r["per_election"], "2008-2024": r["pooled_2008_2024"]}.items():
        lines.append(
            f"| {name} | {c['runoff']:,} | {c['ties']:,} | {c['not_eleito']:,} "
            f"| {c['mayors_without_main_row']:,} | {c['coalitions_without_rows']:,} "
            f"| {c['sides_not_matched']:,} |"
        )
    lines += [
        "",
        "## Implied power (a rough scaling, not a computation on outcomes)",
        "",
        f"Power = {power['formula']}, with K = 1.96 + Phi^-1({power['base_power']}) = "
        f"{power['K']:.4f}, 2,328 pairs (decision 0008, 2008-2020) and n_a, n_u the aligned "
        f"and unaligned pairs of 2008-2020 ({power['n_aligned_2008_2020']:,} and "
        f"{power['n_unaligned_2008_2020']:,}): **{power['power']:.3f}**. Even split "
        f"(1,164 and 1,164), the best case: {power['even_split_best_case']:.3f}.",
        "",
        "## Caveats",
        "",
        "- Exploration half only.",
        "- Alignment is fixed by the mayoral race of the same election; it is not randomised.",
        "- The power scales decision 0008's direct power by the groups' pair counts; it is not "
        "a computation.",
        "- No lineage across elections: alignment is within one election.",
        "- A pair with a side or a mayor that does not match is left out (side first), never "
        "counted as unaligned.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    per_election: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        read = wn.make_reader(store, Path(tmp), half)
        cands = load_candidates(store, Path(tmp), half)
        for year in ELECTIONS:
            per_election[str(year)] = election_counts(read, cands, year)
    results = build_results(per_election)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
