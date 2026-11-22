"""Whose votes move with an allied mayor, with race controls (idea 0010, fork f1 of step s4).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), decisions 0003, 0008, 0011 and 0015,
campaign `research/campaigns/0013-amendments-mechanisms/campaign.md`, fork f1 of step s4. The
national exploration half only: every panel is restricted to it right after it is read.

It loads the parent `explore/0010_vote_mechanisms.py` and keeps its collapse, outcomes, window
check, Holm adjustment, placebo rule, figures and `results.json` layout. Only the fit changes: four
controls fixed before the mayoral election's result (`party_held_mayor`, `ln(population_m)`, a
round-2 indicator and `n_mayor_cands`) enter every fit as extra regressors, demeaned within the
`deputy` group. Randomisation inference re-flips the same races and holds the controls fixed. Rows
with a null control leave every fit and are counted. The descriptive dose regression stays the
parent's, without controls. A fork result is never a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
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

REPO = Path(__file__).resolve().parents[1]
PARENT_RECORD = REPO / "research" / "explore-runs" / "0010" / "45034178304.json"


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


votes0010 = _load("votes0010", "0010_vote_mechanisms.py")
g9 = votes0010.gate.g9

GateError = votes0010.GateError
CYCLES = votes0010.CYCLES
GRID = votes0010.GRID
CHECK_WINDOW = votes0010.CHECK_WINDOW
WINDOW_SOURCE = votes0010.WINDOW_SOURCE
sign_draws = votes0010.sign_draws
in_window = votes0010.in_window
n_races = votes0010.n_races
prepare = votes0010.prepare
Sample = votes0010.Sample
ri_summary = votes0010.ri_summary
read_window = votes0010.read_window
collapse = votes0010.collapse
holm = votes0010.holm
write_figures = votes0010.write_figures
_check_draws = votes0010._check_draws
_all_finite = votes0010._all_finite
_clean = votes0010._clean
_paths = votes0010._paths
_usable = votes0010._usable
_col = g9._col
_solve = g9._solve
_chunks = g9._chunks

Z95 = votes0010.Z95
PLACEBO_RATIO = votes0010.PLACEBO_RATIO
PLACEBO_P = votes0010.PLACEBO_P
PARTY_OUTCOMES = votes0010.PARTY_OUTCOMES
SCOPES = votes0010.SCOPES
DECLARED = votes0010.DECLARED
CONTROL_SOURCES = ("party_held_mayor", "round", "n_mayor_cands")
CONTROLS = ("party_held_mayor", "ln_population_m", "round_2", "n_mayor_cands")
CONTROL_COLUMNS = ("ctl_held", "ctl_lnpop", "ctl_round2", "ctl_ncands")
GROUP = ["cycle", "cd_ibge", "deputy_party"]
READ_COLUMNS = [*votes0010.READ_COLUMNS, *CONTROL_SOURCES]
FORK_LINE = "Fork of s4 (spec: race controls); a fork result is never a finding."


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> pl.DataFrame:
    """The three panels, each restricted to the exploration half right after it is read."""
    parts = []
    for cycle in CYCLES:
        frame = restrict(read(f"panel_{cycle}", READ_COLUMNS), half)
        parts.append(frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8)))
    return pl.concat(parts, how="vertical_relaxed")


def read_parent(path: Path = PARENT_RECORD) -> dict[str, float | None]:
    """The parent run's pooled b for each party-level outcome, from its `results.json`."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    return {o: record["party"][o]["pooled"]["b"] for o in PARTY_OUTCOMES}


# --- Controls


def check_controls(panel: pl.DataFrame) -> None:
    """Raises `GateError` if a control differs within a (cycle, town, party) group."""
    columns = (*CONTROL_SOURCES, "population_m")
    checks = panel.group_by(GROUP).agg([pl.col(c).n_unique().alias(c) for c in columns])
    for c in columns:
        if checks.filter(pl.col(c) > 1).height:
            raise GateError(f"{c} differs within a (cycle, town, party) group")


def add_controls(table: pl.DataFrame) -> pl.DataFrame:
    """The four controls as `ctl_*` columns; null where a source is null (or population is 0)."""
    pop = pl.col("population_m").cast(pl.Float64)
    return table.with_columns(
        pl.col("party_held_mayor").cast(pl.Float64).alias("ctl_held"),
        pl.when(pop > 0).then(pop.log()).otherwise(None).alias("ctl_lnpop"),
        pl.when(pl.col("round").is_not_null())
        .then((pl.col("round") == 2).cast(pl.Float64))
        .otherwise(None)
        .alias("ctl_round2"),
        pl.col("n_mayor_cands").cast(pl.Float64).alias("ctl_ncands"),
    )


def drop_null_controls(table: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Rows with every control present and finite, and the dropped rows pooled and by cycle."""
    ok = pl.all_horizontal(
        [pl.col(c).is_not_null() & pl.col(c).is_finite() for c in CONTROL_COLUMNS]
    ).fill_null(False)
    dropped = table.filter(~ok)
    counts = {"pooled": int(dropped.height)}
    for c in CYCLES:
        counts[c] = int(dropped.filter(pl.col("cycle") == c).height)
    return table.filter(ok), counts


# --- Tables


def with_controls(panel: pl.DataFrame) -> pl.DataFrame:
    """The parent's collapse plus each group's control sources, then the `ctl_*` columns."""
    sources = panel.group_by(GROUP).agg([pl.col(c).first() for c in CONTROL_SOURCES])
    return add_controls(collapse(panel).join(sources, on=GROUP, how="left"))


def party_table(panel: pl.DataFrame) -> pl.DataFrame:
    """The collapsed panel with controls, through `prepare` (so race ids match the draws)."""
    return prepare(with_controls(panel).with_columns(votes0010._NO_PRE))


def deputy_table(panel: pl.DataFrame) -> pl.DataFrame:
    """The parent's deputy table with the `ctl_*` columns."""
    return add_controls(votes0010.deputy_table(panel))


# --- Fits with controls


def _aligned_controls(sub: pl.DataFrame, sample: Sample) -> np.ndarray:
    """(n, 4) controls in the sample's row order, demeaned within deputy.

    `Sample` sorts by deputy and drops single-row deputies; a second sample whose Y is the row
    index gives the same order.
    """
    idx = Sample(
        np.arange(sub.height, dtype=float),
        np.zeros(sub.height),
        np.zeros(sub.height, dtype=int),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    order = idx.y_raw.astype(int)
    ctl = np.column_stack([_col(sub, c) for c in CONTROL_COLUMNS])[order]
    return sample.demean(ctl.T).T


def _sandwich(x: np.ndarray, sample: Sample, beta: np.ndarray, gram: np.ndarray) -> np.ndarray:
    k = x.shape[1]
    scores = x * (sample.y - x @ beta)[:, None]
    sums = np.column_stack([np.bincount(sample.cluster, weights=scores[:, i]) for i in range(k)])
    bread = np.linalg.inv(gram)
    factor = sample.g / (sample.g - 1) * (sample.n - 1) / (sample.n - k)
    return factor * (bread @ (sums.T @ sums) @ bread)


def fe_fit_c(sample: Sample, ctl: np.ndarray) -> dict[str, float]:
    """b on win with the demeaned controls as extra regressors; clustered SE with K = 3 + 4."""
    nan = {"b": float("nan"), "se": float("nan")}
    k = 3 + ctl.shape[1]
    if sample.n <= k:
        return nan
    x = np.column_stack([sample.design(np.ones((1, sample.n)))[0], ctl])
    gram = x.T @ x
    if np.linalg.matrix_rank(gram) < k:
        return nan
    beta = _solve(gram[None], (x.T @ sample.y)[None])[0]
    if not np.isfinite(beta).all():
        return nan
    if sample.g < 2:
        return {"b": float(beta[0]), "se": float("nan")}
    var = _sandwich(x, sample, beta, gram)[0, 0]
    return {"b": float(beta[0]), "se": float(math.sqrt(var)) if var >= 0 else float("nan")}


def ri_b_c(sample: Sample, ctl: np.ndarray, draws: np.ndarray) -> np.ndarray:
    """The win coefficient refitted under every sign vector, the controls held fixed."""
    out = np.full(draws.shape[0], np.nan)
    k = 3 + ctl.shape[1]
    if sample.n <= k:
        return out
    for a, b in _chunks(draws.shape[0]):
        s = draws[a:b][:, sample.rid].astype(float)
        design = sample.design(s)
        x = np.concatenate([design, np.broadcast_to(ctl, (design.shape[0], *ctl.shape))], axis=-1)
        gram = np.einsum("cni,cnj->cij", x, x)
        xy = np.einsum("cni,n->ci", x, sample.y)
        out[a:b] = _solve(gram, xy)[:, 0]
    return out


def estimate_c(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    """The parent's `estimate` with controls: b, se, ri_p, mean and units."""
    sub = _usable(table, w, column)
    nan = float("nan")
    out: dict[str, Any] = {"b": nan, "se": nan, "ri_p": nan, "mean": nan, "units": int(sub.height)}
    if sub.height == 0:
        return out
    y = _col(sub, column)
    out["mean"] = float(y.mean())
    sample = Sample(
        y,
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    ctl = _aligned_controls(sub, sample)
    fitted = fe_fit_c(sample, ctl)
    out["b"], out["se"] = fitted["b"], fitted["se"]
    out["ri_p"], _ = ri_summary(fitted["b"], ri_b_c(sample, ctl, draws))
    return out


def by_cycle_fit_c(table: pl.DataFrame, w: float, column: str) -> dict[str, Any]:
    """The parent's by-cycle fit (K = 9) with the four controls added (K = 9 + 4)."""
    nan = float("nan")
    empty = {c: {"b": nan, "se": nan} for c in (*CYCLES, "c_minus_a")}
    sub = _usable(table, w, column)
    if sub.height == 0:
        return empty
    cycle = np.array([CYCLES.index(c) for c in sub["cycle"]])
    s = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        cycle,
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    ctl = _aligned_controls(sub, s)
    k = 9 + ctl.shape[1]
    if s.n <= k:
        return empty
    win = (s.margin > 0).astype(float)
    cols = [base * (s.rid == c) for base in (win, s.margin, win * s.margin) for c in range(3)]
    x = np.column_stack([s.demean(col[None, :])[0] for col in cols] + [ctl])
    gram = x.T @ x
    if np.linalg.matrix_rank(gram) < k:
        return empty
    beta = _solve(gram[None], (x.T @ s.y)[None])[0]
    if not np.isfinite(beta).all() or s.g < 2:
        return empty
    v = _sandwich(x, s, beta, gram)
    out: dict[str, Any] = {}
    for i, c in enumerate(CYCLES):
        out[c] = {"b": float(beta[i]), "se": float(math.sqrt(v[i, i])) if v[i, i] >= 0 else nan}
    var_diff = v[2, 2] + v[0, 0] - 2 * v[0, 2]
    out["c_minus_a"] = {
        "b": float(beta[2] - beta[0]),
        "se": float(math.sqrt(var_diff)) if var_diff >= 0 else nan,
    }
    return out


def fit(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    """`estimate_c` plus the 95% interval and the races on the fit's rows."""
    e = estimate_c(table, draws, w, column)
    sub = _usable(table, w, column)
    b, se = e["b"], e["se"]
    return {
        "b": b,
        "se": se,
        "ci_low": b - Z95 * se,
        "ci_high": b + Z95 * se,
        "ri_p": e["ri_p"],
        "mean": e["mean"],
        "n_units": e["units"],
        "n_races": n_races(sub) if sub.height else 0,
    }


def cycle_fits(table: pl.DataFrame, w: float, column: str) -> dict[str, Any]:
    raw = by_cycle_fit_c(table, w, column)
    out = {}
    for scope in SCOPES:
        b, se = raw[scope]["b"], raw[scope]["se"]
        out[scope] = {"b": b, "se": se, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se}
    return out


def outcome_block(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    return {"pooled": fit(table, draws, w, column), **cycle_fits(table, w, column)}


def placebo_block(party: pl.DataFrame, draws: np.ndarray, w: float) -> dict[str, Any]:
    """The two t0 placebos with controls; `t0_fail` by the parent's rule."""
    out: dict[str, Any] = {}
    fails = 0
    for key, column in (("party_t0", "party_share_t0"), ("state_t0", "state_party_share_t0")):
        e = estimate_c(party, draws, w, column)
        mean = e["mean"]
        ratio = abs(e["b"]) / mean if math.isfinite(mean) and mean > 0 else float("nan")
        out[key] = {"b": e["b"], "se": e["se"], "ri_p": e["ri_p"], "mean": mean, "ratio": ratio}
        if abs(e["b"]) > PLACEBO_RATIO * mean and e["ri_p"] < PLACEBO_P:
            fails = 1
    out["t0_fail"] = int(fails)
    return out


# --- Results


def build_results(
    panel: pl.DataFrame, h: float, draws: np.ndarray, source: str = WINDOW_SOURCE
) -> dict[str, Any]:
    """The parent's results at the same paths, fitted with controls. `draws` is the parent's."""
    check_controls(panel)
    party_all = party_table(panel)
    dep_all = deputy_table(panel)
    _check_draws(party_all, draws)
    _check_draws(dep_all, draws)
    party, dropped = drop_null_controls(party_all)
    dep, _ = drop_null_controls(dep_all)
    w5 = GRID[CHECK_WINDOW]

    inside = in_window(party, h)
    by_cycle_counts = {}
    for c in CYCLES:
        s = inside.filter(pl.col("cycle") == c)
        by_cycle_counts[c] = {"rows": int(s.height), "races": n_races(s) if s.height else 0}

    party_out = {o: outcome_block(party, draws, h, o) for o in PARTY_OUTCOMES}
    check = {
        o: {k: v for k, v in fit(party, draws, w5, o).items() if k in ("b", "se", "ri_p")}
        for o in PARTY_OUTCOMES
    }
    n_not_running = int(in_window(dep, h).filter(~pl.col("ran_t1").fill_null(False)).height)
    declared_p = [party_out[o]["pooled"]["ri_p"] for o in DECLARED]
    adjusted = holm(declared_p)

    results: dict[str, Any] = {
        "window": {"h_pct": round(h * 100, 6), "check_pct": round(w5 * 100, 6), "source": source},
        "counts": {
            "party_rows_h": int(inside.height),
            "races_h": n_races(inside) if inside.height else 0,
            "groups_h": int(inside["deputy"].n_unique()),
            "by_cycle": by_cycle_counts,
            "races_equal_t1_share": votes0010.races_equal_t1_share(party, h),
            "dropped_null_controls": dropped,
        },
        "controls": {"names": list(CONTROLS)},
        "party": party_out,
        "check_5pct": check,
        "deputy": {
            "rf_zero": outcome_block(dep, draws, h, "rf_zero"),
            "n_not_running": n_not_running,
        },
        "descriptive": {"dose": votes0010.dose(votes0010.deputy_table(panel), h)},
        "placebo": placebo_block(party, draws, h),
        "declared": {
            o: {"p": p, "p_holm": a} for o, p, a in zip(DECLARED, declared_p, adjusted, strict=True)
        },
    }
    results["estimates"] = {"finite": _all_finite(results)}
    return _clean(results)


# --- Summary


def summarize(results: dict[str, Any], parent: dict[str, float | None] | None = None) -> str:
    """The parent's summary, with the parent's pooled b beside each pooled party estimate."""
    parent = parent or {}
    lines = votes0010.summarize(results).split("\n")
    out = [FORK_LINE, ""]
    d = results["counts"]["dropped_null_controls"]
    out += [
        f"Controls in every fit: {', '.join(results['controls']['names'])}. Party rows dropped for "
        f"a null control: {d['pooled']} (A {d['A']}, B {d['B']}, C {d['C']}).",
        "",
    ]
    section = False
    for line in lines:
        if line.startswith("## "):
            section = line == "## Party level (pooled at h)"
        if section and line.startswith("| Outcome"):
            line += " parent b (no controls) |"
        elif section and line.startswith("| --- "):
            line += " --- |"
        elif section and line.startswith("| "):
            label = line.split("|")[1].strip()
            line += f" {votes0010._fmt(parent.get(label))} |"
        out.append(line)
    return "\n".join(out)


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    h = read_window()
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store, national=True)
    with tempfile.TemporaryDirectory() as tmp:

        def read(name: str, columns: list[str]) -> pl.DataFrame:
            remote = _paths("amendments_panel", rf"{name}\.parquet$")[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = pl.read_parquet(local, columns=columns)
            local.unlink()
            return frame

        panel = load_panels(read, half)
    party = party_table(panel)
    draws = sign_draws(n_races(party))
    results = build_results(panel, h, draws)
    write_figures(results, party_drop(party), h, args.out_dir)
    write_results(args.out_dir, summarize(results, read_parent()), results)


def party_drop(party: pl.DataFrame) -> pl.DataFrame:
    """The party table without null-control rows, as the fits see it."""
    return drop_null_controls(party)[0]


if __name__ == "__main__":
    main()
