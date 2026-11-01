# Confirmation

Human-only. Agents may read these folders and must never change them.

- `pap/`: the pre-analysis plan: hypotheses, predicted signs by constituency
  type, the primary outcome, the placebo, and the inference method. Written
  before outcomes are merged with treatment.
- `specs/`: one YAML file per registered specification, copied from
  `specs/TEMPLATE.yaml`. A spec is registered by merging it to main.
- `ledger/`: an append-only record of every confirmation run, written by the
  `confirm-run` workflow (to be added).
- `split.sha256`: the hash of the sealed sample split
  (`research/decisions/0001-split-sample.md`).

A spec runs on a shuffled treatment until the manual `unblind` workflow is
approved. Anything run after unblinding is labelled post-unblinding in the
ledger and the paper.
