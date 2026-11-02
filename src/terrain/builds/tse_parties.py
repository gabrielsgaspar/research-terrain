"""Build party votes and coalition membership (2000-2024) from the raw TSE zips.

Contract of the output: data/contracts/tse_parties.md. Pitfalls of the source
files: data/fixtures/tse/README.md. The reading, typing and error helpers come
from `terrain.builds.tse_candidates`, which this module imports and never
changes. Errors and notes carry counts only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from terrain.builds import tse_candidates
from terrain.builds.tse_candidates import (
    BuildError,
    dtype_of,
    harmonise,
    read_header,
    read_year,
)
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "tse_parties"
MUNICIPALITIES_FILE = "municipalities.parquet"

VOTES = "votes"
COALITIONS = "coalitions"
OUTPUT_PREFIX = {VOTES: "party_votes", COALITIONS: "coalitions"}

# A party's votes in one zone, office and round, under one coalition record. A
# party can appear twice in a zone under two coalition records, so
# `sq_coligacao` is part of the key. These columns are never nulled.
VOTES_KEY = [
    "ano_eleicao",
    "cd_eleicao",
    "sg_ue",
    "nr_zona",
    "cd_cargo",
    "nr_turno",
    "nr_partido",
    "sq_coligacao",
]
# One party in one coalition (or federation) for one office.
COALITION_KEY = ["ano_eleicao", "cd_eleicao", "sg_ue", "cd_cargo", "sq_coligacao", "nr_partido"]
KEYS = {VOTES: VOTES_KEY, COALITIONS: COALITION_KEY}

_VOTES_ZIP = re.compile(r"votacao_partido_munzona_(\d{4})\.zip$")
_COALITION_ZIP = re.compile(r"consulta_coligacao_(\d{4})\.zip$")

# Every module whose code decides what this build writes. Its source is part
# of the output path, so a fix to any of them gives a new path.
CODE_MODULES = (Path(__file__), Path(tse_candidates.__file__))


@dataclass(frozen=True)
class Input:
    year: int
    kind: str
    path: str
    sha256: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def inputs_from_manifest(acquire_manifest: dict[str, Any]) -> list[Input]:
    """The party-vote and coalition zips listed in the acquire manifest."""
    found: list[Input] = []
    for f in acquire_manifest["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if m := _VOTES_ZIP.search(name):
            found.append(Input(int(m.group(1)), VOTES, f["path"], f["sha256"]))
        elif m := _COALITION_ZIP.search(name):
            found.append(Input(int(m.group(1)), COALITIONS, f["path"], f["sha256"]))
    if not found:
        raise BuildError("the acquire manifest lists no party-vote or coalition zips")
    by_year: dict[int, set[str]] = {}
    for i in found:
        by_year.setdefault(i.year, set()).add(i.kind)
    for year, kinds in sorted(by_year.items()):
        if kinds != {VOTES, COALITIONS}:
            raise BuildError(f"{year}: need both a party-vote and a coalition file")
    return sorted(found, key=lambda i: (i.kind, i.year))


def municipality_input(manifest: dict[str, Any]) -> dict[str, Any]:
    """The single `municipalities.parquet` entry of the municipalities manifest."""
    found = [f for f in manifest["files"] if f["path"].endswith("/" + MUNICIPALITIES_FILE)]
    if len(found) != 1:
        raise BuildError(f"expected one {MUNICIPALITIES_FILE} in the municipalities manifest")
    return found[0]


def column_dtype(column: str) -> pl.DataType | type[pl.DataType]:
    return pl.Int64 if column.startswith("qt_") else dtype_of(column)


def type_votes(df: pl.DataFrame) -> pl.DataFrame:
    """Cast the `qt_*` vote counts to Int64. A bad value stops the build."""
    counts = [c for c in df.columns if c.startswith("qt_")]
    try:
        return df.with_columns(pl.col(c).cast(pl.Int64) for c in counts)
    except pl.exceptions.PolarsError as err:
        raise BuildError("a vote count is not an integer") from err


def add_cd_ibge(df: pl.DataFrame, munis: pl.DataFrame) -> pl.DataFrame:
    """Add `cd_ibge` after `sg_ue`, joining `sg_ue` to `cd_tse`. Left join: no row is lost."""
    pairs = munis.filter(pl.col("cd_tse").is_not_null()).select("cd_tse", "cd_ibge")
    if pairs["cd_tse"].is_duplicated().any():
        raise BuildError("the municipalities table repeats a cd_tse")
    joined = df.join(pairs, left_on="sg_ue", right_on="cd_tse", how="left")
    if joined.height != df.height:
        raise BuildError("joining cd_ibge changed the row count")
    columns = [c for c in df.columns]
    columns.insert(columns.index("sg_ue") + 1, "cd_ibge")
    return joined.select(columns)


def check(df: pl.DataFrame, expected_rows: int, key: list[str], what: str) -> None:
    """Row count equals the BRASIL file's; the key is unique; every row has a `cd_ibge`."""
    if df.height != expected_rows:
        raise BuildError(f"{what}: {df.height} rows built, {expected_rows} in the source file")
    repeated = df.select(key).is_duplicated().sum()
    if repeated:
        raise BuildError(f"{what}: {repeated} rows repeat the key ({', '.join(key)})")
    missing = df["cd_ibge"].null_count()
    if missing:
        raise BuildError(f"{what}: {missing} rows have no cd_ibge")


def align(df: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Same columns in the same order for every year; null where a year lacks one."""
    return df.select(
        pl.col(c) if c in df.columns else pl.lit(None, dtype=column_dtype(c)).alias(c)
        for c in columns
    )


def input_hash(shas: list[str], code_modules: tuple[Path, ...] | list[Path] = CODE_MODULES) -> str:
    """Hash of the sorted input SHA-256s and the sorted source of every code module."""
    sources = sorted(Path(p).read_bytes().decode("utf-8") for p in code_modules)
    return content_hash(",".join(sorted(shas)), *sources)


def build(
    store: Store,
    acquire_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
    code_modules: tuple[Path, ...] | list[Path] = CODE_MODULES,
) -> dict[str, Any]:
    """Build the per-year tables into `<derived_root><hash>/`.

    Returns the manifest. The caller writes it (`terrain.manifest.write_manifest`)
    when `status` is `created`; when the output path already has a manifest,
    nothing is read or written and the status is `unchanged`.
    """
    inputs = inputs_from_manifest(acquire_manifest)
    muni_entry = municipality_input(municipalities_manifest)
    shas = [i.sha256 for i in inputs] + [muni_entry["sha256"]]
    prefix = f"{derived_root}{input_hash(shas, code_modules)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    muni_path = tmp_dir / MUNICIPALITIES_FILE
    store.download(muni_entry["path"], muni_path)
    if sha256_file(muni_path) != muni_entry["sha256"]:
        raise BuildError("municipalities.parquet does not match the sha256 in its manifest")
    munis = pl.read_parquet(muni_path, columns=["cd_ibge", "cd_tse"])

    local: dict[tuple[str, int], Path] = {}
    for i in inputs:
        target = tmp_dir / i.name
        store.download(i.path, target)
        if sha256_file(target) != i.sha256:
            raise BuildError(f"{i.name} does not match the sha256 in the acquire manifest")
        local[(i.kind, i.year)] = target

    years = sorted({y for _, y in local})
    columns: dict[str, list[str]] = {}
    for kind in (VOTES, COALITIONS):
        cols: list[str] = []
        for y in years:
            cols += [c for c in read_header(local[(kind, y)]) if c not in cols]
        cols.insert(cols.index("sg_ue") + 1, "cd_ibge")
        columns[kind] = cols

    files: list[dict[str, Any]] = []
    built: list[tuple[str, Path]] = []
    rows: dict[str, dict[int, int]] = {VOTES: {}, COALITIONS: {}}
    for kind in (VOTES, COALITIONS):
        key = KEYS[kind]
        for y in years:
            df, raw_rows = read_year(local[(kind, y)])
            df = type_votes(harmonise(df, key=key))
            df = add_cd_ibge(df, munis)
            check(df, raw_rows, key, f"{kind} {y}")
            rows[kind][y] = df.height
            name = f"{OUTPUT_PREFIX[kind]}_{y}.parquet"
            out = tmp_dir / name
            align(df, columns[kind]).write_parquet(out)
            del df
            built.append((name, out))

    # Upload only after every year and table has passed its checks, so a failed
    # run leaves no partial output in the bucket.
    for name, out in built:
        store.create(prefix + name, out)
        files.append(
            {"path": prefix + name, "sha256": sha256_file(out), "bytes": out.stat().st_size}
        )

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            acquire_manifest["gcs_prefix"] + MANIFEST_NAME,
            municipalities_manifest["gcs_prefix"] + MANIFEST_NAME,
        ],
        notes=(
            "party_votes rows per year: "
            + ", ".join(f"{y}={n}" for y, n in rows[VOTES].items())
            + "; coalitions rows per year: "
            + ", ".join(f"{y}={n}" for y, n in rows[COALITIONS].items())
        ),
        code_commit=code_commit,
        created_at=created_at,
    )
