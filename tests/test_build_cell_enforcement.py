import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest
import shapefile

from terrain import grid, ibama
from terrain.builds import cell_enforcement as ce
from terrain.builds.cell_enforcement import BuildError, build, input_hash, normalise
from terrain.catalog import dataset
from terrain.explore import EXPLORE_LIST
from terrain.manifest import MANIFEST_NAME, check_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
DERIVED = "data/derived/cell_enforcement/"
SEALED = "sealed/outcomes/cell_enforcement/"
YEARS = tuple(range(2000, 2026))
A, B, FAR = "1100015", "1100023", "2100000"  # exploration, confirmation, not in grid_cells
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


def cell(x: int, y: int) -> str:
    return f"1KME{x}N{y}"


# Municipality A is x 5000-5003 and B x 5003-5006 (Albers km), both y 10000-10003.
# (5002, 10002) lies in A's polygon but belongs to B in grid_cells, and (5003, 10002) lies
# in B's polygon but belongs to A.
CELLS = [(cell(x, y), A) for x in (5000, 5001, 5002) for y in (10000, 10001, 10002)] + [
    (cell(x, y), B) for x in (5003, 5004, 5005) for y in (10000, 10001, 10002)
]
CELLS = [(n, B if n == cell(5002, 10002) else A if n == cell(5003, 10002) else m) for n, m in CELLS]


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


def boundaries_zip(work: Path) -> bytes:
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / "BR_Municipios_2024"), encoding="utf-8")
    writer.field("CD_MUN", "C", 7, 0)
    for code, box in ((A, (5000, 10000, 5003, 10003)), (B, (5003, 10000, 5006, 10003))):
        writer.shape(km_polygon(*box))
        writer.record(code)
    writer.shape(km_polygon(6000, 10000, 6003, 10003))
    writer.record(FAR)
    writer.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ext in ("shp", "shx", "dbf"):
            name = f"BR_Municipios_2024.{ext}"
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), (work / name).read_bytes())
    return buf.getvalue()


def at(x: float, y: float) -> dict:
    lon, lat = grid.km_to_lonlat([x], [y])
    return {"latitude": float(lat[0]), "longitude": float(lon[0])}


def parquet(name: str, rows: list[dict]) -> bytes:
    schema = ibama.SCHEMAS[name]
    frame = pl.DataFrame({c: [r.get(c) for r in rows] for c in schema}, schema=schema)
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


class Rows:
    """Synthetic records; each gets its own id."""

    def __init__(self, fonte: str) -> None:
        self.fonte, self.n = fonte, 0

    def base(self, muni: str, x: float, y: float, year: int | None, **extra) -> dict:
        self.n += 1
        when = date(year, 6, 1) if year else None
        row = {
            "fonte": self.fonte,
            "data_auto": when,
            "data_embargo": when,
            "ano": year,
            "id_municipio": muni,
            "indicador_coordenada_valida": "sim",
            **at(x, y),
            **extra,
        }
        return row

    def fine(self, muni, x, y, year=2010, tipo="Flora", cancelled="Não", **extra) -> dict:
        row = self.base(muni, x, y, year, tipo_infracao=tipo, indicador_cancelado=cancelled)
        return {**row, "id_auto": f"a{self.n}", **extra}

    def embargo(self, muni, x, y, year=2010, **extra) -> dict:
        row = self.base(muni, x, y, year)
        return {**row, "id_embargo": f"e{self.n}", **extra}


def fines_rows(fonte: str, confirmation: bool) -> list[dict]:
    r = Rows(fonte)
    nan = float("nan")
    rows = [
        r.fine(A, 5000.5, 10000.5),  # counts in cell E5000N10000
        r.fine(A, 5000.5, 10000.5, cancelled=None, indicador_coordenada_valida=None),
        r.fine(A, 5000.5, 10000.5, cancelled="Sim"),  # cancelled
        r.fine(A, 5000.5, 10000.5, tipo="Fauna"),  # not flora
        r.fine(A, 5004.5, 10000.5),  # in B's polygon: outside its own
        r.fine(A, 5002.5, 10002.5, indicador_coordenada_valida="nao"),  # cell is B's
        r.fine(A, 5000.5, 10000.5, latitude=nan, longitude=nan),  # no coordinates
        r.fine(A, 5000.5, 10000.5, year=1999),  # outside 2000-2025
        r.fine(FAR, 6000.5, 10000.5),  # not Legal Amazon
        {**r.fine(A, 5001.5, 10001.5, year=None), "ano": 2011},  # year from `ano`
        r.fine(A, 5001.5, 10001.5, year=None),  # no date and no year
    ]
    if confirmation:
        rows += [
            r.fine(B, 5004.5, 10000.5),
            r.fine(B, 5004.5, 10000.5, cancelled="Sim"),
            r.fine(B, 5004.5, 10000.5, latitude=nan, longitude=nan),
            r.fine(B, 5001.5, 10000.5),  # in A's polygon
            r.fine(B, 5003.5, 10002.5),  # cell is A's
            r.fine(B, 5004.5, 10000.5, year=1999),
            r.fine(B, 5004.5, 10000.5, year=None),
            r.fine(B, 5004.5, 10000.5, tipo="Fauna"),
        ]
    return rows


def embargo_rows(fonte: str, confirmation: bool) -> list[dict]:
    r = Rows(fonte)
    rows = [
        r.embargo(A, 5001.5, 10000.5),
        r.embargo(A, 5001.5, 10000.5, indicador_coordenada_valida="S"),
        r.embargo(A, 5004.5, 10000.5, indicador_coordenada_valida="nao"),  # outside
    ]
    if confirmation:
        rows += [
            r.embargo(B, 5005.5, 10002.5),
            r.embargo(B, 5001.5, 10000.5),
            r.embargo(B, 5005.5, 10002.5, year=2030),
        ]
    return rows


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def world(tmp_path: Path, fonte="basedosdados", confirmation=True, fines=None, embargoes=None):
    """A store holding every input, and the four manifests."""
    store = MemoryStore()
    manifests = []
    blobs = {
        "data/raw/ibama/autos/2026-01-01/ibama_autos.parquet": parquet(
            "ibama_autos", fines if fines is not None else fines_rows(fonte, confirmation)
        ),
        "data/raw/ibama/embargos/2026-01-01/ibama_embargos.parquet": parquet(
            "ibama_embargos",
            embargoes if embargoes is not None else embargo_rows(fonte, confirmation),
        ),
        "data/raw/ibge/boundaries_2024/2026-01-01/BR_Municipios_2024.zip": boundaries_zip(
            tmp_path / "shp"
        ),
    }
    buf = io.BytesIO()
    pl.DataFrame(
        {
            "nome_1KM": [c[0] for c in CELLS],
            "cd_ibge": [c[1] for c in CELLS],
            "x_km": [0] * len(CELLS),
            "y_km": [0] * len(CELLS),
        }
    ).write_parquet(buf)
    blobs["data/derived/grid_cells/aaaa/grid_cells.parquet"] = buf.getvalue()
    for path, blob in blobs.items():
        store.create(path, blob)
        manifests.append({"gcs_prefix": path.rsplit("/", 1)[0] + "/", "files": [entry(path, blob)]})
    store.create(EXPLORE_LIST, f"code_ibge\n{A}\n".encode())
    return store, manifests


def run(store, manifests, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(
        store,
        *manifests,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=work,
        code_commit="abc",
        created_at="2026-01-01T00:00:00+00:00",
    )


def read(store, path) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


@pytest.fixture
def built(tmp_path):
    store, manifests = world(tmp_path)
    manifest = run(store, manifests, tmp_path)
    prefix = manifest["gcs_prefix"]
    sealed = SEALED + prefix.removeprefix(DERIVED)
    return store, manifest, prefix, sealed


def rows_of(frame: pl.DataFrame) -> list[tuple]:
    return [tuple(r) for r in frame.iter_rows()]


# --- Done when 1: the halves and the counts


def test_derived_holds_only_the_exploration_municipality_and_counts_are_right(built):
    store, _, prefix, _ = built
    cells_2010 = read(store, prefix + "cell_enforcement_2010.parquet")
    assert cells_2010.columns == ["nome_1KM", "cd_ibge", "ano", "n_fines_flora", "n_embargoes"]
    assert set(cells_2010.schema.values()) == {pl.Utf8, pl.Int64}
    assert rows_of(cells_2010) == [
        (cell(5000, 10000), A, 2010, 2, 0),
        (cell(5001, 10000), A, 2010, 0, 2),
    ]
    assert rows_of(read(store, prefix + "cell_enforcement_2011.parquet")) == [
        (cell(5001, 10001), A, 2011, 1, 0)
    ]
    assert read(store, prefix + "cell_enforcement_2000.parquet").is_empty()
    muni = read(store, prefix + "muni_enforcement_2010.parquet")
    assert muni.columns == [
        "cd_ibge",
        "ano",
        "n_fines_flora_all",
        "n_fines_flora_located",
        "n_embargoes_all",
        "n_embargoes_located",
    ]
    assert rows_of(muni) == [(A, 2010, 5, 2, 3, 2)]


def test_sealed_holds_only_the_other_municipality(built):
    store, _, _, sealed = built
    assert rows_of(read(store, sealed + "cell_enforcement_2010.parquet")) == [
        (cell(5004, 10000), B, 2010, 1, 0),
        (cell(5005, 10002), B, 2010, 0, 1),
    ]
    # B: four flora fines in 2010 (one located) and two embargoes (one located).
    assert rows_of(read(store, sealed + "muni_enforcement_2010.parquet")) == [(B, 2010, 4, 1, 2, 1)]


def test_every_file_of_every_year_holds_only_its_half(built):
    store, manifest, prefix, sealed = built
    for y in YEARS:
        for name in ("cell_enforcement", "muni_enforcement"):
            assert set(read(store, f"{prefix}{name}_{y}.parquet")["cd_ibge"]) <= {A}
            assert set(read(store, f"{sealed}{name}_{y}.parquet")["cd_ibge"]) <= {B}
    assert len(manifest["files"]) == len(manifest["sealed_files"]) == 2 * len(YEARS)


# --- Done when 2: each rule, each way


def test_cancelled_flora_and_location_cases(built):
    store, _, prefix, _ = built
    muni = read(store, prefix + "muni_enforcement_2010.parquet").row(0, named=True)
    # `Sim` and `Fauna` never count; a point outside its polygon or in a neighbour's cell
    # and a record without coordinates are in `all` but not located.
    assert muni["n_fines_flora_all"] == 5
    assert muni["n_fines_flora_located"] == 2
    assert muni["n_embargoes_all"] == 3
    assert muni["n_embargoes_located"] == 2


def test_year_falls_back_to_ano_and_out_of_range_records_are_dropped(built):
    store, _, prefix, _ = built
    assert read(store, prefix + "muni_enforcement_2011.parquet")["n_fines_flora_all"].to_list() == [
        1
    ]
    total = sum(
        int(read(store, f"{prefix}muni_enforcement_{y}.parquet")["n_fines_flora_all"].sum())
        for y in YEARS
    )
    assert total == 6  # 5 in 2010, 1 in 2011; 1999, no year and FAR are dropped


def test_unknown_cancelled_value_stops_the_build(tmp_path):
    rows = fines_rows("basedosdados", False)
    rows.append(Rows("basedosdados").fine(A, 5000.5, 10000.5, cancelled="talvez"))
    store, manifests = world(tmp_path, fines=rows)
    before = store.list("")
    with pytest.raises(BuildError, match="talvez"):
        run(store, manifests, tmp_path)
    assert store.list("") == before


def test_no_flora_value_stops_the_build(tmp_path):
    rows = [Rows("basedosdados").fine(A, 5000.5, 10000.5, tipo="Fauna")]
    store, manifests = world(tmp_path, fines=rows)
    before = store.list("")
    with pytest.raises(BuildError, match="flora"):
        run(store, manifests, tmp_path)
    assert store.list("") == before


def test_normalise_strips_casefolds_and_removes_accents():
    assert normalise("  NÃO ") == "nao"
    assert normalise("Verdadeiro") == "verdadeiro"
    assert normalise(None) is None
    assert normalise("") == ""


def test_a_municipality_without_a_polygon_stops_the_build(tmp_path):
    store, manifests = world(tmp_path)
    buf = io.BytesIO()
    pl.DataFrame({"nome_1KM": [cell(1, 1)], "cd_ibge": ["1100031"]}).write_parquet(buf)
    path = "data/derived/grid_cells/bbbb/grid_cells.parquet"
    store.create(path, buf.getvalue())
    manifests[3] = {
        "gcs_prefix": "data/derived/grid_cells/bbbb/",
        "files": [entry(path, buf.getvalue())],
    }
    with pytest.raises(BuildError, match="no polygon"):
        run(store, manifests, tmp_path)


# --- Done when 3: every municipality of the half, every year


def test_muni_table_has_every_municipality_of_its_half_for_every_year(built):
    store, _, prefix, sealed = built
    for y in YEARS:
        derived = read(store, f"{prefix}muni_enforcement_{y}.parquet")
        confirmation = read(store, f"{sealed}muni_enforcement_{y}.parquet")
        assert derived["cd_ibge"].to_list() == [A]
        assert confirmation["cd_ibge"].to_list() == [B]
        assert set(derived["ano"]) == set(confirmation["ano"]) == {y}
    zeros = read(store, f"{prefix}muni_enforcement_2000.parquet").row(0)
    assert zeros == (A, 2000, 0, 0, 0, 0)


# --- Done when 4: the notes


def test_notes_carry_fonte_drops_and_the_agreement_line(built):
    _, manifest, _, _ = built
    notes = manifest["notes"]
    assert "fonte ibama_autos=basedosdados" in notes
    assert "fonte ibama_embargos=basedosdados" in notes
    assert "ibama_autos: not_legal_amazon=1, no_date_no_year=1, outside_2000_2025=1" in notes
    assert (
        "ibama_autos 2010: no_coordinates=1, outside_own_polygon=1, "
        "cell_in_another_municipality_or_not_in_grid=1"
    ) in notes
    assert (
        "ibama_embargos 2010: no_coordinates=0, outside_own_polygon=1, "
        "cell_in_another_municipality_or_not_in_grid=0"
    ) in notes
    # 8 exploration records with coordinates: 6 agree, 1 disagrees (fine outside, claimed
    # valid), 1 has no claim.
    assert "agree=0.7500 (6), disagree=0.1250 (1), not_comparable=0.1250 (1)" in notes


def test_no_agreement_line_when_fonte_is_ibama(tmp_path):
    store, manifests = world(tmp_path, fonte="ibama")
    notes = run(store, manifests, tmp_path)["notes"]
    assert "fonte ibama_autos=ibama" in notes
    assert "agreement" not in notes


def test_confirmation_records_leave_no_trace_in_the_notes(tmp_path):
    with_confirmation, manifests = world(tmp_path / "a", confirmation=True)
    without, manifests_without = world(tmp_path / "b", confirmation=False)
    full = run(with_confirmation, manifests, tmp_path / "a")
    bare = run(without, manifests_without, tmp_path / "b")
    # The confirmation records fail every check (no coordinates, outside the polygon,
    # another municipality's cell, cancelled, no year, outside the years); none shows.
    assert full["notes"] == bare["notes"]


# --- Done when 5: hash, sealed objects, rerun


def test_source_of_ibama_or_of_the_build_changes_the_hash(tmp_path, monkeypatch):
    store, manifests = world(tmp_path)
    first = run(store, manifests, tmp_path)["gcs_prefix"]
    assert {p.name for p in ce.CODE_MODULES} == {
        "cell_enforcement.py",
        "grid.py",
        "ibama.py",
        "cell_outcomes.py",
        "polling_place_tenure.py",
    }
    for module in ("ibama.py", "cell_enforcement.py"):
        copy = tmp_path / f"copy_{module}"
        original = next(p for p in ce.CODE_MODULES if p.name == module)
        copy.write_text(original.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        changed = tuple(copy if p.name == module else p for p in ce.CODE_MODULES)
        monkeypatch.setattr(ce, "CODE_MODULES", changed)
        other, manifests = world(tmp_path / module)
        assert run(other, manifests, tmp_path / module)["gcs_prefix"] != first
        monkeypatch.undo()


def test_hash_depends_on_split_list_years_and_code():
    files = [{"sha256": "a" * 64}]
    base = input_hash(files, "s1", (2004,), code=["x"])
    assert input_hash(files, "s2", (2004,), code=["x"]) != base
    assert input_hash(files, "s1", (2004, 2005), code=["x"]) != base
    assert input_hash(files, "s1", (2004,), code=["y"]) != base
    assert input_hash([{"sha256": "b" * 64}], "s1", (2004,), code=["x"]) != base


def test_existing_sealed_object_stops_before_any_derived_file(tmp_path):
    store, manifests = world(tmp_path)
    hashed = run(store, manifests, tmp_path)["gcs_prefix"].removeprefix(DERIVED)
    fresh, manifests = world(tmp_path / "fresh")
    fresh.create(f"{SEALED}{hashed}cell_enforcement_2010.parquet", b"already here")
    with pytest.raises(BuildError, match="already exists"):
        run(fresh, manifests, tmp_path / "fresh")
    assert fresh.list(DERIVED) == []


def test_second_run_is_unchanged_and_writes_nothing(tmp_path):
    store, manifests = world(tmp_path)
    first = run(store, manifests, tmp_path)
    check_manifest(first, stage="build", dataset="cell_enforcement")
    assert len(first["files"]) == len(first["sealed_files"]) == 2 * len(YEARS)
    assert all(f["path"].startswith(DERIVED) for f in first["files"])
    assert all(f["path"].startswith(SEALED) for f in first["sealed_files"])
    store.create(first["gcs_prefix"] + MANIFEST_NAME, json.dumps(first).encode("utf-8"))
    before = store.list("")
    second = run(store, manifests, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert store.list("") == before


def test_sha_mismatch_stops_the_build(tmp_path):
    store, manifests = world(tmp_path)
    manifests[0]["files"][0]["sha256"] = "0" * 64
    before = store.list("")
    with pytest.raises(BuildError, match="sha256"):
        run(store, manifests, tmp_path)
    assert store.list("") == before


# --- Done when 6: the contract and the catalog


def test_contract_documents_columns_and_the_catalog_points_to_it():
    text = (ROOT / "data" / "contracts" / "cell_enforcement.md").read_text(encoding="utf-8")
    for column in (
        "nome_1KM",
        "cd_ibge",
        "ano",
        "n_fines_flora",
        "n_embargoes",
        "n_fines_flora_all",
        "n_fines_flora_located",
        "n_embargoes_all",
        "n_embargoes_located",
    ):
        assert f"`{column}`" in text
    entry_ = dataset("cell_enforcement")
    assert entry_["contract"] == "data/contracts/cell_enforcement.md"
    assert entry_["derived"] == DERIVED
    assert entry_["sealed"] == SEALED
