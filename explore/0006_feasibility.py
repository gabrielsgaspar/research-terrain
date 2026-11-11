"""Feasibility of the geography-of-representation design before any election outcome (idea 0006).

Can idea 0006 (`research/ideas/0006-geography-of-representation.md`) work at all? On the national
exploration half (decision 0011) and in pre-election outcome years only (referee R2, decision
0003), this script measures: enough close pairs; polling places located well enough; enough
polling places matched to schools; baselines balanced on the treatment; a flat pre-election
placebo; enough power. It writes the six fields that kill rules k1-k6 of campaign step s17 read
(`research/campaigns/0006-geography-of-representation/campaign.md`, step s16).

For election E it reads `place_outcomes_E<E>_y<y>.parquet` only for: school counts at y = E-4
and E; built-up share at y = E; night lights at y = E-4 .. E-1. It never reads a year after E
(`place_outcomes_year` raises) and never the 10 km native-vegetation column; every read names
its columns (`USE_COLUMNS`). Treatment tables are read for
2008, 2012, 2016 and 2020.

Definitions (fixed by the task): close pairs at 0.50% from `terrain.strongholds`; for each
polling place p of a municipality with a close pair, D_p = sum over the pairs k of (s_wk,p -
s_lk,p) and S_p = sum of (s_wk,p + s_lk,p), a candidate with no row at a place having share 0.
The slope of an outcome on D_p with S_p, a stated baseline and municipality-by-election fixed
effects comes by Frisch-Waugh. Randomisation inference: 2,000 draws, seed 20261110, each draw
flips every pair's winner with probability 1/2 (D changes, S does not). The p-value is `ri_p`
and the spread `mde_stats` of `0001_power.py`; the clustered SE is `clustered_se` of
`0001_placebo.py` (both loaded, not copied). MDE of the placebo = 2.8 x the RI sd of the slope
x mean |D| / sd of the pre-election change.

A by-state value is null when its sample has fewer than 2 close pairs or no variation (the
number of close pairs itself is always written). The shares are null only without a
denominator. No post-election quantity, no effect estimate, no verdict on the kill rules.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import (
    PLACE_KEY,
    candidacy_votes,
    close_pairs,
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


pw = _load("representation_power", "0001_power.py")
pb = pw.pb

ELECTIONS = (2008, 2012, 2016, 2020)
PLACEBO_ELECTIONS = (2012, 2016, 2020)  # INEP starts in 2007: no E-4 for 2008
LIGHTS_ELECTIONS = (2016, 2020)  # VIIRS starts in 2013
WINDOW = 0.005
DRAWS = 2000
SEED = 20261110
BATCH = 100
MUNICIPAL = "3"  # INEP `rede` of municipal schools
STATE_NETWORK = "2"
CONFIDENT = ("high", "medium")
KEY = list(PLACE_KEY)  # cd_ibge, sg_ue, nr_zona, nr_local_votacao
BASELINES = ("school", "lights", "builtup")

UF_BY_CODE = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}

Read = Callable[..., pl.DataFrame]
ReadSections = Callable[[int, int, frozenset[str]], list[tuple[pl.DataFrame, pl.DataFrame]]]


# --- Outcome years and the place_outcomes reader


def outcome_years(election: int, use: str) -> list[int]:
    """The only years read for `use`: school {E-4, E}, built-up {E}, lights E-4 .. E-1."""
    if use == "school":
        return [election - 4, election]
    if use == "builtup":
        return [election]
    if use == "lights":
        return list(range(election - 4, election))
    raise ValueError(f"unknown outcome use {use!r}")


USE_COLUMNS = {
    "school": [*KEY, "located_1km", "school_id", "school_rede", "school_n_fac"],
    "builtup": [*KEY, "located_1km", "builtup_1km"],
    "lights": [*KEY, "located_1km", "lights_1km"],
}


def place_outcomes_year(read: Read, election: int, year: int, use: str) -> pl.DataFrame:
    """One `place_outcomes` file of election E and year y, explicit columns; never y > E."""
    if year > election:
        raise ValueError(f"year {year} is after election {election}")
    if year not in outcome_years(election, use):
        raise ValueError(f"year {year} is not read for {use!r} at election {election}")
    columns = USE_COLUMNS[use]
    pattern = rf"place_outcomes_E{election}_y{year}\.parquet$"
    return typed(read("place_outcomes", pattern, columns))


def typed(df: pl.DataFrame) -> pl.DataFrame:
    """Place keys as the treatment tables have them: text codes, integer zone and place."""
    casts = {
        "cd_ibge": pl.Utf8,
        "sg_ue": pl.Utf8,
        "nr_zona": pl.Int64,
        "nr_local_votacao": pl.Int64,
    }
    return df.with_columns(*(pl.col(c).cast(t) for c, t in casts.items() if c in df.columns))


def uf_expr() -> pl.Expr:
    return (
        pl.col("cd_ibge")
        .cast(pl.Utf8)
        .str.slice(0, 2)
        .replace_strict(UF_BY_CODE, default="??", return_dtype=pl.Utf8)
    )


# --- One state-year of section votes


def state_piece(
    lf: pl.LazyFrame, main: int, half: frozenset[str], vote_munis: frozenset[str]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(sections, place votes) of one state file: council, round 1, main election, half only.

    `sections` are the distinct sections of the half; the place votes are those of
    `place_candidate_votes`, read only for municipalities in `vote_munis` (with a close pair).
    """
    base = lf.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == 13)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
        & (pl.col("cd_eleicao") == main)
        & pl.col("cd_ibge").cast(pl.Utf8).is_in(sorted(half))
    )
    sections = base.select("cd_ibge", "sg_ue", "nr_zona", "nr_secao", "nr_local_votacao").unique()
    votes = base.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(sorted(vote_munis))).select(
        "cd_cargo",
        "nr_turno",
        "cd_eleicao",
        "vote_type",
        "annulled_in_results",
        "nr_zona",
        "nr_local_votacao",
        "cd_ibge",
        "sg_ue",
        "sq_candidato",
        "qt_votos",
    )
    sec, vot = pl.collect_all([sections, votes])
    return typed(restrict(sec, half)), place_candidate_votes(restrict(vot, half), main)


# --- One election


def located_places(places: pl.DataFrame) -> pl.DataFrame:
    """Place keys with a coordinate whose `conf_dist_km` is at most 1."""
    return typed(places).filter(
        pl.col("lat").is_not_null()
        & pl.col("long").is_not_null()
        & (pl.col("conf_dist_km") <= 1.0 + 1e-12)
    )


def tally(df: pl.DataFrame, hit: pl.Expr) -> dict[str, list[int]]:
    """{state: [rows where `hit`, rows]}."""
    out = df.group_by(uf_expr().alias("uf")).agg(
        hit.fill_null(False).sum().alias("hit"), pl.len().alias("n")
    )
    return {r["uf"]: [int(r["hit"]), int(r["n"])] for r in out.iter_rows(named=True)}


def add_tallies(a: dict[str, list[int]], b: dict[str, list[int]]) -> dict[str, list[int]]:
    out = {k: list(v) for k, v in a.items()}
    for k, (hit, n) in b.items():
        cur = out.setdefault(k, [0, 0])
        cur[0] += hit
        cur[1] += n
    return out


def pair_place_rows(
    pairs: pl.DataFrame, place_votes: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(places with D and S, (place, pair, diff) triples) of one election.

    A place is a polling place with votes in a municipality with a close pair; `pair_id` is
    the row of `pairs`. `diff` = s_w - s_l and the place's `D` and `S` sum it and s_w + s_l.
    """
    cols = ["pair_id", "cd_ibge", "sg_ue", "cd_eleicao", "w", "l"]
    pair_rows = pairs.with_row_index("pair_id").select(cols)
    totals = place_totals(place_votes).select(*KEY, "cd_eleicao")
    shares = place_shares(place_votes)
    rows = totals.join(pair_rows, on=["cd_ibge", "sg_ue", "cd_eleicao"])
    for side in ("w", "l"):
        look = shares.select(
            *KEY,
            "cd_eleicao",
            pl.col("sq_candidato").alias(side),
            pl.col("s_cp").alias(f"s_{side}"),
        )
        rows = rows.join(look, on=[*KEY, "cd_eleicao", side], how="left")
    rows = rows.with_columns(
        pl.col("s_w").fill_null(0.0), pl.col("s_l").fill_null(0.0)
    ).with_columns(
        (pl.col("s_w") - pl.col("s_l")).alias("diff"), (pl.col("s_w") + pl.col("s_l")).alias("tot")
    )
    triples = rows.select(*KEY, "pair_id", "diff").sort([*KEY, "pair_id"])
    places = (
        rows.group_by(KEY)
        .agg(pl.col("diff").sum().alias("D"), pl.col("tot").sum().alias("S"))
        .sort(KEY)
    )
    return places, triples


def outcome_table(read: Read, year: int) -> pl.DataFrame:
    """Per place of E: located, school, network, school counts at E and E-4, lights, built-up.

    Only the years of `outcome_years`; `school_n_fac_pre` is null for 2008, `lights_mean` for
    elections without VIIRS years.
    """
    school = place_outcomes_year(read, year, year, "school")
    out = school.select(
        *KEY,
        pl.col("located_1km").fill_null(False),
        pl.col("school_id"),
        pl.col("school_rede").cast(pl.Utf8).str.strip_chars().alias("rede"),
        pl.col("school_n_fac").cast(pl.Float64).alias("n_fac"),
    )
    if year in PLACEBO_ELECTIONS:
        pre = place_outcomes_year(read, year, year - 4, "school")
        out = out.join(
            pre.select(*KEY, pl.col("school_n_fac").cast(pl.Float64).alias("n_fac_pre")),
            on=KEY,
            how="left",
        )
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias("n_fac_pre"))
    built = place_outcomes_year(read, year, year, "builtup")
    out = out.join(
        built.select(*KEY, pl.col("builtup_1km").cast(pl.Float64).alias("builtup")),
        on=KEY,
        how="left",
    )
    if year in LIGHTS_ELECTIONS:
        frames = [
            place_outcomes_year(read, year, y, "lights").select(
                *KEY, pl.col("lights_1km").cast(pl.Float64)
            )
            for y in outcome_years(year, "lights")
        ]
        lights = (
            pl.concat(frames)
            .group_by(KEY)
            .agg(pl.col("lights_1km").cast(pl.Float64).mean().alias("lights"))
        )
        out = out.join(lights, on=KEY, how="left")
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias("lights"))
    return out


def load_election(read: Read, read_sections: ReadSections, year: int) -> dict[str, Any]:
    """Everything one election gives: pairs, regression places, triples and tallies."""
    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    places = read(
        "polling_places",
        rf"polling_places_{year}\.parquet$",
        [*KEY, "lat", "long", "conf_dist_km"],
    )
    match = typed(
        read(
            "school_polling_match",
            rf"school_polling_match_{year}\.parquet$",
            [*KEY, "confidence"],
        )
    )
    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    pairs = close_pairs(paired, WINDOW)
    pair_munis = frozenset(pairs["cd_ibge"].unique().to_list())
    pieces = read_sections(year, main, pair_munis)
    sections = pl.concat([s for s, _ in pieces]).unique(["cd_ibge", "sg_ue", "nr_zona", "nr_secao"])
    votes = pl.concat([v for _, v in pieces])
    located = located_places(places).select(KEY).unique().with_columns(pl.lit(True).alias("_loc"))
    located_sections = sections.join(located, on=KEY, how="left")
    out = outcome_table(read, year)
    reg, triples = pair_place_rows(pairs, votes)
    reg = reg.join(out, on=KEY, how="left")
    return {
        "year": year,
        "pairs": pairs,
        "reg": reg,
        "triples": triples,
        "sections": tally(located_sections, pl.col("_loc")),
        "match": tally(match, pl.col("confidence").is_in(list(CONFIDENT))),
        "places_with_pairs": int(out.filter(pl.col("cd_ibge").is_in(sorted(pair_munis))).height),
        "municipal_places": int(
            out.filter(pl.col("school_id").is_not_null() & (pl.col("rede") == MUNICIPAL)).height
        ),
        "state_places": int(
            out.filter(pl.col("school_id").is_not_null() & (pl.col("rede") == STATE_NETWORK)).height
        ),
    }


# --- Regression: Frisch-Waugh and randomisation inference


def demean(x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Subtract the group mean from `x` (1-D, or each column of a 2-D array)."""
    x = np.asarray(x, dtype=float)
    _, code = np.unique(groups, return_inverse=True)
    if x.ndim == 2 and x.shape[1] == 0:
        return x
    if x.ndim == 2:
        return np.column_stack([demean(x[:, j], code) for j in range(x.shape[1])]).reshape(x.shape)
    counts = np.bincount(code)
    return x - (np.bincount(code, weights=x) / counts)[code]


def partial_out(x: np.ndarray, controls: np.ndarray) -> np.ndarray:
    """Residual of `x` after a least-squares fit on `controls` (columns; none = unchanged)."""
    if controls.shape[1] == 0:
        return x
    coef, *_ = np.linalg.lstsq(controls, x, rcond=None)
    return x - controls @ coef


def fwl_beta(y: np.ndarray, d: np.ndarray, controls: np.ndarray, groups: np.ndarray) -> float:
    """Slope of `y` on `d` with `controls` and group fixed effects, by Frisch-Waugh.

    Demean everything within `groups`, partial the demeaned controls out of the demeaned `d`,
    beta = sum(d y) / sum(d^2). `nan` when `d` has no variation left.
    """
    y_t = demean(y, groups)
    c_t = demean(np.asarray(controls, dtype=float).reshape(len(y_t), -1), groups)
    d_t = partial_out(demean(d, groups), c_t)
    den = float(np.sum(d_t**2))
    return float("nan") if den <= 1e-12 else float(np.sum(d_t * y_t) / den)


@dataclass
class Prepared:
    """One regression sample, ready to give the slope for any flip of the pairs."""

    n: int
    code: np.ndarray  # municipality-by-election group of each place
    counts: np.ndarray
    cluster: np.ndarray  # municipality of each place
    y_t: np.ndarray  # demeaned outcome
    y_perp: np.ndarray  # demeaned outcome, controls partialled out
    c_t: np.ndarray  # demeaned controls (n x k)
    proj: np.ndarray  # n x k: c_t (c_t' c_t)^+, so the control part of x is proj @ (c_t' x)
    t_loc: np.ndarray  # triple -> row of the sample
    t_pair: np.ndarray  # triple -> pair (global id)
    t_diff: np.ndarray
    width: int  # number of pairs in the design
    n_pairs: int  # pairs touching the sample

    def d_raw(self, sigma: np.ndarray) -> np.ndarray:
        """D_p = sum over pairs k of sigma[k] (s_w - s_l); sigma is +1 as observed, -1 flipped."""
        return np.bincount(self.t_loc, weights=sigma[self.t_pair] * self.t_diff, minlength=self.n)

    def d_perp(self, sigma: np.ndarray) -> np.ndarray:
        """Demeaned D with controls partialled out when pair k is flipped by `sigma[k]` (+1/-1)."""
        d = self.d_raw(sigma)
        d = d - (np.bincount(self.code, weights=d) / self.counts)[self.code]
        return d - self.proj @ (self.c_t.T @ d) if self.c_t.shape[1] else d

    def beta(self, sigma: np.ndarray) -> float:
        d = self.d_perp(sigma)
        den = float(d @ d)
        return float("nan") if den <= 1e-12 else float(d @ self.y_t) / den

    def observed_d(self) -> np.ndarray:
        return self.d_raw(np.ones(self.width))


def prepare(
    places: pl.DataFrame,
    mask: np.ndarray,
    y: np.ndarray,
    controls: np.ndarray,
    t_place: np.ndarray,
    t_pair: np.ndarray,
    t_diff: np.ndarray,
    width: int,
) -> Prepared | None:
    """The sample `mask` of the design's places; None with fewer than 2 pairs or places."""
    rows = np.flatnonzero(mask)
    position = np.full(places.height, -1, dtype=np.int64)
    position[rows] = np.arange(rows.size)
    in_sample = position[t_place] >= 0
    pairs_here = np.unique(t_pair[in_sample])
    if rows.size < 2 or pairs_here.size < 2:
        return None
    sub = places[rows.tolist()]
    code = np.unique(sub["group"].to_numpy(), return_inverse=True)[1]
    cluster = np.unique(sub["cd_ibge"].to_numpy(), return_inverse=True)[1]
    c = np.asarray(controls, dtype=float).reshape(places.height, -1)[rows]
    y_t = demean(y[rows], code)
    c_t = demean(c, code)
    proj = c_t @ np.linalg.pinv(c_t.T @ c_t)
    return Prepared(
        n=rows.size,
        code=code,
        counts=np.bincount(code).astype(float),
        cluster=cluster,
        y_t=y_t,
        y_perp=y_t - proj @ (c_t.T @ y_t),
        c_t=c_t,
        proj=proj,
        t_loc=position[t_place[in_sample]],
        t_pair=t_pair[in_sample],
        t_diff=t_diff[in_sample],
        width=width,
        n_pairs=int(pairs_here.size),
    )


def observed_beta(prep: Prepared) -> float:
    return prep.beta(np.ones(prep.width))


def ri_draws(
    preps: dict[Any, Prepared],
    n_pairs: int,
    draws: int = DRAWS,
    seed: int = SEED,
    batch: int = BATCH,
) -> dict[Any, np.ndarray]:
    """The slope of every sample under the same flips: each pair flips with probability 1/2.

    Draws come in batches so that the sign matrix stays small; every sample sees the same ones.
    """
    rng = np.random.default_rng(seed)
    out = {k: np.full(draws, np.nan) for k in preps}
    for start in range(0, draws, batch):
        size = min(batch, draws - start)
        sigma = rng.integers(0, 2, size=(size, n_pairs)).astype(float) * 2.0 - 1.0
        for key, prep in preps.items():
            for r in range(size):
                out[key][start + r] = prep.beta(sigma[r])
    return out


def sd_ri(draws: np.ndarray) -> float | None:
    return pw.mde_stats(draws)["sd_ri"]


def joint_balance(
    preps: dict[str, Prepared | None], sims: dict[str, np.ndarray | None]
) -> float | None:
    """(1 + #{T_draw >= T_obs}) / (1 + draws), T = sum_j (beta_j / sd_RI(beta_j))^2.

    Each draw's T uses the observed samples' sd_RI. A draw without an estimate counts as
    extreme, as in `ri_p`. None if a baseline is missing or has no variation.
    """
    obs, spread, draws = [], [], []
    for name in BASELINES:
        prep, sim = preps.get(name), sims.get(name)
        if prep is None or sim is None:
            return None
        sd = sd_ri(sim)
        b = observed_beta(prep)
        if sd is None or not sd > 0 or np.isnan(b):
            return None
        obs.append(b)
        spread.append(sd)
        draws.append(sim)
    t_obs = float(sum((b / s) ** 2 for b, s in zip(obs, spread, strict=True)))
    t_draw = sum((d / s) ** 2 for d, s in zip(draws, spread, strict=True))
    extreme = int(np.sum(t_draw[~np.isnan(t_draw)] >= t_obs)) + int(np.sum(np.isnan(t_draw)))
    return (1 + extreme) / (1 + t_draw.size)


# --- The design and its samples


@dataclass
class Design:
    places: pl.DataFrame  # one row per regression place
    t_place: np.ndarray
    t_pair: np.ndarray
    t_diff: np.ndarray
    n_pairs: int


def build_design(data: dict[int, dict[str, Any]]) -> Design:
    """Stack the elections: global place rows, pair ids and (place, pair, diff) triples."""
    places, t_place, t_pair, t_diff = [], [], [], []
    place_offset = pair_offset = 0
    for year in sorted(data):
        reg = data[year]["reg"].with_row_index("loc").with_columns(pl.lit(year).alias("E"))
        triples = data[year]["triples"].join(reg.select(*KEY, "loc"), on=KEY)
        t_place.append(triples["loc"].to_numpy().astype(np.int64) + place_offset)
        t_pair.append(triples["pair_id"].to_numpy().astype(np.int64) + pair_offset)
        t_diff.append(triples["diff"].to_numpy().astype(float))
        places.append(reg.drop("loc"))
        place_offset += reg.height
        pair_offset += data[year]["pairs"].height
    if not places:
        raise ValueError("no election")
    stacked = pl.concat(places)
    stacked = stacked.with_columns(
        (pl.col("E").cast(pl.Utf8) + "-" + pl.col("cd_ibge")).alias("group"),
        uf_expr().alias("uf"),
    )
    return Design(
        stacked,
        np.concatenate(t_place),
        np.concatenate(t_pair),
        np.concatenate(t_diff),
        pair_offset,
    )


def _array(df: pl.DataFrame, column: str) -> np.ndarray:
    return df[column].cast(pl.Float64).fill_null(np.nan).to_numpy().astype(float)


def regressions(design: Design, uf: str | None = None) -> dict[str, Prepared | None]:
    """The four regressions on D with S_p: baselines school, lights, builtup and the placebo.

    `uf` restricts every sample to one state. All use municipality-by-election fixed effects.
    """
    p = design.places
    in_scope = np.ones(p.height, dtype=bool) if uf is None else (p["uf"] == uf).to_numpy()
    municipal = (
        (p["school_id"].is_not_null() & (p["rede"] == MUNICIPAL)).fill_null(False).to_numpy()
    )
    located = p["located_1km"].fill_null(False).to_numpy()
    s = _array(p, "S")
    n_fac, n_pre = _array(p, "n_fac"), _array(p, "n_fac_pre")
    lights, built = _array(p, "lights"), _array(p, "builtup")
    placebo_year = p["E"].is_in(list(PLACEBO_ELECTIONS)).to_numpy()
    specs = {
        "school": (municipal & ~np.isnan(n_fac), n_fac, s),
        "lights": (located & ~np.isnan(lights), lights, s),
        "builtup": (located & ~np.isnan(built), built, s),
        "placebo": (
            municipal & placebo_year & ~np.isnan(n_fac) & ~np.isnan(n_pre),
            n_fac - n_pre,
            np.column_stack([s, n_pre]),
        ),
    }
    out: dict[str, Prepared | None] = {}
    for name, (mask, y, controls) in specs.items():
        out[name] = prepare(
            p,
            mask & in_scope,
            np.nan_to_num(y),
            np.nan_to_num(controls),
            design.t_place,
            design.t_pair,
            design.t_diff,
            design.n_pairs,
        )
    return out


def school_placebo(prep: Prepared | None, sim: np.ndarray | None) -> dict[str, Any]:
    """ri_p, slope, clustered SE, places, RI sd and mean |D| of the placebo regression."""
    empty = {
        "ri_p": None,
        "beta": None,
        "clustered_se": None,
        "n_places": None if prep is None else prep.n,
        "sd_ri": None,
        "mean_abs_d": None,
    }
    if prep is None or sim is None:
        return empty
    beta = observed_beta(prep)
    if np.isnan(beta):
        return empty
    d_obs = prep.observed_d()
    nonzero = np.abs(d_obs[np.abs(d_obs) > 0])
    return {
        "ri_p": pw.ri_p(beta, sim),
        "beta": beta,
        "clustered_se": pb.clustered_se(
            prep.d_perp(np.ones(prep.width)), prep.y_perp, prep.cluster
        ),
        "n_places": prep.n,
        "sd_ri": sd_ri(sim),
        "mean_abs_d": float(nonzero.mean()) if nonzero.size else None,
    }


# --- Results


def share(tallies: dict[str, list[int]], uf: str | None = None) -> float | None:
    hit = n = 0
    for key, (h, m) in tallies.items():
        if uf is None or key == uf:
            hit += h
            n += m
    return None if n == 0 else hit / n


def sd_of_change(design: Design, uf: str | None = None) -> float | None:
    """Standard deviation (ddof 1) of the placebo outcome, school_n_fac at E minus at E-4."""
    p = design.places
    keep = (
        (p["school_id"].is_not_null() & (p["rede"] == MUNICIPAL))
        & p["E"].is_in(list(PLACEBO_ELECTIONS))
        & p["n_fac"].is_not_null()
        & p["n_fac_pre"].is_not_null()
    ).fill_null(False)
    if uf is not None:
        keep = keep & (p["uf"] == uf)
    change = (p["n_fac"] - p["n_fac_pre"]).filter(keep).to_numpy().astype(float)
    if change.size < 2:
        return None
    sd = float(np.std(change, ddof=1))
    return sd if sd > 0 else None


def scope_results(
    design: Design,
    preps: dict[str, Prepared | None],
    sims: dict[str, np.ndarray | None],
    uf: str | None,
) -> dict[str, Any]:
    """Balance, placebo and power of one scope (all places, or one state)."""
    balance_beta, balance_p = {}, {}
    for name in BASELINES:
        prep, sim = preps.get(name), sims.get(name)
        b = None if prep is None else observed_beta(prep)
        balance_beta[name] = None if b is None or np.isnan(b) else b
        balance_p[name] = None if balance_beta[name] is None else pw.ri_p(b, sim)
    plc = school_placebo(preps.get("placebo"), sims.get("placebo"))
    sd_pre = sd_of_change(design, uf)
    mde = None
    if plc["sd_ri"] is not None and sd_pre is not None and plc["mean_abs_d"] is not None:
        mde = pw.Z_TWO_SIDED * plc["sd_ri"] * plc["mean_abs_d"] / sd_pre
    return {
        "balance": {
            "ri_p_joint": joint_balance(preps, sims),
            "beta": balance_beta,
            "ri_p": balance_p,
        },
        "placebo": {
            "ri_p_school": plc["ri_p"],
            "beta": plc["beta"],
            "clustered_se": plc["clustered_se"],
            "n_places": plc["n_places"],
        },
        "power": {
            "mde_sd_school": mde,
            "sd_ri": plc["sd_ri"],
            "mean_abs_d": plc["mean_abs_d"],
            "sd_pre_change": sd_pre,
        },
    }


def compute(
    data: dict[int, dict[str, Any]],
    draws: int = DRAWS,
    seed: int = SEED,
    batch: int = BATCH,
) -> dict[str, Any]:
    """The results of the task from the per-election inputs."""
    design = build_design(data)
    states = sorted(set(design.places["uf"].to_list()))
    preps: dict[tuple[str | None, str], Prepared] = {}
    for scope in (None, *states):
        for name, prep in regressions(design, scope).items():
            if prep is not None:
                preps[(scope, name)] = prep
    sims = ri_draws(preps, design.n_pairs, draws, seed, batch)

    def of(scope: str | None) -> tuple[dict, dict]:
        keys = ("school", "lights", "builtup", "placebo")
        return (
            {k: preps.get((scope, k)) for k in keys},
            {k: sims.get((scope, k)) for k in keys},
        )

    pooled = scope_results(design, *of(None), None)
    sections: dict[str, list[int]] = {}
    match: dict[str, list[int]] = {}
    for year in sorted(data):
        sections = add_tallies(sections, data[year]["sections"])
        match = add_tallies(match, data[year]["match"])
    pair_states: dict[str, int] = {}
    for year in sorted(data):
        for r in data[year]["pairs"].select(uf_expr().alias("uf")).iter_rows():
            pair_states[r[0]] = pair_states.get(r[0], 0) + 1
    by_state = {}
    all_states = sorted({*states, *pair_states, *sections, *match})
    for uf in all_states:
        scoped = scope_results(design, *of(uf), uf)
        by_state[uf] = {
            "pairs_050": pair_states.get(uf, 0),
            "located_share": share(sections, uf),
            "match_share": share(match, uf),
            "ri_p_joint": scoped["balance"]["ri_p_joint"],
            "ri_p_school": scoped["placebo"]["ri_p_school"],
            "mde_sd_school": scoped["power"]["mde_sd_school"],
        }
    results = {
        "counts": {
            "pairs_050": sum(data[y]["pairs"].height for y in data),
            "pairs_by_election": {str(y): data[y]["pairs"].height for y in sorted(data)},
            "places_with_pairs": sum(data[y]["places_with_pairs"] for y in data),
        },
        "coverage": {"located_share": share(sections)},
        "schools": {
            "match_share": share(match),
            "municipal_places": sum(data[y]["municipal_places"] for y in data),
            "state_places": sum(data[y]["state_places"] for y in data),
        },
        **pooled,
        "by_state": by_state,
        "design": {
            "window": WINDOW,
            "draws": draws,
            "seed": seed,
            "elections": list(ELECTIONS),
            "outcome_years": "see the issue",
        },
    }
    return pw._clean(results)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _summary(results: dict[str, Any]) -> str:
    c, s = results["counts"], results["schools"]
    b, p, w = results["balance"], results["placebo"], results["power"]
    lines = [
        "## Feasibility of idea 0006 before the election (exploration half, pre-election years)",
        "",
        f"- Close pairs at 0.50%: {c['pairs_050']:,} "
        + ", ".join(f"{e}: {n}" for e, n in c["pairs_by_election"].items()),
        f"- Polling places in municipalities with a close pair: {c['places_with_pairs']:,}",
        f"- Share of sections at a place located within 1 km: "
        f"{_fmt(results['coverage']['located_share'])}",
        f"- Share of places matched to a school (high or medium): {_fmt(s['match_share'])}",
        f"- Places of municipal schools: {s['municipal_places']:,}; of state schools: "
        f"{s['state_places']:,}",
        f"- Balance on D, joint randomisation-inference p: {_fmt(b['ri_p_joint'])}",
        "- Balance slopes (p): "
        + ", ".join(f"{k} {_fmt(b['beta'][k])} ({_fmt(b['ri_p'][k])})" for k in BASELINES),
        f"- Placebo (change in school facilities), randomisation-inference p: "
        f"{_fmt(p['ri_p_school'])}; slope {_fmt(p['beta'])}; clustered SE "
        f"{_fmt(p['clustered_se'])}; places {p['n_places']}",
        f"- Minimum detectable shift of a mean-|D| change, in SD of the pre-election change: "
        f"{_fmt(w['mde_sd_school'])} (RI SD {_fmt(w['sd_ri'])}, mean |D| "
        f"{_fmt(w['mean_abs_d'])}, SD {_fmt(w['sd_pre_change'])})",
        "",
        "| State | Pairs | Located | Matched | Balance p | Placebo p | MDE (SD) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for uf, v in results["by_state"].items():
        lines.append(
            f"| {uf} | {v['pairs_050']} | {_fmt(v['located_share'])} | {_fmt(v['match_share'])} | "
            f"{_fmt(v['ri_p_joint'])} | {_fmt(v['ri_p_school'])} | {_fmt(v['mde_sd_school'])} |"
        )
    lines += [
        "",
        "Caveats: exploration half only; pre-election outcome years only; "
        f"{results['design']['draws']:,} flips of every pair (seed {results['design']['seed']}); "
        "no statement about effects and no verdict on the kill rules.",
    ]
    return "\n".join(lines)


# --- Reading from GCS


def make_readers(store: GCSStore, tmp: Path, half: frozenset[str]) -> tuple[Read, ReadSections]:
    """A reader of one built file (exploration half, `files` of the manifest) and of sections."""

    def read(manifest: str, pattern: str, columns: list[str] | None = None) -> pl.DataFrame:
        remote = pb.census._paths(manifest, pattern)[0]
        local = tmp / Path(remote).name
        store.download(remote, local)
        frame = restrict(pl.read_parquet(local, columns=columns), half)
        local.unlink()
        return frame

    def read_sections(
        year: int, main: int, vote_munis: frozenset[str]
    ) -> list[tuple[pl.DataFrame, pl.DataFrame]]:
        pieces = []
        for remote in pb.census._paths(
            "section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"
        ):
            local = tmp / Path(remote).name
            store.download(remote, local)
            pieces.append(state_piece(pl.scan_parquet(local), main, half, vote_munis))
            local.unlink()
        return pieces

    return read, read_sections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:
        read, read_sections = make_readers(store, Path(tmp), half)
        data = {year: load_election(read, read_sections, year) for year in ELECTIONS}
    results = compute(data)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
