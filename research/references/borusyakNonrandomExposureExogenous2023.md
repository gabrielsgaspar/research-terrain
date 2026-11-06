---
citekey: borusyakNonrandomExposureExogenous2023
doi: 10.3982/ECTA19367
zotero_key: XVVUFBPZ
status: core
role:
strands: []
links: []
---
## Question            <!-- agent-drafted, confirm -->

(drafted; check) A methods paper. How can one estimate causal effects of treatments or instruments that combine several sources of variation by a known formula, when only some of those inputs are exogenous shocks and the others (exposure to the shocks) are not random? Examples are network spillovers, market access, and simulated policy-eligibility instruments (pp. 2155–2156). The paper shows that conventional regressions can suffer omitted-variable bias (OVB) from nonrandom exposure. It proposes recentering by the expected treatment or instrument, computed over counterfactual shocks (p. 2156).

## Setting and data    <!-- agent-drafted, confirm -->

(drafted; check) The framework is general (Section 3). Three stylised motivating examples run through Section 2 (pp. 2158–2162):

- spillovers from deworming in a network (Miguel and Kremer 2004);
- railroad market access growth (Donaldson and Hornbeck 2016);
- Medicaid eligibility, combining state policy with household income and demographics (Currie and Gruber 1996).

Empirical application (Section 4, pp. 2170–2175; Appendix A, pp. 2176–2177):

- **Units and period.** Chinese high-speed rail (HSR) in 340 prefectures, 2007–2016; 275 prefectures have usable outcome data.
- **Treatment.** Log market access (MA) growth, with MA_it = Σ_j exp(−0.02·τ_ijt)·Pop_j,2000, where τ is predicted travel time.
- **Outcome.** Urban employment growth from the China City Statistical Yearbooks.
- **Network.** 83 HSR lines opened between 2007 and 2016. A further 66 were completed or under construction by April 2019 (p. 2171).

## Identification      <!-- agent-drafted, confirm -->

(drafted; check) **Setup (Section 3.1, pp. 2163–2164).**

- Model: y_i = βx_i + ε_i (eq. 2), with scalar, demeaned variables. Observations need not be iid.
- Candidate instrument: z_i = f_i(g; w) (eq. 3). Here f_i are known functions, g is a K×1 vector of shocks, and w holds predetermined variables of unrestricted dimension. Setting x_i = z_i gives the formula-treatment case.
- **Assumption 1 (shock exogeneity, p. 2163):** g ⊥ ε | w. This combines an exclusion restriction with as-good-as-random assignment, and leaves E[ε_i | w] unrestricted. Footnote 13 says the identification results hold under the weaker condition E[ε | g, w] = E[ε | w].
- Identification is defined through the full-sample moments: relevance E[(1/N)Σ z_i x_i] ≠ 0 and orthogonality E[(1/N)Σ z_i ε_i] = 0 (p. 2164).

**Expected instrument and recentering (Section 3.2, pp. 2164–2165).**

- Define μ_i = E[f_i(g; w) | w].
- Under Assumption 1 alone, E[(1/N)Σ z_i ε_i] = E[(1/N)Σ μ_i ε_i] (eq. 4), by iterated expectations. So orthogonality generally fails, and μ_i is the sole confounder.
- The recentered instrument z̃_i = z_i − μ_i satisfies E[(1/N)Σ z̃_i ε_i] = 0, so β is identified by IV with z̃_i if z̃_i is relevant (p. 2165).
- Alternative: control for μ_i while instrumenting with z_i (control-function approach, p. 2165; fn. 17 cites Appendix B.1 of the 2021 working paper).
- Conventional controls or fixed effects purge OVB only if they linearly span μ_i (p. 2165). In panels, unit fixed effects work only when μ_it is time-invariant, which needs a stationary shock distribution (fn. 18).
- Footnote 16: z̃_i = E[x_i | g, w] − E[x_i | w] is relevant whenever Var[E[x_i | g, w] | w] is not almost surely zero for some i.

**Computing μ_i (Section 3.3, pp. 2166–2167).**

- **Assumption 2 (known assignment process):** G(g | w) is known on the support of w. Then μ_i = ∫ f_i(γ; w) dG(γ | w).
- Assumption 2 is satisfied by:
  - randomisation protocols, as in RCTs and lotteries;
  - scientific knowledge of natural processes, such as weather or seismic shocks;
  - local randomisation at RD cutoffs (Lee 2008);
  - in observational data, permutations. If the g_k are iid, μ_i = (1/K!) Σ_π f_i(π(g); w) (p. 2166), approximated with random permutations. Within-cluster permutations work under weaker exchangeability.
- Footnote 19: any number S of independent simulated draws preserves identification.
- If G is uncertain, controlling for several candidate μ_i purges OVB as long as one of them is correct (or there was no OVB to begin with). This is a robustness check (p. 2167, fn. 20).

**Consistency (Section 3.4, pp. 2167–2169).**

- Estimator: β̂ = (Σ z̃_i y_i)/(Σ z̃_i x_i).
- **Assumption 3 (weak mutual dependence):** E[(1/N²) Σ_{i,j} |Cov(z̃_i, z̃_j | w)|] → 0.
- **Proposition 1:** under Assumptions 1–3 and bounded E[ε_i² | w], Var[(1/N)Σ z̃_i ε_i] → 0. There is no restriction on dependence among the ε_i. Proposition 2 (Appendix C) shows Assumption 3 is also necessary if convergence must hold for all error distributions.
- Lower-level conditions (Appendix C, pp. 2178–2179):
  - Proposition 3: Assumption 3 requires K → ∞ when f_i is Lipschitz.
  - Proposition 4: Assumption 3 holds if an HHI-type measure of average shock exposure vanishes (binary, normal or linear shocks; monotone f; independent shocks).
  - Proposition 5: Assumption 3 holds if most pairs of observations depend on non-overlapping sets of shocks.
  - Proposition 6, first stage: with a linear first stage x_i = πz_i + u_i, π ≠ 0, the first-stage moment stays bounded away from zero if the average individual-exposure HHI stays above zero.
- Consistency also holds with a fixed number S of simulations (fn. 21).

**Randomisation inference (Section 3.5, pp. 2169–2170).**

- **Test statistic:** T = (1/N) Σ (f_i(g; w) − μ_i)(y_i − b·x_i).
- Under H0: β = b and Assumption 1, the distribution of T given (ε, w) is implied by G(g | w). Simulate it by redrawing g, and invert the test to get a confidence set.
- Size is correct in finite samples of observations and shocks, conditionally and unconditionally (pp. 2169–2170; Appendix C.3 of the 2021 working paper).
- β̂ is the Hodges–Lehmann estimator for this T (Lemma 2 of the working paper), and the test is consistent (Proposition S2 of the working paper).
- Confidence sets come from test inversion, not from the distribution of β̂ across counterfactuals (fn. 28).
- The procedure relies on a sharp constant-effect null (fns. 26, 30).
- **Falsification tests:** z̃_i must be orthogonal to any r_i with g ⊥ r | w.
  - Test statistic T = (1/N)Σ z̃_i r_i.
  - For several variables, use the sum of squared fitted values z̃′R(R′R)⁻¹R′z̃ (fn. 29).
  - Lagged outcomes test Assumption 1. Setting r_i = 1 or r_i = μ_i tests Assumption 2 (p. 2170).

**Extensions (Section 3.6, p. 2170).**

- With heterogeneous effects, recentered IV identifies a convex-weighted average under first-stage monotonicity, with weights proportional to σ_i² = Var(z̃_i | w).
- The rescaled instrument (z_i − μ_i)/σ_i² identifies the average effect in y_i = β_i z_i + ε_i, and the LATE with binary x and z.
- Controls, multiple treatments and nonlinear models are covered in Appendices C.6–C.8 of the working paper.

**Recommendation (Section 5, p. 2176).**

- With a true randomisation protocol, recenter first, then add predetermined controls.
- In natural experiments, control for one or several candidate μ_i, a "double-robustness" property.

**Application design (pp. 2173–2174).**

- The 2016 completion status is permuted between built and planned-but-unbuilt lines, only among lines with the same number of cross-prefecture links. Built lines average 3.19 links against 2.44 for unbuilt lines (p = 0.048).
- This gives 1999 counterfactual networks.
- Standard errors are Conley spatial with a 500 km bandwidth, plus RI confidence intervals.

## Main result         <!-- agent-drafted, confirm; include magnitudes -->

(drafted; check) **Formal results.**

- OVB equals E[(1/N)Σ μ_i ε_i] (eq. 4, p. 2164).
- Recentering by μ_i, or controlling for it, restores orthogonality under Assumption 1 alone (p. 2165).
- Consistency under Assumptions 1–3 (Proposition 1, p. 2167).
- Exact finite-sample RI with the statistic T (Section 3.5, p. 2169).
- Convex-weighted average under heterogeneous effects (Section 3.6, p. 2170).

**Chinese HSR application, Table I (p. 2172; text pp. 2171, 2174–2175).**

| | Unadjusted OLS (col. 1) | Recentered IV (col. 2) | OLS controlling for μ (col. 3) |
|---|---|---|---|
| Panel A, no controls: MA growth | 0.232 (0.075) | 0.084 (0.097), RI CI [−0.245, 0.337] | 0.072 (0.093), RI CI [−0.169, 0.337] |
| Panel A: expected MA growth | | | 0.317 (0.096) |
| Panel B, geography controls: MA growth | 0.133 (0.064) | 0.056 (0.089), RI CI [−0.135, 0.280] | 0.047 (0.092), RI CI [−0.146, 0.280] |
| Panel B: expected MA growth | | | 0.214 (0.073) |

- Panel B controls are distance to Beijing, latitude and longitude.
- The unadjusted elasticity, with mean MA growth of 0.54 log points, implies 12.4% employment growth from HSR for the average prefecture, almost half of the 26.6% average growth (p. 2171).
- Neither adjusted estimate is distinguishable from zero.
- The authors read the 0.32 coefficient on expected MA growth as employment growing faster where prefectures were more exposed to potential HSR, whether or not nearby lines had been built (p. 2175).

**Table II (p. 2173).**

- Distance to Beijing, latitude and longitude explain R² = 0.824 of unadjusted MA growth.
- For recentered MA growth, R² = 0.083 with joint RI p = 0.443.
- Recentered MA growth on expected MA growth gives a coefficient of 0.026 (0.056), R² = 0.010, p = 0.711.
- The authors read this as consistent with a correctly specified assignment process. They say it does not directly support Assumption 1 (fn. 35, p. 2174).

## What it doesn't do  <!-- Gabriel -->
## Relevance to us     <!-- Gabriel: what we borrow, how we differ -->
