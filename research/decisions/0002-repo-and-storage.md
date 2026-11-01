# 0002: Public repository, GCS for data, Overleaf for the paper

Date: 2026-11-01

## Decision

- The repository is public. On a free GitHub plan, rulesets and secret push
  protection exist only for public repositories, and standard Actions runners
  are free there. The agent pipeline depends on both.
- Data lives in `gs://research-terrain/data/` (`raw/` write-once, `derived/`,
  `explore/` deleted after 90 days); the sealed split lives in
  `gs://research-terrain-sealed/`. Both buckets enforce public access
  prevention.
- GitHub Actions reach GCP only through Workload Identity Federation, in jobs
  bound to the `data-write`, `analysis` or `unblind` environments, which only
  run from main. Code on a pull request never gets GCP credentials.
- The paper lives in Overleaf, linked as the `overleaf/` submodule. Only the
  pipeline's generated files go in `overleaf/generated/`; people write the rest.

## Consequences

Drafts and ideas are public before the paper circulates. Data and the
confirmation half are not.
