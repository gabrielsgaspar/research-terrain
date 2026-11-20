"""Mayoral races 2004-2020 with what happened four years later: the incumbency panel (idea 0011).

Contract of the output: data/contracts/mayor_incumbency_panel.md. Decisions 0003 and 0011. The
models are `terrain.builds.amendments_panel` (mayoral races, the CGU payments; imported) and
`terrain.builds.politics_panel` (the derived/sealed split, CPF links in memory).

One row per municipality, mayoral election e (2004 to 2020) and finalist party: the two
candidacies with most votes in the deciding round. Each row holds the race (margin, win, the
finalist's attributes, whether the party held the mayoralty at e-4, the size of its federal
bench in the state at e-2), what happened at e+4 (did the party and the finalist run and
win; could the finalist run at all) and the individual amendment money paid to the
municipality during the term. Rows of exploration-half municipalities (both exploration
lists) go to the derived folder; every other row goes to a sealed folder that this build only
creates in and never reads.

Candidate CPFs are used only in memory, to link a finalist to e-4 and e+4 in the same
municipality. No CPF, voter ID, name or hash of one is written to a column, a note or an
exception message. `Código do Favorecido` and `Favorecido` are never read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from terrain import explore as terrain_explore
from terrain import parties
from terrain.builds import amendments_panel as ap
from terrain.builds import cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.amendments_panel import _fetch_frame
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.profile import write_profile
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "mayor_incumbency_panel"
ELECTIONS = (2004, 2008, 2012, 2016, 2020)
STEP = 4
MAYOR = 11
DEPUTY = 6
VALID = "Válido"
FEMALE = ap.FEMALE
HIGHER_ED = ap.HIGHER_ED
CPF_PATTERN = r"^\d{11}$"
TITULO_PATTERN = r"^\d{12}$"  # título eleitoral
MIN_KEY_SHARE = 0.98  # round-1 mayoral candidacies of a year with a CPF or título to link by
# The general election two years before e whose federal deputies make the bench (none for
# 2004 and 2008: the federal-deputy files start in 2010).
BENCH_YEAR = {2012: 2010, 2016: 2014, 2020: 2018}
# `CD_SIT_TOT_TURNO` of an elected federal deputy. 2010 files use 1 (ELEITO) and 5 (MÉDIA),
# with 2 for SUPLENTE; from 2014, 1 (ELEITO), 2 (ELEITO POR QP) and 3 (ELEITO POR MÉDIA).
ELECTED_CODES = {2010: (1, 5)}
ELECTED_CODES_LATER = (1, 2, 3)
FEDERAL_SEATS = 513  # elected federal deputies in each general election
MIN_RACES = 5000  # two-finalist races per election (both halves)
MAX_RACES = 5600
TOLERANCE = 1e-9
LAST_PAYMENT_MONTH = 9  # the term's window stops in September of e+4, before the election

VOTES_COLUMNS = (
    "cd_cargo",
    "nr_turno",
    "cd_eleicao",
    "sg_ue",
    "sq_candidato",
    "qt_votos_nominais",
    "qt_votos_nominais_validos",
    "nm_tipo_destinacao_votos",
    "cd_ibge",
)
TURNOUT_COLUMNS = ap.TURNOUT_COLUMNS
CANDIDATE_COLUMNS = (*ap.CANDIDATE_COLUMNS, "nr_cpf_candidato", "nr_titulo_eleitoral_candidato")
COALITION_COLUMNS = ("nr_partido", "nr_federacao")
POPULATION_COLUMNS = ap.POPULATION_COLUMNS
MUNICIPALITY_COLUMNS = ap.MUNICIPALITY_COLUMNS

SCHEMA: dict[str, Any] = {
    "election": pl.Int64,
    "cd_ibge": pl.Utf8,
    "uf": pl.Utf8,
    "party": pl.Utf8,
    "round": pl.Int64,
    "margin": pl.Float64,
    "win": pl.Boolean,
    "fin_female": pl.Boolean,
    "fin_age": pl.Int64,
    "fin_higher_ed": pl.Boolean,
    "party_held_mayor_lag": pl.Boolean,
    "population_e": pl.Int64,
    "ln_pop": pl.Float64,
    "n_mayor_cands": pl.Int64,
    "bench_fed": pl.Int64,
    "party_next": pl.Utf8,
    "party_runs_next": pl.Boolean,
    "party_wins_next": pl.Boolean,
    "finalist_runs_next": pl.Boolean,
    "finalist_wins_next": pl.Boolean,
    "finalist_eligible": pl.Boolean,
    "amend_after_total": pl.Float64,
    "amend_after_pix": pl.Float64,
}
PAYMENTS = ("amend_after_total", "amend_after_pix")

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, `amendments_panel` (races, CGU payments, recipient matching), `parties`
# (mergers and federations), `explore` (the exploration lists), `place_outcomes`
# (`read_lists`), `cell_outcomes` (the list parser and the upload) and `polling_place_tenure`
# (`_file` picks the inputs, `_fetch` checks their SHA-256).
CODE_MODULES = (
    Path(__file__),
    Path(ap.__file__),
    Path(parties.__file__),
    Path(terrain_explore.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def output_name(election: int) -> str:
    return f"panel_{election}.parquet"


def code_sources(modules: tuple[Path, ...] | None = None) -> list[str]:
    return [
        m.read_text(encoding="utf-8") for m in sorted(CODE_MODULES if modules is None else modules)
    ]


def input_hash(
    files: list[dict[str, Any]],
    split_shas: list[str],
    elections: tuple[int, ...] = ELECTIONS,
    code: list[str] | None = None,
) -> str:
    shas = ",".join(sorted(f["sha256"] for f in files))
    sources = code_sources() if code is None else code
    spec = ",".join(str(e) for e in sorted(elections))
    return content_hash(shas, ",".join(split_shas), spec, *sources)


def result_years(elections: tuple[int, ...]) -> list[int]:
    """The municipal elections the panel reads: e-4, e and e+4 of each election."""
    return sorted({y for e in elections for y in (e - STEP, e, e + STEP)})


def after_window(election: int) -> tuple[int, int]:
    """The payment months (YYYYMM) of the term that starts after `election`: January of e+1
    to September of e+4, the last month before the next election."""
    return (election + 1) * 100 + 1, (election + STEP) * 100 + LAST_PAYMENT_MONTH


KEYS = ("cpf_key", "tit_key")  # in memory only: never in an output, note or message


def _key(column: str, pattern: str) -> pl.Expr:
    """The identifier, stripped, where it has exactly the pattern's digits; else null. Never
    padded or otherwise recoded: 2012 holds some CPFs without their leading zeros, and 2024
    holds no CPF at all, so the título links those."""
    value = pl.col(column).str.strip_chars()
    return pl.when(value.str.contains(pattern).fill_null(False)).then(value)


def _linkable() -> pl.Expr:
    return pl.col("cpf_key").is_not_null() | pl.col("tit_key").is_not_null()


def _flag_match(frame: pl.DataFrame, target: pl.DataFrame, name: str) -> pl.DataFrame:
    """Add `name`: the row's CPF or título is one of `target`'s in the same municipality."""
    flags = []
    for i, key in enumerate(KEYS):
        found = (
            target.filter(pl.col(key).is_not_null())
            .select("cd_ibge", key)
            .unique()
            .with_columns(pl.lit(True).alias(f"_m{i}"))
        )
        frame = frame.join(found, on=["cd_ibge", key], how="left")
        flags.append(pl.col(f"_m{i}").fill_null(False))
    return frame.with_columns(pl.any_horizontal(flags).alias(name)).drop(
        [f"_m{i}" for i in range(len(KEYS))]
    )


# --- One municipal election


class MayorYear(NamedTuple):
    finalists: pl.DataFrame  # one row per finalist of a two-finalist race (KEYS in memory)
    winners: pl.DataFrame  # cd_ibge, party, KEYS: the top candidacy of the deciding round
    runners: pl.DataFrame  # cd_ibge, party, KEYS: round-1 candidacies with votes above 0
    held: frozenset[str]  # municipalities with a round-1 mayoral election
    n_cands: pl.DataFrame  # cd_ibge, n_mayor_cands
    counts: dict[str, int]  # races, no_party, same_party, one_candidate, ties


def candidacy_votes(rows: pl.DataFrame) -> pl.DataFrame:
    """Votes per candidacy, summed over zones; candidacies without votes are dropped.

    A row counts if its destination is null (2000-2012) or exactly `Válido` (2016 on;
    annulled votes are left out). Votes are `qt_votos_nominais_validos`, or
    `qt_votos_nominais` where that is null: the 2000 file holds the votes in the valid column
    and 0 in the other; 2004-2012 have no valid column.
    """
    destination = pl.col("nm_tipo_destinacao_votos")
    kept = rows.filter(destination.is_null() | (destination == VALID))
    votes = pl.coalesce(
        pl.col("qt_votos_nominais_validos").cast(pl.Float64),
        pl.col("qt_votos_nominais").cast(pl.Float64),
    )
    return (
        kept.group_by(["sg_ue", "sq_candidato"], maintain_order=True)
        .agg(
            votes.sum().alias("votes"),
            pl.col("cd_ibge").first(),
            pl.col("runoff").first(),
        )
        .filter(pl.col("votes") > 0)
    )


def deciding_round(cv: pl.DataFrame, main: int) -> pl.DataFrame:
    """Mayoral rows of each municipality's deciding round, with a `runoff` flag.

    Round 2 (`nr_turno` 2 under `main` or `main + 1`, as the files of different years code
    it) where the municipality has one, else round 1 under `main`. Rows of other elections
    (supplementary) are dropped.
    """
    mayor = cv.filter(pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR).with_columns(
        pl.col("cd_eleicao").cast(pl.Int64, strict=False),
        pl.col("nr_turno").cast(pl.Int64, strict=False),
    )
    round2 = mayor.filter((pl.col("nr_turno") == 2) & pl.col("cd_eleicao").is_in([main, main + 1]))
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


def attributes(attrs: pl.DataFrame, year: int, main: int) -> pl.DataFrame:
    """One row per candidacy of `year` (`sg_ue`, `sq_candidato`): party, gender, birth date,
    education, election date, and CPF and título as link keys (in memory only). Round 1
    (`main`) wins over round 2."""
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
            pl.col("nr_partido").str.strip_chars().alias("party"),
            "cd_genero",
            "dt_nascimento",
            "cd_grau_instrucao",
            "dt_eleicao",
            _key("nr_cpf_candidato", CPF_PATTERN).alias("cpf_key"),
            _key("nr_titulo_eleitoral_candidato", TITULO_PATTERN).alias("tit_key"),
        )
    )


def mayor_year(
    cv: pl.DataFrame, turnout: pl.DataFrame, attrs: pl.DataFrame, year: int, *, check_codes: bool
) -> MayorYear:
    """The finalists, the winner and the round-1 candidacies of each municipality in `year`."""
    main = ap.main_election(cv)
    rows = deciding_round(cv, main)
    votes = candidacy_votes(rows)
    cattrs = attributes(attrs, year, main)
    if check_codes:
        ap.check_candidate_codes(votes, cattrs, year)
    pairs = ap.races(votes, ap.valid_votes_mayor(turnout, rows)).join(
        cattrs, on=["sg_ue", "sq_candidato"], how="left"
    )
    per_race = pairs.group_by("sg_ue").agg(
        pl.col("party").null_count().alias("no_party"),
        pl.col("party").n_unique().alias("parties"),
    )
    no_party = per_race.filter(pl.col("no_party") > 0)["sg_ue"].to_list()
    same_party = per_race.filter((pl.col("no_party") == 0) & (pl.col("parties") < 2))
    dropped = [*no_party, *same_party["sg_ue"].to_list()]
    pairs = pairs.filter(~pl.col("sg_ue").is_in(dropped))
    margin = (pl.col("own") - pl.col("other")) / pl.col("valid")
    birth, date = pl.col("dt_nascimento"), pl.col("dt_eleicao")

    def month_day(d: pl.Expr) -> pl.Expr:  # cast first: month * 100 overflows Int8
        return d.dt.month().cast(pl.Int64) * 100 + d.dt.day().cast(pl.Int64)

    before_birthday = month_day(date) < month_day(birth)
    finalists = pairs.select(
        "cd_ibge",
        "party",
        pl.when(pl.col("runoff")).then(2).otherwise(1).cast(pl.Int64).alias("round"),
        margin.alias("margin"),
        (pl.col("cd_genero") == FEMALE).alias("fin_female"),
        (date.dt.year() - birth.dt.year() - before_birthday.cast(pl.Int64))
        .cast(pl.Int64)
        .alias("fin_age"),
        (pl.col("cd_grau_instrucao") == HIGHER_ED).alias("fin_higher_ed"),
        *KEYS,
    )
    winners = (
        votes.sort(["sg_ue", "votes", "sq_candidato"], descending=[False, True, False])
        .unique(subset=["sg_ue"], keep="first", maintain_order=True)
        .join(cattrs, on=["sg_ue", "sq_candidato"], how="left")
        .select("cd_ibge", "party", *KEYS)
    )
    first = cv.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
        & (pl.col("cd_eleicao").cast(pl.Int64, strict=False) == main)
    ).with_columns(pl.lit(False).alias("runoff"))
    held = frozenset(first["cd_ibge"].drop_nulls().unique().to_list())
    first_votes = candidacy_votes(first)
    runners = first_votes.join(cattrs, on=["sg_ue", "sq_candidato"], how="left").select(
        "cd_ibge", "party", *KEYS
    )
    n_cands = first_votes.group_by("cd_ibge").agg(pl.len().cast(pl.Int64).alias("n_mayor_cands"))
    one = votes.group_by("sg_ue").len().filter(pl.col("len") == 1).height
    counts = {
        "races": finalists.height // 2,
        "no_party": len(no_party),
        "same_party": same_party.height,
        "one_candidate": one,
        "ties": finalists.filter(pl.col("margin").abs() <= TOLERANCE).height // 2,
    }
    return MayorYear(finalists, winners, runners, held, n_cands, counts)


# --- What happened four years before and after


def with_successor(frame: pl.DataFrame, column: str, from_year: int, to_year: int) -> pl.DataFrame:
    """Add `<column>_then`: the party number `column` (of `from_year`) at `to_year`."""
    names = frame[column].drop_nulls().unique().to_list()
    lookup = pl.DataFrame(
        {
            column: names,
            f"{column}_then": [parties.successor(n, from_year, to_year) for n in names],
        },
        schema={column: pl.Utf8, f"{column}_then": pl.Utf8},
    )
    return frame.join(lookup, on=column, how="left")


def _grouped(frame: pl.DataFrame, column: str, groups: dict[str, str], name: str) -> pl.DataFrame:
    names = frame[column].drop_nulls().unique().to_list()
    lookup = pl.DataFrame(
        {column: names, name: [parties.group_of(n, groups) for n in names]},
        schema={column: pl.Utf8, name: pl.Utf8},
    )
    return frame.join(lookup, on=column, how="left")


def lag_columns(finalists: pl.DataFrame, before: MayorYear | None, e: int) -> pl.DataFrame:
    """`party_held_mayor_lag` (the party, followed through mergers, had the top candidacy of
    the deciding round at e-4; false where there was no result) and `finalist_eligible` (the
    finalist's CPF or título is not the e-4 winner's in the municipality; null if the finalist
    has neither)."""
    out = finalists
    if before is None:
        return out.with_columns(
            pl.lit(False).alias("party_held_mayor_lag"),
            pl.when(_linkable()).then(True).alias("finalist_eligible"),
        )
    held = (
        with_successor(before.winners.filter(pl.col("party").is_not_null()), "party", e - STEP, e)
        .select("cd_ibge", pl.col("party_then").alias("party"))
        .unique()
        .with_columns(pl.lit(True).alias("party_held_mayor_lag"))
    )
    out = _flag_match(out.join(held, on=["cd_ibge", "party"], how="left"), before.winners, "won")
    return out.with_columns(
        pl.col("party_held_mayor_lag").fill_null(False),
        pl.when(_linkable()).then(~pl.col("won")).alias("finalist_eligible"),
    ).drop("won")


def next_columns(
    finalists: pl.DataFrame, after: MayorYear, groups: dict[str, str], e: int
) -> pl.DataFrame:
    """What happened at e+4 in the same municipality (null where it had no round-1 mayoral
    election then):

    - `party_next`: the party followed through mergers to e+4 (its number), or its federation
      there (`F` and the federation's number);
    - `party_runs_next`, `party_wins_next`: a round-1 candidacy with votes, and the top
      candidacy of the deciding round, of `party_next` (any party of the federation);
    - `finalist_runs_next`, `finalist_wins_next`: the same for the finalist, linked by CPF or
      título (in memory; null if the finalist has neither).
    """
    out = with_successor(finalists, "party", e, e + STEP)
    out = _grouped(out, "party_then", groups, "group").drop("party_then")
    runners = _grouped(after.runners, "party", groups, "group")
    winners = _grouped(after.winners, "party", groups, "group")
    ran = runners.select("cd_ibge", "group").unique()
    won = winners.select("cd_ibge", "group").unique()

    out = out.join(
        ran.with_columns(pl.lit(True).alias("p_ran")), on=["cd_ibge", "group"], how="left"
    ).join(won.with_columns(pl.lit(True).alias("p_won")), on=["cd_ibge", "group"], how="left")
    out = _flag_match(_flag_match(out, after.runners, "f_ran"), after.winners, "f_won")
    there = pl.col("cd_ibge").is_in(sorted(after.held))
    linked = _linkable()
    return out.with_columns(
        pl.when(there).then(pl.col("p_ran").fill_null(False)).alias("party_runs_next"),
        pl.when(there).then(pl.col("p_won").fill_null(False)).alias("party_wins_next"),
        pl.when(there & linked).then(pl.col("f_ran")).alias("finalist_runs_next"),
        pl.when(there & linked).then(pl.col("f_won")).alias("finalist_wins_next"),
        pl.when(pl.col("group").str.starts_with("P"))
        .then(pl.col("group").str.slice(1))
        .otherwise(pl.col("group"))
        .alias("party_next"),
    ).drop("p_ran", "p_won", "f_ran", "f_won", "group")


# --- The federal bench at e-2


def read_bench(zip_path: Path, tmp_dir: Path, year: int) -> pl.DataFrame:
    """Elected federal deputies of a general election: `uf`, `party`, `federation` (null if
    none). Elected is `ELECTED_CODES` of the year."""
    raw = ap.read_tse_csv(
        zip_path,
        tmp_dir,
        ("SG_UF", "CD_CARGO", "NR_PARTIDO", "CD_SIT_TOT_TURNO"),
        ("NR_FEDERACAO",),
    )
    codes = ELECTED_CODES.get(year, ELECTED_CODES_LATER)
    rows = raw.filter(
        (pl.col("CD_CARGO").cast(pl.Int64, strict=False) == DEPUTY)
        & pl.col("CD_SIT_TOT_TURNO").cast(pl.Int64, strict=False).is_in(codes)
    )
    federation = (
        pl.col("NR_FEDERACAO").str.strip_chars()
        if "NR_FEDERACAO" in rows.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    return rows.select(
        pl.col("SG_UF").alias("uf"),
        pl.col("NR_PARTIDO").str.strip_chars().alias("party"),
        federation.alias("federation"),
    )


def bench_table(elected: pl.DataFrame, g: int, e: int) -> pl.DataFrame:
    """(`uf`, `party`, `bench_fed`): elected federal deputies at `g` per state and party
    number of `e` (each deputy's party followed through mergers to e). Where the file shows a
    federation, its parties count together: every member's row gets the federation's total.
    """
    out = with_successor(elected, "party", g, e)
    try:
        groups = parties.federation_groups(
            out.select("party_then", "federation").unique().iter_rows()
        )
    except parties.FederationError as err:
        raise BuildError(f"bench {g}: {err}") from err
    out = _grouped(out, "party_then", groups, "group")
    counts = out.group_by(["uf", "group"]).agg(pl.len().cast(pl.Int64).alias("bench_fed"))
    members = out.select("party_then", "group").unique()
    return (
        members.join(counts, on="group", how="inner")
        .select("uf", pl.col("party_then").alias("party"), "bench_fed")
        .sort("uf", "party")
    )


def check_bench(elected: dict[int, pl.DataFrame], seats: int = FEDERAL_SEATS) -> None:
    """Stops unless each general election has exactly `seats` elected federal deputies."""
    for g, frame in sorted(elected.items()):
        if frame.height != seats:
            write_profile(
                "federal_bench",
                [(str(y), "ok" if f.height == seats else "out_of_range", f.height)
                 for y, f in sorted(elected.items())],
            )  # fmt: skip
            raise BuildError(f"{g}: {frame.height} elected federal deputies, not {seats}")


# --- Amendment money during the term


def payment_sums(
    paid: pl.DataFrame, stats: dict[str, Any], e: int
) -> tuple[pl.DataFrame | None, dict[str, int]]:
    """(`cd_ibge`, `amend_after_total`, `amend_after_pix`) for the term after `e`: individual
    payments (every author) with a municipality, in `after_window(e)`, negative rows summed
    with the rest and a total below 0 set to 0. None where the CGU file does not cover the
    whole window. Also the rows set to 0, per column."""
    start, end = after_window(e)
    if stats["first"] > start or stats["last"] < end:
        return None, {c: 0 for c in PAYMENTS}
    rows = paid.filter(pl.col("ym").is_between(start, end) & pl.col("cd_ibge").is_not_null())
    sums = rows.group_by("cd_ibge").agg(
        pl.col("value").sum().alias("amend_after_total"),
        pl.col("value").filter(pl.col("pix")).sum().alias("amend_after_pix"),
    )
    floored = {c: sums.filter(pl.col(c) < 0).height for c in PAYMENTS}
    sums = sums.with_columns(pl.col(c).clip(lower_bound=0.0) for c in PAYMENTS)
    return sums, floored


# --- Checks


def check_panel(
    tables: dict[int, pl.DataFrame],
    *,
    min_races: int = MIN_RACES,
    max_races: int = MAX_RACES,
) -> None:
    """Every stop condition on the panel of every election (both halves). Counts only."""
    races = {e: t.select("cd_ibge").unique().height for e, t in tables.items()}
    for e, table in sorted(tables.items()):
        if table.schema != pl.Schema(SCHEMA):
            raise BuildError(f"{e}: the columns differ from the contract")
        per_race = table.group_by("cd_ibge").agg(
            pl.len().alias("n"),
            pl.col("margin").sum().alias("sum"),
            pl.col("win").sum().alias("wins"),
            (pl.col("margin").abs() <= TOLERANCE).any().alias("tie"),
        )
        bad = per_race.filter(
            (pl.col("n") != 2)
            | (pl.col("sum").abs() > TOLERANCE)
            | (pl.col("wins") != pl.when(pl.col("tie")).then(0).otherwise(1))
        ).height
        if bad:
            write_profile(
                "two_rows_per_race",
                [(str(e), "ok", per_race.height - bad), (str(e), "inconsistent", bad)],
            )
            raise BuildError(f"{e}: {bad} races do not have two rows with one winner")
        outside = table.filter(
            (pl.col("margin").abs() > 1 + TOLERANCE) | (pl.col("win") != (pl.col("margin") > 0))
        ).height
        if outside:
            raise BuildError(f"{e}: {outside} rows have a margin outside [-1, 1] or a wrong win")
        for won, ran in (
            ("party_wins_next", "party_runs_next"),
            ("finalist_wins_next", "finalist_runs_next"),
        ):
            wrong = table.filter(pl.col(won).fill_null(False) & ~pl.col(ran).fill_null(False))
            if wrong.height:
                raise BuildError(f"{e}: {wrong.height} rows have {won} without {ran}")
        for column in PAYMENTS:
            low = table.filter(pl.col(column) < 0).height
            if low:
                raise BuildError(f"{e}: {low} rows have {column} below 0")
        identifiers = [
            c
            for c, t in table.schema.items()
            if t == pl.Utf8 and table[c].str.contains(r"^\s*\d{11,12}\s*$").any()
        ]
        if identifiers:
            raise BuildError(f"{e}: a text column holds an 11- or 12-digit number")
    low = {e: n for e, n in races.items() if not min_races <= n <= max_races}
    if low:
        write_profile(
            "races_per_election",
            [(str(e), "out_of_range" if e in low else "ok", n) for e, n in sorted(races.items())],
        )
        e, n = sorted(low.items())[0]
        raise BuildError(f"{e}: {n} races, outside {min_races}-{max_races}")


def key_counts(year: MayorYear) -> dict[str, int]:
    """Round-1 mayoral candidacies with votes of a year: with a CPF, with a título, with
    neither and in all (counts only)."""
    r = year.runners
    return {
        "cpf": r.filter(pl.col("cpf_key").is_not_null()).height,
        "titulo": r.filter(pl.col("tit_key").is_not_null()).height,
        "neither": r.filter(~_linkable()).height,
        "all": r.height,
    }


def check_keys(mayors: dict[int, MayorYear], min_share: float = MIN_KEY_SHARE) -> None:
    """Stops if fewer than `min_share` of a year's round-1 mayoral candidacies have a CPF or a
    título to link by: a year published without identifiers would otherwise read as "the
    finalist did not run" (profile `linkable_candidacies`)."""
    counts = {y: key_counts(m) for y, m in sorted(mayors.items())}
    low = {y: c for y, c in counts.items() if c["all"] - c["neither"] < min_share * c["all"]}
    if low:
        write_profile(
            "linkable_candidacies",
            [(str(y), "ok", c["all"] - c["neither"]) for y, c in counts.items()]
            + [(str(y), "empty", c["neither"]) for y, c in counts.items()],
        )
        y, c = next(iter(low.items()))
        raise BuildError(
            f"{y}: {c['neither']} of {c['all']} mayoral candidacies have neither CPF nor título"
        )


# --- One election's table


def election_table(
    e: int,
    year: MayorYear,
    before: MayorYear | None,
    after: MayorYear,
    groups_after: dict[str, str],
    bench: pl.DataFrame | None,
    sums: pl.DataFrame | None,
    population: pl.DataFrame,
    munis: pl.DataFrame,
) -> pl.DataFrame:
    """The rows of election `e`, with the contract's columns and types, sorted by `cd_ibge`
    and `party`."""
    pop = population.filter(pl.col("ano") == e).select(
        pl.col("id_municipio").cast(pl.Utf8).str.zfill(7).alias("cd_ibge"),
        pl.col("populacao").cast(pl.Int64).alias("population_e"),
    )
    rows = lag_columns(year.finalists, before, e)
    rows = next_columns(rows, after, groups_after, e)
    rows = (
        rows.join(munis.select("cd_ibge", "uf"), on="cd_ibge", how="left")
        .join(year.n_cands, on="cd_ibge", how="left")
        .join(pop, on="cd_ibge", how="left")
    )
    if bench is None:
        rows = rows.with_columns(pl.lit(None, dtype=pl.Int64).alias("bench_fed"))
    else:
        rows = rows.join(bench, on=["uf", "party"], how="left").with_columns(
            pl.col("bench_fed").fill_null(0)
        )
    if sums is None:
        rows = rows.with_columns(pl.lit(None, dtype=pl.Float64).alias(c) for c in PAYMENTS)
    else:
        rows = rows.join(sums, on="cd_ibge", how="left").with_columns(
            pl.col(c).fill_null(0.0) for c in PAYMENTS
        )
    pop_f = pl.col("population_e").cast(pl.Float64)
    rows = rows.with_columns(
        pl.lit(e, dtype=pl.Int64).alias("election"),
        (pl.col("margin") > 0).alias("win"),
        pl.when(pop_f > 0).then(pop_f.log()).alias("ln_pop"),
    )
    return rows.select([pl.col(n).cast(t) for n, t in SCHEMA.items()]).sort(["cd_ibge", "party"])


def _year(
    store: Store,
    votes: dict[int, dict[str, Any]],
    turnout: dict[int, dict[str, Any]],
    year: int,
    tmp_dir: Path,
    attrs: pl.DataFrame,
    *,
    check_codes: bool,
) -> MayorYear:
    cv = _fetch_frame(store, votes[year], tmp_dir, VOTES_COLUMNS)
    t = _fetch_frame(store, turnout[year], tmp_dir, TURNOUT_COLUMNS)
    return mayor_year(cv, t, attrs, year, check_codes=check_codes)


def _groups(store: Store, entry: dict[str, Any], tmp_dir: Path, year: int) -> dict[str, str]:
    frame = _fetch_frame(store, entry, tmp_dir, COALITION_COLUMNS)
    try:
        return parties.federation_groups(frame.unique().iter_rows())
    except parties.FederationError as err:
        raise BuildError(f"{year}: {err}") from err


def _bench(store: Store, entry: dict[str, Any], tmp_dir: Path, year: int) -> pl.DataFrame:
    path = _fetch(store, entry, tmp_dir)
    try:
        return read_bench(path, tmp_dir, year)
    finally:
        path.unlink(missing_ok=True)


def _parties_gone(year: MayorYear, after: MayorYear, groups: dict[str, str], e: int) -> list[str]:
    """Finalist parties of `e`, followed to e+4, with no round-1 candidacy anywhere then: a
    merger `parties.MERGERS` lacks would show here (counts and party numbers only)."""
    now = with_successor(year.finalists.select("party").unique(), "party", e, e + STEP)
    now = _grouped(now, "party_then", groups, "group")
    later = set(_grouped(after.runners, "party", groups, "group")["group"].drop_nulls().to_list())
    return sorted(set(now["group"].to_list()) - later)


# --- Build


def build(
    store: Store,
    results_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    parties_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    population_manifest: dict[str, Any],
    general_manifest: dict[str, Any],
    cgu_manifest: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    elections: tuple[int, ...] = ELECTIONS,
    min_races: int = MIN_RACES,
    max_races: int = MAX_RACES,
    federal_seats: int = FEDERAL_SEATS,
    min_key_share: float = MIN_KEY_SHARE,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-election, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.write_manifest`)
    when `status` is `created`. The build never lists, reads or checks the sealed folder: a
    create-only upload fails if an object is there. Nothing is uploaded unless every check has
    passed.
    """
    explore, split_shas = read_lists(store)
    years = result_years(elections)
    vote_entries = {y: _file(results_manifest, f"/candidate_votes_{y}.parquet") for y in years}
    turnout_entries = {y: _file(results_manifest, f"/turnout_{y}.parquet") for y in years}
    next_years = sorted({e + STEP for e in elections})
    coalition_entries = {y: _file(parties_manifest, f"/coalitions_{y}.parquet") for y in next_years}
    bench_years = {e: BENCH_YEAR[e] for e in elections if e in BENCH_YEAR}
    bench_entries = {
        g: _file(general_manifest, f"/consulta_cand_{g}.zip")
        for g in sorted(set(bench_years.values()))
    }
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    pop_entry = _file(population_manifest, "/ibge_population_annual.parquet")
    cgu_entry = _file(cgu_manifest, "/EmendasParlamentares.zip")
    entries = [
        cand_entry,
        muni_entry,
        pop_entry,
        cgu_entry,
        *vote_entries.values(),
        *turnout_entries.values(),
        *coalition_entries.values(),
        *bench_entries.values(),
    ]
    hashed = input_hash(entries, split_shas, elections)
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

    # Amendment payments: every individual payment with a municipality, any author.
    cgu_path = _fetch(store, cgu_entry, tmp_dir)
    try:
        raw = ap.read_cgu(cgu_path)
    finally:
        cgu_path.unlink(missing_ok=True)
    individual, stats = ap.parse_payments(raw)
    del raw
    ap.check_payment_stats(stats)
    windows = [after_window(e) for e in elections]
    in_any = pl.any_horizontal([pl.col("ym").is_between(*w) for w in windows])
    paid, dropped = ap.match_recipients(individual.filter(in_any), munis)
    del individual

    elected = {g: _bench(store, entry, tmp_dir, g) for g, entry in bench_entries.items()}
    check_bench(elected, federal_seats)

    mayors: dict[int, MayorYear] = {}
    for y in years:
        mayors[y] = _year(
            store, vote_entries, turnout_entries, y, tmp_dir, attrs, check_codes=y in elections
        )
    del attrs
    check_keys(mayors, min_key_share)

    tables: dict[int, pl.DataFrame] = {}
    notes: list[str] = []
    explore_ids = sorted(explore)
    for e in sorted(elections):
        groups = _groups(store, coalition_entries[e + STEP], tmp_dir, e + STEP)
        bench = (
            bench_table(elected[bench_years[e]], bench_years[e], e) if e in bench_years else None
        )
        sums, floored = payment_sums(paid, stats, e)
        year, after = mayors[e], mayors[e + STEP]
        table = election_table(
            e, year, mayors.get(e - STEP), after, groups, bench, sums, population, munis
        )
        tables[e] = table
        half = table.filter(pl.col("cd_ibge").is_in(explore_ids))
        unlinkable = year.finalists.filter(
            ~_linkable() & pl.col("cd_ibge").is_in(explore_ids)
        ).height
        c = year.counts
        notes.append(
            f"E{e}: races={half.height // 2}, rows={half.height}, "
            f"races_both_halves={c['races']}, races_without_party={c['no_party']}, "
            f"races_one_party={c['same_party']}, one_candidate={c['one_candidate']}, "
            f"ties={c['ties']}, unlinkable_finalists={unlinkable}, "
            f"no_election_next={half.filter(pl.col('party_runs_next').is_null()).height}, "
            f"no_population={half.filter(pl.col('population_e').is_null()).height}, "
            f"bench={'none' if bench is None else bench_years[e]}, "
            "amendments="
            + ("none" if sums is None else "..".join(ap._month(m) for m in after_window(e)))
        )
        notes.append(f"E{e}_floored_to_zero=" + ",".join(f"{k}:{n}" for k, n in floored.items()))
        gone = _parties_gone(year, after, groups, e)
        notes.append(f"E{e}_parties_without_candidates_next=" + ("+".join(gone) or "none"))
        federations = sorted(set(groups.values()))
        listed = ",".join(
            f + "=" + "+".join(sorted(p for p, g in groups.items() if g == f)) for f in federations
        )
        notes.append(f"E{e}_federations_next={listed or 'none'}")

    for g, frame in sorted(elected.items()):
        notes.append(f"bench_{g}: elected_federal_deputies={frame.height}")
    for y, m in sorted(mayors.items()):
        k = key_counts(m)
        notes.append(
            f"keys_{y}: candidacies={k['all']}, with_cpf={k['cpf']}, with_titulo={k['titulo']}, "
            f"with_neither={k['neither']}"
        )
    notes.append(f"dropped_recipient_rows_no_municipality={ap._years(dropped['no_municipality'])}")
    notes.append(f"dropped_recipient_rows_unmatched={ap._years(dropped['unmatched'])}")
    notes.extend(ap.placeholder_notes(dropped))
    notes.append(
        f"first_payment_month={ap._month(stats['first'])}, last={ap._month(stats['last'])}"
    )

    check_panel(tables, min_races=min_races, max_races=max_races)

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per election
    for e, table in tables.items():
        is_explore = table["cd_ibge"].is_in(explore_ids)
        sealed_file, derived_file = sealed_dir / output_name(e), derived_dir / output_name(e)
        table.filter(~is_explore).write_parquet(sealed_file)
        table.filter(is_explore).write_parquet(derived_file)
        local.append((sealed_file, derived_file))

    # Every check has passed. Sealed first; the manifest is the caller's last step.
    sealed_files = [_upload(store, sealed_prefix + p.name, p) for p, _ in local]
    files = [_upload(store, derived_prefix + p.name, p) for _, p in local]
    manifest = build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=derived_prefix,
        files=files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (
                results_manifest,
                candidates_manifest,
                parties_manifest,
                municipalities_manifest,
                population_manifest,
                general_manifest,
                cgu_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
