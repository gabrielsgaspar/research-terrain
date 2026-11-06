"""Kill criterion 2 of idea 0001: the pre-election placebo, exploration half.

Does stronghold exposure to the close council races of election E predict clearing in
the four years before E (E-4 to E-1)? Outcome `Y_iE`: the sum over those years of
`code_4 / 10,000` from `cell_outcomes` (loss of primary vegetation as a share of the
cell; decision 0006). Exposure: the recentred `D_i / 2` of decision 0004, for `exp2`
(decisive), `ring2` and `ring5`. Estimate: OLS with municipality-by-election fixed
effects, pooled over 2008-2024 and per election. Inference: randomisation inference that
flips each close pair independently (2,000 draws, seed 20261106); the
municipality-clustered standard error of pooled `exp2` is reported as a check.

The pair terms `t_ip` are computed as `strongholds.exposure` computes `D_i` but grouped by
cell and pair, so that the sum over pairs equals `D_i`; the script stops if it does not
match `cell_exposure`. The census script `0001_feasibility_census.py` is loaded for paths.
Only exploration-half cells are read.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    CELL,
    KERNELS,
    PLACE_KEY,
    TOLERANCE,
    candidacy_votes,
    cell_place_distances,
    close_pairs,
    kernel,
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
_SPEC = importlib.util.spec_from_file_location(
    "feasibility_census", _REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

YEARS = census.YEARS
SEED = 20261106
DRAWS = 2000
KC_P = 0.05
LAG = 4  # pre-election years: E-4 .. E-1


# --- Pair terms


def pair_terms(
    dist: pl.DataFrame,
    totals: pl.DataFrame,
    shares: pl.DataFrame,
    pairs: pl.DataFrame,
    kernel_name: str,
) -> pl.DataFrame:
    """(CELL, `pair_id`, `t`): each pair's term of `D_i`, share measure.

    The same as `strongholds.exposure` (`pair_id` is the row index of `pairs`), grouped by
    cell and pair, and divided by the cell's `sum_k` over all its places with votes, so
    that the sum of `t` over a cell's pairs is `D_i`. Pairs with no term at a cell have no row.
    """
    near = (
        dist.join(totals.select(PLACE_KEY).unique(), on=PLACE_KEY, how="semi")
        .with_columns(kernel(kernel_name, pl.col("d")).alias("k"))
        .filter(pl.col("k") > 0)
    )
    sum_k = near.group_by(CELL).agg(pl.col("k").sum().alias("sum_k"))
    pair_rows = pairs.with_row_index("pair_id")
    rows = near.join(
        pair_rows.select("pair_id", "cd_ibge", "sg_ue", "cd_eleicao", "w", "l"),
        on=["cd_ibge", "sg_ue"],
    )
    lookup = shares.select(*PLACE_KEY, "cd_eleicao", "sq_candidato", pl.col("s_cp").alias("a"))
    keys = [*PLACE_KEY, "cd_eleicao"]
    for side in ("w", "l"):
        side_lookup = lookup.rename({"sq_candidato": side, "a": f"a_{side}"})
        rows = rows.join(side_lookup, on=[*keys, side], how="left")
    term = pl.col("k") * (pl.col("a_w").fill_null(0.0) - pl.col("a_l").fill_null(0.0))
    return (
        rows.group_by([*CELL, "pair_id"])
        .agg(term.sum().alias("term"))
        .join(sum_k, on=CELL)
        .select(*CELL, "pair_id", (pl.col("term") / pl.col("sum_k")).alias("t"))
        .sort([*CELL, "pair_id"])
    )


def check_terms(terms: pl.DataFrame, cell_exposure: pl.DataFrame, kernel_name: str) -> None:
    """Stop unless the pair terms of every cell add up to `d_<kernel>` of `cell_exposure`.

    Checked for the reached cells (`d_<kernel>` not null) with `n_pairs` > 0; a reached
    cell with no term counts as 0. A term at a cell that is not checked is a mismatch too.
    """
    column = f"d_{kernel_name}"
    summed = terms.group_by(CELL).agg(pl.col("t").sum().alias("t_sum"))
    checked = cell_exposure.filter((pl.col("n_pairs") > 0) & pl.col(column).is_not_null())
    joined = checked.select(*CELL, column).join(summed, on=CELL, how="full", coalesce=True)
    diff = (pl.col("t_sum").fill_null(0.0) - pl.col(column).fill_null(0.0)).abs()
    bad = joined.filter(diff > TOLERANCE)
    if bad.height:
        raise SystemExit(
            f"{kernel_name}: the pair terms differ from {column} in {bad.height} cells "
            f"(largest difference {bad.select(diff.max()).item():.3g})"
        )


# --- Outcome


def pre_election_outcome(
    outcomes_by_year: dict[int, pl.DataFrame], election: int
) -> tuple[pl.DataFrame, int]:
    """`Y` per `nome_1KM` for `election`, and the number of cells dropped.

    `Y` is the sum of `code_4 / 10,000` over the years E-4 to E-1. A cell is kept only if
    it appears in all four years with `has_data` true; the others are dropped and counted.
    """
    years = list(range(election - LAG, election))
    missing = [y for y in years if y not in outcomes_by_year]
    if missing:
        raise ValueError(f"no outcome for years {missing}")
    stacked = pl.concat(
        [
            outcomes_by_year[y].select(
                "nome_1KM",
                pl.lit(y, dtype=pl.Int64).alias("yr"),
                pl.col("has_data").fill_null(False).alias("ok"),
                (pl.col("code_4").cast(pl.Float64) / 10_000).alias("v"),
            )
            for y in years
        ]
    )
    per_cell = stacked.group_by("nome_1KM").agg(
        pl.len().alias("n"),
        pl.col("yr").n_unique().alias("n_years"),
        pl.col("ok").all().alias("ok"),
        pl.col("v").sum().alias("Y"),
    )
    kept = per_cell.filter((pl.col("n") == LAG) & (pl.col("n_years") == LAG) & pl.col("ok"))
    return kept.select("nome_1KM", "Y").sort("nome_1KM"), per_cell.height - kept.height


# --- Design, estimate, inference


@dataclass
class Design:
    """The regression sample in arrays, with the demeaned terms kept per pair.

    Per cell: `y_tilde` (Y demeaned within municipality and election), `group` (the
    municipality-election), `election` and `muni`. Terms: cell `rows`, pair `cols` and
    `vals` = t / 2, so the recentred exposure of the cell is `sum(vals * s[cols])` for a
    sign vector `s` over pairs (+1 as observed, -1 for a flipped pair). The exposure is
    demeaned within the group only where it enters (`demeaned_exposure`).
    """

    y_tilde: np.ndarray
    group: np.ndarray
    election: np.ndarray
    muni: np.ndarray
    rows: np.ndarray
    cols: np.ndarray
    vals: np.ndarray
    n_pairs: int


def make_design(sample: pl.DataFrame, terms: pl.DataFrame, n_pairs: int, election: int) -> Design:
    """Build the design of one election.

    `sample` has CELL columns and `Y` (one row per cell); `terms` comes from `pair_terms`
    with `pair_id` below `n_pairs`. Terms at cells outside the sample are ignored.
    """
    cells = sample.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
        pl.col("Y").cast(pl.Float64),
    ).with_row_index("row")
    cells = cells.with_columns(
        (pl.col("cd_ibge").rank("dense").cast(pl.Int64) - 1).alias("group"),
        (pl.col("Y") - pl.col("Y").mean().over("cd_ibge")).alias("y_tilde"),
    )
    used = terms.with_columns(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    ).join(cells.select(*CELL, "row"), on=CELL, how="inner")
    return Design(
        y_tilde=cells["y_tilde"].to_numpy().astype(float),
        group=cells["group"].to_numpy().astype(np.int64),
        election=np.full(cells.height, election, dtype=np.int64),
        muni=cells["cd_ibge"].to_numpy(),
        rows=used["row"].to_numpy().astype(np.int64),
        cols=used["pair_id"].to_numpy().astype(np.int64),
        vals=used["t"].to_numpy().astype(float) / 2.0,
        n_pairs=n_pairs,
    )


def stack(designs: list[Design]) -> Design:
    """Concatenate designs, offsetting cells, groups and pairs so that none overlap."""
    cell_off = group_off = pair_off = 0
    parts: dict[str, list[np.ndarray]] = {
        k: [] for k in ("y_tilde", "group", "election", "muni", "rows", "cols", "vals")
    }
    for d in designs:
        parts["y_tilde"].append(d.y_tilde)
        parts["group"].append(d.group + group_off)
        parts["election"].append(d.election)
        parts["muni"].append(d.muni)
        parts["rows"].append(d.rows + cell_off)
        parts["cols"].append(d.cols + pair_off)
        parts["vals"].append(d.vals)
        cell_off += d.y_tilde.size
        group_off += int(d.group.max()) + 1 if d.group.size else 0
        pair_off += d.n_pairs
    return Design(
        y_tilde=np.concatenate(parts["y_tilde"]) if designs else np.zeros(0),
        group=np.concatenate(parts["group"]) if designs else np.zeros(0, dtype=np.int64),
        election=np.concatenate(parts["election"]) if designs else np.zeros(0, dtype=np.int64),
        muni=np.concatenate(parts["muni"]) if designs else np.zeros(0, dtype=str),
        rows=np.concatenate(parts["rows"]) if designs else np.zeros(0, dtype=np.int64),
        cols=np.concatenate(parts["cols"]) if designs else np.zeros(0, dtype=np.int64),
        vals=np.concatenate(parts["vals"]) if designs else np.zeros(0),
        n_pairs=pair_off,
    )


def exposure_for(design: Design, signs: np.ndarray) -> np.ndarray:
    """The recentred exposure `D_i / 2` of each cell for pair signs `signs` (+1 or -1)."""
    n = design.y_tilde.size
    return np.bincount(design.rows, weights=design.vals * signs[design.cols], minlength=n)


def demeaned_exposure(design: Design, signs: np.ndarray) -> np.ndarray:
    """`exposure_for`, demeaned within each municipality-election."""
    d = exposure_for(design, signs)
    if d.size == 0:
        return d
    n_groups = int(design.group.max()) + 1
    mean = np.bincount(design.group, weights=d, minlength=n_groups) / np.bincount(
        design.group, minlength=n_groups
    )
    return d - mean[design.group]


def beta(d_tilde: np.ndarray, y_tilde: np.ndarray) -> float | None:
    """OLS slope of demeaned Y on demeaned D: sum(D Y) / sum(D^2); None if D has no variance."""
    den = float(np.sum(d_tilde**2))
    return None if den <= 0 else float(np.sum(d_tilde * y_tilde) / den)


def _layout(design: Design, elections: tuple[int, ...]) -> dict[str, np.ndarray]:
    levels = np.array(sorted(elections))
    n_groups = int(design.group.max()) + 1 if design.group.size else 0
    group_election = np.zeros(n_groups, dtype=np.int64)
    group_election[design.group] = design.election
    return {
        "eidx": np.searchsorted(levels, design.election),
        "group_eidx": np.searchsorted(levels, group_election),
        "group_n": np.bincount(design.group, minlength=n_groups).astype(float),
    }


def _betas(design: Design, layout: dict[str, np.ndarray], signs: np.ndarray, k: int) -> np.ndarray:
    """[pooled, election 1, ...]: beta for the signs; nan where D has no variance."""
    d = exposure_for(design, signs)
    n_groups = layout["group_n"].size
    group_sum = np.bincount(design.group, weights=d, minlength=n_groups)
    num = np.bincount(layout["eidx"], weights=d * design.y_tilde, minlength=k)
    den = np.bincount(layout["eidx"], weights=d * d, minlength=k) - np.bincount(
        layout["group_eidx"], weights=group_sum**2 / np.maximum(layout["group_n"], 1.0), minlength=k
    )
    num = np.concatenate([[num.sum()], num])
    den = np.concatenate([[den.sum()], den])
    out = np.full(num.size, np.nan)
    np.divide(num, den, out=out, where=den > 1e-12)
    return out


def ri(
    design: Design,
    elections: tuple[int, ...] = YEARS,
    draws: int = DRAWS,
    seed: int = SEED,
) -> dict[str, dict[str, float | None]]:
    """Beta, its randomisation-inference p-value and 2.5% / 97.5% quantiles.

    Keys: "pooled" and each election (as text). Each draw flips every pair independently
    with probability 1/2; the sample and the demeaning stay as observed. p = (1 + #{|b_r|
    >= |b|}) / (1 + draws), two-sided. All estimates share the same draws.
    """
    layout = _layout(design, elections)
    k = len(elections)
    observed = _betas(design, layout, np.ones(design.n_pairs), k)
    rng = np.random.default_rng(seed)
    sims = np.empty((draws, k + 1))
    for r in range(draws):
        signs = rng.integers(0, 2, size=design.n_pairs).astype(float) * 2.0 - 1.0
        sims[r] = _betas(design, layout, signs, k)
    out: dict[str, dict[str, float | None]] = {}
    for j, label in enumerate(["pooled", *(str(e) for e in sorted(elections))]):
        b = observed[j]
        if np.isnan(b):
            out[label] = {"beta": None, "p": None, "q025": None, "q975": None}
            continue
        col = sims[:, j]
        finite = col[~np.isnan(col)]
        extreme = int(np.sum(np.abs(finite) >= abs(b)))
        out[label] = {
            "beta": float(b),
            "p": (1 + extreme) / (1 + draws),
            "q025": float(np.quantile(finite, 0.025)) if finite.size else None,
            "q975": float(np.quantile(finite, 0.975)) if finite.size else None,
        }
    return out


def clustered_se(d_tilde: np.ndarray, y_tilde: np.ndarray, muni: np.ndarray) -> float | None:
    """CR1 standard error of beta, clustered by municipality.

    var = G/(G-1) * sum_g (sum_i D_i e_i)^2 / (sum D^2)^2, with e the residual of the
    demeaned regression. The fixed effects are nested in the clusters, so they are not
    counted in the degrees of freedom, and the (N-1)/(N-K) term of CR1 is 1 with one slope.
    """
    den = float(np.sum(d_tilde**2))
    _, cluster = np.unique(muni, return_inverse=True)
    g = int(cluster.max()) + 1 if cluster.size else 0
    if den <= 0 or g < 2:
        return None
    b = float(np.sum(d_tilde * y_tilde) / den)
    score = np.bincount(cluster, weights=d_tilde * (y_tilde - b * d_tilde), minlength=g)
    var = g / (g - 1) * float(np.sum(score**2)) / den**2
    return float(np.sqrt(var))


# --- One year


def _counts(sample: pl.DataFrame, pairs: pl.DataFrame, dropped: int) -> dict[str, Any]:
    munis = set(sample["cd_ibge"].to_list())
    return {
        "cells": sample.height,
        "municipalities": len(munis),
        "pairs": pairs.filter(pl.col("cd_ibge").is_in(list(munis))).height,
        "cells_nonzero": sample.filter(pl.col("D") != 0).height,
        "cells_dropped": dropped,
        "sum_y": float(sample["Y"].sum()) if sample.height else 0.0,
    }


def _year(
    store: GCSStore, tmp: Path, half: frozenset[str], year: int
) -> dict[str, tuple[Design, dict[str, Any]]]:
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
    exposed = read("cell_exposure", rf"cell_exposure_{year}\.parquet$").with_columns(
        pl.col("cd_ibge").cast(pl.Utf8)
    )
    outcomes = {
        y: read(
            "cell_outcomes",
            rf"cell_outcomes_{y}\.parquet$",
            ["nome_1KM", "cd_ibge", "has_data", "code_4"],
        )
        for y in range(year - LAG, year)
    }
    main = main_election(cv)
    cands = candidacy_votes(cv, year, main)
    pairs = close_pairs(margins(within_list_pairs(cands), valid_votes(turnout, main)))

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = tmp / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(place_candidate_votes(sv, main))
    place_votes = pl.concat(pieces)
    totals = place_totals(place_votes)
    shares = place_shares(place_votes)

    with_pairs = exposed.filter(pl.col("n_pairs") > 0)
    dist = cell_place_distances(with_pairs.select(CELL), locate_places(places))
    y_table, _ = pre_election_outcome(outcomes, year)

    out: dict[str, tuple[Design, dict[str, Any]]] = {}
    for name in KERNELS:
        terms = pair_terms(dist, totals, shares, pairs, name)
        check_terms(terms, with_pairs, name)
        reached = with_pairs.filter(pl.col(f"d_{name}").is_not_null())
        sample = reached.join(y_table, on="nome_1KM", how="inner").with_columns(
            pl.col(f"d_{name}").alias("D")
        )
        counts = _counts(sample, pairs, reached.height - sample.height)
        out[name] = (make_design(sample, terms, pairs.height, year), counts)
    return out


# --- Report


def _pooled_counts(per_year: list[dict[str, Any]], n_munis: int) -> dict[str, Any]:
    cells = sum(c["cells"] for c in per_year)
    total_y = sum(c["sum_y"] for c in per_year)
    return {
        "cells": cells,
        "municipalities": n_munis,
        "pairs": sum(c["pairs"] for c in per_year),
        "cells_nonzero": sum(c["cells_nonzero"] for c in per_year),
        "cells_dropped": sum(c["cells_dropped"] for c in per_year),
        "mean_y": total_y / cells if cells else None,
    }


def report(
    designs: dict[int, Design],
    counts: dict[int, dict[str, Any]],
    draws: int = DRAWS,
    seed: int = SEED,
) -> dict[str, dict[str, Any]]:
    """Per label ("pooled", each election): counts, beta, RI p and quantiles for one kernel."""
    years = tuple(sorted(designs))
    total = stack([designs[y] for y in years])
    stats = ri(total, years, draws, seed)
    out: dict[str, dict[str, Any]] = {}
    for y in years:
        c = dict(counts[y])
        c["mean_y"] = c["sum_y"] / c["cells"] if c["cells"] else None
        del c["sum_y"]
        out[str(y)] = {**c, **stats[str(y)]}
    n_munis = int(np.unique(total.muni).size)
    out["pooled"] = {**_pooled_counts([counts[y] for y in years], n_munis), **stats["pooled"]}
    d_tilde = demeaned_exposure(total, np.ones(total.n_pairs))
    out["pooled"]["clustered_se"] = clustered_se(d_tilde, total.y_tilde, total.muni)
    return {label: out[label] for label in ["pooled", *(str(y) for y in years)]}


def _fmt(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _table(rows: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| Sample | Cells | Pairs | beta | RI p | Mean Y |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, r in rows.items():
        lines.append(
            f"| {label} | {r['cells']:,} | {r['pairs']:,} | {_fmt(r['beta'])} | {_fmt(r['p'])} "
            f"| {_fmt(r['mean_y'])} |"
        )
    return lines


def _summary(results: dict[str, dict[str, dict[str, Any]]]) -> str:
    lines = ["## Kill criterion 2: the pre-election placebo (exploration half)"]
    lines += [
        "",
        "Y = sum over the four years before the election of the share of the cell that lost "
        "primary vegetation; beta is the slope on the recentred exposure D/2 with "
        "municipality-by-election fixed effects. RI: 2,000 draws flipping each close pair "
        f"(seed {SEED}), two-sided.",
    ]
    for name in KERNELS:
        lines += ["", f"### {name}" + (" (decisive)" if name == "exp2" else ""), ""]
        lines += _table(results[name])
    pooled = results["exp2"]["pooled"]
    lines += [
        "",
        f"Pooled exp2: municipality-clustered SE of beta {_fmt(pooled['clustered_se'])}; "
        f"RI 2.5%-97.5% of beta {_fmt(pooled['q025'])} to {_fmt(pooled['q975'])}.",
        "",
    ]
    p = pooled["p"]
    if p is not None and p < KC_P:
        lines.append(f"Kill criterion 2 is met: pooled exp2 RI p = {p:.4f}, below {KC_P}.")
    else:
        lines.append(
            f"Kill criterion 2 is not met: pooled exp2 RI p = {_fmt(p)}, not below {KC_P}."
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    designs: dict[str, dict[int, Design]] = {k: {} for k in KERNELS}
    counts: dict[str, dict[int, dict[str, Any]]] = {k: {} for k in KERNELS}
    with tempfile.TemporaryDirectory() as tmp:
        for year in YEARS:
            for name, (design, c) in _year(store, Path(tmp), half, year).items():
                designs[name][year] = design
                counts[name][year] = c
    results = {name: report(designs[name], counts[name]) for name in KERNELS}
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
