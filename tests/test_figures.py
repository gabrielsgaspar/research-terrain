"""Tests of terrain.figures and the contract of the figure scripts. No network, no GCS."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tempfile
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapely
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.patches import Rectangle

from terrain import figures
from terrain.grid import km_to_lonlat
from terrain.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


def _layers_file(path: Path) -> Path:
    def box(x0: float, y0: float, x1: float, y1: float) -> bytes:
        return shapely.to_wkb(shapely.box(x0, y0, x1, y1))

    rows = [
        ("country", "BRA", "Brazil", None, box(-74, -18, -43, 5)),
        ("country", "PER", "Peru", None, box(-80, -18, -74, 0)),
        ("ocean", None, None, None, box(-50, -20, -26, 10)),
        ("lake", None, "L", 1, box(-60, -5, -58, -3)),
        (
            "river",
            None,
            "R",
            3,
            shapely.to_wkb(shapely.linestrings([[-70, -5], [-60, -4], [-50, 0]])),
        ),
        (
            "river",
            None,
            "minor",
            9,
            shapely.to_wkb(shapely.linestrings([[-70, -6], [-60, -6]])),
        ),
        ("state", "AM", "Amazonas", None, box(-74, -10, -56, 2)),
        ("state", "PA", "Para", None, box(-56, -10, -44, 3)),
        ("legal_amazon", None, "Legal", None, box(-73, -12, -44, 4)),
        ("indigenous", None, "I", None, box(-68, -8, -64, -4)),
        ("settlement", None, "S", None, box(-60, -6, -57, -3)),
        ("undesignated", None, "U", None, box(-55, -4, -50, 0)),
    ]
    pl.DataFrame(
        rows,
        schema={
            "layer": pl.String,
            "code": pl.String,
            "name": pl.String,
            "scalerank": pl.Int64,
            "geometry": pl.Binary,
        },
        orient="row",
    ).write_parquet(path)
    return path


def _points(n: int, lon: float, lat: float) -> np.ndarray:
    return figures.project_points([lat] * n, [lon] * n)


@pytest.fixture
def layers(tmp_path: Path) -> figures.Layers:
    return figures.read_layers(_layers_file(tmp_path / "figure_layers.parquet"))


def _years(layers: figures.Layers) -> dict[int, np.ndarray]:
    rng = np.random.default_rng(0)
    out = {}
    for year in figures.YEARS:
        lon = rng.uniform(-70, -46, 200)
        lat = rng.uniform(-10, 3, 200)
        out[year] = figures.project_points(lat, lon)
    return out


def test_read_layers_projects_to_albers_km(layers: figures.Layers) -> None:
    assert set(layers) == {
        "country",
        "ocean",
        "lake",
        "river",
        "state",
        "legal_amazon",
        "indigenous",
        "settlement",
        "undesignated",
    }
    geom, code, name, _ = layers["country"][0]
    assert (code, name) == ("BRA", "Brazil")
    assert abs(geom.bounds[0]) < 10000  # km, not degrees
    assert [r[3] for r in layers["river"]] == [3, 9]


def _pngs(out: Path) -> list[str]:
    return sorted(p.name for p in out.iterdir())


def _rgb(colour: str) -> tuple[float, float, float]:
    return to_rgb(colour)


def test_study_area_writes_one_png(layers: figures.Layers, tmp_path: Path) -> None:
    out = tmp_path / "out"
    figures.study_area(layers, out)
    assert _pngs(out) == ["01_study_area.png"]
    assert (out / "01_study_area.png").read_bytes().startswith(b"\x89PNG")


def test_study_area_inset_lies_inside_the_map_at_half_size(layers: figures.Layers) -> None:
    fig = figures.study_area_figure(layers)
    fig.canvas.draw()
    main = fig.axes[0]
    inset = main.child_axes[0]
    outer, inner = main.get_window_extent(), inset.get_window_extent()
    assert outer.x0 < inner.x0 < inner.x1 < outer.x1
    assert outer.y0 < inner.y0 < inner.y1 < outer.y1
    assert inner.width <= outer.width * figures.INSET_WIDTH + 1e-6
    assert inner.x1 > outer.x0 + outer.width / 2 and inner.y1 < outer.y0 + outer.height / 2
    figures.plt.close(fig)


def test_maps_are_framed_with_water(layers: figures.Layers) -> None:
    fig = figures.study_area_figure(layers)
    for ax in (fig.axes[0], fig.axes[0].child_axes[0]):
        assert ax.get_facecolor()[:3] == pytest.approx(_rgb(figures.style.WATER))
        assert all(spine.get_visible() for spine in ax.spines.values())
        assert not len(ax.get_xticks()) and not len(ax.get_yticks())
    figures.plt.close(fig)


def test_polling_places_writes_two_pngs(layers: figures.Layers, tmp_path: Path) -> None:
    out = tmp_path / "out"
    figures.polling_places(layers, _years(layers), out)
    assert _pngs(out) == ["02_polling_places.png", "02_polling_places_appendix.png"]


def test_polling_places_colour_bar_spans_all_panels(layers: figures.Layers) -> None:
    built = figures.polling_places_figures(layers, _years(layers))
    assert len(built["02_polling_places_appendix"][1]) == len(figures.YEARS)
    for fig, panels, bar in built.values():
        x0 = min(ax.get_position().x0 for ax in panels)
        x1 = max(ax.get_position().x1 for ax in panels)
        pos = bar.ax.get_position()
        assert pos.x0 == pytest.approx(x0) and pos.x1 == pytest.approx(x1)
        assert pos.y1 < min(ax.get_position().y0 for ax in panels)
        assert bar.orientation == "horizontal"
        labels = [t.get_text() for t in bar.ax.get_xticklabels()]
        assert labels and all(t.replace(",", "").isdigit() for t in labels)
        for ax in panels:
            assert ax.get_facecolor()[:3] == pytest.approx(_rgb(figures.style.WATER))
        figures.plt.close(fig)


def test_hex_scale_is_the_maximum_over_all_years(layers: figures.Layers, tmp_path: Path) -> None:
    extent = figures.amazon_extent(layers)
    points = _years(layers)
    points[2008] = np.vstack([points[2008], _points(5, -60, -5)])
    points[2024] = np.vstack([points[2024], _points(40, -50, 0)])
    only_2008 = figures.hex_scale({2008: points[2008]}, extent, figures.HEX_KM)
    scale = figures.hex_scale(points, extent, figures.HEX_KM)
    assert scale >= 40
    assert scale > only_2008
    assert scale == figures.hex_scale({2024: points[2024]}, extent, figures.HEX_KM)

    norms = figures.polling_places(layers, points, tmp_path / "out")
    assert set(norms) == {"02_polling_places", "02_polling_places_appendix"}
    for norm in norms.values():
        assert (norm.vmin, norm.vmax) == (1, scale)


def test_same_inputs_give_identical_pngs(layers: figures.Layers, tmp_path: Path) -> None:
    points = _years(layers)
    for run in ("a", "b"):
        figures.study_area(layers, tmp_path / run)
        figures.polling_places(layers, points, tmp_path / run)
        figures.tenure(layers, tmp_path / run)
    for name in _pngs(tmp_path / "a"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_cell_polygons_keep_populated_cells_only() -> None:
    squares, values = figures.cell_polygons([10, 11, 13], [20, 20, 22], [5, 0, 40])
    assert squares.shape == (2, 4, 2)
    assert values.tolist() == [5.0, 40.0]
    assert squares[0].tolist() == [[10, 20], [11, 20], [11, 21], [10, 21]]


def test_cell_polygons_reject_bad_input() -> None:
    with pytest.raises(ValueError):
        figures.cell_polygons([], [], [])
    with pytest.raises(ValueError):
        figures.cell_polygons([1, 2], [1], [1, 2])


def _cells() -> pl.DataFrame:
    rng = np.random.default_rng(1)
    return pl.DataFrame(
        {
            "x_km": rng.integers(-1500, -500, 300),
            "y_km": rng.integers(-1000, 0, 300),
            "pop_2022": rng.integers(0, 500, 300),
        }
    )


def test_population_draws_filled_cells_without_outlines(
    layers: figures.Layers, tmp_path: Path
) -> None:
    cells = _cells().unique(["x_km", "y_km"])
    fig, ax, bar = figures.population_figure(layers, cells)
    polys = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(polys) == 1
    assert len(polys[0].get_paths()) == int((cells["pop_2022"] > 0).sum())
    assert max(polys[0].get_linewidths()) == 0
    outlines = [c for c in ax.collections if isinstance(c, LineCollection)]
    assert all(c.get_zorder() != 2.2 for c in outlines)  # no tenure layer on this map
    assert bar.ax.get_position().x0 == pytest.approx(ax.get_position().x0)
    assert bar.ax.get_position().x1 == pytest.approx(ax.get_position().x1)
    x0, x1, y0, y1 = figures.POPULATION_ZOOM
    assert ax.get_xlim() == (x0, x1) and ax.get_ylim() == (y0, y1)
    (child,) = ax.child_axes  # the Legal Amazon, boxing the zoom
    assert child.get_xlim() == figures.amazon_extent(layers)[:2]
    (box,) = [p for p in child.patches if isinstance(p, Rectangle)]
    assert (box.get_x(), box.get_y(), box.get_width(), box.get_height()) == (
        x0,
        y0,
        x1 - x0,
        y1 - y0,
    )
    figures.plt.close(fig)
    for run in ("a", "b"):
        norm = figures.population(layers, cells, tmp_path / run)
        assert (norm.vmin, norm.vmax) == (1, int(cells["pop_2022"].max()))
    assert _pngs(tmp_path / "a") == ["03_population.png"]
    assert (tmp_path / "a" / "03_population.png").read_bytes() == (
        tmp_path / "b" / "03_population.png"
    ).read_bytes()


def test_tenure_has_three_categories_and_a_bottom_legend(
    layers: figures.Layers, tmp_path: Path
) -> None:
    fig, ax, legend = figures.tenure_figure(layers)
    labels = [t.get_text() for t in legend.get_texts()]
    assert labels == ["Indigenous land", "Settlement", "Undesignated public forest"]
    assert legend._ncols == 3
    fig.canvas.draw()
    assert legend.get_window_extent().y1 <= ax.get_window_extent().y0 + 1
    figures.plt.close(fig)
    figures.tenure(layers, tmp_path / "out")
    assert _pngs(tmp_path / "out") == ["04_tenure.png"]


def _manifest(path: str, data: bytes) -> dict:
    return {"files": [{"path": path, "sha256": hashlib.sha256(data).hexdigest()}]}


def test_fetch_downloads_and_checks_sha256(tmp_path: Path) -> None:
    store = MemoryStore()
    store.create("data/derived/x/h/figure_layers.parquet", b"hello")
    manifest = _manifest("data/derived/x/h/figure_layers.parquet", b"hello")
    got = figures.fetch(store, manifest, "figure_layers.parquet", tmp_path)
    assert got.read_bytes() == b"hello"


def test_fetch_raises_on_sha256_mismatch(tmp_path: Path) -> None:
    store = MemoryStore()
    store.create("data/derived/x/h/figure_layers.parquet", b"tampered")
    manifest = _manifest("data/derived/x/h/figure_layers.parquet", b"hello")
    with pytest.raises(ValueError, match="sha256"):
        figures.fetch(store, manifest, "figure_layers.parquet", tmp_path)


def test_fetch_needs_exactly_one_match(tmp_path: Path) -> None:
    manifest = {"files": [{"path": "a/b.parquet", "sha256": "0"}]}
    with pytest.raises(ValueError, match="expected one"):
        figures.fetch(MemoryStore(), manifest, "c.parquet", tmp_path)


def test_tenure_classes_one_cell_of_each_kind() -> None:
    classes, extent, counts = figures.tenure_classes(
        [10, 11, 12, 13], [20, 20, 20, 21], [0, 5, 7, 0], [0.5, 0.2, 0.0, 0.0]
    )
    assert extent == (10, 14, 20, 22)
    assert classes.shape == (2, 4)
    assert [classes[0, 0], classes[0, 1], classes[0, 2]] == [0, 1, 2]
    assert classes.mask[1, 3]  # empty cell outside undesignated forest
    assert classes.mask[1, 0]  # pixel with no cell
    assert int(classes.count()) == 3
    assert list(counts.values()) == [1, 1, 1]
    assert list(counts) == list(figures.TENURE_CLASSES)


def test_tenure_classes_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        figures.tenure_classes([], [], [], [])
    with pytest.raises(ValueError):
        figures.tenure_classes([1, 2], [1, 2], [1, 2], [1])


def test_land_without_voters_writes_one_png_with_comma_counts(
    layers: figures.Layers, tmp_path: Path
) -> None:
    rng = np.random.default_rng(2)
    cells = pl.concat([_cells().with_columns(pl.col("x_km") + 1000 * i) for i in range(5)])
    cells = cells.with_columns(
        pl.Series("share_undesignated_2024", rng.choice([0.0, 0.0, 0.4, 1.0], cells.height))
    )
    fig, _, legend, counts = figures.land_without_voters_figure(layers, cells)
    big = [label for label, n in counts.items() if n >= 1000]
    texts = [t.get_text() for t in legend.get_texts()]
    for label in big:
        assert f"{counts[label]:,}" in next(t for t in texts if t.startswith(label))
    figures.plt.close(fig)
    for run in ("a", "b"):
        counts = figures.land_without_voters(layers, cells, tmp_path / run)
    undesignated = cells["share_undesignated_2024"] > 0
    populated = cells["pop_2022"] > 0
    assert list(counts.values()) == [
        int((undesignated & ~populated).sum()),
        int((undesignated & populated).sum()),
        int((~undesignated & populated).sum()),
    ]
    assert _pngs(tmp_path / "a") == ["05_land_without_voters.png"]
    assert (tmp_path / "a" / "05_land_without_voters.png").read_bytes() == (
        tmp_path / "b" / "05_land_without_voters.png"
    ).read_bytes()


SCRIPTS = sorted(p.name for p in (ROOT / "figures").glob("[0-9][0-9]_*.py"))
ALLOWED = {"terrain.figures", "terrain.storage", "terrain.style"}


def _terrain_imports(text: str) -> set[str]:
    imported = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("terrain"):
            if node.module == "terrain":
                imported.update(f"terrain.{a.name}" for a in node.names)
            else:
                imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names if a.name.startswith("terrain"))
    return imported


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_are_thin_and_use_the_style(script: str) -> None:
    text = (ROOT / "figures" / script).read_text(encoding="utf-8")
    assert "gs://" not in text
    assert "http" not in text
    imported = _terrain_imports(text)
    assert imported <= ALLOWED
    assert imported & {"terrain.figures", "terrain.style"}  # terrain.figures uses the style


@pytest.mark.parametrize("path", [*SCRIPTS, "../src/terrain/figures.py"])
def test_no_figure_saves_by_itself_or_writes_pdf(path: str) -> None:
    text = (ROOT / "figures" / path).read_text(encoding="utf-8")
    assert "savefig" not in text
    assert ".pdf" not in text.lower()


def test_terrain_figures_saves_through_the_style() -> None:
    text = (ROOT / "src" / "terrain" / "figures.py").read_text(encoding="utf-8")
    assert "style.save_png" in text
    assert "from terrain import style" in text


# --- Figure 6: one close pair

X0, Y0 = 4000, 9000
INDIGENOUS_FIRST = {"p1": (0.0, 9.0), "p2": (9.0, 1.0)}  # elected near indigenous land
SETTLEMENT_FIRST = {"p1": (9.0, 0.0), "p2": (0.0, 9.0)}  # elected near a settlement
BOTH_SETTLEMENTS = {"p1": (9.0, 1.0), "p2": (9.0, 1.0)}
BOTH_LAYERS = {"p1": (0.0, 0.0), "p2": (9.0, 1.0)}  # the elected stronghold is near both


def _spec(ibge: str, margin_votes: int, near: dict) -> dict:
    return {"ibge": ibge, "ve": 5000 + margin_votes, "vo": 5000, **near}


def _put(store: MemoryStore, manifests: dict, name: str, filename: str, data: bytes) -> None:
    path = f"data/derived/{name}/h/{filename}"
    store.create(path, data)
    entry = {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
    manifests.setdefault(name, {"files": []})["files"].append(entry)


def _parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def _frame(rows: list, schema: list[str]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema, orient="row")


def _selection_world(specs: list[dict], year: int = 2012) -> tuple[MemoryStore, dict]:
    """2012 tables: per municipality one list with a close pair and two polling places.

    The elected candidate's stronghold is place 1, the other's place 2.
    """
    candidates, turnout, sections, tenure = [], [], [], []
    for s in specs:
        ibge = s["ibge"]
        ue = "9" + ibge[-4:]
        elected, other = int(ibge) * 10 + 1, int(ibge) * 10 + 2
        candidates += [
            (13, 1, 1, ue, ibge, elected, 7, s["ve"], 2),
            (13, 1, 1, ue, ibge, other, 7, s["vo"], 4),
        ]
        turnout.append((13, 1, 1, ue, ibge, 10000))
        for local, (ve, vo) in ((1, (60, 10)), (2, (10, 60))):
            sections += [
                (13, 1, 1, "candidate", False, 1, local, ibge, ue, elected, ve),
                (13, 1, 1, "candidate", False, 1, local, ibge, ue, other, vo),
                (13, 1, 1, "legend", False, 1, local, ibge, ue, None, 30),
            ]
        for local, key in ((1, "p1"), (2, "p2")):
            tenure.append((year, ibge, ue, 1, local, *s[key], 50.0))
    store, manifests = MemoryStore(), {}
    tables = {
        ("tse_results", f"candidate_votes_{year}.parquet"): _frame(
            candidates,
            [
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
        ),
        ("tse_results", f"turnout_{year}.parquet"): _frame(
            turnout,
            ["cd_cargo", "nr_turno", "cd_eleicao", "sg_ue", "cd_ibge", "qt_total_votos_validos"],
        ),
        ("section_votes", f"section_votes_{year}_AC.parquet"): _frame(
            sections,
            [
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
        ),
        ("polling_place_tenure", f"polling_place_tenure_{year}.parquet"): _frame(
            tenure,
            [
                "ano",
                "cd_ibge",
                "sg_ue",
                "nr_zona",
                "nr_local_votacao",
                "dist_indigenous_km",
                "dist_settlement_km",
                "dist_undesignated_km",
            ],
        ),
    }
    for (name, filename), frame in tables.items():
        _put(store, manifests, name, filename, _parquet(frame))
    return store, manifests


def _select(specs: list[dict], half: set[str] | None = None) -> tuple[dict, pl.DataFrame]:
    store, manifests = _selection_world(specs)
    codes = frozenset(half if half is not None else {s["ibge"] for s in specs})
    with tempfile.TemporaryDirectory() as tmp:
        return figures.select_close_pair(store, manifests, codes, Path(tmp), years=(2012,))


A, B, C, D = "1100001", "1100002", "1100003", "1100004"


def test_selection_returns_the_one_eligible_pair() -> None:
    pair, place_votes = _select(
        [
            _spec(A, 40, INDIGENOUS_FIRST),
            _spec(B, 10, BOTH_SETTLEMENTS),  # smaller margin, not eligible
            _spec(C, 5, BOTH_LAYERS),  # smaller margin, not eligible
        ]
    )
    assert (pair["year"], pair["cd_ibge"]) == (2012, A)
    assert pair["margin"] == pytest.approx(0.004)
    assert (pair["elected_near"], pair["other_near"]) == ("indigenous", "settlement")
    assert pair["elected_sq"] == str(int(A) * 10 + 1)
    assert place_votes["cd_ibge"].unique().to_list() == [A]


def test_selection_takes_the_smaller_margin_either_way_round() -> None:
    pair, _ = _select([_spec(A, 40, INDIGENOUS_FIRST), _spec(D, 20, SETTLEMENT_FIRST)])
    assert pair["cd_ibge"] == D
    assert (pair["elected_near"], pair["other_near"]) == ("settlement", "indigenous")
    pair, _ = _select([_spec(A, 20, INDIGENOUS_FIRST), _spec(D, 40, SETTLEMENT_FIRST)])
    assert pair["cd_ibge"] == A


def test_selection_raises_when_nothing_is_eligible() -> None:
    with pytest.raises(ValueError, match="no close pair"):
        _select([_spec(B, 10, BOTH_SETTLEMENTS), _spec(C, 5, BOTH_LAYERS)])


def test_selection_ignores_pairs_that_are_not_close() -> None:
    with pytest.raises(ValueError, match="no close pair"):
        _select([_spec(A, 80, INDIGENOUS_FIRST)])  # a margin of 0.8%


def test_selection_never_picks_a_municipality_outside_the_half() -> None:
    specs = [_spec(A, 1, INDIGENOUS_FIRST), _spec(D, 40, SETTLEMENT_FIRST)]
    pair, place_votes = _select(specs, half={D})
    assert pair["cd_ibge"] == D
    assert place_votes["cd_ibge"].unique().to_list() == [D]
    with pytest.raises(ValueError, match="no close pair"):
        _select(specs, half={B})


def _eligible(rows: list[tuple]) -> pl.DataFrame:
    return _frame(
        [
            (ibge, "10", 1, sq, "99", margin, "indigenous", "settlement")
            for ibge, sq, margin in rows
        ],
        [
            "cd_ibge",
            "sg_ue",
            "cd_eleicao",
            "elected_sq",
            "other_sq",
            "margin",
            "elected_near",
            "other_near",
        ],
    )


def test_choose_pair_smaller_margin_beats_later_year() -> None:
    got = figures.choose_pair(
        {2012: _eligible([(A, "5", 0.001)]), 2020: _eligible([(A, "5", -0.002)])}
    )
    assert got["year"] == 2012


def test_choose_pair_ties_go_to_the_later_year_then_ibge_then_candidate() -> None:
    tie = 0.002
    got = figures.choose_pair({2012: _eligible([(A, "5", tie)]), 2020: _eligible([(B, "5", tie)])})
    assert (got["year"], got["cd_ibge"]) == (2020, B)
    got = figures.choose_pair({2020: _eligible([(B, "5", tie), (A, "5", tie)])})
    assert got["cd_ibge"] == A
    got = figures.choose_pair({2020: _eligible([(A, "10", tie), (A, "9", tie)])})
    assert got["elected_sq"] == "9"  # a number, not text order
    assert set(got) >= {"year", "cd_ibge", "margin", "elected_near"}
    assert not any(key.startswith("_") for key in got)


def test_choose_pair_raises_without_pairs() -> None:
    with pytest.raises(ValueError, match="no close pair"):
        figures.choose_pair({2012: _eligible([]), 2016: _eligible([])})


def test_near_layers_uses_two_km_and_nothing_for_missing_tenure() -> None:
    key = {"cd_eleicao": [1] * 4, "sg_ue": ["10"] * 4, "cd_ibge": [A] * 4}
    strong = pl.DataFrame(
        {
            **key,
            "sq_candidato": [1, 2, 3, 4],
            "nr_zona": [1, 1, 1, 1],
            "nr_local_votacao": [1, 2, 3, 4],
        }
    )
    tenure = pl.DataFrame(
        {
            "cd_ibge": [A] * 3,
            "sg_ue": ["10"] * 3,
            "nr_zona": [1, 1, 1],
            "nr_local_votacao": [1, 2, 3],
            "dist_indigenous_km": [0.0, 2.0, 2.5],
            "dist_settlement_km": [2.0000001, None, 0.0],
        }
    )
    got = figures.near_layers(strong, tenure).sort("sq_candidato")
    assert got["near_indigenous"].to_list() == [True, True, False, False]
    assert got["near_settlement"].to_list() == [False, False, True, False]


def test_candidate_exposure_is_the_kernel_weighted_share() -> None:
    cx, cy = X0 + 0.5, Y0 + 0.5  # the cell's centre
    lon, lat = km_to_lonlat([cx + 1, cx - 3], [cy, cy])  # places 1 km and 3 km away
    places = pl.DataFrame(
        {
            "cd_ibge": [A, A],
            "sg_ue": ["10", "10"],
            "nr_zona": [1, 1],
            "nr_local_votacao": [1, 2],
            "lat": lat,
            "long": lon,
        }
    )
    rows = [
        (1, 1, "candidate", 7, 30),
        (1, 1, "legend", None, 70),
        (1, 2, "candidate", 7, 20),
        (1, 2, "legend", None, 80),
        (1, 2, "candidate", 8, 50),  # another candidate; V_p is 150
    ]
    place_votes = _frame(
        [(A, "10", 1, local, 1, kind, sq, v) for _, local, kind, sq, v in rows],
        [
            "cd_ibge",
            "sg_ue",
            "nr_zona",
            "nr_local_votacao",
            "cd_eleicao",
            "vote_type",
            "sq_candidato",
            "votes",
        ],
    )
    cells = pl.DataFrame({"cd_ibge": [A], "x_km": [X0], "y_km": [Y0]})
    pair = {"cd_ibge": A, "sg_ue": "10", "cd_eleicao": 1}
    got = figures.candidate_exposure(place_votes, places, cells, pair, "7")
    s1, s2 = 30 / 100, 20 / 150
    k1, k2 = np.exp(-0.5), np.exp(-1.5)
    assert got.columns == ["x_km", "y_km", "e"]
    assert got["e"].to_list() == pytest.approx([(k1 * s1 + k2 * s2) / (k1 + k2)], rel=1e-6)
    # the other candidate has no votes at place 1: zero there
    other = figures.candidate_exposure(place_votes, places, cells, pair, "8")
    assert other["e"].to_list() == pytest.approx([k2 * (50 / 150) / (k1 + k2)], rel=1e-6)


def _panels() -> tuple[list[str], list[pl.DataFrame], list[pl.DataFrame]]:
    left = pl.DataFrame({"x_km": [X0, X0 + 1, X0 + 2], "y_km": [Y0] * 3, "e": [0.0, 0.1, 0.3]})
    right = pl.DataFrame({"x_km": [X0, X0 + 1, X0 + 2], "y_km": [Y0] * 3, "e": [0.2, 0.0, 0.05]})
    circles = pl.DataFrame(
        {
            "x_km": [X0, X0 + 2],
            "y_km": [Y0, Y0],
            "share": [0.5, 0.2],
            "stronghold": [True, False],
        }
    )
    titles = [
        figures._panel_title("Narrowly elected", "indigenous"),
        figures._panel_title("Narrowly defeated", "settlement"),
    ]
    return titles, [left, right], [circles, circles]


def test_close_pair_figure_shares_one_norm_and_one_bar(layers: figures.Layers) -> None:
    titles, exposures, circles = _panels()
    fig, axes, bar, legend = figures.close_pair_figure(layers, titles, exposures, circles)
    norm = bar.mappable.norm
    assert (norm.vmin, norm.vmax) == (0.0, 0.3)  # the larger of the two maxima
    for ax, exposure in zip(axes, exposures, strict=True):
        polys = [c for c in ax.collections if isinstance(c, PolyCollection)]
        assert len(polys) == 1
        assert polys[0].norm is norm
        assert len(polys[0].get_paths()) == int((exposure["e"] > 0).sum())  # zeros unfilled
        assert ax.get_xlim() == axes[0].get_xlim()
        assert ax.get_ylim() == axes[0].get_ylim()
    fig.canvas.draw()
    xs = [bar.ax.get_position().x0, bar.ax.get_position().x1]
    assert xs == pytest.approx([axes[0].get_position().x0, axes[1].get_position().x1])
    ticks = [t.get_text() for t in bar.ax.get_xticklabels() if t.get_text()]
    assert ticks
    assert all(text.endswith("%") for text in ticks)
    assert bar.ax.get_xlabel() == "Exposure: kernel-weighted vote share"
    assert legend._ncols == 6
    assert legend.get_window_extent().y1 <= bar.ax.get_tightbbox().y0 + 1
    figures.plt.close(fig)


def test_close_pair_extent_is_the_reached_cells_plus_ten_km() -> None:
    _, exposures, _ = _panels()
    assert figures.close_pair_extent(exposures) == (X0 - 10, X0 + 3 + 10, Y0 - 10, Y0 + 1 + 10)
    with pytest.raises(ValueError):
        figures.close_pair_extent([exposures[0].clear()])


def test_close_pair_titles_name_the_layer_and_no_candidate(layers: figures.Layers) -> None:
    titles, exposures, circles = _panels()
    fig, axes, _, _ = figures.close_pair_figure(layers, titles, exposures, circles)
    shown = [ax.get_title() for ax in axes]
    assert shown[0].startswith("Narrowly elected")
    assert "stronghold near an indigenous land" in shown[0]
    assert shown[1].startswith("Narrowly defeated")
    assert "stronghold near a settlement" in shown[1]
    assert not any(ch.isdigit() for title in shown for ch in title)
    figures.plt.close(fig)


def test_candidate_places_marks_the_stronghold() -> None:
    lon, lat = km_to_lonlat([X0 + 1.5, X0 + 6.5], [Y0 + 1.5, Y0 + 1.5])
    places = pl.DataFrame(
        {
            "cd_ibge": [A, A],
            "sg_ue": ["10", "10"],
            "nr_zona": [1, 1],
            "nr_local_votacao": [1, 2],
            "lat": lat,
            "long": lon,
        }
    )
    rows = [(1, "candidate", 7, 60), (1, "legend", None, 40), (2, "candidate", 7, 5)]
    rows += [(2, "legend", None, 95)]
    place_votes = _frame(
        [(A, "10", 1, local, 1, kind, sq, v) for local, kind, sq, v in rows],
        [
            "cd_ibge",
            "sg_ue",
            "nr_zona",
            "nr_local_votacao",
            "cd_eleicao",
            "vote_type",
            "sq_candidato",
            "votes",
        ],
    )
    got = figures.candidate_places(place_votes, places, "7")
    assert got["share"].to_list() == pytest.approx([0.6, 0.05])
    assert got["stronghold"].to_list() == [True, False]  # place 2 has V_p of 100, quotient lower


def test_close_pair_writes_one_png_and_the_record(layers: figures.Layers, tmp_path: Path) -> None:
    specs = [
        _spec(A, 40, INDIGENOUS_FIRST),
        _spec(B, 10, BOTH_SETTLEMENTS),
        _spec(D, 20, SETTLEMENT_FIRST),
        _spec("1100005", 3, INDIGENOUS_FIRST),  # the smallest margin, outside the half
    ]
    store, manifests = _selection_world(specs)
    lon, lat = km_to_lonlat([X0 + 3.5, X0 + 8.5], [Y0 + 3.5, Y0 + 3.5])
    codes = [s["ibge"] for s in specs]
    places = [
        (2012, s["ibge"], "9" + s["ibge"][-4:], 1, n + 1, lat[n], lon[n])
        for s in specs
        for n in (0, 1)
    ]
    place_schema = ["ano", "cd_ibge", "sg_ue", "nr_zona", "nr_local_votacao", "lat", "long"]
    cells = [(ibge, X0 + dx, Y0 + dy) for ibge in codes for dx in range(12) for dy in range(8)]
    names = [(ibge, f"Town {i}") for i, ibge in enumerate(codes)]
    layers_file = _layers_file(tmp_path / "figure_layers.parquet")
    for name, filename, data in (
        ("polling_places", "polling_places_2012.parquet", _parquet(_frame(places, place_schema))),
        ("grid_cells", "grid_cells.parquet", _parquet(_frame(cells, ["cd_ibge", "x_km", "y_km"]))),
        (
            "municipalities",
            "municipalities.parquet",
            _parquet(_frame(names, ["cd_ibge", "name_ibge"])),
        ),
        ("figure_layers", "figure_layers.parquet", layers_file.read_bytes()),
    ):
        _put(store, manifests, name, filename, data)
    split = "code_ibge\n" + "\n".join(codes[:3]) + "\n"
    store.create("data/derived/split/explore_municipalities.csv", split.encode("utf-8"))

    record = figures.close_pair(store, manifests, tmp_path / "out", years=(2012,))
    assert record == {
        "year": 2012,
        "cd_ibge": D,
        "name_ibge": "Town 2",
        "margin": 0.002,
        "near": {"elected": "settlement", "not_elected": "indigenous"},
    }
    assert _pngs(tmp_path / "out") == ["06_close_pair.png"]
    assert json.loads(json.dumps(record)) == record


def test_close_pair_script_prints_one_json_line() -> None:
    text = (ROOT / "figures" / "06_close_pair.py").read_text(encoding="utf-8")
    assert "print(json.dumps(record))" in text
    assert "close_pair" in text
