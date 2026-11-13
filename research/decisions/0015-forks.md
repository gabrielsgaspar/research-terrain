---
id: "0015"
title: "Forks: agent-proposed variants inside an approved envelope"
status: proposed
date: 2026-11-13
supersedes: null
---

# 0015: Forks: agent-proposed variants inside an approved envelope

Date: 2026-11-13. Status: proposed, drafted by Claude for Gabriel from his
request of 2026-11-13 and the brief `forks-workflow-update.md`. It takes
effect when Gabriel merges the pull request that adds it (with the formats
and the validator in `src/terrain/campaigns/forks.py` and `spec.py`, the
kill-rule library, the approved publishers, CODEOWNERS and the `AGENTS.md`
change). The machinery that files forks comes in the next pull requests:
until it is merged, no fork can be proposed, so nothing runs differently.
It amends decision 0010, point 8, and nothing else in decisions 0010, 0012,
0013 or 0014.

## The question

Campaign 0007 stopped at its second gate: gold measured as the density of
gold sites gave a first-stage F of 2.44, where the kill rule needed at least
10. The same run showed, as a side result, that a yes/no measure gives
F 12.28. The campaign could not act on that: it closed, a person diagnosed
it, and campaign 0008 had to be designed by hand. The workflow is closer to
the data than Gabriel is. Can a campaign try variants of its own steps
(other transformations, samples, specifications, measures, related
questions), without a person, while the exploration half still counts every
analysis and no agent ever sets a threshold?

## What changes in decision 0010

Point 8 said: "Agents' suggestions for new variants go in that report and
are never run in the same campaign." Now:

Gabriel approves every campaign's plan, kill rules **and fork envelope**
before it runs. Inside the envelope, agents may add variants that inherit
the approved kill rules. Agents still cannot write or change a threshold,
change the plan's own steps, touch owned files, or see the sealed half.
Variants outside the envelope stay suggestions in the close-out report.

## Decision

1. **The envelope.** A campaign file may carry a `forks:` block: how many
   forks (at most 5), how many at one fork point, how many new datasets
   (at most 2), how many steps per fork (at most 6), which kinds
   (`transform`, `sample`, `spec`, `measure`, `question`), how many
   `question` forks (at most 2), which verdicts open a fork point
   (`killed`, `survived`), which explore runs are fork points, and a budget
   of its own (tasks, explore runs, pipeline runs, model jobs). No block,
   no forks: a campaign without one behaves exactly as before.
2. **The fork point.** After an explore run of the plan gets a verdict
   listed in the envelope, the tick starts one ideation job: a model, read
   only, that proposes up to the envelope's number of forks in priority
   order, or says none is advisable, with reasons. Plain code checks each
   proposal against the envelope and the rules below; what passes is
   written to the repository as fork files, in a pull request the tick
   merges when the gate passes. What fails is listed in the report as a
   suggestion. Ideation never blocks a campaign: no result after two hours
   is recorded as "no forks" and the campaign goes on.
3. **Running.** Fork steps then run through the existing loop (plan, build,
   review, gate, merge, run, kill rules), after the plan's own steps.
4. **Adoption.** If the plan's step was killed at a fork point and a fork
   survives, the first surviving fork in the declared order adopts the
   steps that kill skipped, so the campaign carries on without Gabriel.
5. **The report.** The close-out reports the plan's path and every fork,
   how many were tried at each point, and recommends at most one design
   for the confirmation half.

## The rules (each enforced by code, each with a test)

- **F1. Exploration half only.** Fork code follows every existing explore
  rule. Nothing changes about `sealed/`, `confirm/` or the split. A fork's
  explore task may change only `explore/` and `tests/test_explore*`; its
  build task only new files named `*_fK` and, if the fork brings new data,
  `data/catalog.yaml`.
- **F2. Declared before run.** A fork's file is on `main` before any of its
  steps starts (the tick reads steps from `main` only). Fork files are
  append-only: the gate refuses any pull request that modifies or deletes
  an existing fork file unless Gabriel opened it.
- **F3. All declared forks at a point run.** The tick does not stop at the
  first survivor, so the number tried does not depend on the results.
  Budget or the end date may still stop them; the report says which did
  not run.
- **F4. Inherited kill rules.** Every fork's explore run names the step
  whose kill rules it inherits (`inherits: sNN`); code copies them
  unchanged. A `question` fork, whose results the parent's rules cannot
  read, names rules from the kill-rule library
  (`research/campaigns/kill-rule-library.yaml`, owned by Gabriel), with the
  library's thresholds. No fork file holds a threshold, a rule of its own or
  an `on_kill`. Every fork run needs at least one rule other than "the
  numbers are finite"; if none fits, the variant is only a suggestion.
- **F5. One declared difference.** A fork states one type and one dimension
  (what changes). Its drafts carry a section "What differs from the
  parent", and the reviewer's row R8 checks that nothing else differs.
- **F6. Samples are never chosen on outcomes.** A `sample` fork filters
  only on things fixed before the outcome (it names one of geography,
  biome, baseline characteristics dated before the first outcome year, or
  years), and code adds the library rule `min_clusters` to its run. R8
  checks the code.
- **F7. New data only from approved publishers**
  (`data/approved-publishers.yaml`, owned by Gabriel), with
  `identifiers: none` and at most 5 GB. Anything else is a suggestion.
- **F8. A fork result is never a finding.** Verdicts read "survived (fork)"
  or "killed (fork)". The report states how many forks were tried at each
  point next to any fork that survived.
- **F9. Adoption is mechanical.** Only at a killed fork point; only the
  first surviving fork in the declared order (with `adopts_downstream`);
  only steps that were skipped because of that kill and never started;
  their drafts, allowed paths and kill rules stay as approved, plus a
  section holding the fork's short `delta` text. At most one adoption per
  campaign.
- **F10. One design per idea goes to the confirmation half.** The close-out
  recommends at most one design for registration. A registered
  specification of an idea that had forks lists every fork tried, by id
  and count, in one line of its `hypothesis` (`Forks tried in campaign
  NNNN: f1, f2 (2).`); CI checks it. Registering stays Gabriel's.
- **F11. Depth one.** No forks of forks. Fork steps are never fork points.
- **F12. A budget of its own.** Fork steps count against the envelope's
  budget, never the plan's; adopted steps count against the plan's (they
  were approved there). One ideation job per fork point, counted in the
  envelope's model jobs.
- **F13. The plan first.** Fork steps start only when no step of the plan
  can start. The in-flight limits stay as they are (one task per campaign;
  the run limits across campaigns). No new parallelism.

## What does not change

- Campaigns without a `forks:` block behave exactly as before (a test
  replays every campaign folder through the validator and the tick).
- The confirmation half, the split, `sealed/`, `confirm/`, CODEOWNERS'
  existing entries, the ruleset, the gate's existing checks, self-repair's
  limits and the in-flight limits.
- No new model call except one ideation job per fork point. The tick and
  the gate stay plain code.
- No personal identifiers, no URLs in code, no credential patterns.
- Kill rules: still applied by code to `results.json`; a fork's are copies
  of rules Gabriel confirmed, or library rules he confirmed.

## Risks and how they are handled

- **Forking paths.** Several variants raise the chance that one passes by
  luck. Every variant is declared in a file on `main` before it runs, all
  declared variants at a point run (F3), the count is capped (at most 5),
  the report puts the number tried next to every surviving fork (F8), and
  at most one design per idea goes to the confirmation half, with every
  fork tried listed (F10). The confirmation half stays the test.
- **The agent writes its own exam.** It cannot: thresholds come only from
  the parent's confirmed rules or from the library Gabriel owns (F4).
- **Data the campaign did not plan.** Only from publishers Gabriel listed,
  with no identifiers and a size cap (F7).
- **Same-model review.** The reviewer's R8 is a model's judgement; the gate's
  file, draft and path checks, and the validator's checks on every fork
  file, do not depend on it. Gabriel reads every fork in the close-out.
- **Silent spending.** Forks have their own budget (F12) and run only when
  the plan's own steps cannot (F13).

## How we will know it works

A campaign whose gate is killed tries the cheapest variants that could
change the decision, carries on with the first that survives, and its
report lists every variant with its numbers, without Gabriel designing a
second campaign by hand as he did for 0008.
