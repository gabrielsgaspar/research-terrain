"""The HTTP layer shared by every acquire script. Tests pass a fake `Fetcher` instead."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

TIMEOUT = 120
# Some servers (the World Bank's, behind Cloudflare) refuse urllib's default agent with 403.
USER_AGENT = "research-terrain (+github.com/gabrielsgaspar/research-terrain)"


class HTTPStatusError(OSError):
    """A request was answered with an HTTP error status.

    An `OSError`, as urllib's own `HTTPError` is, so callers that retry on
    `OSError` (the download loop in `terrain.acquire`) still do.
    """

    def __init__(self, method: str, url: str, status: int, reason: str) -> None:
        super().__init__(f"{method} {url}: HTTP {status} {reason}".rstrip())
        self.method = method
        self.url = url
        self.status = status
        self.reason = reason


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

    def read(self, url: str, limit: int) -> bytes:
        """GET `url` and return at most `limit` bytes of its body (a record, never a data file)."""
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
    headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT, **extra}
    return urllib.request.Request(url, method=method, headers=headers)


def _urlopen(request: urllib.request.Request) -> urllib.response.addinfourl:
    """Open `request`; an HTTP error status raises `HTTPStatusError` naming method and URL."""
    try:
        return urllib.request.urlopen(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        err.close()
        method, url = request.get_method(), request.full_url
        raise HTTPStatusError(method, url, err.code, str(err.reason or "")) from None


class UrllibFetcher:
    def head(self, url: str) -> Headers:
        with _urlopen(_request(url, "HEAD")) as resp:
            return _headers(resp)

    @contextmanager
    def get(self, url: str) -> Iterator[tuple[Headers, BinaryIO]]:
        with _urlopen(_request(url, "GET")) as resp:
            yield _headers(resp), resp

    def json(self, url: str) -> Any:
        with _urlopen(_request(url, "GET")) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def read(self, url: str, limit: int) -> bytes:
        with _urlopen(_request(url, "GET")) as resp:
            return resp.read(limit)

    @contextmanager
    def get_from(self, url: str, offset: int) -> Iterator[tuple[int, str, Headers, BinaryIO]]:
        with _urlopen(_request(url, "GET", Range=f"bytes={offset}-")) as resp:
            yield resp.status, resp.headers.get("Content-Range", ""), _headers(resp), resp
