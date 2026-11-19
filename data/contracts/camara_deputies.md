# camara_deputies

The Chamber of Deputies' list of every federal deputy, `deputados.csv` (about 1.4 MB), stored
exactly as fetched, in a new dated folder under the entry's `gcs:` in `data/catalog.yaml`.
Acquired by `pipeline/acquire/camara_deputies.py` (logic in `src/terrain/acquire.py`). Added
by the owner fix "amendments panel v2" for idea 0010 (the author link of `amendments_panel`).

## File

One row per deputy since 1826 (7,890 rows on 2026-11-18). `;`-separated, quoted, UTF-8 with
a byte-order mark. Columns: `uri` (the Chamber's deputy id, as an API URL), `nome`
(parliamentary name), `idLegislaturaInicial`, `idLegislaturaFinal` (first and last
legislature, numbered: 55 is 2015-2019, 56 is 2019-2023, 57 is 2023-2027), `nomeCivil` (civil
name), `cpf`, `siglaSexo`, `urlRedeSocial`, `urlWebsite`, `dataNascimento`,
`dataFalecimento`, `ufNascimento`, `municipioNascimento`.

The acquire checks the header (`uri`, `nome`, `idLegislaturaInicial`, `idLegislaturaFinal`,
`nomeCivil`), at least 7,000 data rows, and the byte count against the server's
Content-Length.

## What the file lacks

- No state of election: `ufNascimento` is the state of birth.
- `cpf` was empty for every deputy of legislatures 55-57 on 2026-11-18, so the file has no
  identifier shared with TSE. The link to TSE is by civil name (see
  `data/contracts/amendments_panel.md`).

## Identifiers

`nome`, `nomeCivil`, `dataNascimento` and `cpf` identify people. Only `nome`, `nomeCivil` and
the two legislature columns are read, and only in memory, by the `amendments_panel` build.
No build writes a name, a CPF or a birth date to a column, a note, a log or an exception
message.
