"""Close council races and the exposure of 1 km cells to them (idea 0001, decision 0004).

These are the definitions of `explore/0001_feasibility_census.py` and
`explore/0001_exposure_options.py`, and, in the last section, of
`explore/0001_displacement_options.py` (decision 0005; three kernels, no `nearest`),
copied without a change in behaviour so that a build can use them (builds never import
`explore/`). `tests/test_strongholds.py` checks each function against its original on
the same tables. Change a function here only together with a new exploration run that
says so.
"""

from __future__ import annotations

from collections.abc import Collection

import numpy as np
import polars as pl
import shapely
from shapely import STRtree

from terrain.grid import to_albers_km

# --- From the census

HEADLINE = 0.005
COUNCIL = 13
LIST_KEY = ["cd_eleicao", "sg_ue", "cd_ibge", "sq_coligacao"]
CAND_KEY = ["cd_eleicao", "sg_ue", "sq_candidato"]
PLACE_KEY = ["cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao"]
MIN_PLACE_VOTES = 50

# cd_sit_tot_turno: the codes changed between 2008 and 2012.
ELECTED_CODES = {2008: {1, 5}, 2012: {2, 3}}
NOT_ELECTED_CODES = {2008: {2, 4}, 2012: {4, 5}}


def _codes(table: dict[int, set[int]], year: int) -> list[int]:
    return sorted(table[2008] if year == 2008 else table[2012])


def _council_round1(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(
        (pl.col("cd_cargo").cast(pl.Int64, strict=False) == COUNCIL)
        & (pl.col("nr_turno").cast(pl.Int64, strict=False) == 1)
    )


def main_election(candidate_votes: pl.DataFrame) -> int:
    """The council, round-1 `cd_eleicao` with the most rows (the year's main election)."""
    rows = _council_round1(candidate_votes).group_by("cd_eleicao").len()
    return int(rows.sort(["len", "cd_eleicao"], descending=[True, False])["cd_eleicao"][0])


def elected_status(df: pl.DataFrame, year: int) -> pl.DataFrame:
    """Add `elected` (bool) from `cd_sit_tot_turno`; other codes are dropped."""
    code = pl.col("cd_sit_tot_turno").cast(pl.Int64, strict=False)
    elected = code.is_in(_codes(ELECTED_CODES, year))
    not_elected = code.is_in(_codes(NOT_ELECTED_CODES, year))
    return df.filter(elected | not_elected).with_columns(elected.alias("elected"))


def candidacy_votes(candidate_votes: pl.DataFrame, year: int, main: int) -> pl.DataFrame:
    """Counted votes per candidacy in the main council election, summed over zones."""
    df = _council_round1(candidate_votes).filter(pl.col("cd_eleicao") == main)
    df = elected_status(df, year).filter(pl.col("sq_coligacao").is_not_null())
    return df.group_by(CAND_KEY, maintain_order=True).agg(
        pl.col("qt_votos_nominais").sum().alias("votes"),
        pl.col("cd_ibge").first(),
        pl.col("sq_coligacao").first(),
        pl.col("elected").first(),
    )


def within_list_pairs(cands: pl.DataFrame) -> pl.DataFrame:
    """Per list: the elected candidate with the fewest votes vs the non-elected with the most.

    Only candidates with votes above 0 take part; a list needs one of each kind.
    """
    voted = cands.filter(pl.col("votes") > 0)
    low = (
        voted.filter(pl.col("elected"))
        .sort(["votes", "sq_candidato"])
        .group_by(LIST_KEY, maintain_order=True)
        .first()
        .select(
            *LIST_KEY,
            pl.col("sq_candidato").alias("elected_sq"),
            pl.col("votes").alias("elected_votes"),
        )
    )
    high = (
        voted.filter(~pl.col("elected"))
        .sort(["votes", "sq_candidato"], descending=[True, False])
        .group_by(LIST_KEY, maintain_order=True)
        .first()
        .select(
            *LIST_KEY,
            pl.col("sq_candidato").alias("other_sq"),
            pl.col("votes").alias("other_votes"),
        )
    )
    return low.join(high, on=LIST_KEY, how="inner").sort(LIST_KEY)


def valid_votes(turnout: pl.DataFrame, main: int) -> pl.DataFrame:
    """Valid council votes per municipality, round 1, main election, summed over zones."""
    df = _council_round1(turnout).filter(pl.col("cd_eleicao") == main)
    return df.group_by(["cd_eleicao", "sg_ue"]).agg(
        pl.col("qt_total_votos_validos").sum().alias("valid_votes")
    )


def margins(pairs: pl.DataFrame, valid: pl.DataFrame) -> pl.DataFrame:
    """Add `margin` = (elected - other) / valid votes, and `inverted` when it is negative."""
    out = pairs.join(valid, on=["cd_eleicao", "sg_ue"], how="left")
    margin = (pl.col("elected_votes") - pl.col("other_votes")) / pl.col("valid_votes")
    return out.with_columns(margin.alias("margin"), (margin < 0).fill_null(False).alias("inverted"))


def place_candidate_votes(section_votes: pl.DataFrame, main: int) -> pl.DataFrame:
    """Counted candidate and legend votes per polling place and candidacy.

    Council, round 1, the main election; annulled rows and other vote types dropped.
    """
    df = _council_round1(section_votes).filter(
        (pl.col("cd_eleicao") == main)
        & pl.col("vote_type").is_in(["candidate", "legend"])
        & ~pl.col("annulled_in_results").fill_null(False)
    )
    return (
        df.with_columns(pl.col("nr_zona").cast(pl.Int64), pl.col("nr_local_votacao").cast(pl.Int64))
        .group_by([*PLACE_KEY, "cd_eleicao", "vote_type", "sq_candidato"])
        .agg(pl.col("qt_votos").sum().alias("votes"))
    )


def strongholds(place_votes: pl.DataFrame, min_place_votes: int = MIN_PLACE_VOTES) -> pl.DataFrame:
    """The place with the highest location quotient among places with V_p >= the minimum.

    `place_votes` comes from `place_candidate_votes`. V_p is the place's candidate
    plus legend votes; the municipal total is the sum of V_p over all its places.
    Ties go to the place with more of the candidate's votes, then the lower place key.
    """
    muni = ["cd_eleicao", "sg_ue"]
    places = place_votes.group_by([*PLACE_KEY, "cd_eleicao"]).agg(pl.col("votes").sum().alias("vp"))
    totals = places.group_by(muni).agg(pl.col("vp").sum().alias("muni_total"))
    cands = place_votes.filter(pl.col("vote_type") == "candidate").filter(
        pl.col("sq_candidato").is_not_null()
    )
    cand_totals = cands.group_by(CAND_KEY).agg(pl.col("votes").sum().alias("cand_total"))
    joined = (
        cands.join(places, on=[*PLACE_KEY, "cd_eleicao"])
        .join(totals, on=muni)
        .join(cand_totals, on=CAND_KEY)
        .filter((pl.col("vp") >= min_place_votes) & (pl.col("cand_total") > 0))
        .with_columns(
            (
                (pl.col("votes") / pl.col("vp")) / (pl.col("cand_total") / pl.col("muni_total"))
            ).alias("quotient")
        )
    )
    return (
        joined.sort(
            ["quotient", "votes", "nr_zona", "nr_local_votacao"],
            descending=[True, True, False, False],
        )
        .group_by(CAND_KEY, maintain_order=True)
        .first()
        .select(
            *CAND_KEY,
            "cd_ibge",
            "nr_zona",
            "nr_local_votacao",
            "quotient",
            pl.col("votes").alias("stronghold_votes"),
        )
    )


# --- From the exposure options

CELL = ["cd_ibge", "x_km", "y_km"]
MAX_KM = 10.0
TOLERANCE = 1e-9
KERNELS = ("exp2", "ring2", "ring5")
MEASURES = ("share", "votes")


def _text_keys() -> list[pl.Expr]:
    return [pl.col("cd_ibge").cast(pl.Utf8), pl.col("sg_ue").cast(pl.Utf8)]


def close_pairs(paired: pl.DataFrame, threshold: float = HEADLINE) -> pl.DataFrame:
    """Non-inverted pairs within `threshold`: `w` is the elected candidate, `l` the other."""
    close = paired.filter(~pl.col("inverted") & (pl.col("margin").abs() <= threshold + 1e-12))
    return close.select(
        *_text_keys(),
        "cd_eleicao",
        pl.col("elected_sq").cast(pl.Utf8).alias("w"),
        pl.col("other_sq").cast(pl.Utf8).alias("l"),
    )


def place_totals(place_votes: pl.DataFrame) -> pl.DataFrame:
    """`vp`, the candidate plus legend votes of each place; places with `vp` = 0 are dropped."""
    keys = [*PLACE_KEY, "cd_eleicao"]
    totals = (
        place_votes.with_columns(*_text_keys())
        .group_by(keys)
        .agg(pl.col("votes").sum().alias("vp"))
    )
    return totals.filter(pl.col("vp") > 0)


def place_shares(place_votes: pl.DataFrame) -> pl.DataFrame:
    """Per place and candidate: `v_cp` (votes) and `s_cp` (votes / V_p). Places with V_p = 0 go."""
    keys = [*PLACE_KEY, "cd_eleicao"]
    totals = place_totals(place_votes)
    cands = (
        place_votes.with_columns(*_text_keys())
        .filter((pl.col("vote_type") == "candidate") & pl.col("sq_candidato").is_not_null())
        .with_columns(pl.col("sq_candidato").cast(pl.Utf8))
        .group_by([*keys, "sq_candidato"])
        .agg(pl.col("votes").sum().alias("v_cp"))
    )
    return cands.join(totals, on=keys, how="inner").select(
        *keys, "sq_candidato", "v_cp", (pl.col("v_cp") / pl.col("vp")).alias("s_cp")
    )


def locate_places(places: pl.DataFrame) -> pl.DataFrame:
    """Places with coordinates, keyed as `PLACE_KEY`, with `x_km` and `y_km` in Albers km."""
    located = (
        places.filter(pl.col("lat").is_not_null() & pl.col("long").is_not_null())
        .with_columns(
            *_text_keys(),
            pl.col("nr_zona").cast(pl.Int64),
            pl.col("nr_local_votacao").cast(pl.Int64),
        )
        .unique(PLACE_KEY, keep="first", maintain_order=True)
    )
    points = to_albers_km(
        shapely.points(
            located["long"].to_numpy().astype(float), located["lat"].to_numpy().astype(float)
        )
    )
    return located.select(
        *PLACE_KEY,
        pl.Series("x_km", shapely.get_x(points), dtype=pl.Float64),
        pl.Series("y_km", shapely.get_y(points), dtype=pl.Float64),
    )


def cell_place_distances(
    cells: pl.DataFrame, places: pl.DataFrame, max_km: float = MAX_KM
) -> pl.DataFrame:
    """(cell, place, `d`) for places within `max_km` of the cell centre, same municipality only.

    `cells` has `cd_ibge`, `x_km`, `y_km` (lower-left corner); `places` comes from
    `locate_places`. One `STRtree` per municipality holds only that municipality's places.
    """
    by_muni = {
        part["cd_ibge"][0]: part
        for part in places.with_columns(*_text_keys()).partition_by("cd_ibge")
    }
    pieces = []
    for part in cells.with_columns(pl.col("cd_ibge").cast(pl.Utf8)).partition_by("cd_ibge"):
        found = by_muni.get(part["cd_ibge"][0])
        if found is None:
            continue
        cx = part["x_km"].to_numpy().astype(float) + 0.5
        cy = part["y_km"].to_numpy().astype(float) + 0.5
        px = found["x_km"].to_numpy()
        py = found["y_km"].to_numpy()
        tree = STRtree(shapely.points(px, py))
        hit = tree.query(shapely.points(cx, cy), predicate="dwithin", distance=max_km)
        if hit.shape[1] == 0:
            continue
        cell_i, place_i = hit[0], hit[1]
        d = np.hypot(cx[cell_i] - px[place_i], cy[cell_i] - py[place_i])
        pieces.append(
            pl.concat(
                [
                    part.select(CELL)[cell_i.tolist()],
                    found.select("sg_ue", "nr_zona", "nr_local_votacao")[place_i.tolist()],
                    pl.DataFrame({"d": d}),
                ],
                how="horizontal",
            )
        )
    if not pieces:
        return pl.DataFrame(
            schema={
                "cd_ibge": pl.Utf8,
                "x_km": pl.Int64,
                "y_km": pl.Int64,
                "sg_ue": pl.Utf8,
                "nr_zona": pl.Int64,
                "nr_local_votacao": pl.Int64,
                "d": pl.Float64,
            }
        )
    return pl.concat(pieces)


def kernel(name: str, d: pl.Expr) -> pl.Expr:
    """K(d): `exp2` = exp(-d/2) up to 10 km, `ring2` and `ring5` = 1 up to 2 and 5 km, else 0."""
    if name == "exp2":
        return pl.when(d <= MAX_KM + TOLERANCE).then((-d / 2).exp()).otherwise(0.0)
    if name in ("ring2", "ring5"):
        radius = float(name[4:])
        return pl.when(d <= radius + TOLERANCE).then(1.0).otherwise(0.0)
    raise ValueError(f"unknown kernel {name!r}")


def exposure(
    dist: pl.DataFrame,
    totals: pl.DataFrame,
    shares: pl.DataFrame,
    pairs: pl.DataFrame,
    kernel_name: str,
    measure: str,
) -> pl.DataFrame:
    """Reached cells with `D_i` and `exposed` for one kernel and one measure.

    A cell is reached when the kernel weights of the municipality's places (those with
    votes) add up to more than 0; cells that are not reached are not returned. `D_i` is
    the sum over the municipality's pairs of E_iw - E_il: with `share`, E is the
    kernel-weighted mean of the candidate's place share (0 where the candidate has no
    votes at a reached place); with `votes`, the kernel-weighted sum of votes.
    """
    if measure not in MEASURES:
        raise ValueError(f"unknown measure {measure!r}")
    column = "s_cp" if measure == "share" else "v_cp"
    near = (
        dist.join(totals.select(PLACE_KEY).unique(), on=PLACE_KEY, how="semi")
        .with_columns(kernel(kernel_name, pl.col("d")).alias("k"))
        .filter(pl.col("k") > 0)
    )
    reached = near.group_by(CELL).agg(pl.col("k").sum().alias("sum_k"))
    pair_rows = pairs.with_row_index("pair_id")
    rows = near.join(
        pair_rows.select("pair_id", "cd_ibge", "sg_ue", "cd_eleicao", "w", "l"),
        on=["cd_ibge", "sg_ue"],
    )
    lookup = shares.select(*PLACE_KEY, "cd_eleicao", "sq_candidato", pl.col(column).alias("a"))
    keys = [*PLACE_KEY, "cd_eleicao"]
    for side in ("w", "l"):
        side_lookup = lookup.rename({"sq_candidato": side, "a": f"a_{side}"})
        rows = rows.join(side_lookup, on=[*keys, side], how="left")
    contrast = (
        rows.with_columns(
            (pl.col("k") * (pl.col("a_w").fill_null(0.0) - pl.col("a_l").fill_null(0.0))).alias(
                "term"
            )
        )
        .group_by(CELL)
        .agg(pl.col("term").sum().alias("D_i"))
    )
    out = reached.join(contrast, on=CELL, how="left").with_columns(pl.col("D_i").fill_null(0.0))
    if measure == "share":
        out = out.with_columns(pl.col("D_i") / pl.col("sum_k"))
    return out.select(*CELL, "D_i", (pl.col("D_i").abs() > 0).alias("exposed")).sort(CELL)


# --- From the displacement options

OUTER_KM = 50.0
DISPLACEMENT_KERNELS = ("exp10", "ring10_20", "ring20_50")


def stronghold_pairs(
    pairs: pl.DataFrame, strong: pl.DataFrame, located: pl.DataFrame
) -> tuple[pl.DataFrame, int, int]:
    """Attach `xw`, `yw`, `xl`, `yl` (Albers km) of each pair's strongholds.

    Returns (pairs used, `dropped_same_place`, `dropped_no_coordinates`). A pair whose
    two candidates share a stronghold place is dropped as same place. Any other pair
    where a candidate has no stronghold (no place with enough votes) or a stronghold
    without coordinates is dropped as no coordinates.
    """
    cand = strong.select(
        "cd_eleicao",
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("sq_candidato").cast(pl.Utf8).alias("cand"),
        pl.col("cd_ibge").cast(pl.Utf8).alias("cd_place"),
        pl.col("nr_zona").cast(pl.Int64).alias("zona"),
        pl.col("nr_local_votacao").cast(pl.Int64).alias("local"),
    )
    where = located.select(
        pl.col("cd_ibge").alias("cd_place"),
        pl.col("sg_ue"),
        pl.col("nr_zona").alias("zona"),
        pl.col("nr_local_votacao").alias("local"),
        "x_km",
        "y_km",
    )
    out = pairs
    for side in ("w", "l"):
        side_place = cand.select(
            "cd_eleicao",
            "sg_ue",
            pl.col("cand").alias(side),
            *(pl.col(c).alias(f"{c}_{side}") for c in ("cd_place", "zona", "local")),
        )
        side_where = where.select(
            "sg_ue",
            *(pl.col(c).alias(f"{c}_{side}") for c in ("cd_place", "zona", "local")),
            pl.col("x_km").alias(f"x{side}"),
            pl.col("y_km").alias(f"y{side}"),
        )
        out = out.join(side_place, on=["cd_eleicao", "sg_ue", side], how="left").join(
            side_where,
            on=["sg_ue", f"cd_place_{side}", f"zona_{side}", f"local_{side}"],
            how="left",
        )
    both = pl.col("local_w").is_not_null() & pl.col("local_l").is_not_null()
    same = (
        both
        & (pl.col("cd_place_w") == pl.col("cd_place_l"))
        & (pl.col("zona_w") == pl.col("zona_l"))
        & (pl.col("local_w") == pl.col("local_l"))
    ).fill_null(False)
    located_both = pl.col("xw").is_not_null() & pl.col("xl").is_not_null()
    used = out.filter(~same & located_both).select(
        "cd_ibge", "sg_ue", "cd_eleicao", "w", "l", "xw", "yw", "xl", "yl"
    )
    return used, out.filter(same).height, out.filter(~same & ~located_both).height


def unrepresented(
    cells: pl.DataFrame, exposure_year: pl.DataFrame, muni_with_pair: Collection[str]
) -> pl.DataFrame:
    """Cells with `pop_2022` = 0 that `exposure_year` does not reach, where a pair exists."""
    reached = exposure_year.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    ).unique()
    return (
        cells.with_columns(
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("x_km").cast(pl.Int64),
            pl.col("y_km").cast(pl.Int64),
        )
        .filter((pl.col("pop_2022") == 0) & pl.col("cd_ibge").is_in(list(muni_with_pair)))
        .join(reached, on=CELL, how="anti")
    )


def kernel_g(name: str, d_w: np.ndarray, d_l: np.ndarray) -> np.ndarray:
    """One pair's term of `G_i` for each cell, from distances (km) to `p_w` and `p_l`.

    `ring10_20`: 1 for 10 < d <= 20 km; `ring20_50`: 1 for 20 < d <= 50; `exp10`:
    exp(-d / 10) for d <= 50. Each is K(d_w) - K(d_l). Boundaries use `TOLERANCE`: a
    distance of 10 + 1e-12 counts as 10.
    """
    d_w = np.asarray(d_w, dtype=float)
    d_l = np.asarray(d_l, dtype=float)

    def ring(d: np.ndarray, low: float, high: float) -> np.ndarray:
        return ((d > low + TOLERANCE) & (d <= high + TOLERANCE)).astype(float)

    def expo(d: np.ndarray) -> np.ndarray:
        return np.where(d <= OUTER_KM + TOLERANCE, np.exp(-d / 10.0), 0.0)

    if name == "ring10_20":
        return ring(d_w, 10.0, 20.0) - ring(d_l, 10.0, 20.0)
    if name == "ring20_50":
        return ring(d_w, 20.0, 50.0) - ring(d_l, 20.0, 50.0)
    if name == "exp10":
        return expo(d_w) - expo(d_l)
    raise ValueError(f"unknown variant {name}")


def displacement(cells: pl.DataFrame, used_pairs: pl.DataFrame) -> pl.DataFrame:
    """`G_<kernel>` for each cell: CELL columns plus one column per displacement kernel.

    Distances run from the cell centre (corner + 0.5 km) to the strongholds of pairs
    of the cell's own municipality. A municipality without a used pair gets 0.
    """
    cells = cells.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("x_km").cast(pl.Int64),
        pl.col("y_km").cast(pl.Int64),
    )
    cx = cells["x_km"].to_numpy().astype(float) + 0.5
    cy = cells["y_km"].to_numpy().astype(float) + 0.5
    muni = cells["cd_ibge"].to_numpy()
    totals = {v: np.zeros(cells.height) for v in DISPLACEMENT_KERNELS}
    pair_muni = used_pairs["cd_ibge"].cast(pl.Utf8).to_numpy()
    rows = used_pairs.select("xw", "yw", "xl", "yl").to_numpy()
    for code in np.unique(pair_muni):
        index = np.flatnonzero(muni == code)
        if index.size == 0:
            continue
        for xw, yw, xl, yl in rows[pair_muni == code]:
            d_w = np.hypot(cx[index] - xw, cy[index] - yw)
            d_l = np.hypot(cx[index] - xl, cy[index] - yl)
            for v in DISPLACEMENT_KERNELS:
                totals[v][index] += kernel_g(v, d_w, d_l)
    return cells.with_columns(*(pl.Series(f"G_{v}", totals[v]) for v in DISPLACEMENT_KERNELS))
