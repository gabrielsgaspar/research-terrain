"""A minimal BigQuery REST client, for acquire scripts that read Base dos Dados.

The endpoint, scope, table and columns come from a catalog entry's `bigquery:`
block. The query is built from that block only. Personal identifiers are
never selected: the builder refuses names that start with `cpf_cnpj` or
`nome`, and `geometria` and `telefone`, even if the catalog lists them. The
one exception is `ALLOWED_BY_TABLE`, fixed here and not in the catalog: the
exact column `nome` of INEP's school catalogue, which is a school's name.

The HTTP session is passed in (anything with `post` and `get` like a
`requests` session), so tests use a fake. Nothing here logs or raises with a
header, a token or a data value.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

from terrain.acquire import AcquireError

IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
TABLE = re.compile(r"[a-z0-9_-]+\.[a-z0-9_]+\.[a-z0-9_]+")
STATE = re.compile(r"[A-Z]{2}")
FILTER_VALUE = re.compile(r"[A-Za-z0-9_]{1,20}")
PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]*")
FORBIDDEN_PREFIXES = ("cpf_cnpj", "nome")
FORBIDDEN_NAMES = ("geometria", "telefone")
# Columns a table may select although FORBIDDEN_PREFIXES refuses them, because
# there they name no person. Only exact names; `telefone` is never allowed.
# basedosdados.br_bd_diretorios_brasil.escola is INEP's Catálogo de Escolas:
# its `nome` is the name of a school, a public building (inep_school_catalogue).
ALLOWED_BY_TABLE: dict[str, frozenset[str]] = {
    "basedosdados.br_bd_diretorios_brasil.escola": frozenset({"nome"}),
}

PAGE_SIZE = 50_000
TIMEOUT_MS = 60_000
REQUEST_TIMEOUT = 180  # seconds, per HTTP call
MAX_POLLS = 600
POLL_SECONDS = 2.0


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    total_bytes_processed: int
    job_id: str
    location: str


def _identifier(name: object, allowed: frozenset[str] = frozenset()) -> str:
    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
        raise AcquireError("bigquery: a column name is not a plain identifier")
    if name in FORBIDDEN_NAMES:
        raise AcquireError("bigquery: a column that may hold a personal identifier is refused")
    if name.startswith(FORBIDDEN_PREFIXES) and name not in allowed:
        raise AcquireError("bigquery: a column that may hold a personal identifier is refused")
    return name


def _where(bq: dict[str, Any]) -> str:
    states = bq["states"]
    for state in states:
        if not isinstance(state, str) or not STATE.fullmatch(state):
            raise AcquireError("bigquery: a state is not a two-letter code")
    listed = ", ".join(f"'{s}'" for s in states)
    years = bq.get("years")
    if years is None:
        return f"WHERE sigla_uf IN ({listed})"
    if (
        len(years) != 2
        or not all(isinstance(y, int) and not isinstance(y, bool) for y in years)
        or years[0] > years[1]
    ):
        raise AcquireError("bigquery: years must be two integers, first not after second")
    return f"WHERE sigla_uf IN ({listed}) AND ano BETWEEN {years[0]} AND {years[1]}"


def _table(bq: dict[str, Any]) -> str:
    table = bq["table"]
    if not isinstance(table, str) or not TABLE.fullmatch(table):
        raise AcquireError("bigquery: the table id is malformed")
    return f"`{table}`"


def _filter_value(value: object) -> str:
    if not isinstance(value, str) or not FILTER_VALUE.fullmatch(value):
        raise AcquireError("bigquery: a filter value is not 1-20 letters, digits or underscores")
    return value


def _filters(bq: dict[str, Any]) -> str:
    """Extra `AND ...` clauses for the block's optional `filters`; empty when it has none."""
    filters = bq.get("filters")
    if filters is None:
        return ""
    if not isinstance(filters, list):
        raise AcquireError("bigquery: filters must be a list")
    allowed = ALLOWED_BY_TABLE.get(str(bq.get("table")), frozenset())
    clauses: list[str] = []
    for item in filters:
        if not isinstance(item, dict):
            raise AcquireError("bigquery: a filter must be a mapping")
        column = _identifier(item.get("column"), allowed)
        if "prefix_between" in item and "in" not in item:
            bounds = item["prefix_between"]
            length = item.get("length")
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise AcquireError("bigquery: prefix_between needs exactly two values")
            if not isinstance(length, int) or isinstance(length, bool) or length < 1:
                raise AcquireError("bigquery: a prefix filter needs a positive integer length")
            low, high = (_filter_value(v) for v in bounds)
            clauses.append(f"SUBSTR({column}, 1, {length}) BETWEEN '{low}' AND '{high}'")
        elif "in" in item and "prefix_between" not in item:
            values = item["in"]
            if not isinstance(values, list) or not values:
                raise AcquireError("bigquery: an in filter needs a non-empty list")
            listed = ", ".join(f"'{_filter_value(v)}'" for v in values)
            clauses.append(f"{column} IN ({listed})")
        else:
            raise AcquireError("bigquery: a filter needs exactly one of prefix_between and in")
    return "".join(f" AND {c}" for c in clauses)


def _where_all(bq: dict[str, Any]) -> str:
    return _where(bq) + _filters(bq)


def _aggregate(bq: dict[str, Any], aggregate: Any, order: bool) -> str:
    """The grouped count query for the block's `aggregate`, with or without ORDER BY."""
    if not isinstance(aggregate, dict):
        raise AcquireError("bigquery: aggregate must be a mapping")
    allowed = ALLOWED_BY_TABLE.get(str(bq.get("table")), frozenset())
    group_by = [_identifier(c, allowed) for c in aggregate.get("group_by") or []]
    if not group_by:
        raise AcquireError("bigquery: aggregate lists no group_by column")
    count = _identifier(aggregate.get("count"))
    sums = [_identifier(c, allowed) for c in aggregate.get("sums") or []]
    groups = ", ".join(group_by)
    parts = [*group_by, f"COUNT(*) AS {count}"]
    parts += [f"SUM(CAST({s} AS FLOAT64)) AS sum_{s}" for s in sums]
    text = f"SELECT {', '.join(parts)} FROM {_table(bq)} {_where_all(bq)} GROUP BY {groups}"
    return f"{text} ORDER BY {groups}" if order else text


def aggregate_columns(bq: dict[str, Any]) -> list[str]:
    """The columns an `aggregate` query returns, in order; checked like the query."""
    aggregate = bq["aggregate"]
    _aggregate(bq, aggregate, order=True)
    return [
        *aggregate["group_by"],
        aggregate["count"],
        *(f"sum_{s}" for s in aggregate.get("sums") or []),
    ]


def build_query(bq: dict[str, Any]) -> str:
    """The SELECT for the catalog's `bigquery:` block; raises on a refused name."""
    if bq.get("aggregate") is not None:
        return _aggregate(bq, bq["aggregate"], order=True)
    allowed = ALLOWED_BY_TABLE.get(str(bq.get("table")), frozenset())
    columns = [_identifier(c, allowed) for c in bq["columns"]]
    order_by = [_identifier(c, allowed) for c in bq["order_by"]]
    if not columns:
        raise AcquireError("bigquery: no columns listed")
    return (
        f"SELECT {', '.join(columns)} FROM {_table(bq)} {_where_all(bq)} "
        f"ORDER BY {', '.join(order_by)}"
    )


def build_summary_query(bq: dict[str, Any]) -> str:
    """Row count over the same rows as `build_query`.

    When the block names a `freshness_column`, the latest value of it comes too.
    With `aggregate`, it counts the aggregated rows.
    """
    if bq.get("aggregate") is not None:
        return f"SELECT COUNT(*) AS n FROM ({_aggregate(bq, bq['aggregate'], order=False)})"
    freshness = bq.get("freshness_column")
    if freshness is None:
        return f"SELECT COUNT(*) AS n FROM {_table(bq)} {_where_all(bq)}"
    column = _identifier(freshness)
    return f"SELECT MAX({column}) AS max_{column}, COUNT(*) AS n FROM {_table(bq)} {_where_all(bq)}"


_TYPES: dict[str, Callable[[str], Any]] = {
    "INT64": int,
    "INTEGER": int,
    "FLOAT64": float,
    "FLOAT": float,
    "DATE": date.fromisoformat,
    "STRING": str,
}


def _payload(response: Any) -> dict[str, Any]:
    if response.status_code != 200:
        raise AcquireError(f"bigquery: HTTP status {response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise AcquireError("bigquery: the response is not a JSON object")
    if "errors" in body:
        raise AcquireError("bigquery: the response reports errors")
    return body


def _type_rows(fields: list[dict[str, Any]], raw_rows: Iterable[dict[str, Any]]) -> list[list[Any]]:
    converters: list[Callable[[str], Any]] = []
    for field in fields:
        kind = field.get("type")
        if kind not in _TYPES:
            raise AcquireError("bigquery: a column has a type this client does not read")
        converters.append(_TYPES[kind])
    rows: list[list[Any]] = []
    for raw in raw_rows:
        cells = raw["f"]
        if len(cells) != len(converters):
            raise AcquireError("bigquery: a row does not match the schema")
        rows.append(
            [
                None if c["v"] is None else conv(c["v"])
                for c, conv in zip(cells, converters, strict=True)
            ]
        )
    return rows


def run_query(
    session: Any,
    endpoint: str,
    project: str,
    query: str,
    location: str,
    max_bytes: int,
    *,
    allowed_columns: Iterable[str] | None = None,
    page_size: int = PAGE_SIZE,
    sleep: Callable[[float], None] = time.sleep,
) -> QueryResult:
    """Run `query` and return every row, typed. Raises `AcquireError` on any problem.

    Posts `jobs.query`, polls `getQueryResults` while the job is not complete,
    then pages with `pageToken` using the location the job reports. Fails when
    the status is not 200, the response has `errors`, a column is not in
    `allowed_columns`, or the rows received differ from `totalRows`.
    """
    if not PROJECT.fullmatch(project):
        raise AcquireError("bigquery: the billing project id is malformed")
    base = f"{endpoint}projects/{quote(project, safe='')}/queries"
    body = {
        "query": query,
        "useLegacySql": False,
        "location": location,
        "maximumBytesBilled": str(max_bytes),
        "maxResults": page_size,
        "timeoutMs": TIMEOUT_MS,
    }
    response = _payload(session.post(base, json=body, timeout=REQUEST_TIMEOUT))
    job = response.get("jobReference") or {}
    job_id = job.get("jobId")
    job_location = job.get("location") or location

    polls = 0
    while not response.get("jobComplete"):
        if not job_id:
            raise AcquireError("bigquery: the job is not complete and has no id")
        polls += 1
        if polls > MAX_POLLS:
            raise AcquireError("bigquery: the job did not complete in time")
        sleep(POLL_SECONDS)
        response = _payload(
            session.get(
                f"{base}/{quote(job_id, safe='')}",
                params={"location": job_location, "maxResults": page_size, "timeoutMs": TIMEOUT_MS},
                timeout=REQUEST_TIMEOUT,
            )
        )
        job_location = (response.get("jobReference") or {}).get("location") or job_location

    fields = (response.get("schema") or {}).get("fields")
    if not fields:
        raise AcquireError("bigquery: the response has no schema")
    columns = [f["name"] for f in fields]
    if allowed_columns is not None:
        allowed = set(allowed_columns)
        if any(c not in allowed for c in columns):
            raise AcquireError("bigquery: the response has a column not in the catalog list")
    try:
        total_rows = int(response["totalRows"])
        total_bytes = int(response.get("totalBytesProcessed") or 0)
    except (KeyError, ValueError) as err:
        raise AcquireError("bigquery: the response has no usable totalRows") from err

    rows = _type_rows(fields, response.get("rows") or [])
    token = response.get("pageToken")
    while token:
        if not job_id:
            raise AcquireError("bigquery: a next page was offered but the job has no id")
        page = _payload(
            session.get(
                f"{base}/{quote(job_id, safe='')}",
                params={
                    "location": job_location,
                    "maxResults": page_size,
                    "timeoutMs": TIMEOUT_MS,
                    "pageToken": token,
                },
                timeout=REQUEST_TIMEOUT,
            )
        )
        rows.extend(_type_rows(fields, page.get("rows") or []))
        token = page.get("pageToken")

    if len(rows) != total_rows:
        raise AcquireError(f"bigquery: received {len(rows)} rows, totalRows says {total_rows}")
    return QueryResult(columns, rows, total_bytes, job_id or "", job_location)


def default_session(scope: str) -> Any:
    """An authorised `requests` session from Application Default Credentials.

    Never called in tests: they pass a fake session.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=[scope])
    return AuthorizedSession(credentials)
