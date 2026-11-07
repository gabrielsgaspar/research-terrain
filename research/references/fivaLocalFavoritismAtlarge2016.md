---
citekey: fivaLocalFavoritismAtlarge2016
doi: 10.1016/j.jpubeco.2016.08.002
zotero_key: WSL7G62F
status: core
role:
strands: []
links: []
---
## Question            <!-- agent-drafted, confirm -->
(drafted; check) Do politicians steer public spending to their hometowns in an at-large, closed-list PR system, where candidates have no clear electoral incentive to favour their home municipality? Specifically: does a municipality get more regional investment funding when it has a regional council member from the governor's party (an "aligned representative")? Secondary questions: do voters show a hometown bias toward parties whose top candidate is local, and is the favoritism driven by local-career ambitions or by local roots (pp. 15-16)?

## Setting and data    <!-- agent-drafted, confirm -->
(drafted; check) Norway's 18 regional governments (fylkeskommuner; Oslo excluded), 1976-2011 (p. 16). Each region is a single at-large district. Councils have 35-85 members, seats are allocated by modified Sainte-Laguë, and lists were closed from 1975 to 1999. From 2003 there are preference votes, but the paper says these had negligible effect: 98.8% of 2003 winners would have won without them (p. 16, fn. 13). Until 2003, 1/6 of seats were reserved for candidates from municipalities with no seat yet (fn. 11). The council elects a governor (fylkesordfører), who is almost always a list's top candidate. The four regions that adopted parliamentary models from 1999 are excluded (fn. 8).

- **Unit:** municipality x four-year election period, N = 3,658 (Tables 1, 4).
- **Outcome:** regional-government funding of local public investments, taken from municipal accounts (Statistics Norway / NSD). It is reimbursement to a municipality when it invests in goods that fall partly or fully within the regional remit (roads, sports facilities, etc.). It is inflation-adjusted, summed over the election period, and expressed in NOK per capita (p. 17). The mean is 409 NOK per capita (Table 4). The median is 107 NOK, the 90th percentile 1,024 and the 99th 4,186 (Table 1, p. 17). This funding is 5.4% of total regional investment.
- **Hometown:** the municipality where the council member lives at the time of election (fn. 15, p. 17).
- **Parties:** grouped into a left bloc (SV, Labour) and a right bloc (V, SP, KrF, H, FrP). Only parties that ever hold the governorship enter the alignment variables: Labour (Left), and Center, Christian Democrats and Conservatives (Right1-3) (p. 17).
- **Extra data:** top-candidate hometowns and simultaneous local-election vote shares (Section 5.1). Candidate-level panels for 2001-2015 for the career analysis (Section 5.2).

## Identification      <!-- agent-drafted, confirm -->
(drafted; check) The design is a fuzzy RD on the **bloc seat majority on the regional council**. It is not a within-list RD on candidates' seat margins.

- **Running variable:** the rightwing bloc's win margin. This is the vote shift across blocs needed to flip the seat majority in 50% of simulations, using the simulation method of Fiva, Folke and Sørensen (p. 18, fn. 16). Crossing zero raises the probability of a rightwing governor by 90-95 pp. The cutoff is fuzzy because a right majority sometimes still yields a Labour governor (Fig. 1, p. 19).
- **Treatment:** Align_irt = 1 if municipality i has any regional council member from the governor's party.
- **First stage:** Align_irt is instrumented with interactions of Left-majority x party-specific representative dummies (rep from Left, Right1, Right2, Right3) (eq. 1, p. 18). The first stage includes municipality and period FE and a polynomial in the win margin on each side, interacted with each party-rep dummy. Excluded-instrument F is 13.1-16.9 (Table 3, p. 21).
- **Second stage (eq. 2, p. 19):** per-capita funding on the instrumented Align, with the same controls. Standard errors are clustered by region. Because there are only 18 clusters, p-values come from the Cameron-Gelbach-Miller wild bootstrap (fn. 19).
- **Bandwidth:** the baseline uses **all observations (full bandwidth)** with a 2nd- or 3rd-order polynomial in the win margin (p. 19; Table 4). The figures also show a ±10 pp bandwidth with a linear fit (Figs. 1-2, panel B). The paper says results are insensitive to dropping observations far from the threshold (Online Appendix B, p. 19).
- **Validity checks:** no bunching at the cutoff and covariates balanced (Online App. Figs. A.1-A.3, p. 18). Close right wins are somewhat more frequent early in the sample (p = 0.10), which motivates the period FE (fn. 17). In placebo leads and lags (k = -2, -1, +1, +2), effects are small and insignificant (Fig. 3, pp. 19-20). Results are unchanged when controlling for mayor-governor cross-tier alignment (Online App. Table A.3, p. 20).
- **Within-list rank RD:** a rank-distance RD within party lists (marginal winners vs. marginal losers) appears only in the career analysis (Fig. 4, pp. 23-24). The authors state that it does not necessarily identify a causal effect, because parties can anticipate seat counts.
- **Voting analysis:** a separate FE regression, not an RD. Regional-election vote shares are regressed on local top-candidate dummies, controlling for the same party's vote share in the simultaneous local election (eq. 3, p. 22).

## Main result         <!-- agent-drafted, confirm; include magnitudes -->
(drafted; check)
- **Hometown/alignment effect:** having an aligned representative raises regional investment funding by **582-639 NOK per capita per election period** (2SLS, Table 4 cols. 1-4, p. 21). Against a mean of 409 NOK, the paper summarises this as "about NOK 600 (USD 90)", or about **0.56 SD** (p. 19). Wild-bootstrap p-values are 0.02, 0.05, 0.07 and 0.12, and the most demanding specification (3rd-order polynomial plus municipality FE, col. 4) is not significant at 10%. OLS gives 76.6 NOK, about 1/8 of the RD estimate (Table 4 col. 5, p. 21).
- **Reduced-form jumps (full bandwidth, cubic):** -489 NOK for municipalities with only leftwing reps (p = 0.41) and +616 NOK for those with only rightwing reps (p = 0.03). Jumps are near zero for groups with no reps or reps from both blocs (Fig. 2, p. 18; fn. 18).
- **Large projects:** the effect is driven by large projects. It is positive and significant for a dummy for more than 1,000 NOK per capita, and smaller and insignificant for more than 100 NOK per capita (Online App. Table A.2, p. 19). There is also a positive effect on finished road construction 4-7 years later (Online App. C, p. 20).
- **Heterogeneity (Table 6, p. 25):**
  - Municipalities with only newly elected members: 499 NOK (p = 0.10).
  - Municipalities with only incumbents: 234 NOK (p = 0.86).
  - Below-median population: 789 NOK (p = 0.11), and 0.28 on the more-than-1,000-NOK dummy (p = 0.01).
  - Above-median population: 17 NOK (p = 0.90).
  - The authors cannot reject equal effects for small and large municipalities (fn. 30).
- **Friends-and-neighbors voting:** a local gubernatorial (first-placed) candidate raises the party's share of the electorate by 1.4-3.2 pp, significant at 1% for all four parties (Table 5 diagonal, p. 23). Only a small part of this comes from lower abstention. The effect is about twice as large in below-median-size municipalities (Online App. E.1-E.2, p. 23).
- **Careers (Fig. 4, pp. 23-24):** no evidence that regional councilors prepare a local career. Marginal winners are not more likely to be local top candidates at t+4. They are more likely to run nationally at t+6 (28% vs. 19%, significant at 5%; Online App. Table F.1). About half of regional council members previously held a local council seat (p. 24).

## What it doesn't do  <!-- Gabriel -->
(drafted by Claude Code; Gabriel to rewrite)

- Its outcome is regional investment money paid to municipalities, not land
  use, in Norway, a high-capacity, low-corruption state.
- Its identifying RD is on the bloc seat majority, not on individual
  candidates. The within-list rank RD appears only in the career analysis,
  and the authors do not claim it is causal, because parties can anticipate
  seat counts.
- "Hometown" is a place of residence, a single point. It has no geography of
  votes within municipalities.
- It has only 18 clusters (wild-bootstrap p-values).

## Relevance to us     <!-- Gabriel: what we borrow, how we differ -->
(drafted by Claude Code; Gabriel to rewrite)

- It is the closest analogue: local favouritism in an at-large proportional
  system. Brazilian councils are elected at large by open-list PR within the
  municipality, where personal votes give councillors even more reason to
  favour their bases than Norway's closed lists did.
- Favouritism runs through alignment with the executive (the governor's
  party) and is concentrated in small municipalities. That is the motivation
  for idea 0004 (alignment with the mayor).
- Friends-and-neighbours voting (1.4-3.2 pp, Table 5) supports reading vote
  geography as constituency, as our strongholds do.
- How we differ: our within-list close races are a candidate-level RD on vote
  margins. In open lists, order is set by votes, not by the party, so its
  caution about anticipated seats applies less. Sorting at the margin still
  has to be checked (balance, task 35).
