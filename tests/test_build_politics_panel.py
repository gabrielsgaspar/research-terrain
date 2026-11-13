"""The politics panel on a synthetic world: two municipalities, two elections (2004, 2008).

Every identifier and every value is made up inside this file. A is in the exploration half
(the first list), B is in neither list's municipalities of the panel, so it goes to sealed.
"""

import hashlib
import io
import json

import polars as pl
import pytest

from terrain.builds import politics_panel as pp
from terrain.builds.politics_panel import BuildError, build
from terrain.explore import EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/politics_panel/"
SEALED = "sealed/outcomes/politics_panel/"
ELECTIONS = (2004, 2008)
A, B, OTHER = "1100015", "1100023", "3550308"
TSE_A, TSE_B = "00019", "00027"


def cpf(n: int) -> str:
    """A synthetic 11-digit CPF, made up here."""
    return f"{n:011d}"


CA1, CA2, CN3, CB2, CB3 = cpf(40001), cpf(40002), cpf(40003), cpf(50002), cpf(50003)
SHORT = "12345"  # not 11 digits: unlinked
CPFS = [CA1, CA2, CN3, CB2, CB3, SHORT]

VOTE_SCHEMA = {
    "cd_cargo": pl.Utf8,
    "nr_turno": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "sq_candidato": pl.Utf8,
    "qt_votos_nominais": pl.Int64,
    "qt_votos_nominais_validos": pl.Int64,
    "cd_sit_tot_turno": pl.Utf8,
}
TURNOUT_SCHEMA = {
    "cd_cargo": pl.Utf8,
    "nr_turno": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "qt_total_votos_validos": pl.Int64,
}
CAND_SCHEMA = {
    "ano_eleicao": pl.Int32,
    "cd_eleicao": pl.Int32,
    "sg_ue": pl.Utf8,
    "sq_candidato": pl.Utf8,
    "cd_ocupacao": pl.Utf8,
    "sg_partido": pl.Utf8,
    "nr_cpf_candidato": pl.Utf8,
}
RECEIPT_SCHEMA = {
    "ano": pl.Int64,
    "id_municipio": pl.Utf8,
    "cargo": pl.Utf8,
    "cnae_2_doador": pl.Utf8,
    "n_receitas": pl.Int64,
    "sum_valor_receita": pl.Float64,
}


def rows(data, schema):
    return pl.DataFrame(data, schema=schema, orient="row")


# --- The world. Votes of 2004 are in the valid column (nominal 0, as in the 2000 file);
# votes of 2008 are in the nominal column (no valid column). Supplementary elections and
# round 2 exist and must be ignored.


def votes_2004():
    def c(ue, sq, n, sit, cargo="13", turn=1, el=100):
        return (cargo, turn, el, ue, sq, 0, n, sit)

    return rows(
        [
            c(TSE_A, "1", 60, "1"),
            c(TSE_A, "1", 40, "1"),  # same candidacy, second zone
            c(TSE_A, "2", 80, "1"),
            c(TSE_A, "3", 50, "2"),
            c(TSE_A, "4", 30, "2"),
            c(TSE_A, "5", 0, "2"),  # on the ballot, no votes
            c(TSE_A, "9", 999, "1", el=200),  # supplementary election
            c(TSE_A, "11", 400, "1", cargo="11"),
            c(TSE_A, "11", 200, "1", cargo="11"),
            c(TSE_A, "12", 300, "2", cargo="11"),
            c(TSE_A, "13", 100, "2", cargo="11"),
            c(TSE_A, "14", 0, "2", cargo="11"),
            c(TSE_A, "11", 900, "1", cargo="11", turn=2),  # round 2
            c(TSE_B, "1", 10, "1"),  # sq repeats across municipalities before 2012
            c(TSE_B, "2", 5, "2"),
            c(TSE_B, "11", 500, "1", cargo="11"),
            c(TSE_B, "12", 500, "2", cargo="11"),
        ],
        VOTE_SCHEMA,
    )


def votes_2008():
    def c(ue, sq, n, sit, cargo="13", turn=1, el=300):
        return (cargo, turn, el, ue, sq, n, None, sit)

    return rows(
        [
            c(TSE_A, "1", 90, "1"),
            c(TSE_A, "2", 70, "5"),  # 2008 code 5 is also elected
            c(TSE_A, "3", 60, "1"),
            c(TSE_A, "4", 40, "2"),
            c(TSE_A, "5", 20, "3"),  # a code that is neither: still ran, not elected
            c(TSE_A, "6", 5, "2", el=400),
            c(TSE_A, "11", 800, "1", cargo="11"),
            c(TSE_A, "12", 0, "2", cargo="11"),
            c(TSE_B, "1", 30, "1"),
            c(TSE_B, "2", 20, "2"),
            c(TSE_B, "3", 10, "4"),
            c(TSE_B, "11", 700, "1", cargo="11"),
            c(TSE_B, "12", 200, "2", cargo="11"),
        ],
        VOTE_SCHEMA,
    )


def turnout(year, el, valid_a, valid_b):
    return rows(
        [
            ("11", 1, el, TSE_A, valid_a // 2),
            ("11", 1, el, TSE_A, valid_a - valid_a // 2),
            ("11", 1, el, TSE_B, valid_b),
            ("11", 2, el, TSE_A, 7),
            ("13", 1, el, TSE_A, 5000),
        ],
        TURNOUT_SCHEMA,
    )


def candidates():
    def c(year, el, ue, sq, occ, party, who):
        return (year, el, ue, sq, occ, party, who)

    return rows(
        [
            c(2004, 100, TSE_A, "1", "605", "P1", CA1),
            c(2004, 100, TSE_A, "2", "111", "P2", CA2),
            c(2004, 100, TSE_A, "3", "253", "P1", cpf(40004)),
            c(2004, 100, TSE_A, "4", "111", "P3", cpf(40005)),
            c(2004, 100, TSE_A, "5", "605", "P3", ""),  # no votes: not counted
            c(2004, 100, TSE_B, "1", "111", "P1", SHORT),  # elected, unlinked
            c(2004, 100, TSE_B, "2", "111", "P2", cpf(50001)),
            c(2008, 300, TSE_A, "1", "111", "P1", CA1),  # re-elected
            c(2008, 300, TSE_A, "2", "111", "P2", ""),  # elected, unlinked
            c(2008, 300, TSE_A, "3", "605", "P4", CN3),
            c(2008, 300, TSE_A, "4", "111", "P2", CA2),  # runs again and loses
            c(2008, 300, TSE_A, "5", "253", "P1", cpf(40006)),
            c(2008, 300, TSE_B, "1", "111", "P9", CB3),
            c(2008, 300, TSE_B, "2", "111", "P1", CB2),
            c(2008, 300, TSE_B, "3", "111", "P2", cpf(50004)),
        ],
        CAND_SCHEMA,
    )


def municipalities():
    return rows(
        [(A, TSE_A, "RO"), (B, TSE_B, "RO")],
        {"cd_ibge": pl.Utf8, "cd_tse": pl.Utf8, "uf": pl.Utf8},
    )


def homicides():
    return rows(
        [
            (1999, A, 50),  # before every window
            (2000, A, 5),
            (2002, A, 3),
            (2003, A, 2),
            (2004, A, 1),
            (2007, A, 3),
            (2008, A, 50),  # not before 2008
            (2005, B, 7),
            (2005, None, 99),  # no municipality
        ],
        {"ano": pl.Int64, "id_municipio_ocorrencia": pl.Utf8, "n_obitos": pl.Int64},
    )


def population():
    data = [(y, A, 20000) for y in range(2000, 2004)] + [(y, A, 25000) for y in range(2004, 2008)]
    data += [(2000, B, 5000), (2001, B, None), (2002, B, 5000), (2003, B, 5000)]
    data += [(y, B, 5000) for y in range(2004, 2008)]
    return rows(data, {"ano": pl.Int64, "id_municipio": pl.Utf8, "populacao": pl.Int64})


def receipts():
    return rows(
        [
            (2004, A, "Vereador", "0710301", 2, 100.0),  # division 07
            (2004, A, "PREFEITO", "8991901", 4, 300.0),
            (2004, A, "Vereador", "990401", 1, 50.0),  # padded to 0990401: class 0990
            (2004, A, "Vereador", None, 3, 150.0),  # no CNAE
            (2004, A, "Vice-prefeito", "0710301", 9, 999.0),  # not an office of the panel
            (2004, A, "Prefeito", "08.11-4/00", 1, 50.0),  # digits only: division 08
            (2006, A, "Vereador", "0710301", 1, 7777.0),  # another year
            (2008, A, "Prefeito", None, 2, 200.0),
            (2008, B, "Vereador", "0710301", 1, 10.0),
            (2008, B, "Governador", "0710301", 5, 5000.0),
        ],
        RECEIPT_SCHEMA,
    )


def world():
    return {
        "cands": candidates(),
        "votes": {2004: votes_2004(), 2008: votes_2008()},
        "turnout": {2004: turnout(2004, 100, 1000, 1000), 2008: turnout(2008, 300, 900, 950)},
        "munis": municipalities(),
        "hom": homicides(),
        "pop": population(),
        "receipts": receipts(),
    }


# --- Staging in a fake store


def parquet(frame):
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def entry(path, blob):
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def stage(store, w, lists=None):
    """Put every input in the store; return the six manifests."""
    first, second = lists or (f"code_ibge\n{A}\n", f"code_ibge\n{OTHER}\n")
    store.create(EXPLORE_LIST, first.encode("utf-8"))
    store.create(EXPLORE_LIST_NON_AMAZON, second.encode("utf-8"))

    def put(path, frame):
        blob = parquet(frame)
        store.create(path, blob)
        return entry(path, blob)

    def manifest(name, prefix, files):
        return {"dataset": name, "gcs_prefix": prefix, "files": files}

    cp = "data/derived/tse_candidates/c1/"
    rp = "data/derived/tse_results/r1/"
    mp = "data/derived/municipalities/m1/"
    result_files = []
    for year in ELECTIONS:
        result_files.append(put(f"{rp}candidate_votes_{year}.parquet", w["votes"][year]))
        result_files.append(put(f"{rp}turnout_{year}.parquet", w["turnout"][year]))
    return (
        manifest("tse_candidates", cp, [put(cp + "candidates.parquet", w["cands"])]),
        manifest("tse_results", rp, result_files),
        manifest("municipalities", mp, [put(mp + "municipalities.parquet", w["munis"])]),
        manifest(
            "sim_homicides",
            "data/raw/sim/homicides/2026-11-13/",
            [put("data/raw/sim/homicides/2026-11-13/sim_homicides.parquet", w["hom"])],
        ),
        manifest(
            "ibge_population_annual",
            "data/raw/ibge/population_annual/2026-11-13/",
            [
                put(
                    "data/raw/ibge/population_annual/2026-11-13/ibge_population_annual.parquet",
                    w["pop"],
                )
            ],
        ),
        manifest(
            "tse_receipts",
            "data/raw/tse/receipts/2026-11-13/",
            [put("data/raw/tse/receipts/2026-11-13/tse_receipts.parquet", w["receipts"])],
        ),
    )


def run(store, manifests, tmp_path, **kwargs):
    options = {"min_municipalities": 1, "min_mining_cands": 1, "elections": ELECTIONS}
    options.update(kwargs)
    tmp = tmp_path / "work"
    tmp.mkdir(exist_ok=True)
    return build(
        store,
        *manifests,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=tmp,
        code_commit="abc",
        created_at="2026-11-13T00:00:00+00:00",
        **options,
    )


def read(store, path):
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


@pytest.fixture
def built(tmp_path):
    store = MemoryStore()
    manifests = stage(store, world())
    before = set(store.list(""))
    manifest = run(store, manifests, tmp_path)
    return store, manifest, before


def row_of(store, manifest, municipality, election):
    """The one row of a municipality and election, from derived or sealed."""
    name = pp.output_name(election)
    found = []
    for entry_ in [*manifest["files"], *manifest["sealed_files"]]:
        if entry_["path"].endswith("/" + name):
            frame = read(store, entry_["path"]).filter(pl.col("cd_ibge") == municipality)
            found += frame.to_dicts()
    assert len(found) == 1
    return found[0]


# --- 1. The outcomes against hand computations


def test_outcomes_of_a_2004(built):
    store, manifest, _ = built
    got = row_of(store, manifest, A, 2004)
    # council: 4 ran (a5 had no votes) for 2 seats; 605 and 253 among those who ran: 2 of 4;
    # of the 2 elected, 1 has code 605
    assert got["uf"] == "RO" and got["election"] == 2004
    assert (got["n_council_cands"], got["n_seats"]) == (4, 2)
    assert got["cands_per_seat"] == pytest.approx(2.0)
    assert got["n_mining_cands"] == 2
    assert got["mining_cand_share"] == pytest.approx(0.5)
    assert got["mining_councillor_share"] == pytest.approx(0.5)
    # mayor: 600, 300 and 100 votes (the 0-vote candidate and round 2 do not count)
    assert got["n_mayor_cands"] == 3
    assert got["valid_votes_mayor"] == 1000
    assert got["enc_mayor"] == pytest.approx(1 / (0.6**2 + 0.3**2 + 0.1**2))
    assert got["margin_mayor"] == pytest.approx(0.3)
    # no earlier election in the world
    assert got["seat_turnover"] is None and got["incumbent_reelected"] is None
    # money: vereador and prefeito only; total 100+300+50+150+50, with a CNAE 500,
    # mining 100 (07) + 50 (0990) + 50 (08)
    assert got["receipts_total"] == pytest.approx(650.0)
    assert got["receipts_with_cnae"] == pytest.approx(500.0)
    assert got["n_receipts_with_cnae"] == 8
    assert got["mining_money_share"] == pytest.approx(200 / 650)
    # homicides 2000-2003: 5 + 3 + 2 over 4 x 20,000
    assert got["homicides_sum"] == 10
    assert got["homicide_rate"] == pytest.approx(12.5)


def test_outcomes_of_a_2008(built):
    store, manifest, _ = built
    got = row_of(store, manifest, A, 2008)
    # 5 ran (code 3 is neither elected nor not elected, yet ran); 3 elected (codes 1 and 5)
    assert (got["n_council_cands"], got["n_seats"]) == (5, 3)
    assert got["cands_per_seat"] == pytest.approx(5 / 3)
    assert got["n_mining_cands"] == 2
    assert got["mining_cand_share"] == pytest.approx(2 / 5)
    assert got["mining_councillor_share"] == pytest.approx(1 / 3)
    # one mayoral candidate: margin 1.0, one effective candidate
    assert got["n_mayor_cands"] == 1
    assert got["valid_votes_mayor"] == 900
    assert got["enc_mayor"] == pytest.approx(1.0)
    assert got["margin_mayor"] == 1.0
    # seats 2008: P1, P2, P4; seats 2004: P1, P2. overlap 2 of 3 seats
    assert got["seat_turnover"] == pytest.approx(1 - 2 / 3)
    # elected 2004: CA1 and CA2; elected 2008: CA1 (re-elected), an unlinked one, CN3
    assert got["incumbent_reelected"] == pytest.approx(0.5)
    # money: one prefeito row without a CNAE
    assert got["receipts_total"] == pytest.approx(200.0)
    assert got["receipts_with_cnae"] == pytest.approx(0.0)
    assert got["n_receipts_with_cnae"] == 0
    assert got["mining_money_share"] == pytest.approx(0.0)
    # homicides 2004-2007: 1 + 3 over 4 x 25,000
    assert got["homicides_sum"] == 4
    assert got["homicide_rate"] == pytest.approx(4.0)


def test_outcomes_of_b(built):
    store, manifest, _ = built
    b04 = row_of(store, manifest, B, 2004)
    assert (b04["n_council_cands"], b04["n_seats"]) == (2, 1)
    assert b04["n_mining_cands"] == 0 and b04["mining_cand_share"] == 0.0
    assert b04["enc_mayor"] == pytest.approx(2.0)
    assert b04["margin_mayor"] == pytest.approx(0.0)
    # no receipts row: null, not 0
    assert b04["receipts_total"] is None and b04["mining_money_share"] is None
    # 2001's population is null: the rate is null; no death row: 0 homicides
    assert b04["homicide_rate"] is None and b04["homicides_sum"] == 0

    b08 = row_of(store, manifest, B, 2008)
    assert b08["cands_per_seat"] == pytest.approx(3.0)
    assert b08["seat_turnover"] == pytest.approx(1.0)  # P9 against P1: no seat kept
    # the only 2004 councillor has a CPF that is not 11 digits: nobody to link
    assert b08["incumbent_reelected"] is None
    assert b08["enc_mayor"] == pytest.approx(1 / ((700 / 900) ** 2 + (200 / 900) ** 2))
    assert b08["margin_mayor"] == pytest.approx(500 / 950)
    assert b08["mining_money_share"] == pytest.approx(1.0)
    assert (b08["receipts_total"], b08["n_receipts_with_cnae"]) == (10.0, 1)
    assert b08["homicides_sum"] == 7
    assert b08["homicide_rate"] == pytest.approx(7 / 20000 * 100_000)


def test_the_2004_codes_are_the_2008_ones():
    assert pp.code_year(2000) == 2008 and pp.code_year(2004) == 2008
    assert pp.code_year(2008) == 2008 and pp.code_year(2012) == 2012


# --- 2. No CPF anywhere


def cell_strings(frame):
    out = list(frame.columns)
    for column in frame.columns:
        if frame.schema[column] == pl.Utf8:
            out += [v for v in frame[column].to_list() if v is not None]
    return out


def test_no_output_holds_a_cpf(built):
    store, manifest, _ = built
    paths = [f["path"] for f in [*manifest["files"], *manifest["sealed_files"]]]
    assert len(paths) == 4
    for path in paths:
        frame = read(store, path)
        assert [c for c in frame.columns if "cpf" in c or "nome" in c] == []
        for text in cell_strings(frame):
            assert not any(c in text for c in CPFS)
    dump = json.dumps(manifest)
    assert not any(c in dump for c in CPFS)
    for key in store.list(DERIVED) + store.list(SEALED):
        assert not any(c.encode("utf-8") in store.read_bytes(key) for c in CPFS)


def test_the_link_functions_return_no_identifier():
    cur = pl.DataFrame(
        {"cd_ibge": [A, A], "elected": [True, True], "party": ["P1", "P2"], "cpf": [CA1, ""]}
    )
    prev = pl.DataFrame(
        {"cd_ibge": [A, A], "elected": [True, True], "party": ["P1", "P2"], "cpf": [CA1, CA2]}
    )
    out = pp.incumbent_reelected(cur, prev)
    assert out.columns == ["cd_ibge", "incumbent_reelected"]
    assert out["incumbent_reelected"].to_list() == [0.5]
    unlinked = pp.unlinked_cpfs(cur)
    assert unlinked.columns == ["cd_ibge", "n_unlinked"]
    assert unlinked["n_unlinked"].to_list() == [1]


# --- 3. Rows by half, and the notes


def test_rows_land_by_half(built):
    store, manifest, before = built
    derived = {f["path"] for f in manifest["files"]}
    sealed = {f["path"] for f in manifest["sealed_files"]}
    prefix = manifest["gcs_prefix"]
    assert prefix.startswith(DERIVED) and prefix.endswith("/")
    assert derived == {f"{prefix}politics_panel_{e}.parquet" for e in ELECTIONS}
    assert sealed == {
        f"{SEALED}{prefix[len(DERIVED) :]}politics_panel_{e}.parquet" for e in ELECTIONS
    }
    for path in derived:
        assert read(store, path)["cd_ibge"].to_list() == [A]
    for path in sealed:
        assert read(store, path)["cd_ibge"].to_list() == [B]
    assert set(store.list("")) - before == derived | sealed


def test_the_schema_is_the_contract(built):
    store, manifest, _ = built
    for f in [*manifest["files"], *manifest["sealed_files"]]:
        assert dict(read(store, f["path"]).schema) == pp.SCHEMA


def test_notes_count_exploration_rows_only(built):
    _, manifest, _ = built
    assert manifest["notes"] == (
        "E2004: rows=1, unlinked_cpfs=0; E2008: rows=1, unlinked_cpfs=1; "
        "years_with_receipt_cnae=2004"
    )


def test_a_repeat_is_unchanged_and_uploads_nothing(tmp_path):
    store = MemoryStore()
    manifests = stage(store, world())
    first = run(store, manifests, tmp_path)
    assert first["status"] == "created"
    write_manifest(first, store, tmp_path / "m.json")
    after = set(store.list(""))
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert set(store.list("")) == after


# --- 3. Every stop condition raises and uploads nothing


def assert_stops(tmp_path, w, match, **kwargs):
    store = MemoryStore()
    manifests = stage(store, w)
    before = set(store.list(""))
    with pytest.raises(BuildError, match=match) as err:
        run(store, manifests, tmp_path, **kwargs)
    assert set(store.list("")) == before
    assert not any(c in str(err.value) for c in CPFS)


def test_a_cd_tse_without_a_cd_ibge_stops(tmp_path):
    w = world()
    w["munis"] = w["munis"].filter(pl.col("cd_ibge") == A)
    assert_stops(tmp_path, w, "no cd_ibge")


def test_fewer_candidates_than_seats_stops(tmp_path):
    w = world()
    # A's council candidates 3, 4 and 5 become elected: 5 seats, and 4 ran (5 had no votes)
    council_a = (
        (pl.col("sg_ue") == TSE_A)
        & (pl.col("cd_cargo") == "13")
        & (pl.col("cd_eleicao") == 100)
        & pl.col("sq_candidato").is_in(["3", "4", "5"])
    )
    w["votes"][2004] = w["votes"][2004].with_columns(
        pl.when(council_a)
        .then(pl.lit("1"))
        .otherwise(pl.col("cd_sit_tot_turno"))
        .alias("cd_sit_tot_turno")
    )
    assert_stops(tmp_path, w, "fewer candidates than seats")


def test_a_share_outside_zero_one_stops(tmp_path):
    w = world()
    w["turnout"][2004] = turnout(2004, 100, 200, 1000)  # margin 300 / 200
    assert_stops(tmp_path, w, "margin_mayor outside")


def test_fewer_municipalities_than_the_floor_stops(tmp_path):
    assert_stops(tmp_path, world(), "below 5000", min_municipalities=5000)


def test_a_homicide_rate_above_1000_stops(tmp_path):
    w = world()
    w["hom"] = w["hom"].with_columns(
        pl.when(pl.col("id_municipio_ocorrencia") == A)
        .then(pl.col("n_obitos") * 1000)
        .otherwise(pl.col("n_obitos"))
        .alias("n_obitos")
    )
    assert_stops(tmp_path, w, "homicide rate above 1,000")


def test_too_few_mining_candidates_stops(tmp_path):
    # the world has 4 candidates with code 605 or 253 in 2004 and 2008
    assert_stops(tmp_path, world(), "below 5", min_mining_cands=5)
    assert_stops(tmp_path, world(), "below 100", min_mining_cands=100)


def test_a_year_without_vereador_or_prefeito_receipts_stops(tmp_path):
    w = world()
    w["receipts"] = w["receipts"].filter(
        ~(
            (pl.col("ano") == 2004)
            & pl.col("cargo").str.to_lowercase().is_in(["vereador", "prefeito"])
        )
    )
    assert_stops(tmp_path, w, "2004: no receipts of vereador or prefeito")


# --- Units


def test_office_names_are_compared_without_case_or_accents():
    assert pp.office_key("PRÉFEITO ") == "prefeito"
    assert pp.office_key("Vereador") == "vereador"
    assert pp.office_key("Vice-prefeito") == "vice-prefeito"


def test_a_mining_cnae_is_found_after_padding_to_seven_digits():
    frame = rows(
        [
            (2004, A, "vereador", "0710301", 1, 1.0),  # division 07
            (2004, A, "vereador", "0891600", 1, 1.0),  # division 08
            (2004, A, "vereador", "990401", 1, 1.0),  # 0990401 after padding
            (2004, A, "vereador", "0990401", 1, 1.0),  # the same, already padded
            (2004, A, "vereador", "9900401", 1, 1.0),  # 9900: not mining
            (2004, A, "vereador", "7100000", 1, 1.0),  # not mining
            (2004, A, "vereador", None, 1, 1.0),  # no CNAE: not counted at all
        ],
        RECEIPT_SCHEMA,
    )
    got = pp.money_table(frame, 2004).row(0, named=True)
    assert got["receipts_total"] == 7.0 and got["receipts_with_cnae"] == 6.0
    assert got["n_receipts_with_cnae"] == 6
    assert got["mining_money_share"] == pytest.approx(4 / 7)


def test_check_panel_accepts_the_built_tables(built):
    store, manifest, _ = built
    tables = {
        e: pl.concat(
            [
                read(store, f["path"])
                for f in [*manifest["files"], *manifest["sealed_files"]]
                if f["path"].endswith(f"_{e}.parquet")
            ]
        )
        for e in ELECTIONS
    }
    pp.check_panel(tables, min_municipalities=2, min_mining_cands=4)
    with pytest.raises(BuildError, match="below 3"):
        pp.check_panel(tables, min_municipalities=3, min_mining_cands=4)


def test_the_two_exploration_lists_must_not_overlap(tmp_path):
    store = MemoryStore()
    manifests = stage(store, world(), lists=(f"code_ibge\n{A}\n", f"code_ibge\n{A}\n"))
    with pytest.raises(BuildError, match="both exploration lists"):
        run(store, manifests, tmp_path)
