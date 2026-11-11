# gold_exposure

Two treatment-side tables for idea `research/ideas/0007-gold-and-the-ballot.md` (campaign 0007
step s6): the gold exposure of every Brazilian municipality, fixed by geology and by pre-2000
ANM titles, and the real gold and soybean prices per year. Both are treatment-side data, so
they are not split by half (`research/decisions/0003-confirmation-rows.md`,
`research/decisions/0011-national-scope.md`); explore code reads them only through `restrict`.
Built by `src/terrain/builds/gold_exposure.py`.

Paths come from the catalog entry `gold_exposure`:

- `data/derived/gold_exposure/<hash>/gold_exposure.parquet`
- `data/derived/gold_exposure/<hash>/gold_prices.parquet`

`<hash>` is `content_hash` of the sorted SHA-256s of the seven input files and the source of
`terrain/builds/gold_exposure.py`, `terrain/builds/cell_enforcement.py` (`read_polygons`),
`terrain/builds/polling_place_tenure.py` (`_file`, `_fetch`, the CNFP reader, `is_indigenous`)
and `terrain/grid.py` (the Albers projection). A run whose path already has a manifest is
`unchanged`.

## Sources

- `anm_sigmine` (`data/contracts/anm_sigmine.md`): `sigmine_active.parquet`, active processes
  only; `subs`, `fase`, `ano`, `uf`, `geometry_wkb`.
- `sgb_gold_occurrences`: `sgb_ocorrencias.csv`; `substancias`, `status_economico`,
  `longitude`, `latitude`.
- `gold_price`: `CMO-Historical-Data-Monthly.xlsx` and `CPIAUCSL.csv`.
- `ibge_boundaries_2024`: `BR_Municipios_2024.zip`, keyed by `CD_MUN`.
- `municipalities`: `municipalities.parquet`; `cd_ibge`, `uf`, `legal_amazon` (5,571 rows).
  The two lagoon polygons 4300001 and 4300002 are not in it, so they are dropped.
- `cnfp_public_forests`: `CNFP_2025.zip`; the Indigenous lands (`is_indigenous`). All
  Indigenous polygons are read, with no regional limit (the shared CNFP reader's Legal Amazon
  box is not applied), so the South and the Southeast are covered.

## `gold_exposure.parquet`

One row per `municipalities` row, sorted by `cd_ibge`. Areas are in the Albers projection of
`terrain.grid`, in km². Polygons that are invalid are repaired with `shapely.make_valid` and
only the polygonal parts are kept.

| Column | Type | Meaning |
| --- | --- | --- |
| `cd_ibge` | text | municipality, 7 digits |
| `uf` | text | state |
| `legal_amazon` | bool | in the Legal Amazon |
| `area_km2` | float64 | polygon area, km² |
| `centroid_x_km`, `centroid_y_km` | float64 | polygon centroid, Albers km (for Conley errors) |
| `geo_n_gold` | int64 | gold occurrences in the municipality |
| `geo_gold_per_km2` | float64 | `geo_n_gold / area_km2` |
| `geo_exposed` | bool | `geo_n_gold >= 1` |
| `geo_n_gold_garimpo` | int64 | gold occurrences whose `status_economico` is "Garimpo" |
| `geo_n_gold_indigenous` | int64 | gold occurrences inside an Indigenous land |
| `geo_gold_indigenous_share` | float64 | the last over `geo_n_gold`; null when `geo_n_gold` is 0 |
| `title_n_gold` | int64 | active gold titles whose polygon intersects the municipality |
| `title_n_gold_dated` | int64 | the same, with a valid `ano` |
| `title_n_gold_pre2000` | int64 | the same, with a valid `ano` below 2000 |
| `title_n_garimpo_pre2000` | int64 | pre-2000 gold titles in a garimpo phase |
| `title_gold_pre2000_share` | float64 | area of the union of pre-2000 gold title polygons inside the municipality, over `area_km2` (overlaps count once) |
| `title_garimpo_pre2000_share` | float64 | the same for pre-2000 garimpo titles |
| `title_sand_pre2000_share` | float64 | the same for pre-2000 sand-and-gravel titles (placebo) |
| `title_exposed` | bool | `title_n_gold_pre2000 >= 1` |
| `indigenous_share` | float64 | share of the area inside the union of Indigenous lands |

### Definitions

- **SGB points.** A point is assigned to the municipality polygon (degrees) that contains it
  (`within`, so a point exactly on a boundary is outside). Points with a missing, non-numeric
  or non-finite coordinate, and points outside every polygon, are dropped and counted in the
  notes.
- **Gold occurrence.** `substancias` split on commas, each item stripped, has an item equal to
  "Ouro", compared after casefold and removal of accents (NFKD). "Ouro Preto" does not count.
  "Garimpo" is compared the same way.
- **Gold titles.** `subs` stripped is exactly "OURO", "MINÉRIO DE OURO" or "OURO NATIVO".
  Garimpo titles are gold titles with `fase` "LAVRA GARIMPEIRA" or "REQUERIMENTO DE LAVRA
  GARIMPEIRA". Sand-and-gravel titles have `subs` "AREIA", "AREIA COMUM", "AREIA LAVADA",
  "CASCALHO" or "SAIBRO".
- **Years.** A valid `ano` is an integer from 1900 to 2026. Pre-2000 means a valid `ano`
  below 2000; a title with a missing or invalid year is never pre-2000.
- **Titles without a polygon** are not counted anywhere; they are counted in the notes. A
  title counts in every municipality its polygon intersects (touching counts).

## `gold_prices.parquet`

One row per calendar year in which gold, soybeans and CPI each have 12 months, sorted by
`year`. The sheet "Monthly Prices" is found through `xl/workbook.xml` and its relationships;
the columns are the ones headed "Gold" and "Soybeans" in row 5; months are `YYYYMmm` in column
A; "…" or an empty cell is missing. CPI is `CPIAUCSL.csv` (`observation_date` `YYYY-MM-01`).

One CPI month may be filled. When a year's CPI misses exactly one month and the months on each
side (across a year end too) have values, that month is the geometric mean of the two. This is
for October 2025, which the BLS never published (the 2025 US government shutdown): FRED leaves
it empty, and the fill is 324.654 from September's 324.245 and November's 325.063. Gold and
soybeans are never filled.

| Column | Type | Meaning |
| --- | --- | --- |
| `year` | int64 | calendar year |
| `gold_usd`, `soy_usd` | float64 | annual mean of the monthly nominal prices, US dollars |
| `cpi` | float64 | annual mean of the monthly CPI |
| `gold_real`, `soy_real` | float64 | 2024 dollars: `price × cpi_2024 / cpi` |
| `ln_gold_real`, `ln_soy_real` | float64 | natural logs of the real prices |
| `n_months_gold`, `n_months_soy`, `n_months_cpi` | int64 | months in the mean (always 12) |
| `n_months_cpi_filled` | int64 | CPI months filled as above (0, or 1 for 2025) |

The World Bank changed its gold method in June 2025 and its soybean specification several
times (see the catalog entry `gold_price`); the series is not corrected for that.

## Checks

The build raises `BuildError` before anything is uploaded when:

- a file's SHA-256 differs from its manifest, or an input lacks a column it uses, or the
  workbook lacks the sheet or a header;
- the municipalities table has fewer than 5,571 rows or repeats a code, or a code has no
  polygon in the boundaries, or a polygon has no area;
- the SGB file has fewer than 30,000 rows or fewer than 4,000 gold occurrences;
- the ANM file has fewer than 250,000 rows, or fewer than 9,000 gold titles with `ano` < 2000;
- the CNFP edition has no Indigenous land polygon;
- fewer than 60 price years, any year from 1985 to 2025 missing, 2024 incomplete, or a
  non-positive price or CPI;
- any share is outside [0, 1] by more than 1e-9 (smaller excesses are clipped).

## Upload and manifest

Both files are written locally and checked first, then uploaded create-only, then the caller
writes the manifest. The manifest notes hold:

- the municipalities, and the counts by `uf` of `geo_exposed` and of `title_exposed`;
- the SGB rows and gold occurrences; the points dropped for unusable coordinates and the
  points outside every polygon, each also as gold occurrences only;
- the ANM rows, gold titles, and gold and sand titles without a polygon;
- the polygons repaired (ANM gold and sand titles, Indigenous lands);
- the price years, first to last, and their number.
- the CPI months filled (`cpi_months_filled=2025-10`, or `none`).
