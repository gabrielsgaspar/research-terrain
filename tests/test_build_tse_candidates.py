import csv
import hashlib
import io
import re
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from terrain.builds.tse_candidates import (
    KEY,
    MISSING,
    BuildError,
    build,
    check,
    dtype_of,
    harmonise,
    join_complementar,
    snake,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "tse"
CONTRACT = Path(__file__).resolve().parents[1] / "data" / "contracts" / "tse_candidates.md"
DERIVED = dataset("tse_candidates")["derived"]
RAW = "data/raw/tse/candidates/2026-11-02/"
YEARS = [2000, 2004, 2008, 2012, 2016, 2020, 2024]
COMP_YEARS = [2020, 2024]


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}_sample.csv").read_bytes()


def records(data: bytes) -> int:
    text = data.decode("latin-1")
    return sum(1 for _ in csv.reader(io.StringIO(text, newline=""), delimiter=";")) - 1


def make_zip(name: str, data: bytes, *, state_files: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}_BRASIL.csv", data)
        if state_files:
            # The real zips repeat every BRASIL row in per-state files.
            zf.writestr(f"{name}_PA.csv", data)
            zf.writestr(f"{name}_AM.csv", data)
        zf.writestr("leiame.pdf", b"%PDF-")
    return buf.getvalue()


def stage(
    store: MemoryStore,
    *,
    overrides: dict[str, bytes] | None = None,
    state_files: tuple[str, ...] = (),
) -> dict:
    """Put zips made from the fixtures in `store`; return the acquire manifest."""
    overrides = overrides or {}
    names = [f"consulta_cand_{y}" for y in YEARS]
    names += [f"consulta_cand_complementar_{y}" for y in COMP_YEARS]
    files = []
    for name in names:
        data = overrides.get(name, fixture(name))
        blob = make_zip(name, data, state_files=name in state_files)
        path = f"{RAW}{name}.zip"
        store.create(path, blob)
        files.append({"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)})
    return {"dataset": "tse_candidates", "gcs_prefix": RAW, "files": files}


def run(store: MemoryStore, manifest: dict, tmp_path: Path) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(store, manifest, derived_root=DERIVED, tmp_dir=work, code_commit="abc")


def read_output(store: MemoryStore, manifest: dict) -> pl.DataFrame:
    return pl.read_parquet(store.read_bytes(manifest["files"][0]["path"]))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    store = MemoryStore()
    tmp = tmp_path_factory.mktemp("build")
    out = run(store, stage(store), tmp)
    return store, out, read_output(store, out)


def with_line_changed(data: bytes, *, index: int, field: int | None, value: bytes | None) -> bytes:
    """Append a copy of data row `index` (0 = first data row), with one field replaced."""
    lines = data.split(b"\r\n")
    row = lines[1 + index]
    if field is not None:
        parts = row.split(b";")
        parts[field] = value
        row = b";".join(parts)
    body = [ln for ln in lines if ln]
    return b"\r\n".join(body + [row]) + b"\r\n"


# --- Done when 1: row counts and state files


def test_one_row_per_fixture_row_over_all_years(built):
    _, out, df = built
    expected = sum(records(fixture(f"consulta_cand_{y}")) for y in YEARS)
    assert df.height == expected
    assert out["status"] == "created"
    assert validate_manifest(out, stage="build", dataset="tse_candidates") == []
    for y in YEARS:
        assert df.filter(pl.col("ano_eleicao") == y).height == records(
            fixture(f"consulta_cand_{y}")
        )


def test_state_files_beside_brasil_do_not_double_rows(built, tmp_path):
    _, _, df = built
    store = MemoryStore()
    names = tuple(f"consulta_cand_{y}" for y in YEARS)
    out = run(store, stage(store, state_files=names), tmp_path)
    assert read_output(store, out).height == df.height


# --- Done when 2: text and identifiers


def test_accents_decode_and_identifiers_keep_leading_zeros(built):
    _, _, df = built
    assert "ELEIÇÃO SUPLEMENTAR" in df["nm_tipo_eleicao"].to_list()
    assert "ELEIÇÃO ORDINÁRIA" in df["nm_tipo_eleicao"].to_list()
    for c in ("sq_candidato", "sg_ue", "nr_cpf_candidato", "nr_titulo_eleitoral_candidato"):
        assert df.schema[c] == pl.String
    assert "05436" in df["sg_ue"].to_list()
    assert "00000000001" in df["nr_cpf_candidato"].to_list()
    titles = df["nr_titulo_eleitoral_candidato"].drop_nulls()
    assert titles.len() > 0
    assert (titles.str.len_chars() == 12).all()
    assert titles.str.starts_with("0").any()


def test_dates_and_integers_are_typed(built):
    _, _, df = built
    assert df.schema["dt_eleicao"] == pl.Date
    assert df.schema["dt_nascimento"] == pl.Date
    assert date(2024, 10, 6) in df["dt_eleicao"].to_list()
    assert df.schema["cd_eleicao"] == pl.Int32


# --- Done when 3: missing-value codes


def test_missing_codes_are_null_in_the_output(built):
    _, _, df = built
    for c in df.columns:
        if c in KEY or df.schema[c] != pl.String:
            continue
        assert not df[c].is_in(MISSING).any(), c
    # codes that the fixtures contain: #NE (2000), #NE# (2012), #NULO (2024), -4 (CPF 2024)
    assert df.filter(pl.col("ano_eleicao") == 2000)["cd_cor_raca"].is_null().all()
    assert df.filter(pl.col("ano_eleicao") == 2012)["cd_cor_raca"].is_null().all()
    assert df.filter(pl.col("ano_eleicao") == 2024)["nm_social_candidato"].is_null().all()
    assert df.filter(pl.col("ano_eleicao") == 2024)["nr_cpf_candidato"].is_null().all()


def test_harmonise_nulls_every_listed_code():
    codes = ["#NE", "#NE#", "#NULO", "#NULO#", "-1", "-3", "-4", "NÃO DIVULGÁVEL"]
    n = len(codes)
    df = pl.DataFrame(
        {
            "ANO_ELEICAO": ["2024"] * n,
            "CD_ELEICAO": ["1"] * n,
            "SG_UE": ["01234"] * n,
            "SQ_CANDIDATO": [f"{i:012d}" for i in range(n)],
            "NR_CPF_CANDIDATO": codes,
            "DS_EMAIL": codes,
            "DT_NASCIMENTO": ["01/07/1970"] * n,
        }
    )
    out = harmonise(df)
    assert out["nr_cpf_candidato"].null_count() == n
    assert out["email"].null_count() == n
    assert out["sg_ue"][0] == "01234"
    assert out["dt_nascimento"][0] == date(1970, 7, 1)


def test_email_columns_become_one():
    assert snake("NM_EMAIL") == snake("DS_EMAIL") == "email"
    assert snake("SQ_CANDIDATO") == "sq_candidato"


# --- Done when 4: ethnicity


def test_2024_ethnicity_comes_from_the_complementary_file(built):
    _, _, df = built
    names = df.filter(pl.col("ano_eleicao") == 2024)["ds_etnia_indigena"].drop_nulls().to_list()
    assert "KAINGANG" in names
    assert "MUNDURUKÚ" in names
    # not filled before 2020, and "-3"/"-4" in 2020 are null
    assert df.filter(pl.col("ano_eleicao") < 2020)["ds_etnia_indigena"].is_null().all()
    assert df.filter(pl.col("ano_eleicao") == 2020)["ds_etnia_indigena"].is_null().all()


# --- Done when 5: supplementary elections


def test_supplementary_rows_have_their_own_cd_eleicao(built):
    _, _, df = built
    sup = df.filter(pl.col("nm_tipo_eleicao").str.contains("SUPLEMENTAR"))
    assert sup.height > 0
    for y in sup["ano_eleicao"].unique().to_list():
        ordinary = df.filter(
            (pl.col("ano_eleicao") == y) & ~pl.col("nm_tipo_eleicao").str.contains("SUPLEMENTAR")
        )
        sup_y = sup.filter(pl.col("ano_eleicao") == y)
        assert set(sup_y["cd_eleicao"]).isdisjoint(set(ordinary["cd_eleicao"]))
        assert set(sup_y["cd_tipo_eleicao"]).isdisjoint(set(ordinary["cd_tipo_eleicao"]))


# --- Done when 6: hash and idempotence


def test_changing_one_input_sha_changes_the_output_path(built, tmp_path):
    _, out, _ = built
    store = MemoryStore()
    changed = stage(store, state_files=("consulta_cand_2008",))
    other = run(store, changed, tmp_path)
    assert other["gcs_prefix"] != out["gcs_prefix"]
    assert other["gcs_prefix"].startswith(DERIVED)
    assert other["files"][0]["path"] == other["gcs_prefix"] + "candidates.parquet"


def test_same_inputs_give_the_same_path(built, tmp_path):
    _, out, _ = built
    store = MemoryStore()
    again = run(store, stage(store), tmp_path)
    assert again["gcs_prefix"] == out["gcs_prefix"]


def test_second_build_is_unchanged_and_writes_nothing(tmp_path):
    store = MemoryStore()
    manifest = stage(store)
    first = run(store, manifest, tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = store.list("")
    assert first["gcs_prefix"] + MANIFEST_NAME in before
    second = run(store, manifest, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert store.list("") == before


def test_a_zip_that_differs_from_its_manifest_sha_is_refused(tmp_path):
    store = MemoryStore()
    manifest = stage(store)
    manifest["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="sha256"):
        run(store, manifest, tmp_path)
    assert store.list(DERIVED) == []


# --- Done when 7: checks


def test_row_count_check_raises():
    df = pl.DataFrame(
        {"ano_eleicao": [2024], "cd_eleicao": [1], "sg_ue": ["1"], "sq_candidato": ["1"]}
    )
    check(df, 1)
    with pytest.raises(BuildError, match="rows built"):
        check(df, 2)


def test_uniqueness_check_raises_on_a_repeated_candidacy(tmp_path):
    data = fixture("consulta_cand_2024")
    store = MemoryStore()
    manifest = stage(
        store,
        overrides={"consulta_cand_2024": with_line_changed(data, index=0, field=None, value=None)},
    )
    with pytest.raises(BuildError, match="repeat"):
        run(store, manifest, tmp_path)


def test_same_sq_in_two_municipalities_is_accepted_in_2000(tmp_path):
    data = fixture("consulta_cand_2000")
    header = next(csv.reader(io.StringIO(data.decode("latin-1")), delimiter=";"))
    sg_ue = header.index("SG_UE")
    sq = header.index("SQ_CANDIDATO")
    changed = with_line_changed(data, index=0, field=sg_ue, value=b'"09999"')
    lines = [ln for ln in changed.split(b"\r\n") if ln]
    assert lines[1].split(b";")[sq] == lines[-1].split(b";")[sq]
    store = MemoryStore()
    out = run(store, stage(store, overrides={"consulta_cand_2000": changed}), tmp_path)
    df = read_output(store, out).filter(pl.col("ano_eleicao") == 2000)
    assert df.height == records(data) + 1
    assert df["sg_ue"].is_in(["05436", "09999"]).all()
    assert df.filter(pl.col("sq_candidato") == df["sq_candidato"][0]).height == 2


def test_join_check_raises_on_an_orphan_complementary_row(tmp_path):
    data = fixture("consulta_cand_complementar_2024")
    header = next(csv.reader(io.StringIO(data.decode("latin-1")), delimiter=";"))
    orphan = with_line_changed(data, index=0, field=header.index("SQ_CANDIDATO"), value=b"1")
    store = MemoryStore()
    manifest = stage(store, overrides={"consulta_cand_complementar_2024": orphan})
    with pytest.raises(BuildError, match="match no candidacy"):
        run(store, manifest, tmp_path)


def test_join_check_raises_on_a_repeated_complementary_row():
    keys = {"ano_eleicao": [2024, 2024], "cd_eleicao": [1, 1], "sq_candidato": ["1", "1"]}
    df = pl.DataFrame({**keys, "sg_ue": ["1", "1"]})
    comp = pl.DataFrame(
        {
            **keys,
            "cd_etnia_indigena": ["1", "1"],
            "ds_etnia_indigena": ["A", "A"],
            "st_quilombola": ["N", "N"],
        }
    )
    with pytest.raises(BuildError, match="repeats"):
        join_complementar(df, comp)


# --- Done when 8: contract


def contract_columns() -> list[tuple[str, str]]:
    rows = re.findall(r"^\| `(\w+)` \| (int|date|text) \|", CONTRACT.read_text("utf-8"), re.M)
    return [(name, kind) for name, kind in rows]


def test_contract_lists_every_output_column_in_order_with_its_type(built):
    _, _, df = built
    kinds = {pl.Int32: "int", pl.Date: "date", pl.String: "text"}
    actual = [(c, kinds[df.schema[c]]) for c in df.columns]
    assert contract_columns() == actual
    assert all(df.schema[c] == dtype_of(c) for c in df.columns)
