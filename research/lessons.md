# Lessons

A dated log of what was tried, what happened and what it means. Every
exploration adds an entry, including failures. Newest first.

Format:

```
## YYYY-MM-DD: short title (idea NNNN, issue #N)
- Tried: what was done, on which data and half.
- Result: what came out, with the key number.
- Why: the best explanation.
- Implication: what changes because of it.
```

## 2026-11-01: The original design's headline effect is implausibly large (idea 0002)
- Tried: reading the legacy paper's close-election RDD on indigenous councilors.
- Result: the estimate of 0.003 against a mean of about 0.004 is roughly a 75%
  rise in yearly deforestation (the Poisson estimate of 0.55 implies the same),
  from one councilor on a council of nine or more; 139 municipality-elections.
- Why: likely confounding or a specification artefact, and grid-cell
  observations overstate precision when treatment varies by municipality.
- Implication: any rerun clusters at the municipality, aggregates to the
  municipality as a check, and reports a density test.

## 2026-11-01: Name-based indigenous classification is not usable (idea 0002)
- Tried: reviewing the legacy name classifier.
- Result: it mostly finds candidates who use an ethnonym as a political
  surname, a mobilised and movement-aligned subset; Tupi-derived given names
  produce false positives.
- Why: most indigenous Brazilians have Portuguese names.
- Implication: identity uses TSE self-declaration (from 2014) and the 2024
  ethnicity declaration, with switchers flagged; constituency is measured
  separately from polling-station votes.
