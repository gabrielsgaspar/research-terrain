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

## 2026-11-04: Land-tenure sources: the public-forest register replaces FUNAI and INCRA (idea 0001)
- Tried: finding official downloads for indigenous lands (FUNAI),
  settlements (INCRA) and undesignated public forests (CNFP).
- Result: FUNAI's GeoServer returned 503 on every request; INCRA's download
  server no longer resolves and its portal redirects to the home page. The
  Forest Service's register (CNFP) is downloadable for 2008-2025 and holds all
  three: indigenous lands (TI, 664 polygons in 2025), settlements (2025 only
  for conventional PA: 6,135; PAE and PDS in every edition) and
  undesignated land (TIPO B: 497 tracts in 2008, 1,742 in 2025). Every 2025
  settlement and 883 of 1,087 indigenous-land polygons have a creation date.
- Why: the agencies' own services are down or retired; the register compiles
  their boundaries.
- Implication: indigenous and undesignated land come from each election
  year's own edition; settlements from 2025, dated back by creation date
  (earlier editions lack conventional settlements). The 2008 edition records
  far less undesignated land (496 tracts in the Legal Amazon box, against
  1,624-10,548 later), so over-time comparisons of undesignated land should
  start in 2012 or adjust for coverage. Caveats: 2025 boundaries for earlier years; settlement polygons are
  the register's, which may be forest portions of a settlement.

## 2026-11-04: Kill criterion 1 for idea 0001 looks passed (preliminary)
- Tried: on the whole Legal Amazon (treatment-side data only, no outcomes),
  the strongholds of close-pair candidates (margin at most 0.5%), 2008-2024
  pooled, against CNFP 2025 indigenous lands and the settlements created by
  each election.
- Result: 1,334 strongholds inside or within 5 km of an indigenous land (443
  inside) and 5,244 inside or within 5 km of a settlement (310 inside), of
  18,060 with coordinates. The exploration half should have about half:
  roughly 667 and 2,622, against the criterion's 200.
- Why: preliminary, outside the explore-run pipeline; distances approximate
  (degrees times 111 km).
- Implication: the formal test runs as an explore task once land tenure is
  built. The 5 km settlement band covers 29% of close-pair strongholds, which
  may be too wide to separate constituency types; the stronghold typing task
  should report 0, 2 and 5 km.

## 2026-11-03: Feasibility census: enough close races with strongholds outside the seat (idea 0001)
- Tried: `explore/0001_feasibility_census.py` on the exploration half, run
  41719271978 (record in `research/explore-runs/0001/`), council elections
  2008-2024, with the definitions in task 10.
- Result: 765-1,060 within-list pairs per election decided by at most 0.5%
  of the municipality's valid council votes (1,343-1,918 at 2%). Of the
  candidates in those pairs, 48-55% have their stronghold outside the
  municipal seat, mostly in other towns, then in dispersed and rural places,
  and they cast 25-29% of their votes outside it. Among all candidates the
  figures are 42-45% and 23-25%. 2024 has 7 inverted pairs (excluded).
- Why: not tested here; the census is descriptive.
- Implication: the design has enough variation to continue. Caveats: place
  types use the 2022 urbanized areas for every year; the indigenous,
  quilombola and settlement labels are weak (about 2% of close-pair
  strongholds); a stronghold is one polling place. Next: constituency
  polygons (FUNAI, INCRA, public forests), then stronghold catchments.

## 2026-11-02: Nearest locality alone mistypes big-city polling places
- Tried: typing Legal Amazon polling places by their nearest IBGE locality.
- Result: in municipalities with more than 100,000 voters, 15% of voters were
  typed quilombola and 12.5% indigenous, including central Manaus
  neighbourhoods. Outside those cities the rule looked sensible.
- Why: a city has one seat point; at its edges some locality point is closer.
- Implication: urban clusters from IBGE's 2022 urbanized areas come first
  (seat cluster, other clusters), and the nearest locality types only places
  outside every urban area. Big cities are then 85% seat and 14% town.
  Constituency types (indigenous, settlement) need FUNAI and INCRA polygons.

## 2026-11-02: The 2004 section files are incomplete in four states
- Tried: the section-votes build over the whole Legal Amazon.
- Result: in 2004 only 675 of 771 municipalities have section data: Amapá
  3 of 16, Roraima 1 of 15, Mato Grosso 83 of 141, Maranhão 170 of 181 (the
  others complete). 2008-2024 are complete in every state.
- Why: gaps in the TSE's 2004 section files.
- Implication: 2004 section data cannot place every candidate's votes;
  strongholds for 2004 would cover 87% of municipalities, and 2004 has no
  coordinates anyway. The build measures agreement only where sections
  exist (99.6% in 2004; 99.9-100% from 2008) and reports coverage by state.

## 2026-11-02: Annulled candidacies are missing from the results file, not only zeroed
- Tried: the first real run of the section-votes build.
- Result: it stopped on 2004: 390 of 44,183 candidate numbers voted for in
  the sections had no candidacy in the results file (0.88%).
- Why: votes for candidacies whose registration was refused, cancelled or
  not apt are cast and recorded by section, but most years' results files
  leave those candidacies out entirely (2012 lists them with 0 votes, which
  is the only case task 07b expected). In Pará they are 1.5% (2004) to 4.3%
  (2024) of numbers, with 16,646 to 324,228 votes a year; every one of them
  is in the candidate file.
- Implication: the build now takes those candidacies from the candidate
  file and flags their rows `annulled_in_results`. Numbers in neither file
  are 0 in Pará except 2 in 2008. On the real Pará files, 2004-2024, the build
  passes: section sums equal counted votes for 99.6% (2004) to 100% of
  candidates. Close-race margins must use counted votes only.

## 2026-11-02: Section files count votes cast, results files count votes counted
- Tried: checking task 07b's vote-sum rule on Pará, 2004-2024, before filing.
- Result: in 2012, 256 candidates have 0 nominal votes in the results file
  but votes in the section file. Excluding them, section sums equal the
  results for every candidate with votes in 2008-2024 and 99.7% in 2004.
- Why: votes for candidates whose registration was refused or cancelled are
  cast (and recorded by section) but not counted.
- Implication: for close races, margins must use counted votes (the results
  file, or section votes not flagged `annulled_in_results`). A candidate whose
  votes are annulled can change who is "narrowly elected"; such races should
  be identified and reported, not silently dropped.

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
