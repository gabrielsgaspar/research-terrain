"""Coverage, counts, power and placebo of IBAMA enforcement near close-pair strongholds (idea 0005).

Can the enforcement outcome be studied at all? Before any post-election year is read, this
script measures, on the exploration half and in pre-election years only: how well IBAMA records
are located inside their own municipality (`coverage`), how many located flora fines and
embargoes fall in the cells exposed to close pairs at the 0.50% window (`counts`), the minimum
detectable effect at 80% power as a share of the baseline mean at the 0.25% and 0.50% windows
(`power`, decision 0007), and the pre-election placebo at 0.50% (`placebo`).

The outcome Y of a cell for election E is `n_fines_flora + n_embargoes` of `cell_enforcement`
summed over E-4 .. E-1 (`pre_years`, fixed in code; the reader refuses any year from E on). A
cell reached by the exposure kernel but absent from `cell_enforcement` has Y = 0. Only the
direct slope is used: exposure `exp2` (decision 0004), recentred D / 2, municipality-by-election
fixed effects, pooled 2008-2020, randomisation inference by re-flipping each close pair (2,000
draws, seed 20261106). MDE slope = 2.8 x the SD of the slope over the draws; the share is that
slope x mean |D| over the exposed cells, divided by their mean Y (`pw.exposure_cells`).

The windows, pair terms, designs and randomisation inference are those of `0001_window.py`
(which loads `0001_power.py` and `0001_placebo.py`); they are loaded, not copied. This script
assembles the treatment inputs itself and reads no outcome file other than the enforcement
tables. No post-election quantity, no clearing, no clustered SE, no verdict on the kill rules.
Only exploration-half rows are read.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    CELL,
    candidacy_votes,
    cell_place_distances,
    locate_places,
    main_election,
    margins,
    place_candidate_votes,
    place_shares,
    place_totals,
    valid_votes,
    within_list_pairs,
)

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


wn = _load("enforcement_window", "0001_window.py")
pw = wn.pw
pb = wn.pb

ELECTIONS = (2008, 2012, 2016, 2020)
WINDOW_025 = 0.0025
WINDOW_050 = 0.005
DRAWS = wn.DRAWS
SEED = wn.SEED
MIN_SHARE = 0.5  # an election is usable when at least half of its records are located
CELL_COLUMNS = ["nome_1KM", "cd_ibge", "n_fines_flora", "n_embargoes"]
MUNI_COLUMNS = [
    "cd_ibge",
    "n_fines_flora_all",
    "n_fines_flora_located",
    "n_embargoes_all",
    "n_embargoes_located",
]
KINDS = {"cell": CELL_COLUMNS, "muni": MUNI_COLUMNS}

Read = Callable[..., pl.DataFrame]
ReadMany = Callable[[str, str], list[pl.DataFrame]]


# --- Years and the enforcement reader


def pre_years(election: int) -> list[int]:
    """The only outcome years read for `election`: E-4 .. E-1."""
    return list(range(election - 4, election))


def enforcement_year(read: Read, kind: str, election: int, year: int) -> pl.DataFrame:
    """One enforcement table (`kind` is "cell" or "muni") of `year`; never a year from E on."""
    if year not in pre_years(election):
        raise ValueError(f"year {year} is not before election {election}")
    pattern = rf"{kind}_enforcement_{year}\.parquet$"
    return read("cell_enforcement", pattern, KINDS[kind])


def read_pre(read: Read, kind: str, election: int) -> dict[int, pl.DataFrame]:
    """The `kind` tables of `pre_years(election)` and no other year."""
    return {y: enforcement_year(read, kind, election, y) for y in pre_years(election)}


# --- Outcome and coverage


def pre_y(cells_by_year: dict[int, pl.DataFrame], election: int) -> pl.DataFrame:
    """(`nome_1KM`, `Y`): flora fines plus embargoes over E-4 .. E-1; cells without a row have 0."""
    if sorted(cells_by_year) != pre_years(election):
        raise ValueError(
            f"outcome years must be {pre_years(election)}, got {sorted(cells_by_year)}"
        )
    stacked = pl.concat(
        [
            f.select(
                "nome_1KM",
                (
                    pl.col("n_fines_flora").cast(pl.Float64).fill_null(0.0)
                    + pl.col("n_embargoes").cast(pl.Float64).fill_null(0.0)
                ).alias("Y"),
            )
            for f in cells_by_year.values()
        ]
    )
    return stacked.group_by("nome_1KM").agg(pl.col("Y").sum()).sort("nome_1KM")


def coverage_share(muni_by_year: dict[int, pl.DataFrame], election: int) -> float | None:
    """Located / all flora fines plus embargoes over E-4 .. E-1; None if there are none."""
    if sorted(muni_by_year) != pre_years(election):
        raise ValueError(
            f"coverage years must be {pre_years(election)}, got {sorted(muni_by_year)}"
        )
    located = 0
    total = 0
    for f in muni_by_year.values():
        located += int(f["n_fines_flora_located"].sum() or 0) + int(
            f["n_embargoes_located"].sum() or 0
        )
        total += int(f["n_fines_flora_all"].sum() or 0) + int(f["n_embargoes_all"].sum() or 0)
    return None if total == 0 else located / total


def elections_ok(shares: dict[int, float | None]) -> int:
    """How many elections have a share of at least `MIN_SHARE`; a null share does not count."""
    return sum(1 for s in shares.values() if s is not None and s >= MIN_SHARE)


# --- Treatment inputs (the stronghold pieces of 0001, without any outcome table)


def treatment_inputs(
    cv: pl.DataFrame,
    turnout: pl.DataFrame,
    section_pieces: list[pl.DataFrame],
    places: pl.DataFrame,
    year: int,
) -> dict[str, Any]:
    """Pairs, their margins, place totals and shares, and located places of one election."""
    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    pairs, margin = wn.pair_index(paired)
    place_votes = pl.concat([place_candidate_votes(sv, main) for sv in section_pieces])
    totals = place_totals(place_votes)
    shares = place_shares(place_votes)
    pair_cands = pl.concat(
        [
            pairs.select("cd_eleicao", pl.col("w").alias("sq_candidato")),
            pairs.select("cd_eleicao", pl.col("l").alias("sq_candidato")),
        ]
    ).unique()
    shares = shares.join(pair_cands, on=["cd_eleicao", "sq_candidato"], how="semi")
    return {
        "pairs": pairs,
        "margin": margin,
        "totals": totals,
        "shares": shares,
        "located": locate_places(places),
    }


def load_election(read: Read, read_many: ReadMany, year: int) -> dict[str, Any]:
    """Everything one election gives: treatment inputs, pre-election Y and coverage."""
    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    places = read("polling_places", rf"polling_places_{year}\.parquet$")
    pieces = read_many("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$")
    out = treatment_inputs(cv, turnout, pieces, places, year)
    out["y_table"] = pre_y(read_pre(read, "cell", year), year)
    out["coverage"] = coverage_share(read_pre(read, "muni", year), year)
    return out


# --- The direct estimate in one window


def window_direct(
    inputs: dict[int, dict[str, Any]], grid: pl.DataFrame, threshold: float
) -> dict[str, Any] | None:
    """Observed direct slope on pre-election Y, its re-flip draws and the exposed cells.

    Pairs are the close pairs with |margin| at most `threshold`, renumbered from 0 in each
    election. Y is used in both outcome slots of `pw.make_part`; only the `Y4` slope is read.
    None if the window has no pair in any election.
    """
    parts = []
    total = 0
    for year in sorted(inputs):
        inp = inputs[year]
        pairs = inp["pairs"].filter(pl.Series(wn.window_mask(inp["margin"], threshold)))
        n = pairs.height
        total += n
        if n == 0:
            parts.append(wn.ef.empty_part(0, year))
            continue
        munis = pairs["cd_ibge"].unique().to_list()
        cells = grid.filter(pl.col("cd_ibge").is_in(munis))
        dist = cell_place_distances(cells.select(CELL), inp["located"])
        reached = wn.reached_cells(dist, inp["totals"])
        sample = (
            reached.join(cells.select("nome_1KM", *CELL), on=CELL, how="inner")
            .join(inp["y_table"], on="nome_1KM", how="left")
            .with_columns(
                pl.col("Y").fill_null(0.0).alias("Y4"), pl.col("Y").fill_null(0.0).alias("Y2")
            )
            .select(*CELL, "Y4", "Y2")
        )
        terms = pb.pair_terms(dist, inp["totals"], inp["shares"], pairs, "exp2")
        parts.append(pw.make_part(sample, {"beta": terms}, n, year))
    if total == 0:
        return None
    spec = pw.assemble("direct", parts)
    observed, sims = pw.run_ri({"direct": spec}, DRAWS, SEED)
    key = ("direct", "Y4", "beta")
    x_abs, y = pw.exposure_cells(spec, "beta", "Y4")
    return {"observed": observed[key], "draws": sims[key], "x_abs": x_abs, "y": y}


def mde_share(window: dict[str, Any] | None) -> float | None:
    """MDE as a share of baseline: 2.8 SD x mean |D| / mean Y over the exposed cells; else None."""
    if window is None or window["x_abs"].size == 0:
        return None
    mde = pw.mde_stats(window["draws"])["mde_sd"]
    if mde is None:
        return None
    pct = pw.pct_effect(mde, float(np.mean(window["x_abs"])), float(np.mean(window["y"])))
    if pct is None or not np.isfinite(pct) or pct <= 0:
        return None
    return float(pct / 100.0)


def pre_reach_actions(window: dict[str, Any] | None) -> int:
    """Y summed over the cells with D != 0 (the exposed cells); 0 if the window has no pair."""
    return 0 if window is None else int(round(float(np.sum(window["y"]))))


def placebo_p(window: dict[str, Any] | None) -> float | None:
    """Two-sided randomisation-inference p of the observed direct slope."""
    return None if window is None else pw.ri_p(window["observed"], window["draws"])


# --- Report


def build_results(
    shares: dict[int, float | None],
    window_025: dict[str, Any] | None,
    window_050: dict[str, Any] | None,
) -> dict[str, Any]:
    """Exactly the keys of the task, nested; a number that cannot be computed is null."""
    coverage: dict[str, Any] = {f"e{e}": {"share_geolocated": shares.get(e)} for e in ELECTIONS}
    coverage["elections_ok"] = elections_ok({e: shares.get(e) for e in ELECTIONS})
    return pw._clean(
        {
            "coverage": coverage,
            "counts": {"pre_reach_actions": pre_reach_actions(window_050)},
            "power": {
                "mde_share_025": mde_share(window_025),
                "mde_share_050": mde_share(window_050),
            },
            "placebo": {"ri_p_050": placebo_p(window_050)},
        }
    )


def compute(inputs: dict[int, dict[str, Any]], grid: pl.DataFrame) -> dict[str, Any]:
    """The results from the inputs of the elections."""
    shares = {e: inputs[e]["coverage"] for e in ELECTIONS if e in inputs}
    return build_results(
        shares, window_direct(inputs, grid, WINDOW_025), window_direct(inputs, grid, WINDOW_050)
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _summary(results: dict[str, Any]) -> str:
    cov = results["coverage"]
    lines = ["## Enforcement before the election, exploration half (pre-election years only)", ""]
    lines += ["| Election | Share located |", "| --- | --- |"]
    for e in ELECTIONS:
        lines.append(f"| {e} | {_fmt(cov[f'e{e}']['share_geolocated'])} |")
    lines += [
        "",
        f"Elections with at least half located: {cov['elections_ok']} of {len(ELECTIONS)}.",
        f"Located pre-election actions in the cells exposed at 0.50%: "
        f"{results['counts']['pre_reach_actions']:,}.",
        f"MDE as a share of baseline, 0.25% window: {_fmt(results['power']['mde_share_025'])}.",
        f"MDE as a share of baseline, 0.50% window: {_fmt(results['power']['mde_share_050'])}.",
        f"Pre-election placebo at 0.50%, randomisation-inference p: "
        f"{_fmt(results['placebo']['ri_p_050'])}.",
        "",
        "Caveats: exploration half; Y is flora fines plus embargoes in E-4 .. E-1; a cell "
        "absent from the enforcement table counts 0; the MDE is 2.8 SD of the direct slope "
        f"over {DRAWS:,} re-flips (seed {SEED}). No verdict on the kill rules.",
    ]
    return "\n".join(lines)


# --- Reading from GCS


def make_readers(store: GCSStore, tmp: Path, half: frozenset[str]) -> tuple[Read, ReadMany]:
    """A reader of one built file and of all files matching a pattern, exploration half only."""
    read = wn.make_reader(store, tmp, half)

    def read_many(manifest: str, pattern: str) -> list[pl.DataFrame]:
        frames = []
        for remote in wn.census._paths(manifest, pattern):
            local = tmp / Path(remote).name
            store.download(remote, local)
            frames.append(restrict(pl.read_parquet(local), half))
            local.unlink()
        return frames

    return read, read_many


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    with tempfile.TemporaryDirectory() as tmp:
        read, read_many = make_readers(store, Path(tmp), half)
        grid = read("grid_cells", r"grid_cells\.parquet$", wn.GRID_COLUMNS).with_columns(
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("x_km").cast(pl.Int64),
            pl.col("y_km").cast(pl.Int64),
        )
        inputs = {year: load_election(read, read_many, year) for year in ELECTIONS}
    results = compute(inputs, grid)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
