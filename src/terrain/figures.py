"""Logic of the paper figures: 1 study area, 2 polling-place density, 3 population,
4 indigenous lands and settlements, 5 land without voters, 6 one close pair.

Everything is drawn in IBGE's Albers km (`terrain.grid.to_albers_km`), which is
equal-area, in the one style of `terrain.style` (figures/STYLE.md): PNG only,
light-blue water, framed maps, bottom legends, plain comma-separated numbers.
Layers come from `figure_layers.parquet` (data/contracts/figure_layers.md);
figures 3 and 5 also read `grid_cells.parquet`. Each figure has a `*_figure`
function that returns the matplotlib figure (for tests of its layout) and a
function that saves it. Scripts: figures/NN_*.py; contract: figures/README.md.

Figure 6 picks its municipality from the exploration half only: it reads the split list
and restricts every table with `cd_ibge` (`terrain.explore`) before using it.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapely
from matplotlib.cm import ScalarMappable
from matplotlib.collections import LineCollection, PathCollection, PolyCollection
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.path import Path as MplPath

from terrain import strongholds as sh
from terrain import style
from terrain.explore import exploration_municipalities, restrict
from terrain.grid import to_albers_km
from terrain.manifest import sha256_file
from terrain.storage import Store

plt = style.configure()

MAX_RIVER_SCALERANK = 6
MARGIN_KM = 150.0
HEX_KM = 25.0
YEARS = (2008, 2012, 2016, 2020, 2024)
PAPER_YEARS = (2008, 2024)
COLOUR_LABEL = "Polling places per hexagon"
POP_LABEL = "People per km² (2022)"
# longitude/latitude frame of the layers (data/contracts/figure_layers.md)
FRAME = (-92.0, -57.0, -26.0, 14.0)
# Figure 1's inset: half the width and height it had before the style (25% of the figure).
INSET_WIDTH = 0.125
INSET_HEIGHT = 0.3  # an upper bound: the inset keeps South America's aspect
TENURE_LAYERS = (
    ("undesignated", "Undesignated public forest", "green"),
    ("settlement", "Settlement", "pink"),
    ("indigenous", "Indigenous land", "orange"),
)
TENURE_CLASSES = (
    "Undesignated forest, no residents",
    "Undesignated forest, residents",
    "Other populated cells",
)
TENURE_CLASS_COLOURS = (
    style.CATEGORIES["green"][0],
    style.SCALE_ENDS["purple"][1],
    "#bcbddc",  # a light purple: populated, so on the population hue
)

Layers = dict[str, list[tuple[Any, str | None, str | None, int | None]]]
Extent = tuple[float, float, float, float]


# --- Reading


def fetch(store: Store, manifest: dict[str, Any], suffix: str, tmp_dir: Path) -> Path:
    """Download the one file of `manifest` whose path ends in `suffix`; check its SHA-256."""
    matches = [f for f in manifest["files"] if f["path"].endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected one file ending in {suffix!r}, found {len(matches)}")
    entry = matches[0]
    target = tmp_dir / entry["path"].rsplit("/", 1)[-1]
    store.download(entry["path"], target)
    if sha256_file(target) != entry["sha256"]:
        raise ValueError(f"{target.name} does not match the sha256 in its manifest")
    return target


def read_layers(path: Path) -> Layers:
    """`figure_layers.parquet` to {layer: [(geometry in Albers km, code, name, scalerank)]}."""
    df = pl.read_parquet(path)
    geoms = to_albers_km(shapely.from_wkb(df["geometry"].to_list()))
    layers: Layers = {}
    rows = zip(df["layer"], df["code"], df["name"], df["scalerank"], geoms, strict=True)
    for layer, code, name, rank, geom in rows:
        layers.setdefault(layer, []).append((geom, code, name, rank))
    return layers


def project_points(lat: Any, long: Any) -> np.ndarray:
    """Points with coordinates (nulls dropped) as an (n, 2) array of Albers km."""
    frame = pl.DataFrame({"lat": lat, "long": long}).drop_nulls()
    if frame.height == 0:
        return np.empty((0, 2))
    points = to_albers_km(shapely.points(frame["long"].to_numpy(), frame["lat"].to_numpy()))
    return shapely.get_coordinates(points)


# --- Drawing helpers


def _polygons(geoms: list[Any]) -> list[Any]:
    out: list[Any] = []
    for geom in geoms:
        out.extend(shapely.get_parts(geom))
    return [g for g in out if g.geom_type == "Polygon" and not g.is_empty]


def _polygon_path(polygons: list[Any]) -> MplPath:
    vertices: list[np.ndarray] = []
    codes: list[np.ndarray] = []
    for poly in polygons:
        for ring in [poly.exterior, *poly.interiors]:
            xy = np.asarray(ring.coords)
            code = np.full(len(xy), MplPath.LINETO, dtype=np.uint8)
            code[0] = MplPath.MOVETO
            code[-1] = MplPath.CLOSEPOLY
            vertices.append(xy)
            codes.append(code)
    if not vertices:
        return MplPath(np.empty((0, 2)))
    return MplPath(np.concatenate(vertices), np.concatenate(codes))


def add_polygons(
    ax: Any,
    geoms: list[Any],
    facecolor: Any,
    edgecolor: Any = "none",
    linewidth: float = 0.0,
    alpha: float | None = None,
    zorder: float = 1,
) -> None:
    """Draw polygons (multi-polygons and holes included) as one `PathCollection`."""
    polygons = _polygons(geoms)
    if not polygons:
        return
    paths = [_polygon_path([p]) for p in polygons]
    ax.add_collection(
        PathCollection(
            paths,
            facecolors=facecolor,
            edgecolors=edgecolor,
            linewidths=linewidth,
            alpha=alpha,
            zorder=zorder,
        )
    )


def add_outlines(ax: Any, geoms: list[Any], line: tuple[str, float], zorder: float = 2) -> None:
    """Draw polygon boundaries (holes included) as lines; `line` is (colour, width)."""
    lines = []
    for poly in _polygons(geoms):
        lines.extend(np.asarray(ring.coords) for ring in [poly.exterior, *poly.interiors])
    if lines:
        colour, width = line
        ax.add_collection(LineCollection(lines, colors=colour, linewidths=width, zorder=zorder))


def add_lines(ax: Any, geoms: list[Any], line: tuple[str, float], zorder: float = 1.2) -> None:
    """Draw line geometries (multi-lines included) as one `LineCollection`."""
    lines = []
    for geom in geoms:
        for part in shapely.get_parts(geom):
            if part.geom_type == "LineString" and not part.is_empty:
                lines.append(np.asarray(part.coords))
    if lines:
        colour, width = line
        ax.add_collection(LineCollection(lines, colors=colour, linewidths=width, zorder=zorder))


def _geoms(layers: Layers, layer: str, keep: Any = None) -> list[Any]:
    return [g for g, code, _, rank in layers.get(layer, []) if keep is None or keep(code, rank)]


def _setup(ax: Any, extent: Extent) -> None:
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    style.frame_map(ax)


def amazon_extent(layers: Layers) -> Extent:
    """The Legal Amazon outline's Albers bounds plus 150 km on each side."""
    xmin, ymin, xmax, ymax = shapely.total_bounds(_geoms(layers, "legal_amazon"))
    return (xmin - MARGIN_KM, xmax + MARGIN_KM, ymin - MARGIN_KM, ymax + MARGIN_KM)


def frame_extent() -> Extent:
    """The Albers bounds of the layers' longitude/latitude frame (South America)."""
    corners = to_albers_km(shapely.box(*FRAME).segmentize(1.0))
    x0, y0, x1, y1 = corners.bounds
    return (x0, x1, y0, y1)


def base_map(ax: Any, layers: Layers, extent: Extent) -> None:
    """Every map's base layers (figures/STYLE.md): water, land, borders, rivers, outline."""
    _setup(ax, extent)
    ax.set_facecolor(style.WATER)
    add_polygons(ax, _geoms(layers, "ocean"), style.WATER)
    others = _geoms(layers, "country", lambda c, r: c != "BRA")
    add_polygons(ax, others, style.LAND_OTHER)
    add_polygons(ax, _geoms(layers, "country", lambda c, r: c == "BRA"), style.BRAZIL)
    add_outlines(ax, others, style.COUNTRY_BORDER, zorder=1.1)
    add_polygons(ax, _geoms(layers, "lake"), style.WATER, zorder=1.1)
    rivers = _geoms(layers, "river", lambda c, r: r is not None and r <= MAX_RIVER_SCALERANK)
    add_lines(ax, rivers, style.RIVER)
    add_outlines(ax, _geoms(layers, "state"), style.STATE_BORDER)
    add_outlines(ax, _geoms(layers, "legal_amazon"), style.AMAZON_BORDER, zorder=3)


# --- Hexagon scale


def hex_grid(extent: Extent, size_km: float) -> int:
    """`gridsize` of `hexbin`: hexagons along x. Hexagons are about `size_km` across."""
    return max(1, round((extent[1] - extent[0]) / size_km))


def _hex_counts(points: np.ndarray, extent: Extent, gridsize: int) -> np.ndarray:
    fig, ax = plt.subplots()
    try:
        _setup(ax, extent)
        collection = ax.hexbin(
            points[:, 0], points[:, 1], gridsize=gridsize, extent=extent, mincnt=1
        )
        return np.asarray(collection.get_array())
    finally:
        plt.close(fig)


def hex_scale(points_by_year: dict[int, np.ndarray], extent: Extent, size_km: float) -> int:
    """The largest hexagon count over all years, binned exactly as the panels are."""
    gridsize = hex_grid(extent, size_km)
    best = 1
    for points in points_by_year.values():
        if len(points):
            counts = _hex_counts(np.asarray(points, dtype=float), extent, gridsize)
            if counts.size:
                best = max(best, int(counts.max()))
    return best


def _colour_norm(vmax: int) -> LogNorm:
    return LogNorm(vmin=1, vmax=max(vmax, 2))


def save(fig: Any, out_dir: Path, name: str) -> Path:
    """Save as `<out_dir>/<name>.png` through `style.save_png` (PNG only)."""
    return style.save_png(fig, Path(out_dir) / f"{name}.png")


# --- Figure 1


def study_area_figure(layers: Layers) -> Any:
    """South America zoomed to the Legal Amazon, with an inset of the continent."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=style.TALL)
    base_map(ax, layers, extent)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    child = style.inset(ax, INSET_WIDTH, INSET_HEIGHT)
    base_map(child, layers, frame_extent())
    child.add_patch(
        Rectangle(
            (extent[0], extent[2]),
            extent[1] - extent[0],
            extent[3] - extent[2],
            fill=False,
            edgecolor=style.TEXT,
            linewidth=style.LINE_WIDTH,
            zorder=4,
        )
    )
    return fig


def study_area(layers: Layers, out_dir: Path) -> Path:
    """Figure 1."""
    return save(study_area_figure(layers), out_dir, "01_study_area")


# --- Figure 2


def _hex_panel(
    ax: Any,
    layers: Layers,
    extent: Extent,
    points: np.ndarray,
    norm: LogNorm,
    gridsize: int,
    year: int,
) -> Any:
    base_map(ax, layers, extent)
    collection = ax.hexbin(
        points[:, 0],
        points[:, 1],
        gridsize=gridsize,
        extent=extent,
        mincnt=1,
        cmap=style.SCALES["purple"],
        norm=norm,
        linewidths=0.0,
        edgecolors="none",
        zorder=2.5,
    )
    ax.set_title(str(year))
    return collection


def polling_places_figures(
    layers: Layers, points_by_year: dict[int, np.ndarray]
) -> dict[str, tuple[Any, list[Any], Any]]:
    """Figure 2 (2008 and 2024) and its appendix (five years), on one shared scale.

    Returns {name: (figure, panel axes, colour bar)}.
    `hexbin`'s `gridsize` counts hexagons along x, so "25 km across" is approximate.
    """
    extent = amazon_extent(layers)
    gridsize = hex_grid(extent, HEX_KM)
    norm = _colour_norm(hex_scale(points_by_year, extent, HEX_KM))
    out: dict[str, tuple[Any, list[Any], Any]] = {}

    fig, axes = plt.subplots(1, 2, figsize=style.WIDE)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.17, wspace=0.03)
    last = None
    for ax, year in zip(axes, PAPER_YEARS, strict=True):
        last = _hex_panel(ax, layers, extent, points_by_year[year], norm, gridsize, year)
    bar = style.bottom_colorbar(fig, list(axes), last, COLOUR_LABEL)
    out["02_polling_places"] = (fig, list(axes), bar)

    fig, grid = plt.subplots(2, 3, figsize=style.MAP_GRID)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.13, wspace=0.03, hspace=0.12)
    flat = list(grid.ravel())
    panels = flat[: len(YEARS)]
    for ax, year in zip(panels, YEARS, strict=True):
        last = _hex_panel(ax, layers, extent, points_by_year[year], norm, gridsize, year)
    for spare in flat[len(YEARS) :]:
        spare.set_axis_off()
    bar = style.bottom_colorbar(fig, panels, last, COLOUR_LABEL)
    out["02_polling_places_appendix"] = (fig, panels, bar)
    return out


def polling_places(
    layers: Layers, points_by_year: dict[int, np.ndarray], out_dir: Path
) -> dict[str, LogNorm]:
    """Figure 2 and its appendix; returns the colour norm of each output, by file stem."""
    norms = {}
    for name, (fig, _, bar) in polling_places_figures(layers, points_by_year).items():
        norms[name] = bar.mappable.norm
        save(fig, out_dir, name)
    return norms


# --- Figure 3


def cell_polygons(x_km: Any, y_km: Any, pop: Any) -> tuple[np.ndarray, np.ndarray]:
    """The 1 km squares of the populated cells (n × 4 × 2, Albers km) and their population.

    Cells with population 0 or below are left out (drawn unfilled).
    """
    x = np.asarray(x_km, dtype=float)
    y = np.asarray(y_km, dtype=float)
    values = np.asarray(pop, dtype=float)
    if x.size == 0 or not (x.size == y.size == values.size):
        raise ValueError("x_km, y_km and pop must be non-empty and of the same length")
    keep = values > 0
    x, y, values = x[keep], y[keep], values[keep]
    corners = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    squares = np.stack([x, y], axis=1)[:, None, :] + corners[None, :, :]
    return squares, values


def population_figure(layers: Layers, cells: pl.DataFrame) -> tuple[Any, Any, Any]:
    """Figure 3: populated 1 km cells as filled squares coloured by 2022 population."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=style.TALL)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.1)
    base_map(ax, layers, extent)
    squares, values = cell_polygons(
        cells["x_km"].to_numpy(), cells["y_km"].to_numpy(), cells["pop_2022"].to_numpy()
    )
    norm = _colour_norm(int(values.max()) if values.size else 1)
    collection = PolyCollection(
        squares,
        array=values,
        cmap=style.SCALES["purple"],
        norm=norm,
        edgecolors="none",
        linewidths=0.0,
        antialiaseds=False,
        zorder=2.5,
    )
    collection.set_rasterized(True)  # about 534,000 squares; the PNG looks the same
    ax.add_collection(collection)
    bar = style.bottom_colorbar(fig, [ax], collection, POP_LABEL)
    return fig, ax, bar


def population(layers: Layers, cells: pl.DataFrame, out_dir: Path) -> LogNorm:
    """Figure 3; returns its colour norm."""
    fig, _, bar = population_figure(layers, cells)
    norm = bar.mappable.norm
    save(fig, out_dir, "03_population")
    return norm


# --- Figure 4


def tenure_figure(layers: Layers) -> tuple[Any, Any, Any]:
    """Figure 4: indigenous lands, settlements and undesignated forest (2024), as categories."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=style.TALL)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.06)
    base_map(ax, layers, extent)
    handles = []
    for i, (layer, label, hue) in enumerate(TENURE_LAYERS):
        fill, edge = style.CATEGORIES[hue]
        add_polygons(
            ax,
            _geoms(layers, layer),
            fill,
            edgecolor=edge,
            linewidth=style.CATEGORY_EDGE_WIDTH,
            alpha=style.CATEGORY_ALPHA,
            zorder=2.2 + i / 10,
        )
        handles.append(
            Patch(
                facecolor=fill,
                edgecolor=edge,
                linewidth=style.CATEGORY_EDGE_WIDTH,
                alpha=style.CATEGORY_ALPHA,
                label=label,
            )
        )
    legend = style.bottom_legend(fig, [ax], handles[::-1])
    return fig, ax, legend


def tenure(layers: Layers, out_dir: Path) -> Path:
    """Figure 4."""
    fig, _, _ = tenure_figure(layers)
    return save(fig, out_dir, "04_tenure")


# --- Figure 5


def tenure_classes(
    x_km: Any, y_km: Any, pop: Any, share_undesignated: Any
) -> tuple[np.ma.MaskedArray, Extent, dict[str, int]]:
    """Class of each 1 km cell for figure 5, its extent and the cells per class.

    0: undesignated, nobody lived there in 2022; 1: undesignated, populated;
    2: populated, not undesignated. Other cells and pixels with no cell are masked.
    """
    x = np.asarray(x_km).astype(np.int64)
    y = np.asarray(y_km).astype(np.int64)
    people = np.asarray(pop).astype(float)
    share = np.asarray(share_undesignated).astype(float)
    if x.size == 0 or not (x.size == y.size == people.size == share.size):
        raise ValueError("x_km, y_km, pop and share_undesignated must be non-empty and equal")
    undesignated = share > 0
    populated = people > 0
    cls = np.full(x.size, -1, dtype=np.int64)
    cls[undesignated & ~populated] = 0
    cls[undesignated & populated] = 1
    cls[~undesignated & populated] = 2
    x_min, x_max = int(x.min()), int(x.max())
    y_min, y_max = int(y.min()), int(y.max())
    grid = np.full((y_max - y_min + 1, x_max - x_min + 1), -1, dtype=np.int64)
    grid[y - y_min, x - x_min] = cls
    counts = {label: int((cls == i).sum()) for i, label in enumerate(TENURE_CLASSES)}
    return np.ma.masked_less(grid, 0), (x_min, x_max + 1, y_min, y_max + 1), counts


def land_without_voters_figure(
    layers: Layers, cells: pl.DataFrame
) -> tuple[Any, Any, Any, dict[str, int]]:
    """Figure 5: undesignated forest in 2024 by whether anyone lived there in 2022."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=style.TALL)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.06)
    base_map(ax, layers, extent)
    raster, raster_extent, counts = tenure_classes(
        cells["x_km"].to_numpy(),
        cells["y_km"].to_numpy(),
        cells["pop_2022"].to_numpy(),
        cells["share_undesignated_2024"].to_numpy(),
    )
    ax.imshow(
        raster,
        origin="lower",
        extent=raster_extent,
        interpolation="nearest",
        cmap=ListedColormap(TENURE_CLASS_COLOURS),
        norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], len(TENURE_CLASS_COLOURS)),
        zorder=2.5,
    )
    _setup(ax, extent)
    handles = [
        Patch(facecolor=colour, label=f"{label} ({style.thousands(counts[label])} cells)")
        for label, colour in zip(TENURE_CLASSES, TENURE_CLASS_COLOURS, strict=True)
    ]
    legend = style.bottom_legend(fig, [ax], handles)
    return fig, ax, legend, counts


def land_without_voters(layers: Layers, cells: pl.DataFrame, out_dir: Path) -> dict[str, int]:
    """Figure 5; returns the cells per class."""
    fig, _, _, counts = land_without_voters_figure(layers, cells)
    save(fig, out_dir, "05_land_without_voters")
    return counts


# --- Figure 6

NEAR_KM = 2.0
CLOSE_YEARS = YEARS
LAYER_COLUMNS = {"indigenous": "dist_indigenous_km", "settlement": "dist_settlement_km"}
PANEL_TITLES = ("Narrowly elected", "Narrowly defeated")
NEAR_TEXT = {
    "indigenous": "(stronghold near an indigenous land)",
    "settlement": "(stronghold near a settlement)",
}
EXPOSURE_LABEL = "Exposure: kernel-weighted vote share"
EXTENT_MARGIN_KM = 10.0
CIRCLE_AREA = 90.0  # marker area in pt² for a vote share of 100%
LEGEND_SHARES = (0.10, 0.25, 0.50)
STRONGHOLD_WIDTH = 1.0
CIRCLE_WIDTH = 0.4
CELL_NAMES = ["x_km", "y_km"]


def near_layers(strong: pl.DataFrame, tenure: pl.DataFrame) -> pl.DataFrame:
    """Each stronghold with `near_indigenous` and `near_settlement` (within 2 km, 0 = inside).

    The join is that of `explore/0001_kill_criterion_1.py`: zone and place cast to Int64.
    A stronghold with no tenure row, or no distance, is near nothing.
    """
    casts = [
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("sg_ue").cast(pl.Utf8),
        pl.col("nr_zona").cast(pl.Int64),
        pl.col("nr_local_votacao").cast(pl.Int64),
    ]
    left = strong.with_columns(casts)
    right = (
        tenure.select(*sh.PLACE_KEY, *LAYER_COLUMNS.values())
        .with_columns(casts)
        .unique(sh.PLACE_KEY, keep="first", maintain_order=True)
    )
    joined = left.join(right, on=sh.PLACE_KEY, how="left")
    near = [
        (pl.col(column) <= NEAR_KM + sh.TOLERANCE).fill_null(False).alias(f"near_{layer}")
        for layer, column in LAYER_COLUMNS.items()
    ]
    return joined.select(
        "cd_eleicao", "sg_ue", pl.col("sq_candidato").cast(pl.Utf8), "cd_ibge", *near
    )


def eligible_pairs(paired: pl.DataFrame, near: pl.DataFrame) -> pl.DataFrame:
    """The close pairs (0.5%, not inverted) of one year with one stronghold near each layer.

    Eligible: one candidate's stronghold is near an indigenous land and not near a
    settlement, and the other's is near a settlement and not near an indigenous land.
    `paired` comes from `margins`; `near` from `near_layers`. Candidate numbers are text.
    """
    close = sh.close_pairs(paired)
    margins = paired.select(
        pl.col("cd_ibge").cast(pl.Utf8),
        pl.col("sg_ue").cast(pl.Utf8),
        "cd_eleicao",
        pl.col("elected_sq").cast(pl.Utf8).alias("w"),
        pl.col("other_sq").cast(pl.Utf8).alias("l"),
        "margin",
    )
    out = close.join(margins, on=["cd_ibge", "sg_ue", "cd_eleicao", "w", "l"], how="left")
    for side, column in (("elected", "w"), ("other", "l")):
        found = near.select(
            "cd_eleicao",
            "sg_ue",
            pl.col("sq_candidato").alias(column),
            pl.col("near_indigenous").alias(f"{side}_ind"),
            pl.col("near_settlement").alias(f"{side}_set"),
        )
        out = out.join(found, on=["cd_eleicao", "sg_ue", column], how="inner")
    indigenous_first = (
        pl.col("elected_ind") & ~pl.col("elected_set") & pl.col("other_set") & ~pl.col("other_ind")
    )
    settlement_first = (
        pl.col("elected_set") & ~pl.col("elected_ind") & pl.col("other_ind") & ~pl.col("other_set")
    )
    kept = out.filter(indigenous_first | settlement_first)
    return kept.select(
        "cd_ibge",
        "sg_ue",
        "cd_eleicao",
        pl.col("w").alias("elected_sq"),
        pl.col("l").alias("other_sq"),
        "margin",
        pl.when(indigenous_first)
        .then(pl.lit("indigenous"))
        .otherwise(pl.lit("settlement"))
        .alias("elected_near"),
        pl.when(indigenous_first)
        .then(pl.lit("settlement"))
        .otherwise(pl.lit("indigenous"))
        .alias("other_near"),
    ).sort("cd_ibge", "elected_sq")


def choose_pair(by_year: dict[int, pl.DataFrame]) -> dict[str, Any]:
    """The eligible pair with the smallest |margin|.

    Ties go to the later year, then the lower IBGE code, then the lower elected candidate
    number. `by_year` maps a year to its `eligible_pairs`. Raises `ValueError` if none is left.
    """
    frames = [f.with_columns(pl.lit(year).alias("year")) for year, f in by_year.items() if f.height]
    if not frames:
        raise ValueError(
            "no close pair in the exploration half has one stronghold near an indigenous "
            "land and the other near a settlement"
        )
    ranked = (
        pl.concat(frames)
        .with_columns(
            pl.col("margin").abs().round(12).alias("_abs_margin"),
            pl.col("elected_sq").cast(pl.Int64, strict=False).alias("_sq_number"),
        )
        .sort(
            ["_abs_margin", "year", "cd_ibge", "_sq_number", "elected_sq"],
            descending=[False, True, False, False, False],
            nulls_last=True,
        )
    )
    row = ranked.row(0, named=True)
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _read(
    store: Store,
    manifest: dict[str, Any],
    suffix: str,
    tmp_dir: Path,
    half: frozenset[str] | None = None,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """One parquet of a build manifest, checked, read, deleted; restricted to `half` if given."""
    path = fetch(store, manifest, suffix, tmp_dir)
    try:
        frame = pl.read_parquet(path, columns=columns)
    finally:
        path.unlink()
    return frame if half is None else restrict(frame, half)


def _section_files(manifest: dict[str, Any], year: int) -> list[str]:
    names = (f["path"].rsplit("/", 1)[-1] for f in manifest["files"])
    return sorted(n for n in names if re.fullmatch(rf"section_votes_{year}_[A-Z]{{2}}\.parquet", n))


def _year_eligible(
    store: Store,
    manifests: dict[str, dict[str, Any]],
    half: frozenset[str],
    year: int,
    tmp_dir: Path,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A year's eligible pairs and the place votes of the municipalities that hold them."""
    results = manifests["tse_results"]
    votes = _read(store, results, f"candidate_votes_{year}.parquet", tmp_dir, half)
    turnout = _read(store, results, f"turnout_{year}.parquet", tmp_dir, half)
    tenure_name = f"polling_place_tenure_{year}.parquet"
    tenure = _read(store, manifests["polling_place_tenure"], tenure_name, tmp_dir, half)
    if "ano" in tenure.columns:
        tenure = tenure.filter(pl.col("ano") == year)
    if votes.height == 0:  # no council candidates in the half this year
        return pl.DataFrame(), pl.DataFrame()
    main = sh.main_election(votes)
    cands = sh.candidacy_votes(votes, year, main)
    paired = sh.margins(sh.within_list_pairs(cands), sh.valid_votes(turnout, main))
    files = _section_files(manifests["section_votes"], year)
    if not files:
        raise ValueError(f"the section_votes manifest has no files for {year}")
    pieces = [
        sh.place_candidate_votes(_read(store, manifests["section_votes"], f, tmp_dir, half), main)
        for f in files
    ]
    place_votes = pl.concat(pieces)
    near = near_layers(sh.strongholds(place_votes), tenure)
    eligible = eligible_pairs(paired, near)
    keep = eligible["cd_ibge"].to_list()
    kept_votes = place_votes.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(keep))
    return eligible, kept_votes


def select_close_pair(
    store: Store,
    manifests: dict[str, dict[str, Any]],
    half: frozenset[str],
    tmp_dir: Path,
    years: Sequence[int] = CLOSE_YEARS,
) -> tuple[dict[str, Any], pl.DataFrame]:
    """The close pair of figure 6 and the place votes of its municipality and year.

    Every table with `cd_ibge` is restricted to the exploration half `half` before use.
    The pair is a dict: `year`, `cd_ibge`, `sg_ue`, `cd_eleicao`, `elected_sq`,
    `other_sq`, `margin`, `elected_near`, `other_near`.
    """
    eligible: dict[int, pl.DataFrame] = {}
    votes: dict[int, pl.DataFrame] = {}
    for year in years:
        eligible[year], votes[year] = _year_eligible(store, manifests, half, year, tmp_dir)
    pair = choose_pair(eligible)
    muni_votes = votes[pair["year"]].filter(
        (pl.col("cd_ibge").cast(pl.Utf8) == pair["cd_ibge"])
        & (pl.col("sg_ue").cast(pl.Utf8) == pair["sg_ue"])
    )
    return pair, muni_votes


def candidate_exposure(
    place_votes: pl.DataFrame,
    places: pl.DataFrame,
    cells: pl.DataFrame,
    pair: dict[str, Any],
    sq: str,
) -> pl.DataFrame:
    """`E_ic` of candidate `sq` for the reached cells: columns `x_km`, `y_km`, `e`.

    The `exp2` kernel and the share measure of decision 0004, from
    `strongholds.exposure` with a one-row pairs table: the candidate as `w` and a null
    `l`, so `D_i` is `E_ic` itself.
    """
    pairs = pl.DataFrame(
        {
            "cd_ibge": [pair["cd_ibge"]],
            "sg_ue": [pair["sg_ue"]],
            "cd_eleicao": [pair["cd_eleicao"]],
            "w": [str(sq)],
            "l": pl.Series([None], dtype=pl.Utf8),
        }
    )
    dist = sh.cell_place_distances(cells, sh.locate_places(places))
    out = sh.exposure(
        dist, sh.place_totals(place_votes), sh.place_shares(place_votes), pairs, "exp2", "share"
    )
    return out.select(*CELL_NAMES, pl.col("D_i").alias("e"))


def candidate_places(place_votes: pl.DataFrame, places: pl.DataFrame, sq: str) -> pl.DataFrame:
    """Polling places where candidate `sq` has votes: `x_km`, `y_km`, `share`, `stronghold`."""
    shares = sh.place_shares(place_votes).filter(
        (pl.col("sq_candidato") == str(sq)) & (pl.col("s_cp") > 0)
    )
    top = (
        sh.strongholds(place_votes)
        .filter(pl.col("sq_candidato").cast(pl.Utf8) == str(sq))
        .select(
            pl.col("cd_ibge").cast(pl.Utf8),
            pl.col("sg_ue").cast(pl.Utf8),
            pl.col("nr_zona").cast(pl.Int64),
            pl.col("nr_local_votacao").cast(pl.Int64),
            pl.lit(True).alias("stronghold"),
        )
    )
    return (
        shares.join(sh.locate_places(places), on=sh.PLACE_KEY, how="inner")
        .join(top, on=sh.PLACE_KEY, how="left")
        .with_columns(pl.col("stronghold").fill_null(False))
        .select(*CELL_NAMES, pl.col("s_cp").alias("share"), "stronghold")
        .sort(CELL_NAMES)
    )


def close_pair_extent(exposures: Sequence[pl.DataFrame]) -> Extent:
    """The Albers bounds of the reached cells plus 10 km on each side (cells are 1 km squares)."""
    cells = pl.concat([e.select(CELL_NAMES) for e in exposures])
    if cells.height == 0:
        raise ValueError("the municipality has no reached cells to draw")
    m = EXTENT_MARGIN_KM
    return (
        float(cells["x_km"].min()) - m,
        float(cells["x_km"].max()) + 1 + m,
        float(cells["y_km"].min()) - m,
        float(cells["y_km"].max()) + 1 + m,
    )


def _close_pair_handles() -> list[Any]:
    handles: list[Any] = []
    for hue, label in (("orange", "Indigenous land"), ("pink", "Settlement")):
        fill, edge = style.CATEGORIES[hue]
        handles.append(
            Patch(
                facecolor=fill,
                edgecolor=edge,
                linewidth=style.CATEGORY_EDGE_WIDTH,
                alpha=style.CATEGORY_ALPHA,
                label=label,
            )
        )

    def circle(share: float, width: float, label: str) -> Line2D:
        return Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor="white",
            markeredgecolor="black",
            markeredgewidth=width,
            markersize=float(np.sqrt(share * CIRCLE_AREA)),
            label=label,
        )

    for i, share in enumerate(LEGEND_SHARES):
        text = style.percent(share)
        handles.append(circle(share, CIRCLE_WIDTH, f"Polling place: {text}" if i == 0 else text))
    handles.append(circle(LEGEND_SHARES[1], STRONGHOLD_WIDTH, "Stronghold"))
    return handles


def close_pair_figure(
    layers: Layers,
    titles: Sequence[str],
    exposures: Sequence[pl.DataFrame],
    places: Sequence[pl.DataFrame],
) -> tuple[Any, list[Any], Any, Any]:
    """Figure 6: two panels, one extent and one exposure scale; returns fig, axes, bar, legend."""
    extent = close_pair_extent(exposures)
    vmax = max(float(e["e"].max() or 0.0) for e in exposures)
    norm = Normalize(0.0, vmax if vmax > 0 else 1.0)
    fig, grid = plt.subplots(1, 2, figsize=style.WIDE)
    axes = list(grid)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.30, wspace=0.03)
    for ax, title, exposure, circles in zip(axes, titles, exposures, places, strict=True):
        base_map(ax, layers, extent)
        for i, (layer, hue) in enumerate((("indigenous", "orange"), ("settlement", "pink"))):
            fill, edge = style.CATEGORIES[hue]
            add_polygons(
                ax,
                _geoms(layers, layer),
                fill,
                edgecolor=edge,
                linewidth=style.CATEGORY_EDGE_WIDTH,
                alpha=style.CATEGORY_ALPHA,
                zorder=2.2 + i / 10,
            )
        filled = exposure.filter(pl.col("e") > 0)
        if filled.height:
            squares, values = cell_polygons(
                filled["x_km"].to_numpy(), filled["y_km"].to_numpy(), filled["e"].to_numpy()
            )
            ax.add_collection(
                PolyCollection(
                    squares,
                    array=values,
                    cmap=style.SCALES[style.DEFAULT_SCALE],
                    norm=norm,
                    edgecolors="none",
                    linewidths=0.0,
                    antialiaseds=False,
                    zorder=2.5,
                )
            )
        for strong, width, z in ((False, CIRCLE_WIDTH, 4.0), (True, STRONGHOLD_WIDTH, 4.5)):
            part = circles.filter(pl.col("stronghold") == strong)
            if part.height:
                ax.scatter(
                    part["x_km"].to_numpy(),
                    part["y_km"].to_numpy(),
                    s=part["share"].to_numpy() * CIRCLE_AREA,
                    facecolors="white",
                    edgecolors="black",
                    linewidths=width,
                    zorder=z,
                )
        ax.set_title(title)
    mappable = ScalarMappable(norm=norm, cmap=style.SCALES[style.DEFAULT_SCALE])
    mappable.set_array([])
    bar = style.bottom_colorbar(fig, axes, mappable, EXPOSURE_LABEL, formatter=style.PERCENT)
    legend = style.bottom_legend(fig, axes, _close_pair_handles(), gap=0.17)
    return fig, axes, bar, legend


def _panel_title(heading: str, near: str) -> str:
    return f"{heading}\n{NEAR_TEXT[near]}"


def close_pair(
    store: Store,
    manifests: dict[str, dict[str, Any]],
    out_dir: Path,
    years: Sequence[int] = CLOSE_YEARS,
) -> dict[str, Any]:
    """Figure 6: saves `06_close_pair.png` and returns the record the script prints."""
    half = exploration_municipalities(store)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pair, place_votes = select_close_pair(store, manifests, half, tmp_dir, years)
        year, ibge = pair["year"], pair["cd_ibge"]

        def one_muni(frame: pl.DataFrame) -> pl.DataFrame:
            return frame.filter(pl.col("cd_ibge").cast(pl.Utf8) == ibge)

        def read(name: str, suffix: str, columns: list[str] | None = None) -> pl.DataFrame:
            return one_muni(_read(store, manifests[name], suffix, tmp_dir, half, columns))

        places = read("polling_places", f"polling_places_{year}.parquet")
        if "ano" in places.columns:
            places = places.filter(pl.col("ano") == year)
        cells = read("grid_cells", "grid_cells.parquet", ["cd_ibge", "x_km", "y_km"])
        munis = read("municipalities", "municipalities.parquet", ["cd_ibge", "name_ibge"])
        if munis.height != 1:
            raise ValueError(f"expected one row for {ibge} in municipalities, got {munis.height}")
        layers_file = fetch(store, manifests["figure_layers"], "figure_layers.parquet", tmp_dir)
        layers = read_layers(layers_file)
        candidates = (pair["elected_sq"], pair["other_sq"])
        exposures = [candidate_exposure(place_votes, places, cells, pair, sq) for sq in candidates]
        circles = [candidate_places(place_votes, places, sq) for sq in candidates]
        near = (pair["elected_near"], pair["other_near"])
        titles = [_panel_title(h, n) for h, n in zip(PANEL_TITLES, near, strict=True)]
        fig, _, _, _ = close_pair_figure(layers, titles, exposures, circles)
        save(fig, out_dir, "06_close_pair")
    return {
        "year": int(year),
        "cd_ibge": ibge,
        "name_ibge": munis["name_ibge"][0],
        "margin": round(float(pair["margin"]), 4),
        "near": {"elected": near[0], "not_elected": near[1]},
    }
