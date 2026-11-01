# 0001: Split the sample before any outcome data exists

Date: 2026-11-01

## Decision

Legal Amazon municipalities are split once, stratified by state, into an
exploration half and a confirmation half (Anderson and Magruder 2017;
Fafchamps and Labonne 2017). All exploration uses the exploration half. An
idea that survives is registered in `confirm/specs/` and run once on the
confirmation half by the `confirm-run` workflow.

## How

- `scripts/seal_split.py` draws the split with a system random source and no
  seed, so it cannot be regenerated or tuned.
- The full split goes to `gs://research-terrain-sealed/`; the exploration list
  goes to `data/derived/split/`; only the SHA-256 is committed, as
  `confirm/split.sha256`.

## What this does and does not protect

The confirmation half's membership is inferable: it is every municipality not
in the exploration list. The protection is therefore procedural, not secrecy:

1. The split is fixed and hashed before any outcome data exists, so it cannot
   be chosen to fit results.
2. Exploration code reads only exploration municipalities, and reviewers treat
   any other use as a must-fix error.
3. Every confirmation run is logged in `confirm/ledger/`.

A stronger version, to decide before outcomes are built: derived outcome
panels in the main bucket contain exploration rows only, and full panels are
written only to the sealed bucket.

## Cost

About half the statistical power for confirmation. Acceptable if the
feasibility census finds thousands of close pairs; revisit if it does not.
