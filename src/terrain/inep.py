"""Acquire INEP school facilities and the school catalogue (idea 0006, campaign 0006 s6).

Shared by `pipeline/acquire/inep_schools.py` and `inep_school_catalogue.py`.
Contracts: `data/contracts/inep_schools.md` and `inep_school_catalogue.md`.
Every URL, table, column list and fingerprint comes from the catalog entry.

`inep_schools` reads Base dos Dados on BigQuery, as `terrain.ibama` does.
`inep_school_catalogue` reads one year of INEP's Censo Escolar microdata and
joins school coordinates from BigQuery. INEP's server does not send its
intermediate certificate, so before any request to INEP the run downloads that
certificate from the address in the catalog, checks its SHA-256 against the
catalog, and adds it to a copy of the system trust store. Verification stays
on and the chain must still end at a root the system trusts. The certificate
is kept in memory: it is never stored, logged or put in a manifest.

Phone numbers, emails and personal names are never selected, and nothing here
logs a row value or a header.
"""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import hashlib
import json
import os
import ssl
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import polars as pl

from terrain.acquire import AcquireError, _free_prefix, _sha256
from terrain.bigquery import build_query, build_summary_query, default_session, run_query
from terrain.catalog import dataset
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

CHUNK = 1 << 20
MAX_BYTES = 2 * 1024**3
MAX_CERT_BYTES = 1 << 16
REQUEST_TIMEOUT = 180  # seconds

FACILITIES = [
    "agua_rede_publica",
    "esgoto_rede_publica",
    "energia_rede_publica",
    "internet",
    "biblioteca_sala_leitura",
    "laboratorio_ciencias",
    "laboratorio_informatica",
    "quadra_esportes",
    "dependencia_pne",
    "acessibilidade_inexistente",
]
SCHOOLS_SCHEMA: dict[str, Any] = {
    "ano": pl.Int64,
    "id_escola": pl.Utf8,
    "id_municipio": pl.Utf8,
    "sigla_uf": pl.Utf8,
    "rede": pl.Utf8,
    "tipo_localizacao": pl.Utf8,
    **{c: pl.Int8 for c in FACILITIES},
}

# catalogue column <- microdata column
CATALOGUE_SOURCE = {
    "ano": "NU_ANO_CENSO",
    "id_escola": "CO_ENTIDADE",
    "nome_escola": "NO_ENTIDADE",
    "id_municipio": "CO_MUNICIPIO",
    "sigla_uf": "SG_UF",
    "rede": "TP_DEPENDENCIA",
    "tipo_localizacao": "TP_LOCALIZACAO",
    "endereco": "DS_ENDERECO",
    "numero": "NU_ENDERECO",
    "complemento": "DS_COMPLEMENTO",
    "bairro": "NO_BAIRRO",
    "cep": "CO_CEP",
}
CATALOGUE_SCHEMA: dict[str, Any] = {
    "ano": pl.Int64,
    **{c: pl.Utf8 for c in CATALOGUE_SOURCE if c != "ano"},
    "latitude": pl.Float64,
    "longitude": pl.Float64,
}
FORBIDDEN_MICRODATA = ("NU_DDD", "NU_TELEFONE")
LAT_RANGE = (-34.0, 6.0)
LON_RANGE = (-74.0, -28.0)

Opener = Callable[..., Any]


def _urlopen(url: str, context: ssl.SSLContext | None = None) -> Any:
    if urlsplit(url).scheme not in ("http", "https"):
        raise AcquireError("a download address is not an http address")
    return urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT, context=context)  # noqa: S310


def _frame_from(result: Any, schema: dict[str, Any]) -> pl.DataFrame:
    missing = [c for c in schema if c not in result.columns]
    if missing:
        raise AcquireError("bigquery: a column of the contract is missing from the result")
    data = {c: [row[i] for row in result.rows] for i, c in enumerate(result.columns) if c in schema}
    try:
        return pl.DataFrame(data, schema={c: schema[c] for c in data})
    except Exception as err:
        raise AcquireError("bigquery: a value does not fit its column type") from err


def _source(bq: dict[str, Any], query: str, result: Any) -> dict[str, Any]:
    return {
        "fonte": "basedosdados",
        "url": bq.get("page"),
        "table": bq["table"],
        "query": query,
        "location": result.location,
        "rows": len(result.rows),
        "total_bytes_processed": result.total_bytes_processed,
        "job_id": result.job_id,
    }


def _write_parquet(name: str, frame: pl.DataFrame, tmp_dir: Path) -> tuple[Path, int]:
    out = tmp_dir / f"{name}.parquet"
    frame.write_parquet(out)
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise AcquireError(f"{name}.parquet is {size} bytes, over the 2 GB limit")
    return out, size


def _finish_manifest(
    name: str,
    store: Store,
    root: str,
    today: date,
    out: Path,
    size: int,
    sources: list[dict[str, Any]],
    notes: str,
    code_commit: str,
) -> dict[str, Any]:
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


# --- inep_schools --------------------------------------------------------------


def _schools_notes(frame: pl.DataFrame) -> str:
    per_year = frame.group_by("ano").len().sort("ano")
    lines = [
        f"rows: {frame.height}",
        "rows per year: " + ", ".join(f"{a}={n}" for a, n in per_year.iter_rows()),
    ]
    for col in FACILITIES:
        all_null = (
            frame.group_by("ano")
            .agg(pl.col(col).is_not_null().sum().alias("n"))
            .filter(pl.col("n") == 0)
            .sort("ano")["ano"]
            .to_list()
        )
        lines.append(f"years all null {col}: " + (", ".join(map(str, all_null)) or "none"))
    for col in ("rede", "tipo_localizacao"):
        values = sorted("null" if v is None else str(v) for v in frame[col].unique().to_list())
        lines.append(f"distinct {col}: {', '.join(values)}")
    return "\n".join(lines)


def acquire_schools(
    name: str,
    store: Store,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the `inep_schools` acquire. Uploads the Parquet only when `created`."""
    entry = entry or dataset(name)
    bq = entry["bigquery"]
    root = entry["gcs"]
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
        allowed_columns=["n"],
    )
    if len(summary.rows) != 1:
        raise AcquireError("bigquery: the summary query did not return one row")
    count = summary.rows[0][0]

    old = latest_manifest(store, root)
    if old is not None:
        for s in old.get("sources", []):
            if (
                s.get("fonte") == "basedosdados"
                and s.get("query") == query
                and s.get("rows") == count
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

    result = run_query(
        session,
        bq["endpoint"],
        project,
        query,
        bq["location"],
        max_bytes,
        allowed_columns=bq["columns"],
    )
    frame = _frame_from(result, SCHOOLS_SCHEMA)
    frame = frame.select(list(SCHOOLS_SCHEMA)).sort(bq["order_by"], nulls_last=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out, size = _write_parquet(name, frame, tmp_dir)
    return _finish_manifest(
        name,
        store,
        root,
        today,
        out,
        size,
        [_source(bq, query, result)],
        _schools_notes(frame),
        code_commit,
    )


# --- TLS for INEP --------------------------------------------------------------


def fetch_certificate(microdata: dict[str, Any], opener: Opener) -> bytes:
    """Download the intermediate certificate and check its SHA-256 against the catalog."""
    expected = str(microdata["extra_ca_sha256"]).lower()
    try:
        with opener(microdata["extra_ca_url"]) as response:
            der = response.read(MAX_CERT_BYTES + 1)
    except Exception as err:
        raise AcquireError(
            f"the intermediate certificate could not be downloaded ({type(err).__name__})"
        ) from err
    if not der or len(der) > MAX_CERT_BYTES:
        raise AcquireError("the intermediate certificate download has an unusable size")
    if hashlib.sha256(der).hexdigest() != expected:
        raise AcquireError("the intermediate certificate does not match extra_ca_sha256")
    return der


def certificate_context(microdata: dict[str, Any], opener: Opener) -> ssl.SSLContext:
    """A verifying context: the system trust store plus the checked certificate.

    Raises before any request to INEP when the download or the fingerprint fails.
    `VERIFY_X509_PARTIAL_CHAIN` is never set.
    """
    der = fetch_certificate(microdata, opener)
    context = ssl.create_default_context()
    # Python 3.13 turns this flag on by default; the chain must end at a trusted root.
    context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    try:
        context.load_verify_locations(cadata=der)
    except ssl.SSLError as err:
        raise AcquireError("the intermediate certificate could not be loaded") from err
    return context


# --- inep_school_catalogue -----------------------------------------------------


def _download(opener: Opener, url: str, context: ssl.SSLContext, dest: Path) -> int:
    try:
        with opener(url, context=context) as response, open(dest, "wb") as out:
            for chunk in iter(lambda: response.read(CHUNK), b""):
                out.write(chunk)
    except Exception as err:
        raise AcquireError(f"the microdata download failed ({type(err).__name__})") from err
    return dest.stat().st_size


def _member_to_utf8(zip_path: Path, pattern: str, encoding: str, dest: Path) -> None:
    """Check the zip, then stream its one matching member to `dest` as UTF-8."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if zf.testzip() is not None:
                raise AcquireError("the microdata zip has a corrupt member")
            members = [n for n in zf.namelist() if fnmatch.fnmatch(n, pattern)]
            if len(members) != 1:
                raise AcquireError("the microdata zip does not hold exactly one matching member")
            decoder = codecs.getincrementaldecoder(encoding)()
            with zf.open(members[0]) as raw, open(dest, "w", encoding="utf-8", newline="") as out:
                for chunk in iter(lambda: raw.read(CHUNK), b""):
                    out.write(decoder.decode(chunk))
                out.write(decoder.decode(b"", final=True))
    except zipfile.BadZipFile as err:
        raise AcquireError("the microdata download is not a valid zip") from err
    except UnicodeError as err:
        raise AcquireError(
            "the microdata member does not decode with the catalog encoding"
        ) from err


def _read_microdata(csv_path: Path, microdata: dict[str, Any]) -> pl.DataFrame:
    wanted = list(microdata["columns"])
    if any(c in FORBIDDEN_MICRODATA or "EMAIL" in c for c in wanted):
        raise AcquireError("the catalog lists a contact column of the microdata")
    lazy = pl.scan_csv(csv_path, separator=microdata["delimiter"], infer_schema=False)
    header = lazy.collect_schema().names()
    if any(c not in header for c in wanted):
        raise AcquireError("a listed microdata column is missing from the file header")
    return lazy.select(wanted).collect()


def _text(col: str) -> pl.Expr:
    """A text column, trimmed, with empty text as null."""
    trimmed = pl.col(col).str.strip_chars()
    return pl.when(trimmed == "").then(None).otherwise(trimmed)


def _catalogue_frame(micro: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Type the microdata columns. Returns the frame and the count of unusable CEPs."""
    try:
        frame = micro.select(
            pl.col("NU_ANO_CENSO").str.strip_chars().cast(pl.Int64).alias("ano"),
            *[_text(src).alias(dst) for dst, src in CATALOGUE_SOURCE.items() if dst != "ano"],
        )
    except Exception as err:
        raise AcquireError("the survey year does not fit its column type") from err
    if frame["id_escola"].null_count() or frame["id_escola"].n_unique() != frame.height:
        raise AcquireError("CO_ENTIDADE is not a unique key")
    ok = frame["id_municipio"].str.contains(r"^\d{7}$")
    if not ok.all():
        raise AcquireError("CO_MUNICIPIO has a value that is not 7 digits")
    valid_cep = pl.col("cep").str.contains(r"^\d{1,8}$")
    bad_ceps = frame.filter(pl.col("cep").is_not_null() & ~valid_cep).height
    frame = frame.with_columns(
        pl.when(valid_cep).then(pl.col("cep").str.zfill(8)).otherwise(None).alias("cep")
    )
    return frame, bad_ceps


def _coordinates(
    entry: dict[str, Any], session_factory: Callable[[], Any], project: str | None
) -> tuple[pl.DataFrame, dict[str, Any]]:
    bq = entry["bigquery"]
    if not project:
        raise AcquireError("GOOGLE_CLOUD_PROJECT is not set")
    query = build_query(bq)
    result = run_query(
        session_factory(),
        bq["endpoint"],
        project,
        query,
        bq["location"],
        int(bq["maximum_bytes_billed"]),
        allowed_columns=bq["columns"],
    )
    schema = {
        "id_escola": pl.Utf8,
        "id_municipio": pl.Utf8,
        "sigla_uf": pl.Utf8,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
    }
    frame = _frame_from(result, schema).select(["id_escola", "latitude", "longitude"])
    if frame["id_escola"].null_count() or frame["id_escola"].n_unique() != frame.height:
        raise AcquireError("bigquery: id_escola is not a unique key in the coordinates table")
    return frame, _source(bq, query, result)


def _join_coordinates(frame: pl.DataFrame, coords: pl.DataFrame) -> tuple[pl.DataFrame, int, int]:
    """Left-join coordinates. Returns the frame, microdata rows with no coordinate row,
    and coordinate rows with no microdata row."""
    only_coords = coords.join(frame.select("id_escola"), on="id_escola", how="anti").height
    marked = coords.with_columns(pl.lit(True).alias("_found"))
    joined = frame.join(marked, on="id_escola", how="left")
    no_row = joined.filter(pl.col("_found").is_null()).height
    lat, lon = pl.col("latitude"), pl.col("longitude")
    usable = (
        lat.is_not_null()
        & lon.is_not_null()
        & (lat != 0)
        & (lon != 0)
        & lat.is_between(*LAT_RANGE)
        & lon.is_between(*LON_RANGE)
    )
    joined = joined.with_columns(
        pl.when(usable).then(lat).otherwise(None).alias("latitude"),
        pl.when(usable).then(lon).otherwise(None).alias("longitude"),
    ).drop("_found")
    return joined, no_row, only_coords


def _catalogue_notes(
    frame: pl.DataFrame,
    bad_ceps: int,
    no_coord_row: int,
    no_microdata_row: int,
    microdata: dict[str, Any],
) -> str:
    n = frame.height
    per_state = frame.group_by("sigla_uf").len().sort("sigla_uf")
    share_cep = frame["cep"].is_not_null().sum() / n if n else 0.0
    share_coord = frame["latitude"].is_not_null().sum() / n if n else 0.0
    lines = [
        f"rows: {n}",
        "rows per state: " + ", ".join(f"{s}={c}" for s, c in per_state.iter_rows()),
        f"share with a cep: {share_cep:.4f}",
        f"share with coordinates: {share_coord:.4f}",
        f"cep values not 1-8 digits (set to null): {bad_ceps}",
        f"microdata rows with no coordinate row: {no_coord_row}",
        f"coordinate rows with no microdata row: {no_microdata_row}",
        f"intermediate certificate: {microdata['extra_ca_url']}",
        f"intermediate certificate sha256: {microdata['extra_ca_sha256']}",
    ]
    return "\n".join(lines)


def acquire_catalogue(
    name: str,
    store: Store,
    opener: Opener,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the `inep_school_catalogue` acquire. Nothing is uploaded until every check passed."""
    entry = entry or dataset(name)
    micro = entry["microdata"]
    tmp_dir.mkdir(parents=True, exist_ok=True)

    context = certificate_context(micro, opener)  # before any request to INEP
    zip_path = tmp_dir / "microdata.zip"
    csv_path = tmp_dir / "microdata.csv"
    zip_bytes = _download(opener, micro["url"], context, zip_path)
    zip_sha = _sha256(zip_path)
    _member_to_utf8(zip_path, micro["member"], micro["encoding"], csv_path)
    zip_path.unlink()
    frame, bad_ceps = _catalogue_frame(_read_microdata(csv_path, micro))
    csv_path.unlink()

    coords, bq_source = _coordinates(entry, session_factory, project)
    frame, no_coord_row, no_microdata_row = _join_coordinates(frame, coords)
    frame = frame.select(list(CATALOGUE_SCHEMA)).cast(CATALOGUE_SCHEMA).sort("id_escola")

    out, size = _write_parquet(name, frame, tmp_dir)
    sources = [
        {
            "fonte": "inep",
            "url": micro["url"],
            "bytes": zip_bytes,
            "sha256": zip_sha,
            "extra_ca_url": micro["extra_ca_url"],
            "extra_ca_sha256": micro["extra_ca_sha256"],
        },
        bq_source,
    ]
    notes = _catalogue_notes(frame, bad_ceps, no_coord_row, no_microdata_row, micro)
    return _finish_manifest(
        name, store, entry["gcs"], today, out, size, sources, notes, code_commit
    )


# --- entry points --------------------------------------------------------------


def execute(
    name: str,
    store: Store,
    opener: Opener,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    manifest_out: Path,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one acquire, then write the manifest last (a created one goes to the store too)."""
    if name == "inep_schools":
        manifest = acquire_schools(
            name, store, session_factory, project, today, tmp_dir, code_commit, entry
        )
    elif name == "inep_school_catalogue":
        manifest = acquire_catalogue(
            name, store, opener, session_factory, project, today, tmp_dir, code_commit, entry
        )
    else:
        raise AcquireError(f"{name} is not an INEP dataset")
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
                _urlopen,
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
