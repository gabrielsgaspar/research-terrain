import io
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest
from terrain.sources.tse import AcquireError, Headers, acquire, source_urls
from terrain.storage import MemoryStore

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "tse"
CAND = dataset("tse_candidates")
COMP = dataset("tse_candidates_complementar")
URLS = source_urls(CAND, COMP)
ROOT = CAND["gcs"]


def make_zip(url: str, *, member: str | None = None, corrupt: bool = False) -> bytes:
    name = url.rsplit("/", 1)[-1].removesuffix(".zip")
    sample = (FIXTURES / f"{name}_sample.csv").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(member or f"{name}_BRASIL.csv", sample)
    data = bytearray(buf.getvalue())
    if corrupt:
        start = data.index(sample[:20])  # stored: member bytes appear verbatim
        for i in range(start, start + 10):
            data[i] ^= 0xFF
    return bytes(data)


class FakeFetcher:
    """Serves zips from memory. Never touches the network."""

    def __init__(self) -> None:
        self.bodies = {u: make_zip(u) for u in URLS}
        self.etags = {u: f'"etag-{i}"' for i, u in enumerate(URLS)}
        self.get_etags: dict[str, str] = {}
        self.declared: dict[str, int] = {}

    def _head(self, url: str) -> Headers:
        n = self.declared.get(url, len(self.bodies[url]))
        return Headers("Mon, 01 Jan 2024 00:00:00 GMT", self.etags[url], n)

    def head(self, url: str) -> Headers:
        return self._head(url)

    @contextmanager
    def get(self, url: str):
        h = self._head(url)
        if url in self.get_etags:
            h = Headers(h.last_modified, self.get_etags[url], h.content_length)
        yield h, io.BytesIO(self.bodies[url])


def run(store, fetcher, tmp_path, today=date(2025, 3, 1)):
    return acquire(
        store,
        fetcher,
        candidates=CAND,
        complementar=COMP,
        today=today,
        tmp_dir=tmp_path / "dl",
        code_commit="abc123",
    )


def test_urls_come_from_the_catalog():
    assert len(URLS) == 9
    assert all(u.startswith("https://") and "<year>" not in u for u in URLS)
    assert sum("complementar" in u for u in URLS) == 2


def test_first_run_creates_nine_zips(tmp_path):
    store = MemoryStore()
    m = run(store, FakeFetcher(), tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01/"
    assert validate_manifest(m, stage="acquire", dataset="tse_candidates") == []
    assert len(m["files"]) == 9
    assert len(m["sources"]) == 9
    objects = store.list(ROOT)
    assert len([p for p in objects if p.endswith(".zip")]) == 9
    assert all(p.startswith(m["gcs_prefix"]) for p in objects)


def test_second_run_is_unchanged(tmp_path):
    store = MemoryStore()
    first = run(store, FakeFetcher(), tmp_path)
    from terrain.manifest import write_manifest

    write_manifest(first, store, tmp_path / "m.json")
    before = store.list(ROOT)
    assert len([p for p in before if p.endswith(MANIFEST_NAME)]) == 1
    second = run(store, FakeFetcher(), tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert second["files"] == first["files"]
    assert store.list(ROOT) == before


def test_changed_etag_creates_suffixed_folder(tmp_path):
    from terrain.manifest import write_manifest

    store = MemoryStore()
    write_manifest(run(store, FakeFetcher(), tmp_path), store, tmp_path / "m.json")
    changed = FakeFetcher()
    changed.etags[URLS[3]] = '"new"'
    m = run(store, changed, tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01-2/"
    assert len(store.list(m["gcs_prefix"])) == 9


def test_changed_etag_on_a_later_day_uses_plain_date(tmp_path):
    from terrain.manifest import write_manifest

    store = MemoryStore()
    write_manifest(run(store, FakeFetcher(), tmp_path), store, tmp_path / "m.json")
    changed = FakeFetcher()
    changed.etags[URLS[0]] = '"new"'
    m = run(store, changed, tmp_path, today=date(2025, 3, 2))
    assert m["gcs_prefix"] == f"{ROOT}2025-03-02/"


def _short(f):
    f.declared[URLS[2]] = len(f.bodies[URLS[2]]) + 5


def _no_brasil(f):
    f.bodies[URLS[1]] = make_zip(URLS[1], member="other.csv")


def _corrupt(f):
    f.bodies[URLS[4]] = make_zip(URLS[4], corrupt=True)


def _etag_mismatch(f):
    f.get_etags[URLS[5]] = '"different"'


@pytest.mark.parametrize("break_it", [_short, _no_brasil, _corrupt, _etag_mismatch])
def test_failures_raise_and_leave_store_unchanged(tmp_path, break_it):
    store = MemoryStore()
    fetcher = FakeFetcher()
    break_it(fetcher)
    with pytest.raises(AcquireError):
        run(store, fetcher, tmp_path)
    assert store.list("") == []
