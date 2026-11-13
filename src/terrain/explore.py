"""Helpers every `explore/` script uses.

Exploration reads only the exploration half of the municipality split
(research/decisions/0001-split-sample.md). Every explore script calls
`exploration_municipalities` and `restrict` before computing anything; a test
in tests/test_explore.py checks that each script does.

Ideas with national scope (decision 0011; today idea 0006) call
`exploration_municipalities(store, national=True)`, which returns the Legal
Amazon exploration list and the exploration list of the municipalities
outside it, together. A test checks that every `explore/0006_*.py` does.

The contract for `explore/NNNN_slug.py`, run by the `explore-run` workflow:

    python explore/NNNN_slug.py --out-dir DIR

Environment: TERRAIN_BUCKET, EXPLORE_RUN_ID, CODE_COMMIT. The script writes
DIR/summary.md (Markdown, at most 20 KB) and DIR/results.json (at most 200 KB)
with `write_results`. Larger outputs go to GCS under `output_prefix`.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import polars as pl

from terrain.storage import Store

EXPLORE_LIST = "data/derived/split/explore_municipalities.csv"
EXPLORE_LIST_NON_AMAZON = "data/derived/split/explore_municipalities_non_amazon.csv"
# Every exploration list of a national idea (decision 0011), in reading order.
EXPLORE_LISTS_NATIONAL = (EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON)
NATIONAL_IDEAS = ("0006", "0007", "0008")
EXPLORE_ROOT = "data/explore/"
SUMMARY_MAX_BYTES = 20_000
RESULTS_MAX_BYTES = 200_000
_SCRIPT = re.compile(r"(\d{4})_[a-z0-9_]{1,60}")


class ExploreError(Exception):
    """An explore script broke the contract above."""


def _read_list(store: Store, path: str) -> frozenset[str]:
    try:
        text = store.read_bytes(path).decode("utf-8")
    except Exception as exc:  # a missing list must stop the run, whatever the store raises
        raise ExploreError(f"cannot read {path}; has the split been sealed?") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["code_ibge"]:
        raise ExploreError(f"{path} must have exactly one column, code_ibge")
    codes = frozenset(row["code_ibge"].strip() for row in reader)
    if not codes or not all(len(c) == 7 and c.isdigit() for c in codes):
        raise ExploreError(f"{path} is empty or holds non-IBGE codes")
    return codes


def exploration_municipalities(store: Store, national: bool = False) -> frozenset[str]:
    """IBGE codes (7 digits, strings) of the exploration half.

    By default the Legal Amazon exploration list (decision 0001). With
    `national=True`, the union of that list and the list outside the Legal
    Amazon (decision 0011); a code in both lists stops the run.
    """
    if not national:
        return _read_list(store, EXPLORE_LIST)
    amazon, rest = (_read_list(store, path) for path in EXPLORE_LISTS_NATIONAL)
    if amazon & rest:
        raise ExploreError(f"{len(amazon & rest)} codes are in both exploration lists")
    return amazon | rest


def restrict(
    df: pl.DataFrame, municipalities: frozenset[str], column: str = "cd_ibge"
) -> pl.DataFrame:
    """Keep only rows of exploration municipalities. Raises if `column` is missing."""
    if column not in df.columns:
        raise ExploreError(f"cannot restrict to the exploration half: no column {column!r}")
    return df.filter(pl.col(column).cast(pl.Utf8).is_in(sorted(municipalities)))


def idea_of(script_name: str) -> str:
    """'0001_feasibility_census' -> '0001'."""
    match = _SCRIPT.fullmatch(script_name)
    if not match:
        raise ExploreError(f"explore script names look like 0001_some_name, not {script_name!r}")
    return match.group(1)


def output_prefix(script_name: str, run_id: str) -> str:
    """Where a run's large outputs go: data/explore/<idea>/<script>/<run_id>/."""
    if not run_id.isdigit():
        raise ExploreError(f"run id must be digits, not {run_id!r}")
    idea_of(script_name)
    return f"{EXPLORE_ROOT}{script_name[:4]}/{script_name}/{run_id}/"


def write_results(out_dir: Path, summary_md: str, results: dict[str, Any]) -> None:
    """Write summary.md and results.json, enforcing the size limits."""
    summary = summary_md.strip() + "\n"
    payload = json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if len(summary.encode("utf-8")) > SUMMARY_MAX_BYTES:
        raise ExploreError("summary.md is over 20 KB; put detail in results.json or GCS")
    if len(payload.encode("utf-8")) > RESULTS_MAX_BYTES:
        raise ExploreError("results.json is over 200 KB; put large outputs in GCS")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    (out_dir / "results.json").write_text(payload, encoding="utf-8")
