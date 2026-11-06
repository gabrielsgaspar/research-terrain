# Figure style

Every paper figure uses one style, implemented in `src/terrain/style.py`
(imported as `terrain.style`) and tested in `tests/test_figure_style.py`. A
figure calls `style.configure()` once, draws with the constants and helpers
below, and saves only with `style.save_png`. If a figure needs something this
file does not cover, add it to the module and to this file first.

The module lives under `src/terrain/` rather than `figures/` because the
drawing code (`terrain.figures`) and the tests import it, and only the
`terrain` package is importable from there.

## Output

- **PNG only**, 300 dpi, white background, tight bounding box: `save_png(fig,
  path)`, which refuses any other suffix. No figure calls `savefig` itself.
- Sizes (inches): `WIDE` 8 × 4.53, `TALL` 8 × 6.8, `SQUARE` 7.2 × 7.2. Maps use
  the same sizes as every other figure; a grid of two rows of three Legal
  Amazon maps uses `MAP_GRID` 8 × 5.6, the height at which the maps fill
  their panels.

## Typography

- Latin Modern Roman, math in Computer Modern, all text black.
- Base 7.5 pt; titles 8.5 pt regular; axis labels 7.5; ticks 6.5; legends 6.0
  without a frame.
- Lookup, in order: an installed Latin Modern Roman; TinyTeX or MiKTeX through
  `kpsewhich`; `/usr/share/texmf/fonts/opentype/public/lm/` (the Ubuntu
  package `fonts-lmodern`, installed by `figures-run`); STIX as the last
  resort, with a warning, so a fallback shows in the logs.

## Numbers

- One formatter, `thousands`: whole numbers with a comma between thousands
  (1, 100, 1,000, 10,000, 1,234,567). Never `10^n`, scientific notation or
  `k`/`M` abbreviations, in ticks, labels, annotations or notes.
- Shares use `percent`: a fraction as a whole percent, no decimals (0%, 10%,
  25%, 100%). Colour bars of shares pass `formatter=PERCENT` to
  `bottom_colorbar`; every other colour bar keeps `thousands`.
- Log scales tick at powers of ten only (`log_ticks`), without minor ticks.

## Maps

- **Frame:** every map axis has a black 0.7 pt frame and no ticks, tick
  labels or grid (`frame_map`), and keeps an equal aspect.
- **Base layers, on every map:**

| Layer | Colour | Line |
| --- | --- | --- |
| Water (ocean, lakes, wide rivers) | `#dceaf5` (`WATER`) | none |
| Land outside Brazil | `#e6e6e6` (`LAND_OTHER`) | country borders white, 0.4 pt |
| Brazil | white | state borders `#9e9e9e`, 0.3 pt |
| Legal Amazon outline | — | black, 0.8 pt |
| Rivers as lines | `#a9cbe6`, 0.3 pt | — |

- **Insets** sit inside the main map's frame, in a corner, with a margin of
  2% of the axes width on both sides (`inset`), framed like the main map.

## Colour

- **Continuous scales are one hue, light to dark** (`SCALES`):

| Name | For | Light | Dark |
| --- | --- | --- | --- |
| `purple` (default) | anything without its own hue: polling-place density, population (starts mid-light so sparse cells show; Gabriel, 2026-11-05) | `#c3b4d8` | `#54278f` |
| `orange` | indigenous lands | `#fff5eb` | `#7f2704` |
| `green` | forest, including undesignated public forest | `#f7fcf5` | `#00441b` |
| `pink` | settlements | `#fde0ef` | `#8e0152` |

  Settlements are pink, not blue, so they never fade into the light-blue
  water (Gabriel, 2026-11-04).
- **Categories** (areas drawn as kinds, not values): a mid-tone fill at 60%
  opacity with a darker 0.3 pt edge of the same hue (`CATEGORIES`): orange
  `#e6550d` / `#a63603`, pink `#dd3497` / `#7a0177`, green `#31a354` /
  `#006d2c`.
- Panels that are compared share one scale: compute the limits over all
  panels (all years) before drawing.

## Legends

- **At the bottom, spanning the full width** of the map, or of all panels
  together (`bottom_colorbar`, `bottom_legend`, built from the panels'
  combined position, after the layout is fixed).
- Colour bars are horizontal, without an outline, with tick length 0 and
  `thousands` labels (`percent` for shares).
- Category legends are one row, frameless.
