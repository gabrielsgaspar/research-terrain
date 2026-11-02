import csv
import hashlib
import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import tse_candidates
from terrain.builds.tse_parties import (
    COALITION_KEY,
    CODE_MODULES,
    VOTES_KEY,
    BuildError,
    add_cd_ibge,
    build,
    check,
    inputs_from_manifest,
    municipality_input,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest
from terrain.storage import MemoryStore

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "tse"
DERIVED = dataset("tse_parties")["derived"]
RAW = "data/raw/tse/results/2026-11-02/"
MUNI_PREFIX = "data/derived/municipalities/abc/"
YEARS = [2000, 2024]
KINDS = {"votes": "votacao_partido_munzona", "coalitions": "consulta_coligacao"}
SG_UE = {2000: "05436", 2024: "05533"}

# A fixed timestamp: zip entries otherwise carry the current time, so the same
# fixture would give a different SHA-256 (and output path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}_sample.csv").read_bytes()


def records(data: bytes) -> int:
    text = data.decode("latin-1")
    return sum(1 for _ in csv.reader(io.StringIO(text, newline=""), delimiter=";")) - 1


def make_zip(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo(f"{name}_BRASIL.csv", date_time=FIXED_TIME), data)
        zf.writestr(zipfile.ZipInfo(f"{name}_PA.csv", date_time=FIXED_TIME), data)
        zf.writestr(zipfile.ZipInfo("leiame.pdf", date_time=FIXED_TIME), b"%PDF-")
    return buf.getvalue()


def munis_blob(pairs: list[tuple[str, str]] | None = None) -> bytes:
    pairs = pairs if pairs is not None else [("05436", "1507409"), ("05533", "1507961")]
    df = pl.DataFrame(
        {
            "cd_ibge": [i for _, i in pairs] + ["1100015"],
            "cd_tse": [t for t, _ in pairs] + [None],
        },
        schema={"cd_ibge": pl.String, "cd_tse": pl.String},
    )
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def stage(
    store: MemoryStore,
    *,
    overrides: dict[str, bytes] | None = None,
    munis: bytes | None = None,
    extra_files: tuple[str, ...] = (),
) -> tuple[dict, dict]:
    """Put zips made from the fixtures and a municipalities table in `store`."""
    overrides = overrides or {}
    files = []
    names = [f"{base}_{y}" for base in KINDS.values() for y in YEARS] + list(extra_files)
    for name in names:
        blob = make_zip(name, overrides.get(name, fixture(name)))
        path = f"{RAW}{name}.zip"
        store.create(path, blob)
        files.append({"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)})
    acquire = {"dataset": "tse_results", "gcs_prefix": RAW, "files": files}
    blob = munis if munis is not None else munis_blob()
    path = MUNI_PREFIX + "municipalities.parquet"
    store.create(path, blob)
    muni = {
        "dataset": "municipalities",
        "gcs_prefix": MUNI_PREFIX,
        "files": [
            {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)},
            {"path": MUNI_PREFIX + "legal_amazon.csv", "sha256": "0" * 64, "bytes": 1},
        ],
    }
    return acquire, muni


def run(store: MemoryStore, acquire: dict, muni: dict, tmp_path: Path, **kw) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(store, acquire, muni, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kw)


def read(store: MemoryStore, manifest: dict, name: str) -> pl.DataFrame:
    path = manifest["gcs_prefix"] + name
    return pl.read_parquet(store.read_bytes(path))


def with_row_copied(data: bytes, *, index: int, field: int | None, value: bytes | None) -> bytes:
    """Append a copy of data row `index` (0 = first), with one field replaced."""
    lines = [ln for ln in data.split(b"\r\n") if ln]
    row = lines[1 + index]
    if field is not None:
        parts = row.split(b";")
        parts[field] = value
        row = b";".join(parts)
    return b"\r\n".join(lines + [row]) + b"\r\n"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    store = MemoryStore()
    acquire, muni = stage(store)
    out = run(store, acquire, muni, tmp_path_factory.mktemp("build"))
    return store, out


# --- Done when 1: every row has a cd_ibge, row counts equal the fixtures


@pytest.mark.parametrize("kind", ["votes", "coalitions"])
@pytest.mark.parametrize("year", YEARS)
def test_rows_equal_fixture_rows_and_all_have_cd_ibge(built, kind, year):
    store, out = built
    prefix = "party_votes" if kind == "votes" else "coalitions"
    df = read(store, out, f"{prefix}_{year}.parquet")
    assert df.height == records(fixture(f"{KINDS[kind]}_{year}"))
    assert df.height > 0
    assert df["cd_ibge"].null_count() == 0
    assert df["sg_ue"].unique().to_list() == [SG_UE[year]]
    assert df["cd_ibge"].unique().to_list() == [{2000: "1507409", 2024: "1507961"}[year]]
    cols = df.columns
    assert cols[cols.index("sg_ue") + 1] == "cd_ibge"


def test_manifest_lists_every_file_and_is_valid(built):
    _, out = built
    names = sorted(f["path"].rsplit("/", 1)[-1] for f in out["files"])
    assert names == [
        "coalitions_2000.parquet",
        "coalitions_2024.parquet",
        "party_votes_2000.parquet",
        "party_votes_2024.parquet",
    ]
    assert validate_manifest(out, stage="build", dataset="tse_parties") == []
    assert out["inputs"] == [RAW + MANIFEST_NAME, MUNI_PREFIX + MANIFEST_NAME]
    assert "party_votes rows per year: 2000=" in out["notes"]


def test_keys_and_types(built):
    store, out = built
    v = read(store, out, "party_votes_2024.parquet")
    assert v["nr_zona"].dtype == pl.String
    assert v["qt_votos_nominais_validos"].dtype == pl.Int64
    assert v["ano_eleicao"].dtype == pl.Int32
    # Key columns are never nulled: -1 stays text.
    assert v["sq_coligacao"].null_count() == 0
    c = read(store, out, "coalitions_2000.parquet")
    assert c["sq_coligacao"].null_count() == 0
    assert "-1" in c["sq_coligacao"].to_list()


def test_vote_columns_differ_by_year_and_are_null_where_absent(built):
    store, out = built
    v2000 = read(store, out, "party_votes_2000.parquet")
    v2024 = read(store, out, "party_votes_2024.parquet")
    assert v2000.columns == v2024.columns  # each kind aligns across years
    assert v2000["qt_votos_nominais"].null_count() == 0
    assert v2024["qt_votos_nominais"].null_count() == v2024.height


# --- Done when 3: federation columns


def test_2024_coalitions_carry_federation_columns_and_2000_has_them_null(built):
    store, out = built
    c2024 = read(store, out, "coalitions_2024.parquet")
    c2000 = read(store, out, "coalitions_2000.parquet")
    for col in ("nr_federacao", "sg_federacao", "ds_composicao_federacao"):
        assert col in c2000.columns
        assert c2000[col].null_count() == c2000.height
        assert c2024[col].null_count() < c2024.height
    psol = c2024.filter(pl.col("sg_partido") == "PSOL")
    assert psol["nr_federacao"].drop_nulls().to_list()


def test_coalition_membership_uses_each_rows_own_party(built):
    store, out = built
    c = read(store, out, "coalitions_2024.parquet")
    # One row per party and coalition record; no row is created from the text.
    assert c.height == records(fixture("consulta_coligacao_2024"))
    assert not c.select(COALITION_KEY).is_duplicated().any()


# --- Done when 2: a party under two coalition records, a true duplicate


def test_a_party_under_two_coalition_records_keeps_both_rows(tmp_path):
    data = fixture("votacao_partido_munzona_2000")
    changed = with_row_copied(data, index=0, field=22, value=b"99")
    store = MemoryStore()
    acquire, muni = stage(store, overrides={"votacao_partido_munzona_2000": changed})
    out = run(store, acquire, muni, tmp_path)
    df = read(store, out, "party_votes_2000.parquet")
    assert df.height == records(data) + 1
    first = df.filter((pl.col("nr_partido") == "45") & (pl.col("nr_zona") == "50"))
    assert first.height >= 2
    assert not df.select(VOTES_KEY).is_duplicated().any()


def test_an_exact_duplicate_row_raises(tmp_path):
    data = fixture("votacao_partido_munzona_2000")
    dup = with_row_copied(data, index=0, field=None, value=None)
    store = MemoryStore()
    acquire, muni = stage(store, overrides={"votacao_partido_munzona_2000": dup})
    with pytest.raises(BuildError, match="repeat the key"):
        run(store, acquire, muni, tmp_path)


def test_a_duplicate_coalition_row_raises(tmp_path):
    data = fixture("consulta_coligacao_2024")
    dup = with_row_copied(data, index=0, field=None, value=None)
    store = MemoryStore()
    acquire, muni = stage(store, overrides={"consulta_coligacao_2024": dup})
    with pytest.raises(BuildError, match="repeat the key"):
        run(store, acquire, muni, tmp_path)


# --- Done when 4: each check raises


def frame(n: int = 3, with_ibge: bool = True) -> pl.DataFrame:
    return pl.DataFrame(
        {
            **{k: [str(i) for i in range(n)] for k in COALITION_KEY},
            "cd_ibge": ["1507409"] * n if with_ibge else [None] * n,
        }
    )


def test_row_count_check_raises():
    with pytest.raises(BuildError, match="3 rows built, 4 in the source"):
        check(frame(3), 4, COALITION_KEY, "coalitions 2000")


def test_key_check_raises():
    df = pl.concat([frame(2), frame(2)])
    with pytest.raises(BuildError, match="repeat the key"):
        check(df, 4, COALITION_KEY, "coalitions 2000")


def test_cd_ibge_check_raises():
    with pytest.raises(BuildError, match="3 rows have no cd_ibge"):
        check(frame(3, with_ibge=False), 3, COALITION_KEY, "coalitions 2000")


def test_check_passes_on_good_input():
    check(frame(3), 3, COALITION_KEY, "coalitions 2000")


def test_a_town_missing_from_the_municipalities_table_stops_the_build(tmp_path):
    store = MemoryStore()
    acquire, muni = stage(store, munis=munis_blob([("05436", "1507409")]))
    with pytest.raises(BuildError, match="no cd_ibge"):
        run(store, acquire, muni, tmp_path)


def test_add_cd_ibge_keeps_every_row_and_rejects_a_repeated_tse_code():
    df = pl.DataFrame({"sg_ue": ["1", "2", "9"], "x": ["a", "b", "c"]})
    munis = pl.DataFrame({"cd_ibge": ["11", "22"], "cd_tse": ["1", "2"]})
    out = add_cd_ibge(df, munis)
    assert out.columns == ["sg_ue", "cd_ibge", "x"]
    assert out["cd_ibge"].to_list() == ["11", "22", None]
    bad = pl.DataFrame({"cd_ibge": ["11", "22"], "cd_tse": ["1", "1"]})
    with pytest.raises(BuildError, match="repeats a cd_tse"):
        add_cd_ibge(df, bad)


# --- Inputs


def test_only_party_and_coalition_zips_are_used(tmp_path):
    store = MemoryStore()
    acquire, _ = stage(store)
    acquire["files"].append(
        {"path": RAW + "votacao_candidato_munzona_2000.zip", "sha256": "1" * 64, "bytes": 1}
    )
    found = inputs_from_manifest(acquire)
    assert len(found) == 4
    assert {i.kind for i in found} == {"votes", "coalitions"}


def test_a_year_with_only_one_kind_is_refused():
    manifest = {"files": [{"path": RAW + "votacao_partido_munzona_2000.zip", "sha256": "1" * 64}]}
    with pytest.raises(BuildError, match="need both"):
        inputs_from_manifest(manifest)


def test_no_matching_zips_is_refused():
    with pytest.raises(BuildError, match="lists no party-vote"):
        inputs_from_manifest({"files": []})


def test_municipality_input_needs_exactly_one_parquet():
    with pytest.raises(BuildError):
        municipality_input({"files": [{"path": MUNI_PREFIX + "legal_amazon.csv"}]})


def test_a_zip_that_differs_from_its_manifest_sha_is_refused(tmp_path):
    store = MemoryStore()
    acquire, muni = stage(store)
    acquire["files"][0]["sha256"] = "f" * 64
    with pytest.raises(BuildError, match="does not match the sha256"):
        run(store, acquire, muni, tmp_path)


# --- Done when 5: the path hashes inputs and code


def test_changing_any_input_sha_changes_the_output_path(built, tmp_path):
    from terrain.builds.tse_parties import input_hash

    shas = ["1" * 64, "2" * 64, "3" * 64]
    base = input_hash(shas)
    assert input_hash([*shas[:-1], "4" * 64]) != base
    assert input_hash(shas[::-1]) == base  # sorted, so order does not matter
    # A different municipalities table, with the same zips, gives a new path.
    _, out = built
    store = MemoryStore()
    acquire, muni = stage(store, munis=munis_blob([("05436", "1507409"), ("05533", "1507962")]))
    other = run(store, acquire, muni, tmp_path)
    assert other["gcs_prefix"] != out["gcs_prefix"]


def test_changing_the_source_of_tse_candidates_changes_the_path(tmp_path):
    from terrain.builds.tse_parties import input_hash

    other = tmp_path / "tse_candidates_changed.py"
    other.write_text(Path(tse_candidates.__file__).read_text(encoding="utf-8") + "\n# fix\n")
    this = CODE_MODULES[0]
    shas = ["1" * 64, "2" * 64]
    assert input_hash(shas, CODE_MODULES) == input_hash(shas, [this, CODE_MODULES[1]])
    assert input_hash(shas, CODE_MODULES) != input_hash(shas, [this, other])
    assert input_hash(shas, CODE_MODULES) == input_hash(shas[::-1], CODE_MODULES)


def test_code_modules_include_tse_candidates():
    assert Path(tse_candidates.__file__) in CODE_MODULES


def test_injected_code_list_changes_the_built_path(tmp_path):
    store = MemoryStore()
    acquire, muni = stage(store)
    a = run(store, acquire, muni, tmp_path)
    other = tmp_path / "other.py"
    other.write_text("# changed\n")
    b = run(store, acquire, muni, tmp_path, code_modules=[CODE_MODULES[0], other])
    assert a["gcs_prefix"] != b["gcs_prefix"]
    assert b["status"] == "created"


def test_second_build_is_unchanged_and_writes_nothing(tmp_path):
    from terrain.manifest import write_manifest

    store = MemoryStore()
    acquire, muni = stage(store)
    first = run(store, acquire, muni, tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = sorted(store.list(""))
    second = run(store, acquire, muni, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert sorted(store.list("")) == before


def test_same_inputs_give_the_same_path(built, tmp_path):
    _, out = built
    store = MemoryStore()
    acquire, muni = stage(store)
    again = run(store, acquire, muni, tmp_path)
    assert again["gcs_prefix"] == out["gcs_prefix"]


def test_changing_a_fixture_changes_the_path(built, tmp_path):
    _, out = built
    data = fixture("consulta_coligacao_2000")
    store = MemoryStore()
    acquire, muni = stage(
        store, overrides={"consulta_coligacao_2000": data.replace(b"Deferido", b"DEFERIDO")}
    )
    other = run(store, acquire, muni, tmp_path)
    assert other["gcs_prefix"] != out["gcs_prefix"]
