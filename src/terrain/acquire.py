"""Generic acquirer: download what a catalog entry's `acquire:` block lists.

URLs and the raw folder come from `data/catalog.yaml`. The HTTP layer is a
`Fetcher` passed in by the caller, so tests can fake it. Every file is
downloaded and checked before anything is uploaded; the manifest is written
last by `run_script`.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import tempfile
import zipfile
from datetime import UTC, date, datetime
from itertools import product
from pathlib import Path
from typing import Any

from terrain.catalog import dataset
from terrain.http import Fetcher, Headers, UrllibFetcher
from terrain.manifest import build_manifest, latest_manifest, write_manifest
from terrain.storage import GCSStore, Store

CHUNK = 1 << 20


class AcquireError(RuntimeError):
    """A download failed a check; nothing was uploaded."""


def expand_urls(entry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every (url, check) the entry's `acquire.files` expands to, in catalog order."""
    out: list[tuple[str, dict[str, Any]]] = []
    for item in entry["acquire"]["files"]:
        years = [str(y) for y in item.get("years", [])] or [None]
        ufs = [str(u) for u in item.get("ufs", [])] or [None]
        for year, uf in product(years, ufs):
            url = item["url"]
            if year is not None:
                url = url.replace("<year>", year)
            if uf is not None:
                url = url.replace("<uf>", uf)
            out.append((url, item["check"]))
    names = [u.rsplit("/", 1)[-1] for u, _ in out]
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


def check_file(path: Path, check: dict[str, Any]) -> None:
    """Raise `AcquireError` unless `path` passes its catalog check."""
    kind = check["type"]
    try:
        if kind == "zip":
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


def _download(fetcher: Fetcher, url: str, head: Headers, dest: Path) -> str:
    """Stream `url` to `dest`; return its SHA-256 after checking it against HEAD."""
    with fetcher.get(url) as (got, stream):
        if got != head:
            raise AcquireError(f"{url}: headers changed between HEAD and GET")
        h = hashlib.sha256()
        with open(dest, "wb") as out:
            for chunk in iter(lambda: stream.read(CHUNK), b""):
                out.write(chunk)
                h.update(chunk)
    return h.hexdigest()


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
    for url, _ in files_wanted:
        heads[url] = fetcher.head(url)
        if heads[url].content_length is None:
            raise AcquireError(f"{url}: no Content-Length")
    sources = [_source(u, heads[u]) for u, _ in files_wanted]

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
    for url, check in files_wanted:
        fname = url.rsplit("/", 1)[-1]
        dest = tmp_dir / fname
        digest = _download(fetcher, url, heads[url], dest)
        expected = heads[url].content_length
        assert expected is not None
        size = dest.stat().st_size
        if size != expected:
            raise AcquireError(f"{fname}: got {size} bytes, expected {expected}")
        check_file(dest, check)
        local.append((fname, dest, digest, expected))

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
    except AcquireError as err:
        raise SystemExit(f"acquire failed: {err}") from err
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))
