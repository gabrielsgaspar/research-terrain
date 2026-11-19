"""What amendments buy: first stage of the powered outcomes and reduced form (idea 0010, step s5).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), decisions 0003, 0008 (the window
rule) and 0011 (national scope), campaign `research/campaigns/0011-amendments-share-of-quota/`,
step s5. The national exploration half only: every panel is restricted to it right after it is
read, before anything else.

It loads `explore/0010_amendments_gate.py` (and through it 0009's gate) and reuses its outcomes,
window rule, draws, model and clustered errors unchanged. Which outcomes are estimated comes from
the run record of step s4's gate (`gate_record`), never from a constant: an outcome the record marks
unpowered is not estimated. It reads `amendments_panel` (`panel_A`, `panel_B`, `panel_C`) only, with
the post-window money and the votes at t1 as outcomes. Its `results.json` carries
`first_stage.n_strong` and `estimates.finite`, the fields step s6's kill rules read. Nothing on the
exploration half is a finding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "research" / "explore-runs" / "0010"


def _load(name: str, file: str) -> Any:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("gate0010", "0010_amendments_gate.py")

GateError = gate.GateError
OUTCOMES = gate.OUTCOMES
CYCLES = gate.CYCLES
GRID = gate.GRID
CHECK_WINDOW = gate.CHECK_WINDOW
sign_draws = gate.sign_draws
choose_window = gate.choose_window
in_window = gate.in_window
estimate = gate.estimate
n_races = gate.n_races
prepare = gate.prepare
Sample = gate.g9.Sample
_check_draws = gate._check_draws
_all_finite = gate._all_finite
_clean = gate._clean
_get = gate._get
_paths = gate._paths
_col = gate.g9._col
_solve = gate.g9._solve
fe_fit = gate.g9.fe_fit

READ_COLUMNS = [
    *gate.READ_COLUMNS,
    "amend_post_share",
    "amend_post_log_pc",
    "amend_post_total",
    "votes_t0",
    "votes_t1",
    "d_share",
    "ran_t1",
]
OUTCOME_COLUMN = {"share": "amend_post_share", "log_pc": "amend_post_log_pc"}
Z = 2.2414  # 97.5% two-sided
STRONG_F = 10.0
GATE_HEADER = "# 0010_amendments_gate, run "


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


# --- The gate's run record


def gate_record(directory: Path) -> dict[str, Any]:
    """Run id, window `h_pct` and powered outcomes (in `OUTCOMES` order) of s4's latest gate record.

    Takes the `<id>.md` files whose first line starts with `# 0010_amendments_gate, run ` and that
    have `<id>.json` beside them (fork records have other script names). Raises if there is none or
    if no outcome is powered.
    """
    found: list[int] = []
    for md in Path(directory).glob("*.md"):
        if not md.stem.isdigit() or not md.with_suffix(".json").is_file():
            continue
        first = md.read_text(encoding="utf-8").split("\n", 1)[0]
        if first.startswith(GATE_HEADER):
            found.append(int(md.stem))
    if not found:
        raise GateError(f"no gate run record in {directory}")
    run_id = max(found)
    record = json.loads((Path(directory) / f"{run_id}.json").read_text(encoding="utf-8"))
    outcomes = record["power"]["outcomes"]
    powered = [o for o in OUTCOMES if outcomes[o]["powered"] == 1]
    if not powered:
        raise GateError(f"gate run {run_id} has no powered outcome")
    return {"run_id": run_id, "h_pct": record["window"]["h_pct"], "powered": powered}


# --- Estimates


def add_columns(table: pl.DataFrame) -> pl.DataFrame:
    """`rf_y` (change in vote share) and `dv_y` (change in votes); null unless `ran_t1` is true."""
    ran = pl.col("ran_t1").fill_null(False).cast(pl.Boolean)
    return table.with_columns(
        pl.when(ran).then(pl.col("d_share").cast(pl.Float64)).otherwise(None).alias("rf_y"),
        pl.when(ran)
        .then(pl.col("votes_t1").cast(pl.Float64) - pl.col("votes_t0").cast(pl.Float64))
        .otherwise(None)
        .alias("dv_y"),
    )


def _usable(table: pl.DataFrame, w: float, column: str) -> pl.DataFrame:
    return in_window(table, w).filter(
        pl.col(column).is_not_null() & pl.col(column).cast(pl.Float64).is_finite()
    )


def full_fit(table: pl.DataFrame, draws: np.ndarray, w: float, column: str) -> dict[str, Any]:
    """`estimate` plus the 97.5% interval, `f_cluster`, `strong` and the races in the fit."""
    e = estimate(table, draws, w, column)
    sub = _usable(table, w, column)
    b, se = e["b"], e["se"]
    f = (b / se) ** 2 if math.isfinite(b) and math.isfinite(se) and se > 0 else float("nan")
    return {
        "b": b,
        "se": se,
        "ci_low": b - Z * se,
        "ci_high": b + Z * se,
        "ri_p": e["ri_p"],
        "mean": e["mean"],
        "n_units": e["units"],
        "n_races": n_races(sub) if sub.height else 0,
        "f_cluster": f,
        "strong": int(math.isfinite(f) and f >= STRONG_F),
    }


def plain_b(table: pl.DataFrame, w: float, column: str) -> float:
    """b of the model for `column` at window `w`, no randomisation inference."""
    sub = _usable(table, w, column)
    if sub.height == 0:
        return float("nan")
    sample = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        sub["race"].to_numpy(),
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    return fe_fit(sample)["b"]


def by_cycle_fit(table: pl.DataFrame, w: float, column: str) -> dict[str, Any]:
    """Win, margin and win x margin each times the cycle dummies; deputy fixed effects.

    Returns b and the clustered SE (by `cd_ibge`, factor G/(G-1) (N-1)/(N-K), K = 9) of `win` in
    each cycle, and the C-minus-A difference. No randomisation inference.
    """
    nan = float("nan")
    empty = {c: {"b": nan, "se": nan} for c in (*CYCLES, "c_minus_a")}
    sub = _usable(table, w, column)
    if sub.height == 0:
        return empty
    cycle = np.array([CYCLES.index(c) for c in sub["cycle"]])
    # the cycle index rides in the `rid` slot: Sample keeps it aligned with its own row order
    s = Sample(
        _col(sub, column),
        _col(sub, "margin"),
        cycle,
        sub["deputy"].to_numpy(),
        sub["cd_ibge"].to_numpy(),
    )
    k = 9
    if s.n <= k:
        return empty
    win = (s.margin > 0).astype(float)
    bases = (win, s.margin, win * s.margin)
    cols = [base * (s.rid == c) for base in bases for c in range(3)]
    x = np.column_stack([s.demean(col[None, :])[0] for col in cols])
    gram = x.T @ x
    try:
        beta = np.linalg.solve(gram, x.T @ s.y)
        bread = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        return empty
    if not np.isfinite(beta).all() or s.g < 2:
        return empty
    scores = x * (s.y - x @ beta)[:, None]
    sums = np.column_stack([np.bincount(s.cluster, weights=scores[:, i]) for i in range(k)])
    factor = s.g / (s.g - 1) * (s.n - 1) / (s.n - k)
    v = factor * (bread @ (sums.T @ sums) @ bread)
    out: dict[str, Any] = {}
    for i, c in enumerate(CYCLES):
        var = v[i, i]
        out[c] = {"b": float(beta[i]), "se": float(math.sqrt(var)) if var >= 0 else nan}
    var_diff = v[2, 2] + v[0, 0] - 2 * v[0, 2]
    out["c_minus_a"] = {
        "b": float(beta[2] - beta[0]),
        "se": float(math.sqrt(var_diff)) if var_diff >= 0 else nan,
    }
    return out


# --- Results

FS_KEYS = (
    "f_cluster",
    "strong",
    "b",
    "se",
    "ci_low",
    "ci_high",
    "ri_p",
    "mean",
    "n_units",
    "n_races",
)
RF_KEYS = ("b", "se", "ci_low", "ci_high", "ri_p", "mean", "n_units")


def build_results(panel: pl.DataFrame, record: dict[str, Any], draws: np.ndarray) -> dict[str, Any]:
    """Everything the step reports. Raises `GateError` if the window or `f_cluster` is unusable."""
    table = add_columns(prepare(panel))
    _check_draws(table, draws)
    chosen = choose_window(panel, draws)
    if not chosen["found"]:
        raise GateError("no window passes decision 0008's balance rule")
    if not math.isclose(chosen["h_pct"], record["h_pct"], abs_tol=1e-9):
        raise GateError(
            f"window h is {chosen['h_pct']}% but the gate record has {record['h_pct']}%: "
            "the data changed since the gate"
        )
    h, w5 = chosen["h"], GRID[CHECK_WINDOW]
    powered = list(record["powered"])

    fs: dict[str, Any] = {}
    fs5: dict[str, Any] = {}
    cycle_fs: dict[str, Any] = {}
    for o in powered:
        col = OUTCOME_COLUMN[o]
        fit = full_fit(table, draws, h, col)
        if not math.isfinite(fit["f_cluster"]):
            raise GateError(f"outcome {o}: f_cluster is not finite")
        fs[o] = {k: fit[k] for k in FS_KEYS}
        f5 = full_fit(table, draws, w5, col)
        fs5[o] = {k: f5[k] for k in ("f_cluster", "b", "se", "ri_p")}
        cycle_fs[o] = by_cycle_fit(table, h, col)

    rf = full_fit(table, draws, h, "rf_y")
    rf5 = full_fit(table, draws, w5, "rf_y")
    not_running = in_window(table, h).filter(~pl.col("ran_t1").fill_null(False)).height

    rf_votes = plain_b(table, h, "dv_y")
    fs_reais = plain_b(table, h, "amend_post_total")
    ratio = 1000.0 * rf_votes / fs_reais if fs_reais != 0 else float("nan")

    results: dict[str, Any] = {
        "gate": {"run_id": record["run_id"], "h_pct": record["h_pct"], "powered": powered},
        "window": {"h_pct": chosen["h_pct"]},
        "first_stage": {"n_strong": sum(v["strong"] for v in fs.values()), "outcomes": fs},
        "reduced_form": {**{k: rf[k] for k in RF_KEYS}, "n_not_running": not_running},
        "by_cycle": {"first_stage": cycle_fs, "reduced_form": by_cycle_fit(table, h, "rf_y")},
        "wald": {
            "votes_per_1000_reais": ratio,
            "rf_votes_b": rf_votes,
            "fs_reais_b": fs_reais,
        },
        "at_5pct": {
            "first_stage": fs5,
            "reduced_form": {k: rf5[k] for k in ("b", "se", "ri_p")},
        },
    }
    results["estimates"] = {"finite": _all_finite(results)}
    results = _clean(results)
    if not isinstance(results["first_stage"]["n_strong"], int):
        raise GateError("first_stage.n_strong is not an integer")
    return results


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def summarize(results: dict[str, Any]) -> str:
    g, fs, rf = results["gate"], results["first_stage"], results["reduced_form"]
    names = {"share": "first stage: share", "log_pc": "first stage: log reais per capita"}
    lines = [
        f"Gate record read: run {g['run_id']} (h {g['h_pct']:g}%). Powered outcomes: "
        f"{', '.join(g['powered'])}. Window h used: {results['window']['h_pct']:g}%. "
        f"Strong first stages (F >= 10): {fs['n_strong']}.",
        "",
        "## Estimates (alpha 0.025 each; 97.5% interval)",
        "",
        "| Estimate | b | SE | 97.5% interval | RI p | mean | units | races |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for o, v in fs["outcomes"].items():
        lines.append(
            f"| {names[o]} at h | {_fmt(v['b'])} | {_fmt(v['se'])} "
            f"| [{_fmt(v['ci_low'])}, {_fmt(v['ci_high'])}] | {_fmt(v['ri_p'])} "
            f"| {_fmt(v['mean'])} | {v['n_units']} | {v['n_races']} |"
        )
    lines.append(
        f"| reduced form at h | {_fmt(rf['b'])} | {_fmt(rf['se'])} "
        f"| [{_fmt(rf['ci_low'])}, {_fmt(rf['ci_high'])}] | {_fmt(rf['ri_p'])} "
        f"| {_fmt(rf['mean'])} | {rf['n_units']} | |"
    )
    for o, v in results["at_5pct"]["first_stage"].items():
        lines.append(
            f"| {names[o]} at 5% | {_fmt(v['b'])} | {_fmt(v['se'])} | | {_fmt(v['ri_p'])} | | | |"
        )
    r5 = results["at_5pct"]["reduced_form"]
    lines.append(
        f"| reduced form at 5% | {_fmt(r5['b'])} | {_fmt(r5['se'])} | | {_fmt(r5['ri_p'])} | | | |"
    )
    lines += [
        "",
        f"Units in the window whose deputy did not run at t1 (left out of the reduced form): "
        f"{rf['n_not_running']}.",
        "",
        "## By cycle (b and SE; no randomisation inference)",
        "",
        "| Estimate | A | B | C | C minus A |",
        "| --- | --- | --- | --- | --- |",
    ]

    def row(label: str, c: dict[str, Any]) -> str:
        cells = [f"{_fmt(c[k]['b'])} ({_fmt(c[k]['se'])})" for k in ("A", "B", "C", "c_minus_a")]
        return f"| {label} | " + " | ".join(cells) + " |"

    for o, c in results["by_cycle"]["first_stage"].items():
        lines.append(row(names[o], c))
    lines.append(row("reduced form", results["by_cycle"]["reduced_form"]))
    w = results["wald"]
    lines += [
        "",
        "## Votes per real (upper bound: allied mayors also campaign)",
        "",
        f"Votes per 1,000 reais: {_fmt(w['votes_per_1000_reais'])} (upper bound), from the reduced "
        f"form on votes, b = {_fmt(w['rf_votes_b'])}, divided by the first stage on reais, "
        f"b = {_fmt(w['fs_reais_b'])}. No standard error, no test.",
        "",
        "## Caveats",
        "",
        "- The outcomes were chosen after campaign 0010's gate failed on per-capita reais.",
        "- Nothing on the exploration half is a finding.",
    ]
    return "\n".join(lines)


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    record = gate_record(RUNS)
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
    draws = sign_draws(n_races(panel))
    results = build_results(panel, record, draws)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
