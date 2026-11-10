import hashlib
import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds.non_amazon_municipalities import (
    CODE_MODULES,
    OUTPUT_NAME,
    POPULATION_FILE,
    BuildError,
    build,
    input_hash,
    parse_count,
    read_population,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest
from terrain.split import population_strata, read_population_municipalities
from terrain.storage import MemoryStore

DERIVED = dataset("non_amazon_municipalities")["derived"]
MUN_DERIVED = "data/derived/municipalities/0123456789abcdef/"
POP_RAW = "data/raw/ibge/population/2026-11-10/"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

HEADER = [
    "",
    "UF",
    "COD. UF",
    "COD. MUNIC",
    "NOME DO MUNICÍPIO",
    "População Município 2010\n(Sinopse)",
    "População 2010 (Alterações de Limites até 2022)1",
    "População Censo 2022",
]

# Synthetic municipalities: (code, uf, legal_amazon, 2010 population on 2022 boundaries).
# 5101837 stands for a Legal Amazon municipality created after the census.
MUNICIPALITIES = [
    ("1100015", "RO", True, "24 392"),
    ("2100055", "MA", True, "29 044"),
    ("2100105", "MA", False, "6 102"),
    ("2200053", "PI", False, "6 303"),
    ("2200103", "PI", False, "12 199"),
    ("2200202", "PI", False, "5 020"),
    ("3100104", "MG", False, "6 960"),
    ("3550308", "SP", False, "11 253 503"),
    ("5101837", "MT", True, None),
    ("5300108", "DF", False, "2 570 160"),
]


def _xml_cell(text: str) -> str:
    if not text:
        return "<table:table-cell />"
    paragraphs = "".join(f"<text:p>{line}</text:p>" for line in text.split("\n"))
    return f"<table:table-cell>{paragraphs}</table:table-cell>"


def make_ods(rows: list[list[str]]) -> bytes:
    body = "".join(
        "<table:table-row>" + "".join(_xml_cell(c) for c in r) + "</table:table-row>" for r in rows
    )
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<office:body><office:spreadsheet><table:table table:name="Municípios">'
        f"{body}</table:table></office:spreadsheet></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype", date_time=FIXED_TIME),
            "application/vnd.oasis.opendocument.spreadsheet",
        )
        zf.writestr(zipfile.ZipInfo("content.xml", date_time=FIXED_TIME), xml)
    return buf.getvalue()


def population_rows(municipalities=MUNICIPALITIES) -> list[list[str]]:
    rows = [
        [],
        ["", "Censo Demográfico 2022: População e Domicílios - Primeiros Resultados"],
        HEADER,
    ]
    for code, uf, _, pop in municipalities:
        if pop is not None:
            rows.append(["", uf, code[:2], code[2:], "Nome", pop, pop, "1 000"])
    rows += [[], ["", "Nota: as populações de 2010 foram reconstituídas."], ["", "Fonte: IBGE."]]
    return rows


def municipalities_frame(municipalities=MUNICIPALITIES) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cd_ibge": [m[0] for m in municipalities],
            "cd_tse": ["00000"] * len(municipalities),
            "uf": [m[1] for m in municipalities],
            "legal_amazon": [m[2] for m in municipalities],
        }
    )


def stage(store: MemoryStore, pop_rows=None, table=None) -> tuple[dict, dict]:
    def put(path: str, data: bytes) -> dict:
        store.create(path, data)
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    buf = io.BytesIO()
    (table if table is not None else municipalities_frame()).write_parquet(buf)
    mun = {
        "dataset": "municipalities",
        "gcs_prefix": MUN_DERIVED,
        "files": [
            put(MUN_DERIVED + "municipalities.parquet", buf.getvalue()),
            put(MUN_DERIVED + "legal_amazon.csv", b"code_ibge,uf\n"),
        ],
    }
    ods = make_ods(pop_rows if pop_rows is not None else population_rows())
    pop = {
        "dataset": "ibge_population_2022",
        "gcs_prefix": POP_RAW,
        "files": [put(POP_RAW + POPULATION_FILE, ods)],
    }
    return mun, pop


def run(store, manifests, tmp_path: Path) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc")


def output(store: MemoryStore, manifest: dict) -> str:
    return store.read_bytes(manifest["gcs_prefix"] + OUTPUT_NAME).decode("utf-8")


def test_writes_every_municipality_outside_the_legal_amazon(tmp_path):
    store = MemoryStore()
    out = run(store, stage(store), tmp_path)
    assert out["status"] == "created"
    assert validate_manifest(out, stage="build", dataset="non_amazon_municipalities") == []
    assert output(store, out) == (
        "code_ibge,uf,population\n"
        "2100105,MA,6102\n"
        "2200053,PI,6303\n"
        "2200103,PI,12199\n"
        "2200202,PI,5020\n"
        "3100104,MG,6960\n"
        "3550308,SP,11253503\n"
        "5300108,DF,2570160\n"
    )
    assert "non_amazon=7" in out["notes"]
    assert "legal_amazon_without_population=['5101837']" in out["notes"]
    assert "PI=3" in out["notes"]


def test_output_is_the_input_seal_split_reads(tmp_path):
    store = MemoryStore()
    out = run(store, stage(store), tmp_path)
    rows = read_population_municipalities(output(store, out))
    strata = dict(population_strata(rows))
    assert strata["2200202"] == "PI-T1" and strata["2200053"] == "PI-T2"
    assert strata["2200103"] == "PI-T3"


def test_second_run_is_unchanged(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    first = run(store, manifests, tmp_path)
    store.create(first["gcs_prefix"] + MANIFEST_NAME, b'{"gcs_prefix": "x", "status": "created"}')
    assert run(store, manifests, tmp_path)["status"] == "unchanged"


@pytest.mark.parametrize(
    ("text", "value"),
    [("24 392", 24392), ("11 253 503", 11253503), ("1.234", 1234), ("7", 7)],
)
def test_parse_count(text, value):
    assert parse_count(text) == value


@pytest.mark.parametrize("text", ["", "-", "12,5", "n/a"])
def test_parse_count_rejects_non_numbers(text):
    with pytest.raises(BuildError):
        parse_count(text)


def _replace(rows, code, column, value):
    for r in rows:
        if len(r) > 3 and r[2] + r[3] == code:
            r[column] = value
    return rows


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda rows: _replace(rows, "2200053", 6, "x"), "not a whole number"),
        (lambda rows: _replace(rows, "2200053", 6, "0"), "has population 0"),
        (lambda rows: _replace(rows, "2200053", 1, "CE"), "listed under"),
        (lambda rows: rows + [rows[3]], "repeated code"),
        (lambda rows: [r for r in rows if r is not rows[2]], "no header row"),
        (lambda rows: rows[:2] + [HEADER[:6] + HEADER[7:]] + rows[3:], "expected one column"),
    ],
)
def test_bad_population_table_stops_the_build(tmp_path, change, message):
    store = MemoryStore()
    manifests = stage(store, pop_rows=change(population_rows()))
    with pytest.raises(BuildError, match=message):
        run(store, manifests, tmp_path)
    assert not [p for p in store.list(DERIVED)]


def test_a_non_amazon_municipality_without_population_stops_the_build(tmp_path):
    store = MemoryStore()
    rows = [r for r in population_rows() if not (len(r) > 3 and r[2] + r[3] == "3100104")]
    with pytest.raises(BuildError, match="have no population: \\['3100104'\\]"):
        run(store, stage(store, pop_rows=rows), tmp_path)


def test_a_population_code_that_is_not_a_municipality_stops_the_build(tmp_path):
    store = MemoryStore()
    table = municipalities_frame().filter(pl.col("cd_ibge") != "3100104")
    with pytest.raises(BuildError, match="not municipalities: \\['3100104'\\]"):
        run(store, stage(store, table=table), tmp_path)


def test_a_file_that_does_not_match_its_manifest_stops_the_build(tmp_path):
    store = MemoryStore()
    mun, pop = stage(store)
    pop["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="does not match"):
        run(store, (mun, pop), tmp_path)


def test_output_path_hashes_inputs_and_code():
    files = [{"sha256": "a"}, {"sha256": "b"}]
    assert input_hash(files) == input_hash(list(reversed(files)))
    assert input_hash(files, ["x"]) != input_hash(files, ["y"])
    assert {p.name for p in CODE_MODULES} == {
        "non_amazon_municipalities.py",
        "ods.py",
        "municipalities.py",
    }


def test_read_population_skips_titles_and_notes():
    found = read_population(make_ods(population_rows()))
    assert len(found) == 9
    assert found["3550308"] == ("SP", 11253503)


def test_catalog_names_the_file_the_build_reads():
    files = dataset("ibge_population_2022")["acquire"]["files"]
    assert [f["url"].rsplit("/", 1)[-1] for f in files] == [POPULATION_FILE]
