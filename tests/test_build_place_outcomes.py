import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapefile
import tifffile

from terrain import grid
from terrain.builds import place_outcomes as po
from terrain.builds.place_outcomes import BuildError, build
from terrain.explore import EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/place_outcomes/"
SEALED = "sealed/outcomes/place_outcomes/"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)
ELECTIONS = (2008, 2012, 2016, 2020)
A, B, C = "1100015", "3500105", "4100103"  # list 1, list 2, neither
# A is x 5000-5006, B x 5006-5012 and C x 5012-5018 (Albers km), all y 10000-10006.
GRID = {"x0": 5000, "x1": 5018, "y0": 10000, "y1": 10006}
COVERAGE_YEARS = list(range(2004, 2025))
VIIRS_YEARS = list(range(2013, 2025))
VIIRS_BLOCK = {
    "mode": "log1p_mean",
    "years": VIIRS_YEARS,
    "scale": 1000,
    "grid_km": GRID,
    "file": "viirs_log1p_<year>.tif",
}
COVERAGE_BLOCK = {
    "mode": "groups",
    "groups": {"urban": [24], "native": [3, 4, 5, 6, 49, 11, 12, 32, 29, 50]},
    "years": COVERAGE_YEARS,
    "scale": 10000,
    "grid_km": GRID,
    "file": "coverage_shares_<year>.tif",
}


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
    boxes = ((A, (5000, 10000, 5006, 10006)), (B, (5006, 10000, 5012, 10006)))
    for code, box in (*boxes, (C, (5012, 10000, 5018, 10006))):
        writer.shape(km_polygon(*box))
        writer.record(code)
    writer.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ext in ("shp", "shx", "dbf"):
            name = f"BR_Municipios_2024.{ext}"
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), (work / name).read_bytes())
    return buf.getvalue()


def parquet(frame: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def tif(path: Path, arr: np.ndarray) -> bytes:
    tifffile.imwrite(path, arr, photometric="minisblack")
    return path.read_bytes()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def at(x: float, y: float) -> dict:
    lon, lat = grid.km_to_lonlat([x], [y])
    return {"lat": float(lat[0]), "long": float(lon[0])}


def place(code: str, number: int, x: float, y: float, conf: float | None = 0.0) -> dict:
    where = at(x, y) if conf is not None else {"lat": None, "long": None}
    return {
        "cd_ibge": code,
        "sg_ue": "00001",
        "nr_zona": 1,
        "nr_local_votacao": number,
        **where,
        "conf_dist_km": conf,
    }


def place_rows(variant: bool) -> list[tuple[dict, str | None, str | None]]:
    """(place, school, confidence). A1 interior, A2 at the border with B, A3 not located."""
    rows = [
        (place(A, 1, 5002.5, 10003.5), "S1", "high"),
        (place(A, 2, 5005.5, 10003.5), "S2", "medium"),
        (place(A, 3, 5001.5, 10001.5, conf=5.0), "S3", "high"),
        (place(A, 4, 5003.5, 10001.5), "S4", "low"),
        (place(B, 5, 5007.5, 10002.5), "SB", "high"),
        (place(C, 6, 5013.5, 10002.5), "SC", "high"),
    ]
    if variant:
        rows += [
            (place(C, 7, 5016.5, 10004.5), "SD", "medium"),
            (place(C, 8, 5014.5, 10001.5), None, "none"),
        ]
    return rows


def schools_frame(variant: bool) -> pl.DataFrame:
    """Facilities: every one is 1. S2 has no row in 2014 and no internet value in 2016."""
    rows = []
    for sid, rede in (
        ("S1", "3"),
        ("S2", "2"),
        ("S3", "3"),
        ("S4", "3"),
        ("SB", "3"),
        ("SC", "3"),
        ("SD", "3"),
    ):
        for year in range(2007, 2025):
            if sid == "S2" and year == 2014:
                continue
            value = 0 if variant and sid in ("SC", "SD") else 1
            row = {"ano": year, "id_escola": sid, "rede": rede}
            row |= {c: value for c in po.FACILITIES}
            if sid == "S2" and year == 2016:
                row["internet"] = None
            row["dependencia_pne"] = value if year <= 2018 else None
            row["acessibilidade_inexistente"] = None if year <= 2018 else 1
            rows.append(row)
    columns = [
        "ano",
        "id_escola",
        "rede",
        *po.FACILITIES,
        "dependencia_pne",
        "acessibilidade_inexistente",
    ]
    return pl.DataFrame(
        {c: [r.get(c) for r in rows] for c in columns},
        schema={
            "ano": pl.Int64,
            "id_escola": pl.Utf8,
            "rede": pl.Utf8,
            **{c: pl.Int8 for c in columns[3:]},
        },
    )


def lights_array(year: int, variant: bool) -> np.ndarray:
    arr = np.zeros((6, 18), dtype=np.uint16)
    arr[:, 0:6] = 3000 + 10 * (year - 2013)
    arr[:, 6:12] = 6000
    arr[:, 12:18] = 1234 if variant else 9000
    return arr


def coverage_array(variant: bool) -> np.ndarray:
    arr = np.zeros((6, 18, 2), dtype=np.uint16)
    arr[:, 0:6] = (1000, 2000)  # urban, native
    arr[:, 6:12] = (2000, 8000)
    arr[:, 12:18] = (777, 4321) if variant else (3000, 5000)
    return arr


def world(
    tmp_path: Path, variant: bool = False, lists: tuple[bytes | None, bytes | None] | None = None
):
    """A store holding every input, and the six manifests."""
    store = MemoryStore()
    blobs: dict[str, dict[str, bytes]] = {
        "places": {},
        "match": {},
        "schools": {},
        "boundaries": {},
        "viirs": {},
        "coverage": {},
    }
    rows = place_rows(variant)
    key = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
    for e in ELECTIONS:
        base = pl.DataFrame(
            [{"ano": e, **p} for p, _, _ in rows],
            schema={
                "ano": pl.Int64,
                "cd_ibge": pl.Utf8,
                "sg_ue": pl.Utf8,
                "nr_zona": pl.Int64,
                "nr_local_votacao": pl.Int64,
                "lat": pl.Float64,
                "long": pl.Float64,
                "conf_dist_km": pl.Float64,
            },
        )
        blobs["places"][f"polling_places_{e}.parquet"] = parquet(base)
        match = base.select(key).with_columns(
            pl.Series("id_escola", [s for _, s, _ in rows], dtype=pl.Utf8),
            pl.Series("confidence", [c for _, _, c in rows], dtype=pl.Utf8),
        )
        blobs["match"][f"school_polling_match_{e}.parquet"] = parquet(match)
    blobs["schools"]["inep_schools.parquet"] = parquet(schools_frame(variant))
    blobs["boundaries"]["BR_Municipios_2024.zip"] = boundaries_zip(tmp_path / "shp")
    for y in VIIRS_YEARS:
        blobs["viirs"][f"viirs_log1p_{y}.tif"] = tif(
            tmp_path / "scratch.tif", lights_array(y, variant)
        )
    for y in COVERAGE_YEARS:
        blobs["coverage"][f"coverage_shares_{y}.tif"] = tif(
            tmp_path / "scratch.tif", coverage_array(variant)
        )
    manifests = []
    for name, files in blobs.items():
        prefix = f"data/raw/{name}/2026-01-01/"
        for fname, blob in files.items():
            store.create(prefix + fname, blob)
        manifests.append(
            {"gcs_prefix": prefix, "files": [entry(prefix + f, b) for f, b in files.items()]}
        )
    one, two = (
        lists if lists is not None else (f"code_ibge\n{A}\n".encode(), f"code_ibge\n{B}\n".encode())
    )
    for path, data in ((EXPLORE_LIST, one), (EXPLORE_LIST_NON_AMAZON, two)):
        if data is not None:
            store.create(path, data)
    return store, manifests


def run(store, manifests, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(
        store,
        *manifests,
        VIIRS_BLOCK,
        COVERAGE_BLOCK,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=work,
        code_commit="test",
        created_at="2026-01-02T00:00:00+00:00",
    )


def read(store, path: str) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(store.read_bytes(path)))


def table(store, manifest, folder: str, election: int, year: int) -> pl.DataFrame:
    key = "files" if folder == "derived" else "sealed_files"
    name = po.output_name(election, year)
    (found,) = [f for f in manifest[key] if f["path"].endswith("/" + name)]
    return read(store, found["path"])


@pytest.fixture
def built(tmp_path):
    store, manifests = world(tmp_path)
    return store, run(store, manifests, tmp_path)


def test_rows_are_split_by_half(built):
    store, manifest = built
    assert len(manifest["files"]) == len(manifest["sealed_files"]) == 36
    assert all(f["path"].startswith(DERIVED) for f in manifest["files"])
    assert all(f["path"].startswith(SEALED) for f in manifest["sealed_files"])
    names = {f["path"].rsplit("/", 1)[1] for f in manifest["files"]}
    assert names == {f["path"].rsplit("/", 1)[1] for f in manifest["sealed_files"]}
    assert "place_outcomes_E2008_y2004.parquet" in names
    assert "place_outcomes_E2020_y2024.parquet" in names
    for e in ELECTIONS:
        for y in range(e - 4, e + 5):
            derived = table(store, manifest, "derived", e, y)
            sealed = table(store, manifest, "sealed", e, y)
            assert set(derived["cd_ibge"]) == {A, B}
            assert set(sealed["cd_ibge"]) == {C}
            assert set(derived["y"]) == set(sealed["y"]) == {y}
    assert not [p for p in store.list("") if p.startswith(SEALED) and p.startswith(DERIVED)]


def test_a_ring_at_a_border_excludes_the_neighbour(built):
    store, manifest = built
    rows = table(store, manifest, "derived", 2016, 2016)
    border = rows.filter(pl.col("nr_local_votacao") == 2).row(0, named=True)
    # A is 6 x 6 cells and all of it is within 10 km; B's 36 cells are not counted.
    assert border["ring_cells_10km"] == 36
    assert border["native_10km"] == pytest.approx(0.2)
    # The cell east of the place is B's: four cells remain in the 1 km ring.
    assert border["ring_cells_1km"] == 4
    assert border["lights_1km"] == pytest.approx(3.03)
    assert border["builtup_1km"] == pytest.approx(0.1)
    inner = rows.filter(pl.col("nr_local_votacao") == 1).row(0, named=True)
    assert inner["ring_cells_1km"] == 5
    other = rows.filter(pl.col("nr_local_votacao") == 5).row(0, named=True)
    assert other["native_10km"] == pytest.approx(0.8)
    assert other["lights_1km"] == pytest.approx(6.0)
    sealed = table(store, manifest, "sealed", 2016, 2016).row(0, named=True)
    assert sealed["native_10km"] == pytest.approx(0.5)


def test_years_without_a_viirs_file_have_null_lights(built):
    store, manifest = built
    early = table(store, manifest, "derived", 2008, 2008)
    assert early["lights_1km"].null_count() == early.height
    assert early.filter(pl.col("located_1km"))["native_10km"].null_count() == 0


def test_places_that_are_not_located_have_no_ring(built):
    store, manifest = built
    rows = table(store, manifest, "derived", 2016, 2016)
    far = rows.filter(pl.col("nr_local_votacao") == 3).row(0, named=True)
    assert far["located_1km"] is False
    assert far["native_10km"] is None and far["lights_1km"] is None
    assert far["ring_cells_1km"] is None and far["ring_cells_10km"] is None
    assert far["school_id"] == "S3"


def test_accessibility_source_switches_between_2018_and_2019(built):
    store, manifest = built
    counts = {
        y: table(store, manifest, "derived", 2016, y).filter(pl.col("nr_local_votacao") == 1)[
            "school_n_fac"
        ][0]
        for y in (2017, 2018, 2019, 2020)
    }
    # 2018 counts dependencia_pne (1); 2019 counts 1 - acessibilidade_inexistente (0).
    assert counts == {2017: 9, 2018: 9, 2019: 8, 2020: 8}


def test_a_null_facility_or_missing_year_gives_a_null_count(built):
    store, manifest = built

    def count(year: int):
        rows = table(store, manifest, "derived", 2016, year)
        return rows.filter(pl.col("nr_local_votacao") == 2)["school_n_fac"][0]

    assert count(2016) is None  # internet is null
    assert count(2014) is None  # no row for the school
    assert count(2015) == 9
    rows = table(store, manifest, "derived", 2016, 2016)
    assert rows.filter(pl.col("nr_local_votacao") == 2)["school_rede"][0] == "2"


def test_a_low_confidence_match_gives_no_school(built):
    store, manifest = built
    rows = table(store, manifest, "derived", 2016, 2016)
    low = rows.filter(pl.col("nr_local_votacao") == 4).row(0, named=True)
    assert low["school_id"] is None and low["school_rede"] is None and low["school_n_fac"] is None
    medium = rows.filter(pl.col("nr_local_votacao") == 2).row(0, named=True)
    assert medium["school_id"] == "S2"


def test_notes_count_exploration_rows_only(built, tmp_path):
    store, manifest = built
    assert (
        "E2016 y2016: places=5, places_with_school=4 (by rede 2=1/3=3), school_n_fac_null=1, "
        "located_places=4, empty_rings_1km=0, empty_rings_10km=0"
    ) in manifest["notes"]
    assert A not in manifest["notes"] and C not in manifest["notes"]


def test_changing_confirmation_inputs_leaves_the_notes_unchanged(built, tmp_path):
    _, manifest = built
    other_store, other_manifests = world(tmp_path / "other", variant=True)
    other = run(other_store, other_manifests, tmp_path / "other")
    assert other["notes"] == manifest["notes"]
    # The sealed rows did change, so the test is not vacuous.
    assert table(other_store, other, "sealed", 2016, 2016).height == 3
    derived = table(other_store, other, "derived", 2016, 2016)
    assert derived.height == 5


def test_a_rerun_with_the_same_inputs_is_unchanged(built, tmp_path):
    store, first = built
    store2, manifests = world(tmp_path / "again")
    created = run(store2, manifests, tmp_path / "again")
    write_manifest(created, store2, tmp_path / "manifest.json")
    again = run(store2, manifests, tmp_path / "again")
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]


def test_a_code_in_both_lists_stops_the_build_with_nothing_written(tmp_path):
    both = f"code_ibge\n{A}\n".encode()
    store, manifests = world(tmp_path, lists=(both, both))
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


@pytest.mark.parametrize("missing", [0, 1])
def test_a_missing_list_stops_the_build_with_nothing_written(tmp_path, missing):
    lists = [f"code_ibge\n{A}\n".encode(), f"code_ibge\n{B}\n".encode()]
    lists[missing] = None
    store, manifests = world(tmp_path, lists=(lists[0], lists[1]))
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


def test_the_output_path_depends_on_the_code():
    files = [{"sha256": "a" * 64}]
    one = po.input_hash(files, ["x", "y"], (2013,), code=["one"])
    assert one != po.input_hash(files, ["x", "y"], (2013,), code=["two"])
    assert one != po.input_hash(files, ["x", "z"], (2013,), code=["one"])
    assert one != po.input_hash(files, ["x", "y"], (2013, 2014), code=["one"])
    assert {Path(p).name for p in map(str, po.CODE_MODULES)} >= {
        "place_outcomes.py",
        "grid.py",
        "explore.py",
        "cell_outcomes.py",
    }
