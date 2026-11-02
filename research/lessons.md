# Lessons

A dated log of what was tried, what happened and what it means. Every
exploration adds an entry, including failures. Newest first.

This log is for research and data findings. Lessons about the agent
pipeline, GitHub and GCP live in `harness/LESSONS.md`.

Format:

```
## YYYY-MM-DD: short title (idea NNNN, issue #N)
- Tried: what was done, on which data and half.
- Result: what came out, with the key number.
- Why: the best explanation.
- Implication: what changes because of it.
```

## 2026-11-02: The 2008 candidate file is missing candidacies that have votes
- Tried: building candidate votes for 2000-2024 against the candidates table.
- Result: 1,458 of the 336,668 candidacies with votes in 2008 (0.43%) are
  not in the 2008 candidate file, 204 of them in Pará; 311 are in
  municipalities with no candidate rows at all. Other years: 67 (2000), 126
  (2004), 4 (2012), none from 2016. Votes agree with turnout in 11,305 of
  11,306 municipality-office-rounds in 2008, so the results file is complete.
- Why: gaps in the TSE's 2008 consulta_cand, not a join error (the same SQs
  are not under another election code).
- Implication: for 2008, candidate attributes (party, race, birth date) are
  missing for those candidacies; vote margins are not, because the results
  file carries party and number. Strongholds for 2008 should take party from
  the results file, and any 2008 analysis using candidate attributes must
  report this gap.

## 2026-11-02: Strongholds can use 2008-2024, not 2000-2024 (idea 0001)
- Tried: profiling TSE section votes, TSE polling places and the Hidalgo
  geocodes for Pará, 2000-2024.
- Result: 2000 section votes have no polling-place IDs and cover 93 of 143
  municipalities; 2004 has IDs but no coordinates anywhere (TSE coordinates
  start 2010, Hidalgo 2006). From 2008, 99.7% (2008) and 97.9% (2024) of
  section polling places have coordinates. Section sums equal the results
  file exactly for every candidate in 2008 and 2024.
- Why: the TSE's section files and polling-place register changed over time.
- Implication: the design uses five elections: 2008, 2012, 2016, 2020, 2024.
  2004 is still usable for vote margins without geography.

## 2026-11-02: A community TSE-IBGE crosswalk had seven wrong codes
- Tried: checking the widely used betafcc crosswalk against IBGE's DTB 2024
  names, a name match within each state, and the Hidalgo pairs.
- Result: five Bahia municipalities were rotated and two in Santa Catarina
  swapped, and Boa Esperança do Norte (MT, Legal Amazon) was missing. The
  Hidalgo pairs agree with the name match in every disputed case and cover
  every TSE code in the candidate files; 14 pairs differ only in spelling or
  a rename.
- Why: hand-maintained tables drift; nothing checked the names.
- Implication: the crosswalk is built from Hidalgo's pairs, every pair is
  checked by name, and the 14 known variants are a reviewed list in
  `data/reference/tse_ibge_name_variants.yaml`. Any other mismatch fails.

## 2026-11-02: Before 2012, SQ_CANDIDATO is not a national ID
- Tried: checking which key identifies a candidacy in each candidate file.
- Result: (election, SQ_CANDIDATO) repeats about 400,000 times in 2000;
  (election, municipality, SQ_CANDIDATO) is unique in every year.
- Why: until 2008 the TSE numbered candidates within each municipality.
- Implication: every join and uniqueness check uses (year, election,
  municipality, SQ_CANDIDATO). Task draft 03 had the wrong key and was fixed
  before filing.

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
