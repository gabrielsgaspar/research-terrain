"""The amendments gate for the share and log outcomes (idea 0010, step s3).

Idea 0010 (`research/ideas/0010-amendments-share-of-quota.md`), decisions 0003, 0008 (the window
rule) and 0011 (national scope), campaign `research/campaigns/0011-amendments-share-of-quota/`,
step s3. The national exploration half only: every panel is restricted to it right after it is
read, before anything else.

It loads `explore/0009_amendments_gate.py` and reuses its window rule, draws, model and clustered
errors unchanged. On top of them it adds the first-stage power and the placebo of two outcomes,
`share` (the municipality's share of the deputy's pre-window money, relative statistic) and `log_pc`
(ln(1 + reais per inhabitant), absolute statistic), and the deputy-author link by money. It reads no
post-election outcome: `READ_COLUMNS` and `LINK_COLUMNS` are the only columns taken. Its
`results.json` carries the six fields that the kill rules of step s4 read (`RULE_FIELDS`). Nothing
on the exploration half is a finding.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


g9 = _load("gate0009", "0009_amendments_gate.py")

GateError = g9.GateError
sign_draws = g9.sign_draws
choose_window = g9.choose_window
in_window = g9.in_window
estimate = g9.estimate
counts_at = g9.counts_at
n_races = g9.n_races
prepare = g9.prepare
_check_draws = g9._check_draws
_all_finite = g9._all_finite
_clean = g9._clean
_get = g9._get
_paths = g9._paths
GRID = g9.GRID
CHECK_WINDOW = g9.CHECK_WINDOW
COVARIATES = g9.COVARIATES
DRAWS = g9.DRAWS
SEED = g9.SEED
RULE_P = g9.RULE_P
CYCLES = g9.CYCLES

# The only columns read from the panels: nothing measured after the mayoral election.
READ_COLUMNS = [*g9.READ_COLUMNS, "amend_pre_share", "amend_pre_log_pc"]
LINK_COLUMNS = [
    "cycle",
    "authors",
    "deputies",
    "senators",
    "ambiguous",
    "unmatched",
    "ties_broken",
    "non_current_authors",
    "chamber_links",
    "money_share",
]
COUNT_COLUMNS = LINK_COLUMNS[1:-1]
OUTCOMES = ("share", "log_pc")
OUTCOME_COLUMN = {"share": "amend_pre_share", "log_pc": "amend_pre_log_pc"}
LIMITS = {"share": 0.25, "log_pc": 0.223}
ALPHA = 0.025
MDE_K = NormalDist().inv_cdf(1 - ALPHA / 2) + NormalDist().inv_cdf(0.80)
RULE_FIELDS = (
    "window.found",
    "counts.races_h",
    "power.n_powered",
    "placebo.powered_failing",
    "placebo.vote_share_abs",
    "link.money_share",
)


# --- Reading


def load_panels(
    read: Callable[[str, list[str]], pl.DataFrame], half: frozenset[str]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The three panels, each restricted to the exploration half right after it is read.

    `read(name, columns)` returns one file of `amendments_panel` (`panel_A`, `panel_B`,
    `panel_C`, `author_link`). The author link has no `cd_ibge` and is counts only, so it is
    read without `restrict`.
    """
    parts = []
    for cycle in CYCLES:
        frame = restrict(read(f"panel_{cycle}", READ_COLUMNS), half)
        parts.append(frame.with_columns(pl.col("cd_ibge").cast(pl.Utf8)))
    panel = pl.concat(parts, how="vertical_relaxed")
    return panel, read("author_link", LINK_COLUMNS)


# --- Power and placebo of one outcome


def outcome_stats(e: dict[str, Any], outcome: str) -> dict[str, Any]:
    """Power and placebo numbers of one outcome from 0009's `estimate` output."""
    relative = outcome == "share"
    stat = e["share_abs"] if relative else abs(e["b"])
    mde = MDE_K * e["sd_ri"]
    if relative:
        mde_stat = mde / e["mean"] if e["mean"] > 0 else float("nan")
    else:
        mde_stat = mde
    limit = LIMITS[outcome]
    powered = int(math.isfinite(mde_stat) and mde_stat <= limit)
    fails = int(bool(stat > limit))
    return {
        "mde": mde,
        "sd_ri": e["sd_ri"],
        "mean": e["mean"],
        "units": e["units"],
        "mde_stat": mde_stat,
        "limit": limit,
        "powered": powered,
        "b": e["b"],
        "se": e["se"],
        "ri_p": e["ri_p"],
        "stat": stat,
        "fails": fails,
    }


# --- Link


def link_stats(link: pl.DataFrame) -> dict[str, Any]:
    """Per cycle: counts, `money_share` and the head-count share; `money_share` is the smallest.

    Raises if a cycle's row is missing or repeated, or its `money_share` is null.
    """
    by_cycle: dict[str, Any] = {}
    for c in CYCLES:
        rows = link.filter(pl.col("cycle") == c)
        if rows.height != 1:
            raise GateError(f"author_link must have exactly one row for cycle {c}")
        money = rows["money_share"][0]
        if money is None or not math.isfinite(float(money)):
            raise GateError(f"author_link cycle {c}: money_share is null")
        r = {k: int(rows[k][0]) for k in COUNT_COLUMNS}
        denom = r["authors"] - r["senators"]
        if denom <= 0:
            raise GateError(f"author_link cycle {c}: authors minus senators is {denom}")
        by_cycle[c] = {"money_share": float(money), "share": r["deputies"] / denom, **r}
    return {
        "money_share": min(v["money_share"] for v in by_cycle.values()),
        "author_share": min(v["share"] for v in by_cycle.values()),
        "by_cycle": by_cycle,
    }


# --- Results


def build_results(panel: pl.DataFrame, link: pl.DataFrame, draws: np.ndarray) -> dict[str, Any]:
    """Everything the gate reports. Raises `GateError` if a kill-rule field is not a number."""
    table = prepare(panel)
    _check_draws(table, draws)
    chosen = choose_window(panel, draws)
    h = chosen["h"]
    w5 = GRID[CHECK_WINDOW]
    at_h = counts_at(table, h)
    at_5 = counts_at(table, w5)
    stats_h = {o: outcome_stats(estimate(table, draws, h, OUTCOME_COLUMN[o]), o) for o in OUTCOMES}
    stats_5 = {o: outcome_stats(estimate(table, draws, w5, OUTCOME_COLUMN[o]), o) for o in OUTCOMES}
    vote_h = estimate(table, draws, h, "share_t0")
    vote_5 = estimate(table, draws, w5, "share_t0")
    for o in OUTCOMES:
        s = stats_h[o]
        if s["powered"] and not math.isfinite(s["stat"]):
            raise GateError(f"outcome {o} is powered but its placebo statistic is not finite")

    power_keys = ("mde", "sd_ri", "mean", "units", "mde_stat", "limit", "powered")
    placebo_keys = ("b", "se", "ri_p", "mean", "units", "stat", "limit", "fails")
    link_out = link_stats(link)
    results: dict[str, Any] = {
        "window": {"found": chosen["found"], "h_pct": chosen["h_pct"], "grid": chosen["grid"]},
        "counts": {
            "races_h": at_h["races"],
            "units_h": at_h["units"],
            "deputies_h": at_h["deputies"],
            "min_cycle_races_h": min(v["races_h"] for v in at_h["by_cycle"].values()),
            "by_cycle": at_h["by_cycle"],
            "races_5pct": at_5["races"],
            "units_5pct": at_5["units"],
        },
        "power": {
            "alpha": ALPHA,
            "mde_k": MDE_K,
            "n_powered": sum(stats_h[o]["powered"] for o in OUTCOMES),
            "outcomes": {o: {k: stats_h[o][k] for k in power_keys} for o in OUTCOMES},
            "at_5pct": {o: {"mde_stat": stats_5[o]["mde_stat"]} for o in OUTCOMES},
        },
        "placebo": {
            "powered_failing": sum(stats_h[o]["powered"] * stats_h[o]["fails"] for o in OUTCOMES),
            "outcomes": {o: {k: stats_h[o][k] for k in placebo_keys} for o in OUTCOMES},
            "vote_share_abs": vote_h["share_abs"],
            "vote_b": vote_h["b"],
            "vote_se": vote_h["se"],
            "vote_ri_p": vote_h["ri_p"],
            "vote_mean": vote_h["mean"],
            "at_5pct": {
                **{o: {"stat": stats_5[o]["stat"]} for o in OUTCOMES},
                "vote_share_abs": vote_5["share_abs"],
            },
        },
        "link": link_out,
    }
    results["estimates"] = {"finite": _all_finite(results)}
    results = _clean(results)
    for field in RULE_FIELDS:
        value = _get(results, field)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateError(f"kill-rule field {field} is not a finite number")
    return results


# --- Summary


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def summarize(results: dict[str, Any]) -> str:
    win, counts, power = results["window"], results["counts"], results["power"]
    placebo, link = results["placebo"], results["link"]
    h = "none (0.5% fails; other fields use 0.5%)" if not win["found"] else f"{win['h_pct']:g}%"
    lines = [
        f"Window h by decision 0008's balance rule: {h}. "
        f"Close races at h: {counts['races_h']} ({counts['units_h']} units, "
        f"{counts['deputies_h']} deputies). Powered outcomes: {power['n_powered']} of 2. "
        f"Powered outcomes failing the placebo: {placebo['powered_failing']}. "
        f"Smallest money share of the author link: {_fmt(link['money_share'])}.",
        "",
        "## Window table",
        "",
        "| Window | races | units | omnibus p | min p | covariate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, g in win["grid"].items():
        lines.append(
            f"| {label} | {g['races']} | {g['units']} | {_fmt(g['omnibus_p'])} "
            f"| {_fmt(g['min_p'])} | {g['min_p_covariate'] or 'n/a'} |"
        )
    lines += [
        "",
        "## Counts at h",
        "",
        "| Cycle | races | units |",
        "| --- | --- | --- |",
    ]
    for c, v in counts["by_cycle"].items():
        lines.append(f"| {c} | {v['races_h']} | {v['units_h']} |")
    lines.append("")
    lines.append(
        f"At 5% (reported only): {counts['races_5pct']} races, {counts['units_5pct']} units."
    )
    names = {
        "share": "share of the deputy's pre-window money (statistic: abs b / mean)",
        "log_pc": "ln(1 + reais per inhabitant) (statistic: abs b)",
    }
    for o in OUTCOMES:
        p, q = power["outcomes"][o], placebo["outcomes"][o]
        lines += [
            "",
            f"## Outcome `{o}`: {names[o]}",
            "",
            "| mde | mean | units | mde stat | limit | powered |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {_fmt(p['mde'])} | {_fmt(p['mean'])} | {p['units']} | {_fmt(p['mde_stat'])} "
            f"| {_fmt(p['limit'])} | {p['powered']} |",
            "",
            "| placebo b | SE | ri p | stat | limit | fails |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {_fmt(q['b'])} | {_fmt(q['se'])} | {_fmt(q['ri_p'])} | {_fmt(q['stat'])} "
            f"| {_fmt(q['limit'])} | {q['fails']} |",
            "",
            f"At 5% (reported only): mde stat {_fmt(power['at_5pct'][o]['mde_stat'])}, "
            f"placebo stat {_fmt(placebo['at_5pct'][o]['stat'])}.",
        ]
    lines += [
        "",
        "## Vote placebo at h",
        "",
        "| b | SE | ri p | mean | abs b / mean |",
        "| --- | --- | --- | --- | --- |",
        f"| {_fmt(placebo['vote_b'])} | {_fmt(placebo['vote_se'])} "
        f"| {_fmt(placebo['vote_ri_p'])} | {_fmt(placebo['vote_mean'])} "
        f"| {_fmt(placebo['vote_share_abs'])} |",
        "",
        f"At 5% (reported only): {_fmt(placebo['at_5pct']['vote_share_abs'])}.",
        "",
        "## Author link by money",
        "",
        "| Cycle | money share | head-count share | authors | deputies | senators "
        "| ambiguous | unmatched | ties broken | non-current | chamber links |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c, v in link["by_cycle"].items():
        lines.append(
            f"| {c} | {_fmt(v['money_share'])} | {_fmt(v['share'])} | {v['authors']} "
            f"| {v['deputies']} | {v['senators']} | {v['ambiguous']} | {v['unmatched']} "
            f"| {v['ties_broken']} | {v['non_current_authors']} | {v['chamber_links']} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- The two outcomes were chosen after campaign 0010's gate failed on per-capita reais.",
        "- A placebo that passes is not proof of balance.",
        "- Nothing on the exploration half is a finding.",
    ]
    return "\n".join(lines)


# --- Entry point


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

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

        panel, link = load_panels(read, half)
    draws = sign_draws(n_races(panel))
    results = build_results(panel, link, draws)
    write_results(args.out_dir, summarize(results), results)


if __name__ == "__main__":
    main()
