# Follow-up to the 2026-11-07 run: your choices, tasks 37 and 38

For Gabriel. You reviewed `harness/reports/2026-11-07-autonomous-run.md` and
asked that your choices be recorded and the next step run under handoff 5's
rules and hard stops. Session projects-4c did all of it. Every step is in
`harness/AUTONOMY_LOG.md`, under "Follow-up: Gabriel's choices on the run
report".

## 1. What was done

| What you asked | What | Links | State |
| --- | --- | --- | --- |
| Confirm decision 0008 | Your acceptance under its "Accepted" section | #222 | merged |
| Decision 0009 for the plan | Your five points, in your words, plus kill criterion 1's counts at 0.25% | #230; task 38: issue #224, build #225, run [42384056410](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42384056410), record #228 | merged |
| Update the plan draft | `harness/drafts/pap-draft.md`, framed as a registered test of the direct effect; still "Draft; nothing here is registered" | #230 | merged |
| Mark idea 0003 dead | Kill criteria confirmed (texts unchanged), dead by kill criterion 1 | #222 | merged |
| Task 37 | Aligned and unaligned pairs at 0.25% for idea 0004; counts and implied power in the idea file | draft #222; issue #223, build #226, fix #229 / #231, run [42384829937](https://github.com/gabrielsgaspar/research-terrain/actions/runs/42384829937), record #232, idea and lessons #233 | merged (one fix round) |
| Label PR #213 | Label "unverified; drafted from memory; do not merge"; PR left open | #213 | labelled, open |
| Task 35's row | `harness/issue-drafts/README.md` row 35 now "done (#212; record #219, decision 0008)" | #222 | merged |
| — | This report | {{REPORT_PR}} | |

## 2. Results

### Kill criterion 1 at 0.25% (idea 0001, task 38)

**Numbers.** On the exploration half, pooled 2008-2024, at 0.25%: **434**
close-pair candidates have a stronghold in or within 5 km of an indigenous
land, and **1,625** of a settlement (5,738 candidates, twice the 2,869
pairs). At 0.50% the same run gives 711 and 2,590, the same as run
41839642406 in every cell.

**What it means.** Under decision 0009, kill criterion 1 is read at the
registered window, and it is not met there (minimum 200). If the
confirmation half is about as large, the indigenous count would clear the
bar by about two to one.

**Limits.** Exploration half only. The count of indigenous-side candidates
(434) is about 61% of the 0.50% count, so a much smaller confirmation half
could come closer to 200. That is unlikely, because the split is stratified.

### Alignment with the mayor (idea 0004, task 37)

**Numbers.** Close pairs at 0.25%, pooled 2008-2024: **1,414 aligned, 1,446
unaligned, 4 mixed**, and 5 left out (all in 2008: 3 with an unmatched
side, 2 with an unmatched mayor). In 2008-2020: 1,100 aligned and 1,219
unaligned. The implied power for an aligned-minus-unaligned gap of one
effect size (8%) is **0.335**. The best case, an even split, gives 0.337.

**What it means.** Drafted kill criterion 1 (fewer than 200 of either) is
not met, so idea 0004 has enough pairs to estimate. But it cannot test
moderation at 80% power on a half of this size. Drafted kill criterion 3
would read "cannot be applied". By the same scaling, 80% needs a gap of
about 1.8 effect sizes.

**Limits.** The power is a rough scaling of decision 0008's direct power
(0.868 on 2,328 pairs). It assumes each group's slope has variance
proportional to 1 over its pairs. It is not computed on outcomes, as you
asked. Alignment is fixed by the mayoral race, not randomised, so a
difference would be heterogeneity, not an effect of alignment.

## 3. Decisions taken by rule, judgement calls, and stops

**Decisions accepted by rule:** none. Decisions 0008 (your acceptance) and
0009 record your own choices.

**Judgement calls you may want to check:**

- **Decision 0009's "What follows from it"** is my reading, not yours. With
  displacement secondary, kill criterion 4 is read on the direct effect
  alone, at 5% two-sided (Holm over one test), where decision 0007 used
  0.025 for two tests. A clearly non-zero displacement effect still means
  "not met" by the criterion's text, but cannot kill. The balance fallback
  is triggered by any covariate, though the adjustment is for incumbency
  only.
- **The incumbency adjustment** in the plan draft (section 4) is a
  proposal. It adds one regressor: the exposure of the side that held the
  seat minus the side that did not, summed over pairs whose sides differ in
  incumbency. It does not change under re-flips, so the RI test stays
  valid.
- **0009 lists 0007 as superseded** only for "How kill criteria 3 and 4 are
  applied" on the confirmation half. Decision 0007's file was not edited,
  and its status is still `accepted`.
- **Idea 0003's kill criteria:** the "(drafted; confirm)" marks were
  removed and the texts kept as drafted.
- **Label name:** GitHub rejects commas in label names, so your commas
  became semicolons. A second label, created by mistake while testing
  names, was deleted at once.
- **Referee rows R4 and R5 "Not applicable"** on #225, #226 and #231
  (counts only, no inference) were read as no referee problem, as in the
  last run.
- **Disk:** the scratch disk filled up once; I deleted the rebuildable
  Python environments of finished worktrees. No data or branch was touched.

**Stops hit:** one, contained. Record PR #227 (task 37's first run) had the
expected counts, but its verdict on kill criterion 1 was inverted: it said
"met" for 1,414 and 1,446. Notes that do not match are a stop for a record,
so I did not merge it and did not edit it. A fix (issue #229, PR #231,
reviewed and approved) flipped the verdict only. The re-run (42384829937)
gave identical counts with the right verdict, and its record (#232) was
merged. #227 is closed and its branch kept. The cause was partly my draft's
wording: "(200 each) is met" was ambiguous, and the issue had no test of
the verdict's direction. A harness lesson and a new filing checklist item
cover it.

No file under `sealed/` or `confirm/` was read. No outcome was read in
either task, and no identifier was committed or printed. Nothing touched
permissions, secrets, workflows or rulesets.

## 4. What needs you now

1. **Check decision 0009's "What follows from it"** (kill criterion 4 at 5%
   on the direct effect alone; the fallback triggered by any covariate).
   *Recommendation: accept both.* They are the plainest readings of your
   five points.
2. **The incumbency adjustment's specification** (plan draft, section 4).
   *Recommendation: accept it.* It is the only form I found that stays
   fixed under re-flips.
3. **When to spend the confirmation half.** The plan is now a test of the
   direct effect at 0.868 power, with kill criterion 1 passing.
   *Recommendation: rewrite the draft in your words into `confirm/pap/` and
   register it.* Idea 0004 is not a reason to wait: it cannot test
   moderation at 80% (power 0.34).
4. **Idea 0004.** Confirm its drafted kill criteria, or retire it.
   *Recommendation: keep it as a secondary, descriptive split of the
   registered direct effect* (aligned and unaligned slopes reported, no kill
   role), or mark it dead under drafted kill criterion 3 once confirmed. A
   standalone design would need a gap of about 1.8 effect sizes.
5. **PR #213 (party lineage)** stays open under its new label. *No action
   needed* unless idea 0004 ever goes across elections.
