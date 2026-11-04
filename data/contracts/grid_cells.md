# grid_cells

One row per 1 km IBGE grid cell whose centre lies in a Legal Amazon municipality
(5,029,081 cells on the real files), with its coordinates, municipality, 2010 and
2022 population and households, and the share of the cell inside indigenous land,
settlements and undesignated forest in each election year. Built by
`src/terrain/builds/grid_cells.py` (helpers in `src/terrain/grid.py`); written to
`data/derived/grid_cells/<hash>/grid_cells.parquet`, where `<hash>` is
`content_hash` of the sorted input SHA-256s, the years and the source of
`terrain/grid.py`, `terrain/builds/grid_cells.py` and
`terrain/builds/polling_place_tenure.py`.

## Sources

- `ibge_grid_2022`: `BR1KM_20251002.zip`. Only the `.dbf` is read (`nome_1KM`,
  `TOTAL`, `TOTAL_DOM`); the cell comes from its name, not its polygon.
- `ibge_grid_2010`: every tile zip. Only the `.dbf` is read (`nome_1KM`, `POP`,
  `DOM_OCU`).
- `ibge_boundaries_2024`: `BR_Municipios_2024.zip` (`CD_MUN`), SIRGAS 2000 degrees.
- `municipalities`: the 773 rows with `legal_amazon` true.
- `cnfp_public_forests`: the editions of the election years and `CNFP_2025.zip`,
  read with the functions of `terrain.builds.polling_place_tenure`.

## Columns

Sorted by `cd_ibge`, `y_km`, `x_km`.

| Column | Type | Meaning |
| --- | --- | --- |
| `nome_1KM` | text | IBGE cell name; unique |
| `x_km`, `y_km` | int | lower-left corner, Albers km |
| `lon`, `lat` | float | centre, SIRGAS 2000 degrees |
| `cd_ibge` | text | municipality containing the centre |
| `pop_2010`, `dom_2010` | int | 2010 grid people and occupied households |
| `pop_2022`, `dom_2022` | int | 2022 grid people (`TOTAL`) and occupied households (`TOTAL_DOM`) |
| `share_indigenous_<y>` | float | share of the cell inside indigenous land in election year `y`, 0 to 1 |
| `share_settlement_<y>` | float | share inside settlements created by `y`, 0 to 1 |
| `share_undesignated_<y>` | float | share inside undesignated forest in `y`, 0 to 1 |

`<y>` is each of 2008, 2012, 2016, 2020 and 2024: 15 share columns.

## The rules

1. Projection. IBGE's Albers equal-area (`+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2
   +lat_2=-22 +x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m`), with pyproj. A name
   `1KME<e>N<n>` is the cell whose lower-left corner is at easting `e` km and
   northing `n` km; its centre is (`e` + 0.5, `n` + 0.5) and its square is
   `box(e, n, e + 1, n + 1)`.
2. 2022 cells. A name that does not parse stops the build.
3. Municipality. A cell belongs to the Legal Amazon municipality whose polygon
   contains its centre in degrees. Only centres inside longitude -74.5 to -43 and
   latitude -19 to 6 are tested, with a shapely `STRtree`. A cell whose centre is in
   no Legal Amazon municipality is dropped.
4. 2010 population. `POP` and `DOM_OCU` are summed by `nome_1KM` over all tiles,
   whether the row is a 1 km or a 200 m cell. `ID_UNICO` is never parsed. A tile's
   name is not tied to its contents.
5. Tenure shares. Layers and dates follow `polling_place_tenure` (indigenous and
   undesignated from the edition of the year, settlements from the 2025 edition
   created by the year). Polygons are projected to Albers km, repaired with
   `shapely.make_valid` (only polygonal parts kept) and merged with
   `shapely.union_all`, so overlaps count once. For each part of the union, the
   candidate cells are those of its bounding box; a cell's share is the area of its
   square inside the part. Cells of the grid that the layer misses have share 0.
6. Types. Populations and households are integers; shares are stored clipped to 1.

## Checks

The build raises `BuildError` and uploads nothing when:

- a name does not parse or appears twice, or a centre is in more than one municipality;
- a Legal Amazon municipality has no cell;
- a kept cell has no 2010 parent;
- a share is outside [0, 1 + 1e-9];
- for a layer and year, the shares sum (km²) to more than the union's area × 1.001;
- a layer is empty in a year;
- an input's SHA-256 differs from its manifest.

## Notes in the manifest

Per state (first two digits of `cd_ibge`): cells, `pop_2010`, `pop_2022` and the share of
cells with no one in 2022. Per layer and year: cells with a share above 0, the sum of
shares in km² and the union's area in km².

## Caveat

The 2010 grid counts 2-7% fewer people than the 2010 census in every state.
