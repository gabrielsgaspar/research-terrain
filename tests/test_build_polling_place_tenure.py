import gzip
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapefile
from shapely.geometry import box

from terrain.builds import polling_place_tenure as pt
from terrain.builds import polling_places as pp
from terrain.builds.polling_place_tenure import (
    BuildError,
    build,
    check_layers_nonempty,
    check_nonnegative,
    check_one_row_per_place,
    creation_year,
    extract_edition,
    input_hash,
    is_indigenous,
    is_settlement,
    is_undesignated,
    nearest_km,
    project_geometries,
    project_km,
    read_cnfp,
    settlement_layer,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
TSE_FIXTURE = ROOT / "data" / "fixtures" / "tse" / "eleitorado_local_votacao_2024_sample.csv"
HIDALGO_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "geocoded_polling_stations_sample.csv"
PANEL_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "panel_ids_sample.csv"
CNFP_FIXTURES = {
    y: ROOT / "data" / "fixtures" / "cnfp" / f"cnfp_{y}_sample.geojson" for y in (2008, 2024, 2025)
}
CONTRACT = ROOT / "data" / "contracts" / "polling_place_tenure.md"
DERIVED = dataset("polling_place_tenure")["derived"]

RAW_TSE = "data/raw/tse/polling_places/2026-11-02/"
RAW_HIDALGO = "data/raw/geocodes/hidalgo/2026-11-02/"
RAW_CNFP = "data/raw/cnfp/2026-11-04/"
MUNICIPALITIES = "data/derived/municipalities/0123456789abcdef/"
YEARS = (2008, 2024)
EDITION_NAMES = {2008: "CNFP_2008.zip", 2024: "CNFP_2024_retificado.zip", 2025: "CNFP_2025.zip"}

# Fixed timestamps: otherwise the same fixture gives a different SHA-256 (and
# output path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


# --- Inputs made from the fixtures


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), data)
    return buf.getvalue()


def municipalities_bytes(path: Path) -> bytes:
    rows = [
        ("1507706", "05533", True),
        ("1507979", "04367", True),
        ("1506351", "04243", True),
        ("2905602", "34118", False),
    ]
    pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "cd_tse": [r[1] for r in rows],
            "uf": ["PA", "PA", "PA", "BA"],
            "name_ibge": ["a", "b", "c", "d"],
            "name_tse": ["a", "b", "c", "d"],
            "legal_amazon": [r[2] for r in rows],
            "name_check": ["exact"] * 4,
        }
    ).write_parquet(path)
    return path.read_bytes()


def fixture_features(year: int) -> list[tuple[dict, dict]]:
    data = json.loads(CNFP_FIXTURES[year].read_text(encoding="utf-8"))
    return [(f["geometry"], f["properties"]) for f in data["features"]]


def square(lat: float, long: float, half: float = 0.01) -> dict:
    ring = [
        [long - half, lat - half],
        [long + half, lat - half],
        [long + half, lat + half],
        [long - half, lat + half],
        [long - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def indigenous_properties(year: int) -> dict:
    if year == 2008:
        return {
            "nome": "TI teste",
            "tipo_flor": "TIPO A",
            "categoria": "Terra Indígena",
            "data_cria": "01/01/1990",
        }
    return {"nome": "TI teste", "tipo": "TIPO A", "categoria": "TI", "anocriacao": "01/01/1990"}


def cnfp_zip(
    tmp_path: Path,
    year: int,
    features: list[tuple[dict, dict]],
    *,
    nome_size: int = 120,
) -> bytes:
    """A zip holding a shapefile in the real schema of the edition (2008 or 2012 onward)."""
    work = tmp_path / f"shp_{year}"
    work.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(work / "cnfp"), encoding="utf-8")
    old = year == 2008
    columns = (
        ["nome", "tipo_flor", "categoria", "data_cria"]
        if old
        else ["nome", "tipo", "categoria", "anocriacao"]
    )
    for column in columns:
        writer.field(column, "C", nome_size if column == "nome" else 80)
    for geometry, props in features:
        writer.shape(geometry)
        writer.record(*[props.get(c, "") for c in columns])
    writer.close()
    return zip_bytes(
        {f"CNFP_{year}.{ext}": (work / f"cnfp.{ext}").read_bytes() for ext in ("shp", "shx", "dbf")}
    )


def stage(
    store: MemoryStore,
    tmp_path: Path,
    *,
    extra: dict[int, list[tuple[dict, dict]]] | None = None,
    nome_size: int = 120,
) -> tuple[dict, dict]:
    """Build `polling_places` from the fixtures and add CNFP zips; return the two manifests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    tse_blob = zip_bytes({"eleitorado_local_votacao_2024.csv": TSE_FIXTURE.read_bytes()})
    store.create(f"{RAW_TSE}eleitorado_local_votacao_2024.zip", tse_blob)
    tse_manifest = {
        "dataset": "tse_polling_places",
        "gcs_prefix": RAW_TSE,
        "files": [entry(f"{RAW_TSE}eleitorado_local_votacao_2024.zip", tse_blob)],
    }
    hid_files = []
    for name, source in (
        ("geocoded_polling_stations.csv.gz", HIDALGO_FIXTURE),
        ("panel_ids.csv.gz", PANEL_FIXTURE),
    ):
        blob = gzip.compress(
            pl.read_csv(source, infer_schema=False).write_csv().encode("utf-8"), mtime=0
        )
        store.create(RAW_HIDALGO + name, blob)
        hid_files.append(entry(RAW_HIDALGO + name, blob))
    hidalgo_manifest = {
        "dataset": "polling_stations_geocoded",
        "gcs_prefix": RAW_HIDALGO,
        "files": hid_files,
    }
    mun_blob = municipalities_bytes(tmp_path / "municipalities_in.parquet")
    store.create(MUNICIPALITIES + "municipalities.parquet", mun_blob)
    mun_manifest = {
        "dataset": "municipalities",
        "gcs_prefix": MUNICIPALITIES,
        "files": [entry(MUNICIPALITIES + "municipalities.parquet", mun_blob)],
    }
    pp_work = tmp_path / "pp_work"
    pp_work.mkdir(exist_ok=True)
    pp_manifest = pp.build(
        store,
        tse_manifest,
        hidalgo_manifest,
        mun_manifest,
        derived_root=dataset("polling_places")["derived"],
        tmp_dir=pp_work,
        years=YEARS,
        code_commit="abc",
    )

    extra = extra or {}
    cnfp_files = []
    for edition, name in EDITION_NAMES.items():
        features = fixture_features(edition) + extra.get(edition, [])
        blob = cnfp_zip(tmp_path, edition, features, nome_size=nome_size)
        store.create(RAW_CNFP + name, blob)
        cnfp_files.append(entry(RAW_CNFP + name, blob))
    return pp_manifest, {
        "dataset": "cnfp_public_forests",
        "gcs_prefix": RAW_CNFP,
        "files": cnfp_files,
    }


def with_indigenous(*squares: dict) -> dict[int, list[tuple[dict, dict]]]:
    return {y: [(g, indigenous_properties(y)) for g in squares] for y in EDITION_NAMES}


def run(store: MemoryStore, manifests, tmp_path: Path, **kwargs) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kwargs.setdefault("years", YEARS)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kwargs)


def read_year(store: MemoryStore, manifest: dict, year: int) -> pl.DataFrame:
    (path,) = [f["path"] for f in manifest["files"] if f["path"].endswith(f"_{year}.parquet")]
    return pl.read_parquet(store.read_bytes(path))


def place_coordinates(store: MemoryStore, pp_manifest: dict, year: int) -> pl.DataFrame:
    (path,) = [f["path"] for f in pp_manifest["files"] if f["path"].endswith(f"_{year}.parquet")]
    return pl.read_parquet(store.read_bytes(path)).sort(pt.KEY)


def built(tmp_path: Path, **kwargs):
    store = MemoryStore()
    manifests = stage(store, tmp_path, **kwargs)
    return store, manifests, run(store, manifests, tmp_path)


def indigenous_built(tmp_path: Path, *squares: dict):
    return built(tmp_path, extra=with_indigenous(*squares))


def far_square() -> dict:
    return square(-3.0, -50.0)


# --- Done when 1 and 2: the fixture counts


def test_2024_places_against_settlements_and_undesignated_land(tmp_path):
    store, _, manifest = indigenous_built(tmp_path, far_square())
    out = read_year(store, manifest, 2024)
    assert out.height == 18
    assert (out["dist_settlement_km"] == 0).sum() == 5
    assert (out["dist_settlement_km"] <= 2).sum() == 15
    assert (out["dist_settlement_km"] <= 5).sum() == 15
    assert (out["dist_undesignated_km"] <= 5).sum() == 0


def test_2008_stations_of_town_04367(tmp_path):
    store, _, manifest = indigenous_built(tmp_path, far_square())
    out = read_year(store, manifest, 2008).filter(pl.col("sg_ue") == "04367")
    assert out.height == 14
    settlement, undesignated = out["dist_settlement_km"], out["dist_undesignated_km"]
    assert [(settlement <= t).sum() for t in (0, 2, 5)] == [0, 3, 12]
    assert [(undesignated <= t).sum() for t in (0, 2, 5)] == [2, 12, 14]


def test_output_columns_types_and_manifest(tmp_path):
    store, (pp_manifest, _), manifest = indigenous_built(tmp_path, far_square())
    assert validate_manifest(manifest, stage="build", dataset="polling_place_tenure") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    assert [f["path"].rsplit("/", 1)[-1] for f in manifest["files"]] == [
        "polling_place_tenure_2008.parquet",
        "polling_place_tenure_2024.parquet",
    ]
    for year in YEARS:
        out = read_year(store, manifest, year)
        source = place_coordinates(store, pp_manifest, year)
        assert out.columns == pt.OUTPUT_COLUMNS
        assert out.select(pt.KEY).equals(source.select(pt.KEY))
        for column in ("nr_zona", "nr_local_votacao"):
            assert out.schema[column] == source.schema[column]
        assert all(out[c].null_count() == 0 for c in pt.DISTANCES)
    assert "2024: places=18, no_coordinates=0" in manifest["notes"]
    assert "settlement_polygons=" in manifest["notes"]
    assert "settlements_without_year=" in manifest["notes"]


# --- Done when 3: indigenous land and distances


def test_a_fixture_place_inside_an_indigenous_land_has_distance_zero(tmp_path):
    store = MemoryStore()
    pp_manifest, cnfp_manifest = stage(store, tmp_path / "probe")
    places = place_coordinates(store, pp_manifest, 2024)
    a = places.row(0, named=True)
    store2 = MemoryStore()
    manifests = stage(store2, tmp_path / "real", extra=with_indigenous(square(a["lat"], a["long"])))
    out = read_year(store2, run(store2, manifests, tmp_path), 2024)
    mine = out.join(places.select(pt.KEY), on=pt.KEY).sort(pt.KEY)
    assert mine["dist_indigenous_km"][0] == 0


def test_a_place_about_3_km_from_an_indigenous_land(tmp_path):
    store = MemoryStore()
    pp_manifest, _ = stage(store, tmp_path / "probe")
    places = place_coordinates(store, pp_manifest, 2024)
    b = places.row(0, named=True)
    # A small square whose west edge is 3 km east of the place, on its latitude.
    edge = b["long"] + 3.0 / (pt.KM_PER_DEGREE_LON * math.cos(math.radians(b["lat"])))
    land = square(b["lat"], edge + 0.005, half=0.005)
    store2 = MemoryStore()
    manifests = stage(store2, tmp_path / "real", extra=with_indigenous(land))
    out = read_year(store2, run(store2, manifests, tmp_path), 2024)
    assert 2.9 < out["dist_indigenous_km"][0] < 3.1


def test_nearest_km_inside_outside_and_without_coordinates():
    land = project_geometries([box(-50.01, -3.01, -49.99, -2.99)])
    far_lon = -49.99 + 3.0 / (pt.KM_PER_DEGREE_LON * math.cos(math.radians(-3.0)))
    got = nearest_km([-50.0, far_lon, float("nan")], [-3.0, -3.0, float("nan")], land)
    assert got[0] == 0
    assert got[1] == pytest.approx(3.0, abs=0.05)
    assert math.isnan(got[2])
    assert np.isnan(nearest_km([-50.0], [-3.0], [])).all()


def test_projection_is_within_one_percent_of_great_circle_at_amazon_distances():
    x1, y1 = project_km(-50.0, -3.0)
    x2, y2 = project_km(-50.0, -3.1)
    assert float(np.hypot(x2 - x1, y2 - y1)) == pytest.approx(11.06, abs=0.12)


# --- Done when 4: settlement dates


def test_group_rules():
    assert is_indigenous("TI") and is_indigenous("Terra Indígena")
    assert is_indigenous("PAE / TI") and is_indigenous("GLEBA; Terra Ind�gena")
    assert not is_indigenous("TRQ") and not is_indigenous(None)
    assert is_settlement("PA") and is_settlement("PAE / APA") and is_settlement("PDS;TI")
    assert not is_settlement("APA / PAE") and not is_settlement("TI") and not is_settlement("")
    assert is_undesignated("TIPO B") and is_undesignated(" TIPO B ")
    assert not is_undesignated("TIPO A") and not is_undesignated(None)


def test_creation_year_takes_the_first_year_in_range():
    assert creation_year("01/01/2020") == 2020
    assert creation_year("05-10-1989") == 1989
    assert creation_year("07/11/2006 / 05-10-1989") == 2006
    assert creation_year("12345 and 1799 and 2100") is None
    assert creation_year("") is None and creation_year(None) is None
    assert creation_year("0/0/0000 1995") == 1995


def test_settlement_created_after_the_election_year_is_not_in_its_layer():
    settlements = [("a", 2020), ("b", 2005), ("c", None)]
    assert settlement_layer(settlements, 2016) == ["b"]
    assert settlement_layer(settlements, 2020) == ["a", "b"]
    assert settlement_layer(settlements, 2024) == ["a", "b"]


def test_a_2025_settlement_dated_2020_counts_for_2024_not_2008(tmp_path):
    store = MemoryStore()
    pp_manifest, _ = stage(store, tmp_path / "probe")
    a = place_coordinates(store, pp_manifest, 2024).row(0, named=True)
    late = (square(a["lat"], a["long"], 0.0005), {"categoria": "PA", "anocriacao": "01/01/2020"})
    base = with_indigenous(far_square())
    outputs = {}
    for name, extra in (("base", base), ("late", base | {2025: [late]})):
        s = MemoryStore()
        manifests = stage(s, tmp_path / name, extra=extra)
        manifest = run(s, manifests, tmp_path / name)
        outputs[name] = {y: read_year(s, manifest, y) for y in YEARS}
    first = pl.all_horizontal(pl.col(k) == a[k] for k in pt.KEY)
    assert outputs["late"][2024].filter(first)["dist_settlement_km"][0] == 0
    # In 2008 the polygon (created 2020) is not in the layer: nothing changes.
    assert outputs["late"][2008].equals(outputs["base"][2008])


# --- Done when 5: text cut mid-character


@pytest.mark.filterwarnings("ignore::shapefile.PossibleDataLoss")
def test_text_cut_mid_character_does_not_stop_the_build(tmp_path):
    cut = (square(-3.0, -50.0), {"nome": "ÁÁÁÁ", "categoria": "PA", "anocriacao": "01/01/2000"})
    zip_path = tmp_path / "CNFP_2024.zip"
    zip_path.write_bytes(cnfp_zip(tmp_path, 2024, [cut], nome_size=5))
    dest = tmp_path / "unpacked"
    dest.mkdir()
    features = read_cnfp(extract_edition(zip_path, dest))
    assert len(features) == 1 and features[0].categoria == "PA"

    # Every field of every edition is cut to 5 bytes, so most names end mid-character.
    extra = with_indigenous(far_square())
    extra[2024] = [*extra[2024], cut]
    store2 = MemoryStore()
    manifests = stage(store2, tmp_path / "c", extra=extra, nome_size=5)
    assert run(store2, manifests, tmp_path / "c")["status"] == "created"


def test_empty_and_far_shapes_are_skipped(tmp_path):
    work = tmp_path / "shp"
    work.mkdir()
    writer = shapefile.Writer(str(work / "cnfp"), encoding="utf-8")
    for column in ("nome", "tipo", "categoria", "anocriacao"):
        writer.field(column, "C", 40)
    writer.null()
    writer.record("empty", "TIPO B", "PA", "")
    writer.shape(square(-23.5, -46.6))
    writer.record("outside", "TIPO B", "PA", "")
    writer.shape(square(-3.5, -50.0))
    writer.record("inside", "TIPO B", "PA", "")
    writer.close()
    features = read_cnfp(work / "cnfp.shp")
    assert [f.tipo for f in features] == ["TIPO B"]


# --- Done when 6: checks


def key_frame(**overrides) -> pl.DataFrame:
    data = {
        "ano": [2024, 2024],
        "cd_ibge": ["1507706", "1507706"],
        "sg_ue": ["05533", "05533"],
        "nr_zona": [48, 48],
        "nr_local_votacao": [1023, 1031],
        "dist_indigenous_km": [1.0, None],
        "dist_settlement_km": [0.0, None],
        "dist_undesignated_km": [5.0, None],
    }
    data.update(overrides)
    return pl.DataFrame(data)


def test_one_row_per_place_check_raises_on_a_repeat_a_gap_or_a_stranger():
    source = key_frame()
    check_one_row_per_place(source, source)
    with pytest.raises(BuildError, match="more than once"):
        check_one_row_per_place(source, key_frame(nr_local_votacao=[1023, 1023]))
    with pytest.raises(BuildError, match="output rows"):
        check_one_row_per_place(source, source.head(1))
    with pytest.raises(BuildError, match="missing"):
        check_one_row_per_place(source, key_frame(nr_local_votacao=[1023, 9999]))


def test_layer_check_raises_on_an_empty_layer():
    sizes = {"indigenous": 1, "settlement": 2, "undesignated": 3}
    check_layers_nonempty(2024, sizes)
    for name in sizes:
        with pytest.raises(BuildError, match=name):
            check_layers_nonempty(2024, sizes | {name: 0})


def test_nonnegative_check_raises_on_a_negative_distance():
    check_nonnegative(key_frame())
    with pytest.raises(BuildError, match="dist_settlement_km"):
        check_nonnegative(key_frame(dist_settlement_km=[-0.1, None]))


def test_build_without_indigenous_land_stops_and_uploads_nothing(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)  # the fixtures have no indigenous land
    with pytest.raises(BuildError, match="empty layers"):
        run(store, manifests, tmp_path)
    assert not store.list(DERIVED)


def test_build_with_a_negative_distance_uploads_nothing(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    monkeypatch.setattr(pt, "nearest_km", lambda lon, lat, polygons: np.full(len(lon), -1.0))
    with pytest.raises(BuildError, match="negative"):
        run(store, manifests, tmp_path)
    assert not store.list(DERIVED)


def test_build_with_a_bad_row_count_uploads_nothing(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))

    def broken(source, out):
        raise BuildError("broken")

    monkeypatch.setattr(pt, "check_one_row_per_place", broken)
    with pytest.raises(BuildError, match="broken"):
        run(store, manifests, tmp_path)
    assert not store.list(DERIVED)


def test_a_year_without_an_edition_is_refused(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    with pytest.raises(BuildError, match="no register edition"):
        run(store, manifests, tmp_path, years=(2010,))


# --- Done when 7: output path


def test_changing_the_module_source_changes_the_output_prefix(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    first = run(store, manifests, tmp_path)

    files = [f for m in manifests for f in m["files"]]
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files, YEARS, code=["b"])
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files[:-1], YEARS, code=["a"])
    assert input_hash(files, YEARS, code=["a"]) == input_hash(files[::-1], YEARS, code=["a"])

    changed = tmp_path / "polling_place_tenure_changed.py"
    changed.write_text(
        Path(pt.__file__).read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8"
    )
    monkeypatch.setattr(pt, "CODE_MODULES", (changed,))
    second = run(store, manifests, tmp_path)
    assert second["status"] == "created"
    assert second["gcs_prefix"] != first["gcs_prefix"]


def test_second_run_is_unchanged(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path, extra=with_indigenous(far_square()))
    first = run(store, manifests, tmp_path)
    write_manifest(first, store, tmp_path / "manifest.json")
    assert store.exists(first["gcs_prefix"] + MANIFEST_NAME)
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]


def test_the_contract_exists_and_names_the_rules():
    text = CONTRACT.read_text(encoding="utf-8")
    for word in ("dist_indigenous_km", "TIPO B", "2025", "BuildError", "coverage", "TRQ"):
        assert word in text
