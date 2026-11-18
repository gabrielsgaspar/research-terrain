"""The amendments panel on a synthetic world: cycle A (mayors 2016, general elections 2014, 2018).

Two states (RO, AC), six municipalities, three parties (10, 20, 30), three elected deputies, a
substitute who served, one senator author, one ambiguous author and one unmatched author. Every
identifier, name and value is made up inside this file.

R1 (exploration list 1) and C1 (list 2) are in the exploration half; the rest go to sealed.
"""

import csv
import functools
import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import amendments_panel as ap
from terrain.builds.amendments_panel import BuildError, build
from terrain.explore import EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/amendments_panel/"
SEALED = "sealed/outcomes/amendments_panel/"
R1, R2, R3, C1, C2, C3 = "1100015", "1100023", "1100031", "1200013", "1200054", "1200104"
TSE = {R1: "00019", R2: "00027", R3: "00035", C1: "01015", C2: "01058", C3: "01104"}
SENTINEL_FAVORECIDO = ("SENTINEL-FAV-CODE", "SENTINEL FAVORECIDO NAME")
NAMES = ("joao da mata", "maria oliveira", "pedro souza", "lucas rocha", "carlos lima", "ana costa")
CODES = ("100", "200", "300", "400", "500", "600", "700")

IND = "Emenda Individual - Transferências com Finalidade Definida"
PIX = "Emenda Individual - Transferências Especiais"
BANC = "Emenda de Bancada"


def cpf(n: int) -> str:
    """A synthetic 11-digit CPF, made up here."""
    return f"{n:011d}"


CPF1, CPF2, CPF3, SHORT = cpf(70001), cpf(70002), cpf(70003), "123"


def rows(data, schema):
    return pl.DataFrame(data, schema=schema, orient="row")


# --- Files of the world


def csv_bytes(header, data, encoding="latin-1"):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(data)
    return buf.getvalue().encode(encoding)


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
    return buf.getvalue()


CAND_HEADER = [
    "ANO_ELEICAO",
    "SQ_CANDIDATO",
    "CD_CARGO",
    "SG_UF",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "NR_PARTIDO",
    "CD_SIT_TOT_TURNO",
    "NR_CPF_CANDIDATO",
    "NR_TITULO_ELEITORAL_CANDIDATO",
]


def cand_zip(year, data):
    body = csv_bytes(CAND_HEADER, [(year, *r, "000000000001") for r in data])
    return make_zip(
        {
            f"consulta_cand_{year}_BRASIL.csv": body,
            f"consulta_cand_{year}_BR.csv": b"not,a;csv\n\x00",  # never read
        }
    )


def votes_zip(year, data, valid=False):
    header = ["SG_UF", "CD_MUNICIPIO", "CD_CARGO", "NR_TURNO", "SQ_CANDIDATO", "QT_VOTOS_NOMINAIS"]
    if valid:
        header.append("QT_VOTOS_NOMINAIS_VALIDOS")
    return make_zip(
        {
            f"votacao_candidato_munzona_{year}_BRASIL.csv": csv_bytes(header, data),
            f"votacao_candidato_munzona_{year}_BR.csv": b"garbage",
        }
    )


# (sq, cargo, uf, full name, urn name, party, status, cpf)
CANDIDATES_2010 = [
    ("S10-1", "5", "RO", "Carlos Alberto Lima", "Carlos Lima", "10", "1", cpf(1)),
    ("S10-2", "5", "RO", "Zeca Tatu da Silva", "Zeca Tatu", "20", "4", cpf(2)),  # not elected
]
CANDIDATES_2014 = [
    ("1001", "6", "RO", "João da Mata Santos", "JOÃO DA MATA", "10", "2", CPF1),
    ("1002", "6", "RO", "Maria Oliveira Dias", "Maria Oliveira", "20", "3", CPF2),
    ("2001", "6", "AC", "Pedro Souza Neto", "Pedro Souza", "30", "1", CPF3),
    ("1003", "6", "RO", "Lucas Rocha Neto", "Lucas Rocha", "10", "5", SHORT),  # substitute
    ("1004", "6", "RO", "Ana Costa Reis", "Ana Costa", "10", "4", cpf(4)),
    ("2002", "6", "AC", "Ana Costa Lopes", "Ana Costa", "30", "4", cpf(5)),
    ("1005", "6", "RO", "Fulano de Tal", "Fulano Tal", "20", "4", cpf(6)),
    ("S14-1", "5", "RO", "Outro Senador", "Outro Senador", "30", "1", cpf(7)),
]
CANDIDATES_2018 = [
    ("1801", "6", "RO", "João da Mata Santos", "JOÃO DA MATA", "10", "2", CPF1),
    ("1802", "6", "RO", "Maria Oliveira Dias", "Maria Oliveira", "20", "4", CPF2),
    ("1809", "6", "RO", "Outra Pessoa", "Outra Pessoa", "30", "4", cpf(8)),
    ("2801", "6", "AC", "Pedro Souza Neto", "Pedro Souza", "30", "4", cpf(9)),  # other CPF
]
# (uf, tse municipality, cargo, round, sq, nominal votes)
VOTES_2014 = [
    ("RO", "19", "6", "1", "1001", "200"),
    ("RO", "19", "6", "1", "1001", "100"),  # second zone
    ("RO", "19", "6", "1", "1002", "100"),
    ("RO", "19", "6", "1", "1003", "50"),
    ("RO", "19", "6", "1", "1004", "50"),
    ("RO", "19", "6", "1", "1005", "20"),
    ("RO", "19", "5", "1", "S14-1", "999"),  # a senator
    ("RO", "19", "6", "2", "1001", "50"),  # a round that deputies do not have
    ("RO", "27", "6", "1", "1001", "100"),
    ("RO", "27", "6", "1", "1002", "200"),
    ("RO", "27", "6", "1", "1003", "10"),
    ("RO", "35", "6", "1", "1001", "40"),
    ("RO", "35", "6", "1", "1002", "10"),
    ("AC", "1015", "6", "1", "2001", "400"),
    ("AC", "1015", "6", "1", "2002", "100"),
    ("AC", "1058", "6", "1", "2001", "200"),
    ("AC", "1058", "6", "1", "2002", "50"),
    ("ZZ", "99999", "6", "1", "1001", "5"),  # votes abroad
]
# the valid column is smaller than the nominal one where they differ: it is the one used
VOTES_2018 = [
    ("RO", "19", "6", "1", "1801", "260", "250"),
    ("RO", "19", "6", "1", "1802", "150", "150"),
    ("RO", "19", "6", "1", "1809", "100", "100"),
    ("RO", "27", "6", "1", "1801", "120", "120"),
    ("RO", "27", "6", "1", "1802", "100", "100"),
    ("RO", "35", "6", "1", "1801", "30", "30"),
    ("AC", "1015", "6", "1", "2801", "5", "5"),
]

CGU_HEADER = [
    "Código da Emenda",
    "Código do Autor da Emenda",
    "Nome do Autor da Emenda",
    "Número da emenda",
    "Tipo de Emenda",
    "Ano/Mês",
    "Código do Favorecido",
    "Favorecido",
    "Natureza Jurídica",
    "Tipo Favorecido",
    "UF Favorecido",
    "Município Favorecido",
    "Valor Recebido",
]


def pay(code, author, kind, ym, uf, muni, value):
    return ["1", code, author, "1", kind, ym, *SENTINEL_FAVORECIDO, "x", "y", uf, muni, value]


def cgu_rows(pix=PIX):
    return [
        # João da Mata (elected, RO, party 10)
        pay("100", "João da Mata", IND, "2015/02", "RO", "ALTA FLORESTA D'OESTE", "1.000,50"),
        pay("100", "João da Mata", IND, "2016/09", "RO", "Alta Floresta d'Oeste", "2.000,00"),
        pay("100", "João da Mata", IND, "2016/10", "RO", "ALTA FLORESTA D'OESTE", "7.000,00"),
        pay("100", "João da Mata", pix, "2017/05", "RO", "ALTA FLORESTA D'OESTE", "500,00"),
        pay("100", "João da Mata", IND, "2017/06", "RO", "CABIXI", "100,00"),
        pay("100", "João da Mata", IND, "2017/07", "RO", "", "5,00"),  # a state recipient
        pay("100", "João da Mata", IND, "2018/09", "RO", "ALTA FLORESTA D'OESTE", "300,25"),
        pay("100", "João da Mata", IND, "2018/10", "RO", "ALTA FLORESTA D'OESTE", "9.999,00"),
        # Maria Oliveira (elected, RO, party 20)
        pay("200", "Maria Oliveira", IND, "2015/05", "RO", "ARIQUEMES", "50,00"),
        pay("200", "Maria Oliveira", IND, "2017/08", "RO", "ARIQUEMES", "70,00"),
        pay("200", "Maria Oliveira", IND, "2017/09", "AC", "ACRELANDIA", "15,00"),  # other state
        # Pedro Souza (elected, AC, party 30)
        pay("300", "Pedro Souza", IND, "2016/01", "AC", "ACRELANDIA", "10,00"),
        pay("300", "Pedro Souza", IND, "2018/02", "AC", "ASSIS BRASIL", "20,00"),
        # a senator, an ambiguous name, a substitute, an author with no candidacy
        pay("400", "Carlos Lima", IND, "2015/03", "RO", "ALTA FLORESTA D'OESTE", "999,00"),
        pay("500", "Ana Costa", IND, "2015/04", "RO", "ALTA FLORESTA D'OESTE", "888,00"),
        pay("600", "Lucas Rocha", IND, "2017/03", "RO", "ALTA FLORESTA D'OESTE", "1.234,56"),
        pay("700", "Zeca Tatu", IND, "2015/06", "RO", "ARIQUEMES", "11,00"),
        pay("700", "Zeca Tatu", pix, "2021/05", "RO", "ARIQUEMES", "30,00"),  # outside windows
        # not individual: only the file's first and last months
        pay("S/I", "", BANC, "2015/01", "RO", "ALTA FLORESTA D'OESTE", "5,00"),
        pay("S/I", "", BANC, "2026/09", "RO", "ALTA FLORESTA D'OESTE", "5,00"),
    ]


def municipalities():
    data = [
        (R1, TSE[R1], "RO", "Alta Floresta d'Oeste"),
        (R2, TSE[R2], "RO", "Ariquemes"),
        (R3, TSE[R3], "RO", "Cabixi"),
        (C1, TSE[C1], "AC", "Acrelândia"),
        (C2, TSE[C2], "AC", "Assis Brasil"),
        (C3, TSE[C3], "AC", "Brasiléia"),
    ]
    schema = {"cd_ibge": pl.Utf8, "cd_tse": pl.Utf8, "uf": pl.Utf8, "name_ibge": pl.Utf8}
    return rows(data, schema)


def population():
    data = [(2016, R1, 20000), (2016, R2, 100000), (2016, R3, 8000), (2016, C1, 12000)]
    data += [(2016, C2, 6000), (2015, R1, 1), (2017, R1, 2)]
    return rows(data, {"ano": pl.Int64, "id_municipio": pl.Utf8, "populacao": pl.Int64})


VOTE_SCHEMA = {
    "cd_cargo": pl.Utf8,
    "nr_turno": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "sq_candidato": pl.Utf8,
    "nr_zona": pl.Utf8,
    "qt_votos_nominais": pl.Int64,
    "qt_votos_nominais_validos": pl.Int64,
    "nm_tipo_destinacao_votos": pl.Utf8,
    "cd_ibge": pl.Utf8,
}
TURNOUT_SCHEMA = {
    "cd_cargo": pl.Utf8,
    "nr_turno": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "qt_total_votos_validos": pl.Int64,
}
ATTR_SCHEMA = {
    "ano_eleicao": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "sq_candidato": pl.Utf8,
    "nr_partido": pl.Utf8,
    "cd_genero": pl.Utf8,
    "dt_nascimento": pl.Date,
    "cd_grau_instrucao": pl.Utf8,
    "dt_eleicao": pl.Date,
}
BY_TSE = {v: k for k, v in TSE.items()}


def votes_2016():
    def c(ue, sq, n, el=100, turn=1, cargo="11", dest="Válido", valid=None):
        valid = n if valid is None else valid
        return (cargo, turn, el, ue, sq, "1", n, valid, dest, BY_TSE[ue])

    return rows(
        [
            c(TSE[R1], "m1", 500),
            c(TSE[R1], "m1", 9999, dest="Anulado sub judice"),  # annulled: not counted
            c(TSE[R1], "m2", 300),
            c(TSE[R1], "m3", 100),
            c(TSE[R2], "m4", 400),
            c(TSE[R2], "m6", 350),
            c(TSE[R2], "m5", 250),
            c(TSE[R2], "m4", 450, el=101, turn=2),  # the run-off
            c(TSE[R2], "m6", 500, el=101, turn=2),
            c(TSE[R3], "m7", 600),
            c(TSE[R3], "m8", 200),
            c(TSE[R3], "m7", 99999, el=150),  # supplementary election
            c(TSE[R3], "x1", 5000, cargo="13"),  # council
            c(TSE[C1], "m9", 700),
            c(TSE[C1], "m10", 100),
            c(TSE[C2], "m11", 400),
            c(TSE[C2], "m12", 300),
            c(TSE[C3], "m13", 100),
        ],
        VOTE_SCHEMA,
    )


def turnout_2016():
    data = [(TSE[R1], 900), (TSE[R2], 1000), (TSE[R3], 800), (TSE[C1], 800), (TSE[C2], 700)]
    out = [("11", 1, 100, ue, n) for ue, n in data] + [("11", 1, 100, TSE[C3], 100)]
    out += [("11", 2, 101, TSE[R2], 1000), ("13", 1, 100, TSE[R3], 7000)]
    return rows(out, TURNOUT_SCHEMA)


def votes_2012():
    def c(ue, sq, n):
        return ("11", 1, 200, ue, sq, "1", n, None, None, BY_TSE[ue])

    return rows(
        [
            c(TSE[R1], "a1", 450),
            c(TSE[R1], "a2", 300),
            c(TSE[R2], "a3", 500),
            c(TSE[R2], "a4", 400),
            c(TSE[R3], "a5", 600),
            c(TSE[R3], "a6", 100),
            c(TSE[C1], "a7", 700),
            c(TSE[C1], "a8", 100),
            c(TSE[C2], "a9", 400),
            c(TSE[C2], "a10", 300),
        ],
        VOTE_SCHEMA,
    )


def turnout_2012():
    data = [(TSE[R1], 750), (TSE[R2], 900), (TSE[R3], 700), (TSE[C1], 800), (TSE[C2], 700)]
    return rows([("11", 1, 200, ue, n) for ue, n in data], TURNOUT_SCHEMA)


def attributes(higher="8"):
    d16, d12 = date(2016, 10, 2), date(2012, 10, 7)

    def c(year, el, ue, sq, party, gender, born, edu, on):
        return (year, el, TSE[ue], sq, party, gender, born, edu, on)

    data = [
        c(2016, 100, R1, "m1", "10", "2", date(1980, 10, 2), "6", d16),  # 36 on the day
        c(2016, 100, R1, "m2", "20", "4", date(1990, 12, 25), higher, d16),
        c(2016, 100, R1, "m3", "30", "2", date(1970, 1, 1), "4", d16),
        c(2016, 100, R2, "m4", "10", "2", date(1975, 10, 3), higher, d16),  # 40, birthday after
        c(2016, 100, R2, "m5", "30", "2", date(1970, 1, 1), "4", d16),
        c(2016, 100, R2, "m6", "20", "2", date(1960, 5, 5), "6", d16),
        c(2016, 100, R3, "m7", "30", "2", date(1970, 1, 1), "6", d16),
        c(2016, 100, R3, "m8", "10", "4", date(1985, 3, 3), "6", d16),
        c(2016, 100, C1, "m9", "30", "2", date(1970, 1, 1), "6", d16),
        c(2016, 100, C1, "m10", "10", "2", date(1970, 1, 1), "6", d16),
        c(2016, 100, C2, "m11", "20", "2", date(1970, 1, 1), "6", d16),
        c(2016, 100, C2, "m12", "30", "2", None, "6", d16),  # no birth date
        c(2016, 100, C3, "m13", "30", "2", date(1970, 1, 1), "6", d16),
        c(2012, 200, R1, "a1", "10", "2", date(1970, 1, 1), higher, d12),
        c(2012, 200, R1, "a2", "20", "4", date(1970, 1, 1), "6", d12),
        c(2012, 200, R2, "a3", "20", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, R2, "a4", "10", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, R3, "a5", "30", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, R3, "a6", "10", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, C1, "a7", "30", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, C1, "a8", "20", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, C2, "a9", "20", "2", date(1970, 1, 1), "6", d12),
        c(2012, 200, C2, "a10", "30", "2", date(1970, 1, 1), "6", d12),
    ]
    return rows(data, ATTR_SCHEMA)


# --- Staging in a fake store


def parquet(frame):
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def entry(path, blob):
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def cgu_zip(data, encoding="utf-8", header=None):
    body = csv_bytes(header or CGU_HEADER, data, encoding)
    other = csv_bytes(["a"], [["b"]], encoding)
    return make_zip(
        {
            "EmendasParlamentares.csv": other,
            "EmendasParlamentares_PorFavorecido.csv": body,
            "EmendasParlamentares_Convenios.csv": other,
        }
    )


def stage(store, *, cgu=None, attrs=None, lists=None):
    """Put every input in the store; return the six manifests."""
    first, second = lists or (f"code_ibge\n{R1}\n", f"code_ibge\n{C1}\n")
    store.create(EXPLORE_LIST, first.encode("utf-8"))
    store.create(EXPLORE_LIST_NON_AMAZON, second.encode("utf-8"))

    def put(path, blob):
        store.create(path, blob)
        return entry(path, blob)

    def manifest(name, prefix, files):
        return {"dataset": name, "gcs_prefix": prefix, "files": files}

    gp = "data/raw/tse/general/2026-11-15/"
    general = [
        put(gp + "consulta_cand_2010.zip", cand_zip(2010, CANDIDATES_2010)),
        put(gp + "consulta_cand_2014.zip", cand_zip(2014, CANDIDATES_2014)),
        put(gp + "consulta_cand_2018.zip", cand_zip(2018, CANDIDATES_2018)),
        put(gp + "votacao_candidato_munzona_2014.zip", votes_zip(2014, VOTES_2014)),
        put(gp + "votacao_candidato_munzona_2018.zip", votes_zip(2018, VOTES_2018, valid=True)),
    ]
    cp = "data/raw/cgu/amendments/2026-11-15/"
    blob = cgu if cgu is not None else cgu_zip(cgu_rows())
    rp = "data/derived/tse_results/r1/"
    results = [
        put(rp + "candidate_votes_2016.parquet", parquet(votes_2016())),
        put(rp + "turnout_2016.parquet", parquet(turnout_2016())),
        put(rp + "candidate_votes_2012.parquet", parquet(votes_2012())),
        put(rp + "turnout_2012.parquet", parquet(turnout_2012())),
    ]
    tp = "data/derived/tse_candidates/c1/"
    mp = "data/derived/municipalities/m1/"
    pp = "data/raw/ibge/population_annual/2026-11-15/"
    frame = attributes() if attrs is None else attrs
    return (
        manifest("tse_general", gp, general),
        manifest("cgu_amendments", cp, [put(cp + "EmendasParlamentares.zip", blob)]),
        manifest("tse_results", rp, results),
        manifest("tse_candidates", tp, [put(tp + "candidates.parquet", parquet(frame))]),
        manifest(
            "municipalities", mp, [put(mp + "municipalities.parquet", parquet(municipalities()))]
        ),
        manifest(
            "ibge_population_annual",
            pp,
            [put(pp + "ibge_population_annual.parquet", parquet(population()))],
        ),
    )


def run(store, manifests, tmp_path, **kwargs):
    options = {"cycles": ("A",), "min_rows": 1, "max_rows": 100}
    options.update(kwargs)
    tmp = tmp_path / "work"
    tmp.mkdir(parents=True, exist_ok=True)
    return build(
        store,
        *manifests,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=tmp,
        code_commit="abc",
        created_at="2026-11-15T00:00:00+00:00",
        **options,
    )


def read(store, path):
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


@pytest.fixture
def built(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    before = set(store.list(""))
    manifest = run(store, manifests, tmp_path)
    return store, manifest, before


def panel_files(manifest, name="panel_A.parquet"):
    derived = [f["path"] for f in manifest["files"] if f["path"].endswith("/" + name)]
    sealed = [f["path"] for f in manifest["sealed_files"] if f["path"].endswith("/" + name)]
    return derived, sealed


def whole_panel(store, manifest):
    derived, sealed = panel_files(manifest)
    return pl.concat([read(store, p) for p in derived + sealed])


def row(panel, deputy, cd_ibge):
    found = panel.filter((pl.col("deputy") == deputy) & (pl.col("cd_ibge") == cd_ibge))
    assert found.height == 1
    return found.to_dicts()[0]


# --- 1. The rows and their values


def test_rows_are_the_deputies_and_municipalities_where_the_party_had_a_finalist(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    got = sorted(zip(panel["deputy"], panel["cd_ibge"], strict=True))
    expected = [("1001", m) for m in (R1, R2, R3)] + [("1003", m) for m in (R1, R2, R3)]
    expected += [("1002", R1), ("1002", R2), ("2001", C1), ("2001", C2)]
    assert got == sorted(expected)  # the senator, the ambiguous and the unmatched have none
    assert panel.schema == pl.Schema(ap.SCHEMA)


def test_race_columns(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    first = row(panel, "1001", R1)  # party 10 finalist, 500 against 300 of 900 valid
    assert (first["cycle"], first["m"], first["t0"], first["t1"]) == ("A", 2016, 2014, 2018)
    assert (first["uf"], first["deputy_party"], first["deputy_elected"]) == ("RO", "10", True)
    assert (first["round"], first["n_mayor_cands"], first["population_m"]) == (1, 3, 20000)
    assert first["margin"] == pytest.approx(200 / 900) and first["win"] is True
    assert (first["fin_female"], first["fin_age"], first["fin_higher_ed"]) == (False, 36, False)
    assert first["party_held_mayor"] is True
    other = row(panel, "1002", R1)  # party 20 finalist: the same race seen from the other side
    assert other["margin"] == pytest.approx(-200 / 900) and other["win"] is False
    assert (other["fin_female"], other["fin_age"], other["fin_higher_ed"]) == (True, 25, True)
    assert other["party_held_mayor"] is False


def test_run_off_is_the_deciding_round(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    ten, twenty = row(panel, "1001", R2), row(panel, "1002", R2)
    assert (ten["round"], ten["n_mayor_cands"]) == (2, 3)  # first-round candidates
    assert ten["margin"] == pytest.approx(-50 / 1000) and twenty["margin"] == pytest.approx(0.05)
    assert ten["win"] is False and twenty["win"] is True
    assert ten["fin_age"] == 40  # born 1975-10-03, election 2016-10-02
    assert (ten["party_held_mayor"], twenty["party_held_mayor"]) == (False, True)
    assert panel.filter(pl.col("round") == 2).height == 3  # R2 only: two of party 10, one of 20


def test_missing_birth_date_is_a_null_age(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    assert row(panel, "2001", C2)["fin_age"] is None
    assert row(panel, "2001", C2)["margin"] == pytest.approx(-100 / 700)


def test_payments_by_window(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    got = row(panel, "1001", R1)
    # pre: 2015-02 and 2016-09 (the last month of the window); 2016-10 is outside
    assert (got["amend_pre_total"], got["n_pay_pre"], got["amend_pre_pix"]) == (3000.5, 2, 0.0)
    # post: 2017-05 (Pix) and 2018-09 (the last month); 2018-10 is outside
    assert got["amend_post_total"] == pytest.approx(800.25)
    assert (got["n_pay_post"], got["amend_post_pix"]) == (2, 500.0)
    cabixi = row(panel, "1001", R3)
    assert (cabixi["amend_post_total"], cabixi["n_pay_post"]) == (100.0, 1)
    none = row(panel, "1001", R2)
    assert none["amend_pre_total"] == 0 and none["n_pay_pre"] == 0 and none["n_pay_post"] == 0
    assert (
        row(panel, "1002", R2)["amend_pre_total"] == 50 and row(panel, "1002", R2)["n_pay_pre"] == 1
    )
    assert row(panel, "1002", R2)["amend_post_total"] == 70
    # a payment to another state's municipality is in no row
    assert panel.filter(pl.col("deputy") == "1002")["amend_post_total"].sum() == 70
    assert row(panel, "2001", C1)["amend_pre_total"] == 10
    assert row(panel, "2001", C2)["amend_post_total"] == 20
    assert panel["amend_post_pix"].sum() == 500  # one Pix payment in the windows


def test_substitute_who_served_has_rows_and_brazilian_decimals(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    got = row(panel, "1003", R1)
    assert got["deputy_elected"] is False
    assert got["amend_post_total"] == pytest.approx(1234.56) and got["n_pay_post"] == 1
    assert row(panel, "1003", R3)["votes_t0"] == 0  # no votes there: 0, not null


def test_votes_at_t0_and_t1(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    got = row(panel, "1001", R1)
    assert (got["votes_t0"], got["valid_t0"]) == (300, 520)  # abroad votes are not counted
    assert got["share_t0"] == pytest.approx(300 / 520)
    assert got["ran_t1"] is True
    assert (got["votes_t1"], got["valid_t1"]) == (250, 500)  # the valid column, not 260
    assert got["share_t1"] == pytest.approx(0.5)
    assert got["d_share"] == pytest.approx(0.5 - 300 / 520)
    second = row(panel, "1002", R2)
    assert (second["votes_t0"], second["valid_t0"]) == (200, 310)
    assert (second["votes_t1"], second["valid_t1"]) == (100, 220)


def test_a_deputy_who_did_not_run_at_t1(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    for deputy, municipality in (("2001", C1), ("1003", R1)):  # no candidacy; unlinkable CPF
        got = row(panel, deputy, municipality)
        assert got["ran_t1"] is False
        assert got["votes_t1"] is None and got["valid_t1"] is None
        assert got["share_t1"] is None and got["d_share"] is None
        assert got["share_t0"] is not None


# --- 2. The author link


def test_author_link_counts(built):
    store, manifest, _ = built
    link = read(
        store, next(f["path"] for f in manifest["files"] if f["path"].endswith("link.parquet"))
    )
    assert link.columns == list(ap.LINK_SCHEMA)
    assert link.to_dicts() == [
        {"cycle": "A", "authors": 7, "deputies": 4, "senators": 1, "ambiguous": 1, "unmatched": 2}
    ]
    note = next(n for n in manifest["notes"].split("; ") if n.startswith("A:"))
    assert "authors=7, deputy_authors=4, senator_authors=1, ambiguous_authors=1" in note
    assert "unmatched_authors=2, unlinked_cpfs=1" in note  # the substitute's short CPF
    assert "party_without_mayor_cands=0" in note
    assert "vote_rows_abroad=1" in note


def test_manifest_notes(built):
    _, manifest, _ = built
    notes = manifest["notes"]
    assert "dropped_recipient_rows_no_municipality=2017:1" in notes
    assert "dropped_recipient_rows_unmatched=none" in notes
    assert "placeholder_recipient_rows=none" in notes
    assert "top_unmatched_recipients=none" in notes
    assert "first_payment_month=2015-01, last=2026-09" in notes
    note = next(n for n in notes.split("; ") if n.startswith("A:"))
    assert note.startswith("A: rows=4, deputies=4")  # exploration half: R1 (3 deputies) and C1
    floored = "amend_pre_total:0,amend_pre_pix:0,amend_post_total:0,amend_post_pix:0"
    assert f"A_floored_to_zero={floored}" in notes.split("; ")
    assert "negative_payment_rows=none" in notes.split("; ")
    assert "negative_payment_value_brl=none" in notes.split("; ")


def test_manifest_notes_carry_placeholders_and_top_unmatched(tmp_path, monkeypatch):
    """Two placeholders and a `Sem informação` with a real UF, in 2017; the 2% stop is lifted."""
    loose = functools.partial(ap.match_recipients, max_unmatched=1.0)
    monkeypatch.setattr(ap, "match_recipients", loose)
    data = cgu_rows() + [
        pay("100", "João da Mata", IND, "2017/07", "", "Sem informação", "1.000,00"),
        pay("100", "João da Mata", IND, "2017/07", "-1", "SEM INFORMAÇÃO", "500,00"),
        pay("100", "João da Mata", IND, "2017/07", "SP", "Sem informação", "1,00"),
    ]
    store = MemoryStore()
    manifests = stage(store, cgu=cgu_zip(data))
    notes = run(store, manifests, tmp_path)["notes"].split("; ")
    assert "dropped_recipient_rows_no_municipality=2017:3" in notes  # the state row too
    assert "dropped_recipient_rows_unmatched=2017:1" in notes
    assert "placeholder_recipient_rows=2017:2" in notes
    assert "placeholder_recipient_value_brl=2017:1500.00" in notes
    total = 500 + 100 + 5 + 70 + 15 + 1234.56 + 1500 + 1  # every 2017 individual payment
    assert f"placeholder_recipient_value_share=2017:{1500 / total:.4f}" in notes
    assert "top_unmatched_recipients_2017=SP/SEM INFORMACAO:1" in notes
    assert not any(sentinel in n for sentinel in SENTINEL_FAVORECIDO for n in notes)


# --- Negative payment rows (refunds and reversals)


def with_negatives():
    """João da Mata: a reversal of 50 in R1's pre window (total 3000.50 -> 2950.50), and one
    of 300 in Cabixi's post window, against a payment of 100 (net -200)."""
    return cgu_rows() + [
        pay("100", "João da Mata", IND, "2016/03", "RO", "ALTA FLORESTA D'OESTE", "-50,00"),
        pay("100", "João da Mata", IND, "2018/01", "RO", "CABIXI", "-300,00"),
    ]


@pytest.fixture
def built_negative(tmp_path):
    store = MemoryStore()
    manifests = stage(store, cgu=cgu_zip(with_negatives()))
    return store, run(store, manifests, tmp_path)


def test_a_negative_row_reduces_a_positive_total(built_negative):
    store, manifest = built_negative
    got = row(whole_panel(store, manifest), "1001", R1)
    assert got["amend_pre_total"] == pytest.approx(2950.5)
    assert got["n_pay_pre"] == 3  # the reversal is a payment row too


def test_a_row_netting_below_zero_becomes_zero_and_is_counted(built_negative):
    store, manifest = built_negative
    cabixi = row(whole_panel(store, manifest), "1001", R3)
    assert cabixi["amend_post_total"] == 0.0 and cabixi["n_pay_post"] == 2
    floored = "amend_pre_total:0,amend_pre_pix:0,amend_post_total:1,amend_post_pix:0"
    assert f"A_floored_to_zero={floored}" in manifest["notes"].split("; ")


def test_the_notes_carry_the_negative_rows_per_year(built_negative):
    _, manifest = built_negative
    notes = manifest["notes"].split("; ")
    assert "negative_payment_rows=2016:1,2018:1" in notes
    assert "negative_payment_value_brl=2016:-50.00,2018:-300.00" in notes


def test_floor_payments_counts_per_column():
    panel = pl.DataFrame(
        {
            "amend_pre_total": [-5.0, 0.0, 10.0],
            "amend_pre_pix": [-1.0, -2.0, 0.0],
            "amend_post_total": [3.0, 0.0, 1.0],
            "amend_post_pix": [0.0, 0.0, 0.0],
        }
    )
    floored, counts = ap.floor_payments(panel)
    assert counts == {
        "amend_pre_total": 1,
        "amend_pre_pix": 2,
        "amend_post_total": 0,
        "amend_post_pix": 0,
    }
    assert floored["amend_pre_total"].to_list() == [0.0, 0.0, 10.0]
    assert floored["amend_pre_pix"].to_list() == [0.0, 0.0, 0.0]
    assert floored["amend_post_total"].to_list() == [3.0, 0.0, 1.0]


def test_a_senator_is_not_a_deputy_and_a_name_needs_one_candidacy(built):
    store, manifest, _ = built
    panel = whole_panel(store, manifest)
    # 999 (senator) and 888 (ambiguous) are paid to R1 but belong to no deputy row
    assert row(panel, "1001", R1)["amend_pre_total"] == 3000.5
    assert panel["amend_pre_total"].sum() == pytest.approx(3000.5 + 50 + 10)


# --- 3. No identifier in any output


def test_no_identifier_in_any_output(built):
    store, manifest, before = built
    paths = [f["path"] for f in manifest["files"] + manifest["sealed_files"]]
    forbidden = [*NAMES, *[s.lower() for s in SENTINEL_FAVORECIDO], CPF1, CPF2, CPF3]
    forbidden += ["cpf", "titulo", "favorecido", "nome", "000000000001"]
    for path in paths:
        frame = read(store, path)
        for column in frame.columns:
            assert not any(word in column.lower() for word in ("cpf", "titulo", "nome", "name"))
            assert "favorecido" not in column.lower()
            assert column not in ("author", "author_code", "code", "name")  # `authors` is a count
        for column, dtype in frame.schema.items():
            if dtype == pl.Utf8:
                for value in frame[column].drop_nulls().unique().to_list():
                    assert not any(word in value.lower() for word in forbidden), (path, column)
                    assert value not in CODES, (path, column)  # an author code
    text = json.dumps(manifest).lower()
    assert not any(word in text for word in [*NAMES, *[s.lower() for s in SENTINEL_FAVORECIDO]])
    assert CPF1 not in text and CPF2 not in text and CPF3 not in text
    new = set(store.list("")) - before
    assert {p for p in new if not p.startswith(("data/derived/", "sealed/"))} == set()


# --- 4. The split


def test_exploration_half_in_derived_and_the_rest_only_in_sealed(built):
    store, manifest, before = built
    derived, sealed = panel_files(manifest)
    assert len(derived) == 1 and len(sealed) == 1
    in_derived, in_sealed = read(store, derived[0]), read(store, sealed[0])
    assert set(in_derived["cd_ibge"]) == {R1, C1} and in_derived.height == 4
    assert set(in_sealed["cd_ibge"]) == {R2, R3, C2} and in_sealed.height == 6
    assert derived[0].startswith(DERIVED) and sealed[0].startswith(SEALED)
    assert not any(f["path"].startswith(SEALED) for f in manifest["files"])
    assert not any(f["path"].startswith(DERIVED) for f in manifest["sealed_files"])
    link_paths = [f["path"] for f in manifest["files"] + manifest["sealed_files"]]
    links = [p for p in link_paths if p.endswith("author_link.parquet")]
    assert len(links) == 1 and links[0].startswith(DERIVED)
    assert not any(p.startswith(SEALED) and "link" in p for p in store.list(SEALED))
    assert manifest["gcs_prefix"].startswith(DERIVED)
    assert {p for p in store.list("") if p not in before} >= set(links)


def test_a_second_run_is_unchanged(built, tmp_path):
    store, manifest, _ = built
    write_manifest(manifest, store, tmp_path / "manifest.json")
    again = run(store, stage_manifests(store), tmp_path)
    assert again["status"] == "unchanged"


def stage_manifests(store):
    """The manifests of the inputs already in `store` (the same bytes, so the same hash)."""
    inputs = {}
    for path in store.list("data/"):
        inputs[path] = store.read_bytes(path)
    gp, cp = "data/raw/tse/general/2026-11-15/", "data/raw/cgu/amendments/2026-11-15/"
    rp, tp = "data/derived/tse_results/r1/", "data/derived/tse_candidates/c1/"
    mp, pp = "data/derived/municipalities/m1/", "data/raw/ibge/population_annual/2026-11-15/"

    def files(prefix):
        return [entry(p, b) for p, b in inputs.items() if p.startswith(prefix)]

    def manifest(name, prefix):
        return {"dataset": name, "gcs_prefix": prefix, "files": files(prefix)}

    return (
        manifest("tse_general", gp),
        manifest("cgu_amendments", cp),
        manifest("tse_results", rp),
        manifest("tse_candidates", tp),
        manifest("municipalities", mp),
        manifest("ibge_population_annual", pp),
    )


def test_a_code_change_in_any_module_changes_the_path():
    files = [{"sha256": "a" * 64}]
    base = ap.input_hash(files, ["s1", "s2"], ("A",))
    sources = ap.code_sources()
    assert len(sources) == len(ap.CODE_MODULES)
    for i in range(len(sources)):
        changed = list(sources)
        changed[i] += "\n# changed"
        assert ap.input_hash(files, ["s1", "s2"], ("A",), code=changed) != base
    assert ap.input_hash(files, ["s1", "s2"], ("A", "B")) != base
    assert ap.input_hash(files, ["s1", "s3"], ("A",)) != base
    assert ap.input_hash([{"sha256": "b" * 64}], ["s1", "s2"], ("A",)) != base


def test_code_modules_list_this_file_and_every_data_module_it_imports():
    from terrain import explore
    from terrain.builds import cell_outcomes, place_outcomes, polling_place_tenure

    modules = set(ap.CODE_MODULES)
    expected = {ap.__file__, explore.__file__, place_outcomes.__file__}
    expected |= {cell_outcomes.__file__, polling_place_tenure.__file__}
    assert modules == {Path(p) for p in expected}


# --- 5. The stop rules


def panel_a(built):
    store, manifest, _ = built
    return whole_panel(store, manifest)


def test_check_panel_passes_on_the_world(built):
    ap.check_panel({"A": panel_a(built)}, min_rows=1, max_rows=100)


def test_stop_on_a_duplicate_key(built):
    panel = panel_a(built)
    with pytest.raises(BuildError, match="appears twice"):
        ap.check_panel({"A": pl.concat([panel, panel.head(1)])}, min_rows=1, max_rows=100)


def test_stop_on_a_margin_outside_one_or_a_wrong_win(built):
    panel = panel_a(built)
    with pytest.raises(BuildError, match="margin"):
        ap.check_panel({"A": panel.with_columns(pl.lit(1.5).alias("margin"))}, min_rows=1)
    with pytest.raises(BuildError, match="wrong win"):
        ap.check_panel({"A": panel.with_columns(pl.lit(True).alias("win"))}, min_rows=1)


@pytest.mark.parametrize("column", ["share_t0", "share_t1"])
def test_stop_on_a_share_outside_zero_one(built, column):
    panel = panel_a(built).with_columns(pl.lit(1.5).alias(column))
    with pytest.raises(BuildError, match=f"{column} outside"):
        ap.check_panel({"A": panel}, min_rows=1, max_rows=100)


def test_stop_on_a_negative_payment(built):
    panel = panel_a(built).with_columns(pl.lit(-1.0).alias("amend_post_total"))
    with pytest.raises(BuildError, match="below 0"):
        ap.check_panel({"A": panel}, min_rows=1, max_rows=100)


def test_stop_on_row_bounds(built):
    panel = panel_a(built)
    with pytest.raises(BuildError, match="rows, outside"):
        ap.check_panel({"A": panel}, min_rows=11, max_rows=100)
    with pytest.raises(BuildError, match="rows, outside"):
        ap.check_panel({"A": panel}, min_rows=1, max_rows=9)
    with pytest.raises(BuildError, match="rows, outside"):
        ap.check_panel({"A": panel})  # the defaults: 5,000 to 300,000


def test_the_build_stops_on_row_bounds(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    with pytest.raises(BuildError, match="rows, outside"):
        run(store, manifests, tmp_path, min_rows=11)
    assert not [p for p in store.list("") if p.startswith((DERIVED, SEALED))]


def test_stop_on_the_payment_month_range():
    good = {"first": 201501, "last": 202609, "pix_from": 3}
    ap.check_payment_stats(good)
    with pytest.raises(BuildError, match="earliest payment month"):
        ap.check_payment_stats({**good, "first": 201502})
    with pytest.raises(BuildError, match="latest payment month"):
        ap.check_payment_stats({**good, "last": 202608})
    with pytest.raises(BuildError, match="no payment month"):
        ap.check_payment_stats({**good, "first": None, "last": None})


def test_the_build_stops_on_a_late_first_month(tmp_path):
    store = MemoryStore()
    data = [r for r in cgu_rows() if r[5] != "2015/01"]
    manifests = stage(store, cgu=cgu_zip(data))
    with pytest.raises(BuildError, match="earliest payment month"):
        run(store, manifests, tmp_path)


def test_stop_when_there_is_no_pix_from_2020(tmp_path):
    store = MemoryStore()
    manifests = stage(store, cgu=cgu_zip(cgu_rows(pix=IND)))
    with pytest.raises(BuildError, match="no individual Pix payment"):
        run(store, manifests, tmp_path)


def test_a_pix_before_2020_does_not_count(tmp_path):
    data = [r for r in cgu_rows() if r[5] != "2021/05"]  # keeps the 2017 Pix only
    store = MemoryStore()
    manifests = stage(store, cgu=cgu_zip(data))
    with pytest.raises(BuildError, match="no individual Pix payment"):
        run(store, manifests, tmp_path)


def recipients(n_ok, n_bad, year=2017):
    """`n_ok` payment rows to Ariquemes and `n_bad` to a place that is not a municipality."""
    n = n_ok + n_bad
    frame = pl.DataFrame(
        {
            "muni": ["Ariquemes"] * n_ok + ["Lugar Nenhum"] * n_bad,
            "uf": ["RO"] * n,
            "ym": [year * 100 + 3] * n,
            "value": [1.0] * n,
        }
    )
    return frame, municipalities()


def test_recipient_matching_stops_above_two_percent_in_a_year():
    frame, munis = recipients(97, 3)
    with pytest.raises(BuildError, match="2017: 3 of 100 recipient rows"):
        ap.match_recipients(frame, munis)
    out, counts = ap.match_recipients(*recipients(98, 2))
    assert counts["unmatched"] == {2017: 2} and counts["no_municipality"] == {}
    assert out.filter(pl.col("cd_ibge").is_null()).height == 2
    assert out.filter(pl.col("cd_ibge") == R2).height == 98


def test_recipient_matching_is_per_year():
    a, munis = recipients(97, 3, year=2017)
    b, _ = recipients(100, 0, year=2018)
    with pytest.raises(BuildError, match="2017"):
        ap.match_recipients(pl.concat([a, b]), munis)


def test_empty_municipalities_are_counted_not_matched():
    frame = pl.DataFrame(
        {"muni": ["", None, "Ariquemes"], "uf": ["RO"] * 3, "ym": [201703] * 3, "value": [1.0] * 3}
    )
    out, counts = ap.match_recipients(frame, municipalities())
    assert counts["no_municipality"] == {2017: 2} and counts["unmatched"] == {}
    assert counts["placeholder"] == {} and counts["top_unmatched"] == {}
    assert out.sort("cd_ibge", nulls_last=True)["cd_ibge"].to_list() == [R2, None, None]


def placeholders(ufs, n_ok, year=2017, value=1.0):
    """`n_ok` rows to Ariquemes (value 1) and one `Sem informação` row per UF in `ufs`."""
    n = len(ufs)
    return pl.DataFrame(
        {
            "muni": ["Ariquemes"] * n_ok + [" Sem informação "] * n,
            "uf": ["RO"] * n_ok + list(ufs),
            "ym": [year * 100 + 3] * (n_ok + n),
            "value": [1.0] * n_ok + [value] * n,
        }
    )


def test_cgu_placeholders_are_no_municipality_not_unmatched():
    frame = placeholders(["", " -1 ", None], 9, value=10.0)
    out, counts = ap.match_recipients(frame, municipalities(), max_unmatched=0.0)
    assert counts["no_municipality"] == {2017: 3} and counts["unmatched"] == {}
    assert counts["placeholder"] == {2017: 3}
    assert counts["placeholder_value"] == {2017: 30.0}
    assert counts["placeholder_share"] == {2017: pytest.approx(30.0 / 39.0)}
    assert out.filter(pl.col("cd_ibge").is_null()).height == 3
    assert "placeholder" not in out.columns


def test_sem_informacao_with_a_real_uf_is_unmatched():
    frame = placeholders(["SP"], 98)
    out, counts = ap.match_recipients(frame, municipalities())
    assert counts["unmatched"] == {2017: 1} and counts["no_municipality"] == {}
    assert counts["placeholder"] == {}
    assert counts["top_unmatched"] == {2017: [("SP", "SEM INFORMACAO", 1)]}
    with pytest.raises(BuildError, match="2017: 1 of 49 recipient rows"):
        ap.match_recipients(placeholders(["SP"], 48), municipalities())


def test_placeholders_do_not_hide_real_unmatched_names():
    frame, munis = recipients(97, 3)
    frame = pl.concat([frame, placeholders(["", "-1"] * 50, 0)])
    with pytest.raises(BuildError, match="2017: 3 of 100 recipient rows"):
        ap.match_recipients(frame, munis)


def test_top_unmatched_pairs_are_the_ten_most_frequent_per_year():
    names = [f"Lugar {chr(65 + i)}" for i in range(12)]
    muni = [n for i, n in enumerate(names) for _ in range(i + 1)]  # Lugar L most frequent
    frame = pl.DataFrame(
        {"muni": muni, "uf": ["RO"] * len(muni), "ym": [201703] * len(muni)},
    ).with_columns(pl.lit(1.0).alias("value"))
    _, counts = ap.match_recipients(frame, municipalities(), max_unmatched=1.0)
    top = counts["top_unmatched"][2017]
    assert len(top) == ap.TOP_UNMATCHED
    assert top[0] == ("RO", "LUGAR L", 12) and top[-1] == ("RO", "LUGAR C", 3)


def test_two_municipalities_with_one_name_stop_the_build():
    munis = pl.concat(
        [municipalities(), municipalities().head(1).with_columns(pl.lit("9").alias("cd_ibge"))]
    )
    frame = pl.DataFrame({"muni": ["Ariquemes"], "uf": ["RO"], "ym": [201703], "value": [1.0]})
    with pytest.raises(BuildError, match="share a state"):
        ap.match_recipients(frame, munis)


def test_read_cgu_accepts_utf8_and_latin1(tmp_path):
    for encoding in ("utf-8", "latin-1"):
        path = tmp_path / f"{encoding}.zip"
        path.write_bytes(cgu_zip(cgu_rows(), encoding=encoding))
        frame = ap.read_cgu(path)
        assert frame.height == len(cgu_rows())
        assert "João da Mata" in frame["author"].to_list()  # decoded, not mangled
        assert set(frame.columns) == set(ap.CGU_COLUMNS)  # no favorecido column is read
    body = b"\xef\xbb\xbf" + csv_bytes(CGU_HEADER, cgu_rows(), "utf-8")  # with a byte-order mark
    bom = tmp_path / "bom.zip"
    bom.write_bytes(make_zip({ap.CGU_MEMBER: body}))
    assert ap.read_cgu(bom).height == len(cgu_rows())


def test_stop_when_no_encoding_gives_the_header(tmp_path):
    path = tmp_path / "bad.zip"
    path.write_bytes(
        cgu_zip(cgu_rows(), header=[h.replace("Município", "Cidade") for h in CGU_HEADER])
    )
    with pytest.raises(BuildError, match="no encoding"):
        ap.read_cgu(path)
    missing = tmp_path / "missing.zip"
    missing.write_bytes(make_zip({"Other.csv": b"a"}))
    with pytest.raises(BuildError, match="member"):
        ap.read_cgu(missing)


def raw_payments(months, kind=IND, value="1,00"):
    return pl.DataFrame(
        {
            "type": [kind] * len(months),
            "code": ["1"] * len(months),
            "author": ["x"] * len(months),
            "ym": months,
            "uf": ["RO"] * len(months),
            "muni": ["Ariquemes"] * len(months),
            "value": [value] * len(months),
        }
    )


@pytest.mark.parametrize("text", ["2016/03", "03/2016", "201603", " 2016/03 "])
def test_payment_months_in_three_formats(text):
    rows_, stats = ap.parse_payments(raw_payments([text]))
    assert rows_["ym"].to_list() == [201603] and stats["first"] == stats["last"] == 201603


@pytest.mark.parametrize("text", ["2016-03", "2016/13", "March 2016", "16/03", "2016/00"])
def test_stop_on_a_month_in_no_format(text):
    with pytest.raises(BuildError, match="Ano/Mês"):
        ap.parse_payments(raw_payments(["2016/03", text]))


def test_a_row_without_a_month_is_dropped_and_counted():
    rows_, stats = ap.parse_payments(raw_payments(["2016/03", "", None]))
    assert rows_.height == 1 and stats["no_month"] == 2


def test_brazilian_decimals_and_individual_types():
    frame = pl.concat(
        [
            raw_payments(["2016/03"], value="1.234,56"),
            raw_payments(["2016/04"], value="R$ 10,5"),
            raw_payments(["2016/05"], value=""),
            raw_payments(["2016/06"], kind=BANC, value="not a number"),  # not read
            raw_payments(["2016/07"], kind="EMENDA INDIVIDUAL - TRANSFERENCIAS ESPECIAIS"),
        ]
    )
    out, stats = ap.parse_payments(frame)
    assert out["value"].to_list() == [1234.56, 10.5, 0.0, 1.0]
    assert out["pix"].to_list() == [False, False, False, True]
    assert stats["last"] == 201607
    with pytest.raises(BuildError, match="not a number"):
        ap.parse_payments(raw_payments(["2016/03"], value="abc"))


def test_the_type_rules():
    assert ap.is_individual(ap.normalise_type(IND)) and ap.is_individual(ap.normalise_type(PIX))
    assert not ap.is_individual(ap.normalise_type(BANC))
    assert ap.is_pix(ap.normalise_type(PIX)) and not ap.is_pix(ap.normalise_type(IND))
    assert ap.normalise_name("  João  d'Ávila-Ñu ") == "JOAO DAVILANU"  # letters and spaces only
    assert ap.normalise_name(None) == ""


def test_stop_when_no_mayoral_candidate_has_code_4_or_8(tmp_path):
    for column, value, text in (
        ("cd_grau_instrucao", "6", "education code 8"),
        ("cd_genero", "2", "gender code 4"),
    ):
        store = MemoryStore()
        frame = attributes().with_columns(pl.lit(value).alias(column))
        manifests = stage(store, attrs=frame)
        with pytest.raises(BuildError, match=text):
            run(store, manifests, tmp_path / column)


def test_a_missing_input_column_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store, attrs=attributes().drop("cd_genero"))
    with pytest.raises(BuildError, match="lacks a column"):
        run(store, manifests, tmp_path)


def test_a_wrong_sha_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    manifests[1]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="does not match"):
        run(store, manifests, tmp_path)
