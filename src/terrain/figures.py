"""Logic of paper figures 1 (study area), 2 (polling-place density), 3 (population)
and 5 (land without voters).

Everything is drawn in IBGE's Albers km (`terrain.grid.to_albers_km`), which is
equal-area, so hexagons have equal area. Layers come from `figure_layers.parquet`
(data/contracts/figure_layers.md); figure 3 also reads three columns of
`grid_cells.parquet`. Scripts: figures/01_study_area.py, figures/02_polling_places.py
and figures/03_population.py; contract: figures/README.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "research-terrain"

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
import shapely  # noqa: E402
from matplotlib.collections import LineCollection, PathCollection  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402

from terrain.grid import to_albers_km  # noqa: E402
from terrain.manifest import sha256_file  # noqa: E402
from terrain.storage import Store  # noqa: E402

OCEAN = "#cfe3f3"
LAKE = "#cfe3f3"
RIVER = "#cfe3f3"
OTHER_COUNTRY = "#e6e6e6"
BRAZIL = "#ffffff"
STATE_EDGE = "#9a9a9a"
STATE_WIDTH = 0.3
AMAZON_EDGE = "#000000"
AMAZON_WIDTH = 1.2
RIVER_WIDTH = 0.4
MAX_RIVER_SCALERANK = 6
MARGIN_KM = 150.0
HEX_KM = 25.0
YEARS = (2008, 2012, 2016, 2020, 2024)
PAPER_YEARS = (2008, 2024)
COLOUR_LABEL = "Polling places per hexagon"
CMAP = "viridis"
TENURE = (("indigenous", "#d95f02"), ("settlement", "#7570b3"), ("undesignated", "#1b9e77"))
TENURE_WIDTH = 0.15
POP_CMAP = "magma_r"
POP_LABEL = "People per km² (2022)"
# longitude/latitude frame of the layers (data/contracts/figure_layers.md)
FRAME = (-92.0, -57.0, -26.0, 14.0)
EMPTY_UNDESIGNATED = "#1b9e77"
POPULATED_UNDESIGNATED = "#d95f02"
POPULATED_OTHER = "#bdbdbd"
TENURE_CLASSES = (
    "Undesignated forest, no residents",
    "Undesignated forest, residents",
    "Other populated cells",
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
    ax: Any, geoms: list[Any], facecolor: str, edgecolor: str = "none", linewidth: float = 0.0
) -> None:
    """Draw polygons (multi-polygons and holes included) as one `PathCollection`."""
    polygons = _polygons(geoms)
    if not polygons:
        return
    paths = [_polygon_path([p]) for p in polygons]
    ax.add_collection(
        PathCollection(paths, facecolors=facecolor, edgecolors=edgecolor, linewidths=linewidth)
    )


def add_outlines(ax: Any, geoms: list[Any], color: str, linewidth: float) -> None:
    """Draw polygon boundaries (holes included) as lines."""
    lines = []
    for poly in _polygons(geoms):
        lines.extend(np.asarray(ring.coords) for ring in [poly.exterior, *poly.interiors])
    if lines:
        ax.add_collection(LineCollection(lines, colors=color, linewidths=linewidth))


def add_lines(ax: Any, geoms: list[Any], color: str, linewidth: float) -> None:
    """Draw line geometries (multi-lines included) as one `LineCollection`."""
    lines = []
    for geom in geoms:
        for part in shapely.get_parts(geom):
            if part.geom_type == "LineString" and not part.is_empty:
                lines.append(np.asarray(part.coords))
    if lines:
        ax.add_collection(LineCollection(lines, colors=color, linewidths=linewidth))


def _geoms(layers: Layers, layer: str, keep: Any = None) -> list[Any]:
    return [g for g, code, _, rank in layers.get(layer, []) if keep is None or keep(code, rank)]


def _setup(ax: Any, extent: Extent) -> None:
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])


def amazon_extent(layers: Layers) -> Extent:
    """The Legal Amazon outline's Albers bounds plus 150 km on each side."""
    xmin, ymin, xmax, ymax = shapely.total_bounds(_geoms(layers, "legal_amazon"))
    return (xmin - MARGIN_KM, xmax + MARGIN_KM, ymin - MARGIN_KM, ymax + MARGIN_KM)


def _background(ax: Any, layers: Layers, extent: Extent, full: bool) -> None:
    """Ocean and neighbours (`full`) or Brazil only, then states and the Amazon outline."""
    _setup(ax, extent)
    if full:
        ax.set_facecolor(OCEAN)
        add_polygons(ax, _geoms(layers, "ocean"), OCEAN)
        add_polygons(ax, _geoms(layers, "country", lambda c, r: c != "BRA"), OTHER_COUNTRY)
    add_polygons(ax, _geoms(layers, "country", lambda c, r: c == "BRA"), BRAZIL)
    if full:
        add_polygons(ax, _geoms(layers, "lake"), LAKE)
        add_lines(
            ax,
            _geoms(layers, "river", lambda c, r: r is not None and r <= MAX_RIVER_SCALERANK),
            RIVER,
            RIVER_WIDTH,
        )
    add_outlines(ax, _geoms(layers, "state"), STATE_EDGE, STATE_WIDTH)
    add_outlines(ax, _geoms(layers, "legal_amazon"), AMAZON_EDGE, AMAZON_WIDTH)


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


# --- Saving


def save(fig: Any, out_dir: Path, name: str) -> None:
    """Write `name.png` (300 dpi) and a deterministic `name.pdf`, then close the figure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # tight: crop to the drawn content, so outer labels are kept and margins dropped
    tight = {"bbox_inches": "tight", "pad_inches": 0.03}
    fig.savefig(out_dir / f"{name}.png", dpi=300, **tight)
    fig.savefig(out_dir / f"{name}.pdf", dpi=300, metadata={"CreationDate": None}, **tight)
    plt.close(fig)


# --- Figures


def study_area(layers: Layers, out_dir: Path) -> None:
    """Figure 1: South America zoomed to the Legal Amazon, with an inset of the continent."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    _background(ax, layers, extent, full=True)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)

    inset = fig.add_axes((0.70, 0.03, 0.25, 0.25))
    corners = to_albers_km(shapely.box(FRAME[0], FRAME[1], FRAME[2], FRAME[3]).segmentize(1.0))
    fx0, fy0, fx1, fy1 = corners.bounds
    _background(inset, layers, (fx0, fx1, fy0, fy1), full=True)
    inset.add_patch(
        Rectangle(
            (extent[0], extent[2]),
            extent[1] - extent[0],
            extent[3] - extent[2],
            fill=False,
            edgecolor="black",
            linewidth=1.0,
        )
    )
    save(fig, out_dir, "01_study_area")


def _colour_norm(vmax: int) -> LogNorm:
    return LogNorm(vmin=1, vmax=max(vmax, 2))


def _panel(
    ax: Any, layers: Layers, extent: Extent, points: np.ndarray, norm: LogNorm, gridsize: int
) -> Any:
    _background(ax, layers, extent, full=False)
    ax.set_facecolor("#f4f4f4")
    collection = ax.hexbin(
        points[:, 0],
        points[:, 1],
        gridsize=gridsize,
        extent=extent,
        mincnt=1,
        cmap=CMAP,
        norm=norm,
        linewidths=0.0,
    )
    return collection


def polling_places(
    layers: Layers, points_by_year: dict[int, np.ndarray], out_dir: Path
) -> dict[str, LogNorm]:
    """Figure 2: hexagon density with one colour scale; the paper pair and the appendix.

    `hexbin`'s `gridsize` counts hexagons along x, so "25 km across" is approximate.
    Returns the colour norm of each output, keyed by file name stem.
    """
    extent = amazon_extent(layers)
    gridsize = hex_grid(extent, HEX_KM)
    norm = _colour_norm(hex_scale(points_by_year, extent, HEX_KM))
    norms: dict[str, LogNorm] = {}

    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.6))
    last = None
    for ax, year in zip(axes, PAPER_YEARS, strict=True):
        last = _panel(ax, layers, extent, points_by_year[year], norm, gridsize)
        ax.set_xlabel(str(year))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.2, wspace=0.03)
    cax = fig.add_axes((0.25, 0.07, 0.5, 0.03))
    fig.colorbar(last, cax=cax, orientation="horizontal", label=COLOUR_LABEL)
    norms["02_polling_places"] = last.norm
    save(fig, out_dir, "02_polling_places")

    fig, axes = plt.subplots(2, 3, figsize=(6.5, 4.4))
    flat = list(axes.ravel())
    for ax, year in zip(flat, YEARS, strict=False):
        last = _panel(ax, layers, extent, points_by_year[year], norm, gridsize)
        ax.set_xlabel(str(year))
    spare = flat[len(YEARS)]
    spare.set_axis_off()
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.05, wspace=0.03, hspace=0.12)
    box = spare.get_position()
    cax = fig.add_axes((box.x0 + 0.02, box.y0 + box.height * 0.45, box.width - 0.04, 0.03))
    fig.colorbar(last, cax=cax, orientation="horizontal", label=COLOUR_LABEL)
    norms["02_polling_places_appendix"] = last.norm
    save(fig, out_dir, "02_polling_places_appendix")
    return norms


def population_raster(x_km: Any, y_km: Any, pop: Any) -> tuple[np.ma.MaskedArray, Extent]:
    """One pixel per 1 km cell; pixels with no cell or population <= 0 are masked."""
    x = np.asarray(x_km).astype(np.int64)
    y = np.asarray(y_km).astype(np.int64)
    values = np.asarray(pop).astype(float)
    if x.size == 0 or not (x.size == y.size == values.size):
        raise ValueError("x_km, y_km and pop must be non-empty and of the same length")
    x_min, x_max = int(x.min()), int(x.max())
    y_min, y_max = int(y.min()), int(y.max())
    grid = np.zeros((y_max - y_min + 1, x_max - x_min + 1))
    grid[y - y_min, x - x_min] = values
    masked = np.ma.masked_less_equal(grid, 0)
    return masked, (x_min, x_max + 1, y_min, y_max + 1)


def population(layers: Layers, cells: pl.DataFrame, out_dir: Path) -> LogNorm:
    """Figure 3: 2022 population per 1 km cell on a log scale, with land-tenure outlines."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    _background(ax, layers, extent, full=True)
    raster, raster_extent = population_raster(
        cells["x_km"].to_numpy(), cells["y_km"].to_numpy(), cells["pop_2022"].to_numpy()
    )
    norm = _colour_norm(int(raster.max()) if raster.count() else 1)
    image = ax.imshow(
        raster,
        origin="lower",
        extent=raster_extent,
        interpolation="nearest",
        cmap=POP_CMAP,
        norm=norm,
        zorder=1.5,  # above the background fills (1), below the outlines (2)
    )
    before = len(ax.collections)
    for layer, colour in TENURE:
        add_outlines(ax, _geoms(layers, layer), colour, TENURE_WIDTH)
    # thousands of tenure polygons as vectors would put the PDF over 10 MB
    for collection in ax.collections[before:]:
        collection.set_rasterized(True)
        collection.set_alpha(0.7)
    add_outlines(ax, _geoms(layers, "legal_amazon"), AMAZON_EDGE, AMAZON_WIDTH)
    _setup(ax, extent)
    handles = [
        Line2D([0], [0], color=colour, linewidth=1.0, label=layer) for layer, colour in TENURE
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=6, frameon=True)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    fig.colorbar(image, ax=ax, shrink=0.6, pad=0.01, label=POP_LABEL)
    save(fig, out_dir, "03_population")
    return norm


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


def land_without_voters(layers: Layers, cells: pl.DataFrame, out_dir: Path) -> dict[str, int]:
    """Figure 5: undesignated forest in 2024 by whether anyone lived there in 2022."""
    extent = amazon_extent(layers)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    _background(ax, layers, extent, full=True)
    raster, raster_extent, counts = tenure_classes(
        cells["x_km"].to_numpy(),
        cells["y_km"].to_numpy(),
        cells["pop_2022"].to_numpy(),
        cells["share_undesignated_2024"].to_numpy(),
    )
    colours = [EMPTY_UNDESIGNATED, POPULATED_UNDESIGNATED, POPULATED_OTHER]
    ax.imshow(
        raster,
        origin="lower",
        extent=raster_extent,
        interpolation="nearest",
        cmap=ListedColormap(colours),
        norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], len(colours)),
        zorder=1.5,  # above the background fills (1), below the outlines (2)
    )
    add_outlines(ax, _geoms(layers, "legal_amazon"), AMAZON_EDGE, AMAZON_WIDTH)
    _setup(ax, extent)
    handles = [
        Patch(facecolor=colour, label=f"{label} ({counts[label]:,} cells)")
        for label, colour in zip(TENURE_CLASSES, colours, strict=True)
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=6, frameon=True)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    save(fig, out_dir, "05_land_without_voters")
    return counts
