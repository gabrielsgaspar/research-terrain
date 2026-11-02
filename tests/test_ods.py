import io
import zipfile
from pathlib import Path

import pytest

from terrain.ods import OdsError, read_sheet

IBGE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "ibge"

HEAD = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
    "<office:body><office:spreadsheet>"
)
TAIL = "</office:spreadsheet></office:body></office:document-content>"


def cell(text: str = "", repeat: int | None = None) -> str:
    attr = f' table:number-columns-repeated="{repeat}"' if repeat else ""
    if not text:
        return f"<table:table-cell{attr} />"
    return f"<table:table-cell{attr}><text:p>{text}</text:p></table:table-cell>"


def row(*cells: str, repeat: int | None = None) -> str:
    attr = f' table:number-rows-repeated="{repeat}"' if repeat else ""
    return f"<table:table-row{attr}>{''.join(cells)}</table:table-row>"


def sheet(name: str, *rows: str) -> str:
    return f'<table:table table:name="{name}">{"".join(rows)}</table:table>'


def make_ods(*tables: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype", date_time=(2024, 1, 1, 0, 0, 0)),
            "application/vnd.oasis.opendocument.spreadsheet",
        )
        zf.writestr(
            zipfile.ZipInfo("content.xml", date_time=(2024, 1, 1, 0, 0, 0)),
            HEAD + "".join(tables) + TAIL,
        )
    return buf.getvalue()


def test_reads_text_and_drops_trailing_empty_cells_and_rows():
    data = make_ods(
        sheet(
            "A",
            row(cell("a"), cell("b"), cell(repeat=16000)),
            row(cell("c"), cell(), cell("d"), cell(repeat=5000)),
            row(cell(repeat=16384), repeat=3),
        )
    )
    assert read_sheet(data) == [["a", "b"], ["c", "", "d"]]


def test_repeated_columns_and_rows_are_expanded():
    data = make_ods(sheet("A", row(cell("x", repeat=3), cell("y")), row(cell("z"), repeat=2)))
    assert read_sheet(data) == [["x", "x", "x", "y"], ["z"], ["z"]]


def test_empty_rows_in_the_middle_are_kept():
    data = make_ods(sheet("A", row(cell("a")), row(cell(repeat=4), repeat=2), row(cell("b"))))
    assert read_sheet(data) == [["a"], [], [], ["b"]]


def test_empty_repeats_are_cut_to_the_cap():
    data = make_ods(
        sheet("A", row(cell("a"), cell(repeat=500), cell("b")), row(cell(), repeat=500))
    )
    assert read_sheet(data, max_repeat=10) == [["a"] + [""] * 10 + ["b"]]


def test_a_non_empty_repeat_above_the_cap_raises():
    with pytest.raises(OdsError, match="repeated"):
        read_sheet(make_ods(sheet("A", row(cell("x", repeat=50)))), max_repeat=10)
    with pytest.raises(OdsError, match="repeated"):
        read_sheet(make_ods(sheet("A", row(cell("x"), repeat=50))), max_repeat=10)


def test_sheet_by_name_and_first_sheet_by_default():
    data = make_ods(sheet("One", row(cell("1"))), sheet("Two", row(cell("2"))))
    assert read_sheet(data) == [["1"]]
    assert read_sheet(data, sheet="Two") == [["2"]]
    with pytest.raises(OdsError, match="sheet not found"):
        read_sheet(data, sheet="Three")


def test_reads_from_a_path(tmp_path):
    path = tmp_path / "x.ods"
    path.write_bytes(make_ods(sheet("A", row(cell("a")))))
    assert read_sheet(path) == [["a"]]


def test_not_an_ods_raises():
    with pytest.raises(OdsError):
        read_sheet(b"not a zip")


def test_the_ibge_fixtures_read():
    for name, header in (
        ("RELATORIO_DTB_BRASIL_2024_MUNICIPIOS", "Código Município Completo"),
        ("Municipios_da_Amazonia_Legal_2024", "CD_MUN"),
    ):
        xml = (IBGE / f"{name}.content.xml").read_bytes()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(zipfile.ZipInfo("content.xml", date_time=(2024, 1, 1, 0, 0, 0)), xml)
        rows = read_sheet(buf.getvalue())
        assert any(header in r for r in rows)
        assert max(len(r) for r in rows) < 100
