"""Deputy x municipality x cycle panel of individual amendments and votes (idea 0009).

Contract of the output: data/contracts/amendments_panel.md. Campaign 0009 step s4; decisions
0003 and 0011. The models are `terrain.builds.politics_panel` (the derived/sealed split and
in-memory CPF linking) and `explore/0003_mayor_power.py` (mayoral races; copied here, never
imported).

One row per cycle, federal deputy (the TSE `sq_candidato` of the t0 candidacy) and
municipality of the deputy's state in which the deputy's party had one of the two finalists of
the mayoral election. Rows of exploration-half municipalities (both exploration lists) go to
the derived folder; every other row goes to a sealed folder that this build only creates in
and never reads. `author_link.parquet` (counts only) goes to the derived folder.

Names and CPFs are used only in memory, to link CGU authors to candidacies and a deputy's t0
candidacy to t1. No CPF, voter ID, name or favorecido code, and no hash of one, is written to a
column, a note or an exception message. `Código do Favorecido` and `Favorecido` are never read.
"""

from __future__ import annotations

import csv
import json
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from terrain import explore as terrain_explore
from terrain.builds import cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "amendments_panel"
MAYOR = 11
DEPUTY = 6
SENATOR = 5
ELECTED_CODES = (1, 2, 3)
FEMALE = "4"
HIGHER_ED = "8"
CPF_PATTERN = r"^\d{11}$"
MAX_UNMATCHED_RECIPIENTS = 0.02  # share of the named recipient rows, per year
PLACEHOLDER_NAME = "SEM INFORMACAO"  # CGU's unidentified recipient, normalised
PLACEHOLDER_UFS = ("", "-1")  # stripped `UF Favorecido` values that go with it
TOP_UNMATCHED = 10  # unmatched (UF, municipality name) pairs in the notes, per year
MIN_ROWS = 5000  # per cycle
MAX_ROWS = 300_000
FIRST_MONTH = 201501  # the earliest payment month may not be later
LAST_MONTH = 202609  # the latest payment month may not be earlier
PIX_FROM = 202001  # individual Pix payments must exist from this month on
TOLERANCE = 1e-9
CHUNK_BYTES = 1 << 24


class Cycle(NamedTuple):
    m: int  # mayoral election
    t0: int  # base general election
    t1: int  # next general election
    pre: tuple[int, int]  # first and last payment month (YYYYMM), inclusive
    post: tuple[int, int]


CYCLES: dict[str, Cycle] = {
    "A": Cycle(2016, 2014, 2018, (201501, 201609), (201701, 201809)),
    "B": Cycle(2020, 2018, 2022, (201901, 202009), (202101, 202209)),
    "C": Cycle(2024, 2022, 2026, (202301, 202409), (202501, 202609)),
}

CGU_MEMBER = "emendasparlamentares_porfavorecido.csv"
CGU_COLUMNS = {
    "type": "Tipo de Emenda",
    "code": "Código do Autor da Emenda",
    "author": "Nome do Autor da Emenda",
    "ym": "Ano/Mês",
    "uf": "UF Favorecido",
    "muni": "Município Favorecido",
    "value": "Valor Recebido",
}
VOTES_COLUMNS = (
    "cd_cargo",
    "nr_turno",
    "cd_eleicao",
    "sg_ue",
    "sq_candidato",
    "nr_zona",
    "qt_votos_nominais",
    "qt_votos_nominais_validos",
    "nm_tipo_destinacao_votos",
    "cd_ibge",
)
TURNOUT_COLUMNS = ("cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "qt_total_votos_validos")
CANDIDATE_COLUMNS = (
    "ano_eleicao",
    "cd_eleicao",
    "sg_ue",
    "sq_candidato",
    "nr_partido",
    "cd_genero",
    "dt_nascimento",
    "cd_grau_instrucao",
    "dt_eleicao",
)
POPULATION_COLUMNS = ("ano", "id_municipio", "populacao")
MUNICIPALITY_COLUMNS = ("cd_ibge", "cd_tse", "uf", "name_ibge")

SCHEMA: dict[str, Any] = {
    "cycle": pl.Utf8,
    "m": pl.Int64,
    "t0": pl.Int64,
    "t1": pl.Int64,
    "cd_ibge": pl.Utf8,
    "uf": pl.Utf8,
    "deputy": pl.Utf8,
    "deputy_party": pl.Utf8,
    "deputy_elected": pl.Boolean,
    "population_m": pl.Int64,
    "round": pl.Int64,
    "n_mayor_cands": pl.Int64,
    "margin": pl.Float64,
    "win": pl.Boolean,
    "fin_female": pl.Boolean,
    "fin_age": pl.Int64,
    "fin_higher_ed": pl.Boolean,
    "party_held_mayor": pl.Boolean,
    "amend_pre_total": pl.Float64,
    "amend_pre_pix": pl.Float64,
    "n_pay_pre": pl.Int64,
    "amend_post_total": pl.Float64,
    "amend_post_pix": pl.Float64,
    "n_pay_post": pl.Int64,
    "votes_t0": pl.Int64,
    "valid_t0": pl.Int64,
    "share_t0": pl.Float64,
    "ran_t1": pl.Boolean,
    "votes_t1": pl.Int64,
    "valid_t1": pl.Int64,
    "share_t1": pl.Float64,
    "d_share": pl.Float64,
}
LINK_SCHEMA: dict[str, Any] = {
    "cycle": pl.Utf8,
    "authors": pl.Int64,
    "deputies": pl.Int64,
    "senators": pl.Int64,
    "ambiguous": pl.Int64,
    "unmatched": pl.Int64,
}
SHARES = ("share_t0", "share_t1")
PAYMENTS = ("amend_pre_total", "amend_pre_pix", "amend_post_total", "amend_post_pix")

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, `explore` (the exploration lists), `place_outcomes` (`read_lists`),
# `cell_outcomes` (the list parser and the upload) and `polling_place_tenure` (`_file` picks
# the inputs, `_fetch` checks their SHA-256).
CODE_MODULES = (
    Path(__file__),
    Path(terrain_explore.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def panel_name(cycle: str) -> str:
    return f"panel_{cycle}.parquet"


LINK_NAME = "author_link.parquet"


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_shas: list[str],
    cycles: tuple[str, ...] = tuple(CYCLES),
    code: list[str] | None = None,
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    spec = ",".join(f"{c}={tuple(CYCLES[c])}" for c in sorted(cycles))
    return content_hash(shas, ",".join(split_shas), spec, *sources)


# --- Text


def normalise_name(text: str | None) -> str:
    """Upper case, no accents, letters and spaces only, single spaces."""
    if text is None:
        return ""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    kept = "".join(c for c in plain.upper() if c.isalpha() or c.isspace())
    return " ".join(kept.split())


normalise_type = normalise_name


def is_individual(normalised_type: str) -> bool:
    return normalised_type.startswith("EMENDA INDIVIDUAL")


def is_pix(normalised_type: str) -> bool:
    return "TRANSFERENCIAS ESPECIAIS" in normalised_type


def with_norm(frame: pl.DataFrame, column: str, name: str) -> pl.DataFrame:
    """Add `name`: the normalised text of `column` ("" where null). Normalises each value once."""
    lookup = (
        frame.select(pl.col(column).unique())
        .drop_nulls()
        .with_columns(pl.col(column).map_elements(normalise_name, return_dtype=pl.Utf8).alias(name))
    )
    return frame.join(lookup, on=column, how="left").with_columns(pl.col(name).fill_null(""))


# --- CGU payments


def _month_parts(text: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    year = pl.coalesce(
        text.str.extract(r"^(\d{4})/\d{1,2}$", 1),
        text.str.extract(r"^\d{1,2}/(\d{4})$", 1),
        text.str.extract(r"^(\d{4})\d{2}$", 1),
    )
    month = pl.coalesce(
        text.str.extract(r"^\d{4}/(\d{1,2})$", 1),
        text.str.extract(r"^(\d{1,2})/\d{4}$", 1),
        text.str.extract(r"^\d{4}(\d{2})$", 1),
    )
    return year.cast(pl.Int64, strict=False), month.cast(pl.Int64, strict=False)


def read_cgu(zip_path: Path) -> pl.DataFrame:
    """The columns the build needs of `EmendasParlamentares_PorFavorecido.csv`, as text.

    Tries UTF-8 and then Latin-1; the first encoding whose header holds every needed column
    wins. `Código do Favorecido` and `Favorecido` are not selected. Stops if the member is
    missing or no encoding gives the header.
    """
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower() == CGU_MEMBER]
        if len(members) != 1:
            raise BuildError(f"expected one {CGU_MEMBER} member, found {len(members)}")
        data = zf.read(members[0])
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        header = next(csv.reader([text.split("\n", 1)[0].rstrip("\r")], delimiter=";"))
        raw = {h.strip(): h for h in header}
        if any(name not in raw for name in CGU_COLUMNS.values()):
            continue
        frame = pl.read_csv(
            text.encode("utf-8"),
            separator=";",
            quote_char='"',
            infer_schema=False,
            columns=[raw[name] for name in CGU_COLUMNS.values()],
        )
        return frame.rename({raw[name]: key for key, name in CGU_COLUMNS.items()})
    raise BuildError("no encoding (UTF-8, Latin-1) gives the expected CGU header")


def parse_payments(raw: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Add `ym` (YYYYMM), `type_norm` and `value` to the CGU rows; return the rows and stats.

    `Ano/Mês` is accepted as YYYY/MM, MM/YYYY or YYYYMM; a row with an empty value is dropped
    and counted, one with any other text stops the build. `value` is read only for individual
    amendments (Brazilian decimals: `1.234,56`). Stats: first and last month of the file,
    rows without a month, and the individual Pix rows from `PIX_FROM` on.
    """
    text = pl.col("ym").str.strip_chars()
    year, month = _month_parts(text)
    ym = (year * 100 + month).alias("ym_int")
    frame = raw.with_columns(
        ym, (text.is_null() | (text == "")).alias("no_month"), (month.is_between(1, 12)).alias("ok")
    )
    bad = frame.filter(~pl.col("no_month") & ~pl.col("ok").fill_null(False)).height
    if bad:
        raise BuildError(f"{bad} rows have an Ano/Mês in no accepted format")
    no_month = int(frame["no_month"].sum())
    frame = frame.filter(~pl.col("no_month")).drop("ym", "ok", "no_month").rename({"ym_int": "ym"})
    frame = with_norm(frame, "type", "type_norm")
    is_ind = pl.col("type_norm").str.starts_with("EMENDA INDIVIDUAL")
    is_pix = pl.col("type_norm").str.contains("TRANSFERENCIAS ESPECIAIS", literal=True)
    frame = frame.with_columns(is_ind.alias("individual"), (is_ind & is_pix).alias("pix"))
    stats = {
        "first": int(frame["ym"].min()) if frame.height else None,
        "last": int(frame["ym"].max()) if frame.height else None,
        "no_month": no_month,
        "pix_from": frame.filter(pl.col("pix") & (pl.col("ym") >= PIX_FROM)).height,
    }
    individual = frame.filter(pl.col("individual"))
    cleaned = (
        pl.col("value")
        .str.strip_chars()
        .str.replace_all(r"R\$|\s", "")
        .str.replace_all(r"\.", "")
        .str.replace(",", ".", literal=True)
    )
    value = cleaned.cast(pl.Float64, strict=False)
    unreadable = individual.filter(cleaned.str.len_chars() > 0).filter(value.is_null()).height
    if unreadable:
        raise BuildError(f"{unreadable} rows have a Valor Recebido that is not a number")
    individual = individual.with_columns(value.fill_null(0.0).alias("value"))
    return individual, stats


def check_payment_stats(stats: dict[str, Any]) -> None:
    """The payment-month range and the Pix check. Messages carry counts and months only."""
    if stats["first"] is None:
        raise BuildError("the CGU file has no payment month")
    if stats["first"] > FIRST_MONTH:
        raise BuildError(f"the earliest payment month is {stats['first']}, after {FIRST_MONTH}")
    if stats["last"] < LAST_MONTH:
        raise BuildError(f"the latest payment month is {stats['last']}, before {LAST_MONTH}")
    if stats["pix_from"] == 0:
        raise BuildError(f"no individual Pix payment from {PIX_FROM} on")


def in_windows(cycles: tuple[str, ...]) -> pl.Expr:
    """True for a payment month inside the pre or post window of any cycle in `cycles`."""
    parts = [pl.col("ym").is_between(*w) for c in cycles for w in (CYCLES[c].pre, CYCLES[c].post)]
    return pl.any_horizontal(parts)


def is_placeholder() -> pl.Expr:
    """CGU's recipient it does not identify: `Sem informação` with an empty or `-1` UF.

    Reads `name_key` and `uf_key`. With a real UF the row still names a municipality.
    """
    uf = pl.col("uf_key").fill_null("")
    return (pl.col("name_key") == PLACEHOLDER_NAME) & uf.is_in(PLACEHOLDER_UFS)


def match_recipients(
    payments: pl.DataFrame,
    munis: pl.DataFrame,
    *,
    max_unmatched: float = MAX_UNMATCHED_RECIPIENTS,
) -> tuple[pl.DataFrame, dict[str, dict[int, Any]]]:
    """Add `cd_ibge` to the payments from (`UF Favorecido`, municipality name).

    Rows with no municipality and rows that name a municipality that matches nothing keep a
    null `cd_ibge` (they have no row in the panel; their authors still count in the author
    link). No municipality: an empty name (state or federal recipients), or CGU's placeholder
    (`is_placeholder`). Both are counted per year; a year in which more than `max_unmatched` of
    the rows that name a municipality match nothing stops the build.

    Counts per year: `no_municipality` (placeholders included), `unmatched`, `placeholder`
    (rows), `placeholder_value` (sum of `value`), `placeholder_share` (of the year's `value`)
    and `top_unmatched`: up to `TOP_UNMATCHED` (UF, normalised name, rows) of the unmatched
    rows, most frequent first. Municipality names only.
    """
    key = (
        munis.select("cd_ibge", pl.col("uf").str.to_uppercase().alias("uf_key"), "name_ibge")
        .pipe(with_norm, "name_ibge", "name_key")
        .select("cd_ibge", "uf_key", "name_key")
    )
    if key.select(pl.struct("uf_key", "name_key").is_duplicated().any()).item():
        raise BuildError("municipalities: two municipalities share a state and a normalised name")
    rows = (
        payments.pipe(with_norm, "muni", "name_key")
        .with_columns(pl.col("uf").str.strip_chars().str.to_uppercase().alias("uf_key"))
        .with_columns((pl.col("ym") // 100).alias("year"))
    )
    joined = rows.join(key, on=["uf_key", "name_key"], how="left").with_columns(
        is_placeholder().alias("placeholder")
    )
    none = (pl.col("name_key") == "") | pl.col("placeholder")
    named = joined.filter(~none)
    failed = named.filter(pl.col("cd_ibge").is_null())
    named_by_year = _per_year(named)
    failed_by_year = _per_year(failed)
    for year, n in sorted(failed_by_year.items()):
        if n > max_unmatched * named_by_year[year]:
            raise BuildError(
                f"{year}: {n} of {named_by_year[year]} recipient rows match no municipality"
            )
    empty_by_year = _per_year(joined.filter(none))
    placeholder = joined.filter(pl.col("placeholder"))
    value_by_year = _value_per_year(joined)
    placeholder_value = _value_per_year(placeholder)
    top = (
        failed.group_by("year", pl.col("uf_key").fill_null(""), "name_key")
        .len()
        .sort(["year", "len", "uf_key", "name_key"], descending=[False, True, False, False])
    )
    top_unmatched: dict[int, list[tuple[str, str, int]]] = {}
    for year, uf, name, n in top.iter_rows():
        pairs = top_unmatched.setdefault(int(year), [])
        if len(pairs) < TOP_UNMATCHED:
            pairs.append((uf, name, int(n)))
    out = joined.drop("year", "uf_key", "name_key", "muni", "uf", "placeholder")
    return out, {
        "no_municipality": empty_by_year,
        "unmatched": failed_by_year,
        "placeholder": _per_year(placeholder),
        "placeholder_value": placeholder_value,
        "placeholder_share": {
            y: (v / value_by_year[y] if value_by_year[y] else 0.0)
            for y, v in placeholder_value.items()
        },
        "top_unmatched": top_unmatched,
    }


def _value_per_year(frame: pl.DataFrame) -> dict[int, float]:
    sums = frame.group_by("year").agg(pl.col("value").sum()).sort("year")
    return {int(y): float(v) for y, v in sums.iter_rows()}


def _per_year(frame: pl.DataFrame) -> dict[int, int]:
    counts = frame.group_by("year").len().sort("year")
    return {int(y): int(n) for y, n in counts.iter_rows()}


# --- TSE general elections


def _member(zf: zipfile.ZipFile) -> str:
    members = [n for n in zf.namelist() if n.lower().endswith("_brasil.csv")]
    if len(members) != 1:
        raise BuildError(f"expected one *_BRASIL.csv member, found {len(members)}")
    return members[0]


def read_tse_csv(
    zip_path: Path, tmp_dir: Path, wanted: tuple[str, ...], optional=()
) -> pl.DataFrame:
    """The `wanted` and any `optional` columns of the `*_BRASIL.csv` member, as text.

    The member is decoded (Latin-1) in chunks into a temporary UTF-8 file, read, and deleted;
    it is never held whole in memory. A missing wanted column stops the build.
    """
    target = tmp_dir / (zip_path.stem + ".utf8.csv")
    try:
        with zipfile.ZipFile(zip_path) as zf, zf.open(_member(zf)) as src, target.open("wb") as out:
            while chunk := src.read(CHUNK_BYTES):
                out.write(chunk.decode("latin-1").encode("utf-8"))
        header = pl.read_csv(
            target, separator=";", quote_char='"', infer_schema=False, n_rows=1
        ).columns
        if [c for c in wanted if c not in header]:
            raise BuildError(f"{zip_path.name} lacks a column the build needs")
        columns = [*wanted, *[c for c in optional if c in header]]
        return pl.read_csv(
            target, separator=";", quote_char='"', infer_schema=False, columns=columns
        )
    finally:
        target.unlink(missing_ok=True)


def read_votes(
    zip_path: Path, tmp_dir: Path, munis: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Votes of federal deputies per candidacy and municipality: `uf`, `sq`, `cd_ibge`, `votes`.

    Round 1, `CD_CARGO` 6, summed over zones. Votes are `QT_VOTOS_NOMINAIS_VALIDOS` where the
    file has the column, else `QT_VOTOS_NOMINAIS`. Rows whose TSE municipality is not in
    `municipalities` (votes abroad, `SG_UF` `ZZ`) are dropped and counted.
    """
    raw = read_tse_csv(
        zip_path,
        tmp_dir,
        ("SG_UF", "CD_MUNICIPIO", "CD_CARGO", "SQ_CANDIDATO", "NR_TURNO", "QT_VOTOS_NOMINAIS"),
        ("QT_VOTOS_NOMINAIS_VALIDOS",),
    )
    column = "QT_VOTOS_NOMINAIS_VALIDOS"
    if column not in raw.columns:
        column = "QT_VOTOS_NOMINAIS"
    rows = raw.filter(
        (pl.col("CD_CARGO").cast(pl.Int64, strict=False) == DEPUTY)
        & (pl.col("NR_TURNO").cast(pl.Int64, strict=False) == 1)
    )
    votes = pl.col(column).cast(pl.Int64, strict=False)
    if rows.filter(votes.is_null()).height:
        raise BuildError(f"{zip_path.name}: a vote count is not an integer")
    rows = rows.with_columns(
        votes.alias("votes"), pl.col("CD_MUNICIPIO").str.strip_chars().str.zfill(5).alias("cd_tse")
    )
    lookup = munis.select("cd_tse", "cd_ibge")
    joined = rows.join(lookup, on="cd_tse", how="left")
    missing = joined.filter(pl.col("cd_ibge").is_null())
    counts = {
        "abroad": missing.filter(pl.col("SG_UF") == "ZZ").height,
        "unmatched": missing.filter(pl.col("SG_UF") != "ZZ").height,
    }
    out = (
        joined.filter(pl.col("cd_ibge").is_not_null())
        .group_by(["SG_UF", "SQ_CANDIDATO", "cd_ibge"])
        .agg(pl.col("votes").sum())
        .rename({"SG_UF": "uf", "SQ_CANDIDATO": "sq"})
    )
    return out, counts


def read_candidacies(zip_path: Path, tmp_dir: Path, *, with_cpf: bool) -> pl.DataFrame:
    """Deputy and senate candidacies: `cargo`, `sq`, `uf`, `party`, `elected`, `name_urn`,
    `name_full` and, if asked, `cpf` (in memory only). Names are normalised; `elected` is
    `CD_SIT_TOT_TURNO` 1-3.
    """
    wanted = (
        "SQ_CANDIDATO",
        "CD_CARGO",
        "SG_UF",
        "NM_URNA_CANDIDATO",
        "NM_CANDIDATO",
        "NR_PARTIDO",
        "CD_SIT_TOT_TURNO",
    )
    raw = read_tse_csv(zip_path, tmp_dir, wanted, ("NR_CPF_CANDIDATO",) if with_cpf else ())
    if with_cpf and "NR_CPF_CANDIDATO" not in raw.columns:
        raise BuildError(f"{zip_path.name} lacks a column the build needs")
    rows = raw.with_columns(pl.col("CD_CARGO").cast(pl.Int64, strict=False).alias("cargo"))
    rows = rows.filter(pl.col("cargo").is_in([DEPUTY, SENATOR])).with_columns(
        pl.col("SQ_CANDIDATO").alias("sq"),
        pl.col("SG_UF").alias("uf"),
        pl.col("NR_PARTIDO").alias("party"),
        pl.col("CD_SIT_TOT_TURNO")
        .cast(pl.Int64, strict=False)
        .is_in(ELECTED_CODES)
        .fill_null(False)
        .alias("elected"),
    )
    rows = with_norm(rows, "NM_URNA_CANDIDATO", "name_urn")
    rows = with_norm(rows, "NM_CANDIDATO", "name_full")
    keep = ["cargo", "sq", "uf", "party", "elected", "name_urn", "name_full"]
    if with_cpf:
        rows = rows.with_columns(pl.col("NR_CPF_CANDIDATO").alias("cpf"))
        keep.append("cpf")
    return rows.select(keep)


# --- The author link (names are used in memory only)


def author_link(
    authors: pl.DataFrame, deputies: pl.DataFrame, senators: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Link each author (`aid`, `name`) to a t0 deputy candidacy or a senator.

    `deputies` has `sq`, `name_urn` and `name_full`; `senators` has `key`, `name_urn` and
    `name_full` (elected senate candidacies at t0 and t0-4). Exactly one deputy candidacy
    matching a name: deputy. Several: ambiguous, so unmatched. An unmatched author who matches
    exactly one senate candidacy is a senator. Returns `aid`, `kind` (deputy, senator or
    unmatched) and `sq` (set for deputies), and the counts.
    """

    def long(frame: pl.DataFrame, key: str) -> pl.DataFrame:
        return (
            pl.concat(
                [
                    frame.select(pl.col("name_urn").alias("name"), key),
                    frame.select(pl.col("name_full").alias("name"), key),
                ]
            )
            .filter(pl.col("name") != "")
            .unique()
        )

    def matches(long_table: pl.DataFrame, key: str, n_name: str) -> pl.DataFrame:
        return (
            authors.join(long_table, on="name", how="left")
            .group_by("aid")
            .agg(
                pl.col(key).drop_nulls().n_unique().alias(n_name),
                pl.col(key).drop_nulls().first().alias(key),
            )
        )

    dep = matches(long(deputies, "sq"), "sq", "n_dep")
    sen = matches(long(senators, "key"), "key", "n_sen").select("aid", "n_sen")
    table = (
        authors.select("aid")
        .join(dep, on="aid", how="left")
        .join(sen, on="aid", how="left")
        .with_columns(pl.col("n_dep").fill_null(0), pl.col("n_sen").fill_null(0))
        .with_columns(
            pl.when(pl.col("n_dep") == 1)
            .then(pl.lit("deputy"))
            .when(pl.col("n_sen") == 1)
            .then(pl.lit("senator"))
            .otherwise(pl.lit("unmatched"))
            .alias("kind")
        )
        .with_columns(pl.when(pl.col("kind") == "deputy").then(pl.col("sq")).alias("sq"))
    )
    counts = {
        "authors": table.height,
        "deputies": table.filter(pl.col("kind") == "deputy").height,
        "senators": table.filter(pl.col("kind") == "senator").height,
        "ambiguous": table.filter(pl.col("n_dep") > 1).height,
        "unmatched": table.filter(pl.col("kind") == "unmatched").height,
    }
    return table.select("aid", "kind", "sq"), counts


def linkable() -> pl.Expr:
    return pl.col("cpf").str.strip_chars().str.contains(CPF_PATTERN).fill_null(False)


def link_to_t1(
    deputies: pl.DataFrame, t1: pl.DataFrame, t1_votes: pl.DataFrame
) -> tuple[pl.DataFrame, int]:
    """For each deputy (`sq`, `uf`, `cpf`): `sq1`, the t1 candidacy in the same state with the
    same CPF, and `ran_t1`, true if its statewide votes are above 0.

    The CPF stays in memory. A CPF that is empty or not 11 digits is unlinked; returns the
    count of unlinked deputies. `t1` has `sq`, `uf`, `cpf`; `t1_votes` has `uf`, `sq`, `votes`.
    """
    unlinked = deputies.filter(~linkable()).height
    now = (
        t1.filter(linkable())
        .select("uf", pl.col("cpf").str.strip_chars(), pl.col("sq").alias("sq1"))
        .sort("sq1")
        .unique(subset=["uf", "cpf"], keep="first")
    )
    state_votes = (
        t1_votes.group_by(["uf", "sq"])
        .agg(pl.col("votes").sum().alias("total"))
        .rename({"sq": "sq1"})
    )
    out = (
        deputies.filter(linkable())
        .select("sq", "uf", pl.col("cpf").str.strip_chars())
        .join(now, on=["uf", "cpf"], how="left")
        .join(state_votes, on=["uf", "sq1"], how="left")
        .select("sq", "sq1", (pl.col("total").fill_null(0) > 0).alias("ran_t1"))
    )
    rest = deputies.filter(~linkable()).select(
        "sq", pl.lit(None, dtype=pl.Utf8).alias("sq1"), pl.lit(False).alias("ran_t1")
    )
    return pl.concat([out.with_columns(pl.col("sq1").cast(pl.Utf8)), rest]), unlinked


# --- Mayoral races (copied from explore/0003_mayor_power.py, changed to keep the finalists)


def main_election(cv: pl.DataFrame) -> int:
    """The round-1 `cd_eleicao` with the most mayoral rows."""
    rows = (
        cv.filter(
            (pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR)
            & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
        )
        .group_by("cd_eleicao")
        .len()
    )
    if rows.height == 0:
        raise BuildError("no first-round mayoral rows")
    return int(rows.sort(["len", "cd_eleicao"], descending=[True, False])["cd_eleicao"][0])


def deciding_round(cv: pl.DataFrame, main: int) -> pl.DataFrame:
    """Mayoral rows of each municipality's deciding round, with a `runoff` flag.

    Round 2 under `main + 1` when the municipality has mayoral rows there, else round 1 under
    `main`. Rows of other elections (supplementary) are dropped.
    """
    mayor = cv.filter(pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR).with_columns(
        pl.col("cd_eleicao").cast(pl.Int64, strict=False),
        pl.col("nr_turno").cast(pl.Int64, strict=False),
    )
    round2 = mayor.filter((pl.col("cd_eleicao") == main + 1) & (pl.col("nr_turno") == 2))
    in_runoff = round2["sg_ue"].unique().to_list()
    round1 = mayor.filter(
        (pl.col("cd_eleicao") == main)
        & (pl.col("nr_turno") == 1)
        & ~pl.col("sg_ue").is_in(in_runoff)
    )
    return pl.concat(
        [
            round2.with_columns(pl.lit(True).alias("runoff")),
            round1.with_columns(pl.lit(False).alias("runoff")),
        ]
    )


def candidacy_votes_mayor(rows: pl.DataFrame, year: int) -> pl.DataFrame:
    """Votes per candidacy in `rows`, summed over zones; candidacies without votes are dropped.

    2016 and later: `qt_votos_nominais_validos` on rows whose destination is exactly `Válido`.
    Before: `qt_votos_nominais` (the files have no destination column).
    """
    if year >= 2016:
        kept = rows.filter(pl.col("nm_tipo_destinacao_votos") == "Válido")
        column = "qt_votos_nominais_validos"
    else:
        kept = rows
        column = "qt_votos_nominais"
    return (
        kept.group_by(["sg_ue", "sq_candidato"], maintain_order=True)
        .agg(
            pl.col(column).cast(pl.Float64).sum().alias("votes"),
            pl.col("cd_ibge").first(),
            pl.col("runoff").first(),
        )
        .filter(pl.col("votes") > 0)
    )


def valid_votes_mayor(turnout: pl.DataFrame, rows: pl.DataFrame) -> pl.DataFrame:
    """(`sg_ue`, `valid`): valid mayoral votes of the deciding round, summed over zones."""
    chosen = rows.select("sg_ue", "cd_eleicao", "nr_turno").unique()
    t = turnout.filter(pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR).with_columns(
        pl.col("cd_eleicao").cast(pl.Int64, strict=False),
        pl.col("nr_turno").cast(pl.Int64, strict=False),
    )
    return (
        t.join(chosen, on=["sg_ue", "cd_eleicao", "nr_turno"], how="inner")
        .group_by("sg_ue")
        .agg(pl.col("qt_total_votos_validos").cast(pl.Float64).sum().alias("valid"))
    )


def races(votes: pl.DataFrame, valid: pl.DataFrame) -> pl.DataFrame:
    """One row per finalist of a race with two candidacies and valid votes.

    The first and second candidacies by votes (ties broken by `sq_candidato`) are the finalists.
    Columns: `sg_ue`, `cd_ibge`, `runoff`, `valid`, `sq_candidato`, `own` (its votes) and
    `other` (the other finalist's votes). Municipalities with one candidacy have no race.
    """
    ordered = votes.sort(["sg_ue", "votes", "sq_candidato"], descending=[False, True, False])
    g = ordered.group_by("sg_ue", maintain_order=True).agg(
        pl.col("cd_ibge").first(),
        pl.col("runoff").first(),
        pl.len().alias("n"),
        pl.col("sq_candidato").first().alias("sq1"),
        pl.col("votes").first().alias("v1"),
        pl.col("sq_candidato").slice(1, 1).first().alias("sq2"),
        pl.col("votes").slice(1, 1).first().alias("v2"),
    )
    two = g.filter(pl.col("n") >= 2).join(valid, on="sg_ue", how="left")
    two = two.filter(pl.col("valid").is_not_null() & (pl.col("valid") > 0))
    first = two.select(
        "sg_ue",
        "cd_ibge",
        "runoff",
        "valid",
        pl.col("sq1").alias("sq_candidato"),
        pl.col("v1").alias("own"),
        pl.col("v2").alias("other"),
        pl.lit(0).alias("rank"),
    )
    second = two.select(
        "sg_ue", "cd_ibge", "runoff", "valid", pl.col("sq2").alias("sq_candidato"),
        pl.col("v2").alias("own"), pl.col("v1").alias("other"), pl.lit(1).alias("rank"),
    )  # fmt: skip
    return pl.concat([first, second])


def candidate_attributes(attrs: pl.DataFrame, year: int, main: int) -> pl.DataFrame:
    """One row per mayoral candidacy of `year` (`sg_ue`, `sq_candidato`): party, gender,
    birth date, education and election date. Round 1 (`main`) wins over a round-2 row."""
    return (
        attrs.filter(
            (pl.col("ano_eleicao").cast(pl.Int64, strict=False) == year)
            & pl.col("cd_eleicao").cast(pl.Int64, strict=False).is_in([main, main + 1])
        )
        .sort("cd_eleicao")
        .unique(subset=["sg_ue", "sq_candidato"], keep="first", maintain_order=True)
        .select(
            "sg_ue",
            "sq_candidato",
            pl.col("nr_partido").alias("party"),
            "cd_genero",
            "dt_nascimento",
            "cd_grau_instrucao",
            "dt_eleicao",
        )
    )


def check_candidate_codes(votes: pl.DataFrame, attrs: pl.DataFrame, year: int) -> None:
    """Stops if no mayoral candidate of the year has gender code "4" or education code "8"."""
    joined = votes.join(attrs, on=["sg_ue", "sq_candidato"], how="left")
    if joined.filter(pl.col("cd_genero") == FEMALE).height == 0:
        raise BuildError(f"{year}: no mayoral candidate has gender code {FEMALE}")
    if joined.filter(pl.col("cd_grau_instrucao") == HIGHER_ED).height == 0:
        raise BuildError(f"{year}: no mayoral candidate has education code {HIGHER_ED}")


class Mayors(NamedTuple):
    finalists: pl.DataFrame  # one row per (cd_ibge, party) finalist
    winners: pl.DataFrame  # (cd_ibge, party) of the top candidacy of each municipality
    parties: frozenset[str]  # party numbers with a first-round candidacy
    n_cands: pl.DataFrame  # (cd_ibge, n_mayor_cands), round 1


def mayor_year(cv: pl.DataFrame, turnout: pl.DataFrame, attrs: pl.DataFrame, year: int) -> Mayors:
    """Finalists, winners and first-round candidates of the mayoral election of `year`."""
    main = main_election(cv)
    rows = deciding_round(cv, main)
    votes = candidacy_votes_mayor(rows, year)
    cattrs = candidate_attributes(attrs, year, main)
    check_candidate_codes(votes, cattrs, year)
    finalists = (
        races(votes, valid_votes_mayor(turnout, rows))
        .join(cattrs, on=["sg_ue", "sq_candidato"], how="left")
        .filter(pl.col("party").is_not_null())
        .sort(["sg_ue", "rank"])
        .unique(subset=["sg_ue", "party"], keep="first", maintain_order=True)
    )
    margin = (pl.col("own") - pl.col("other")) / pl.col("valid")
    birth, date = pl.col("dt_nascimento"), pl.col("dt_eleicao")

    def month_day(d: pl.Expr) -> pl.Expr:  # cast first: month * 100 overflows Int8
        return d.dt.month().cast(pl.Int64) * 100 + d.dt.day().cast(pl.Int64)

    before_birthday = month_day(date) < month_day(birth)
    finalists = finalists.select(
        "cd_ibge",
        "party",
        pl.when(pl.col("runoff")).then(2).otherwise(1).cast(pl.Int64).alias("round"),
        margin.alias("margin"),
        (pl.col("cd_genero") == FEMALE).alias("fin_female"),
        (date.dt.year() - birth.dt.year() - before_birthday.cast(pl.Int64))
        .cast(pl.Int64)
        .alias("fin_age"),
        (pl.col("cd_grau_instrucao") == HIGHER_ED).alias("fin_higher_ed"),
    )
    top = (
        votes.sort(["sg_ue", "votes", "sq_candidato"], descending=[False, True, False])
        .unique(subset=["sg_ue"], keep="first", maintain_order=True)
        .join(cattrs, on=["sg_ue", "sq_candidato"], how="left")
        .filter(pl.col("party").is_not_null())
        .select("cd_ibge", "party")
    )
    first_round = candidacy_votes_mayor(
        cv.filter(
            (pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR)
            & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
            & (pl.col("cd_eleicao").cast(pl.Int64, strict=False) == main)
        ).with_columns(pl.lit(False).alias("runoff")),
        year,
    )
    parties = frozenset(
        first_round.join(cattrs, on=["sg_ue", "sq_candidato"], how="left")["party"]
        .drop_nulls()
        .to_list()
    )
    n_cands = first_round.group_by("cd_ibge").agg(pl.len().cast(pl.Int64).alias("n_mayor_cands"))
    return Mayors(finalists, top, parties, n_cands)


# --- One cycle


def window_sums(payments: pl.DataFrame, cycle: Cycle) -> pl.DataFrame:
    """Per (`deputy`, `cd_ibge`): the payments of the pre and post windows.

    Negative payment rows (refunds and reversals) are summed with the rest; `floor_payments`
    then sets a total below 0 to 0.
    """
    pre = pl.col("ym").is_between(*cycle.pre)
    post = pl.col("ym").is_between(*cycle.post)
    value = pl.col("value")
    return payments.group_by(["deputy", "cd_ibge"]).agg(
        value.filter(pre).sum().alias("amend_pre_total"),
        value.filter(pre & pl.col("pix")).sum().alias("amend_pre_pix"),
        pre.sum().cast(pl.Int64).alias("n_pay_pre"),
        value.filter(post).sum().alias("amend_post_total"),
        value.filter(post & pl.col("pix")).sum().alias("amend_post_pix"),
        post.sum().cast(pl.Int64).alias("n_pay_post"),
    )


def _share(votes: str, valid: str) -> pl.Expr:
    return pl.when(pl.col(valid) > 0).then(pl.col(votes) / pl.col(valid))


def cycle_panel(
    name: str,
    *,
    deputies: pl.DataFrame,
    payments: pl.DataFrame,
    mayors: Mayors,
    previous: Mayors,
    population: pl.DataFrame,
    munis: pl.DataFrame,
    votes0: pl.DataFrame,
    votes1: pl.DataFrame,
    t1_link: pl.DataFrame,
) -> tuple[pl.DataFrame, int]:
    """The panel rows of one cycle, and the number of deputies whose party number has no
    first-round mayoral candidate in the cycle's mayoral election (mergers).

    `deputies`: the deputies of the cycle (`sq`, `uf`, `party`, `elected`). `payments`:
    individual payments with `deputy` (t0 `sq`), `cd_ibge`, `ym`, `value`, `pix`. `votes0` and
    `votes1`: `uf`, `sq`, `cd_ibge`, `votes` at t0 and t1. `t1_link`: `sq`, `sq1`, `ran_t1`.
    """
    cycle = CYCLES[name]
    base = deputies.select(
        pl.col("sq").alias("deputy"),
        "uf",
        pl.col("party").alias("deputy_party"),
        pl.col("elected").alias("deputy_elected"),
    )
    finalists = mayors.finalists.join(
        munis.select("cd_ibge", "uf"), on="cd_ibge", how="inner"
    ).rename({"party": "deputy_party"})
    held = previous.winners.with_columns(pl.lit(True).alias("party_held_mayor")).rename(
        {"party": "deputy_party"}
    )
    pop = population.filter(pl.col("ano") == cycle.m).select(
        pl.col("id_municipio").cast(pl.Utf8).str.zfill(7).alias("cd_ibge"),
        pl.col("populacao").cast(pl.Int64).alias("population_m"),
    )
    v0 = (
        votes0.group_by(["uf", "sq", "cd_ibge"])
        .agg(pl.col("votes").sum().alias("votes_t0"))
        .rename({"sq": "deputy"})
    )
    valid0 = votes0.group_by("cd_ibge").agg(pl.col("votes").sum().alias("valid_t0"))
    v1 = (
        votes1.group_by(["uf", "sq", "cd_ibge"])
        .agg(pl.col("votes").sum().alias("v1"))
        .rename({"sq": "sq1"})
    )
    valid1 = votes1.group_by("cd_ibge").agg(pl.col("votes").sum().alias("valid_t1"))
    ran = t1_link.rename({"sq": "deputy"})
    rows = (
        base.join(finalists, on=["uf", "deputy_party"], how="inner")
        .join(held, on=["cd_ibge", "deputy_party"], how="left")
        .join(mayors.n_cands, on="cd_ibge", how="left")
        .join(pop, on="cd_ibge", how="left")
        .join(window_sums(payments, cycle), on=["deputy", "cd_ibge"], how="left")
        .join(v0, on=["uf", "deputy", "cd_ibge"], how="left")
        .join(valid0, on="cd_ibge", how="left")
        .join(ran, on="deputy", how="left")
        .join(v1, on=["uf", "sq1", "cd_ibge"], how="left")
        .join(valid1, on="cd_ibge", how="left")
    )
    ran_t1 = pl.col("ran_t1").fill_null(False)
    rows = rows.with_columns(
        pl.lit(name).alias("cycle"),
        pl.lit(cycle.m, dtype=pl.Int64).alias("m"),
        pl.lit(cycle.t0, dtype=pl.Int64).alias("t0"),
        pl.lit(cycle.t1, dtype=pl.Int64).alias("t1"),
        (pl.col("margin") > 0).alias("win"),
        pl.col("party_held_mayor").fill_null(False),
        *[pl.col(c).fill_null(0.0) for c in PAYMENTS],
        pl.col("n_pay_pre").fill_null(0),
        pl.col("n_pay_post").fill_null(0),
        pl.col("votes_t0").fill_null(0),
        ran_t1.alias("ran_t1"),
    ).with_columns(
        _share("votes_t0", "valid_t0").alias("share_t0"),
        pl.when(ran_t1).then(pl.col("v1").fill_null(0)).alias("votes_t1"),
        pl.when(ran_t1).then(pl.col("valid_t1")).alias("valid_t1"),
    )
    rows = rows.with_columns(_share("votes_t1", "valid_t1").alias("share_t1")).with_columns(
        (pl.col("share_t1") - pl.col("share_t0")).alias("d_share")
    )
    panel = rows.select([pl.col(n).cast(t) for n, t in SCHEMA.items()]).sort(["deputy", "cd_ibge"])
    merger = deputies.filter(~pl.col("party").is_in(sorted(mayors.parties)))
    return panel, merger.height


def floor_payments(panel: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Set each payment column (`PAYMENTS`) that nets below 0 to 0.

    Returns the panel and, per column, the number of rows set to 0 (both halves).
    """
    counts = {c: panel.filter(pl.col(c) < 0).height for c in PAYMENTS}
    floored = panel.with_columns(
        pl.when(pl.col(c) < 0).then(0.0).otherwise(pl.col(c)).alias(c) for c in PAYMENTS
    )
    return floored, counts


def negative_payments(individual: pl.DataFrame) -> tuple[dict[int, int], dict[int, float]]:
    """Per year: the individual payment rows with a value below 0, and their sum (reais)."""
    rows = individual.filter(pl.col("value") < 0).with_columns((pl.col("ym") // 100).alias("year"))
    return _per_year(rows), _value_per_year(rows)


def check_panel(
    tables: dict[str, pl.DataFrame], *, min_rows: int = MIN_ROWS, max_rows: int = MAX_ROWS
) -> None:
    """Every stop condition on the panel of every cycle (both halves). Counts only."""
    for name, table in sorted(tables.items()):
        if table.select(pl.struct("cycle", "deputy", "cd_ibge").is_duplicated().any()).item():
            raise BuildError(f"{name}: a (cycle, deputy, cd_ibge) appears twice")
        outside = table.filter(
            (pl.col("margin").abs() > 1 + TOLERANCE) | (pl.col("win") != (pl.col("margin") > 0))
        ).height
        if outside:
            raise BuildError(f"{name}: {outside} rows have a margin outside [-1, 1] or a wrong win")
        for column in SHARES:
            bad = table.filter(
                (pl.col(column) < -TOLERANCE) | (pl.col(column) > 1 + TOLERANCE)
            ).height
            if bad:
                raise BuildError(f"{name}: {bad} rows have {column} outside [0, 1]")
        for column in PAYMENTS:
            bad = table.filter(pl.col(column) < 0).height
            if bad:
                raise BuildError(f"{name}: {bad} rows have {column} below 0")
        if table.height < min_rows or table.height > max_rows:
            raise BuildError(f"{name}: {table.height} rows, outside {min_rows}-{max_rows}")


def _month(ym: int) -> str:
    return f"{ym // 100}-{ym % 100:02d}"


def _years(counts: dict[int, Any], fmt: str = "") -> str:
    return ",".join(f"{y}:{n:{fmt}}" for y, n in sorted(counts.items())) or "none"


def placeholder_notes(dropped: dict[str, dict[int, Any]]) -> list[str]:
    """The placeholder counts and the most frequent unmatched (UF, name) pairs, per year."""
    notes = [
        f"placeholder_recipient_rows={_years(dropped['placeholder'])}",
        f"placeholder_recipient_value_brl={_years(dropped['placeholder_value'], '.2f')}",
        f"placeholder_recipient_value_share={_years(dropped['placeholder_share'], '.4f')}",
    ]
    top = dropped["top_unmatched"]
    for year, pairs in sorted(top.items()):
        listed = ", ".join(f"{uf or '(empty)'}/{name}:{n}" for uf, name, n in pairs)
        notes.append(f"top_unmatched_recipients_{year}={listed}")
    if not top:
        notes.append("top_unmatched_recipients=none")
    return notes


def _fetch_frame(
    store: Store,
    entry: dict[str, Any],
    tmp_dir: Path,
    wanted: tuple[str, ...],
) -> pl.DataFrame:
    path = _fetch(store, entry, tmp_dir)
    try:
        schema = pl.read_parquet_schema(path)
        if [c for c in wanted if c not in schema]:
            raise BuildError(f"{path.name} lacks a column the build needs")
        return pl.read_parquet(path, columns=list(wanted))
    finally:
        path.unlink(missing_ok=True)


def general_entries(
    manifest: dict[str, Any], cycles: tuple[str, ...]
) -> dict[tuple[str, int], dict[str, Any]]:
    """The tse_general zips the cycles need, by (kind, year): kind is `consulta_cand` or
    `votacao_candidato_munzona`."""
    needed: dict[tuple[str, int], dict[str, Any]] = {}
    for c in cycles:
        cy = CYCLES[c]
        for year in (cy.t0 - 4, cy.t0, cy.t1):
            needed[("consulta_cand", year)] = _file(manifest, f"/consulta_cand_{year}.zip")
        for year in (cy.t0, cy.t1):
            needed[("votacao_candidato_munzona", year)] = _file(
                manifest, f"/votacao_candidato_munzona_{year}.zip"
            )
    return needed


def _candidacies(
    store: Store, entry: dict[str, Any], tmp_dir: Path, *, with_cpf: bool
) -> pl.DataFrame:
    path = _fetch(store, entry, tmp_dir)
    try:
        return read_candidacies(path, tmp_dir, with_cpf=with_cpf)
    finally:
        path.unlink(missing_ok=True)


def _votes(
    store: Store, entry: dict[str, Any], tmp_dir: Path, munis: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    path = _fetch(store, entry, tmp_dir)
    try:
        return read_votes(path, tmp_dir, munis)
    finally:
        path.unlink(missing_ok=True)


def _mayors(
    store: Store,
    votes: dict[int, dict[str, Any]],
    turnout: dict[int, dict[str, Any]],
    year: int,
    tmp_dir: Path,
    attrs: pl.DataFrame,
) -> Mayors:
    cv = _fetch_frame(store, votes[year], tmp_dir, VOTES_COLUMNS)
    return mayor_year(cv, _fetch_frame(store, turnout[year], tmp_dir, TURNOUT_COLUMNS), attrs, year)


def _senators(old: pl.DataFrame, new: pl.DataFrame, t0: int) -> pl.DataFrame:
    """Elected senate candidacies at t0 and t0-4, each with a key of year and `sq`."""
    parts = [
        frame.filter((pl.col("cargo") == SENATOR) & pl.col("elected")).select(
            pl.concat_str([pl.lit(f"{year}:"), pl.col("sq")]).alias("key"), "name_urn", "name_full"
        )
        for frame, year in ((old, t0 - 4), (new, t0))
    ]
    return pl.concat(parts)


def cycle_inputs(
    name: str,
    store: Store,
    general: dict[tuple[str, int], dict[str, Any]],
    payments: pl.DataFrame,
    munis: pl.DataFrame,
    tmp_dir: Path,
) -> dict[str, Any]:
    """Everything of one cycle that comes from the TSE general elections and the CGU rows:
    the deputies of the cycle, their payments, the t1 link and the votes at t0 and t1."""
    cy = CYCLES[name]
    tse_munis = munis.filter(pl.col("cd_tse").is_not_null())
    old = _candidacies(store, general[("consulta_cand", cy.t0 - 4)], tmp_dir, with_cpf=False)
    cand0 = _candidacies(store, general[("consulta_cand", cy.t0)], tmp_dir, with_cpf=True)
    cand1 = _candidacies(store, general[("consulta_cand", cy.t1)], tmp_dir, with_cpf=True)
    votes0, dropped0 = _votes(
        store, general[("votacao_candidato_munzona", cy.t0)], tmp_dir, tse_munis
    )
    votes1, dropped1 = _votes(
        store, general[("votacao_candidato_munzona", cy.t1)], tmp_dir, tse_munis
    )

    base = cand0.filter(pl.col("cargo") == DEPUTY)
    if base["sq"].is_duplicated().any():
        raise BuildError(f"{name}: a candidacy appears twice in the t0 candidates")
    senators = _senators(old, cand0, cy.t0)
    mine = payments.filter(in_windows((name,))).with_columns(pl.col("code").fill_null(""))
    mine = with_norm(mine, "author", "name")
    authors = mine.select("code", "name").unique().sort("code", "name").with_row_index("aid")
    link, counts = author_link(authors, base, senators)
    served = link.filter(pl.col("kind") == "deputy")
    deputies = base.filter(pl.col("elected") | pl.col("sq").is_in(served["sq"].to_list()))
    paid = (
        mine.filter(pl.col("cd_ibge").is_not_null())
        .join(authors, on=["code", "name"], how="inner")
        .join(served.select("aid", pl.col("sq").alias("deputy")), on="aid", how="inner")
        .select("deputy", "cd_ibge", "ym", "value", "pix")
    )
    t1_link, unlinked = link_to_t1(
        deputies.select("sq", "uf", "cpf"),
        cand1.filter(pl.col("cargo") == DEPUTY).select("sq", "uf", "cpf"),
        votes1,
    )
    return {
        "deputies": deputies.select("sq", "uf", "party", "elected"),
        "payments": paid,
        "t1_link": t1_link,
        "votes0": votes0,
        "votes1": votes1,
        "counts": counts,
        "unlinked": unlinked,
        "dropped_votes": {k: dropped0[k] + dropped1[k] for k in dropped0},
    }


# --- Build


def build(
    store: Store,
    general_manifest: dict[str, Any],
    cgu_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    population_manifest: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    cycles: tuple[str, ...] = tuple(CYCLES),
    min_rows: int = MIN_ROWS,
    max_rows: int = MAX_ROWS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-cycle, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.write_manifest`)
    when `status` is `created`. The build never lists, reads or checks the sealed folder: a
    create-only upload fails if an object is there. Nothing is uploaded unless every check has
    passed.
    """
    explore, split_shas = read_lists(store)
    general = general_entries(general_manifest, cycles)
    cgu_entry = _file(cgu_manifest, "/EmendasParlamentares.zip")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    pop_entry = _file(population_manifest, "/ibge_population_annual.parquet")
    result_years = sorted({y for c in cycles for y in (CYCLES[c].m - 4, CYCLES[c].m)})
    vote_entries = {
        y: _file(results_manifest, f"/candidate_votes_{y}.parquet") for y in result_years
    }
    turnout_entries = {y: _file(results_manifest, f"/turnout_{y}.parquet") for y in result_years}

    entries = [
        cgu_entry,
        muni_entry,
        cand_entry,
        pop_entry,
        *general.values(),
        *vote_entries.values(),
        *turnout_entries.values(),
    ]
    hashed = input_hash(entries, split_shas, cycles)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    munis = _fetch_frame(store, muni_entry, tmp_dir, MUNICIPALITY_COLUMNS)
    if munis.filter(pl.col("cd_tse").is_not_null())["cd_tse"].is_duplicated().any():
        raise BuildError("municipalities: a cd_tse appears twice")
    attrs = _fetch_frame(store, cand_entry, tmp_dir, CANDIDATE_COLUMNS)
    population = _fetch_frame(store, pop_entry, tmp_dir, POPULATION_COLUMNS).with_columns(
        pl.col("ano").cast(pl.Int64)
    )

    cgu_path = _fetch(store, cgu_entry, tmp_dir)
    try:
        raw = read_cgu(cgu_path)
    finally:
        cgu_path.unlink(missing_ok=True)
    individual, stats = parse_payments(raw)
    del raw
    check_payment_stats(stats)
    negative_rows, negative_value = negative_payments(individual)
    windowed = individual.filter(in_windows(cycles))
    del individual
    paid, dropped = match_recipients(windowed, munis)

    tables: dict[str, pl.DataFrame] = {}
    links: list[dict[str, Any]] = []
    notes: list[str] = []
    explore_ids = sorted(explore)
    for name in cycles:
        cy = CYCLES[name]
        parts = cycle_inputs(name, store, general, paid, munis, tmp_dir)
        mayors = _mayors(store, vote_entries, turnout_entries, cy.m, tmp_dir, attrs)
        previous = _mayors(store, vote_entries, turnout_entries, cy.m - 4, tmp_dir, attrs)
        panel, mergers = cycle_panel(
            name,
            deputies=parts["deputies"],
            payments=parts["payments"],
            mayors=mayors,
            previous=previous,
            population=population,
            munis=munis,
            votes0=parts["votes0"],
            votes1=parts["votes1"],
            t1_link=parts["t1_link"],
        )
        panel, floored = floor_payments(panel)
        tables[name] = panel
        counts = parts["counts"]
        links.append({"cycle": name, **counts})
        half = panel.filter(pl.col("cd_ibge").is_in(explore_ids))
        notes.append(
            f"{name}: rows={half.height}, deputies={half['deputy'].n_unique()}, "
            f"authors={counts['authors']}, deputy_authors={counts['deputies']}, "
            f"senator_authors={counts['senators']}, ambiguous_authors={counts['ambiguous']}, "
            f"unmatched_authors={counts['unmatched']}, unlinked_cpfs={parts['unlinked']}, "
            f"party_without_mayor_cands={mergers}, "
            f"vote_rows_abroad={parts['dropped_votes']['abroad']}, "
            f"vote_rows_no_municipality={parts['dropped_votes']['unmatched']}"
        )
        notes.append(f"{name}_floored_to_zero=" + ",".join(f"{c}:{n}" for c, n in floored.items()))
        del parts

    notes.append(f"dropped_recipient_rows_no_municipality={_years(dropped['no_municipality'])}")
    notes.append(f"dropped_recipient_rows_unmatched={_years(dropped['unmatched'])}")
    notes.extend(placeholder_notes(dropped))
    notes.append(f"negative_payment_rows={_years(negative_rows)}")
    notes.append(f"negative_payment_value_brl={_years(negative_value, '.2f')}")
    notes.append(f"first_payment_month={_month(stats['first'])}, last={_month(stats['last'])}")
    notes.append(f"rows_without_payment_month={stats['no_month']}")

    check_panel(tables, min_rows=min_rows, max_rows=max_rows)

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per cycle
    for name, table in tables.items():
        is_explore = table["cd_ibge"].is_in(explore_ids)
        sealed_file, derived_file = sealed_dir / panel_name(name), derived_dir / panel_name(name)
        table.filter(~is_explore).write_parquet(sealed_file)
        table.filter(is_explore).write_parquet(derived_file)
        local.append((sealed_file, derived_file))
    link_file = derived_dir / LINK_NAME
    pl.DataFrame(links, schema=LINK_SCHEMA).write_parquet(link_file)

    # Every check has passed. Sealed first; the manifest is the caller's last step.
    sealed_files = [_upload(store, sealed_prefix + p.name, p) for p, _ in local]
    files = [_upload(store, derived_prefix + p.name, p) for _, p in local]
    files.append(_upload(store, derived_prefix + LINK_NAME, link_file))
    manifest = build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=derived_prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (
                general_manifest,
                cgu_manifest,
                results_manifest,
                candidates_manifest,
                municipalities_manifest,
                population_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
