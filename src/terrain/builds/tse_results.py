"""Build candidate votes and turnout (2000-2024) from the raw TSE zips.

Contract of the output: data/contracts/tse_results.md. Pitfalls of the source
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
    KEY as CANDIDACY_KEY,
)
from terrain.builds.tse_candidates import (
    BuildError,
    dtype_of,
    harmonise,
    read_header,
    read_year,
)
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "tse_results"
MUNICIPALITIES_FILE = "municipalities.parquet"
CANDIDATES_FILE = "candidates.parquet"

VOTES = "votes"
TURNOUT = "turnout"
OUTPUT_PREFIX = {VOTES: "candidate_votes", TURNOUT: "turnout"}

# One candidacy in one zone and round. These columns are never nulled.
VOTES_KEY = [*CANDIDACY_KEY, "nr_turno", "nr_zona"]
# One zone, office and round. These columns are never nulled.
TURNOUT_KEY = ["ano_eleicao", "cd_eleicao", "sg_ue", "nr_zona", "cd_cargo", "nr_turno"]
KEYS = {VOTES: VOTES_KEY, TURNOUT: TURNOUT_KEY}
# Protected from the missing-value rule: the key plus the office code.
PROTECTED = {VOTES: [*VOTES_KEY, "cd_cargo"], TURNOUT: TURNOUT_KEY}

# The unit of the consistency report: a municipality, office and round.
GROUP = ["ano_eleicao", "cd_eleicao", "sg_ue", "cd_cargo", "nr_turno"]
VALID = "qt_votos_nominais_validos"
NOMINAL = "qt_votos_nominais"

MAX_UNMATCHED_SHARE = 0.001

_VOTES_ZIP = re.compile(r"votacao_candidato_munzona_(\d{4})\.zip$")
_TURNOUT_ZIP = re.compile(r"detalhe_votacao_munzona_(\d{4})\.zip$")

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
    """The candidate-vote and turnout zips listed in the acquire manifest.

    Party-vote and coalition zips are ignored. Each year needs both kinds.
    """
    found: list[Input] = []
    for f in acquire_manifest["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if m := _VOTES_ZIP.search(name):
            found.append(Input(int(m.group(1)), VOTES, f["path"], f["sha256"]))
        elif m := _TURNOUT_ZIP.search(name):
            found.append(Input(int(m.group(1)), TURNOUT, f["path"], f["sha256"]))
    if not found:
        raise BuildError("the acquire manifest lists no candidate-vote or turnout zips")
    by_year: dict[int, set[str]] = {}
    for i in found:
        by_year.setdefault(i.year, set()).add(i.kind)
    for year, kinds in sorted(by_year.items()):
        if kinds != {VOTES, TURNOUT}:
            raise BuildError(f"{year}: need both a candidate-vote and a turnout file")
    return sorted(found, key=lambda i: (i.kind, i.year))


def manifest_file(manifest: dict[str, Any], filename: str) -> dict[str, Any]:
    """The single entry of `filename` in a build manifest."""
    found = [f for f in manifest["files"] if f["path"].endswith("/" + filename)]
    if len(found) != 1:
        raise BuildError(f"expected one {filename} in the manifest")
    return found[0]


def column_dtype(column: str) -> pl.DataType | type[pl.DataType]:
    if column == "matched":
        return pl.Boolean
    return pl.Int64 if column.startswith("qt_") else dtype_of(column)


def type_counts(df: pl.DataFrame) -> pl.DataFrame:
    """Cast the `qt_*` counts to Int64. A bad value stops the build."""
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
    columns = list(df.columns)
    columns.insert(columns.index("sg_ue") + 1, "cd_ibge")
    return joined.select(columns)


def add_matched(df: pl.DataFrame, candidates: pl.DataFrame) -> pl.DataFrame:
    """Add `matched`: whether the candidacy key is in the candidates table."""
    keys = candidates.select(CANDIDACY_KEY).unique().with_columns(pl.lit(True).alias("matched"))
    joined = df.join(keys, on=CANDIDACY_KEY, how="left")
    if joined.height != df.height:
        raise BuildError("joining the candidates table changed the row count")
    return joined.with_columns(pl.col("matched").fill_null(False))


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


def check_matched(df: pl.DataFrame, what: str, max_share: float = MAX_UNMATCHED_SHARE) -> int:
    """Raise if unmatched candidacies exceed `max_share` of the rows. Returns their count."""
    unmatched = int((~df["matched"]).sum())
    if df.height and unmatched / df.height > max_share:
        raise BuildError(f"{what}: {unmatched} of {df.height} rows match no candidacy")
    return unmatched


def _group_sums(df: pl.DataFrame, column: str, name: str) -> pl.DataFrame:
    return df.group_by(GROUP).agg(pl.col(column).sum().alias(name))


def consistency(votes: pl.DataFrame, turnout: pl.DataFrame) -> tuple[int, int]:
    """Compare candidates' valid votes with turnout's, per municipality-office-round.

    Returns (agree, total). Candidates' votes are `qt_votos_nominais_validos`,
    or `qt_votos_nominais` for a year whose file lacks the first. A group in only
    one of the two tables counts in `total` and not in `agree`.
    """
    column = VALID if votes[VALID].null_count() < votes.height else NOMINAL
    left = _group_sums(votes, column, "from_votes")
    right = _group_sums(turnout, VALID, "from_turnout")
    both = left.join(right, on=GROUP, how="full", coalesce=True)
    agree = both.filter(pl.col("from_votes") == pl.col("from_turnout")).height
    return agree, both.height


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


def _fetch(store: Store, path: str, sha256: str, target: Path, what: str) -> Path:
    store.download(path, target)
    if sha256_file(target) != sha256:
        raise BuildError(f"{what} does not match the sha256 in its manifest")
    return target


def build(
    store: Store,
    acquire_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    code_commit: str | None = None,
    created_at: str | None = None,
    max_unmatched_share: float = MAX_UNMATCHED_SHARE,
    code_modules: tuple[Path, ...] | list[Path] = CODE_MODULES,
) -> dict[str, Any]:
    """Build the per-year tables into `<derived_root><hash>/`.

    Returns the manifest. The caller writes it (`terrain.manifest.write_manifest`)
    when `status` is `created`; when the output path already has a manifest,
    nothing is read or written and the status is `unchanged`.
    """
    inputs = inputs_from_manifest(acquire_manifest)
    cand_entry = manifest_file(candidates_manifest, CANDIDATES_FILE)
    muni_entry = manifest_file(municipalities_manifest, MUNICIPALITIES_FILE)
    shas = [i.sha256 for i in inputs] + [cand_entry["sha256"], muni_entry["sha256"]]
    prefix = f"{derived_root}{input_hash(shas, code_modules)}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    muni_path = _fetch(
        store, muni_entry["path"], muni_entry["sha256"], tmp_dir / MUNICIPALITIES_FILE, "munis"
    )
    munis = pl.read_parquet(muni_path, columns=["cd_ibge", "cd_tse"])
    cand_path = _fetch(
        store, cand_entry["path"], cand_entry["sha256"], tmp_dir / CANDIDATES_FILE, "candidates"
    )
    candidates = pl.read_parquet(cand_path, columns=CANDIDACY_KEY)

    local: dict[tuple[str, int], Path] = {}
    for i in inputs:
        target = tmp_dir / i.name
        store.download(i.path, target)
        if sha256_file(target) != i.sha256:
            raise BuildError(f"{i.name} does not match the sha256 in the acquire manifest")
        local[(i.kind, i.year)] = target

    years = sorted({y for _, y in local})
    columns: dict[str, list[str]] = {}
    for kind in (VOTES, TURNOUT):
        cols: list[str] = []
        for y in years:
            cols += [c for c in read_header(local[(kind, y)]) if c not in cols]
        cols.insert(cols.index("sg_ue") + 1, "cd_ibge")
        columns[kind] = cols
    if VALID not in columns[VOTES]:
        columns[VOTES].append(VALID)
    columns[VOTES].append("matched")

    files: list[dict[str, Any]] = []
    rows: dict[str, dict[int, int]] = {VOTES: {}, TURNOUT: {}}
    unmatched: dict[int, int] = {}
    agreement: dict[int, tuple[int, int]] = {}
    for y in years:
        frames: dict[str, pl.DataFrame] = {}
        for kind in (VOTES, TURNOUT):
            df, raw_rows = read_year(local[(kind, y)])
            df = type_counts(harmonise(df, key=PROTECTED[kind]))
            df = add_cd_ibge(df, munis)
            if kind == VOTES:
                df = add_matched(df, candidates)
            check(df, raw_rows, KEYS[kind], f"{kind} {y}")
            if kind == VOTES:
                unmatched[y] = check_matched(df, f"{kind} {y}", max_unmatched_share)
            rows[kind][y] = df.height
            frames[kind] = df
        if VALID not in frames[VOTES].columns:
            frames[VOTES] = frames[VOTES].with_columns(pl.lit(None, dtype=pl.Int64).alias(VALID))
        agreement[y] = consistency(frames[VOTES], frames[TURNOUT])
        for kind in (VOTES, TURNOUT):
            name = f"{OUTPUT_PREFIX[kind]}_{y}.parquet"
            out = tmp_dir / name
            align(frames[kind], columns[kind]).write_parquet(out)
            store.create(prefix + name, out)
            files.append(
                {
                    "path": prefix + name,
                    "sha256": sha256_file(out),
                    "bytes": out.stat().st_size,
                }
            )
        del frames

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            acquire_manifest["gcs_prefix"] + MANIFEST_NAME,
            candidates_manifest["gcs_prefix"] + MANIFEST_NAME,
            municipalities_manifest["gcs_prefix"] + MANIFEST_NAME,
        ],
        notes=(
            "candidate_votes rows per year: "
            + ", ".join(f"{y}={n}" for y, n in rows[VOTES].items())
            + "; turnout rows per year: "
            + ", ".join(f"{y}={n}" for y, n in rows[TURNOUT].items())
            + "; unmatched candidacies per year: "
            + ", ".join(f"{y}={n}" for y, n in unmatched.items())
            + "; votes agree with turnout (municipality-office-rounds): "
            + ", ".join(f"{y}={a}/{t}" for y, (a, t) in agreement.items())
        ),
        code_commit=code_commit,
        created_at=created_at,
    )
