---
id: "0012"
title: "The close-out: Gabriel approves it, the tick merges it"
status: accepted
date: 2026-11-11
supersedes: null
---

# 0012: The close-out: Gabriel approves it, the tick merges it

Date: 2026-11-11. Status: accepted. Drafted by Claude for Gabriel; Gabriel
accepted it on 2026-11-11 by merging pull request #328, which added it with
the matching change to `src/terrain/campaigns/tick.py`. It replaces point 8
of decision 0010 and nothing else in it.

## The question

Decision 0010, point 8, says the close-out pull request touches owned paths,
"so Gabriel always merges it, after reading it". In practice he reads the
report on GitHub, and a review is already where GitHub asks a code owner to
say yes. Merging by hand is then one more step that adds no check. Can he
accept the report with the approval itself, without weakening any lock?

## Decision

1. **Gabriel approves the close-out pull request; the tick merges the
   approved commit.** When the close-out pull request is mergeable (the gate
   passes and GitHub reports no conflict) and the campaign's `owner` has
   approved its head commit with a GitHub review, the tick merges it at
   exactly that commit and posts "Close-out approved by @owner; merging PR
   #n." on the tracking issue.
2. **Only the owner's approval counts.** An approval by anyone else never
   leads to a merge. Neither does a review that requests changes, or an
   approval of an older commit: the approval must be the owner's latest
   review, on the head commit.
3. **Until then the tick asks once.** It posts, one time, "@owner the report
   is ready: PR #n. To accept it, open the pull request, choose Files
   changed, then Review changes, then Approve. It is then merged for you. To
   reject it, close the pull request."
4. **Rejecting is closing.** A closed close-out pull request is a blocked
   close-out, reported like any other block.

## What does not change

- Owned paths still need Gabriel's review. The ruleset on main requires a
  code owner's approval for them, and the agent App is not on the bypass
  list. The merge succeeds only because Gabriel approved that commit; after
  a later push the tick waits for his approval of the new head commit.
- The gate (`campaign-gate`) and its checks on the close-out: CI, the agent
  review of the head commit, and the close-out file list.
- Step pull requests still merge only through the gate, as decision 0010
  says. Nothing about them depends on a person's approval.
- The exploration/confirmation split, `confirm/` and the sealed half.
- The rest of decision 0010.

## Risks and how they are handled

- **An approval given by mistake.** It is the same click that already
  satisfied the ruleset; before this decision Gabriel then merged. To undo
  it, he dismisses his review or closes the pull request before the next
  tick runs.
- **A push after the approval.** `PullRequest.approvals` counts only reviews
  of the head commit, and the merge names that commit, so new commits are
  never merged on an old approval.

## How we will know it works

The next campaign's close-out is merged by the tick within minutes of
Gabriel's approval, at the commit he approved, with no merge by hand.
