# TSE candidate fixtures

Small cuts of the real TSE candidate files, for tests. Cut on 2026-11-02 from
`https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_<year>.zip`
and `.../consulta_cand_complementar/consulta_cand_complementar_<year>.zip`,
file `*_BRASIL.csv`.

## What each file contains

- `consulta_cand_<year>_sample.csv`, 2000 to 2024: about 30 candidates from one
  Pará municipality (councilors elected and not, mayors, vice-mayors), up to
  three supplementary-election rows, and up to four candidates who
  self-declared as Indigenous (from 2016).
- `consulta_cand_complementar_<2020|2024>_sample.csv`: the complementary rows
  for the same candidates (joined on `SQ_CANDIDATO`), including two named
  Indigenous ethnicities in 2024.

## Byte-for-byte format, except identities

Encoding Latin-1, `;` separator, CRLF line endings, the TSE's own quoting
(strings quoted, many numbers not). `.gitattributes` keeps git from changing
any of this.

Personal data are replaced, because this repository is public: names
(`CANDIDATO 0001`, `URNA 0001`), CPF, voter-ID, protocol and process numbers
(zero-padded row numbers), e-mails (`candidatoNNNN@example.com`), birth day
and month (set to 1 July; the year is kept), and `SQ_CANDIDATO` /
`SQ_SUBSTITUIDO` (remapped consistently, so the main and complementary files
still join). Missing-value codes (`#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`,
`-4`, `NÃO DIVULGÁVEL`) are left as they were.

## Facts about the real files (checked 2026-11-02)

| Year | Columns | Rows (BRASIL) | Supplementary rows | Race recorded | Indigenous |
| --- | --- | --- | --- | --- | --- |
| 2000 | 71 | 399,455 | 0 | no (`#NE`) | 0 |
| 2004 | 63 | 402,157 | 368 | no (`#NE`) | 0 |
| 2008 | 63 | 382,079 | 632 | no (`#NE`) | 0 |
| 2012 | 63 | 483,741 | 673 | no (`#NE#`) | 0 |
| 2016 | 75 | 498,391 | 1,186 | yes | 1,715 |
| 2020 | 50 | 558,804 | 894 | yes | 2,223 |
| 2024 | 50 | 463,885 | 287 | yes | 2,578 |

- Each zip has one CSV per state plus `*_BRASIL.csv`, which repeats every row
  of the state files (the row counts match exactly), and a `leiame.pdf`. Read
  `BRASIL` or the state files, never both.
- Each file includes supplementary elections held later (the 2024 file has a
  2026 election in Melgaço, PA). Keep `CD_ELEICAO`, `CD_TIPO_ELEICAO` and
  `DT_ELEICAO`; never assume one election per year.
- Columns change across years: `NM_EMAIL` becomes `DS_EMAIL` in 2020;
  federation columns appear in 2016; many status columns disappear in 2020
  (some move to the complementary file).
- `SG_UE` is the TSE municipality code, not the IBGE code; a crosswalk is a
  separate dataset.
- The TSE re-generates files: the 2024 zip was modified on 2026-11-01. Acquire
  must record `Last-Modified`, `ETag` and size, and treat a changed file as a
  new version.
- Ethnicity (`CD_ETNIA_INDIGENA`, `DS_ETNIA_INDIGENA`) and `ST_QUILOMBOLA` are
  in the complementary file. They are filled only in 2024; in 2020 the columns
  exist but hold `-3` or `-4`. There is no complementary file before 2020.
