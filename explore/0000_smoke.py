"""Smoke test for the explore-run workflow (idea 0000: infrastructure).

Reads the exploration list and the municipalities table, restricts the
table to the exploration half, and reports counts by state. It proves the
workflow, the analysis account and the restriction work end to end; it is
not research.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "data" / "manifests" / "build" / "municipalities.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = [f["path"] for f in manifest["files"]]
    path = next(p for p in files if p.endswith("municipalities.parquet"))
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "municipalities.parquet"
        store.download(path, local)
        table = pl.read_parquet(local)
    legal = table.filter(pl.col("legal_amazon"))
    kept = restrict(legal, half)
    by_state = kept.group_by("uf").len().sort("uf")
    counts = {row["uf"]: row["len"] for row in by_state.iter_rows(named=True)}
    summary = (
        "## explore-run smoke test\n\n"
        f"- Legal Amazon municipalities: {legal.height}\n"
        f"- In the exploration half: {kept.height}\n"
        f"- By state: {', '.join(f'{k} {v}' for k, v in counts.items())}\n\n"
        "Infrastructure check only; not a research result.\n"
    )
    write_results(
        args.out_dir,
        summary,
        {"legal_amazon": legal.height, "exploration_half": kept.height, "by_state": counts},
    )


if __name__ == "__main__":
    main()
