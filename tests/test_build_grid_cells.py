import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapefile
from shapely.geometry import box

from terrain import grid
from terrain.builds import grid_cells as gc
from terrain.builds import polling_place_tenure as pt
from terrain.builds.grid_cells import BuildError, build, layer_shares
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
IBGE = ROOT / "data" / "fixtures" / "ibge"
CNFP_FIXTURES = {
    y: ROOT / "data" / "fixtures" / "cnfp" / f"cnfp_{y}_sample.geojson" for y in (2008, 2024, 2025)
}
CONTRACT = ROOT / "data" / "contracts" / "grid_cells.md"
DERIVED = dataset("grid_cells")["derived"]

RAW_2022 = "data/raw/ibge/grid_2022/2026-11-04/"
RAW_2010 = "data/raw/ibge/grid_2010/2026-11-04/"
RAW_BOUNDARIES = "data/raw/ibge/boundaries_2024/2026-11-04/"
RAW_CNFP = "data/raw/cnfp/2026-11-04/"
MUNICIPALITIES = "data/derived/municipalities/0123456789abcdef/"
YEARS = (2008, 2024)
EDITION_NAMES = {2008: "CNFP_2008.zip", 2024: "CNFP_2024_retificado.zip", 2025: "CNFP_2025.zip"}
TOWNS = ("1507706", "1507979")

# Fixed timestamps: otherwise the same fixture gives a different SHA-256 (and
# output path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

Feature = tuple[dict, dict]


# --- Inputs made from the fixtures


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), data)
    return buf.getvalue()


def geojson_features(path: Path) -> list[Feature]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(f["geometry"], f["properties"]) for f in data["features"]]


def shapefile_zip(
    work: Path, stem: str, fields: list[tuple[str, str, int, int]], features: list[Feature]
) -> bytes:
    """A zip holding `<stem>.shp/.shx/.dbf` with the given fields (name, type, size, decimals)."""
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / stem), encoding="utf-8")
    for name, kind, size, decimals in fields:
        writer.field(name, kind, size, decimals)
    for geometry, props in features:
        writer.shape(geometry)
        writer.record(*[props[name] for name, *_ in fields])
    writer.close()
    return zip_bytes(
        {f"{stem}.{ext}": (work / f"{stem}.{ext}").read_bytes() for ext in "shp shx dbf".split()}
    )


def grid_2022_zip(work: Path, features: list[Feature]) -> bytes:
    fields = [("nome_1KM", "C", 30, 0), ("TOTAL", "N", 12, 0), ("TOTAL_DOM", "N", 12, 0)]
    return shapefile_zip(work, "BR1KM", fields, features)


def grid_2010_zip(work: Path, features: list[Feature]) -> bytes:
    fields = [
        ("ID_UNICO", "C", 30, 0),
        ("nome_1KM", "C", 30, 0),
        ("POP", "N", 12, 0),
        ("DOM_OCU", "N", 12, 0),
    ]
    return shapefile_zip(work, "grade_id73", fields, features)


def boundaries_zip(work: Path, features: list[Feature]) -> bytes:
    return shapefile_zip(
        work, "BR_Municipios_2024", [("CD_MUN", "C", 7, 0), ("NM_MUN", "C", 60, 0)], features
    )


def cnfp_zip(work: Path, year: int, features: list[Feature]) -> bytes:
    old = year == 2008
    columns = (
        ["nome", "tipo_flor", "categoria", "data_cria"]
        if old
        else ["nome", "tipo", "categoria", "anocriacao"]
    )
    fields = [(c, "C", 120 if c == "nome" else 80, 0) for c in columns]
    padded = [(g, {c: p.get(c, "") for c in columns}) for g, p in features]
    return shapefile_zip(work / f"cnfp_{year}", f"CNFP_{year}", fields, padded)


def municipalities_bytes(path: Path, legal: list[str]) -> bytes:
    codes = sorted({*legal, "2905602"})
    pl.DataFrame(
        {
            "cd_ibge": codes,
            "cd_tse": ["0"] * len(codes),
            "uf": ["PA"] * len(codes),
            "name_ibge": codes,
            "name_tse": codes,
            "legal_amazon": [c in legal for c in codes],
            "name_check": ["exact"] * len(codes),
        }
    ).write_parquet(path)
    return path.read_bytes()


def km_polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
    """A rectangle given in Albers km, as a GeoJSON polygon in degrees (edges densified)."""
    t = np.linspace(0.0, 1.0, 41)
    xs = np.concatenate([x0 + (x1 - x0) * t, np.full(41, x1), x1 - (x1 - x0) * t, np.full(41, x0)])
    ys = np.concatenate([np.full(41, y0), y0 + (y1 - y0) * t, np.full(41, y1), y1 - (y1 - y0) * t])
    lon, lat = grid.km_to_lonlat(xs, ys)
    ring = [[float(a), float(b)] for a, b in zip(lon, lat, strict=True)]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def square(lat: float, long: float, half: float = 0.01) -> dict:
    ring = [
        [long - half, lat - half],
        [long + half, lat - half],
        [long + half, lat + half],
        [long - half, lat + half],
        [long - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def far_square() -> dict:
    return square(-3.0, -50.0)


def indigenous_properties(year: int) -> dict:
    if year == 2008:
        return {"nome": "TI", "tipo_flor": "TIPO A", "categoria": "Terra Indígena"}
    return {"nome": "TI", "tipo": "TIPO A", "categoria": "TI", "anocriacao": "01/01/1990"}


def with_indigenous(*polygons: dict) -> dict[int, list[Feature]]:
    return {y: [(g, indigenous_properties(y)) for g in polygons] for y in EDITION_NAMES}


def identity(features: list[Feature]) -> list[Feature]:
    return features


def stage(
    store: MemoryStore,
    tmp_path: Path,
    *,
    extra: dict[int, list[Feature]] | None = None,
    legal: list[str] | None = None,
    edit_2022: Callable[[list[Feature]], list[Feature]] = identity,
    edit_2010: Callable[[list[Feature]], list[Feature]] = identity,
    edit_boundaries: Callable[[list[Feature]], list[Feature]] = identity,
) -> tuple[dict, dict, dict, dict, dict]:
    """Write all five inputs into `store`; return their manifests in the order `build` takes."""
    tmp_path.mkdir(parents=True, exist_ok=True)

    def put(root: str, name: str, blob: bytes) -> dict:
        store.create(root + name, blob)
        return entry(root + name, blob)

    f2022 = edit_2022(geojson_features(IBGE / "BR1KM_2022_sample.geojson"))
    m2022 = {
        "dataset": "ibge_grid_2022",
        "gcs_prefix": RAW_2022,
        "files": [put(RAW_2022, "BR1KM_20251002.zip", grid_2022_zip(tmp_path / "g22", f2022))],
    }
    f2010 = edit_2010(geojson_features(IBGE / "grade_2010_sample.geojson"))
    m2010 = {
        "dataset": "ibge_grid_2010",
        "gcs_prefix": RAW_2010,
        "files": [put(RAW_2010, "grade_id73.zip", grid_2010_zip(tmp_path / "g10", f2010))],
    }
    towns = edit_boundaries(geojson_features(IBGE / "BR_Municipios_2024_sample.geojson"))
    towns = [(g, {"CD_MUN": p["CD_MUN"], "NM_MUN": p["NM_MUN"]}) for g, p in towns]
    mb = {
        "dataset": "ibge_boundaries_2024",
        "gcs_prefix": RAW_BOUNDARIES,
        "files": [
            put(RAW_BOUNDARIES, "BR_Municipios_2024.zip", boundaries_zip(tmp_path / "bnd", towns))
        ],
    }
    extra = extra or {}
    cnfp_files = []
    for edition, name in EDITION_NAMES.items():
        features = geojson_features(CNFP_FIXTURES[edition]) + extra.get(edition, [])
        cnfp_files.append(put(RAW_CNFP, name, cnfp_zip(tmp_path, edition, features)))
    mc = {"dataset": "cnfp_public_forests", "gcs_prefix": RAW_CNFP, "files": cnfp_files}
    mm = {
        "dataset": "municipalities",
        "gcs_prefix": MUNICIPALITIES,
        "files": [
            put(
                MUNICIPALITIES,
                "municipalities.parquet",
                municipalities_bytes(tmp_path / "mun.parquet", legal or list(TOWNS)),
            )
        ],
    }
    return m2022, m2010, mb, mc, mm


def run(store: MemoryStore, manifests, tmp_path: Path, **kwargs) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kwargs.setdefault("years", YEARS)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kwargs)


def read_output(store: MemoryStore, manifest: dict) -> pl.DataFrame:
    (path,) = [f["path"] for f in manifest["files"]]
    return pl.read_parquet(store.read_bytes(path))


def built(tmp_path: Path, **kwargs):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()), **kwargs)
    manifest = run(store, manifests, tmp_path)
    return store, manifests, manifest, read_output(store, manifest)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return built(tmp_path_factory.mktemp("base"))


def assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, match, **kwargs):
    with pytest.raises(BuildError, match=match):
        run(store, manifests, tmp_path, **kwargs)
    assert not store.list(DERIVED)


# --- Done when 2: the fixture totals


def test_fixture_build_has_240_cells_and_the_expected_totals(base):
    _, _, manifest, out = base
    assert out.height == 240
    by_town = out.group_by("cd_ibge").agg(
        pl.len().alias("cells"),
        pl.col("pop_2022").sum().alias("pop_2022"),
        pl.col("dom_2022").sum().alias("dom_2022"),
        pl.col("pop_2010").sum().alias("pop_2010"),
        pl.col("dom_2010").sum().alias("dom_2010"),
    )
    rows = {r["cd_ibge"]: r for r in by_town.iter_rows(named=True)}
    assert set(rows) == set(TOWNS)
    assert (rows["1507706"]["cells"], rows["1507979"]["cells"]) == (165, 75)
    assert (rows["1507706"]["pop_2022"], rows["1507979"]["pop_2022"]) == (15_117, 16_989)
    assert (rows["1507706"]["dom_2022"], rows["1507979"]["dom_2022"]) == (3_917, 4_451)
    assert (rows["1507706"]["pop_2010"], rows["1507979"]["pop_2010"]) == (12_266, 13_804)
    assert (rows["1507706"]["dom_2010"], rows["1507979"]["dom_2010"]) == (2_625, 2_896)
    assert validate_manifest(manifest, stage="build", dataset="grid_cells") == []


def test_columns_types_order_and_coordinates(base):
    _, _, _, out = base
    assert out.columns == gc.output_columns(YEARS)
    assert out.columns[-6:] == [
        "share_indigenous_2008",
        "share_settlement_2008",
        "share_undesignated_2008",
        "share_indigenous_2024",
        "share_settlement_2024",
        "share_undesignated_2024",
    ]
    for column in ("x_km", "y_km", "pop_2010", "dom_2010", "pop_2022", "dom_2022"):
        assert out.schema[column] == pl.Int64
    assert out.schema["nome_1KM"] == out.schema["cd_ibge"] == pl.String
    assert out["nome_1KM"].is_unique().all()
    assert out.equals(out.sort(["cd_ibge", "y_km", "x_km"]))
    for row in out.head(20).iter_rows(named=True):
        assert grid.parse_name(row["nome_1KM"]) == (row["x_km"], row["y_km"])
        lon, lat = grid.centre_lonlat(row["x_km"], row["y_km"])
        assert row["lon"] == pytest.approx(float(lon)) and row["lat"] == pytest.approx(float(lat))
    for column in gc.share_columns(YEARS):
        assert out[column].min() >= 0 and out[column].max() <= 1


def test_manifest_notes_name_states_and_layers(base):
    _, _, manifest, _ = base
    assert "state 15: cells=240" in manifest["notes"]
    assert "indigenous 2008: cells_with_share=" in manifest["notes"]
    assert "undesignated 2024: cells_with_share=" in manifest["notes"]
    assert manifest["gcs_prefix"].startswith(DERIVED)


# --- Done when 3: shares


def test_shares_of_a_polygon_covering_one_cell_exactly_and_in_half():
    cell = box(5, 5, 6, 6)
    table, area = layer_shares([cell])
    assert table.rows() == [(5, 5, 1.0)] and area == 1.0
    half, area = layer_shares([box(5, 5, 5.5, 6)])
    assert half.rows() == [(5, 5, 0.5)] and area == 0.5


def test_overlapping_polygons_count_once_and_other_cells_get_nothing():
    table, area = layer_shares([box(5, 5, 6, 6), box(5, 5, 6, 6), box(4.5, 5, 5.5, 6)])
    shares = {(x, y): s for x, y, s in table.rows()}
    assert shares == {(4, 5): 0.5, (5, 5): 1.0}
    assert (6, 5) not in shares
    assert area == 1.5
    assert sum(shares.values()) == area


def test_a_polygon_spanning_cells_sums_to_its_area():
    table, area = layer_shares([box(0.25, 0.25, 3.5, 2.75)])
    assert table["share"].sum() == pytest.approx(area)
    assert table.height == 4 * 3
    assert table.filter((pl.col("x_km") == 1) & (pl.col("y_km") == 1))["share"][0] == 1.0


def cell_column(out: pl.DataFrame, x: int, y: int, column: str) -> float:
    return out.filter((pl.col("x_km") == x) & (pl.col("y_km") == y))[column][0]


def test_build_shares_on_a_fixture_cell(tmp_path, base):
    _, _, _, probe = base
    x, y = probe.row(0, named=True)["x_km"], probe.row(0, named=True)["y_km"]
    whole = km_polygon(x - 0.1, y - 0.1, x + 1.1, y + 1.1)
    left_half = km_polygon(x - 2, y - 2, x + 0.5, y + 3)
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square(), whole, whole))
    out = read_output(store, run(store, manifests, tmp_path))
    assert cell_column(out, x, y, "share_indigenous_2024") == 1.0
    assert cell_column(out, x, y, "share_indigenous_2008") == 1.0
    # A cell the layer misses: the neighbour two cells away.
    assert out.filter(pl.col("share_indigenous_2024") == 0).height > 0

    store = MemoryStore()
    manifests = stage(store, tmp_path / "half", extra=with_indigenous(far_square(), left_half))
    out = read_output(store, run(store, manifests, tmp_path / "half"))
    assert cell_column(out, x, y, "share_indigenous_2024") == pytest.approx(0.5, abs=1e-4)


def test_overlapping_polygons_in_the_build_count_once(tmp_path, base):
    _, _, _, probe = base
    x, y = probe.row(0, named=True)["x_km"], probe.row(0, named=True)["y_km"]
    one = km_polygon(x - 0.1, y - 0.1, x + 1.1, y + 1.1)
    two = km_polygon(x - 0.2, y - 0.2, x + 1.2, y + 1.2)
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square(), one, two))
    out = read_output(store, run(store, manifests, tmp_path))
    assert cell_column(out, x, y, "share_indigenous_2024") == 1.0


def test_a_cell_the_layer_misses_has_share_zero(base):
    _, _, _, out = base
    # The only indigenous polygon is far away, so every cell has share 0.
    assert (out["share_indigenous_2008"] == 0).all()
    assert (out["share_indigenous_2024"] == 0).all()


def test_a_settlement_created_after_the_year_is_not_counted(tmp_path, base):
    _, _, _, probe = base
    x, y = probe.row(0, named=True)["x_km"], probe.row(0, named=True)["y_km"]
    late = (
        km_polygon(x - 0.1, y - 0.1, x + 1.1, y + 1.1),
        {"nome": "PA tardio", "categoria": "PA", "anocriacao": "01/01/2020"},
    )
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()) | {2025: [late]})
    out = read_output(store, run(store, manifests, tmp_path))
    assert cell_column(out, x, y, "share_settlement_2024") == 1.0
    assert out["share_settlement_2008"].equals(probe["share_settlement_2008"])


# --- Done when 4: checks


def test_check_functions_raise_on_their_own_input():
    gc.check_names(pl.Series(["1KME1N2", "1KME1N3"]))
    with pytest.raises(BuildError, match="do not parse"):
        gc.check_names(pl.Series(["1KME1N2", "200ME1N2"]))
    with pytest.raises(BuildError, match="duplicate"):
        gc.check_names(pl.Series(["1KME1N2", "1KME1N2"]))
    gc.check_one_municipality(np.array([0, 1, 1]))
    with pytest.raises(BuildError, match="more than one"):
        gc.check_one_municipality(np.array([1, 2]))
    gc.check_municipalities_covered({"a"}, {"a", "b"})
    with pytest.raises(BuildError, match="no cells"):
        gc.check_municipalities_covered({"a", "c"}, {"a"})
    parents = pl.DataFrame({"nome_1KM": ["a", "b"], "pop_2010": [1, None]})
    with pytest.raises(BuildError, match="2010 parent"):
        gc.check_parents(parents)
    gc.check_shares("indigenous", 2024, np.array([0.0, 1.0 + 1e-12]))
    for bad in (np.array([1.01]), np.array([-0.1]), np.array([np.nan])):
        with pytest.raises(BuildError, match="indigenous 2024"):
            gc.check_shares("indigenous", 2024, bad)
    gc.check_share_sum("settlement", 2024, 10.0, 10.0)
    with pytest.raises(BuildError, match="settlement 2024"):
        gc.check_share_sum("settlement", 2024, 10.02, 10.0)


def test_a_malformed_name_stops_the_build(tmp_path):
    def broken(features):
        (geometry, props), *rest = features
        return [(geometry, props | {"nome_1KM": "1KME12"}), *rest]

    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()), edit_2022=broken)
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "do not parse")


def test_a_repeated_name_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(
        store,
        tmp_path,
        extra=with_indigenous(far_square()),
        edit_2022=lambda features: [*features, features[0]],
    )
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "duplicate")


def test_a_kept_cell_without_a_2010_parent_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(
        store, tmp_path, extra=with_indigenous(far_square()), edit_2010=lambda features: []
    )
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "no 2010 parent")


def test_a_legal_amazon_municipality_without_cells_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(
        store, tmp_path, extra=with_indigenous(far_square()), legal=[*TOWNS, "1506351"]
    )
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "no cells")


def test_a_centre_in_two_municipalities_stops_the_build(tmp_path):
    def overlapping(features):
        geometry, props = features[0]
        return [*features, (geometry, props | {"CD_MUN": "1506351"})]

    store = MemoryStore()
    manifests = stage(
        store,
        tmp_path,
        extra=with_indigenous(far_square()),
        legal=[*TOWNS, "1506351"],
        edit_boundaries=overlapping,
    )
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "more than one")


def test_an_empty_layer_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)  # the fixtures hold no indigenous land
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "empty layers")


def test_a_share_above_one_stops_the_build(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    x, y = 4717, 11118
    table = pl.DataFrame({"x_km": [x], "y_km": [y], "share": [1.5]})
    monkeypatch.setattr(gc, "layer_shares", lambda polygons: (table, 10.0))
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "outside")


def test_shares_summing_to_more_than_the_union_stop_the_build(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    table = pl.DataFrame({"x_km": [4717], "y_km": [11118], "share": [0.9]})
    monkeypatch.setattr(gc, "layer_shares", lambda polygons: (table, 0.5))
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "more than the union")


def test_a_year_without_an_edition_is_refused(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    assert_fails_and_leaves_store_unchanged(
        store, manifests, tmp_path, "no register edition", years=(2010,)
    )


# --- Done when 5: output path


def test_a_second_run_is_unchanged_and_writes_nothing(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    first = run(store, manifests, tmp_path)
    assert first["status"] == "created"
    write_manifest(first, store, tmp_path / "manifest.json")
    assert store.exists(first["gcs_prefix"] + MANIFEST_NAME)
    before = store.list("")
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]
    assert store.list("") == before


def test_editing_grid_or_the_layer_rules_changes_the_output_path(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    first = run(store, manifests, tmp_path)

    files = [f for m in manifests for f in m["files"]]
    assert gc.input_hash(files, YEARS, code=["a"]) != gc.input_hash(files, YEARS, code=["b"])
    assert gc.input_hash(files, YEARS, code=["a"]) != gc.input_hash(files[:-1], YEARS, code=["a"])
    assert gc.input_hash(files, YEARS, code=["a"]) == gc.input_hash(files[::-1], YEARS, code=["a"])
    assert gc.input_hash(files, YEARS, code=["a"]) != gc.input_hash(files, (2024,), code=["a"])

    prefixes = {first["gcs_prefix"]}
    for original in (Path(grid.__file__), Path(pt.__file__)):
        changed = tmp_path / f"changed_{original.name}"
        changed.write_text(original.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
        modules = tuple(changed if m == original else m for m in gc.CODE_MODULES)
        monkeypatch.setattr(gc, "CODE_MODULES", modules)
        second = run(store, manifests, tmp_path)
        assert second["status"] == "created"
        prefixes.add(second["gcs_prefix"])
    assert len(prefixes) == 3


def test_an_input_that_differs_from_its_manifest_sha256_raises(tmp_path):
    store = MemoryStore()
    manifests = list(stage(store, tmp_path, extra=with_indigenous(far_square())))
    tampered = json.loads(json.dumps(manifests[1]))
    tampered["files"][0]["sha256"] = "0" * 64
    manifests[1] = tampered
    assert_fails_and_leaves_store_unchanged(store, manifests, tmp_path, "does not match")


# --- Done when 6: the contract


def test_the_contract_lists_every_output_column():
    text = CONTRACT.read_text(encoding="utf-8")
    for column in gc.output_columns(()):
        assert f"`{column}`" in text
    for layer in gc.LAYERS:
        assert f"`share_{layer}_<y>`" in text
    for word in ("BuildError", "make_valid", "lower-left", "STRtree"):
        assert word in text
