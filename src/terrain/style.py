"""The one visual style of every paper figure. Documented in figures/STYLE.md.

Typography and sizes follow the songs project's paper style; map layers,
colour scales, legends and saving follow handoff 2 (2026-11-04). Figures call
`configure()` once, draw with the constants and helpers here, and save only
through `save_png`.
"""

from __future__ import annotations

import shutil
import subprocess
import warnings
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_rgb  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter  # noqa: E402

# --- Typography and sizes

FONT_FAMILY = "Latin Modern Roman"
FALLBACK_FAMILY = "STIXGeneral"
TEXT = "black"
LATIN_MODERN_FILES = (
    "lmroman10-regular.otf",
    "lmroman10-bold.otf",
    "lmroman10-italic.otf",
    "lmroman10-bolditalic.otf",
)
# The Ubuntu package fonts-lmodern, installed on the figures-run runner.
UBUNTU_LM_DIR = Path("/usr/share/texmf/fonts/opentype/public/lm")

DPI = 300
WIDE = (8.0, 4.53)
TALL = (8.0, 6.8)
SQUARE = (7.2, 7.2)
MAP_GRID = (8.0, 5.6)  # two rows of three Legal Amazon maps, without blank bands
LINE_WIDTH = 0.7  # axes frames

RCPARAMS: dict[str, Any] = {
    "font.size": 7.5,
    "axes.titlesize": 8.5,
    "axes.titleweight": "regular",
    "axes.labelsize": 7.5,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.0,
    "legend.frameon": False,
    "text.color": TEXT,
    "axes.labelcolor": TEXT,
    "axes.titlecolor": TEXT,
    "xtick.color": TEXT,
    "ytick.color": TEXT,
    "legend.labelcolor": TEXT,
    "axes.edgecolor": TEXT,
    "axes.linewidth": LINE_WIDTH,
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "savefig.facecolor": "white",
    "axes.formatter.useoffset": False,
    "axes.formatter.use_mathtext": False,
}


def _registers(paths: Sequence[Path]) -> bool:
    for path in paths:
        if path.is_file():
            font_manager.fontManager.addfont(str(path))
    return _installed()


def _installed() -> bool:
    try:
        font_manager.findfont(FONT_FAMILY, fallback_to_default=False)
    except ValueError:
        return False
    return True


def _kpsewhich_paths() -> list[Path]:
    exe = shutil.which("kpsewhich")
    if not exe:
        return []
    found = []
    for name in LATIN_MODERN_FILES:
        result = subprocess.run([exe, name], check=False, capture_output=True, text=True)
        lines = result.stdout.strip().splitlines()
        if result.returncode == 0 and lines:
            found.append(Path(lines[0]))
    return found


@cache
def font_family() -> str:
    """Latin Modern Roman if it can be found, else STIX with a warning.

    Order: an installed font; TinyTeX or MiKTeX through `kpsewhich`; the Ubuntu
    package folder (the runner); STIX as the last resort.
    """
    if _installed() or _registers(_kpsewhich_paths()):
        return FONT_FAMILY
    if _registers([UBUNTU_LM_DIR / name for name in LATIN_MODERN_FILES]):
        return FONT_FAMILY
    warnings.warn(
        f"{FONT_FAMILY} not found; figures fall back to {FALLBACK_FAMILY}. "
        "Install fonts-lmodern (Ubuntu) or the TeX lm package.",
        stacklevel=2,
    )
    return FALLBACK_FAMILY


def configure() -> Any:
    """Apply the paper style to matplotlib and return pyplot."""
    family = font_family()
    plt.rcParams.update(
        {
            **RCPARAMS,
            "font.family": family,
            "mathtext.fontset": "cm" if family == FONT_FAMILY else "stix",
        }
    )
    return plt


# --- Numbers


def thousands(value: float) -> str:
    """1, 100, 1,000, 10,000: whole numbers with a comma between thousands."""
    return f"{value:,.0f}"


THOUSANDS = FuncFormatter(lambda value, _pos: thousands(value))


def log_ticks(vmin: float, vmax: float) -> list[float]:
    """Powers of ten from the first at or above `vmin` to the last at or below `vmax`."""
    if vmin <= 0 or vmax < vmin:
        raise ValueError("log ticks need 0 < vmin <= vmax")
    ticks, tick = [], 1.0
    while tick > vmin:
        tick /= 10
    while tick <= vmax * (1 + 1e-12):
        if tick >= vmin * (1 - 1e-12):
            ticks.append(tick)
        tick *= 10
    return ticks


# --- Colours

# Base layers of every map.
WATER = "#dceaf5"
LAND_OTHER = "#e6e6e6"
BRAZIL = "white"
COUNTRY_BORDER = ("white", 0.4)
STATE_BORDER = ("#9e9e9e", 0.3)
AMAZON_BORDER = (TEXT, 0.8)
RIVER = ("#a9cbe6", 0.3)

# Sequential scales, one hue, light to dark. Settlements are pink, not blue,
# so they never fade into the water (Gabriel, 2026-11-04).
SCALE_ENDS = {
    "purple": ("#f2f0f7", "#54278f"),  # default, including polling places and population
    "orange": ("#fff5eb", "#7f2704"),  # indigenous lands
    "green": ("#f7fcf5", "#00441b"),  # forest, including undesignated public forest
    "pink": ("#fde0ef", "#8e0152"),  # settlements
}
SCALES = {
    name: LinearSegmentedColormap.from_list(f"terrain_{name}", ends)
    for name, ends in SCALE_ENDS.items()
}
DEFAULT_SCALE = "purple"

# Areas drawn as categories: a mid-tone fill at 60% opacity, a darker edge.
CATEGORY_ALPHA = 0.6
CATEGORY_EDGE_WIDTH = 0.3
CATEGORIES = {
    "orange": ("#e6550d", "#a63603"),
    "pink": ("#dd3497", "#7a0177"),
    "green": ("#31a354", "#006d2c"),
}


def luminance(colour: Any) -> float:
    """Relative luminance (sRGB, WCAG weights) of a colour."""

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in to_rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# --- Maps, legends, insets


def frame_map(ax: Any) -> None:
    """A map axis: equal aspect, a black frame, no ticks, labels or grid."""
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(TEXT)
        spine.set_linewidth(LINE_WIDTH)


def _union(axes: Sequence[Any]) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the axes' combined position, in figure fractions."""
    boxes = [ax.get_position() for ax in axes]
    return (
        min(b.x0 for b in boxes),
        min(b.y0 for b in boxes),
        max(b.x1 for b in boxes),
        max(b.y1 for b in boxes),
    )


def bottom_colorbar(
    fig: Any,
    axes: Sequence[Any],
    mappable: Any,
    label: str,
    *,
    height: float = 0.022,
    gap: float = 0.05,
) -> Any:
    """A horizontal colour bar under `axes`, exactly as wide as all of them together.

    Call after the layout is fixed (`subplots_adjust`), since it reads the axes'
    positions. Log scales tick at powers of ten; every tick uses `thousands`.
    """
    fig.canvas.draw()  # apply equal-aspect positions before reading them
    x0, y0, x1, _ = _union(axes)
    cax = fig.add_axes((x0, y0 - gap - height, x1 - x0, height))
    bar = fig.colorbar(mappable, cax=cax, orientation="horizontal")
    norm = mappable.norm
    if isinstance(norm, LogNorm):
        bar.ax.xaxis.set_major_locator(FixedLocator(log_ticks(norm.vmin, norm.vmax)))
    bar.ax.xaxis.set_major_formatter(THOUSANDS)
    bar.minorticks_off()
    bar.outline.set_visible(False)
    bar.ax.tick_params(length=0)
    bar.set_label(label)
    return bar


def bottom_legend(
    fig: Any, axes: Sequence[Any], handles: Sequence[Any], *, gap: float = 0.01
) -> Any:
    """A one-row, frameless category legend under `axes`, spanning their width."""
    fig.canvas.draw()
    x0, y0, x1, _ = _union(axes)
    return fig.legend(
        handles=list(handles),
        loc="upper left",
        bbox_to_anchor=(x0, y0 - gap, x1 - x0, 0.0),
        bbox_transform=fig.transFigure,
        ncol=len(handles),
        mode="expand",
        frameon=False,
        borderaxespad=0.0,
    )


def inset(
    ax: Any, width: float, height: float, *, corner: str = "lower right", margin: float = 0.02
) -> Any:
    """An inset map inside `ax`, at most `width` × `height` as fractions of `ax`, framed.

    The margin is `margin` of the axes width on both sides, so it looks equal. The
    inset keeps its map's aspect, so it may be narrower or lower than the box.
    """
    fig = ax.figure
    fig.canvas.draw()
    box = ax.get_window_extent()
    mx = margin
    my = margin * box.width / box.height
    x = mx if "left" in corner else 1 - mx - width
    y = my if "lower" in corner else 1 - my - height
    child = ax.inset_axes((x, y, width, height))
    frame_map(child)
    # an equal-aspect map shrinks inside its box; pin it to the corner
    child.set_anchor(
        {"lower right": "SE", "lower left": "SW", "upper right": "NE"}.get(corner, "NW")
    )
    return child


# --- Saving


def save_png(fig: Any, path: Path) -> Path:
    """Save `fig` as a 300-dpi PNG with a white background and a tight box; close it."""
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise ValueError(f"figures are saved as PNG only, not {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white", bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    return path
