"""Tests of terrain.figures and the contract of the figure scripts. No network, no GCS."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapely

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


def test_study_area_writes_exactly_two_files(layers: figures.Layers, tmp_path: Path) -> None:
    out = tmp_path / "out"
    figures.study_area(layers, out)
    assert sorted(p.name for p in out.iterdir()) == ["01_study_area.pdf", "01_study_area.png"]
    assert (out / "01_study_area.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "01_study_area.pdf").read_bytes().startswith(b"%PDF-")


def test_polling_places_writes_exactly_four_files(layers: figures.Layers, tmp_path: Path) -> None:
    out = tmp_path / "out"
    figures.polling_places(layers, _years(layers), out)
    assert sorted(p.name for p in out.iterdir()) == [
        "02_polling_places.pdf",
        "02_polling_places.png",
        "02_polling_places_appendix.pdf",
        "02_polling_places_appendix.png",
    ]
    assert (out / "02_polling_places_appendix.pdf").read_bytes().startswith(b"%PDF-")


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


def test_same_inputs_give_identical_pdfs(layers: figures.Layers, tmp_path: Path) -> None:
    points = _years(layers)
    for run in ("a", "b"):
        figures.study_area(layers, tmp_path / run)
        figures.polling_places(layers, points, tmp_path / run)
    for name in (
        "01_study_area.pdf",
        "02_polling_places.pdf",
        "02_polling_places_appendix.pdf",
    ):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_population_raster_masks_empty_and_zero_cells() -> None:
    raster, extent = figures.population_raster([10, 11, 13], [20, 20, 22], [5, 0, 40])
    assert raster.shape == (3, 4)
    assert extent == (10, 14, 20, 23)
    assert raster[0, 0] == 5
    assert raster[2, 3] == 40
    assert int(raster.count()) == 2
    assert raster.mask[0, 1]  # the zero-population cell


def test_population_raster_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        figures.population_raster([], [], [])
    with pytest.raises(ValueError):
        figures.population_raster([1, 2], [1], [1, 2])


def _cells() -> pl.DataFrame:
    rng = np.random.default_rng(1)
    return pl.DataFrame(
        {
            "x_km": rng.integers(-1500, -500, 300),
            "y_km": rng.integers(-1000, 0, 300),
            "pop_2022": rng.integers(0, 500, 300),
        }
    )


def test_population_writes_two_files_and_is_deterministic(
    layers: figures.Layers, tmp_path: Path
) -> None:
    cells = _cells()
    for run in ("a", "b"):
        norm = figures.population(layers, cells, tmp_path / run)
        assert norm.vmin == 1
        assert norm.vmax == int(cells["pop_2022"].max())
    out = tmp_path / "a"
    assert sorted(p.name for p in out.iterdir()) == ["03_population.pdf", "03_population.png"]
    assert (out / "03_population.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "03_population.pdf").read_bytes() == (
        tmp_path / "b" / "03_population.pdf"
    ).read_bytes()


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


@pytest.mark.parametrize("script", ["01_study_area.py", "02_polling_places.py", "03_population.py"])
def test_scripts_are_thin(script: str) -> None:
    text = (ROOT / "figures" / script).read_text(encoding="utf-8")
    assert "gs://" not in text
    assert "http" not in text
    imported = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "terrain":
                imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names if a.name.split(".")[0] == "terrain")
    assert imported <= {"terrain.figures", "terrain.storage"}
