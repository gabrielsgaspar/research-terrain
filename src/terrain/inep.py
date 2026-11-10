"""Acquire INEP school facilities and the school catalogue (idea 0006, campaign 0006 s6).

Shared by `pipeline/acquire/inep_schools.py` and `inep_school_catalogue.py`.
Contracts: `data/contracts/inep_schools.md` and `inep_school_catalogue.md`.
Every table and column list comes from the catalog entry.

Both read Base dos Dados on BigQuery, as `terrain.ibama` does:

- `inep_schools`: INEP's Censo Escolar school table, facilities by year;
- `inep_school_catalogue`: INEP's Catálogo de Escolas as copied by Base dos
  Dados (`basedosdados.br_bd_diretorios_brasil.escola`). Its address is one
  text field; the postcode, street number and neighbourhood are parsed from it.

The catalogue was first read from INEP's Censo Escolar microdata at
download.inep.gov.br, but INEP resets every connection from GitHub's servers
(campaign 0006 s8, runs 42861990498 and 42900676058), so it is read from
BigQuery instead.

Phone numbers, emails and personal names are never selected. The one name
selected is `nome` of the catalogue table, which is a school's name (see
`terrain.bigquery.ALLOWED_BY_TABLE`). Nothing here logs a row value or a header.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from terrain.acquire import AcquireError, _free_prefix, _sha256
from terrain.bigquery import build_query, build_summary_query, default_session, run_query
from terrain.catalog import dataset
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

MAX_BYTES = 2 * 1024**3

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

# The Base dos Dados columns the catalogue needs (all STRING in BigQuery).
CATALOGUE_COLUMNS = [
    "id_escola",
    "id_municipio",
    "sigla_uf",
    "nome",
    "endereco",
    "latitude",
    "longitude",
    "dependencia_administrativa",
    "localizacao",
    "situacao_catalogo",
]
CATALOGUE_SCHEMA: dict[str, Any] = {
    "ano": pl.Int64,
    "id_escola": pl.Utf8,
    "nome_escola": pl.Utf8,
    "id_municipio": pl.Utf8,
    "sigla_uf": pl.Utf8,
    "rede": pl.Utf8,
    "tipo_localizacao": pl.Utf8,
    "endereco": pl.Utf8,
    "numero": pl.Utf8,
    "complemento": pl.Utf8,
    "bairro": pl.Utf8,
    "cep": pl.Utf8,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
}
# INEP's codes (TP_DEPENDENCIA, TP_LOCALIZACAO) for the catalogue's labels; a
# value that is already a code is kept.
REDE_CODES = {"FEDERAL": "1", "ESTADUAL": "2", "MUNICIPAL": "3", "PRIVADA": "4"}
LOCALIZACAO_CODES = {"URBANA": "1", "RURAL": "2"}
MAX_UNKNOWN_SHARE = 0.01  # above this share of unknown labels in a column, the run stops
LAT_RANGE = (-34.0, 6.0)
LON_RANGE = (-74.0, -28.0)

CEP = re.compile(r"(?<!\d)(\d{5})-?(\d{3})(?!\d)")
NUMBER = re.compile(r"(S/N|SN|\d+[A-Z]?)(?=$|[\s.,;-])[\s.,;-]*(.*)$", re.IGNORECASE)
CITY_TAIL = re.compile(r"\.\s+[^.,]+\s-\s[A-Z]{2}\.?$")


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


def _count(session: Any, bq: dict[str, Any], project: str, summary_query: str) -> Any:
    summary = run_query(
        session,
        bq["endpoint"],
        project,
        summary_query,
        bq["location"],
        int(bq["maximum_bytes_billed"]),
        allowed_columns=["n"],
    )
    if len(summary.rows) != 1:
        raise AcquireError("bigquery: the summary query did not return one row")
    return summary.rows[0][0]


def _unchanged(
    store: Store, root: str, name: str, query: str, count: Any, code_commit: str
) -> dict[str, Any] | None:
    """The `unchanged` manifest when the latest one has the same query and row count."""
    old = latest_manifest(store, root)
    if old is None:
        return None
    for s in old.get("sources", []):
        if s.get("fonte") == "basedosdados" and s.get("query") == query and s.get("rows") == count:
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
    session = session_factory()
    count = _count(session, bq, project, build_summary_query(bq))
    old = _unchanged(store, root, name, query, count, code_commit)
    if old is not None:
        return old

    result = run_query(
        session,
        bq["endpoint"],
        project,
        query,
        bq["location"],
        int(bq["maximum_bytes_billed"]),
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


# --- inep_school_catalogue -----------------------------------------------------


def parse_endereco(text: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """`(street, number, neighbourhood, cep)` from the catalogue's one address field.

    The postcode is the last run of 8 digits, with or without the dash
    (`76801-000` or `76801000`); the text after it (the city) is dropped. Of
    what is before it, `<street>, <number> <neighbourhood>` gives all three
    parts; anything else is kept whole as the street, with no number and no
    neighbourhood. A part that cannot be found is None.
    """
    if text is None:
        return None, None, None, None
    s = " ".join(text.split())
    if not s:
        return None, None, None, None
    cep = None
    matches = list(CEP.finditer(s))
    if matches:
        last = matches[-1]
        cep = last.group(1) + last.group(2)
        head = s[: last.start()]
    else:
        head = CITY_TAIL.sub("", s)
    head = head.strip(" .,;-")
    street, number, bairro = head or None, None, None
    if "," in head:
        before, after = head.split(",", 1)
        m = NUMBER.match(after.strip())
        if m and before.strip():
            street = before.strip()
            number = m.group(1).upper()
            bairro = m.group(2).strip(" .,;-") or None
    return street, number, bairro, cep


def _label(value: str | None) -> str | None:
    """Upper case without accents, trimmed; None when empty."""
    if value is None or not value.strip():
        return None
    plain = unicodedata.normalize("NFKD", value.strip())
    return "".join(c for c in plain if not unicodedata.combining(c)).upper()


def _codes(values: list[str | None], codes: dict[str, str], column: str) -> tuple[list, dict]:
    """INEP codes for the labels of `column`. Unknown labels become None and are counted."""
    known = {**codes, **{v: v for v in codes.values()}}
    out: list[str | None] = []
    unknown: dict[str, int] = {}
    for v in values:
        label = _label(v)
        if label is None:
            out.append(None)
        elif label in known:
            out.append(known[label])
        else:
            out.append(None)
            unknown[label[:40]] = unknown.get(label[:40], 0) + 1
    if values and sum(unknown.values()) / len(values) > MAX_UNKNOWN_SHARE:
        listed = ", ".join(f"{k}={n}" for k, n in sorted(unknown.items())[:10])
        raise AcquireError(
            f"{column}: {sum(unknown.values())} of {len(values)} values are not a known "
            f"label ({listed})"
        )
    return out, unknown


def _number(col: str) -> pl.Expr:
    """A coordinate text as Float64 (a decimal comma is read as a point); None if not one."""
    return pl.col(col).str.replace(",", ".", literal=True).cast(pl.Float64, strict=False)


def _text_frame(result: Any, columns: list[str]) -> pl.DataFrame:
    """The result as text columns, trimmed, empty text as null."""
    missing = [c for c in columns if c not in result.columns]
    if missing:
        raise AcquireError("bigquery: a column of the contract is missing from the result")
    index = {c: i for i, c in enumerate(result.columns)}
    data = {
        c: [None if row[index[c]] is None else str(row[index[c]]) for row in result.rows]
        for c in columns
    }
    frame = pl.DataFrame(data, schema={c: pl.Utf8 for c in columns})
    trimmed = {c: pl.col(c).str.strip_chars() for c in columns}
    return frame.select(
        [pl.when(t == "").then(None).otherwise(t).alias(c) for c, t in trimmed.items()]
    )


def catalogue_frame(raw: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, Any]]:
    """The contract's columns from the Base dos Dados rows, and counts for the notes."""
    if raw["id_escola"].null_count() or raw["id_escola"].n_unique() != raw.height:
        raise AcquireError("id_escola is not a unique key")
    if not raw["id_municipio"].str.contains(r"^\d{7}$").fill_null(False).all():
        raise AcquireError("id_municipio has a value that is not 7 digits")

    parts = [parse_endereco(v) for v in raw["endereco"].to_list()]
    rede, rede_unknown = _codes(
        raw["dependencia_administrativa"].to_list(), REDE_CODES, "dependencia_administrativa"
    )
    loc, loc_unknown = _codes(raw["localizacao"].to_list(), LOCALIZACAO_CODES, "localizacao")

    lat, lon = _number("latitude"), _number("longitude")
    typed = raw.with_columns(lat.alias("lat_n"), lon.alias("lon_n"))
    not_numbers = typed.filter(
        (pl.col("latitude").is_not_null() & pl.col("lat_n").is_null())
        | (pl.col("longitude").is_not_null() & pl.col("lon_n").is_null())
    ).height
    la, lo = pl.col("lat_n"), pl.col("lon_n")
    both = la.is_not_null() & lo.is_not_null()
    usable = both & (la != 0) & (lo != 0) & la.is_between(*LAT_RANGE) & lo.is_between(*LON_RANGE)
    outside = typed.filter(both & ~usable).height

    frame = typed.select(
        pl.lit(None, dtype=pl.Int64).alias("ano"),
        pl.col("id_escola"),
        pl.col("nome").alias("nome_escola"),
        pl.col("id_municipio"),
        pl.col("sigla_uf"),
        pl.Series("rede", rede, dtype=pl.Utf8),
        pl.Series("tipo_localizacao", loc, dtype=pl.Utf8),
        pl.Series("endereco", [p[0] for p in parts], dtype=pl.Utf8),
        pl.Series("numero", [p[1] for p in parts], dtype=pl.Utf8),
        pl.lit(None, dtype=pl.Utf8).alias("complemento"),
        pl.Series("bairro", [p[2] for p in parts], dtype=pl.Utf8),
        pl.Series("cep", [p[3] for p in parts], dtype=pl.Utf8),
        pl.when(usable).then(la).otherwise(None).alias("latitude"),
        pl.when(usable).then(lo).otherwise(None).alias("longitude"),
    )
    frame = frame.select(list(CATALOGUE_SCHEMA)).cast(CATALOGUE_SCHEMA).sort("id_escola")
    situacao = raw.group_by("situacao_catalogo").len().sort("situacao_catalogo", nulls_last=True)
    stats = {
        "with_endereco": raw["endereco"].is_not_null().sum(),
        "rede_unknown": rede_unknown,
        "loc_unknown": loc_unknown,
        "not_numbers": not_numbers,
        "outside": outside,
        "situacao": [("null" if s is None else s[:40], n) for s, n in situacao.iter_rows()],
    }
    return frame, stats


def _catalogue_notes(frame: pl.DataFrame, stats: dict[str, Any]) -> str:
    n = frame.height

    def share(col: str) -> str:
        return f"{frame[col].is_not_null().sum() / n:.4f}" if n else "0.0000"

    def unknown(counts: dict[str, int]) -> str:
        return ", ".join(f"{k}={c}" for k, c in sorted(counts.items())) or "none"

    per_state = frame.group_by("sigla_uf").len().sort("sigla_uf")
    lines = [
        f"rows: {n}",
        "rows per state: " + ", ".join(f"{s}={c}" for s, c in per_state.iter_rows()),
        f"rows with an endereco: {stats['with_endereco']}",
        f"share with a cep parsed from endereco: {share('cep')}",
        f"share with a street number parsed from endereco: {share('numero')}",
        f"share with a neighbourhood parsed from endereco: {share('bairro')}",
        f"share with coordinates: {share('latitude')}",
        f"coordinates that are not numbers (set to null): {stats['not_numbers']}",
        f"coordinates at 0 or outside Brazil (set to null): {stats['outside']}",
        f"dependencia_administrativa labels not known (rede null): "
        f"{unknown(stats['rede_unknown'])}",
        f"localizacao labels not known (tipo_localizacao null): {unknown(stats['loc_unknown'])}",
        "rows per situacao_catalogo: " + ", ".join(f"{s}={c}" for s, c in stats["situacao"]),
        "ano is null: the catalogue has no census year",
    ]
    return "\n".join(lines)


def acquire_catalogue(
    name: str,
    store: Store,
    session_factory: Callable[[], Any],
    project: str | None,
    today: date,
    tmp_dir: Path,
    code_commit: str,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the `inep_school_catalogue` acquire. Uploads the Parquet only when `created`."""
    entry = entry or dataset(name)
    bq = entry["bigquery"]
    root = entry["gcs"]
    if list(bq["columns"]) != CATALOGUE_COLUMNS:
        raise AcquireError("the catalog's columns for the school catalogue are not the expected")
    if not project:
        raise AcquireError("GOOGLE_CLOUD_PROJECT is not set")
    query = build_query(bq)
    session = session_factory()
    count = _count(session, bq, project, build_summary_query(bq))
    old = _unchanged(store, root, name, query, count, code_commit)
    if old is not None:
        return old

    result = run_query(
        session,
        bq["endpoint"],
        project,
        query,
        bq["location"],
        int(bq["maximum_bytes_billed"]),
        allowed_columns=bq["columns"],
    )
    frame, stats = catalogue_frame(_text_frame(result, CATALOGUE_COLUMNS))
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
        _catalogue_notes(frame, stats),
        code_commit,
    )


# --- entry points --------------------------------------------------------------


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
    if name == "inep_schools":
        acquire = acquire_schools
    elif name == "inep_school_catalogue":
        acquire = acquire_catalogue
    else:
        raise AcquireError(f"{name} is not an INEP dataset")
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
