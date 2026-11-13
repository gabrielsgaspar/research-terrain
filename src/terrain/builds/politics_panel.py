"""Council entry, competition, turnover, mining money and homicides per municipality and election.

Contract of the output: data/contracts/politics_panel.md. Idea 0008, decisions 0003 and
0011; the models are `terrain.builds.place_outcomes` (the derived/sealed split) and
`terrain.strongholds` (TSE results: main election, elected status).

One row per municipality and municipal election 2000-2024, with the nine outcomes of the
idea. Rows of exploration-half municipalities (both exploration lists) go to the derived
folder; every other row goes to a sealed folder that this build only creates in and never
reads. The notes count exploration-half rows only and hold no statistic of any outcome.

Candidate CPFs are used only inside `incumbent_reelected` and `unlinked_cpfs`, in memory,
to link councillors from one election to the next. No CPF, name or hash of either is
written to a column, a note or an exception message.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import polars as pl

from terrain import explore as terrain_explore
from terrain import strongholds
from terrain.builds import cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "politics_panel"
ELECTIONS = tuple(range(2000, 2025, 4))
MONEY_ELECTIONS = (2004, 2008, 2012)
WINDOW = 4
COUNCIL = strongholds.COUNCIL
MAYOR = 11
MINING_OCCUPATIONS = (605, 253)  # GARIMPEIRO; TRABALHADOR DE MINAS E PEDREIRAS...
MONEY_OFFICES = ("vereador", "prefeito")
MINING_DIVISIONS = ("07", "08")
MINING_CLASS = "0990"
CPF_PATTERN = r"^\d{11}$"
MIN_MUNICIPALITIES = 5000  # per election from 2004 on
CHECKED_FROM = 2004
MIN_MINING_CANDS = 100  # national, summed over 2004-2012
MAX_HOMICIDE_RATE = 1000.0  # per 100,000
TOLERANCE = 1e-9

CANDIDATE_COLUMNS = (
    "ano_eleicao",
    "cd_eleicao",
    "sg_ue",
    "sq_candidato",
    "cd_ocupacao",
    "sg_partido",
    "nr_cpf_candidato",
)
VOTES_COLUMNS = (
    "cd_cargo",
    "nr_turno",
    "cd_eleicao",
    "sg_ue",
    "sq_candidato",
    "qt_votos_nominais",
    "qt_votos_nominais_validos",
    "cd_sit_tot_turno",
)
TURNOUT_COLUMNS = ("cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "qt_total_votos_validos")
RECEIPT_COLUMNS = (
    "ano",
    "id_municipio",
    "cargo",
    "cnae_2_doador",
    "n_receitas",
    "sum_valor_receita",
)
HOMICIDE_COLUMNS = ("ano", "id_municipio_ocorrencia", "n_obitos")
POPULATION_COLUMNS = ("ano", "id_municipio", "populacao")

SCHEMA: dict[str, Any] = {
    "cd_ibge": pl.Utf8,
    "uf": pl.Utf8,
    "election": pl.Int64,
    "n_council_cands": pl.Int64,
    "n_seats": pl.Int64,
    "cands_per_seat": pl.Float64,
    "n_mining_cands": pl.Int64,
    "mining_cand_share": pl.Float64,
    "n_mayor_cands": pl.Int64,
    "valid_votes_mayor": pl.Int64,
    "enc_mayor": pl.Float64,
    "margin_mayor": pl.Float64,
    "seat_turnover": pl.Float64,
    "mining_councillor_share": pl.Float64,
    "incumbent_reelected": pl.Float64,
    "mining_money_share": pl.Float64,
    "receipts_total": pl.Float64,
    "receipts_with_cnae": pl.Float64,
    "n_receipts_with_cnae": pl.Int64,
    "homicide_rate": pl.Float64,
    "homicides_sum": pl.Int64,
}
SHARES = (
    "mining_cand_share",
    "margin_mayor",
    "seat_turnover",
    "mining_councillor_share",
    "incumbent_reelected",
    "mining_money_share",
)

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, `strongholds` (main election, elected status), `explore` (the exploration
# lists), `place_outcomes` (`read_lists`), `cell_outcomes` (the list parser and the upload)
# and `polling_place_tenure` (`_file` picks the inputs, `_fetch` checks their SHA-256).
CODE_MODULES = (
    Path(__file__),
    Path(strongholds.__file__),
    Path(terrain_explore.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def output_name(election: int) -> str:
    return f"politics_panel_{election}.parquet"


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
    return content_hash(shas, ",".join(split_shas), ",".join(str(e) for e in elections), *sources)


# --- Inputs


def read_columns(path: Path, wanted: tuple[str, ...]) -> pl.DataFrame:
    schema = pl.read_parquet_schema(path)
    if [c for c in wanted if c not in schema]:
        raise BuildError(f"{path.name} lacks a column the build needs")
    return pl.read_parquet(path, columns=list(wanted))


def _read(
    store: Store, entry: dict[str, Any], tmp_dir: Path, wanted: tuple[str, ...]
) -> pl.DataFrame:
    path = _fetch(store, entry, tmp_dir)
    try:
        return read_columns(path, wanted)
    finally:
        path.unlink(missing_ok=True)


def add_ibge(frame: pl.DataFrame, munis: pl.DataFrame, what: str) -> pl.DataFrame:
    """Add `cd_ibge` from `sg_ue` (= `cd_tse`); stops if a TSE code has no IBGE code."""
    mapped = frame.join(
        munis.select("cd_tse", "cd_ibge"), left_on="sg_ue", right_on="cd_tse", how="left"
    )
    missing = int(mapped["cd_ibge"].null_count())
    if missing:
        raise BuildError(f"{what}: {missing} rows have a cd_tse with no cd_ibge")
    return mapped


# --- TSE results


def code_year(year: int) -> int:
    """The year whose `cd_sit_tot_turno` codes `strongholds.elected_status` should read.

    `strongholds` knows the 2008 codes and, for every other year, the 2012 codes. 2000 and
    2004 are read with the 2008 codes (the 2000 codes are unconfirmed; see the contract).
    """
    return 2008 if year <= 2008 else year


def round1(df: pl.DataFrame, cargo: int) -> pl.DataFrame:
    return df.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == cargo)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
    )


def main_election_of(df: pl.DataFrame, cargo: int) -> int | None:
    """The round-1 `cd_eleicao` of `cargo` with the most rows; None if there is none."""
    rows = round1(df, cargo).group_by("cd_eleicao").len()
    if rows.height == 0:
        return None
    return int(rows.sort(["len", "cd_eleicao"], descending=[True, False])["cd_eleicao"][0])


def _votes() -> pl.Expr:
    """Counted votes of a row. The 2000 file holds them in the valid column and 0 in the
    other; the 2008 file has no valid column (null)."""
    return pl.coalesce(
        pl.col("qt_votos_nominais_validos").cast(pl.Int64, strict=False),
        pl.col("qt_votos_nominais").cast(pl.Int64, strict=False),
    )


def council_candidates(
    votes: pl.DataFrame, attrs: pl.DataFrame, year: int, munis: pl.DataFrame
) -> pl.DataFrame:
    """One row per council candidacy of the main election: `votes`, `elected`, `mining`,
    `party` and `cpf` (the CPF stays in memory; it never leaves this module's frames)."""
    if round1(votes, COUNCIL).height == 0:
        raise BuildError(f"{year}: no first-round council rows")
    main = strongholds.main_election(votes)
    rows = round1(votes, COUNCIL).filter(pl.col("cd_eleicao") == main)
    cands = rows.group_by(["sg_ue", "sq_candidato"]).agg(
        _votes().sum().fill_null(0).alias("votes"),
        pl.col("cd_sit_tot_turno").drop_nulls().first(),
    )
    flags = strongholds.elected_status(cands, code_year(year)).select(
        "sg_ue", "sq_candidato", "elected"
    )
    cands = cands.join(flags, on=["sg_ue", "sq_candidato"], how="left").with_columns(
        pl.col("elected").fill_null(False)
    )
    wanted = attrs.filter((pl.col("ano_eleicao") == year) & (pl.col("cd_eleicao") == main)).select(
        "sg_ue",
        "sq_candidato",
        pl.col("cd_ocupacao")
        .str.strip_chars()
        .cast(pl.Int64, strict=False)
        .is_in(MINING_OCCUPATIONS)
        .fill_null(False)
        .alias("mining"),
        pl.col("sg_partido").alias("party"),
        pl.col("nr_cpf_candidato").alias("cpf"),
    )
    if wanted.select(pl.struct("sg_ue", "sq_candidato").is_duplicated().any()).item():
        raise BuildError(f"{year}: a candidacy appears twice in the candidates")
    cands = cands.join(wanted, on=["sg_ue", "sq_candidato"], how="left").with_columns(
        pl.col("mining").fill_null(False)
    )
    return add_ibge(cands, munis, f"{year} council")


def council_summary(cands: pl.DataFrame) -> pl.DataFrame:
    """Outcomes 1, 2 and 6 per municipality: candidates who ran, seats, mining shares."""
    ran = pl.col("votes") > 0
    out = cands.group_by("cd_ibge").agg(
        ran.sum().cast(pl.Int64).alias("n_council_cands"),
        pl.col("elected").sum().cast(pl.Int64).alias("n_seats"),
        (ran & pl.col("mining")).sum().cast(pl.Int64).alias("n_mining_cands"),
        (pl.col("elected") & pl.col("mining")).sum().cast(pl.Int64).alias("n_mining_elected"),
    )
    return out.select(
        "cd_ibge",
        "n_council_cands",
        "n_seats",
        pl.when(pl.col("n_seats") > 0)
        .then(pl.col("n_council_cands") / pl.col("n_seats"))
        .alias("cands_per_seat"),
        "n_mining_cands",
        pl.when(pl.col("n_council_cands") > 0)
        .then(pl.col("n_mining_cands") / pl.col("n_council_cands"))
        .alias("mining_cand_share"),
        pl.when(pl.col("n_seats") > 0)
        .then(pl.col("n_mining_elected") / pl.col("n_seats"))
        .alias("mining_councillor_share"),
    )


def mayor_candidates(votes: pl.DataFrame, year: int, munis: pl.DataFrame) -> pl.DataFrame:
    """`cd_ibge` and `votes` per mayoral candidacy of the main mayoral election, round 1."""
    main = main_election_of(votes, MAYOR)
    if main is None:
        return pl.DataFrame(schema={"cd_ibge": pl.Utf8, "votes": pl.Int64})
    rows = round1(votes, MAYOR).filter(pl.col("cd_eleicao") == main)
    cands = rows.group_by(["sg_ue", "sq_candidato"]).agg(_votes().sum().fill_null(0).alias("votes"))
    return add_ibge(cands, munis, f"{year} mayor").select("cd_ibge", "votes")


def mayor_valid_votes(turnout: pl.DataFrame, votes: pl.DataFrame, munis: pl.DataFrame, year: int):
    """Valid mayoral votes per municipality, round 1, main mayoral election, summed over zones."""
    main = main_election_of(votes, MAYOR)
    empty = pl.DataFrame(schema={"cd_ibge": pl.Utf8, "valid_votes_mayor": pl.Int64})
    if main is None:
        return empty
    rows = round1(turnout, MAYOR).filter(pl.col("cd_eleicao") == main)
    valid = rows.group_by("sg_ue").agg(
        pl.col("qt_total_votos_validos")
        .cast(pl.Int64, strict=False)
        .sum()
        .alias("valid_votes_mayor")
    )
    return add_ibge(valid, munis, f"{year} mayor turnout").select("cd_ibge", "valid_votes_mayor")


def mayor_summary(mayor: pl.DataFrame, valid: pl.DataFrame) -> pl.DataFrame:
    """Outcomes 3 and 4: effective number of candidates and the first-round margin.

    A candidate ran if their votes are above 0. With one candidate the margin is 1.0.
    """
    base = mayor.select("cd_ibge").unique()
    ranked = (
        mayor.filter(pl.col("votes") > 0)
        .sort(["cd_ibge", "votes"], descending=[False, True])
        .with_columns(pl.int_range(pl.len()).over("cd_ibge").alias("rank"))
    )
    stats = ranked.group_by("cd_ibge").agg(
        pl.len().cast(pl.Int64).alias("n_mayor_cands"),
        ((pl.col("votes") / pl.col("votes").sum()) ** 2).sum().alias("hhi"),
        pl.col("votes").max().alias("first"),
        pl.col("votes").filter(pl.col("rank") == 1).sum().alias("second"),
    )
    out = (
        base.join(stats, on="cd_ibge", how="left")
        .join(valid, on="cd_ibge", how="left")
        .with_columns(pl.col("n_mayor_cands").fill_null(0))
    )
    margin = (
        pl.when(pl.col("n_mayor_cands") == 1)
        .then(1.0)
        .when(pl.col("valid_votes_mayor") > 0)
        .then((pl.col("first") - pl.col("second")) / pl.col("valid_votes_mayor"))
    )
    return out.select(
        "cd_ibge",
        "n_mayor_cands",
        "valid_votes_mayor",
        (1.0 / pl.col("hhi")).alias("enc_mayor"),
        margin.alias("margin_mayor"),
    )


# --- Links between two elections (CPFs are used here, in memory, and nowhere else)


def _linkable() -> pl.Expr:
    return pl.col("cpf").str.strip_chars().str.contains(CPF_PATTERN).fill_null(False)


def seat_turnover(cur: pl.DataFrame, prev: pl.DataFrame) -> pl.DataFrame:
    """Outcome 5: 1 - sum over parties of min(seats now, seats four years ago) / seats now.

    Null where either election has no elected councillor in the municipality.
    """

    def seats(frame: pl.DataFrame, name: str) -> pl.DataFrame:
        return (
            frame.filter(pl.col("elected"))
            .group_by("cd_ibge")
            .agg(pl.len().cast(pl.Int64).alias(name))
        )

    def by_party(frame: pl.DataFrame, name: str) -> pl.DataFrame:
        return (
            frame.filter(pl.col("elected") & pl.col("party").is_not_null())
            .group_by(["cd_ibge", "party"])
            .agg(pl.len().cast(pl.Int64).alias(name))
        )

    overlap = (
        by_party(cur, "s_cur")
        .join(by_party(prev, "s_prev"), on=["cd_ibge", "party"], how="inner")
        .group_by("cd_ibge")
        .agg(pl.min_horizontal("s_cur", "s_prev").sum().alias("overlap"))
    )
    both = seats(cur, "seats_cur").join(seats(prev, "seats_prev"), on="cd_ibge", how="inner")
    out = both.join(overlap, on="cd_ibge", how="left").with_columns(pl.col("overlap").fill_null(0))
    return out.select(
        "cd_ibge", (1.0 - pl.col("overlap") / pl.col("seats_cur")).alias("seat_turnover")
    )


def incumbent_reelected(cur: pl.DataFrame, prev: pl.DataFrame) -> pl.DataFrame:
    """Outcome 7: the share of the councillors elected four years ago who are elected again.

    Linked by CPF within the municipality. A CPF that is empty or not 11 digits is
    unlinked and left out of the share. Only `cd_ibge` and the share leave this function.
    """
    before = (
        prev.filter(pl.col("elected") & _linkable())
        .select("cd_ibge", pl.col("cpf").str.strip_chars())
        .unique()
    )
    now = (
        cur.filter(pl.col("elected") & _linkable())
        .select("cd_ibge", pl.col("cpf").str.strip_chars())
        .unique()
        .with_columns(pl.lit(True).alias("again"))
    )
    return (
        before.join(now, on=["cd_ibge", "cpf"], how="left")
        .group_by("cd_ibge")
        .agg(pl.col("again").fill_null(False).cast(pl.Float64).mean().alias("incumbent_reelected"))
    )


def unlinked_cpfs(cands: pl.DataFrame) -> pl.DataFrame:
    """Elected councillors per municipality whose CPF cannot be linked (counts only)."""
    return (
        cands.filter(pl.col("elected") & ~_linkable())
        .group_by("cd_ibge")
        .agg(pl.len().cast(pl.Int64).alias("n_unlinked"))
    )


# --- Mining money


def office_key(value: str) -> str:
    """Lower-cased, accent-stripped, trimmed text of an office name."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def money_table(receipts: pl.DataFrame, election: int) -> pl.DataFrame:
    """Outcome 8 for one election year: receipts of vereador and prefeito by donor sector.

    A mining CNAE is, after keeping the digits and padding to 7, division 07 or 08 or the
    class 0990. Stops if neither office appears in the year.
    """
    year = receipts.filter(pl.col("ano").cast(pl.Int64, strict=False) == election).with_columns(
        pl.col("cargo").cast(pl.Utf8)
    )
    names = [v for v in year["cargo"].unique().to_list() if v is not None]
    lookup = pl.DataFrame(
        {"cargo": names, "office": [office_key(v) for v in names]},
        schema={"cargo": pl.Utf8, "office": pl.Utf8},
    )
    year = year.join(lookup, on="cargo", how="inner").filter(pl.col("office").is_in(MONEY_OFFICES))
    if year.height == 0:
        raise BuildError(f"{election}: no receipts of vereador or prefeito")
    digits = pl.col("cnae_2_doador").cast(pl.Utf8).str.replace_all(r"\D", "").str.zfill(7)
    has_cnae = pl.col("cnae_2_doador").is_not_null()
    mining = (
        has_cnae
        & (
            digits.str.slice(0, 2).is_in(MINING_DIVISIONS)
            | (digits.str.slice(0, 4) == MINING_CLASS)
        )
    ).fill_null(False)
    value = pl.col("sum_valor_receita").cast(pl.Float64, strict=False)
    out = (
        year.with_columns(pl.col("id_municipio").cast(pl.Utf8).str.zfill(7).alias("cd_ibge"))
        .group_by("cd_ibge")
        .agg(
            value.sum().alias("receipts_total"),
            value.filter(has_cnae).sum().alias("receipts_with_cnae"),
            value.filter(mining).sum().alias("mining_value"),
            pl.col("n_receitas")
            .cast(pl.Int64, strict=False)
            .filter(has_cnae)
            .sum()
            .alias("n_receipts_with_cnae"),
        )
    )
    return out.select(
        "cd_ibge",
        "receipts_total",
        "receipts_with_cnae",
        "n_receipts_with_cnae",
        pl.when(pl.col("receipts_total") != 0)
        .then(pl.col("mining_value") / pl.col("receipts_total"))
        .alias("mining_money_share"),
    )


# --- Homicides


def homicide_table(hom: pl.DataFrame, pop: pl.DataFrame, election: int) -> pl.DataFrame:
    """Outcome 9: homicides over e-4..e-1 per 100,000 of the population of the same years.

    The rate is null unless all four years have a population. SIM has no row for a
    municipality-year without a death, so a missing year counts as 0 homicides.
    """
    years = list(range(election - WINDOW, election))
    deaths = (
        hom.filter(pl.col("ano").cast(pl.Int64).is_in(years))
        .with_columns(pl.col("id_municipio_ocorrencia").cast(pl.Utf8).str.zfill(7).alias("cd_ibge"))
        .group_by("cd_ibge")
        .agg(pl.col("n_obitos").cast(pl.Int64).sum().alias("homicides_sum"))
    )
    people = (
        pop.filter(pl.col("ano").cast(pl.Int64).is_in(years) & pl.col("populacao").is_not_null())
        .with_columns(pl.col("id_municipio").cast(pl.Utf8).str.zfill(7).alias("cd_ibge"))
        .group_by("cd_ibge")
        .agg(
            pl.col("ano").n_unique().alias("n_years"),
            pl.col("populacao").cast(pl.Float64).sum().alias("population"),
        )
        .filter((pl.col("n_years") == len(years)) & (pl.col("population") > 0))
    )
    return deaths.join(people, on="cd_ibge", how="full", coalesce=True).select(
        "cd_ibge",
        pl.col("homicides_sum"),
        (pl.col("homicides_sum").fill_null(0) / pl.col("population") * 100_000).alias(
            "homicide_rate"
        ),
    )


# --- One election


def election_table(
    election: int,
    universe: pl.DataFrame,
    parts: list[pl.DataFrame],
) -> pl.DataFrame:
    """Join the per-municipality parts onto the universe and fix the schema of the contract."""
    table = universe.with_columns(pl.lit(election, dtype=pl.Int64).alias("election"))
    for part in parts:
        table = table.join(part, on="cd_ibge", how="left")
    for name, dtype in SCHEMA.items():
        if name not in table.columns:
            table = table.with_columns(pl.lit(None, dtype=dtype).alias(name))
    table = table.with_columns(pl.col("homicides_sum").fill_null(0))
    return table.select(*[pl.col(n).cast(t) for n, t in SCHEMA.items()]).sort("cd_ibge")


def check_panel(
    tables: dict[int, pl.DataFrame],
    *,
    min_municipalities: int = MIN_MUNICIPALITIES,
    min_mining_cands: int = MIN_MINING_CANDS,
) -> None:
    """Every stop condition on the whole panel (both halves). Messages carry counts only."""
    for election, table in sorted(tables.items()):
        if table["cd_ibge"].is_duplicated().any():
            raise BuildError(f"{election}: a municipality appears twice")
        if election >= CHECKED_FROM and table.height < min_municipalities:
            raise BuildError(
                f"{election}: {table.height} municipalities, below {min_municipalities}"
            )
        low = table.filter(pl.col("cands_per_seat") < 1).height
        if low:
            raise BuildError(f"{election}: {low} rows have fewer candidates than seats")
        for column in SHARES:
            outside = table.filter(
                (pl.col(column) < -TOLERANCE) | (pl.col(column) > 1 + TOLERANCE)
            ).height
            if outside:
                raise BuildError(f"{election}: {outside} rows have {column} outside [0, 1]")
        high = table.filter(pl.col("homicide_rate") > MAX_HOMICIDE_RATE).height
        if high:
            raise BuildError(f"{election}: {high} rows have a homicide rate above 1,000")
    mining = sum(
        int(tables[e]["n_mining_cands"].sum() or 0) for e in MONEY_ELECTIONS if e in tables
    )
    if mining < min_mining_cands:
        raise BuildError(
            f"{mining} mining-occupation candidates in 2004-2012, below {min_mining_cands}"
        )


def year_note(
    explore_rows: pl.DataFrame, unlinked: pl.DataFrame, explore: frozenset[str], election: int
) -> str:
    """Counts of exploration-half rows only: never a statistic of an outcome."""
    n_unlinked = int(unlinked.filter(pl.col("cd_ibge").is_in(sorted(explore)))["n_unlinked"].sum())
    return f"E{election}: rows={explore_rows.height}, unlinked_cpfs={n_unlinked}"


# --- Build


def build(
    store: Store,
    candidates_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    homicides_manifest: dict[str, Any],
    population_manifest: dict[str, Any],
    receipts_manifest: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    elections: tuple[int, ...] = ELECTIONS,
    min_municipalities: int = MIN_MUNICIPALITIES,
    min_mining_cands: int = MIN_MINING_CANDS,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the per-election, per-half Parquet files; return the manifest.

    Exploration files go to `<derived_root><hash>/`, confirmation files to
    `<sealed_root><hash>/`. The caller writes the manifest (`terrain.manifest.
    write_manifest`) when `status` is `created`. The build never lists, reads or
    checks the sealed folder: a create-only upload fails if an object is there.
    Nothing is uploaded unless every check has passed.
    """
    explore, split_shas = read_lists(store)
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    hom_entry = _file(homicides_manifest, "/sim_homicides.parquet")
    pop_entry = _file(population_manifest, "/ibge_population_annual.parquet")
    receipt_entry = _file(receipts_manifest, "/tse_receipts.parquet")
    vote_entries = {e: _file(results_manifest, f"/candidate_votes_{e}.parquet") for e in elections}
    turnout_entries = {e: _file(results_manifest, f"/turnout_{e}.parquet") for e in elections}

    entries = [
        cand_entry,
        muni_entry,
        hom_entry,
        pop_entry,
        receipt_entry,
        *vote_entries.values(),
        *turnout_entries.values(),
    ]
    hashed = input_hash(entries, split_shas, elections)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    munis = _read(store, muni_entry, tmp_dir, ("cd_ibge", "cd_tse", "uf"))
    munis = munis.filter(pl.col("cd_tse").is_not_null())
    if munis["cd_tse"].is_duplicated().any():
        raise BuildError("municipalities: a cd_tse appears twice")
    attrs = _read(store, cand_entry, tmp_dir, CANDIDATE_COLUMNS)
    hom = _read(store, hom_entry, tmp_dir, HOMICIDE_COLUMNS)
    pop = _read(store, pop_entry, tmp_dir, POPULATION_COLUMNS)
    receipts = _read(store, receipt_entry, tmp_dir, RECEIPT_COLUMNS)

    tables: dict[int, pl.DataFrame] = {}
    unlinked: dict[int, pl.DataFrame] = {}
    prev: pl.DataFrame | None = None  # the previous election's candidates, in memory only
    prev_year = 0
    for e in sorted(elections):
        votes = _read(store, vote_entries[e], tmp_dir, VOTES_COLUMNS)
        turnout = _read(store, turnout_entries[e], tmp_dir, TURNOUT_COLUMNS)
        cands = council_candidates(votes, attrs, e, munis)
        mayors = mayor_candidates(votes, e, munis)
        valid = mayor_valid_votes(turnout, votes, munis, e)
        del votes, turnout

        universe = (
            pl.concat([cands.select("cd_ibge"), mayors.select("cd_ibge")])
            .unique()
            .join(munis.select("cd_ibge", "uf"), on="cd_ibge", how="left")
        )
        parts = [council_summary(cands), mayor_summary(mayors, valid), homicide_table(hom, pop, e)]
        if prev is not None and prev_year == e - WINDOW:
            parts += [seat_turnover(cands, prev), incumbent_reelected(cands, prev)]
        if e in MONEY_ELECTIONS:
            parts.append(money_table(receipts, e))
        tables[e] = election_table(e, universe, parts)
        unlinked[e] = unlinked_cpfs(cands)
        prev, prev_year = cands.select("cd_ibge", "elected", "party", "cpf"), e
        del cands

    check_panel(tables, min_municipalities=min_municipalities, min_mining_cands=min_mining_cands)

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    notes: list[str] = []
    local: list[tuple[Path, Path]] = []  # (sealed file, derived file) per election
    cnae_years: list[int] = []
    for e, table in tables.items():
        is_explore = table["cd_ibge"].is_in(sorted(explore))
        mine = table.filter(is_explore)
        notes.append(year_note(mine, unlinked[e], explore, e))
        if mine["n_receipts_with_cnae"].sum():
            cnae_years.append(e)
        sealed_file, derived_file = sealed_dir / output_name(e), derived_dir / output_name(e)
        table.filter(~is_explore).write_parquet(sealed_file)
        mine.write_parquet(derived_file)
        local.append((sealed_file, derived_file))
    notes.append("years_with_receipt_cnae=" + (",".join(map(str, cnae_years)) or "none"))

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
                candidates_manifest,
                results_manifest,
                municipalities_manifest,
                homicides_manifest,
                population_manifest,
                receipts_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
