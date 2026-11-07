"""A synthetic world for idea 0001's registered analysis: every table it reads.

Forty municipalities in one state, council elections 2004-2024 (2004 only for
incumbency), four lists per municipality and election, each list one close pair (the
elected candidate 5 to 45 votes ahead of 10,000 valid votes, so every pair is within
0.5%), four polling places, a 1 km grid, MapBiomas-like outcomes 2004-2024, candidate
records with made-up voter IDs, and mayoral races with coalitions. Clearing rises in the
four years after each election with the cell's exposure to the winners (`EFFECT`).

`write_world(store, manifests_dir)` writes everything under made-up build paths, with one
manifest per dataset as the pipeline writes them. Even-numbered municipalities are the
exploration half; their outcome rows are in `files`, the others' in `sealed_files`.
Nothing here is real data.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import random
from pathlib import Path

import numpy as np
import polars as pl

from terrain import strongholds as sh
from terrain.builds import cell_displacement as cdisp
from terrain.builds import cell_exposure as cexp
from terrain.grid import km_to_lonlat

N_MUNIS = 40
LISTS = 4
ELECTIONS = (2008, 2012, 2016, 2020, 2024)
MAIN = {2004: 15, 2008: 30, 2012: 47, 2016: 220, 2020: 426, 2024: 619}
OUTCOME_YEARS = range(2004, 2025)
VALID_VOTES = 10_000
PLACES = (1.5, 4.5, 7.5, 10.5)  # x offsets (km) of the four places
# (indigenous km, settlement km) of each place: indigenous, settlement, both, neither.
TENURE = ((1.0, 30.0), (30.0, 2.0), (3.0, 4.0), (40.0, 40.0))
CELLS_X, CELLS_Y = 36, 3
EFFECT = 4000.0  # code_4 units (1/10,000 of a cell) per unit of exposure, E+1 .. E+4
X0, Y0 = 4000, 9000
STATE = "RO"
HASH = "synthetic0001"


def code(i: int) -> str:
    return f"{1100001 + i}"


def ue(i: int) -> str:
    return f"{10001 + i}"


def explore_half() -> frozenset[str]:
    return frozenset(code(i) for i in range(0, N_MUNIS, 2))


def confirm_half() -> frozenset[str]:
    return frozenset(code(i) for i in range(1, N_MUNIS, 2))


def split_csv() -> bytes:
    rows = [f"{code(i)},{'explore' if i % 2 == 0 else 'confirm'}" for i in range(N_MUNIS)]
    return ("code_ibge,half\n" + "\n".join(sorted(rows)) + "\n").encode("utf-8")


def sq(year: int, i: int, j: int, side: int) -> str:
    return f"{year}{i:03d}{j}{side}"


def person(year: int, i: int, j: int, side: int) -> str:
    """Made-up voter IDs. Winners keep the seat for two terms; some losers held it before.

    So some pairs have an incumbent winner, some an incumbent loser, some neither.
    """
    e = (year - 2004) // 4

    def winner(k: int) -> str:
        return f"vid-a-{i:03d}-{j}-{((i + j + k) // 2) % 2}"

    if side == 0:
        return winner(e)
    previous = winner(e - 1)
    if (i + j + e) % 3 == 0 and previous != winner(e):
        return previous
    return f"vid-b-{i:03d}-{j}-{e}"


def elected_code(year: int, elected: bool) -> int:
    if year == 2008:
        return 1 if elected else 4
    return 2 if elected else 4


def gap(year: int, i: int, j: int) -> int:
    return 5 + ((year // 4 + 3 * i + 7 * j) % 9) * 5  # 5 .. 45 votes


def homes(year: int, i: int, j: int) -> tuple[int, int]:
    e = (year - 2004) // 4
    a = (j + e + i) % len(PLACES)
    return a, (a + 1 + (i + j) % 3) % len(PLACES)


def council_votes(year: int, i: int, j: int) -> dict[int, list[int]]:
    """Votes per place of the elected (side 0) and the other (side 1) candidate."""
    total = {0: 1000, 1: 1000 - gap(year, i, j)}
    out = {}
    for side, home in zip((0, 1), homes(year, i, j), strict=True):
        spread = [total[side] // 10] * len(PLACES)
        spread[home] = total[side] - (total[side] // 10) * (len(PLACES) - 1)
        out[side] = spread
    return out


def candidate_votes(year: int) -> pl.DataFrame:
    rows = []
    for i in range(N_MUNIS):
        for j in range(LISTS):
            votes = council_votes(year, i, j)
            for side in (0, 1):
                rows.append(
                    {
                        "ano_eleicao": year,
                        "cd_eleicao": MAIN[year],
                        "cd_tipo_eleicao": 2,
                        "nr_turno": 1,
                        "sg_ue": ue(i),
                        "cd_ibge": code(i),
                        "cd_cargo": 13,
                        "sq_candidato": sq(year, i, j, side),
                        "sq_coligacao": f"L{j}",
                        "nr_zona": 1,
                        "qt_votos_nominais": sum(votes[side]),
                        "qt_votos_nominais_validos": sum(votes[side]),
                        "nm_tipo_destinacao_votos": "Válido",
                        "ds_sit_tot_turno": "ELEITO" if side == 0 else "SUPLENTE",
                        "cd_sit_tot_turno": elected_code(year, side == 0),
                    }
                )
        for m, mvotes in ((1, 5000), (2, 4000)):
            rows.append(
                {
                    "ano_eleicao": year,
                    "cd_eleicao": MAIN[year],
                    "cd_tipo_eleicao": 2,
                    "nr_turno": 1,
                    "sg_ue": ue(i),
                    "cd_ibge": code(i),
                    "cd_cargo": 11,
                    "sq_candidato": f"{year}{i:03d}9{m}",
                    "sq_coligacao": f"M{m}",
                    "nr_zona": 1,
                    "qt_votos_nominais": mvotes,
                    "qt_votos_nominais_validos": mvotes,
                    "nm_tipo_destinacao_votos": "Válido",
                    "ds_sit_tot_turno": "ELEITO" if m == 1 else "NÃO ELEITO",
                    "cd_sit_tot_turno": elected_code(year, m == 1),
                }
            )
    return pl.DataFrame(rows)


def turnout(year: int) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "cd_eleicao": MAIN[year],
                "nr_turno": 1,
                "sg_ue": ue(i),
                "cd_ibge": code(i),
                "cd_cargo": 13,
                "qt_total_votos_validos": VALID_VOTES,
            }
            for i in range(N_MUNIS)
        ]
    )


def section_votes(year: int) -> pl.DataFrame:
    rows = []
    for i in range(N_MUNIS):
        for j in range(LISTS):
            for side, per_place in council_votes(year, i, j).items():
                for p, v in enumerate(per_place):
                    rows.append(
                        (
                            13,
                            1,
                            MAIN[year],
                            "candidate",
                            False,
                            1,
                            p + 1,
                            code(i),
                            ue(i),
                            sq(year, i, j, side),
                            v,
                        )
                    )
    return pl.DataFrame(
        rows,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "vote_type",
            "annulled_in_results",
            "nr_zona",
            "nr_local_votacao",
            "cd_ibge",
            "sg_ue",
            "sq_candidato",
            "qt_votos",
        ],
        orient="row",
    )


def muni_x(i: int) -> int:
    return X0 + 100 * i


def polling_places() -> pl.DataFrame:
    rows = [
        (code(i), ue(i), 1, p + 1, muni_x(i) + x, Y0 + 1.5)
        for i in range(N_MUNIS)
        for p, x in enumerate(PLACES)
    ]
    lon, lat = km_to_lonlat([r[4] for r in rows], [r[5] for r in rows])
    return pl.DataFrame(
        {
            "cd_ibge": [r[0] for r in rows],
            "sg_ue": [r[1] for r in rows],
            "nr_zona": [r[2] for r in rows],
            "nr_local_votacao": [r[3] for r in rows],
            "lat": lat.tolist(),
            "long": lon.tolist(),
        }
    )


def tenure(year: int) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "cd_ibge": code(i),
                "sg_ue": ue(i),
                "nr_zona": 1,
                "nr_local_votacao": p + 1,
                "dist_indigenous_km": TENURE[p][0],
                "dist_settlement_km": TENURE[p][1],
                "ano": year,
            }
            for i in range(N_MUNIS)
            for p in range(len(PLACES))
        ]
    )


def place_types(year: int) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "cd_ibge": code(i),
                "sg_ue": ue(i),
                "nr_zona": 1,
                "nr_local_votacao": p + 1,
                "seat_km": float(p * 3),
                "place_type": ("seat", "town", "rural", "rural")[p],
                "ano": year,
            }
            for i in range(N_MUNIS)
            for p in range(len(PLACES))
        ]
    )


def grid_cells() -> pl.DataFrame:
    rows = []
    for i in range(N_MUNIS):
        for cx in range(CELLS_X):
            for cy in range(CELLS_Y):
                x, y = muni_x(i) + cx, Y0 + cy
                rows.append((f"1KME{x}N{y}", code(i), x, y, 10 if cx < 22 else 0))
    return pl.DataFrame(
        rows, schema=["nome_1KM", "cd_ibge", "x_km", "y_km", "pop_2022"], orient="row"
    )


def candidates() -> pl.DataFrame:
    rng = random.Random(3)
    rows = []
    for year in (2004, *ELECTIONS):
        for i in range(N_MUNIS):
            for j in range(LISTS):
                for side in (0, 1):
                    rows.append(
                        {
                            "ano_eleicao": year,
                            "cd_eleicao": MAIN[year],
                            "nr_turno": 1,
                            "cd_cargo": 13,
                            "sg_ue": ue(i),
                            "sq_candidato": sq(year, i, j, side),
                            "cd_genero": rng.choice((2, 4)),
                            "dt_eleicao": dt.date(year, 10, 5),
                            "dt_nascimento": dt.date(
                                1950 + rng.randrange(40), 1 + rng.randrange(12), 1
                            ),
                            "cd_grau_instrucao": rng.randrange(1, 9),
                            "nr_titulo_eleitoral_candidato": person(year, i, j, side),
                            "ds_sit_tot_turno": "ELEITO" if side == 0 else "SUPLENTE",
                            "st_reeleicao": "N",
                            "nr_partido": str(10 + j if side == 0 else 20 + j),
                            "sq_coligacao": f"L{j}",
                            "nr_federacao": None,
                        }
                    )
            if year == 2004:
                continue
            for m in (1, 2):
                rows.append(
                    {
                        "ano_eleicao": year,
                        "cd_eleicao": MAIN[year],
                        "nr_turno": 1,
                        "cd_cargo": 11,
                        "sg_ue": ue(i),
                        "sq_candidato": f"{year}{i:03d}9{m}",
                        "cd_genero": 2,
                        "dt_eleicao": dt.date(year, 10, 5),
                        "dt_nascimento": dt.date(1960, 1, 1),
                        "cd_grau_instrucao": 8,
                        "nr_titulo_eleitoral_candidato": f"vid-mayor-{i:03d}-{m}",
                        "ds_sit_tot_turno": "ELEITO" if m == 1 else "NÃO ELEITO",
                        "st_reeleicao": "N",
                        "nr_partido": "10" if m == 1 else "30",
                        "sq_coligacao": f"M{m}",
                        "nr_federacao": None,
                    }
                )
    return pl.DataFrame(rows)


def coalitions(year: int) -> pl.DataFrame:
    rows = [
        {
            "cd_eleicao": MAIN[year],
            "cd_cargo": 11,
            "sg_ue": ue(i),
            "cd_ibge": code(i),
            "sq_coligacao": "M1",
            "nr_partido": party,
            "nr_federacao": None,
        }
        for i in range(N_MUNIS)
        for party in ("10", "11", "20")
    ]
    return pl.DataFrame(rows, schema_overrides={"nr_federacao": pl.Utf8})


def municipalities() -> pl.DataFrame:
    return pl.DataFrame(
        {"cd_ibge": [code(i) for i in range(N_MUNIS)], "cd_tse": [ue(i) for i in range(N_MUNIS)]}
    )


def outcomes() -> dict[int, pl.DataFrame]:
    """code_4 per cell and year: noise, plus EFFECT x D_i (exp2, all pairs) after each election."""
    grid = grid_cells()
    located = sh.locate_places(polling_places())
    dist = sh.cell_place_distances(grid.select(sh.CELL), located)
    bump = {y: np.zeros(grid.height) for y in OUTCOME_YEARS}
    index = {(c, x, y): k for k, (c, x, y) in enumerate(grid.select(sh.CELL).iter_rows())}
    for year in ELECTIONS[:-1]:
        cv, votes = candidate_votes(year), sh.place_candidate_votes(section_votes(year), MAIN[year])
        main = sh.main_election(cv)
        paired = sh.margins(
            sh.within_list_pairs(sh.candidacy_votes(cv, year, main)),
            sh.valid_votes(turnout(year), main),
        )
        d = sh.exposure(
            dist,
            sh.place_totals(votes),
            sh.place_shares(votes),
            sh.close_pairs(paired),
            "exp2",
            "share",
        )
        for c, x, y, value in d.select(*sh.CELL, "D_i").iter_rows():
            for later in range(year + 1, year + 5):
                bump[later][index[(c, x, y)]] += EFFECT * value
    rng = np.random.default_rng(11)
    out = {}
    for y in OUTCOME_YEARS:
        out[y] = pl.DataFrame(
            {
                "nome_1KM": grid["nome_1KM"],
                "cd_ibge": grid["cd_ibge"],
                "has_data": [True] * grid.height,
                "code_2": [5000] * grid.height,
                "code_4": np.maximum(
                    0, np.round(60 + rng.normal(0, 25, grid.height) + bump[y])
                ).astype(np.int64),
            }
        )
    return out


def _parquet(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def write_world(store, manifests: Path, with_builds: bool = True) -> None:
    """Write the world into `store` and its manifests into `manifests`.

    `with_builds` also writes `cell_exposure` and `cell_displacement` (0.5%, all
    municipalities), which only `explore/0001_effects.py` reads.
    """
    files: dict[str, dict[str, list[dict]]] = {}

    def put(
        dataset: str, name: str, df: pl.DataFrame, key: str = "files", root: str = "data/derived"
    ) -> None:
        path = f"{root}/{dataset}/{HASH}/{name}"
        blob = _parquet(df)
        store.create(path, blob)
        entry = {"path": path, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
        files.setdefault(dataset, {}).setdefault(key, []).append(entry)

    grid = grid_cells()
    places = polling_places()
    put("grid_cells", "grid_cells.parquet", grid)
    put("tse_candidates", "candidates.parquet", candidates())
    put("municipalities", "municipalities.parquet", municipalities())
    for year in ELECTIONS:
        cv, to, sv = candidate_votes(year), turnout(year), section_votes(year)
        put("tse_results", f"candidate_votes_{year}.parquet", cv)
        put("tse_results", f"turnout_{year}.parquet", to)
        put("section_votes", f"section_votes_{year}_{STATE}.parquet", sv)
        put("polling_places", f"polling_places_{year}.parquet", places)
        put("polling_place_tenure", f"polling_place_tenure_{year}.parquet", tenure(year))
        put("polling_place_types", f"polling_place_types_{year}.parquet", place_types(year))
        put("tse_parties", f"coalitions_{year}.parquet", coalitions(year))
        if with_builds:
            exposure, _ = cexp.year_table(year, cv, to, places, [sv], grid.drop("pop_2022"))
            put("cell_exposure", f"cell_exposure_{year}.parquet", exposure)
            displaced, _ = cdisp.year_table(year, cv, to, places, [sv], grid, exposure)
            put("cell_displacement", f"cell_displacement_{year}.parquet", displaced)
    explore = sorted(explore_half())
    for y, df in outcomes().items():
        name = f"cell_outcomes_{y}.parquet"
        put("cell_outcomes", name, df.filter(pl.col("cd_ibge").is_in(explore)))
        put(
            "cell_outcomes",
            name,
            df.filter(~pl.col("cd_ibge").is_in(explore)),
            key="sealed_files",
            root="sealed/outcomes",
        )
    manifests.mkdir(parents=True, exist_ok=True)
    for dataset, entries in files.items():
        body = {"dataset": dataset, "files": entries.get("files", [])}
        if "sealed_files" in entries:
            body["sealed_files"] = entries["sealed_files"]
        (manifests / f"{dataset}.json").write_text(json.dumps(body), encoding="utf-8")
