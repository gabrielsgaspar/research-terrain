# figure_layers

Simplified map layers for the paper figures 1-3, so `figures-run` (which reads only
`data/derived/`) can draw them. One Parquet file, `figure_layers.parquet`. Built by
`src/terrain/builds/figure_layers.py`; written to `data/derived/figure_layers/<hash>/`,
where `<hash>` is `content_hash` of the sorted SHA-256s of the input files used and
the source of `figure_layers.py` and of `polling_place_tenure.py` (whose readers and
rules it reuses).

## Sources

- `naturalearth_basemap`: `ne_10m_admin_0_countries.zip`, `ne_10m_ocean.zip`,
  `ne_10m_lakes.zip`, `ne_10m_rivers_lake_centerlines.zip`.
- `ibge_boundaries_2024`: `BR_UF_2024.zip` and `Limites_Amazonia_Legal_2024_shp.zip`.
  `BR_Municipios_2024.zip` is not read, so it is not part of the hash.
- `cnfp_public_forests`: `CNFP_2024_retificado.zip` and `CNFP_2025.zip`.

Shapefiles are read with `pyshp` from the zip, as UTF-8, in longitude/latitude degrees.
Each input file is checked against the SHA-256 in its acquire manifest.

## Columns

Sorted by `layer`, then input order.

| Column | Type | Meaning |
| --- | --- | --- |
| `layer` | text | one of the nine layers below |
| `code` | text | `ADM0_A3` for `country`, `SIGLA_UF` for `state`; null elsewhere |
| `name` | text | `NAME`, `name`, `NM_UF` or `NOME` as in the table; null elsewhere |
| `scalerank` | int | Natural Earth `scalerank` for `lake` and `river`; null elsewhere |
| `geometry` | binary | WKB, 2D, longitude/latitude degrees |

## Layers

`FRAME` is longitude -92 to -26, latitude -57 to 14. `simplify` is
`shapely.simplify(g, tol, preserve_topology=True)` then `shapely.make_valid`; only the
parts of the layer's own dimension are kept (polygons, or lines for `river`), and a
geometry that ends up empty is dropped.

| `layer` | Source | Rows | `code`, `name` | Clip | Tolerance |
| --- | --- | --- | --- | --- | --- |
| `country` | `ne_10m_admin_0_countries` | those meeting `FRAME` | `ADM0_A3`, `NAME` | `FRAME` | 0.01 |
| `ocean` | `ne_10m_ocean` | all | null, null | `FRAME` | 0.01 |
| `lake` | `ne_10m_lakes` | those meeting `FRAME` | null, `name` | `FRAME` | 0.01 |
| `river` | `ne_10m_rivers_lake_centerlines` | those meeting `FRAME` | null, `name` | `FRAME` | 0.01 |
| `state` | `BR_UF_2024` | all | `SIGLA_UF`, `NM_UF` | none | 0.01 |
| `legal_amazon` | `Limites_Amazonia_Legal_2024_shp` | all | null, `NOME` | none | 0.005 |
| `indigenous` | `CNFP_2024_retificado` | `is_indigenous(categoria)` | null, null | none | 0.002 |
| `settlement` | `CNFP_2025` | `is_settlement(categoria)` and `creation_year(anocriacao)` <= 2024 | null, null | none | 0.002 |
| `undesignated` | `CNFP_2024_retificado` | `is_undesignated(tipo)` | null, null | none | 0.002 |

The tenure layers use the functions of `terrain.builds.polling_place_tenure`
(`extract_edition`, `read_cnfp`, `is_indigenous`, `is_settlement`, `is_undesignated`,
`creation_year`), so they are the same polygons as the 2024 layers of that build.
A settlement without a creation year is left out.

## Checks

Each raises `BuildError` before anything is written to the store:

1. every layer is non-empty;
2. `country` contains `BRA`;
3. `state` has exactly 27 rows with distinct codes;
4. `legal_amazon` has one row whose bounds lie within longitude -74 to -43 and latitude
   -18.5 to 5.5;
5. every geometry is valid;
6. no tenure layer loses more than 1% of its polygons as empty after simplifying.

## Manifest notes

Rows per layer; for the tenure layers also the count before simplifying and the number
dropped as empty.
