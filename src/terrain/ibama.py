"""Acquire IBAMA fines and embargoes: the open-data portal first, Base dos Dados after.

Shared by `pipeline/acquire/ibama_autos.py` and `ibama_embargos.py`. Contracts:
`data/contracts/ibama_autos.md` and `ibama_embargos.md`. Every URL, table and
column list comes from the catalog entry.

One run: a HEAD probe of the portal page; the portal path only when the
catalog mapping is complete; otherwise (or on any failure) the BigQuery path
in the same run. Both write one Parquet in the contract schema. Names,
CPF/CNPJ and geometries are never stored, and on the BigQuery path never
selected. Nothing here logs a row value or a header.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from terrain.acquire import AcquireError, _free_prefix, _sha256
from terrain.bigquery import build_query, build_summary_query, default_session, run_query
from terrain.catalog import dataset
from terrain.http import Fetcher, UrllibFetcher
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

CHUNK = 1 << 20
MAX_BYTES = 2 * 1024**3  # max_size_gb: 2 in campaign 0004
FORMAT_CHANGE = date(2019, 10, 8)  # Sicafi -> AIe
OPTIONAL_COLUMNS = ("indicador_coordenada_valida", "data_extracao")

_COMMON = {
    "id_municipio": pl.Utf8,
    "sigla_uf": pl.Utf8,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
}
SCHEMAS: dict[str, dict[str, Any]] = {
    "ibama_autos": {
        "fonte": pl.Utf8,
        "formato": pl.Utf8,
        "id_auto": pl.Utf8,
        "data_auto": pl.Date,
        "ano": pl.Int64,
        **_COMMON,
        "tipo_infracao": pl.Utf8,
        "tipo_auto": pl.Utf8,
        "situacao_auto": pl.Utf8,
        "indicador_cancelado": pl.Utf8,
        "gravidade": pl.Utf8,
        "indicador_coordenada_valida": pl.Utf8,
        "data_extracao": pl.Date,
    },
    "ibama_embargos": {
        "fonte": pl.Utf8,
        "id_embargo": pl.Utf8,
        "id_auto": pl.Utf8,
        "data_embargo": pl.Date,
        "ano": pl.Int64,
        **_COMMON,
        "area_ha": pl.Float64,
        "tipo_area": pl.Utf8,
        "indicador_desembargado": pl.Utf8,
        "indicador_coordenada_valida": pl.Utf8,
        "data_extracao": pl.Date,
    },
}
DISTINCT: dict[str, list[str]] = {
    "ibama_autos": [
        "tipo_infracao",
        "tipo_auto",
        "situacao_auto",
        "indicador_cancelado",
        "indicador_coordenada_valida",
    ],
    "ibama_embargos": ["tipo_area", "indicador_desembargado", "indicador_coordenada_valida"],
}


class _PortalError(Exception):
    """The portal path failed; the message holds no data value."""


# --- portal path ---------------------------------------------------------------


def mapping_complete(entry: dict[str, Any]) -> bool:
    """True when the portal mapping names everything the portal path needs."""
    portal = entry.get("portal") or {}
    if portal.get("delimiter") is None or portal.get("encoding") is None:
        return False
    files = portal.get("files") or []
    if not files or any(not f.get("url") for f in files):
        return False
    columns = portal.get("columns") or {}
    required = [v for k, v in columns.items() if k not in OPTIONAL_COLUMNS]
    if not columns or any(v is None for v in required):
        return False
    coordinates = portal.get("coordinates")
    return not (coordinates and any(v is None for v in coordinates.values()))


def probe_portal(fetcher: Fetcher, page: str) -> str:
    """One HEAD request to the portal page; returns a short status line."""
    try:
        fetcher.head(page)
    except Exception as err:
        code = getattr(err, "code", None)
        return f"HTTP {code}" if isinstance(code, int) else type(err).__name__
    return "ok"


def _convert(values: list[str | None], dtype: Any) -> list[Any]:
    out: list[Any] = []
    try:
        for v in values:
            if v is None or v.strip() == "":
                out.append(None)
            elif dtype == pl.Utf8:
                out.append(v)
            elif dtype == pl.Date:
                out.append(date.fromisoformat(v.strip()[:10]))
            elif dtype == pl.Int64:
                out.append(int(v.strip()))
            elif dtype == pl.Float64:
                out.append(float(v.strip().replace(",", ".")))
            else:
                raise _PortalError("a column has a type the portal path does not read")
    except ValueError as err:
        raise _PortalError("a value does not fit its column type") from err
    return out


def _read_zip(path: Path, delimiter: str, encoding: str, wanted: list[str]) -> dict[str, list]:
    """Read only the `wanted` columns of the first CSV inside a zip."""
    try:
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                raise _PortalError("a downloaded zip has a corrupt member")
            members = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
            if not members:
                raise _PortalError("a downloaded zip holds no CSV")
            with zf.open(members[0]) as raw:
                text = io.TextIOWrapper(raw, encoding=encoding, newline="")
                reader = csv.DictReader(text, delimiter=delimiter)
                header = reader.fieldnames or []
                if any(w not in header for w in wanted):
                    raise _PortalError("a mapped column is missing from a file header")
                columns: dict[str, list] = {w: [] for w in wanted}
                for row in reader:
                    for w in wanted:
                        columns[w].append(row.get(w))
                return columns
    except zipfile.BadZipFile as err:
        raise _PortalError("a downloaded file is not a valid zip") from err
    except UnicodeError as err:
        raise _PortalError("a file does not decode with the catalog encoding") from err


def _download(fetcher: Fetcher, url: str, dest: Path) -> dict[str, Any]:
    head = fetcher.head(url)
    with fetcher.get(url) as (_, stream), open(dest, "wb") as out:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            out.write(chunk)
    size = dest.stat().st_size
    if head.content_length is not None and size != head.content_length:
        raise _PortalError("a download is not the size the server announced")
    return {"url": url, "last_modified": head.last_modified, "bytes": size}


def _portal_frame(
    entry: dict[str, Any], fetcher: Fetcher, tmp_dir: Path
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    portal = entry["portal"]
    schema = SCHEMAS[entry["name"]]
    delimiter, encoding = portal["delimiter"], portal["encoding"]
    mapping = portal["columns"]
    sources: list[dict[str, Any]] = []
    main: dict[str, list] | None = None
    coords: dict[str, list] | None = None
    for i, item in enumerate(portal["files"]):
        dest = tmp_dir / f"portal_{i}.zip"
        try:
            info = _download(fetcher, item["url"], dest)
            sources.append({"fonte": "ibama", **info})
            if item.get("role") == "coordinates":
                c = portal["coordinates"]
                coords = _read_zip(
                    dest, delimiter, encoding, [c["key"], c["latitude"], c["longitude"], c["order"]]
                )
            else:
                wanted = [v for v in mapping.values() if v is not None]
                main = _read_zip(dest, delimiter, encoding, list(dict.fromkeys(wanted)))
        finally:
            dest.unlink(missing_ok=True)
    if main is None:
        raise _PortalError("the mapping lists no main file")

    n = len(next(iter(main.values()))) if main else 0
    data: dict[str, list] = {}
    for col, dtype in schema.items():
        if col in ("fonte", "formato"):
            continue
        source_col = mapping.get(col)
        data[col] = [None] * n if source_col is None else _convert(main[source_col], dtype)
    frame = pl.DataFrame(data, schema={c: t for c, t in schema.items() if c in data}, strict=False)
    if coords is not None:
        frame = _fill_coordinates(frame, portal["coordinates"], coords)
    return frame, sources


def _fill_coordinates(
    frame: pl.DataFrame, c: dict[str, str], coords: dict[str, list]
) -> pl.DataFrame:
    """Fill null latitude and longitude from the point with the smallest `order` per key."""
    best: dict[str, tuple[int, float | None, float | None]] = {}
    keys = _convert(coords[c["key"]], pl.Utf8)
    orders = _convert(coords[c["order"]], pl.Int64)
    lats = _convert(coords[c["latitude"]], pl.Float64)
    lons = _convert(coords[c["longitude"]], pl.Float64)
    for key, order, lat, lon in zip(keys, orders, lats, lons, strict=True):
        if key is None or order is None:
            continue
        if key not in best or order < best[key][0]:
            best[key] = (order, lat, lon)
    points = pl.DataFrame(
        {
            "id_auto": list(best),
            "_lat": [v[1] for v in best.values()],
            "_lon": [v[2] for v in best.values()],
        },
        schema={"id_auto": pl.Utf8, "_lat": pl.Float64, "_lon": pl.Float64},
    )
    return (
        frame.join(points, on="id_auto", how="left")
        .with_columns(
            pl.col("latitude").fill_null(pl.col("_lat")),
            pl.col("longitude").fill_null(pl.col("_lon")),
        )
        .drop("_lat", "_lon")
    )


# --- BigQuery path -------------------------------------------------------------


def _bigquery_frame(
    entry: dict[str, Any],
    store: Store,
    session_factory: Callable[[], Any],
    project: str | None,
) -> tuple[pl.DataFrame | None, dict[str, Any]]:
    """Returns (frame, source); the frame is None when nothing changed since the last run."""
    bq = entry["bigquery"]
    if not project:
        raise AcquireError("GOOGLE_CLOUD_PROJECT is not set")
    query = build_query(bq)
    summary_query = build_summary_query(bq)
    session = session_factory()
    max_bytes = int(bq["maximum_bytes_billed"])
    summary = run_query(
        session,
        bq["endpoint"],
        project,
        summary_query,
        bq["location"],
        max_bytes,
        allowed_columns=["max_data_extracao", "n"],
    )
    if len(summary.rows) != 1:
        raise AcquireError("bigquery: the summary query did not return one row")
    latest, count = summary.rows[0]
    max_extraction = latest.isoformat() if latest is not None else None

    old = latest_manifest(store, entry["gcs"])
    if old is not None:
        for s in old.get("sources", []):
            if (
                s.get("fonte") == "basedosdados"
                and s.get("query") == query
                and s.get("max_data_extracao") == max_extraction
                and s.get("rows") == count
            ):
                return None, s

    result = run_query(
        session,
        bq["endpoint"],
        project,
        query,
        bq["location"],
        max_bytes,
        allowed_columns=bq["columns"],
    )
    frame = pl.DataFrame(
        {c: [row[i] for row in result.rows] for i, c in enumerate(result.columns)},
        infer_schema_length=None,
    )
    source = {
        "fonte": "basedosdados",
        "url": bq["page"],
        "table": bq["table"],
        "query": query,
        "location": result.location,
        "max_data_extracao": max_extraction,
        "rows": len(result.rows),
        "total_bytes_processed": result.total_bytes_processed,
        "job_id": result.job_id,
    }
    return frame, source


# --- shared output -------------------------------------------------------------


def add_formato(frame: pl.DataFrame) -> pl.DataFrame:
    """`sicafi` before 2019-10-08, `aie` from that day, null for a null date."""
    return frame.with_columns(
        pl.when(pl.col("data_auto").is_null())
        .then(None)
        .when(pl.col("data_auto") < FORMAT_CHANGE)
        .then(pl.lit("sicafi"))
        .otherwise(pl.lit("aie"))
        .cast(pl.Utf8)
        .alias("formato")
    )


def _finish(name: str, entry: dict[str, Any], frame: pl.DataFrame, fonte: str) -> pl.DataFrame:
    schema = SCHEMAS[name]
    frame = frame.with_columns(pl.lit(fonte).alias("fonte"))
    if name == "ibama_autos":
        frame = add_formato(frame.with_columns(pl.col("data_auto").cast(pl.Date)))
    missing = [c for c in schema if c not in frame.columns]
    if missing:
        raise AcquireError("a column of the contract is missing from the data")
    frame = frame.select(list(schema)).cast(schema)
    order_by = entry["bigquery"]["order_by"]
    return frame.sort(order_by, nulls_last=True, maintain_order=True)


def _distinct_line(frame: pl.DataFrame, column: str) -> str:
    values = sorted("null" if v is None else str(v) for v in frame[column].unique().to_list())
    return f"distinct {column}: {', '.join(values)}"


def _notes(name: str, fonte: str, probe: str, route: str, frame: pl.DataFrame) -> str:
    lines = [
        f"source used: {fonte}",
        f"portal probe: {probe}",
        route,
        f"rows: {frame.height}",
    ]
    lines += [_distinct_line(frame, c) for c in DISTINCT[name]]
    return "\n".join(lines)


def acquire_ibama(
    name: str,
    store: Store,
    fetcher: Fetcher,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one acquire. Returns the manifest; uploads the Parquet only when `created`.

    The caller writes `_MANIFEST.json` (see `execute`), so it is the last object.
    """
    entry = entry or dataset(name)
    portal = entry["portal"]
    root = entry["gcs"]
    probe = probe_portal(fetcher, portal["page"])
    tmp_dir.mkdir(parents=True, exist_ok=True)

    frame: pl.DataFrame | None = None
    sources: list[dict[str, Any]] = []
    fonte = "ibama"
    if mapping_complete(entry):
        try:
            frame, sources = _portal_frame(entry, fetcher, tmp_dir)
            route = "portal used"
        except _PortalError as err:
            route = f"portal failed: {err}"
        except Exception as err:
            route = f"portal failed: {type(err).__name__}"
    else:
        route = "portal skipped: mapping incomplete"

    if frame is None:
        fonte = "basedosdados"
        frame, source = _bigquery_frame(entry, store, session_factory, project)
        if frame is None:
            old = latest_manifest(store, root)
            assert old is not None
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
        sources = [source]

    frame = _finish(name, entry, frame, fonte)
    out = tmp_dir / f"{name}.parquet"
    frame.write_parquet(out)
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise AcquireError(f"{name}.parquet is {size} bytes, over the 2 GB limit")

    notes = _notes(name, fonte, probe, route, frame)
    prefix = _free_prefix(store, root, today)
    store.create(prefix + out.name, out)
    files = [{"path": prefix + out.name, "sha256": _sha256(out), "bytes": size}]
    return build_manifest(
        dataset=name,
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=files,
        sources=sources,
        notes=notes,
        code_commit=code_commit,
    )


def execute(
    name: str,
    store: Store,
    fetcher: Fetcher,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    manifest_out: Path,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`acquire_ibama`, then the manifest last (a created one goes to the store too)."""
    manifest = acquire_ibama(
        name, store, fetcher, session_factory, project, today, tmp_dir, code_commit, entry
    )
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
                UrllibFetcher(),
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
