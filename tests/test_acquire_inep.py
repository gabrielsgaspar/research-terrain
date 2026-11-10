"""The INEP acquirers and the `bigquery.py` changes, with a fake store and session.

No test touches the network, GCS or BigQuery. Every value is synthetic.
"""

import copy
import io
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from terrain import bigquery, inep
from terrain.acquire import AcquireError
from terrain.bigquery import build_query, build_summary_query
from terrain.catalog import dataset
from terrain.inep import (
    CATALOGUE_COLUMNS,
    CATALOGUE_SCHEMA,
    FACILITIES,
    SCHOOLS_SCHEMA,
    execute,
    parse_endereco,
)
from terrain.storage import MemoryStore

TODAY = date(2026, 11, 10)
REPO = Path(__file__).resolve().parents[1]
STATES = (
    "AC, AL, AM, AP, BA, CE, DF, ES, GO, MA, MG, MS, MT, PA, PB, PE, PI, PR, RJ, RN, RO, RR, RS, "
    "SC, SE, SP, TO"
).split(", ")
STATES_SQL = ", ".join(f"'{s}'" for s in STATES)

PHONE = "987654321"


# --- fakes ---------------------------------------------------------------------


class RecordingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.created: list[str] = []

    def create(self, path, data):
        super().create(path, data)
        self.created.append(path)


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
        self.count = count  # None: the number of rows the main query returns
        self.queries: list[str] = []

    def post(self, url, json=None, timeout=None):
        query = json["query"]
        self.queries.append(query)
        job = {"projectId": "proj", "jobId": "job1", "location": "US"}
        if "COUNT(*)" in query:
            n = len(self.coords if "br_bd_diretorios_brasil" in query else self.schools)
            columns, rows = ["n"], [{"n": n if self.count is None else self.count}]
        elif "br_bd_diretorios_brasil" in query:
            columns = dataset("inep_school_catalogue")["bigquery"]["columns"]
            rows = self.coords
        else:
            columns, rows = dataset("inep_schools")["bigquery"]["columns"], self.schools
        catalogue = "br_bd_diretorios_brasil" in query and "COUNT(*)" not in query
        # every column of the catalogue table is STRING in BigQuery
        fields = [{"name": c, "type": "STRING" if catalogue else _kind(c)} for c in columns]
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


def test_catalogue_entry_and_query():
    entry = dataset("inep_school_catalogue")
    bq = entry["bigquery"]
    assert entry["gcs"] == "data/raw/inep/catalogue/"
    assert entry["licence"] == dataset("inep_schools")["licence"]
    assert "microdata" not in entry
    assert bq["columns"] == CATALOGUE_COLUMNS
    assert "telefone" not in bq["columns"]
    assert bq["states"] == STATES
    assert "years" not in bq
    assert "nome" in entry["notes"] and "ALLOWED_BY_TABLE" in entry["notes"]
    assert build_query(bq) == (
        "SELECT id_escola, id_municipio, sigla_uf, nome, endereco, latitude, longitude, "
        "dependencia_administrativa, localizacao, situacao_catalogo "
        "FROM `basedosdados.br_bd_diretorios_brasil.escola` "
        f"WHERE sigla_uf IN ({STATES_SQL}) ORDER BY id_escola"
    )
    assert build_summary_query(bq) == (
        "SELECT COUNT(*) AS n FROM `basedosdados.br_bd_diretorios_brasil.escola` "
        f"WHERE sigla_uf IN ({STATES_SQL})"
    )


@pytest.mark.parametrize("column", ["telefone", "nome", "nome_escola"])
def test_refused_bigquery_columns(column):
    bq = copy.deepcopy(dataset("inep_schools")["bigquery"])
    bq["columns"] = ["id_escola", column]
    with pytest.raises(AcquireError):
        build_query(bq)


def test_nome_is_allowed_only_in_the_school_catalogue_table():
    """The one exception to the `nome` guard: a school's name (bigquery.ALLOWED_BY_TABLE)."""
    catalogue = copy.deepcopy(dataset("inep_school_catalogue")["bigquery"])
    assert "nome" in build_query(catalogue)
    assert bigquery.ALLOWED_BY_TABLE == {
        "basedosdados.br_bd_diretorios_brasil.escola": frozenset({"nome"})
    }
    for column in ("telefone", "nome_escola", "nome_diretor", "cpf_cnpj"):
        bq = {**catalogue, "columns": ["id_escola", column]}
        with pytest.raises(AcquireError):
            build_query(bq)
    for name in ("inep_schools", "ibama_autos"):
        other = {**dataset(name)["bigquery"], "columns": ["id_escola", "nome"]}
        with pytest.raises(AcquireError):
            build_query(other)


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
            no_session,
            None,
            TODAY,
            tmp_path / "work",
            "",
            tmp_path / "m.json",
        )


# --- inep_school_catalogue: Base dos Dados' copy of INEP's catalogue -----------


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        (
            "RUA JOSE DE ALENCAR, 1234 CENTRO. 76801-000 Porto Velho - RO.",
            ("RUA JOSE DE ALENCAR", "1234", "CENTRO", "76801000"),
        ),
        (
            "AVENIDA BRASIL, S/N ZONA RURAL. 69900000 Rio Branco - AC.",
            ("AVENIDA BRASIL", "S/N", "ZONA RURAL", "69900000"),
        ),
        (
            "RUA 7 DE SETEMBRO, 15A JARDIM AÇAÍ. 01310-100 São Paulo - SP.",
            ("RUA 7 DE SETEMBRO", "15A", "JARDIM AÇAÍ", "01310100"),
        ),
        (
            "RODOVIA BR 364, KM 5. 76800-000 Porto Velho - RO.",
            ("RODOVIA BR 364, KM 5", None, None, "76800000"),
        ),
        ("RUA A, 10", ("RUA A", "10", None, None)),
        ("SITIO BOA VISTA. Porto Velho - RO.", ("SITIO BOA VISTA", None, None, None)),
        ("RUA X, 123456789", ("RUA X", "123456789", None, None)),  # 9 digits: no CEP
        ("  RUA   B,  20   VILA  NOVA .  76801000  ", ("RUA B", "20", "VILA NOVA", "76801000")),
        ("", (None, None, None, None)),
        (None, (None, None, None, None)),
    ],
)
def test_parse_endereco(text, parts):
    assert parse_endereco(text) == parts


def catalogue_row(id_escola, **over):
    row = {
        "id_escola": id_escola,
        "id_municipio": "1100015",
        "sigla_uf": "RO",
        "nome": "ESCOLA MUNICIPAL JOÃO PAULO",
        "endereco": "RUA AÇAÍ, 10 SÃO JOSÉ. 76801-000 Porto Velho - RO.",
        "latitude": "-8.76",
        "longitude": "-63.9",
        "dependencia_administrativa": "Municipal",
        "localizacao": "Urbana",
        "situacao_catalogo": "Presente",
    }
    row.update(over)
    return row


CATALOGUE = [
    catalogue_row("11000001"),
    catalogue_row(
        "11000002",
        dependencia_administrativa="ESTADUAL",
        localizacao="rural",
        latitude="0",
        longitude="0",
        endereco="LINHA 10, KM 5",
    ),
    catalogue_row(
        "11000003",
        id_municipio="1200013",
        sigla_uf="AC",
        dependencia_administrativa="Privada",
        latitude="40.0",
        longitude="-3.0",
        endereco=None,
        situacao_catalogo="Ausente",
    ),
    catalogue_row("11000004", dependencia_administrativa="3", latitude="-9,5", longitude="-63,1"),
    catalogue_row("11000005", dependencia_administrativa="Federal", latitude="sem dado"),
] + [catalogue_row(f"2{i:07d}") for i in range(200)]


def run_catalogue(tmp_path, rows=CATALOGUE, store=None, name="manifest.json"):
    store = store if store is not None else RecordingStore()
    session = Session(coords=rows)
    manifest = execute(
        "inep_school_catalogue",
        store,
        lambda: session,
        "proj",
        TODAY,
        tmp_path / "work",
        "abc123",
        tmp_path / name,
    )
    return manifest, store, session


def test_catalogue_writes_the_contract_columns(tmp_path):
    manifest, store, session = run_catalogue(tmp_path)
    prefix = "data/raw/inep/catalogue/2026-11-10/"
    assert store.created == [prefix + "inep_school_catalogue.parquet", prefix + "_MANIFEST.json"]
    frame = read_parquet(store, prefix + "inep_school_catalogue.parquet")
    assert frame.columns == list(CATALOGUE_SCHEMA)
    assert dict(frame.schema) == CATALOGUE_SCHEMA
    assert frame.height == len(CATALOGUE)
    assert frame["ano"].null_count() == frame.height
    assert frame["complemento"].null_count() == frame.height

    by_id = {r["id_escola"]: r for r in frame.iter_rows(named=True)}
    first = by_id["11000001"]
    assert first["nome_escola"] == "ESCOLA MUNICIPAL JOÃO PAULO"
    assert (first["endereco"], first["numero"], first["bairro"], first["cep"]) == (
        "RUA AÇAÍ",
        "10",
        "SÃO JOSÉ",
        "76801000",
    )
    assert (first["rede"], first["tipo_localizacao"]) == ("3", "1")
    assert (first["latitude"], first["longitude"]) == (-8.76, -63.9)
    assert [by_id[k]["rede"] for k in ("11000002", "11000003", "11000004", "11000005")] == [
        "2",
        "4",
        "3",
        "1",
    ]
    assert by_id["11000002"]["tipo_localizacao"] == "2"
    # no CEP in the text: street kept whole, number and neighbourhood empty
    assert (by_id["11000002"]["endereco"], by_id["11000002"]["numero"]) == ("LINHA 10, KM 5", None)
    assert by_id["11000002"]["cep"] is None
    assert by_id["11000003"]["endereco"] is None and by_id["11000003"]["cep"] is None
    # (0, 0), a point outside Brazil and a non-number are null; a decimal comma is read
    for key in ("11000002", "11000003", "11000005"):
        assert (by_id[key]["latitude"], by_id[key]["longitude"]) == (None, None)
    assert (by_id["11000004"]["latitude"], by_id["11000004"]["longitude"]) == (-9.5, -63.1)

    notes = manifest["notes"]
    n = len(CATALOGUE)
    assert f"rows: {n}" in notes
    assert "rows per state: AC=1, RO=" in notes
    assert f"rows with an endereco: {n - 1}" in notes
    assert f"share with a cep parsed from endereco: {(n - 2) / n:.4f}" in notes
    assert f"share with coordinates: {(n - 3) / n:.4f}" in notes
    assert "coordinates that are not numbers (set to null): 1" in notes
    assert "coordinates at 0 or outside Brazil (set to null): 2" in notes
    assert "dependencia_administrativa labels not known (rede null): none" in notes
    assert f"rows per situacao_catalogo: Ausente=1, Presente={n - 1}" in notes
    assert "ano is null" in notes
    source = manifest["sources"][0]
    assert source["fonte"] == "basedosdados"
    assert source["table"] == "basedosdados.br_bd_diretorios_brasil.escola"
    assert source["rows"] == n
    assert all("telefone" not in q for q in session.queries)


def test_catalogue_matching_count_is_unchanged_and_uploads_nothing(tmp_path):
    _, store, _ = run_catalogue(tmp_path)
    before = list(store.created)
    manifest, _, again = run_catalogue(tmp_path, store=store, name="second.json")
    assert manifest["status"] == "unchanged"
    assert store.created == before
    assert again.main_queries == []


def test_catalogue_refuses_a_phone_column_in_the_result(tmp_path):
    """Even if the table sent `telefone`, the client refuses a column it did not ask for."""
    entry = copy.deepcopy(dataset("inep_school_catalogue"))

    class WithPhone(Session):
        def post(self, url, json=None, timeout=None):
            response = super().post(url, json, timeout)
            if "COUNT(*)" not in json["query"]:
                payload = response.payload
                payload["schema"]["fields"].append({"name": "telefone", "type": "STRING"})
                for r in payload["rows"]:
                    r["f"].append({"v": PHONE})
            return response

    store = RecordingStore()
    with pytest.raises(AcquireError) as info:
        inep.acquire_catalogue(
            "inep_school_catalogue",
            store,
            lambda: WithPhone(coords=CATALOGUE),
            "proj",
            TODAY,
            tmp_path,
            "",
            entry,
        )
    assert PHONE not in str(info.value)
    assert store.created == []


def test_catalogue_unknown_labels_are_null_up_to_one_percent(tmp_path):
    rows = [*CATALOGUE[:-1], catalogue_row("19999999", dependencia_administrativa="Comunitária")]
    manifest, store, _ = run_catalogue(tmp_path, rows=rows)
    frame = read_parquet(store, store.created[0])
    assert frame.filter(pl.col("id_escola") == "19999999")["rede"].to_list() == [None]
    assert "rede null): COMUNITARIA=1" in manifest["notes"]

    many = [catalogue_row(f"3{i:07d}", localizacao="Indefinida") for i in range(3)] + CATALOGUE
    with pytest.raises(AcquireError, match="localizacao: 3 of"):
        run_catalogue(tmp_path, rows=many, name="m2.json")


@pytest.mark.parametrize(
    "rows",
    [
        [catalogue_row("11000001"), catalogue_row("11000001")],
        [catalogue_row("11000001", id_municipio="12")],
        [catalogue_row(None)],
    ],
)
def test_catalogue_stops_on_a_bad_key(tmp_path, rows):
    with pytest.raises(AcquireError):
        run_catalogue(tmp_path, rows=rows)


def test_catalogue_failed_query_fails_the_run(tmp_path):
    class Failing:
        def post(self, url, json=None, timeout=None):
            return FakeResponse({}, 500)

    store = RecordingStore()
    with pytest.raises(AcquireError):
        inep.acquire_catalogue(
            "inep_school_catalogue", store, Failing, "proj", TODAY, tmp_path, "", None
        )
    assert store.created == []


def test_catalogue_refuses_other_catalog_columns(tmp_path):
    entry = copy.deepcopy(dataset("inep_school_catalogue"))
    entry["bigquery"]["columns"] = [*CATALOGUE_COLUMNS, "porte"]
    with pytest.raises(AcquireError, match="not the expected"):
        inep.acquire_catalogue(
            "inep_school_catalogue",
            RecordingStore(),
            no_session,
            "proj",
            TODAY,
            tmp_path,
            "",
            entry,
        )
