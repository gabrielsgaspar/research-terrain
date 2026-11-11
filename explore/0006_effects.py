"""Post-election effects of narrow council wins on their voters' places (idea 0006, step s18).

Idea 0006 (`research/ideas/0006-geography-of-representation.md`), decisions 0011 (national
exploration half) and 0003 (outcome years), campaign
`research/campaigns/0006-geography-of-representation/campaign.md`, step s18. It runs only after
step s17 (feasibility) survives; step s19 runs it through `explore-run`.

The design, the treatment D_p and S_p, the regression (Frisch-Waugh, municipality-by-election
fixed effects), the randomisation inference and the clustered SE are those of
`0006_feasibility.py`, loaded, not copied (`fs`); `ri_p` is that of `0001_power.py` and
`clustered_se` that of `0001_placebo.py`. Alignment is that of `0004_alignment_counts.py`.

For election E it reads `place_outcomes_E<E>_y<y>.parquet` for y in E-4 .. E+4 only (referee R2),
and exactly: school counts at E-4 (from 2012), E and E+4; night lights E-4 .. E-1 and E+1 .. E+4
(none before 2013); built-up share and native vegetation at E and E+4. Every read names its
columns (`USE_COLUMNS`).

Estimates (nothing else is computed, referee R7):

1. Primary: `school_n_fac` at E+4 minus at E on municipal-school places, windows 0.50% (main),
   0.25% and 1.00%, baseline `school_n_fac` at E.
2. Falsification at 0.50%: the same on state-school places.
3. Secondary at 0.50% on located places: night lights (post mean minus pre mean, 2016 and
   2020), built-up (E+4 minus E), native-vegetation loss (E minus E+4); Benjamini-Hochberg
   over their three randomisation p-values.
4. Heterogeneity at 0.50%: D split by whether the pair's winner is in the elected mayor's
   coalition (aligned, unaligned, unknown), one regression on the three terms.

All by the same 2,000 flips at a window (seed 20261110). Exploration half only: a result here is
a reason to register, not a finding.
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
    candidacy_votes,
    close_pairs,
    main_election,
    margins,
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


fs = _load("effects_feasibility", "0006_feasibility.py")
al = _load("effects_alignment", "0004_alignment_counts.py")
pw = fs.pw
pb = fs.pb

ELECTIONS = fs.ELECTIONS
LIGHTS_ELECTIONS = fs.LIGHTS_ELECTIONS
PLACEBO_ELECTIONS = fs.PLACEBO_ELECTIONS
DRAWS = fs.DRAWS
SEED = fs.SEED
BATCH = fs.BATCH
MUNICIPAL = fs.MUNICIPAL
STATE_NETWORK = fs.STATE_NETWORK
KEY = fs.KEY
WINDOWS = {"w025": 0.0025, "w050": 0.005, "w100": 0.01}
MAIN_WINDOW = "w050"
FIRST_SCHOOL_YEAR = 2007  # INEP starts in 2007
FIRST_LIGHTS_YEAR = 2013  # VIIRS starts in 2013
GROUPS = ("aligned", "unaligned", "unknown")
BH_LEVEL = 0.05
FINITE_KEYS = frozenset(
    {
        "beta",
        "ri_p",
        "clustered_se",
        "effect_sd",
        "sd_pre",
        "bh_p",
        "beta_aligned",
        "beta_unaligned",
        "diff",
        "ri_p_aligned",
        "ri_p_unaligned",
        "ri_p_diff",
    }
)

Read = fs.Read
ReadSections = fs.ReadSections
ReadCandidates = Callable[[int], pl.DataFrame]


# --- Outcome years and the place_outcomes reader


def outcome_years(election: int, use: str) -> list[int]:
    """The only years read for `use`; all lie in E-4 .. E+4."""
    if use == "school":
        return [y for y in (election - 4, election, election + 4) if y >= FIRST_SCHOOL_YEAR]
    if use == "lights":
        return [
            y for y in range(election - 4, election + 5) if y != election and y >= FIRST_LIGHTS_YEAR
        ]
    if use in ("builtup", "native"):
        return [election, election + 4]
    raise ValueError(f"unknown outcome use {use!r}")


USE_COLUMNS = {
    "school": [*KEY, "located_1km", "school_id", "school_rede", "school_n_fac"],
    "builtup": [*KEY, "located_1km", "builtup_1km"],
    "lights": [*KEY, "located_1km", "lights_1km"],
    "native": [*KEY, "located_1km", "native_10km"],
}


def place_outcomes_year(read: Read, election: int, year: int, use: str) -> pl.DataFrame:
    """One `place_outcomes` file of election E and year y, explicit columns; y in E-4 .. E+4."""
    if not election - 4 <= year <= election + 4:
        raise ValueError(f"year {year} is outside {election - 4} .. {election + 4}")
    if year not in outcome_years(election, use):
        raise ValueError(f"year {year} is not read for {use!r} at election {election}")
    pattern = rf"place_outcomes_E{election}_y{year}\.parquet$"
    return fs.typed(read("place_outcomes", pattern, USE_COLUMNS[use]))


def _column_at(read: Read, election: int, year: int, use: str, column: str, name: str):
    frame = place_outcomes_year(read, election, year, use)
    return frame.select(*KEY, pl.col(column).cast(pl.Float64).alias(name))


def outcome_table(read: Read, election: int) -> pl.DataFrame:
    """Per place of E: located, school, network and the outcomes and baselines of the estimates.

    `n_fac`, `n_fac_pre`, `n_fac_post`; `builtup0`, `builtup4`; `native0`, `native4`;
    `lights_pre`, `lights_post` (means over the years read). Absent years give nulls.
    """
    school = place_outcomes_year(read, election, election, "school")
    out = school.select(
        *KEY,
        pl.col("located_1km").fill_null(False),
        pl.col("school_id"),
        pl.col("school_rede").cast(pl.Utf8).str.strip_chars().alias("rede"),
        pl.col("school_n_fac").cast(pl.Float64).alias("n_fac"),
    )
    school_years = outcome_years(election, "school")
    for year, name in ((election - 4, "n_fac_pre"), (election + 4, "n_fac_post")):
        if year in school_years:
            col = _column_at(read, election, year, "school", "school_n_fac", name)
            out = out.join(col, on=KEY, how="left")
        else:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
    for use, column, names in (
        ("builtup", "builtup_1km", ("builtup0", "builtup4")),
        ("native", "native_10km", ("native0", "native4")),
    ):
        for year, name in zip((election, election + 4), names, strict=True):
            out = out.join(_column_at(read, election, year, use, column, name), on=KEY, how="left")
    if election in LIGHTS_ELECTIONS:
        years = outcome_years(election, "lights")
        for part, name in (
            ([y for y in years if y < election], "lights_pre"),
            ([y for y in years if y > election], "lights_post"),
        ):
            frames = [
                _column_at(read, election, y, "lights", "lights_1km", "lights_1km") for y in part
            ]
            mean = (
                pl.concat(frames)
                .drop_nulls("lights_1km")
                .group_by(KEY)
                .agg(pl.col("lights_1km").mean().alias(name))
            )
            out = out.join(mean, on=KEY, how="left")
    else:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("lights_pre"),
            pl.lit(None, dtype=pl.Float64).alias("lights_post"),
        )
    return out


# --- Alignment of the winner of each pair


def pair_alignment(
    pairs: pl.DataFrame,
    cv: pl.DataFrame,
    cands: pl.DataFrame,
    coalitions: pl.DataFrame,
    main: int,
    year: int,
) -> list[str]:
    """'aligned', 'unaligned' or 'unknown' for each row of `pairs`, by its **winner**.

    Unknown: the municipality has no matched mayor, or the winner has no matched party.
    """
    mayors, _ = al.elected_mayor(cv, main, year)
    coalition, _ = al.mayor_coalition(mayors, cands, coalitions, main)
    sides = al.council_parties(cands, main)
    known = {
        (ue, sq): (party, fed) for ue, sq, party, fed in sides.iter_rows() if party is not None
    }
    out = []
    for ue, winner in pairs.select("sg_ue", "w").iter_rows():
        side = known.get((ue, winner))
        if side is None or ue not in coalition:
            out.append("unknown")
        else:
            aligned = al.is_aligned(side[0], side[1], coalition[ue], year)
            out.append("aligned" if aligned else "unaligned")
    return out


# --- One election


def load_election(
    read: Read,
    read_sections: ReadSections,
    read_candidates: ReadCandidates,
    half: frozenset[str],
    year: int,
) -> dict[str, Any]:
    """Pairs, regression places and triples at each window, and the alignment of 0.50% pairs."""
    cv = read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = read("tse_results", rf"turnout_{year}\.parquet$")
    main = main_election(cv)
    paired = margins(within_list_pairs(candidacy_votes(cv, year, main)), valid_votes(turnout, main))
    pairs = {name: close_pairs(paired, window) for name, window in WINDOWS.items()}
    widest = frozenset(pairs["w100"]["cd_ibge"].unique().to_list())
    pieces = read_sections(year, main, widest)  # sections once, for the 1.00% superset
    votes = pl.concat([v for _, v in pieces])
    out = outcome_table(read, year)
    windows = {}
    for name, window_pairs in pairs.items():
        reg, triples = fs.pair_place_rows(window_pairs, votes)
        reg = restrict(reg.join(out, on=KEY, how="left"), half)
        windows[name] = {"pairs": window_pairs, "reg": reg, "triples": triples}
    coalitions = read("tse_parties", rf"coalitions_{year}\.parquet$", al.COALITION_COLUMNS)
    align = pair_alignment(pairs[MAIN_WINDOW], cv, read_candidates(year), coalitions, main, year)
    return {"year": year, "windows": windows, "align": align}


# --- Benjamini-Hochberg


def bh_adjust(p: list[float]) -> list[float]:
    """Step-up Benjamini-Hochberg adjusted p-values, monotone and capped at 1.

    All `nan` if any p-value is missing: the family cannot be adjusted.
    """
    m = len(p)
    if m == 0 or any(x is None or not np.isfinite(x) for x in p):
        return [float("nan")] * m
    order = sorted(range(m), key=lambda i: p[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * m / rank)
        adjusted[i] = running
    return adjusted


# --- Samples


def _num(df: pl.DataFrame, column: str) -> np.ndarray:
    return fs._array(df, column)


def sample_specs(
    design: Any, names: tuple[str, ...]
) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """(mask, outcome, controls) of each estimate. Controls: S_p and the stated baseline."""
    p = design.places
    s = _num(p, "S")
    has_school = p["school_id"].is_not_null()
    municipal = (has_school & (p["rede"] == MUNICIPAL)).fill_null(False).to_numpy()
    state = (has_school & (p["rede"] == STATE_NETWORK)).fill_null(False).to_numpy()
    located = p["located_1km"].fill_null(False).to_numpy()
    year = p["E"].to_numpy()
    n0, n4 = _num(p, "n_fac"), _num(p, "n_fac_post")
    school_change = n4 - n0
    pre, post = _num(p, "lights_pre"), _num(p, "lights_post")
    b0, b4 = _num(p, "builtup0"), _num(p, "builtup4")
    v0, v4 = _num(p, "native0"), _num(p, "native4")
    school_ok = np.isfinite(school_change) & np.isfinite(n0)
    lights_year = np.isin(year, list(LIGHTS_ELECTIONS))
    every = {
        "primary": (municipal & school_ok, school_change, np.column_stack([s, n0])),
        "falsification": (state & school_ok, school_change, np.column_stack([s, n0])),
        "lights": (
            located & lights_year & np.isfinite(post - pre),
            post - pre,
            np.column_stack([s, pre]),
        ),
        "builtup": (located & np.isfinite(b4 - b0), b4 - b0, np.column_stack([s, b0])),
        "native": (located & np.isfinite(v0 - v4), v0 - v4, np.column_stack([s, v0])),
    }
    return {k: every[k] for k in names}


def sd_pre(design: Any, network: str) -> float | None:
    """SD (ddof 1) of `school_n_fac` at E minus at E-4, places of one network, 2012-2020."""
    p = design.places
    keep = (
        (p["school_id"].is_not_null() & (p["rede"] == network))
        & p["E"].is_in(list(PLACEBO_ELECTIONS))
        & p["n_fac"].is_not_null()
        & p["n_fac_pre"].is_not_null()
    ).fill_null(False)
    change = (p["n_fac"] - p["n_fac_pre"]).filter(keep).to_numpy().astype(float)
    if change.size < 2:
        return None
    sd = float(np.std(change, ddof=1))
    return sd if sd > 0 else None


def prepare_all(
    design: Any, names: tuple[str, ...]
) -> dict[str, tuple[fs.Prepared | None, tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    out = {}
    for name, (mask, y, controls) in sample_specs(design, names).items():
        prep = fs.prepare(
            design.places,
            mask,
            np.nan_to_num(y),
            np.nan_to_num(controls),
            design.t_place,
            design.t_pair,
            design.t_diff,
            design.n_pairs,
        )
        out[name] = (prep, (mask, y, controls))
    return out


# --- Heterogeneity: one regression on D split by the winner's alignment


@dataclass
class Joint:
    """The regression on D_aligned, D_unaligned and D_unknown, for any flip of the pairs."""

    prep: Any  # Prepared, for the same sample as the primary
    group: np.ndarray  # group (0, 1, 2) of the pair of each triple in the sample

    def d_columns(self, sigma: np.ndarray) -> np.ndarray:
        """n x 3 raw D of each group; the columns add up to the pooled D."""
        p = self.prep
        w = sigma[p.t_pair] * p.t_diff
        return np.column_stack(
            [
                np.bincount(p.t_loc, weights=w * (self.group == g), minlength=p.n)
                for g in range(len(GROUPS))
            ]
        )

    def betas(self, sigma: np.ndarray) -> np.ndarray:
        """Slopes of the three terms; `nan` for a term without variation left."""
        p = self.prep
        d = self.d_columns(sigma)
        means = np.column_stack([np.bincount(p.code, weights=d[:, g]) for g in range(d.shape[1])])
        d = d - (means / p.counts[:, None])[p.code]
        if p.c_t.shape[1]:
            d = d - p.proj @ (p.c_t.T @ d)
        gram, moment = d.T @ d, d.T @ p.y_t
        out = np.full(d.shape[1], np.nan)
        active = [g for g in range(d.shape[1]) if gram[g, g] > 1e-12]
        if active:
            try:
                out[active] = np.linalg.solve(gram[np.ix_(active, active)], moment[active])
            except np.linalg.LinAlgError:
                pass
        return out


def make_joint(prep: Any, pair_group: np.ndarray) -> Joint:
    return Joint(prep, pair_group[prep.t_pair])


def joint_draws(
    joint: Joint, n_pairs: int, draws: int = DRAWS, seed: int = SEED, batch: int = BATCH
) -> np.ndarray:
    """(draws x 3) slopes under the same flips as `fs.ri_draws` (same seed, shape and batches)."""
    rng = np.random.default_rng(seed)
    out = np.full((draws, len(GROUPS)), np.nan)
    for start in range(0, draws, batch):
        size = min(batch, draws - start)
        sigma = rng.integers(0, 2, size=(size, n_pairs)).astype(float) * 2.0 - 1.0
        for r in range(size):
            out[start + r] = joint.betas(sigma[r])
    return out


def heterogeneity(
    prep: Any | None, pair_group: np.ndarray, draws: int, seed: int, batch: int, n_pairs: int
) -> dict[str, Any]:
    keys = (
        "beta_aligned",
        "beta_unaligned",
        "diff",
        "ri_p_aligned",
        "ri_p_unaligned",
        "ri_p_diff",
        "n_pairs_aligned",
        "n_pairs_unaligned",
        "n_pairs_unknown",
        "n_places",
    )
    if prep is None:
        return dict.fromkeys(keys)
    joint = make_joint(prep, pair_group)
    observed = joint.betas(np.ones(prep.width))
    sims = joint_draws(joint, n_pairs, draws, seed, batch)
    in_sample = pair_group[np.unique(prep.t_pair)]
    diff = observed[0] - observed[1]
    return {
        "beta_aligned": float(observed[0]),
        "beta_unaligned": float(observed[1]),
        "diff": float(diff),
        "ri_p_aligned": pw.ri_p(observed[0], sims[:, 0]),
        "ri_p_unaligned": pw.ri_p(observed[1], sims[:, 1]),
        "ri_p_diff": pw.ri_p(diff, sims[:, 0] - sims[:, 1]),
        "n_pairs_aligned": int(np.sum(in_sample == 0)),
        "n_pairs_unaligned": int(np.sum(in_sample == 1)),
        "n_pairs_unknown": int(np.sum(in_sample == 2)),
        "n_places": prep.n,
    }


# --- Estimates


def estimate(prep: Any | None, sim: np.ndarray | None) -> dict[str, Any]:
    """beta, RI p, clustered SE, mean |D|, places and pairs of one regression."""
    r = fs.school_placebo(prep, sim)
    return {
        "beta": r["beta"],
        "ri_p": r["ri_p"],
        "clustered_se": r["clustered_se"],
        "mean_abs_d": r["mean_abs_d"],
        "n_places": r["n_places"],
        "n_pairs": None if prep is None else prep.n_pairs,
    }


def with_effect_sd(est: dict[str, Any], sd: float | None) -> dict[str, Any]:
    """Add `sd_pre` and `effect_sd` = beta x mean |D| / sd_pre."""
    ok = est["beta"] is not None and est["mean_abs_d"] is not None and sd is not None
    return {**est, "sd_pre": sd, "effect_sd": est["beta"] * est["mean_abs_d"] / sd if ok else None}


def window_design(data: dict[int, dict[str, Any]], name: str) -> Any:
    return fs.build_design({y: data[y]["windows"][name] for y in sorted(data)})


def all_finite(estimates: dict[str, Any]) -> bool:
    """True only if every beta, p, SE, effect_sd, sd_pre and bh_p is a finite number."""
    seen = 0

    def walk(value: Any) -> bool:
        nonlocal seen
        if not isinstance(value, dict):
            return True
        for key, item in value.items():
            if isinstance(item, dict):
                if not walk(item):
                    return False
            elif key in FINITE_KEYS:
                seen += 1
                if isinstance(item, bool) or not isinstance(item, (int, float, np.number)):
                    return False
                if not np.isfinite(item):
                    return False
        return True

    return walk(estimates) and seen > 0


def compute(
    data: dict[int, dict[str, Any]],
    draws: int = DRAWS,
    seed: int = SEED,
    batch: int = BATCH,
) -> dict[str, Any]:
    """The `estimates` and `design` of the task from the per-election inputs."""
    primary: dict[str, Any] = {}
    estimates: dict[str, Any] = {}
    for name in WINDOWS:
        design = window_design(data, name)
        names = (
            ("primary", "falsification", "lights", "builtup", "native")
            if name == MAIN_WINDOW
            else ("primary",)
        )
        prepared = prepare_all(design, names)
        preps = {k: v[0] for k, v in prepared.items() if v[0] is not None}
        sims = fs.ri_draws(preps, design.n_pairs, draws, seed, batch)
        get = {k: (preps.get(k), sims.get(k)) for k in names}
        primary[name] = with_effect_sd(estimate(*get["primary"]), sd_pre(design, MUNICIPAL))
        if name != MAIN_WINDOW:
            continue
        falsification = with_effect_sd(
            estimate(*get["falsification"]), sd_pre(design, STATE_NETWORK)
        )
        secondary = {k: estimate(*get[k]) for k in ("lights", "builtup", "native")}
        adjusted = bh_adjust(
            [np.nan if secondary[k]["ri_p"] is None else secondary[k]["ri_p"] for k in secondary]
        )
        for k, bh in zip(secondary, adjusted, strict=True):
            secondary[k]["bh_p"] = bh
            secondary[k]["bh_reject_05"] = bool(bh <= BH_LEVEL)
        labels = [g for y in sorted(data) for g in data[y]["align"]]
        pair_group = np.array([GROUPS.index(g) for g in labels], dtype=np.int64)
        hetero = heterogeneity(get["primary"][0], pair_group, draws, seed, batch, design.n_pairs)
    estimates = {
        "primary": primary,
        "falsification": {MAIN_WINDOW: falsification},
        "secondary": secondary,
        "heterogeneity": hetero,
    }
    estimates["finite"] = all_finite(estimates)  # before nan becomes null
    results = {
        "estimates": estimates,
        "design": {
            "windows": dict(WINDOWS),
            "draws": draws,
            "seed": seed,
            "elections": list(ELECTIONS),
            "outcome_years": {
                "school": "E-4 (from 2012), E, E+4",
                "lights": "E-4 .. E-1 and E+1 .. E+4, none before 2013 (2016, 2020 only)",
                "builtup": "E, E+4",
                "native": "E, E+4",
            },
        },
    }
    return pw._clean(results)


# --- Report


def _fmt(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _row(label: str, e: dict[str, Any]) -> str:
    return (
        f"| {label} | {_fmt(e['beta'])} | {_fmt(e['clustered_se'])} | {_fmt(e['ri_p'])} | "
        f"{_fmt(e.get('effect_sd'))} | {_fmt(e.get('sd_pre'))} | {_fmt(e['mean_abs_d'])} | "
        f"{e['n_places']} | {e['n_pairs']} |"
    )


def _summary(results: dict[str, Any]) -> str:
    est, design = results["estimates"], results["design"]
    head = (
        "| Estimate | Slope | Clustered SE | RI p | Effect (SD) | SD pre | Mean abs D | Places "
        "| Pairs |"
    )
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [
        "## Effects of narrow council wins on polling places (exploration half, idea 0006)",
        "",
        "### Primary: change in school facilities, municipal schools, E to E+4",
        "",
        head,
        rule,
    ]
    for name, window in WINDOWS.items():
        lines.append(_row(f"{window:.2%} window", est["primary"][name]))
    lines += [
        "",
        "### Falsification: the same on state schools (expected near zero), 0.50%",
        "",
        head,
        rule,
        _row("0.50% window, state schools", est["falsification"][MAIN_WINDOW]),
        "",
        "### Secondary outcomes, 0.50%, located places",
        "",
        "| Outcome | Slope | Clustered SE | RI p | BH p | Reject at 5% | Mean abs D | Places "
        "| Pairs |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    labels = {"lights": "Night lights", "builtup": "Built-up", "native": "Native loss"}
    for k, label in labels.items():
        e = est["secondary"][k]
        lines.append(
            f"| {label} | {_fmt(e['beta'])} | {_fmt(e['clustered_se'])} | {_fmt(e['ri_p'])} | "
            f"{_fmt(e['bh_p'])} | {e['bh_reject_05']} | {_fmt(e['mean_abs_d'])} | "
            f"{e['n_places']} | {e['n_pairs']} |"
        )
    h = est["heterogeneity"]
    lines += [
        "",
        "### Heterogeneity, 0.50%: winner in the elected mayor's coalition or not",
        "",
        "| Term | Slope | RI p | Pairs |",
        "| --- | --- | --- | --- |",
        f"| Aligned | {_fmt(h['beta_aligned'])} | {_fmt(h['ri_p_aligned'])} | "
        f"{h['n_pairs_aligned']} |",
        f"| Unaligned | {_fmt(h['beta_unaligned'])} | {_fmt(h['ri_p_unaligned'])} | "
        f"{h['n_pairs_unaligned']} |",
        f"| Aligned minus unaligned | {_fmt(h['diff'])} | {_fmt(h['ri_p_diff'])} | |",
        f"| Unknown | | | {h['n_pairs_unknown']} |",
        "",
        f"Places in the heterogeneity regression: {h['n_places']}. All estimates finite: "
        f"{est['finite']}.",
        "",
        f"Caveats: exploration half only; {design['draws']:,} flips of every pair (seed "
        f"{design['seed']}), the same at a window; post-election years E+1 .. E+4 only as listed "
        "in the design. A result here is a reason to register, not a finding, and carries no "
        "causal claim beyond the exploration half.",
    ]
    return "\n".join(lines)


# --- Reading from GCS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:
        read, read_sections = fs.make_readers(store, Path(tmp), half)
        cands = al.load_candidates(store, Path(tmp), half)

        def read_candidates(year: int) -> pl.DataFrame:
            return cands.filter(pl.col("ano_eleicao") == year)

        data = {
            year: load_election(read, read_sections, read_candidates, half, year)
            for year in ELECTIONS
        }
    results = compute(data)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
