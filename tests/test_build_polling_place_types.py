import gzip
import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import polars as pl
import pytest
import shapefile
from shapely.geometry import box

from terrain.builds import polling_place_types as pt
from terrain.builds import polling_places as pp
from terrain.builds.polling_place_types import (
    BuildError,
    build,
    check_locality_coverage,
    check_one_row_per_place,
    check_typed,
    classify,
    eligible_voters,
    haversine_km,
    input_hash,
    read_urban_polygons,
    urban_clusters,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
TSE_FIXTURE = ROOT / "data" / "fixtures" / "tse" / "eleitorado_local_votacao_2024_sample.csv"
HIDALGO_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "geocoded_polling_stations_sample.csv"
PANEL_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "panel_ids_sample.csv"
LOCALITIES_FIXTURE = ROOT / "data" / "fixtures" / "ibge" / "BR_localidades_2022_sample.csv"
AREAS_FIXTURE = ROOT / "data" / "fixtures" / "ibge" / "AreasUrbanizadas2022_sample.geojson"
CONTRACT = ROOT / "data" / "contracts" / "polling_place_types.md"
DERIVED = dataset("polling_place_types")["derived"]

RAW_TSE = "data/raw/tse/polling_places/2026-11-02/"
RAW_HIDALGO = "data/raw/geocodes/hidalgo/2026-11-02/"
RAW_LOCALITIES = "data/raw/ibge/localities/2026-11-02/"
RAW_URBAN = "data/raw/ibge/urbanized_areas/2026-11-02/"
MUNICIPALITIES = "data/derived/municipalities/0123456789abcdef/"
YEARS = (2008, 2024)

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


def make_gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def csv_bytes(df: pl.DataFrame) -> bytes:
    return df.write_csv().encode("utf-8")


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


def locality_rows() -> list[list[str]]:
    return [
        line.split(",")
        for line in LOCALITIES_FIXTURE.read_text(encoding="utf-8").splitlines()[1:]
        if line
    ]


def gpkg_zip(tmp_path: Path, rows: list[list[str]]) -> bytes:
    """A zip with a SQLite file holding the localities table, as in the real GeoPackage."""
    path = tmp_path / "localities.gpkg"
    path.unlink(missing_ok=True)
    columns = LOCALITIES_FIXTURE.read_text(encoding="utf-8").splitlines()[0].split(",")
    with sqlite3.connect(path) as con:
        con.execute(f"CREATE TABLE BR_localidades_2022 ({', '.join(c + ' TEXT' for c in columns)})")
        con.executemany(
            f"INSERT INTO BR_localidades_2022 VALUES ({', '.join('?' * len(columns))})", rows
        )
    con.close()
    return zip_bytes({"Localidades_Brasil.gpkg": path.read_bytes()})


def shapefile_zip(tmp_path: Path, features: list[tuple[dict, str]]) -> bytes:
    """A zip holding a shapefile of (GeoJSON geometry, Tipo) polygons."""
    work = tmp_path / "shp"
    work.mkdir(exist_ok=True)
    writer = shapefile.Writer(str(work / "areas"), encoding="utf-8")
    writer.field("Tipo", "C", 40)
    writer.field("Densidade", "C", 20)
    for geometry, tipo in features:
        writer.shape(geometry)
        writer.record(tipo, "Densa")
    writer.close()
    (work / "areas.cpg").write_text("UTF-8", encoding="utf-8")
    return zip_bytes(
        {
            f"AreasUrbanizadas2022_Brasil.{ext}": (work / f"areas.{ext}").read_bytes()
            for ext in ("shp", "shx", "dbf", "cpg")
        }
    )


def fixture_features() -> list[tuple[dict, str]]:
    data = json.loads(AREAS_FIXTURE.read_text(encoding="utf-8"))
    return [(f["geometry"], f["properties"]["Tipo"]) for f in data["features"]]


def stage(
    store: MemoryStore, tmp_path: Path, *, localities: list[list[str]] | None = None
) -> tuple[dict, dict, dict, dict]:
    """Build `polling_places` from the fixtures into `store`; return the four manifests."""
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
        blob = make_gz(csv_bytes(pl.read_csv(source, infer_schema=False)))
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

    loc_blob = gpkg_zip(tmp_path, localities if localities is not None else locality_rows())
    loc_path = f"{RAW_LOCALITIES}Localidades_Brasil_gpkg.zip"
    store.create(loc_path, loc_blob)
    urban_blob = shapefile_zip(tmp_path, fixture_features())
    urban_path = f"{RAW_URBAN}AreasUrbanizadas2022_Brasil.zip"
    store.create(urban_path, urban_blob)
    return (
        pp_manifest,
        {
            "dataset": "ibge_localities",
            "gcs_prefix": RAW_LOCALITIES,
            "files": [entry(loc_path, loc_blob)],
        },
        {
            "dataset": "ibge_urbanized_areas",
            "gcs_prefix": RAW_URBAN,
            "files": [entry(urban_path, urban_blob)],
        },
        tse_manifest,
    )


def run(store: MemoryStore, manifests, tmp_path: Path, **kwargs) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kwargs.setdefault("years", YEARS)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kwargs)


def read_year(store: MemoryStore, manifest: dict, year: int) -> pl.DataFrame:
    (path,) = [f["path"] for f in manifest["files"] if f["path"].endswith(f"_{year}.parquet")]
    return pl.read_parquet(store.read_bytes(path))


def built(tmp_path: Path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    return store, manifests, run(store, manifests, tmp_path)


def counts(df: pl.DataFrame) -> dict[str, int]:
    found = df.group_by("place_type").len()
    return dict(zip(found["place_type"].to_list(), found["len"].to_list(), strict=True))


# --- Done when 1: the fixture counts


def test_fixture_places_are_typed_as_in_the_fixture_readme(tmp_path):
    store, _, manifest = built(tmp_path)
    out_2024 = read_year(store, manifest, 2024)
    assert out_2024.height == 18
    assert counts(out_2024) == {"seat": 5, "town": 3, "rural": 1, "dispersed": 9}

    out_2008 = read_year(store, manifest, 2008).filter(pl.col("sg_ue") == "04367")
    assert counts(out_2008) == {"seat": 9, "rural": 1, "dispersed": 4}


def test_output_columns_distances_and_manifest(tmp_path):
    store, _, manifest = built(tmp_path)
    assert validate_manifest(manifest, stage="build", dataset="polling_place_types") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    assert [f["path"].rsplit("/", 1)[-1] for f in manifest["files"]] == [
        "polling_place_types_2008.parquet",
        "polling_place_types_2024.parquet",
    ]
    out = read_year(store, manifest, 2024)
    assert out.columns == pt.OUTPUT_COLUMNS
    assert not out.select(pt.KEY).is_duplicated().any()
    assert out["seat_km"].null_count() == 0
    assert out["nearest_locality_km"].null_count() == 0
    seats = out.filter(pl.col("place_type") == "seat")
    assert seats["seat_km"].max() < 10
    assert "2024: rows=18, no_coordinates=0" in manifest["notes"]
    assert "seat=5 (0.2778)" in manifest["notes"]


# --- Done when 2-4: the rule on synthetic data


def places_frame(rows: list[tuple[str, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "lat": [r[1] for r in rows],
            "long": [r[2] for r in rows],
        },
        schema={"cd_ibge": pl.String, "lat": pl.Float64, "long": pl.Float64},
    )


def localities_frame(rows: list[tuple[str, str, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "category": [r[1] for r in rows],
            "lat": [r[2] for r in rows],
            "long": [r[3] for r in rows],
        },
        schema={
            "cd_ibge": pl.String,
            "category": pl.String,
            "lat": pl.Float64,
            "long": pl.Float64,
        },
    )


def square(lat: float, long: float, half: float = 0.01) -> dict:
    ring = [
        [long - half, lat - half],
        [long + half, lat - half],
        [long + half, lat + half],
        [long - half, lat + half],
        [long - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def test_empty_subdivision_is_not_urban(tmp_path):
    zip_path = tmp_path / "areas.zip"
    zip_path.write_bytes(
        shapefile_zip(
            tmp_path,
            [(square(-3.0, -50.0), "Loteamento vazio"), (square(-3.5, -50.0), "Área urbanizada")],
        )
    )
    polygons = read_urban_polygons(zip_path)
    assert len(polygons) == 1
    clusters = urban_clusters(polygons)

    places = places_frame([("X", -3.0, -50.0), ("X", -3.5, -50.0)])
    seat_far = localities_frame([("X", "Cidade", -3.5, -50.2)])
    typed, _ = classify(places, seat_far, clusters)
    # Inside the empty subdivision: no cluster, and the seat is 22 km away.
    assert typed["place_type"].to_list() == ["dispersed", "town"]

    # The same polygon as built-up area would have made the first point urban.
    zip_path.write_bytes(shapefile_zip(tmp_path, [(square(-3.0, -50.0), "Área urbanizada")]))
    clusters = urban_clusters(read_urban_polygons(zip_path))
    assert classify(places.head(1), seat_far, clusters)[0]["place_type"].to_list() == ["town"]


def test_shapes_outside_the_legal_amazon_box_are_dropped(tmp_path):
    zip_path = tmp_path / "areas.zip"
    zip_path.write_bytes(
        shapefile_zip(
            tmp_path,
            [(square(-23.5, -46.6), "Área urbanizada"), (square(-3.5, -50.0), "Área urbanizada")],
        )
    )
    assert len(read_urban_polygons(zip_path)) == 1


def test_clusters_merge_polygons_about_100_m_apart():
    near = [box(0.0, 0.0, 0.01, 0.01), box(0.0105, 0.0, 0.02, 0.01)]  # ~55 m gap
    far = [box(0.0, 0.0, 0.01, 0.01), box(0.03, 0.0, 0.04, 0.01)]
    assert len(urban_clusters(near)) == 1
    assert len(urban_clusters(far)) == 2
    assert urban_clusters([]) == []


def test_seat_outside_every_cluster_falls_back_to_2_km():
    seat = (-3.0, -50.0)
    towns = [box(-60.0, -10.0, -59.0, -9.0)]  # some other cluster
    places = places_frame(
        [("X", seat[0] + 0.008, seat[1]), ("X", seat[0] + 0.027, seat[1])]  # ~0.9 km, ~3.0 km
    )
    locs = localities_frame([("X", "Cidade", *seat)])
    typed, no_cluster = classify(places, locs, towns)
    assert no_cluster == ["X"]
    assert typed["place_type"].to_list() == ["seat", "rural"]
    assert typed["seat_km"].round(1).to_list() == [0.9, 3.0]


def test_manaus_case_a_closer_quilombola_locality_does_not_beat_the_seat_cluster():
    cluster = [box(-0.05, -0.05, 0.05, 0.05), box(1.0, 1.0, 1.05, 1.05)]
    locs = localities_frame(
        [
            ("X", "Cidade", 0.03, 0.03),
            ("X", "Localidade Quilombola", -0.041, -0.041),
        ]
    )
    places = places_frame([("X", -0.04, -0.04), ("X", 1.02, 1.02), ("X", 0.5, 0.5)])
    typed, no_cluster = classify(places, locs, cluster)
    assert no_cluster == []
    assert typed["nearest_locality_category"].to_list()[0] == "Localidade Quilombola"
    assert typed["nearest_locality_km"][0] < typed["seat_km"][0]
    assert typed["place_type"].to_list() == ["seat", "town", "dispersed"]


def test_countryside_types_follow_the_nearest_locality_of_the_same_municipality():
    locs = localities_frame(
        [
            ("X", "Cidade", 0.0, 0.0),
            ("X", "Localidade Indígena", 0.0, 0.1),
            ("X", "Localidade Quilombola", 0.0, 0.2),
            ("X", "Agrovila do PA", 0.0, 0.3),
            ("X", "Povoado", 0.0, 0.4),
            ("Y", "Cidade", 0.0, 0.5),
            ("Y", "Localidade Indígena", 0.0, 0.52),
        ]
    )
    places = places_frame(
        [
            ("X", 0.01, 0.1),
            ("X", 0.01, 0.2),
            ("X", 0.01, 0.3),
            ("X", 0.01, 0.4),
            # Y's seat and indigenous locality are 1 to 3 km away, but they are not X's:
            # X's nearest locality is 11 km off.
            ("X", 0.01, 0.52),
            ("X", 0.01, 0.1 + 0.05),  # 5.5 km from the nearest locality of X
            ("X", 0.01, 0.1 + 0.04),  # 4.4 km from it
        ]
    )
    typed, _ = classify(places, locs, [])
    assert typed["place_type"].to_list() == [
        "indigenous",
        "quilombola",
        "settlement",
        "rural",
        "dispersed",
        "dispersed",
        "indigenous",
    ]


def test_places_without_coordinates_get_no_type():
    places = places_frame([("X", 0.0, 0.0)]).vstack(
        pl.DataFrame({"cd_ibge": ["X"], "lat": [None], "long": [None]}, schema=pt_schema())
    )
    locs = localities_frame([("X", "Cidade", 0.0, 0.0)])
    typed, _ = classify(places, locs, [box(-1, -1, 1, 1)])
    assert typed["place_type"].to_list() == ["seat", None]
    assert typed["seat_km"].to_list()[1] is None


def pt_schema() -> dict:
    return {"cd_ibge": pl.String, "lat": pl.Float64, "long": pl.Float64}


def test_haversine_one_degree_of_latitude():
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.2, abs=0.1)


# --- Done when 5: eligible voters


def test_eligible_voters_are_the_round_1_sum_in_2024_and_null_in_2008(tmp_path):
    store, _, manifest = built(tmp_path)
    out = read_year(store, manifest, 2024)

    raw = pl.read_csv(
        TSE_FIXTURE,
        separator=";",
        encoding="utf8-lossy",
        schema_overrides={"CD_MUNICIPIO": pl.String},
    )
    expected = (
        raw.filter(pl.col("NR_TURNO") == 1)
        .group_by(
            pl.col("CD_MUNICIPIO").alias("sg_ue"),
            pl.col("NR_ZONA").cast(pl.Int32).alias("nr_zona"),
            pl.col("NR_LOCAL_VOTACAO").cast(pl.Int32).alias("nr_local_votacao"),
        )
        .agg(pl.col("QT_ELEITOR_SECAO").sum().alias("expected"))
    )
    joined = out.join(expected, on=["sg_ue", "nr_zona", "nr_local_votacao"], how="left")
    assert joined["expected"].null_count() == 0
    assert joined["eligible_voters"].to_list() == joined["expected"].to_list()
    assert out["eligible_voters"].sum() == raw["QT_ELEITOR_SECAO"].sum() > 0

    assert (
        read_year(store, manifest, 2008)["eligible_voters"].null_count()
        == read_year(store, manifest, 2008).height
    )


def test_eligible_voters_ignore_round_2_other_years_and_pad_the_code(tmp_path):
    header = (
        '"AA_ELEICAO";"NR_TURNO";"CD_MUNICIPIO";"NR_ZONA";"NR_LOCAL_VOTACAO";"QT_ELEITOR_SECAO"'
    )
    rows = [
        '2024;1;"4367";5;10;10',
        '2024;1;"4367";5;10;20',
        '2024;2;"4367";5;10;999',
        '2026;1;"4367";5;10;500',
        '2024;1;"4367";5;11;7',
    ]
    zip_path = tmp_path / "tse.zip"
    zip_path.write_bytes(
        zip_bytes(
            {"eleitorado_local_votacao_2024.csv": "\r\n".join([header, *rows]).encode("latin-1")}
        )
    )
    out = eligible_voters(zip_path, 2024).sort("nr_local_votacao")
    assert out["sg_ue"].to_list() == ["04367", "04367"]
    assert out["eligible_voters"].to_list() == [30, 7]

    zip_path.write_bytes(
        zip_bytes(
            {
                "eleitorado_local_votacao_2024.csv": "\r\n".join(
                    [header, '2024;1;"4367";5;10;x']
                ).encode()
            }
        )
    )
    with pytest.raises(BuildError, match="integer"):
        eligible_voters(zip_path, 2024)


# --- Done when 6: checks


def key_frame(**overrides) -> pl.DataFrame:
    data = {
        "ano": [2024, 2024],
        "cd_ibge": ["1507706", "1507706"],
        "sg_ue": ["05533", "05533"],
        "nr_zona": [48, 48],
        "nr_local_votacao": [1023, 1031],
        "lat": [-1.7, None],
        "long": [-49.5, None],
        "place_type": ["seat", None],
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


def test_type_present_check_raises_for_a_located_place_without_a_type():
    check_typed(key_frame())  # the unlocated place may have no type
    with pytest.raises(BuildError, match="no place_type"):
        check_typed(key_frame(place_type=[None, None]))


def test_locality_coverage_check_raises_without_a_locality_or_a_seat_point():
    locs = localities_frame([("A", "Cidade", 0.0, 0.0), ("B", "Povoado", 1.0, 1.0)])
    check_locality_coverage({"A"}, locs)
    with pytest.raises(BuildError, match="no locality"):
        check_locality_coverage({"A", "C"}, locs)
    with pytest.raises(BuildError, match="no seat point"):
        check_locality_coverage({"A", "B"}, locs)


def test_build_stops_and_uploads_nothing_when_a_municipality_has_no_locality(tmp_path):
    store = MemoryStore()
    rows = [r for r in locality_rows() if r[1] != "1507979"]
    manifests = stage(store, tmp_path, localities=rows)
    with pytest.raises(BuildError, match="no locality"):
        run(store, manifests, tmp_path)
    assert not store.list(DERIVED)


# --- Output path, determinism, no network


def test_changing_the_module_source_changes_the_output_prefix(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    first = run(store, manifests, tmp_path)

    files = [f for m in manifests for f in m["files"]]
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files, YEARS, code=["b"])
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files[:-1], YEARS, code=["a"])
    assert input_hash(files, YEARS, code=["a"]) == input_hash(files[::-1], YEARS, code=["a"])

    changed = tmp_path / "polling_place_types_changed.py"
    changed.write_text(
        Path(pt.__file__).read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8"
    )
    monkeypatch.setattr(pt, "CODE_MODULES", (changed,))
    second = run(store, manifests, tmp_path)
    assert second["status"] == "created"
    assert second["gcs_prefix"] != first["gcs_prefix"]


def test_second_run_is_unchanged(tmp_path):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    first = run(store, manifests, tmp_path)
    write_manifest(first, store, tmp_path / "manifest.json")
    assert store.exists(first["gcs_prefix"] + MANIFEST_NAME)
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == first["gcs_prefix"]


def test_inputs_are_deterministic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert gpkg_zip(tmp_path / "a", locality_rows()) == gpkg_zip(tmp_path / "b", locality_rows())
    assert shapefile_zip(tmp_path / "a", fixture_features()) == shapefile_zip(
        tmp_path / "b", fixture_features()
    )
    first = built(tmp_path / "a")[2]
    second = built(tmp_path / "b")[2]
    assert first["gcs_prefix"] == second["gcs_prefix"]


def test_the_contract_exists_and_names_the_checks():
    text = CONTRACT.read_text(encoding="utf-8")
    for word in ("place_type", "seat_km", "Loteamento vazio", "eligible_voters", "BuildError"):
        assert word in text
