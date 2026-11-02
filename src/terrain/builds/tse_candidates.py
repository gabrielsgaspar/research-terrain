"""Build the candidates table (one row per candidacy, 2000-2024) from the raw TSE zips.

Contract of the output: data/contracts/tse_candidates.md. Pitfalls of the source
files: data/fixtures/tse/README.md. Nothing here logs or prints names, CPF,
voter-ID numbers or e-mails: errors and notes carry counts only.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "tse_candidates"
OUTPUT_NAME = "candidates.parquet"
MEMBER_GLOB = "*_BRASIL.csv"

# TSE codes for "no value". Also the empty string, which the files use for
# fields that were never filled in.
MISSING = ["#NE", "#NE#", "#NULO", "#NULO#", "-1", "-3", "-4", "NÃO DIVULGÁVEL", ""]

# A candidacy. These columns are never nulled by the missing-value rule.
KEY = ["ano_eleicao", "cd_eleicao", "sg_ue", "sq_candidato"]
COMPLEMENTAR_KEY = ["ano_eleicao", "cd_eleicao", "sq_candidato"]
COMPLEMENTAR_COLUMNS = ["cd_etnia_indigena", "ds_etnia_indigena", "st_quilombola"]

INT_COLUMNS = {"ano_eleicao", "cd_tipo_eleicao", "nr_turno", "cd_eleicao"}
DATE_COLUMNS = {"dt_eleicao", "dt_nascimento"}
STRICT_DATE_COLUMNS = {"dt_eleicao"}  # a bad value stops the build
DATE_FORMAT = "%d/%m/%Y"

# Birth dates: a bad value becomes null (original text kept in dt_nascimento_raw).
BIRTH_MIN = date(1900, 1, 1)
MIN_AGE_YEARS = 18
MAX_BAD_BIRTH_SHARE = 0.001

_CAND_ZIP = re.compile(r"consulta_cand_(\d{4})\.zip$")
_COMP_ZIP = re.compile(r"consulta_cand_complementar_(\d{4})\.zip$")


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


@dataclass(frozen=True)
class Input:
    year: int
    complementar: bool
    path: str
    sha256: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def dtype_of(column: str) -> pl.DataType | type[pl.DataType]:
    if column in INT_COLUMNS:
        return pl.Int32
    if column in DATE_COLUMNS:
        return pl.Date
    return pl.String


def snake(name: str) -> str:
    name = name.strip().lower()
    return "email" if name in ("nm_email", "ds_email") else name


def inputs_from_manifest(acquire_manifest: dict[str, Any]) -> list[Input]:
    """The candidate and complementary zips listed in the acquire manifest."""
    found: list[Input] = []
    for f in acquire_manifest["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if m := _COMP_ZIP.search(name):
            found.append(Input(int(m.group(1)), True, f["path"], f["sha256"]))
        elif m := _CAND_ZIP.search(name):
            found.append(Input(int(m.group(1)), False, f["path"], f["sha256"]))
    if not any(not i.complementar for i in found):
        raise BuildError("the acquire manifest lists no candidate zips")
    years = {i.year for i in found if not i.complementar}
    for i in found:
        if i.complementar and i.year not in years:
            raise BuildError(f"complementary file for {i.year} has no candidate file")
    return sorted(found, key=lambda i: (i.complementar, i.year))


def _brasil_member(zf: zipfile.ZipFile) -> str:
    members = [n for n in zf.namelist() if fnmatch.fnmatch(n.lower(), MEMBER_GLOB.lower())]
    if len(members) != 1:
        raise BuildError(f"expected one {MEMBER_GLOB} member, found {len(members)}")
    return members[0]


def read_header(zip_path: Path) -> list[str]:
    """Snake-case column names of the BRASIL file, read from its first line only."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(_brasil_member(zf)) as fh:
        line = fh.readline().decode("latin-1")
    return [snake(c) for c in next(csv.reader([line], delimiter=";"))]


def read_year(zip_path: Path) -> tuple[pl.DataFrame, int]:
    """Read the BRASIL file of one zip, every column as text.

    Returns the frame and an independent count of its records. The state files
    in the same zip repeat the BRASIL rows and are never opened.
    """
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(_brasil_member(zf)).decode("latin-1")
    records = sum(1 for _ in csv.reader(io.StringIO(raw, newline=""), delimiter=";"))
    df = pl.read_csv(
        io.BytesIO(raw.encode("utf-8")),
        separator=";",
        infer_schema=False,
    )
    return df, records - 1


def harmonise(df: pl.DataFrame, key: list[str] = KEY) -> pl.DataFrame:
    """Snake_case names, missing codes to null, integers and `dt_eleicao` typed.

    `dt_nascimento` stays text here; see `type_birth_dates`.
    `key` columns must exist and are never nulled.
    """
    df = df.rename({c: snake(c) for c in df.columns})
    missing = [c for c in key if c not in df.columns]
    if missing:
        raise BuildError(f"missing key columns: {missing}")
    text = [c for c in df.columns if c not in key]
    df = df.with_columns(
        pl.when(pl.col(c).is_in(MISSING)).then(None).otherwise(pl.col(c)).alias(c) for c in text
    )
    typed = []
    for c in df.columns:
        if c in INT_COLUMNS:
            typed.append(pl.col(c).cast(pl.Int32))
        elif c in STRICT_DATE_COLUMNS:
            typed.append(pl.col(c).str.to_date(DATE_FORMAT, strict=True))
    return df.with_columns(typed)


def type_birth_dates(df: pl.DataFrame) -> tuple[pl.DataFrame, int, int]:
    """Type `dt_nascimento` leniently; keep the original text in `dt_nascimento_raw`.

    Spaces are removed and parsing is non-strict. A value that does not parse, or
    that falls before BIRTH_MIN or under MIN_AGE_YEARS before `dt_eleicao`, becomes
    null. Returns the frame, the number of unparseable and of implausible values.
    """
    if "dt_nascimento" not in df.columns:
        return df, 0, 0
    parsed = (
        pl.col("dt_nascimento")
        .str.replace_all(" ", "", literal=True)
        .str.to_date(DATE_FORMAT, strict=False)
    )
    df = df.with_columns(pl.col("dt_nascimento").alias("dt_nascimento_raw"))
    df = df.with_columns(parsed.alias("dt_nascimento"))
    unparseable = df.filter(
        pl.col("dt_nascimento_raw").is_not_null() & pl.col("dt_nascimento").is_null()
    ).height
    implausible_mask = pl.col("dt_nascimento").is_not_null() & (
        (pl.col("dt_nascimento") < BIRTH_MIN)
        | (pl.col("dt_nascimento") > pl.col("dt_eleicao").dt.offset_by(f"-{MIN_AGE_YEARS}y"))
    )
    implausible = df.filter(implausible_mask).height
    df = df.with_columns(
        pl.when(implausible_mask)
        .then(None)
        .otherwise(pl.col("dt_nascimento"))
        .alias("dt_nascimento")
    )
    return df, unparseable, implausible


def check_birth_dates(
    year: int, rows: int, unparseable: int, implausible: int, max_share: float
) -> None:
    """Raise if more than `max_share` of a year's birth dates are unusable. Counts only."""
    for label, n in (("unparseable", unparseable), ("implausible", implausible)):
        if rows and n / rows > max_share:
            raise BuildError(f"{year}: {n} of {rows} birth dates {label} (max share {max_share})")


def join_complementar(df: pl.DataFrame, comp: pl.DataFrame) -> pl.DataFrame:
    """Add the ethnicity and quilombola columns. Every complementary row must join."""
    absent = [c for c in COMPLEMENTAR_KEY + COMPLEMENTAR_COLUMNS if c not in comp.columns]
    if absent:
        raise BuildError(f"complementary file lacks columns: {absent}")
    comp = comp.select(COMPLEMENTAR_KEY + COMPLEMENTAR_COLUMNS)
    if comp.select(COMPLEMENTAR_KEY).is_duplicated().any():
        raise BuildError("complementary file repeats a (ano_eleicao, cd_eleicao, sq_candidato)")
    orphans = comp.join(df.select(COMPLEMENTAR_KEY), on=COMPLEMENTAR_KEY, how="anti").height
    if orphans:
        raise BuildError(f"{orphans} complementary rows match no candidacy")
    joined = df.join(comp, on=COMPLEMENTAR_KEY, how="left")
    if joined.height != df.height:
        raise BuildError("joining the complementary file changed the row count")
    return joined


def check(df: pl.DataFrame, expected_rows: int) -> None:
    """Row count equals the BRASIL file's; the candidacy key is unique."""
    if df.height != expected_rows:
        raise BuildError(f"{df.height} rows built, {expected_rows} in the source file")
    repeated = df.select(KEY).is_duplicated().sum()
    if repeated:
        raise BuildError(f"{repeated} rows repeat (ano_eleicao, cd_eleicao, sg_ue, sq_candidato)")


def align(df: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Same columns in the same order for every year; null where a year lacks one."""
    return df.select(
        pl.col(c) if c in df.columns else pl.lit(None, dtype=dtype_of(c)).alias(c) for c in columns
    )


def input_hash(inputs: list[Input]) -> str:
    code = Path(__file__).read_bytes()
    return content_hash(",".join(sorted(i.sha256 for i in inputs)), code.decode("utf-8"))


def build(
    store: Store,
    acquire_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
    max_bad_birth_share: float = MAX_BAD_BIRTH_SHARE,
) -> dict[str, Any]:
    """Build the table into `<derived_root><hash>/candidates.parquet`.

    Returns the manifest. The caller writes it (`terrain.manifest.write_manifest`)
    when `status` is `created`; when the output path already has a manifest,
    nothing is read or written and the status is `unchanged`.
    """
    inputs = inputs_from_manifest(acquire_manifest)
    prefix = f"{derived_root}{input_hash(inputs)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    local: dict[tuple[bool, int], Path] = {}
    for i in inputs:
        target = tmp_dir / i.name
        store.download(i.path, target)
        if sha256_file(target) != i.sha256:
            raise BuildError(f"{i.name} does not match the sha256 in the acquire manifest")
        local[(i.complementar, i.year)] = target

    years = sorted(y for c, y in local if not c)
    columns: list[str] = []
    for y in years:
        columns += [c for c in read_header(local[(False, y)]) if c not in columns]
    if "dt_nascimento" in columns:
        columns.insert(columns.index("dt_nascimento") + 1, "dt_nascimento_raw")
    columns += [c for c in COMPLEMENTAR_COLUMNS if c not in columns]

    parts: list[Path] = []
    rows: dict[int, int] = {}
    bad_birth: dict[int, tuple[int, int]] = {}
    for y in years:
        df, raw_rows = read_year(local[(False, y)])
        df = harmonise(df)
        df, unparseable, implausible = type_birth_dates(df)
        check_birth_dates(y, df.height, unparseable, implausible, max_bad_birth_share)
        bad_birth[y] = (unparseable, implausible)
        if (True, y) in local:
            comp, _ = read_year(local[(True, y)])
            df = join_complementar(df, harmonise(comp, COMPLEMENTAR_KEY))
        check(df, raw_rows)
        rows[y] = df.height
        part = tmp_dir / f"part_{y}.parquet"
        align(df, columns).write_parquet(part)
        parts.append(part)
        del df

    out = tmp_dir / OUTPUT_NAME
    pl.concat([pl.scan_parquet(p) for p in parts]).sink_parquet(out)
    store.create(prefix + OUTPUT_NAME, out)

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=[
            {
                "path": prefix + OUTPUT_NAME,
                "sha256": sha256_file(out),
                "bytes": out.stat().st_size,
            }
        ],
        inputs=[acquire_manifest["gcs_prefix"] + MANIFEST_NAME],
        notes=(
            "rows per year: "
            + ", ".join(f"{y}={n}" for y, n in rows.items())
            + "; birth dates unparseable: "
            + ", ".join(f"{y}={u}" for y, (u, _) in bad_birth.items())
            + "; implausible: "
            + ", ".join(f"{y}={i}" for y, (_, i) in bad_birth.items())
        ),
        code_commit=code_commit,
        created_at=created_at,
    )
