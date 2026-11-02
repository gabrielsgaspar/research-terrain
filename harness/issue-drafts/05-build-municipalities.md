# Task: build the municipalities table and the TSE-IBGE crosswalk

## Goal

One table of Brazilian municipalities with both the IBGE and the TSE code,
the IBGE and TSE names, and a Legal Amazon flag, verified so that a wrong
pair cannot get through. Every later join between electoral and
geographical data uses it.

## Idea

Infrastructure for `research/ideas/0001-electoral-strongholds.md`. Read
`data/fixtures/ibge/README.md`, `data/fixtures/hidalgo/README.md` and
`data/reference/tse_ibge_name_variants.yaml` first.

## In scope

- `src/terrain/ods.py`: read an ODS sheet into rows with `zipfile` and
  `xml.etree.ElementTree` (no new dependency), expanding
  `table:number-columns-repeated` with a cap.
- `src/terrain/builds/municipalities.py` and
  `pipeline/build/municipalities.py`, following `pipeline/README.md`.
  Inputs, from `data/manifests/acquire/`: `ibge_municipalities` (DTB 2024
  and the Legal Amazon list), `polling_stations_geocoded` (TSE-IBGE pairs)
  and `tse_candidates` (the TSE name of each municipality, latest year).
- Output `data/derived/municipalities/<hash>/municipalities.parquet`, one row
  per IBGE municipality: `cd_ibge` (7 digits, string), `cd_tse` (5 digits,
  zero-padded string, null if the municipality never appears in TSE data),
  `uf`, `name_ibge`, `name_tse`, `legal_amazon` (bool), `name_check`
  (`exact` or `variant`). Also write `legal_amazon.csv` (`code_ibge,uf`) in
  the same folder, the input to `scripts/seal_split.py`.
- Pairs come from Hidalgo's `cd_localidade_tse` and `cod_localidade_ibge`.
  Each pair is checked by comparing names after upper-casing, removing
  accents and treating apostrophes and hyphens as spaces. A pair that fails
  is accepted only if it is listed in
  `data/reference/tse_ibge_name_variants.yaml` with the same codes.
- Checks the build enforces before writing (each raises with a clear
  message): the pairs are one-to-one; every IBGE code is in DTB 2024; every
  TSE code that appears in the candidate files has a pair; every Legal
  Amazon municipality is in the table; every name mismatch is a listed
  variant.
- `data/contracts/municipalities.md`: columns, types, sources, checks.

## Out of scope

- Fixing or extending `data/reference/` (people maintain it).
- Any other build. `pyproject.toml`, `uv.lock`, workflows,
  `data/manifests/`, `data/fixtures/`.

## Done when

1. From the fixtures, the build maps Boa Esperança do Norte (TSE `73709`)
   to `5101837` with `legal_amazon` true.
2. The five Bahia and two Santa Catarina test municipalities map to the
   codes in the Hidalgo fixture, and their names match exactly.
3. A test that swaps two pairs in the input makes the build raise on the
   name check; a test with an unlisted variant raises; a listed variant
   passes with `name_check = variant`.
4. Tests show the one-to-one, coverage and Legal Amazon checks each raise
   on broken input.
5. `legal_amazon.csv` has exactly the columns `code_ibge,uf`, and
   `scripts/seal_split.py`'s reader accepts it.
6. Building twice with the same inputs reports `unchanged`.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`
   pass.
