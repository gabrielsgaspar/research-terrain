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

v3 adds the vote shares of the deputy's party (or federation) among federal and state deputies
at t0 and t1, from the TSE party-vote files (`tse_general_parties`), and exposes the deputy
link and the row keys to `terrain.builds.amendments_monthly`.

Names and CPFs are used only in memory, to link CGU authors to candidacies and a deputy's t0
candidacy to t1. No CPF, voter ID, name or favorecido code, and no hash of one, is written to a
column, a note or an exception message. `Código do Favorecido` and `Favorecido` are never read.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from terrain import explore as terrain_explore
from terrain import parties
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
STATE_DEPUTY = 7
SENATOR = 5
SENATE_SUBSTITUTES = (9, 10)  # first and second suplente
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
    "amendment": "Código da Emenda",
    "type": "Tipo de Emenda",
    "code": "Código do Autor da Emenda",
    "author": "Nome do Autor da Emenda",
    "ym": "Ano/Mês",
    "uf": "UF Favorecido",
    "muni": "Município Favorecido",
    "value": "Valor Recebido",
}
AMENDMENTS_MEMBER = "emendasparlamentares.csv"
AMENDMENT_COLUMNS = {"amendment": "Código da Emenda", "year": "Ano da Emenda"}
AMENDMENT_CODE = r"^\d+$"  # CGU writes `Sem informação` where it has no amendment code
# Leading titles CGU or TSE may put before a name; a name is also tried without them.
HONORIFICS = frozenset(
    {
        "DEP", "DEPUTADO", "DEPUTADA", "DR", "DRA", "DOUTOR", "DOUTORA", "PASTOR", "PASTORA",
        "PR", "DELEGADO", "DELEGADA", "CORONEL", "CEL", "PROFESSOR", "PROFESSORA", "PROF",
        "PROFA", "CAPITAO", "MAJOR", "SARGENTO", "SGT", "GENERAL", "TENENTE", "SUBTENENTE",
    }
)  # fmt: skip
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
CHAMBER_COLUMNS = {
    "nome": "chamber_name",
    "nomeCivil": "civil_name",
    "idLegislaturaInicial": "leg_first",
    "idLegislaturaFinal": "leg_last",
}
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
    "amend_pre_share": pl.Float64,
    "amend_post_share": pl.Float64,
    "amend_pre_log_pc": pl.Float64,
    "amend_post_log_pc": pl.Float64,
    "votes_t0": pl.Int64,
    "valid_t0": pl.Int64,
    "share_t0": pl.Float64,
    "ran_t1": pl.Boolean,
    "votes_t1": pl.Int64,
    "valid_t1": pl.Int64,
    "share_t1": pl.Float64,
    "d_share": pl.Float64,
    "party_share_t0": pl.Float64,
    "party_share_t1": pl.Float64,
    "state_party_share_t0": pl.Float64,
    "state_party_share_t1": pl.Float64,
}
LINK_SCHEMA: dict[str, Any] = {
    "cycle": pl.Utf8,
    "authors": pl.Int64,
    "deputies": pl.Int64,
    "senators": pl.Int64,
    "ambiguous": pl.Int64,
    "unmatched": pl.Int64,
    "ties_broken": pl.Int64,
    "non_current_authors": pl.Int64,
    "chamber_links": pl.Int64,
    "money_share": pl.Float64,
}
SHARES = ("share_t0", "share_t1", "amend_pre_share", "amend_post_share")
LOGS = ("amend_pre_log_pc", "amend_post_log_pc")
PAYMENTS = ("amend_pre_total", "amend_pre_pix", "amend_post_total", "amend_post_pix")
PARTY_SHARES = ("party_share_t0", "party_share_t1", "state_party_share_t0", "state_party_share_t1")
# The two vote columns of a party-vote file whose sum is a party's valid votes: nominal votes
# of its candidates plus party-list (legenda) votes. 2018 and later name valid votes; 2014
# has only the plain counts. The first pair a file has is used.
PARTY_VOTE_PAIRS = (
    ("QT_VOTOS_NOMINAIS_VALIDOS", "QT_TOTAL_VOTOS_LEG_VALIDOS"),
    ("QT_VOTOS_NOMINAIS", "QT_VOTOS_LEGENDA"),
)

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, `explore` (the exploration lists), `parties` (mergers and federations),
# `place_outcomes` (`read_lists`), `cell_outcomes` (the list parser and the upload) and
# `polling_place_tenure` (`_file` picks the inputs, `_fetch` checks their SHA-256).
CODE_MODULES = (
    Path(__file__),
    Path(terrain_explore.__file__),
    Path(parties.__file__),
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


def author_keys(text: str | None) -> list[str]:
    """The keys a CGU author or a TSE name is matched on: the name and, if it starts with titles
    (`HONORIFICS`), the name without them.

    Text in parentheses (CGU's note on an amendment taken over from a former member) is dropped,
    accents are stripped, letters are upper-cased and everything else splits words. A key is
    the words joined without spaces, so `ANA-MARIA`, `ANA MARIA` and `ANAMARIA` agree.
    """
    if text is None:
        return []
    bare = re.sub(r"\([^)]*(\)|$)", " ", text)
    plain = "".join(c for c in unicodedata.normalize("NFKD", bare) if not unicodedata.combining(c))
    words = "".join(c if c.isalpha() else " " for c in plain.upper()).split()
    keys = ["".join(words)] if words else []
    while words and words[0] in HONORIFICS:
        words = words[1:]
    if words and "".join(words) not in keys:
        keys.append("".join(words))
    return keys


def with_keys(frame: pl.DataFrame, column: str) -> pl.DataFrame:
    """One row per row of `frame` and key of `column` (`key`); rows without a key are dropped."""
    lookup = (
        frame.select(pl.col(column).unique())
        .drop_nulls()
        .with_columns(
            pl.col(column).map_elements(author_keys, return_dtype=pl.List(pl.Utf8)).alias("key")
        )
        .explode("key")
        .drop_nulls("key")
    )
    return frame.join(lookup, on=column, how="inner")


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
    return _read_member(zip_path, CGU_MEMBER, CGU_COLUMNS)


def read_amendment_years(zip_path: Path) -> tuple[pl.DataFrame, dict[str, int]]:
    """(`amendment`, `year`) of `EmendasParlamentares.csv`, one row per pair.

    Rows whose `Código da Emenda` is not a number (CGU's `Sem informação`) are skipped and
    counted. An `Ano da Emenda` that is not a four-digit year stops the build. Counts:
    `skipped` rows and `multi_year` codes with more than one year.
    """
    raw = _read_member(zip_path, AMENDMENTS_MEMBER, AMENDMENT_COLUMNS)
    code = pl.col("amendment").str.strip_chars()
    coded = raw.filter(code.str.contains(AMENDMENT_CODE).fill_null(False))
    year = pl.col("year").str.strip_chars()
    bad = coded.filter(~year.str.contains(r"^\d{4}$").fill_null(False)).height
    if bad:
        raise BuildError(f"{bad} amendment rows have an Ano da Emenda that is not a year")
    pairs = coded.select(code.alias("amendment"), year.cast(pl.Int64).alias("year")).unique()
    multi = pairs.group_by("amendment").len().filter(pl.col("len") > 1).height
    return pairs.sort("amendment", "year"), {
        "skipped": raw.height - coded.height,
        "multi_year": multi,
    }


def _read_member(zip_path: Path, member: str, columns: dict[str, str]) -> pl.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower() == member]
        if len(members) != 1:
            raise BuildError(f"expected one {member} member, found {len(members)}")
        data = zf.read(members[0])
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        header = next(csv.reader([text.split("\n", 1)[0].rstrip("\r")], delimiter=";"))
        raw = {h.strip(): h for h in header}
        if any(name not in raw for name in columns.values()):
            continue
        frame = pl.read_csv(
            text.encode("utf-8"),
            separator=";",
            quote_char='"',
            infer_schema=False,
            columns=[raw[name] for name in columns.values()],
        )
        return frame.rename({raw[name]: key for key, name in columns.items()})
    raise BuildError(f"no encoding (UTF-8, Latin-1) gives the expected header of {member}")


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
    out = joined.drop("year", "name_key", "muni", "uf", "placeholder").rename(
        {"uf_key": "recipient_uf"}
    )
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
    """Deputy, senate and senate-substitute candidacies: `cargo`, `sq`, `uf`, `party`,
    `elected`, `number` (ballot number), `name_urn`, `name_full` and, if asked, `cpf` (in
    memory only). Names are as written (`author_keys`
    normalises them); `elected` is `CD_SIT_TOT_TURNO` 1-3.
    """
    wanted = (
        "SQ_CANDIDATO",
        "CD_CARGO",
        "SG_UF",
        "NM_URNA_CANDIDATO",
        "NM_CANDIDATO",
        "NR_PARTIDO",
        "CD_SIT_TOT_TURNO",
        "NR_CANDIDATO",
    )
    raw = read_tse_csv(zip_path, tmp_dir, wanted, ("NR_CPF_CANDIDATO",) if with_cpf else ())
    if with_cpf and "NR_CPF_CANDIDATO" not in raw.columns:
        raise BuildError(f"{zip_path.name} lacks a column the build needs")
    rows = raw.with_columns(pl.col("CD_CARGO").cast(pl.Int64, strict=False).alias("cargo"))
    rows = rows.filter(pl.col("cargo").is_in([DEPUTY, SENATOR, *SENATE_SUBSTITUTES])).with_columns(
        pl.col("SQ_CANDIDATO").alias("sq"),
        pl.col("NR_CANDIDATO").str.strip_chars().alias("number"),
        pl.col("SG_UF").alias("uf"),
        pl.col("NR_PARTIDO").alias("party"),
        pl.col("CD_SIT_TOT_TURNO")
        .cast(pl.Int64, strict=False)
        .is_in(ELECTED_CODES)
        .fill_null(False)
        .alias("elected"),
    )
    rows = rows.with_columns(
        pl.col("NM_URNA_CANDIDATO").alias("name_urn"), pl.col("NM_CANDIDATO").alias("name_full")
    )
    keep = ["cargo", "sq", "uf", "party", "elected", "number", "name_urn", "name_full"]
    if with_cpf:
        rows = rows.with_columns(pl.col("NR_CPF_CANDIDATO").alias("cpf"))
        keep.append("cpf")
    return rows.select(keep)


def read_party_votes(
    zip_path: Path, tmp_dir: Path, munis: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, str], dict[str, int]]:
    """Valid votes per party, office and municipality of a general election's party-vote file.

    Federal (`CD_CARGO` 6) and state (7) deputies, round 1, summed over zones and over the
    coalition records a party can appear under in one zone. A party's votes are the nominal
    votes of its candidates plus its party-list votes (`PARTY_VOTE_PAIRS`). Rows whose TSE
    municipality is not in `municipalities` (votes abroad) are dropped and counted.

    Returns (`cargo`, `cd_ibge`, `party`, `votes`), the federation group of each party in a
    federation (`parties.federation_groups`, from `NR_FEDERACAO` where the file has it) and
    the counts `abroad` and `unmatched` (rows).
    """
    wanted = ("SG_UF", "CD_MUNICIPIO", "CD_CARGO", "NR_TURNO", "NR_PARTIDO")
    optional = ("NR_FEDERACAO", *{c for pair in PARTY_VOTE_PAIRS for c in pair})
    raw = read_tse_csv(zip_path, tmp_dir, wanted, tuple(sorted(optional)))
    pair = next((p for p in PARTY_VOTE_PAIRS if all(c in raw.columns for c in p)), None)
    if pair is None:
        raise BuildError(f"{zip_path.name} lacks a column the build needs")
    cargo = pl.col("CD_CARGO").cast(pl.Int64, strict=False)
    rows = raw.filter(
        cargo.is_in([DEPUTY, STATE_DEPUTY]) & (pl.col("NR_TURNO").cast(pl.Int64, strict=False) == 1)
    )
    parts = [pl.col(c).str.strip_chars().cast(pl.Int64, strict=False) for c in pair]
    if rows.filter(pl.any_horizontal(p.is_null() for p in parts)).height:
        raise BuildError(f"{zip_path.name}: a vote count is not an integer")
    groups: dict[str, str] = {}
    if "NR_FEDERACAO" in rows.columns:
        pairs = rows.select("NR_PARTIDO", "NR_FEDERACAO").unique().iter_rows()
        try:
            groups = parties.federation_groups(pairs)
        except parties.FederationError as err:
            raise BuildError(f"{zip_path.name}: {err}") from err
    rows = rows.with_columns(
        cargo.alias("cargo"),
        (parts[0] + parts[1]).alias("votes"),
        pl.col("NR_PARTIDO").str.strip_chars().alias("party"),
        pl.col("CD_MUNICIPIO").str.strip_chars().str.zfill(5).alias("cd_tse"),
    )
    joined = rows.join(munis.select("cd_tse", "cd_ibge"), on="cd_tse", how="left")
    missing = joined.filter(pl.col("cd_ibge").is_null())
    counts = {
        "abroad": missing.filter(pl.col("SG_UF") == "ZZ").height,
        "unmatched": missing.filter(pl.col("SG_UF") != "ZZ").height,
    }
    out = (
        joined.filter(pl.col("cd_ibge").is_not_null())
        .group_by(["cargo", "cd_ibge", "party"])
        .agg(pl.col("votes").sum())
        .sort(["cargo", "cd_ibge", "party"])
    )
    return out, groups, counts


class PartyVotes(NamedTuple):
    votes: pl.DataFrame  # cargo, cd_ibge, party, votes (`read_party_votes`)
    groups: dict[str, str]  # party -> federation group, for parties in a federation


def party_shares(
    panel: pl.DataFrame, cycle: Cycle, at_t0: PartyVotes, at_t1: PartyVotes
) -> tuple[pl.DataFrame, dict[str, list[str]]]:
    """Add `party_share_t0`, `party_share_t1`, `state_party_share_t0` and `state_party_share_t1`.

    The share of a year is the valid votes (nominal plus party list) of the deputy's party in
    the municipality over the valid votes of every party, for federal deputies (`party_*`) or
    state deputies (`state_party_*`). The party is `deputy_party` (the t0 number), followed to
    the year's number through mergers (`parties.successor`); where it is in a federation that
    year, the federation's votes count. Null where the municipality has no valid votes for
    the office that year.

    Also returns, per year (`t0`, `t1`), the groups of the panel's parties with no federal
    deputy votes anywhere that year (a merger `parties.MERGERS` lacks would show here).
    """
    numbers = sorted(panel["deputy_party"].drop_nulls().unique().to_list())
    missing: dict[str, list[str]] = {}
    out = panel
    for label, year, data in (("t0", cycle.t0, at_t0), ("t1", cycle.t1, at_t1)):
        lookup = pl.DataFrame(
            {
                "deputy_party": numbers,
                "group": [
                    parties.group_of(parties.successor(n, cycle.t0, year), data.groups)
                    for n in numbers
                ],
            },
            schema={"deputy_party": pl.Utf8, "group": pl.Utf8},
        )
        votes = data.votes
        names = votes["party"].unique().to_list()
        to_group = pl.DataFrame(
            {"party": names, "group": [parties.group_of(n, data.groups) for n in names]},
            schema={"party": pl.Utf8, "group": pl.Utf8},
        )
        grouped = (
            votes.join(to_group, on="party", how="left")
            .group_by(["cargo", "cd_ibge", "group"])
            .agg(pl.col("votes").sum().alias("group_votes"))
        )
        valid = votes.group_by(["cargo", "cd_ibge"]).agg(pl.col("votes").sum().alias("valid"))
        federal = set(grouped.filter(pl.col("cargo") == DEPUTY)["group"].to_list())
        missing[label] = sorted(set(lookup["group"].to_list()) - federal)
        out = out.join(lookup, on="deputy_party", how="left")
        offices = ((DEPUTY, f"party_share_{label}"), (STATE_DEPUTY, f"state_party_share_{label}"))
        for cargo, column in offices:
            g = grouped.filter(pl.col("cargo") == cargo).drop("cargo")
            v = valid.filter(pl.col("cargo") == cargo).drop("cargo")
            out = (
                out.join(g, on=["cd_ibge", "group"], how="left")
                .join(v, on="cd_ibge", how="left")
                .with_columns(
                    pl.when(pl.col("valid") > 0)
                    .then(pl.col("group_votes").fill_null(0) / pl.col("valid"))
                    .alias(column)
                )
                .drop("group_votes", "valid")
            )
        out = out.drop("group")
    return out.select([pl.col(n).cast(t) for n, t in SCHEMA.items()]), missing


# --- The author link (names are used in memory only)


def author_link(
    authors: pl.DataFrame, deputies: pl.DataFrame, senators: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Link each author (`aid`, `name`, `top_uf`) to a t0 deputy candidacy or a senator.

    `deputies` has `sq`, `uf`, `name_urn` and `name_full`; `senators` has `senator`, `uf`,
    `name_urn` and `name_full` (elected senate candidacies at t0 and t0-4). Names are compared
    by `author_keys`: an author matches a candidacy when any key of the author's name equals
    any key of the candidacy's urn or full name. `top_uf` is the state that received most of
    the author's money. Exactly one deputy candidacy matching: deputy. Several: only those of
    `top_uf` are kept (a tie broken), and exactly one left makes a deputy; otherwise the author
    is ambiguous, so unmatched. An author who is not a deputy and matches exactly one senate
    candidacy, by the same rules, is a senator. Returns `aid`, `kind` (deputy, senator or
    unmatched) and `sq` (set for deputies), and the counts.
    """
    author_long = with_keys(authors.select("aid", "name", "top_uf"), "name").select(
        "aid", "top_uf", "key"
    )

    def long(frame: pl.DataFrame, id_col: str) -> pl.DataFrame:
        parts = [
            with_keys(frame.select(id_col, "uf", column), column).select(id_col, "uf", "key")
            for column in ("name_urn", "name_full")
        ]
        return pl.concat(parts).unique()

    def matches(table: pl.DataFrame, id_col: str, n_name: str) -> pl.DataFrame:
        pairs = author_long.join(table, on="key", how="inner").select(
            "aid", id_col, (pl.col("uf") == pl.col("top_uf")).fill_null(False).alias("home")
        )
        pairs = pairs.group_by("aid", id_col).agg(pl.col("home").any())
        n_all = pl.col(id_col).n_unique()
        n_home = pl.col(id_col).filter(pl.col("home")).n_unique()
        return pairs.group_by("aid").agg(
            n_all.alias(n_name),
            n_home.alias(n_name + "_home"),
            pl.when(n_all == 1)
            .then(pl.col(id_col).first())
            .otherwise(pl.col(id_col).filter(pl.col("home")).first())
            .alias(id_col),
        )

    def resolved(n_name: str) -> pl.Expr:
        n, home = pl.col(n_name), pl.col(n_name + "_home")
        return (n == 1) | ((n > 1) & (home == 1))

    dep = matches(long(deputies, "sq"), "sq", "n_dep")
    sen = matches(long(senators, "senator"), "senator", "n_sen").drop("senator")
    table = (
        authors.select("aid")
        .join(dep, on="aid", how="left")
        .join(sen, on="aid", how="left")
        .with_columns(
            pl.col(c).fill_null(0) for c in ("n_dep", "n_dep_home", "n_sen", "n_sen_home")
        )
        .with_columns(
            pl.when(resolved("n_dep"))
            .then(pl.lit("deputy"))
            .when(resolved("n_sen"))
            .then(pl.lit("senator"))
            .otherwise(pl.lit("unmatched"))
            .alias("kind")
        )
        .with_columns(pl.when(pl.col("kind") == "deputy").then(pl.col("sq")).alias("sq"))
    )
    deputy = pl.col("kind") == "deputy"
    counts = {
        "authors": table.height,
        "deputies": table.filter(deputy).height,
        "senators": table.filter(pl.col("kind") == "senator").height,
        "ambiguous": table.filter((pl.col("n_dep") > 1) & ~deputy).height,
        "unmatched": table.filter(pl.col("kind") == "unmatched").height,
        "ties_broken": table.filter((pl.col("n_dep") > 1) & deputy).height,
    }
    return table.select("aid", "kind", "sq"), counts


def legislature(cycle: Cycle) -> tuple[int, int]:
    """The first and last `Ano da Emenda` of the legislature elected at t0: t0+2 to t0+5.

    The budget of year Y is voted, and amended, in year Y-1, so the amendments of budget year
    t0+1 were written by the outgoing legislature. (Authors of consecutive budget years overlap
    93-98% within a legislature and about half across t0+1 and t0+2.)
    """
    return cycle.t0 + 2, cycle.t0 + 5


def current_authors(author_years: pl.DataFrame, cycle: Cycle) -> pl.DataFrame:
    """(`code`, `author`) of the authors with at least one individual amendment whose
    `Ano da Emenda` falls in the cycle's legislature. `author_years` has `code`, `author`, `year`
    (null where the amendment has no year)."""
    return (
        author_years.filter(pl.col("year").is_between(*legislature(cycle)))
        .select("code", "author")
        .unique()
    )


def author_years(individual: pl.DataFrame, years: pl.DataFrame) -> pl.DataFrame:
    """(`code`, `author`, `year`): the `Ano da Emenda` of every individual amendment an author
    has a payment row for, in any month of the file. `year` is null where `Código da Emenda` has
    no year in `EmendasParlamentares.csv`."""
    code = pl.col("amendment").fill_null("").str.strip_chars()
    return (
        individual.select("code", "author", code.alias("amendment"))
        .unique()
        .join(years, on="amendment", how="left")
        .select("code", "author", "year")
        .unique()
    )


def top_uf(payments: pl.DataFrame) -> pl.DataFrame:
    """(`aid`, `top_uf`): the recipient state with the largest sum of `value` per author.

    Rows without a state (`recipient_uf` empty, null or `-1`) are left out; ties go to the
    first state in alphabetical order.
    """
    uf = pl.col("recipient_uf").fill_null("")
    return (
        payments.filter(~uf.is_in(PLACEHOLDER_UFS))
        .group_by("aid", "recipient_uf")
        .agg(pl.col("value").sum())
        .sort(["aid", "value", "recipient_uf"], descending=[False, True, False])
        .unique(subset=["aid"], keep="first", maintain_order=True)
        .select("aid", pl.col("recipient_uf").alias("top_uf"))
    )


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


def deputy_totals(sums: pl.DataFrame) -> pl.DataFrame:
    """(`deputy`, `den_pre`, `den_post`): per deputy, the sum over every municipality the
    deputy paid in the window (any state) of the municipality's total floored at 0. `sums`
    is `window_sums` of the payments with an identified municipality."""
    return sums.group_by("deputy").agg(
        pl.col("amend_pre_total").clip(lower_bound=0).sum().alias("den_pre"),
        pl.col("amend_post_total").clip(lower_bound=0).sum().alias("den_post"),
    )


def amendment_outcomes() -> list[pl.Expr]:
    """`amend_<w>_share` and `amend_<w>_log_pc` for the pre and post windows.

    share: the municipality's total (floored at 0) / the deputy's `den_<w>`; null where that
    is 0 or missing. log_pc: ln(1 + total floored at 0 / `population_m`), reais per inhabitant
    as the 0009 per-capita measure uses `population_m`; null where the population is null or 0.
    """
    pop = pl.col("population_m").cast(pl.Float64)
    out = []
    for w in ("pre", "post"):
        total = pl.col(f"amend_{w}_total").clip(lower_bound=0)
        den = pl.col(f"den_{w}").fill_null(0.0)
        out.append(pl.when(den > 0).then(total / den).alias(f"amend_{w}_share"))
        out.append(pl.when(pop > 0).then((1.0 + total / pop).log()).alias(f"amend_{w}_log_pc"))
    return out


def panel_keys(deputies: pl.DataFrame, mayors: Mayors, munis: pl.DataFrame) -> pl.DataFrame:
    """The rows of a cycle before any value: each deputy (`sq`, `uf`, `party`, `elected`)
    with each municipality of the deputy's state where the deputy's party had a finalist,
    with the finalist's race columns. `terrain.builds.amendments_monthly` uses the same rows.
    """
    base = deputies.select(
        pl.col("sq").alias("deputy"),
        "uf",
        pl.col("party").alias("deputy_party"),
        pl.col("elected").alias("deputy_elected"),
    )
    finalists = mayors.finalists.join(
        munis.select("cd_ibge", "uf"), on="cd_ibge", how="inner"
    ).rename({"party": "deputy_party"})
    return base.join(finalists, on=["uf", "deputy_party"], how="inner")


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
    """The panel rows of one cycle (every column but the party shares, which `party_shares`
    adds), and the number of deputies whose party number has no first-round mayoral candidate
    in the cycle's mayoral election (mergers).

    `deputies`: the deputies of the cycle (`sq`, `uf`, `party`, `elected`). `payments`:
    individual payments with `deputy` (t0 `sq`), `cd_ibge`, `ym`, `value`, `pix`. `votes0` and
    `votes1`: `uf`, `sq`, `cd_ibge`, `votes` at t0 and t1. `t1_link`: `sq`, `sq1`, `ran_t1`.
    """
    cycle = CYCLES[name]
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
    sums = window_sums(payments, cycle)
    rows = (
        panel_keys(deputies, mayors, munis)
        .join(held, on=["cd_ibge", "deputy_party"], how="left")
        .join(mayors.n_cands, on="cd_ibge", how="left")
        .join(pop, on="cd_ibge", how="left")
        .join(sums, on=["deputy", "cd_ibge"], how="left")
        .join(deputy_totals(sums), on="deputy", how="left")
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
    rows = rows.with_columns(
        _share("votes_t1", "valid_t1").alias("share_t1"), *amendment_outcomes()
    ).with_columns((pl.col("share_t1") - pl.col("share_t0")).alias("d_share"))
    columns = [pl.col(n).cast(t) for n, t in SCHEMA.items() if n not in PARTY_SHARES]
    panel = rows.select(columns).sort(["deputy", "cd_ibge"])
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
        for column in PARTY_SHARES:
            bad = table.filter(
                (pl.col(column) < -TOLERANCE) | (pl.col(column) > 1 + TOLERANCE)
            ).height
            if bad:
                raise BuildError(f"{name}: {bad} rows have {column} outside [0, 1]")
        for column in PAYMENTS:
            bad = table.filter(pl.col(column) < 0).height
            if bad:
                raise BuildError(f"{name}: {bad} rows have {column} below 0")
        for column in LOGS:
            bad = table.filter(pl.col(column) < -TOLERANCE).height
            if bad:
                raise BuildError(f"{name}: {bad} rows have {column} below 0")
        if table.height < min_rows or table.height > max_rows:
            raise BuildError(f"{name}: {table.height} rows, outside {min_rows}-{max_rows}")


def outcome_nulls(panel: pl.DataFrame) -> dict[str, int]:
    """Rows (both halves) where each share or log outcome is null: a share whose deputy has
    no positive payment with an identified municipality in the window, or no population."""
    return {c: panel[c].null_count() for c in (*SHARES[2:], *LOGS)}


def _money(counts: dict[str, Any]) -> str:
    def share(x: float | None) -> str:
        return "none" if x is None else f"{x:.4f}"

    return (
        f"money_share={share(counts['money_share'])}, "
        f"money_share_with_unidentified={share(counts['money_share_with_unidentified'])}, "
        f"window_value_brl={counts['window_value']:.2f}, "
        f"current_value_brl={counts['current_value']:.2f}, "
        f"deputy_value_brl={counts['deputy_value']:.2f}, "
        f"senator_value_brl={counts['senator_value']:.2f}, "
        f"non_current_rows={counts['non_current_rows']}, "
        f"non_current_value_brl={counts['non_current_value']:.2f}, "
        f"unidentified_author_rows={counts['unidentified_rows']}, "
        f"unidentified_author_value_brl={counts['unidentified_value']:.2f}"
    )


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


def party_entries(manifest: dict[str, Any], cycles: tuple[str, ...]) -> dict[int, dict[str, Any]]:
    """The tse_general_parties zips the cycles need (t0 and t1), by year."""
    years = sorted({y for c in cycles for y in (CYCLES[c].t0, CYCLES[c].t1)})
    return {y: _file(manifest, f"/votacao_partido_munzona_{y}.zip") for y in years}


def _party_votes(
    store: Store, entry: dict[str, Any], tmp_dir: Path, munis: pl.DataFrame
) -> tuple[PartyVotes, dict[str, int]]:
    path = _fetch(store, entry, tmp_dir)
    try:
        votes, groups, counts = read_party_votes(path, tmp_dir, munis)
    finally:
        path.unlink(missing_ok=True)
    return PartyVotes(votes, groups), counts


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
    """The senate seats of the legislature: elected senate candidacies at t0 and t0-4, and the
    substitutes (`SENATE_SUBSTITUTES`) on their tickets (same election, state and ballot
    number), each with `senator`: the year and `sq`.

    A substitute who took the seat writes amendments as a senator.
    """
    parts = []
    for frame, year in ((old, t0 - 4), (new, t0)):
        elected = frame.filter((pl.col("cargo") == SENATOR) & pl.col("elected"))
        tickets = elected.select("uf", "number").unique()
        substitutes = frame.filter(pl.col("cargo").is_in(SENATE_SUBSTITUTES)).join(
            tickets, on=["uf", "number"], how="semi"
        )
        parts.append(
            pl.concat([elected, substitutes]).select(
                pl.concat_str([pl.lit(f"{year}:"), pl.col("sq")]).alias("senator"),
                "uf",
                "name_urn",
                "name_full",
            )
        )
    return pl.concat(parts)


def read_chamber(path: Path) -> pl.DataFrame:
    """`chamber_name`, `civil_name`, `leg_first`, `leg_last` of the Chamber's `deputados.csv`.

    Stops if a needed column is missing or a legislature number is not an integer.
    """
    raw = pl.read_csv(
        path, separator=";", quote_char='"', infer_schema=False, encoding="utf8-lossy"
    )
    raw = raw.rename({c: c.lstrip("\ufeff") for c in raw.columns})
    if [c for c in CHAMBER_COLUMNS if c not in raw.columns]:
        raise BuildError(f"{path.name} lacks a column the build needs")
    frame = raw.select(list(CHAMBER_COLUMNS)).rename(CHAMBER_COLUMNS)
    legs = [
        pl.col(c).str.strip_chars().cast(pl.Int64, strict=False) for c in ("leg_first", "leg_last")
    ]
    bad = frame.filter(pl.any_horizontal(e.is_null() for e in legs)).height
    if bad:
        raise BuildError(f"{path.name}: {bad} rows have a legislature that is not a number")
    return frame.with_columns(legs)


def legislature_number(cycle: Cycle) -> int:
    """The Chamber's number of the legislature elected at t0 (55 for 2014)."""
    return 55 + (cycle.t0 - 2014) // 4


def chamber_names(
    chamber: pl.DataFrame, base: pl.DataFrame, cycle: Cycle
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Each deputy of the cycle's legislature on the Chamber's list, by parliamentary name,
    as an extra name of the t0 deputy candidacy whose civil name it matches.

    A Chamber row matches a candidacy when a key (`author_keys`) of its `civil_name` equals a
    key of the candidacy's `name_full` (TSE's civil name). Rows that match no candidacy or
    several are left out and counted. Returns (`sq`, `uf`, `name_urn` = the Chamber name,
    `name_full` = null) and the counts `rows`, `added`, `none` and `several`.
    """
    number = legislature_number(cycle)
    rows = chamber.filter(
        (pl.col("leg_first") <= number) & (pl.col("leg_last") >= number)
    ).with_row_index("cid")
    civil = with_keys(rows.select("cid", "civil_name"), "civil_name").select("cid", "key")
    full = with_keys(base.select("sq", "name_full"), "name_full").select("sq", "key")
    hits = civil.join(full, on="key", how="inner").group_by("cid").agg(pl.col("sq").unique())
    one = hits.filter(pl.col("sq").list.len() == 1).with_columns(pl.col("sq").list.first())
    extra = (
        one.join(rows.select("cid", "chamber_name"), on="cid", how="inner")
        .join(base.select("sq", "uf"), on="sq", how="inner")
        .select(
            "sq",
            "uf",
            pl.col("chamber_name").alias("name_urn"),
            pl.lit(None, dtype=pl.Utf8).alias("name_full"),
        )
        .sort("sq", "name_urn")
    )
    return extra, {
        "rows": rows.height,
        "added": one.height,
        "none": rows.height - hits.height,
        "several": hits.height - one.height,
    }


def link_cycle(
    name: str,
    payments: pl.DataFrame,
    author_years: pl.DataFrame,
    base: pl.DataFrame,
    senators: pl.DataFrame,
    extra_names: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """The author link of one cycle and its counts.

    `extra_names` (`sq`, `uf`, `name_urn`, `name_full`) adds names to t0 deputy candidacies
    (the Chamber's parliamentary names, `chamber_names`).

    `payments`: individual payments (`amendment`, `code`, `author`, `ym`, `value`,
    `recipient_uf`, `cd_ibge`, `pix`). Only the cycle's window rows are used. An author is
    (`code`, normalised `author`). Authors with no individual amendment of the cycle's
    legislature (`current_authors`) are left out with all their payments, which are counted:
    `non_current_*`, and of them the rows with no amendment code (CGU's unidentified author),
    `unidentified_*`. The rest are linked by `author_link`.

    Returns the window rows of the authors linked as deputies, with `deputy` (t0 `sq`), the
    counts (the `author_link` counts, `non_current_authors`, `money_share` = linked deputy
    value / (value of current-legislature authors - senators' value), null if that is 0, and
    the value sums behind it, reais, nominal) and the authors linked as deputies (`code`,
    `name_norm`, `deputy`), in memory only, for payments outside the windows
    (`terrain.builds.amendments_monthly`).
    """
    cy = CYCLES[name]
    mine = payments.filter(in_windows((name,))).with_columns(pl.col("code").fill_null(""))
    mine = with_norm(mine, "author", "name_norm")
    current = (
        with_norm(
            current_authors(author_years, cy).with_columns(pl.col("code").fill_null("")),
            "author",
            "name_norm",
        )
        .select("code", "name_norm")
        .unique()
    )
    keys = ["code", "name_norm"]
    kept = mine.join(current, on=keys, how="semi")
    left_out = mine.join(current, on=keys, how="anti")
    no_code = ~pl.col("amendment").fill_null("").str.strip_chars().str.contains(AMENDMENT_CODE)
    unidentified = left_out.filter(no_code)
    authors = (
        kept.group_by(keys)
        .agg(pl.col("author").min().alias("name"))
        .sort(keys)
        .with_row_index("aid")
    )
    rows = kept.join(authors.select("aid", *keys), on=keys, how="inner")
    authors = authors.join(top_uf(rows), on="aid", how="left")
    names = base.select("sq", "uf", "name_urn", "name_full")
    if extra_names is not None:
        names = pl.concat([names, extra_names.select(names.columns)])
    link, counts = author_link(authors.select("aid", "name", "top_uf"), names, senators)
    valued = rows.join(link, on="aid", how="inner")

    def total(frame: pl.DataFrame) -> float:
        return float(frame["value"].sum()) if frame.height else 0.0

    value_all = total(valued)
    value_deputy = total(valued.filter(pl.col("kind") == "deputy"))
    value_senator = total(valued.filter(pl.col("kind") == "senator"))
    pool = value_all - value_senator
    with_unidentified = pool + total(unidentified)
    counts |= {
        "non_current_authors": left_out.select(keys).unique().height,
        "non_current_rows": left_out.height,
        "non_current_value": total(left_out),
        "unidentified_rows": unidentified.height,
        "unidentified_value": total(unidentified),
        "window_value": total(mine),
        "current_value": value_all,
        "deputy_value": value_deputy,
        "senator_value": value_senator,
        "money_share": value_deputy / pool if pool else None,
        "money_share_with_unidentified": (
            value_deputy / with_unidentified if with_unidentified else None
        ),
    }
    linked = valued.filter(pl.col("kind") == "deputy").rename({"sq": "deputy"})
    author_map = (
        authors.join(link.filter(pl.col("kind") == "deputy"), on="aid", how="inner")
        .select(*keys, pl.col("sq").alias("deputy"))
        .sort(keys)
    )
    return linked, counts, author_map


class CycleLink(NamedTuple):
    deputies: pl.DataFrame  # sq, uf, party, elected, cpf (in memory only)
    linked: pl.DataFrame  # window payment rows of the authors linked as deputies, with `deputy`
    counts: dict[str, Any]  # `link_cycle` counts, `chamber_links` and `chamber`
    author_map: pl.DataFrame  # code, name_norm, deputy (in memory only)


def cycle_link(
    name: str,
    store: Store,
    general: dict[tuple[str, int], dict[str, Any]],
    payments: pl.DataFrame,
    author_years: pl.DataFrame,
    chamber: pl.DataFrame,
    tmp_dir: Path,
) -> CycleLink:
    """The deputies of one cycle and the author link: t0 deputy candidacies that were elected
    or are linked as authors with a payment in the cycle's windows (`link_cycle`). Reads the
    t0-4 and t0 candidacies only. `terrain.builds.amendments_monthly` uses the same link."""
    cy = CYCLES[name]
    old = _candidacies(store, general[("consulta_cand", cy.t0 - 4)], tmp_dir, with_cpf=False)
    cand0 = _candidacies(store, general[("consulta_cand", cy.t0)], tmp_dir, with_cpf=True)
    base = cand0.filter(pl.col("cargo") == DEPUTY)
    if base["sq"].is_duplicated().any():
        raise BuildError(f"{name}: a candidacy appears twice in the t0 candidates")
    senators = _senators(old, cand0, cy.t0)
    extra, chamber_counts = chamber_names(chamber, base, cy)
    linked, counts, author_map = link_cycle(name, payments, author_years, base, senators, extra)
    counts["chamber_links"] = chamber_counts["added"]
    counts["chamber"] = chamber_counts
    served = linked["deputy"].unique().to_list()
    deputies = base.filter(pl.col("elected") | pl.col("sq").is_in(served))
    return CycleLink(
        deputies.select("sq", "uf", "party", "elected", "cpf"), linked, counts, author_map
    )


def cycle_inputs(
    name: str,
    store: Store,
    general: dict[tuple[str, int], dict[str, Any]],
    payments: pl.DataFrame,
    author_years: pl.DataFrame,
    chamber: pl.DataFrame,
    munis: pl.DataFrame,
    tmp_dir: Path,
) -> dict[str, Any]:
    """Everything of one cycle that comes from the TSE general elections and the CGU rows:
    the deputies of the cycle, their payments, the t1 link and the votes at t0 and t1."""
    cy = CYCLES[name]
    tse_munis = munis.filter(pl.col("cd_tse").is_not_null())
    link = cycle_link(name, store, general, payments, author_years, chamber, tmp_dir)
    cand1 = _candidacies(store, general[("consulta_cand", cy.t1)], tmp_dir, with_cpf=True)
    votes0, dropped0 = _votes(
        store, general[("votacao_candidato_munzona", cy.t0)], tmp_dir, tse_munis
    )
    votes1, dropped1 = _votes(
        store, general[("votacao_candidato_munzona", cy.t1)], tmp_dir, tse_munis
    )
    deputies = link.deputies
    paid = link.linked.filter(pl.col("cd_ibge").is_not_null()).select(
        "deputy", "cd_ibge", "ym", "value", "pix"
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
        "counts": link.counts,
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
    chamber_manifest: dict[str, Any],
    parties_manifest: dict[str, Any],
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
    party_files = party_entries(parties_manifest, cycles)
    cgu_entry = _file(cgu_manifest, "/EmendasParlamentares.zip")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    pop_entry = _file(population_manifest, "/ibge_population_annual.parquet")
    chamber_entry = _file(chamber_manifest, "/deputados.csv")
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
        chamber_entry,
        *general.values(),
        *party_files.values(),
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

    chamber_path = _fetch(store, chamber_entry, tmp_dir)
    try:
        chamber = read_chamber(chamber_path)
    finally:
        chamber_path.unlink(missing_ok=True)

    cgu_path = _fetch(store, cgu_entry, tmp_dir)
    try:
        raw = read_cgu(cgu_path)
        years, year_stats = read_amendment_years(cgu_path)
    finally:
        cgu_path.unlink(missing_ok=True)
    individual, stats = parse_payments(raw)
    del raw
    check_payment_stats(stats)
    negative_rows, negative_value = negative_payments(individual)
    years_by_author = author_years(individual, years)
    no_year = individual.join(
        years,
        left_on=pl.col("amendment").fill_null("").str.strip_chars(),
        right_on="amendment",
        how="anti",
    ).height
    windowed = individual.filter(in_windows(cycles))
    del individual
    paid, dropped = match_recipients(windowed, munis)

    tse_munis = munis.filter(pl.col("cd_tse").is_not_null())
    party_votes: dict[int, PartyVotes] = {}
    party_dropped: dict[int, dict[str, int]] = {}
    for year, party_entry in party_files.items():
        party_votes[year], party_dropped[year] = _party_votes(
            store, party_entry, tmp_dir, tse_munis
        )

    tables: dict[str, pl.DataFrame] = {}
    links: list[dict[str, Any]] = []
    notes: list[str] = []
    explore_ids = sorted(explore)
    for name in cycles:
        cy = CYCLES[name]
        parts = cycle_inputs(name, store, general, paid, years_by_author, chamber, munis, tmp_dir)
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
        panel, no_votes = party_shares(panel, cy, party_votes[cy.t0], party_votes[cy.t1])
        panel, floored = floor_payments(panel)
        tables[name] = panel
        counts = parts["counts"]
        links.append({k: counts.get(k, name) for k in LINK_SCHEMA} | {"cycle": name})
        chamber_counts = counts["chamber"]
        half = panel.filter(pl.col("cd_ibge").is_in(explore_ids))
        notes.append(
            f"{name}: rows={half.height}, deputies={half['deputy'].n_unique()}, "
            f"authors={counts['authors']}, deputy_authors={counts['deputies']}, "
            f"senator_authors={counts['senators']}, ambiguous_authors={counts['ambiguous']}, "
            f"unmatched_authors={counts['unmatched']}, ties_broken={counts['ties_broken']}, "
            f"non_current_authors={counts['non_current_authors']}, "
            f"unlinked_cpfs={parts['unlinked']}, "
            f"party_without_mayor_cands={mergers}, "
            f"vote_rows_abroad={parts['dropped_votes']['abroad']}, "
            f"vote_rows_no_municipality={parts['dropped_votes']['unmatched']}"
        )
        notes.append(f"{name}_floored_to_zero=" + ",".join(f"{c}:{n}" for c, n in floored.items()))
        notes.append(f"{name}_link: " + _money(counts))
        notes.append(
            f"{name}_chamber: rows={chamber_counts['rows']}, "
            f"names_added={chamber_counts['added']}, no_candidacy={chamber_counts['none']}, "
            f"several_candidacies={chamber_counts['several']}"
        )
        nulls = outcome_nulls(panel)
        notes.append(f"{name}_outcome_nulls=" + ",".join(f"{c}:{n}" for c, n in nulls.items()))
        notes.append(
            f"{name}_party_shares: "
            + ", ".join(f"{c}_nulls={panel[c].null_count()}" for c in PARTY_SHARES)
            + ", groups_without_votes_t0="
            + ("+".join(no_votes["t0"]) or "none")
            + ", groups_without_votes_t1="
            + ("+".join(no_votes["t1"]) or "none")
        )
        del parts

    for year in sorted(party_votes):
        groups = party_votes[year].groups
        federations = sorted({g for g in groups.values()})
        listed = ",".join(
            f"{f}=" + "+".join(sorted(p for p, g in groups.items() if g == f)) for f in federations
        )
        notes.append(
            f"party_votes_{year}: rows={party_votes[year].votes.height}, "
            f"rows_abroad={party_dropped[year]['abroad']}, "
            f"rows_no_municipality={party_dropped[year]['unmatched']}, "
            f"federations={listed or 'none'}"
        )
    notes.append(f"dropped_recipient_rows_no_municipality={_years(dropped['no_municipality'])}")
    notes.append(f"dropped_recipient_rows_unmatched={_years(dropped['unmatched'])}")
    notes.extend(placeholder_notes(dropped))
    notes.append(f"negative_payment_rows={_years(negative_rows)}")
    notes.append(f"negative_payment_value_brl={_years(negative_value, '.2f')}")
    notes.append(f"first_payment_month={_month(stats['first'])}, last={_month(stats['last'])}")
    notes.append(f"rows_without_payment_month={stats['no_month']}")
    notes.append(
        f"amendment_rows_without_code={year_stats['skipped']}, "
        f"amendment_codes_with_several_years={year_stats['multi_year']}, "
        f"individual_payment_rows_without_amendment_year={no_year}"
    )

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
                chamber_manifest,
                parties_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
