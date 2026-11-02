"""Build the municipalities table and the TSE-IBGE crosswalk.

Contract of the output: data/contracts/municipalities.md. The IBGE DTB 2024 gives
the municipalities, Hidalgo's geocoded polling stations give the TSE-IBGE code
pairs, and the built candidates table gives the name the TSE uses. Every pair is
checked by name; the reviewed exceptions are in
data/reference/tse_ibge_name_variants.yaml.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.ods import read_sheet
from terrain.storage import Store

DATASET = "municipalities"
TABLE_NAME = "municipalities.parquet"
LEGAL_AMAZON_NAME = "legal_amazon.csv"

DTB_MEMBER = "*MUNICIPIOS.ods"
DTB_CODE = "Código Município Completo"
DTB_NAME = "Nome_Município"
LA_CODE = "CD_MUN"
LA_UF = "SIGLA_UF"
HIDALGO_FILE = "geocoded_polling_stations.csv.gz"

# IBGE state codes (first two digits of a municipality code).
UF_BY_CODE = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}

_IBGE_CODE = re.compile(r"\d{7}")
_TSE_CODE = re.compile(r"\d{5}")


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def normalise_name(name: str) -> str:
    """Upper case, no accents, apostrophes and hyphens as spaces, single spaces."""
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = plain.upper().replace("'", " ").replace("’", " ").replace("-", " ")
    return " ".join(plain.split())


# --- Readers


def _header_row(rows: list[list[str]], header: str, what: str) -> tuple[int, list[str]]:
    for i, row in enumerate(rows):
        if header in row:
            return i, row
    raise BuildError(f"{what}: no header row with {header!r}")


def read_dtb(ods_bytes: bytes) -> dict[str, str]:
    """IBGE code -> IBGE name from the DTB sheet. Codes must be unique 7-digit text."""
    rows = read_sheet(ods_bytes)
    i, header = _header_row(rows, DTB_CODE, "DTB")
    if DTB_NAME not in header:
        raise BuildError(f"DTB: no column {DTB_NAME!r}")
    code_at, name_at = header.index(DTB_CODE), header.index(DTB_NAME)
    found: dict[str, str] = {}
    for row in rows[i + 1 :]:
        code = row[code_at].strip() if len(row) > code_at else ""
        if not code:
            continue
        if not _IBGE_CODE.fullmatch(code):
            raise BuildError(f"DTB: not a 7-digit IBGE code: {code!r}")
        if code in found:
            raise BuildError(f"DTB: repeated code {code}")
        found[code] = row[name_at].strip() if len(row) > name_at else ""
    if not found:
        raise BuildError("DTB: no municipalities")
    return found


def read_legal_amazon(ods_bytes: bytes) -> dict[str, str]:
    """IBGE code -> state letters from the first sheet of the Legal Amazon list."""
    rows = read_sheet(ods_bytes)
    i, header = _header_row(rows, LA_CODE, "Legal Amazon list")
    if LA_UF not in header:
        raise BuildError(f"Legal Amazon list: no column {LA_UF!r}")
    code_at, uf_at = header.index(LA_CODE), header.index(LA_UF)
    found: dict[str, str] = {}
    for row in rows[i + 1 :]:
        code = row[code_at].strip() if len(row) > code_at else ""
        if not code:
            continue
        if not _IBGE_CODE.fullmatch(code):
            raise BuildError(f"Legal Amazon list: not a 7-digit IBGE code: {code!r}")
        if code in found:
            raise BuildError(f"Legal Amazon list: repeated code {code}")
        found[code] = row[uf_at].strip().upper() if len(row) > uf_at else ""
    if not found:
        raise BuildError("Legal Amazon list: no municipalities")
    return found


def read_pairs(csv_gz: Path) -> list[tuple[str, str]]:
    """Distinct (TSE code padded to 5 digits, IBGE code) pairs from the Hidalgo file."""
    df = pl.read_csv(
        csv_gz,
        columns=["cd_localidade_tse", "cod_localidade_ibge"],
        infer_schema=False,
    ).drop_nulls()
    pairs: list[tuple[str, str]] = []
    for tse, ibge in df.unique().sort(["cd_localidade_tse", "cod_localidade_ibge"]).iter_rows():
        tse, ibge = tse.strip().zfill(5), ibge.strip()
        if not _TSE_CODE.fullmatch(tse):
            raise BuildError(f"Hidalgo: not a TSE code: {tse!r}")
        if not _IBGE_CODE.fullmatch(ibge):
            raise BuildError(f"Hidalgo: not a 7-digit IBGE code: {ibge!r}")
        pairs.append((tse, ibge))
    return sorted(set(pairs))


def read_tse_names(parquet: Path) -> tuple[dict[str, str], int]:
    """TSE code -> name from the code's latest election year.

    Only `ano_eleicao`, `sg_ue`, `sg_uf`, `nm_ue` are read. Codes that are not five
    digits (not municipalities) are left out; their number is the second value.
    """
    df = pl.read_parquet(parquet, columns=["ano_eleicao", "sg_ue", "sg_uf", "nm_ue"])
    valid = df.filter(pl.col("sg_ue").str.contains(r"^\d{5}$"))
    other = df.filter(~pl.col("sg_ue").str.contains(r"^\d{5}$") | pl.col("sg_ue").is_null())
    other_codes = other["sg_ue"].n_unique()
    latest = (
        valid.filter(pl.col("nm_ue").is_not_null())
        .filter(pl.col("ano_eleicao") == pl.col("ano_eleicao").max().over("sg_ue"))
        .group_by("sg_ue")
        .agg(pl.col("nm_ue").min())
        .sort("sg_ue")
    )
    names = dict(latest.iter_rows())
    # A code that appears in the candidates but has no name still has to have a pair.
    for code in valid["sg_ue"].unique().to_list():
        names.setdefault(code, "")
    return names, other_codes


def load_variants(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """(TSE code, IBGE code) -> the reviewed variant entry."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in doc["variants"]:
        key = (str(entry["tse"]).zfill(5), str(entry["ibge"]))
        found[key] = entry
    return found


# --- Checks


def check_one_to_one(pairs: list[tuple[str, str]]) -> None:
    by_tse: dict[str, set[str]] = {}
    by_ibge: dict[str, set[str]] = {}
    for tse, ibge in pairs:
        by_tse.setdefault(tse, set()).add(ibge)
        by_ibge.setdefault(ibge, set()).add(tse)
    many_ibge = sorted(t for t, v in by_tse.items() if len(v) > 1)
    many_tse = sorted(i for i, v in by_ibge.items() if len(v) > 1)
    if many_ibge or many_tse:
        raise BuildError(
            "the TSE-IBGE pairs are not one-to-one: "
            f"TSE codes with several IBGE codes {many_ibge[:10]}, "
            f"IBGE codes with several TSE codes {many_tse[:10]}"
        )


def check_in_dtb(pairs: list[tuple[str, str]], dtb: dict[str, str]) -> None:
    missing = sorted({i for _, i in pairs if i not in dtb})
    if missing:
        raise BuildError(
            f"{len(missing)} IBGE codes in the pairs are not in DTB 2024: {missing[:10]}"
        )


def check_tse_coverage(pairs: list[tuple[str, str]], tse_names: dict[str, str]) -> None:
    have = {t for t, _ in pairs}
    missing = sorted(set(tse_names) - have)
    if missing:
        raise BuildError(f"{len(missing)} TSE codes in the candidates have no pair: {missing[:10]}")


def check_legal_amazon(legal: dict[str, str], dtb: dict[str, str]) -> None:
    missing = sorted(set(legal) - set(dtb))
    if missing:
        raise BuildError(f"{len(missing)} Legal Amazon codes are not in DTB 2024: {missing[:10]}")
    wrong = sorted(c for c, uf in legal.items() if UF_BY_CODE.get(c[:2]) != uf)
    if wrong:
        raise BuildError(f"{len(wrong)} Legal Amazon codes disagree with their state: {wrong[:10]}")


def check_names(
    pairs: list[tuple[str, str]],
    dtb: dict[str, str],
    tse_names: dict[str, str],
    variants: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Name check of every pair: "exact", "variant" or "unchecked" (no TSE name).

    A mismatch that is not a listed variant with the same two codes raises.
    """
    result: dict[tuple[str, str], str] = {}
    bad: list[tuple[str, str]] = []
    for tse, ibge in pairs:
        tse_name = tse_names.get(tse, "")
        if not tse_name:
            result[(tse, ibge)] = "unchecked"
        elif normalise_name(tse_name) == normalise_name(dtb[ibge]):
            result[(tse, ibge)] = "exact"
        elif (tse, ibge) in variants:
            result[(tse, ibge)] = "variant"
        else:
            bad.append((tse, ibge))
    if bad:
        raise BuildError(
            f"{len(bad)} pairs fail the name check and are not listed variants: "
            + ", ".join(f"{t}/{i}" for t, i in bad[:10])
        )
    return result


# --- Table


def make_table(
    dtb: dict[str, str],
    legal: dict[str, str],
    pairs: list[tuple[str, str]],
    tse_names: dict[str, str],
    checks: dict[tuple[str, str], str],
) -> pl.DataFrame:
    tse_of = {ibge: tse for tse, ibge in pairs}
    rows = []
    for code in sorted(dtb):
        tse = tse_of.get(code)
        rows.append(
            {
                "cd_ibge": code,
                "cd_tse": tse,
                "uf": UF_BY_CODE[code[:2]],
                "name_ibge": dtb[code],
                "name_tse": (tse_names.get(tse) or None) if tse else None,
                "legal_amazon": code in legal,
                "name_check": checks[(tse, code)] if tse else None,
            }
        )
    schema = {
        "cd_ibge": pl.String,
        "cd_tse": pl.String,
        "uf": pl.String,
        "name_ibge": pl.String,
        "name_tse": pl.String,
        "legal_amazon": pl.Boolean,
        "name_check": pl.String,
    }
    return pl.DataFrame(rows, schema=schema)


def legal_amazon_csv(table: pl.DataFrame) -> bytes:
    """`code_ibge,uf` for the Legal Amazon rows, sorted, LF line endings."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["code_ibge", "uf"])
    for code, uf in table.filter(pl.col("legal_amazon")).select("cd_ibge", "uf").iter_rows():
        writer.writerow([code, uf])
    return buf.getvalue().encode("utf-8")


# --- Build


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


def input_hash(files: list[dict[str, Any]], variants_path: Path) -> str:
    code = Path(__file__).read_text(encoding="utf-8")
    shas = ",".join(f["sha256"] for f in files)
    return content_hash(shas, variants_path.read_text(encoding="utf-8"), code)


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def _dtb_ods(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if Path(n).match(DTB_MEMBER)]
        if len(names) != 1:
            raise BuildError(f"DTB zip: expected one {DTB_MEMBER} member, found {len(names)}")
        return zf.read(names[0])


def build(
    store: Store,
    ibge_manifest: dict[str, Any],
    hidalgo_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    variants_path: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the table into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    dtb_entry = _file(ibge_manifest, "DTB_2024.zip")
    legal_entry = _file(ibge_manifest, ".ods")
    hidalgo_entry = _file(hidalgo_manifest, HIDALGO_FILE)
    candidates_entry = _file(candidates_manifest, ".parquet")
    entries = [dtb_entry, legal_entry, hidalgo_entry, candidates_entry]

    prefix = f"{derived_root}{input_hash(entries, variants_path)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    dtb = read_dtb(_dtb_ods(_fetch(store, dtb_entry, tmp_dir)))
    legal = read_legal_amazon(_fetch(store, legal_entry, tmp_dir).read_bytes())
    pairs = read_pairs(_fetch(store, hidalgo_entry, tmp_dir))
    tse_names, non_municipal = read_tse_names(_fetch(store, candidates_entry, tmp_dir))
    variants = load_variants(variants_path)

    check_one_to_one(pairs)
    check_in_dtb(pairs, dtb)
    check_tse_coverage(pairs, tse_names)
    check_legal_amazon(legal, dtb)
    checks = check_names(pairs, dtb, tse_names, variants)

    table = make_table(dtb, legal, pairs, tse_names, checks)
    table_path = tmp_dir / TABLE_NAME
    table.write_parquet(table_path)
    legal_path = tmp_dir / LEGAL_AMAZON_NAME
    legal_path.write_bytes(legal_amazon_csv(table))
    store.create(prefix + TABLE_NAME, table_path)
    store.create(prefix + LEGAL_AMAZON_NAME, legal_path)

    counts = {k: list(checks.values()).count(k) for k in ("exact", "variant", "unchecked")}
    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=[
            {"path": prefix + name, "sha256": sha256_file(p), "bytes": p.stat().st_size}
            for name, p in ((TABLE_NAME, table_path), (LEGAL_AMAZON_NAME, legal_path))
        ],
        inputs=[m["gcs_prefix"] + MANIFEST_NAME for m in (ibge_manifest, hidalgo_manifest)]
        + [candidates_manifest["gcs_prefix"] + MANIFEST_NAME],
        notes=(
            f"municipalities={table.height}; legal_amazon={len(legal)}; "
            f"with_tse_code={table['cd_tse'].count()}; "
            f"name_check exact={counts['exact']}, variant={counts['variant']}, "
            f"unchecked={counts['unchecked']}; "
            f"non-municipal sg_ue values in candidates ignored={non_municipal}"
        ),
        code_commit=code_commit,
        created_at=created_at,
    )
