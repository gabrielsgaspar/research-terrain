"""Acquire the TSE candidate files (2000-2024) into one dated raw folder.

URLs come from `data/catalog.yaml`. The HTTP layer is a `Fetcher` passed in by
the caller, so tests can fake it. Every file is downloaded and checked before
anything is uploaded; the manifest is written last by the calling script.
"""

from __future__ import annotations

import fnmatch
import hashlib
import zipfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from terrain.manifest import build_manifest, latest_manifest
from terrain.storage import Store

DATASET = "tse_candidates"
YEARS = tuple(range(2000, 2025, 4))
COMPLEMENTAR_YEARS = (2020, 2024)
CHUNK = 1 << 20


class AcquireError(RuntimeError):
    """A download failed a check; nothing was uploaded."""


@dataclass(frozen=True)
class Headers:
    last_modified: str
    etag: str
    content_length: int | None


class Fetcher(Protocol):
    def head(self, url: str) -> Headers: ...

    def get(self, url: str) -> AbstractContextManager[tuple[Headers, BinaryIO]]: ...


def source_urls(candidates: dict[str, Any], complementar: dict[str, Any]) -> list[str]:
    """The nine source URLs, built from the two catalog entries."""
    urls = [candidates["source"].replace("<year>", str(y)) for y in YEARS]
    urls += [complementar["source"].replace("<year>", str(y)) for y in COMPLEMENTAR_YEARS]
    return urls


def verify_zip(path: Path, expected_bytes: int) -> None:
    """Raise `AcquireError` unless `path` is a sound zip with a `*_BRASIL.csv`."""
    size = path.stat().st_size
    if size != expected_bytes:
        raise AcquireError(f"{path.name}: got {size} bytes, expected {expected_bytes}")
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise AcquireError(f"{path.name}: corrupt member {bad}")
            if not any(fnmatch.fnmatch(n, "*_BRASIL.csv") for n in zf.namelist()):
                raise AcquireError(f"{path.name}: no *_BRASIL.csv member")
    except zipfile.BadZipFile as err:
        raise AcquireError(f"{path.name}: not a valid zip") from err


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
    *,
    candidates: dict[str, Any],
    complementar: dict[str, Any],
    today: date,
    tmp_dir: Path,
    code_commit: str,
) -> dict[str, Any]:
    """Run one acquire. Returns the manifest; uploads only when status is `created`.

    The caller writes `_MANIFEST.json` (see `pipeline/acquire/tse_candidates.py`),
    so that it is always the last object created.
    """
    root = candidates["gcs"]
    if complementar["gcs"] != root:
        raise AcquireError("catalog entries disagree on the raw folder")
    urls = source_urls(candidates, complementar)

    heads: dict[str, Headers] = {}
    for url in urls:
        heads[url] = fetcher.head(url)
        if heads[url].content_length is None:
            raise AcquireError(f"{url}: no Content-Length")
    sources = [_source(u, heads[u]) for u in urls]

    old = latest_manifest(store, root)
    if old is not None and _unchanged(old, sources):
        return build_manifest(
            dataset=DATASET,
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
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        dest = tmp_dir / name
        digest = _download(fetcher, url, heads[url], dest)
        expected = heads[url].content_length
        assert expected is not None
        verify_zip(dest, expected)
        local.append((name, dest, digest, expected))

    prefix = _free_prefix(store, root, today)
    files: list[dict[str, Any]] = []
    for name, dest, digest, size in local:
        store.create(prefix + name, dest)
        files.append({"path": prefix + name, "sha256": digest, "bytes": size})
    return build_manifest(
        dataset=DATASET,
        stage="acquire",
        status="created",
        gcs_prefix=prefix,
        files=files,
        sources=sources,
        code_commit=code_commit,
    )
