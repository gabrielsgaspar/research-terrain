"""The IBAMA acquirers, with a fake fetcher, store and BigQuery session.

No test touches the network, GCS or BigQuery. Every value is synthetic.
"""

import copy
import csv
import io
import json
import re
import urllib.error
import zipfile
from contextlib import contextmanager
from datetime import date
from email.message import Message
from pathlib import Path

import polars as pl
import pytest

from terrain.acquire import AcquireError
from terrain.catalog import dataset
from terrain.http import Headers
from terrain.ibama import SCHEMAS, add_formato, execute, mapping_complete
from terrain.storage import MemoryStore

TODAY = date(2026, 11, 10)
NAMES = ["ibama_autos", "ibama_embargos"]
REPO = Path(__file__).resolve().parents[1]

# synthetic personal data, planted in the fake portal files
SYNTH_NAME = "João Sintético"
SYNTH_CPF = "99999999999"


# --- fakes ---------------------------------------------------------------------


class RecordingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.created: list[str] = []

    def create(self, path, data):
        super().create(path, data)
        self.created.append(path)


class FakeFetcher:
    """Serves `files` (url -> bytes); every other URL answers 403."""

    def __init__(self, files=None):
        self.files = files or {}
        self.requests: list[tuple[str, str]] = []

    def _forbidden(self, url):
        return urllib.error.HTTPError(url, 403, "Forbidden", Message(), None)

    def head(self, url):
        self.requests.append(("HEAD", url))
        if url not in self.files:
            raise self._forbidden(url)
        return Headers("Mon, 01 Jan 2024 00:00:00 GMT", "", len(self.files[url]))

    @contextmanager
    def get(self, url):
        self.requests.append(("GET", url))
        if url not in self.files:
            raise self._forbidden(url)
        data = self.files[url]
        yield Headers("Mon, 01 Jan 2024 00:00:00 GMT", "", len(data)), io.BytesIO(data)

    def json(self, url):
        raise AssertionError("not used")

    def get_from(self, url, offset):
        raise AssertionError("not used")


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


def _kind(column):
    if column == "ano":
        return "INTEGER"
    if column.startswith("data_"):
        return "DATE"
    if column in ("latitude", "longitude", "area_ha"):
        return "FLOAT"
    return "STRING"


class BQSession:
    """Answers the summary query and the main query for one dataset."""

    def __init__(self, name, rows, max_extraction="2026-01-01", status=200):
        self.columns = dataset(name)["bigquery"]["columns"]
        self.rows = rows
        self.max_extraction = max_extraction
        self.status = status
        self.queries: list[str] = []

    def post(self, url, json=None, timeout=None):
        query = json["query"]
        self.queries.append(query)
        job = {"projectId": "proj", "jobId": "job1", "location": "US"}
        if self.status != 200:
            return FakeResponse({}, self.status)
        if "COUNT(*)" in query:
            fields = [
                {"name": "max_data_extracao", "type": "DATE"},
                {"name": "n", "type": "INTEGER"},
            ]
            cells = [{"v": self.max_extraction}, {"v": str(len(self.rows))}]
            return FakeResponse(
                {
                    "jobComplete": True,
                    "jobReference": job,
                    "schema": {"fields": fields},
                    "totalRows": "1",
                    "rows": [{"f": cells}],
                }
            )
        fields = [{"name": c, "type": _kind(c)} for c in self.columns]
        rows = [
            {"f": [{"v": None if r.get(c) is None else str(r[c])} for c in self.columns]}
            for r in self.rows
        ]
        return FakeResponse(
            {
                "jobComplete": True,
                "jobReference": job,
                "schema": {"fields": fields},
                "totalRows": str(len(rows)),
                "totalBytesProcessed": "99",
                "rows": rows,
            }
        )

    def get(self, url, params=None, timeout=None):
        raise AssertionError("no paging expected")

    @property
    def main_queries(self):
        return [q for q in self.queries if "COUNT(*)" not in q]


def no_session():
    raise AssertionError("BigQuery must not be used")


AUTOS_ROWS = [
    {
        "ano": 2019,
        "data_auto": "2019-10-07",
        "id_auto": "B",
        "id_municipio": "1500000",
        "sigla_uf": "PA",
        "latitude": -3.5,
        "longitude": -50.25,
        "tipo_infracao": "FLORA",
        "tipo_auto": "AI",
        "situacao_auto": "ATIVO",
        "indicador_cancelado": "N",
        "gravidade": "G",
        "indicador_coordenada_valida": "true",
        "data_extracao": "2026-01-01",
    },
    {
        "ano": 2019,
        "data_auto": "2019-10-08",
        "id_auto": "A",
        "id_municipio": "1300000",
        "sigla_uf": "AM",
        "latitude": None,
        "longitude": None,
        "tipo_infracao": None,
        "tipo_auto": "AI",
        "situacao_auto": "CANCELADO",
        "indicador_cancelado": "S",
        "gravidade": None,
        "indicador_coordenada_valida": "false",
        "data_extracao": "2026-01-01",
    },
    {
        "ano": 2018,
        "data_auto": None,
        "id_auto": "C",
        "sigla_uf": "MT",
        "data_extracao": "2026-01-01",
    },
]
EMBARGOS_ROWS = [
    {
        "ano": 2020,
        "data_embargo": "2020-05-01",
        "id_embargo": "E2",
        "id_auto": "A1",
        "id_municipio": "1300000",
        "sigla_uf": "AM",
        "latitude": -5.0,
        "longitude": -60.0,
        "area_ha": 12.5,
        "tipo_area": "rural",
        "indicador_desembargado": "N",
        "indicador_coordenada_valida": "true",
        "data_extracao": "2026-01-01",
    },
    {"ano": 2019, "id_embargo": "E1", "sigla_uf": "PA", "data_extracao": "2026-01-01"},
]
ROWS = {"ibama_autos": AUTOS_ROWS, "ibama_embargos": EMBARGOS_ROWS}


def go(name, store, fetcher, session_factory, tmp_path, entry=None, today=TODAY):
    return execute(
        name,
        store,
        fetcher,
        session_factory,
        "proj",
        today,
        tmp_path / "work",
        "abc123",
        tmp_path / "manifest.json",
        entry,
    )


def stored_frame(store, manifest):
    (file,) = manifest["files"]
    return pl.read_parquet(io.BytesIO(store.read_bytes(file["path"])))


# --- the synthetic portal ------------------------------------------------------


def make_zip(member, header, rows, delimiter=";", encoding="latin-1"):
    text = io.StringIO()
    writer = csv.writer(text, delimiter=delimiter, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            zipfile.ZipInfo(member, date_time=(2020, 1, 1, 0, 0, 0)),
            text.getvalue().encode(encoding),
        )
    return buf.getvalue()


PORTAL_MAP = {
    "id_auto": "SEQ_AUTO_INFRACAO",
    "data_auto": "DAT_HORA_AUTO_INFRACAO",
    "ano": "ANO",
    "id_municipio": "COD_MUN",
    "sigla_uf": "UF",
    "latitude": "LAT",
    "longitude": "LON",
    "tipo_infracao": "TIPO_INF",
    "tipo_auto": "TIPO_AUTO",
    "situacao_auto": "SIT",
    "indicador_cancelado": "CANC",
    "gravidade": "GRAV",
    "indicador_coordenada_valida": None,
    "data_extracao": None,
}
MAIN_URL = "fake://portal/main.zip"
COORD_URL = "fake://portal/coord.zip"
MAIN_HEADER = [
    "SEQ_AUTO_INFRACAO", "DAT_HORA_AUTO_INFRACAO", "ANO", "COD_MUN", "UF", "LAT", "LON",
    "TIPO_INF", "TIPO_AUTO", "SIT", "CANC", "GRAV", "NOME_INFRATOR", "CPF_CNPJ_INFRATOR",
]  # fmt: skip
MAIN_ROWS = [
    [*head, SYNTH_NAME, SYNTH_CPF]
    for head in (
        ["100", "2019-10-07 10:00:00", "2019", "1500000", "PA", "-3,5", ""]
        + ["FLORA", "AI", "ATIVO", "N", "G"],
        ["200", "2019-10-08 00:00:00", "2019", "1300000", "AM", "-4,0", "-51,0"]
        + ["", "AI", "ATIVO", "N", "L"],
        ["300", "", "2018", "5100000", "MT", "", ""] + ["FAUNA", "AI", "ATIVO", "S", "L"],
    )
]
COORD_HEADER = ["SEQ_AUTO_INFRACAO", "LATITUDE", "LONGITUDE", "SEQ_PONTO_POLIGONO"]
COORD_ROWS = [
    ["100", "1,0", "2,0", "2"],
    ["100", "-10,5", "-60,5", "1"],
    ["200", "9,0", "9,0", "1"],
]


def portal_entry():
    entry = copy.deepcopy(dataset("ibama_autos"))
    portal = entry["portal"]
    portal["delimiter"] = ";"
    portal["encoding"] = "latin-1"
    portal["columns"] = dict(PORTAL_MAP)
    portal["files"][0]["url"] = MAIN_URL
    portal["files"][1]["url"] = COORD_URL
    return entry


def portal_fetcher(main_header=MAIN_HEADER):
    drop = [i for i, h in enumerate(MAIN_HEADER) if h not in main_header]
    rows = [[v for i, v in enumerate(r) if i not in drop] for r in MAIN_ROWS]
    return FakeFetcher(
        {
            MAIN_URL: make_zip("auto.csv", main_header, rows),
            COORD_URL: make_zip("coord.csv", COORD_HEADER, COORD_ROWS),
        }
    )


# --- catalog and contract ------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_catalog_entry_has_every_field(name):
    entry = dataset(name)
    assert entry["status"] == "planned"
    assert entry["contract"] == f"data/contracts/{name}.md"
    assert entry["licence"].startswith("IBAMA enforcement records published under")
    assert (REPO / entry["contract"]).is_file()
    bq = entry["bigquery"]
    assert bq["location"] == "US"
    assert bq["maximum_bytes_billed"] == 20000000000
    assert bq["years"] == [2000, 2025]
    assert bq["states"] == ["AC", "AM", "AP", "MA", "MT", "PA", "RO", "RR", "TO"]
    columns = entry["portal"]["columns"]
    assert set(columns) == {c for c in SCHEMAS[name] if c not in ("fonte", "formato")}


@pytest.mark.parametrize("name", NAMES)
def test_contract_lists_the_schema_columns_in_order(name):
    text = (REPO / "data" / "contracts" / f"{name}.md").read_text(encoding="utf-8")
    listed = []
    for line in text.splitlines():
        if line.startswith("| `"):
            listed += re.findall(r"`(\w+)`", line.split("|")[1])
    assert listed == list(SCHEMAS[name])


def test_portal_mapping_is_dormant_in_the_catalog():
    assert not mapping_complete(dataset("ibama_autos"))
    assert not mapping_complete(dataset("ibama_embargos"))
    assert mapping_complete(portal_entry())


# --- BigQuery fallback ---------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_403_on_the_portal_falls_back_to_bigquery(name, tmp_path):
    store, fetcher, session = MemoryStore(), FakeFetcher(), BQSession(name, ROWS[name])
    manifest = go(name, store, fetcher, lambda: session, tmp_path)

    assert manifest["status"] == "created"
    assert [p for p in store.list("") if not p.endswith("_MANIFEST.json")] == [
        manifest["files"][0]["path"]
    ]
    assert manifest["files"][0]["path"].endswith(f"{name}.parquet")
    frame = stored_frame(store, manifest)
    assert list(frame.schema.items()) == list(SCHEMAS[name].items())
    assert set(frame["fonte"]) == {"basedosdados"}
    (source,) = manifest["sources"]
    assert source["fonte"] == "basedosdados"
    assert source["query"] == session.main_queries[0]
    assert source["max_data_extracao"] == "2026-01-01"
    assert source["rows"] == len(ROWS[name])
    assert source["total_bytes_processed"] == 99
    assert source["job_id"] == "job1"
    assert "portal probe: HTTP 403" in manifest["notes"]
    assert fetcher.requests == [("HEAD", dataset(name)["portal"]["page"])]
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_autos_are_sorted_and_carry_formato(tmp_path):
    session = BQSession("ibama_autos", AUTOS_ROWS)
    store = MemoryStore()
    frame = stored_frame(store, go("ibama_autos", store, FakeFetcher(), lambda: session, tmp_path))
    assert frame["id_auto"].to_list() == ["C", "A", "B"]
    assert frame["formato"].to_list() == [None, "aie", "sicafi"]
    assert frame["data_auto"].to_list() == [None, date(2019, 10, 8), date(2019, 10, 7)]
    assert frame["latitude"].to_list() == [None, None, -3.5]
    assert frame["ano"].to_list() == [2018, 2019, 2019]


def test_embargos_are_sorted(tmp_path):
    session = BQSession("ibama_embargos", EMBARGOS_ROWS)
    store = MemoryStore()
    frame = stored_frame(
        store, go("ibama_embargos", store, FakeFetcher(), lambda: session, tmp_path)
    )
    assert frame["id_embargo"].to_list() == ["E1", "E2"]
    assert frame["area_ha"].to_list() == [None, 12.5]


def test_formato_boundary():
    frame = pl.DataFrame(
        {"data_auto": [date(2019, 10, 7), date(2019, 10, 8), None]},
        schema={"data_auto": pl.Date},
    )
    assert add_formato(frame)["formato"].to_list() == ["sicafi", "aie", None]


@pytest.mark.parametrize("status", [403, 500])
def test_a_failed_query_raises_before_any_upload(status, tmp_path):
    store = RecordingStore()
    session = BQSession("ibama_autos", AUTOS_ROWS, status=status)
    with pytest.raises(AcquireError):
        go("ibama_autos", store, FakeFetcher(), lambda: session, tmp_path)
    assert store.created == []


def test_a_missing_billing_project_raises(tmp_path):
    store = RecordingStore()
    with pytest.raises(AcquireError):
        execute(
            "ibama_autos", store, FakeFetcher(), no_session, None, TODAY, tmp_path / "w",
            "c", tmp_path / "m.json",
        )  # fmt: skip
    assert store.created == []


# --- incomplete mapping --------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_incomplete_mapping_requests_only_the_head_probe(name, tmp_path):
    entry = dataset(name)
    urls = {f["url"]: b"x" for f in entry["portal"]["files"] if f["url"]}
    urls[entry["portal"]["page"]] = b"page"
    fetcher = FakeFetcher(urls)  # everything would succeed, if asked
    session = BQSession(name, ROWS[name])
    manifest = go(name, MemoryStore(), fetcher, lambda: session, tmp_path)
    assert fetcher.requests == [("HEAD", entry["portal"]["page"])]
    assert "portal probe: ok" in manifest["notes"]
    assert "portal skipped: mapping incomplete" in manifest["notes"]


# --- complete synthetic mapping ------------------------------------------------


def test_portal_path_writes_the_same_schema_without_personal_data(tmp_path, caplog, capsys):
    caplog.set_level("DEBUG")
    entry = portal_entry()
    fetcher = portal_fetcher()
    fetcher.files[entry["portal"]["page"]] = b"page"
    store = RecordingStore()
    manifest = go("ibama_autos", store, fetcher, no_session, tmp_path, entry)

    frame = stored_frame(store, manifest)
    assert list(frame.schema.items()) == list(SCHEMAS["ibama_autos"].items())
    assert set(frame["fonte"]) == {"ibama"}
    assert frame["id_auto"].to_list() == ["300", "100", "200"]  # sorted by ano, id_auto
    assert frame["formato"].to_list() == [None, "sicafi", "aie"]
    assert frame["latitude"].to_list() == [None, -3.5, -4.0]
    # row 100: main latitude kept, longitude filled from the point with the smallest order
    assert frame["longitude"].to_list() == [None, -60.5, -51.0]
    assert frame["tipo_infracao"].to_list() == ["FAUNA", "FLORA", None]
    assert frame["indicador_coordenada_valida"].null_count() == 3
    assert frame["data_extracao"].null_count() == 3

    assert "portal used" in manifest["notes"]
    assert [s["url"] for s in manifest["sources"]] == [MAIN_URL, COORD_URL]
    assert all(s["fonte"] == "ibama" and s["bytes"] > 0 for s in manifest["sources"])
    assert not list((tmp_path / "work").glob("portal_*"))  # downloads deleted
    assert store.created[-1].endswith("_MANIFEST.json")

    stored = store.read_bytes(manifest["files"][0]["path"])
    everything = [
        stored,
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        (tmp_path / "manifest.json").read_bytes(),
        caplog.text.encode("utf-8"),
        "".join(capsys.readouterr()).encode("utf-8"),
    ]
    forbidden = [SYNTH_NAME, SYNTH_CPF, "NOME_INFRATOR", "CPF_CNPJ_INFRATOR"]
    for blob in everything:
        for item in forbidden:
            assert item.encode("utf-8") not in blob
            assert item.encode("latin-1") not in blob


def test_a_missing_mapped_column_falls_back_to_bigquery(tmp_path):
    entry = portal_entry()
    header = [h for h in MAIN_HEADER if h != "TIPO_AUTO"]
    fetcher = portal_fetcher(header)
    fetcher.files[entry["portal"]["page"]] = b"page"
    session = BQSession("ibama_autos", AUTOS_ROWS)
    store = MemoryStore()
    manifest = go("ibama_autos", store, fetcher, lambda: session, tmp_path, entry)
    assert set(stored_frame(store, manifest)["fonte"]) == {"basedosdados"}
    assert "portal failed: a mapped column is missing from a file header" in manifest["notes"]
    assert "TIPO_AUTO" not in manifest["notes"]
    assert not list((tmp_path / "work").glob("portal_*"))


def test_a_403_on_a_complete_mapping_falls_back_without_a_data_value(tmp_path):
    session = BQSession("ibama_autos", AUTOS_ROWS)
    manifest = go(
        "ibama_autos", MemoryStore(), FakeFetcher(), lambda: session, tmp_path, portal_entry()
    )
    assert "portal failed: HTTPError" in manifest["notes"]
    assert manifest["sources"][0]["fonte"] == "basedosdados"


def test_a_value_that_will_not_type_falls_back(tmp_path):
    entry = portal_entry()
    rows = [[*r[:2], "not-a-year", *r[3:]] for r in MAIN_ROWS]
    fetcher = FakeFetcher(
        {
            entry["portal"]["page"]: b"p",
            MAIN_URL: make_zip("auto.csv", MAIN_HEADER, rows),
            COORD_URL: make_zip("coord.csv", COORD_HEADER, COORD_ROWS),
        }
    )
    session = BQSession("ibama_autos", AUTOS_ROWS)
    manifest = go("ibama_autos", MemoryStore(), fetcher, lambda: session, tmp_path, entry)
    assert "portal failed: a value does not fit its column type" in manifest["notes"]
    assert "not-a-year" not in manifest["notes"]


# --- unchanged, new folders, the manifest last ---------------------------------


def test_unchanged_uploads_nothing_and_a_new_run_gets_a_new_folder(tmp_path):
    name = "ibama_autos"
    store, fetcher = RecordingStore(), FakeFetcher()
    session = BQSession(name, AUTOS_ROWS)

    first = go(name, store, fetcher, lambda: session, tmp_path)
    assert first["status"] == "created"
    assert len(store.created) == 2
    assert store.created[-1] == first["gcs_prefix"] + "_MANIFEST.json"
    assert len(session.main_queries) == 1

    second = go(name, store, fetcher, lambda: session, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert second["files"] == first["files"]
    assert len(store.created) == 2
    assert len(session.main_queries) == 1  # the main query was not run
    written = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert written["status"] == "unchanged"

    session.max_extraction = "2026-02-01"
    third = go(name, store, fetcher, lambda: session, tmp_path)
    assert third["status"] == "created"
    assert third["gcs_prefix"] == first["gcs_prefix"][:-1] + "-2/"
    assert store.created[-1] == third["gcs_prefix"] + "_MANIFEST.json"
    assert third["sources"][0]["max_data_extracao"] == "2026-02-01"

    session.rows = [*AUTOS_ROWS, {"ano": 2021, "id_auto": "Z", "sigla_uf": "PA"}]
    fourth = go(name, store, fetcher, lambda: session, tmp_path)  # same date, one more row
    assert fourth["status"] == "created"
    assert fourth["gcs_prefix"].endswith("-3/")


# --- notes ---------------------------------------------------------------------


def test_notes_list_sorted_distinct_values_without_counts(tmp_path):
    session = BQSession("ibama_autos", AUTOS_ROWS + [dict(AUTOS_ROWS[0], id_auto="D")])
    manifest = go("ibama_autos", MemoryStore(), FakeFetcher(), lambda: session, tmp_path)
    lines = manifest["notes"].splitlines()
    assert "distinct tipo_infracao: FLORA, null" in lines
    assert "distinct tipo_auto: AI, null" in lines
    assert "distinct situacao_auto: ATIVO, CANCELADO, null" in lines
    assert "distinct indicador_cancelado: N, S, null" in lines
    assert "distinct indicador_coordenada_valida: false, null, true" in lines
    assert "source used: basedosdados" in lines


def test_embargo_notes_list_their_own_columns(tmp_path):
    session = BQSession("ibama_embargos", EMBARGOS_ROWS)
    manifest = go("ibama_embargos", MemoryStore(), FakeFetcher(), lambda: session, tmp_path)
    lines = manifest["notes"].splitlines()
    assert "distinct tipo_area: null, rural" in lines
    assert "distinct indicador_desembargado: N, null" in lines
    assert "distinct indicador_coordenada_valida: null, true" in lines
    assert not any(line.startswith("distinct tipo_infracao") for line in lines)
