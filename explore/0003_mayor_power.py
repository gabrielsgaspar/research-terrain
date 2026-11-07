"""Power of close mayoral races at the municipality level (idea 0003, kill criterion 1).

With one observation per close mayoral race, what effect could the races detect? For the
windows 0.5%, 1% and 2% this script reports the spread of a winner-minus-loser contrast
under random sign flips (`sd_ri`), the minimum detectable effect (MDE = 2.8 `sd_ri`) and
the power at decision 0007's effect size (8% of baseline clearing).

Nothing here is an estimate of any effect: there is no observed contrast, only the spread
of the re-flip distribution. The outcome Y of a municipality is pre-election clearing
only: the years E-4 .. E-1 of each election E (`pre_years`, fixed in code); year E and
later are never read. Only exploration-half rows are read.

Races are the mayoral deciding rounds (run-off when the municipality had one, else round
1) of 2008 .. 2020. Votes, margins and windows follow the task definitions; the council
code of `terrain.strongholds` is reused only for `main_election`.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import polars as pl

from terrain.explore import exploration_municipalities, restrict, write_results
from terrain.storage import GCSStore
from terrain.strongholds import main_election

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "mayor_power_census", _REPO / "explore" / "0001_feasibility_census.py"
)
census = importlib.util.module_from_spec(_SPEC)
sys.modules["mayor_power_census"] = census
_SPEC.loader.exec_module(census)

ELECTIONS = (2008, 2012, 2016, 2020)
WINDOWS = (0.005, 0.01, 0.02)
TOL = 1e-12
SEED = 20261106
DRAWS = 2000
EFFECT = 0.08  # decision 0007
Z = 1.96
MDE_K = 2.8
MAYOR = 11
VALID = "Válido"

CV_COLUMNS = [
    "ano_eleicao",
    "cd_eleicao",
    "cd_tipo_eleicao",
    "nr_turno",
    "sg_ue",
    "cd_ibge",
    "cd_cargo",
    "sq_candidato",
    "nr_zona",
    "qt_votos_nominais",
    "qt_votos_nominais_validos",
    "nm_tipo_destinacao_votos",
    "ds_sit_tot_turno",
]
TURNOUT_COLUMNS = [
    "cd_eleicao",
    "nr_turno",
    "sg_ue",
    "cd_ibge",
    "cd_cargo",
    "qt_total_votos_validos",
]
OUTCOME_COLUMNS = ["nome_1KM", "cd_ibge", "has_data", "code_2", "code_4"]


def pre_years(election: int) -> list[int]:
    """The only outcome years read for `election`: E-4 .. E-1."""
    return list(range(election - 4, election))


# --- Deciding round, votes, races


def deciding_round(cv: pl.DataFrame, main: int) -> tuple[pl.DataFrame, int]:
    """Mayoral rows of each municipality's deciding round, with a `runoff` flag.

    Round 2 under `main + 1` when the municipality has mayoral rows there, else round 1
    under `main`. Also returns the number of mayoral round-2 rows under any other id,
    which are not used. Rows of other elections (supplementary) are dropped.
    """
    mayor = cv.filter(pl.col("cd_cargo").cast(pl.Int64, strict=False) == MAYOR).with_columns(
        pl.col("cd_eleicao").cast(pl.Int64, strict=False),
        pl.col("nr_turno").cast(pl.Int64, strict=False),
    )
    round2 = mayor.filter((pl.col("cd_eleicao") == main + 1) & (pl.col("nr_turno") == 2))
    other = mayor.filter((pl.col("nr_turno") == 2) & (pl.col("cd_eleicao") != main + 1)).height
    in_runoff = round2["sg_ue"].unique().to_list()
    round1 = mayor.filter(
        (pl.col("cd_eleicao") == main)
        & (pl.col("nr_turno") == 1)
        & ~pl.col("sg_ue").is_in(in_runoff)
    )
    rows = pl.concat(
        [
            round2.with_columns(pl.lit(True).alias("runoff")),
            round1.with_columns(pl.lit(False).alias("runoff")),
        ]
    )
    return rows, other


def candidacy_votes_mayor(rows: pl.DataFrame, year: int) -> tuple[pl.DataFrame, int]:
    """Votes per candidacy in the deciding round, summed over zones, and rows left out.

    2016 and 2020: `qt_votos_nominais_validos` on rows whose destination is exactly
    `Válido`; other rows (annulled ones) are left out and counted. 2008 and 2012 have no
    destination column and use `qt_votos_nominais`. Candidacies without votes are dropped.
    """
    if year >= 2016:
        left_out = rows.filter(
            pl.col("nm_tipo_destinacao_votos").is_null()
            | (pl.col("nm_tipo_destinacao_votos") != VALID)
        ).height
        kept = rows.filter(pl.col("nm_tipo_destinacao_votos") == VALID)
        column = "qt_votos_nominais_validos"
    else:
        left_out = 0
        kept = rows
        column = "qt_votos_nominais"
    votes = (
        kept.group_by(["sg_ue", "sq_candidato"], maintain_order=True)
        .agg(
            pl.col(column).cast(pl.Float64).sum().alias("votes"),
            pl.col("cd_ibge").first(),
            pl.col("runoff").first(),
            pl.col("ds_sit_tot_turno").first().alias("status"),
        )
        .filter(pl.col("votes") > 0)
    )
    return votes, left_out


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


def races(votes: pl.DataFrame, valid: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """(`sg_ue`, `cd_ibge`, `runoff`, `margin`) per municipality with two candidacies, and counts.

    First and second candidacies by votes, ties broken by `sq_candidato`. Margin = (first
    - second) / valid votes. Counted: municipalities with one candidacy (no margin), ties,
    races without valid votes (no margin), races whose first candidacy is not `ELEITO`
    (kept), and run-off races.
    """
    ordered = votes.sort(["sg_ue", "votes", "sq_candidato"], descending=[False, True, False])
    g = ordered.group_by("sg_ue", maintain_order=True).agg(
        pl.col("cd_ibge").first(),
        pl.col("runoff").first(),
        pl.len().alias("n"),
        pl.col("votes").first().alias("v1"),
        pl.col("votes").slice(1, 1).first().alias("v2"),
        pl.col("status").first().alias("status1"),
    )
    g = g.join(valid, on="sg_ue", how="left")
    two = g.filter(pl.col("n") >= 2)
    has_valid = pl.col("valid").is_not_null() & (pl.col("valid") > 0)
    out = two.filter(has_valid).select(
        "sg_ue",
        "cd_ibge",
        "runoff",
        ((pl.col("v1") - pl.col("v2")) / pl.col("valid")).alias("margin"),
    )
    counts = {
        "one_candidacy": g.filter(pl.col("n") == 1).height,
        "ties": two.filter(pl.col("v1") == pl.col("v2")).height,
        "no_valid_votes": two.filter(~has_valid).height,
        "first_not_eleito": two.filter(has_valid & (pl.col("status1") != "ELEITO")).height,
        "runoff_races": out.filter(pl.col("runoff")).height,
        "races": out.height,
    }
    return out, counts


# --- Outcome


def outcome_tables(election: int, read: Any) -> dict[int, pl.DataFrame]:
    """`cell_outcomes` of `pre_years(election)` through `read(year)`; no other year."""
    return {y: read(y) for y in pre_years(election)}


def outcome(cells_by_year: dict[int, pl.DataFrame], election: int) -> pl.DataFrame:
    """(`cd_ibge`, `Y`) per municipality seen in any pre year.

    Cells with `has_data` true in every pre year qualify. Y = sum of `code_4` over the
    four years and cells, divided by the sum of `code_2 + code_4` in E-4 over the same
    cells. Y is null when no cell qualifies or the denominator is 0.
    """
    years = pre_years(election)
    if sorted(cells_by_year) != years:
        raise ValueError(f"outcome years must be exactly {years}, got {sorted(cells_by_year)}")
    frames = [
        cells_by_year[y].select(
            "nome_1KM",
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("has_data").fill_null(False).alias(f"h{y}"),
            pl.col("code_2").cast(pl.Float64).fill_null(0.0).alias(f"c2_{y}"),
            pl.col("code_4").cast(pl.Float64).fill_null(0.0).alias(f"c4_{y}"),
        )
        for y in years
    ]
    wide = frames[0]
    for f in frames[1:]:
        wide = wide.join(f.drop("cd_ibge"), on="nome_1KM", how="inner")
    seen = pl.concat([f.select("cd_ibge") for f in frames]).unique()
    ok = pl.all_horizontal([pl.col(f"h{y}") for y in years])
    first = years[0]
    cells = wide.filter(ok).with_columns(
        pl.sum_horizontal([pl.col(f"c4_{y}") for y in years]).alias("num"),
        (pl.col(f"c2_{first}") + pl.col(f"c4_{first}")).alias("den"),
    )
    per = cells.group_by("cd_ibge").agg(pl.col("num").sum(), pl.col("den").sum())
    per = per.with_columns(
        pl.when(pl.col("den") > 0).then(pl.col("num") / pl.col("den")).otherwise(None).alias("Y")
    )
    return seen.join(per.select("cd_ibge", "Y"), on="cd_ibge", how="left").sort("cd_ibge")


def attach_outcome(race_table: pl.DataFrame, y: pl.DataFrame) -> pl.DataFrame:
    """`race_table` with `Y` (null when the municipality has none)."""
    return race_table.with_columns(pl.col("cd_ibge").cast(pl.Utf8)).join(
        y, on="cd_ibge", how="left"
    )


# --- Windows and re-flips


def close_races(race_table: pl.DataFrame, window: float = max(WINDOWS)) -> pl.DataFrame:
    return race_table.filter(pl.col("margin").abs() <= window + TOL)


def window_ids(per_election: dict[int, pl.DataFrame]) -> pl.DataFrame:
    """The 2% races with a non-null Y, numbered; narrower windows are subsets, same ids.

    Races with a null Y are dropped before numbering (they are in no window). Within an
    election the races are sorted by `sg_ue` and numbered by row; ids are offset across
    years in election order. Columns: `election`, `id`, `margin`, `Y`, `runoff`.
    """
    parts = []
    offset = 0
    for election in sorted(per_election):
        t = (
            close_races(per_election[election])
            .filter(pl.col("Y").is_not_null())
            .sort("sg_ue")
            .with_row_index("id")
            .with_columns(
                (pl.col("id").cast(pl.Int64) + offset).alias("id"),
                pl.lit(election).alias("election"),
            )
            .select("election", "id", "margin", "Y", "runoff")
        )
        offset += t.height
        parts.append(t)
    return pl.concat(parts)


def sign_draws(n: int, rng: np.random.Generator, draws: int = DRAWS) -> np.ndarray:
    """`draws` sign vectors of length `n`, each `rng.integers(0, 2, size=n) * 2 - 1`."""
    return np.array(
        [rng.integers(0, 2, size=n) * 2 - 1 for _ in range(draws)], dtype=float
    ).reshape(draws, n)


def delta(ytilde: np.ndarray, s: np.ndarray) -> float:
    """Mean of `ytilde` where s = +1 minus mean where s = -1; NaN if a side is empty."""
    pos = s == 1
    neg = s == -1
    if not pos.any() or not neg.any():
        return float("nan")
    return float(ytilde[pos].mean() - ytilde[neg].mean())


def window_table(table: pl.DataFrame, window: float) -> pl.DataFrame:
    """Races of `window` with `ytilde` = Y minus the mean of Y of the same election."""
    return (
        table.filter(pl.col("margin").abs() <= window + TOL)
        .with_columns((pl.col("Y") - pl.col("Y").mean().over("election")).alias("ytilde"))
        .sort("id")
    )


def window_deltas(table: pl.DataFrame, window: float, signs: np.ndarray) -> np.ndarray:
    """Delta of every draw (row of `signs`, indexed by race id) for the races of `window`."""
    w = window_table(table, window)
    ids = w["id"].to_numpy()
    yt = w["ytilde"].to_numpy().astype(float)
    s = signs[:, ids]
    pos = (s == 1).astype(float)
    n_pos = pos.sum(axis=1)
    n_neg = ids.size - n_pos
    sum_pos = pos @ yt
    with np.errstate(divide="ignore", invalid="ignore"):
        out = sum_pos / n_pos - (yt.sum() - sum_pos) / n_neg
    out[(n_pos == 0) | (n_neg == 0)] = np.nan
    return out


def power_stats(deltas: np.ndarray, ybar: float) -> dict[str, Any]:
    """Spread, MDE and power at 8% of `ybar` from the re-flip draws of Delta."""
    finite = deltas[~np.isnan(deltas)]
    out: dict[str, Any] = {
        "draws": int(deltas.size),
        "draws_without_delta": int(deltas.size - finite.size),
        "sd_ri": None,
        "q025": None,
        "q975": None,
        "mde": None,
        "mde_pct_of_ybar": None,
        "power": None,
    }
    if finite.size < 2:
        return out
    sd = float(np.std(finite, ddof=1))
    out["sd_ri"] = sd
    out["q025"] = float(np.quantile(finite, 0.025))
    out["q975"] = float(np.quantile(finite, 0.975))
    out["mde"] = MDE_K * sd
    if ybar > 0:
        out["mde_pct_of_ybar"] = 100.0 * MDE_K * sd / ybar
    if sd > 0:
        out["power"] = NormalDist().cdf(EFFECT * ybar / sd - Z)
    return out


def window_report(table: pl.DataFrame, window: float, signs: np.ndarray) -> dict[str, Any]:
    w = window_table(table, window)
    n = w.height
    y = w["Y"].to_numpy().astype(float)
    ybar = float(y.mean()) if n else float("nan")
    per_election = {
        str(e): int(c) for e, c in w.group_by("election").len().sort("election").iter_rows()
    }
    report: dict[str, Any] = {
        "window": window,
        "races": n,
        "races_per_election": per_election,
        "runoff_races": int(w.filter(pl.col("runoff")).height),
        "ybar": ybar if n else None,
        "sd_y": float(np.std(y, ddof=1)) if n > 1 else None,
    }
    if n:
        report.update(power_stats(window_deltas(table, window, signs), ybar))
    return report


# --- One election


def election_races(
    cv: pl.DataFrame, turnout: pl.DataFrame, year: int
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Mayoral races of `year` (with margin) and the per-year counts."""
    main = main_election(cv)
    rows, other_ids = deciding_round(cv, main)
    votes, annulled = candidacy_votes_mayor(rows, year)
    race_table, counts = races(votes, valid_votes_mayor(turnout, rows))
    counts["round2_rows_other_ids"] = other_ids
    counts["annulled_rows_left_out"] = annulled
    return race_table, counts


# --- Report


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _label(window: float) -> str:
    return f"{window * 100:g}%"


def build_results(
    per_election: dict[int, pl.DataFrame], counts: dict[int, dict[str, int]]
) -> dict[str, Any]:
    """Everything the summary reports, from the races (with margin and Y) of each election."""
    table = window_ids(per_election)
    signs = sign_draws(table.height, np.random.default_rng(SEED))
    left_out = {}
    for e, t in per_election.items():
        close = close_races(t)
        left_out[str(e)] = {
            "null_outcome_in_2pct": int(close["Y"].null_count()),
            **{k: v for k, v in counts[e].items()},
        }
    return _clean(
        {
            "elections": list(ELECTIONS),
            "pre_years": {str(e): pre_years(e) for e in ELECTIONS},
            "draws": DRAWS,
            "seed": SEED,
            "effect": EFFECT,
            "per_election": left_out,
            "windows": {_label(w): window_report(table, w, signs) for w in WINDOWS},
        }
    )


def _summary(results: dict[str, Any]) -> str:
    wins = results["windows"]
    head = "; ".join(
        f"{k}: power {_pct(r.get('power'))}, MDE {_fmt(r.get('mde_pct_of_ybar'), 3)}% of baseline"
        for k, r in wins.items()
    )
    lines = [f"Power at 8% of baseline clearing (decision 0007), by window: {head}.", ""]
    lines += ["## Races", ""]
    elections = [str(e) for e in ELECTIONS]
    lines += [
        "| Window | " + " | ".join(elections) + " | pooled | run-off |",
        "| --- | " + " | ".join(["---"] * (len(elections) + 2)) + " |",
    ]
    for k, r in wins.items():
        per = r["races_per_election"]
        cells = " | ".join(str(per.get(e, 0)) for e in elections)
        lines.append(f"| {k} | {cells} | {r['races']} | {r['runoff_races']} |")
    lines += [
        "",
        "Left out and counted, per election:",
        "",
        "| Election | one candidacy | ties | no valid votes | null outcome (2%) | "
        "round-2 rows, other ids | annulled rows | first not ELEITO | run-off races |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e, c in results["per_election"].items():
        lines.append(
            f"| {e} | {c['one_candidacy']} | {c['ties']} | {c['no_valid_votes']} "
            f"| {c['null_outcome_in_2pct']} | {c['round2_rows_other_ids']} "
            f"| {c['annulled_rows_left_out']} | {c['first_not_eleito']} | {c['runoff_races']} |"
        )
    lines += [
        "",
        "## Power",
        "",
        "| Window | races | ybar | SD of Y | sd_ri | q2.5 | q97.5 | MDE | MDE % of ybar | "
        "power at 8% |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for k, r in wins.items():
        lines.append(
            f"| {k} | {r['races']} | {_fmt(r['ybar'])} | {_fmt(r['sd_y'])} "
            f"| {_fmt(r.get('sd_ri'))} | {_fmt(r.get('q025'))} | {_fmt(r.get('q975'))} "
            f"| {_fmt(r.get('mde'))} | {_fmt(r.get('mde_pct_of_ybar'), 3)} "
            f"| {_pct(r.get('power'))} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- Exploration half only.",
        "- Pre-election clearing (E-4 .. E-1) stands in for the outcome's spread.",
        "- One observation per race ignores turf geography.",
        "- Delta is the best case: a race-level attribute that splits the races 50/50.",
        "- The municipal outcome stops at exploration-half cells.",
        "- No effect is estimated; there is no observed contrast.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    half = exploration_municipalities(store)
    per_election: dict[int, pl.DataFrame] = {}
    counts: dict[int, dict[str, int]] = {}
    with tempfile.TemporaryDirectory() as tmp:

        def read(manifest: str, pattern: str, columns: list[str]) -> pl.DataFrame:
            remote = census._paths(manifest, pattern)[0]
            local = Path(tmp) / Path(remote).name
            store.download(remote, local)
            frame = restrict(pl.read_parquet(local, columns=columns), half)
            local.unlink()
            return frame

        for year in ELECTIONS:
            cv = read("tse_results", rf"candidate_votes_{year}\.parquet$", CV_COLUMNS)
            turnout = read("tse_results", rf"turnout_{year}\.parquet$", TURNOUT_COLUMNS)
            race_table, counts[year] = election_races(cv, turnout, year)
            cells = outcome_tables(
                year,
                lambda y: read("cell_outcomes", rf"cell_outcomes_{y}\.parquet$", OUTCOME_COLUMNS),
            )
            per_election[year] = attach_outcome(race_table, outcome(cells, year))
    results = build_results(per_election, counts)
    write_results(args.out_dir, _summary(results), results)


if __name__ == "__main__":
    main()
