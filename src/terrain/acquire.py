"""Generic acquirer: download what a catalog entry's `acquire:` block lists.

URLs and the raw folder come from `data/catalog.yaml`. The HTTP layer is a
`Fetcher` passed in by the caller, so tests can fake it. Every file is
downloaded and checked before anything is uploaded; the manifest is written
last by `run_script`.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import gzip
import hashlib
import json
import os
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import UTC, date, datetime
from http.client import IncompleteRead
from itertools import product
from pathlib import Path
from typing import Any, NamedTuple

from terrain.catalog import dataset
from terrain.http import Fetcher, Headers, HTTPStatusError, UrllibFetcher
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

CHUNK = 1 << 20
MAX_FAILURES = 8  # stalls or bad resumes tolerated per file


class AcquireError(RuntimeError):
    """A download failed a check; nothing was uploaded."""


class WantedFile(NamedTuple):
    url: str
    check: dict[str, Any]
    name: str  # stored file name
    meta: str | None  # URL of a JSON record that gives the version, if any


def expand_urls(entry: dict[str, Any]) -> list[WantedFile]:
    """Every file the entry's `acquire.files` expands to, in catalog order."""
    out: list[WantedFile] = []
    for item in entry["acquire"]["files"]:
        years = [str(y) for y in item.get("years", [])] or [None]
        ufs = [str(u) for u in item.get("ufs", [])] or [None]
        for year, uf in product(years, ufs):
            url = item["url"]
            meta = item.get("meta")
            if year is not None:
                url = url.replace("<year>", year)
                meta = meta.replace("<year>", year) if meta else meta
            if uf is not None:
                url = url.replace("<uf>", uf)
                meta = meta.replace("<uf>", uf) if meta else meta
            name = item.get("name") or url.rsplit("/", 1)[-1]
            out.append(WantedFile(url, item["check"], name, meta))
    names = [f.name for f in out]
    if len(names) != len(set(names)):
        raise AcquireError(f"{entry['name']}: two URLs share a file name")
    return out


def _check_zip(path: Path, member: str | None) -> None:
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise AcquireError(f"{path.name}: corrupt member {bad}")
        if member is not None and not any(fnmatch.fnmatch(n, member) for n in zf.namelist()):
            raise AcquireError(f"{path.name}: no member matching {member}")


def _check_csv(path: Path, columns: list[str], forbid_columns: list[str], min_rows: int) -> None:
    """Header has every `columns` name and no `forbid_columns` name; enough rows.

    Messages name the file, the catalog's column names and counts only, never a
    cell of the file (an HTML page's first line must not be echoed).
    """
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                raise AcquireError(f"{path.name}: empty file")
            names = set(header)
            missing = [c for c in columns if c not in names]
            if missing:
                raise AcquireError(f"{path.name}: missing columns {missing}")
            forbidden = [c for c in forbid_columns if c in names]
            if forbidden:
                raise AcquireError(f"{path.name}: forbidden columns {forbidden}")
            rows = sum(1 for row in reader if any(cell.strip() for cell in row))
    except UnicodeDecodeError:
        raise AcquireError(f"{path.name}: not valid UTF-8") from None
    except csv.Error:
        raise AcquireError(f"{path.name}: not readable as CSV") from None
    if rows < min_rows:
        raise AcquireError(f"{path.name}: {rows} data rows, expected at least {min_rows}")


def check_file(path: Path, check: dict[str, Any]) -> None:
    """Raise `AcquireError` unless `path` passes its catalog check."""
    kind = check["type"]
    try:
        if kind == "csv":
            _check_csv(
                path,
                list(check["columns"]),
                list(check.get("forbid_columns", [])),
                int(check.get("min_rows", 1)),
            )
        elif kind == "zip":
            _check_zip(path, check.get("member"))
        elif kind == "ods":
            _check_zip(path, "content.xml")
        elif kind == "gzip":
            with gzip.open(path, "rb") as f:
                while f.read(CHUNK):
                    pass
        else:
            raise AcquireError(f"{path.name}: unknown check type {kind}")
    except zipfile.BadZipFile as err:
        raise AcquireError(f"{path.name}: not a valid zip") from err
    except (gzip.BadGzipFile, EOFError, OSError) as err:
        raise AcquireError(f"{path.name}: not a complete gzip stream") from err


def _source(url: str, h: Headers) -> dict[str, Any]:
    return {
        "url": url,
        "last_modified": h.last_modified,
        "etag": h.etag,
        "bytes": h.content_length,
    }


def _unchanged(old: dict[str, Any], current: list[dict[str, Any]]) -> bool:
    old_by_url = {s.get("url"): s for s in old.get("sources", [])}
    if set(old_by_url) != {s["url"] for s in current}:
        return False
    keys = ("last_modified", "etag", "bytes")
    return all(all(old_by_url[s["url"]].get(k) == s[k] for k in keys) for s in current)


class _Short(Exception):
    """The stream ended before the expected number of bytes."""


@contextmanager
def _open(fetcher: Fetcher, url: str, offset: int):
    if offset == 0:
        with fetcher.get(url) as (got, stream):
            yield 200, "", got, stream
    else:
        with fetcher.get_from(url, offset) as response:
            yield response


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(
    fetcher: Fetcher, url: str, head: Headers | None, dest: Path, expected: int | None
) -> str:
    """Stream `url` to `dest`; return its SHA-256, taken from the finished file.

    With a `head`, the GET headers must equal it; without one (the version came
    from a record) they are not compared. A stall or short read resumes from the
    bytes already written with a Range request; a resume not answered by the
    right 206 restarts from the start. Each stall or restart is a failure, and
    after MAX_FAILURES the file raises.
    """
    dest.unlink(missing_ok=True)
    failures = 0

    def fail(why: str) -> None:
        nonlocal failures
        failures += 1
        if failures > MAX_FAILURES:
            raise AcquireError(f"{url}: download failed {failures} times ({why})")

    while True:
        offset = dest.stat().st_size if dest.exists() else 0
        try:
            with _open(fetcher, url, offset) as (status, content_range, got, stream):
                if offset and not (status == 206 and content_range.startswith(f"bytes {offset}-")):
                    fail(f"resume from {offset} answered {status}")
                    offset = 0
                    dest.unlink()
                    if status != 200:
                        continue
                if offset == 0 and head is not None and got != head:
                    raise AcquireError(f"{url}: headers changed between HEAD and GET")
                with open(dest, "ab") as out:
                    for chunk in iter(lambda: stream.read(CHUNK), b""):
                        out.write(chunk)
                if expected is not None and dest.stat().st_size < expected:
                    raise _Short
            break
        except HTTPStatusError as err:
            fail(f"HTTP {err.status} {err.reason}".rstrip())
        except (OSError, IncompleteRead, _Short) as err:
            fail(type(err).__name__)
    return _sha256(dest)


def _free_prefix(store: Store, root: str, today: date) -> str:
    base = f"{root}{today.isoformat()}"
    n = 1
    while True:
        prefix = f"{base}/" if n == 1 else f"{base}-{n}/"
        if not store.list(prefix):
            return prefix
        n += 1


def acquire(
    store: Store,
    fetcher: Fetcher,
    entry: dict[str, Any],
    today: date,
    tmp_dir: Path,
    code_commit: str,
) -> dict[str, Any]:
    """Run one acquire. Returns the manifest; uploads only when status is `created`.

    The caller writes `_MANIFEST.json` (see `run_script`), so that it is always
    the last object created.
    """
    root = entry["gcs"]
    name = entry["name"]
    files_wanted = expand_urls(entry)

    heads: dict[str, Headers] = {}
    expected_size: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    for f in files_wanted:
        if f.meta is not None:
            record = fetcher.json(f.meta)
            size = record.get("size") if isinstance(record, dict) else None
            if not isinstance(size, int) or isinstance(size, bool):
                raise AcquireError(f"{f.meta}: record has no integer size")
            if record.get("modified") in (None, ""):
                raise AcquireError(f"{f.meta}: record has no modified")
            expected_size[f.url] = size
            sources.append(
                {
                    "url": f.url,
                    "last_modified": str(record["modified"]),
                    "etag": "",
                    "bytes": size,
                }
            )
        else:
            heads[f.url] = fetcher.head(f.url)
            length = heads[f.url].content_length
            if length is None:
                raise AcquireError(f"{f.url}: no Content-Length")
            expected_size[f.url] = length
            sources.append(_source(f.url, heads[f.url]))

    old = latest_manifest(store, root)
    if old is not None and _unchanged(old, sources):
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

    tmp_dir.mkdir(parents=True, exist_ok=True)
    local: list[tuple[str, Path, str, int]] = []
    for f in files_wanted:
        dest = tmp_dir / f.name
        expected = expected_size[f.url]
        digest = _download(fetcher, f.url, heads.get(f.url), dest, expected)
        size = dest.stat().st_size
        if size != expected:
            raise AcquireError(f"{f.name}: got {size} bytes, expected {expected}")
        check_file(dest, f.check)
        local.append((f.name, dest, digest, expected))

    prefix = _free_prefix(store, root, today)
    files: list[dict[str, Any]] = []
    for fname, dest, digest, size in local:
        store.create(prefix + fname, dest)
        files.append({"path": prefix + fname, "sha256": digest, "bytes": size})
    return build_manifest(
        dataset=name,
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=files,
        sources=sources,
        code_commit=code_commit,
    )


def run_script(name: str) -> None:
    """Entry point for `pipeline/acquire/<name>.py`. Contract: pipeline/README.md."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = acquire(
                store,
                UrllibFetcher(),
                dataset(name),
                datetime.now(UTC).date(),
                Path(tmp),
                os.environ.get("CODE_COMMIT", ""),
            )
            if manifest["status"] == "created":
                write_manifest(manifest, store, args.manifest_out)
            else:
                args.manifest_out.write_text(
                    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
                )
    except (AcquireError, HTTPStatusError) as err:
        raise SystemExit(f"acquire failed: {err}") from err
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))
