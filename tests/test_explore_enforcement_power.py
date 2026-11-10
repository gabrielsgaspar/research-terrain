import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from terrain.explore import write_results
from terrain.grid import km_to_lonlat

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0005_enforcement_power.py"
SPEC = importlib.util.spec_from_file_location("enforcement_power", SCRIPT)
ep = importlib.util.module_from_spec(SPEC)
sys.modules["enforcement_power"] = ep
SPEC.loader.exec_module(ep)

X0, Y0 = 4000, 9000
ELECTIONS = (2008, 2012, 2016, 2020)
POISON_YEARS = range(2020, 2024)  # after every election: no election may read them
FINAL_YEAR = 2023
# Margins are d / 100,000 valid votes: 0.1% and 0.4% are inside 0.25% / 0.50%, 1% is outside.
VALID = 100_000
INSIDE_025, BETWEEN, OUTSIDE = 100, 400, 1000
# (located, all) per year; both divisible by 8, as the frame splits them over 8 columns.
SHARE_BY_ELECTION = {2008: (400, 800), 2012: (392, 800), 2016: (640, 800), 2020: (0, 0)}


def muni_code(m):
    return f"11{m:05d}"


def n_munis(inside):
    return inside + 3 + 1  # inside 0.25%, three between, one outside 0.50%


def distances(inside):
    return [INSIDE_025] * inside + [BETWEEN] * 3 + [OUTSIDE]


def tse_frames(year, inside):
    cv, turnout, sv = [], [], []
    elected, other = (1, 2) if year == 2008 else (2, 4)
    for m, d in enumerate(distances(inside)):
        ue, ibge = str(10 + m), muni_code(m)
        for sq, votes, code in ((f"{m}1", 1000 + d, elected), (f"{m}2", 1000, other)):
            cv.append((13, 1, year, ue, ibge, sq, 7, votes, code))
        turnout.append((13, 1, year, ue, VALID))
        for local, (a, b) in enumerate(((80, 20), (20, 80), (50, 50)), start=1):
            for sq, v in ((f"{m}1", a), (f"{m}2", b)):
                sv.append((13, 1, year, "candidate", False, 1, local, ibge, ue, sq, v))
    cv = pl.DataFrame(
        cv,
        schema=[
            "cd_cargo",
            "nr_turno",
            "cd_eleicao",
            "sg_ue",
            "cd_ibge",
            "sq_candidato",
            "sq_coligacao",
            "qt_votos_nominais",
            "cd_sit_tot_turno",
        ],
        orient="row",
    )
    turnout = pl.DataFrame(
        turnout,
        schema=["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "qt_total_votos_validos"],
        orient="row",
    )
    sv = pl.DataFrame(
        sv,
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
    half = sv["cd_ibge"].unique().sort().to_list()[: n_munis(inside) // 2]
    first = sv.filter(pl.col("cd_ibge").is_in(half))
    second = sv.filter(~pl.col("cd_ibge").is_in(half))
    return cv, turnout, {"AC": first, "AM": second}


def places_frame(inside):
    # P1 and P2 are 7 km apart (cells between them have D of both signs); P3 is 50/50 and far.
    lon, lat = km_to_lonlat([X0 + 0.5, X0 + 7.5, X0 + 40.5], [Y0 + 0.5] * 3)
    rows = []
    for m in range(n_munis(inside)):
        for local in (1, 2, 3):
            rows.append((muni_code(m), str(10 + m), 1, local, lat[local - 1], lon[local - 1]))
    return pl.DataFrame(
        rows,
        schema={
            "cd_ibge": pl.Utf8,
            "sg_ue": pl.Utf8,
            "nr_zona": pl.Int64,
            "nr_local_votacao": pl.Int64,
            "lat": pl.Float64,
            "long": pl.Float64,
        },
        orient="row",
    )


def grid_frame(inside):
    rows = []
    for m in range(n_munis(inside)):
        for dx in [*range(8), 40]:  # dx = 40 is the cell of the 50/50 place: D = 0
            rows.append((f"{muni_code(m)}_{dx}", muni_code(m), X0 + dx, Y0))
    return pl.DataFrame(rows, schema=["nome_1KM", "cd_ibge", "x_km", "y_km"], orient="row")


def cell_frame(year, inside, rule, rng):
    """Rows of `cell_enforcement_<year>`; absent cells have no row."""
    rows = []
    for m in range(n_munis(inside)):
        for dx in [*range(8), 40]:
            if year in POISON_YEARS:
                fines, emb = 1000, 1000
            elif rule == "effect":
                fines, emb = (2, 1) if dx <= 3 else (0, 0)
                if dx == 40:
                    fines, emb = 5, 0
            else:
                fines, emb = int(rng.integers(0, 4)), int(rng.integers(0, 3))
            if fines or emb:
                rows.append((f"{muni_code(m)}_{dx}", muni_code(m), year, fines, emb))
    return pl.DataFrame(
        rows,
        schema={
            "nome_1KM": pl.Utf8,
            "cd_ibge": pl.Utf8,
            "ano": pl.Int64,
            "n_fines_flora": pl.Int64,
            "n_embargoes": pl.Int64,
        },
        orient="row",
    )


def muni_frame(year, election):
    located, total = SHARE_BY_ELECTION[election]
    if year >= election:
        located, total = 999, 1000  # poison: would change every share
    return pl.DataFrame(
        {
            "cd_ibge": [muni_code(0), muni_code(1)],
            "ano": [year, year],
            "n_fines_flora_all": [total // 8, total // 8],
            "n_fines_flora_located": [located // 8, located // 8],
            "n_embargoes_all": [total // 8, total // 8],
            "n_embargoes_located": [located // 8, located // 8],
        }
    )


class World:
    """An in-memory reader over synthetic files that records every request."""

    def __init__(self, rule="noise", inside=5):
        self.inside = inside
        rng = np.random.default_rng(7)
        self.files = {}
        self.sections = {}
        for e in ELECTIONS:
            cv, turnout, sv = tse_frames(e, inside)
            self.files[("tse_results", f"candidate_votes_{e}.parquet")] = cv
            self.files[("tse_results", f"turnout_{e}.parquet")] = turnout
            self.files[("polling_places", f"polling_places_{e}.parquet")] = places_frame(inside)
            self.sections[e] = sv
        self.cells = {}
        for year in range(2004, FINAL_YEAR + 1):
            self.cells[year] = cell_frame(year, inside, rule, rng)
            self.files[("cell_enforcement", f"cell_enforcement_{year}.parquet")] = self.cells[year]
            elected = min((e for e in ELECTIONS if year < e), default=2020)
            self.files[("cell_enforcement", f"muni_enforcement_{year}.parquet")] = muni_frame(
                year, elected
            )
        self.grid = grid_frame(inside).with_columns(
            pl.col("x_km").cast(pl.Int64), pl.col("y_km").cast(pl.Int64)
        )
        self.log = []

    def read(self, manifest, pattern, columns=None):
        self.log.append((manifest, pattern))
        hits = [
            f for (m, name), f in self.files.items() if m == manifest and re.search(pattern, name)
        ]
        assert len(hits) == 1, (manifest, pattern, len(hits))
        return hits[0] if columns is None else hits[0].select(columns)

    def read_many(self, manifest, pattern):
        self.log.append((manifest, pattern))
        year = int(re.search(r"_(\d{4})_", pattern).group(1))
        return list(self.sections[year].values())

    def inputs(self):
        out = {}
        for e in ELECTIONS:
            before = len(self.log)
            out[e] = ep.load_election(self.read, self.read_many, e)
            self.last = self.log[before:]
        return out

    def requested_years(self, election):
        before = len(self.log)
        ep.load_election(self.read, self.read_many, election)
        found = [
            (re.search(r"(cell|muni)_enforcement_(\d{4})", p).groups())
            for m, p in self.log[before:]
            if m == "cell_enforcement"
        ]
        return sorted((kind, int(year)) for kind, year in found)


@pytest.fixture(scope="module")
def noise():
    world = World("noise")
    inputs = world.inputs()
    return world, inputs, ep.compute(inputs, world.grid)


# --- 2. Years and the reader


def test_pre_years_and_the_reader_refuses_years_from_the_election_on():
    assert ep.pre_years(2008) == [2004, 2005, 2006, 2007]
    world = World()
    for election in ELECTIONS:
        for year in (election, election + 1, election + 4):
            with pytest.raises(ValueError):
                ep.enforcement_year(world.read, "cell", election, year)
            with pytest.raises(ValueError):
                ep.enforcement_year(world.read, "muni", election, year)
    assert world.log == []  # a refused year is never requested
    with pytest.raises(ValueError):
        ep.pre_y({2004: world.cells[2004]}, 2008)


# --- 1. The keys, and no post-election frame requested


def test_results_have_every_key_at_its_nested_path_and_no_late_year_is_read(noise, tmp_path):
    world, _, results = noise
    expected = {
        "coverage": {
            "e2008": {"share_geolocated"},
            "e2012": {"share_geolocated"},
            "e2016": {"share_geolocated"},
            "e2020": {"share_geolocated"},
            "elections_ok": None,
        },
        "counts": {"pre_reach_actions": None},
        "power": {"mde_share_025": None, "mde_share_050": None},
        "placebo": {"ri_p_050": None},
    }
    assert set(results) == set(expected)
    for group, keys in expected.items():
        assert set(results[group]) == set(keys), group
    for e in ELECTIONS:
        assert set(results["coverage"][f"e{e}"]) == {"share_geolocated"}
    assert not any("." in key for group in results.values() for key in group)

    write_results(tmp_path, ep._summary(results), results)
    on_disk = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert on_disk == results
    assert on_disk["coverage"]["elections_ok"] == 2
    assert isinstance(on_disk["counts"]["pre_reach_actions"], int)

    for election in ELECTIONS:
        assert world.requested_years(election) == sorted(
            [("cell", y) for y in ep.pre_years(election)]
            + [("muni", y) for y in ep.pre_years(election)]
        )
    wanted = {f"{kind}_enforcement_{y}" for kind in ("cell", "muni") for y in POISON_YEARS}
    assert not any(any(w in p for w in wanted) for _, p in world.log)


def test_poisoned_late_frames_change_nothing():
    world = World("noise")
    clean = ep.compute(world.inputs(), world.grid)
    for year in POISON_YEARS:
        for key in (f"cell_enforcement_{year}.parquet", f"muni_enforcement_{year}.parquet"):
            # An emptied frame would change the numbers if anything read it.
            world.files[("cell_enforcement", key)] = world.files[("cell_enforcement", key)].clear()
    assert ep.compute(world.inputs(), world.grid) == clean


# --- 3. Coverage


def muni_counts(located, total):
    return pl.DataFrame(
        {
            "cd_ibge": ["1"],
            "n_fines_flora_all": [total // 2],
            "n_fines_flora_located": [located // 2],
            "n_embargoes_all": [total - total // 2],
            "n_embargoes_located": [located - located // 2],
        }
    )


def test_elections_ok_counts_a_half_but_not_49_percent_or_a_zero_denominator():
    def share(located, total):
        return ep.coverage_share({y: muni_counts(located, total) for y in ep.pre_years(2008)}, 2008)

    half, almost, empty = share(50, 100), share(49, 100), share(0, 0)
    assert half == 0.5 and almost == 0.49 and empty is None
    assert ep.elections_ok({2008: half, 2012: almost, 2016: empty, 2020: None}) == 1
    assert ep.elections_ok({2008: half, 2012: share(80, 100)}) == 2
    assert ep.elections_ok({}) == 0


def test_coverage_in_the_world_follows_the_located_counts(noise):
    _, _, results = noise
    shares = {e: results["coverage"][f"e{e}"]["share_geolocated"] for e in ELECTIONS}
    assert shares == {2008: 0.5, 2012: 0.49, 2016: 0.8, 2020: None}
    assert results["coverage"]["elections_ok"] == 2


# --- 4. Counts


def expected_actions(world, threshold):
    """Located actions of the exposed cells (dx 0..7, never the 50/50 cell), by hand."""
    total = 0
    for e in ELECTIONS:
        munis = [m for m, d in enumerate(distances(world.inside)) if d / VALID <= threshold + 1e-12]
        wanted = {f"{muni_code(m)}_{dx}" for m in munis for dx in range(8)}
        for year in ep.pre_years(e):
            rows = world.cells[year].filter(pl.col("nome_1KM").is_in(sorted(wanted)))
            total += int(rows["n_fines_flora"].sum() + rows["n_embargoes"].sum())
    return total


def test_pre_reach_actions_counts_only_cells_with_d_and_treats_absent_cells_as_zero(noise):
    world, inputs, results = noise
    got = results["counts"]["pre_reach_actions"]
    assert got == expected_actions(world, 0.005) > 0
    window = ep.window_direct(inputs, world.grid, ep.WINDOW_050)
    munis = 5 + 3
    assert window["x_abs"].size == 8 * munis * len(ELECTIONS)  # the 50/50 cell has D = 0
    assert (window["x_abs"] > 1e-12).all()
    # In the world where only dx <= 3 has actions the count is exact: 4 cells x 12 per cell.
    # The other four exposed cells of each municipality are absent from the table (Y = 0),
    # and the 50/50 cell has 20 actions but D = 0, so it is not counted.
    effect = World("effect")
    effect_inputs = effect.inputs()
    exposed = ep.window_direct(effect_inputs, effect.grid, ep.WINDOW_050)
    assert (exposed["y"] == 0).sum() == 4 * munis * len(ELECTIONS)
    assert ep.pre_reach_actions(exposed) == munis * len(ELECTIONS) * 4 * 12
    assert ep.compute(effect_inputs, effect.grid)["counts"] == {
        "pre_reach_actions": munis * len(ELECTIONS) * 4 * 12
    }


# --- 5. Placebo


def test_placebo_p_is_in_the_unit_interval_without_an_effect_and_small_when_y_follows_d(noise):
    _, _, results = noise
    p = results["placebo"]["ri_p_050"]
    assert 0 < p <= 1
    assert p > 0.05
    effect = World("effect")
    p_effect = ep.compute(effect.inputs(), effect.grid)["placebo"]["ri_p_050"]
    assert 0 < p_effect <= 0.05


# --- 6. Power


def test_mde_shares_are_positive_and_finite(noise):
    _, _, results = noise
    for key in ("mde_share_025", "mde_share_050"):
        value = results["power"][key]
        assert value is not None and np.isfinite(value) and value > 0


def test_mde_share_is_2_8_sd_times_mean_d_over_mean_y():
    rng = np.random.default_rng(3)
    draws = rng.normal(0, 0.5, 2000)
    window = {"draws": draws, "x_abs": np.array([0.1, 0.3]), "y": np.array([2.0, 6.0])}
    expected = 2.8 * np.std(draws, ddof=1) * 0.2 / 4.0
    assert ep.mde_share(window) == pytest.approx(expected)
    assert ep.mde_share(None) is None
    assert ep.mde_share({**window, "y": np.zeros(2)}) is None
    assert ep.mde_share({**window, "x_abs": np.zeros(0), "y": np.zeros(0)}) is None
    assert ep.mde_share({**window, "draws": np.full(5, np.nan)}) is None


def test_an_empty_025_window_gives_null_and_leaves_the_050_numbers():
    world = World("noise", inside=0)
    results = ep.compute(world.inputs(), world.grid)
    assert results["power"]["mde_share_025"] is None
    assert results["power"]["mde_share_050"] is not None
    assert results["counts"]["pre_reach_actions"] > 0
    nothing = ep.build_results({}, None, None)
    assert nothing["power"] == {"mde_share_025": None, "mde_share_050": None}
    assert nothing["counts"]["pre_reach_actions"] == 0
    assert nothing["placebo"]["ri_p_050"] is None
    assert nothing["coverage"]["elections_ok"] == 0


# --- 7. Imports and reads


def test_the_script_does_not_import_registered_or_read_outcome_files():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("registered" in name for name in imported), imported
    for forbidden in ("terrain.registered", "cell_outcomes", "polling_place_tenure"):
        assert forbidden not in source
    assert "polling_place_types" not in source
    assert "exploration_municipalities(" in source and "restrict(" in source
    world = World()
    world.inputs()
    manifests = {m for m, _ in world.log}
    assert manifests == {
        "tse_results",
        "polling_places",
        "section_votes",
        "cell_enforcement",
    }
