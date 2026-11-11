"""Feasibility counts for the gold-and-the-ballot design, with no outcome data (idea 0007).

Can idea 0007 (`research/ideas/0007-gold-and-the-ballot.md`) carry a municipality panel? On the
national exploration half (decision 0011) this script only counts: how many municipalities have
gold in their geology (`geo_exposed`) and in how many states; how many gold titles carry a request
year; how many close council pairs (margin at most 0.50%, decisions 0004 and 0008) fall in exposed
municipalities; how many council candidates list a mining occupation (pooled, never split by
exposure); and the range of the real gold price. It writes the four fields that the kill rules k1-k4
of campaign step s9 read (`research/campaigns/0007-gold-and-the-ballot/campaign.md`, step s8):
`exposure.n_munis_exposed`, `exposure.n_states_10plus`, `titles.share_dated` and
`exposure.top_state_share`.

It reads three datasets and no other: `gold_exposure` (`gold_exposure.parquet` and
`gold_prices.parquet`), `tse_results` (`candidate_votes_<y>.parquet` and `turnout_<y>.parquet`) and
`tse_candidates` (occupation columns only; never a CPF, a voter ID or a name). It reads no
`mining_panel`, no `politics_panel`, no MapBiomas and no SIM data. No outcome data, no estimate.

Definitions: exposure is `geo_exposed`; `title_exposed` is a pre-2000 gold title. A title that
spans two municipalities counts in both. Close pairs come from `terrain.strongholds` exactly as in
`explore/0006_feasibility.py` (`main_election`, `candidacy_votes`, `within_list_pairs`,
`valid_votes`, `margins`, `close_pairs`). Candidates have no `cd_ibge`, only the TSE code `sg_ue`
(`data/contracts/tse_candidates.md`); it is mapped to `cd_ibge` with the distinct pairs of that
year's `candidate_votes`, and the candidates left unmatched (or outside the half) are counted.
Candidate counts include supplementary elections of the same year.

`gold_prices` has no `cd_ibge`: it is a national, treatment-side series, so it is read without
`restrict` (which would raise). Every table with a `cd_ibge` is restricted to the exploration half
before anything is counted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    candidacy_votes,
    close_pairs,
    main_election,
    margins,
    valid_votes,
    within_list_pairs,
)

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = REPO / "data" / "manifests" / "build"

WINDOW = 0.005
PAIR_ELECTIONS = (2008, 2012, 2016, 2020, 2024)
CANDIDATE_ELECTIONS = (2000, 2004, 2008, 2012, 2016, 2020, 2024)
COUNCIL = 13
MINING_CODES = (605, 253)  # GARIMPEIRO; TRABALHADOR DE MINAS E PEDREIRAS...
PRICE_YEARS = (1985, 2025)
STATE_MIN = 10

CV_COLUMNS = [
    "cd_cargo",
    "nr_turno",
    "cd_eleicao",
    "cd_sit_tot_turno",
    "sq_coligacao",
    "sg_ue",
    "sq_candidato",
    "qt_votos_nominais",
    "cd_ibge",
]
MAP_COLUMNS = ["sg_ue", "cd_ibge"]
TURNOUT_COLUMNS = [
    "cd_cargo",
    "nr_turno",
    "cd_eleicao",
    "sg_ue",
    "cd_ibge",
    "qt_total_votos_validos",
]
EXPOSURE_COLUMNS = [
    "cd_ibge",
    "uf",
    "geo_exposed",
    "title_exposed",
    "title_n_gold",
    "title_n_gold_dated",
    "title_n_gold_pre2000",
    "title_n_garimpo_pre2000",
]
PRICE_COLUMNS = ["year", "gold_real"]
CANDIDATE_COLUMNS = ["ano_eleicao", "sg_ue", "cd_cargo", "cd_ocupacao", "ds_ocupacao"]

Read = Callable[[str, str, list[str]], pl.DataFrame]


# --- Counts


def exposure_counts(exposure: pl.DataFrame) -> dict[str, Any]:
    """The `exposure.*` keys from the exploration-half rows of `gold_exposure`."""
    exposed = exposure.filter(pl.col("geo_exposed").fill_null(False))
    by_state = (
        exposed.group_by("uf").agg(pl.len().alias("n")).sort(["n", "uf"], descending=[True, False])
    )
    counts = {r["uf"]: int(r["n"]) for r in by_state.iter_rows(named=True)}
    n_exposed = exposed.height
    top_state, top_n = next(iter(counts.items())) if counts else ("none", 0)
    return {
        "n_munis_exposed": n_exposed,
        "n_states_10plus": sum(1 for n in counts.values() if n >= STATE_MIN),
        "top_state_share": 1.0 if n_exposed == 0 else top_n / n_exposed,
        "top_state": top_state,
        "by_state": dict(sorted(counts.items())),
        "n_munis_title_exposed": int(exposure["title_exposed"].fill_null(False).sum()),
        "n_munis_both": exposure.filter(
            pl.col("geo_exposed").fill_null(False) & pl.col("title_exposed").fill_null(False)
        ).height,
        "n_munis_half": exposure.height,
    }


def title_counts(exposure: pl.DataFrame) -> dict[str, Any]:
    """The `titles.*` keys. A title spanning two municipalities counts in both."""
    total = int(exposure["title_n_gold"].fill_null(0).sum())
    dated = int(exposure["title_n_gold_dated"].fill_null(0).sum())
    return {
        "share_dated": 0.0 if total == 0 else dated / total,
        "n_pre2000": int(exposure["title_n_gold_pre2000"].fill_null(0).sum()),
        "n_garimpo_pre2000": int(exposure["title_n_garimpo_pre2000"].fill_null(0).sum()),
    }


def election_pairs(cv: pl.DataFrame, turnout: pl.DataFrame, year: int) -> pl.DataFrame:
    """Close council pairs (margin at most 0.50%) of one election, as `0006` loads them."""
    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    return close_pairs(paired, WINDOW)


def pairs_in(pairs: pl.DataFrame, exposed: frozenset[str]) -> int:
    """Close pairs whose municipality is in `exposed`."""
    return pairs.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(sorted(exposed))).height


def _plain(text: str) -> str:
    """Upper case with accents removed."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def _year_keys(years: tuple[int, ...]) -> list[str]:
    return [f"y{y}" for y in years]


def occupation_counts(cands: pl.DataFrame, years: tuple[int, ...]) -> dict[str, dict[str, int]]:
    """Council candidates of the half, by year: code 605 or 253, and 'GARIMPEIRO' in the text.

    `cands` holds only candidates already matched to the exploration half, with `ano_eleicao`,
    `cd_cargo`, `cd_ocupacao`, `ds_ocupacao`. Pooled over municipalities, never split by exposure.
    """
    council = cands.filter(pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
    texts = council["ds_ocupacao"].drop_nulls().unique().to_list()
    garimpeiro = sorted(t for t in texts if "GARIMPEIRO" in _plain(t))
    flagged = council.with_columns(
        pl.col("cd_ocupacao").cast(pl.Int64, strict=False).is_in(list(MINING_CODES)).alias("_code"),
        pl.col("ds_ocupacao").is_in(garimpeiro).alias("_desc"),
    )
    out: dict[str, dict[str, int]] = {"n_mining_occupation": {}, "n_desc_garimpeiro": {}}
    for year in years:
        rows = flagged.filter(pl.col("ano_eleicao") == year)
        out["n_mining_occupation"][f"y{year}"] = int(rows["_code"].fill_null(False).sum())
        out["n_desc_garimpeiro"][f"y{year}"] = int(rows["_desc"].fill_null(False).sum())
    return out


def match_candidates(
    cands: pl.DataFrame, sg_map: pl.DataFrame, year: int, half: frozenset[str]
) -> tuple[pl.DataFrame, int, int]:
    """(council candidates of `year` in the half, how many matched, how many did not).

    `sg_map` is the distinct (`sg_ue`, `cd_ibge`) pairs of that year's `candidate_votes`, already
    restricted to the half. A candidate whose `sg_ue` is not in it is unmatched (or outside).
    """
    council = cands.filter(
        (pl.col("ano_eleicao") == year)
        & (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
    ).with_columns(pl.col("sg_ue").cast(pl.Utf8))
    lookup = (
        sg_map.select(pl.col("sg_ue").cast(pl.Utf8), pl.col("cd_ibge").cast(pl.Utf8))
        .sort(["sg_ue", "cd_ibge"])
        .unique("sg_ue", keep="first")
    )
    joined = restrict(council.join(lookup, on="sg_ue", how="inner"), half)
    return joined, joined.height, council.height - joined.height


def price_stats(prices: pl.DataFrame) -> dict[str, Any]:
    """The `price.*` keys over the years 1985-2025."""
    low, high = PRICE_YEARS
    rows = prices.filter(pl.col("year").is_between(low, high)).sort("year")
    if rows.is_empty():
        raise ValueError(f"gold_prices has no year from {low} to {high}")
    lowest = rows.sort(["gold_real", "year"]).row(0, named=True)
    highest = rows.sort(["gold_real", "year"], descending=[True, False]).row(0, named=True)
    return {
        "n_years": rows.height,
        "first_year": int(rows["year"].min()),
        "last_year": int(rows["year"].max()),
        "min_real": float(lowest["gold_real"]),
        "max_real": float(highest["gold_real"]),
        "min_year": int(lowest["year"]),
        "max_year": int(highest["year"]),
    }


def _floats(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [x for v in value.values() for x in _floats(v)]
    return []


def compute(
    exposure: pl.DataFrame,
    prices: pl.DataFrame,
    pairs: dict[int, pl.DataFrame],
    candidate_counts: dict[str, Any],
) -> dict[str, Any]:
    """Put the counts together. `exposure` and `pairs` are already restricted to the half."""
    exp = exposure_counts(exposure)
    exposed = frozenset(
        exposure.filter(pl.col("geo_exposed").fill_null(False))["cd_ibge"].cast(pl.Utf8).to_list()
    )
    by_year = {f"y{y}": pairs_in(pairs[y], exposed) for y in PAIR_ELECTIONS}
    results: dict[str, Any] = {
        "exposure": exp,
        "titles": title_counts(exposure),
        "pairs": {"n_050_exposed": sum(by_year.values()), "n_050_exposed_by_year": by_year},
        "candidates": candidate_counts,
        "price": price_stats(prices),
    }
    results["estimates"] = {"finite": all(math.isfinite(x) for x in _floats(results))}
    return results


def build_results(
    exposure: pl.DataFrame,
    prices: pl.DataFrame,
    cv: dict[int, pl.DataFrame],
    turnout: dict[int, pl.DataFrame],
    cands: pl.DataFrame,
    half: frozenset[str],
) -> dict[str, Any]:
    """Restrict every table with a `cd_ibge` to the half, then count.

    `cv` has an entry for every candidate election year (for the `sg_ue` map); `turnout` for
    the pair years. `prices` has no `cd_ibge` and is national, so it is not restricted.
    """
    exposure = restrict(exposure, half)
    cv = {year: restrict(frame, half) for year, frame in cv.items()}
    turnout = {year: restrict(frame, half) for year, frame in turnout.items()}
    pairs = {year: election_pairs(cv[year], turnout[year], year) for year in PAIR_ELECTIONS}
    unmatched, mining, garimpeiro = {}, {}, {}
    for year in CANDIDATE_ELECTIONS:
        rows, _, n_out = match_candidates(cands, cv[year], year, half)
        unmatched[f"y{year}"] = n_out
        counts = occupation_counts(rows, (year,))
        mining.update(counts["n_mining_occupation"])
        garimpeiro.update(counts["n_desc_garimpeiro"])
    candidate_counts = {
        "n_mining_occupation": mining,
        "n_desc_garimpeiro": garimpeiro,
        "n_council_not_in_half": unmatched,
    }
    return compute(exposure, prices, pairs, candidate_counts)


# --- Summary


def _rows(title: str, header: tuple[str, str], rows: list[tuple[str, Any]]) -> list[str]:
    lines = [f"### {title}", "", f"| {header[0]} | {header[1]} |", "| --- | --- |"]
    for label, value in rows:
        text = (
            f"{value:,}"
            if isinstance(value, int)
            else (f"{value:.4g}" if isinstance(value, float) else str(value))
        )
        lines.append(f"| {label} | {text} |")
    return [*lines, ""]


def _summary(results: dict[str, Any]) -> str:
    e, t, p = results["exposure"], results["titles"], results["pairs"]
    c, pr = results["candidates"], results["price"]
    lines = ["## Feasibility of idea 0007 (national exploration half; counts only)", ""]
    lines += _rows(
        "Exposure (municipalities)",
        ("Count", "Municipalities"),
        [
            ("With gold in the geology (`geo_exposed`)", e["n_munis_exposed"]),
            (f"States with at least {STATE_MIN} of them", e["n_states_10plus"]),
            (f"Share in the largest state ({e['top_state']})", e["top_state_share"]),
            ("With a pre-2000 gold title (`title_exposed`)", e["n_munis_title_exposed"]),
            ("With both", e["n_munis_both"]),
            ("In the exploration half and in `gold_exposure`", e["n_munis_half"]),
        ],
    )
    lines += _rows(
        "Exposed municipalities by state",
        ("State", "Municipalities"),
        list(e["by_state"].items()),
    )
    lines += _rows(
        "Gold titles",
        ("Count", "Value"),
        [
            ("Share of gold titles with a request year", t["share_dated"]),
            ("Pre-2000 gold titles", t["n_pre2000"]),
            ("Pre-2000 garimpo titles", t["n_garimpo_pre2000"]),
        ],
    )
    lines += ["A title that spans two municipalities counts in both.", ""]
    lines += _rows(
        "Close council pairs (margin at most 0.50%) in exposed municipalities",
        ("Election", "Pairs"),
        [*((k[1:], v) for k, v in p["n_050_exposed_by_year"].items()), ("All", p["n_050_exposed"])],
    )
    years = list(c["n_mining_occupation"])
    lines += [
        "### Council candidates with a mining occupation (pooled; not split by exposure)",
        "",
        "| Election | Code 605 or 253 | Text has GARIMPEIRO | Not matched to the half |",
        "| --- | --- | --- | --- |",
    ]
    for y in years:
        lines.append(
            f"| {y[1:]} | {c['n_mining_occupation'][y]:,} | {c['n_desc_garimpeiro'][y]:,} | "
            f"{c['n_council_not_in_half'][y]:,} |"
        )
    lines += [
        "",
        "Candidate counts include supplementary elections of the same year. Candidates whose "
        "`sg_ue` has no `candidate_votes` row in the half are counted as not matched.",
        "",
    ]
    lines += _rows(
        "Real gold price (2024 USD per troy ounce)",
        ("Count", "Value"),
        [
            ("Years", pr["n_years"]),
            ("First year", pr["first_year"]),
            ("Last year", pr["last_year"]),
            ("Lowest", f"{pr['min_real']:.4g} ({pr['min_year']})"),
            ("Highest", f"{pr['max_real']:.4g} ({pr['max_year']})"),
        ],
    )
    lines.append("No outcome data was read, and nothing was estimated.")
    return "\n".join(lines)


# --- Reading from GCS


def _paths(manifest: str, pattern: str) -> list[str]:
    data = json.loads((MANIFESTS / f"{manifest}.json").read_text(encoding="utf-8"))
    hits = sorted(f["path"] for f in data["files"] if re.search(pattern, f["path"]))
    if not hits:
        raise SystemExit(f"{manifest}: no file matches {pattern}")
    return hits


def make_reader(store: GCSStore, tmp: Path) -> Read:
    """A reader of one built file with named columns; the caller restricts."""

    def read(manifest: str, pattern: str, columns: list[str]) -> pl.DataFrame:
        remote = _paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = pl.read_parquet(local, columns=columns)
        local.unlink()
        return frame

    return read


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:
        read = make_reader(store, Path(tmp))
        exposure = read("gold_exposure", r"gold_exposure\.parquet$", EXPOSURE_COLUMNS)
        prices = read("gold_exposure", r"gold_prices\.parquet$", PRICE_COLUMNS)
        cands = read("tse_candidates", r"candidates\.parquet$", CANDIDATE_COLUMNS)
        cv, turnout = {}, {}
        for year in CANDIDATE_ELECTIONS:
            columns = CV_COLUMNS if year in PAIR_ELECTIONS else MAP_COLUMNS
            cv[year] = read("tse_results", rf"candidate_votes_{year}\.parquet$", columns)
            if year in PAIR_ELECTIONS:
                turnout[year] = read("tse_results", rf"turnout_{year}\.parquet$", TURNOUT_COLUMNS)
    results = build_results(exposure, prices, cv, turnout, cands, half)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
