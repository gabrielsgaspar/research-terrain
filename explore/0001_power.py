"""Minimum detectable effects of the stronghold design (idea 0001), exploration half.

Kill criteria 3 and 4 of idea 0001 need 80% power for an effect size that the
pre-analysis plan has not fixed yet (decision 0007 will fix it). This script measures how
small an effect the design can detect, for three estimates: direct exposure (`exp2`,
decision 0004), displacement (`g_exp10`, decision 0005) and the indigenous / settlement
constituency split of the direct exposure, at 5 km (main) and 2 km (robustness).

Only pre-election clearing is read: the outcome of election E is the sum of `code_4 /
10,000` (decision 0006) over E-4 .. E-1 (`Y4`) or E-2 .. E-1 (`Y2`), for E = 2008 ..
2020. No year E or later is read; `outcome_years` fixes the years in code. Each of the
2,000 randomisation-inference draws flips every close pair with probability 1/2 (seed
20261106) and computes every estimate once, so all estimates and both windows share the
draws. The spread of each slope over the draws gives its minimum detectable effect. The
script gives no verdict on kill criteria 3 or 4.

The design, pair terms, randomisation inference and clustered SE are those of
`0001_placebo.py`; the stronghold distances are those of `0001_kill_criterion_1.py`.
Both are loaded below and not copied. Only exploration-half rows are read.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
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
    TOLERANCE,
    candidacy_votes,
    cell_place_distances,
    close_pairs,
    kernel_g,
    locate_places,
    main_election,
    margins,
    place_candidate_votes,
    place_shares,
    place_totals,
    stronghold_pairs,
    strongholds,
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


pb = _load("power_placebo", "0001_placebo.py")
kc1 = _load("power_kc1", "0001_kill_criterion_1.py")
census = pb.census

ELECTIONS = (2008, 2012, 2016, 2020)
BANDS = (5, 2)
SEED = pb.SEED
DRAWS = pb.DRAWS
TYPES = ("indigenous", "settlement", "both", "neither", "untyped")
WINDOWS = ("Y4", "Y2")
MIN_TYPED = 200
Z_TWO_SIDED = 2.8  # 1.96 + 0.84
Z_ONE_SIDED = 2.487  # 1.645 + 0.84
NO_CANDIDATE = "__none__"
LABELS = ("direct", "displacement", "split5", "split2")


# --- Outcome windows


def outcome_years(election: int) -> list[int]:
    """The only outcome years read for `election`: E-4 .. E-1."""
    return list(range(election - pb.LAG, election))


def windows(outcomes_by_year: dict[int, pl.DataFrame], election: int) -> tuple[pl.DataFrame, int]:
    """(`nome_1KM`, `Y4`, `Y2`) for the cells kept by the placebo's rule, and the cells dropped.

    `Y4` is the placebo's `Y` (E-4 .. E-1); `Y2` sums the same `code_4 / 10,000` over
    E-2 .. E-1 for the same cells. Years outside `outcome_years` are never touched.
    """
    y4, dropped = pb.pre_election_outcome(outcomes_by_year, election)
    last = outcome_years(election)[-2:]
    recent = pl.concat(
        [
            outcomes_by_year[y].select(
                "nome_1KM", (pl.col("code_4").cast(pl.Float64) / 10_000).alias("v")
            )
            for y in last
        ]
    )
    y2 = (
        recent.join(y4.select("nome_1KM"), on="nome_1KM", how="semi")
        .group_by("nome_1KM")
        .agg(pl.col("v").sum().alias("Y2"))
    )
    out = y4.rename({"Y": "Y4"}).join(y2, on="nome_1KM", how="inner").sort("nome_1KM")
    return out, dropped


# --- Candidate types


def candidate_type(ind: pl.Expr, sett: pl.Expr, band: float) -> pl.Expr:
    """The type of a candidate from its stronghold's distances (km) to indigenous land and
    settlements, within `band` (`<= band + 1e-9`, as kill criterion 1). A missing distance
    (no stronghold, or none with coordinates) is `untyped`, never "far away".
    """
    near_ind = ind <= band + TOLERANCE
    near_set = sett <= band + TOLERANCE
    return (
        pl.when(ind.is_null() | sett.is_null())
        .then(pl.lit("untyped"))
        .when(near_ind & near_set)
        .then(pl.lit("both"))
        .when(near_ind)
        .then(pl.lit("indigenous"))
        .when(near_set)
        .then(pl.lit("settlement"))
        .otherwise(pl.lit("neither"))
    )


def pair_types(pairs: pl.DataFrame, cand: pl.DataFrame, band: float) -> pl.DataFrame:
    """`pairs` with `pair_id` (row index), `type_w` and `type_l` at `band`.

    `cand` comes from `candidate_distances` (one row per close-pair candidate).
    """
    types = cand.select(
        "cd_eleicao",
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8).alias("cand"),
        candidate_type(pl.col("dist_indigenous_km"), pl.col("dist_settlement_km"), band).alias(
            "type"
        ),
    )
    out = pairs.with_row_index("pair_id")
    for side in ("w", "l"):
        out = out.join(
            types.select(
                "cd_eleicao",
                "sg_ue",
                pl.col("cand").alias(side),
                pl.col("type").alias(f"type_{side}"),
            ),
            on=["cd_eleicao", "sg_ue", side],
            how="left",
        )
    return out.with_columns(
        pl.col("type_w").fill_null("untyped"), pl.col("type_l").fill_null("untyped")
    ).sort("pair_id")


def type_counts(ptypes: pl.DataFrame) -> dict[str, dict[str, int]]:
    """Winners, losers and both, per type."""
    out = {}
    for t in TYPES:
        w = int(ptypes.filter(pl.col("type_w") == t).height)
        l = int(ptypes.filter(pl.col("type_l") == t).height)  # noqa: E741
        out[t] = {"winners": w, "losers": l, "total": w + l}
    return out


def pool_type_counts(per_year: dict[str, dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
    return {
        t: {k: sum(c[t][k] for c in per_year.values()) for k in ("winners", "losers", "total")}
        for t in TYPES
    }


# --- Pair terms by side and by type


def side_terms(
    dist: pl.DataFrame,
    totals: pl.DataFrame,
    shares: pl.DataFrame,
    pairs: pl.DataFrame,
    kernel_name: str = "exp2",
) -> pl.DataFrame:
    """(CELL, `pair_id`, `e_w`, `e_l`): the two sides of the placebo's pair term `t`.

    `e_w` is the kernel-weighted share of the elected candidate and `e_l` that of the other,
    both divided by the cell's `sum_k`, so `t` = `e_w` - `e_l`. They come from
    `pair_terms` with one side replaced by a candidate that has no votes.
    """
    ew = pb.pair_terms(
        dist, totals, shares, pairs.with_columns(pl.lit(NO_CANDIDATE).alias("l")), kernel_name
    ).rename({"t": "e_w"})
    el = pb.pair_terms(
        dist, totals, shares, pairs.with_columns(pl.lit(NO_CANDIDATE).alias("w")), kernel_name
    ).select(*CELL, "pair_id", (-pl.col("t")).alias("e_l"))
    return (
        ew.join(el, on=[*CELL, "pair_id"], how="full", coalesce=True)
        .with_columns(pl.col("e_w").fill_null(0.0), pl.col("e_l").fill_null(0.0))
        .sort([*CELL, "pair_id"])
    )


def components(side: pl.DataFrame, ptypes: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """(CELL, `pair_id`, `t`) per type: the term of `D^T_i` of each pair.

    `t` = 1(type of the winner = T) `e_w` - 1(type of the loser = T) `e_l`; zero terms are
    dropped. Flipping a pair negates both of its contributions, so each component is
    linear in the pair's sign like `D_i`.
    """
    joined = side.join(ptypes.select("pair_id", "type_w", "type_l"), on="pair_id", how="left")
    out = {}
    for t in TYPES:
        term = pl.when(pl.col("type_w") == t).then(pl.col("e_w")).otherwise(0.0) - pl.when(
            pl.col("type_l") == t
        ).then(pl.col("e_l")).otherwise(0.0)
        out[t] = joined.select(*CELL, "pair_id", term.alias("t")).filter(pl.col("t") != 0)
    return out


def check_components(
    comps: dict[str, pl.DataFrame], cell_exposure: pl.DataFrame, kernel_name: str = "exp2"
) -> None:
    """Stop (`SystemExit`) unless the components of every cell add up to `d_<kernel>`."""
    pb.check_terms(pl.concat(list(comps.values())), cell_exposure, kernel_name)


# --- Displacement pair terms


def with_pair_ids(used: pl.DataFrame, pairs: pl.DataFrame) -> pl.DataFrame:
    """`used` (from `stronghold_pairs`) with the `pair_id` of the same pair in `pairs`."""
    ids = pairs.with_row_index("pair_id").select(
        "pair_id", "cd_ibge", "sg_ue", "cd_eleicao", "w", "l"
    )
    out = used.join(ids, on=["cd_ibge", "sg_ue", "cd_eleicao", "w", "l"], how="inner")
    if out.height != used.height:
        raise SystemExit(f"{used.height - out.height} located pairs have no pair id")
    return out


def displacement_terms(cells: pl.DataFrame, used: pl.DataFrame) -> pl.DataFrame:
    """(CELL, `pair_id`, `t`): each pair's term of `G_exp10` at each cell of its municipality.

    `used` has `pair_id` and the stronghold coordinates `xw`, `yw`, `xl`, `yl` (Albers km).
    Distances run from the cell centre (corner + 0.5 km), as in `strongholds.displacement`;
    only non-zero terms are kept.
    """
    cells = cells.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    cx = cells["x_km"].to_numpy().astype(float) + 0.5
    cy = cells["y_km"].to_numpy().astype(float) + 0.5
    muni = cells["cd_ibge"].to_numpy()
    pair_muni = used["cd_ibge"].cast(pl.Utf8).to_numpy()
    rows = used.select("pair_id", "xw", "yw", "xl", "yl").to_numpy()
    index_out: list[np.ndarray] = []
    pair_out: list[np.ndarray] = []
    term_out: list[np.ndarray] = []
    for code in np.unique(pair_muni):
        index = np.flatnonzero(muni == code)
        if index.size == 0:
            continue
        for pair_id, xw, yw, xl, yl in rows[pair_muni == code]:
            d_w = np.hypot(cx[index] - xw, cy[index] - yw)
            d_l = np.hypot(cx[index] - xl, cy[index] - yl)
            g = kernel_g("exp10", d_w, d_l)
            nonzero = g != 0
            index_out.append(index[nonzero])
            pair_out.append(np.full(int(nonzero.sum()), int(pair_id), dtype=np.int64))
            term_out.append(g[nonzero])
    if not index_out:
        return pl.DataFrame(
            schema={
                "cd_ibge": pl.Utf8,
                "x_km": pl.Int64,
                "y_km": pl.Int64,
                "pair_id": pl.Int64,
                "t": pl.Float64,
            }
        )
    at = np.concatenate(index_out)
    return pl.DataFrame(
        {
            "cd_ibge": cells["cd_ibge"].gather(at),
            "x_km": cells["x_km"].gather(at),
            "y_km": cells["y_km"].gather(at),
            "pair_id": np.concatenate(pair_out),
            "t": np.concatenate(term_out),
        }
    ).sort([*CELL, "pair_id"])


def check_displacement(terms: pl.DataFrame, cells: pl.DataFrame, column: str = "g_exp10") -> None:
    """Stop (`SystemExit`) unless the terms of every cell add up to `column` of `cells`."""
    summed = terms.group_by(CELL).agg(pl.col("t").sum().alias("t_sum"))
    own = cells.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
        pl.col(column),
    )
    joined = own.join(summed, on=CELL, how="full", coalesce=True)
    diff = (pl.col("t_sum").fill_null(0.0) - pl.col(column).fill_null(0.0)).abs()
    bad = joined.filter(diff > TOLERANCE)
    if bad.height:
        raise SystemExit(
            f"the displacement pair terms differ from {column} in {bad.height} cells "
            f"(largest difference {bad.select(diff.max()).item():.3g})"
        )


# --- Samples and specifications


@dataclass
class YearPart:
    """One election of one estimate: a design per regressor and the outcomes of both windows."""

    designs: dict[str, Any]
    y_raw: dict[str, np.ndarray]
    y2_tilde: np.ndarray


def demeaned(sample: pl.DataFrame, column: str) -> np.ndarray:
    """`column` demeaned within municipality, in the row order of `sample`."""
    y = pl.col(column).cast(pl.Float64)
    out = sample.select((y - y.mean().over(pl.col("cd_ibge").cast(pl.Utf8))).alias("v"))["v"]
    return out.to_numpy().astype(float)


def make_part(
    sample: pl.DataFrame, comp_terms: dict[str, pl.DataFrame], n_pairs: int, election: int
) -> YearPart:
    """`sample` has CELL, `Y4` and `Y2`; `comp_terms` maps a regressor name to its pair terms."""
    base = sample.with_columns(pl.col("Y4").alias("Y"))
    return YearPart(
        designs={
            name: pb.make_design(base, terms, n_pairs, election)
            for name, terms in comp_terms.items()
        },
        y_raw={w: sample[w].to_numpy().astype(float) for w in WINDOWS},
        y2_tilde=demeaned(sample, "Y2"),
    )


@dataclass
class Spec:
    """One estimate over all elections: stacked designs, outcomes and what it reports."""

    label: str
    designs: dict[str, Any]
    y_tilde: dict[str, np.ndarray]
    y_raw: dict[str, np.ndarray]
    kept: list[str]
    slopes: list[str]

    @property
    def single(self) -> bool:
        return list(self.designs) == ["beta"]


def assemble(label: str, parts: list[YearPart]) -> Spec:
    """Stack the elections. A regressor with no variance after demeaning is dropped."""
    names = list(parts[0].designs)
    designs = {n: pb.stack([p.designs[n] for p in parts]) for n in names}
    first = designs[names[0]]
    y_tilde = {"Y4": first.y_tilde, "Y2": np.concatenate([p.y2_tilde for p in parts])}
    y_raw = {w: np.concatenate([p.y_raw[w] for p in parts]) for w in WINDOWS}
    ones = np.ones(first.n_pairs)
    kept = [n for n in names if float(np.sum(pb.demeaned_exposure(designs[n], ones) ** 2)) > 1e-12]
    if names == ["beta"]:
        slopes = list(kept)
    else:
        slopes = [*kept, *(["delta"] if {"indigenous", "settlement"} <= set(kept) else [])]
    return Spec(label, designs, y_tilde, y_raw, kept, slopes)


# --- Estimates and randomisation inference


def solve_joint(xtx: np.ndarray, xty: np.ndarray) -> np.ndarray | None:
    """Solve the normal equations; None if the (scaled) system is singular."""
    scale = np.sqrt(np.diag(xtx))
    if np.any(scale <= 0):
        return None
    scaled = xtx / np.outer(scale, scale)
    if np.linalg.matrix_rank(scaled) < xtx.shape[0]:
        return None
    return np.linalg.solve(xtx, xty)


def estimates(spec: Spec, signs: np.ndarray) -> dict[tuple[str, str], float]:
    """Every slope of `spec` in both windows for the pair signs `signs` (nan if undefined)."""
    nan = float("nan")
    xs = {n: pb.demeaned_exposure(spec.designs[n], signs) for n in spec.kept}
    out: dict[tuple[str, str], float] = {}
    if spec.single:
        for w in WINDOWS:
            b = pb.beta(xs["beta"], spec.y_tilde[w]) if "beta" in xs else None
            out[(w, "beta")] = nan if b is None else b
        return out
    cols = list(spec.kept)
    if not cols:
        return out
    x = np.column_stack([xs[n] for n in cols])
    xtx = x.T @ x
    for w in WINDOWS:
        coef = solve_joint(xtx, x.T @ spec.y_tilde[w])
        for i, n in enumerate(cols):
            out[(w, n)] = nan if coef is None else float(coef[i])
        if "delta" in spec.slopes:
            out[(w, "delta")] = (
                nan
                if coef is None
                else float(coef[cols.index("indigenous")] - coef[cols.index("settlement")])
            )
    return out


def run_ri(
    specs: dict[str, Spec], draws: int = DRAWS, seed: int = SEED
) -> tuple[dict[tuple[str, str, str], float], dict[tuple[str, str, str], np.ndarray]]:
    """Observed slopes and the RI draws of every (estimate, window, slope).

    One sign vector per draw is shared by every estimate and both windows.
    """
    n_pairs = next(iter(next(iter(specs.values())).designs.values())).n_pairs
    observed: dict[tuple[str, str, str], float] = {}
    sims: dict[tuple[str, str, str], np.ndarray] = {}
    for label, spec in specs.items():
        for (w, s), v in estimates(spec, np.ones(n_pairs)).items():
            observed[(label, w, s)] = v
            sims[(label, w, s)] = np.full(draws, np.nan)
    rng = np.random.default_rng(seed)
    for r in range(draws):
        signs = rng.integers(0, 2, size=n_pairs).astype(float) * 2.0 - 1.0
        for label, spec in specs.items():
            for (w, s), v in estimates(spec, signs).items():
                sims[(label, w, s)][r] = v
    return observed, sims


def ri_p(observed: float, draws: np.ndarray) -> float | None:
    """Two-sided RI p as the placebo's: a draw with no estimate counts as extreme."""
    if np.isnan(observed):
        return None
    finite = draws[~np.isnan(draws)]
    extreme = int(np.sum(np.abs(finite) >= abs(observed))) + draws.size - finite.size
    return (1 + extreme) / (1 + draws.size)


def mde_stats(draws: np.ndarray, one_sided: bool = False) -> dict[str, float | None]:
    """Spread and minimum detectable effects (two-sided 5%, 80% power) from RI draws.

    `mde_sd` = 2.8 `sd_ri`. `mde_q_pos` = q(0.975) - q(0.20) and `mde_q_neg` = q(0.80) -
    q(0.025) are the shifts of the RI distribution that it would detect 80% of the time,
    upward and downward. With `one_sided` (kill criterion 3: delta < 0), also `mde1_sd` =
    2.487 `sd_ri` and `mde1_q` = q(0.80) - q(0.05).
    """
    b = draws[~np.isnan(draws)]
    keys = ["sd_ri", "mde_sd", "mde_q_pos", "mde_q_neg"] + (
        ["mde1_sd", "mde1_q"] if one_sided else []
    )
    if b.size < 2:
        return dict.fromkeys(keys)

    def q(p: float) -> float:
        return float(np.quantile(b, p))

    sd = float(np.std(b, ddof=1))
    out: dict[str, float | None] = {
        "sd_ri": sd,
        "mde_sd": Z_TWO_SIDED * sd,
        "mde_q_pos": q(0.975) - q(0.20),
        "mde_q_neg": q(0.80) - q(0.025),
    }
    if one_sided:
        out["mde1_sd"] = Z_ONE_SIDED * sd
        out["mde1_q"] = q(0.80) - q(0.05)
    return out


# --- Effect sizes


def pct_effect(mde: float, x: float, ybar: float) -> float | None:
    """`100 mde |x| / ybar`: the change of Y for exposure `x`, as a percentage of baseline."""
    return None if not ybar > 0 else 100.0 * mde * abs(x) / ybar


def exposure_cells(spec: Spec, component: str, window: str) -> tuple[np.ndarray, np.ndarray]:
    """|x| and Y (of `window`) of the cells with a non-zero observed regressor.

    x is the full exposure (`D`, `G` or `D^T`), twice the recentred regressor.
    """
    design = spec.designs[component]
    x = 2.0 * pb.exposure_for(design, np.ones(design.n_pairs))
    mask = np.abs(x) > 1e-12
    return np.abs(x[mask]), spec.y_raw[window][mask]


def effect_size(mde: float | None, x_abs: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """|x| median / mean / p90, baseline `ybar` and the three percentage effects."""
    if x_abs.size == 0:
        return {"cells": 0}
    points = {
        "median": float(np.median(x_abs)),
        "mean": float(np.mean(x_abs)),
        "p90": float(np.quantile(x_abs, 0.9)),
    }
    ybar = float(np.mean(y))
    at_p90 = y[x_abs >= points["p90"]]
    out: dict[str, Any] = {
        "cells": int(x_abs.size),
        "x": points,
        "ybar": ybar,
        "ybar_at_p90": float(np.mean(at_p90)) if at_p90.size else None,
    }
    out["pct"] = {k: None if mde is None else pct_effect(mde, v, ybar) for k, v in points.items()}
    return out


def report_spec(
    spec: Spec,
    observed: dict[tuple[str, str, str], float],
    sims: dict[tuple[str, str, str], np.ndarray],
    clustered: bool,
) -> dict[str, Any]:
    """Per window and slope: observed value, RI p, spread, MDEs and effect sizes."""
    ones = np.ones(next(iter(spec.designs.values())).n_pairs)
    out: dict[str, Any] = {
        "windows": {},
        "not_estimable": [n for n in spec.designs if n not in spec.kept],
    }
    for w in WINDOWS:
        rows: dict[str, Any] = {}
        for s in spec.slopes:
            key = (spec.label, w, s)
            delta = s == "delta"
            stats = mde_stats(sims[key], one_sided=delta)
            comp = "indigenous" if delta else s
            x_abs, y = exposure_cells(spec, comp, w)
            row: dict[str, Any] = {
                "observed": observed[key],
                "ri_p": ri_p(observed[key], sims[key]),
                **stats,
                "effect": effect_size(stats["mde_sd"], x_abs, y),
            }
            if delta:
                row["effect_one_sided"] = effect_size(stats["mde1_sd"], x_abs, y)
            if clustered and spec.single:
                d_tilde = pb.demeaned_exposure(spec.designs[s], ones)
                row["clustered_se"] = pb.clustered_se(
                    d_tilde, spec.y_tilde[w], spec.designs[s].muni
                )
            rows[s] = row
        out["windows"][w] = rows
    out["cells_nonzero_by_regressor"] = {
        n: int(np.sum(np.abs(pb.exposure_for(d, np.ones(d.n_pairs))) > 1e-12))
        for n, d in spec.designs.items()
    }
    return _clean(out)


def _clean(value: Any) -> Any:
    """JSON-ready: nan and inf become None."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


# --- One election


def _year(store: GCSStore, tmp: Path, half: frozenset[str], year: int) -> dict[str, Any]:
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
    tenure = read("polling_place_tenure", rf"polling_place_tenure_{year}\.parquet$")
    if "ano" in tenure.columns:
        tenure = tenure.filter(pl.col("ano") == year)
    exposed = read("cell_exposure", rf"cell_exposure_{year}\.parquet$").with_columns(
        pl.col("cd_ibge").cast(pl.Utf8)
    )
    displaced = read(
        "cell_displacement",
        rf"cell_displacement_{year}\.parquet$",
        ["nome_1KM", "cd_ibge", "x_km", "y_km", "g_exp10"],
    ).with_columns(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    outcomes = {
        y: read(
            "cell_outcomes",
            rf"cell_outcomes_{y}\.parquet$",
            ["nome_1KM", "cd_ibge", "has_data", "code_4"],
        )
        for y in outcome_years(year)
    }

    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    pairs = close_pairs(paired)
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
    strong = strongholds(place_votes)
    located = locate_places(places)

    y_table, outcome_dropped = windows(outcomes, year)
    n_pairs = pairs.height
    with_pairs = exposed.filter(pl.col("n_pairs") > 0)
    dist = cell_place_distances(with_pairs.select(CELL), located)

    # Estimate 1: direct exposure, as the placebo's exp2.
    terms = pb.pair_terms(dist, totals, shares, pairs, "exp2")
    pb.check_terms(terms, with_pairs, "exp2")
    reached = with_pairs.filter(pl.col("d_exp2").is_not_null())
    sample = reached.join(y_table, on="nome_1KM", how="inner").with_columns(
        pl.col("d_exp2").alias("D")
    )
    counts = {"direct": _counts(sample, pairs, reached.height - sample.height)}
    parts = {"direct": make_part(sample, {"beta": terms}, n_pairs, year)}

    # Estimate 2: displacement exposure g_exp10.
    used = with_pair_ids(stronghold_pairs(pairs, strong, located)[0], pairs)
    d_terms = displacement_terms(displaced, used)
    check_displacement(d_terms, displaced)
    d_sample = displaced.join(y_table, on="nome_1KM", how="inner").with_columns(
        pl.col("g_exp10").alias("D")
    )
    counts["displacement"] = _counts(d_sample, pairs, displaced.height - d_sample.height)
    parts["displacement"] = make_part(d_sample, {"beta": d_terms}, n_pairs, year)

    # Estimate 3: the constituency split, at each band.
    cand = kc1.candidate_distances(census.close_candidates(paired), strong, tenure)
    side = side_terms(dist, totals, shares, pairs)
    types = {}
    for band in BANDS:
        ptypes = pair_types(pairs, cand, band)
        comps = components(side, ptypes)
        check_components(comps, with_pairs)
        parts[f"split{band}"] = make_part(sample, comps, n_pairs, year)
        counts[f"split{band}"] = counts["direct"]
        types[f"{band}km"] = type_counts(ptypes)
    return {"parts": parts, "counts": counts, "types": types, "outcome_dropped": outcome_dropped}


def _counts(sample: pl.DataFrame, pairs: pl.DataFrame, dropped: int) -> dict[str, Any]:
    return pb._counts(sample.with_columns(pl.col("Y4").alias("Y")), pairs, dropped)


# --- Report


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _per_election(counts: dict[str, dict[int, dict[str, Any]]], specs: dict[str, Spec]) -> dict:
    out = {}
    for label, by_year in counts.items():
        n_munis = int(np.unique(next(iter(specs[label].designs.values())).muni).size)
        pooled = pb._pooled_counts([by_year[y] for y in sorted(by_year)], n_munis)
        per = {str(y): {k: v for k, v in c.items() if k != "sum_y"} for y, c in by_year.items()}
        out[label] = {"pooled": pooled, "per_election": per}
    return out


def _types_table(band: str, pooled: dict, per_year: dict[str, dict]) -> list[str]:
    cols = [*per_year, "pooled"]
    lines = [
        f"### Candidates per type, {band} (winners / losers / total)",
        "",
        "| Type | " + " | ".join(cols) + " |",
        "| --- | " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for t in TYPES:
        cells = []
        for c in [*(per_year[y][t] for y in per_year), pooled[t]]:
            cells.append(f"{c['winners']:,} / {c['losers']:,} / {c['total']:,}")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    return lines


def _mde_table(rows: dict[str, Any]) -> list[str]:
    lines = [
        "| Slope | sd_ri | mde_sd | mde_q_pos | mde_q_neg | mde1_sd | mde1_q | cells | "
        "|x| med | mean | p90 | ybar | % med | % mean | % p90 | ybar p90 |",
        "| " + " | ".join(["---"] * 16) + " |",
    ]
    for s, r in rows.items():
        e = r["effect"]
        x = e.get("x") or {}
        pct = e.get("pct") or {}
        lines.append(
            f"| {s} | {_fmt(r['sd_ri'])} | {_fmt(r['mde_sd'])} | {_fmt(r['mde_q_pos'])} "
            f"| {_fmt(r['mde_q_neg'])} | {_fmt(r.get('mde1_sd'))} | {_fmt(r.get('mde1_q'))} "
            f"| {e.get('cells', 0):,} | {_fmt(x.get('median'))} | {_fmt(x.get('mean'))} "
            f"| {_fmt(x.get('p90'))} | {_fmt(e.get('ybar'))} | {_fmt(pct.get('median'), 2)} "
            f"| {_fmt(pct.get('mean'), 2)} | {_fmt(pct.get('p90'), 2)} "
            f"| {_fmt(e.get('ybar_at_p90'))} |"
        )
        one = r.get("effect_one_sided")
        if one:
            p1 = one.get("pct") or {}
            lines.append(
                f"| {s}, one-sided (mde1_sd) | | | | | | | | | | | | "
                f"{_fmt(p1.get('median'), 2)} | {_fmt(p1.get('mean'), 2)} "
                f"| {_fmt(p1.get('p90'), 2)} | |"
            )
    return lines


def _summary(results: dict[str, Any]) -> str:
    lines: list[str] = []
    pooled5 = results["type_counts"]["5km"]["pooled"]
    short = [t for t in ("indigenous", "settlement") if pooled5[t]["total"] < MIN_TYPED]
    if short:
        lines += [
            f"**Fewer than {MIN_TYPED} candidates pooled at 5 km: "
            + ", ".join(f"{t} ({pooled5[t]['total']:,})" for t in short)
            + ".**",
            "",
        ]
    lines += ["## Minimum detectable effects for decision 0007 (exploration half)", ""]
    for band in ("5km", "2km"):
        t = results["type_counts"][band]
        lines += _types_table(band, t["pooled"], t["per_election"]) + [""]
    names = {
        "direct": "1. Direct exposure (exp2)",
        "displacement": "2. Displacement (g_exp10)",
        "split5": "3. Constituency split, 5 km (main)",
        "split2": "3. Constituency split, 2 km (robustness)",
    }
    for label in LABELS:
        est = results["estimates"][label]
        c = est["counts"]["pooled"]
        lines += [
            f"## {names[label]}",
            "",
            f"Cells {c['cells']:,}, with a non-zero regressor {c['cells_nonzero']:,}, "
            f"municipalities {c['municipalities']:,}, pairs {c['pairs']:,}, "
            f"cells dropped for missing data {c['cells_dropped']:,}.",
        ]
        if est["not_estimable"]:
            lines.append("Not estimable (no variance): " + ", ".join(est["not_estimable"]) + ".")
        for w, title in (("Y4", "E-4 .. E-1"), ("Y2", "E-2 .. E-1")):
            lines += ["", f"Window {title}:", ""] + _mde_table(est["windows"][w])
        lines.append("")
    lines += [
        "## Context: observed pre-election slopes (not used for any verdict)",
        "",
        "| Estimate | Window | Slope | beta | RI p | clustered SE |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label in LABELS:
        for w in WINDOWS:
            for s, r in results["estimates"][label]["windows"][w].items():
                lines.append(
                    f"| {label} | {w} | {s} | {_fmt(r['observed'], 4)} | {_fmt(r['ri_p'], 3)} "
                    f"| {_fmt(r.get('clustered_se'), 3)} |"
                )
    lines += [
        "",
        "Caveats: the spread is measured on pre-election clearing, which is not the "
        "post-election outcome; the 2 km split is a robustness check; shifting the RI "
        "distribution (`mde_q_*`) is an approximation to power, and `mde_sd` = 2.8 sd_ri "
        "assumes it is symmetric and close to normal. The one-sided rows are for delta < 0 "
        "(kill criterion 3). Percentages are 100 x mde_sd x |x| / ybar, with |x| the "
        "exposure D (or G, or D^T) of the cells with a non-zero regressor. 2024 is not in "
        "the estimates. No verdict on kill criteria 3 or 4.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    parts: dict[str, list[YearPart]] = {k: [] for k in LABELS}
    counts: dict[str, dict[int, dict[str, Any]]] = {k: {} for k in LABELS}
    types: dict[str, dict[str, dict[str, dict[str, int]]]] = {f"{b}km": {} for b in BANDS}
    dropped: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for year in ELECTIONS:
            got = _year(store, Path(tmp), half, year)
            dropped[str(year)] = got["outcome_dropped"]
            for label in LABELS:
                parts[label].append(got["parts"][label])
                counts[label][year] = got["counts"][label]
            for band, per in got["types"].items():
                types[band][str(year)] = per
    specs = {label: assemble(label, parts[label]) for label in LABELS}
    observed, sims = run_ri(specs)
    per_election = _per_election(counts, specs)
    estimates_out = {}
    for label, spec in specs.items():
        estimates_out[label] = report_spec(spec, observed, sims, clustered=True)
        estimates_out[label]["counts"] = per_election[label]
    results = {
        "elections": list(ELECTIONS),
        "draws": DRAWS,
        "seed": SEED,
        "outcome_years": {str(e): outcome_years(e) for e in ELECTIONS},
        "outcome_cells_dropped": dropped,
        "type_counts": {
            band: {"per_election": per, "pooled": pool_type_counts(per)}
            for band, per in types.items()
        },
        "estimates": estimates_out,
    }
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
