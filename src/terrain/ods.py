"""Read one sheet of an ODS spreadsheet into rows of text, with the standard library only.

An ODS file is a zip whose `content.xml` holds the sheets. ODS stores runs of
identical cells and rows as one element with a `number-*-repeated` count, and
exports often end every row with thousands of empty repeated cells. Empty
repeats are expanded up to `max_repeat`; a non-empty repeat above the cap
raises, because cutting it would lose data.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
_TABLE = f"{{{NS['table']}}}table"
_ROW = f"{{{NS['table']}}}table-row"
_CELLS = {f"{{{NS['table']}}}table-cell", f"{{{NS['table']}}}covered-table-cell"}
_NAME = f"{{{NS['table']}}}name"
_COLS_REPEATED = f"{{{NS['table']}}}number-columns-repeated"
_ROWS_REPEATED = f"{{{NS['table']}}}number-rows-repeated"
_PARAGRAPH = f"{{{NS['text']}}}p"

DEFAULT_MAX_REPEAT = 1000


class OdsError(ValueError):
    """Raised when a file is not a readable ODS or a repeat exceeds the cap."""


def _cell_text(cell: ET.Element) -> str:
    return "\n".join("".join(p.itertext()) for p in cell.iter(_PARAGRAPH))


def _repeat(element: ET.Element, attribute: str) -> int:
    try:
        return max(1, int(element.get(attribute, "1")))
    except ValueError as err:
        raise OdsError(f"bad {attribute} value: {element.get(attribute)!r}") from err


def _row_cells(row: ET.Element, max_repeat: int) -> list[str]:
    cells: list[str] = []
    for cell in row:
        if cell.tag not in _CELLS:
            continue
        text = _cell_text(cell)
        n = _repeat(cell, _COLS_REPEATED)
        if text and n > max_repeat:
            raise OdsError(f"a non-empty cell is repeated {n} times (cap {max_repeat})")
        cells.extend([text] * min(n, max_repeat))
    while cells and cells[-1] == "":
        cells.pop()
    return cells


def read_sheet(
    source: str | Path | bytes, sheet: str | None = None, max_repeat: int = DEFAULT_MAX_REPEAT
) -> list[list[str]]:
    """Rows of the sheet called `sheet` (the first sheet if None), every cell as text.

    Trailing empty cells and trailing empty rows are dropped. A run of empty
    rows or cells inside the sheet is cut to `max_repeat`.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source) as zf:
            root = ET.fromstring(zf.read("content.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as err:
        raise OdsError(f"not a readable ODS file: {err}") from err

    tables = list(root.iter(_TABLE))
    if sheet is None:
        chosen = tables[0] if tables else None
    else:
        chosen = next((t for t in tables if t.get(_NAME) == sheet), None)
    if chosen is None:
        raise OdsError(f"sheet not found: {sheet!r}")

    rows: list[list[str]] = []
    for row in chosen.iter(_ROW):
        cells = _row_cells(row, max_repeat)
        n = _repeat(row, _ROWS_REPEATED)
        if cells and n > max_repeat:
            raise OdsError(f"a non-empty row is repeated {n} times (cap {max_repeat})")
        rows.extend([list(cells) for _ in range(min(n, max_repeat))])
    while rows and not rows[-1]:
        rows.pop()
    return rows
