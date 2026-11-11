import hashlib
import ssl
import urllib.parse
from datetime import date

import polars as pl
import pytest

from terrain import anm
from terrain.acquire import AcquireError
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = "data/raw/test_anm/"
LAYER = "https://layer.test/FeatureServer/0"
CERT_URL = "http://cert.test/intermediate.crt"
DER = b"fake-der-bytes"
SHA = hashlib.sha256(DER).hexdigest()
FIELDS = ["OBJECTID", "PROCESSO", "NUMERO", "ANO", "FASE", "SUBS", "USO", "AREA_HA", "UF"]
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}


def entry(**changes):
    cfg = {
        "layer": LAYER,
        "out_fields": FIELDS,
        "order_by": "OBJECTID",
        "page_size": 2000,
        "out_sr": 4674,
        "min_records": 10,
        "tls_intermediate": {"url": CERT_URL, "sha256": SHA},
    }
    cfg.update(changes)
    return {"name": "test_anm", "gcs": ROOT, "arcgis": cfg}


def feature(i, subs="OURO", ano=2001, uf="PA", geometry=SQUARE):
    props = {
        "OBJECTID": i,
        "PROCESSO": f"8{i:05d}/{ano}",
        "NUMERO": i,
        "ANO": ano,
        "FASE": "LAVRA GARIMPEIRA",
        "SUBS": subs,
        "USO": None,
        "AREA_HA": 10.5,
        "UF": uf,
    }
    return {"type": "Feature", "properties": props, "geometry": geometry}


class FakeService:
    """Answers layer queries from memory and records every request."""

    def __init__(self, features, count=None):
        self.features = features
        self.count = len(features) if count is None else count
        self.requests = []
        self.error = False
        self.fail_first = 0

    def __call__(self, url):
        self.requests.append(url)
        if self.fail_first:
            self.fail_first -= 1
            raise OSError("boom")
        if self.error:
            return {"error": {"code": 500, "message": "boom"}}
        assert url.startswith(LAYER + "/query?")
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        if q.get("returnCountOnly") == "true":
            return {"count": self.count}
        assert q["outFields"] == ",".join(FIELDS)
        assert q["orderByFields"] == "OBJECTID"
        assert q["outSR"] == "4674"
        assert q["f"] == "geojson"
        a = int(q["resultOffset"])
        page = self.features[a : a + int(q["resultRecordCount"])]
        return {"type": "FeatureCollection", "features": page}


def run(store, service, tmp_path, cfg=None, today=date(2025, 3, 1), contexts=None, **kw):
    seen = [] if contexts is None else contexts
    got_bytes = []

    def get_bytes(url):
        got_bytes.append(url)
        return kw.pop("der", DER)

    def make(ctx):
        seen.append(ctx)
        return service

    fake_ctx = FakeContext()
    original = anm.ssl.create_default_context
    anm.ssl.create_default_context = lambda: fake_ctx
    try:
        return anm.acquire(
            store,
            cfg or entry(),
            today,
            tmp_path / "dl",
            "abc123",
            get_bytes=get_bytes,
            make_get_json=make,
            sleep=lambda s: None,
        )
    finally:
        anm.ssl.create_default_context = original


class FakeContext:
    def __init__(self):
        self.cadata = None
        self.verify_flags = ssl.VERIFY_DEFAULT
        self.check_hostname = True
        self.verify_mode = ssl.CERT_REQUIRED

    def load_verify_locations(self, cadata=None):
        self.cadata = cadata


def many(n, **kw):
    return [feature(i, **kw) for i in range(1, n + 1)]


# --- the happy path -------------------------------------------------------------


def test_three_pages_give_a_parquet_with_the_expected_columns(tmp_path):
    service = FakeService(many(4007))
    store = MemoryStore()
    m = run(store, service, tmp_path, cfg=entry(min_records=4000))
    assert m["status"] == "created"
    assert validate_manifest(m, stage="acquire", dataset="test_anm") == []
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01/"
    pages = [u for u in service.requests if "returnCountOnly" not in u]
    assert len(pages) == 3
    frame = pl.read_parquet(tmp_path / "dl" / anm.OUTPUT)
    assert frame.height == 4007
    assert frame.columns == [f.lower() for f in FIELDS] + ["geometry_wkb"]
    assert frame.schema["geometry_wkb"] == pl.Binary
    assert frame.schema["ano"] == pl.Int64
    assert store.list(ROOT) == [m["gcs_prefix"] + anm.OUTPUT]


def test_nome_is_never_in_a_request(tmp_path):
    service = FakeService(many(12))
    run(MemoryStore(), service, tmp_path)
    assert service.requests
    assert not any("NOME" in u.upper() for u in service.requests)


def test_notes_carry_every_count(tmp_path):
    feats = [
        feature(1, subs="OURO", ano=1990, uf="PA"),
        feature(2, subs="MINÉRIO DE OURO", ano=2005, uf="PA"),
        feature(3, subs="OURO NATIVO", ano=None, uf="MT"),
        feature(4, subs="OURO PIGMENTO", ano=1980, uf="MT"),
        feature(5, subs="AREIA", ano=1980, uf="MT", geometry=BOWTIE),
        feature(6, subs="AREIA", ano=2010, uf="MT", geometry=None),
    ]
    store = MemoryStore()
    m = run(store, FakeService(feats), tmp_path, cfg=entry(min_records=1))
    lines = dict(line.split(": ", 1) for line in m["notes"].split("\n"))
    assert lines["records"] == "6"
    assert lines["records by uf"] == "MT=4, PA=2"
    assert lines["gold records"] == "3"
    assert lines["gold records with ano < 2000"] == "1"
    assert lines["records without ano"] == "1"
    assert lines["invalid geometries (kept as given)"] == "1"
    assert lines["records without geometry"] == "1"
    assert lines["intermediate certificate sha256"] == SHA


# --- paging checks ----------------------------------------------------------------


def test_count_mismatch_pages_once_more_then_raises_with_both_counts(tmp_path):
    service = FakeService(many(12), count=15)
    store = MemoryStore()
    with pytest.raises(AcquireError, match=r"15.*12|12.*15"):
        run(store, service, tmp_path)
    counts = [u for u in service.requests if "returnCountOnly" in u]
    assert len(counts) == 2
    assert store.list("") == []


def test_count_mismatch_that_clears_on_the_second_try_passes(tmp_path):
    service = FakeService(many(12), count=15)
    original = service.__call__
    state = {"counts": 0}

    def flaky(url):
        if "returnCountOnly" in url:
            state["counts"] += 1
            service.count = 15 if state["counts"] == 1 else 12
        return original(url)

    assert run(MemoryStore(), flaky, tmp_path)["status"] == "created"


def test_duplicate_objectid_raises(tmp_path):
    feats = many(12)
    feats[5]["properties"]["OBJECTID"] = 1
    store = MemoryStore()
    with pytest.raises(AcquireError, match="OBJECTID"):
        run(store, FakeService(feats), tmp_path)
    assert store.list("") == []


def test_too_few_records_raises(tmp_path):
    store = MemoryStore()
    with pytest.raises(AcquireError, match="minimum"):
        run(store, FakeService(many(12)), tmp_path, cfg=entry(min_records=13))
    assert store.list("") == []


def test_error_body_raises_after_three_retries(tmp_path):
    service = FakeService(many(12))
    service.error = True
    store = MemoryStore()
    with pytest.raises(AcquireError, match="4 times"):
        run(store, service, tmp_path)
    assert len(service.requests) == 4
    assert store.list("") == []


def test_a_failure_that_clears_is_retried(tmp_path):
    service = FakeService(many(12))
    service.fail_first = 3
    assert run(MemoryStore(), service, tmp_path)["status"] == "created"


# --- fields -----------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["NOME", "NOME_X", "nome", "NOME_TITULAR"])
def test_a_nome_field_raises_before_any_call(tmp_path, bad):
    service = FakeService(many(12))
    calls = []
    store = MemoryStore()
    cfg = entry(out_fields=[*FIELDS, bad])
    with pytest.raises(AcquireError):
        anm.acquire(
            store,
            cfg,
            date(2025, 3, 1),
            tmp_path,
            "abc",
            get_bytes=lambda url: calls.append(url) or DER,
            make_get_json=lambda ctx: service,
            sleep=lambda s: None,
        )
    assert calls == []
    assert service.requests == []
    assert store.list("") == []


def test_a_feature_with_an_unrequested_attribute_raises(tmp_path):
    feats = many(12)
    feats[3]["properties"]["NOME"] = "someone"
    store = MemoryStore()
    with pytest.raises(AcquireError) as err:
        run(store, FakeService(feats), tmp_path)
    assert "someone" not in str(err.value)
    assert store.list("") == []


def test_a_feature_missing_an_attribute_raises(tmp_path):
    feats = many(12)
    del feats[0]["properties"]["UF"]
    with pytest.raises(AcquireError):
        run(MemoryStore(), FakeService(feats), tmp_path)


# --- TLS ----------------------------------------------------------------------------


def test_wrong_sha_raises_before_any_layer_request(tmp_path):
    service = FakeService(many(12))
    store = MemoryStore()
    cfg = entry(tls_intermediate={"url": CERT_URL, "sha256": "0" * 64})
    with pytest.raises(AcquireError, match="pinned"):
        run(store, service, tmp_path, cfg=cfg)
    assert service.requests == []
    assert store.list("") == []


def test_the_context_has_cadata_the_partial_chain_flag_and_checks_on(monkeypatch):
    fake = FakeContext()
    monkeypatch.setattr(anm.ssl, "create_default_context", lambda: fake)
    ctx = anm.ssl_context(DER)
    assert ctx is fake
    assert ctx.cadata == DER
    assert ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_the_real_default_context_keeps_checks_on():
    ctx = ssl.create_default_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_acquire_builds_the_context_from_the_pinned_bytes(tmp_path):
    contexts = []
    run(MemoryStore(), FakeService(many(12)), tmp_path, contexts=contexts)
    assert len(contexts) == 1
    assert contexts[0].cadata == DER


# --- the unchanged rule --------------------------------------------------------------


def test_same_counts_give_unchanged_and_no_upload(tmp_path):
    store = MemoryStore()
    first = run(store, FakeService(many(12)), tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = store.list("")
    second = run(store, FakeService(many(12)), tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert store.list("") == before
    assert MANIFEST_NAME in before[-1] or any(MANIFEST_NAME in p for p in before)


def test_a_new_count_gives_a_new_folder(tmp_path):
    store = MemoryStore()
    write_manifest(run(store, FakeService(many(12)), tmp_path), store, tmp_path / "m.json")
    m = run(store, FakeService(many(13)), tmp_path)
    assert m["status"] == "created"
    assert m["gcs_prefix"] == f"{ROOT}2025-03-01-2/"


def test_a_new_uf_split_gives_a_new_folder(tmp_path):
    store = MemoryStore()
    write_manifest(run(store, FakeService(many(12)), tmp_path), store, tmp_path / "m.json")
    other = many(12)
    other[0]["properties"]["UF"] = "MT"
    assert run(store, FakeService(other), tmp_path)["status"] == "created"


# --- the real catalog entry -----------------------------------------------------------


def test_the_real_catalog_entry_loads_and_has_no_holder_name():
    e = dataset("anm_sigmine")
    cfg = e["arcgis"]
    assert e["gcs"].endswith("/")
    assert cfg["order_by"] == "OBJECTID"
    assert len(cfg["tls_intermediate"]["sha256"]) == 64
    anm.check_fields(cfg["out_fields"])
    assert not any(f.upper().startswith("NOME") for f in cfg["out_fields"])
