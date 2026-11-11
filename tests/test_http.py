"""The urllib layer, with `urlopen` replaced: these tests never touch the network."""

import email.message
import io
import urllib.error
import urllib.request

import pytest

from terrain import http
from terrain.http import USER_AGENT, HTTPStatusError, UrllibFetcher

URL = "https://example.test/data.xlsx"


class _Response(io.BytesIO):
    def __init__(self, body: bytes = b"{}") -> None:
        super().__init__(body)
        self.status = 200
        self.headers = email.message.Message()
        self.headers["Content-Length"] = str(len(body))


@pytest.fixture
def sent(monkeypatch):
    """Record every request `urlopen` is given; answer each with `{}`."""
    requests: list[urllib.request.Request] = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requests


def _refuse(monkeypatch, status: int, reason: str) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, status, reason, email.message.Message(), io.BytesIO()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _call_all(fetcher: UrllibFetcher) -> None:
    fetcher.head(URL)
    with fetcher.get(URL) as (_, stream):
        stream.read()
    fetcher.json(URL)
    fetcher.read(URL, 100)
    with fetcher.get_from(URL, 10) as (_, _, _, stream):
        stream.read()


def test_every_request_sends_the_user_agent(sent):
    _call_all(UrllibFetcher())
    assert [r.get_method() for r in sent] == ["HEAD", "GET", "GET", "GET", "GET"]
    for request in sent:
        assert request.get_header("User-agent") == USER_AGENT


def test_existing_headers_are_kept(sent):
    _call_all(UrllibFetcher())
    for request in sent:
        assert request.get_header("Accept-encoding") == "identity"
    assert sent[-1].get_header("Range") == "bytes=10-"


def test_user_agent_names_the_project_without_a_url_scheme():
    assert USER_AGENT.startswith("research-terrain ")
    assert "://" not in USER_AGENT  # test_acquire forbids URLs in code


@pytest.mark.parametrize(
    "call, method",
    [
        (lambda f: f.head(URL), "HEAD"),
        (lambda f: f.json(URL), "GET"),
        (lambda f: f.read(URL, 100), "GET"),
        (lambda f: f.get(URL).__enter__(), "GET"),
        (lambda f: f.get_from(URL, 5).__enter__(), "GET"),
    ],
)
def test_http_error_names_method_url_and_status(monkeypatch, call, method):
    _refuse(monkeypatch, 403, "Forbidden")
    with pytest.raises(HTTPStatusError) as caught:
        call(UrllibFetcher())
    err = caught.value
    assert (err.method, err.url, err.status, err.reason) == (method, URL, 403, "Forbidden")
    assert str(err) == f"{method} {URL}: HTTP 403 Forbidden"


def test_http_error_is_still_an_os_error(monkeypatch):
    # acquire's download loop retries on OSError, as it did for urllib's HTTPError
    _refuse(monkeypatch, 503, "Service Unavailable")
    with pytest.raises(OSError):
        UrllibFetcher().head(URL)


def test_timeout_is_unchanged(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(timeout)
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    UrllibFetcher().head(URL)
    assert seen == [http.TIMEOUT]


def test_read_returns_at_most_limit_bytes(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Response(b"x" * 50))
    assert UrllibFetcher().read(URL, 10) == b"x" * 10
    assert UrllibFetcher().read(URL, 100) == b"x" * 50
