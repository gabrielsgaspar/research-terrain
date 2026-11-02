"""Build section votes of the Legal Amazon linked to candidacies, one Parquet per state-year.

Contract of the output: data/contracts/section_votes.md. Pitfalls of the source
files: data/fixtures/tse/README.md.

Section votes are votes cast; the results file counts votes counted. Votes for a
candidacy whose votes were annulled stay in the output, flagged
`annulled_in_results`: analyses of vote margins must use counted votes.

Memory: one state-year file is held at a time (Pará 2024 alone has 1.6 million
rows). Everything is written locally first and uploaded only when every check
has passed. Errors and notes carry counts only.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import polars as pl

from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash, sha256_file
from terrain.storage import Store

DATASET = "section_votes"
YEARS = (2004, 2008, 2012, 2016, 2020, 2024)
# 2000 has no polling-place IDs (-3) and covers 93 of 143 municipalities in Pará.
SKIPPED_YEARS = (2000,)
# The section files carry SQ_CANDIDATO from this year; before it, candidacies are
# found by matching the candidate number to the results.
FILE_SQ_FROM = 2024
# Share of candidates with votes in the results whose section sums must equal them.
MIN_AGREE_SHARE = 0.99
# Share of distinct candidate numbers that may be left without a candidacy.
MAX_UNMATCHED_SHARE = 0.005

MEMBER = "votacao_secao_*.csv"
VEREADOR = "13"
BLANK, NULL, ANNULLED = 95, 96, 97
MISSING_SQ = ("-1", "-3", "-4", "#NE", "#NE#", "#NULO", "#NULO#")

TEXT_KEYS = ["sg_ue", "nr_zona", "nr_secao", "cd_cargo"]
INT_KEYS = ["ano_eleicao", "cd_eleicao", "nr_turno"]
KEY = ["ano_eleicao", "cd_eleicao", "sg_ue", "nr_zona", "nr_secao", "cd_cargo", "nr_turno"]
KEY = [*KEY, "nr_votavel"]
# One candidacy in one round. Before 2012 `sq_candidato` repeats across municipalities.
CANDIDACY = ["cd_eleicao", "sg_ue", "cd_cargo", "nr_turno", "sq_candidato"]
# One candidate number in one municipality, office and round.
NUMBER = ["cd_eleicao", "sg_ue", "cd_cargo", "nr_turno", "nr_votavel"]
OUTPUT_COLUMNS = [
    *KEY,
    "cd_ibge",
    "nr_local_votacao",
    "qt_votos",
    "vote_type",
    "sq_candidato",
    "annulled_in_results",
]

_SECTION_ZIP = re.compile(r"votacao_secao_(\d{4})_([A-Z]{2})\.zip$")


class BuildError(ValueError):
    """Raised when an input or a check breaks the contract."""


def output_name(year: int, uf: str) -> str:
    return f"section_votes_{year}_{uf}.parquet"


# --- Reading


def _text(column: str) -> pl.Expr:
    stripped = pl.col(column).str.strip_chars()
    return pl.when(stripped == "").then(None).otherwise(stripped).alias(column)


def read_section_zip(zip_path: Path) -> pl.DataFrame:
    """The needed columns of one `votacao_secao_<year>_<uf>.zip`.

    Zone, section, municipality and office stay text, so leading zeros survive.
    Years, round, polling-place number, candidate number and votes are integers.
    A missing column, an empty key or a value that is not an integer stops the
    build. `sq_file` is the file's own `SQ_CANDIDATO` (null if absent or coded
    as missing).
    """
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if re.fullmatch(r"votacao_secao_.*\.csv", n.lower())]
        if len(members) != 1:
            raise BuildError(f"expected one {MEMBER} member, found {len(members)}")
        raw = zf.read(members[0]).decode("latin-1")
    df = pl.read_csv(io.BytesIO(raw.encode("utf-8")), separator=";", infer_schema=False)
    del raw
    df = df.rename({c: c.strip().lower() for c in df.columns})
    needed = [*TEXT_KEYS, *INT_KEYS, "nr_votavel", "nr_local_votacao", "qt_votos"]
    absent = [c for c in needed if c not in df.columns]
    if absent:
        raise BuildError(f"the section file lacks {len(absent)} needed columns")
    if "sq_candidato" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("sq_candidato"))
    df = df.select(_text(c) for c in [*needed, "sq_candidato"])
    try:
        df = df.with_columns(
            pl.col(c).cast(pl.Int32) for c in [*INT_KEYS, "nr_local_votacao"]
        ).with_columns(pl.col("nr_votavel").cast(pl.Int64), pl.col("qt_votos").cast(pl.Int64))
    except pl.exceptions.PolarsError as err:
        raise BuildError("a key, polling-place number or vote count is not an integer") from err
    empty = [c for c in needed if df[c].null_count()]
    if empty:
        raise BuildError(f"{len(empty)} needed columns have empty values")
    sq = pl.col("sq_candidato")
    return df.with_columns(
        pl.when(sq.is_in(list(MISSING_SQ))).then(None).otherwise(sq).alias("sq_file")
    ).drop("sq_candidato")


def read_candidacies(path: Path, sg_ue: list[str]) -> pl.DataFrame:
    """Votes counted per candidacy, summed over zones, for the given municipalities.

    One row per `CANDIDACY`, with `nr_candidato` and `nominal` (the sum of
    `qt_votos_nominais`).
    """
    df = pl.read_parquet(
        path,
        columns=[*CANDIDACY, "nr_candidato", "qt_votos_nominais"],
    ).filter(pl.col("sg_ue").is_in(sg_ue))
    return df.group_by(CANDIDACY).agg(
        pl.col("nr_candidato").cast(pl.Int64, strict=False).min(),
        pl.col("qt_votos_nominais").cast(pl.Int64).fill_null(0).sum().alias("nominal"),
    )


# --- Classify and link


def vote_type() -> pl.Expr:
    """95 blank, 96 null, 97 annulled; a two-digit councillor number is a party (legend).

    A two-digit mayoral number is a candidate: mayors run under their party number.
    """
    n = pl.col("nr_votavel")
    return (
        pl.when(n == BLANK)
        .then(pl.lit("blank"))
        .when(n == NULL)
        .then(pl.lit("null"))
        .when(n == ANNULLED)
        .then(pl.lit("annulled"))
        .when((pl.col("cd_cargo") == VEREADOR) & (n < 100))
        .then(pl.lit("legend"))
        .otherwise(pl.lit("candidate"))
        .alias("vote_type")
    )


def pick_candidacy(cand: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """One candidacy per candidate number: the one with the most counted votes.

    Ties go to the smallest `sq_candidato`. Also returns how many numbers have
    more than one candidacy with counted votes (the pick is then the largest).
    """
    number = ["cd_eleicao", "sg_ue", "cd_cargo", "nr_turno", "nr_candidato"]
    ranked = cand.filter(pl.col("nr_candidato").is_not_null()).sort(
        ["nominal", "sq_candidato"], descending=[True, False]
    )
    several = (
        ranked.filter(pl.col("nominal") > 0)
        .group_by(number)
        .agg(pl.len().alias("k"))
        .filter(pl.col("k") > 1)
        .height
    )
    pick = ranked.unique(subset=number, keep="first", maintain_order=True).select(
        *number[:-1], pl.col("nr_candidato").alias("nr_votavel"), pl.col("sq_candidato")
    )
    return pick, several


def link_candidates(
    df: pl.DataFrame, year: int, cand: pl.DataFrame, pick: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Add `sq_candidato` (candidate votes only), `nominal`, and `annulled_in_results`.

    Returns the rows and one row per candidacy with section votes (`sec_votes`)
    and counted votes (`nominal`, null when the candidacy is not in the results).
    """
    is_candidate = pl.col("vote_type") == "candidate"
    if year >= FILE_SQ_FROM:
        df = df.with_columns(pl.when(is_candidate).then(pl.col("sq_file")).alias("sq_candidato"))
    else:
        df = df.join(pick.rename({"sq_candidato": "sq_pick"}), on=NUMBER, how="left")
        df = df.with_columns(pl.when(is_candidate).then(pl.col("sq_pick")).alias("sq_candidato"))
        df = df.drop("sq_pick")
    df = df.drop("sq_file")
    counted = cand.select(*CANDIDACY, "nominal")
    sec = (
        df.filter(pl.col("sq_candidato").is_not_null())
        .group_by(CANDIDACY)
        .agg(pl.col("qt_votos").sum().alias("sec_votes"))
        .join(counted, on=CANDIDACY, how="left")
    )
    df = df.join(sec.select(*CANDIDACY, "sec_votes", "nominal"), on=CANDIDACY, how="left")
    flagged = ((pl.col("nominal") == 0) & (pl.col("sec_votes") > 0)).fill_null(False)
    df = df.with_columns(flagged.alias("annulled_in_results")).drop("sec_votes", "nominal")
    return df, sec


# --- Checks


def check_key(df: pl.DataFrame) -> None:
    repeated = df.select(KEY).is_duplicated().sum()
    if repeated:
        raise BuildError(f"{repeated} rows repeat the key {', '.join(KEY)}")


def check_agreement(year: int, agree: int, total: int, min_share: float) -> None:
    """Stop when too few candidates' section sums equal their counted votes."""
    if total == 0:
        raise BuildError(f"{year}: no candidates with counted votes to compare")
    if agree / total < min_share:
        raise BuildError(
            f"{year}: section sums equal the counted votes for {agree} of {total} "
            f"candidates (min share {min_share})"
        )


def check_unmatched(year: int, numbers: int, unmatched: int, max_share: float) -> None:
    """Stop when candidate numbers without a candidacy reach `max_share` of all numbers."""
    if numbers and unmatched / numbers >= max_share:
        raise BuildError(
            f"{year}: {unmatched} of {numbers} candidate numbers have no candidacy "
            f"(max share {max_share})"
        )


# --- One state-year


def process_file(
    raw: pl.DataFrame,
    year: int,
    cand: pl.DataFrame,
    pick: pl.DataFrame,
    legal: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int]]:
    """Classify, link and check one state-year; return rows, candidacy sums and counts.

    `legal` has `cd_ibge` and `sg_ue` of the Legal Amazon municipalities.
    """
    other_year = raw.filter(pl.col("ano_eleicao") != year).height
    df = raw.filter(pl.col("ano_eleicao") == year)
    inside = df.join(legal, on="sg_ue", how="inner")
    outside = df.height - inside.height
    df = inside.with_columns(vote_type())
    numbers = df.filter(pl.col("vote_type") == "candidate").select(NUMBER).unique().height
    df, sec = link_candidates(df, year, cand, pick)
    unmatched = (
        df.filter((pl.col("vote_type") == "candidate") & pl.col("sq_candidato").is_null())
        .select(NUMBER)
        .unique()
        .height
    )
    df = df.select(OUTPUT_COLUMNS).sort(KEY)
    check_key(df)
    stats = {
        "rows": df.height,
        "other_year": other_year,
        "outside": outside,
        "numbers": numbers,
        "unmatched": unmatched,
        "annulled": sec.filter((pl.col("nominal") == 0) & (pl.col("sec_votes") > 0)).height,
    }
    return df, sec.select(*CANDIDACY, "sec_votes"), stats


# --- Build

# Every module whose code decides what this build writes. Its source is part of
# the output path. This build imports no other data-handling terrain module.
CODE_MODULES = (Path(__file__),)


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]], years: tuple[int, ...], code: list[str] | None = None
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    return content_hash(shas, ",".join(str(y) for y in sorted(years)), *sources)


def _file(manifest: dict[str, Any], suffix: str) -> dict[str, Any]:
    found = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(found) != 1:
        raise BuildError(f"{manifest.get('dataset')}: expected one file ending {suffix}")
    return found[0]


def section_entries(manifest: dict[str, Any]) -> dict[int, dict[str, dict[str, Any]]]:
    """The section zips of the acquire manifest, by year and state."""
    found: dict[int, dict[str, dict[str, Any]]] = {}
    for f in manifest["files"]:
        if m := _SECTION_ZIP.search(f["path"]):
            found.setdefault(int(m.group(1)), {})[m.group(2)] = f
    if not found:
        raise BuildError("the acquire manifest lists no section zips")
    return found


def _fetch(store: Store, entry: dict[str, Any], tmp_dir: Path) -> Path:
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise BuildError(f"{target.name} does not match the sha256 in its manifest")
    return target


def _note(year: int, s: dict[str, int]) -> str:
    return (
        f"{year}: rows={s['rows']}, section_sums_equal_results={s['agree']}/{s['total']} "
        f"({s['agree'] / s['total']:.4f}), annulled_in_results_candidacies={s['annulled']}, "
        f"unmatched_candidate_numbers={s['unmatched']}/{s['numbers']}, "
        f"numbers_with_several_voted_candidacies={s['several']}, "
        f"rows_outside_legal_amazon={s['outside']}, other_election_year_rows={s['other_year']}"
    )


def build(
    store: Store,
    sections_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    *,
    derived_root: str,
    tmp_dir: Path,
    years: tuple[int, ...] = YEARS,
    min_agree_share: float = MIN_AGREE_SHARE,
    max_unmatched_share: float = MAX_UNMATCHED_SHARE,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one Parquet per state and year into `<derived_root><hash>/`; return the manifest.

    The caller writes the manifest (`terrain.manifest.write_manifest`) when `status`
    is `created`. When the output path already has a manifest, nothing is read or
    written and the status is `unchanged`.
    """
    by_year = section_entries(sections_manifest)
    todo = sorted(y for y in by_year if y in years and y not in SKIPPED_YEARS)
    skipped = sorted(y for y in by_year if y in SKIPPED_YEARS)
    if not todo:
        raise BuildError("no section zips for the requested years")
    cand_entries = {y: _file(results_manifest, f"candidate_votes_{y}.parquet") for y in todo}
    mun_entry = _file(municipalities_manifest, ".parquet")
    entries = [
        mun_entry,
        *cand_entries.values(),
        *(e for y in todo for e in by_year[y].values()),
    ]

    prefix = f"{derived_root}{input_hash(entries, tuple(todo))}/"
    if store.exists(prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    municipalities = pl.read_parquet(
        _fetch(store, mun_entry, tmp_dir), columns=["cd_ibge", "cd_tse", "legal_amazon"]
    )
    legal = municipalities.filter(pl.col("legal_amazon") & pl.col("cd_tse").is_not_null()).select(
        "cd_ibge", pl.col("cd_tse").alias("sg_ue")
    )
    if legal["sg_ue"].is_duplicated().any():
        raise BuildError("the municipalities table repeats a cd_tse")

    # Every state-year is built and checked locally first; nothing reaches the
    # store unless all of them pass, so a failed run leaves no partial output.
    local: list[tuple[str, Path]] = []
    notes = [f"{y}: skipped, the section files have no polling-place IDs" for y in skipped]
    for y in todo:
        cand_path = _fetch(store, cand_entries[y], tmp_dir)
        cand = read_candidacies(cand_path, legal["sg_ue"].to_list())
        cand_path.unlink()
        pick, several = pick_candidacy(cand)
        parts: list[pl.DataFrame] = []
        totals = {"rows": 0, "other_year": 0, "outside": 0, "numbers": 0, "unmatched": 0}
        totals["annulled"] = 0
        for uf in sorted(by_year[y]):
            zip_path = _fetch(store, by_year[y][uf], tmp_dir)
            raw = read_section_zip(zip_path)
            zip_path.unlink()
            df, sec, stats = process_file(raw, y, cand, pick, legal)
            del raw
            for k, v in stats.items():
                totals[k] += v
            parts.append(sec)
            path = tmp_dir / output_name(y, uf)
            df.write_parquet(path)
            del df
            local.append((output_name(y, uf), path))
        check_unmatched(y, totals["numbers"], totals["unmatched"], max_unmatched_share)
        sums = pl.concat(parts)
        results = cand.filter(pl.col("nominal") > 0).join(
            sums.select(*CANDIDACY, "sec_votes"), on=CANDIDACY, how="left"
        )
        agree = results.filter(pl.col("sec_votes") == pl.col("nominal")).height
        check_agreement(y, agree, results.height, min_agree_share)
        notes.append(
            _note(y, {**totals, "agree": agree, "total": results.height, "several": several})
        )

    files: list[dict[str, Any]] = []
    for name, path in local:
        store.create(prefix + name, path)
        files.append(
            {"path": prefix + name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        )

    return build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (sections_manifest, results_manifest, municipalities_manifest)
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
