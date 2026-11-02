import gzip
import hashlib
import io
import re
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import polling_places as pp
from terrain.builds.polling_places import (
    BuildError,
    build,
    check_coverage,
    check_key,
    check_legal_amazon,
    collapse_places,
    input_hash,
    read_hidalgo,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
TSE_FIXTURE = ROOT / "data" / "fixtures" / "tse" / "eleitorado_local_votacao_2024_sample.csv"
HIDALGO_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "geocoded_polling_stations_sample.csv"
PANEL_FIXTURE = ROOT / "data" / "fixtures" / "hidalgo" / "panel_ids_sample.csv"
CONTRACT = ROOT / "data" / "contracts" / "polling_places.md"
DERIVED = dataset("polling_places")["derived"]

RAW_TSE = "data/raw/tse/polling_places/2026-11-02/"
RAW_HIDALGO = "data/raw/geocodes/hidalgo/2026-11-02/"
MUNICIPALITIES = "data/derived/municipalities/0123456789abcdef/"
YEARS = (2008, 2024)

# Fixed timestamps: otherwise the same fixture gives a different SHA-256 (and
# output path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

# Field positions in a TSE polling-place row (split on ";").
F_ZONE, F_PLACE, F_PHONE, F_LAT, F_LONG = 9, 14, 21, 22, 23


# --- Inputs made from the fixtures


def make_zip(year: int, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo(f"eleitorado_local_votacao_{year}.csv", FIXED_TIME), data)
        zf.writestr(zipfile.ZipInfo("leiame.pdf", FIXED_TIME), b"%PDF-")
    return buf.getvalue()


def make_gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def edit_rows(data: bytes, fn) -> bytes:
    """Rewrite the TSE rows: `fn(fields)` returns the list of rows (each a field list)."""
    lines = data.split(b"\r\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line:
            out.extend(b";".join(fields) for fields in fn(line.split(b";")))
    return b"\r\n".join(out) + b"\r\n"


def tse_bytes() -> bytes:
    return TSE_FIXTURE.read_bytes()


def hidalgo_frame() -> pl.DataFrame:
    return pl.read_csv(HIDALGO_FIXTURE, infer_schema=False)


def panel_frame() -> pl.DataFrame:
    return pl.read_csv(PANEL_FIXTURE, infer_schema=False)


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


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def stage(
    store: MemoryStore,
    tmp_path: Path,
    *,
    tse: bytes | None = None,
    hidalgo: pl.DataFrame | None = None,
    panel: pl.DataFrame | None = None,
    with_tse: bool = True,
) -> tuple[dict, dict, dict]:
    """Put the inputs in `store`; return the TSE, Hidalgo and municipalities manifests."""
    tse_files = []
    if with_tse:
        blob = make_zip(2024, tse if tse is not None else tse_bytes())
        path = f"{RAW_TSE}eleitorado_local_votacao_2024.zip"
        store.create(path, blob)
        tse_files.append(entry(path, blob))
    hid_files = []
    for name, frame, default in (
        ("geocoded_polling_stations.csv.gz", hidalgo, hidalgo_frame),
        ("panel_ids.csv.gz", panel, panel_frame),
    ):
        blob = make_gz(csv_bytes(frame if frame is not None else default()))
        store.create(RAW_HIDALGO + name, blob)
        hid_files.append(entry(RAW_HIDALGO + name, blob))
    mun_blob = municipalities_bytes(tmp_path / "municipalities_in.parquet")
    store.create(MUNICIPALITIES + "municipalities.parquet", mun_blob)
    mun_files = [entry(MUNICIPALITIES + "municipalities.parquet", mun_blob)]
    return (
        {"dataset": "tse_polling_places", "gcs_prefix": RAW_TSE, "files": tse_files},
        {"dataset": "polling_stations_geocoded", "gcs_prefix": RAW_HIDALGO, "files": hid_files},
        {"dataset": "municipalities", "gcs_prefix": MUNICIPALITIES, "files": mun_files},
    )


def run(store: MemoryStore, manifests, tmp_path: Path, **kwargs) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kwargs.setdefault("years", YEARS)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kwargs)


def read_year(store: MemoryStore, manifest: dict, year: int) -> pl.DataFrame:
    (path,) = [f["path"] for f in manifest["files"] if f["path"].endswith(f"_{year}.parquet")]
    return pl.read_parquet(store.read_bytes(path))


def built(tmp_path: Path, **stage_kwargs):
    store = MemoryStore()
    manifests = stage(store, tmp_path, **stage_kwargs)
    manifest = run(store, manifests, tmp_path)
    return store, manifest


def note_for(manifest: dict, year: int) -> str:
    (note,) = [n for n in manifest["notes"].split("; ") if n.startswith(f"{year}:")]
    return note


def set_hidalgo(df: pl.DataFrame, year: str, tse_code: str, place: str, **values) -> pl.DataFrame:
    hit = (
        (pl.col("ano") == year)
        & (pl.col("cd_localidade_tse") == tse_code)
        & (pl.col("nr_locvot") == place)
    )
    return df.with_columns(
        pl.when(hit).then(pl.lit(v)).otherwise(pl.col(k)).alias(k) for k, v in values.items()
    )


# --- Done when 1: TSE coordinates first, Hidalgo's where the TSE has none


def test_tse_coordinates_are_used_and_minus_one_takes_hidalgo(tmp_path):
    def blank_1058(fields):
        if fields[F_PLACE] == b"1058":
            fields[F_LAT], fields[F_LONG] = b'"-1"', b'"-1"'
        return [fields]

    seen = {"n": 0}

    def blank_two_of_1023(fields):
        # Two of this place's seven sections have no coordinate; the others do.
        if fields[F_PLACE] == b"1023" and seen["n"] < 2:
            seen["n"] += 1
            fields[F_LAT], fields[F_LONG] = b'"-1"', b'"-1"'
        return [fields]

    tse = edit_rows(edit_rows(tse_bytes(), blank_1058), blank_two_of_1023)
    hidalgo = set_hidalgo(
        hidalgo_frame(), "2024", "5533", "1058", lat="-1.5", long="-49.5", conf_dist_km="7.5"
    )
    store, manifest = built(tmp_path, tse=tse, hidalgo=hidalgo)
    out = read_year(store, manifest, 2024)

    gap = out.filter(pl.col("nr_local_votacao") == 1058)
    assert gap["coord_source"].to_list() == ["hidalgo"]
    assert gap["lat"].to_list() == [-1.5]
    assert gap["long"].to_list() == [-49.5]
    assert gap["conf_dist_km"].to_list() == [7.5]

    rest = out.filter(pl.col("nr_local_votacao") != 1058)
    assert rest["coord_source"].unique().to_list() == ["tse"]
    assert rest["conf_dist_km"].unique().to_list() == [0.0]
    partly = rest.filter(pl.col("nr_local_votacao") == 1023)
    assert partly["lat"].to_list() == [-1.7196846]
    assert partly["long"].to_list() == [-49.5304953]
    assert out.height == 18
    assert out["lat"].null_count() == 0


# --- Done when 2: 2008 from Hidalgo only


def test_2008_comes_from_hidalgo_and_never_reads_tse(tmp_path):
    hidalgo = pl.concat(
        [
            hidalgo_frame(),
            # A 2008 station in a municipality outside the Legal Amazon.
            hidalgo_frame()
            .filter(pl.col("cd_localidade_tse") == "34118")
            .with_columns(pl.lit("2008").alias("ano"), pl.lit("999999").alias("local_id")),
        ]
    )
    store = MemoryStore()
    manifests = stage(store, tmp_path, hidalgo=hidalgo, with_tse=False)
    manifest = run(store, manifests, tmp_path, years=(2008,))
    out = read_year(store, manifest, 2008)

    expected = hidalgo_frame().filter(
        (pl.col("ano") == "2008") & pl.col("cd_localidade_tse").is_in(["5533", "4367"])
    )
    assert out.height == expected.height > 0
    assert out["coord_source"].unique().to_list() == ["hidalgo"]
    assert out["ano"].unique().to_list() == [2008]
    assert set(out["cd_ibge"]) == {"1507706", "1507979"}
    assert not manifest["files"][0]["path"].endswith("_2024.parquet")


# --- Done when 3: two TSE pairs


def test_place_with_two_pairs_takes_the_most_frequent_and_is_counted(tmp_path):
    added = {"n": 0}

    def add_minority_row(fields):
        rows = [fields]
        if fields[F_PLACE] == b"1155" and not added["n"]:
            # Two sections with one pair, plus one with another. Not -1.0: that is
            # the TSE's "no coordinate" code.
            added["n"] += 1
            other = list(fields)
            other[F_LAT], other[F_LONG] = b'"-1.2"', b'"-49.0"'
            rows.append(other)
        return rows

    seen = {"n": 0}

    def split_tie_1147(fields):
        # Two sections, one pair each: a tie, so the smallest pair wins.
        if fields[F_PLACE] == b"1147":
            seen["n"] += 1
            if seen["n"] == 1:
                fields[F_LAT], fields[F_LONG] = b'"-1.8"', b'"-49.5"'
        return [fields]

    tse = edit_rows(edit_rows(tse_bytes(), add_minority_row), split_tie_1147)
    store, manifest = built(tmp_path, tse=tse)
    out = read_year(store, manifest, 2024)

    majority = out.filter(pl.col("nr_local_votacao") == 1155)
    assert majority["lat"].to_list() == [-1.62645722]
    assert majority["long"].to_list() == [-49.53701489]
    tie = out.filter(pl.col("nr_local_votacao") == 1147)
    assert tie["lat"].to_list() == [-1.8]
    assert "two_pair_places=2" in note_for(manifest, 2024)
    assert "two_pair_places=0" in note_for(manifest, 2008)


def test_collapse_places_counts_only_places_with_several_pairs():
    base = {
        "cd_municipio": ["00001"] * 4 + ["00002"],
        "nr_zona": [1] * 5,
        "nr_local_votacao": [1, 1, 1, 1, 2],
        "nm_local_votacao": ["B", "A", None, "A", "C"],
        "ds_endereco": [None] * 5,
        "nm_bairro": [None] * 5,
        "lat": [1.0, 2.0, 2.0, None, 3.0],
        "long": [1.0, 2.0, 2.0, None, 3.0],
    }
    places, several = collapse_places(pl.DataFrame(base))
    assert several == 1
    one = places.filter(pl.col("cd_municipio") == "00001")
    assert one["lat"].to_list() == [2.0]
    assert one["nm_local_votacao"].to_list() == ["A"]


# --- Done when 4: no phone numbers


def test_no_phone_column_or_value_in_the_output(tmp_path):
    store, manifest = built(tmp_path)
    phones = set()
    for line in tse_bytes().split(b"\r\n")[1:]:
        if line:
            phones.add(line.split(b";")[F_PHONE].decode("latin-1").strip('"'))
    phones.discard("-1")
    assert "00000101" in phones

    for year in YEARS:
        out = read_year(store, manifest, year)
        assert not [c for c in out.columns if re.search("telefone|phone|fone", c, re.I)]
        cells = {str(x) for c in out.columns for x in out[c].to_list()}
        assert not (cells & phones)
    assert not [c for c in pp.TSE_COLUMNS if "telefone" in c]


# --- Done when 4a: panel_id


def test_panel_id_where_the_station_has_one(tmp_path):
    panel = panel_frame().filter(pl.col("local_id") != "859830")  # place 1023 loses its panel row
    store, manifest = built(tmp_path, panel=panel)
    out = read_year(store, manifest, 2024)

    stations = (
        hidalgo_frame()
        .filter(pl.col("ano") == "2024")
        .join(panel, on="local_id", how="left")
        .select(
            pl.col("cd_localidade_tse").str.zfill(5).alias("sg_ue"),
            pl.col("nr_locvot").cast(pl.Int32).alias("nr_local_votacao"),
            pl.col("panel_id").alias("expected"),
        )
    )
    joined = out.join(stations, on=["sg_ue", "nr_local_votacao"], how="left")
    assert joined["panel_id"].to_list() == joined["expected"].to_list()
    assert joined["panel_id"].null_count() > 0
    assert joined["panel_id"].count() > 0
    assert out.filter(pl.col("nr_local_votacao") == 1023)["panel_id"].null_count() == 1

    for year in YEARS:
        part = read_year(store, manifest, year)
        share = part["panel_id"].count() / part.height
        assert f"panel_id_share={share:.4f}" in note_for(manifest, year)


# --- Done when 5: checks


def table(**overrides) -> pl.DataFrame:
    data = {
        "ano": [2024, 2024],
        "cd_ibge": ["1507706", "1507706"],
        "sg_ue": ["05533", "05533"],
        "nr_zona": [48, 48],
        "nr_local_votacao": [1023, 1031],
    }
    data.update(overrides)
    return pl.DataFrame(data)


def test_key_check_raises_on_a_repeated_key():
    check_key(table())
    with pytest.raises(BuildError, match="repeat"):
        check_key(table(nr_local_votacao=[1023, 1023]))


def test_legal_amazon_check_raises_outside_the_legal_amazon():
    check_legal_amazon(table(), {"1507706"})
    with pytest.raises(BuildError, match="Legal Amazon"):
        check_legal_amazon(table(cd_ibge=["1507706", "2905602"]), {"1507706"})
    with pytest.raises(BuildError, match="Legal Amazon"):
        check_legal_amazon(table(cd_ibge=["1507706", None]), {"1507706"})


def test_coverage_check_raises_at_five_percent():
    check_coverage(2024, 100, 4, 0.05)
    with pytest.raises(BuildError, match="no coordinate"):
        check_coverage(2024, 100, 5, 0.05)
    with pytest.raises(BuildError, match="no polling places"):
        check_coverage(2024, 0, 0, 0.05)


def test_build_raises_when_a_place_has_no_coordinate_anywhere(tmp_path):
    def add_uncovered_place(fields):
        rows = [fields]
        if fields[F_PLACE] == b"1155":
            other = list(fields)
            other[F_PLACE] = b"9999"  # not a Hidalgo station
            other[F_LAT], other[F_LONG] = b'"-1"', b'"-1"'
            rows.append(other)
        return rows

    store = MemoryStore()
    manifests = stage(store, tmp_path, tse=edit_rows(tse_bytes(), add_uncovered_place))
    with pytest.raises(BuildError, match="2024: 1 of 19"):
        run(store, manifests, tmp_path)
    assert run(store, manifests, tmp_path, max_missing_share=0.5)["status"] == "created"


def test_hidalgo_repeated_station_raises(tmp_path):
    geocoded = tmp_path / "g.csv.gz"
    panel = tmp_path / "p.csv.gz"
    frame = hidalgo_frame()
    duplicate = frame.head(1).with_columns(pl.lit("999999").alias("local_id"))
    geocoded.write_bytes(make_gz(csv_bytes(pl.concat([frame, duplicate]))))
    panel.write_bytes(make_gz(csv_bytes(panel_frame())))
    with pytest.raises(BuildError, match="repeats"):
        read_hidalgo(geocoded, panel)

    geocoded.write_bytes(make_gz(csv_bytes(pl.concat([frame, frame.head(1)]))))
    with pytest.raises(BuildError, match="local_id repeats"):
        read_hidalgo(geocoded, panel)

    geocoded.write_bytes(make_gz(csv_bytes(frame)))
    panel.write_bytes(make_gz(csv_bytes(pl.concat([panel_frame(), panel_frame().head(1)]))))
    with pytest.raises(BuildError, match="panel_ids"):
        read_hidalgo(geocoded, panel)


# --- Done when 6: output path, determinism, no network


def test_changing_the_module_source_changes_the_output_prefix(tmp_path, monkeypatch):
    store = MemoryStore()
    manifests = stage(store, tmp_path)
    first = run(store, manifests, tmp_path)

    files = [f for m in manifests for f in m["files"]]
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files, YEARS, code=["b"])
    assert input_hash(files, YEARS, code=["a"]) != input_hash(files[:-1], YEARS, code=["a"])
    assert input_hash(files, YEARS, code=["a"]) == input_hash(files[::-1], YEARS, code=["a"])

    changed = tmp_path / "polling_places_changed.py"
    changed.write_text(
        Path(pp.__file__).read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8"
    )
    monkeypatch.setattr(pp, "CODE_MODULES", (changed,))
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


def test_manifest_is_valid_and_lists_one_file_per_year(tmp_path):
    store, manifest = built(tmp_path)
    assert validate_manifest(manifest, stage="build", dataset="polling_places") == []
    assert manifest["gcs_prefix"].startswith(DERIVED)
    assert [f["path"].rsplit("/", 1)[-1] for f in manifest["files"]] == [
        "polling_places_2008.parquet",
        "polling_places_2024.parquet",
    ]
    out = read_year(store, manifest, 2024)
    assert out.columns == pp.OUTPUT_COLUMNS
    assert not out.select(pp.KEY).is_duplicated().any()


def test_inputs_are_deterministic(tmp_path):
    assert make_zip(2024, tse_bytes()) == make_zip(2024, tse_bytes())
    blob = make_gz(csv_bytes(hidalgo_frame()))
    assert blob == make_gz(csv_bytes(hidalgo_frame()))
    assert blob[4:8] == b"\x00\x00\x00\x00"  # gzip mtime field
    with zipfile.ZipFile(io.BytesIO(make_zip(2024, b"x"))) as zf:
        assert {i.date_time for i in zf.infolist()} == {FIXED_TIME}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = built(tmp_path / "a")[1]
    second = built(tmp_path / "b")[1]
    assert first["gcs_prefix"] == second["gcs_prefix"]


def test_the_contract_exists_and_names_the_checks():
    text = CONTRACT.read_text(encoding="utf-8")
    for word in ("coord_source", "conf_dist_km", "panel_id", "max_missing_share"):
        assert word in text


# --- Present coordinates that are not numbers: counted, and the build stops above a share


def test_unparsed_coordinates_are_counted_and_stop_the_build_above_the_share(tmp_path):
    def comma_1058(fields):
        if fields[F_PLACE] == b"1058":
            fields[F_LAT] = b'"-1,5"'  # a decimal comma: present, not a number
        return [fields]

    hidalgo = set_hidalgo(
        hidalgo_frame(), "2024", "5533", "1058", lat="-1.5", long="-49.5", conf_dist_km="7.5"
    )
    tse = edit_rows(tse_bytes(), comma_1058)

    # Within a permissive share: the place falls back to Hidalgo and the count is noted.
    store = MemoryStore()
    manifests = stage(store, tmp_path, tse=tse, hidalgo=hidalgo)
    manifest = run(store, manifests, tmp_path, max_unparsed_share=1.0)
    note = note_for(manifest, 2024)
    unparsed = int(re.search(r"tse_unparsed=(\d+)", note).group(1))
    assert unparsed > 0
    out = read_year(store, manifest, 2024)
    assert out.filter(pl.col("nr_local_votacao") == 1058)["coord_source"].to_list() == ["hidalgo"]

    # At the default share the same input stops the build, naming the problem.
    store = MemoryStore()
    manifests = stage(store, tmp_path, tse=tse, hidalgo=hidalgo)
    with pytest.raises(BuildError, match="not numbers"):
        run(store, manifests, tmp_path)


def test_equator_coordinates_without_a_leading_zero_parse():
    df = pl.DataFrame({"x": [".00756662", "-.0065359", "-1", "", "abc"]})
    parsed = df.select(pp._coordinate("x").alias("value"), pp._unparsed("x").alias("bad"))
    assert parsed["value"].to_list()[:3] == [0.00756662, -0.0065359, None]
    assert parsed["bad"].to_list() == [False, False, False, False, True]


def test_rows_of_another_election_year_are_dropped_and_counted(tmp_path):
    first = {"done": False}

    def later_election(fields):
        rows = [fields]
        if not first["done"]:
            first["done"] = True
            extra = list(fields)
            extra[F_PLACE] = b"9999"
            extra[2] = b"2026"  # AA_ELEICAO
            rows.append(extra)
        return rows

    store, manifest = built(tmp_path, tse=edit_rows(tse_bytes(), later_election))
    assert "tse_other_election_year_rows=1" in note_for(manifest, 2024)
    out = read_year(store, manifest, 2024)
    assert 9999 not in out["nr_local_votacao"].to_list()
