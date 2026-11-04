import hashlib
import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest
import shapefile
import shapely
from shapely.geometry import GeometryCollection, LineString, Point, box

from terrain.builds import figure_layers as fl
from terrain.builds import polling_place_tenure as pt
from terrain.builds.figure_layers import (
    BuildError,
    build,
    clip_to_frame,
    input_hash,
    keep_dimension,
    read_shapefile_zip,
    simplify,
)
from terrain.catalog import dataset
from terrain.manifest import validate_manifest, write_manifest
from terrain.storage import MemoryStore

# Some fixture fields are longer than the 80-byte test columns; the cut is harmless.
pytestmark = pytest.mark.filterwarnings("ignore::shapefile.PossibleDataLoss")

ROOT = Path(__file__).resolve().parents[1]
CNFP_FIXTURES = {
    y: ROOT / "data" / "fixtures" / "cnfp" / f"cnfp_{y}_sample.geojson" for y in (2024, 2025)
}
CONTRACT = ROOT / "data" / "contracts" / "figure_layers.md"
DERIVED = dataset("figure_layers")["derived"]

RAW_NE = "data/raw/naturalearth/2026-11-04/"
RAW_IBGE = "data/raw/ibge/boundaries_2024/2026-11-04/"
RAW_CNFP = "data/raw/cnfp/2026-11-04/"

# Fixed timestamps: otherwise the same input gives a different SHA-256 (and output
# path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

COUNTRIES = [("BRA", "Brazil", box(-60, -12, -40, 0)), ("PER", "Peru", box(-80, -14, -70, -2))]
OUTSIDE = ("ZZZ", "Faraway", box(10, 10, 12, 12))
AMAZON_OUTLINE = box(-70, -15, -45, 4)


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), data)
    return buf.getvalue()


def shp_zip(
    tmp_path: Path,
    stem: str,
    fields: list[tuple[str, str, int, int]],
    items: list[tuple[object, list]],
) -> bytes:
    """A zip holding one shapefile; `items` are (shapely geometry, record values)."""
    work = tmp_path / f"shp_{stem}"
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / stem), encoding="utf-8")
    for name, kind, size, decimals in fields:
        writer.field(name, kind, size, decimals)
    for geometry, values in items:
        writer.shape(shapely.geometry.mapping(geometry))
        writer.record(*values)
    writer.close()
    return zip_bytes(
        {f"{stem}.{ext}": (work / f"{stem}.{ext}").read_bytes() for ext in ("shp", "shx", "dbf")}
    )


def cnfp_zip(tmp_path: Path, year: int, features: list[tuple[dict, dict]]) -> bytes:
    work = tmp_path / f"cnfp_{year}"
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / "cnfp"), encoding="utf-8")
    columns = ["nome", "tipo", "categoria", "anocriacao"]
    for column in columns:
        writer.field(column, "C", 80)
    for geometry, props in features:
        writer.shape(geometry)
        writer.record(*[props.get(c, "") for c in columns])
    writer.close()
    return zip_bytes(
        {f"CNFP_{year}.{ext}": (work / f"cnfp.{ext}").read_bytes() for ext in ("shp", "shx", "dbf")}
    )


def fixture_features(year: int) -> list[tuple[dict, dict]]:
    data = json.loads(CNFP_FIXTURES[year].read_text(encoding="utf-8"))
    return [(f["geometry"], f["properties"]) for f in data["features"]]


def square(lat: float, long: float, half: float = 0.05) -> dict:
    ring = [
        [long - half, lat - half],
        [long + half, lat - half],
        [long + half, lat + half],
        [long - half, lat + half],
        [long - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


TI = (square(-3.0, -52.0), {"nome": "TI teste", "tipo": "TIPO A", "categoria": "TI"})
EARLY = (square(-4.0, -52.0), {"categoria": "PA", "anocriacao": "01/01/2020"})
LATE = (square(-5.0, -52.0), {"categoria": "PA", "anocriacao": "01/01/2025"})


def state_items(n: int) -> list[tuple[object, list]]:
    items = []
    for i in range(n):
        x = -60 + (i % 9) * 2.0
        y = -12 + (i // 9) * 2.0
        items.append((box(x, y, x + 1.5, y + 1.5), [f"S{i:02d}", f"State {i}"]))
    return items


def stage(
    store: MemoryStore,
    tmp_path: Path,
    *,
    countries=None,
    states: int = 27,
    amazon=AMAZON_OUTLINE,
    indigenous: bool = True,
    extra_2025=(EARLY, LATE),
) -> tuple[dict, dict, dict]:
    """Zip synthetic inputs into the store; return the three acquire manifests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    countries = [*COUNTRIES, OUTSIDE] if countries is None else countries
    ne = {
        "ne_10m_admin_0_countries.zip": shp_zip(
            tmp_path,
            "ne_10m_admin_0_countries",
            [("ADM0_A3", "C", 3, 0), ("NAME", "C", 40, 0)],
            [(g, [code, name]) for code, name, g in countries],
        ),
        "ne_10m_ocean.zip": shp_zip(
            tmp_path,
            "ne_10m_ocean",
            [("featurecla", "C", 10, 0)],
            [(box(-120, -80, 20, 40), ["Ocean"])],
        ),
        "ne_10m_lakes.zip": shp_zip(
            tmp_path,
            "ne_10m_lakes",
            [("name", "C", 40, 0), ("scalerank", "N", 3, 0)],
            [(box(-55, -5, -54, -4), ["Lago", 2]), (box(100, 0, 101, 1), ["Far lake", 0])],
        ),
        "ne_10m_rivers_lake_centerlines.zip": shp_zip(
            tmp_path,
            "ne_10m_rivers_lake_centerlines",
            [("name", "C", 40, 0), ("scalerank", "N", 3, 0)],
            [(LineString([(-60, -3), (-50, -3), (-40, -2)]), ["Rio", 1])],
        ),
    }
    ibge = {
        "BR_UF_2024.zip": shp_zip(
            tmp_path,
            "BR_UF_2024",
            [("SIGLA_UF", "C", 3, 0), ("NM_UF", "C", 40, 0)],
            state_items(states),
        ),
        "Limites_Amazonia_Legal_2024_shp.zip": shp_zip(
            tmp_path,
            "Limites_Amazonia_Legal_2024",
            [("NOME", "C", 40, 0)],
            [(amazon, ["Amazônia Legal"])],
        ),
    }
    cnfp = {
        "CNFP_2024_retificado.zip": cnfp_zip(
            tmp_path, 2024, fixture_features(2024) + ([TI] if indigenous else [])
        ),
        "CNFP_2025.zip": cnfp_zip(tmp_path, 2025, fixture_features(2025) + list(extra_2025)),
    }
    manifests = []
    for dataset_name, raw, blobs in (
        ("naturalearth_basemap", RAW_NE, ne),
        ("ibge_boundaries_2024", RAW_IBGE, ibge),
        ("cnfp_public_forests", RAW_CNFP, cnfp),
    ):
        files = []
        for name, blob in blobs.items():
            store.create(raw + name, blob)
            files.append(entry(raw + name, blob))
        manifests.append({"dataset": dataset_name, "gcs_prefix": raw, "files": files})
    return tuple(manifests)


def run(store: MemoryStore, manifests, tmp_path: Path) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc")


def read_output(store: MemoryStore, manifest: dict) -> pl.DataFrame:
    (path,) = [f["path"] for f in manifest["files"]]
    assert path.endswith("figure_layers.parquet")
    return pl.read_parquet(store.read_bytes(path))


def built(tmp_path: Path, **kwargs):
    store = MemoryStore()
    manifests = stage(store, tmp_path, **kwargs)
    return store, manifests, run(store, manifests, tmp_path)


def fixture_counts() -> dict[str, int]:
    f2024, f2025 = fixture_features(2024), fixture_features(2025)
    return {
        "settlement": sum(
            1
            for _, p in f2025
            if pt.is_settlement(p["categoria"])
            and (pt.creation_year(p["anocriacao"]) or 9999) <= 2024
        ),
        "undesignated": sum(1 for _, p in f2024 if pt.is_undesignated(p["tipo"])),
    }


# --- Done when 1: rows per layer, clipping


def test_rows_per_layer_and_the_manifest(tmp_path):
    store, _, manifest = built(tmp_path)
    out = read_output(store, manifest)
    assert out.columns == fl.OUTPUT_COLUMNS
    assert out.schema["scalerank"] == pl.Int64 and out.schema["geometry"] == pl.Binary
    counts = out.group_by("layer").len().to_dict(as_series=False)
    got = dict(zip(counts["layer"], counts["len"], strict=True))
    expected = fixture_counts()
    assert got == {
        "country": 2,
        "ocean": 1,
        "lake": 1,
        "river": 1,
        "state": 27,
        "legal_amazon": 1,
        "indigenous": 1,
        "settlement": expected["settlement"] + 1,
        "undesignated": expected["undesignated"],
    }
    assert out["layer"].to_list() == sorted(out["layer"].to_list())
    assert validate_manifest(manifest, stage="build", dataset="figure_layers") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    assert "indigenous=1 (before_simplify=1, dropped_empty=0)" in manifest["notes"]
    assert "state=27" in manifest["notes"]


def test_country_outside_the_frame_is_absent_and_the_ocean_is_clipped(tmp_path):
    store, _, manifest = built(tmp_path)
    out = read_output(store, manifest)
    countries = out.filter(pl.col("layer") == "country")
    assert sorted(countries["code"]) == ["BRA", "PER"]
    assert "Faraway" not in countries["name"].to_list()
    assert "Far lake" not in out.filter(pl.col("layer") == "lake")["name"].to_list()
    (ocean,) = out.filter(pl.col("layer") == "ocean")["geometry"]
    min_x, min_y, max_x, max_y = shapely.bounds(shapely.from_wkb(ocean))
    assert (min_x, min_y, max_x, max_y) == fl.FRAME_BOX


def test_codes_names_and_scalerank(tmp_path):
    store, _, manifest = built(tmp_path)
    out = read_output(store, manifest)
    brazil = out.filter(pl.col("code") == "BRA")
    assert brazil["name"].to_list() == ["Brazil"] and brazil["scalerank"].to_list() == [None]
    lake = out.filter(pl.col("layer") == "lake")
    assert lake["name"].to_list() == ["Lago"] and lake["scalerank"].to_list() == [2]
    assert out.filter(pl.col("layer") == "river")["scalerank"].to_list() == [1]
    assert out.filter(pl.col("layer") == "legal_amazon")["name"].to_list() == ["Amazônia Legal"]
    assert out.filter(pl.col("layer") == "indigenous")["code"].to_list() == [None]
    assert out.filter(pl.col("layer") == "state")["scalerank"].null_count() == 27


# --- Done when 2: settlement dates


def test_settlement_created_by_2024_is_kept_and_a_later_one_dropped(tmp_path):
    store, _, manifest = built(tmp_path)
    settlements = read_output(store, manifest).filter(pl.col("layer") == "settlement")
    shapes = [shapely.from_wkb(g) for g in settlements["geometry"]]
    assert any(s.contains(Point(-52.0, -4.0)) for s in shapes)
    assert not any(s.intersects(Point(-52.0, -5.0)) for s in shapes)
    assert len(shapes) == fixture_counts()["settlement"] + 1


# --- Done when 3: valid geometry


def test_every_geometry_reads_back_and_is_valid(tmp_path):
    store, _, manifest = built(tmp_path)
    out = read_output(store, manifest)
    geometries = [shapely.from_wkb(g) for g in out["geometry"]]
    assert len(geometries) == out.height > 0
    assert all(shapely.is_valid(g) and not shapely.is_empty(g) for g in geometries)
    rivers = [g for g, layer in zip(geometries, out["layer"], strict=True) if layer == "river"]
    assert all(g.geom_type in ("LineString", "MultiLineString") for g in rivers)


# --- Done when 4: each check fails on its own broken input


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"countries": [c for c in COUNTRIES if c[0] != "BRA"]},
            "no BRA",
        ),
        ({"states": 26}, "27 states"),
        ({"indigenous": False}, "empty layers"),
        ({"amazon": box(-90, -15, -45, 4)}, "Legal Amazon"),
    ],
)
def test_a_broken_input_raises_and_leaves_the_store_unchanged(tmp_path, kwargs, message):
    store = MemoryStore()
    manifests = stage(store, tmp_path, **kwargs)
    before = store.list("")
    with pytest.raises(BuildError, match=message):
        run(store, manifests, tmp_path)
    assert store.list("") == before
    assert not store.list(DERIVED)


def test_check_layers_catches_duplicate_state_codes_and_invalid_geometry():
    good = box(-60, -10, -50, 0)
    bowtie = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    rows = [(name, None, None, None, good) for name in fl.LAYER_NAMES if name != "state"]
    rows = [(r[0], "BRA" if r[0] == "country" else None, None, None, r[4]) for r in rows]
    states = [("state", f"S{i}", None, None, good) for i in range(27)]
    fl.check_layers(rows + states, {})
    with pytest.raises(BuildError, match="distinct codes"):
        fl.check_layers(rows + states[:26] + [("state", "S0", None, None, good)], {})
    with pytest.raises(BuildError, match="invalid geometries"):
        fl.check_layers([*rows, *states, ("river", None, None, None, bowtie)], {})
    with pytest.raises(BuildError, match="empty after simplifying"):
        fl.check_layers(rows + states, {"indigenous": (100, 2)})
    fl.check_layers(rows + states, {"indigenous": (100, 1)})


# --- Done when 5: output path and a second run


def test_second_run_is_unchanged_and_writes_nothing(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    first = run(store, manifests, tmp_path)
    assert first["status"] == "created"
    write_manifest(first, store, tmp_path / "manifest.json")
    objects = store.list("")
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]
    assert store.list("") == objects


def test_changing_the_tenure_module_source_changes_the_output_path(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    first = run(store, manifests, tmp_path)

    files = [f for m in manifests for f in m["files"]]
    assert input_hash(files, code=["a"]) != input_hash(files, code=["b"])
    assert input_hash(files, code=["a"]) != input_hash(files[:-1], code=["a"])
    assert input_hash(files, code=["a"]) == input_hash(files[::-1], code=["a"])
    assert Path(pt.__file__) in fl.CODE_MODULES and Path(fl.__file__) in fl.CODE_MODULES

    changed = tmp_path / "polling_place_tenure_changed.py"
    changed.write_text(
        Path(pt.__file__).read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8"
    )
    monkeypatch.setattr(fl, "CODE_MODULES", (Path(fl.__file__), changed))
    second = run(store, manifests, tmp_path)
    assert second["status"] == "created"
    assert second["gcs_prefix"] != first["gcs_prefix"]


# --- Done when 6: checksums


def test_a_file_that_differs_from_its_manifest_raises(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    ibge = manifests[1]
    ibge["files"][0]["sha256"] = "0" * 64
    before = store.list("")
    with pytest.raises(BuildError, match="sha256"):
        run(store, manifests, tmp_path)
    assert store.list("") == before


# --- Geometry helpers and reader


def test_keep_dimension_drops_stray_points_and_lines():
    mixed = GeometryCollection([box(0, 0, 1, 1), LineString([(2, 2), (3, 3)]), Point(5, 5)])
    assert keep_dimension(mixed, 2).equals(box(0, 0, 1, 1))
    assert keep_dimension(mixed, 1).equals(LineString([(2, 2), (3, 3)]))
    assert keep_dimension(Point(0, 0), 2) is None
    assert keep_dimension(GeometryCollection(), 2) is None


def test_simplify_repairs_and_clip_drops_what_misses_the_frame():
    bowtie = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    out = simplify(bowtie, 0.001)
    assert out is not None and shapely.is_valid(out)
    assert clip_to_frame(box(10, 10, 12, 12)) is None
    assert clip_to_frame(box(-26, -10, -20, -5)) is None  # touches the frame edge only
    assert clip_to_frame(box(-100, -60, 0, 20)).equals(fl.FRAME)


def test_read_shapefile_zip_reads_utf8_and_names_the_member(tmp_path):
    blob = shp_zip(tmp_path, "x", [("NOME", "C", 20, 0)], [(box(0, 0, 1, 1), ["Amazônia"])])
    path = tmp_path / "x.zip"
    path.write_bytes(blob)
    ((record, geometry),) = read_shapefile_zip(path)
    assert record["NOME"] == "Amazônia" and geometry.equals(box(0, 0, 1, 1))
    assert len(read_shapefile_zip(path, "x.shp")) == 1
    with pytest.raises(BuildError, match="not in"):
        read_shapefile_zip(path, "y.shp")


def test_the_contract_exists_and_names_the_rules():
    text = CONTRACT.read_text(encoding="utf-8")
    for word in ("figure_layers.parquet", "FRAME", "BRA", "27", "BuildError", "scalerank"):
        assert word in text
