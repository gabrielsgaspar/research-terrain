import gzip
import hashlib
import io
import json
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

import terrain.acquire
from terrain.acquire import AcquireError, acquire, check_file, expand_urls, run_script
from terrain.catalog import dataset, load_catalog
from terrain.http import Headers, HTTPStatusError
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
        self.texts: dict[str, bytes] = {}  # small bodies served by read()
        self.reads: list[str] = []
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

    def read(self, url: str, limit: int) -> bytes:
        self.reads.append(url)
        return self.texts[url][:limit]

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
        ("gold_price", 2),
        ("sgb_gold_occurrences", 1),
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


# --- csv check ---------------------------------------------------------------

GOOD_CSV = b"FID,uf,value\nA.1,PA,10\nA.2,MT,20\nA.3,AM,30\n"
CSV_CHECK = {"type": "csv", "columns": ["FID", "uf"], "min_rows": 3}


def test_csv_check_passes_with_and_without_bom(tmp_path):
    check_file(_write(tmp_path, GOOD_CSV), CSV_CHECK)
    check_file(_write(tmp_path, b"\xef\xbb\xbf" + GOOD_CSV), CSV_CHECK)


def test_csv_check_fails_on_html_page(tmp_path):
    page = b"<!DOCTYPE html>\n<html><body>Blocked</body></html>\n" * 5
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, page), CSV_CHECK)


def test_csv_check_fails_on_missing_column(tmp_path):
    with pytest.raises(AcquireError, match="f.bin"):
        check_file(_write(tmp_path, GOOD_CSV), {**CSV_CHECK, "columns": ["FID", "municipio"]})


def test_csv_check_fails_on_forbidden_column(tmp_path):
    with pytest.raises(AcquireError, match="f.bin"):
        check_file(_write(tmp_path, GOOD_CSV), {**CSV_CHECK, "forbid_columns": ["value"]})


def test_csv_check_fails_on_too_few_rows(tmp_path):
    with pytest.raises(AcquireError, match="f.bin"):
        check_file(_write(tmp_path, GOOD_CSV), {**CSV_CHECK, "min_rows": 4})
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, b"FID,uf\n\n\n"), {"type": "csv", "columns": ["FID"]})
    with pytest.raises(AcquireError):
        check_file(_write(tmp_path, b""), {"type": "csv", "columns": ["FID"]})


def test_csv_check_fails_on_invalid_utf8(tmp_path):
    with pytest.raises(AcquireError, match="f.bin"):
        check_file(_write(tmp_path, GOOD_CSV + b"A.4,\xff\xfe,1\n"), CSV_CHECK)


def test_csv_error_messages_hold_no_data_value(tmp_path):
    secret = b"Zeca Pessoa"
    body = b"nome_secreto,uf\n" + secret + b",PA\n"
    cases = [
        {"type": "csv", "columns": ["FID"]},
        {"type": "csv", "columns": ["uf"], "forbid_columns": ["nome_secreto"]},
        {"type": "csv", "columns": ["uf"], "min_rows": 5},
    ]
    for check in cases:
        with pytest.raises(AcquireError) as err:
            check_file(_write(tmp_path, body), check)
        assert "Zeca" not in str(err.value)
        assert "PA" not in str(err.value).replace("f.bin", "")
    with pytest.raises(AcquireError) as err:
        check_file(_write(tmp_path, b"\xff" + secret), {"type": "csv", "columns": ["FID"]})
    assert "Zeca" not in str(err.value)


def test_real_csv_checks_and_no_geologo_requested():
    gold = {f.name: f for f in expand_urls(dataset("gold_price"))}
    assert gold["CPIAUCSL.csv"].check["columns"] == ["observation_date", "CPIAUCSL"]
    assert gold["CMO-Historical-Data-Monthly.xlsx"].check["type"] == "zip"
    (sgb,) = expand_urls(dataset("sgb_gold_occurrences"))
    assert sgb.name == "sgb_ocorrencias.csv"
    assert sgb.check["type"] == "csv"
    for col in ("FID", "substancias", "status_economico", "municipio", "uf"):
        assert col in sgb.check["columns"]
    assert "geologo" in sgb.check["forbid_columns"]
    assert "geologo" not in sgb.url


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


class _RefusingFetcher(FakeFetcher):
    """Answers HEAD or GET of one URL with an HTTP error status."""

    def __init__(self, url, method, status=403, reason="Forbidden") -> None:
        super().__init__()
        self.refuse = (url, method, status, reason)

    def _check(self, url, method):
        refused, m, status, reason = self.refuse
        if url == refused and method == m:
            raise HTTPStatusError(method, url, status, reason)

    def head(self, url):
        self._check(url, "HEAD")
        return super().head(url)

    @contextmanager
    def get(self, url):
        self._check(url, "GET")
        with super().get(url) as response:
            yield response


def test_refused_head_names_url_and_status_and_leaves_store_unchanged(tmp_path):
    store = MemoryStore()
    with pytest.raises(HTTPStatusError, match=rf"HEAD {URLS[4]}: HTTP 403 Forbidden"):
        run(store, _RefusingFetcher(URLS[4], "HEAD"), tmp_path)
    assert store.list("") == []


def test_refused_get_retries_then_names_url_and_status(tmp_path):
    store = MemoryStore()
    fetcher = _RefusingFetcher(URLS[4], "GET", 503, "Service Unavailable")
    with pytest.raises(AcquireError) as caught:
        run(store, fetcher, tmp_path)
    assert str(caught.value) == f"{URLS[4]}: download failed 9 times (HTTP 503 Service Unavailable)"
    assert store.list("") == []


def test_run_script_reports_refused_url_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAIN_BUCKET", "unused")
    monkeypatch.setattr(terrain.acquire, "GCSStore", lambda bucket: MemoryStore())
    monkeypatch.setattr(terrain.acquire, "dataset", lambda name: ENTRY)
    monkeypatch.setattr(terrain.acquire, "UrllibFetcher", lambda: _RefusingFetcher(URLS[0], "HEAD"))
    monkeypatch.setattr("sys.argv", ["acquire", "--manifest-out", str(tmp_path / "m.json")])
    with pytest.raises(SystemExit) as caught:
        run_script("test_ds")
    assert str(caught.value) == f"acquire failed: HEAD {URLS[0]}: HTTP 403 Forbidden"


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


# --- csv files without a byte size, checked by the WFS row count ------------

WURL = "https://example.test/ows?request=GetFeature&outputFormat=csv"
HITS = "https://example.test/ows?request=GetFeature&resultType=hits"
LAST_MODIFIED = "Mon, 01 Jan 2024 00:00:00 GMT"  # what FakeFetcher sends
WCHECK = {"type": "csv", "columns": ["FID", "uf"], "forbid_columns": ["geologo"], "min_rows": 3}


def wentry(**over) -> dict:
    item = {
        "url": WURL,
        "name": "points.csv",
        "count": {"type": "wfs_hits", "url": HITS},
        "check": dict(WCHECK),
    }
    item.update(over)
    return {"name": "test_ds", "gcs": ROOT, "acquire": {"files": [item]}}


def points_csv(rows: int, header: str = "FID,uf") -> bytes:
    lines = [header] + [f"p.{i},PA" for i in range(rows)]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def hits_xml(matched: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
        f'numberMatched="{matched}" numberReturned="0" timeStamp="2026-11-11T00:00:00Z"/>'
    ).encode()


def wfs_fetcher(rows: int = 5, matched: int | str | None = None) -> FakeFetcher:
    """A GeoServer-like source: no Content-Length and no ETag."""
    f = FakeFetcher(urls=[WURL])
    f.bodies[WURL] = points_csv(rows)
    f.no_length.add(WURL)
    f.etags[WURL] = ""
    f.texts[HITS] = hits_xml(str(rows if matched is None else matched))
    return f


def wrun(store, fetcher, tmp_path, entry=None, today=date(2025, 3, 1)):
    return run(store, fetcher, tmp_path, today=today, entry=entry or wentry())


def test_csv_without_content_length_and_without_count_raises(tmp_path):
    # the failure of campaign 0007 s5 (run 43113036449): GeoServer sends no Content-Length
    store = MemoryStore()
    entry = wentry()
    del entry["acquire"]["files"][0]["count"]
    with pytest.raises(AcquireError, match="no Content-Length"):
        wrun(store, wfs_fetcher(), tmp_path, entry=entry)
    assert store.list("") == []


def test_rows_equal_to_the_wfs_count_are_accepted(tmp_path):
    store = MemoryStore()
    f = wfs_fetcher(rows=5)
    m = wrun(store, f, tmp_path)
    assert m["status"] == "created"
    assert validate_manifest(m, stage="acquire", dataset="test_ds") == []
    assert m["sources"] == [
        {"url": WURL, "last_modified": LAST_MODIFIED, "etag": "", "bytes": None, "rows": 5}
    ]
    body = f.bodies[WURL]
    assert m["files"] == [
        {
            "path": m["gcs_prefix"] + "points.csv",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    ]
    assert f.reads == [HITS]


@pytest.mark.parametrize("matched", [4, 6])
def test_rows_different_from_the_wfs_count_raise(tmp_path, matched):
    store = MemoryStore()
    with pytest.raises(AcquireError, match="5 data rows, the server's count is"):
        wrun(store, wfs_fetcher(rows=5, matched=matched), tmp_path)
    assert store.list("") == []


def test_a_cut_stream_is_caught_by_the_count(tmp_path):
    # the stream ends early with no error: no byte size to compare, the count catches it
    store = MemoryStore()
    f = wfs_fetcher(rows=40)
    f.bodies[WURL] = f.bodies[WURL][: len(f.bodies[WURL]) // 2]
    with pytest.raises(AcquireError, match="the server's count is 40"):
        wrun(store, f, tmp_path)
    assert store.list("") == []


def test_count_keeps_the_csv_checks(tmp_path):
    store = MemoryStore()
    with pytest.raises(AcquireError, match="expected at least 3"):
        wrun(store, wfs_fetcher(rows=2), tmp_path)
    f = wfs_fetcher(rows=5)
    f.bodies[WURL] = points_csv(5, header="FID,uf,geologo")
    with pytest.raises(AcquireError, match="forbidden columns"):
        wrun(store, f, tmp_path)
    f = wfs_fetcher(rows=5)
    f.bodies[WURL] = points_csv(5, header="FID,sigla")
    with pytest.raises(AcquireError, match="missing columns"):
        wrun(store, f, tmp_path)
    assert store.list("") == []


def test_count_keeps_a_content_length_when_one_is_sent(tmp_path):
    store = MemoryStore()
    f = wfs_fetcher(rows=5)
    f.no_length.discard(WURL)
    f.declared[WURL] = len(f.bodies[WURL]) + 7
    with pytest.raises(AcquireError):
        wrun(store, f, tmp_path)
    assert store.list("") == []


@pytest.mark.parametrize(
    "answer",
    [
        hits_xml("unknown"),
        hits_xml(""),
        hits_xml("-3"),
        hits_xml("1e3"),
        hits_xml("\u0665"),  # a non-ASCII digit
        b'<?xml version="1.0"?><ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1"/>',
        b'<FeatureCollection numberReturned="0"/>',
        b"<html><body>Zeca</body></html",
        b'<!DOCTYPE x [<!ENTITY a "aaaa">]><FeatureCollection numberMatched="5"/>',
        hits_xml("5") + b" " * (1 << 16),
    ],
)
def test_bad_count_answers_raise_before_any_download(tmp_path, answer):
    store = MemoryStore()
    f = wfs_fetcher(rows=5)
    f.texts[HITS] = answer
    with pytest.raises(AcquireError) as err:
        wrun(store, f, tmp_path)
    assert "Zeca" not in str(err.value)
    assert f.requests == []
    assert store.list("") == []


def test_same_count_is_unchanged_and_a_new_count_is_a_new_folder(tmp_path):
    store = MemoryStore()
    first = wrun(store, wfs_fetcher(rows=5), tmp_path)
    write_manifest(first, store, tmp_path / "m.json")

    again = wfs_fetcher(rows=5)
    second = wrun(store, again, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert again.requests == []

    third = wrun(store, wfs_fetcher(rows=6), tmp_path)
    assert third["status"] == "created"
    assert third["gcs_prefix"] == f"{ROOT}2025-03-01-2/"


@pytest.mark.parametrize(
    "over",
    [
        {"count": {"type": "rows", "url": HITS}},
        {"count": {"type": "wfs_hits", "url": "http://example.test/hits"}},
        {"count": {"type": "wfs_hits", "url": HITS, "min": 1}},
        {"count": {"type": "wfs_hits"}},
        {"count": HITS},
        {"meta": "https://example.test/items/abc?f=json"},
        {"check": {"type": "zip", "member": "*.csv"}},
    ],
)
def test_bad_count_declarations_raise(over):
    with pytest.raises(AcquireError):
        expand_urls(wentry(**over))


def test_count_url_expands_like_the_file_url():
    entry = wentry(
        url="https://example.test/<uf>_<year>.csv",
        name=None,
        years=[2024],
        ufs=["PA"],
        count={"type": "wfs_hits", "url": "https://example.test/hits?uf=<uf>&year=<year>"},
    )
    (f,) = expand_urls(entry)
    assert (f.url, f.count) == (
        "https://example.test/PA_2024.csv",
        "https://example.test/hits?uf=PA&year=2024",
    )


def test_real_sgb_count_is_the_hits_of_the_same_layer():
    (sgb,) = expand_urls(dataset("sgb_gold_occurrences"))
    assert sgb.count is not None and sgb.meta is None
    assert "resultType=hits" in sgb.count
    assert "typeNames=geosgb:ocorrencias_recursos_minerais" in sgb.count
    assert "typeNames=geosgb:ocorrencias_recursos_minerais" in sgb.url
    assert "geologo" not in sgb.count
    assert sgb.check["min_rows"] == 30000
    assert all(f.count is None for f in expand_urls(dataset("gold_price")))


# --- zips without a byte size, whose own directory proves them complete ------

ZURL = "https://example.test/related/Prices.xlsx"
ZCHECK = {"type": "zip", "member": "xl/workbook.xml"}


def small_xlsx() -> bytes:
    sheet = b"".join(b'<row r="%d"><c r="A%d"><v>%d</v></c></row>' % (i, i, i) for i in range(60))
    return make_zip({"xl/workbook.xml": b"<workbook/>", "xl/worksheets/sheet1.xml": sheet})


def zentry(**over) -> dict:
    item = {"url": ZURL, "name": "Prices.xlsx", "complete_by": "zip_directory", "check": ZCHECK}
    item.update(over)
    return {"name": "test_ds", "gcs": ROOT, "acquire": {"files": [item]}}


def zip_fetcher() -> FakeFetcher:
    """A Cloudflare-like source: Last-Modified, no Content-Length, no ETag."""
    f = FakeFetcher(urls=[ZURL])
    f.bodies[ZURL] = small_xlsx()
    f.no_length.add(ZURL)
    f.etags[ZURL] = ""
    return f


def zrun(store, fetcher, tmp_path, entry=None):
    return run(store, fetcher, tmp_path, entry=entry or zentry())


def test_zip_without_content_length_and_without_complete_by_raises(tmp_path):
    # the failure of campaign 0007 s4 (run 43098821873): the World Bank sends no Content-Length
    store = MemoryStore()
    entry = zentry()
    del entry["acquire"]["files"][0]["complete_by"]
    with pytest.raises(AcquireError, match="no Content-Length"):
        zrun(store, zip_fetcher(), tmp_path, entry=entry)
    assert store.list("") == []


def test_zip_proven_by_its_directory_is_accepted(tmp_path):
    store = MemoryStore()
    f = zip_fetcher()
    m = zrun(store, f, tmp_path)
    assert m["status"] == "created"
    assert validate_manifest(m, stage="acquire", dataset="test_ds") == []
    assert m["sources"] == [
        {"url": ZURL, "last_modified": LAST_MODIFIED, "etag": "", "bytes": None}
    ]
    body = f.bodies[ZURL]
    assert m["files"] == [
        {
            "path": m["gcs_prefix"] + "Prices.xlsx",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    ]


def test_every_cut_of_a_zip_fails_its_check(tmp_path):
    body = small_xlsx()
    path = tmp_path / "cut.xlsx"
    for n in range(len(body)):
        path.write_bytes(body[:n])
        with pytest.raises(AcquireError):
            check_file(path, ZCHECK)
    path.write_bytes(body)
    check_file(path, ZCHECK)


def test_a_cut_stream_is_caught_by_the_zip_directory(tmp_path):
    store = MemoryStore()
    f = zip_fetcher()
    f.bodies[ZURL] = f.bodies[ZURL][:-40]
    with pytest.raises(AcquireError, match="not a valid zip"):
        zrun(store, f, tmp_path)
    assert store.list("") == []


def test_a_damaged_member_is_caught_by_its_crc(tmp_path):
    store = MemoryStore()
    f = zip_fetcher()
    body = bytearray(f.bodies[ZURL])
    at = body.index(b'<row r="30">')  # stored: member bytes appear verbatim
    body[at + 1] ^= 0xFF
    f.bodies[ZURL] = bytes(body)
    with pytest.raises(AcquireError, match="corrupt member"):
        zrun(store, f, tmp_path)
    assert store.list("") == []


def test_complete_by_keeps_a_content_length_when_one_is_sent(tmp_path):
    store = MemoryStore()
    f = zip_fetcher()
    f.no_length.discard(ZURL)
    f.declared[ZURL] = len(f.bodies[ZURL]) + 7
    with pytest.raises(AcquireError):
        zrun(store, f, tmp_path)
    assert store.list("") == []


def test_same_last_modified_is_unchanged_and_a_new_one_is_a_new_folder(tmp_path):
    store = MemoryStore()
    first = zrun(store, zip_fetcher(), tmp_path)
    write_manifest(first, store, tmp_path / "m.json")

    again = zip_fetcher()
    assert zrun(store, again, tmp_path)["status"] == "unchanged"
    assert again.requests == []

    newer = zip_fetcher()
    newer._head = lambda url: Headers("Tue, 01 Dec 2026 00:00:00 GMT", "", None)
    third = zrun(store, newer, tmp_path)
    assert third["status"] == "created"
    assert third["gcs_prefix"] == f"{ROOT}2025-03-01-2/"


@pytest.mark.parametrize(
    "over",
    [
        {"complete_by": "size"},
        {"complete_by": True},
        {"check": {"type": "csv", "columns": ["FID"]}},
        {"check": {"type": "gzip"}},
        {"meta": "https://example.test/items/abc?f=json"},
    ],
)
def test_bad_complete_by_declarations_raise(over):
    with pytest.raises(AcquireError):
        expand_urls(zentry(**over))


def test_complete_by_with_count_raises():
    entry = wentry(complete_by="zip_directory")
    with pytest.raises(AcquireError):
        expand_urls(entry)


def test_real_gold_price_xlsx_is_proven_by_its_zip_directory():
    files = {f.name: f for f in expand_urls(dataset("gold_price"))}
    xlsx = files["CMO-Historical-Data-Monthly.xlsx"]
    assert xlsx.complete_by == "zip_directory"
    assert xlsx.check == {"type": "zip", "member": "xl/workbook.xml"}
    assert files["CPIAUCSL.csv"].complete_by is None
    others = [f for e in load_catalog() if "acquire" in e for f in expand_urls(e)]
    assert [f.name for f in others if f.complete_by] == ["CMO-Historical-Data-Monthly.xlsx"]
