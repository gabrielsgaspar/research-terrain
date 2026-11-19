---
id: "0016"
title: "Repairs see the failure, and may add only bounded data rules"
status: proposed
date: 2026-11-19
supersedes: null
---

# 0016: Repairs see the failure, and may add only bounded data rules

Date: 2026-11-19. Status: proposed, drafted by Claude for Gabriel from his
request of 2026-11-19 (lessons of campaigns 0009 to 0011). It takes effect
when Gabriel merges the pull request that adds it, with
`src/terrain/profile.py`, `src/terrain/datarule.py`,
`scripts/profile_failure.py`, the changes to the repair template, the gate,
the tick and the GitHub reader in `src/terrain/campaigns/`, the two
workflow changes and the `AGENTS.md` change. It amends decision 0014
(points 3 and 5, and the risk "A fix that hides a data problem") and
nothing else.

## The question

Campaign 0009's repair (#410) could not plan a fix. The error line said
"2026: 2378 of 55898 recipient rows match no municipality", but nothing
said why, and the true cause, a placeholder 'Sem informação' in the CGU
file, came from Gabriel by hand (PR #411). That fix was a data rule: one
class of rows treated differently. The repair template forbade it ("the
same rows"), so even a planner who guessed the cause had to block. Can a
repair see what Gabriel saw, and make a fix like his, without being able to
hide a data problem?

## Decision

1. **The error line.** The GitHub reader reads the failed job's whole log
   and keeps its last error line: a line that starts with "build failed:"
   or "acquire failed:", or names a BuildError. The repair issue quotes it
   under "## The error it stopped on", cleaned like the log. The gate's
   template check accepts any one such line there, and nothing else.
2. **The row counts.** A build check that can fail on real data counts the
   rows it examined, per period and category, and writes them with
   `terrain.profile.write_profile` before it raises. After a failed step,
   the `data-pipeline` workflow runs the fixed script
   `scripts/profile_failure.py`, which prints the counts between
   `profile: begin` and `profile: end`. The repair issue quotes the block
   under "## Rows by category". A profile holds a code label for the check,
   periods (years, year and month, or "all"), categories from the fixed
   list `terrain.profile.CATEGORIES` and whole numbers of rows: never a
   value or an identifier. Code refuses anything else at three points: when
   the build writes it, when the script prints it and when the tick reads
   it. The gate accepts only a block that passes the same check, or one of
   the fixed "none" lines.
3. **The reviewer.** The repair reviewer still never sees the log, and now
   not the error line either (it comes from the log). It does see the row
   counts: code lets only counts and fixed labels through.
4. **Bounded data rules.** A repair may add a data rule (code that treats
   one class of rows differently) only if all of these hold:
   1. it targets one named class of rows;
   2. it covers at most 1% of the step's key value (for example reais
      paid), or of its rows if the step has no key value, in every period.
      The build proves it: `terrain.datarule.check_rule` measures the share
      in each period, stops the build above 1%, and returns the line the
      build adds to its manifest notes;
   3. it changes no threshold, no check and no kill rule;
   4. it is listed in the close-out report: the tick copies the data-rule
      lines of the manifest that the run after the repair recorded into the
      Repairs table of the friction facts.
   Anything else (a rule over 1%, a looser check, a new source, a file
   outside the repair's list) blocks the repair for Gabriel, as before.

## What stays

Everything else in decision 0014: when a repair is filed, its limits (one
per step, two per campaign), its files, the template check, and that the
run after a repair is never retried or repaired again.

## Risks and how they are handled

- **A value leaks through a category.** Categories come from a fixed list,
  not from the data, and a period is a year or "all". A municipality name
  cannot pass as a category or a period. Counts have at most 10 digits, so
  none is shaped like a CPF or a voter ID number.
- **The log fakes a profile or an error line.** The scanner and the gate
  accept only the shapes above; a faked profile can at worst be wrong
  counts, which the planner reads as data. Headings quoted inside the log
  block are ignored.
- **A data rule hides a problem.** 1% in every period is small next to the
  limits the checks hold (2% for unmatched recipients in campaign 0009),
  the bound is enforced by code in the build, the share is in the manifest
  for anyone to read, and the close-out lists every rule. A rule that
  needs more than 1% is a decision for Gabriel.
- **Builds that do not count rows yet.** The issue says "no row counts"
  and the repair works from the error line, as before. New checks count
  rows (`AGENTS.md`, "Data").
