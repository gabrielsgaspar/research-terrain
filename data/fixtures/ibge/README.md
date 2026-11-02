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
