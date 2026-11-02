import csv
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from terrain.builds.municipalities import (
    CODE_MODULES,
    BuildError,
    build,
    check_legal_amazon,
    input_hash,
    normalise_name,
)
from terrain.catalog import dataset
from terrain.manifest import MANIFEST_NAME, validate_manifest
from terrain.split import read_municipalities
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
VARIANTS = ROOT / "data" / "reference" / "tse_ibge_name_variants.yaml"
DERIVED = dataset("municipalities")["derived"]
IBGE_RAW = "data/raw/ibge/municipalities/2026-11-02/"
HIDALGO_RAW = "data/raw/geocodes/hidalgo/2026-11-02/"
CANDIDATES_DERIVED = "data/derived/tse_candidates/0123456789abcdef/"

DTB_XML = "RELATORIO_DTB_BRASIL_2024_MUNICIPIOS"
LEGAL_XML = "Municipios_da_Amazonia_Legal_2024"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)  # zip entries otherwise carry the current time

BAHIA_SC = ["36765", "36773", "36790", "36811", "36820", "81205", "81507"]


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=FIXED_TIME), data)
    return buf.getvalue()


def ods_from(xml_name: str, replace: tuple[str, str] | None = None) -> bytes:
    """An ODS made from a fixture content.xml (see data/fixtures/ibge/README.md)."""
    xml = (FIXTURES / "ibge" / f"{xml_name}.content.xml").read_text(encoding="utf-8")
    if replace:
        assert replace[0] in xml
        xml = xml.replace(*replace)
    return _zip(
        {
            "mimetype": b"application/vnd.oasis.opendocument.spreadsheet",
            "content.xml": xml.encode("utf-8"),
        }
    )


def hidalgo_frame() -> pl.DataFrame:
    return pl.read_csv(
        FIXTURES / "hidalgo" / "geocoded_polling_stations_sample.csv", infer_schema=False
    )


def tse_fixture_names() -> list[tuple[int, str, str]]:
    """(year, sg_ue, nm_ue) of every candidate in the TSE fixtures."""
    found = []
    for path in sorted((FIXTURES / "tse").glob("consulta_cand_20??_sample.csv")):
        text = path.read_bytes().decode("latin-1")
        for r in csv.DictReader(io.StringIO(text, newline=""), delimiter=";"):
            found.append((int(r["ANO_ELEICAO"]), r["SG_UE"], r["NM_UE"]))
    return found


def candidates_frame(hidalgo: pl.DataFrame) -> pl.DataFrame:
    """Candidate names for every code in `hidalgo`.

    The TSE fixtures hold some of these towns (and others that have no pair, which
    are left out); for the rest the name is Hidalgo's own, in 2024.
    """
    codes = {c.zfill(5) for c in hidalgo["cd_localidade_tse"]}
    rows = [(y, ue, nm) for y, ue, nm in tse_fixture_names() if ue in codes]
    named = {ue for _, ue, _ in rows}
    latest = (
        hidalgo.sort("ano")
        .group_by("cd_localidade_tse", maintain_order=True)
        .agg(pl.col("nm_localidade").last())
    )
    for code, name in latest.iter_rows():
        if code.zfill(5) not in named:
            rows.append((2024, code.zfill(5), name))
    return pl.DataFrame(
        {
            "ano_eleicao": pl.Series([r[0] for r in rows], dtype=pl.Int32),
            "sg_ue": [r[1] for r in rows],
            "sg_uf": ["XX"] * len(rows),
            "nm_ue": [r[2] for r in rows],
            "other_column": ["not read"] * len(rows),
        }
    )


def gz_csv(df: pl.DataFrame) -> bytes:
    return gzip.compress(df.write_csv().encode("utf-8"), mtime=0)


def stage(
    store: MemoryStore,
    *,
    hidalgo: pl.DataFrame | None = None,
    candidates: pl.DataFrame | None = None,
    legal_replace: tuple[str, str] | None = None,
) -> tuple[dict, dict, dict]:
    """Put inputs made from the fixtures in `store`; return the three manifests."""
    hidalgo = hidalgo if hidalgo is not None else hidalgo_frame()
    candidates = candidates if candidates is not None else candidates_frame(hidalgo)

    def put(path: str, data: bytes) -> dict:
        store.create(path, data)
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    dtb = _zip({f"{DTB_XML}.ods": ods_from(DTB_XML), "leiame.txt": b"x"})
    ibge = {
        "dataset": "ibge_municipalities",
        "gcs_prefix": IBGE_RAW,
        "files": [
            put(IBGE_RAW + "DTB_2024.zip", dtb),
            put(IBGE_RAW + f"{LEGAL_XML}.ods", ods_from(LEGAL_XML, legal_replace)),
        ],
    }
    pairs = {
        "dataset": "polling_stations_geocoded",
        "gcs_prefix": HIDALGO_RAW,
        "files": [
            put(HIDALGO_RAW + "geocoded_polling_stations.csv.gz", gz_csv(hidalgo)),
            put(HIDALGO_RAW + "panel_ids.csv.gz", gzip.compress(b"x\n", mtime=0)),
        ],
    }
    buf = io.BytesIO()
    candidates.write_parquet(buf)
    built = {
        "dataset": "tse_candidates",
        "gcs_prefix": CANDIDATES_DERIVED,
        "files": [put(CANDIDATES_DERIVED + "candidates.parquet", buf.getvalue())],
    }
    return ibge, pairs, built


def run(store: MemoryStore, manifests, tmp_path: Path, variants: Path = VARIANTS) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return build(
        store,
        *manifests,
        derived_root=DERIVED,
        tmp_dir=work,
        variants_path=variants,
        code_commit="abc",
    )


def table_of(store: MemoryStore, manifest: dict) -> pl.DataFrame:
    path = next(f["path"] for f in manifest["files"] if f["path"].endswith(".parquet"))
    return pl.read_parquet(store.read_bytes(path))


def swapped(df: pl.DataFrame, a: str, b: str) -> pl.DataFrame:
    ibge = {r[0]: r[1] for r in df.select("cd_localidade_tse", "cod_localidade_ibge").iter_rows()}
    return df.with_columns(
        pl.when(pl.col("cd_localidade_tse") == a)
        .then(pl.lit(ibge[b]))
        .when(pl.col("cd_localidade_tse") == b)
        .then(pl.lit(ibge[a]))
        .otherwise(pl.col("cod_localidade_ibge"))
        .alias("cod_localidade_ibge")
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    store = MemoryStore()
    manifests = stage(store)
    out = run(store, manifests, tmp_path_factory.mktemp("build"))
    return store, manifests, out, table_of(store, out)


# --- Done when 1 and 2: the mapping


def test_boa_esperanca_do_norte_maps_and_is_in_the_legal_amazon(built):
    _, _, out, df = built
    row = df.filter(pl.col("cd_tse") == "73709").row(0, named=True)
    assert row["cd_ibge"] == "5101837"
    assert row["legal_amazon"] is True
    assert row["uf"] == "MT"
    assert out["status"] == "created"
    assert validate_manifest(out, stage="build", dataset="municipalities") == []


def test_bahia_and_santa_catarina_map_to_hidalgo_codes_with_exact_names(built):
    _, _, _, df = built
    expected = {
        r[0].zfill(5): r[1]
        for r in hidalgo_frame().select("cd_localidade_tse", "cod_localidade_ibge").iter_rows()
    }
    for code in BAHIA_SC:
        row = df.filter(pl.col("cd_tse") == code).row(0, named=True)
        assert row["cd_ibge"] == expected[code]
        assert row["name_check"] == "exact"
        assert row["legal_amazon"] is False


def test_table_shape(built):
    _, _, _, df = built
    assert df.columns == [
        "cd_ibge",
        "cd_tse",
        "uf",
        "name_ibge",
        "name_tse",
        "legal_amazon",
        "name_check",
    ]
    assert df.height == 17  # the municipalities in the DTB fixture
    assert df["cd_ibge"].is_unique().all()
    assert df["cd_ibge"].to_list() == sorted(df["cd_ibge"].to_list())
    assert df.schema["legal_amazon"] == pl.Boolean
    assert (df["cd_tse"].drop_nulls().str.len_chars() == 5).all()
    assert df["legal_amazon"].sum() == 9


def test_name_tse_comes_from_the_latest_year(tmp_path):
    hidalgo = hidalgo_frame()
    cands = candidates_frame(hidalgo)
    old = pl.DataFrame(
        {
            "ano_eleicao": pl.Series([2000], dtype=pl.Int32),
            "sg_ue": ["05533"],
            "sg_uf": ["PA"],
            "nm_ue": ["NOME ANTIGO"],
            "other_column": ["x"],
        }
    )
    store = MemoryStore()
    manifests = stage(store, hidalgo=hidalgo, candidates=pl.concat([old, cands]))
    df = table_of(store, run(store, manifests, tmp_path))
    assert df.filter(pl.col("cd_tse") == "05533")["name_tse"].item() == "SÃO SEBASTIÃO DA BOA VISTA"


def test_pair_without_a_candidate_name_is_unchecked(tmp_path):
    hidalgo = hidalgo_frame()
    cands = candidates_frame(hidalgo).filter(pl.col("sg_ue") != "05436")
    store = MemoryStore()
    df = table_of(store, run(store, stage(store, hidalgo=hidalgo, candidates=cands), tmp_path))
    row = df.filter(pl.col("cd_tse") == "05436").row(0, named=True)
    assert row["name_check"] == "unchecked"
    assert row["name_tse"] is None


def test_municipality_without_a_pair_has_null_tse_code(tmp_path):
    hidalgo = hidalgo_frame().filter(pl.col("cd_localidade_tse") != "5436")
    store = MemoryStore()
    df = table_of(store, run(store, stage(store, hidalgo=hidalgo), tmp_path))
    row = df.filter(pl.col("cd_ibge") == "1507201").row(0, named=True)
    assert row["cd_tse"] is None
    assert row["name_check"] is None


# --- Done when 3: name checks


def test_swapped_pairs_fail_the_name_check(tmp_path):
    store = MemoryStore()
    manifests = stage(store, hidalgo=swapped(hidalgo_frame(), "36765", "36773"))
    with pytest.raises(BuildError, match="name check"):
        run(store, manifests, tmp_path)


def test_an_unlisted_variant_raises(tmp_path):
    empty = tmp_path / "variants.yaml"
    empty.write_text("variants: []\n", encoding="utf-8")
    store = MemoryStore()
    with pytest.raises(BuildError, match="04120"):
        run(store, stage(store), tmp_path, variants=empty)


def test_a_listed_variant_passes_as_variant(built):
    _, _, _, df = built
    for code in ("04120", "34118"):
        assert df.filter(pl.col("cd_tse") == code)["name_check"].item() == "variant"


def test_a_variant_listed_with_other_codes_still_raises(tmp_path):
    listed = tmp_path / "variants.yaml"
    listed.write_text(
        'variants:\n  - {tse: "04120", ibge: "1501782"}\n  - {tse: "34118", ibge: "2905602"}\n',
        encoding="utf-8",
    )
    store = MemoryStore()
    with pytest.raises(BuildError, match="04120"):
        run(store, stage(store), tmp_path, variants=listed)


def test_normalise_name():
    assert normalise_name("Espigão D'Oeste") == "ESPIGAO D OESTE"
    assert normalise_name("  Ilhéus-Itabuna ") == "ILHEUS ITABUNA"
    assert normalise_name("SÃO LUÍS") == normalise_name("Sao Luis")


# --- Done when 4: the other checks


def test_pairs_that_are_not_one_to_one_raise(tmp_path):
    extra = (
        hidalgo_frame()
        .filter(pl.col("cd_localidade_tse") == "5436")
        .with_columns(pl.lit("1501782").alias("cod_localidade_ibge"))
    )
    store = MemoryStore()
    manifests = stage(store, hidalgo=pl.concat([hidalgo_frame(), extra]))
    with pytest.raises(BuildError, match="one-to-one"):
        run(store, manifests, tmp_path)


def test_an_ibge_code_missing_from_the_dtb_raises(tmp_path):
    hidalgo = hidalgo_frame().with_columns(
        pl.when(pl.col("cd_localidade_tse") == "5436")
        .then(pl.lit("1234567"))
        .otherwise(pl.col("cod_localidade_ibge"))
        .alias("cod_localidade_ibge")
    )
    store = MemoryStore()
    with pytest.raises(BuildError, match="not in DTB"):
        run(store, stage(store, hidalgo=hidalgo), tmp_path)


def test_a_tse_code_in_the_candidates_without_a_pair_raises(tmp_path):
    hidalgo = hidalgo_frame()
    extra = pl.DataFrame(
        {
            "ano_eleicao": pl.Series([2024], dtype=pl.Int32),
            "sg_ue": ["99999"],
            "sg_uf": ["PA"],
            "nm_ue": ["SEM PAR"],
            "other_column": ["x"],
        }
    )
    store = MemoryStore()
    manifests = stage(
        store, hidalgo=hidalgo, candidates=pl.concat([candidates_frame(hidalgo), extra])
    )
    with pytest.raises(BuildError, match="no pair"):
        run(store, manifests, tmp_path)


def test_a_legal_amazon_code_missing_from_the_dtb_raises(tmp_path):
    store = MemoryStore()
    manifests = stage(store, legal_replace=("<text:p>5101837</text:p>", "<text:p>5199999</text:p>"))
    with pytest.raises(BuildError, match="Legal Amazon"):
        run(store, manifests, tmp_path)


def test_check_legal_amazon_rejects_a_wrong_state():
    dtb = {"1501782": "Breu Branco"}
    check_legal_amazon({"1501782": "PA"}, dtb)
    with pytest.raises(BuildError, match="state"):
        check_legal_amazon({"1501782": "MT"}, dtb)


def test_a_file_that_does_not_match_its_manifest_sha_raises(tmp_path):
    store = MemoryStore()
    ibge, pairs, cands = stage(store)
    ibge["files"][0]["sha256"] = "0" * 64
    with pytest.raises(BuildError, match="sha256"):
        run(store, (ibge, pairs, cands), tmp_path)


# --- Done when 5: legal_amazon.csv


def test_legal_amazon_csv_is_read_by_the_split_reader(built):
    store, _, out, df = built
    path = next(f["path"] for f in out["files"] if f["path"].endswith("legal_amazon.csv"))
    text = store.read_bytes(path).decode("utf-8")
    assert text.splitlines()[0] == "code_ibge,uf"
    rows = read_municipalities(text)
    assert len(rows) == 9
    assert ("5101837", "MT") in rows
    assert {c for c, _ in rows} == set(df.filter(pl.col("legal_amazon"))["cd_ibge"])


# --- Done when 6: idempotence


def test_second_build_is_unchanged(built, tmp_path):
    store, manifests, out, _ = built
    # The caller records the manifest when the status is "created".
    store.create(out["gcs_prefix"] + MANIFEST_NAME, json.dumps(out).encode("utf-8"))
    again = run(store, manifests, tmp_path)
    assert again["status"] == "unchanged"
    assert again["gcs_prefix"] == out["gcs_prefix"]


def test_changed_input_gives_a_new_path(built, tmp_path):
    _, _, out, _ = built
    store = MemoryStore()
    hidalgo = hidalgo_frame().filter(pl.col("cd_localidade_tse") != "5436")
    other = run(store, stage(store, hidalgo=hidalgo), tmp_path)
    assert other["gcs_prefix"] != out["gcs_prefix"]


def test_output_path_covers_the_ods_reader_and_input_order(tmp_path):
    names = {m.name for m in CODE_MODULES}
    assert names == {"municipalities.py", "ods.py"}
    variants = tmp_path / "variants.yaml"
    variants.write_text("variants: []\n", encoding="utf-8")
    files = [{"sha256": "a" * 64}, {"sha256": "b" * 64}]
    base = input_hash(files, variants, code=["build", "ods"])
    assert input_hash(list(reversed(files)), variants, code=["build", "ods"]) == base
    assert input_hash(files, variants, code=["build", "ods changed"]) != base
    assert input_hash(files, variants) != base  # the real sources are hashed by default
