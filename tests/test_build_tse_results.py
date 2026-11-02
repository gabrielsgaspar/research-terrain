import csv
import hashlib
import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import tse_candidates
from terrain.builds.tse_candidates import harmonise
from terrain.builds.tse_results import (
    CODE_MODULES,
    TURNOUT_KEY,
    VOTES_KEY,
    BuildError,
    add_matched,
    build,
    check,
    check_matched,
    consistency,
    input_hash,
    inputs_from_manifest,
    manifest_file,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "tse"
DERIVED = dataset("tse_results")["derived"]
RAW = "data/raw/tse/results/2026-11-02/"
CAND_PREFIX = "data/derived/tse_candidates/abc/"
MUNI_PREFIX = "data/derived/municipalities/abc/"
YEARS = [2000, 2024]
VOTES_NAME = "votacao_candidato_munzona"
TURNOUT_NAME = "detalhe_votacao_munzona"
SG_UE = {2000: "05436", 2024: "05533"}
IBGE = {"05436": "1507409", "05533": "1507961"}
# The fixtures hold 2 candidacies per year that are not in the candidate fixture.
LOOSE = 0.5

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


def to_parquet(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def candidates_blob(extra: list[dict] | None = None) -> bytes:
    """A candidates table (key columns only) cut from the candidate fixtures."""
    frames = []
    for y in YEARS:
        text = fixture(f"consulta_cand_{y}").decode("latin-1").encode("utf-8")
        df = harmonise(pl.read_csv(io.BytesIO(text), separator=";", infer_schema=False))
        frames.append(df.select(tse_candidates.KEY))
    out = pl.concat(frames)
    if extra:
        out = pl.concat([out, pl.DataFrame(extra, schema=out.schema)])
    return to_parquet(out)


def munis_blob(pairs: dict[str, str] | None = None) -> bytes:
    pairs = pairs if pairs is not None else IBGE
    df = pl.DataFrame(
        {
            "cd_ibge": [*pairs.values(), "1100015"],
            "cd_tse": [*pairs.keys(), None],
        },
        schema={"cd_ibge": pl.String, "cd_tse": pl.String},
    )
    return to_parquet(df)


def entry(store: MemoryStore, path: str, blob: bytes) -> dict:
    store.create(path, blob)
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def stage(
    store: MemoryStore,
    *,
    overrides: dict[str, bytes] | None = None,
    munis: bytes | None = None,
    candidates: bytes | None = None,
    extra_files: tuple[str, ...] = ("votacao_partido_munzona_2000", "consulta_coligacao_2000"),
) -> tuple[dict, dict, dict]:
    """Put zips made from the fixtures and the two parquet inputs in `store`."""
    overrides = overrides or {}
    names = [f"{base}_{y}" for base in (VOTES_NAME, TURNOUT_NAME) for y in YEARS]
    files = []
    for name in names:
        files.append(
            entry(store, f"{RAW}{name}.zip", make_zip(name, overrides[name]))
            if name in overrides
            else entry(store, f"{RAW}{name}.zip", make_zip(name, fixture(name)))
        )
    for name in extra_files:  # zips this build must ignore
        files.append(entry(store, f"{RAW}{name}.zip", make_zip(name, fixture(name))))
    acquire = {"dataset": "tse_results", "gcs_prefix": RAW, "files": files}
    cand = {
        "dataset": "tse_candidates",
        "gcs_prefix": CAND_PREFIX,
        "files": [
            entry(
                store,
                CAND_PREFIX + "candidates.parquet",
                candidates if candidates is not None else candidates_blob(),
            )
        ],
    }
    muni = {
        "dataset": "municipalities",
        "gcs_prefix": MUNI_PREFIX,
        "files": [
            entry(
                store,
                MUNI_PREFIX + "municipalities.parquet",
                munis if munis is not None else munis_blob(),
            ),
            {"path": MUNI_PREFIX + "legal_amazon.csv", "sha256": "0" * 64, "bytes": 1},
        ],
    }
    return acquire, cand, muni


def run(store: MemoryStore, manifests: tuple, tmp_path: Path, **kw) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kw.setdefault("max_unmatched_share", LOOSE)
    return build(store, *manifests, derived_root=DERIVED, tmp_dir=work, code_commit="abc", **kw)


def read(store: MemoryStore, manifest: dict, name: str) -> pl.DataFrame:
    return pl.read_parquet(store.read_bytes(manifest["gcs_prefix"] + name))


def with_rows_added(data: bytes, rows: list[tuple[int, dict[int, bytes]]]) -> bytes:
    """Append copies of data rows `(index, {field: value})`, 0 = first data row."""
    lines = [ln for ln in data.split(b"\r\n") if ln]
    added = []
    for index, fields in rows:
        parts = lines[1 + index].split(b";")
        for field, value in fields.items():
            parts[field] = value
        added.append(b";".join(parts))
    return b"\r\n".join(lines + added) + b"\r\n"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    store = MemoryStore()
    manifests = stage(store)
    out = run(store, manifests, tmp_path_factory.mktemp("build"))
    return store, out


# --- Done when 1: fixtures


@pytest.mark.parametrize("year", YEARS)
def test_fixture_rows_match_a_candidacy_except_two(built, year):
    store, out = built
    df = read(store, out, f"candidate_votes_{year}.parquet")
    assert df.height == records(fixture(f"{VOTES_NAME}_{year}")) == 27
    assert df["matched"].sum() == 25
    assert (~df["matched"]).sum() == 2
    assert df["cd_ibge"].unique().to_list() == [IBGE[SG_UE[year]]]
    cols = df.columns
    assert cols[cols.index("sg_ue") + 1] == "cd_ibge"
    assert f"{year}=2" in out["notes"].split("unmatched candidacies per year: ")[1]


@pytest.mark.parametrize("year", YEARS)
def test_turnout_rows_equal_fixture_rows_and_have_cd_ibge(built, year):
    store, out = built
    df = read(store, out, f"turnout_{year}.parquet")
    assert df.height == records(fixture(f"{TURNOUT_NAME}_{year}")) > 0
    assert df["cd_ibge"].null_count() == 0
    assert "matched" not in df.columns
    assert df["qt_aptos"].dtype == pl.Int64


def test_manifest_lists_every_file_and_is_valid(built):
    _, out = built
    names = sorted(f["path"].rsplit("/", 1)[-1] for f in out["files"])
    assert names == [
        "candidate_votes_2000.parquet",
        "candidate_votes_2024.parquet",
        "turnout_2000.parquet",
        "turnout_2024.parquet",
    ]
    assert validate_manifest(out, stage="build", dataset="tse_results") == []
    assert out["inputs"] == [
        RAW + MANIFEST_NAME,
        CAND_PREFIX + MANIFEST_NAME,
        MUNI_PREFIX + MANIFEST_NAME,
    ]
    assert "candidate_votes rows per year: 2000=27, 2024=27" in out["notes"]
    assert "votes agree with turnout" in out["notes"]


def test_columns_align_across_years_and_valid_votes_are_null_where_absent(built):
    store, out = built
    a = read(store, out, "candidate_votes_2000.parquet")
    b = read(store, out, "candidate_votes_2024.parquet")
    assert a.columns == b.columns
    assert a["qt_votos_nominais_validos"].dtype == pl.Int64
    assert a["ano_eleicao"].dtype == pl.Int32
    assert a["nr_zona"].dtype == pl.String
    assert a["sq_candidato"].dtype == pl.String


# --- Done when 2: same sq_candidato, different municipalities


def test_same_sq_candidato_in_two_municipalities_stays_distinct(tmp_path):
    data = fixture(f"{VOTES_NAME}_2000")
    changed = with_rows_added(data, [(0, {11: b'"99999"'})])
    store = MemoryStore()
    manifests = stage(
        store,
        overrides={f"{VOTES_NAME}_2000": changed},
        munis=munis_blob({**IBGE, "99999": "1500000"}),
    )
    out = run(store, manifests, tmp_path)
    df = read(store, out, "candidate_votes_2000.parquet")
    assert df.height == records(data) + 1
    first = df["sq_candidato"][0]
    same = df.filter(pl.col("sq_candidato") == first)
    assert sorted(same["sg_ue"].to_list()) == ["05436", "99999"]
    assert sorted(same["cd_ibge"].to_list()) == ["1500000", "1507409"]
    assert not df.select(VOTES_KEY).is_duplicated().any()


def test_add_matched_uses_the_whole_key():
    cand = pl.DataFrame(
        {"ano_eleicao": [2000], "cd_eleicao": [1], "sg_ue": ["A"], "sq_candidato": ["7"]},
        schema_overrides={"ano_eleicao": pl.Int32, "cd_eleicao": pl.Int32},
    )
    df = cand.select("ano_eleicao", "cd_eleicao", "sg_ue", "sq_candidato").with_columns(
        pl.Series("x", [1])
    )
    other = df.with_columns(pl.lit("B").alias("sg_ue"))
    out = add_matched(pl.concat([df, other]), cand)
    assert out["matched"].to_list() == [True, False]


# --- Done when 3: consistency report


def votes_frame(valid: list[int | None], nominal: list[int | None] | None = None):
    n = len(valid)
    return pl.DataFrame(
        {
            "ano_eleicao": [2024] * n,
            "cd_eleicao": [619] * n,
            "sg_ue": ["A", "A", "B"][:n],
            "cd_cargo": ["13"] * n,
            "nr_turno": [1] * n,
            "qt_votos_nominais_validos": valid,
            "qt_votos_nominais": nominal if nominal is not None else [None] * n,
        },
        schema_overrides={"qt_votos_nominais_validos": pl.Int64, "qt_votos_nominais": pl.Int64},
    )


def turnout_frame(valid: list[int]):
    # Two zones for A (summed), one for B; counts as one group per municipality.
    return pl.DataFrame(
        {
            "ano_eleicao": [2024] * 3,
            "cd_eleicao": [619] * 3,
            "sg_ue": ["A", "A", "B"],
            "cd_cargo": ["13"] * 3,
            "nr_turno": [1] * 3,
            "qt_votos_nominais_validos": valid,
        }
    )


def test_consistency_counts_agreement():
    votes = votes_frame([10, 5, 7])
    assert consistency(votes, turnout_frame([12, 3, 7])) == (2, 2)


def test_consistency_counts_a_mismatch_after_one_count_changes():
    votes = votes_frame([10, 5, 8])
    assert consistency(votes, turnout_frame([12, 3, 7])) == (1, 2)


def test_consistency_uses_nominal_votes_when_valid_votes_are_absent():
    votes = votes_frame([None, None, None], [10, 5, 7])
    assert consistency(votes, turnout_frame([15, 0, 7])) == (2, 2)


def test_consistency_counts_a_group_in_one_table_only():
    votes = votes_frame([10, 5])
    assert consistency(votes, turnout_frame([15, 0, 7])) == (1, 2)


def test_consistency_disagreement_does_not_stop_the_build(tmp_path):
    data = fixture(f"{TURNOUT_NAME}_2024")
    store = MemoryStore()
    # Change the valid nominal votes of the first turnout row (field 30).
    changed = with_rows_added(data, [])
    lines = changed.split(b"\r\n")
    parts = lines[1].split(b";")
    parts[30] = b"1"
    lines[1] = b";".join(parts)
    manifests = stage(store, overrides={f"{TURNOUT_NAME}_2024": b"\r\n".join(lines)})
    out = run(store, manifests, tmp_path)
    assert out["status"] == "created"


# --- Done when 4: supplementary and extraordinary elections


def test_supplementary_and_extraordinary_rows_are_both_kept(tmp_path):
    data = fixture(f"{VOTES_NAME}_2024")
    extra = [
        (0, {3: b"1", 4: '"ELEIÇÃO SUPLEMENTAR"'.encode("latin-1"), 6: b"9001"}),
        (1, {3: b"3", 4: '"ELEIÇÃO EXTRAORDINÁRIA"'.encode("latin-1"), 6: b"9002"}),
    ]
    store = MemoryStore()
    manifests = stage(store, overrides={f"{VOTES_NAME}_2024": with_rows_added(data, extra)})
    out = run(store, manifests, tmp_path)
    df = read(store, out, "candidate_votes_2024.parquet")
    assert df.height == records(data) + 2
    assert df["cd_tipo_eleicao"].dtype == pl.Int32
    kept = df.filter(pl.col("cd_eleicao").is_in([9001, 9002])).sort("cd_eleicao")
    assert kept["cd_tipo_eleicao"].to_list() == [1, 3]
    assert (~kept["matched"]).all()


# --- Done when 5: each check raises


def frame(n: int = 3, with_ibge: bool = True) -> pl.DataFrame:
    return pl.DataFrame(
        {
            **{k: [str(i) for i in range(n)] for k in TURNOUT_KEY},
            "cd_ibge": ["1507409"] * n if with_ibge else [None] * n,
        }
    )


def test_row_count_check_raises():
    with pytest.raises(BuildError, match="3 rows built, 4 in the source"):
        check(frame(3), 4, TURNOUT_KEY, "turnout 2000")


def test_key_check_raises():
    with pytest.raises(BuildError, match="repeat the key"):
        check(pl.concat([frame(2), frame(2)]), 4, TURNOUT_KEY, "turnout 2000")


def test_cd_ibge_check_raises():
    with pytest.raises(BuildError, match="3 rows have no cd_ibge"):
        check(frame(3, with_ibge=False), 3, TURNOUT_KEY, "turnout 2000")


def test_checks_pass_on_good_input():
    check(frame(3), 3, TURNOUT_KEY, "turnout 2000")


def test_match_share_check_raises_above_the_share_and_counts_otherwise():
    df = pl.DataFrame({"matched": [True] * 999 + [False]})
    assert check_matched(df, "votes 2000", max_share=0.001) == 1  # exactly the share is allowed
    with pytest.raises(BuildError, match="2 of 1000 rows match no candidacy"):
        check_matched(
            pl.DataFrame({"matched": [True] * 998 + [False] * 2}), "votes 2000", max_share=0.001
        )
    # The default allows 1%: the 2008 candidate file lacks 0.43% of candidacies.
    assert check_matched(pl.DataFrame({"matched": [True] * 990 + [False] * 10}), "votes 2008") == 10
    with pytest.raises(BuildError, match="match no candidacy"):
        check_matched(df, "votes 2000", max_share=0.0001)


def test_default_match_share_stops_the_fixture_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    with pytest.raises(BuildError, match="match no candidacy"):
        run(store, manifests, tmp_path, max_unmatched_share=0.001)


def test_a_duplicate_vote_row_raises(tmp_path):
    data = fixture(f"{VOTES_NAME}_2000")
    store = MemoryStore()
    manifests = stage(store, overrides={f"{VOTES_NAME}_2000": with_rows_added(data, [(0, {})])})
    with pytest.raises(BuildError, match="repeat the key"):
        run(store, manifests, tmp_path)


def test_a_duplicate_turnout_row_raises(tmp_path):
    data = fixture(f"{TURNOUT_NAME}_2000")
    store = MemoryStore()
    manifests = stage(store, overrides={f"{TURNOUT_NAME}_2000": with_rows_added(data, [(0, {})])})
    with pytest.raises(BuildError, match="repeat the key"):
        run(store, manifests, tmp_path)


def test_a_town_missing_from_the_municipalities_table_stops_the_build(tmp_path):
    store = MemoryStore()
    manifests = stage(store, munis=munis_blob({"05436": "1507409"}))
    with pytest.raises(BuildError, match="no cd_ibge"):
        run(store, manifests, tmp_path)


def test_a_vote_count_that_is_not_an_integer_stops_the_build(tmp_path):
    data = fixture(f"{TURNOUT_NAME}_2000")
    store = MemoryStore()
    # Field 18 is QT_APTOS.
    changed = with_rows_added(data, [(0, {18: b"abc", 15: b"77"})])
    manifests = stage(store, overrides={f"{TURNOUT_NAME}_2000": changed})
    with pytest.raises(BuildError, match="not an integer"):
        run(store, manifests, tmp_path)


# --- Inputs


def test_only_candidate_vote_and_turnout_zips_are_used():
    store = MemoryStore()
    acquire, _, _ = stage(store)
    assert len(acquire["files"]) == 6
    found = inputs_from_manifest(acquire)
    assert len(found) == 4
    assert {i.kind for i in found} == {"votes", "turnout"}


def test_a_year_with_only_one_kind_is_refused():
    manifest = {"files": [{"path": RAW + "votacao_candidato_munzona_2000.zip", "sha256": "1" * 64}]}
    with pytest.raises(BuildError, match="need both"):
        inputs_from_manifest(manifest)


def test_no_matching_zips_is_refused():
    with pytest.raises(BuildError, match="lists no candidate-vote"):
        inputs_from_manifest({"files": []})


def test_manifest_file_needs_exactly_one_match():
    with pytest.raises(BuildError):
        manifest_file({"files": [{"path": MUNI_PREFIX + "legal_amazon.csv"}]}, "x.parquet")


def test_a_zip_that_differs_from_its_manifest_sha_is_refused(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    manifests[0]["files"][0]["sha256"] = "f" * 64
    with pytest.raises(BuildError, match="does not match the sha256"):
        run(store, manifests, tmp_path)


# --- Done when 6: the path hashes inputs and code


def test_changing_any_input_sha_changes_the_output_path():
    shas = ["1" * 64, "2" * 64, "3" * 64]
    base = input_hash(shas)
    assert input_hash([*shas[:-1], "4" * 64]) != base
    assert input_hash(shas[::-1]) == base  # sorted, so order does not matter


def test_changing_the_source_of_tse_candidates_changes_the_path(tmp_path):
    other = tmp_path / "tse_candidates_changed.py"
    other.write_text(
        Path(tse_candidates.__file__).read_text(encoding="utf-8") + "\n# fix\n", encoding="utf-8"
    )
    this = CODE_MODULES[0]
    shas = ["1" * 64, "2" * 64]
    assert input_hash(shas, CODE_MODULES) == input_hash(shas, [this, CODE_MODULES[1]])
    assert input_hash(shas, CODE_MODULES) != input_hash(shas, [this, other])


def test_code_modules_include_this_build_and_tse_candidates():
    assert Path(tse_candidates.__file__) in CODE_MODULES
    assert Path(__file__).parents[1] / "src" / "terrain" / "builds" / "tse_results.py" in [
        Path(p) for p in CODE_MODULES
    ]


def test_a_different_candidates_or_municipalities_table_gives_a_new_path(built, tmp_path):
    _, out = built
    store = MemoryStore()
    manifests = stage(store, munis=munis_blob({"05436": "1507409", "05533": "1507962"}))
    assert run(store, manifests, tmp_path)["gcs_prefix"] != out["gcs_prefix"]
    store = MemoryStore()
    extra = [{"ano_eleicao": 2000, "cd_eleicao": 1, "sg_ue": "X", "sq_candidato": "1"}]
    manifests = stage(store, candidates=candidates_blob(extra=extra))
    assert run(store, manifests, tmp_path)["gcs_prefix"] != out["gcs_prefix"]
    store = MemoryStore()
    assert run(store, stage(store), tmp_path)["gcs_prefix"] == out["gcs_prefix"]


def test_second_build_is_unchanged_and_writes_nothing(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    first = run(store, manifests, tmp_path)
    write_manifest(first, store, tmp_path / "m.json")
    before = sorted(store.list(""))
    second = run(store, manifests, tmp_path)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]
    assert sorted(store.list("")) == before


def test_match_share_counts_candidacies_not_rows():
    # One unmatched candidacy with a row in each of 13 zones is 1 of 2 candidacies,
    # not 13 of 14 rows.
    key = {"ano_eleicao": [2008] * 14, "cd_eleicao": [1] * 14, "sg_ue": ["04367"] * 14}
    df = pl.DataFrame({**key, "sq_candidato": ["a"] + ["b"] * 13, "matched": [True] + [False] * 13})
    assert check_matched(df, "votes 2008", max_share=0.5) == 1
    with pytest.raises(BuildError, match="1 of 2 candidacies match no candidacy"):
        check_matched(df, "votes 2008", max_share=0.4)


def test_a_failed_year_leaves_nothing_in_the_store(tmp_path):
    store = MemoryStore()
    manifests = stage(store)
    before = set(store.list(""))
    with pytest.raises(BuildError):
        run(store, manifests, tmp_path, max_unmatched_share=0.0)
    assert set(store.list("")) == before
