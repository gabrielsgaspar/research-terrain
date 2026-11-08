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

## 2026-11-08: The registered analysis new paths pass all seven structural checks (idea 0001, issue #254)
- Tried: campaign 0002 ran `explore/0001_registered_paths_check.py` on the
  exploration half at the 0.50% window, run 42514591508
  (`research/explore-runs/0001/42514591508.md`): seven checks of the
  incumbency-adjusted estimates, the direct placebo, the alignment split and
  the balance table. Counts and pass or fail only.
- Result: all seven pass, and no kill rule was met. Pooled 2008-2020, 1,294
  close pairs have exactly one incumbent (690 plus, 604 minus), against
  k8's threshold of 200.
- Why: the frozen code satisfies the identities the checks test, and each
  election has pairs with exactly one incumbent.
- Implication: one item before registration can be ticked, with the caveat
  that 0.50% is not the registered window. The count at 0.25% is not known and
  may be lower; no estimate was produced.

## 2026-11-08: The smoke-test campaign reproduced the known power check (idea 0003, issue #245)
- Tried: campaign 0001 re-ran `explore/0003_mayor_power.py` on the
  exploration half, run 42494552921
  (`research/explore-runs/0003/42494552921.md`), and compared it with the
  first run, 42367009833 (`research/explore-runs/0003/42367009833.md`).
- Result: the same numbers. 45, 80 and 157 races at 0.5%, 1% and 2%; power
  4.4%, 5.2% and 7.2% at 8% of baseline. Kill rule k1 (power below 0.8 at 1%)
  was met, as expected.
- Why: the script has a fixed seed and the inputs did not change.
- Implication: the single-step path of the campaign machinery gave the
  expected record and verdict. Idea 0003 stays dead; nothing new was learned
  about close mayoral races.

## 2026-11-08: The registered analysis reproduces the explore code at 0.50% (idea 0001, issue #241)
- Tried: `explore/0001_registered_check.py` on the exploration half at the
  0.50% window, run 42476480500
  (`research/explore-runs/0001/42476480500.md`), on main after PR #236:
  idea 0001's registered analysis (`src/terrain/registered/r0001/`) run
  with the real treatment, 2,000 re-flips and seed 20261106, its numbers
  compared with run 42298466207 (the eleven estimates, dropped cells, type
  counts) and run 41839642406 (kill criterion 1's counts). Only the
  comparison is reported.
- Result: reproduced. 875 numbers compared (821 and 54), 0 differ; the
  largest relative difference is 1.44e-14, within the rule (whole numbers,
  text, RI p-values and p1 equal; others within a relative 1e-9).
- Why: the registered core is a verbatim copy of the explore functions, so
  only the order of floating-point sums can differ.
- Implication: the code path of the registered analysis gives the numbers
  of the explore runs it was frozen from, on the exploration half at 0.50%
  only. The new paths (direct_adj, ring2_adj, ring5_adj, direct_pre,
  direct_pre_adj, align and balance) were computed but not compared, as no
  earlier run has them, so this run does not check them. Nothing ran at the
  registered 0.25% window.

## 2026-11-07: Alignment with the mayor splits close pairs evenly, but the moderation test has power near 0.34 (idea 0004, issue #223)
- Tried: `explore/0004_alignment_counts.py` on the exploration half, run
  42384829937 (`research/explore-runs/0004/42384829937.md`): close council
  pairs at 0.25% typed by whether their party was in the elected mayor's
  coalition the same election (2024 federations count); no lineage table,
  no outcome data. A first run (42384059012) had the same counts but an
  inverted verdict; it was fixed (#229, #231) and re-run, not edited.
- Result: 1,414 aligned, 1,446 unaligned, 4 mixed, 5 left out (2008),
  pooled 2008-2024; 1,100 and 1,219 in 2008-2020. Drafted kill criterion 1
  (fewer than 200 of either) is not met. The implied power for a gap of one
  effect size is 0.335, a rough scaling of decision 0008's direct power.
- Why: about half of close council pairs belong to the mayor's coalition,
  so the split is close to even, which is already the best case (0.337). A
  difference between two slopes, each estimated on half the pairs, has
  about twice the standard error of the pooled slope.
- Implication: idea 0004 has enough pairs to be estimated, but on a half of
  this size it cannot test moderation of one effect size at 80% power.
  Drafted kill criterion 3 would read "cannot be applied". By the same
  scaling, 80% power needs a gap of about 1.8 effect sizes. Gabriel to decide
  whether the idea is worth a design, and to confirm its kill criteria.

## 2026-11-07: Kill criterion 1 still passes at the 0.25% window (idea 0001, issue #224)
- Tried: `explore/0001_kill_criterion_1_window.py` on the exploration half,
  run 42384056410 (`research/explore-runs/0001/42384056410.md`): kill
  criterion 1's counts (close-pair candidates with a stronghold in or within
  5 km of an indigenous land, and of a settlement; 2008-2024 pooled) at
  decision 0008's 0.25% window, with 0.50% recounted in the same pass. No
  outcome data.
- Result: at 0.25%, 434 indigenous-side and 1,625 settlement-side
  candidates (5,738 candidates, twice the 2,869 pairs); not met (minimum
  200). The 0.50% recount equals run 41839642406 in every cell (711 and
  2,590).
- Why: halving the window keeps about 61-63% of the candidates on each side,
  as it keeps 63% of the pairs; constituency types are not concentrated in
  the widest races.
- Implication: under decision 0009 ("0.5%" in kill criterion 1 means the
  registered window), the criterion is not met at 0.25% on this half. A
  confirmation half of the same size would clear the bar by about two to
  one on the indigenous side. The split itself remains secondary, with power
  near 0.31.

## 2026-11-07: The balance rule picks a 0.25% window; 0.50% is unbalanced on incumbency (idea 0001, issue #206)
- Tried: `explore/0001_window.py` on the exploration half, run 42366460941
  (`research/explore-runs/0001/42366460941.md`): seven close-race windows
  (0.10% to 2.00%), elections 2008-2024 pooled, ten pre-election covariates
  (incumbency rebuilt from the previous election's elected councillors), one
  set of 2,000 re-flips, omnibus p from the re-flip distribution of the
  minimum p, and the rule of issue #206 (the widest window with omnibus p at
  least 0.15, every smaller window also). No post-election outcome was read.
  Pairs per window match the feasibility census to the unit.
- Result: omnibus p 0.191 (0.10%), 0.548 (0.25%), 0.119 (0.50%), 0.0005 from
  0.75% up. The rule picks 0.25% (decision 0008, accepted by rule). The
  imbalance is incumbency: winners held the seat before more often than
  losers, by 1.1, 2.0 and 2.3 percentage points at 0.10%, 0.25% and 0.50%
  (RI p 0.53, 0.084, 0.014), rising to 6.4 points at 2.00%. Power at 8% falls
  at 0.25% to 0.868 (direct), 0.622 (displacement) and 0.307 (split), from
  0.944, 0.797 and 0.448 at 0.50%.
- Why: incumbents are more likely to win close races, and the wider the
  window, the more a "close" race is one that incumbents tend to win. The gap
  at 0.25% is almost the gap at 0.50%; 0.25% passes mainly because it has
  fewer pairs, so the test has less power to see the gap.
- Implication: task B's 0.50% result (2026-11-06 entry) stands as
  pre-specified but is reported with a caveat: at 0.50% narrow winners and
  losers are not balanced on incumbency, so the contrast partly mixes winning
  with having held the seat. Its nulls are not overturned by this. The
  pre-analysis plan uses 0.25%, which costs power: on a confirmation half of
  this size, kill criteria 3 and 4 would be further below 80% than at 0.50%.
  The plan should report incumbency balance in the chosen window and say
  whether incumbency enters as a control. Gabriel to review decision 0008.

## 2026-11-07: Close mayoral races cannot detect an 8% effect (idea 0003, issue #214)
- Tried: `explore/0003_mayor_power.py` on the exploration half, run 42367009833
  (`research/explore-runs/0003/42367009833.md`): close mayoral races
  (deciding round, 2008-2020) at 0.5%, 1% and 2%, one observation per race,
  pre-election clearing only (E-4..E-1, municipal share of primary vegetation
  lost), the spread of the winner-minus-loser contrast over 2,000 re-flips.
  No effect was estimated and no post-election year was read.
- Result: 45, 80 and 157 races (as expected from the Legal Amazon counts:
  about half of 91, 162 and 310). Power at decision 0007's 8% is 4.4%, 5.2%
  and 7.2%. The minimum detectable effect at 80% power is 89%, 67% and 45% of
  baseline clearing (baseline about 0.048). Only 1 of the 157 races at 2% was
  decided in a run-off.
- Why: one observation per race, and municipal clearing varies a lot between
  municipalities (SD of Y 0.051 against a mean of 0.049), so 157 races give a
  re-flip SD of 0.0078. That is about 2 SD / √n, the best case for a 50/50
  attribute.
- Implication: a municipality-level design on close mayoral races is not
  worth building: even at 2% it could only detect effects of about half the
  baseline. A turf design compares cells within the same municipality, so it
  would be more precise, but it rests on the same 157 races. As a rough
  guide, not a computation: idea 0001's direct design has an MDE of 6.3% with
  3,684 pairs, and scaling that by √(3,684 / 157) gives about 30%. Idea
  0003's drafted kill criterion 1 (power below 0.50 at every window) is met.
  The idea stays `proposed` until Gabriel confirms its kill criteria. The
  recommendation is to mark it dead.

## 2026-11-06: Kill criteria 3 and 4 on the exploration half (idea 0001, issue #201)
- Tried: `explore/0001_effects.py` on the exploration half, run 42298466207
  (`research/explore-runs/0001/42298466207.md`): the direct slope (`exp2`),
  the displacement slope (`g_exp10`) and the constituency split (5 km; 2 km
  as robustness) on post-election clearing (E+1..E+4, and E+1..E+2),
  elections 2008-2020 pooled, 2,000 re-flips of the close pairs shared by
  every estimate; verdicts by decision 0007. Same pairs, cells and candidate
  types as the power run (42265146230), to the unit.
- Result: both criteria "cannot be applied at 80% power on this half".
  Direct slope -0.0032, -1.0% of baseline at the mean exposure (RI p 0.59);
  displacement -0.0086, -4.4% (RI p 0.086); under Holm neither is non-zero
  (the smaller p, 0.086, is above 0.025). Split difference (indigenous-side
  minus settlement-side) +0.0118, +3.4% (one-sided p1 0.81, two-sided p
  0.40): the point estimate has the opposite sign to the prediction.
  Displacement placebo (E-4..E-1) -0.0117, -5.35% (RI p 0.06); change
  outcome dY +0.0032 (RI p 0.49). The 95% re-flip band of the direct slope
  is about -3.6% to +3.4% of baseline, and of the displacement slope about
  -5.0% to +4.8%.
- Why: the direct null is informative: the design detects 8% with power
  0.94, and the 95% band excludes effects beyond about ±3.5% of baseline.
  The displacement slope after the election is about as large as before it,
  so it reflects a pre-existing difference, not the election. The split's
  point estimate runs against the prediction, but rests on 455
  indigenous-side candidates (power 0.45).
- Implication: criteria 3 and 4 are unchanged and the confirmation half
  stays sealed. If the confirmation half is about as large, kill criterion
  3 will again have power near 0.45, so
  the pre-analysis plan has to say how it is read there. The displacement
  effect cannot be separated from its pre-election difference on this half,
  which is why dY is reported. No pre-specified criterion is met, but the
  exploration gives no support to the idea's predictions: the direct effect
  is ruled out at the effect size of interest, displacement is not separated
  from a pre-existing difference, and the split points the wrong way. Kill
  criterion 4 is "cannot be applied" only because displacement's power is
  0.797 against a bar of 0.80. The pre-existing displacement difference also
  questions balance at the 0.5% window; the window-selection task tests
  this. Before the pre-analysis plan, decide whether the confirmation half
  is spent on this design.

## 2026-11-06: The design's minimum detectable effects, for decision 0007 (idea 0001, issue #194)
- Tried: `explore/0001_power.py` on the exploration half, run 42265146230
  (`research/explore-runs/0001/42265146230.md`): the spread over 2,000
  re-flips of the close pairs (the placebo's design, elections 2008-2020) of
  the direct slope (`exp2`), the displacement slope (`g_exp10`) and the
  constituency split (indigenous-side, settlement-side, both, neither,
  untyped strongholds at 5 km, and 2 km as robustness), on pre-election
  clearing only (E-4..E-1 and E-2..E-1).
- Result: candidates per type at 5 km, pooled: 455 indigenous-side, 1,987
  settlement-side, 96 both, 4,791 neither, 39 untyped (2 km: 337 and
  1,211). Minimum detectable effect at 80% power (two-sided 5%, four-year
  window), as a percentage of baseline clearing for a cell at the mean
  exposure: direct 6.3%, displacement 8.0%; the split's difference
  (one-sided 5%) 13.1% at 5 km and 17.7% at 2 km. At the median exposure
  the same numbers are 2.8%, 3.7% and 5.1%; at the 90th percentile 17%,
  22% and 34%. `2.8 x sd_ri` and the re-flip quantiles agree within a few
  percent, so the re-flip distribution is close to normal.
- Why: about 1.9 million exposed cell-elections give a precise pooled
  slope, but the split rests on 455 indigenous-side candidates and the
  exposure is skewed (mean |D| 0.071, median 0.032).
- Implication: decision 0007 must state the exposure point at which the
  effect size is read, because it moves the detectable effect about
  sixfold between the median and the 90th percentile. Context, not a test:
  the pre-election displacement slope has RI p 0.06 (four-year window); kill
  criterion 2 covers the direct exposure only, so the pre-analysis plan
  should report the displacement placebo too.

## 2026-11-06: Kill criterion 2, the pre-election placebo, is not met (idea 0001, issue #189)
- Tried: `explore/0001_placebo.py` on the exploration half, run 42193625417
  (`research/explore-runs/0001/42193625417.md`): the sum of loss of primary
  vegetation (MapBiomas code 4) over the four years before each election
  2008-2024, on decision 0004's recentred exposure D/2, municipality-by-election
  fixed effects, randomisation inference over 2,000 re-flips of the close
  pairs; reached cells of municipalities with a close pair.
- Result: pooled `exp2` beta -0.0075 (RI p 0.34; clustered SE 0.0070;
  2,423,814 cell-elections, 4,575 pairs; mean Y 0.027). The rings agree
  (`ring2` p 0.33, `ring5` p 0.54). One of the 15 per-election estimates is
  below 0.05 (`exp2` 2008, beta -0.032, p 0.029), about what 15 tests give
  by chance.
- Why: close-race outcomes are as good as random relative to clearing before
  the election, as the design assumes.
- Implication: the idea survives kill criterion 2. The 2008 term starts from
  the highest clearing (mean Y 0.040); per-election placebos go in the
  pre-analysis plan as a reported check, not a test.

## 2026-11-05: Displacement-exposure formulas compared for decision 0005 (idea 0001, issue #161)
- Tried: `explore/0001_displacement_options.py` on the exploration half, run
  41949908031 (`research/explore-runs/0001/41949908031.md`): for empty cells
  beyond decision 0004's 10 km reach ("unrepresented"), the sum over close
  pairs of a kernel at the elected candidate's stronghold minus the same at
  the other's, for a 10-20 km ring, a 20-50 km ring, exp(-d/10) to 50 km and
  "nearest stronghold within 50 km", 2008-2024.
- Result: 76-79% of the cells of municipalities with a close pair are
  unrepresented (1.77 to 1.94 million cells a year). exp(-d/10) gives a
  non-zero exposure to 683,263 (2008) to 733,859 (2016) of them, the
  20-50 km ring to 382,458-461,884, the 10-20 km ring to 137,826-164,336. In
  2024, 14% of the cells exposed under exp(-d/10) are in undesignated forest,
  24% touch an indigenous land and 5% a settlement (2008: 6% in undesignated
  forest, the register's thinner first edition). exp(-d/10) agrees with the
  10-20 km ring (2024 correlation 0.91) and the nearest-stronghold rule (0.64)
  but not with the 20-50 km ring (0.03): the decay is carried by the cells
  closest to the strongholds. 100-116 pairs a year (about 12%) have both
  strongholds at the same polling place and carry no displacement contrast.
- Why: the strongholds of a pair are usually a few kilometres apart, so far
  from both the two kernels nearly cancel, and only the near band
  distinguishes the winner's side from the loser's.
- Implication: decision 0005 is proposed with exp(-d/10) to 50 km as the
  displacement exposure, the 10-20 and 20-50 km rings as robustness, and
  recentring as G / 2; Gabriel decides. The far ring measures something else
  (nearly unrelated), so it is a separate check, not a substitute.

## 2026-11-05: Figure 6's municipality: Santa Rosa do Purus, 2024 (idea 0001, issue #141)
- Tried: the rule of task 25, applied by `figures/06_close_pair.py` in
  figures-run 41937619933 on the exploration half only: among close pairs
  (margin at most 0.5%, 2008-2024) where one candidate's stronghold is within
  2 km of an indigenous land and not of a settlement and the other's the
  reverse, take the smallest |margin|; ties to the later year, the lower
  `cd_ibge`, the lower elected `sq_candidato`.
- Result: 2024, Santa Rosa do Purus (AC, IBGE 1200435), margin 0.0000 at four
  decimals: the two candidates were tied or within 0.005% of the valid votes.
  The narrowly elected candidate's stronghold is near (inside) an indigenous
  land, the narrowly defeated one's near a settlement on the border with
  Peru. The figure is `paper/figures/06_close_pair.png`; candidates are not
  named.
- Why: the rule picks the closest race, and a near tie is as close to a coin
  flip as the design gets.
- Implication: the example shows the design's contrast at its cleanest. The
  same rule reruns deterministically; changing it means changing task 25's
  rule, and recording it here.

## 2026-11-04: cell_exposure reproduces the explored exposure exactly (idea 0001, issue #125)
- Tried: the `cell_exposure` build (decision 0004, both halves), restricted
  afterwards to the exploration half and compared with explore run
  41913964880.
- Result: identical in every year for every count compared: cells reached
  and exposed under exp(-d/2), reached and exposed under the 5 km ring,
  reached under the 2 km ring, and municipalities with a close pair (2024:
  539,862 reached, 483,734 exposed, 338 municipalities). On the whole Legal
  Amazon 668 (2024) to 723 (2012) municipalities have a close pair, and
  869,625 (2008) to 1,013,325 (2024) cells are reached.
- Why: the build uses `terrain.strongholds`, a copy of the explored
  functions tested equal to them.
- Implication: exposure can be used as built. The manifest's
  `municipalities_with_pair` and `close_pairs` notes count all of Brazil
  (4,591-4,938 municipalities), because the results tables are national;
  only Legal Amazon cells are in the output, so the values are unaffected.
  Fixed on 2026-11-05 (PR #156): the rebuild gave byte-identical files, and
  its notes count Legal Amazon pairs only (698 to 723 municipalities).

## 2026-11-04: Exposure formulas compared for decision 0004 (idea 0001, issue #116)
- Tried: `explore/0001_exposure_options.py` on the exploration half, run
  41913964880 (`research/explore-runs/0001/41913964880.md`): every 1 km cell's
  exposure to the close pairs (margin at most 0.5%) of its municipality,
  winner minus loser, for three kernels (exp(-d/2) to 10 km, 2 km and 5 km
  rings) and two measures (kernel-weighted mean vote share, kernel-weighted
  votes), 2008-2024.
- Result: of 2,530,638 exploration-half cells, exp(-d/2) reaches 458,285
  (2008) to 539,862 (2024) and exposes 412,042 to 483,734; the 5 km ring
  exposes about 40% as many, the 2 km ring about 10%. 76% of cells exposed
  under exp(-d/2) have no one living in them (42-44% under the 2 km ring).
  With the share measure the kernels agree (2024 correlation of D with the
  2 km ring 0.97, with the 5 km ring 0.98), but share and votes do not (0.15
  under exp(-d/2)): votes exposure is four times larger in populated cells
  than in empty ones (mean |D| 21.9 against 5.4), share exposure is similar
  (0.067 against 0.078) and highest in indigenous-land cells (0.106). Median
  |D| under exp(-d/2) and share is 0.029-0.033 in every year.
- Why: votes scale with how many people vote at nearby places, so votes
  exposure mostly measures population density; the share measure is the
  candidate's relative strength, which is what a stronghold is. The kernels
  differ in reach, not in ranking.
- Implication: decision 0004 is proposed with exp(-d/2) to 10 km and the
  share measure as the main exposure, the rings as robustness, and
  winner-minus-loser recentred as D / 2; Gabriel decides. Most exposed land
  is empty, so the displacement prediction has room.

## 2026-11-04: The 2010 grid undercounts the census; the 2022 grid does not (idea 0001)
- Tried: assigning every 2022 1 km cell to the Legal Amazon municipality
  that contains its centre (`BR_Municipios_2024`, the 773 municipalities of
  the 2024 list), joining the 2010 grid on `nome_1KM`, and comparing state
  totals with the census, before writing task 19.
- Result: 5,029,081 cells (92.6% with nobody in 2022), 26,602,373 people in
  2022 against IBGE's 26.6 million for the Legal Amazon. In the eight states
  wholly inside it, the 2022 grid is within 0.7% of the census (RO 1,580,610
  of 1,581,196; PA 8,116,522 of 8,120,131), but the 2010 grid is 2.3% (TO)
  to 7.2% (RR) below the 2010 census (PA 7,295,449 of 7,581,051): 23,491,572
  people in all. Every 2010 parent cell is in the 2022 file, and every
  Legal Amazon cell has a 2010 row.
- Why: not established. Most likely the 2010 grid leaves out people it
  could not place on the map; IBGE's 2010 methodology note was not checked.
- Implication: growth from 2010 to 2022 measured on the grid is overstated
  by a few percent and unevenly by state; use 2022 for exposure and
  population weights, and 2010 only for robustness, with state effects.

## 2026-11-04: IBGE's grid cells: names, projection and the two censuses (idea 0001)
- Tried: the real 2022 1 km grid (`BR1KM_20251002.zip`), all 38 Legal
  Amazon tiles of the 2010 grid and the 2024 municipal boundaries, before
  writing their catalog entries and fixtures.
- Result: the 2022 file has 8,860,553 cells; in the Legal Amazon box
  6,105,735, of which 533,990 (8.7%) are populated, 40,517,810 people. The
  2010 tiles hold 8,834,513 rows, 1 km cells and 200 m cells mixed, one
  schema in all 38. With IBGE's Albers (lat_0 -12, lon_0 -54, parallels -2
  and -22, false easting 5,000 km, false northing 10,000 km, GRS80) a 1 km
  name gives the cell's lower-left corner in km (`1KME4717N11118`), but a
  200 m name gives its top-left corner in hundreds of metres
  (`200ME47210N111032`); every 200 m cell lies inside its `nome_1KM`. The
  municipal boundaries have 5,573 rows: the 5,571 municipalities plus two
  lagoons in RS (`4300001`, `4300002`, "Área Operacional").
- Why: IBGE names the two cell sizes from different corners; the lagoons
  are mapped as units without a municipality.
- Implication: join and aggregate the censuses on `nome_1KM` only, never by
  parsing `ID_UNICO`; Albers coordinates of a 1 km cell come from its name.
  Drop the two lagoons when matching boundaries to municipalities.

## 2026-11-04: Kill criterion 1 for idea 0001 is not met
- Tried: `explore/0001_kill_criterion_1.py` on the exploration half, run
  41839642406 (record in `research/explore-runs/0001/`), close pairs and
  strongholds as in the feasibility census, distances from
  `polling_place_tenure`.
- Result: of 9,150 close-pair candidates (margin at most 0.5%, 2008-2024
  pooled), 9,090 have a stronghold with coordinates; 711 of those
  strongholds are inside or within 5 km of an indigenous land (261 inside,
  455 within 2 km) and 2,590 of a settlement (180 inside, 1,534 within
  2 km), against the criterion's minimum of 200 for each. The preliminary
  whole-Legal-Amazon estimate expected about 667 and 2,622.
- Why: strongholds near indigenous lands and settlements are common enough
  in close races to compare them.
- Implication: idea 0001 survives its first kill criterion. The 5 km
  settlement band takes in 28% of close-pair strongholds, so the design
  should type constituencies at 0 or 2 km. Next: stronghold catchments, then
  outcome data with decision 0003's split.

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
