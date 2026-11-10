"""The INEP acquirers and the `bigquery.py` changes, with a fake opener, store and session.

No test touches the network, GCS or BigQuery. Every value is synthetic. The
certificate bytes are arbitrary; no certificate file exists in the repository.
"""

import copy
import hashlib
import io
import json
import ssl
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from terrain import inep
from terrain.acquire import AcquireError
from terrain.bigquery import build_query, build_summary_query
from terrain.catalog import dataset
from terrain.inep import (
    CATALOGUE_SCHEMA,
    FACILITIES,
    SCHOOLS_SCHEMA,
    acquire_catalogue,
    certificate_context,
    execute,
)
from terrain.storage import MemoryStore

TODAY = date(2026, 11, 10)
REPO = Path(__file__).resolve().parents[1]
STATES = (
    "AC, AL, AM, AP, BA, CE, DF, ES, GO, MA, MG, MS, MT, PA, PB, PE, PI, PR, RJ, RN, RO, RR, RS, "
    "SC, SE, SP, TO"
).split(", ")
STATES_SQL = ", ".join(f"'{s}'" for s in STATES)
FIXED = (2024, 1, 1, 0, 0, 0)

CERT = b"synthetic certificate bytes, not a certificate \x00\x01\x02"
PHONE = "987654321"
DDD = "69"


# --- fakes ---------------------------------------------------------------------


class RecordingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.created: list[str] = []

    def create(self, path, data):
        super().create(path, data)
        self.created.append(path)


class FakeOpener:
    """Serves `files` (url -> bytes) and records every request."""

    def __init__(self, files):
        self.files = files
        self.requests: list[tuple[str, object]] = []

    def __call__(self, url, context=None):
        self.requests.append((url, context))
        if url not in self.files:
            raise OSError("unreachable")
        return io.BytesIO(self.files[url])

    def urls(self):
        return [u for u, _ in self.requests]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


def _kind(column):
    if column in ("ano", "n") or column in FACILITIES:
        return "INTEGER"
    if column in ("latitude", "longitude"):
        return "FLOAT"
    return "STRING"


class Session:
    """Answers the COUNT query, the schools query and the coordinates query."""

    def __init__(self, schools=None, coords=None, count=None):
        self.schools = schools or []
        self.coords = coords or []
        self.count = len(self.schools) if count is None else count
        self.queries: list[str] = []

    def post(self, url, json=None, timeout=None):
        query = json["query"]
        self.queries.append(query)
        job = {"projectId": "proj", "jobId": "job1", "location": "US"}
        if "COUNT(*)" in query:
            columns, rows = ["n"], [{"n": self.count}]
        elif "br_bd_diretorios_brasil" in query:
            columns = dataset("inep_school_catalogue")["bigquery"]["columns"]
            rows = self.coords
        else:
            columns, rows = dataset("inep_schools")["bigquery"]["columns"], self.schools
        fields = [{"name": c, "type": _kind(c)} for c in columns]
        cells = [
            {"f": [{"v": None if r.get(c) is None else str(r[c])} for c in columns]} for r in rows
        ]
        return FakeResponse(
            {
                "jobComplete": True,
                "jobReference": job,
                "schema": {"fields": fields},
                "totalRows": str(len(cells)),
                "totalBytesProcessed": "99",
                "rows": cells,
            }
        )

    def get(self, url, params=None, timeout=None):
        raise AssertionError("no paging expected")

    @property
    def main_queries(self):
        return [q for q in self.queries if "COUNT(*)" not in q]


def no_session():
    raise AssertionError("BigQuery must not be used")


def school(ano, id_escola, rede="3", **facilities):
    row = {
        "ano": ano,
        "id_escola": id_escola,
        "id_municipio": "1100015",
        "sigla_uf": "RO",
        "rede": rede,
        "tipo_localizacao": "1",
    }
    row.update({c: 1 for c in FACILITIES})
    row.update(facilities)
    return row


SCHOOL_ROWS = [
    school(2019, "11000002", rede="4", dependencia_pne=None, internet=0),
    school(2007, "11000001", acessibilidade_inexistente=None),
    school(2007, "11000002", rede="4", acessibilidade_inexistente=None),
    school(2019, "11000001", dependencia_pne=None),
]


def read_parquet(store, path):
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


# --- bigquery.py: the existing texts, pinned -----------------------------------

IBAMA_STATES = "'AC', 'AM', 'AP', 'MA', 'MT', 'PA', 'RO', 'RR', 'TO'"
IBAMA_AUTOS_QUERY = (
    "SELECT ano, data_auto, id_auto, id_municipio, sigla_uf, latitude, longitude, tipo_infracao, "
    "tipo_auto, situacao_auto, indicador_cancelado, gravidade, indicador_coordenada_valida, "
    "data_extracao FROM `basedosdados.br_ibama_fiscalizacao.auto_infracao` "
    f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025 ORDER BY ano, id_auto"
)
IBAMA_AUTOS_SUMMARY = (
    "SELECT MAX(data_extracao) AS max_data_extracao, COUNT(*) AS n "
    "FROM `basedosdados.br_ibama_fiscalizacao.auto_infracao` "
    f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025"
)
IBAMA_EMBARGOS_QUERY = (
    "SELECT ano, data_embargo, id_embargo, id_auto, id_municipio, sigla_uf, latitude, longitude, "
    "area_ha, tipo_area, indicador_desembargado, indicador_coordenada_valida, data_extracao "
    "FROM `basedosdados.br_ibama_fiscalizacao.area_embargada` "
    f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025 ORDER BY ano, id_embargo"
)
IBAMA_EMBARGOS_SUMMARY = (
    "SELECT MAX(data_extracao) AS max_data_extracao, COUNT(*) AS n "
    "FROM `basedosdados.br_ibama_fiscalizacao.area_embargada` "
    f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025"
)


@pytest.mark.parametrize(
    ("name", "query", "summary"),
    [
        ("ibama_autos", IBAMA_AUTOS_QUERY, IBAMA_AUTOS_SUMMARY),
        ("ibama_embargos", IBAMA_EMBARGOS_QUERY, IBAMA_EMBARGOS_SUMMARY),
    ],
)
def test_ibama_query_texts_are_unchanged(name, query, summary):
    bq = dataset(name)["bigquery"]
    assert bq["freshness_column"] == "data_extracao"
    assert build_query(bq) == query
    assert build_summary_query(bq) == summary


def test_summary_query_without_a_freshness_column_is_a_count():
    bq = dataset("inep_schools")["bigquery"]
    assert "freshness_column" not in bq
    assert build_summary_query(bq) == (
        "SELECT COUNT(*) AS n FROM `basedosdados.br_inep_censo_escolar.escola` "
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 2007 AND 2024"
    )


def test_years_may_be_absent_or_null_but_states_stay_required():
    base = {"table": "p.d.t", "columns": ["id_escola"], "order_by": ["id_escola"]}
    expected = "SELECT id_escola FROM `p.d.t` WHERE sigla_uf IN ('AC') ORDER BY id_escola"
    assert build_query({**base, "states": ["AC"]}) == expected
    assert build_query({**base, "states": ["AC"], "years": None}) == expected
    with pytest.raises(KeyError):
        build_query({**base, "years": None})
    with pytest.raises(AcquireError):
        build_query({**base, "states": ["AC"], "years": [2024, 2007]})


def test_freshness_column_is_checked_like_any_column():
    bq = {**dataset("inep_schools")["bigquery"], "freshness_column": "nome_x"}
    with pytest.raises(AcquireError):
        build_summary_query(bq)


# --- catalog and queries -------------------------------------------------------


def test_inep_schools_entry_and_query():
    entry = dataset("inep_schools")
    bq = entry["bigquery"]
    assert entry["gcs"] == "data/raw/inep/schools/"
    assert entry["status"] == "planned"
    assert entry["contract"] == "data/contracts/inep_schools.md"
    assert bq["states"] == STATES
    assert bq["years"] == [2007, 2024]
    assert bq["order_by"] == ["ano", "id_escola"]
    assert bq["maximum_bytes_billed"] == 50000000000
    assert bq["columns"] == list(SCHOOLS_SCHEMA)
    assert build_query(bq) == (
        f"SELECT {', '.join(bq['columns'])} FROM `basedosdados.br_inep_censo_escolar.escola` "
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 2007 AND 2024 ORDER BY ano, id_escola"
    )
    for fact in ("INT64", "2007-2018", "2019-2024", "4,272,656"):
        assert fact in entry["notes"]


def test_catalogue_entry_and_coordinates_query():
    entry = dataset("inep_school_catalogue")
    micro, bq = entry["microdata"], entry["bigquery"]
    assert entry["gcs"] == "data/raw/inep/catalogue/"
    assert entry["licence"] == dataset("inep_schools")["licence"]
    assert micro["encoding"] == "latin-1"
    assert micro["delimiter"] == ";"
    assert micro["member"] == "*/dados/microdados_ed_basica_2024.csv"
    assert micro["columns"] == list(inep.CATALOGUE_SOURCE.values())
    assert not set(micro["columns"]) & {"NU_DDD", "NU_TELEFONE"}
    assert len(micro["extra_ca_sha256"]) == 64
    assert bq["columns"] == ["id_escola", "id_municipio", "sigla_uf", "latitude", "longitude"]
    assert bq["states"] == STATES
    assert "years" not in bq
    query = build_query(bq)
    assert "ano" not in query
    assert query == (
        "SELECT id_escola, id_municipio, sigla_uf, latitude, longitude "
        "FROM `basedosdados.br_bd_diretorios_brasil.escola` "
        f"WHERE sigla_uf IN ({STATES_SQL}) ORDER BY id_escola"
    )


@pytest.mark.parametrize("column", ["telefone", "nome", "nome_escola"])
def test_refused_bigquery_columns(column):
    bq = copy.deepcopy(dataset("inep_schools")["bigquery"])
    bq["columns"] = ["id_escola", column]
    with pytest.raises(AcquireError):
        build_query(bq)


@pytest.mark.parametrize(
    ("name", "schema"),
    [("inep_schools", SCHOOLS_SCHEMA), ("inep_school_catalogue", CATALOGUE_SCHEMA)],
)
def test_contract_lists_every_column(name, schema):
    text = (REPO / dataset(name)["contract"]).read_text(encoding="utf-8")
    for column in schema:
        assert f"`{column}`" in text


# --- inep_schools --------------------------------------------------------------


def run_schools(store, session, tmp_path, name="manifest.json"):
    return execute(
        "inep_schools",
        store,
        None,
        lambda: session,
        "proj",
        TODAY,
        tmp_path / "work",
        "abc123",
        tmp_path / name,
    )


def test_schools_writes_typed_parquet_and_notes(tmp_path):
    store = RecordingStore()
    session = Session(schools=SCHOOL_ROWS)
    manifest = run_schools(store, session, tmp_path)

    assert manifest["status"] == "created"
    prefix = "data/raw/inep/schools/2026-11-10/"
    assert store.created == [prefix + "inep_schools.parquet", prefix + "_MANIFEST.json"]
    frame = read_parquet(store, prefix + "inep_schools.parquet")
    assert frame.columns == list(SCHOOLS_SCHEMA)
    assert dict(frame.schema) == SCHOOLS_SCHEMA
    assert frame.select("ano", "id_escola").rows() == [
        (2007, "11000001"),
        (2007, "11000002"),
        (2019, "11000001"),
        (2019, "11000002"),
    ]
    assert frame["internet"].null_count() == 0
    assert frame["dependencia_pne"].null_count() == 2

    notes = manifest["notes"]
    assert "rows: 4" in notes
    assert "rows per year: 2007=2, 2019=2" in notes
    assert "years all null dependencia_pne: 2019" in notes
    assert "years all null acessibilidade_inexistente: 2007" in notes
    assert "years all null internet: none" in notes
    assert "distinct rede: 3, 4" in notes
    assert "distinct tipo_localizacao: 1" in notes
    source = manifest["sources"][0]
    assert source["fonte"] == "basedosdados"
    assert source["query"] == session.main_queries[0]
    assert source["rows"] == 4


def test_schools_matching_summary_is_unchanged_and_uploads_nothing(tmp_path):
    store = RecordingStore()
    session = Session(schools=SCHOOL_ROWS)
    run_schools(store, session, tmp_path)
    before = list(store.created)

    again = Session(schools=SCHOOL_ROWS)
    manifest = run_schools(store, again, tmp_path, "second.json")
    assert manifest["status"] == "unchanged"
    assert store.created == before
    assert again.main_queries == []
    assert json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))["status"] == (
        "unchanged"
    )


def test_schools_a_changed_count_is_downloaded_again(tmp_path):
    store = RecordingStore()
    run_schools(store, Session(schools=SCHOOL_ROWS), tmp_path)
    changed = Session(schools=SCHOOL_ROWS[:3])
    manifest = run_schools(store, changed, tmp_path, "second.json")
    assert manifest["status"] == "created"
    assert manifest["gcs_prefix"] == "data/raw/inep/schools/2026-11-10-2/"


def test_schools_needs_a_billing_project(tmp_path):
    with pytest.raises(AcquireError):
        execute(
            "inep_schools",
            RecordingStore(),
            None,
            no_session,
            None,
            TODAY,
            tmp_path / "work",
            "",
            tmp_path / "m.json",
        )


# --- the certificate -----------------------------------------------------------


@pytest.fixture
def cadata(monkeypatch):
    """Replace `load_verify_locations` with a recorder of the `cadata` it receives."""
    seen: list[bytes] = []

    def record(self, cafile=None, capath=None, cadata=None):
        seen.append(cadata)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", record)
    return seen


def catalogue_entry(cert=CERT):
    entry = copy.deepcopy(dataset("inep_school_catalogue"))
    entry["microdata"]["extra_ca_sha256"] = hashlib.sha256(cert).hexdigest()
    return entry


def test_correct_certificate_gives_a_verifying_context(cadata):
    micro = catalogue_entry()["microdata"]
    opener = FakeOpener({micro["extra_ca_url"]: CERT})
    context = certificate_context(micro, opener)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert not context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert cadata == [CERT]
    assert opener.urls() == [micro["extra_ca_url"]]


def test_wrong_fingerprint_raises_before_inep_is_contacted(cadata, tmp_path):
    entry = catalogue_entry(cert=b"other bytes")
    micro = entry["microdata"]
    opener = FakeOpener({micro["extra_ca_url"]: CERT, micro["url"]: b"never served"})
    with pytest.raises(AcquireError):
        acquire_catalogue(
            "inep_school_catalogue",
            RecordingStore(),
            opener,
            no_session,
            "proj",
            TODAY,
            tmp_path,
            "",
            entry,
        )
    assert opener.urls() == [micro["extra_ca_url"]]
    assert cadata == []


def test_failed_certificate_download_raises_before_inep_is_contacted(cadata, tmp_path):
    entry = catalogue_entry()
    micro = entry["microdata"]
    opener = FakeOpener({micro["url"]: b"never served"})
    with pytest.raises(AcquireError):
        acquire_catalogue(
            "inep_school_catalogue",
            RecordingStore(),
            opener,
            no_session,
            "proj",
            TODAY,
            tmp_path,
            "",
            entry,
        )
    assert opener.urls() == [micro["extra_ca_url"]]


def test_an_oversized_certificate_download_raises(cadata):
    micro = catalogue_entry()["microdata"]
    big = b"x" * (inep.MAX_CERT_BYTES + 1)
    micro["extra_ca_sha256"] = hashlib.sha256(big).hexdigest()
    with pytest.raises(AcquireError):
        certificate_context(micro, FakeOpener({micro["extra_ca_url"]: big}))


# --- inep_school_catalogue -----------------------------------------------------

HEADER = [
    "NU_ANO_CENSO",
    "NO_REGIAO",
    "CO_ENTIDADE",
    "NO_ENTIDADE",
    "CO_MUNICIPIO",
    "SG_UF",
    "TP_DEPENDENCIA",
    "TP_LOCALIZACAO",
    "DS_ENDERECO",
    "NU_ENDERECO",
    "DS_COMPLEMENTO",
    "NO_BAIRRO",
    "CO_CEP",
    "NU_DDD",
    "NU_TELEFONE",
]


def micro_row(id_escola, name, cep, municipio="1100015", uf="RO", address="RUA AÇAÍ"):
    return [
        "2024",
        "Norte",
        id_escola,
        name,
        municipio,
        uf,
        "3",
        "1",
        address,
        "10",
        "",
        "SÃO JOSÉ",
        cep,
        DDD,
        PHONE,
    ]


def build_zip(rows, member="microdados_censo_escolar_2024/dados/microdados_ed_basica_2024.csv"):
    text = ";".join(HEADER) + "\r\n" + "".join(";".join(r) + "\r\n" for r in rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo(member, date_time=FIXED), text.encode("latin-1"))
        zf.writestr(
            zipfile.ZipInfo("microdados_censo_escolar_2024/leia-me.txt", date_time=FIXED), b"hi"
        )
    return buffer.getvalue()


CATALOGUE_ROWS = [
    micro_row("11000001", "ESCOLA JOÃO PAULO", "76800000"),
    micro_row("11000002", "ESCOLA AÇAÍ", "1310"),
    micro_row("11000003", "ESCOLA SÃO JOSÉ", "ABC12", municipio="1200013", uf="AC"),
    micro_row("11000004", "ESCOLA SEM PONTO", ""),
] + [micro_row(f"2{i:07d}", f"ESCOLA FILLER {i}", "69900000") for i in range(300)]

COORDS = [
    {"id_escola": "11000001", "id_municipio": "1100015", "sigla_uf": "RO"},
    {"id_escola": "11000002", "id_municipio": "1100015", "sigla_uf": "RO"},
    {"id_escola": "11000003", "id_municipio": "1200013", "sigla_uf": "AC"},
    {"id_escola": "99999999", "id_municipio": "1100015", "sigla_uf": "RO"},
]
for _row, _lat, _lon in zip(
    COORDS, [-8.76, 0.0, 40.0, -9.0], [-63.9, 0.0, -3.0, -63.0], strict=True
):
    _row["latitude"], _row["longitude"] = _lat, _lon


def run_catalogue(tmp_path, data=None, entry=None, rows=CATALOGUE_ROWS, coords=COORDS):
    entry = entry or catalogue_entry()
    micro = entry["microdata"]
    opener = FakeOpener(
        {micro["extra_ca_url"]: CERT, micro["url"]: data if data is not None else build_zip(rows)}
    )
    store = RecordingStore()
    manifest = execute(
        "inep_school_catalogue",
        store,
        opener,
        lambda: Session(coords=coords),
        "proj",
        TODAY,
        tmp_path / "work",
        "abc123",
        tmp_path / "manifest.json",
        entry,
    )
    return manifest, store, opener


def test_catalogue_writes_the_contract_columns(cadata, monkeypatch, tmp_path):
    monkeypatch.setattr(inep, "CHUNK", 1024)
    data = build_zip(CATALOGUE_ROWS)
    manifest, store, opener = run_catalogue(tmp_path, data)

    prefix = "data/raw/inep/catalogue/2026-11-10/"
    assert store.created == [prefix + "inep_school_catalogue.parquet", prefix + "_MANIFEST.json"]
    frame = read_parquet(store, prefix + "inep_school_catalogue.parquet")
    assert frame.columns == list(CATALOGUE_SCHEMA)
    assert dict(frame.schema) == CATALOGUE_SCHEMA
    assert frame.height == len(CATALOGUE_ROWS)

    first = frame.row(0, named=True)
    assert first["id_escola"] == "11000001"
    assert first["nome_escola"] == "ESCOLA JOÃO PAULO"
    assert first["endereco"] == "RUA AÇAÍ"
    assert first["bairro"] == "SÃO JOSÉ"
    assert first["complemento"] is None
    assert first["ano"] == 2024
    assert (first["latitude"], first["longitude"]) == (-8.76, -63.9)

    by_id = {r["id_escola"]: r for r in frame.iter_rows(named=True)}
    assert by_id["11000001"]["cep"] == "76800000"
    assert by_id["11000002"]["cep"] == "00001310"
    assert by_id["11000003"]["cep"] is None
    assert by_id["11000004"]["cep"] is None
    # (0, 0) and a point outside Brazil are null; so is a school with no coordinate row
    for key in ("11000002", "11000003", "11000004"):
        assert by_id[key]["latitude"] is None
        assert by_id[key]["longitude"] is None

    notes = manifest["notes"]
    assert f"rows: {len(CATALOGUE_ROWS)}" in notes
    assert "rows per state: AC=1, RO=" in notes
    assert "cep values not 1-8 digits (set to null): 1" in notes
    assert "microdata rows with no coordinate row: 301" in notes
    assert "coordinate rows with no microdata row: 1" in notes
    assert "share with coordinates: 0.0033" in notes
    micro = catalogue_entry()["microdata"]
    assert micro["extra_ca_url"] in notes
    assert micro["extra_ca_sha256"] in notes
    assert manifest["sources"][0]["sha256"] == hashlib.sha256(data).hexdigest()
    assert opener.urls() == [micro["extra_ca_url"], micro["url"]]
    assert opener.requests[1][1] is not None  # INEP is fetched with the checked context
    assert cadata == [CERT]


def test_catalogue_stores_no_phone_value_and_no_certificate(cadata, tmp_path):
    manifest, store, _ = run_catalogue(tmp_path)
    for path in store.created:
        blob = store.read_bytes(path)
        assert PHONE.encode() not in blob
        assert CERT not in blob
    assert PHONE not in json.dumps(manifest)
    assert PHONE not in (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert CERT.decode("latin-1") not in json.dumps(manifest)
    frame = read_parquet(store, store.created[0])
    assert not {"NU_DDD", "NU_TELEFONE"} & set(frame.columns)
    assert PHONE not in str(frame.rows())
    assert len(store.created) == 2


def test_catalogue_failed_coordinates_query_fails_the_run(cadata, tmp_path):
    entry = catalogue_entry()
    micro = entry["microdata"]
    opener = FakeOpener({micro["extra_ca_url"]: CERT, micro["url"]: build_zip(CATALOGUE_ROWS)})
    store = RecordingStore()

    class Failing:
        def post(self, url, json=None, timeout=None):
            return FakeResponse({}, 500)

    with pytest.raises(AcquireError):
        acquire_catalogue(
            "inep_school_catalogue",
            store,
            opener,
            Failing,
            "proj",
            TODAY,
            tmp_path,
            "",
            entry,
        )
    assert store.created == []


def test_catalogue_rejects_a_zip_without_exactly_one_member(cadata, tmp_path):
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, build_zip(CATALOGUE_ROWS, member="other/file.csv"))


def test_catalogue_rejects_a_download_that_is_not_a_zip(cadata, tmp_path):
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, b"not a zip")


def test_catalogue_stops_on_a_repeated_key(cadata, tmp_path):
    rows = [micro_row("11000001", "A", "1"), micro_row("11000001", "B", "2")]
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, rows=rows)


def test_catalogue_stops_on_a_bad_municipality_code(cadata, tmp_path):
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, rows=[micro_row("11000001", "A", "1", municipio="12")])


def test_catalogue_refuses_a_missing_header_column(cadata, tmp_path):
    entry = catalogue_entry()
    entry["microdata"]["columns"] = [*entry["microdata"]["columns"], "CO_NOT_THERE"]
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, entry=entry)


def test_catalogue_refuses_contact_columns_in_the_catalog(cadata, tmp_path):
    entry = catalogue_entry()
    entry["microdata"]["columns"] = [*entry["microdata"]["columns"], "NU_TELEFONE"]
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, entry=entry)
