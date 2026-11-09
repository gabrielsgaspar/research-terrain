"""Close pairs with exactly one incumbent at the 0.25% window, exploration half (idea 0001).

Decision 0009 (point 5) makes the incumbency-adjusted direct estimate the fallback, and its
Z term draws only on close pairs with exactly one incumbent. Campaign 0002's check 1 counted
them at 0.50%; this script counts them at the registered 0.25% window, by election 2008-2020
and pooled. It reports counts only: no outcome data, no estimate, and it never imports the
registered analysis (which refuses 0.25% before registration).

Definitions are those of campaign 0002's check 1, rebuilt from the explore code the registered
core was copied from: close pairs from `terrain.strongholds`, `incumbent` from
`0001_window.py` (loaded, not copied), and the sign per pair as `incumbent_sign` defines it
(+1 only the winner held the seat, -1 only the loser did, 0 otherwise).

Voter IDs are used in memory by `incumbent` only and reach no output. Exploration half only.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from terrain import strongholds as sh
from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


window_script = _load("one_incumbent_window", "0001_window.py")
census = window_script.census

WINDOW = 0.0025
WINDOW_LABEL = "0.25%"
ELECTIONS = (2008, 2012, 2016, 2020)
DECISION_0008_PAIRS = 2328  # decision 0008; used for one summary line only
KEYS = ("plus", "minus", "zero", "one_incumbent", "pairs")


def year_pairs(
    read: Callable[..., pl.DataFrame], half: frozenset[str], year: int, window: float
) -> pl.DataFrame:
    """The close pairs of one election, as `treatment_year` builds them (no outcome read)."""
    cv = restrict(read("tse_results", rf"candidate_votes_{year}\.parquet$"), half)
    turnout = restrict(read("tse_results", rf"turnout_{year}\.parquet$"), half)
    main = sh.main_election(cv)
    paired = sh.margins(
        sh.within_list_pairs(sh.candidacy_votes(cv, year, main)), sh.valid_votes(turnout, main)
    )
    return sh.close_pairs(paired, window)


def signs(pairs: pl.DataFrame, inc: pl.DataFrame) -> list[int]:
    """+1 if only the winner held the seat, -1 if only the loser did, else 0 (whole numbers)."""
    flag = inc.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        "incumbent",
    )
    out = pairs.with_row_index("pair_id").select(
        "pair_id",
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("w").cast(pl.Utf8),
        pl.col("l").cast(pl.Utf8),
    )
    for side in ("w", "l"):
        out = out.join(
            flag.rename({"sq_candidato": side, "incumbent": f"i_{side}"}),
            on=["cd_eleicao", "sg_ue", side],
            how="left",
        )
    iw, il = pl.col("i_w"), pl.col("i_l")
    sign = pl.when((iw == 1.0) & (il == 0.0)).then(1).when((iw == 0.0) & (il == 1.0)).then(-1)
    return [int(s) for s in out.sort("pair_id").select(sign.otherwise(0).alias("s"))["s"]]


def count(values: list[int]) -> dict[str, int]:
    """Whole-number counts of one election's pair signs."""
    plus = sum(1 for s in values if s == 1)
    minus = sum(1 for s in values if s == -1)
    zero = sum(1 for s in values if s == 0)
    return {
        "plus": plus,
        "minus": minus,
        "zero": zero,
        "one_incumbent": plus + minus,
        "pairs": len(values),
    }


def gather(
    store: Any,
    half: frozenset[str],
    tmp: Path,
    window: float = WINDOW,
) -> dict[int, dict[str, int]]:
    """Counts per election. `window` is a parameter only so tests can run another one."""
    read = window_script.make_reader(store, tmp, half)
    cands, _ = window_script.load_candidates(store, tmp, half)
    out: dict[int, dict[str, int]] = {}
    for year in ELECTIONS:
        inc = window_script.incumbent(cands, year)
        pairs = year_pairs(read, half, year, window)
        out[year] = count(signs(pairs, inc))
    return out


def build_results(counts: dict[int, dict[str, int]]) -> dict[str, Any]:
    """`counts.e<year>` and `counts.pooled`, each with the keys of `KEYS`; whole numbers only."""
    per = {f"e{year}": {k: int(counts[year][k]) for k in KEYS} for year in ELECTIONS}
    pooled = {k: int(sum(counts[year][k] for year in ELECTIONS)) for k in KEYS}
    return {
        "counts": {**per, "pooled": pooled},
        "window": WINDOW_LABEL,
        "elections": list(ELECTIONS),
    }


def _summary(results: dict[str, Any]) -> str:
    c = results["counts"]
    pooled = c["pooled"]
    lines = [
        f"Pairs with exactly one incumbent at {WINDOW_LABEL}, pooled 2008-2020: "
        f"{pooled['one_incumbent']:,}",
        "",
        "| Election | plus | minus | zero | one_incumbent | pairs |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for year in results["elections"]:
        row = c[f"e{year}"]
        lines.append(f"| {year} | " + " | ".join(f"{row[k]:,}" for k in KEYS) + " |")
    lines.append("| pooled | " + " | ".join(f"{pooled[k]:,}" for k in KEYS) + " |")
    same = pooled["pairs"] == DECISION_0008_PAIRS
    lines += [
        "",
        f"Pooled pairs {pooled['pairs']:,} against decision 0008's {DECISION_0008_PAIRS:,}: "
        + ("equal." if same else "not equal."),
        "",
        "Caveats: exploration half only; these are counts of treatments, not outcomes; "
        "no estimate is made; the registered analysis was not run.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    with tempfile.TemporaryDirectory() as tmp:
        counts = gather(store, half, Path(tmp), WINDOW)
    results = build_results(counts)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
