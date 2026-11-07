"""Choosing the close-race window of idea 0001 by covariate balance, exploration half.

The design is a local randomisation design (Cattaneo, Frandsen and Titiunik 2015): the
window is the widest one in which narrow winners and narrow losers do not differ on
characteristics fixed before the election. This script tests balance in seven windows
(|margin| of 0.10% to 2.00% of valid council votes) on ten covariates, pooled over the
elections 2008-2024, with randomisation inference that flips each close pair (2,000
draws, seed 20261106, one sign matrix for every covariate and window). The omnibus p of a
window is read from the re-flip distribution of the minimum p. The rule, fixed in
`choose_window`: the widest window whose omnibus p is at least 0.15 with every narrower
window also at least 0.15; if 0.10% fails, no window is chosen. It also reports each
window's power at the effect size of decision 0007 (never used to choose).

Outcome data: only the years E-4 .. E-1 of each election E (`pre_years`) are read from
`cell_outcomes`, for the pre-election clearing covariate and for power. No year E or
later is read. Voter IDs are used in memory to build `incumbent` and reach no output.

The pair terms, side terms, components, designs and randomisation inference are those of
`0001_power.py` (loaded through `0001_effects.py`, not copied). Exploration half only.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    CELL,
    PLACE_KEY,
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
    stronghold_pairs,
    strongholds,
    unrepresented,
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


ef = _load("window_effects", "0001_effects.py")
pw = ef.pw
pb = pw.pb
kc1 = pw.kc1
census = pw.census

WINDOWS_PCT = (0.10, 0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
LABELS = tuple(f"{p:.2f}%" for p in WINDOWS_PCT)
THRESHOLDS = tuple(p / 100 for p in WINDOWS_PCT)
MAX_T = THRESHOLDS[-1]
EDGE = 1e-12  # a margin of t + 1e-12 counts as t
BALANCE = (
    "female",
    "age",
    "schooling",
    "incumbent",
    "seat_km",
    "place_seat",
    "place_town",
    "dist_indigenous_km",
    "dist_settlement_km",
    "clearing_pre",
)
DESCRIPTIVE = ("pop22_5km",)
COVARIATES = BALANCE + DESCRIPTIVE
ELECTIONS = (2008, 2012, 2016, 2020, 2024)
POWER_ELECTIONS = (2008, 2012, 2016, 2020)
DRAWS = 2000
SEED = 20261106
RULE_P = 0.15
MIN_PAIRS = 20
NO_WINDOW = "No window passes; Gabriel decides"
RTOL = 1e-9  # ties in the p-values are compared with a relative tolerance
CHUNK = 100
DISC_KM = 5.0
TOLERANCE = 1e-9
Z_TWO_SIDED = 1.96
Z_ONE_SIDED = 1.645
POWER_REFERENCE = "decision 0007: 0.94, 0.797, 0.45"
ELECTED_LABELS = ("ELEITO", "MÉDIA", "ELEITO POR QP", "ELEITO POR MÉDIA")
COUNCIL = 13
FIRST_CANDIDATE_YEAR = 2004
CAND3 = ["cd_eleicao", "sg_ue", "sq_candidato"]
CAND_COLUMNS = [
    "ano_eleicao",
    "cd_eleicao",
    "nr_turno",
    "cd_cargo",
    "sg_ue",
    "sq_candidato",
    "cd_genero",
    "dt_eleicao",
    "dt_nascimento",
    "cd_grau_instrucao",
    "nr_titulo_eleitoral_candidato",
    "ds_sit_tot_turno",
    "st_reeleicao",
]
OUTCOME_COLUMNS = ["nome_1KM", "cd_ibge", "has_data", "code_2", "code_4"]
GRID_COLUMNS = ["nome_1KM", "cd_ibge", "x_km", "y_km", "pop_2022"]


# --- Years and windows


def pre_years(election: int) -> list[int]:
    """The only outcome years read for `election`: E-4 .. E-1, fixed in code."""
    return list(range(election - 4, election))


def window_mask(margin: np.ndarray, threshold: float) -> np.ndarray:
    """Pairs of the window: |margin| at most `threshold` (+ 1e-12)."""
    return np.abs(margin) <= threshold + EDGE


def window_pair_ids(margin: np.ndarray, threshold: float) -> np.ndarray:
    """Ids (positions in the 2.00% numbering) of the pairs in the window."""
    return np.flatnonzero(window_mask(margin, threshold))


def pair_index(paired: pl.DataFrame) -> tuple[pl.DataFrame, np.ndarray]:
    """The year's `close_pairs` at 2.00% (id = row index) and the |margin| of each."""
    pairs = close_pairs(paired, MAX_T)
    keep = ~pl.col("inverted") & (pl.col("margin").abs() <= MAX_T + EDGE)
    margin = paired.filter(keep)["margin"].abs().to_numpy().astype(float)
    if margin.size != pairs.height:
        raise SystemExit("the pair index and its margins differ in length")
    return pairs, margin


# --- The rule


def choose_window(ps: Sequence[float | None], labels: Sequence[str] = LABELS) -> str:
    """The widest window with omnibus p >= 0.15 and every narrower window also >= 0.15.

    Once a window fails, no wider window counts. If the narrowest fails: `NO_WINDOW`.
    """
    chosen = None
    for label, p in zip(labels, ps, strict=True):
        if p is None or p < RULE_P:
            break
        chosen = label
    return NO_WINDOW if chosen is None else chosen


def rule_line(ps: Sequence[float | None], labels: Sequence[str] = LABELS) -> str:
    """The first line of the summary."""
    label = choose_window(ps, labels)
    if label == NO_WINDOW:
        return NO_WINDOW
    p = ps[list(labels).index(label)]
    return f"Chosen window: {label} (omnibus p {p:.3f})."


# --- Randomisation inference for balance


def sign_matrix(n_pairs: int, draws: int = DRAWS, seed: int = SEED) -> np.ndarray:
    """One row of +1 / -1 per draw, over all 2.00% pairs; shared by every covariate and window."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, size=(draws, n_pairs), dtype=np.int8) * 2 - 1


def flip_means(
    diff: np.ndarray, signs: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Observed mean difference, its mean under each draw, and the pairs used, per covariate.

    `diff` is (pairs, covariates) of winner - loser, nan for a null side. The window is
    `mask` over the pairs; a covariate averages over the pairs of the window with both
    sides known. A draw flips the sign of each pair's difference.
    """
    cols = np.flatnonzero(mask)
    block = diff[cols]
    valid = ~np.isnan(block)
    d0 = np.where(valid, block, 0.0)
    n = valid.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        observed = d0.sum(axis=0) / n
        draws = np.empty((signs.shape[0], diff.shape[1]))
        for start in range(0, signs.shape[0], CHUNK):
            part = signs[start : start + CHUNK][:, cols].astype(float)
            draws[start : start + CHUNK] = (part @ d0) / n
    return observed, draws, n


def raw_p(observed: np.ndarray, draws: np.ndarray) -> np.ndarray:
    """Two-sided p = (1 + #{r: |m_r| >= |m|}) / (1 + draws), nan where undefined."""
    extreme = np.sum(np.abs(draws) >= np.abs(observed) * (1 - RTOL), axis=0)
    p = (1 + extreme) / (1 + draws.shape[0])
    return np.where(np.isnan(observed), np.nan, p)


def omnibus_p(
    observed: np.ndarray,
    draws: np.ndarray,
    n: np.ndarray,
    use: np.ndarray,
    min_pairs: int = MIN_PAIRS,
) -> float | None:
    """Omnibus p from the re-flip distribution of the minimum p.

    For each draw r and covariate k, p_rk = #{s: |m_sk| >= |m_rk|} / draws; the omnibus p is
    (1 + #{r: min_k p_rk <= min_k p_k}) / (1 + draws). Covariates not in `use`, with fewer
    than `min_pairs` pairs, or undefined are left out. None if none is left.
    """
    ok = use & (n >= min_pairs) & ~np.isnan(observed)
    if not ok.any():
        return None
    r = draws.shape[0]
    smallest = float(np.min(raw_p(observed, draws)[ok]))
    magnitude = np.abs(draws[:, ok])
    p_draw = np.empty_like(magnitude)
    for j in range(magnitude.shape[1]):
        ordered = np.sort(magnitude[:, j])
        below = np.searchsorted(ordered, magnitude[:, j] * (1 - RTOL), side="left")
        p_draw[:, j] = (r - below) / r
    extreme = int(np.sum(p_draw.min(axis=1) <= smallest * (1 + RTOL)))
    return (1 + extreme) / (1 + r)


def balance_by_window(
    diff: np.ndarray,
    margin: np.ndarray,
    signs: np.ndarray,
    names: Sequence[str] = COVARIATES,
    thresholds: Sequence[float] = THRESHOLDS,
    labels: Sequence[str] = LABELS,
) -> list[dict[str, Any]]:
    """Per window: the difference, p and pairs of each covariate, and the omnibus p.

    Only the covariates named in `BALANCE` enter the omnibus; the others are descriptive.
    """
    use = np.array([name in BALANCE for name in names])
    out = []
    for label, t in zip(labels, thresholds, strict=True):
        mask = window_mask(margin, t)
        observed, draws, n = flip_means(diff, signs, mask)
        p = raw_p(observed, draws)
        in_window = int(mask.sum())
        out.append(
            {
                "window": label,
                "pairs": in_window,
                "omnibus_p": omnibus_p(observed, draws, n, use),
                "left_out": [
                    name for name, k, u in zip(names, n, use, strict=True) if u and k < MIN_PAIRS
                ],
                "covariates": {
                    name: {
                        "diff": float(observed[i]),
                        "p": float(p[i]),
                        "pairs": int(n[i]),
                        "null_pairs": in_window - int(n[i]),
                    }
                    for i, name in enumerate(names)
                },
            }
        )
        del draws
    return out


# --- Candidate covariates (all fixed before election E)


def candidate_covariates(cands: pl.DataFrame) -> pl.DataFrame:
    """`female`, `age` and `schooling` per candidacy, keyed `CAND3`."""
    gender = pl.col("cd_genero").cast(pl.Int64, strict=False)
    return cands.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        pl.when(gender.is_null())
        .then(None)
        .otherwise((gender == 4).cast(pl.Float64))
        .alias("female"),
        ((pl.col("dt_eleicao") - pl.col("dt_nascimento")).dt.total_days() / 365.25).alias("age"),
        pl.col("cd_grau_instrucao")
        .cast(pl.Int64, strict=False)
        .cast(pl.Float64)
        .alias("schooling"),
    )


def _council_round1(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
    )


def elected_council(df: pl.DataFrame) -> pl.DataFrame:
    """Council candidacies elected by `ds_sit_tot_turno`, never by `cd_sit_tot_turno`.

    The candidate file's codes change meaning between years (`MÉDIA` is 5 in 2004 and 3 in
    2008, where 5 is `SUPLENTE`), so only the four labels decide.
    """
    label = pl.col("ds_sit_tot_turno").str.strip_chars().str.to_uppercase()
    return df.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
        & label.is_in(list(ELECTED_LABELS))
    )


def incumbent(cands: pl.DataFrame, election: int) -> pl.DataFrame:
    """`incumbent` (1.0 / 0.0, null without a voter ID) of the candidates of `election`.

    A candidate is an incumbent when the voter ID belongs to a candidate elected to the
    council of the same `sg_ue` in the main election of E-4 (its council round-1
    `cd_eleicao` with the most candidate rows). Null for every candidate when E-4 has no
    council round-1 rows. The voter ID is used here only; the result holds `CAND3`.
    """
    voter = "nr_titulo_eleitoral_candidato"
    now = cands.filter(pl.col("ano_eleicao") == election)
    keys = now.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        pl.col(voter).cast(pl.Utf8),
    )
    rows = _council_round1(cands.filter(pl.col("ano_eleicao") == election - 4))
    if rows.height == 0:
        return keys.select(*CAND3, pl.lit(None, dtype=pl.Float64).alias("incumbent"))
    main = main_election(rows)
    held = (
        elected_council(rows.filter(pl.col("cd_eleicao") == main))
        .select(pl.col("sg_ue").cast(pl.Utf8), pl.col(voter).cast(pl.Utf8))
        .drop_nulls()
        .unique()
        .with_columns(pl.lit(True).alias("hit"))
    )
    joined = keys.join(held, on=["sg_ue", voter], how="left")
    flag = (
        pl.when(pl.col(voter).is_null())
        .then(None)
        .otherwise(pl.col("hit").is_not_null().cast(pl.Float64))
    )
    return joined.select(*CAND3, flag.alias("incumbent"))


def incumbency_check(cands: pl.DataFrame, election: int) -> dict[str, Any]:
    """Main-election council candidates of `election`: `st_reeleicao` = S against `incumbent`.

    `st_reeleicao` is null for 2020 and 2024 in the built table, so its count is None there.
    """
    now = cands.filter(pl.col("ano_eleicao") == election)
    rows = _council_round1(now)
    if rows.height == 0:
        return {"candidates": 0, "st_reeleicao_S": None, "incumbent": 0}
    main = main_election(rows)
    rows = rows.filter(pl.col("cd_eleicao") == main)
    in_main = rows.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
    )
    flagged = incumbent(cands, election).join(in_main, on=CAND3, how="semi")
    recorded = rows["st_reeleicao"].drop_nulls()
    return {
        "candidates": rows.height,
        "st_reeleicao_S": (
            int((recorded.str.strip_chars().str.to_uppercase() == "S").sum())
            if recorded.len()
            else None
        ),
        "incumbent": int(flagged["incumbent"].drop_nulls().sum()),
    }


# --- Stronghold covariates


def stronghold_table(
    strong: pl.DataFrame,
    place_types: pl.DataFrame,
    cand_dist: pl.DataFrame,
    located: pl.DataFrame,
) -> pl.DataFrame:
    """Per stronghold of a candidate: `CAND3`, the place covariates and its coordinates.

    `place_types` is the year's `polling_place_types`; `cand_dist` comes from
    `candidate_distances`; `located` from `locate_places`. `place_seat` and `place_town` are
    null when the place has no type.
    """
    text = [pl.col("cd_ibge").cast(pl.Utf8), pl.col("sg_ue").cast(pl.Utf8)]
    zone = [pl.col("nr_zona").cast(pl.Int64), pl.col("nr_local_votacao").cast(pl.Int64)]
    base = strong.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        pl.col("cd_ibge").cast(pl.Utf8),
        *zone,
    )
    types = place_types.select(*text, *zone, "seat_km", "place_type").unique(PLACE_KEY)
    where = located.select(
        *text, *zone, pl.col("x_km").alias("sx"), pl.col("y_km").alias("sy")
    ).unique(PLACE_KEY)
    dist = cand_dist.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        pl.col("dist_indigenous_km").cast(pl.Float64),
        pl.col("dist_settlement_km").cast(pl.Float64),
    ).unique(CAND3)
    out = (
        base.join(types, on=PLACE_KEY, how="left")
        .join(where, on=PLACE_KEY, how="left")
        .join(dist, on=CAND3, how="left")
    )

    def is_type(name: str) -> pl.Expr:
        return (
            pl.when(pl.col("place_type").is_null())
            .then(None)
            .otherwise((pl.col("place_type") == name).cast(pl.Float64))
        )

    return out.select(
        *CAND3,
        pl.col("seat_km").cast(pl.Float64),
        is_type("seat").alias("place_seat"),
        is_type("town").alias("place_town"),
        "dist_indigenous_km",
        "dist_settlement_km",
        "sx",
        "sy",
    )


# --- The disc around a stronghold

_OFFSET = 100_000
_STRIDE = 1_000_000


def _encode(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (np.asarray(x, dtype=np.int64) + _OFFSET) * _STRIDE + (
        np.asarray(y, dtype=np.int64) + _OFFSET
    )


def disc_index(
    x_km: np.ndarray, y_km: np.ndarray, values: dict[str, np.ndarray]
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Cells sorted by (x, y) with the running sums of each value (leading 0)."""
    key = _encode(x_km, y_km)
    order = np.argsort(key, kind="stable")
    sums = {
        name: np.concatenate([[0.0], np.cumsum(np.asarray(v, dtype=float)[order])])
        for name, v in values.items()
    }
    return key[order], sums


def disc_sums(
    index: tuple[np.ndarray, dict[str, np.ndarray]],
    sx: np.ndarray,
    sy: np.ndarray,
    radius: float = DISC_KM,
) -> dict[str, np.ndarray]:
    """Sum of each value over the cells whose centre (corner + 0.5 km) is within `radius`.

    Distances in Albers km; a centre at `radius` + 1e-9 counts. `sx`, `sy` are the strongholds.
    """
    key, sums = index
    sx = np.asarray(sx, dtype=float)
    sy = np.asarray(sy, dtype=float)
    limit = (radius + TOLERANCE) ** 2
    first = np.ceil(sx - radius - 0.5 - TOLERANCE).astype(np.int64)
    out = {name: np.zeros(sx.size) for name in sums}
    for step in range(int(np.ceil(2 * radius)) + 2):
        column = first + step
        slack = limit - (column + 0.5 - sx) ** 2
        live = slack >= 0
        half = np.sqrt(np.maximum(slack, 0.0))
        low = np.ceil(sy - 0.5 - half).astype(np.int64)
        high = np.floor(sy - 0.5 + half).astype(np.int64)
        lo = np.searchsorted(key, _encode(column, low), side="left")
        hi = np.maximum(np.searchsorted(key, _encode(column, high), side="right"), lo)
        for name, running in sums.items():
            out[name] += np.where(live, running[hi] - running[lo], 0.0)
    return out


def read_pre_outcomes(
    read_year: Callable[[int], pl.DataFrame], election: int
) -> dict[int, pl.DataFrame]:
    """`cell_outcomes` of the years of `pre_years(election)` and no other."""
    return {y: read_year(y) for y in pre_years(election)}


def pre_clearing_cells(by_year: dict[int, pl.DataFrame], election: int) -> pl.DataFrame:
    """(`nome_1KM`, `num`, `den`) of the cells present with `has_data` in every pre year.

    `num` is the sum of `code_4` over E-4 .. E-1 and `den` is `code_2` + `code_4` of E-4.
    """
    years = pre_years(election)
    stacked = pl.concat(
        [
            by_year[y].select(
                "nome_1KM",
                pl.lit(y, dtype=pl.Int64).alias("yr"),
                pl.col("has_data").fill_null(False).alias("ok"),
                pl.col("code_4").cast(pl.Float64).alias("c4"),
                (pl.col("code_2").cast(pl.Float64).fill_null(0.0) + pl.col("code_4")).alias("c24"),
            )
            for y in years
        ]
    )
    per_cell = stacked.group_by("nome_1KM").agg(
        pl.len().alias("n"),
        pl.col("yr").n_unique().alias("n_years"),
        pl.col("ok").all().alias("ok"),
        pl.col("c4").sum().alias("num"),
        pl.col("c24").filter(pl.col("yr") == years[0]).sum().alias("den"),
    )
    kept = per_cell.filter((pl.col("n") == len(years)) & (pl.col("n_years") == len(years)))
    return kept.filter(pl.col("ok")).select("nome_1KM", "num", "den").sort("nome_1KM")


def disc_covariates(
    cells: pl.DataFrame, clearing: pl.DataFrame, sx: np.ndarray, sy: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(`pop22_5km`, `clearing_pre`) of the strongholds at (`sx`, `sy`).

    `cells` has `nome_1KM`, `x_km`, `y_km`, `pop_2022`; `clearing` comes from
    `pre_clearing_cells`. Clearing is nan when the denominator is 0 or no cell qualifies.
    """
    table = cells.join(clearing, on="nome_1KM", how="left")
    values = {
        "pop": table["pop_2022"].fill_null(0).cast(pl.Float64).to_numpy(),
        "num": table["num"].fill_null(0.0).to_numpy(),
        "den": table["den"].fill_null(0.0).to_numpy(),
        "qual": table["num"].is_not_null().cast(pl.Float64).to_numpy(),
    }
    index = disc_index(table["x_km"].to_numpy(), table["y_km"].to_numpy(), values)
    got = disc_sums(index, sx, sy)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where((got["qual"] > 0) & (got["den"] > 0), got["num"] / got["den"], np.nan)
    return got["pop"], ratio


# --- Differences within pairs


def pair_differences(pairs: pl.DataFrame, cov: pl.DataFrame, names: Sequence[str]) -> np.ndarray:
    """(pairs, covariates) of winner - loser; nan when either side is null."""
    base = pairs.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("w").cast(pl.Utf8),
        pl.col("l").cast(pl.Utf8),
    ).with_row_index("pair_id")
    for side in ("w", "l"):
        side_cov = cov.select(
            "cd_eleicao",
            "sg_ue",
            pl.col("sq_candidato").alias(side),
            *(pl.col(n).cast(pl.Float64).alias(f"{n}_{side}") for n in names),
        )
        base = base.join(side_cov, on=["cd_eleicao", "sg_ue", side], how="left")
    base = base.sort("pair_id")
    if base.height != pairs.height:
        raise SystemExit("a candidate appears twice in the covariate table")
    columns = [(pl.col(f"{n}_w") - pl.col(f"{n}_l")).alias(n) for n in names]
    return base.select(columns).to_numpy().astype(float).reshape(pairs.height, len(names))


# --- Power (reported, never used to choose)


def power_at(
    draws: np.ndarray, x_abs: np.ndarray, y: np.ndarray, z: float, effect_pct: float
) -> dict[str, Any] | None:
    """Power Φ(τ / sd_ri - z) with τ = effect x mean Y / mean |x| over the cells with x != 0."""
    finite = draws[~np.isnan(draws)]
    if finite.size < 2 or x_abs.size == 0:
        return None
    sd = float(np.std(finite, ddof=1))
    ybar = float(np.mean(y))
    xbar = float(np.mean(x_abs))
    if not (sd > 0 and ybar > 0 and xbar > 0):
        return None
    tau = effect_pct / 100.0 * ybar / xbar
    return {
        "power": NormalDist().cdf(tau / sd - z),
        "tau": tau,
        "sd_ri": sd,
        "ybar": ybar,
        "mean_abs_x": xbar,
        "cells": int(x_abs.size),
    }


def reached_cells(dist: pl.DataFrame, totals: pl.DataFrame) -> pl.DataFrame:
    """Cells within 10 km of a place with votes: the cells the `exp2` kernel reaches."""
    near = (
        dist.join(totals.select(PLACE_KEY).unique(), on=PLACE_KEY, how="semi")
        .with_columns(kernel("exp2", pl.col("d")).alias("k"))
        .filter(pl.col("k") > 0)
    )
    return near.select(CELL).unique()


def window_power(inputs: dict[int, dict[str, Any]], grid: pl.DataFrame, t: float) -> dict[str, Any]:
    """Power of the three estimates in one window, on pre-election clearing, 2008-2020.

    The pairs of the window are renumbered from 0 in each election; the 2,000 draws use the
    seed of the balance draws but their own sign vectors over this window's pairs.
    """
    parts: dict[str, list[Any]] = {"direct": [], "displacement": [], "split5": []}
    types: dict[str, dict[str, dict[str, int]]] = {}
    for year in POWER_ELECTIONS:
        inp = inputs[year]
        pairs = inp["pairs"].filter(pl.Series(window_mask(inp["margin"], t)))
        n = pairs.height
        if n == 0:
            parts["direct"].append(ef.empty_part(0, year))
            parts["displacement"].append(ef.empty_part(0, year))
            parts["split5"].append(ef.empty_part(0, year, pw.TYPES))
            types[str(year)] = pw.type_counts(pw.pair_types(pairs, inp["cand"], 5))
            continue
        munis = pairs["cd_ibge"].unique().to_list()
        cells = grid.filter(pl.col("cd_ibge").is_in(munis))
        dist = cell_place_distances(cells.select(CELL), inp["located"])
        reached = reached_cells(dist, inp["totals"])
        named = cells.select("nome_1KM", *CELL)
        sample = reached.join(named, on=CELL, how="inner").join(
            inp["y_table"], on="nome_1KM", how="inner"
        )
        terms = pb.pair_terms(dist, inp["totals"], inp["shares"], pairs, "exp2")
        parts["direct"].append(pw.make_part(sample, {"beta": terms}, n, year))

        used = pw.with_pair_ids(stronghold_pairs(pairs, inp["strong"], inp["located"])[0], pairs)
        unreached = unrepresented(cells, reached, set(munis))
        d_terms = pw.displacement_terms(unreached, used)
        d_sample = unreached.join(inp["y_table"], on="nome_1KM", how="inner")
        parts["displacement"].append(pw.make_part(d_sample, {"beta": d_terms}, n, year))

        ptypes = pw.pair_types(pairs, inp["cand"], 5)
        side = pw.side_terms(dist, inp["totals"], inp["shares"], pairs)
        parts["split5"].append(pw.make_part(sample, pw.components(side, ptypes), n, year))
        types[str(year)] = pw.type_counts(ptypes)
        del dist, reached, sample, terms, unreached, d_terms, d_sample, side

    specs = {label: pw.assemble(label, p) for label, p in parts.items()}
    observed, sims = pw.run_ri(specs, DRAWS, SEED)
    del observed
    out: dict[str, Any] = {}
    for label, slope, component, z in (
        ("direct", "beta", "beta", Z_TWO_SIDED),
        ("displacement", "beta", "beta", Z_TWO_SIDED),
        ("split5", "delta", "indigenous", Z_ONE_SIDED),
    ):
        key = (label, "Y4", slope)
        spec = specs[label]
        if key not in sims or component not in spec.designs:
            out[label] = None
            continue
        x_abs, y = pw.exposure_cells(spec, component, "Y4")
        out[label] = power_at(sims[key], x_abs, y, z, ef.EFFECT_SIZE_PCT)
    out["types5"] = pw.pool_type_counts(types) if types else {}
    del specs, sims, parts
    gc.collect()
    return out


# --- One election


def make_reader(store: GCSStore, tmp: Path, half: frozenset[str]) -> Callable[..., pl.DataFrame]:
    """A reader of one built file, restricted to the exploration half."""

    def read(manifest: str, pattern: str, columns: list[str] | None = None) -> pl.DataFrame:
        remote = census._paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = restrict(pl.read_parquet(local, columns=columns), half)
        local.unlink()
        return frame

    return read


def load_candidates(
    store: GCSStore, tmp: Path, half: frozenset[str]
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Council candidacies 2004-2024 of the exploration half, with `cd_ibge`.

    `cd_ibge` comes from `municipalities` (`cd_tse` = `sg_ue`); rows without a match are
    counted per year and dropped. Only the columns of `CAND_COLUMNS` are read.
    """
    files = {}
    for name, pattern in (
        ("tse_candidates", r"candidates\.parquet$"),
        ("municipalities", r"municipalities\.parquet$"),
    ):
        remote = census._paths(name, pattern)[0]
        files[name] = tmp / Path(remote).name
        store.download(remote, files[name])
    cands = pl.read_parquet(files["tse_candidates"], columns=CAND_COLUMNS).filter(
        pl.col("ano_eleicao").is_between(FIRST_CANDIDATE_YEAR, ELECTIONS[-1])
        & (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
    )
    munis = pl.read_parquet(files["municipalities"], columns=["cd_ibge", "cd_tse"])
    files["tse_candidates"].unlink()
    files["municipalities"].unlink()
    joined, unmatched = with_ibge(cands, munis)
    return restrict(joined, half), unmatched


def with_ibge(cands: pl.DataFrame, munis: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Add `cd_ibge` by joining `municipalities`; the rows without a match, counted per year."""
    link = (
        munis.select(pl.col("cd_tse").cast(pl.Utf8).alias("sg_ue"), pl.col("cd_ibge").cast(pl.Utf8))
        .drop_nulls("sg_ue")
        .unique("sg_ue")
    )
    joined = cands.with_columns(pl.col("sg_ue").cast(pl.Utf8)).join(link, on="sg_ue", how="left")
    lost = joined.filter(pl.col("cd_ibge").is_null()).group_by("ano_eleicao").len()
    unmatched = {str(y): int(n) for y, n in zip(lost["ano_eleicao"], lost["len"], strict=True)}
    return joined.filter(pl.col("cd_ibge").is_not_null()), unmatched


def election_inputs(
    read: Callable[..., pl.DataFrame],
    census_dir: Path,
    store: GCSStore,
    half: frozenset[str],
    cands: pl.DataFrame,
    grid: pl.DataFrame,
    year: int,
) -> dict[str, Any]:
    """Everything one election gives: pairs, margins, covariate differences, power inputs."""
    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    places = read("polling_places", rf"polling_places_{year}\.parquet$")
    tenure = read("polling_place_tenure", rf"polling_place_tenure_{year}\.parquet$")
    if "ano" in tenure.columns:
        tenure = tenure.filter(pl.col("ano") == year)
    place_types = read("polling_place_types", rf"polling_place_types_{year}\.parquet$")
    if "ano" in place_types.columns:
        place_types = place_types.filter(pl.col("ano") == year)
    by_year = read_pre_outcomes(
        lambda y: read("cell_outcomes", rf"cell_outcomes_{y}\.parquet$", OUTCOME_COLUMNS), year
    )

    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    pairs, margin = pair_index(paired)
    close = census.close_candidates(paired, MAX_T)

    pieces = []
    for remote in census._paths("section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"):
        local = census_dir / Path(remote).name
        store.download(remote, local)
        sv = restrict(pl.read_parquet(local), half)
        local.unlink()
        pieces.append(place_candidate_votes(sv, main))
    place_votes = pl.concat(pieces)
    totals = place_totals(place_votes)
    shares = place_shares(place_votes)
    strong = strongholds(place_votes)
    located = locate_places(places)
    del place_votes, pieces

    pair_cands = pl.concat(
        [
            pairs.select("cd_eleicao", pl.col("w").alias("sq_candidato")),
            pairs.select("cd_eleicao", pl.col("l").alias("sq_candidato")),
        ]
    ).unique()
    shares = shares.join(pair_cands, on=["cd_eleicao", "sq_candidato"], how="semi")

    cand = kc1.candidate_distances(close, strong, tenure)
    table = stronghold_table(strong, place_types, cand, located)
    near = table.filter(pl.col("sx").is_not_null())
    pop, clearing = disc_covariates(
        grid, pre_clearing_cells(by_year, year), near["sx"].to_numpy(), near["sy"].to_numpy()
    )
    table = table.join(
        near.select(*CAND3).with_columns(
            pl.Series("pop22_5km", pop, dtype=pl.Float64),
            pl.Series("clearing_pre", clearing, dtype=pl.Float64).fill_nan(None),
        ),
        on=CAND3,
        how="left",
    )
    now = cands.filter(pl.col("ano_eleicao") == year)
    cov = (
        candidate_covariates(now)
        .join(incumbent(cands, year), on=CAND3, how="left")
        .join(table.drop("sx", "sy"), on=CAND3, how="left")
    )
    out: dict[str, Any] = {
        "pairs": pairs,
        "margin": margin,
        "diff": pair_differences(pairs, cov, COVARIATES),
        "incumbency": incumbency_check(cands, year),
    }
    if year in POWER_ELECTIONS:
        y_table, _ = pw.windows(by_year, year)
        out.update(
            cand=cand,
            located=located,
            totals=totals,
            shares=shares,
            strong=strong,
            y_table=y_table,
        )
    return out


# --- Report


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _diff_p(cell: dict[str, Any]) -> str:
    return f"{_fmt(cell['diff'], 3)} ({_fmt(cell['p'], 3)})"


def pair_counts(margins_by_year: dict[int, np.ndarray]) -> dict[str, Any]:
    """Pairs per window, per election and pooled."""
    per = {
        str(y): {
            label: int(window_mask(m, t).sum()) for label, t in zip(LABELS, THRESHOLDS, strict=True)
        }
        for y, m in margins_by_year.items()
    }
    pooled = {label: sum(c[label] for c in per.values()) for label in LABELS}
    return {"per_election": per, "pooled": pooled}


def build_results(
    balance: list[dict[str, Any]],
    pairs: dict[str, Any],
    power: dict[str, Any],
    incumbency: dict[str, Any],
    unmatched: dict[str, int],
) -> dict[str, Any]:
    """Every number of the report; `power` maps a window label to `window_power`'s output."""
    ps = [b["omnibus_p"] for b in balance]
    chosen = choose_window(ps)
    return pw._clean(
        {
            "rule": {
                "line": rule_line(ps),
                "chosen": None if chosen == NO_WINDOW else chosen,
                "threshold_p": RULE_P,
                "omnibus_p": dict(zip(LABELS, ps, strict=True)),
            },
            "windows": list(LABELS),
            "elections": list(ELECTIONS),
            "draws": DRAWS,
            "seed": SEED,
            "pre_years": {str(e): pre_years(e) for e in ELECTIONS},
            "pairs": pairs,
            "balance": {b["window"]: b for b in balance},
            "balance_covariates": list(BALANCE),
            "descriptive_covariates": list(DESCRIPTIVE),
            "power": power,
            "effect_size_pct": ef.EFFECT_SIZE_PCT,
            "incumbency": incumbency,
            "candidates_without_ibge": unmatched,
        }
    )


def _summary(results: dict[str, Any]) -> str:
    labels = results["windows"]
    lines = [results["rule"]["line"], ""]
    lines += ["## Pairs per window (exploration half)", ""]
    lines += ["| Election | " + " | ".join(labels) + " |"]
    lines += ["| --- | " + " | ".join(["---"] * len(labels)) + " |"]
    per = results["pairs"]["per_election"]
    for year, counts in {**per, "pooled": results["pairs"]["pooled"]}.items():
        lines.append(f"| {year} | " + " | ".join(f"{counts[w]:,}" for w in labels) + " |")
    lines += ["", "Constituency types at 5 km, pooled 2008-2020 (winners + losers):", ""]
    for label in labels:
        types = (results["power"].get(label) or {}).get("types5") or {}
        if types:
            lines.append(
                f"- {label}: " + "; ".join(f"{t} {c['total']:,}" for t, c in types.items()) + "."
            )
    lines += ["", "## Balance: winner - loser, and randomisation p", ""]
    lines += ["| Covariate | " + " | ".join(labels) + " |"]
    lines += ["| --- | " + " | ".join(["---"] * len(labels)) + " |"]
    rows = results["balance"]
    for name in results["balance_covariates"]:
        cells = [_diff_p(rows[w]["covariates"][name]) for w in labels]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    omnibus = " | ".join(_fmt(rows[w]["omnibus_p"], 3) for w in labels)
    lines += [f"| **omnibus p** | {omnibus} |", ""]
    lines += ["Pairs left out for a null side (per covariate; window pairs in the last row):", ""]
    lines += ["| Covariate | " + " | ".join(labels) + " |"]
    lines += ["| --- | " + " | ".join(["---"] * len(labels)) + " |"]
    for name in results["balance_covariates"]:
        cells = [f"{rows[w]['covariates'][name]['null_pairs']:,}" for w in labels]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["| pairs in window | " + " | ".join(f"{rows[w]['pairs']:,}" for w in labels) + " |"]
    left = [f"{w}: {', '.join(rows[w]['left_out'])}" for w in labels if rows[w]["left_out"]]
    lines += [
        "",
        "Covariates with fewer than 20 pairs, left out of the omnibus: "
        + ("; ".join(left) if left else "none")
        + ".",
        "",
    ]
    lines += ["Descriptive, not in the rule:", ""]
    lines += ["| Covariate | " + " | ".join(labels) + " |"]
    lines += ["| --- | " + " | ".join(["---"] * len(labels)) + " |"]
    for name in results["descriptive_covariates"]:
        cells = [_diff_p(rows[w]["covariates"][name]) for w in labels]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Power at 8% of baseline clearing, mean exposure (reported, never used to choose)",
        "",
    ]
    lines += ["| Window | Direct | Displacement | Split (5 km) |", "| --- | --- | --- | --- |"]
    for label in labels:
        got = results["power"].get(label) or {}
        cells = [
            _fmt((got.get(k) or {}).get("power"), 3) for k in ("direct", "displacement", "split5")
        ]
        tag = f"{label} ({POWER_REFERENCE})" if label == "0.50%" else label
        lines.append(f"| {tag} | " + " | ".join(cells) + " |")
    lines += ["", "## Incumbency check (main-election council candidates)", ""]
    lines += ["| Election | Candidates | st_reeleicao = S | incumbent by voter ID |"]
    lines += ["| --- | --- | --- | --- |"]
    for year, c in results["incumbency"].items():
        s = "n/a" if c["st_reeleicao_S"] is None else f"{c['st_reeleicao_S']:,}"
        lines.append(f"| {year} | {c['candidates']:,} | {s} | {c['incumbent']:,} |")
    lines += [
        "",
        "Caveats: exploration half only; `pop22_5km` is measured in 2022, after the 2008-2020 "
        "elections, so it is descriptive and never enters the rule; the clearing disc stops at "
        "confirmation-half municipalities; power comes from pre-election clearing (E-4 .. E-1), "
        "with exposure cells built from the grid for each window (no `cell_exposure` check), "
        "and `st_reeleicao` is not recorded for 2020 and 2024 in the built table. "
        "Candidates without a municipality match, per year: "
        + ", ".join(f"{y}: {n:,}" for y, n in results["candidates_without_ibge"].items())
        + ".",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    inputs: dict[int, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        read = make_reader(store, Path(tmp), half)
        cands, unmatched = load_candidates(store, Path(tmp), half)
        grid = read("grid_cells", r"grid_cells\.parquet$", GRID_COLUMNS).with_columns(
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("x_km").cast(pl.Int64),
            pl.col("y_km").cast(pl.Int64),
        )
        for year in ELECTIONS:
            inputs[year] = election_inputs(read, Path(tmp), store, half, cands, grid, year)

    margin = np.concatenate([inputs[y]["margin"] for y in ELECTIONS])
    diff = np.concatenate([inputs[y]["diff"] for y in ELECTIONS])
    balance = balance_by_window(diff, margin, sign_matrix(margin.size))
    power = {}
    for label, t in zip(LABELS, THRESHOLDS, strict=True):
        power[label] = window_power(inputs, grid, t)
    incumbency = {str(y): inputs[y]["incumbency"] for y in ELECTIONS}
    pairs = pair_counts({y: inputs[y]["margin"] for y in ELECTIONS})
    results = build_results(balance, pairs, power, incumbency, unmatched)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
