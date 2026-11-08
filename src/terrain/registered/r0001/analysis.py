"""Idea 0001's registered analysis, `0001_direct` (plan draft: harness/drafts/pap-draft.md).

What it computes, in the plan's order (section 7):

1. Kill criterion 1: close-pair candidates within 5 km of an indigenous land and of a
   settlement, pooled 2008-2024, from treatment-side tables only. If either is below
   200 the run stops here, before any outcome is read.
2. The balance table at the window: issue #206's ten covariates (winner minus loser),
   their RI p and decision 0008's omnibus p (the minimum p against its re-flip
   distribution), pooled 2008-2024. An omnibus p below 0.15 triggers the fallback.
3. Every estimate of run 42298466207 (`explore/0001_effects.py`), at the window: the
   direct effect (`exp2`, rings 2 and 5 km), displacement (`g_exp10`, rings 10-20 and
   20-50 km, placebo and change outcome), the constituency split (5 and 2 km) and the
   2020 `Y3` sensitivity, with one sign vector per draw shared by every estimate.
4. New in the plan: the direct placebo (Ypre on the direct exposure), the
   incumbency-adjusted direct estimate (Z, fixed under re-flips), and the alignment
   split (aligned, unaligned, mixed and unmatched pairs as components of D).

The treatment is taken through `assign` once, for every election, before any outcome
is read: in `confirm-run` the pairs come back with their sides swapped by coin flips, in
`unblind` as they are. Everything after that uses the assigned pairs.

`run_exploration` runs the same code on the exploration half, for the validation
against run 42298466207 (issue draft 39); it refuses the registered window, so the
analysis is never run at 0.25% before registration.

Determinism: the inputs are fixed files, the re-flips use a fixed seed (20261106), and
the shuffle's seed is fixed by the specification's hash. `terrain.confirm` records every
number to 12 significant digits, so a rerun gives identical numbers.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from terrain import confirm
from terrain import strongholds as sh
from terrain.registered.r0001 import frozen as fz

REPO = Path(__file__).resolve().parents[4]
MANIFESTS = REPO / "data" / "manifests" / "build"

ANALYSIS = "0001_direct"
OUTCOME_ELECTIONS = (2008, 2012, 2016, 2020)  # 2024 has no post-election years yet
ALL_ELECTIONS = (2008, 2012, 2016, 2020, 2024)  # kill criterion 1 and balance
REGISTERED_WINDOW = 0.0025  # decision 0008
KC1_MINIMUM = 200  # idea 0001, kill criterion 1
FALLBACK_P = 0.15  # decision 0009, point 5
FIRST_CANDIDATE_YEAR = 2004  # incumbency of 2008 needs the 2004 council
DESCRIPTIVE = ("pop22_5km",)
COVARIATES = fz.BALANCE + DESCRIPTIVE
DIRECT_RINGS = ("ring2", "ring5")
DISPLACEMENT_RINGS = ("ring10_20", "ring20_50")
ALIGN_KINDS = ("aligned", "unaligned", "mixed", "left_out")
# Carried over from the exploration half (decisions 0008 and 0009), reported, never recomputed.
POWER = {
    "power_direct": 0.868,
    "power_displacement": 0.622,
    "power_split": 0.307,
    "power_align": 0.335,
    "effect_size_pct": 8.0,
}
MAIN_SLOTS = {"Y4": "Y4", "Y2": "Y2"}
SLOTS = {
    "disp_pre": {"Y4": "Ypre", "Y2": "dY"},
    "direct_y3": {"Y4": "Y3", "Y2": "Y3"},
    "displacement_y3": {"Y4": "Y3", "Y2": "Y3"},
    "direct_pre": {"Y4": "Ypre", "Y2": "Ypre"},
}
# The labels of run 42298466207, in its order.
EFFECT_LABELS = (
    "direct",
    "ring2",
    "ring5",
    "displacement",
    "disp_pre",
    "disp_ring10_20",
    "disp_ring20_50",
    "split5",
    "split2",
    "direct_y3",
    "displacement_y3",
)
NEW_LABELS = ("direct_pre", "align")
ADJUSTED = {"direct_adj": "direct", "ring2_adj": "ring2", "ring5_adj": "ring5"}
ADJUSTED["direct_pre_adj"] = "direct_pre"

CAND_COLUMNS = [
    "ano_eleicao",
    "cd_eleicao",
    "nr_turno",
    "cd_cargo",
    "sg_ue",
    "sq_candidato",
    "cd_genero",
    "dt_eleicao",
    "dt_nascimento",
    "cd_grau_instrucao",
    "nr_titulo_eleitoral_candidato",
    "ds_sit_tot_turno",
    "st_reeleicao",
    "nr_partido",
    "sq_coligacao",
    "nr_federacao",
]
COALITION_COLUMNS = [
    "cd_eleicao",
    "cd_cargo",
    "sg_ue",
    "cd_ibge",
    "sq_coligacao",
    "nr_partido",
    "nr_federacao",
]
OUTCOME_COLUMNS = ["nome_1KM", "cd_ibge", "has_data", "code_2", "code_4"]
GRID_COLUMNS = ["nome_1KM", "cd_ibge", "x_km", "y_km", "pop_2022"]
SPEC_FIELDS = {
    ("outcome", "dataset"): "cell_outcomes",
    ("outcome", "variable"): "code_4",
    ("outcome", "window"): "term_years",
    ("treatment", "design"): "close_pair_swap",
    ("exposure",): "exp2",
    ("fixed_effects",): ["municipality_by_year"],
    ("inference", "method"): "randomisation",
    ("inference", "cluster"): "municipality",
}


@dataclass(frozen=True)
class Settings:
    window: float
    draws: int
    seed: int


# --- Reading


class Reader:
    """Built files of one half. `download(path, local)` fetches; `restrict` keeps the half.

    Paths come from the build manifests in the repository. Outcome files are the
    manifest's `files` (exploration half, `data/derived/`) or `sealed_files`
    (confirmation half, `sealed/outcomes/`), as `outcome_key` says.
    """

    def __init__(
        self,
        download: Callable[[str, Path], None],
        restrict: Callable[[pl.DataFrame], pl.DataFrame],
        outcome_key: str,
        tmp: Path,
        manifests: Path | None = None,
    ) -> None:
        self.download, self.restrict, self.outcome_key = download, restrict, outcome_key
        self.tmp, self.manifests = tmp, MANIFESTS if manifests is None else manifests
        self.read_paths: list[str] = []

    def paths(self, dataset: str, pattern: str, key: str = "files") -> list[str]:
        data = json.loads((self.manifests / f"{dataset}.json").read_text(encoding="utf-8"))
        hits = sorted(f["path"] for f in data.get(key, []) if re.search(pattern, f["path"]))
        if not hits:
            raise confirm.ConfirmError(f"{dataset}: no {key} entry matches {pattern}")
        return hits

    def _frame(self, remote: str, columns: list[str] | None, restrict: bool) -> pl.DataFrame:
        local = self.tmp / Path(remote).name
        self.download(remote, local)
        self.read_paths.append(remote)
        frame = pl.read_parquet(local, columns=columns)
        local.unlink()
        return self.restrict(frame) if restrict else frame

    def read(self, dataset: str, pattern: str, columns: list[str] | None = None) -> pl.DataFrame:
        return self._frame(self.paths(dataset, pattern)[0], columns, True)

    def read_all(self, dataset: str, pattern: str) -> list[pl.DataFrame]:
        return [self._frame(p, None, True) for p in self.paths(dataset, pattern)]

    def read_whole(self, dataset: str, pattern: str, columns: list[str]) -> pl.DataFrame:
        """A table without `cd_ibge` (candidates, the municipality crosswalk): not restricted."""
        return self._frame(self.paths(dataset, pattern)[0], columns, False)

    def outcome(self, year: int) -> pl.DataFrame:
        pattern = rf"cell_outcomes_{year}\.parquet$"
        remote = self.paths("cell_outcomes", pattern, self.outcome_key)[0]
        return self._frame(remote, OUTCOME_COLUMNS, True)


def load_candidates(reader: Reader) -> pl.DataFrame:
    """Council and mayoral candidacies 2004-2024 of the half, with `cd_ibge`."""
    cands = reader.read_whole("tse_candidates", r"candidates\.parquet$", CAND_COLUMNS).filter(
        pl.col("ano_eleicao").is_between(FIRST_CANDIDATE_YEAR, ALL_ELECTIONS[-1])
        & fz._cargo(fz.COUNCIL)
        | (pl.col("ano_eleicao").is_in(list(ALL_ELECTIONS)) & fz._cargo(fz.MAYOR))
    )
    munis = reader.read_whole("municipalities", r"municipalities\.parquet$", ["cd_ibge", "cd_tse"])
    joined, _ = fz.with_ibge(cands, munis)
    return reader.restrict(joined)


# --- Treatment side (no outcome)


def alignment_kinds(
    pairs: pl.DataFrame,
    sides: pl.DataFrame,
    coalition: dict[str, tuple[frozenset[str], frozenset[str]]],
    year: int,
) -> list[str]:
    """Per pair, in order: aligned, unaligned, mixed or left_out (idea 0004's rules).

    As `explore/0004_alignment_counts.py` `pair_types`, per pair instead of counted; its
    two left-out kinds (a side or the mayor not matched) are one kind here.
    """
    known = {
        (ue, sq): (party, fed) for ue, sq, party, fed in sides.iter_rows() if party is not None
    }
    out = []
    for ue, w, l in pairs.select(pl.col("sg_ue").cast(pl.Utf8), "w", "l").iter_rows():  # noqa: E741
        two = [known.get((ue, w)), known.get((ue, l))]
        if any(side is None for side in two) or ue not in coalition:
            out.append("left_out")
            continue
        flags = [fz.is_aligned(side[0], side[1], coalition[ue], year) for side in two]
        out.append("aligned" if all(flags) else "unaligned" if not any(flags) else "mixed")
    return out


def treatment_year(reader: Reader, cands: pl.DataFrame, year: int, window: float) -> dict[str, Any]:
    """Everything one election gives before any outcome is read."""
    cv = reader.read("tse_results", rf"candidate_votes_{year}\.parquet$")
    turnout = reader.read("tse_results", rf"turnout_{year}\.parquet$")
    places = reader.read("polling_places", rf"polling_places_{year}\.parquet$")
    tenure = reader.read("polling_place_tenure", rf"polling_place_tenure_{year}\.parquet$")
    if "ano" in tenure.columns:
        tenure = tenure.filter(pl.col("ano") == year)
    place_types = reader.read("polling_place_types", rf"polling_place_types_{year}\.parquet$")
    if "ano" in place_types.columns:
        place_types = place_types.filter(pl.col("ano") == year)
    coalitions = reader.read("tse_parties", rf"coalitions_{year}\.parquet$", COALITION_COLUMNS)

    main = sh.main_election(cv)
    paired = sh.margins(
        sh.within_list_pairs(sh.candidacy_votes(cv, year, main)), sh.valid_votes(turnout, main)
    )
    pairs = sh.close_pairs(paired, window)
    place_votes = pl.concat(
        [
            sh.place_candidate_votes(sv, main)
            for sv in reader.read_all(
                "section_votes", rf"section_votes_{year}_[A-Z]{{2}}\.parquet$"
            )
        ]
    )
    totals = sh.place_totals(place_votes)
    shares = sh.place_shares(place_votes)
    strong = sh.strongholds(place_votes)
    located = sh.locate_places(places)
    del place_votes
    # Only the pairs' candidates are looked up in `shares` (as in 0001_window.py).
    pair_cands = pl.concat(
        [
            pairs.select("cd_eleicao", pl.col("w").alias("sq_candidato")),
            pairs.select("cd_eleicao", pl.col("l").alias("sq_candidato")),
        ]
    ).unique()
    shares = shares.join(pair_cands, on=["cd_eleicao", "sq_candidato"], how="semi")

    cand = fz.candidate_distances(fz.close_candidates(paired, window), strong, tenure)
    council = cands.filter(fz._cargo(fz.COUNCIL))
    now = cands.filter(pl.col("ano_eleicao") == year)
    inc = fz.incumbent(council, year)
    cov_base = fz.candidate_covariates(council.filter(pl.col("ano_eleicao") == year)).join(
        inc, on=fz.CAND3, how="left"
    )
    mayors, _ = fz.elected_mayor(cv, main, year)
    coalition, _ = fz.mayor_coalition(mayors, now, coalitions, main)
    kinds = alignment_kinds(pairs, fz.council_parties(now, main), coalition, year)
    return {
        "pairs": pairs,
        "totals": totals,
        "shares": shares,
        "strong": strong,
        "located": located,
        "cand": cand,
        "kc1": fz.band_counts(cand),
        "table": fz.stronghold_table(strong, place_types, cand, located),
        "cov_base": cov_base,
        "inc": inc,
        "align": kinds,
    }


def incumbent_sign(pairs: pl.DataFrame, inc: pl.DataFrame) -> pl.DataFrame:
    """(`pair_id`, `s`): +1 if only the winner held the seat, -1 if only the loser did.

    Pairs with exactly one incumbent contribute to Z; the others (both, neither, or a
    side whose incumbency is unknown) have `s` = 0. Swapping a pair's sides negates `s`
    and its exposure term together, so Z does not change under re-flips.
    """
    flag = inc.select(
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8),
        "incumbent",
    )
    out = pairs.with_row_index("pair_id").select(
        "pair_id",
        pl.col("cd_eleicao").cast(pl.Int64),
        pl.col("sg_ue").cast(pl.Utf8),
        "w",
        "l",
    )
    for side in ("w", "l"):
        out = out.join(
            flag.rename({"sq_candidato": side, "incumbent": f"i_{side}"}),
            on=["cd_eleicao", "sg_ue", side],
            how="left",
        )
    iw, il = pl.col("i_w"), pl.col("i_l")
    s = pl.when((iw == 1.0) & (il == 0.0)).then(1.0).when((iw == 0.0) & (il == 1.0)).then(-1.0)
    return out.sort("pair_id").select("pair_id", s.otherwise(0.0).alias("s"))


def z_terms(terms: pl.DataFrame, sign: pl.DataFrame) -> pl.DataFrame:
    """(CELL, `pair_id`, `t`): the pair terms of Z, `s` times the pair's term of D."""
    return (
        terms.join(sign, on="pair_id", how="inner")
        .select(*sh.CELL, "pair_id", (pl.col("t") * pl.col("s")).alias("t"))
        .filter(pl.col("t") != 0)
        .sort([*sh.CELL, "pair_id"])
    )


def align_components(terms: pl.DataFrame, kinds: list[str]) -> dict[str, pl.DataFrame]:
    """D split by the pair's alignment kind: (CELL, `pair_id`, `t`) per kind."""
    kind = pl.DataFrame({"pair_id": np.arange(len(kinds), dtype=np.int64), "kind": kinds})
    joined = terms.join(
        kind.with_columns(pl.col("pair_id").cast(terms["pair_id"].dtype)), on="pair_id"
    )
    return {
        k: joined.filter(pl.col("kind") == k).select(*sh.CELL, "pair_id", "t") for k in ALIGN_KINDS
    }


# --- Outcome side


def exposure_table(
    cells: pl.DataFrame,
    located: pl.DataFrame,
    totals: pl.DataFrame,
    shares: pl.DataFrame,
    pairs: pl.DataFrame,
) -> pl.DataFrame:
    """The cells of the pairs' municipalities as `cell_exposure` holds them for these pairs.

    `terrain.builds.cell_exposure.year_table` with the window's pairs: `d_<kernel>` from
    `strongholds.exposure`, exp2 deciding the rows, then `nome_1KM` and `n_pairs`.
    """
    text = cells.with_columns(pl.col("cd_ibge").cast(pl.Utf8))
    dist = sh.cell_place_distances(text.select(sh.CELL), located)
    table = None
    for name in sh.KERNELS:
        d = sh.exposure(dist, totals, shares, pairs, name, "share").select(
            *sh.CELL, pl.col("D_i").alias(f"d_{name}")
        )
        table = d if table is None else table.join(d, on=sh.CELL, how="left")
    n_pairs = pairs.group_by("cd_ibge").len().select("cd_ibge", pl.col("len").alias("n_pairs"))
    return (
        table.join(text.select("nome_1KM", *sh.CELL), on=sh.CELL, how="inner")
        .join(n_pairs, on="cd_ibge", how="left")
        .with_columns(pl.col("n_pairs").fill_null(0).cast(pl.Int64))
        .sort(["cd_ibge", "y_km", "x_km"])
    )


def displacement_table(
    cells: pl.DataFrame, reached: pl.DataFrame, used: pl.DataFrame, munis: set[str]
) -> pl.DataFrame:
    """The unrepresented cells as `cell_displacement` holds them for these pairs."""
    text = cells.with_columns(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    unrep = sh.unrepresented(text, reached, munis)
    g = sh.displacement(unrep, used).rename({f"G_{k}": f"g_{k}" for k in sh.DISPLACEMENT_KERNELS})
    return g.join(text.select("nome_1KM", *sh.CELL), on=sh.CELL, how="inner").sort(
        ["cd_ibge", "y_km", "x_km"]
    )


def outcome_year(
    t: dict[str, Any], pairs: pl.DataFrame, grid: pl.DataFrame, by_year: dict, year: int
) -> dict:
    """One election's parts of every estimate, as `explore/0001_effects.py` `_year` builds them."""
    totals, shares, strong, located, cand = (
        t[k] for k in ("totals", "shares", "strong", "located", "cand")
    )
    y_table, outcome_dropped = fz.outcome_table(by_year, year)
    n_pairs = pairs.height
    munis = set(pairs["cd_ibge"].cast(pl.Utf8).to_list())
    cells = grid.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(sorted(munis)))
    with_pairs = exposure_table(cells, located, totals, shares, pairs).filter(pl.col("n_pairs") > 0)
    dist = sh.cell_place_distances(with_pairs.select(sh.CELL), located)
    parts: dict[str, Any] = {}
    counts: dict[str, dict[str, Any]] = {}
    sign = incumbent_sign(pairs, t["inc"])

    def add(label: str, sample: pl.DataFrame, terms: dict[str, pl.DataFrame], n_cells: int) -> None:
        parts[label] = fz.make_part(sample, terms, n_pairs, year)
        counts[label] = fz._counts(sample, pairs, n_cells - sample.height)

    for name in ("exp2", *DIRECT_RINGS):
        terms = fz.pair_terms(dist, totals, shares, pairs, name)
        fz.check_terms(terms, with_pairs, name)
        reached = with_pairs.filter(pl.col(f"d_{name}").is_not_null())
        sample = fz.slot_sample(reached, y_table, f"d_{name}", MAIN_SLOTS)
        label = "direct" if name == "exp2" else name
        add(label, sample, {"beta": terms}, reached.height)
        parts[f"{label}_adj"] = fz.make_part(sample, {"z": z_terms(terms, sign)}, n_pairs, year)
        if name == "exp2":
            direct_terms, direct_sample, direct_cells = terms, sample, reached.height
            direct_y3 = (
                fz.slot_sample(reached, y_table, "d_exp2", SLOTS["direct_y3"])
                if "Y3" in y_table.columns
                else None
            )
            pre = fz.slot_sample(reached, y_table, "d_exp2", SLOTS["direct_pre"])
            add("direct_pre", pre, {"beta": terms}, reached.height)
            parts["direct_pre_adj"] = fz.make_part(pre, {"z": z_terms(terms, sign)}, n_pairs, year)

    used = fz.with_pair_ids(sh.stronghold_pairs(pairs, strong, located)[0], pairs)
    displaced = displacement_table(cells, with_pairs.select(sh.CELL), used, munis)
    disp_terms = {}
    for name in ("exp10", *DISPLACEMENT_RINGS):
        terms = fz.displacement_terms_for(displaced, used, name)
        fz.check_displacement(terms, displaced, f"g_{name}")
        disp_terms[name] = terms
        sample = fz.slot_sample(displaced, y_table, f"g_{name}", MAIN_SLOTS)
        add(
            "displacement" if name == "exp10" else f"disp_{name}",
            sample,
            {"beta": terms},
            displaced.height,
        )
    sample = fz.slot_sample(displaced, y_table, "g_exp10", SLOTS["disp_pre"])
    add("disp_pre", sample, {"beta": disp_terms["exp10"]}, displaced.height)

    side = fz.side_terms(dist, totals, shares, pairs)
    types = {}
    for band in (5, 2):
        ptypes = fz.pair_types(pairs, cand, band)
        comps = fz.components(side, ptypes)
        fz.check_components(comps, with_pairs)
        add(f"split{band}", direct_sample, comps, direct_cells)
        types[f"{band}km"] = fz.type_counts(ptypes)

    add("align", direct_sample, align_components(direct_terms, t["align"]), direct_cells)

    if year == fz.Y3_ELECTION:
        add("direct_y3", direct_y3, {"beta": direct_terms}, direct_cells)
        y3_disp = fz.slot_sample(displaced, y_table, "g_exp10", SLOTS["displacement_y3"])
        add("displacement_y3", y3_disp, {"beta": disp_terms["exp10"]}, displaced.height)
    else:
        for label in ("direct_y3", "displacement_y3"):
            parts[label] = fz.empty_part(n_pairs, year)
            counts[label] = fz._counts(
                fz.slot_sample(displaced.head(0), y_table.head(0), "g_exp10", MAIN_SLOTS), pairs, 0
            )
    return {"parts": parts, "counts": counts, "types": types, "dropped": outcome_dropped}


def balance_differences(
    t: dict[str, Any], pairs: pl.DataFrame, grid: pl.DataFrame, by_year: dict, year: int
) -> np.ndarray:
    """(pairs, covariates) winner minus loser, as `explore/0001_window.py` builds them."""
    table = t["table"]
    near = table.filter(pl.col("sx").is_not_null())
    pop, clearing = fz.disc_covariates(
        grid, fz.pre_clearing_cells(by_year, year), near["sx"].to_numpy(), near["sy"].to_numpy()
    )
    table = table.join(
        near.select(*fz.CAND3).with_columns(
            pl.Series("pop22_5km", pop, dtype=pl.Float64),
            pl.Series("clearing_pre", clearing, dtype=pl.Float64).fill_nan(None),
        ),
        on=fz.CAND3,
        how="left",
    )
    cov = t["cov_base"].join(table.drop("sx", "sy"), on=fz.CAND3, how="left")
    return fz.pair_differences(pairs, cov, COVARIATES)


# --- Estimates and inference


@dataclass
class Adjusted:
    """The direct estimate with Z: D flips with the signs, Z (demeaned) stays fixed."""

    label: str
    design: Any
    z: np.ndarray
    y_tilde: dict[str, np.ndarray]


def adjusted_estimates(adj: Adjusted, signs: np.ndarray) -> dict[tuple[str, str], float]:
    """Coefficient on D / 2 with Z / 2 in the regression (Frisch-Waugh), and on Z / 2."""
    x = fz.demeaned_exposure(adj.design, signs)
    zz = float(adj.z @ adj.z)
    out: dict[tuple[str, str], float] = {}
    for w in fz.WINDOWS:
        y = adj.y_tilde[w]
        if zz <= 1e-12:
            b = fz.beta(x, y)
            out[(w, "beta")] = np.nan if b is None else b
            out[(w, "gamma")] = np.nan
            continue
        xr = x - (float(x @ adj.z) / zz) * adj.z
        den = float(xr @ xr)
        b = float(xr @ y) / den if den > 1e-12 else np.nan
        out[(w, "beta")] = b
        out[(w, "gamma")] = (float(adj.z @ y) - (0.0 if np.isnan(b) else b) * float(adj.z @ x)) / zz
    return out


def run_ri(
    specs: dict[str, Any], adjusted: dict[str, Adjusted], draws: int, seed: int
) -> tuple[dict, dict]:
    """`frozen.run_ri` with the adjusted estimates added, on the same sign vectors.

    The draws are those of `frozen.run_ri` (same generator, same calls, same order), so
    the estimates of run 42298466207 come out of the same draws as in that run.
    """
    n_pairs = next(iter(next(iter(specs.values())).designs.values())).n_pairs
    observed: dict[tuple[str, str, str], float] = {}
    sims: dict[tuple[str, str, str], np.ndarray] = {}
    ones = np.ones(n_pairs)
    for label, spec in specs.items():
        for (w, s), v in fz.estimates(spec, ones).items():
            observed[(label, w, s)] = v
            sims[(label, w, s)] = np.full(draws, np.nan)
    for label, adj in adjusted.items():
        for (w, s), v in adjusted_estimates(adj, ones).items():
            observed[(label, w, s)] = v
            sims[(label, w, s)] = np.full(draws, np.nan)
    rng = np.random.default_rng(seed)
    for r in range(draws):
        signs = rng.integers(0, 2, size=n_pairs).astype(float) * 2.0 - 1.0
        for label, spec in specs.items():
            for (w, s), v in fz.estimates(spec, signs).items():
                sims[(label, w, s)][r] = v
        for label, adj in adjusted.items():
            for (w, s), v in adjusted_estimates(adj, signs).items():
                sims[(label, w, s)][r] = v
    return observed, sims


def report_adjusted(adj: Adjusted, base: Any, observed: dict, sims: dict) -> dict[str, Any]:
    """Per window: the adjusted slope, its RI p and quantiles, and the coefficient on Z / 2."""
    out: dict[str, Any] = {"slots": {}, "z_cells_nonzero": int(np.sum(np.abs(adj.z) > 1e-12))}
    for w in fz.WINDOWS:
        b = observed[(adj.label, w, "beta")]
        draws = sims[(adj.label, w, "beta")]
        finite = draws[~np.isnan(draws)]
        x_abs, y_active = fz.exposure_cells(base, "beta", w)
        ybar = float(np.mean(y_active)) if y_active.size else None
        x_mean = float(np.mean(x_abs)) if x_abs.size else None
        out["slots"][w] = {
            "beta": {
                "slope": b,
                "ri_p": fz.ri_p(b, draws),
                "q025": float(np.quantile(finite, 0.025)) if finite.size else None,
                "q975": float(np.quantile(finite, 0.975)) if finite.size else None,
                "mean_y": float(np.mean(base.y_raw[w])) if base.y_raw[w].size else None,
                "pct_of_baseline": None
                if x_mean is None or ybar is None or np.isnan(b)
                else fz.pct_effect(b, x_mean, ybar),
                "coef_z": observed[(adj.label, w, "gamma")],
            }
        }
    return fz._clean(out)


def report_align(spec: Any, observed: dict, sims: dict) -> dict[str, Any]:
    """`report_estimate` of the alignment components, plus aligned minus unaligned."""
    out = fz.report_estimate(spec, observed, sims)
    if {"aligned", "unaligned"} <= set(spec.kept):
        for w in fz.WINDOWS:
            d = observed[(spec.label, w, "aligned")] - observed[(spec.label, w, "unaligned")]
            draws = sims[(spec.label, w, "aligned")] - sims[(spec.label, w, "unaligned")]
            finite = draws[~np.isnan(draws)]
            out["slots"][w]["delta"] = fz._clean(
                {
                    "slope": d,
                    "ri_p": fz.ri_p(d, draws),
                    "q025": float(np.quantile(finite, 0.025)) if finite.size else None,
                    "q975": float(np.quantile(finite, 0.975)) if finite.size else None,
                }
            )
    return out


def balance(diffs: list[np.ndarray], draws: int, seed: int) -> dict[str, Any]:
    """Issue #206's balance table at the window, pooled 2008-2024, and the omnibus p."""
    diff = np.concatenate(diffs) if diffs else np.zeros((0, len(COVARIATES)))
    signs = fz.sign_matrix(diff.shape[0], draws, seed)
    observed, sims, n = fz.flip_means(diff, signs, np.ones(diff.shape[0], dtype=bool))
    p = fz.raw_p(observed, sims)
    use = np.array([name in fz.BALANCE for name in COVARIATES])
    return fz._clean(
        {
            "pairs": int(diff.shape[0]),
            "omnibus_p": fz.omnibus_p(observed, sims, n, use),
            "covariates": {
                name: {"diff": float(observed[i]), "p": float(p[i]), "pairs": int(n[i])}
                for i, name in enumerate(COVARIATES)
            },
        }
    )


# --- The run


def assign_all(
    by_year: dict[int, pl.DataFrame], assign: Callable[[pl.DataFrame], pl.DataFrame]
) -> dict[int, pl.DataFrame]:
    """Take the treatment of every election in one call, before any outcome is read.

    `assign` sees one narrow table (election, pair keys, `w`, `l`) and returns it with
    `w` and `l` as assigned, rows in the same order. Each year's pairs keep their own
    columns and types; only `w` and `l` are replaced.
    """
    narrow = pl.concat(
        [
            p.select(
                pl.lit(y, dtype=pl.Int64).alias("election"),
                pl.col("cd_eleicao").cast(pl.Int64),
                pl.col("sg_ue").cast(pl.Utf8),
                pl.col("w").cast(pl.Utf8),
                pl.col("l").cast(pl.Utf8),
            )
            for y, p in by_year.items()
        ]
    )
    got = assign(narrow)
    if got.height != narrow.height or not got["election"].equals(narrow["election"]):
        raise confirm.ConfirmError("assign must return every pair, in order")
    out = {}
    for y, p in by_year.items():
        part = got.filter(pl.col("election") == y)
        out[y] = p.with_columns(part["w"].alias("w"), part["l"].alias("l"))
    return out


def run(
    reader: Reader, settings: Settings, assign: Callable[[pl.DataFrame], pl.DataFrame]
) -> dict[str, Any]:
    """The whole analysis on the half `reader` reads. Returns the full results."""
    cands = load_candidates(reader)
    treated = {y: treatment_year(reader, cands, y, settings.window) for y in ALL_ELECTIONS}
    del cands

    pairs = assign_all({y: treated[y]["pairs"] for y in ALL_ELECTIONS}, assign)

    kc1_pooled = fz.pool({str(y): treated[y]["kc1"] for y in ALL_ELECTIONS})
    kc1_deciding = {layer: kc1_pooled[layer]["5km"] for layer in fz.LAYERS}
    results: dict[str, Any] = {
        "window": settings.window,
        "draws": settings.draws,
        "seed": settings.seed,
        "pairs": {str(y): pairs[y].height for y in ALL_ELECTIONS},
        "kill_criterion_1": {
            "per_election": {str(y): treated[y]["kc1"] for y in ALL_ELECTIONS},
            "pooled": kc1_pooled,
            "met": any(v < KC1_MINIMUM for v in kc1_deciding.values()),
        },
        "alignment_kinds": {
            str(y): {k: treated[y]["align"].count(k) for k in ALIGN_KINDS} for y in ALL_ELECTIONS
        },
    }
    if results["kill_criterion_1"]["met"]:
        results["stopped"] = "kill_criterion_1"
        return results

    grid = reader.read("grid_cells", r"grid_cells\.parquet$", GRID_COLUMNS)
    labels = (*EFFECT_LABELS, *NEW_LABELS, *ADJUSTED)
    parts: dict[str, list[Any]] = {k: [] for k in labels}
    counts: dict[str, dict[int, dict[str, Any]]] = {k: {} for k in (*EFFECT_LABELS, *NEW_LABELS)}
    types: dict[str, dict[str, Any]] = {"5km": {}, "2km": {}}
    dropped: dict[str, dict[str, int]] = {}
    diffs = []
    for year in ALL_ELECTIONS:
        years = fz.outcome_years(year) if year in OUTCOME_ELECTIONS else fz.pre_years(year)
        by_year = {y: reader.outcome(y) for y in years}
        diffs.append(balance_differences(treated[year], pairs[year], grid, by_year, year))
        if year in OUTCOME_ELECTIONS:
            got = outcome_year(treated[year], pairs[year], grid, by_year, year)
            dropped[str(year)] = got["dropped"]
            for label in labels:
                parts[label].append(got["parts"][label])
            for label in counts:
                counts[label][year] = got["counts"][label]
            for band, per in got["types"].items():
                types[band][str(year)] = per
        del by_year
    results["balance"] = balance(diffs, settings.draws, settings.seed)
    omnibus = results["balance"]["omnibus_p"]
    results["fallback"] = omnibus is None or omnibus < FALLBACK_P

    specs = {label: fz.assemble(label, parts[label]) for label in (*EFFECT_LABELS, *NEW_LABELS)}
    adjusted = {}
    for label, base in ADJUSTED.items():
        z_spec = fz.assemble(label, parts[label])
        z_design = z_spec.designs["z"]
        adjusted[label] = Adjusted(
            label=label,
            design=specs[base].designs["beta"],
            z=fz.demeaned_exposure(z_design, np.ones(z_design.n_pairs)),
            y_tilde=specs[base].y_tilde,
        )
    observed, sims = run_ri(specs, adjusted, settings.draws, settings.seed)
    per_election = fz._per_election(counts, specs)
    estimates = {}
    for label, spec in specs.items():
        estimates[label] = (
            report_align(spec, observed, sims)
            if label == "align"
            else fz.report_estimate(spec, observed, sims)
        )
        estimates[label]["counts"] = per_election[label]
    for label, base in ADJUSTED.items():
        estimates[label] = report_adjusted(adjusted[label], specs[base], observed, sims)
    results.update(
        {
            "elections": list(OUTCOME_ELECTIONS),
            "outcome_years": {str(e): fz.outcome_years(e) for e in OUTCOME_ELECTIONS},
            "y3_years": list(fz.Y3_YEARS),
            "outcome_cells_dropped": dropped,
            "type_counts": {
                band: {"per_election": per, "pooled": fz.pool_type_counts(per)}
                for band, per in types.items()
            },
            "pairs_one_incumbent": {
                str(y): int(
                    incumbent_sign(pairs[y], treated[y]["inc"]).filter(pl.col("s") != 0).height
                )
                for y in OUTCOME_ELECTIONS
            },
            "estimates": estimates,
            "confirmatory": {
                "kill_criterion_4": "direct_adj" if results["fallback"] else "direct",
                "kill_criterion_2": "direct_pre_adj" if results["fallback"] else "direct_pre",
            },
        }
    )
    return results


# --- The ledger's numbers


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def ledger_results(results: dict[str, Any]) -> dict[str, Any]:
    """The results as `terrain.confirm.validate_results` takes them: numbers and names only."""
    kc1 = results["kill_criterion_1"]
    counts: dict[str, int] = {f"pairs_{y}": n for y, n in results["pairs"].items()}
    for layer in fz.LAYERS:
        for band, n in kc1["pooled"][layer].items():
            counts[f"kc1_{layer}_{band}"] = int(n)
    counts["kc1_met"] = int(kc1["met"])
    for kind in ALIGN_KINDS:
        counts[f"align_{kind}"] = sum(
            v[kind] for y, v in results["alignment_kinds"].items() if int(y) <= 2020
        )
    out: dict[str, Any] = {"estimates": [], "counts": counts, "values": dict(POWER)}
    if results.get("stopped"):
        out["stopped"] = results["stopped"]
        return out
    counts["fallback"] = int(results["fallback"])
    counts["pairs_one_incumbent"] = sum(results["pairs_one_incumbent"].values())
    bal = results["balance"]
    for name, row in bal["covariates"].items():
        out["estimates"].append(
            {
                "name": f"balance_{name}",
                "estimate": _num(row["diff"]),
                "p_value": _num(row["p"]),
                "confirmatory": False,
            }
        )
    out["values"]["balance_omnibus_p"] = _num(bal["omnibus_p"])
    confirmatory = {
        f"{results['confirmatory'][k]}_y4_beta" for k in ("kill_criterion_4", "kill_criterion_2")
    }
    for label, est in results["estimates"].items():
        for w, rows in est["slots"].items():
            for s, r in rows.items():
                name = f"{label}_{w}_{s}".lower()
                row = {
                    "name": name,
                    "estimate": _num(r.get("slope")),
                    "p_value": _num(r.get("ri_p")),
                    "confirmatory": name in confirmatory,
                }
                for extra in (
                    "q025",
                    "q975",
                    "clustered_se",
                    "mean_y",
                    "pct_of_baseline",
                    "p1",
                    "coef_z",
                ):
                    if extra in r:
                        row[extra] = _num(r[extra])
                out["estimates"].append(row)
        if "counts" in est:
            pooled = est["counts"]["pooled"]
            counts[f"cells_{label}"] = int(pooled["cells"])
    return out


def check_spec(spec: dict[str, Any]) -> Settings:
    """The specification's fields must describe what this analysis does."""
    for path, wanted in SPEC_FIELDS.items():
        value: Any = spec
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if value != wanted:
            raise confirm.ConfirmError(
                f"{'.'.join(path)} must be {wanted!r} for {ANALYSIS}, not {value!r}"
            )
    params = spec.get("params") or {}
    window, seed, draws = (
        params.get("window"),
        params.get("ri_seed"),
        spec["inference"].get("draws"),
    )
    if not isinstance(window, float) or not 0 < window < 0.05:
        raise confirm.ConfirmError("params.window must be a share of valid votes, e.g. 0.0025")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise confirm.ConfirmError("params.ri_seed must be a whole number")
    if not isinstance(draws, int) or isinstance(draws, bool) or draws < 100:
        raise confirm.ConfirmError("inference.draws must be a whole number of at least 100")
    return Settings(window=window, draws=draws, seed=seed)


@confirm.register(ANALYSIS)
def analyse(ctx: confirm.RunContext) -> dict[str, Any]:
    """The registered entry point: the confirmation half, through `ctx`."""
    settings = check_spec(dict(ctx.spec))

    def assign(stacked: pl.DataFrame) -> pl.DataFrame:
        return ctx.assign(
            stacked, key=("cd_eleicao", "sg_ue", "w", "l"), side_columns=(("w", "l"),), negate=()
        )

    with tempfile.TemporaryDirectory() as tmp:
        reader = Reader(ctx.download, ctx.restrict, "sealed_files", Path(tmp))
        return ledger_results(run(reader, settings, assign))


def run_exploration(
    store: Any,
    half: frozenset[str],
    window: float,
    tmp: Path,
    draws: int = fz.DRAWS,
    seed: int = fz.SEED,
    manifests: Path | None = None,
    restrict_fn: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
) -> dict[str, Any]:
    """The same analysis on the exploration half, with the real treatment (validation only).

    Refuses the registered window: before registration the analysis is never run at 0.25%.
    """
    from terrain.explore import restrict

    if abs(window - REGISTERED_WINDOW) < 1e-12:
        raise confirm.ConfirmError(
            "the registered window is not run on any data before registration"
        )
    keep = restrict_fn if restrict_fn is not None else (lambda df: restrict(df, half))
    reader = Reader(store.download, keep, "files", tmp, manifests)
    return run(reader, Settings(window=window, draws=draws, seed=seed), lambda df: df)
