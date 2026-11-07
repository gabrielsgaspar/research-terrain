---
id: "0008"
title: "The close-race window, chosen by covariate balance"
status: accepted
date: 2026-11-07
supersedes: null
---

# 0008: The close-race window, chosen by covariate balance

Date: 2026-11-07. Status: accepted by rule (see "Accepted" below); Gabriel to
review. The pre-analysis plan uses this window.

## The question

Which close-race window (|margin| as a share of the municipality's valid
council votes) does the design use? The 0.50% used so far was a judgement.
Handoff 4 (Gabriel, 2026-11-06) fixed a method before any balance was seen:
the local-randomisation window choice of Cattaneo, Frandsen and Titiunik
(2015, J. Causal Inference 3(1)), using pre-election characteristics only.
The rule was written into issue #206 before the run, and this decision
applies it. Nothing is chosen by judgement here.

## The rule (issue #206, fixed before the run)

- Windows: 0.10%, 0.25%, 0.50%, 0.75%, 1.00%, 1.50%, 2.00%. Pairs and margins
  as in `terrain.strongholds`; elections 2008-2024 pooled; exploration half.
- Ten balance covariates: female, age, schooling, incumbent (rebuilt from the
  previous election's elected councillors; `ST_REELEICAO` is reported, not
  used), distance to the municipal seat, place type (seat, town), distance to
  indigenous land and to a settlement, and the pre-election clearing share
  (E-4..E-1 within 5 km of the stronghold). The 2022 population within 5 km
  is descriptive only, because it is measured after the 2008-2020 elections.
  Coalition membership is left out.
- Per window and covariate: the winner-minus-loser mean difference and its
  randomisation p from 2,000 re-flips of the pairs (seed 20261106, the same
  sign vectors for every covariate and window). Omnibus p per window: the
  minimum p across covariates, set against the re-flip distribution of that
  minimum.
- **The chosen window is the widest window with omnibus p at least 0.15 whose
  smaller windows are all at least 0.15.** Once a window fails, no wider
  window can be chosen. If 0.10% fails, no window is chosen and Gabriel
  decides.
- Power is reported for each window and is not used to choose.

## Evidence

`explore/0001_window.py`, run 42366460941
(`research/explore-runs/0001/42366460941.md`), record PR #219. No outcome
after any election was read. Pairs per window match the feasibility census
(run 41719271978) to the unit, in every election, at 0.25%, 0.50%, 1% and 2%.

**Omnibus p per window** (smallest raw p, and the covariate it comes from):

| Window | Pairs (2008-2024) | Omnibus p | Smallest raw p | Passes 0.15? |
| --- | --- | --- | --- | --- |
| 0.10% | 1,289 | 0.191 | 0.023 (distance to indigenous land) | yes |
| **0.25%** | **2,869** | **0.548** | 0.084 (incumbent) | **yes** |
| 0.50% | 4,575 | 0.119 | 0.014 (incumbent) | **no** |
| 0.75% | 5,697 | 0.0005 | 0.0005 (incumbent) | no |
| 1.00% | 6,471 | 0.0005 | 0.0005 (incumbent) | no |
| 1.50% | 7,364 | 0.0005 | 0.0005 (incumbent) | no |
| 2.00% | 7,836 | 0.0005 | 0.0005 (incumbent) | no |

0.0005 is the smallest p 2,000 re-flips can give.

**Incumbency, winner minus loser** (share of the pair who held the seat
before; RI p in brackets): 0.10% +0.011 (0.53); 0.25% +0.020 (0.084); 0.50%
+0.023 (0.014); 0.75% +0.034 (0.0005); 1.00% +0.043; 1.50% +0.055; 2.00%
+0.064 (all 0.0005). Age is the only other covariate below 0.05 in some
window: winners are 0.35 and 0.40 years younger at 1.50% and 2.00% (p 0.028
and 0.010). The full balance table is in the run record.

**Power at decision 0007's 8%**, mean exposure, elections 2008-2020
(pre-election clearing only):

| Window | Pairs (2008-2020) | Direct | Displacement | Split (5 km), one-sided |
| --- | --- | --- | --- | --- |
| 0.10% | 1,062 | 0.605 | 0.350 | 0.259 |
| **0.25%** | **2,328** | **0.868** | **0.622** | **0.307** |
| 0.50% | 3,684 | 0.944 | 0.797 | 0.448 |
| 0.75% | 4,589 | 0.936 | 0.835 | 0.548 |
| 1.00% | 5,182 | 0.955 | 0.891 | 0.528 |
| 1.50% | 5,855 | 0.956 | 0.926 | 0.548 |
| 2.00% | 6,172 | 0.941 | 0.901 | 0.516 |

The 0.50% row reproduces decision 0007 (0.94, 0.797, 0.45), although the
exposure cells were rebuilt for this run. At 0.25% there are 280
indigenous-side and 1,257 settlement-side candidates at 5 km (455 and 1,987
at 0.50%).

## Decision

**The close-race window is 0.25%** of the municipality's valid council votes
(omnibus p 0.548; 0.10% also passes, at 0.191). 0.50% fails (0.119), so no
wider window can be chosen.

### What it means for task B's 0.50% result (run 42298466207)

0.50% is **not balanced** under this rule: its omnibus p is 0.119, below
0.15. The imbalance is incumbency: narrow winners at 0.50% held the seat
before 2.3 percentage points more often than narrow losers (RI p 0.014).
Task B's result stands as pre-specified: kill criteria 3 and 4 "cannot be
applied at 80% power on this half". **It is reported with this caveat**: the
winner-loser contrast at 0.50% partly mixes winning the seat with having held
it before, so its estimates are not clean local-randomisation estimates.
The balance pools 2008-2024; task B used 2008-2020, so the caveat rests on a
pooled imbalance and was not re-tested on task B's years.

### What it means for the pre-analysis plan

- The confirmation half uses 0.25%. On this half that window has about 63%
  of the 0.50% pairs (2,328 against 3,684, 2008-2020), and power at 8% of
  0.868 (direct), 0.622 (displacement) and 0.307 (split). If the
  confirmation half is about as large, kill criterion 4's displacement
  branch and kill criterion 3 will both be below 80% power, by more than at
  0.50%.
- The incumbency difference at 0.25% (+0.020) is close to the one at 0.50%
  (+0.023). 0.25% passes mainly because it has fewer pairs, so the test is
  less able to detect a gap of that size, not because the gap is gone. The
  pre-analysis plan should report incumbency balance in the chosen window,
  and say whether incumbency enters as a control.
- Kill criterion 1 is written for 0.5% and is not changed (accepted
  criteria are not edited here). At 0.25% the 5 km counts (2008-2020) are
  280 indigenous-side and 1,257 settlement-side candidates, both above 200.
- No estimate of task B is re-run at 0.25% on this half. That would be a
  post-election outcome analysis not specified in any merged issue.

## Caveats

- Exploration half only; the confirmation half's balance is not known.
- The omnibus test pools 2008-2024; 2024's pairs have no post-election
  outcome yet and do not enter the power table.
- Power uses pre-election clearing (E-4..E-1) as in decision 0007, with
  exposure cells rebuilt per window. This run did not repeat the power run's
  term checks.
- The rule's 0.15 threshold and the covariate list were fixed before the run
  (handoff 4, issue #206). If Gabriel changes either, this decision is
  superseded, not edited.

## Accepted

Accepted by rule (Claude Code, autonomous run); Gabriel to review.
The rule was fixed in issue #206 before the run; run 42366460941 applied it
on 2026-11-07 and chose 0.25%.
