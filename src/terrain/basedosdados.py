"""Acquire any catalog dataset with a `bigquery:` block from Base dos Dados.

Shared by `pipeline/acquire/sim_homicides.py` and
`pipeline/acquire/ibge_population_annual.py` (idea 0008, campaign 0008 s3).
Everything comes from the catalog entry: the table, the filters, the optional
aggregation, the column list and the minimum row count. The query is built by
`terrain.bigquery`, which refuses personal-identifier columns. Nothing here
logs a row value or a header.

The result is written as `<name>.parquet` and a manifest in a new dated raw
folder. Nothing is uploaded unless the row count matches the summary query and
reaches the block's `min_rows`. A repeat with the same query, the same count
and the same rows per year uploads nothing and reports `unchanged`.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from terrain.acquire import AcquireError
from terrain.bigquery import (
    aggregate_columns,
    build_query,
    build_summary_query,
    default_session,
    run_query,
)
from terrain.catalog import dataset
from terrain.inep import _count, _finish_manifest, _source, _write_parquet
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store


def _dtype(values: list[Any]) -> Any:
    """The polars type of a column from its first non-null Python value."""
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            return pl.Boolean
        if isinstance(v, int):
            return pl.Int64
        if isinstance(v, float):
            return pl.Float64
        if isinstance(v, date):
            return pl.Date
        return pl.Utf8
    return pl.Utf8


def _frame(result: Any) -> pl.DataFrame:
    data = {c: [row[i] for row in result.rows] for i, c in enumerate(result.columns)}
    try:
        return pl.DataFrame(data, schema={c: _dtype(v) for c, v in data.items()})
    except Exception as err:
        raise AcquireError("bigquery: a value does not fit its column type") from err


def _rows_per_year(frame: pl.DataFrame) -> dict[str, int]:
    if "ano" not in frame.columns:
        raise AcquireError("the result has no ano column to count rows per year")
    per_year = frame.group_by("ano").len().sort("ano", nulls_last=True)
    return {"null" if a is None else str(a): n for a, n in per_year.iter_rows()}


def _notes(frame: pl.DataFrame, per_year: dict[str, int]) -> str:
    return "\n".join(
        [
            f"rows: {frame.height}",
            "rows per ano: " + ", ".join(f"{a}={n}" for a, n in per_year.items()),
        ]
    )


def _unchanged(
    store: Store,
    root: str,
    name: str,
    query: str,
    count: int,
    per_year: dict[str, int],
    code_commit: str,
) -> dict[str, Any] | None:
    """The `unchanged` manifest when the latest one has the same query, count and years."""
    old = latest_manifest(store, root)
    if old is None:
        return None
    for s in old.get("sources", []):
        same = (
            s.get("fonte") == "basedosdados"
            and s.get("query") == query
            and s.get("rows") == count
            and s.get("rows_per_year") == per_year
        )
        if same:
            return build_manifest(
                dataset=name,
                stage="acquire",
                status="unchanged",
                gcs_prefix=old["gcs_prefix"],
                files=old["files"],
                sources=old["sources"],
                notes=old.get("notes", ""),
                code_commit=code_commit,
            )
    return None


def acquire(
    name: str,
    store: Store,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the acquire for `name`. Uploads the Parquet only when `created`."""
    entry = entry or dataset(name)
    bq = entry.get("bigquery")
    if not isinstance(bq, dict):
        raise AcquireError(f"{name} has no bigquery block in the catalog")
    root = entry["gcs"]
    if not project:
        raise AcquireError("GOOGLE_CLOUD_PROJECT is not set")
    query = build_query(bq)
    summary_query = build_summary_query(bq)
    allowed = aggregate_columns(bq) if bq.get("aggregate") is not None else bq["columns"]
    order = (
        bq["aggregate"]["group_by"] if bq.get("aggregate") is not None else bq["order_by"]
    ) or []

    session = session_factory()
    count = _count(session, bq, project, summary_query)
    result = run_query(
        session,
        bq["endpoint"],
        project,
        query,
        bq["location"],
        int(bq["maximum_bytes_billed"]),
        allowed_columns=allowed,
    )
    if len(result.rows) != count:
        raise AcquireError(f"the query returned {len(result.rows)} rows, the count says {count}")
    min_rows = int(bq.get("min_rows", 1))
    if len(result.rows) < min_rows:
        raise AcquireError(f"the query returned {len(result.rows)} rows, fewer than {min_rows}")

    frame = _frame(result).sort(list(order), nulls_last=True)
    per_year = _rows_per_year(frame)
    old = _unchanged(store, root, name, query, count, per_year, code_commit)
    if old is not None:
        return old

    tmp_dir.mkdir(parents=True, exist_ok=True)
    out, size = _write_parquet(name, frame, tmp_dir)
    source = {**_source(bq, query, result), "rows_per_year": per_year}
    return _finish_manifest(
        name, store, root, today, out, size, [source], _notes(frame, per_year), code_commit
    )


def execute(
    name: str,
    store: Store,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    manifest_out: Path,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one acquire, then write the manifest last (a created one goes to the store too)."""
    manifest = acquire(name, store, session_factory, project, today, tmp_dir, code_commit, entry)
    if manifest["status"] == "created":
        write_manifest(manifest, store, manifest_out)
    else:
        manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def run(name: str) -> None:
    """Entry point for `pipeline/acquire/<name>.py`. Contract: pipeline/README.md."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    entry = dataset(name)
    scope = entry["bigquery"]["scope"]
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = execute(
                name,
                store,
                lambda: default_session(scope),
                os.environ.get("GOOGLE_CLOUD_PROJECT"),
                datetime.now(UTC).date(),
                Path(tmp),
                os.environ.get("CODE_COMMIT", ""),
                args.manifest_out,
                entry,
            )
    except AcquireError as err:
        raise SystemExit(f"acquire failed: {err}") from err
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))
