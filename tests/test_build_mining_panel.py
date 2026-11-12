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
from terrain.builds import mining_panel as mp
from terrain.builds.mining_panel import BuildError, build
from terrain.explore import EXPLORE_LIST, EXPLORE_LIST_NON_AMAZON
from terrain.manifest import write_manifest
from terrain.storage import MemoryStore

DERIVED = "data/derived/mining_panel/"
SEALED = "sealed/outcomes/mining_panel/"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)
A, B, C = "1100015", "3500105", "4100103"  # list 1, list 2, neither (C is the small one)
LAGOON = "4300001"
# A is x 5000-5003, y 10000-10006; B is x 5003-5006, y 10000-10005; C is a speck inside the
# cell x 5004, y 10005 (raster row 0, column 4), whose centre is in no polygon.
GRID = {"x0": 5000, "x1": 5006, "y0": 10000, "y1": 10006}
YEARS = (2000, 2001)
GROUPS = {
    "garimpo_gold": [1115],
    "garimpo_other": [1102],
    "industrial_gold": [2115],
    "industrial_other": [2102],
}
MINING_BLOCK = {
    "mode": "groups",
    "groups": GROUPS,
    "years": list(YEARS),
    "scale": 10000,
    "grid_km": GRID,
    "file": "mining_shares_<year>.tif",
}
COVERAGE_BLOCK = {
    "mode": "groups",
    "groups": {"native": [3]},
    "years": [2004],
    "scale": 10000,
    "grid_km": GRID,
    "file": "coverage_shares_<year>.tif",
}
BOXES = (
    (A, (5000, 10000, 5003, 10006)),
    (B, (5003, 10000, 5006, 10005)),
    (C, (5004.1, 10005.4, 5004.3, 10005.6)),
    (LAGOON, (5100, 10000, 5102, 10002)),
)


def km_polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
    ring_km = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    lon, lat = grid.km_to_lonlat([p[0] for p in ring_km], [p[1] for p in ring_km])
    ring = [[float(a), float(b)] for a, b in zip(lon, lat, strict=True)]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def boundaries_zip(work: Path) -> bytes:
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / "BR_Municipios_2024"), encoding="utf-8")
    writer.field("CD_MUN", "C", 7, 0)
    for code, box in BOXES:
        writer.shape(km_polygon(*box))
        writer.record(code)
    writer.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ext in ("shp", "shx", "dbf"):
            name = f"BR_Municipios_2024.{ext}"
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), (work / name).read_bytes())
    return buf.getvalue()


def tif(path: Path, arr: np.ndarray) -> bytes:
    tifffile.imwrite(path, arr, photometric="minisblack")
    return path.read_bytes()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def mining_array(year: int, c_gold: int = 10000) -> np.ndarray:
    """Bands: garimpo_gold, garimpo_other, industrial_gold, industrial_other. Row 0 is y 10005."""
    arr = np.zeros((6, 6, 4), dtype=np.uint16)
    arr[:, 0:3, 0] = 1000 * (2 if year == 2001 else 1)  # A
    arr[1:, 3:6, 1] = 2000  # B
    arr[1:, 3:6, 2] = 500
    arr[0, 4, 0] = c_gold  # C, the one cell of the speck
    arr[0, 3, 0] = arr[0, 5, 0] = 5000  # in no polygon: must be dropped
    return arr


def coverage_array(c_native: int = 6000) -> np.ndarray:
    arr = np.zeros((6, 6, 1), dtype=np.uint16)
    arr[:, 0:3, 0] = 4000  # A
    arr[:, 3:6, 0] = 8000  # B
    arr[0, 4, 0] = c_native  # C
    arr[0, 3, 0] = arr[0, 5, 0] = 1  # in no polygon
    return arr


def world(
    tmp_path: Path,
    arrays: dict | None = None,
    skip: tuple[int, ...] = (),
    lists: tuple[bytes, bytes] | None = None,
    c_gold: int = 10000,
    c_native: int = 6000,
):
    """A store holding every input, and the three manifests."""
    store = MemoryStore()
    tmp_path.mkdir(parents=True, exist_ok=True)
    scratch = tmp_path / "scratch.tif"
    sets = {
        "mining": {
            f"mining_shares_{y}.tif": tif(scratch, (arrays or {}).get(y, mining_array(y, c_gold)))
            for y in YEARS
            if y not in skip
        },
        "coverage": {"coverage_shares_2004.tif": tif(scratch, coverage_array(c_native))},
        "boundaries": {"BR_Municipios_2024.zip": boundaries_zip(tmp_path / "shp")},
    }
    manifests = []
    for name, files in sets.items():
        prefix = f"data/raw/{name}/2026-01-01/"
        for fname, blob in files.items():
            store.create(prefix + fname, blob)
        manifests.append(
            {"gcs_prefix": prefix, "files": [entry(prefix + f, b) for f, b in files.items()]}
        )
    one, two = (
        lists if lists is not None else (f"code_ibge\n{A}\n".encode(), f"code_ibge\n{B}\n".encode())
    )
    store.create(EXPLORE_LIST, one)
    store.create(EXPLORE_LIST_NON_AMAZON, two)
    return store, manifests


def run(store, manifests, tmp_path, mining_block=None, **kwargs):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    options = {"years": YEARS, "check_year": 2000, "check_bounds_ha": (100.0, 10_000.0)}
    return build(
        store,
        *manifests,
        mining_block or MINING_BLOCK,
        COVERAGE_BLOCK,
        derived_root=DERIVED,
        sealed_root=SEALED,
        tmp_dir=work,
        code_commit="test",
        created_at="2026-01-02T00:00:00+00:00",
        **{**options, **kwargs},
    )


def table(store, manifest, folder: str, year: int) -> pl.DataFrame:
    key = "files" if folder == "derived" else "sealed_files"
    (found,) = [f for f in manifest[key] if f["path"].endswith(f"/mining_panel_{year}.parquet")]
    return pl.read_parquet(io.BytesIO(store.read_bytes(found["path"])))


@pytest.fixture
def built(tmp_path):
    store, manifests = world(tmp_path)
    return store, run(store, manifests, tmp_path)


def test_hectares_shares_and_cells_are_as_expected(built):
    store, manifest = built
    rows = {r["cd_ibge"]: r for r in table(store, manifest, "derived", 2000).to_dicts()}
    rows.update({r["cd_ibge"]: r for r in table(store, manifest, "sealed", 2000).to_dicts()})
    assert set(rows) == {A, B, C}  # the lagoon is dropped
    a, b, c = rows[A], rows[B], rows[C]
    assert (a["n_cells"], b["n_cells"], c["n_cells"]) == (18, 15, 1)
    assert a["garimpo_gold_ha"] == pytest.approx(180.0)
    assert (a["garimpo_other_ha"], a["industrial_gold_ha"]) == (0.0, 0.0)
    assert a["garimpo_ha"] == pytest.approx(180.0)
    assert a["garimpo_share"] == pytest.approx(0.1)
    assert b["garimpo_other_ha"] == pytest.approx(300.0)
    assert b["industrial_gold_ha"] == pytest.approx(75.0)
    assert b["garimpo_ha"] == pytest.approx(300.0)
    assert b["garimpo_share"] == pytest.approx(0.2)
    assert c["garimpo_gold_ha"] == pytest.approx(100.0)
    assert c["garimpo_share"] == pytest.approx(1.0)
    assert (a["native_share_2004"], b["native_share_2004"]) == (
        pytest.approx(0.4),
        pytest.approx(0.8),
    )
    assert c["native_share_2004"] == pytest.approx(0.6)
    assert set(rows[A]) == set(mp.COLUMNS)


def test_a_second_year_has_its_own_values(built):
    store, manifest = built
    a = table(store, manifest, "derived", 2001).filter(pl.col("cd_ibge") == A).row(0, named=True)
    assert a["year"] == 2001
    assert a["garimpo_gold_ha"] == pytest.approx(360.0)
    assert a["native_share_2004"] == pytest.approx(0.4)


def test_rows_are_split_by_half(built):
    store, manifest = built
    assert len(manifest["files"]) == len(manifest["sealed_files"]) == len(YEARS)
    assert all(f["path"].startswith(DERIVED) for f in manifest["files"])
    assert all(f["path"].startswith(SEALED) for f in manifest["sealed_files"])
    for y in YEARS:
        assert set(table(store, manifest, "derived", y)["cd_ibge"]) == {A, B}
        assert set(table(store, manifest, "sealed", y)["cd_ibge"]) == {C}
    in_sealed = [p for p in store.list("") if p.startswith(SEALED)]
    assert len(in_sealed) == len(YEARS)


def test_notes_count_exploration_rows_only(built, tmp_path):
    _, manifest = built
    notes = manifest["notes"]
    assert "municipalities=2" in notes
    assert "small_municipalities=0" in notes
    assert "garimpo_ha=480.00" in notes  # A + B in 2000, without C's 100 ha
    assert C not in notes and "580" not in notes and "100.00" not in notes
    store, manifests = world(tmp_path / "other", c_gold=2000, c_native=100)
    again = run(store, manifests, tmp_path / "other")
    assert again["notes"] == notes


def test_a_rerun_with_the_same_inputs_is_unchanged(built, tmp_path):
    store, first = built
    write_manifest(first, store, tmp_path / "m.json")
    store2, manifests = world(tmp_path / "again")
    store2._objects.update(
        {p: store.read_bytes(p) for p in store.list("") if p.startswith(DERIVED)}
    )
    again = run(store2, manifests, tmp_path / "again")
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]


def test_a_changed_input_gives_a_new_path(built, tmp_path):
    _, first = built
    store, manifests = world(tmp_path / "other", c_native=5000)
    other = run(store, manifests, tmp_path / "other")
    assert other["gcs_prefix"] != first["gcs_prefix"]


def test_the_output_path_depends_on_the_code_and_the_inputs():
    files = [{"sha256": "a" * 64}]
    one = mp.input_hash(files, ["x", "y"], code=["one"])
    assert one != mp.input_hash(files, ["x", "y"], code=["two"])
    assert one != mp.input_hash(files, ["x", "z"], code=["one"])
    assert one != mp.input_hash([{"sha256": "b" * 64}], ["x", "y"], code=["one"])
    assert {p.name for p in mp.CODE_MODULES} >= {
        "mining_panel.py",
        "place_outcomes.py",
        "grid.py",
        "explore.py",
        "cell_outcomes.py",
        "polling_place_tenure.py",
    }


def wrong_shape(_):
    return np.zeros((6, 5, 4), dtype=np.uint16)


def wrong_dtype(_):
    return np.zeros((6, 6, 4), dtype=np.uint8)


def wrong_bands(_):
    return np.zeros((6, 6, 3), dtype=np.uint16)


def too_much(year):
    arr = mining_array(year)
    arr[2, 1, 0], arr[2, 1, 1] = 6000, 4001
    return arr


@pytest.mark.parametrize("bad", [wrong_shape, wrong_dtype, wrong_bands, too_much])
def test_a_bad_raster_stops_the_build_with_nothing_written(tmp_path, bad):
    store, manifests = world(tmp_path, arrays={2001: bad(2001)})
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


def test_a_missing_year_file_stops_the_build(tmp_path):
    store, manifests = world(tmp_path, skip=(2001,))
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


def test_a_missing_year_in_the_catalog_stops_the_build(tmp_path):
    store, manifests = world(tmp_path)
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path, mining_block={**MINING_BLOCK, "years": [2000]})
    assert store.list("") == before


def test_bands_in_another_order_stop_the_build(tmp_path):
    store, manifests = world(tmp_path)
    groups = dict(reversed(list(GROUPS.items())))
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path, mining_block={**MINING_BLOCK, "groups": groups})


def test_a_code_in_both_lists_stops_the_build(tmp_path):
    both = f"code_ibge\n{A}\n".encode()
    store, manifests = world(tmp_path, lists=(both, both))
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


@pytest.mark.parametrize("extra", ["9999999", LAGOON])
def test_an_exploration_code_missing_from_the_boundaries_stops_the_build(tmp_path, extra):
    lists = (f"code_ibge\n{A}\n{extra}\n".encode(), f"code_ibge\n{B}\n".encode())
    store, manifests = world(tmp_path, lists=lists)
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path)
    assert store.list("") == before


@pytest.mark.parametrize("bounds", [(1_000.0, 2_000.0), (1.0, 100.0)])
def test_a_national_total_outside_the_bounds_stops_the_build(tmp_path, bounds):
    store, manifests = world(tmp_path)  # 2000: 180 + 300 + 100 = 580 ha
    before = store.list("")
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path, check_bounds_ha=bounds)
    assert store.list("") == before


def test_the_bound_year_must_be_in_the_panel(tmp_path):
    store, manifests = world(tmp_path)
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path, check_year=2022)
