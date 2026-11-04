# IBGE fixtures

The two IBGE spreadsheets are ODS files (a zip holding `content.xml`). Zips
are binary and cannot be fixtures, so these are their `content.xml` files,
trimmed to the header rows and the municipalities used in the other
fixtures. A test makes an ODS from one by zipping it as `content.xml`
together with a `mimetype` entry of
`application/vnd.oasis.opendocument.spreadsheet`.

- `RELATORIO_DTB_BRASIL_2024_MUNICIPIOS.content.xml`: from `DTB_2024.zip`
  (IBGE territorial division, 5,571 municipalities). The header row is not
  the first row; find it by the cell `Código Município Completo`.
- `Municipios_da_Amazonia_Legal_2024.content.xml`: from
  `Municipios_da_Amazonia_Legal_2024.ods` (773 municipalities). Header cell
  `CD_MUN`. A second sheet is a data dictionary.

ODS compresses repeated cells: a cell with `table:number-columns-repeated`
stands for that many identical cells, and empty trailing cells can repeat
thousands of times. Parsers must expand the attribute and cap it.

Kept municipalities include Boa Esperança do Norte (MT, `5101837`), created
after 2020, which a community crosswalk lacks.

## Localities and urbanized areas (2022)

- `BR_localidades_2022_sample.csv`: every row of IBGE's Localidades do
  Brasil 2022 for the two polling-place fixture towns (IBGE 1507706, TSE
  05533; IBGE 1507979, TSE 04367): 25 localities, categories Cidade,
  Povoado, Outras Localidades and Localidade Indígena. The real file is a
  GeoPackage (SQLite) with a table `BR_localidades_2022`; tests write these
  rows into an SQLite file of that name with `sqlite3`.
- `AreasUrbanizadas2022_sample.geojson`: the 20 urbanized-area polygons
  within about 1 km of those towns' polling places and seats (14 Área
  urbanizada, 6 Loteamento vazio), simplified to 0.00003 degrees. Properties
  `Tipo` and `Densidade` as in the real shapefile. Tests write them to a
  shapefile with pyshp and zip it.

Classified with the rules in task 09, the 2024 fixture's 18 polling places
are 5 seat, 3 town, 1 rural and 9 dispersed; the 2008 Hidalgo stations of
town 04367 are 9 seat, 1 rural and 4 dispersed.

## Census grid and municipal boundaries

Cut from the real files for the same two fixture towns: every 1 km cell
whose centre lies within 2 km of a polling place of TSE 05533 / IBGE 1507706
(2024, 18 places) or TSE 04367 / IBGE 1507979 (Hidalgo 2008, 14 stations).
GeoJSON with coordinates rounded to 6 decimals (boundaries: 5, simplified to
0.002 degrees); tests write each to a zipped shapefile with pyshp, like the
real download.

| File | Source | Fields kept | Features |
| --- | --- | --- | --- |
| `BR1KM_2022_sample.geojson` | `BR1KM_20251002.zip` (`BR1KM.shp`) | `nome_1KM`, `QUADRANTE`, `TOTAL`, `TOTAL_DOM` | 263 cells (182 and 81 by town), 117 with no population, 32,513 people; tiles `ID_73`, `ID_75` |
| `grade_2010_sample.geojson` | `grade_id73.zip`, `grade_id75.zip` | `ID_UNICO`, `nome_1KM`, `MASC`, `FEM`, `POP`, `DOM_OCU` | 623 rows (248 1 km cells, 375 200 m cells) whose `nome_1KM` is one of the 263, 26,432 people |
| `BR_Municipios_2024_sample.geojson` | `BR_Municipios_2024.zip` | all 15 (`CD_MUN`, `NM_MUN`, ..., `AREA_KM2`) | 2: 1507706 São Sebastião da Boa Vista, 1507979 Terra Santa |

The 2010 file's other fields (`QUADRANTE`, `nome_5KM` ... `nome_500KM`,
`Shape_Leng`, `Shape_Area`) are dropped to keep the fixture under 200 KB.

Cell names, in IBGE's Albers equal-area projection (`+proj=aea +lat_0=-12
+lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 +y_0=10000000 +ellps=GRS80`):

- `1KME4717N11118`: the 1 km cell whose **lower-left** corner is at easting
  4,717 km, northing 11,118 km. Same names in 2010 and 2022.
- `200ME47210N111032`: the 200 m cell whose **top-left** corner is at
  4,721.0 km, 11,103.2 km (hundreds of metres). Every 200 m cell lies inside
  its `nome_1KM`; aggregate on `nome_1KM`, never by parsing `ID_UNICO`.

Polygons are stored in SIRGAS 2000 degrees. All the real files declare
UTF-8 (`.cpg`) and decode strictly as UTF-8.
