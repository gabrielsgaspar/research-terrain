import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.colors import LogNorm, Normalize
from matplotlib.lines import Line2D

from terrain import style


@pytest.mark.parametrize(
    ("value", "text"),
    [(1, "1"), (100, "100"), (1000, "1,000"), (10000, "10,000"), (1234567, "1,234,567")],
)
def test_thousands(value, text):
    assert style.thousands(value) == text
    assert style.THOUSANDS(value, 0) == text


@pytest.mark.parametrize(
    ("value", "text"), [(0, "0%"), (0.1, "10%"), (0.25, "25%"), (1, "100%"), (0.504, "50%")]
)
def test_percent(value, text):
    assert style.percent(value) == text
    assert style.PERCENT(value, 0) == text


def test_log_ticks_are_powers_of_ten_inside_the_range():
    assert style.log_ticks(1, 27239) == [1, 10, 100, 1000, 10000]
    assert style.log_ticks(3, 950) == [10, 100]
    with pytest.raises(ValueError):
        style.log_ticks(0, 10)


@pytest.mark.parametrize("name", sorted(style.SCALES))
def test_every_scale_runs_light_to_dark(name):
    cmap = style.SCALES[name]
    assert style.luminance(cmap(0.0)) > style.luminance(cmap(1.0))


def test_settlements_are_pink_not_blue():
    assert "blue" not in style.SCALES and "pink" in style.SCALES


def test_font_family_is_a_name():
    assert style.font_family() in (style.FONT_FAMILY, style.FALLBACK_FAMILY)


def test_font_fallback_warns(monkeypatch, tmp_path):
    style.font_family.cache_clear()
    monkeypatch.setattr(style, "_installed", lambda: False)
    monkeypatch.setattr(style, "_kpsewhich_paths", lambda: [])
    monkeypatch.setattr(style, "UBUNTU_LM_DIR", tmp_path / "missing")
    try:
        with pytest.warns(UserWarning, match="fall back"):
            assert style.font_family() == style.FALLBACK_FAMILY
    finally:
        style.font_family.cache_clear()


def test_font_found_does_not_warn(monkeypatch):
    style.font_family.cache_clear()
    monkeypatch.setattr(style, "_installed", lambda: True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert style.font_family() == style.FONT_FAMILY
    finally:
        style.font_family.cache_clear()


def _two_maps():
    style.configure()
    fig, axes = plt.subplots(1, 2, figsize=style.WIDE)
    for ax in axes:
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 8)
        style.frame_map(ax)
    fig.subplots_adjust(bottom=0.2)
    return fig, axes


def test_colorbar_spans_exactly_the_panels():
    fig, axes = _two_maps()
    image = axes[0].imshow(np.array([[1.0, 27239.0]]), norm=LogNorm(1, 27239))
    bar = style.bottom_colorbar(fig, axes, image, "People")
    x0 = min(ax.get_position().x0 for ax in axes)
    x1 = max(ax.get_position().x1 for ax in axes)
    pos = bar.ax.get_position()
    assert pos.x0 == pytest.approx(x0) and pos.x1 == pytest.approx(x1)
    assert pos.y1 < min(ax.get_position().y0 for ax in axes)
    assert [t.get_text() for t in bar.ax.get_xticklabels()] == [
        "1",
        "10",
        "100",
        "1,000",
        "10,000",
    ]
    plt.close(fig)


def test_colorbar_formatter_gives_percent_ticks():
    fig, axes = _two_maps()
    image = axes[0].imshow(np.array([[0.0, 0.3]]), norm=Normalize(0, 0.3))
    bar = style.bottom_colorbar(fig, axes, image, "Share", formatter=style.PERCENT)
    fig.canvas.draw()
    labels = [t.get_text() for t in bar.ax.get_xticklabels() if t.get_text()]
    assert labels
    assert all(text.endswith("%") for text in labels)
    assert labels[0] == "0%"
    plt.close(fig)


def test_legend_is_one_row_under_the_panels():
    fig, axes = _two_maps()
    handles = [Line2D([0], [0], label=n) for n in ("a", "b", "c")]
    legend = style.bottom_legend(fig, axes, handles)
    assert legend._ncols == 3 and not legend.get_frame_on()
    plt.close(fig)


def test_inset_lies_inside_the_main_axes():
    fig, axes = _two_maps()
    child = style.inset(axes[1], 0.25, 0.25)
    fig.canvas.draw()
    outer = axes[1].get_window_extent()
    inner = child.get_window_extent()
    assert outer.x0 < inner.x0 < inner.x1 < outer.x1
    assert outer.y0 < inner.y0 < inner.y1 < outer.y1
    assert inner.width <= outer.width * 0.25 + 1e-6
    assert inner.height <= outer.height * 0.25 + 1e-6
    margin = outer.x1 - inner.x1
    assert margin == pytest.approx(outer.width * 0.02, rel=1e-3)
    assert inner.y0 - outer.y0 == pytest.approx(margin, rel=1e-3)
    plt.close(fig)


def test_save_png_only(tmp_path):
    fig, _ = _two_maps()
    out = style.save_png(fig, tmp_path / "x.png")
    assert out.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    fig, _ = _two_maps()
    with pytest.raises(ValueError, match="PNG only"):
        style.save_png(fig, Path(tmp_path / "x.pdf"))
    plt.close(fig)
