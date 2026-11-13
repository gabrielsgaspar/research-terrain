"""The BigQuery client and query builder. A fake session stands in for the network."""

from datetime import date

import pytest

from terrain.acquire import AcquireError
from terrain.bigquery import build_query, build_summary_query, run_query
from terrain.catalog import dataset

ENDPOINT = "bq://v2/"
FIELDS = [
    {"name": "ano", "type": "INTEGER"},
    {"name": "data_auto", "type": "DATE"},
    {"name": "latitude", "type": "FLOAT"},
    {"name": "id_auto", "type": "STRING"},
]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    """Answers the POST with the first response and each GET with the next one."""

    def __init__(self, post_response, get_responses=()):
        self.post_response = post_response
        self.get_responses = list(get_responses)
        self.posts = []
        self.gets = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self.post_response

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        return self.get_responses.pop(0)


def row(*values):
    return {"f": [{"v": v} for v in values]}


def page(rows, **extra):
    return FakeResponse({"jobComplete": True, "rows": rows, **extra})


def first_page(rows, token, total="3"):
    return FakeResponse(
        {
            "jobComplete": True,
            "jobReference": {"projectId": "p", "jobId": "job1", "location": "EU"},
            "schema": {"fields": FIELDS},
            "totalRows": total,
            "totalBytesProcessed": "1234",
            "rows": rows,
            "pageToken": token,
        }
    )


def run(session, **kw):
    return run_query(session, ENDPOINT, "proj", "SELECT 1", "US", 1000, sleep=lambda s: None, **kw)


# --- query builder -------------------------------------------------------------


def test_query_selects_exactly_the_listed_columns_and_filters():
    bq = dataset("ibama_autos")["bigquery"]
    q = build_query(bq)
    assert q.startswith("SELECT " + ", ".join(bq["columns"]) + " FROM `")
    assert "`basedosdados.br_ibama_fiscalizacao.auto_infracao`" in q
    assert "sigla_uf IN ('AC', 'AM', 'AP', 'MA', 'MT', 'PA', 'RO', 'RR', 'TO')" in q
    assert "ano BETWEEN 2000 AND 2025" in q
    assert q.endswith("ORDER BY ano, id_auto")
    s = build_summary_query(bq)
    assert s.startswith("SELECT MAX(data_extracao) AS max_data_extracao, COUNT(*) AS n FROM")
    assert s.split(" FROM ")[1] == q.split(" FROM ")[1].split(" ORDER BY ")[0]


IBAMA_STATES = "'AC', 'AM', 'AP', 'MA', 'MT', 'PA', 'RO', 'RR', 'TO'"
SCHOOL_STATES = (
    "'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', "
    "'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO'"
)


def test_catalog_blocks_without_filters_or_aggregate_give_todays_queries():
    autos = dataset("ibama_autos")["bigquery"]
    assert build_query(autos) == (
        "SELECT ano, data_auto, id_auto, id_municipio, sigla_uf, latitude, longitude, "
        "tipo_infracao, tipo_auto, situacao_auto, indicador_cancelado, gravidade, "
        "indicador_coordenada_valida, data_extracao "
        "FROM `basedosdados.br_ibama_fiscalizacao.auto_infracao` "
        f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025 "
        "ORDER BY ano, id_auto"
    )
    assert build_summary_query(autos) == (
        "SELECT MAX(data_extracao) AS max_data_extracao, COUNT(*) AS n "
        "FROM `basedosdados.br_ibama_fiscalizacao.auto_infracao` "
        f"WHERE sigla_uf IN ({IBAMA_STATES}) AND ano BETWEEN 2000 AND 2025"
    )
    schools = dataset("inep_schools")["bigquery"]
    assert build_query(schools) == (
        "SELECT ano, id_escola, id_municipio, sigla_uf, rede, tipo_localizacao, "
        "agua_rede_publica, esgoto_rede_publica, energia_rede_publica, internet, "
        "biblioteca_sala_leitura, laboratorio_ciencias, laboratorio_informatica, "
        "quadra_esportes, dependencia_pne, acessibilidade_inexistente "
        "FROM `basedosdados.br_inep_censo_escolar.escola` "
        f"WHERE sigla_uf IN ({SCHOOL_STATES}) AND ano BETWEEN 2007 AND 2024 "
        "ORDER BY ano, id_escola"
    )
    assert build_summary_query(schools) == (
        "SELECT COUNT(*) AS n FROM `basedosdados.br_inep_censo_escolar.escola` "
        f"WHERE sigla_uf IN ({SCHOOL_STATES}) AND ano BETWEEN 2007 AND 2024"
    )


BASE = {
    "table": "p.d.t",
    "states": ["AC"],
    "years": [2000, 2001],
    "columns": ["ano", "x"],
    "order_by": ["ano"],
}
WHERE = "WHERE sigla_uf IN ('AC') AND ano BETWEEN 2000 AND 2001"


def test_prefix_between_filter():
    bq = {**BASE, "filters": [{"column": "causa", "prefix_between": ["X85", "Y09"], "length": 3}]}
    clause = "SUBSTR(causa, 1, 3) BETWEEN 'X85' AND 'Y09'"
    assert build_query(bq) == f"SELECT ano, x FROM `p.d.t` {WHERE} AND {clause} ORDER BY ano"
    assert build_summary_query(bq) == f"SELECT COUNT(*) AS n FROM `p.d.t` {WHERE} AND {clause}"


def test_in_filter_and_two_filters_are_joined_with_and():
    bq = {
        **BASE,
        "filters": [
            {"column": "tipo", "in": ["a", "B_2"]},
            {"column": "causa", "prefix_between": ["X85", "Y09"], "length": 3},
        ],
    }
    assert build_summary_query(bq) == (
        f"SELECT COUNT(*) AS n FROM `p.d.t` {WHERE} AND tipo IN ('a', 'B_2') "
        "AND SUBSTR(causa, 1, 3) BETWEEN 'X85' AND 'Y09'"
    )


@pytest.mark.parametrize("value", ["a'b", "a b", "a-b", "", "x" * 21, 5, 'a"b', "a;b"])
def test_a_filter_value_that_is_not_plain_raises(value):
    with pytest.raises(AcquireError):
        build_query({**BASE, "filters": [{"column": "c", "in": [value]}]})
    with pytest.raises(AcquireError):
        build_query(
            {**BASE, "filters": [{"column": "c", "prefix_between": ["A", value], "length": 1}]}
        )


@pytest.mark.parametrize(
    "item",
    [
        {"column": "c", "prefix_between": ["A"], "length": 1},
        {"column": "c", "prefix_between": ["A", "B", "C"], "length": 1},
        {"column": "c", "prefix_between": ["A", "B"], "length": 0},
        {"column": "c", "prefix_between": ["A", "B"]},
        {"column": "c", "in": []},
        {"column": "c"},
        {"column": "c", "in": ["a"], "prefix_between": ["A", "B"], "length": 1},
        {"column": "nome_x", "in": ["a"]},
        {"column": "C d", "in": ["a"]},
        {"in": ["a"]},
    ],
)
def test_a_malformed_filter_raises(item):
    with pytest.raises(AcquireError):
        build_query({**BASE, "filters": [item]})


AGG = {"group_by": ["ano", "mun"], "count": "n_obitos"}


def test_aggregate_query_and_summary():
    bq = {**BASE, "aggregate": AGG}
    inner = f"SELECT ano, mun, COUNT(*) AS n_obitos FROM `p.d.t` {WHERE} GROUP BY ano, mun"
    assert build_query(bq) == inner + " ORDER BY ano, mun"
    assert build_summary_query(bq) == f"SELECT COUNT(*) AS n FROM ({inner})"


def test_aggregate_with_sums_filters_and_no_columns_or_order_by():
    bq = {k: v for k, v in BASE.items() if k not in ("columns", "order_by")}
    bq["filters"] = [{"column": "tipo", "in": ["a"]}]
    bq["aggregate"] = {"group_by": ["ano"], "count": "n", "sums": ["area", "valor"]}
    inner = (
        "SELECT ano, COUNT(*) AS n, SUM(CAST(area AS FLOAT64)) AS sum_area, "
        f"SUM(CAST(valor AS FLOAT64)) AS sum_valor FROM `p.d.t` {WHERE} AND tipo IN ('a') "
        "GROUP BY ano"
    )
    assert build_query(bq) == inner + " ORDER BY ano"
    assert build_summary_query(bq) == f"SELECT COUNT(*) AS n FROM ({inner})"


@pytest.mark.parametrize(
    "aggregate",
    [
        {"group_by": ["cpf_cnpj_doador"], "count": "n"},
        {"group_by": ["ano", "nome_doador"], "count": "n"},
        {"group_by": ["ano"], "count": "nome_n"},
        {"group_by": ["ano"], "count": "n", "sums": ["cpf_cnpj_doador"]},
        {"group_by": ["ano"], "count": "n", "sums": ["nome_doador"]},
        {"group_by": ["geometria"], "count": "n"},
        {"group_by": ["telefone"], "count": "n"},
        {"group_by": [], "count": "n"},
        {"group_by": ["ano"], "count": "n; DROP"},
        {"group_by": ["a b"], "count": "n"},
    ],
)
def test_aggregate_refuses_identifiers_and_odd_names(aggregate):
    bq = {**BASE, "aggregate": aggregate}
    with pytest.raises(AcquireError):
        build_query(bq)
    with pytest.raises(AcquireError):
        build_summary_query(bq)


@pytest.mark.parametrize(
    "bad",
    [
        "cpf_cnpj_infrator",
        "nome_infrator",
        "nome_imovel",
        "geometria",
        "ano desc",
        "a`b",
        "Ano",
        "",
    ],
)
def test_builder_refuses_identifiers_and_odd_names(bad):
    bq = dict(dataset("ibama_autos")["bigquery"])
    bq["columns"] = [*bq["columns"], bad]
    with pytest.raises(AcquireError):
        build_query(bq)
    bq = dict(dataset("ibama_autos")["bigquery"])
    bq["order_by"] = [bad]
    with pytest.raises(AcquireError):
        build_query(bq)


@pytest.mark.parametrize(
    "key, value",
    [
        ("table", "a b.c.d"),
        ("table", "p.d.t`; DROP"),
        ("states", ["PA') OR ('1"]),
        ("years", [2025, 2000]),
        ("years", ["2000", "2025"]),
    ],
)
def test_builder_refuses_malformed_table_states_and_years(key, value):
    bq = {**dataset("ibama_autos")["bigquery"], key: value}
    with pytest.raises(AcquireError):
        build_query(bq)


# --- client --------------------------------------------------------------------


def test_pages_three_times_and_polls_once_and_types_values():
    incomplete = FakeResponse({"jobComplete": False, "jobReference": {"jobId": "job1"}})
    session = FakeSession(
        incomplete,
        [
            first_page([row("2019", "2019-10-08", "-3.5", "A1")], "t2"),
            page([row("2020", None, None, "A2")], pageToken="t3"),
            page([row(None, "2021-01-02", "1e-2", "A3")]),
        ],
    )
    result = run(session)
    assert result.columns == ["ano", "data_auto", "latitude", "id_auto"]
    assert result.rows == [
        [2019, date(2019, 10, 8), -3.5, "A1"],
        [2020, None, None, "A2"],
        [None, date(2021, 1, 2), 0.01, "A3"],
    ]
    assert result.total_bytes_processed == 1234
    assert result.job_id == "job1"
    assert result.location == "EU"
    url, body = session.posts[0]
    assert url == ENDPOINT + "projects/proj/queries"
    assert body["useLegacySql"] is False
    assert body["location"] == "US"
    assert body["maximumBytesBilled"] == "1000"
    assert len(session.gets) == 3  # one poll, two further pages
    assert all(u == ENDPOINT + "projects/proj/queries/job1" for u, _ in session.gets)
    # the poll uses the requested location; the pages use the one the job reports
    assert [p["location"] for _, p in session.gets] == ["US", "EU", "EU"]
    assert "pageToken" not in session.gets[0][1]
    assert [p.get("pageToken") for _, p in session.gets[1:]] == ["t2", "t3"]


def test_allowed_columns_are_enforced():
    session = FakeSession(first_page([row("1", "2020-01-01", "1", "x")], None, total="1"))
    with pytest.raises(AcquireError):
        run(session, allowed_columns=["ano", "data_auto", "latitude"])
    session = FakeSession(first_page([row("1", "2020-01-01", "1", "x")], None, total="1"))
    assert len(run(session, allowed_columns=[f["name"] for f in FIELDS]).rows) == 1


def test_total_rows_mismatch_raises():
    session = FakeSession(first_page([row("1", "2020-01-01", "1", "x")], None, total="2"))
    with pytest.raises(AcquireError, match="totalRows"):
        run(session)


def test_errors_field_raises():
    ok = first_page([], None, total="0").payload
    session = FakeSession(FakeResponse({**ok, "errors": [{"reason": "x"}]}))
    with pytest.raises(AcquireError, match="errors"):
        run(session)


def test_non_200_raises_without_the_body():
    session = FakeSession(FakeResponse({"error": {"message": "secret-ish body"}}, status=403))
    with pytest.raises(AcquireError) as err:
        run(session)
    assert "403" in str(err.value)
    assert "secret-ish" not in str(err.value)


def test_unknown_type_and_bad_project_raise():
    fields = [{"name": "g", "type": "GEOGRAPHY"}]
    ok = FakeResponse(
        {"jobComplete": True, "schema": {"fields": fields}, "totalRows": "1", "rows": [row("x")]}
    )
    with pytest.raises(AcquireError):
        run(FakeSession(ok))
    with pytest.raises(AcquireError):
        run_query(FakeSession(ok), ENDPOINT, "bad project/", "SELECT 1", "US", 1)
