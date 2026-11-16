# cgu_amendments

The CGU Portal da Transparência amendments zip, `EmendasParlamentares.zip`
(about 47 MB), stored exactly as fetched, in a new dated folder under the
entry's `gcs:` in `data/catalog.yaml`. Acquired by
`pipeline/acquire/cgu_amendments.py` (logic in `src/terrain/acquire.py`).
Campaign 0009, step s3; idea 0009.

## Members

Six CSVs (`;`-separated, quoted, Latin-1 to be confirmed by the build):

- `EmendasParlamentares.csv`: one row per amendment (`Código da Emenda`,
  `Ano da Emenda`, `Tipo de Emenda`, `Código do Autor da Emenda`,
  `Nome do Autor da Emenda`, `Código Município IBGE`, the budget
  classification, and the committed, liquidated and paid values).
- `EmendasParlamentares_PorFavorecido.csv`: `Código da Emenda`,
  `Código do Autor da Emenda`, `Nome do Autor da Emenda`, `Número da emenda`,
  `Tipo de Emenda`, `Ano/Mês`, `Código do Favorecido`, `Favorecido`,
  `Natureza Jurídica`, `Tipo Favorecido`, `UF Favorecido`,
  `Município Favorecido`, `Valor Recebido`.
- `_Convenios`, `_Parcerias`, `_PlanodeTrabalhoParcerias` and
  `_PlanodeTrabalhoTransferenciasEspeciais`: not used.

The build (campaign 0009, step s4) reads the first two. Coverage starts in
2014 according to the CGU guide; the first `Ano/Mês` is unconfirmed and the
build checks it.

## Identifiers

`Código do Favorecido` and `Favorecido` can identify people. They stay in the
raw zip only. No build writes them to derived data, logs or results
(`AGENTS.md`, "Personal identifiers").

## Manifest

`stage: acquire`; `files`: the zip with its SHA-256 and bytes.
