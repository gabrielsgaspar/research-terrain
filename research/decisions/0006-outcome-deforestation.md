---
id: "0006"
title: "The outcome: MapBiomas loss of primary vegetation per 1 km cell"
status: accepted
date: 2026-11-04
supersedes: null
---

# 0006: The outcome: MapBiomas loss of primary vegetation per 1 km cell

Date: 2026-11-04. Status: accepted by Gabriel on 2026-11-04, every proposal
unchanged. The MapBiomas acquisition and the outcome build follow from it; decision 0003 fixes where
the rows go (confirmation half only in `sealed/outcomes/`).

## The question

Idea 0001 predicts changes in clearing around strongholds after close wins.
Which product measures clearing, at what unit, and over which years?

## What exists (checked 2026-11-04, metadata and class codes only)

- MapBiomas Collection 10, readable in Earth Engine from project
  `research-500413`:
  - `projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_deforestation_secondary_vegetation_v2`:
    one band per year, `classification_1985` to `classification_2024`, 30 m,
    EPSG:4326. Codes 1 to 7: 1 anthropic, 2 primary vegetation, 3 secondary
    vegetation, **4 loss of primary vegetation**, 5 recovery to secondary
    vegetation, **6 loss of secondary vegetation**, 7 transition noise (to be
    ignored). A loss is confirmed only when the pixel is anthropic in that
    year and the next and natural in the two years before, so **the latest
    year (2024) can change in the next collection**.
  - `.../mapbiomas_brazil_collection10_coverage_v2`: annual land cover,
    1985-2024.
- Aggregation to IBGE's 1 km Albers grid works in Earth Engine: on a test
  tile, the share of each code per cell, computed with `reduceResolution`
  onto the grid of `grid_cells` (`crsTransform` in metres, origin on whole
  km), sums to exactly 1 in every cell. A whole year must be computed as a
  batch export: interactive tiles take about 5.5 hours per year.
- Licence: CC-BY-SA; MapBiomas must be cited.

## Options

| Choice | Options | Decision | Why |
| --- | --- | --- | --- |
| Product | the deforestation and secondary-vegetation map; transitions in the land-cover collection | **Deforestation and secondary vegetation, Collection 10** | MapBiomas already applies the persistence rules that separate clearing from classification noise; land-cover transitions would rebuild them, worse. |
| Main outcome | loss of primary vegetation (code 4); any loss (4 or 6) | **Share of the cell with code 4 in the year** | Primary-forest clearing is what the hypotheses and the policy debate are about; secondary-vegetation loss (6) is a secondary outcome. |
| Unit | 1 km cell; polling-place catchment; municipality | **1 km cell** (`grid_cells`), as exposure (decision 0004) | Same unit as the treatment; catchments and municipalities can be summed from cells. |
| Stored measure | shares of all seven codes per cell and year | **All seven, as shares × 10,000 (`uint16`)** | Keeps denominators (primary forest left, codes 2 and 3) and checks (shares sum to 1) without a second acquisition. |
| Years | 1985-2024 | **2004-2024** | The four years before the first election (2008), for the placebo (kill criterion 2), through the latest year. Terms after the 2024 election (2025-2028) are not out yet; 2024 is provisional (above). |
| Outcome window | per year; the four term years summed | **Each of the four years after an election, and their sum** | The prediction is about the term; years keep event-study plots possible. |

## What follows

1. Acquire: an Earth Engine batch export per year of the seven code shares
   on the `grid_cells` grid to `data/raw/mapbiomas/<date>/` as the acquire
   account; raw holds both halves, like every raw file, and no exploration
   account can read raw.
2. Build: `cell_outcomes`, exploration-half rows to `data/derived/`,
   confirmation-half rows to `sealed/outcomes/` (decision 0003).
3. Then kill criterion 2 (the placebo) on the exploration half.
