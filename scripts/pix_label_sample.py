"""Draw the Pix work-plan texts a model labels (decision 0018). Run once, locally, by Gabriel.

    uv run python scripts/pix_label_sample.py

Reads the acquired `cgu_amendments` zip and the `municipalities` table through the catalog
and their manifests (each file checked against its SHA-256), and the two exploration lists.
Keeps the work-plan rows of exploration-half municipalities, draws 3,000 distinct texts with
seed 20261121, stratified by amendment year, and marks 500 of them for a second labelling
pass. Writes, in the git-ignored `build/pix_texts/`:

- `sample.jsonl`: one line per text, `{"key": ..., "text": ...}`, nothing else (no place,
  amendment, value or year);
- `second_pass.txt`: the keys of the 500 marked texts, one per line.

It prints counts only, never a text. Delete `build/pix_texts/` once the labels are written.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import polars as pl

from terrain import pixtext
from terrain.builds.amendments_panel import MUNICIPALITY_COLUMNS, _fetch_frame
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import _fetch, _file
from terrain.catalog import REPO
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
OUT = REPO / "build" / "pix_texts"
N_TEXTS = 3000
N_SECOND = 500


def _load(stage: str, name: str) -> dict:
    return json.loads((MANIFESTS / stage / f"{name}.json").read_text(encoding="utf-8"))


def exploration_keys(plans: pl.DataFrame, explore: frozenset[str]) -> pl.DataFrame:
    """One row per distinct text of exploration-half plans: `key`, `text`, `year` (the
    earliest amendment year the text appears under there)."""
    mine = plans.filter(pl.col("cd_ibge").is_in(sorted(explore)))
    return mine.group_by("key").agg(pl.col("text").first(), pl.col("year").min()).sort("key")


def write_sample(keys: pl.DataFrame, out: Path) -> tuple[list[str], list[str]]:
    chosen, second = pixtext.sample_keys(keys.select("key", "year"), N_TEXTS, N_SECOND)
    texts = dict(keys.select("key", "text").iter_rows())
    out.mkdir(parents=True, exist_ok=True)
    with (out / "sample.jsonl").open("w", encoding="utf-8") as f:
        for key in chosen:
            f.write(json.dumps({"key": key, "text": texts[key]}, ensure_ascii=False) + "\n")
    (out / "second_pass.txt").write_text("".join(k + "\n" for k in second), encoding="utf-8")
    return chosen, second


def main() -> int:
    store = GCSStore(os.environ.get("TERRAIN_BUCKET", "research-terrain"))
    explore, _ = read_lists(store)
    cgu_entry = _file(_load("acquire", "cgu_amendments"), "/EmendasParlamentares.zip")
    muni_entry = _file(_load("build", "municipalities"), "/municipalities.parquet")
    with tempfile.TemporaryDirectory() as tmp:
        munis = _fetch_frame(store, muni_entry, Path(tmp), MUNICIPALITY_COLUMNS)
        zip_path = _fetch(store, cgu_entry, Path(tmp))
        plans = pixtext.plans_with_municipality(pixtext.read_plans(zip_path), munis)
    keys = exploration_keys(plans, explore)
    chosen, second = write_sample(keys, OUT)
    per_year = keys.filter(pl.col("key").is_in(chosen)).group_by("year").len().sort("year")
    print(f"plan rows: {plans.height}")
    print(f"plan rows with a municipality: {plans['cd_ibge'].drop_nulls().len()}")
    print(f"plan rows with no municipality (states, DF): {plans['name_key'].null_count()}")
    print(
        "plan rows naming a municipality that matches none: "
        f"{plans.filter(pl.col('name_key').is_not_null() & pl.col('cd_ibge').is_null()).height}"
    )
    print(f"distinct texts, exploration half: {keys.height}")
    print("sampled per amendment year: " + ", ".join(f"{y}:{n}" for y, n in per_year.iter_rows()))
    print(f"sampled: {len(chosen)}, marked for a second pass: {len(second)}")
    print(f"written: {OUT / 'sample.jsonl'} and {OUT / 'second_pass.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
