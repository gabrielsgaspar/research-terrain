"""Monthly amendment payments of each row of the amendments panel (idea 0011, H6).

Contract of the output: data/contracts/amendments_monthly.md. Decisions 0003 and 0011. One
row per cycle, deputy, municipality and month, for the rows of `amendments_panel` (the same
deputies, the same author link and the same municipalities, from
`terrain.builds.amendments_panel`), from January of the year before the mayoral election to
October of the next general election. Rows of exploration-half municipalities (both
exploration lists) go to the derived folder; every other row goes to a sealed folder that
this build only creates in and never reads.

Names and CPFs are used only in memory, inside the author link. No CPF, voter ID, name or
favorecido code, and no hash of one, is written to a column, a note or an exception message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from terrain import explore as terrain_explore
from terrain import parties
from terrain.builds import amendments_panel as ap
from terrain.builds import cell_outcomes, place_outcomes
from terrain.builds import polling_place_tenure as tenure
from terrain.builds.amendments_panel import CYCLES, Cycle, _fetch_frame
from terrain.builds.cell_outcomes import _upload
from terrain.builds.place_outcomes import read_lists
from terrain.builds.polling_place_tenure import BuildError, _fetch, _file
from terrain.manifest import MANIFEST_NAME, build_manifest, content_hash
from terrain.storage import Store

__all__ = ["BuildError", "build"]

DATASET = "amendments_monthly"
LAST_MONTH = 10  # October of t1, the month of the general election

SCHEMA: dict[str, Any] = {
    "cycle": pl.Utf8,
    "deputy": pl.Utf8,
    "cd_ibge": pl.Utf8,
    "ym": pl.Int64,
    "amend_total": pl.Float64,
    "amend_pix": pl.Float64,
    "n_pay": pl.Int64,
}
PAYMENTS = ("amend_total", "amend_pix")

# Every module whose code decides what this build writes. Its source is part of the output
# path: this file, `amendments_panel` (the rows, the author link, the CGU payments) and the
# modules it imports (`parties`, `explore`, `place_outcomes`, `cell_outcomes`,
# `polling_place_tenure`).
CODE_MODULES = (
    Path(__file__),
    Path(ap.__file__),
    Path(parties.__file__),
    Path(terrain_explore.__file__),
    Path(place_outcomes.__file__),
    Path(cell_outcomes.__file__),
    Path(tenure.__file__),
)


def output_name(cycle: str) -> str:
    return f"monthly_{cycle}.parquet"


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
    spec = ",".join(f"{c}={tuple(CYCLES[c])}:{month_range(CYCLES[c])}" for c in sorted(cycles))
    return content_hash(shas, ",".join(split_shas), spec, *sources)


def month_range(cycle: Cycle) -> tuple[int, int]:
    """The first and last month (YYYYMM): January of m-1 to October of t1."""
    return (cycle.m - 1) * 100 + 1, cycle.t1 * 100 + LAST_MONTH


def months(cycle: Cycle) -> list[int]:
    first, last = month_range(cycle)
    return [y * 100 + m for y in range(first // 100, last // 100 + 1) for m in range(1, 13)
            if first <= y * 100 + m <= last]  # fmt: skip


def deputy_payments(paid: pl.DataFrame, author_map: pl.DataFrame, cycle: Cycle) -> pl.DataFrame:
    """(`deputy`, `cd_ibge`, `ym`, `value`, `pix`): the payments of the cycle's months to an
    identified municipality by the authors linked as deputies (`author_map`, from
    `amendments_panel.cycle_link`). An author is `Código do Autor da Emenda` with the
    normalised name, as in the link."""
    rows = paid.filter(
        pl.col("ym").is_between(*month_range(cycle)) & pl.col("cd_ibge").is_not_null()
    ).with_columns(pl.col("code").fill_null(""))
    rows = ap.with_norm(rows, "author", "name_norm")
    return rows.join(author_map, on=["code", "name_norm"], how="inner").select(
        "deputy", "cd_ibge", "ym", "value", "pix"
    )


def monthly_table(
    name: str, keys: pl.DataFrame, payments: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Every (`deputy`, `cd_ibge`) of `keys` in every month of the cycle, with the month's
    payments: total and Pix (negative rows summed with the rest; a month below 0 set to 0)
    and the payment rows (negative ones too). Returns the table and the months set to 0, per
    column (both halves)."""
    cycle = CYCLES[name]
    sums = payments.group_by(["deputy", "cd_ibge", "ym"]).agg(
        pl.col("value").sum().alias("amend_total"),
        pl.col("value").filter(pl.col("pix")).sum().alias("amend_pix"),
        pl.len().cast(pl.Int64).alias("n_pay"),
    )
    grid = (
        keys.select("deputy", "cd_ibge")
        .unique()
        .join(pl.DataFrame({"ym": months(cycle)}, schema={"ym": pl.Int64}), how="cross")
    )
    table = grid.join(sums, on=["deputy", "cd_ibge", "ym"], how="left").with_columns(
        pl.lit(name).alias("cycle"),
        *[pl.col(c).fill_null(0.0) for c in PAYMENTS],
        pl.col("n_pay").fill_null(0),
    )
    floored = {c: table.filter(pl.col(c) < 0).height for c in PAYMENTS}
    table = table.with_columns(pl.col(c).clip(lower_bound=0.0) for c in PAYMENTS)
    table = table.select([pl.col(n).cast(t) for n, t in SCHEMA.items()])
    return table.sort(["deputy", "cd_ibge", "ym"]), floored


def check_tables(
    tables: dict[str, pl.DataFrame],
    keys: dict[str, int],
    *,
    min_rows: int = ap.MIN_ROWS,
    max_rows: int = ap.MAX_ROWS,
) -> None:
    """Every stop condition (both halves). Counts only. `keys` are the panel rows per cycle,
    bound as the panel's rows are."""
    for name, table in sorted(tables.items()):
        if table.select(pl.struct("cycle", "deputy", "cd_ibge", "ym").is_duplicated().any()).item():
            raise BuildError(f"{name}: a (cycle, deputy, cd_ibge, ym) appears twice")
        expected = keys[name] * len(months(CYCLES[name]))
        if table.height != expected:
            raise BuildError(f"{name}: {table.height} rows, not {expected}")
        for column in PAYMENTS:
            low = table.filter(pl.col(column) < 0).height
            if low:
                raise BuildError(f"{name}: {low} rows have {column} below 0")
        if table.filter(pl.col("amend_pix") > pl.col("amend_total") + 1e-6).height:
            raise BuildError(f"{name}: a month has more Pix than its total")
        if not min_rows <= keys[name] <= max_rows:
            raise BuildError(f"{name}: {keys[name]} panel rows, outside {min_rows}-{max_rows}")


def entries(
    general_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    cycles: tuple[str, ...],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[int, dict], dict[int, dict]]:
    """The candidacy zips (t0-4 and t0) and the mayoral results (m) the cycles need."""
    general = {}
    for c in cycles:
        cy = CYCLES[c]
        for year in (cy.t0 - 4, cy.t0):
            general[("consulta_cand", year)] = _file(general_manifest, f"/consulta_cand_{year}.zip")
    years = sorted({CYCLES[c].m for c in cycles})
    votes = {y: _file(results_manifest, f"/candidate_votes_{y}.parquet") for y in years}
    turnout = {y: _file(results_manifest, f"/turnout_{y}.parquet") for y in years}
    return general, votes, turnout


def build(
    store: Store,
    general_manifest: dict[str, Any],
    cgu_manifest: dict[str, Any],
    results_manifest: dict[str, Any],
    candidates_manifest: dict[str, Any],
    municipalities_manifest: dict[str, Any],
    chamber_manifest: dict[str, Any],
    *,
    derived_root: str,
    sealed_root: str,
    tmp_dir: Path,
    cycles: tuple[str, ...] = tuple(CYCLES),
    min_rows: int = ap.MIN_ROWS,
    max_rows: int = ap.MAX_ROWS,
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
    general, vote_entries, turnout_entries = entries(general_manifest, results_manifest, cycles)
    cgu_entry = _file(cgu_manifest, "/EmendasParlamentares.zip")
    muni_entry = _file(municipalities_manifest, "/municipalities.parquet")
    cand_entry = _file(candidates_manifest, "/candidates.parquet")
    chamber_entry = _file(chamber_manifest, "/deputados.csv")
    files = [
        cgu_entry,
        muni_entry,
        cand_entry,
        chamber_entry,
        *general.values(),
        *vote_entries.values(),
        *turnout_entries.values(),
    ]
    hashed = input_hash(files, split_shas, cycles)
    derived_prefix = f"{derived_root}{hashed}/"
    sealed_prefix = f"{sealed_root}{hashed}/"
    if store.exists(derived_prefix + MANIFEST_NAME):
        existing = json.loads(store.read_bytes(derived_prefix + MANIFEST_NAME))
        existing["status"] = "unchanged"
        return existing

    munis = _fetch_frame(store, muni_entry, tmp_dir, ap.MUNICIPALITY_COLUMNS)
    if munis.filter(pl.col("cd_tse").is_not_null())["cd_tse"].is_duplicated().any():
        raise BuildError("municipalities: a cd_tse appears twice")
    attrs = _fetch_frame(store, cand_entry, tmp_dir, ap.CANDIDATE_COLUMNS)
    chamber_path = _fetch(store, chamber_entry, tmp_dir)
    try:
        chamber = ap.read_chamber(chamber_path)
    finally:
        chamber_path.unlink(missing_ok=True)
    cgu_path = _fetch(store, cgu_entry, tmp_dir)
    try:
        raw = ap.read_cgu(cgu_path)
        years, _ = ap.read_amendment_years(cgu_path)
    finally:
        cgu_path.unlink(missing_ok=True)
    individual, stats = ap.parse_payments(raw)
    del raw
    ap.check_payment_stats(stats)
    years_by_author = ap.author_years(individual, years)
    ranges = [month_range(CYCLES[c]) for c in cycles]
    in_any = pl.any_horizontal([pl.col("ym").is_between(*r) for r in ranges])
    paid, dropped = ap.match_recipients(individual.filter(in_any), munis)
    del individual

    tables: dict[str, pl.DataFrame] = {}
    keys: dict[str, int] = {}
    notes: list[str] = []
    explore_ids = sorted(explore)
    for name in cycles:
        cy = CYCLES[name]
        link = ap.cycle_link(name, store, general, paid, years_by_author, chamber, tmp_dir)
        mayors = ap._mayors(store, vote_entries, turnout_entries, cy.m, tmp_dir, attrs)
        deputies = link.deputies.select("sq", "uf", "party", "elected")
        panel_rows = ap.panel_keys(deputies, mayors, munis).select("deputy", "cd_ibge")
        payments = deputy_payments(paid, link.author_map, cy)
        table, floored = monthly_table(name, panel_rows, payments)
        tables[name], keys[name] = table, panel_rows.height
        half = table.filter(pl.col("cd_ibge").is_in(explore_ids))
        first, last = month_range(cy)
        share = link.counts["money_share"]
        half_keys = half.select("deputy", "cd_ibge").unique().height
        notes.append(
            f"{name}: rows={half.height}, panel_rows={half_keys}, "
            f"months={len(months(cy))} ({ap._month(first)}..{ap._month(last)}), "
            f"deputy_authors={link.counts['deputies']}, "
            f"money_share={'none' if share is None else f'{share:.4f}'}"
        )
        notes.append(f"{name}_floored_to_zero=" + ",".join(f"{c}:{n}" for c, n in floored.items()))

    notes.append(f"dropped_recipient_rows_no_municipality={ap._years(dropped['no_municipality'])}")
    notes.append(f"dropped_recipient_rows_unmatched={ap._years(dropped['unmatched'])}")
    notes.extend(ap.placeholder_notes(dropped))
    notes.append(
        f"first_payment_month={ap._month(stats['first'])}, last={ap._month(stats['last'])}"
    )

    check_tables(tables, keys, min_rows=min_rows, max_rows=max_rows)

    derived_dir, sealed_dir = tmp_dir / "derived", tmp_dir / "sealed"
    derived_dir.mkdir(exist_ok=True)
    sealed_dir.mkdir(exist_ok=True)
    local: list[tuple[Path, Path]] = []
    for name, table in tables.items():
        is_explore = table["cd_ibge"].is_in(explore_ids)
        sealed_file, derived_file = sealed_dir / output_name(name), derived_dir / output_name(name)
        table.filter(~is_explore).write_parquet(sealed_file)
        table.filter(is_explore).write_parquet(derived_file)
        local.append((sealed_file, derived_file))

    # Every check has passed. Sealed first; the manifest is the caller's last step.
    sealed_files = [_upload(store, sealed_prefix + p.name, p) for p, _ in local]
    out_files = [_upload(store, derived_prefix + p.name, p) for _, p in local]
    manifest = build_manifest(
        dataset=DATASET,
        stage="build",
        status="created",
        gcs_prefix=derived_prefix,
        files=out_files,
        inputs=[
            m["gcs_prefix"] + MANIFEST_NAME
            for m in (
                general_manifest,
                cgu_manifest,
                results_manifest,
                candidates_manifest,
                municipalities_manifest,
                chamber_manifest,
            )
        ],
        notes="; ".join(notes),
        code_commit=code_commit,
        created_at=created_at,
    )
    manifest["sealed_files"] = sealed_files
    return manifest
