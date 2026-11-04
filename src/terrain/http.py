"""The HTTP layer shared by every acquire script. Tests pass a fake `Fetcher` instead."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

TIMEOUT = 120


@dataclass(frozen=True)
class Headers:
    last_modified: str
    etag: str
    content_length: int | None


class Fetcher(Protocol):
    def head(self, url: str) -> Headers: ...

    def get(self, url: str) -> AbstractContextManager[tuple[Headers, BinaryIO]]: ...

    def json(self, url: str) -> Any:
        """GET `url` and return the parsed JSON body."""
        ...

    def get_from(
        self, url: str, offset: int
    ) -> AbstractContextManager[tuple[int, str, Headers, BinaryIO]]:
        """GET with `Range: bytes=<offset>-`; yields (status, Content-Range, headers, stream)."""
        ...


def _headers(resp: urllib.response.addinfourl) -> Headers:
    length = resp.headers.get("Content-Length")
    return Headers(
        last_modified=resp.headers.get("Last-Modified", ""),
        etag=resp.headers.get("ETag", ""),
        content_length=int(length) if length is not None else None,
    )


def _request(url: str, method: str, **extra: str) -> urllib.request.Request:
    # identity: a compressed body would make Content-Length meaningless
    headers = {"Accept-Encoding": "identity", **extra}
    return urllib.request.Request(url, method=method, headers=headers)


class UrllibFetcher:
    def head(self, url: str) -> Headers:
        with urllib.request.urlopen(_request(url, "HEAD"), timeout=TIMEOUT) as resp:
            return _headers(resp)

    @contextmanager
    def get(self, url: str) -> Iterator[tuple[Headers, BinaryIO]]:
        with urllib.request.urlopen(_request(url, "GET"), timeout=TIMEOUT) as resp:
            yield _headers(resp), resp

    def json(self, url: str) -> Any:
        with urllib.request.urlopen(_request(url, "GET"), timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @contextmanager
    def get_from(self, url: str, offset: int) -> Iterator[tuple[int, str, Headers, BinaryIO]]:
        request = _request(url, "GET", Range=f"bytes={offset}-")
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            yield resp.status, resp.headers.get("Content-Range", ""), _headers(resp), resp
