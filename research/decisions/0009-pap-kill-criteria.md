---
id: "0009"
title: "How the pre-analysis plan reads idea 0001's kill criteria on the confirmation half"
status: accepted
date: 2026-11-07
supersedes: "0007"
---

# 0009: How the pre-analysis plan reads idea 0001's kill criteria on the confirmation half

Date: 2026-11-07. Status: accepted (Gabriel, see "Accepted" below).

**What it supersedes.** Only the part of decision 0007 headed "How kill
criteria 3 and 4 are applied", as it would apply to the confirmation half.
The rest of 0007 stands: the effect size (8% of baseline four-year clearing
at the mean exposure), the gap reading of kill criterion 3, and the
secondary displacement outcome ΔY. Decision 0007's file is not edited, and
neither is idea 0001's kill-criteria text. Decision 0008's window (0.25%)
stands and is used throughout.

## The question

Decision 0008 chose a 0.25% close-race window. At that window, on the
exploration half (2,328 pairs, 2008-2020), power at 8% is 0.868 for the
direct effect, 0.622 for displacement and 0.307 for the constituency split.
If the confirmation half is about as large, kill criterion 3 and the
displacement branch of kill criterion 4 would almost surely read "cannot be
applied at 80% power". Kill criterion 1 is written for a 0.5% margin. Narrow
winners at 0.25% are still incumbents 2.0 points more often than narrow
losers (RI p 0.084). How does the plan read each criterion?

## Decision (Gabriel, 2026-11-07)

1. **Kill criterion 1's "0.5%" means the registered window**, 0.25% (decision
   0008). On the exploration half at 0.25%, pooled 2008-2024 (run
   42384056410, issue #224), 434 close-pair candidates have a stronghold in
   or within 5 km of an indigenous land and 1,625 of a settlement, both
   above 200, so kill criterion 1 is **not met** at 0.25%. (At 0.50% the
   same run gives 711 and 2,590, reproducing run 41839642406 in every
   cell.) Of the 434, 340 are in 2008-2020.
2. **The constituency split and the displacement effect are secondary.**
   Kill criterion 3, and the displacement branch of kill criterion 4, are
   reported with their power and are not used to kill the idea.
3. **Confirmation-half power is carried over from the exploration half.**
   The halves are a stratified random split of the same size (decision
   0001), so the exploration half's power at 0.25% (direct 0.868) stands in
   for the confirmation half's. **The sealed half is not read before
   registration**, not even its pre-election years.
4. **An incumbency-adjusted estimate of the direct effect is a registered
   robustness check.** It is reported next to the unadjusted estimate in
   every run of the plan.
5. **A failing confirmation-half balance test is reported, and the
   incumbency-adjusted estimate is the pre-specified fallback.** The
   confirmation half's balance table at 0.25% (issue #206's ten covariates
   and omnibus p) is printed first. If its omnibus p is below 0.15, the
   window is not re-chosen. The balance table is reported, and the
   incumbency-adjusted direct estimate becomes the estimate that kill
   criterion 4 is read on.

The confirmation is therefore **a registered test of the direct effect**
(H1), gated by kill criterion 1 and checked by the placebo (kill criterion
2). Displacement and the split are reported in full, as secondary
estimates.

## What follows from it (Claude Code's reading; Gabriel to check)

These follow from points 1-5 by the texts of the kill criteria. They are
written out so the plan can state them, not decided here.

- **Kill criterion 4** keeps its "not met if either effect is clearly
  non-zero" branch. Its "met" branch is now read on the direct effect alone:
  met if the direct effect is not clearly non-zero and its power (carried
  over, 0.868) is at least 0.80. With one confirmatory test, "clearly
  non-zero" is a two-sided RI p below 0.05 (Holm over one test). Decision
  0007 used Holm over two tests (the smaller p below 0.025). A clearly
  non-zero displacement estimate is still reported, and by the criterion's
  text it still means "not met". It cannot make the idea die.
- **Kill criterion 3** is reported as δ, its one-sided p and its power
  (about 0.31, carried over), with no verdict.
- **Kill criterion 2** (placebo) is unchanged. It applies to the direct
  exposure's pre-election clearing, and under point 5 it uses the same
  estimate as kill criterion 4.
- **The fallback in point 5** is triggered by any covariate, not only
  incumbency, because the omnibus pools all ten. The adjustment is for
  incumbency only, as decided. A failure on another covariate is reported
  as such.
- **The specification of the incumbency adjustment** is not fixed by this
  decision. The plan draft (`harness/drafts/pap-draft.md`) proposes one, for
  Gabriel to confirm before registration.

## Caveats

- Carried-over power assumes that the confirmation half's spread of
  pre-election clearing under re-flips is like the exploration half's. The
  split is stratified, so this is the expected case, but it is not checked,
  because checking would read the sealed half.
- At 0.25% the incumbency gap is close to 0.50%'s. The adjusted estimate
  removes the part of the contrast that incumbency predicts linearly. It
  does not make the comparison balanced on what incumbency stands for.

## Accepted

By Gabriel on 2026-11-07, in his review of the run report
(`harness/reports/2026-11-07-autonomous-run.md`): points 1-5 above, in his
words. Written by Claude Code at his request; the section "What follows from
it" is Claude Code's reading, for Gabriel to check.
