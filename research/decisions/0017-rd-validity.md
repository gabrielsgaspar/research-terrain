---
id: "0017"
title: "Regression discontinuity designs from idea 0012 on"
status: proposed
date: 2026-11-22
supersedes: null
---

# 0017: Regression discontinuity designs from idea 0012 on

Date: 2026-11-22. Status: proposed, drafted by Claude for Gabriel from his
brief of 2026-11-22 (campaign 0014). It takes effect when Gabriel merges
the pull request that adds it, with idea 0012
(`research/ideas/0012-incumbency-curse.md`) and campaign 0014
(`research/campaigns/0014-incumbency-curse/`). It narrows where decision
0008 applies (point 6) and changes nothing else in it.

## The question

Decision 0008 chooses a close-race window by a local-randomisation rule:
differences in means of predetermined covariates inside nested windows,
the widest window whose omnibus p is at least 0.15, stopping at the first
failure. Idea 0011 (campaign 0012) paired that rule with a local linear
regression discontinuity estimator, and the gate stopped before any
outcome was read (`research/explore-runs/0011/44768996266.md`): the
smallest window, 0.5%, failed narrowly (omnibus p 0.07 against 0.15,
while 1%, 2% and 3% passed), and the count, power and placebo rules were
then computed at 0.5%, with 58 to 71 races per election.

Two flaws in that pairing:

1. **Rule and estimator disagree.** A difference in means inside a wide
   window picks up the slope of a covariate in the margin, which a local
   linear model removes. So the rule tests something the estimator does
   not assume. And at its first window the rule stops a perfectly valid
   design 15% of the time by construction (an omnibus p below 0.15).
2. **The power limit was stricter than the hypothesis.** Idea 0011 asked
   for a minimum detectable difference of 0.10, without a published
   effect size behind it.

How should a regression discontinuity design choose its bandwidth, test
its validity and set its gates?

## Decision

For regression discontinuity designs of ideas 0012 and later:

1. **Bandwidth and kernel are stated in the idea file before any data of
   the design is read**, with their source: a published study of the same
   population, or counts that use no outcome. No balance test chooses
   them.
2. **Validity is tested with the estimator itself.** The design's own
   model is fitted with each predetermined covariate, and each lagged
   outcome, as the outcome. p-values come from randomisation inference.
   One omnibus p covers the predetermined covariates: the smallest p,
   set against the re-flip distribution of the smallest p. Lagged
   outcomes are tested the same way and gated by point 3.
3. **Gates.**
   - An omnibus p below 0.05 stops the design. This stops a valid design
     1 time in 20.
   - A lagged-outcome jump stops it only if it is both larger than a size
     stated in the campaign and significant at 5%.
4. **Power limits are stated against a published or otherwise pre-stated
   effect size.**
5. **Robustness bandwidths are declared with the design, and all are
   reported.**
6. **Decision 0008's table is still computed and shown** in the gate
   record (differences in means in nested windows), as information. For
   ideas from 0012 on it neither chooses a window nor stops a design.
   Ideas 0001 to 0011 keep decision 0008 as it applied to them; idea 0010
   keeps its 7.5% window.

## What does not change

Decision 0008 for ideas 0001 to 0011, and every window it chose; the
exploration/confirmation split; randomisation inference by re-flipping
races; that kill rules are confirmed by Gabriel before a campaign starts;
that nothing on the exploration half is a finding.

## Risks and how they are handled

- **A borrowed bandwidth may not fit this sample.** The robustness
  bandwidths (point 5) are declared with the design and all reported, so
  a result that holds at one bandwidth only is visible.
- **A lower bar for validity.** 0.05 instead of 0.15 stops fewer valid
  designs, and also fewer invalid ones. Point 2 tests the assumption the
  estimator makes (no jump in a covariate at the cutoff), which is the
  one that matters; the lagged-outcome rule adds a size condition, so a
  tiny but significant jump in a large sample does not stop a design.
- **Formed after a stop.** This decision was written after campaign
  0012's gate failed. It is not applied to idea 0011, which stays dead;
  idea 0012 says so in its own file.

## Where it is used

- The `campaign-design` skill and its `references/kill-rules.md` point
  here for regression discontinuity designs.
- First use: idea 0012, campaign 0014 (step s2, the gate).
