import hashlib
import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds import section_votes as sv
from terrain.builds.section_votes import (
    BuildError,
    build,
    check_agreement,
    check_unmatched,
    input_hash,
    pick_candidacy,
    read_section_zip,
    vote_type,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest, write_manifest
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures" / "tse"
CONTRACT = ROOT / "data" / "contracts" / "section_votes.md"
DERIVED = dataset("section_votes")["derived"]

RAW_SECTIONS = "data/raw/tse/sections/2026-11-02/"
RESULTS = "data/derived/tse_results/0123456789abcdef/"
MUNICIPALITIES = "data/derived/municipalities/0123456789abcdef/"

# Fixed timestamps: otherwise the same fixture gives a different SHA-256 (and
# output path) a second later.
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


# --- Inputs made from the fixtures


def fixture_bytes(year: int) -> bytes:
    return (FIXTURES / f"votacao_secao_{year}_PA_sample.csv").read_bytes()


def make_zip(year: int, uf: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo(f"votacao_secao_{year}_{uf}.csv", FIXED_TIME), data)
        zf.writestr(zipfile.ZipInfo("leiame.pdf", FIXED_TIME), b"%PDF-")
    return buf.getvalue()


def frame(data: bytes) -> pl.DataFrame:
    text = data.decode("latin-1").encode("utf-8")
    df = pl.read_csv(io.BytesIO(text), separator=";", infer_schema=False)
    return df.rename({c: c.lower() for c in df.columns})


def results_from_sections(data: bytes) -> pl.DataFrame:
    """Counted votes per candidacy, equal to the section sums (as in the real files).

    The candidacy and number of each candidate row come from the fixture's own
    columns; the build never sees those before 2024.
    """
    s = frame(data).with_columns(pl.col("nr_votavel").cast(pl.Int64))
    candidate = ~pl.col("nr_votavel").is_in([95, 96, 97]) & (
        (pl.col("cd_cargo") == "11") | (pl.col("nr_votavel") >= 100)
    )
    return (
        s.filter(candidate)
        .group_by("cd_eleicao", "sg_ue", "cd_cargo", "nr_turno", "sq_candidato", "nr_votavel")
        .agg(pl.col("qt_votos").cast(pl.Int64).sum().alias("qt_votos_nominais"))
        .select(
            pl.col("cd_eleicao").cast(pl.Int32),
            "sg_ue",
            "cd_cargo",
            pl.col("nr_turno").cast(pl.Int32),
            "sq_candidato",
            pl.col("nr_votavel").cast(pl.String).alias("nr_candidato"),
            "qt_votos_nominais",
        )
        .sort("sq_candidato")
    )


def municipalities_bytes(path: Path) -> bytes:
    rows = [
        ("1507706", "05533", True),
        ("1507979", "04367", True),
        ("2905602", "34118", False),
        ("3550308", "71072", False),
    ]
    pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "cd_tse": [r[1] for r in rows],
            "uf": ["PA", "PA", "BA", "SP"],
            "legal_amazon": [r[2] for r in rows],
        }
    ).write_parquet(path)
    return path.read_bytes()


def entry(path: str, blob: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def manifest(dataset_name: str, stage: str, prefix: str, files: list[dict]) -> dict:
    return {"dataset": dataset_name, "stage": stage, "gcs_prefix": prefix, "files": files}


def stage(
    store: MemoryStore,
    tmp_path: Path,
    *,
    sections: dict[tuple[int, str], bytes],
    results: dict[int, pl.DataFrame],
) -> tuple[dict, dict, dict]:
    section_files = []
    for (year, uf), data in sections.items():
        blob = make_zip(year, uf, data)
        path = f"{RAW_SECTIONS}votacao_secao_{year}_{uf}.zip"
        store.create(path, blob)
        section_files.append(entry(path, blob))
    result_files = []
    for year, df in results.items():
        local = tmp_path / f"cv_{year}.parquet"
        df.write_parquet(local)
        blob = local.read_bytes()
        path = f"{RESULTS}candidate_votes_{year}.parquet"
        store.create(path, blob)
        result_files.append(entry(path, blob))
    mun_path = MUNICIPALITIES + "municipalities.parquet"
    blob = municipalities_bytes(tmp_path / "mun.parquet")
    store.create(mun_path, blob)
    return (
        manifest("tse_votes_by_section", "acquire", RAW_SECTIONS, section_files),
        manifest("tse_results", "build", RESULTS, result_files),
        manifest("municipalities", "build", MUNICIPALITIES, [entry(mun_path, blob)]),
    )


def run(store, tmp_path, sections, results, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifests = stage(store, tmp_path, sections=sections, results=results)
    return run_staged(store, tmp_path, manifests, **kwargs)


def run_staged(store, tmp_path, manifests, **kwargs):
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return build(
        store,
        *manifests,
        derived_root=DERIVED,
        tmp_dir=work,
        code_commit="abc",
        created_at="2026-11-02T00:00:00+00:00",
        **kwargs,
    )


def read_output(store: MemoryStore, m: dict, name: str) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(store.read_bytes(m["gcs_prefix"] + name)))


def one_year(year: int) -> tuple[dict, dict]:
    data = fixture_bytes(year)
    return {(year, "PA"): data}, {year: results_from_sections(data)}


def duplicate_first_row(data: bytes) -> bytes:
    lines = data.split(b"\r\n")
    return b"\r\n".join([lines[0], lines[1], *lines[1:]])


# --- Done when


def test_2024_candidate_votes_carry_the_files_sq(tmp_path):
    store = MemoryStore()
    sections, results = one_year(2024)
    m = run(store, tmp_path, sections, results)
    out = read_output(store, m, "section_votes_2024_PA.parquet")
    candidates = out.filter(pl.col("vote_type") == "candidate")
    assert candidates.height > 0
    assert candidates["sq_candidato"].null_count() == 0
    assert out.filter(pl.col("vote_type") != "candidate")["sq_candidato"].null_count() == (
        out.height - candidates.height
    )
    assert out.columns == sv.OUTPUT_COLUMNS
    assert out["sg_ue"].str.len_chars().min() == 5  # leading zeros survive
    assert set(out["cd_ibge"]) <= {"1507706", "1507979"}
    assert validate_manifest(m, stage="build", dataset="section_votes") == []


def test_2008_sq_comes_from_the_results_match_and_equals_the_files(tmp_path):
    store = MemoryStore()
    sections, results = one_year(2008)
    m = run(store, tmp_path, sections, results)
    out = read_output(store, m, "section_votes_2008_PA.parquet")
    raw = frame(fixture_bytes(2008)).select(
        pl.col("cd_eleicao").cast(pl.Int32),
        "sg_ue",
        "nr_zona",
        "nr_secao",
        "cd_cargo",
        pl.col("nr_turno").cast(pl.Int32),
        pl.col("nr_votavel").cast(pl.Int64),
        pl.col("sq_candidato").alias("file_sq"),
    )
    keys = ["cd_eleicao", "sg_ue", "nr_zona", "nr_secao", "cd_cargo", "nr_turno", "nr_votavel"]
    candidates = out.filter(pl.col("vote_type") == "candidate").join(raw, on=keys, how="left")
    assert candidates.height > 0
    assert candidates["sq_candidato"].null_count() == 0
    assert (candidates["sq_candidato"] == candidates["file_sq"]).all()


def test_vote_type_for_each_kind_of_number():
    df = pl.DataFrame(
        {
            "nr_votavel": [95, 96, 97, 13, 45111, 13],
            "cd_cargo": ["13", "13", "13", "13", "13", "11"],
        }
    )
    got = df.with_columns(vote_type())["vote_type"].to_list()
    assert got == ["blank", "null", "annulled", "legend", "candidate", "candidate"]


def test_a_number_with_two_candidacies_picks_the_one_with_votes():
    base = {"cd_eleicao": 30, "sg_ue": "04367", "cd_cargo": "13", "nr_turno": 1}
    cand = pl.DataFrame(
        [
            {**base, "sq_candidato": "1", "nr_candidato": 12345, "nominal": 0},
            {**base, "sq_candidato": "2", "nr_candidato": 12345, "nominal": 40},
            {**base, "sq_candidato": "3", "nr_candidato": 55555, "nominal": 5},
        ]
    )
    pick, several = pick_candidacy(cand)
    chosen = dict(zip(pick["nr_votavel"].to_list(), pick["sq_candidato"].to_list(), strict=True))
    assert chosen == {12345: "2", 55555: "3"}
    assert several == 0
    both_voted = cand.with_columns(
        pl.when(pl.col("sq_candidato") == "1").then(7).otherwise(pl.col("nominal")).alias("nominal")
    )
    pick, several = pick_candidacy(both_voted)
    assert several == 1
    assert pick.filter(pl.col("nr_votavel") == 12345)["sq_candidato"].to_list() == ["2"]


def test_vote_sum_check_passes_on_consistent_input_and_raises_above_one_percent(tmp_path):
    check_agreement(2008, 99, 100, 0.99)
    with pytest.raises(BuildError, match="98 of 100"):
        check_agreement(2008, 98, 100, 0.99)
    with pytest.raises(BuildError, match="no candidates"):
        check_agreement(2008, 0, 0, 0.99)

    store = MemoryStore()
    sections, results = one_year(2008)
    m = run(store, tmp_path, sections, results)
    total = results[2008].height
    assert f"section_sums_equal_results={total}/{total}" in m["notes"]

    bumped = results[2008].with_columns(pl.col("qt_votos_nominais") + 1)
    with pytest.raises(BuildError, match="section sums equal the counted votes"):
        run(MemoryStore(), tmp_path / "b", sections, {2008: bumped})


def test_a_candidacy_with_zero_counted_votes_is_flagged_and_not_a_disagreement(tmp_path):
    store = MemoryStore()
    sections, results = one_year(2008)
    res = results[2008].sort("qt_votos_nominais", descending=True)
    annulled_sq = res["sq_candidato"][0]
    res = res.with_columns(
        pl.when(pl.col("sq_candidato") == annulled_sq)
        .then(0)
        .otherwise(pl.col("qt_votos_nominais"))
        .alias("qt_votos_nominais")
    )
    m = run(store, tmp_path, sections, {2008: res})
    out = read_output(store, m, "section_votes_2008_PA.parquet")
    flagged = out.filter(pl.col("annulled_in_results"))
    assert flagged["sq_candidato"].unique().to_list() == [annulled_sq]
    assert (flagged["vote_type"] == "candidate").all()
    assert out.filter(pl.col("sq_candidato") == annulled_sq).height == flagged.height
    assert "annulled_in_results_candidacies=1" in m["notes"]
    others = res.height - 1
    assert f"section_sums_equal_results={others}/{others}" in m["notes"]


def test_unmatched_numbers_at_half_a_percent_raise(tmp_path):
    check_unmatched(2008, 1000, 4, 0.005)
    with pytest.raises(BuildError, match="5 of 1000"):
        check_unmatched(2008, 1000, 5, 0.005)

    sections, results = one_year(2008)
    missing = results[2008].slice(1)  # one candidacy has no results row
    with pytest.raises(BuildError, match="candidate numbers have no candidacy"):
        run(MemoryStore(), tmp_path, sections, {2008: missing})


def test_a_duplicated_key_raises(tmp_path):
    sections, results = one_year(2008)
    sections = {k: duplicate_first_row(v) for k, v in sections.items()}
    with pytest.raises(BuildError, match="rows repeat the key"):
        run(MemoryStore(), tmp_path, sections, results)


def test_a_2000_input_is_skipped_and_named_in_the_notes(tmp_path):
    store = MemoryStore()
    sections, results = one_year(2008)
    sections[(2000, "PA")] = fixture_bytes(2008)
    m = run(store, tmp_path, sections, results)
    assert "2000: skipped" in m["notes"]
    names = [f["path"].rsplit("/", 1)[-1] for f in m["files"]]
    assert names == ["section_votes_2008_PA.parquet"]


def test_no_partial_upload_when_a_later_year_fails(tmp_path):
    store = MemoryStore()
    s8, r8 = one_year(2008)
    s24, r24 = one_year(2024)
    bad = r24[2024].with_columns(pl.col("qt_votos_nominais") + 1)
    before = set(store.list(""))
    with pytest.raises(BuildError):
        run(store, tmp_path, {**s8, **s24}, {2008: r8[2008], 2024: bad})
    created = [p for p in store.list(DERIVED) if p not in before]
    assert created == []


def test_the_output_path_changes_with_the_code_sources(tmp_path):
    files = [{"sha256": "a" * 64}, {"sha256": "b" * 64}]
    one = input_hash(files, (2008,), ["code one"])
    assert one == input_hash(list(reversed(files)), (2008,), ["code one"])
    assert one != input_hash(files, (2008,), ["code two"])
    assert one != input_hash(files, (2008, 2012), ["code one"])
    assert sv.code_sources() == [Path(sv.__file__).read_text(encoding="utf-8")]


def test_a_second_run_on_the_same_inputs_is_unchanged(tmp_path):
    store = MemoryStore()
    sections, results = one_year(2008)
    manifests = stage(store, tmp_path, sections=sections, results=results)
    first = run_staged(store, tmp_path, manifests)
    assert first["status"] == "created"
    write_manifest(first, store, tmp_path / "manifest.json")
    assert store.exists(first["gcs_prefix"] + MANIFEST_NAME)
    second = run_staged(store, tmp_path, manifests)
    assert second["status"] == "unchanged"
    assert second["gcs_prefix"] == first["gcs_prefix"]


def test_the_reader_keeps_leading_zeros_and_rejects_a_bad_count(tmp_path):
    good = tmp_path / "good.zip"
    good.write_bytes(make_zip(2008, "PA", fixture_bytes(2008)))
    df = read_section_zip(good)
    assert df["sg_ue"].unique().to_list() == ["04367"]
    assert df["nr_votavel"].dtype == pl.Int64

    text = fixture_bytes(2008).decode("latin-1").replace(";3;1015;", ";x;1015;", 1)
    bad = tmp_path / "bad.zip"
    bad.write_bytes(make_zip(2008, "PA", text.encode("latin-1")))
    with pytest.raises(BuildError, match="not an integer"):
        read_section_zip(bad)


def test_fixture_zips_are_deterministic():
    data = fixture_bytes(2008)
    assert make_zip(2008, "PA", data) == make_zip(2008, "PA", data)


def test_the_contract_documents_the_flag_and_the_key():
    text = CONTRACT.read_text(encoding="utf-8")
    for word in ("annulled_in_results", "vote_type", "counted votes", "nr_votavel"):
        assert word in text


# --- Votes cast for candidacies that the results file does not list (annulled)

CANDIDATES = "data/derived/tse_candidates/0123456789abcdef/"


def candidates_manifest(store: MemoryStore, tmp_path: Path, year: int, cv: pl.DataFrame) -> dict:
    """A candidates table holding every candidacy of `cv` (the candidate file)."""
    df = cv.select(
        pl.lit(year, dtype=pl.Int64).alias("ano_eleicao"),
        pl.col("cd_eleicao").cast(pl.Int64),
        "sg_ue",
        "cd_cargo",
        "nr_candidato",
        "sq_candidato",
    )
    local = tmp_path / f"candidates_{year}.parquet"
    df.write_parquet(local)
    blob = local.read_bytes()
    path = CANDIDATES + "candidates.parquet"
    store.create(path, blob)
    return manifest("tse_candidates", "build", CANDIDATES, [entry(path, blob)])


@pytest.mark.parametrize("year", [2008, 2024])
def test_numbers_missing_from_the_results_are_annulled_not_unmatched(tmp_path, year):
    sections, results = one_year(year)
    full = results[year]
    dropped = full.filter(pl.col("cd_cargo") == "13").row(0, named=True)
    counted = full.filter(pl.col("sq_candidato") != dropped["sq_candidato"])
    store = MemoryStore()
    manifests = stage(store, tmp_path, sections=sections, results={year: counted})
    cands = candidates_manifest(store, tmp_path, year, full)
    out = run_staged(
        store, tmp_path, manifests, candidates_manifest=cands, max_unmatched_share=0.0001
    )
    df = read_output(store, out, sv.output_name(year, "PA"))
    rows = df.filter(
        (pl.col("cd_cargo") == "13") & (pl.col("nr_votavel") == int(dropped["nr_candidato"]))
    )
    assert rows.height > 0
    assert rows["sq_candidato"].unique().to_list() == [dropped["sq_candidato"]]
    assert rows["annulled_in_results"].all()
    assert "unmatched_candidate_numbers=0/" in out["notes"]


def test_without_the_candidate_file_a_missing_number_is_unmatched(tmp_path):
    sections, results = one_year(2008)
    full = results[2008]
    dropped = full.filter(pl.col("cd_cargo") == "13").row(0, named=True)
    counted = full.filter(pl.col("sq_candidato") != dropped["sq_candidato"])
    store = MemoryStore()
    manifests = stage(store, tmp_path, sections=sections, results={2008: counted})
    with pytest.raises(BuildError, match="have no candidacy"):
        run_staged(store, tmp_path, manifests, max_unmatched_share=0.0001)


# --- Incomplete section files (2004): agreement only where sections exist


def test_municipalities_without_section_data_are_left_out_of_agreement_and_counted(tmp_path):
    sections, results = one_year(2008)
    cv = results[2008]
    # A second municipality with results but no section file, as in 2004.
    # 05533 is a Legal Amazon municipality in the test table with no 2008 section file.
    extra = cv.with_columns(pl.lit("05533").alias("sg_ue"), (pl.col("sq_candidato") + "9"))
    store = MemoryStore()
    manifests = stage(store, tmp_path, sections=sections, results={2008: pl.concat([cv, extra])})
    out = run_staged(store, tmp_path, manifests, min_coverage_share=0.5)
    assert "municipalities_with_sections=1/2" in out["notes"]
    assert "(by state: PA=1)" in out["notes"]


def test_coverage_below_the_share_stops_the_build(tmp_path):
    sections, results = one_year(2008)
    cv = results[2008]
    # 05533 is a Legal Amazon municipality in the test table with no 2008 section file.
    extra = cv.with_columns(pl.lit("05533").alias("sg_ue"), (pl.col("sq_candidato") + "9"))
    store = MemoryStore()
    manifests = stage(store, tmp_path, sections=sections, results={2008: pl.concat([cv, extra])})
    with pytest.raises(BuildError, match="have section data"):
        run_staged(store, tmp_path, manifests, min_coverage_share=0.8)


def test_2004_coverage_is_reported_and_never_raises(tmp_path):
    # The 2008 fixture relabelled as 2004 (the year column is the unquoted field).
    lines = fixture_bytes(2008).split(b"\r\n")
    data = b"\r\n".join([lines[0], *(x.replace(b";2008;2;", b";2004;2;", 1) for x in lines[1:])])
    cv = results_from_sections(data)
    # 05533 has results but no section file, as in the TSE's incomplete 2004 files.
    extra = cv.with_columns(pl.lit("05533").alias("sg_ue"), (pl.col("sq_candidato") + "9"))

    store = MemoryStore()
    manifests = stage(
        store, tmp_path, sections={(2004, "PA"): data}, results={2004: pl.concat([cv, extra])}
    )
    out = run_staged(store, tmp_path, manifests, min_coverage_share=0.8)
    assert "municipalities_with_sections=1/2" in out["notes"]
    assert "(by state: PA=1)" in out["notes"]


def test_check_coverage_floor_and_report_only_year():
    sv.check_coverage(2008, 8, 10, 0.8)
    with pytest.raises(BuildError, match="only 7 of 10"):
        sv.check_coverage(2008, 7, 10, 0.8)
    sv.check_coverage(2004, 1, 10, 0.8)
    sv.check_coverage(2004, 0, 0, 0.8)
    assert sv.COVERAGE_REPORT_ONLY_YEARS == (2004,)


# --- National scope: a Legal Amazon state (PA) and one outside it (SP)


def as_state(data: bytes, uf: str, sg_ue: str) -> bytes:
    return data.replace(b';"PA";"04367"', f';"{uf}";"{sg_ue}"'.encode())


def test_two_states_are_kept_and_the_legal_amazon_rows_do_not_change(tmp_path):
    pa_data = fixture_bytes(2008)
    sp_data = as_state(pa_data, "SP", "71072")
    assert sp_data != pa_data
    pa_results = results_from_sections(pa_data)
    sp_results = results_from_sections(sp_data)

    pa_store = MemoryStore()
    only_pa = run(pa_store, tmp_path / "pa", {(2008, "PA"): pa_data}, {2008: pa_results})
    store = MemoryStore()
    both = run(
        store,
        tmp_path / "both",
        {(2008, "PA"): pa_data, (2008, "SP"): sp_data},
        {2008: pl.concat([pa_results, sp_results])},
    )
    assert [f["path"].rsplit("/", 1)[-1] for f in both["files"]] == [
        "section_votes_2008_PA.parquet",
        "section_votes_2008_SP.parquet",
    ]
    pa = read_output(store, both, "section_votes_2008_PA.parquet")
    sp = read_output(store, both, "section_votes_2008_SP.parquet")
    # Pará rows are what the Pará-only build gives.
    assert pa.equals(read_output(pa_store, only_pa, "section_votes_2008_PA.parquet"))
    assert sp.height == pa.height > 0
    assert set(sp["sg_ue"]) == {"71072"}
    assert set(sp["cd_ibge"]) == {"3550308"}
    assert sp.drop("sg_ue", "cd_ibge").equals(pa.drop("sg_ue", "cd_ibge"))
    assert "rows_without_municipality=0" in both["notes"]
    assert "rows_outside_legal_amazon" not in both["notes"]
    assert "municipalities_with_sections=2/2" in both["notes"]
    assert "(by state: PA=1, SP=1)" in both["notes"]


def test_a_row_without_a_municipality_is_dropped_and_counted(tmp_path):
    data = fixture_bytes(2008)
    stray = as_state(data, "SP", "99999")
    lines = data.split(b"\r\n")
    mixed = b"\r\n".join([*lines[:-1], stray.split(b"\r\n")[1], b""])
    sections, results = {(2008, "PA"): mixed}, {2008: results_from_sections(data)}
    m = run(MemoryStore(), tmp_path, sections, results)
    assert "rows_without_municipality=1, other_election_year_rows=" in m["notes"]


# --- The streaming reader gives what the old whole-member reader gave


def old_read_section_zip(zip_path: Path) -> pl.DataFrame:
    """A copy of the reader before it streamed: the reference for the new one."""
    import re

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if re.fullmatch(r"votacao_secao_.*\.csv", n.lower())]
        assert len(members) == 1
        raw = zf.read(members[0]).decode("latin-1")
    df = pl.read_csv(io.BytesIO(raw.encode("utf-8")), separator=";", infer_schema=False)
    df = df.rename({c: c.strip().lower() for c in df.columns})
    needed = [*sv.TEXT_KEYS, *sv.INT_KEYS, "nr_votavel", "nr_local_votacao", "qt_votos"]
    if "sq_candidato" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("sq_candidato"))
    df = df.select(sv._text(c) for c in [*needed, "sq_candidato"])
    df = df.with_columns(
        pl.col(c).cast(pl.Int32) for c in [*sv.INT_KEYS, "nr_local_votacao"]
    ).with_columns(pl.col("nr_votavel").cast(pl.Int64), pl.col("qt_votos").cast(pl.Int64))
    sq = pl.col("sq_candidato")
    return df.with_columns(
        pl.when(sq.is_in(list(sv.MISSING_SQ))).then(None).otherwise(sq).alias("sq_file")
    ).drop("sq_candidato")


@pytest.mark.parametrize("year", [2008, 2024])
def test_the_streaming_reader_equals_the_old_reader_on_the_fixtures(tmp_path, year):
    path = tmp_path / f"votacao_secao_{year}_PA.zip"
    path.write_bytes(make_zip(year, "PA", fixture_bytes(year)))
    new = read_section_zip(path)
    old = old_read_section_zip(path)
    assert new.height > 0
    assert new.schema == old.schema
    assert new.equals(old)
    # The fixture's Latin-1 accents are decoded, not mangled.
    assert not any("�" in str(v) for v in new["sg_ue"].to_list())
    assert list(tmp_path.glob("*.utf8.csv")) == []


def test_a_member_larger_than_one_chunk_gives_every_row(tmp_path, monkeypatch):
    lines = fixture_bytes(2008).split(b"\r\n")
    header, body = lines[0], [line for line in lines[1:] if line]
    repeats = 40
    data = b"\r\n".join([header, *(body * repeats), b""])
    path = tmp_path / "votacao_secao_2008_PA.zip"
    path.write_bytes(make_zip(2008, "PA", data))

    monkeypatch.setattr(sv, "CHUNK_BYTES", 4096)
    assert len(data) > 5 * sv.CHUNK_BYTES
    chunked = read_section_zip(path)
    assert chunked.height == len(body) * repeats
    monkeypatch.undo()
    assert chunked.equals(old_read_section_zip(path))
    assert list(tmp_path.glob("*.utf8.csv")) == []


def test_the_reader_raises_on_a_missing_column_an_empty_key_and_a_bad_vote(tmp_path):
    base = fixture_bytes(2008)

    def zipped(name: str, data: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(make_zip(2008, "PA", data))
        return path

    no_column = base.replace(b'"QT_VOTOS"', b'"QT_VOTOS_X"', 1)
    with pytest.raises(BuildError, match="lacks 1 needed columns"):
        read_section_zip(zipped("no_column.zip", no_column))

    assert b'"04367"' in base
    empty_key = base.replace(b'"04367"', b'""', 1)
    with pytest.raises(BuildError, match="needed columns have empty values"):
        read_section_zip(zipped("empty_key.zip", empty_key))

    bad_vote = base.replace(b";3;1015;", b";x;1015;", 1)
    with pytest.raises(BuildError, match="not an integer"):
        read_section_zip(zipped("bad_vote.zip", bad_vote))
    assert list(tmp_path.glob("*.utf8.csv")) == []
