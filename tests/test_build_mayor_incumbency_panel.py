"""The mayoral incumbency panel on a synthetic world: elections 2016 and 2020, with 2012 and 2024.

Two states (RO, AC), six municipalities. R1 and C1 are in the exploration half; the rest go to
sealed. The world has a run-off (R2, 2016), a merger between two elections (PHS, 31, into
Podemos, 19, in 2019; DEM, 25, into União Brasil, 44, in 2022), a federation at 2024 (13 with
65), a finalist who won four years earlier (no term left), an incumbent re-elected, a race
whose second finalist has no party (C3, 2020), a municipality with one candidate (C3, 2016)
and one with no election four years later (C2). Every identifier and value is made up here.
"""

import csv
import hashlib
import io
import json
import math
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import amendments_panel as ap
from terrain.builds import mayor_incumbency_panel as mp
from terrain.builds.mayor_incumbency_panel import BuildError, build
from terrain.explore import EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/mayor_incumbency_panel/"
SEALED = "sealed/outcomes/mayor_incumbency_panel/"
R1, R2, R3, C1, C2, C3 = "1100015", "1100023", "1100031", "1200013", "1200054", "1200104"
TSE = {R1: "00019", R2: "00027", R3: "00035", C1: "01015", C2: "01058", C3: "01104"}
BY_TSE = {v: k for k, v in TSE.items()}
SENTINEL_FAVORECIDO = ("SENTINEL-FAV-CODE", "SENTINEL FAVORECIDO NAME")


def cpf(n: int) -> str:
    """A synthetic 11-digit CPF, made up here."""
    return f"{n:011d}"


A, B, C, D, E, F = (cpf(n) for n in (90001, 90002, 90003, 90004, 90005, 90006))
CPFS = (A, B, C, D, E, F)


def titulo(number: str | None) -> str | None:
    """A synthetic 12-digit título for a synthetic CPF (none for one that cannot be linked)."""
    return "7" + number if number is not None and len(number) == 11 else None


def rows(data, schema):
    return pl.DataFrame(data, schema=schema, orient="row")


# --- TSE results (the tse_results build's columns)

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
EL = {2012: 200, 2016: 100, 2020: 300, 2024: 400}  # main election codes


def vote(year, muni, sq, n, *, turn=1, el=None, cargo="11", dest="Válido"):
    el = EL[year] + (1 if turn == 2 else 0) if el is None else el
    if year < 2016:  # no valid column and no destination
        return (cargo, turn, el, TSE[muni], sq, "1", n, None, None, muni)
    return (cargo, turn, el, TSE[muni], sq, "1", n, n, dest, muni)


VOTES = {
    2012: [
        vote(2012, R1, "a1", 450),
        vote(2012, R1, "a2", 300),
        vote(2012, R2, "a3", 500),
        vote(2012, R2, "a4", 400),
        vote(2012, R3, "a5", 600),
        vote(2012, R3, "a6", 100),
        vote(2012, C1, "a7", 700),
        vote(2012, C1, "a8", 100),
    ],
    2016: [
        vote(2016, R1, "m1", 500),
        vote(2016, R1, "m1", 9999, dest="Anulado sub judice"),  # annulled: not counted
        vote(2016, R1, "m2", 300),
        vote(2016, R1, "m3", 100),
        vote(2016, R2, "m4", 400),
        vote(2016, R2, "m6", 350),
        vote(2016, R2, "m5", 250),
        vote(2016, R2, "m4", 450, turn=2),  # the run-off decides
        vote(2016, R2, "m6", 500, turn=2),
        vote(2016, R3, "m8", 600),
        vote(2016, R3, "m7", 200),
        vote(2016, R3, "m7", 99999, el=150),  # supplementary election
        vote(2016, R3, "x1", 5000, cargo="13"),  # council
        vote(2016, C1, "m9", 700),
        vote(2016, C1, "m10", 100),
        vote(2016, C2, "m11", 400),
        vote(2016, C2, "m12", 300),
        vote(2016, C3, "m13", 100),  # one candidate: no race
    ],
    2020: [
        vote(2020, R1, "n1", 600),
        vote(2020, R1, "n2", 400),
        vote(2020, R2, "n3", 700),
        vote(2020, R2, "n4", 300),
        vote(2020, R3, "o1", 500),
        vote(2020, R3, "o2", 300),
        vote(2020, C1, "p1", 500),
        vote(2020, C1, "p2", 400),
        vote(2020, C3, "q1", 300),
        vote(2020, C3, "q2", 200),  # not in the candidate file: the race has no second party
    ],
    2024: [
        vote(2024, R1, "s1", 300),
        vote(2024, R1, "s2", 500),
        vote(2024, R2, "t1", 400),
        vote(2024, R2, "t2", 300),
        vote(2024, R3, "u1", 400),
        vote(2024, R3, "u2", 100),
        vote(2024, C1, "r1", 600),
        vote(2024, C1, "r2", 500),
    ],
}
VALID = {
    2012: {R1: 750, R2: 900, R3: 700, C1: 800},
    2016: {R1: 900, R2: 1000, R3: 800, C1: 800, C2: 700, C3: 100},
    2020: {R1: 1000, R2: 1000, R3: 800, C1: 900, C3: 500},
    2024: {R1: 800, R2: 700, R3: 500, C1: 1100},
}


def turnout(year):
    out = [
        ("11", 1, EL[year], TSE[m], n) for m, n in VALID[year].items() if m != R2 or year != 2016
    ]
    if year == 2016:
        out += [("11", 1, 100, TSE[R2], 1000), ("11", 2, 101, TSE[R2], 1000)]
    return rows(out, TURNOUT_SCHEMA)


# --- Candidacies (the tse_candidates build's columns)

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
    "nr_cpf_candidato": pl.Utf8,
    "nr_titulo_eleitoral_candidato": pl.Utf8,
}
DAY = {2012: date(2012, 10, 7), 2016: date(2016, 10, 2), 2020: date(2020, 11, 15)}
DAY[2024] = date(2024, 10, 6)

# (year, municipality, sq, party, cpf[, gender, birth, education])
CANDIDATES = [
    (2012, R1, "a1", "10", A),
    (2012, R1, "a2", "20", cpf(11)),
    (2012, R2, "a3", "20", cpf(12)),
    (2012, R2, "a4", "10", cpf(13)),
    (2012, R3, "a5", "30", cpf(14)),
    (2012, R3, "a6", "10", cpf(15)),
    (2012, C1, "a7", "25", cpf(16)),
    (2012, C1, "a8", "20", cpf(17)),
    (2016, R1, "m1", "10", A, "2", date(1980, 10, 2), "6"),  # 36 on the day
    (2016, R1, "m2", "20", B, "4", date(1990, 12, 25), "8"),  # 25, birthday after
    (2016, R1, "m3", "30", cpf(21)),
    (2016, R2, "m4", "10", cpf(22)),
    (2016, R2, "m5", "30", cpf(23)),
    (2016, R2, "m6", "20", D),
    (2016, R3, "m7", "30", cpf(24)),
    (2016, R3, "m8", "31", cpf(25)),
    (2016, C1, "m9", "30", cpf(26)),
    (2016, C1, "m10", "25", "123"),  # a CPF that cannot be linked
    (2016, C2, "m11", "20", cpf(27)),
    (2016, C2, "m12", "30", cpf(28)),
    (2016, C3, "m13", "30", cpf(29)),
    (2020, R1, "n1", "10", C, "4", date(1970, 1, 1), "8"),
    (2020, R1, "n2", "20", B),
    (2020, R2, "n3", "20", D),
    (2020, R2, "n4", "10", cpf(31)),
    (2020, R3, "o1", "19", cpf(32)),
    (2020, R3, "o2", "30", cpf(33)),
    (2020, C1, "p1", "25", E),
    (2020, C1, "p2", "13", cpf(34)),
    (2020, C3, "q1", "30", cpf(35)),
    (2024, R1, "s1", "10", C),
    (2024, R1, "s2", "13", cpf(41)),
    (2024, R2, "t1", "20", cpf(42)),
    (2024, R2, "t2", "10", cpf(43)),
    (2024, R3, "u1", "19", cpf(44)),
    (2024, R3, "u2", "30", cpf(45)),
    (2024, C1, "r1", "44", E),
    (2024, C1, "r2", "65", cpf(46)),
]


def attributes():
    out = []
    for year, muni, sq, party, number, *rest in CANDIDATES:
        gender, born, edu = rest or ("2", date(1970, 1, 1), "6")
        out.append(
            (year, EL[year], TSE[muni], sq, party, gender, born, edu, DAY[year], number)
            + (titulo(number),)
        )
    return rows(out, ATTR_SCHEMA)


def coalitions(year):
    data = [("10", None), ("20", None)]
    if year == 2024:
        data += [("13", "2"), ("65", "2"), ("43", "2"), ("44", "-1")]
    return rows(data, {"nr_partido": pl.Utf8, "nr_federacao": pl.Utf8})


def municipalities():
    data = [
        (R1, TSE[R1], "RO", "Alta Floresta d'Oeste"),
        (R2, TSE[R2], "RO", "Ariquemes"),
        (R3, TSE[R3], "RO", "Cabixi"),
        (C1, TSE[C1], "AC", "Acrelândia"),
        (C2, TSE[C2], "AC", "Assis Brasil"),
        (C3, TSE[C3], "AC", "Brasiléia"),
    ]
    return rows(data, {"cd_ibge": pl.Utf8, "cd_tse": pl.Utf8, "uf": pl.Utf8, "name_ibge": pl.Utf8})


def population():
    data = [(y, m, 1000 * (i + 1)) for y in (2016, 2020) for i, m in enumerate(TSE) if m != C3]
    return rows(data, {"ano": pl.Int64, "id_municipio": pl.Utf8, "populacao": pl.Int64})


# --- Files of the world (zips)


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


BENCH_HEADER = ["SG_UF", "CD_CARGO", "NR_PARTIDO", "CD_SIT_TOT_TURNO", "NR_CPF_CANDIDATO"]
# (uf, cargo, party, status): 2 and 3 are elected from 2014, 5 is a substitute
BENCH = {
    2014: [
        ("RO", "6", "10", "2"),
        ("RO", "6", "10", "3"),
        ("RO", "6", "20", "2"),
        ("RO", "6", "20", "5"),
        ("AC", "6", "30", "2"),
        ("AC", "6", "25", "3"),
        ("RO", "7", "31", "2"),  # a state deputy: not the federal bench
    ],
    2018: [
        ("RO", "6", "31", "2"),  # PHS, in Podemos (19) by 2020
        ("RO", "6", "19", "3"),
        ("RO", "6", "10", "2"),
        ("AC", "6", "25", "2"),
        ("AC", "6", "13", "3"),
        ("AC", "6", "30", "5"),
    ],
}


def cand_zip(year, data):
    body = csv_bytes(BENCH_HEADER, [(*r, cpf(700 + i)) for i, r in enumerate(data)])
    return make_zip(
        {f"consulta_cand_{year}_BRASIL.csv": body, f"consulta_cand_{year}_BR.csv": b"garbage"}
    )


IND = "Emenda Individual - Transferências com Finalidade Definida"
PIX = "Emenda Individual - Transferências Especiais"
BANC = "Emenda de Bancada"
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


def pay_row(author, kind, ym, uf, muni, value):
    head = ["201700000001", author, "Autor " + author, "1", kind, ym, *SENTINEL_FAVORECIDO]
    return [*head, "x", "y", uf, muni, value]


CGU = [
    pay_row("100", IND, "2016/12", "RO", "ALTA FLORESTA D'OESTE", "777,00"),  # before the term
    pay_row("100", IND, "2017/03", "RO", "ALTA FLORESTA D'OESTE", "100,00"),
    pay_row("S/I", PIX, "2019/05", "RO", "Alta Floresta d'Oeste", "50,00"),  # any author
    pay_row("100", IND, "2020/10", "RO", "ALTA FLORESTA D'OESTE", "999,00"),  # after the election
    pay_row("200", IND, "2018/01", "RO", "ARIQUEMES", "10,00"),
    pay_row("200", IND, "2018/02", "RO", "ARIQUEMES", "-30,00"),  # nets below 0
    pay_row("300", PIX, "2021/01", "AC", "ACRELANDIA", "1.000,00"),
    pay_row("300", IND, "2024/09", "AC", "ACRELANDIA", "5,00"),
    pay_row("300", IND, "2024/10", "AC", "ACRELANDIA", "999,00"),
    pay_row("300", IND, "2019/01", "AC", "", "8,00"),  # a state recipient
    pay_row("S/I", BANC, "2015/01", "RO", "ARIQUEMES", "5,00"),  # not individual
    pay_row("S/I", BANC, "2026/09", "RO", "ARIQUEMES", "5,00"),
]


def cgu_zip(data):
    body = csv_bytes(CGU_HEADER, data, "utf-8")
    other = csv_bytes(["Código da Emenda", "Ano da Emenda"], [["201700000001", "2017"]], "utf-8")
    return make_zip(
        {"EmendasParlamentares.csv": other, "EmendasParlamentares_PorFavorecido.csv": body}
    )


# --- Staging in a fake store


def parquet(frame):
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def entry(path, blob):
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


PREFIX = {
    "tse_results": "data/derived/tse_results/r1/",
    "tse_candidates": "data/derived/tse_candidates/c1/",
    "tse_parties": "data/derived/tse_parties/p1/",
    "municipalities": "data/derived/municipalities/m1/",
    "ibge_population_annual": "data/raw/ibge/population_annual/2026-11-13/",
    "tse_general": "data/raw/tse/general/2026-11-16/",
    "cgu_amendments": "data/raw/cgu/amendments/2026-11-16/",
}


def stage(store, *, attrs=None, cgu=None, bench=None, votes=None, coalitions_2024=None):
    """Put every input in the store; return the seven manifests in `build`'s order."""
    store.create(EXPLORE_LIST, f"code_ibge\n{R1}\n".encode())
    store.create(EXPLORE_LIST_NON_AMAZON, f"code_ibge\n{C1}\n".encode())
    blobs: dict[str, dict[str, bytes]] = {name: {} for name in PREFIX}
    for year in (2012, 2016, 2020, 2024):
        data = (votes or VOTES)[year]
        blobs["tse_results"][f"candidate_votes_{year}.parquet"] = parquet(rows(data, VOTE_SCHEMA))
        blobs["tse_results"][f"turnout_{year}.parquet"] = parquet(turnout(year))
    blobs["tse_candidates"]["candidates.parquet"] = parquet(
        attrs if attrs is not None else attributes()
    )
    for year in (2020, 2024):
        frame = coalitions(year) if year != 2024 or coalitions_2024 is None else coalitions_2024
        blobs["tse_parties"][f"coalitions_{year}.parquet"] = parquet(frame)
    blobs["municipalities"]["municipalities.parquet"] = parquet(municipalities())
    blobs["ibge_population_annual"]["ibge_population_annual.parquet"] = parquet(population())
    for year, data in (bench or BENCH).items():
        blobs["tse_general"][f"consulta_cand_{year}.zip"] = cand_zip(year, data)
    blobs["cgu_amendments"]["EmendasParlamentares.zip"] = cgu if cgu is not None else cgu_zip(CGU)
    manifests = []
    for name, prefix in PREFIX.items():
        files = []
        for file, blob in blobs[name].items():
            store.create(prefix + file, blob)
            files.append(entry(prefix + file, blob))
        manifests.append({"dataset": name, "gcs_prefix": prefix, "files": files})
    return manifests


def run(store, manifests, tmp_path, **kwargs):
    options = {
        "elections": (2016, 2020),
        "min_races": 1,
        "max_races": 100,
        "federal_seats": 5,
        "min_key_share": 0.9,  # the world has one candidacy with neither CPF nor título in 13
    }
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
        created_at="2026-11-20T00:00:00+00:00",
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


def whole(store, manifest, election):
    name = mp.output_name(election)
    paths = [f["path"] for f in manifest["files"] + manifest["sealed_files"]]
    return pl.concat([read(store, p) for p in paths if p.endswith("/" + name)])


def row(table, cd_ibge, party):
    found = table.filter((pl.col("cd_ibge") == cd_ibge) & (pl.col("party") == party))
    assert found.height == 1
    return found.to_dicts()[0]


# --- 1. The rows


def test_two_rows_per_race_and_the_contract_schema(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)
    assert first.schema == pl.Schema(mp.SCHEMA)
    got = sorted(zip(first["cd_ibge"], first["party"], strict=True))
    expected = [(R1, "10"), (R1, "20"), (R2, "10"), (R2, "20"), (R3, "30"), (R3, "31")]
    expected += [(C1, "25"), (C1, "30"), (C2, "20"), (C2, "30")]
    assert got == sorted(expected)  # C3 had one candidate
    second = whole(store, manifest, 2020)
    got = sorted(zip(second["cd_ibge"], second["party"], strict=True))
    expected = [(R1, "10"), (R1, "20"), (R2, "10"), (R2, "20"), (R3, "19"), (R3, "30")]
    assert got == sorted(expected + [(C1, "13"), (C1, "25")])  # C3: a finalist without party


def test_race_columns(built):
    store, manifest, _ = built
    table = whole(store, manifest, 2016)
    first = row(table, R1, "10")  # 500 (the annulled 9,999 left out) against 300 of 900
    assert (first["election"], first["uf"], first["round"], first["n_mayor_cands"]) == (
        2016,
        "RO",
        1,
        3,
    )
    assert first["margin"] == pytest.approx(200 / 900) and first["win"] is True
    assert (first["fin_female"], first["fin_age"], first["fin_higher_ed"]) == (False, 36, False)
    assert first["population_e"] == 1000 and first["ln_pop"] == pytest.approx(math.log(1000))
    other = row(table, R1, "20")
    assert other["margin"] == pytest.approx(-200 / 900) and other["win"] is False
    assert (other["fin_female"], other["fin_age"], other["fin_higher_ed"]) == (True, 25, True)
    assert row(table, C2, "20")["population_e"] == 5000


def test_the_run_off_decides(built):
    store, manifest, _ = built
    table = whole(store, manifest, 2016)
    won, lost = row(table, R2, "20"), row(table, R2, "10")
    assert won["round"] == 2 and won["margin"] == pytest.approx(50 / 1000) and won["win"]
    assert lost["margin"] == pytest.approx(-50 / 1000) and lost["n_mayor_cands"] == 3


# --- 2. Four years before


def test_the_party_held_the_mayoralty_four_years_before(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)
    held = {(r["cd_ibge"], r["party"]): r["party_held_mayor_lag"] for r in first.to_dicts()}
    assert held[(R1, "10")] and held[(R2, "20")] and held[(R3, "30")] and held[(C1, "25")]
    assert not held[(R1, "20")] and not held[(R3, "31")] and not held[(C1, "30")]
    assert not held[(C2, "20")] and not held[(C2, "30")]  # no 2012 result
    second = whole(store, manifest, 2020)
    assert row(second, R3, "19")["party_held_mayor_lag"] is True  # PHS (31) won 2016: Podemos
    assert row(second, R3, "30")["party_held_mayor_lag"] is False


def test_a_finalist_who_won_four_years_before_is_not_eligible(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)
    assert row(first, R1, "10")["finalist_eligible"] is False  # won 2012 with the same CPF
    assert row(first, R1, "20")["finalist_eligible"] is True
    assert row(first, C1, "25")["finalist_eligible"] is None  # the CPF cannot be linked
    second = whole(store, manifest, 2020)
    assert row(second, R2, "20")["finalist_eligible"] is False  # the 2016 winner again
    assert row(second, R1, "10")["finalist_eligible"] is True


# --- 3. Four years after


def outcomes(r):
    keys = ("party_runs_next", "party_wins_next", "finalist_runs_next", "finalist_wins_next")
    return tuple(r[k] for k in keys)


def test_what_happened_four_years_later(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)
    assert outcomes(row(first, R1, "10")) == (True, True, False, False)  # term-limited
    assert outcomes(row(first, R1, "20")) == (True, False, True, False)
    assert outcomes(row(first, R2, "20")) == (True, True, True, True)  # re-elected
    assert outcomes(row(first, R2, "10")) == (True, False, False, False)
    assert outcomes(row(first, C1, "30")) == (False, False, False, False)
    assert outcomes(row(first, C1, "25"))[:2] == (True, True)
    assert outcomes(row(first, C1, "25"))[2:] == (None, None)  # the CPF cannot be linked
    assert outcomes(row(first, C2, "20")) == (None, None, None, None)  # no 2020 election


FINALIST = ("finalist_runs_next", "finalist_wins_next", "finalist_eligible")


def test_a_finalist_links_by_titulo_where_the_cpf_is_missing_or_short(built, tmp_path):
    # As in the TSE files: 2024 publishes no CPF; 2012 holds some CPFs without leading zeros.
    store, manifest, _ = built
    cpf = pl.col("nr_cpf_candidato")
    frame = attributes().with_columns(
        pl.when(pl.col("ano_eleicao") == 2024)
        .then(None)
        .when(pl.col("ano_eleicao") == 2012)
        .then(cpf.str.strip_chars_start("0"))
        .otherwise(cpf)
        .alias("nr_cpf_candidato")
    )
    other = MemoryStore()
    again = run(other, stage(other, attrs=frame), tmp_path)
    for e in (2016, 2020):
        assert (
            whole(other, again, e)
            .select(FINALIST)
            .equals(whole(store, manifest, e).select(FINALIST))
        )
    first = whole(other, again, 2016)
    assert row(first, R1, "10")["finalist_eligible"] is False  # A won 2012: linked by título
    assert outcomes(row(first, R2, "20")) == (True, True, True, True)


def test_a_cpf_alone_still_links(tmp_path):
    frame = attributes().with_columns(pl.lit(None, pl.Utf8).alias("nr_titulo_eleitoral_candidato"))
    store = MemoryStore()
    manifest = run(store, stage(store, attrs=frame), tmp_path)
    first = whole(store, manifest, 2016)
    assert row(first, R1, "10")["finalist_eligible"] is False
    assert outcomes(row(first, R2, "20")) == (True, True, True, True)


def test_stop_when_a_year_has_no_identifier(tmp_path):
    keys = ("nr_cpf_candidato", "nr_titulo_eleitoral_candidato")
    frame = attributes().with_columns(
        pl.when(pl.col("ano_eleicao") == 2024).then(None).otherwise(pl.col(k)).alias(k)
        for k in keys
    )
    store = MemoryStore()
    manifests = stage(store, attrs=frame)
    with pytest.raises(BuildError, match="2024: 8 of 8 mayoral candidacies have neither"):
        run(store, manifests, tmp_path)


def test_mergers_and_federations_carry_the_party_forward(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)
    phs = row(first, R3, "31")  # PHS merged into Podemos (19), which won 2020
    assert phs["party_next"] == "19" and outcomes(phs)[:2] == (True, True)
    second = whole(store, manifest, 2020)
    dem = row(second, C1, "25")  # DEM became União Brasil (44), which won 2024
    assert dem["party_next"] == "44" and outcomes(dem) == (True, True, True, True)
    pt = row(second, C1, "13")  # in a federation with 65, whose candidate ran in 2024
    assert pt["party_next"] == "F2" and outcomes(pt) == (True, False, False, False)
    assert row(second, R1, "10")["party_next"] == "10"
    assert outcomes(row(second, R1, "10")) == (True, False, True, False)


# --- 4. The federal bench at e-2


def test_bench_of_the_party_in_the_state(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)  # 2014: codes 2 and 3 elected, 5 a substitute
    bench = {(r["cd_ibge"], r["party"]): r["bench_fed"] for r in first.to_dicts()}
    assert bench[(R1, "10")] == 2 and bench[(R1, "20")] == 1 and bench[(R3, "31")] == 0
    assert bench[(C1, "30")] == 1 and bench[(C1, "25")] == 1 and bench[(C2, "20")] == 0
    second = whole(store, manifest, 2020)  # 2018: PHS's deputy counts for Podemos
    assert row(second, R3, "19")["bench_fed"] == 2
    assert row(second, R1, "20")["bench_fed"] == 0 and row(second, C1, "13")["bench_fed"] == 1


def test_read_bench_uses_the_2010_codes(tmp_path):
    data = [("RO", "6", "10", "1"), ("RO", "6", "10", "5"), ("RO", "6", "20", "2")]
    path = tmp_path / "c.zip"
    path.write_bytes(cand_zip(2010, data))
    got = mp.read_bench(path, tmp_path, 2010)
    assert got["party"].to_list() == ["10", "10"]  # 2 is SUPLENTE in 2010
    assert mp.read_bench(path, tmp_path, 2014)["party"].to_list() == ["10", "20"]


def test_a_federation_at_the_bench_counts_together():
    elected = pl.DataFrame(
        {"uf": ["RO"] * 3, "party": ["13", "65", "10"], "federation": ["2", "2", None]}
    )
    got = {r["party"]: r["bench_fed"] for r in mp.bench_table(elected, 2022, 2024).to_dicts()}
    assert got == {"13": 2, "65": 2, "10": 1}


def test_the_bench_needs_every_seat(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    with pytest.raises(BuildError, match="2014: 5 elected federal deputies, not 6"):
        run(store, manifests, tmp_path, federal_seats=6)


# --- 5. Amendment money during the term


def test_amendments_during_the_term(built):
    store, manifest, _ = built
    first = whole(store, manifest, 2016)  # 2017-01 to 2020-09, any author
    assert row(first, R1, "10")["amend_after_total"] == pytest.approx(150.0)
    assert row(first, R1, "20")["amend_after_pix"] == pytest.approx(50.0)
    assert row(first, R2, "10")["amend_after_total"] == 0.0  # nets below 0: set to 0
    assert row(first, C1, "30")["amend_after_total"] == 0.0
    second = whole(store, manifest, 2020)  # 2021-01 to 2024-09
    assert row(second, C1, "13")["amend_after_total"] == pytest.approx(1005.0)
    assert row(second, C1, "13")["amend_after_pix"] == pytest.approx(1000.0)
    notes = manifest["notes"].split("; ")
    assert "E2016_floored_to_zero=amend_after_total:1,amend_after_pix:0" in notes


def test_amendments_are_null_where_the_cgu_file_does_not_cover_the_term():
    paid = pl.DataFrame(
        {"ym": [201406], "cd_ibge": [R1], "value": [1.0], "pix": [False]},
        schema={"ym": pl.Int64, "cd_ibge": pl.Utf8, "value": pl.Float64, "pix": pl.Boolean},
    )
    sums, floored = mp.payment_sums(paid, {"first": 201406, "last": 202611}, 2012)
    assert sums is None and floored == {"amend_after_total": 0, "amend_after_pix": 0}
    sums, _ = mp.payment_sums(paid, {"first": 201406, "last": 202611}, 2016)
    assert sums is not None
    assert mp.after_window(2016) == (201701, 202009)


# --- 6. Notes, identifiers, the split and the path


def test_manifest_notes(built):
    _, manifest, _ = built
    notes = manifest["notes"].split("; ")
    first = next(n for n in notes if n.startswith("E2016: "))
    assert first.startswith("E2016: races=2, rows=4, races_both_halves=5, races_without_party=0")
    assert "one_candidate=1, ties=0, unlinkable_finalists=1, no_election_next=0" in first
    assert first.endswith("bench=2014, amendments=2017-01..2020-09")
    second = next(n for n in notes if n.startswith("E2020: "))
    assert "races_both_halves=4, races_without_party=1" in second
    assert "E2016_parties_without_candidates_next=none" in notes
    assert "E2020_federations_next=F2=13+43+65" in notes
    assert "bench_2014: elected_federal_deputies=5" in notes
    assert "dropped_recipient_rows_no_municipality=2019:1" in notes
    assert "keys_2016: candidacies=13, with_cpf=12, with_titulo=12, with_neither=1" in notes


def test_no_identifier_in_any_output(built):
    store, manifest, before = built
    for f in manifest["files"] + manifest["sealed_files"]:
        frame = read(store, f["path"])
        assert not any(w in c.lower() for c in frame.columns for w in ("cpf", "titulo", "name"))
        for column, dtype in frame.schema.items():
            if dtype == pl.Utf8:
                values = frame[column].drop_nulls().to_list()
                assert not set(values) & set(CPFS), column
    text = json.dumps(manifest)
    assert not any(c in text for c in CPFS)
    assert not any(titulo(c) in text for c in CPFS)
    assert not any(s in text for s in SENTINEL_FAVORECIDO)
    new = set(store.list("")) - before
    assert {p for p in new if not p.startswith((DERIVED, SEALED))} == set()


def test_exploration_half_in_derived_and_the_rest_only_in_sealed(built):
    store, manifest, _ = built
    for election in (2016, 2020):
        name = mp.output_name(election)
        derived = [f["path"] for f in manifest["files"] if f["path"].endswith(name)]
        sealed = [f["path"] for f in manifest["sealed_files"] if f["path"].endswith(name)]
        assert len(derived) == 1 and len(sealed) == 1
        assert derived[0].startswith(DERIVED) and sealed[0].startswith(SEALED)
        assert set(read(store, derived[0])["cd_ibge"]) == {R1, C1}
        assert not set(read(store, sealed[0])["cd_ibge"]) & {R1, C1}
    assert manifest["gcs_prefix"].startswith(DERIVED)


def test_a_second_run_is_unchanged(built, tmp_path):
    store, manifest, _ = built
    write_manifest(manifest, store, tmp_path / "manifest.json")
    manifests = []
    for name, prefix in PREFIX.items():
        files = [entry(p, store.read_bytes(p)) for p in store.list(prefix)]
        manifests.append({"dataset": name, "gcs_prefix": prefix, "files": files})
    assert run(store, manifests, tmp_path)["status"] == "unchanged"


def test_a_code_change_in_any_module_changes_the_path():
    files = [{"sha256": "a" * 64}]
    base = mp.input_hash(files, ["s1", "s2"], (2016,))
    sources = mp.code_sources()
    assert len(sources) == len(mp.CODE_MODULES)
    for i in range(len(sources)):
        changed = list(sources)
        changed[i] += "\n# changed"
        assert mp.input_hash(files, ["s1", "s2"], (2016,), code=changed) != base
    assert mp.input_hash(files, ["s1", "s2"], (2016, 2020)) != base
    assert mp.input_hash(files, ["s1", "s3"], (2016,)) != base


def test_code_modules_list_this_file_and_every_data_module_it_imports():
    from terrain import explore, parties
    from terrain.builds import cell_outcomes, place_outcomes, polling_place_tenure

    expected = {mp.__file__, ap.__file__, parties.__file__, explore.__file__}
    expected |= {place_outcomes.__file__, cell_outcomes.__file__, polling_place_tenure.__file__}
    assert set(mp.CODE_MODULES) == {Path(p) for p in expected}


# --- 7. Votes of every year


def test_candidacy_votes_read_2000_2012_and_2016_files():
    schema = {**VOTE_SCHEMA, "runoff": pl.Boolean}
    data = [
        ("11", 1, 1, "1", "s2000", "1", 0, 40, None, R1, False),  # 2000: votes in the valid column
        ("11", 1, 1, "1", "s2004", "1", 30, None, None, R1, False),  # 2004-2012: no valid column
        ("11", 1, 1, "1", "s2016", "1", 20, 20, "Válido", R1, False),
        ("11", 1, 1, "1", "s2016", "1", 99, 99, "Anulado", R1, False),
    ]
    got = mp.candidacy_votes(rows(data, schema))
    assert dict(zip(got["sq_candidato"], got["votes"], strict=True)) == {
        "s2000": 40.0,
        "s2004": 30.0,
        "s2016": 20.0,
    }


# --- 8. The stop rules


def tables(built):
    store, manifest, _ = built
    return {e: whole(store, manifest, e) for e in (2016, 2020)}


def test_check_panel_passes_on_the_world(built):
    mp.check_panel(tables(built), min_races=1, max_races=100)


def test_stop_on_a_race_without_two_rows(built):
    t = tables(built)
    t[2016] = t[2016].filter(~((pl.col("cd_ibge") == R1) & (pl.col("party") == "20")))
    with pytest.raises(BuildError, match="2016: 1 races do not have two rows"):
        mp.check_panel(t, min_races=1, max_races=100)


def test_a_tie_has_no_winner(built):
    t = tables(built)
    tie = pl.col("cd_ibge") == R1
    t[2016] = t[2016].with_columns(
        pl.when(tie).then(0.0).otherwise(pl.col("margin")).alias("margin"),
        pl.when(tie).then(False).otherwise(pl.col("win")).alias("win"),
    )
    mp.check_panel(t, min_races=1, max_races=100)


def test_stop_on_a_margin_outside_one(built):
    t = tables(built)
    t[2020] = t[2020].with_columns(pl.col("margin") * 10)
    with pytest.raises(BuildError, match="outside"):
        mp.check_panel(t, min_races=1, max_races=100)


def test_stop_on_a_win_without_running(built):
    t = tables(built)
    t[2016] = t[2016].with_columns(pl.lit(False).alias("finalist_runs_next"))
    with pytest.raises(BuildError, match="finalist_wins_next without finalist_runs_next"):
        mp.check_panel(t, min_races=1, max_races=100)


@pytest.mark.parametrize("number", [A, titulo(A)])
def test_stop_on_an_11_or_12_digit_text(built, number):
    t = tables(built)
    t[2016] = t[2016].with_columns(pl.lit(number).alias("party_next"))
    with pytest.raises(BuildError, match="11- or 12-digit"):
        mp.check_panel(t, min_races=1, max_races=100)


def test_stop_on_race_counts(built, tmp_path):
    with pytest.raises(BuildError, match="2016: 5 races, outside 6-100"):
        mp.check_panel(tables(built), min_races=6, max_races=100)
    store = MemoryStore()
    manifests = stage(store)
    with pytest.raises(BuildError, match="races, outside"):
        run(store, manifests, tmp_path, max_races=4)


def test_stop_when_no_candidate_has_code_4_or_8(tmp_path):
    store = MemoryStore()
    frame = attributes().with_columns(pl.lit("2").alias("cd_genero"))
    manifests = stage(store, attrs=frame)
    with pytest.raises(BuildError, match="gender code 4"):
        run(store, manifests, tmp_path)


def test_a_wrong_sha_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    manifests[0]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="does not match"):
        run(store, manifests, tmp_path)


def test_a_party_in_two_federations_stops_the_build(tmp_path):
    two = rows([("13", "2"), ("13", "3")], {"nr_partido": pl.Utf8, "nr_federacao": pl.Utf8})
    store = MemoryStore()
    manifests = stage(store, coalitions_2024=two)
    with pytest.raises(BuildError, match="two federations"):
        run(store, manifests, tmp_path)
