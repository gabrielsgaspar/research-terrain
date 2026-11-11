"""Acquire ANM SIGMINE active mining processes (idea 0007, campaign 0007 s1).

Contract: `data/contracts/anm_sigmine.md`. Used by `pipeline/acquire/anm_sigmine.py`.
Every URL, field and paging setting comes from the `arcgis:` block of the catalog
entry; nothing is hard-coded here except the holder-name guard.

The layer is an ArcGIS feature service. Its server sends its certificate without
the intermediate, so the intermediate is fetched at run time, checked against a
pinned SHA-256, and added as a trust anchor. Hostname checking stays on.

Some holders are people, so the holder-name field (`NOME`) is never requested
and never stored. Messages here name fields and counts, never row values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from shapely.geometry import shape

from terrain.acquire import AcquireError, _free_prefix, _sha256
from terrain.catalog import dataset
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

FORBIDDEN_PREFIX = "NOME"  # the holder's name; never configurable
MAX_BYTES = 2 * 1024**3
RETRIES = 3  # a failed request is tried again up to this many times
PAUSE_SECONDS = 5.0
TIMEOUT_SECONDS = 120
OUTPUT = "sigmine_active.parquet"
GOLD = {"OURO", "MINÉRIO DE OURO", "OURO NATIVO"}
TYPED = {"OBJECTID": pl.Int64, "ANO": pl.Int64, "AREA_HA": pl.Float64}

GetBytes = Callable[[str], bytes]
GetJson = Callable[[str], Any]
Sleep = Callable[[float], None]


# --- fields and TLS ------------------------------------------------------------


def check_fields(out_fields: list[str]) -> None:
    """Refuse any field that starts with the holder-name prefix. Runs before any request."""
    if not out_fields or "OBJECTID" not in out_fields:
        raise AcquireError("out_fields must list OBJECTID")
    if len(set(out_fields)) != len(out_fields):
        raise AcquireError("out_fields has a repeated field")
    for field in out_fields:
        if str(field).strip().upper().startswith(FORBIDDEN_PREFIX):
            raise AcquireError("out_fields has a holder-name field; it is never requested")


def fetch_intermediate(get_bytes: GetBytes, url: str, sha256: str) -> bytes:
    """The pinned intermediate certificate (DER). A different SHA-256 stops the run."""
    der = get_bytes(url)
    got = hashlib.sha256(der).hexdigest()
    if got != sha256:
        raise AcquireError(f"the intermediate certificate has SHA-256 {got}, not the pinned one")
    return der


def ssl_context(der: bytes) -> ssl.SSLContext:
    """Default context plus the pinned intermediate as a trust anchor.

    The partial-chain flag lets the intermediate anchor the chain even if the
    runner lacks the root above it. Hostname checking and `CERT_REQUIRED` stay on.
    """
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=der)
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def _open(url: str, context: ssl.SSLContext | None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "research-terrain"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context) as response:
        return bytes(response.read())


def default_get_bytes(url: str) -> bytes:
    return _open(url, None)


def default_get_json(context: ssl.SSLContext) -> GetJson:
    def get_json(url: str) -> Any:
        return json.loads(_open(url, context))

    return get_json


# --- paging --------------------------------------------------------------------


def query_url(layer: str, params: dict[str, Any]) -> str:
    return f"{layer}/query?{urllib.parse.urlencode(params)}"


def _get_json(get_json: GetJson, url: str, sleep: Sleep) -> Any:
    """One request, tried again up to RETRIES times. An ArcGIS error body is a failure."""
    reason = ""
    for attempt in range(RETRIES + 1):
        if attempt:
            sleep(PAUSE_SECONDS)
        try:
            body = get_json(url)
        except Exception as err:  # network, TLS, HTTP or JSON errors; only the type is kept
            reason = type(err).__name__
            continue
        if isinstance(body, dict) and "error" in body:
            reason = "the service answered with an error body"
            continue
        return body
    raise AcquireError(f"request failed {RETRIES + 1} times ({reason})")


def _count(get_json: GetJson, layer: str, sleep: Sleep) -> int:
    url = query_url(layer, {"where": "1=1", "returnCountOnly": "true", "f": "json"})
    body = _get_json(get_json, url, sleep)
    n = body.get("count") if isinstance(body, dict) else None
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise AcquireError("the count answer has no whole number `count`")
    return n


def _page(
    get_json: GetJson, cfg: dict[str, Any], offset: int, sleep: Sleep
) -> list[dict[str, Any]]:
    params = {
        "where": "1=1",
        "outFields": ",".join(cfg["out_fields"]),
        "orderByFields": cfg["order_by"],
        "resultOffset": offset,
        "resultRecordCount": cfg["page_size"],
        "outSR": cfg["out_sr"],
        "returnGeometry": "true",
        "f": "geojson",
    }
    body = _get_json(get_json, query_url(cfg["layer"], params), sleep)
    features = body.get("features") if isinstance(body, dict) else None
    if not isinstance(features, list):
        raise AcquireError("a page has no `features` list")
    wanted = set(cfg["out_fields"])
    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict) or set(props) != wanted:
            extra = sorted(set(props) - wanted) if isinstance(props, dict) else []
            raise AcquireError(f"a feature does not carry exactly the requested fields {extra}")
    return features


def _pages(get_json: GetJson, cfg: dict[str, Any], sleep: Sleep) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    size = int(cfg["page_size"])
    while True:
        page = _page(get_json, cfg, len(out), sleep)
        out.extend(page)
        if len(page) < size:  # empty or short
            return out


def page_all(get_json: GetJson, cfg: dict[str, Any], sleep: Sleep = time.sleep) -> list[dict]:
    """Every feature of the layer. Checks the count, the key and the minimum size.

    The service is regenerated daily, so a count that differs from the number
    of features read is tried once more, then fails with both numbers.
    """
    features: list[dict[str, Any]] = []
    expected = 0
    for attempt in range(2):
        expected = _count(get_json, cfg["layer"], sleep)
        features = _pages(get_json, cfg, sleep)
        if len(features) == expected:
            break
        if attempt:
            raise AcquireError(
                f"the service counts {expected} records but {len(features)} were read"
            )
    ids = [f["properties"]["OBJECTID"] for f in features]
    if len(set(ids)) != len(ids):
        raise AcquireError("OBJECTID is not unique")
    if expected < int(cfg["min_records"]):
        raise AcquireError(f"{expected} records, fewer than the minimum {cfg['min_records']}")
    return features


# --- the table -----------------------------------------------------------------


def to_frame(
    features: list[dict[str, Any]], out_fields: list[str]
) -> tuple[pl.DataFrame, int, int]:
    """The table, the number of invalid geometries and of records without geometry.

    Invalid geometries are kept as given; the build repairs them.
    """
    invalid = 0
    missing = 0
    wkb: list[bytes | None] = []
    for feature in features:
        geometry = feature.get("geometry")
        if not geometry:
            missing += 1
            wkb.append(None)
            continue
        try:
            geom = shape(geometry)
        except Exception as err:
            raise AcquireError(f"a geometry cannot be read ({type(err).__name__})") from err
        if not geom.is_valid:
            invalid += 1
        wkb.append(geom.wkb)
    columns = []
    for field in out_fields:
        values = [f["properties"][field] for f in features]
        try:
            columns.append(pl.Series(field.lower(), values, dtype=TYPED.get(field), strict=False))
        except Exception as err:
            raise AcquireError(f"{field}: values do not fit one column type") from err
    columns.append(pl.Series("geometry_wkb", wkb, dtype=pl.Binary))
    return pl.DataFrame(columns), invalid, missing


def counts_by_uf(frame: pl.DataFrame) -> dict[str, int]:
    rows = frame.group_by("uf").len().sort("uf", nulls_last=True).iter_rows()
    return {("null" if uf is None else str(uf)): n for uf, n in rows}


def notes(frame: pl.DataFrame, invalid: int, missing: int, sha256: str) -> str:
    gold = frame.filter(pl.col("subs").str.strip_chars().str.to_uppercase().is_in(sorted(GOLD)))
    lines = [
        f"records: {frame.height}",
        "records by uf: " + ", ".join(f"{k}={n}" for k, n in counts_by_uf(frame).items()),
        f"gold records: {gold.height}",
        f"gold records with ano < 2000: {gold.filter(pl.col('ano') < 2000).height}",
        f"records without ano: {frame['ano'].null_count()}",
        f"invalid geometries (kept as given): {invalid}",
        f"records without geometry: {missing}",
        f"intermediate certificate sha256: {sha256}",
    ]
    return "\n".join(lines)


# --- acquire -------------------------------------------------------------------


def _unchanged(
    store: Store, root: str, name: str, source: dict[str, Any], code_commit: str
) -> dict[str, Any] | None:
    """The `unchanged` manifest when the newest one has the same records and counts per uf."""
    old = latest_manifest(store, root)
    if old is None:
        return None
    for s in old.get("sources", []):
        if (
            s.get("records") == source["records"]
            and s.get("records_by_uf") == source["records_by_uf"]
        ):
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
    store: Store,
    entry: dict[str, Any],
    today: date,
    tmp_dir: Path,
    code_commit: str,
    *,
    get_bytes: GetBytes = default_get_bytes,
    make_get_json: Callable[[ssl.SSLContext], GetJson] = default_get_json,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    """Run the acquire. Uploads the Parquet only when `created`, after every check."""
    cfg = entry["arcgis"]
    check_fields(cfg["out_fields"])
    pin = cfg["tls_intermediate"]
    der = fetch_intermediate(get_bytes, pin["url"], pin["sha256"])
    get_json = make_get_json(ssl_context(der))

    features = page_all(get_json, cfg, sleep)
    frame, invalid, missing = to_frame(features, cfg["out_fields"])
    by_uf = counts_by_uf(frame)
    source = {
        "fonte": "anm_sigmine",
        "layer": cfg["layer"],
        "records": frame.height,
        "records_by_uf": by_uf,
        "intermediate_sha256": pin["sha256"],
    }
    old = _unchanged(store, entry["gcs"], entry["name"], source, code_commit)
    if old is not None:
        return old

    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / OUTPUT
    frame.write_parquet(out)
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise AcquireError(f"{OUTPUT} is {size} bytes, over the 2 GB limit")
    prefix = _free_prefix(store, entry["gcs"], today)
    store.create(prefix + OUTPUT, out)
    return build_manifest(
        dataset=entry["name"],
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=[{"path": prefix + OUTPUT, "sha256": _sha256(out), "bytes": size}],
        sources=[source],
        notes=notes(frame, invalid, missing, pin["sha256"]),
        code_commit=code_commit,
    )


def execute(
    store: Store,
    entry: dict[str, Any],
    today: date,
    tmp_dir: Path,
    code_commit: str,
    manifest_out: Path,
    **injected: Any,
) -> dict[str, Any]:
    """Run the acquire, then write the manifest last (a created one goes to the store too)."""
    manifest = acquire(store, entry, today, tmp_dir, code_commit, **injected)
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
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = execute(
                store,
                entry,
                datetime.now(UTC).date(),
                Path(tmp),
                os.environ.get("CODE_COMMIT", ""),
                args.manifest_out,
            )
    except AcquireError as err:
        raise SystemExit(f"acquire failed: {err}") from err
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))
