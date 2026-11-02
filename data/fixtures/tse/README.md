# TSE fixtures

Small cuts of real TSE files, for tests. Cut on 2026-11-02 from
`https://cdn.tse.jus.br/estatistica/sead/odsele/` (the `*_BRASIL.csv` member
where a zip has one; otherwise its single CSV).

## What each file contains

- `consulta_cand_<year>_sample.csv`, 2000 to 2024: about 30 candidates from one
  Pará municipality (councilors elected and not, mayors, vice-mayors), up to
  three supplementary-election rows, and up to four candidates who
  self-declared as Indigenous (from 2016).
- `consulta_cand_complementar_<2020|2024>_sample.csv`: the complementary rows
  for the same candidates (joined on `SQ_CANDIDATO`), including two named
  Indigenous ethnicities in 2024.
- `votacao_candidato_munzona_<2000|2024>_sample.csv`: votes for the same
  town's candidates by zone, plus two rows for candidates not in the
  candidate fixture (to test unmatched rows).
- `votacao_partido_munzona_`, `detalhe_votacao_munzona_` (turnout) and
  `consulta_coligacao_<2000|2024>_sample.csv`: every row for the same town.
- `votacao_secao_<2008|2024>_PA_sample.csv`: two sections of the 2008 and 2024
  fixture towns, every office and every number voted for.
- `eleitorado_local_votacao_<2012|2024>_sample.csv`: 40 first-round sections
  of the 2012 and 2024 fixture towns, with polling place and coordinates.

The fixture towns (all in Pará) are, by year: 2000 `05436`, 2004 `05835`,
2008 `04367`, 2012 `04243`, 2016 `05410`, 2020 `04448`, 2024 `05533`.

## Byte-for-byte format, except identities

Encoding Latin-1, `;` separator, CRLF line endings, the TSE's own quoting
(strings quoted, many numbers not). `.gitattributes` keeps git from changing
any of this.

Personal data are replaced, because this repository is public: names
(`CANDIDATO 0001`, `URNA 0001`), CPF, voter-ID, protocol and process numbers
(zero-padded row numbers), e-mails (`candidatoNNNN@example.com`), polling
places' phone numbers, birth day and month (set to 1 July; the year is kept),
names in `NM_VOTAVEL` (except blank and null votes), and `SQ_CANDIDATO` /
`SQ_SUBSTITUIDO`. The SQ remapping is the same function in every file, keyed
on (year, municipality, SQ) before 2012 and (year, SQ) from 2012, so
candidates, results, sections and complementary rows still join exactly as
the real files do. Missing-value codes (`#NE`, `#NE#`, `#NULO`, `#NULO#`, `-1`, `-3`,
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

## Keys and joins (checked on the full files, 2026-11-02)

- **A candidacy is identified by (`ANO_ELEICAO`, `CD_ELEICAO`, `SG_UE`,
  `SQ_CANDIDATO`).** Before 2012, `SQ_CANDIDATO` is a sequence within each
  municipality: (`CD_ELEICAO`, `SQ_CANDIDATO`) repeats about 400,000 times in
  2000. From 2012 it is unique nationally. (`SG_UE`, `CD_CARGO`,
  `NR_CANDIDATO`) is not unique in any year (substitutions).
- **Results join to candidates on that key.** All results rows match a
  candidacy except 3 SQs in 2000, 140 in 2008 and 4 in 2012.
- **Section votes carry `SQ_CANDIDATO` only from 2024.** Earlier, match on
  (`SG_UE`, `CD_CARGO`, `NR_TURNO`, `NR_VOTAVEL`) through the results file.
  Numbers 95, 96 and 97 are blank, null and annulled votes.
- **Totals agree across files.** In Pará, summing section votes gives exactly
  the results file's votes for every candidate in 2008 (11,488) and 2024
  (15,763); candidate votes match the turnout file's valid nominal votes in
  287/287 municipality-office-rounds in 2008 and 286/290 in 2024.
- **Election type labels change.** Results files say `ELEIÇÃO
  EXTRAORDINÁRIA` from 2016 where candidate files say `ELEIÇÃO SUPLEMENTAR`;
  use `CD_TIPO_ELEICAO`, never the label. Office labels change case
  (`Prefeito` vs `PREFEITO`); use `CD_CARGO`.
- **Some columns appear only in some years.** For example, 2008 results have
  `QT_VOTOS_NOMINAIS` but no `QT_VOTOS_NOMINAIS_VALIDOS`.

## Geography (checked on Pará)

| Year | Section votes have polling-place ID | Polling-place coordinates |
| --- | --- | --- |
| 2000 | no (`-3`), and only 93 of 143 municipalities | none |
| 2004 | yes | none (TSE file starts 2010; Hidalgo starts 2006) |
| 2008 | yes | Hidalgo: 4,699 of 4,713 polling places |
| 2012-2020 | yes | TSE for 77-92% of rows, Hidalgo for the rest |
| 2024 | yes | TSE: 5,225 of 5,727; Hidalgo: 5,604 of 5,727 |

So the stronghold design can use the 2008, 2012, 2016, 2020 and 2024
elections.
