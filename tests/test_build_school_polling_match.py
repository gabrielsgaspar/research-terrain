import hashlib
import io
import json
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import school_polling_match as spm
from terrain.builds.school_polling_match import (
    KEY,
    OUTPUT_COLUMNS,
    BuildError,
    build,
    check_one_row_per_place,
    check_schools,
    confidence,
    haversine_km,
    input_hash,
    match_year,
    normalise,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest
from terrain.storage import MemoryStore

DERIVED = dataset("school_polling_match")["derived"]
RAW_PLACES = "data/derived/polling_places/aaaa/"
RAW_CATALOGUE = "data/raw/inep/catalogue/2026-11-05/"

# One degree of latitude is about 111.2 km: 0.027 degrees is about 3 km.
LAT0, LON0 = -10.0, -50.0
LAT_3KM = LAT0 + 0.027

PLACE_NAME = "E M E F PROF JOSE DA SILVA"
SCHOOL_NAME = "ESCOLA MUNICIPAL PROFESSOR JOSE DA SILVA"


def place(n: int, name: str, *, cd_ibge: str = "1100015", cep=None, address="", lat=LAT0, lon=LON0):
    return {
        "ano": 2024,
        "cd_ibge": cd_ibge,
        "sg_ue": "00001",
        "nr_zona": 1,
        "nr_local_votacao": n,
        "nm_local_votacao": name,
        "ds_endereco": address,
        "nr_cep": cep,
        "lat": lat,
        "long": lon,
    }


def school(
    id_escola: str,
    name: str,
    *,
    id_municipio: str = "1100015",
    rede: str = "Municipal",
    street=None,
    number=None,
    cep=None,
    lat=LAT0,
    lon=LON0,
):
    return {
        "id_escola": id_escola,
        "nome_escola": name,
        "id_municipio": id_municipio,
        "rede": rede,
        "endereco": street,
        "numero": number,
        "cep": cep,
        "latitude": lat,
        "longitude": lon,
    }


PLACE_SCHEMA = {
    "ano": pl.Int64,
    "cd_ibge": pl.Utf8,
    "sg_ue": pl.Utf8,
    "nr_zona": pl.Int64,
    "nr_local_votacao": pl.Int64,
    "nm_local_votacao": pl.Utf8,
    "ds_endereco": pl.Utf8,
    "nr_cep": pl.Utf8,
    "lat": pl.Float64,
    "long": pl.Float64,
}
SCHOOL_SCHEMA = {
    "id_escola": pl.Utf8,
    "nome_escola": pl.Utf8,
    "id_municipio": pl.Utf8,
    "rede": pl.Utf8,
    "endereco": pl.Utf8,
    "numero": pl.Utf8,
    "cep": pl.Utf8,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
}


def places_df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=PLACE_SCHEMA)


def schools_df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHOOL_SCHEMA)


def one(places: list[dict], schools: list[dict]) -> dict:
    out = match_year(places_df(places), schools_df(schools))
    assert out.height == 1
    return out.row(0, named=True)


# --- Normalising and scores


def test_normalise_names_and_addresses():
    assert normalise("Escola Municipal Professor José da Silva", name=True) == "JOSE SILVA"
    assert normalise(PLACE_NAME, name=True) == "JOSE SILVA"
    assert normalise("Rua  São João, 12-A") == "RUA SAO JOAO 12 A"
    assert normalise("E.M. Dr. Ação", name=True) == "ACAO"
    assert normalise(None) == ""


def test_haversine_km():
    assert haversine_km(LAT0, LON0, LAT0, LON0) == 0.0
    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, abs=0.1)
    assert haversine_km(None, 0.0, 0.0, 0.0) is None
    assert haversine_km(float("nan"), 0.0, 0.0, 0.0) is None


@pytest.mark.parametrize(
    ("name_sim", "addr_sim", "cep_equal", "near", "expected"),
    [
        (0.90, 0.0, True, False, "high"),
        (0.90, 0.80, False, False, "high"),
        (0.95, 0.0, False, True, "high"),
        (0.95, 0.79, False, False, "medium"),
        (0.75, 0.0, True, False, "medium"),
        (0.80, 0.0, False, True, "medium"),
        (0.89, 0.99, False, False, "low"),
        (0.75, 0.0, False, False, "low"),
        (0.60, 0.0, True, True, "low"),
        (0.59, 1.0, True, True, "none"),
    ],
)
def test_confidence_thresholds(name_sim, addr_sim, cep_equal, near, expected):
    assert confidence(name_sim, addr_sim, cep_equal, near) == expected


# --- The Done-when cases


def test_same_cep_gives_high():
    row = one(
        [place(1, PLACE_NAME, cep="12345678", lat=None, lon=None)],
        [school("11", SCHOOL_NAME, cep="12345678", lat=None, lon=None)],
    )
    assert row["confidence"] == "high"
    assert row["id_escola"] == "11"
    assert row["rede"] == "Municipal"
    assert row["name_sim"] == 1.0
    assert row["cep_equal"] is True
    assert row["dist_km"] is None
    assert row["n_candidates"] == 1


def test_three_km_without_cep_or_address_gives_medium():
    row = one(
        [place(1, PLACE_NAME, cep="11111111", address="AV BRASIL 10", lat=LAT_3KM)],
        [school("11", SCHOOL_NAME, cep="22222222", street="RUA DAS FLORES", number="99")],
    )
    assert row["confidence"] == "medium"
    assert row["cep_equal"] is False
    assert row["addr_sim"] < 0.80
    assert row["dist_km"] == pytest.approx(3.0, abs=0.1)


def test_unrelated_name_gives_none_with_null_school():
    row = one(
        [place(1, "IGREJA BATISTA CENTRAL", cep="12345678")],
        [school("11", SCHOOL_NAME, cep="12345678"), school("12", "ESCOLA ESTADUAL ANA LIMA")],
    )
    assert row["confidence"] == "none"
    assert row["id_escola"] is None
    assert row["rede"] is None
    assert row["name_sim"] is None
    assert row["n_candidates"] == 0


def test_school_in_another_municipality_is_never_a_candidate():
    rows_places = [place(1, PLACE_NAME, cep="12345678")]
    other = school("11", SCHOOL_NAME, id_municipio="1100023", cep="12345678")
    row = one(rows_places, [other])
    assert row["confidence"] == "none"
    assert row["n_candidates"] == 0

    own = school("12", "COLEGIO ESTADUAL JOSE SILVA", cep="12345678")
    row = one(rows_places, [other, own])
    assert row["id_escola"] == "12"
    assert row["n_candidates"] == 1


def test_ties_go_to_the_smaller_id_escola():
    schools = [school("30", SCHOOL_NAME), school("20", SCHOOL_NAME), school("40", SCHOOL_NAME)]
    row = one([place(1, PLACE_NAME)], schools)
    assert row["id_escola"] == "20"
    assert row["n_candidates"] == 3


def test_better_confidence_then_better_name_beat_a_smaller_id():
    schools = [
        school("10", "ESCOLA JOSE SILVA SANTOS", cep=None, lat=None, lon=None),
        school("90", SCHOOL_NAME, cep="12345678"),
    ]
    row = one([place(1, PLACE_NAME, cep="12345678")], schools)
    assert row["id_escola"] == "90"
    assert row["confidence"] == "high"


def test_nearer_school_wins_when_scores_tie():
    schools = [school("10", SCHOOL_NAME, lat=LAT_3KM), school("90", SCHOOL_NAME, lat=LAT0)]
    row = one([place(1, PLACE_NAME)], schools)
    assert row["id_escola"] == "90"


def test_empty_names_never_match():
    row = one([place(1, "E M E F")], [school("11", "ESCOLA MUNICIPAL")])
    assert row["confidence"] == "none"


def test_output_has_exactly_the_output_columns_and_no_text():
    out = match_year(
        places_df([place(1, PLACE_NAME), place(2, "IGREJA BATISTA CENTRAL")]),
        schools_df([school("11", SCHOOL_NAME, street="RUA A", number="1")]),
    )
    assert out.columns == OUTPUT_COLUMNS
    assert not {"nome_escola", "nm_local_votacao", "ds_endereco", "endereco"} & set(out.columns)
    assert out.select(KEY).equals(out.select(KEY).sort(KEY))


# --- Checks


def test_check_one_row_per_place():
    source = places_df([place(1, "A"), place(2, "B")])
    check_one_row_per_place(source, match_year(source, schools_df([])))
    with pytest.raises(BuildError, match="rows"):
        check_one_row_per_place(source, match_year(source.head(1), schools_df([])))
    with pytest.raises(BuildError, match="missing"):
        check_one_row_per_place(
            source,
            match_year(source.head(1), schools_df([])).vstack(
                match_year(places_df([place(3, "C")]), schools_df([]))
            ),
        )
    with pytest.raises(BuildError, match="more than once in the input"):
        dup = places_df([place(1, "A"), place(1, "A")])
        check_one_row_per_place(dup, dup)


def test_check_schools_rejects_repeated_codes():
    check_schools(schools_df([school("1", "A"), school("2", "B")]))
    with pytest.raises(BuildError, match="id_escola"):
        check_schools(schools_df([school("1", "A"), school("1", "B")]))


# --- The build, on a small world


def parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def world(years=(2008, 2024), place_rows=None):
    """Two states (11, 15). State 11: one high, one none. State 15: one medium, one low."""
    store = MemoryStore()
    school_rows = [
        school("11", SCHOOL_NAME, cep="12345678"),
        school("21", "ESCOLA ESTADUAL MARIA OLIVEIRA", id_municipio="1500107", cep="99999999"),
        school("22", "ESCOLA ESTADUAL TANCREDO NEVES", id_municipio="1500107", lat=None, lon=None),
    ]
    catalogue = parquet_bytes(schools_df(school_rows))
    cat_path = RAW_CATALOGUE + "inep_school_catalogue.parquet"
    store.create(cat_path, catalogue)
    catalogue_manifest = {
        "dataset": "inep_school_catalogue",
        "gcs_prefix": RAW_CATALOGUE,
        "files": [entry(cat_path, catalogue)],
    }

    files = []
    for year in years:
        rows = place_rows or [
            place(1, PLACE_NAME, cep="12345678"),
            place(2, "IGREJA BATISTA CENTRAL"),
            place(3, "EEEF MARIA OLIVEIRA", cd_ibge="1500107", lat=LAT_3KM, cep="00000000"),
            place(4, "ESCOLA TANCREDO NEVES FILHO", cd_ibge="1500107", lat=None, lon=None),
        ]
        rows = [{**r, "ano": year} for r in rows]
        blob = parquet_bytes(places_df(rows))
        path = RAW_PLACES + f"polling_places_{year}.parquet"
        store.create(path, blob)
        files.append(entry(path, blob))
    places_manifest = {
        "dataset": "polling_places",
        "gcs_prefix": RAW_PLACES,
        "files": files,
    }
    return store, places_manifest, catalogue_manifest


def run_build(store, pm, cm, tmp_path, years=(2008, 2024)):
    return build(
        store,
        pm,
        cm,
        derived_root=DERIVED,
        tmp_dir=tmp_path,
        years=years,
        code_commit="abc123",
        created_at="2026-11-10T00:00:00+00:00",
    )


def test_build_writes_one_file_per_year_and_notes_the_rate_by_state(tmp_path):
    store, pm, cm = world()
    manifest = run_build(store, pm, cm, tmp_path)
    assert manifest["status"] == "created"
    assert validate_manifest(manifest, stage="build", dataset="school_polling_match") == []
    assert [f["path"].rsplit("/", 1)[-1] for f in manifest["files"]] == [
        "school_polling_match_2008.parquet",
        "school_polling_match_2024.parquet",
    ]
    assert manifest["inputs"] == [
        RAW_PLACES + MANIFEST_NAME,
        RAW_CATALOGUE + MANIFEST_NAME,
    ]

    first = manifest["files"][0]
    out = pl.read_parquet(io.BytesIO(store.read_bytes(first["path"])))
    assert out.columns == OUTPUT_COLUMNS
    levels = dict(zip(out["nr_local_votacao"], out["confidence"], strict=True))
    assert levels == {1: "high", 2: "none", 3: "medium", 4: "low"}

    notes = manifest["notes"].split("; ")
    assert len(notes) == 2
    for note, year in zip(notes, (2008, 2024), strict=True):
        assert note.startswith(f"{year}: places=4")
        assert "share_high=0.2500, share_medium=0.2500, share_low=0.2500, share_none=0.2500" in note
        assert "high_medium_rate_by_state=11=0.5000 15=0.5000" in note
        assert "shares_high/medium/low/none_by_state=11=0.5000/0.0000/0.0000/0.5000" in note
        assert "15=0.0000/0.5000/0.5000/0.0000" in note
        assert "places_sharing_a_school=0" in note


def test_notes_count_places_that_share_a_school(tmp_path):
    rows = [place(1, PLACE_NAME), place(2, PLACE_NAME + " ANEXO"), place(3, "IGREJA BATISTA")]
    store, pm, cm = world(years=(2024,), place_rows=rows)
    manifest = run_build(store, pm, cm, tmp_path, years=(2024,))
    assert "places_sharing_a_school=2" in manifest["notes"]


def test_second_run_is_unchanged(tmp_path):
    store, pm, cm = world()
    manifest = run_build(store, pm, cm, tmp_path)
    store.create(manifest["gcs_prefix"] + MANIFEST_NAME, json.dumps(manifest).encode("utf-8"))
    again = run_build(store, pm, cm, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == manifest["gcs_prefix"]


def test_bad_sha256_stops_the_build_and_uploads_nothing(tmp_path):
    store, pm, cm = world()
    pm["files"][1]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="sha256"):
        run_build(store, pm, cm, tmp_path)
    assert not [p for p in store.list(DERIVED)]


def test_output_path_changes_with_inputs_years_and_code():
    files = [{"sha256": "a" * 64}, {"sha256": "b" * 64}]
    base = input_hash(files, (2008, 2024), code=["x"])
    assert input_hash(list(reversed(files)), (2024, 2008), code=["x"]) == base
    assert input_hash(files, (2008,), code=["x"]) != base
    assert input_hash(files, (2008, 2024), code=["y"]) != base
    assert input_hash([{"sha256": "c" * 64}, files[1]], (2008, 2024), code=["x"]) != base
    assert spm.CODE_MODULES == (Path(spm.__file__),)
