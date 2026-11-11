import hashlib
import io
import json
import math
import zipfile
from dataclasses import replace
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import polars as pl
import pytest
import shapefile
import shapely
from shapely.geometry import Polygon, shape

from terrain import grid
from terrain.builds import gold_exposure as ge
from terrain.builds.gold_exposure import (
    BuildError,
    Limits,
    annual_prices,
    build,
    input_hash,
    is_gold_occurrence,
    read_prices_xlsx,
)
from terrain.manifest import MANIFEST_NAME, check_manifest, write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/gold_exposure/"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)
A, B, C = "1100015", "1100023", "5100102"
LAGOON = "4300001"
APPROX = {"rel": 1e-6, "abs": 1e-9}

# Municipalities are 10 km squares in Albers km: A x 5000-5010, B x 5010-5020, C x 5020-5030,
# all y 10000-10010. Every polygon below is built from km coordinates, so its area is exact.
LIMITS = Limits(
    min_municipalities=3,
    min_sgb=7,
    min_gold_occurrences=6,
    min_anm=10,
    min_gold_pre2000=3,
    min_price_years=3,
    required_years=(2022, 2023, 2024),
    base_year=2024,
)


def km_polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
    xs = [x0 + (x1 - x0) * i / 20 for i in range(21)]
    ys = [y0 + (y1 - y0) * i / 20 for i in range(21)]
    ring_km = (
        [(x, y0) for x in xs]
        + [(x1, y) for y in ys[1:]]
        + [(x, y1) for x in reversed(xs[:-1])]
        + [(x0, y) for y in reversed(ys[:-1])]
    )
    lon, lat = grid.km_to_lonlat([p[0] for p in ring_km], [p[1] for p in ring_km])
    ring = [[float(a), float(b)] for a, b in zip(lon, lat, strict=True)]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def wkb(*box: float) -> bytes:
    return shape(km_polygon(*box)).wkb


def bowtie_wkb(x0: float, y0: float, x1: float, y1: float) -> bytes:
    km = [(x0, y0), (x1, y1), (x1, y0), (x0, y1), (x0, y0)]
    lon, lat = grid.km_to_lonlat([p[0] for p in km], [p[1] for p in km])
    polygon = Polygon(list(zip(lon.tolist(), lat.tolist(), strict=True)))
    assert not polygon.is_valid
    return polygon.wkb


def at(x: float, y: float) -> tuple[str, str]:
    lon, lat = grid.km_to_lonlat([x], [y])
    return repr(float(lon[0])), repr(float(lat[0]))


def zipped(work: Path, stem: str, fields: list[tuple[str, int]], rows: list[tuple]) -> bytes:
    """A zip with one shapefile; each row is (box, *attributes)."""
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / stem), encoding="utf-8")
    for name, size in fields:
        writer.field(name, "C", size, 0)
    for box, *attributes in rows:
        writer.shape(km_polygon(*box))
        writer.record(*attributes)
    writer.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ext in ("shp", "shx", "dbf"):
            name = f"{stem}.{ext}"
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), (work / name).read_bytes())
    return buf.getvalue()


def boundaries_zip(work: Path) -> bytes:
    boxes = ((A, (5000, 10000, 5010, 10010)), (B, (5010, 10000, 5020, 10010)))
    rows = [(box, code) for code, box in boxes]
    rows += [((5020, 10000, 5030, 10010), C), ((6000, 10000, 6001, 10001), LAGOON)]
    return zipped(work, "BR_Municipios_2024", [("CD_MUN", 7)], rows)


def cnfp_zip(work: Path) -> bytes:
    rows = [
        ((5000, 10005, 5005, 10010), "TI", "TIPO A", "1990"),  # Indigenous: 25 km² of A
        ((5010, 10000, 5020, 10010), "FLONA", "TIPO A", "1990"),  # not Indigenous
    ]
    fields = [("categoria", 20), ("tipo", 10), ("anocriacao", 10)]
    return zipped(work, "CNFP_2025", fields, rows)


def sgb_csv() -> bytes:
    header = (
        "FID,municipio,uf,data_cadastro,provincia,status_economico,importancia,"
        "situacao_mina,situacao_garimpo,substancias,longitude,latitude"
    )
    points = [
        ("Ouro", "Garimpo", *at(5002, 10007)),  # A, inside the Indigenous land
        ("Diamante, Ouro", "Mina", *at(5015, 10002)),  # B
        ("Ouro Preto", "Garimpo", *at(5002, 10002)),  # a name, not a substance
        ("Ouro", "Mina", *at(6000, 10000)),  # outside every polygon
        ("Ouro", "Mina", "", ""),  # no coordinates
        ("Ouro", "Mina", "abc", "-12"),  # non-numeric
        ("Cobre,  OURO ", "GARIMPO", *at(5016, 10003)),  # B
    ]
    lines = [header]
    for i, (subs, status, lon, lat) in enumerate(points):
        lines.append(f'{i},Town,RO,2020-01-01,Prov,{status},Low,,,"{subs}",{lon},{lat}')
    return ("\n".join(lines) + "\n").encode("utf-8")


def anm_parquet() -> bytes:
    titles = [
        # (subs, fase, ano, geometry)
        ("OURO", "LAVRA GARIMPEIRA", 1990, wkb(5000, 10000, 5006, 10005)),  # 30 km²
        ("MINÉRIO DE OURO", "CONCESSÃO DE LAVRA", 1995, wkb(5004, 10000, 5008, 10005)),  # 20 km²
        ("OURO NATIVO", "AUTORIZAÇÃO DE PESQUISA", 2010, wkb(5008, 10006, 5012, 10008)),  # A and B
        ("AREIA", "LICENCIAMENTO", 1980, wkb(5020, 10000, 5025, 10002)),  # 10 km² of C
        ("OURO", "AUTORIZAÇÃO DE PESQUISA", 1850, wkb(5021, 10001, 5022, 10002)),  # invalid year
        ("OURO", "AUTORIZAÇÃO DE PESQUISA", 2005, bowtie_wkb(5026, 10005, 5028, 10007)),
        ("FERRO", "LAVRA GARIMPEIRA", 1970, wkb(5000, 10000, 5001, 10001)),  # not gold
        ("OURO PIGMENTO", "LAVRA GARIMPEIRA", 1970, wkb(5000, 10008, 5002, 10010)),  # not gold
        ("OURO", "LAVRA GARIMPEIRA", 1990, None),  # gold without a polygon
        ("OURO", "AUTORIZAÇÃO DE PESQUISA", None, wkb(5012, 10000, 5014, 10002)),  # no year
    ]
    frame = pl.DataFrame(
        {
            "objectid": list(range(len(titles))),
            "processo": [f"p{i}" for i in range(len(titles))],
            "numero": [i for i in range(len(titles))],
            "ano": [t[2] for t in titles],
            "fase": [t[1] for t in titles],
            "subs": [t[0] for t in titles],
            "uso": ["x"] * len(titles),
            "area_ha": [1.0] * len(titles),
            "uf": ["RO"] * len(titles),
            "geometry_wkb": pl.Series([t[3] for t in titles], dtype=pl.Binary),
        },
        schema_overrides={"ano": pl.Int64},
    )
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def municipalities_parquet(extra: list[str] | None = None) -> bytes:
    codes = [(A, "RO", True), (B, "RO", True), (C, "MT", False)]
    codes += [(c, "XX", False) for c in extra or []]
    frame = pl.DataFrame(
        {
            "cd_ibge": [c[0] for c in codes],
            "uf": [c[1] for c in codes],
            "legal_amazon": [c[2] for c in codes],
        }
    )
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


# --- The workbook: three sheets, "Monthly Prices" is the third; strings are shared or inline.

SHEET_RELS = {
    "Description": "sheet1.xml",
    "Annual Prices": "sheet2.xml",
    "Monthly Prices": "sheet3.xml",
}


def price_rows() -> list[tuple[str, object, object]]:
    """(month, gold, soybeans); None is an empty cell and "…" a missing value."""
    gold = {2021: 900, 2022: 1000, 2023: 2000, 2024: 2500, 2025: 3000}
    soy = {2021: 500, 2022: 600, 2023: 400, 2024: 300, 2025: 350}
    rows: list[tuple[str, object, object]] = []
    for year in gold:
        for month in range(1, 13):
            if year == 2025 and month == 12:
                continue  # 11 months
            value = "…" if (year, month) == (2021, 12) else gold[year]
            rows.append((f"{year}M{month:02d}", value, soy[year]))
    rows.append(("2025M12", None, None))  # an empty row: month present, both values missing
    return rows


def sheet_xml(rows: dict[int, list[tuple[str, tuple[str, object]]]], strings: list[str]) -> str:
    out = []
    for number in sorted(rows):
        cells = []
        for column, (kind, value) in rows[number]:
            ref = f"{column}{number}"
            if kind == "shared":
                if value not in strings:
                    strings.append(str(value))
                cells.append(f'<c r="{ref}" t="s"><v>{strings.index(str(value))}</v></c>')
            elif kind == "inline":
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            elif kind == "empty":
                cells.append(f'<c r="{ref}"/>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        out.append(f'<row r="{number}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    return f'<worksheet xmlns="{ns}"><sheetData>{"".join(out)}</sheetData></worksheet>'


def monthly_sheet(
    strings: list[str], rows: list[tuple[str, object, object]], gold_header: str = "Gold"
) -> str:
    sheet: dict[int, list[tuple[str, tuple[str, object]]]] = {
        5: [
            ("B", ("shared", "Crude oil, average")),
            ("C", ("inline", gold_header)),
            ("D", ("shared", "Soybeans")),
        ],
        6: [
            ("B", ("shared", "($/bbl)")),
            ("C", ("shared", "($/toz)")),
            ("D", ("shared", "($/mt)")),
        ],
    }
    for i, (month, gold, soy) in enumerate(rows):
        cells: list[tuple[str, tuple[str, object]]] = [("A", ("shared", month))]
        for column, value in (("C", gold), ("D", soy)):
            if value is None:
                cells.append((column, ("empty", None)))
            elif isinstance(value, str):
                cells.append((column, ("shared", value)))
            else:
                cells.append((column, ("number", value)))
        sheet[7 + i] = [("B", ("number", 70.0)), *cells]
    return sheet_xml(sheet, strings)


def price_xlsx(gold_header: str = "Gold") -> bytes:
    strings: list[str] = []
    decoy = {
        5: [("C", ("shared", "Gold")), ("D", ("shared", "Soybeans"))],
        7: [("A", ("shared", "2022M01")), ("C", ("number", 1)), ("D", ("number", 1))],
    }
    sheets = {
        "sheet1.xml": sheet_xml({1: [("A", ("shared", "Description"))]}, strings),
        "sheet2.xml": sheet_xml(decoy, strings),
        "sheet3.xml": monthly_sheet(strings, price_rows(), gold_header),
    }
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rid = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    sheet_list = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i + 10}"/>'
        for i, name in enumerate(SHEET_RELS, 1)
    )
    workbook = f'<workbook xmlns="{ns}" xmlns:r="{rid}"><sheets>{sheet_list}</sheets></workbook>'
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    targets = [
        f'<Relationship Id="rId{i + 10}" Type="worksheet" Target="worksheets/{target}"/>'
        for i, target in enumerate(SHEET_RELS.values(), 1)
    ]
    targets.append('<Relationship Id="rId1" Type="styles" Target="styles.xml"/>')
    rels = f'<Relationships xmlns="{rel_ns}">{"".join(targets)}</Relationships>'
    shared = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    members = {
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": rels,
        "xl/sharedStrings.xml": f'<sst xmlns="{ns}">{shared}</sst>',
        **{f"xl/worksheets/{name}": body for name, body in sheets.items()},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), body.encode("utf-8"))
    return buf.getvalue()


def cpi_csv() -> bytes:
    cpi = {2021: 90, 2022: 100, 2023: 110, 2024: 125, 2025: 130}
    lines = ["observation_date,CPIAUCSL"]
    for year, value in cpi.items():
        for month in range(1, 13 if year < 2025 else 11):
            lines.append(f"{year}-{month:02d}-01,{value}")
    return ("\n".join(lines) + "\n").encode("utf-8")


class Inputs:
    """A store holding every input, and the six manifests the build reads."""

    def __init__(self, work: Path, **overrides: bytes) -> None:
        self.store = MemoryStore()
        self.work = work
        self.tmp = work / "tmp"
        self.tmp.mkdir(parents=True)
        files = {
            "anm": ("data/raw/anm/", "sigmine_active.parquet", anm_parquet()),
            "sgb": ("data/raw/sgb/", "sgb_ocorrencias.csv", sgb_csv()),
            "xlsx": ("data/raw/prices/", "CMO-Historical-Data-Monthly.xlsx", price_xlsx()),
            "cpi": ("data/raw/prices/", "CPIAUCSL.csv", cpi_csv()),
            "bounds": ("data/raw/ibge/", "BR_Municipios_2024.zip", boundaries_zip(work / "b")),
            "munis": (
                "data/derived/municipalities/",
                "municipalities.parquet",
                municipalities_parquet(),
            ),
            "cnfp": ("data/raw/cnfp/", "CNFP_2025.zip", cnfp_zip(work / "c")),
        }
        self.manifests: dict[str, dict] = {}
        for key, (folder, name, data) in files.items():
            data = overrides.get(key, data)
            stage = "build" if key == "munis" else "acquire"
            group = {"cpi": "xlsx"}.get(key, key)
            manifest = self.manifests.setdefault(
                group,
                {"dataset": group, "stage": stage, "gcs_prefix": folder, "files": []},
            )
            self.store.create(folder + name, data)
            manifest["files"].append(
                {"path": folder + name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": 1}
            )

    def build(self, **kwargs):
        m = self.manifests
        defaults = {"limits": LIMITS, "created_at": "2026-11-11T00:00:00+00:00"}
        return build(
            self.store,
            m["anm"],
            m["sgb"],
            m["xlsx"],
            m["bounds"],
            m["munis"],
            m["cnfp"],
            derived_root=DERIVED,
            tmp_dir=self.tmp,
            code_commit="abc",
            **{**defaults, **kwargs},
        )

    def uploaded(self) -> list[str]:
        return self.store.list(DERIVED)


@pytest.fixture
def inputs(tmp_path: Path) -> Inputs:
    return Inputs(tmp_path)


def read(inputs: Inputs, manifest: dict, name: str) -> pl.DataFrame:
    data = inputs.store.read_bytes(manifest["gcs_prefix"] + name)
    return pl.read_parquet(io.BytesIO(data))


# --- 1. Counts, shares, centroids and real prices


def test_exposure_counts_shares_and_centroids(inputs):
    manifest = inputs.build()
    check_manifest(manifest, stage="build", dataset="gold_exposure")
    table = read(inputs, manifest, "gold_exposure.parquet")
    assert table["cd_ibge"].to_list() == [A, B, C]
    rows = {r["cd_ibge"]: r for r in table.iter_rows(named=True)}
    a, b, c = rows[A], rows[B], rows[C]

    for row in (a, b, c):
        assert row["area_km2"] == pytest.approx(100.0, **APPROX)
    assert (a["centroid_x_km"], a["centroid_y_km"]) == pytest.approx((5005, 10005), **APPROX)
    assert (b["centroid_x_km"], b["centroid_y_km"]) == pytest.approx((5015, 10005), **APPROX)
    assert (c["centroid_x_km"], c["centroid_y_km"]) == pytest.approx((5025, 10005), **APPROX)
    assert (a["uf"], c["uf"], a["legal_amazon"], c["legal_amazon"]) == ("RO", "MT", True, False)

    # Geology: "Ouro" and "Diamante, Ouro" count, "Ouro Preto" does not; the outside point and
    # the two without usable coordinates are dropped.
    assert (a["geo_n_gold"], b["geo_n_gold"], c["geo_n_gold"]) == (1, 2, 0)
    assert a["geo_gold_per_km2"] == pytest.approx(0.01, **APPROX)
    assert (a["geo_exposed"], b["geo_exposed"], c["geo_exposed"]) == (True, True, False)
    assert (a["geo_n_gold_garimpo"], b["geo_n_gold_garimpo"]) == (1, 1)
    assert (a["geo_n_gold_indigenous"], b["geo_n_gold_indigenous"]) == (1, 0)
    assert a["geo_gold_indigenous_share"] == 1.0
    assert b["geo_gold_indigenous_share"] == 0.0
    assert c["geo_gold_indigenous_share"] is None

    # Titles: T3 counts in A and B; the title without a polygon counts nowhere.
    assert (a["title_n_gold"], b["title_n_gold"], c["title_n_gold"]) == (3, 2, 2)
    assert (a["title_n_gold_dated"], b["title_n_gold_dated"], c["title_n_gold_dated"]) == (3, 1, 1)
    assert (a["title_n_gold_pre2000"], b["title_n_gold_pre2000"]) == (2, 0)
    assert (a["title_n_garimpo_pre2000"], b["title_n_garimpo_pre2000"]) == (1, 0)
    assert (a["title_exposed"], b["title_exposed"], c["title_exposed"]) == (True, False, False)
    # 30 + 20 km² with 10 km² in common: the overlap counts once.
    assert a["title_gold_pre2000_share"] == pytest.approx(0.4, **APPROX)
    assert a["title_garimpo_pre2000_share"] == pytest.approx(0.3, **APPROX)
    assert (a["title_sand_pre2000_share"], c["title_sand_pre2000_share"]) == pytest.approx(
        (0.0, 0.1), **APPROX
    )
    assert (b["title_gold_pre2000_share"], c["title_gold_pre2000_share"]) == (0.0, 0.0)
    assert (a["indigenous_share"], b["indigenous_share"]) == pytest.approx((0.25, 0.0), **APPROX)


def test_notes_count_drops_repairs_and_years(inputs):
    notes = inputs.build()["notes"]
    assert "geo_exposed by uf: RO=2" in notes
    assert "title_exposed by uf: RO=1" in notes
    assert "sgb_dropped_no_usable_coordinates=2 (gold: 2)" in notes
    assert "sgb_outside_every_polygon=1 (gold: 1)" in notes
    assert "anm_gold_and_sand_titles=1" in notes  # the bowtie
    assert "gold_and_sand_titles_without_geometry=1" in notes
    assert "price_years=2022-2024 (3 years)" in notes


def test_real_prices(inputs):
    prices = read(inputs, inputs.build(), "gold_prices.parquet")
    assert prices["year"].to_list() == [2022, 2023, 2024]
    row = {r["year"]: r for r in prices.iter_rows(named=True)}
    assert row[2022]["gold_usd"] == 1000 and row[2022]["soy_usd"] == 600 and row[2022]["cpi"] == 100
    assert row[2022]["gold_real"] == pytest.approx(1250)
    assert row[2023]["gold_real"] == pytest.approx(2000 * 125 / 110)
    assert row[2023]["soy_real"] == pytest.approx(400 * 125 / 110)
    assert row[2024]["gold_real"] == pytest.approx(2500)
    assert row[2024]["soy_real"] == pytest.approx(300)
    assert row[2022]["ln_gold_real"] == pytest.approx(math.log(1250))
    assert row[2022]["ln_soy_real"] == pytest.approx(math.log(750))
    assert {row[2022]["n_months_gold"], row[2022]["n_months_soy"], row[2022]["n_months_cpi"]} == {
        12
    }


def test_gold_occurrence_matches_items_not_words():
    assert is_gold_occurrence("Ouro")
    assert is_gold_occurrence("Diamante, Ouro")
    assert is_gold_occurrence("cobre ,  ÔURO ")
    assert not is_gold_occurrence("Ouro Preto")
    assert not is_gold_occurrence("Ouro-Preto, Cobre")
    assert not is_gold_occurrence(None)


# --- 2. The workbook


def test_sheet_is_found_by_name_not_by_file(tmp_path):
    path = tmp_path / "prices.xlsx"
    path.write_bytes(price_xlsx())
    with zipfile.ZipFile(path) as zf:
        assert "xl/worksheets/sheet2.xml" in zf.namelist()  # the decoy
    gold, soy = read_prices_xlsx(path)
    assert gold[(2022, 1)] == 1000  # not the decoy's 1
    assert soy[(2024, 6)] == 300


def test_ellipsis_and_empty_cells_are_missing_and_short_years_are_dropped(tmp_path):
    path = tmp_path / "prices.xlsx"
    path.write_bytes(price_xlsx())
    gold, soy = read_prices_xlsx(path)
    assert gold[(2021, 12)] is None and soy[(2021, 12)] == 500  # "…"
    assert gold[(2025, 12)] is None and soy[(2025, 12)] is None  # empty cells
    cpi = ge.read_cpi(_write(tmp_path / "cpi.csv", cpi_csv()))
    prices = annual_prices(gold, soy, cpi, 2024)
    assert prices["year"].to_list() == [2022, 2023, 2024]  # 2021: 11 gold months; 2025: 11 all


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_workbook_without_the_sheet_or_a_header_stops(tmp_path):
    path = _write(tmp_path / "prices.xlsx", price_xlsx())
    with pytest.raises(BuildError, match="no single sheet"):
        read_prices_xlsx(path, sheet="Missing")
    headerless = _write(tmp_path / "bad.xlsx", price_xlsx(gold_header="Gold (nominal)"))
    with pytest.raises(BuildError, match="no column 'Gold'"):
        read_prices_xlsx(headerless)


def test_cpi_with_a_bad_date_stops(tmp_path):
    path = _write(tmp_path / "cpi.csv", b"observation_date,CPIAUCSL\n01/01/2020,100\n")
    with pytest.raises(BuildError, match="YYYY-MM-DD"):
        ge.read_cpi(path)


def _cpi(values: dict[tuple[int, int], float | None]) -> dict:
    return dict(values)


def _year(year: int, value: float, skip: tuple[int, ...] = ()) -> dict:
    return {(year, m): (None if m in skip else value + m) for m in range(1, 13)}


def test_one_missing_cpi_month_is_the_geometric_mean_of_its_neighbours():
    # FRED's CPIAUCSL has no October 2025: the BLS never published it (2025 shutdown)
    cpi = {**_year(2024, 300), **_year(2025, 310, skip=(10,)), **_year(2026, 320)}
    cpi[(2025, 9)], cpi[(2025, 11)] = 324.245, 325.063
    filled, months = ge.fill_cpi_gap(cpi)
    assert months == [(2025, 10)]
    assert filled[(2025, 10)] == pytest.approx(math.sqrt(324.245 * 325.063))
    assert filled[(2025, 10)] == pytest.approx(324.654, abs=1e-3)
    assert {k: v for k, v in filled.items() if k != (2025, 10)} == {
        k: v for k, v in cpi.items() if k != (2025, 10)
    }
    assert cpi[(2025, 10)] is None  # the input is not changed


def test_a_missing_january_uses_the_december_before():
    cpi = {**_year(2024, 300), **_year(2025, 310, skip=(1,))}
    filled, months = ge.fill_cpi_gap(cpi)
    assert months == [(2025, 1)]
    assert filled[(2025, 1)] == pytest.approx(math.sqrt(312 * 312))


@pytest.mark.parametrize(
    "cpi",
    [
        {**_year(2024, 300), **_year(2025, 310, skip=(3, 10))},  # two months missing
        {**_year(2024, 300), **_year(2025, 310, skip=(12,))},  # no January after it
        {k: v for k, v in _year(2025, 310).items() if k[1] <= 10},  # the current year
        {**_year(2024, 300), **_year(2025, 310, skip=(1,)), (2024, 12): None},  # no neighbour
    ],
)
def test_cpi_years_that_are_not_one_month_short_are_left_alone(cpi):
    filled, months = ge.fill_cpi_gap(cpi)
    assert months == [] and filled == cpi


def test_a_filled_cpi_month_completes_its_year(tmp_path):
    gold = {(y, m): 1000.0 for y in (2024, 2025) for m in range(1, 13)}
    soy = {(y, m): 500.0 for y in (2024, 2025) for m in range(1, 13)}
    cpi = {**_year(2024, 300), **_year(2025, 310, skip=(10,)), (2026, 1): 330.0}
    assert annual_prices(gold, soy, cpi, 2024)["year"].to_list() == [2024]  # the old stop
    filled, months = ge.fill_cpi_gap(cpi)
    prices = annual_prices(gold, soy, filled, 2024, months)
    row = {r["year"]: r for r in prices.iter_rows(named=True)}
    assert prices["year"].to_list() == [2024, 2025]
    assert row[2025]["n_months_cpi"] == 12 and row[2025]["n_months_cpi_filled"] == 1
    assert row[2024]["n_months_cpi_filled"] == 0
    expected = (sum(310 + m for m in range(1, 13) if m != 10) + math.sqrt(319 * 321)) / 12
    assert row[2025]["cpi"] == pytest.approx(expected)


def test_build_fills_a_missing_cpi_month_and_says_so(tmp_path):
    # the fixture's 2025 has no gold December, so a 2023 gap stands in for October 2025
    blank = cpi_csv().replace(b"2023-06-01,110\n", b"2023-06-01,\n")
    assert blank != cpi_csv()
    inputs = Inputs(tmp_path, cpi=blank)
    manifest = inputs.build()
    assert (
        "cpi_months_filled=2023-06 (geometric mean of the months on each side)"
        in (manifest["notes"])
    )
    prices = read(inputs, manifest, "gold_prices.parquet")
    row = {r["year"]: r for r in prices.iter_rows(named=True)}
    assert prices["year"].to_list() == [2022, 2023, 2024]
    assert row[2023]["n_months_cpi"] == 12 and row[2023]["n_months_cpi_filled"] == 1
    assert row[2023]["cpi"] == pytest.approx(110)
    assert row[2022]["n_months_cpi_filled"] == 0


def test_notes_say_when_no_cpi_month_was_filled(inputs):
    assert "cpi_months_filled=none" in inputs.build()["notes"]


def test_cpi_missing_value_is_missing(tmp_path):
    path = _write(tmp_path / "cpi.csv", b"observation_date,CPIAUCSL\n2020-01-01,.\n")
    assert ge.read_cpi(path) == {(2020, 1): None}


# --- 3. Every stop condition raises and nothing is uploaded


STOPS = [
    ("municipalities: 3, fewer than 4", {"min_municipalities": 4}),
    ("SGB rows: 7, fewer than 8", {"min_sgb": 8}),
    ("SGB gold occurrences: 6, fewer than 7", {"min_gold_occurrences": 7}),
    ("ANM rows: 10, fewer than 11", {"min_anm": 11}),
    ("gold titles with a year before 2000: 3, fewer than 4", {"min_gold_pre2000": 4}),
    ("gold price years: 3, fewer than 4", {"min_price_years": 4}),
    (r"gold price years missing: \[2026\]", {"required_years": (2022, 2023, 2026)}),
    ("2025 is not a complete year", {"base_year": 2025}),
]


@pytest.mark.parametrize(("message", "change"), STOPS)
def test_each_volume_check_stops_the_build(inputs, message, change):
    with pytest.raises(BuildError, match=message):
        inputs.build(limits=replace(LIMITS, **change))
    assert inputs.uploaded() == []


def test_a_municipality_without_a_polygon_stops(tmp_path):
    inputs = Inputs(tmp_path, munis=municipalities_parquet(extra=["9999999"]))
    with pytest.raises(BuildError, match="has no polygon"):
        inputs.build()
    assert inputs.uploaded() == []


def test_the_default_limits_are_the_production_ones(inputs):
    assert (Limits().min_municipalities, Limits().min_sgb, Limits().min_anm) == (
        5571,
        30000,
        250000,
    )
    assert (Limits().min_gold_occurrences, Limits().min_gold_pre2000) == (4000, 9000)
    assert Limits().min_price_years == 60 and Limits().required_years == tuple(range(1985, 2026))
    with pytest.raises(BuildError, match="gold price years: 3, fewer than 60"):
        inputs.build(limits=Limits())
    assert inputs.uploaded() == []


@pytest.mark.parametrize("bad", [-1e-6, 1 + 1e-6])
def test_a_share_outside_zero_one_stops(bad):
    table = pl.DataFrame({name: [0.5] for name in ge.SHARE_COLUMNS}).with_columns(
        pl.lit(bad).alias("indigenous_share")
    )
    with pytest.raises(BuildError, match="indigenous_share is outside"):
        ge.check_shares(table)


def test_rounding_noise_in_a_share_is_clipped():
    table = pl.DataFrame({name: [0.5] for name in ge.SHARE_COLUMNS}).with_columns(
        pl.lit(1 + 1e-12).alias("indigenous_share")
    )
    assert ge.check_shares(table)["indigenous_share"].to_list() == [1.0]


def test_indigenous_lands_outside_the_legal_amazon_box_are_kept(tmp_path):
    from terrain.builds import polling_place_tenure as tenure

    work = tmp_path / "south"
    work.mkdir()
    writer = shapefile.Writer(str(work / "south"), encoding="utf-8")
    writer.field("categoria", "C", 30, 0)
    south = {  # Rio Grande do Sul, south of the Legal Amazon box
        "type": "Polygon",
        "coordinates": [[[-52.0, -29.0], [-51.9, -29.0], [-51.9, -28.9], [-52.0, -29.0]]],
    }
    for categoria in ("TI", "FLONA"):
        writer.shape(south)
        writer.record(categoria)
    writer.close()
    shp = work / "south.shp"
    assert tenure.read_cnfp(shp) == []  # the shared reader drops it
    lands = ge.read_indigenous(shp)
    assert len(lands) == 1
    assert lands[0].bounds[1] < tenure.LEGAL_AMAZON_BOX[1]


def test_no_indigenous_land_stops(tmp_path):
    work = tmp_path / "c2"
    only_forest = zipped(
        work, "CNFP_2025", [("categoria", 20), ("tipo", 10), ("anocriacao", 10)],
        [((5010, 10000, 5020, 10010), "FLONA", "TIPO A", "1990")],
    )  # fmt: skip
    inputs = Inputs(tmp_path, cnfp=only_forest)
    with pytest.raises(BuildError, match="no Indigenous land"):
        inputs.build()
    assert inputs.uploaded() == []


def test_an_input_that_differs_from_its_manifest_stops(inputs):
    inputs.manifests["sgb"]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="does not match the sha256"):
        inputs.build()
    assert inputs.uploaded() == []


# --- 4. The output path


def test_output_path_changes_with_the_code_and_with_an_input(inputs):
    files = [f for m in inputs.manifests.values() for f in m["files"]]
    base = input_hash(files, code=["x"])
    assert input_hash(files, code=["y"]) != base
    assert input_hash(list(reversed(files)), code=["x"]) == base
    changed = [{**files[0], "sha256": "f" * 64}, *files[1:]]
    assert input_hash(changed, code=["x"]) != base


def test_code_hash_covers_this_module_and_the_modules_it_reuses():
    names = {p.name for p in ge.CODE_MODULES}
    assert names == {
        "gold_exposure.py",
        "cell_enforcement.py",
        "polling_place_tenure.py",
        "grid.py",
    }


def test_a_changed_input_gives_a_new_path_and_a_rerun_is_unchanged(tmp_path, inputs):
    first = inputs.build()
    assert first["status"] == "created"
    assert first["gcs_prefix"].startswith(DERIVED)
    assert sorted(f["path"].rsplit("/", 1)[1] for f in first["files"]) == [
        "gold_exposure.parquet",
        "gold_prices.parquet",
    ]
    write_manifest(first, inputs.store, tmp_path / "manifest.json")
    again = inputs.build()
    assert again["status"] == "unchanged" and again["gcs_prefix"] == first["gcs_prefix"]

    other = Inputs(tmp_path / "other", sgb=sgb_csv() + b"")
    assert other.build()["gcs_prefix"] == first["gcs_prefix"]  # same inputs, same path
    changed = Inputs(tmp_path / "changed", sgb=sgb_csv() + b"9,T,RO,,,,,,,Ferro,,\n")
    assert changed.build(limits=replace(LIMITS, min_sgb=8))["gcs_prefix"] != first["gcs_prefix"]


def test_files_listed_in_the_manifest_match_the_store(inputs):
    manifest = inputs.build()
    for entry in manifest["files"]:
        data = inputs.store.read_bytes(entry["path"])
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert entry["bytes"] == len(data)
    assert json.loads(json.dumps(manifest))["inputs"][0].endswith(MANIFEST_NAME)


# --- Geometry helpers


def test_repair_keeps_only_polygons_and_counts_repairs():
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    repaired, n = ge.repair([bowtie, square, None, shapely.Point(1, 1)])
    assert n == 1
    assert repaired[0].geom_type == "MultiPolygon" and repaired[0].area == pytest.approx(2.0)
    assert repaired[1] is square and repaired[2] is None and repaired[3] is None


def test_assign_points_marks_outside_points():
    squares = [Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), Polygon([(2, 0), (4, 0), (4, 2), (2, 2)])]
    owner, outside = ge.assign_points(
        np.array([1.0, 3.0, 9.0, 2.0]), np.array([1.0, 1.0, 1.0, 1.0]), squares, ["a", "b"]
    )
    assert owner.tolist() == ["a", "b", None, None]  # (2, 1) is on the shared boundary
    assert outside == 2


def test_title_flags_follow_the_issue():
    titles = pl.DataFrame(
        {
            "subs": [" OURO ", "OURO PIGMENTO", "AREIA", "Ouro", "OURO", "OURO"],
            "fase": ["LAVRA GARIMPEIRA", "LAVRA GARIMPEIRA", "x", "LAVRA GARIMPEIRA", "x", None],
            "ano": [1999, 1990, 1980, 1990, 2000, 1899],
        }
    )
    flags = ge.title_flags(titles)
    assert flags["gold"].to_list() == [True, False, False, False, True, True]
    assert flags["garimpo"].to_list() == [True, False, False, False, False, False]
    assert flags["sand"].to_list() == [False, False, True, False, False, False]
    assert flags["dated"].to_list() == [True, True, True, True, True, False]
    assert flags["pre2000"].to_list() == [True, True, True, True, False, False]
