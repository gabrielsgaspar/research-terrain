"""Tests of terrain.figures and the contract of the figure scripts. No network, no GCS."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapely
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgb

from terrain import figures
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
