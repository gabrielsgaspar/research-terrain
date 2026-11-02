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

## 2026-11-02: Agents cannot add dependencies (issue #6)
- Tried: the storage-helpers task, whose plan added `google-cloud-storage`.
- Result: the builder stopped as blocked. It installs offline
  (`UV_OFFLINE=1`) from what `uv.lock` lists, so a new package cannot be
  resolved.
- Why: by design. The builder's sandbox has no general network, so an agent
  can never pull a package nobody approved.
- Implication: a person adds dependencies in their own PR before the task;
  tasks and plans never list `pyproject.toml` or `uv.lock`. Rule added to
  AGENTS.md.

## 2026-11-02: What the TSE candidate files actually contain (idea 0001, 0002)
- Tried: downloading and profiling consulta_cand for every municipal election
  from 2000 to 2024, and the complementary files.
- Result: about 3.19 million candidate rows. Race is recorded in municipal
  elections only from 2016 (1,715 Indigenous candidates in 2016, 2,223 in 2020,
  2,578 in 2024); named Indigenous ethnicity exists only in 2024. Each zip
  repeats every row in a BRASIL file; files include later supplementary
  elections; columns change across years; the TSE re-generates files.
- Why: the TSE's schema and collection changed over time.
- Implication: the earlier note "self-declaration from 2014" applies to
  general elections, not municipal ones. Any identity-based analysis of
  councilors starts in 2016. Details in data/fixtures/tse/README.md.

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
