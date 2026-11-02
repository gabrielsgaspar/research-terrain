"""Helpers every `explore/` script uses.

Exploration reads only the exploration half of the municipality split
(research/decisions/0001-split-sample.md). Every explore script calls
`exploration_municipalities` and `restrict` before computing anything; a test
in tests/test_explore.py checks that each script does.

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
EXPLORE_ROOT = "data/explore/"
SUMMARY_MAX_BYTES = 20_000
RESULTS_MAX_BYTES = 200_000
_SCRIPT = re.compile(r"(\d{4})_[a-z0-9_]{1,60}")


class ExploreError(Exception):
    """An explore script broke the contract above."""


def exploration_municipalities(store: Store) -> frozenset[str]:
    """IBGE codes (7 digits, strings) of the exploration half."""
    try:
        text = store.read_bytes(EXPLORE_LIST).decode("utf-8")
    except Exception as exc:  # a missing list must stop the run, whatever the store raises
        raise ExploreError(f"cannot read {EXPLORE_LIST}; has the split been sealed?") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["code_ibge"]:
        raise ExploreError(f"{EXPLORE_LIST} must have exactly one column, code_ibge")
    codes = frozenset(row["code_ibge"].strip() for row in reader)
    if not codes or not all(len(c) == 7 and c.isdigit() for c in codes):
        raise ExploreError(f"{EXPLORE_LIST} is empty or holds non-IBGE codes")
    return codes


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
