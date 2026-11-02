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
