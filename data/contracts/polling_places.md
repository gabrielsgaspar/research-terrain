# polling_places

Located polling places of Brazil (every municipality with a TSE code; treatment
side, so not split by half, decision 0003), one Parquet per election year:
`polling_places_2008.parquet`, `_2012`, `_2016`, `_2020` and `_2024`. Built by
`src/terrain/builds/polling_places.py`; written to
`data/derived/polling_places/<hash>/`, where `<hash>` is `content_hash` of the
sorted input SHA-256s, the years and the build code. The build imports no other
data-handling `terrain` module.

## Sources

- TSE polling places (`eleitorado_local_votacao_<year>.zip`, 2012 onward): one
  row per section and round. Only these columns are read: `aa_eleicao`,
  `cd_municipio`, `nr_zona`, `nr_local_votacao`, `nm_local_votacao`,
  `ds_endereco`, `nm_bairro`, `nr_cep`, `nr_latitude`, `nr_longitude`. The phone
  column is never selected. A column a year lacks is filled with null. Not read for 2008.
- Hidalgo v0.16 `geocoded_polling_stations.csv.gz`: `cd_localidade_tse` is
  zero-padded to 5 digits; (`ano`, TSE code, `nr_zona`, `nr_locvot`) is unique.
- Hidalgo v0.16 `panel_ids.csv.gz`: `panel_id` joined on `local_id` (unique in
  both files); stations without a row get a null `panel_id`.
- The built `municipalities` table: `cd_ibge`, `cd_tse` and `uf`. Every
  municipality with a `cd_tse` is kept (Brasília included, if it has places);
  `sg_ue` is the TSE code, `uf` is used for the per-state counts in the notes.

## Columns

One row per (`ano`, `cd_ibge`, `sg_ue`, `nr_zona`, `nr_local_votacao`), sorted by
that key.

| Column | Type | Meaning |
| --- | --- | --- |
| `ano` | int | election year |
| `cd_ibge` | text | 7-digit IBGE code |
| `sg_ue` | text | 5-digit TSE municipality code |
| `nr_zona` | int | electoral zone |
| `nr_local_votacao` | int | polling-place number (Hidalgo's `nr_locvot`) |
| `lat`, `long` | float | coordinates; null when neither source has one |
| `coord_source` | text | `tse` or `hidalgo`; null when there is no coordinate |
| `conf_dist_km` | float | error bound: 0 for TSE, Hidalgo's value otherwise; null with no coordinate |
| `panel_id` | text | Hidalgo panel ID of the matched station; null if none |
| `nm_local_votacao`, `ds_endereco`, `nm_bairro` | text | name, address, neighbourhood |
| `nr_cep` | text | postal code, 8 digits with leading zeros; null when neither source has a valid one |

## nr_cep

- 2012 onward: the TSE file's `NR_CEP`. 2008, and any place whose TSE rows carry
  none: Hidalgo's `nr_cep` of the matched station.
- The text is stripped and left-padded with zeros to 8 digits (`1310100` becomes
  `01310100`). Anything that is not 1-8 digits after stripping (`-1`, empty,
  letters) becomes null. No `_raw` column is kept.
- A place whose TSE rows carry several distinct codes takes the most frequent;
  a tie goes to the smallest. Such places are counted (`two_cep_places`).

## Coordinates

- 2008: Hidalgo only (`coord_source = hidalgo`). The TSE file does not exist.
- Other years: places come from the TSE file. The TSE coordinate is used where
  it is not `-1` (`coord_source = tse`, `conf_dist_km = 0`); otherwise Hidalgo's
  station, matched on (`ano`, TSE code, `nr_zona`, `nr_locvot`). Text that is not
  a number counts as missing.
- A place with several distinct non-missing TSE pairs takes the most frequent
  pair; a tie goes to the smallest (`lat`, `long`). Such places are counted.
- `panel_id` comes through the matched Hidalgo station for every year, including
  places whose coordinate is the TSE's.
- From 2012 the universe is the TSE file. Hidalgo stations with no TSE place are
  dropped; their number is in the notes.

## Unparseable coordinates and other election years

- `-1` is the TSE's only "no coordinate" code in these files (checked
  2012-2024; `-3` and `-4` do not occur there). Values written without a
  leading zero near the equator (`.0075`, `-.0065`) parse normally.
- A coordinate that is present but is not a number (for example a decimal
  comma) becomes null and falls back to Hidalgo. The raw text is not kept: it
  is never useful downstream, and the count is what matters. Counts per year
  and source are in the notes (`tse_unparsed`, `hidalgo_unparsed`), and the
  build stops when they exceed 0.1% of a year's rows, so a format change in a
  whole file cannot hide behind the fallback.
- TSE rows whose `AA_ELEICAO` is not the build year (a later supplementary
  election) are dropped and counted (`tse_other_election_year_rows`); none
  occur in 2012-2024.

## Checks the build enforces

Each raises `BuildError` before that year is written.

- The key is unique.
- Every `cd_ibge` is in the municipalities table (with a `cd_tse`), and the
  table does not repeat a `cd_tse`.
- The share of places without any coordinate is under 5% (parameter
  `max_missing_share`).
- `local_id` is unique in both Hidalgo files, and the Hidalgo station key is
  unique.
- Each downloaded file matches the SHA-256 in its manifest.

## Notes

The manifest `notes` give, per year: rows, share without a coordinate, places
by `coord_source`, places with two TSE pairs, share with a `panel_id`, and
Hidalgo stations missing from the TSE file, the share without an `nr_cep`
(`cep_missing_share`), places with two CEPs (`two_cep_places`) and the number of
places per state (`places_by_state`; values only, no names or addresses). In the
Legal Amazon expect 14 places with two pairs in 2024; the tests cannot check
that, and the national count is not known yet.
