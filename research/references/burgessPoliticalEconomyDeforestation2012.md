---
citekey: burgessPoliticalEconomyDeforestation2012
doi: 10.1093/qje/qjs034
zotero_key: 8CMLMRYQ
status: core
role:
strands: []
links: []
---
## Question            <!-- agent-drafted, confirm -->
(drafted; check) How do the incentives of local officials who de facto control forest extraction (legal and illegal) shape deforestation? The paper tests two predictions of a model in which district governments sell (legal or illegal) logging permits and compete à la Cournot within a provincial wood market, facing a probability of detection that costs them their other rents of office:

- More districts in a wood market raise total extraction and lower wood prices.
- Alternative rents (here, oil and gas revenue sharing) substitute for illegal-logging rents. The paper asks whether this holds in both the short and the medium run.

## Setting and data    <!-- agent-drafted, confirm -->
(drafted; check) Indonesia after Suharto. The decentralization laws (passed 1999, in force 2001) put district forest offices under the district head (bupati), and these offices became the gatekeepers for permits, transport documents and patrols (pp. 1715-1718). Districts proliferated: on the forest islands (Sumatra, Kalimantan, Sulawesi, Papua) they went from 189 in 2000 to 312 in 2008 (p. 1715; p. 1730 gives 146 before decentralization). There was a national moratorium on new districts in 2004-2006 (p. 1727; p. 1731 says "from 2004 ... through 2007").

- Deforestation: the authors built a MODIS series (250 m x 250 m, annual, 2001-2008) by training a bagged decision tree on Landsat training images and coding a pixel as cleared if the predicted probability of loss exceeds 90%. They describe it as a lower bound: it catches clear-cutting and large burns, but not selective logging under an intact canopy (pp. 1718-1720). Pixels are summed by district and by the four Forest Estate land-use zones: Production and Conversion (some logging can be legal) and Protection and Conservation (all logging illegal). Total loss over 2000-2008 was 783,040 pixels, about 48,940 km² (Table I, p. 1725). The mean is 113 pixels per district-zone-year (SD 464) (Table II, p. 1726).
- Prices and official quantities: the official Statistics of Forest and Concession Estate, 1994-2007, province level, 114 wood types. Price is value divided by quantity. This source covers only the Production zone and reported (legal) logging (p. 1721).
- Oil and gas revenue sharing per capita by district, from the Ministry of Finance (p. 1729). Direct district-head election timing, candidates and coalitions come from Skoufias et al. (2010) (p. 1749).
- Units: the main jurisdiction regressions are at the **province x forest zone x year** level, with 21 provinces on 2008 boundaries and 608 observations (Table IV). The oil-and-gas regressions are at the **district x forest zone x year** level (Tables VI-VII).

## Identification      <!-- agent-drafted, confirm -->
(drafted; check)
- Jurisdictions and quantities: a fixed-effects Poisson QML count model (eq. 5, p. 1733). The dependent variable is pixels deforested in a province-zone-year. The regressor is the number of districts in the province. Controls are province FE and island x year FE. Standard errors are clustered at the 17 provinces on 1990 boundaries, and each land-use zone is estimated separately. Panel B adds three lags and reports the sum L0-L3.
- Source of variation: the staggered timing of district splits, mostly on the intensive margin (how many new districts, and when), since every province gained at least one (p. 1727). The authors argue that timing is idiosyncratic, driven by a cumbersome legislative process and the moratorium (pp. 1731-1732). They report that split year is uncorrelated with population, area, oil and gas revenue, forest share, pre-period deforestation, a corruption measure, or Golkar vote share (Online App. A.1). Leads are jointly insignificant, with p = 0.20-0.71 (A.5), and results survive added trends (A.4) and dropping one island at a time (A.6) (p. 1736).
- Prices: OLS of log price and log quantity by wood type-province-year on the number of districts, with wood type x province and wood type x island x year FE, weighted by initial volume (eq. 6, p. 1734).
- Alternative explanations (pp. 1743-1744). Weaker enforcement after a split is argued against because the effect grows rather than fades over time and is no larger in the new part of a split district (A.13). Central quota bargaining is argued against because effects of similar size appear in zones where all logging is illegal.
- Rent substitution: a district-level Poisson model of deforestation on per-capita oil and gas revenue, controlling for the number of districts, with district FE and island x year FE (eq. 7, p. 1746). The revenue is argued to be exogenous to forestry because it is on average 20 times forestry revenue and moves with prices, production in own and neighbouring districts, and the sharing formula. Eq. 8 interacts revenue with a dummy for whether the new direct district-head election has taken place (p. 1749).

## Main result         <!-- agent-drafted, confirm; include magnitudes -->
(drafted; check)
- **District splits raise deforestation.** One more district in a province raises the province's deforestation rate by 3.85% in the same year (coefficient 0.0385, SE 0.0160) (Table IV Panel A col. 1, p. 1737; text p. 1734). Three years later the effect is 8.22% (sum L0-L3 = 0.0822, SE 0.0204) (Table IV Panel B col. 1; text p. 1735). The introduction states this as an 8.2% increase "in the overall deforestation rate in that province" (p. 1709).
- By zone, Panel B: 8.09% in Production/Conversion and 10.1% in Conservation/Protection, both significant. Individually, Production is 7.95% and Conservation 15.1%; Conversion (8.5%) and Protection (5.1%) are not significant. In Panel A, Production is 5.35% (1% level), Conservation 9.76% (5% level), and Conversion and Protection are not significant (Table IV; p. 1735).
- **Prices fall.** In official Production-zone statistics, one more district lowers prices by 1.7% (not significant) and raises logged quantity by 8.4% in the same year. After three years prices are down 3.4% (significant at 5%) and quantity is up 13.5% (Table V cols. 1-2, p. 1740; text p. 1739). The introduction rounds the price effect to 3.3% (p. 1710).
- Combining the satellite quantity effects with official prices gives a demand elasticity of about -2.27 in the short run and -2.41 in the medium run (p. 1741). With n = 5.5 districts per province in 2001, the Cournot formula predicts a semi-elasticity of 0.034, against 0.038 (short run) and 0.082 (medium run) estimated. The implied markup is about 0.08, compared with field bribe estimates of roughly 0.01-0.06 (and 0.08-0.16 for official "fees") of the wood price (pp. 1741-1743).
- **Oil and gas rents substitute for logging in the short run.** Each US$1 of per-capita oil and gas revenue lowers deforestation by 0.3% in the same year: 0.3% in Production/Conversion and 0.6% in Conservation/Protection (Table VI Panel A, p. 1748). A one-SD change (23.7) lowers deforestation by 7.1% and 14.2% in those zones (p. 1747).
- In the medium run, the immediate effect is -0.5% per US$1 but the sum L0-L3 is +0.2% and not significant. Equality of the sum and the immediate effect is rejected at 1% (Table VI Panel B; pp. 1748-1749).
- About 35% of the substitution effect disappears once the direct district-head election has been held (interaction 0.00175, significant at 10%, all forest) (Table VII, p. 1750; text p. 1749). Higher oil and gas revenue is associated with fewer candidates and larger winning coalitions, and has no effect on incumbent re-election (Online App. A.15, p. 1749).
- Version note: this QJE version contains no estimate of deforestation around election dates. Its only election variable is the post-direct-election dummy in Table VII.

## What it doesn't do  <!-- Gabriel -->
## Relevance to us     <!-- Gabriel: what we borrow, how we differ -->
