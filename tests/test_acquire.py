import gzip
import hashlib
import io
import json
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from terrain.acquire import AcquireError, acquire, check_file, expand_urls
from terrain.catalog import dataset, load_catalog
from terrain.http import Headers
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "fixtures"
CONTENT_XML = (FIXTURES / "ibge" / "Municipios_da_Amazonia_Legal_2024.content.xml").read_bytes()
CSV = (FIXTURES / "hidalgo" / "geocoded_polling_stations_sample.csv").read_bytes()
STAMP = (2024, 1, 1, 0, 0, 0)
ROOT = "data/raw/test/"

ENTRY = {
    "name": "test_ds",
    "gcs": ROOT,
    "acquire": {
        "files": [
            {
                "url": "https://example.test/a_<year>_<uf>.zip",
                "years": [2020, 2024],
                "ufs": ["PA", "AC"],
                "check": {"type": "zip", "member": "*.csv"},
            },
            {"url": "https://example.test/b.ods", "check": {"type": "ods"}},
            {"url": "https://example.test/c.csv.gz", "check": {"type": "gzip"}},
        ]
    },
}


def make_zip(members: dict[str, bytes], *, corrupt: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=STAMP), data)
    data = bytearray(buf.getvalue())
    if corrupt:
        start = data.index(CSV[:20])  # stored: member bytes appear verbatim
        for i in range(start, start + 10):
            data[i] ^= 0xFF
    return bytes(data)


def good_body(url: str) -> bytes:
    if url.endswith(".ods"):
        return make_zip({"content.xml": CONTENT_XML})
    if url.endswith(".gz"):
        return gzip.compress(CSV, mtime=0)
    return make_zip({"x.csv": CSV})


URLS = [f.url for f in expand_urls(ENTRY)]


class _Stalling(io.BytesIO):
    """Serves its bytes, then times out instead of ending."""

    def read(self, size=-1):
        data = super().read(size)
        if not data:
            raise TimeoutError("stalled")
        return data


class FakeFetcher:
    """Serves bodies from memory. Never touches the network."""

    def __init__(self, urls=URLS) -> None:
        self.bodies = {u: good_body(u) for u in urls}
        self.etags = {u: f'"etag-{i}"' for i, u in enumerate(urls)}
        self.get_etags: dict[str, str] = {}
        self.declared: dict[str, int] = {}
        self.no_length: set[str] = set()
        self.records: dict[str, object] = {}
        self.stalls: dict[str, int] = {}  # downloads still to stall, per URL
        self.resume_status = 206
        self.requests: list[tuple[str, int]] = []  # (url, offset) of every GET

    def _head(self, url: str) -> Headers:
        n = None if url in self.no_length else self.declared.get(url, len(self.bodies[url]))
        return Headers("Mon, 01 Jan 2024 00:00:00 GMT", self.etags[url], n)

    def _serve(self, url: str, offset: int) -> io.BytesIO:
        self.requests.append((url, offset))
        body = self.bodies[url][offset:]
        if self.stalls.get(url, 0) > 0:
            self.stalls[url] -= 1
            return _Stalling(body[: max(1, len(body) // 2)])
        return io.BytesIO(body)

    def head(self, url: str) -> Headers:
        return self._head(url)

    @contextmanager
    def get(self, url: str):
        h = self._head(url)
        if url in self.get_etags:
            h = Headers(h.last_modified, self.get_etags[url], h.content_length)
        yield h, self._serve(url, 0)

    def json(self, url: str):
        return self.records[url]

    @contextmanager
    def get_from(self, url: str, offset: int):
        total = len(self.bodies[url])
        if self.resume_status == 206:
            yield (
                206,
                f"bytes {offset}-{total - 1}/{total}",
                self._head(url),
                self._serve(url, offset),
            )
        else:
            stream = self._serve(url, 0)
            self.requests[-1] = (url, offset)  # log the offset that was asked for
            yield self.resume_status, "", self._head(url), stream


def run(store, fetcher, tmp_path, today=date(2025, 3, 1), entry=ENTRY):
    return acquire(store, fetcher, entry, today, tmp_path / "dl", "abc123")


# --- URL expansion -----------------------------------------------------------


def test_expansion_of_the_synthetic_entry():
    assert len(URLS) == 6
    assert "https://example.test/a_2020_PA.zip" in URLS
    assert all("<" not in u for u in URLS)


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("tse_candidates", 9),
        ("ibge_municipalities", 2),
        ("polling_stations_geocoded", 3),
        ("tse_results", 28),
        ("tse_votes_by_section", 182),
        ("tse_polling_places", 4),
        ("cnfp_public_forests", 6),
        ("ibge_grid_2022", 1),
        ("ibge_grid_2010", 38),
        ("naturalearth_basemap", 4),
        ("ibge_boundaries_2024", 3),
    ],
)
def test_real_catalog_url_counts(name, count):
    assert len(expand_urls(dataset(name))) == count


def test_ibge_grid_2010_stored_names():
    tiles = [
        *range(33, 37),
        *range(42, 47),
        *range(50, 57),
        *range(60, 67),
        *range(70, 77),
        *range(80, 86),
        92,
        93,
    ]
    expected = [f"grade_id{n}.zip" for n in tiles]
    files = expand_urls(dataset("ibge_grid_2010"))
    assert len(expected) == 38
    assert [f.name for f in files] == expected
    assert all(f.meta is None for f in files)


def test_cnfp_files_have_stored_names_and_records():
    files = expand_urls(dataset("cnfp_public_forests"))
    assert [f.name for f in files] == [
        "CNFP_2008.zip",
        "CNFP_2012.zip",
        "CNFP_2016.zip",
        "CNFP_2020.zip",
        "CNFP_2024_retificado.zip",
        "CNFP_2025.zip",
    ]
    assert all(f.meta for f in files)


def test_duplicate_file_names_raise():
    entry = {
        "name": "dup",
        "gcs": ROOT,
        "acquire": {
            "files": [
                {"url": "https://x.test/one/f.zip", "check": {"type": "zip"}},
                {"url": "https://x.test/two/f.zip", "check": {"type": "zip"}},
            ]
        },
    }
    with pytest.raises(AcquireError):
        expand_urls(entry)


# --- the real tse_candidates manifest ----------------------------------------


def test_real_tse_candidates_manifest_gives_unchanged(tmp_path):
    entry = dataset("tse_candidates")
    manifest = json.loads(
        (REPO / "data" / "manifests" / "acquire" / "tse_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    store = MemoryStore()
    store.create(manifest["gcs_prefix"] + MANIFEST_NAME, json.dumps(manifest).encode())
    before = store.list("")

    by_url = {s["url"]: s for s in manifest["sources"]}
    fetcher = FakeFetcher(urls=[])
    fetcher.bodies = {}  # a download would raise KeyError
    fetcher._head = lambda url: Headers(  # type: ignore[method-assign]
        by_url[url]["last_modified"], by_url[url]["etag"], by_url[url]["bytes"]
    )
    m = run(store, fetcher, tmp_path, entry=entry)
    assert m["status"] == "unchanged"
    assert m["gcs_prefix"] == manifest["gcs_prefix"]
    assert store.list("") == before


# --- checks ------------------------------------------------------------------


def _write(tmp_path, data: bytes) -> Path:
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    return p


def test_zip_check_passes(tmp_path):
    check_file(
        _write(tmp_path, make_zip({"x_BRASIL.csv": CSV})), {"type": "zip", "member": "*_BRASIL.csv"}
    )
    check_file(_write(tmp_path, make_zip({"x.csv": CSV})), {"type": "zip"})


def test_zip_check_fails_on_missing_member(tmp_path):
    with pytest.raises(AcquireError):
        check_file(
            _write(tmp_path, make_zip({"other.csv": CSV})),
            {"type": "zip", "member": "*_BRASIL.csv"},
        )


def test_zip_check_fails_on_corrupt_member(tmp_path):
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, make_zip({"x.csv": CSV}, corrupt=True)), {"type": "zip"})


def test_zip_check_fails_on_non_zip(tmp_path):
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, b"not a zip"), {"type": "zip"})


def test_ods_check_passes(tmp_path):
    check_file(_write(tmp_path, make_zip({"content.xml": CONTENT_XML})), {"type": "ods"})


def test_ods_check_fails_when_not_an_ods(tmp_path):
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, make_zip({"x.csv": CSV})), {"type": "ods"})
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, b"plain text"), {"type": "ods"})


def test_gzip_check_passes(tmp_path):
    check_file(_write(tmp_path, gzip.compress(CSV, mtime=0)), {"type": "gzip"})


def test_gzip_check_fails_when_truncated(tmp_path):
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, gzip.compress(CSV, mtime=0)[:-20]), {"type": "gzip"})


def test_gzip_check_fails_on_non_gzip(tmp_path):
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, b"plain text"), {"type": "gzip"})


# --- acquire -----------------------------------------------------------------


def test_first_run_creates_all_files(tmp_path):
    store = MemoryStore()
    m = run(store, FakeFetcher(), tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01/"
    assert validate_manifest(m, stage="acquire", dataset="test_ds") == []
    assert len(m["files"]) == 6
    assert len(m["sources"]) == 6
    assert all(p.startswith(m["gcs_prefix"]) for p in store.list(""))
    assert len(store.list(ROOT)) == 6


def test_second_run_is_unchanged(tmp_path):
    store = MemoryStore()
    first = run(store, FakeFetcher(), tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = store.list(ROOT)
    second = run(store, FakeFetcher(), tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert second["files"] == first["files"]
    assert store.list(ROOT) == before


def test_changed_etag_creates_suffixed_folder(tmp_path):
    store = MemoryStore()
    write_manifest(run(store, FakeFetcher(), tmp_path), store, tmp_path / "m.json")
    changed = FakeFetcher()
    changed.etags[URLS[3]] = '"new"'
    m = run(store, changed, tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01-2/"
    assert len(store.list(m["gcs_prefix"])) == 6


def test_changed_etag_on_a_later_day_uses_plain_date(tmp_path):
    store = MemoryStore()
    write_manifest(run(store, FakeFetcher(), tmp_path), store, tmp_path / "m.json")
    changed = FakeFetcher()
    changed.etags[URLS[0]] = '"new"'
    m = run(store, changed, tmp_path, today=date(2025, 3, 2))
    assert m["gcs_prefix"] == f"{ROOT}2025-03-02/"


def _short(f):
    f.declared[URLS[2]] = len(f.bodies[URLS[2]]) + 5


def _no_member(f):
    f.bodies[URLS[1]] = make_zip({"other.txt": CSV})


def _corrupt(f):
    f.bodies[URLS[4]] = make_zip({"x.csv": CSV}, corrupt=True)


def _not_ods(f):
    f.bodies[URLS[4]] = make_zip({"x.csv": CSV})


def _bad_gzip(f):
    url = URLS[5]
    f.bodies[url] = f.bodies[url][:-20]
    f.declared.pop(url, None)


def _etag_mismatch(f):
    f.get_etags[URLS[5]] = '"different"'


@pytest.mark.parametrize("break_it", [_short, _no_member, _corrupt, _bad_gzip, _etag_mismatch])
def test_failures_raise_and_leave_store_unchanged(tmp_path, break_it):
    store = MemoryStore()
    fetcher = FakeFetcher()
    break_it(fetcher)
    with pytest.raises(AcquireError):
        run(store, fetcher, tmp_path)
    assert store.list("") == []


def test_not_an_ods_leaves_store_unchanged(tmp_path):
    entry = {
        "name": "test_ds",
        "gcs": ROOT,
        "acquire": {"files": [{"url": "https://example.test/b.ods", "check": {"type": "ods"}}]},
    }
    store = MemoryStore()
    fetcher = FakeFetcher(urls=["https://example.test/b.ods"])
    fetcher.bodies["https://example.test/b.ods"] = make_zip({"x.csv": CSV})
    with pytest.raises(AcquireError):
        run(store, fetcher, tmp_path, entry=entry)
    assert store.list("") == []


# --- files versioned by a JSON record, and resumed downloads -----------------

MURL = "https://example.test/items/abc/data"
META = "https://example.test/items/abc?f=json"
MENTRY = {
    "name": "test_ds",
    "gcs": ROOT,
    "acquire": {
        "files": [
            {
                "url": MURL,
                "name": "EDITION.zip",
                "meta": META,
                "check": {"type": "zip", "member": "*.csv"},
            }
        ]
    },
}


def meta_fetcher(size=None, modified=1700000000000) -> FakeFetcher:
    f = FakeFetcher(urls=[MURL])
    f.bodies[MURL] = make_zip({"x.csv": CSV})
    f.no_length.add(MURL)
    f.records[META] = {"size": len(f.bodies[MURL]) if size is None else size, "modified": modified}
    return f


def mrun(store, fetcher, tmp_path, today=date(2025, 3, 1)):
    return run(store, fetcher, tmp_path, today=today, entry=MENTRY)


def test_meta_file_without_content_length_is_accepted(tmp_path):
    store = MemoryStore()
    f = meta_fetcher()
    m = mrun(store, f, tmp_path)
    assert m["status"] == "created"
    assert validate_manifest(m, stage="acquire", dataset="test_ds") == []
    assert m["sources"] == [
        {
            "url": MURL,
            "last_modified": "1700000000000",
            "etag": "",
            "bytes": len(f.bodies[MURL]),
        }
    ]
    assert [x["path"] for x in m["files"]] == [m["gcs_prefix"] + "EDITION.zip"]
    assert store.list(ROOT) == [m["gcs_prefix"] + "EDITION.zip"]


@pytest.mark.parametrize("delta", [3, -3])
def test_size_different_from_the_record_raises(tmp_path, delta):
    store = MemoryStore()
    f = meta_fetcher()
    f.records[META]["size"] += delta
    with pytest.raises(AcquireError):
        mrun(store, f, tmp_path)
    assert store.list("") == []


@pytest.mark.parametrize(
    "record",
    [
        {"modified": 1},
        {"size": "123", "modified": 1},
        {"size": 12.5, "modified": 1},
        {"size": True, "modified": 1},
        {"size": 123},
        ["size", "modified"],
    ],
)
def test_bad_record_raises(tmp_path, record):
    store = MemoryStore()
    f = meta_fetcher()
    f.records[META] = record
    with pytest.raises(AcquireError):
        mrun(store, f, tmp_path)
    assert store.list("") == []
    assert f.requests == []


def test_same_record_is_unchanged_and_new_modified_is_a_new_folder(tmp_path):
    store = MemoryStore()
    first = mrun(store, meta_fetcher(), tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = store.list("")

    again = meta_fetcher()
    second = mrun(store, again, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert again.requests == []
    assert store.list("") == before

    third = mrun(store, meta_fetcher(modified=1800000000000), tmp_path)
    assert third["status"] == "created"
    assert third["gcs_prefix"] == f"{ROOT}2025-03-01-2/"


def test_file_without_meta_and_without_content_length_raises(tmp_path):
    store = MemoryStore()
    f = FakeFetcher()
    f.no_length.add(URLS[0])
    with pytest.raises(AcquireError):
        run(store, f, tmp_path)
    assert store.list("") == []


def test_two_stalls_resumed_with_206_store_one_identical_file(tmp_path):
    store = MemoryStore()
    f = meta_fetcher()
    f.stalls[MURL] = 2
    m = mrun(store, f, tmp_path)
    assert m["status"] == "created"
    assert [offset > 0 for _, offset in f.requests] == [False, True, True]
    (path,) = store.list(ROOT)
    assert path == m["gcs_prefix"] + "EDITION.zip"
    stored = (tmp_path / "dl" / "EDITION.zip").read_bytes()
    assert stored == f.bodies[MURL]
    assert m["files"][0]["sha256"] == hashlib.sha256(f.bodies[MURL]).hexdigest()


def test_resume_answered_with_200_restarts_from_the_start(tmp_path):
    store = MemoryStore()
    f = meta_fetcher()
    f.stalls[MURL] = 1
    f.resume_status = 200
    m = mrun(store, f, tmp_path)
    assert m["status"] == "created"
    assert [offset > 0 for _, offset in f.requests] == [False, True]
    assert (tmp_path / "dl" / "EDITION.zip").read_bytes() == f.bodies[MURL]
    assert m["files"][0]["sha256"] == hashlib.sha256(f.bodies[MURL]).hexdigest()


def test_nine_stalls_raise_and_leave_store_unchanged(tmp_path):
    store = MemoryStore()
    f = meta_fetcher()
    f.stalls[MURL] = 9
    with pytest.raises(AcquireError):
        mrun(store, f, tmp_path)
    assert store.list("") == []


def test_eight_stalls_still_finish(tmp_path):
    store = MemoryStore()
    f = meta_fetcher()
    f.stalls[MURL] = 8
    assert mrun(store, f, tmp_path)["status"] == "created"


# --- no URLs or dataset folders in code --------------------------------------


def test_no_url_or_dataset_folder_in_code():
    folders = [e["gcs"] for e in load_catalog() if e.get("gcs")]
    files = list((REPO / "pipeline").rglob("*.py")) + list((REPO / "src" / "terrain").rglob("*.py"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "https://" not in text, path
        for folder in folders:
            assert folder not in text, (path, folder)
