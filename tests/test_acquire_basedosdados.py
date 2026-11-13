"""The generic Base dos Dados acquirer, with a fake store and session.

No test touches the network, GCS or BigQuery. Every value is synthetic.
"""

import copy
import io
import json
from datetime import date

import polars as pl
import pytest

from terrain.acquire import AcquireError
from terrain.basedosdados import execute
from terrain.bigquery import aggregate_columns, build_query, build_summary_query
from terrain.catalog import dataset
from terrain.storage import MemoryStore

TODAY = date(2026, 11, 13)
STATES = (
    "AC, AL, AM, AP, BA, CE, DF, ES, GO, MA, MG, MS, MT, PA, PB, PE, PI, PR, RJ, RN, RO, RR, RS, "
    "SC, SE, SP, TO"
).split(", ")
STATES_SQL = ", ".join(f"'{s}'" for s in STATES)


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


class Session:
    """Answers the count query with `count` (default: the rows) and the main query with `rows`."""

    def __init__(self, columns, kinds, rows, count=None):
        self.columns = columns
        self.kinds = kinds
        self.rows = rows
        self.count = count
        self.queries: list[str] = []

    def post(self, url, json=None, timeout=None):
        query = json["query"]
        self.queries.append(query)
        job = {"projectId": "proj", "jobId": "job1", "location": "US"}
        if query.startswith("SELECT COUNT(*) AS n FROM"):
            n = len(self.rows) if self.count is None else self.count
            fields = [{"name": "n", "type": "INTEGER"}]
            cells = [{"f": [{"v": str(n)}]}]
        else:
            fields = [{"name": c, "type": k} for c, k in zip(self.columns, self.kinds, strict=True)]
            cells = [{"f": [{"v": None if v is None else str(v)} for v in r]} for r in self.rows]
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
        return [q for q in self.queries if not q.startswith("SELECT COUNT(*) AS n FROM")]


def sim_session(rows=None, count=None):
    rows = rows if rows is not None else SIM_ROWS
    return Session(
        ["ano", "id_municipio_ocorrencia", "n_obitos"],
        ["INTEGER", "STRING", "INTEGER"],
        rows,
        count,
    )


SIM_ROWS = [
    [1997, "1100015", 4],
    [1996, "1100023", 7],
    [1996, "1100015", 2],
    [1997, None, 1],
]


def sim_entry(min_rows=3):
    entry = copy.deepcopy(dataset("sim_homicides"))
    entry["bigquery"]["min_rows"] = min_rows
    return entry


def run(store, session, tmp_path, entry=None, name="manifest.json"):
    return execute(
        "sim_homicides",
        store,
        lambda: session,
        "proj",
        TODAY,
        tmp_path / "work",
        "abc123",
        tmp_path / name,
        entry or sim_entry(),
    )


def test_created_writes_parquet_and_manifest(tmp_path):
    store = RecordingStore()
    session = sim_session()
    manifest = run(store, session, tmp_path)

    assert manifest["status"] == "created"
    prefix = "data/raw/sim/homicides/2026-11-13/"
    assert store.created == [prefix + "sim_homicides.parquet", prefix + "_MANIFEST.json"]
    frame = pl.read_parquet(io.BytesIO(store.read_bytes(prefix + "sim_homicides.parquet")))
    assert frame.columns == ["ano", "id_municipio_ocorrencia", "n_obitos"]
    assert frame.rows() == [
        (1996, "1100015", 2),
        (1996, "1100023", 7),
        (1997, "1100015", 4),
        (1997, None, 1),
    ]
    source = manifest["sources"][0]
    assert source["query"] == session.main_queries[0]
    assert source["table"] == "basedosdados.br_ms_sim.microdados"
    assert source["url"] is None
    assert source["rows"] == 4
    assert source["rows_per_year"] == {"1996": 2, "1997": 2}
    assert "rows per ano: 1996=2, 1997=2" in manifest["notes"]
    written = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert written["status"] == "created"


def test_a_count_mismatch_uploads_nothing(tmp_path):
    store = RecordingStore()
    with pytest.raises(AcquireError):
        run(store, sim_session(count=5), tmp_path)
    assert store.created == []


def test_fewer_rows_than_min_rows_uploads_nothing(tmp_path):
    store = RecordingStore()
    with pytest.raises(AcquireError, match="fewer than 5"):
        run(store, sim_session(), tmp_path, sim_entry(min_rows=5))
    assert store.created == []


def test_a_repeat_is_unchanged_and_uploads_nothing(tmp_path):
    store = RecordingStore()
    run(store, sim_session(), tmp_path)
    before = list(store.created)

    manifest = run(store, sim_session(), tmp_path, name="second.json")
    assert manifest["status"] == "unchanged"
    assert store.created == before
    assert json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))["status"] == (
        "unchanged"
    )


def test_the_same_count_with_other_years_is_downloaded_again(tmp_path):
    store = RecordingStore()
    run(store, sim_session(), tmp_path)
    shifted = [[1998, "1100015", 4], *SIM_ROWS[1:]]
    manifest = run(store, sim_session(shifted), tmp_path, name="second.json")
    assert manifest["status"] == "created"
    assert manifest["sources"][0]["rows_per_year"] == {"1996": 2, "1997": 1, "1998": 1}


def test_a_column_outside_the_catalog_is_refused(tmp_path):
    store = RecordingStore()
    session = Session(["ano", "id_municipio_ocorrencia", "x"], ["INTEGER", "STRING", "INTEGER"], [])
    session.rows = [[1996, "1100015", 1]] * 3
    with pytest.raises(AcquireError):
        run(store, session, tmp_path)
    assert store.created == []


def test_a_billing_project_is_needed(tmp_path):
    with pytest.raises(AcquireError):
        execute(
            "sim_homicides",
            RecordingStore(),
            lambda: sim_session(),
            None,
            TODAY,
            tmp_path / "work",
            "abc",
            tmp_path / "m.json",
            sim_entry(),
        )


def test_the_plain_columns_path_uses_columns_and_order_by(tmp_path):
    entry = copy.deepcopy(dataset("ibge_population_annual"))
    entry["bigquery"]["min_rows"] = 2
    rows = [[2001, "AC", "1200013", 1000], [2000, "AC", "1200013", 900]]
    session = Session(
        ["ano", "sigla_uf", "id_municipio", "populacao"],
        ["INTEGER", "STRING", "STRING", "INTEGER"],
        rows,
    )
    store = RecordingStore()
    manifest = execute(
        "ibge_population_annual",
        store,
        lambda: session,
        "proj",
        TODAY,
        tmp_path / "work",
        "abc",
        tmp_path / "m.json",
        entry,
    )
    assert manifest["status"] == "created"
    prefix = "data/raw/ibge/population_annual/2026-11-13/"
    frame = pl.read_parquet(io.BytesIO(store.read_bytes(prefix + "ibge_population_annual.parquet")))
    assert frame["ano"].to_list() == [2000, 2001]


# --- the catalog entries -------------------------------------------------------


def test_sim_homicides_entry_and_query():
    entry = dataset("sim_homicides")
    bq = entry["bigquery"]
    assert entry["gcs"] == "data/raw/sim/homicides/"
    assert entry["status"] == "planned"
    assert "page" not in bq
    assert bq["states"] == STATES
    assert bq["years"] == [1996, 2024]
    assert bq["min_rows"] == 50000
    assert bq["maximum_bytes_billed"] == 50000000000
    where = (
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 1996 AND 2024 "
        "AND SUBSTR(causa_basica, 1, 3) BETWEEN 'X85' AND 'Y09'"
    )
    inner = (
        "SELECT ano, id_municipio_ocorrencia, COUNT(*) AS n_obitos "
        f"FROM `basedosdados.br_ms_sim.microdados` {where} "
        "GROUP BY ano, id_municipio_ocorrencia"
    )
    assert build_query(bq) == inner + " ORDER BY ano, id_municipio_ocorrencia"
    assert build_summary_query(bq) == f"SELECT COUNT(*) AS n FROM ({inner})"


def test_ibge_population_annual_entry_and_query():
    entry = dataset("ibge_population_annual")
    bq = entry["bigquery"]
    assert entry["gcs"] == "data/raw/ibge/population_annual/"
    assert entry["status"] == "planned"
    assert bq["min_rows"] == 150000
    assert build_query(bq) == (
        "SELECT ano, sigla_uf, id_municipio, populacao "
        "FROM `basedosdados.br_ibge_populacao.municipio` "
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 1991 AND 2025 "
        "ORDER BY ano, id_municipio"
    )
    assert build_summary_query(bq) == (
        "SELECT COUNT(*) AS n FROM `basedosdados.br_ibge_populacao.municipio` "
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 1991 AND 2025"
    )


def test_tse_receipts_entry_and_query():
    entry = dataset("tse_receipts")
    bq = entry["bigquery"]
    assert entry["gcs"] == "data/raw/tse/receipts/"
    assert entry["status"] == "planned"
    assert "page" not in bq
    inep = dataset("inep_schools")["bigquery"]
    for key in ("endpoint", "scope", "location", "maximum_bytes_billed"):
        assert bq[key] == inep[key]
    assert bq["table"] == "basedosdados.br_tse_eleicoes.receitas_candidato"
    assert bq["states"] == STATES
    assert bq["years"] == [2004, 2012]
    assert bq["min_rows"] == 10000
    assert bq["aggregate"] == {
        "group_by": ["ano", "sigla_uf", "id_municipio", "cargo", "cnae_2_doador"],
        "count": "n_receitas",
        "sums": ["valor_receita"],
    }
    inner = (
        "SELECT ano, sigla_uf, id_municipio, cargo, cnae_2_doador, COUNT(*) AS n_receitas, "
        "SUM(CAST(valor_receita AS FLOAT64)) AS sum_valor_receita "
        "FROM `basedosdados.br_tse_eleicoes.receitas_candidato` "
        f"WHERE sigla_uf IN ({STATES_SQL}) AND ano BETWEEN 2004 AND 2012 "
        "GROUP BY ano, sigla_uf, id_municipio, cargo, cnae_2_doador"
    )
    order = " ORDER BY ano, sigla_uf, id_municipio, cargo, cnae_2_doador"
    assert build_query(bq) == inner + order
    assert build_summary_query(bq) == f"SELECT COUNT(*) AS n FROM ({inner})"
    assert aggregate_columns(bq) == [
        "ano",
        "sigla_uf",
        "id_municipio",
        "cargo",
        "cnae_2_doador",
        "n_receitas",
        "sum_valor_receita",
    ]


@pytest.mark.parametrize("column", ["cpf_cnpj_doador", "nome_doador", "nome_candidato"])
def test_tse_receipts_refuses_a_donor_identifier(column):
    grouped = copy.deepcopy(dataset("tse_receipts")["bigquery"])
    grouped["aggregate"]["group_by"].append(column)
    with pytest.raises(AcquireError):
        build_query(grouped)
    with pytest.raises(AcquireError):
        build_summary_query(grouped)
    summed = copy.deepcopy(dataset("tse_receipts")["bigquery"])
    summed["aggregate"]["sums"].append(column)
    with pytest.raises(AcquireError):
        build_query(summed)
