"""The HTTP layer shared by every acquire script. Tests pass a fake `Fetcher` instead."""

from __future__ import annotations

import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import BinaryIO, Protocol

TIMEOUT = 120


@dataclass(frozen=True)
class Headers:
    last_modified: str
    etag: str
    content_length: int | None


class Fetcher(Protocol):
    def head(self, url: str) -> Headers: ...

    def get(self, url: str) -> AbstractContextManager[tuple[Headers, BinaryIO]]: ...


def _headers(resp: urllib.response.addinfourl) -> Headers:
    length = resp.headers.get("Content-Length")
    return Headers(
        last_modified=resp.headers.get("Last-Modified", ""),
        etag=resp.headers.get("ETag", ""),
        content_length=int(length) if length is not None else None,
    )


def _request(url: str, method: str) -> urllib.request.Request:
    # identity: a compressed body would make Content-Length meaningless
    return urllib.request.Request(url, method=method, headers={"Accept-Encoding": "identity"})


class UrllibFetcher:
    def head(self, url: str) -> Headers:
        with urllib.request.urlopen(_request(url, "HEAD"), timeout=TIMEOUT) as resp:
            return _headers(resp)

    @contextmanager
    def get(self, url: str) -> Iterator[tuple[Headers, BinaryIO]]:
        with urllib.request.urlopen(_request(url, "GET"), timeout=TIMEOUT) as resp:
            yield _headers(resp), resp
