"""Structural check of the new paths of idea 0001's registered analysis (campaign 0002, s1).

Runs `terrain.registered.r0001.analysis` on the exploration half at the **0.50%** window
and checks, by seven structural tests, the parts of the analysis that no earlier run has:
the incumbency term Z (`direct_adj`, `ring2_adj`, `ring5_adj`, `direct_pre_adj`), the
direct placebo (`direct_pre`), the alignment split (`align`) and the balance table.

It reports only counts, pass or fail, and the dotted paths of any non-finite value. It
reports no slope, RI p, p1, quantile, clustered SE, mean or percentage of any estimate:
this is a check of the code on real data, not a result. It never runs at the registered
window: `gather` refuses it before reading anything.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain import strongholds as sh
from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.registered.r0001 import analysis
from terrain.registered.r0001 import frozen as fz
from terrain.storage import GCSStore

WINDOW = 0.005  # never the registered window
WINDOW_TEXT = "0.50%"
FLIP_SEED = 20261106  # the seed of the analysis's re-flips
MAX_PATHS = 100
N_CHECKS = 7
KERNELS = {"direct": "exp2", "ring2": "ring2", "ring5": "ring5"}
EXPOSURES = ("direct", "ring2", "ring5", "direct_pre")
ESTIMATE_BLOCKS = ("direct_adj", "ring2_adj", "ring5_adj", "direct_pre", "direct_pre_adj", "align")
NAMES = {
    "c1": "Pairs with exactly one incumbent",
    "c2": "Same cells and pairs with and without Z",
    "c3": "Z fixed under a re-flip",
    "c4": "Alignment split adds up",
    "c5": "Direct placebo uses the direct exposure",
    "c6": "No NaN or infinite value",
    "c7": "Balance on every covariate",
}


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Any failure inside becomes `<name> failed`: no number from the analysis reaches the logs."""
    try:
        yield
    except (Exception, SystemExit):
        raise SystemExit(f"{name} failed") from None


# --- Gathering the parts


def _cells(df: pl.DataFrame) -> pl.DataFrame:
    return df.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    ).sort(sh.CELL)


def _complete(by_year: dict[int, pl.DataFrame], years: list[int]) -> pl.DataFrame:
    """The `nome_1KM` present with `has_data` in every one of `years`."""
    stacked = pl.concat(
        [
            by_year[y]
            .filter(pl.col("has_data").fill_null(False))
            .select("nome_1KM", pl.lit(y, dtype=pl.Int64).alias("yr"))
            for y in years
        ]
    )
    return (
        stacked.group_by("nome_1KM")
        .agg(pl.col("yr").n_unique().alias("n"))
        .filter(pl.col("n") == len(years))
        .select("nome_1KM")
    )


def _swap(pairs: pl.DataFrame, flip: np.ndarray) -> pl.DataFrame:
    mask = pl.Series("flip", flip)
    return pairs.with_columns(
        pl.when(mask).then(pl.col("l")).otherwise(pl.col("w")).alias("w"),
        pl.when(mask).then(pl.col("w")).otherwise(pl.col("l")).alias("l"),
    )


def _direct_parts(
    t: dict[str, Any], pairs: pl.DataFrame, grid: pl.DataFrame, by_year: dict, year: int
) -> dict[str, Any]:
    """The direct cells, terms and samples, rebuilt the way `analysis.outcome_year` does."""
    y_table, _ = fz.outcome_table(by_year, year)
    munis = sorted(set(pairs["cd_ibge"].cast(pl.Utf8).to_list()))
    cells = grid.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(munis))
    with_pairs = analysis.exposure_table(
        cells, t["located"], t["totals"], t["shares"], pairs
    ).filter(pl.col("n_pairs") > 0)
    dist = sh.cell_place_distances(with_pairs.select(sh.CELL), t["located"])
    terms = fz.pair_terms(dist, t["totals"], t["shares"], pairs, "exp2")
    reached = with_pairs.filter(pl.col("d_exp2").is_not_null())
    post_years = fz.window_years(year)["Y4"]
    pre_years = fz.window_years(year)["Ypre"]
    expected = (
        reached.join(_complete(by_year, post_years), on="nome_1KM", how="semi")
        .join(_complete(by_year, pre_years), on="nome_1KM", how="semi")
        .pipe(_cells)
    )
    return {
        "terms": terms,
        "direct": _cells(fz.slot_sample(reached, y_table, "d_exp2", analysis.MAIN_SLOTS)),
        "sample": fz.slot_sample(reached, y_table, "d_exp2", analysis.SLOTS["direct_pre"]),
        "expected": expected,
        "with_cells": with_pairs.select(sh.CELL),
    }


def _flip_terms(
    t: dict[str, Any], pairs: pl.DataFrame, flip: np.ndarray, with_cells: pl.DataFrame
) -> list[dict[str, Any]]:
    """D and Z terms before and after swapping the sides of the flipped pairs."""
    swapped = _swap(pairs, flip)
    dist = sh.cell_place_distances(with_cells, t["located"])
    sign = analysis.incumbent_sign(pairs, t["inc"])
    sign_swapped = analysis.incumbent_sign(swapped, t["inc"])
    out = []
    for label, kernel in KERNELS.items():
        d = fz.pair_terms(dist, t["totals"], t["shares"], pairs, kernel)
        d_swapped = fz.pair_terms(dist, t["totals"], t["shares"], swapped, kernel)
        out.append(
            {
                "label": label,
                "flip": flip,
                "d": d,
                "d_flipped": d_swapped,
                "z": analysis.z_terms(d, sign),
                "z_flipped": analysis.z_terms(d_swapped, sign_swapped),
            }
        )
    return out


def gather(
    store: Any,
    half: frozenset[str],
    window: float,
    tmp: Path,
    draws: int = fz.DRAWS,
    manifests: Path | None = None,
) -> dict[str, Any]:
    """Everything the seven checks read. Refuses the registered window before any read."""
    if abs(window - analysis.REGISTERED_WINDOW) < 1e-12:
        raise ValueError("the registered window is not run on any data before registration")
    reader = analysis.Reader(store.download, lambda df: restrict(df, half), "files", tmp, manifests)
    g: dict[str, Any] = {"window": window}
    with stage("analysis"):
        g["results"] = analysis.run(
            reader, analysis.Settings(window, draws, fz.SEED), lambda df: df
        )
    keep: dict[int, Any] = {}
    g.update(pairs={}, s={}, kinds={}, parts={}, pre={}, diffs={}, flips=[])
    with stage("treatment"):
        cands = analysis.load_candidates(reader)
        grid = reader.read("grid_cells", r"grid_cells\.parquet$", analysis.GRID_COLUMNS)
    for year in analysis.ALL_ELECTIONS:
        with stage(f"election {year}"):
            t = analysis.treatment_year(reader, cands, year, window)
            pairs = t["pairs"]
            g["pairs"][year] = pairs.height
            g["s"][year] = analysis.incumbent_sign(pairs, t["inc"])["s"].to_numpy()
            g["kinds"][year] = list(t["align"])
            outcome = analysis.OUTCOME_ELECTIONS
            years = fz.outcome_years(year) if year in outcome else fz.pre_years(year)
            by_year = {y: reader.outcome(y) for y in years}
            g["diffs"][year] = analysis.balance_differences(t, pairs, grid, by_year, year)
            if year in outcome:
                g["parts"][year] = analysis.outcome_year(t, pairs, grid, by_year, year)["parts"]
                g["pre"][year] = _direct_parts(t, pairs, grid, by_year, year)
                keep[year] = {k: t[k] for k in ("located", "totals", "shares", "inc", "pairs")}
            del by_year, t
    with stage("re-flip"):
        total = sum(g["pairs"][y] for y in analysis.OUTCOME_ELECTIONS)
        rng = np.random.default_rng(FLIP_SEED)
        signs = rng.integers(0, 2, size=total).astype(float) * 2.0 - 1.0
        start = 0
        for year in analysis.OUTCOME_ELECTIONS:
            n = g["pairs"][year]
            flip = signs[start : start + n] < 0
            start += n
            t = keep[year]
            g["flips"] += _flip_terms(t, t["pairs"], flip, g["pre"][year].pop("with_cells"))
    return g


# --- The seven checks, each {"pass": bool, "counts": {...}}


def _key(design: Any) -> np.ndarray:
    return design.rows.astype(np.int64) * max(int(design.n_pairs), 1) + design.cols.astype(np.int64)


def _same_design(a: Any, b: Any) -> bool:
    names = ("y_tilde", "group", "election", "muni", "rows", "cols", "vals")
    return a.n_pairs == b.n_pairs and all(
        np.array_equal(getattr(a, n), getattr(b, n)) for n in names
    )


def check_1(g: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    pooled = {"plus": 0, "minus": 0, "zero": 0}
    ok = True
    for year in analysis.OUTCOME_ELECTIONS:
        s = g["s"][year]
        row = {"plus": int(np.sum(s > 0)), "minus": int(np.sum(s < 0)), "zero": int(np.sum(s == 0))}
        counts[f"e{year}"] = row
        ok = ok and row["plus"] + row["minus"] > 0
        for k in pooled:
            pooled[k] += row[k]
    counts["pooled"] = {**pooled, "one_incumbent": pooled["plus"] + pooled["minus"]}
    return {"pass": bool(ok), "counts": counts}


def check_2(g: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {x: {} for x in EXPOSURES}
    ok = True
    for year in analysis.OUTCOME_ELECTIONS:
        s = g["s"][year]
        for x in EXPOSURES:
            d = g["parts"][year][x].designs["beta"]
            z = g["parts"][year][f"{x}_adj"].designs["z"]
            same = all(
                np.array_equal(getattr(d, n), getattr(z, n))
                for n in ("y_tilde", "group", "election", "muni")
            ) and (d.n_pairs == z.n_pairs == s.size)
            # Z's terms are exactly s times D's, on every pair with s != 0 and a term.
            want = np.flatnonzero((s[d.cols] != 0) & (d.vals != 0))
            want_keys, want_vals = _key(d)[want], (s[d.cols] * d.vals)[want]
            order = np.argsort(want_keys)
            z_order = np.argsort(_key(z))
            same = same and np.array_equal(want_keys[order], _key(z)[z_order])
            same = same and np.array_equal(want_vals[order], z.vals[z_order])
            ok = ok and bool(same)
            counts[x][f"e{year}"] = int(np.unique(z.rows[z.vals != 0]).size)
    return {"pass": bool(ok), "counts": counts}


def _joined(a: pl.DataFrame, b: pl.DataFrame) -> pl.DataFrame | None:
    keys = [*sh.CELL, "pair_id"]
    both = a.join(b.rename({"t": "t_f"}), on=keys, how="full", coalesce=True)
    return None if both["t"].null_count() or both["t_f"].null_count() else both


def check_3(g: dict[str, Any]) -> dict[str, Any]:
    ok, moved = True, 0
    for item in g["flips"]:
        d, z = _joined(item["d"], item["d_flipped"]), _joined(item["z"], item["z_flipped"])
        if d is None or z is None:
            ok = False
            continue
        t, t_f = d["t"].to_numpy(), d["t_f"].to_numpy()
        flipped = item["flip"][d["pair_id"].to_numpy()]
        ok = ok and bool(np.allclose(t_f, np.where(flipped, -t, t), rtol=1e-9, atol=1e-12))
        ok = ok and bool(np.allclose(z["t"].to_numpy(), z["t_f"].to_numpy(), rtol=1e-9, atol=1e-12))
        moved += int(np.sum(flipped & (t != 0)))
    return {"pass": bool(ok and moved > 0), "counts": {}}


def check_4(g: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    ok = True
    for year in analysis.ALL_ELECTIONS:
        kinds = g["kinds"][year]
        row = {k: kinds.count(k) for k in analysis.ALIGN_KINDS}
        row["pairs"] = int(g["pairs"][year])
        counts[f"e{year}"] = row
        ok = ok and sum(row[k] for k in analysis.ALIGN_KINDS) == row["pairs"] == len(kinds)
    for year in analysis.OUTCOME_ELECTIONS:
        parts = g["parts"][year]
        d = parts["direct"].designs["beta"]
        kind_designs = [parts["align"].designs[k] for k in analysis.ALIGN_KINDS]
        n = max(int(d.n_pairs), 1)
        keys = np.concatenate([_key(x) for x in kind_designs])
        vals = np.concatenate([x.vals for x in kind_designs])
        unique, inverse = np.unique(keys, return_inverse=True)
        summed = np.bincount(inverse, weights=vals, minlength=unique.size)
        order = np.argsort(_key(d))
        ok = ok and n == max(int(kind_designs[0].n_pairs), 1)
        ok = ok and np.array_equal(unique, _key(d)[order])
        ok = ok and np.array_equal(summed, d.vals[order])
    return {"pass": bool(ok), "counts": counts}


def check_5(g: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    ok = True
    for year in analysis.OUTCOME_ELECTIONS:
        pre = g["pre"][year]
        sample = _cells(pre["sample"])
        counts[f"e{year}"] = int(pre["sample"].height)
        ok = ok and sample.equals(pre["expected"])
        ok = ok and sample.join(pre["direct"], on=sh.CELL, how="anti").height == 0
        built = fz.make_part(pre["sample"], {"beta": pre["terms"]}, g["pairs"][year], year)
        ok = ok and _same_design(
            built.designs["beta"], g["parts"][year]["direct_pre"].designs["beta"]
        )
    return {"pass": bool(ok), "counts": counts}


def _nonfinite(value: Any, path: str) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _nonfinite(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _nonfinite(v, f"{path}.{i}")
    elif isinstance(value, (float, np.floating)) and not isinstance(value, bool):
        if not np.isfinite(value):
            yield path


def check_6(g: dict[str, Any]) -> dict[str, Any]:
    results = g["results"]
    bad: list[str] = []
    estimates = results.get("estimates", {})
    for label in ESTIMATE_BLOCKS:
        if label in estimates:
            bad += list(_nonfinite(estimates[label], f"estimates.{label}"))
        else:
            bad.append(f"estimates.{label}")
    if "balance" in results:
        bad += list(_nonfinite(results["balance"], "balance"))
    else:
        bad.append("balance")
    return {
        "pass": not bad,
        "counts": {"nonfinite": len(bad)},
        "paths": bad[:MAX_PATHS],
    }


def check_7(g: dict[str, Any]) -> dict[str, Any]:
    ok = "balance" in g["results"] and g["results"]["balance"].get("omnibus_p") is not None
    columns = [analysis.COVARIATES.index(name) for name in fz.BALANCE]
    for year in analysis.ALL_ELECTIONS:
        diff = g["diffs"][year]
        ok = ok and diff.ndim == 2 and diff.shape[0] > 0
        ok = ok and all(bool(np.isfinite(diff[:, c]).any()) for c in columns)
    return {"pass": bool(ok), "counts": {}}


CHECKS = {
    "c1": check_1,
    "c2": check_2,
    "c3": check_3,
    "c4": check_4,
    "c5": check_5,
    "c6": check_6,
    "c7": check_7,
}


def run_checks(g: dict[str, Any]) -> dict[str, Any]:
    return {name: check(g) for name, check in CHECKS.items()}


# --- Output


def build_results(checks: dict[str, Any]) -> dict[str, Any]:
    failed = sum(1 for c in checks.values() if not c["pass"])
    return {
        "checks": checks,
        "n_checks": N_CHECKS,
        "n_fail": failed,
        "all_pass": failed == 0,
        "window": WINDOW_TEXT,
    }


def _flat(counts: Any, prefix: str = "") -> list[str]:
    if isinstance(counts, dict):
        return [x for k, v in counts.items() for x in _flat(v, f"{prefix}{k}.")]
    return [f"{prefix[:-1]}={counts}"]


def summary(results: dict[str, Any]) -> str:
    head = (
        "Structural checks: pass"
        if results["all_pass"]
        else f"Structural checks: fail ({results['n_fail']} of {results['n_checks']})"
    )
    lines = [head, "", "| Check | Result | Counts |", "| --- | --- | --- |"]
    for name, check in results["checks"].items():
        counts = "; ".join(_flat(check["counts"])) or "-"
        result = "pass" if check["pass"] else "fail"
        lines.append(f"| {name}: {NAMES[name]} | {result} | {counts} |")
    paths = results["checks"]["c6"].get("paths", [])
    if paths:
        lines += ["", "Non-finite values at: " + ", ".join(f"`{p}`" for p in paths)]
    lines += [
        "",
        f"Caveats: exploration half only; {results['window']} is not the registered window, "
        "which is never run before registration; this checks code paths, not estimates.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    with tempfile.TemporaryDirectory() as tmp:
        g = gather(store, half, WINDOW, Path(tmp))
    with stage("checks"):
        results = build_results(run_checks(g))
    write_results(args.out_dir, summary(results), results)


if __name__ == "__main__":
    main()
