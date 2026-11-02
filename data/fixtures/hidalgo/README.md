# Hidalgo geocoded polling stations fixture

A cut of `geocoded_polling_stations.csv.gz` from release v0.16 of
https://github.com/fdhidalgo/geocode_br_polling_stations, stored uncompressed
(tests gzip it in memory). UTF-8, comma-separated.

Rows: every polling station of the 2008 and 2024 section-vote fixture towns
in those years, plus one row for each municipality used to test the
crosswalk:

- the five Bahia and two Santa Catarina municipalities whose codes a
  community crosswalk had rotated or swapped (TSE `36765`, `36773`, `36790`,
  `36811`, `36820`, `81205`, `81507`);
- name variants such as `04120` and `34118`
  (`data/reference/tse_ibge_name_variants.yaml`);
- Boa Esperança do Norte (TSE `73709`, IBGE `5101837`);
- every candidate-fixture town.

Columns used: `ano`, `cd_localidade_tse` (TSE code, not zero-padded),
`cod_localidade_ibge`, `nr_zona`, `nr_locvot` (polling-place number, joins
the TSE files' `NR_LOCAL_VOTACAO`), `lat`, `long`, `conf_dist_km` (0 when the
coordinate is the TSE's own). `local_id` is not stable across releases.
