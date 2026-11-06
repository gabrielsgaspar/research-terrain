"""The main exploration of idea 0001: kill criteria 3 and 4, exploration half.

Estimates the direct effect (`exp2`, decision 0004), the displacement effect (`g_exp10`,
decision 0005) and the constituency split (5 km main, 2 km robustness) on post-election
clearing, and prints one verdict line for each of kill criteria 3 and 4 by the rules of
decision 0007 (`research/decisions/0007-effect-size.md`). Outcome (decision 0006): the sum
of `code_4 / 10,000` over E+1 .. E+4 (`Y4`), E+1 .. E+2 (`Y2`), E-4 .. E-1 (`Ypre`), their
difference `dY` = `Y4` - `Ypre`, and for the 2020 election only 2021 .. 2023 (`Y3`; 2024
is provisional). `outcome_years` fixes the years read; the election year E is never read.

The design, pair terms, randomisation inference and clustered SE are those of
`0001_power.py` (loaded below, not copied), itself built on `0001_placebo.py`. Each of
the 2,000 draws (seed 20261106) flips every close pair with probability 1/2 and computes
every estimate once, so all estimates share the sign vectors and a pair has one index
everywhere. Only exploration-half rows are read.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
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


pw = _load("effects_power", "0001_power.py")
pb = pw.pb
kc1 = pw.kc1
census = pw.census

ELECTIONS = (2008, 2012, 2016, 2020)  # 2024 has no post-election years
BANDS = pw.BANDS
TYPES = pw.TYPES
Y3_ELECTION = 2020
Y3_YEARS = (2021, 2022, 2023)

# Decision 0007 (research/decisions/0007-effect-size.md): the effect size is 8% of the
# four-year baseline clearing at the mean exposure; the design's power at that size is
# 0.94 (direct), 0.797 (displacement) and 0.45 (split difference, 5 km, one-sided); the
# bar is 0.80. Holm at 5% overall decides "clearly non-zero" in kill criterion 4.
EFFECT_SIZE_PCT = 8.0
POWER_DIRECT = 0.94
POWER_DISPLACEMENT = 0.797
POWER_SPLIT = 0.45
POWER_BAR = 0.80
ALPHA = 0.05

DIRECT_RINGS = ("ring2", "ring5")
DISPLACEMENT_RINGS = ("ring10_20", "ring20_50")
NO_TERMS = {
    "cd_ibge": pl.Utf8,
    "x_km": pl.Int64,
    "y_km": pl.Int64,
    "pair_id": pl.Int64,
    "t": pl.Float64,
}
# (label, title) of every estimate, in report order. Labels ending `_y3` are 2020 only.
SPECS = {
    "direct": "Direct, exp2 (verdict, kill criterion 4)",
    "ring2": "Direct, ring2 (robustness)",
    "ring5": "Direct, ring5 (robustness)",
    "displacement": "Displacement, g_exp10 (verdict, kill criterion 4)",
    "disp_pre": "Displacement, g_exp10: placebo (Ypre) and change outcome (dY)",
    "disp_ring10_20": "Displacement, ring10_20 (robustness)",
    "disp_ring20_50": "Displacement, ring20_50 (robustness)",
    "split5": "Constituency split, 5 km (main; verdict, kill criterion 3)",
    "split2": "Constituency split, 2 km (robustness)",
    "direct_y3": "Direct, exp2, Y3 (sensitivity: 2024 is provisional)",
    "displacement_y3": "Displacement, g_exp10, Y3 (sensitivity: 2024 is provisional)",
}
# What the two window slots of each estimate hold (the power helpers know only Y4 and Y2).
SLOTS = {
    "disp_pre": {"Y4": "Ypre", "Y2": "dY"},
    "direct_y3": {"Y4": "Y3", "Y2": "Y3"},
    "displacement_y3": {"Y4": "Y3", "Y2": "Y3"},
}


# --- Outcome years and windows


def outcome_years(election: int) -> list[int]:
    """The only outcome years read for `election`: E-4 .. E-1 and E+1 .. E+4, never E."""
    return [*range(election - 4, election), *range(election + 1, election + 5)]


def window_years(election: int) -> dict[str, list[int]]:
    """The years summed into each outcome (`Y3` for the 2020 election only)."""
    out = {
        "Y4": list(range(election + 1, election + 5)),
        "Y2": list(range(election + 1, election + 3)),
        "Ypre": list(range(election - 4, election)),
    }
    if election == Y3_ELECTION:
        out["Y3"] = list(Y3_YEARS)
    return out


def _window(by_year: dict[int, pl.DataFrame], years: list[int], name: str) -> pl.DataFrame:
    """(`nome_1KM`, `<name>`, `<name>_ok`): the sum of `code_4 / 10,000` over `years`.

    `<name>_ok` is true only for a cell present in every year with `has_data` true.
    """
    stacked = pl.concat(
        [
            by_year[y].select(
                "nome_1KM",
                pl.lit(y, dtype=pl.Int64).alias("yr"),
                pl.col("has_data").fill_null(False).alias("ok"),
                (pl.col("code_4").cast(pl.Float64) / 10_000).alias("v"),
            )
            for y in years
        ]
    )
    n = len(years)
    return stacked.group_by("nome_1KM").agg(
        pl.col("v").sum().alias(name),
        ((pl.len() == n) & (pl.col("yr").filter(pl.col("ok")).n_unique() == n)).alias(f"{name}_ok"),
    )


def outcome_table(
    by_year: dict[int, pl.DataFrame], election: int
) -> tuple[pl.DataFrame, dict[str, int]]:
    """(`nome_1KM`, `Y4`, `Y2`, `Ypre`, `dY`, and `Y3` for 2020), and the cells dropped.

    A cell with a missing or `has_data`-false post year (E+1 .. E+4) is dropped from
    everything (`post_incomplete`). A kept cell with a missing pre year has null `Ypre` and
    `dY` (`pre_incomplete`). Only the years of `window_years` are touched.
    """
    years = window_years(election)
    post = _window(by_year, years["Y4"], "Y4")
    short = _window(by_year, years["Y2"], "Y2")
    pre = _window(by_year, years["Ypre"], "Ypre")
    table = post.join(short.select("nome_1KM", "Y2"), on="nome_1KM", how="left").join(
        pre, on="nome_1KM", how="left"
    )
    if "Y3" in years:
        table = table.join(
            _window(by_year, years["Y3"], "Y3").select("nome_1KM", "Y3"),
            on="nome_1KM",
            how="left",
        )
    kept = table.filter(pl.col("Y4_ok"))
    pre_ok = pl.col("Ypre_ok").fill_null(False)
    kept = kept.with_columns(
        pl.when(pre_ok).then(pl.col("Ypre")).alias("Ypre"),
        pl.when(pre_ok).then(pl.col("Y4") - pl.col("Ypre")).alias("dY"),
    )
    dropped = {
        "post_incomplete": table.height - kept.height,
        "pre_incomplete": int(kept.filter(~pre_ok).height),
    }
    columns = ["nome_1KM", "Y4", "Y2", "Ypre", "dY", *(["Y3"] if "Y3" in years else [])]
    return kept.select(columns).sort("nome_1KM"), dropped


# --- Ring pair terms


def displacement_terms_for(cells: pl.DataFrame, used: pl.DataFrame, name: str) -> pl.DataFrame:
    """(CELL, `pair_id`, `t`): each pair's term of `G_<name>` (`exp10`, `ring10_20`, ...).

    As `power.displacement_terms`, which is fixed to `exp10`, with the kernel as an argument.
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
            g = kernel_g(
                name,
                np.hypot(cx[index] - xw, cy[index] - yw),
                np.hypot(cx[index] - xl, cy[index] - yl),
            )
            nonzero = g != 0
            index_out.append(index[nonzero])
            pair_out.append(np.full(int(nonzero.sum()), int(pair_id), dtype=np.int64))
            term_out.append(g[nonzero])
    if not index_out:
        return pl.DataFrame(schema=NO_TERMS)
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


# --- Samples and parts


def slot_sample(
    cells: pl.DataFrame, outcomes: pl.DataFrame, regressor: str, slots: dict[str, str]
) -> pl.DataFrame:
    """CELL, `D` (the regressor), `Y4` and `Y2`: the slots filled from `outcomes`.

    Cells with a null outcome in either slot are dropped. `slots` maps each slot to the
    outcome column that fills it.
    """
    fill = [pl.col(slots["Y4"]).alias("Y4"), pl.col(slots["Y2"]).alias("Y2")]
    return (
        cells.join(outcomes, on="nome_1KM", how="inner")
        .select(*CELL, pl.col(regressor).alias("D"), *fill)
        .drop_nulls(["Y4", "Y2"])
    )


def empty_part(n_pairs: int, election: int, names: tuple[str, ...] = ("beta",)) -> Any:
    """A part with no cells that keeps the election's `n_pairs` in the pooled numbering."""
    sample = pl.DataFrame(
        schema={
            "cd_ibge": pl.Utf8,
            "x_km": pl.Int64,
            "y_km": pl.Int64,
            "D": pl.Float64,
            "Y4": pl.Float64,
            "Y2": pl.Float64,
        }
    )
    return pw.make_part(
        sample, {n: pl.DataFrame(schema=NO_TERMS) for n in names}, n_pairs, election
    )


# --- Statistics and verdicts


def p1_lower(delta: float | None, draws: np.ndarray) -> float | None:
    """One-sided RI p for kill criterion 3: (1 + #{delta_r <= delta}) / (1 + draws).

    A draw with no estimate counts as extreme, as in `ri_p`.
    """
    if delta is None or np.isnan(delta):
        return None
    finite = draws[~np.isnan(draws)]
    extreme = int(np.sum(finite <= delta)) + draws.size - finite.size
    return (1 + extreme) / (1 + draws.size)


def holm_nonzero(p_direct: float | None, p_disp: float | None) -> dict[str, bool]:
    """Holm at 5% overall on two p-values: the smaller must be below 0.025, then the other
    below 0.05. A missing p never counts as non-zero.
    """
    p = {
        "direct": 1.0 if p_direct is None else p_direct,
        "displacement": 1.0 if p_disp is None else p_disp,
    }
    first, second = sorted(p, key=lambda k: p[k])
    first_nz = p[first] < ALPHA / 2
    return {first: first_nz, second: first_nz and p[second] < ALPHA}


def verdict_kc4(nonzero: dict[str, bool], power_direct: float, power_disp: float) -> str:
    """The kill criterion 4 line (decision 0007)."""
    named = [k for k in ("direct", "displacement") if nonzero[k]]
    if named:
        return (
            "Kill criterion 4 is not met: " + " and ".join(named) + " clearly non-zero "
            f"(Holm, {ALPHA:.0%} overall)."
        )
    below = [
        f"{name} power {power:g}"
        for name, power in (("direct", power_direct), ("displacement", power_disp))
        if power < POWER_BAR
    ]
    if below:
        return (
            f"Kill criterion 4 cannot be applied at 80% power on this half ({', '.join(below)}); "
            "the criterion is unchanged."
        )
    return "Kill criterion 4 is met: both effects are indistinguishable from zero at 80% power."


def verdict_kc3(power: float, delta: float | None, p1: float | None, p2: float | None) -> str:
    """The kill criterion 3 line (decision 0007): one-sided at 5% for delta < 0."""
    shown = f"delta {_fmt(delta, 4)}, one-sided p1 {_fmt(p1)}, two-sided p {_fmt(p2)}"
    if power < POWER_BAR:
        return (
            f"Kill criterion 3 cannot be applied at 80% power on this half (power {power:g}); "
            f"the criterion is unchanged. {shown}."
        )
    if p1 is None:
        return f"Kill criterion 3 cannot be evaluated: delta is not estimable. {shown}."
    if p1 >= ALPHA:
        return f"Kill criterion 3 is met: delta is not below zero (p1 >= {ALPHA}). {shown}."
    return f"Kill criterion 3 is not met: delta is below zero (p1 < {ALPHA}). {shown}."


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def report_estimate(
    spec: Any,
    observed: dict[tuple[str, str, str], float],
    sims: dict[tuple[str, str, str], np.ndarray],
) -> dict[str, Any]:
    """Per slot and slope: slope, RI p (p1 for delta), RI quantiles, clustered SE, means."""
    ones = np.ones(next(iter(spec.designs.values())).n_pairs)
    out: dict[str, Any] = {
        "slots": {},
        "not_estimable": [n for n in spec.designs if n not in spec.kept],
    }
    for w in pw.WINDOWS:
        rows: dict[str, Any] = {}
        for s in spec.slopes:
            key = (spec.label, w, s)
            draws = sims[key]
            finite = draws[~np.isnan(draws)]
            x_abs, y_active = pw.exposure_cells(spec, "indigenous" if s == "delta" else s, w)
            ybar = float(np.mean(y_active)) if y_active.size else None
            x_mean = float(np.mean(x_abs)) if x_abs.size else None
            row: dict[str, Any] = {
                "slope": observed[key],
                "ri_p": pw.ri_p(observed[key], draws),
                "q025": float(np.quantile(finite, 0.025)) if finite.size else None,
                "q975": float(np.quantile(finite, 0.975)) if finite.size else None,
                "mean_y": float(np.mean(spec.y_raw[w])) if spec.y_raw[w].size else None,
                "mean_abs_x": x_mean,
                "mean_y_nonzero": ybar,
                "pct_of_baseline": (
                    None
                    if x_mean is None or ybar is None or np.isnan(observed[key])
                    else pw.pct_effect(observed[key], x_mean, ybar)
                ),
            }
            if s == "delta":
                row["p1"] = p1_lower(observed[key], draws)
            if spec.single:
                d_tilde = pb.demeaned_exposure(spec.designs[s], ones)
                row["clustered_se"] = pb.clustered_se(
                    d_tilde, spec.y_tilde[w], spec.designs[s].muni
                )
            rows[s] = row
        out["slots"][w] = rows
    out["cells_nonzero_by_regressor"] = {
        n: int(np.sum(np.abs(pb.exposure_for(d, ones)) > 1e-12)) for n, d in spec.designs.items()
    }
    return pw._clean(out)


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
    g_columns = [f"g_{k}" for k in ("exp10", *DISPLACEMENT_RINGS)]
    displaced = read(
        "cell_displacement",
        rf"cell_displacement_{year}\.parquet$",
        ["nome_1KM", "cd_ibge", "x_km", "y_km", *g_columns],
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

    y_table, outcome_dropped = outcome_table(outcomes, year)
    n_pairs = pairs.height
    with_pairs = exposed.filter(pl.col("n_pairs") > 0)
    dist = cell_place_distances(with_pairs.select(CELL), located)
    main_slots = {"Y4": "Y4", "Y2": "Y2"}
    parts: dict[str, Any] = {}
    counts: dict[str, dict[str, Any]] = {}

    def add(label: str, sample: pl.DataFrame, terms: dict[str, pl.DataFrame], cells: int) -> None:
        parts[label] = pw.make_part(sample, terms, n_pairs, year)
        counts[label] = pw._counts(sample, pairs, cells - sample.height)

    # Direct effect: exp2, then each ring on its own reached sample.
    for name in ("exp2", *DIRECT_RINGS):
        terms = pb.pair_terms(dist, totals, shares, pairs, name)
        pb.check_terms(terms, with_pairs, name)
        reached = with_pairs.filter(pl.col(f"d_{name}").is_not_null())
        sample = slot_sample(reached, y_table, f"d_{name}", main_slots)
        add("direct" if name == "exp2" else name, sample, {"beta": terms}, reached.height)
        if name == "exp2":
            direct_terms = terms
            direct_sample = sample
            direct_cells = reached.height
            direct_y3 = (
                slot_sample(reached, y_table, "d_exp2", SLOTS["direct_y3"])
                if "Y3" in y_table.columns
                else None
            )

    # Displacement effect: g_exp10, each ring, the placebo and change outcome.
    used = pw.with_pair_ids(stronghold_pairs(pairs, strong, located)[0], pairs)
    disp_terms = {}
    for name in ("exp10", *DISPLACEMENT_RINGS):
        terms = displacement_terms_for(displaced, used, name)
        pw.check_displacement(terms, displaced, f"g_{name}")
        disp_terms[name] = terms
        sample = slot_sample(displaced, y_table, f"g_{name}", main_slots)
        label = "displacement" if name == "exp10" else f"disp_{name}"
        add(label, sample, {"beta": terms}, displaced.height)
    sample = slot_sample(displaced, y_table, "g_exp10", SLOTS["disp_pre"])
    add("disp_pre", sample, {"beta": disp_terms["exp10"]}, displaced.height)

    # The constituency split.
    cand = kc1.candidate_distances(census.close_candidates(paired), strong, tenure)
    side = pw.side_terms(dist, totals, shares, pairs)
    types = {}
    for band in BANDS:
        ptypes = pw.pair_types(pairs, cand, band)
        comps = pw.components(side, ptypes)
        pw.check_components(comps, with_pairs)
        add(f"split{band}", direct_sample, comps, direct_cells)
        types[f"{band}km"] = pw.type_counts(ptypes)

    # Sensitivity on Y3: the 2020 election only; the other elections hold no cells but keep
    # their pairs, so each draw uses the 2020 part of the same sign vector.
    if year == Y3_ELECTION:
        add("direct_y3", direct_y3, {"beta": direct_terms}, direct_cells)
        y3_disp = slot_sample(displaced, y_table, "g_exp10", SLOTS["displacement_y3"])
        add("displacement_y3", y3_disp, {"beta": disp_terms["exp10"]}, displaced.height)
    else:
        for label in ("direct_y3", "displacement_y3"):
            parts[label] = empty_part(n_pairs, year)
            counts[label] = pw._counts(
                slot_sample(displaced.head(0), y_table.head(0), "g_exp10", main_slots), pairs, 0
            )
    return {"parts": parts, "counts": counts, "types": types, "dropped": outcome_dropped}


# --- Report


def _table(est: dict[str, Any], slot_names: dict[str, str]) -> list[str]:
    lines = [
        "| Slope | Window | Slope est. | RI p | p1 | RI 2.5% | RI 97.5% | Clustered SE "
        "| Mean Y | % of baseline |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for w, rows in est["slots"].items():
        for s, r in rows.items():
            lines.append(
                f"| {s} | {slot_names[w]} | {_fmt(r['slope'], 4)} | {_fmt(r['ri_p'])} "
                f"| {_fmt(r.get('p1'))} | {_fmt(r['q025'], 3)} | {_fmt(r['q975'], 3)} "
                f"| {_fmt(r.get('clustered_se'), 3)} | {_fmt(r['mean_y'], 3)} "
                f"| {_fmt(r['pct_of_baseline'], 3)} |"
            )
    return lines


def _types_table(band: str, pooled: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        f"{band}: " + "; ".join(f"{t} {pooled[t]['total']:,}" for t in TYPES),
    ]
    return lines


def _slot_names(label: str) -> dict[str, str]:
    if label == "disp_pre":
        return {"Y4": "placebo Ypre (E-4..E-1)", "Y2": "change dY = Y4 - Ypre"}
    if label.endswith("_y3"):
        return {"Y4": "Y3 (2021-2023)", "Y2": "Y3 (2021-2023, repeated)"}
    return {"Y4": "Y4 (E+1..E+4)", "Y2": "Y2 (E+1..E+2)"}


def _summary(results: dict[str, Any]) -> str:
    v = results["verdicts"]
    lines = [
        "## Kill criteria 3 and 4 (exploration half, decision 0007)",
        "",
        v["kc3"],
        "",
        v["kc4"],
        "",
    ]
    lines += ["Candidates per type, pooled 2008-2020 (winners + losers):"]
    for band in ("5km", "2km"):
        lines += _types_table(band, results["type_counts"][band]["pooled"])
    lines += [""]
    for label, title in SPECS.items():
        est = results["estimates"][label]
        c = est["counts"]["pooled"]
        lines += [
            f"## {title}",
            "",
            f"Cells {c['cells']:,}, non-zero regressor {c['cells_nonzero']:,}, "
            f"municipalities {c['municipalities']:,}, pairs {c['pairs']:,}, "
            f"cells dropped {c['cells_dropped']:,}.",
        ]
        if est["not_estimable"]:
            lines.append("Not estimable (no variance): " + ", ".join(est["not_estimable"]) + ".")
        if label == "disp_pre":
            lines.append("Two blocks: placebo (no verdict) and change outcome (no verdict).")
        lines += [""] + _table(est, _slot_names(label)) + [""]
    drops = results["outcome_cells_dropped"]
    lines += [
        "Outcome cells dropped per election (post year missing: dropped everywhere; pre year "
        "missing: dropped from Ypre and dY only): "
        + "; ".join(
            f"{y}: {d['post_incomplete']:,} / {d['pre_incomplete']:,}" for y, d in drops.items()
        )
        + ".",
        "",
        "Caveats: exploration half only; the power in decision 0007 was measured on "
        "pre-election clearing; the 2 km split and the rings are robustness; the placebo and "
        "dY have no kill-criterion role; Y3 covers the 2020 election only and 2024 is "
        "provisional; the Y2 and Y3 windows, rings, 2 km split, placebo and dY never enter a "
        "verdict. Percentages are 100 x slope x mean |x| / mean Y over the cells with a "
        "non-zero regressor. No effect is interpreted beyond the verdicts.",
    ]
    return "\n".join(lines)


def verdicts(estimates: dict) -> dict[str, Any]:
    """The two verdict lines from the pooled `Y4` estimates (decision 0007)."""
    p_direct = estimates["direct"]["slots"]["Y4"]["beta"]["ri_p"]
    p_disp = estimates["displacement"]["slots"]["Y4"]["beta"]["ri_p"]
    nonzero = holm_nonzero(p_direct, p_disp)
    delta = estimates["split5"]["slots"]["Y4"].get("delta", {})
    return {
        "kc3": verdict_kc3(POWER_SPLIT, delta.get("slope"), delta.get("p1"), delta.get("ri_p")),
        "kc4": verdict_kc4(nonzero, POWER_DIRECT, POWER_DISPLACEMENT),
        "holm_nonzero": nonzero,
        "p_direct": p_direct,
        "p_displacement": p_disp,
        "constants": {
            "effect_size_pct": EFFECT_SIZE_PCT,
            "power_direct": POWER_DIRECT,
            "power_displacement": POWER_DISPLACEMENT,
            "power_split": POWER_SPLIT,
            "power_bar": POWER_BAR,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    parts: dict[str, list[Any]] = {k: [] for k in SPECS}
    counts: dict[str, dict[int, dict[str, Any]]] = {k: {} for k in SPECS}
    types: dict[str, dict[str, dict[str, dict[str, int]]]] = {f"{b}km": {} for b in BANDS}
    dropped: dict[str, dict[str, int]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for year in ELECTIONS:
            got = _year(store, Path(tmp), half, year)
            dropped[str(year)] = got["dropped"]
            for label in SPECS:
                parts[label].append(got["parts"][label])
                counts[label][year] = got["counts"][label]
            for band, per in got["types"].items():
                types[band][str(year)] = per
    specs = {label: pw.assemble(label, parts[label]) for label in SPECS}
    observed, sims = pw.run_ri(specs)
    per_election = pw._per_election(counts, specs)
    estimates = {}
    for label, spec in specs.items():
        estimates[label] = report_estimate(spec, observed, sims)
        estimates[label]["counts"] = per_election[label]
    results = {
        "elections": list(ELECTIONS),
        "draws": pw.DRAWS,
        "seed": pw.SEED,
        "outcome_years": {str(e): outcome_years(e) for e in ELECTIONS},
        "y3_years": list(Y3_YEARS),
        "outcome_cells_dropped": dropped,
        "type_counts": {
            band: {"per_election": per, "pooled": pw.pool_type_counts(per)}
            for band, per in types.items()
        },
        "estimates": estimates,
        "verdicts": verdicts(estimates),
    }
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
