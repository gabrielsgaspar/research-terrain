---
id: "0004"
title: "Council effects moderated by alignment with the elected mayor"
status: proposed
created: 2026-11-07
updated: 2026-11-07
datasets:
  - tse_results
  - tse_parties
  - tse_candidates
  - municipalities
  - section_votes
  - polling_places
  - polling_place_types
  - polling_place_tenure
  - grid_cells
  - cell_exposure
  - cell_outcomes
kill_criteria:
  - "(drafted; confirm) Too little variation: fewer than 200 close pairs (decision 0008's window, 2008-2024 pooled, exploration half) are aligned, or fewer than 200 are unaligned."
  - "(drafted; confirm) A non-flat placebo: in the four years before the election, the aligned-minus-unaligned difference in the direct slope (`exp2`) is non-zero (randomisation-inference p below 0.05) on the exploration half."
  - "(drafted; confirm) No moderation: the aligned-minus-unaligned difference in the direct slope is indistinguishable from zero (two-sided 5%), with at least 80% power for a gap of one effect size (decision 0007's 8%, read as its option A)."
related: ["0001"]
---

# 0004: Council effects moderated by alignment with the elected mayor

## Claim

A councillor can deliver for their voters mainly through the mayor, who runs
the executive. So a narrow council win should change land use around the
winner's stronghold more when the winner is aligned with the elected mayor
than when they are not.

## Prediction

Working version, to be fixed in a pre-analysis plan before any post-election
outcome is read:

- The direct effect of idea 0001 (`exp2`) is larger in absolute value for
  aligned close pairs than for unaligned ones.
- The same difference in the four pre-election years: zero (placebo).

Against the idea: no difference with adequate power, or a non-flat placebo.
Alignment is the **only** moderator (Gabriel, 2026-11-07). Ideology and party
splits are not explored, so this idea adds one comparison, not a search.

## Design

- **Alignment.** A council candidate is aligned if their party is in the
  winning mayor's coalition in the same election (`tse_parties`, the
  coalition rows of the mayoral race; the winner from `tse_results`, deciding
  round). From 2024, a party in a federation counts as in the coalition when
  its federation is.
- **Why it can be used as a moderator.** The mayoral race is decided the same
  day, by different votes; which of two council candidates narrowly wins does
  not change who became mayor. So alignment is fixed with respect to the
  council coin flip. It is not randomly assigned: aligned and unaligned pairs
  can differ in other ways (party size, municipality), so a difference is
  heterogeneity, not an effect of alignment.
- **Pairs.** Idea 0001's within-list close pairs. Before 2020, a list is a
  coalition, so the two sides of a pair can be from different parties and
  differ in alignment. A pair is aligned when both sides are, unaligned when
  neither is, and mixed otherwise. Mixed pairs (before 2020 only) are counted
  and reported, and left out of the contrast. From 2020 lists are parties, so
  no pair is mixed.
- **Estimate.** Idea 0001's direct slope, estimated separately on aligned and
  unaligned pairs, with one set of re-flips shared by both; the statistic is
  the difference. Window from decision 0008, effect size from decision 0007.

**Party lineage.** Parties were renamed or merged over 2008-2024 (PMDB to
MDB, PR to PL, PRB to Republicanos, DEM and PSL to União, ...). Alignment in
one election compares that election's own party codes, so it does not need a
lineage. Anything that follows a party across elections does (party fixed
effects, alignment with the previous mayor, pooling by party). The lineage
table would live in `data/reference/` (protected): a proposal is drafted for
Gabriel to review and is not merged.

## Data needed

`tse_results`, `tse_parties`, `tse_candidates`, `municipalities`, and idea
0001's geography and outcome datasets (`section_votes`, `polling_places`,
`polling_place_types`, `polling_place_tenure`, `grid_cells`, `cell_exposure`,
`cell_outcomes`). All exist. The party-lineage table exists only as a
proposal.

## Status

- 2026-11-07: proposed. Alignment with the elected mayor is the only
  moderator, fixed before any outcome is read. No task yet; the first step
  would count aligned, unaligned and mixed close pairs (kill criterion 1).
- 2026-11-07: still proposed. Close pairs at 0.25% (decision 0008) on the
  exploration half, pooled 2008-2024 (run 42384829937): **1,414 aligned,
  1,446 unaligned, 4 mixed** (5 left out for an unmatched side or mayor, all
  in 2008), so drafted kill criterion 1 (fewer than 200 of either) is not
  met. In 2008-2020 there are 1,100 aligned and 1,219 unaligned. **Implied
  power** for an aligned-minus-unaligned gap of one effect size (8%),
  two-sided 5%, is about **0.34** (0.337 for an even split, the best case),
  a rough scaling of decision 0008's direct power (0.868 on 2,328 pairs),
  not a computation on outcomes. Drafted kill criterion 3 needs 80% power,
  so on a half of this size it would read "cannot be applied". Kill
  criteria are still drafts until Gabriel confirms them.

## Log

- 2026-11-07: idea file written (Claude Code, autonomous run; Gabriel to
  review). Kill criteria are drafts until Gabriel confirms them.
- 2026-11-07: aligned and unaligned pair counts at 0.25%: issue #223, PR
  #226, fix issue #229 and PR #231 (the first run's verdict was inverted;
  record #227 not merged), run 42384829937
  (`research/explore-runs/0004/42384829937.md`), record PR #232;
  `research/lessons.md` entry of the same date.
