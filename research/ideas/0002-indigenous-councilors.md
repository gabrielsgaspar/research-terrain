# 0002: Indigenous councilors and deforestation (the original design)

## Claim

Electing an indigenous councilor changes deforestation in the municipality,
with effects that differ inside and outside indigenous territories and by
alignment with the mayor's coalition.

## Prediction

Legacy result: more deforestation overall, concentrated outside indigenous
territories and when the councilor is not in the mayor's coalition. Under idea
0001 this is a special case: protection where indigenous voters are, displacement
elsewhere.

## Design

Close-election RDD on the within-coalition margin (Novaes 2024) for
municipality-elections with an indigenous candidate near the threshold; grid
outcomes from Hansen et al. forest loss.

## Data needed

The legacy data in `legacy/`, rebuilt from `tse_candidates` with a new
indigenous measure (self-declared race from 2016, named ethnicity in 2024).

## Status

- 2026-11-01: dead as a standalone design (see `research/lessons.md`), kept as
  the comparison for 0001 and as the source of the identity-versus-constituency
  question.

## Log
