# Issue drafts

Ready-to-file agent tasks. Create one with

    gh issue create --title "<first line without '# '>" --body-file <file>

then add the `agent-plan` label. First check it has not been filed already:
`gh issue list --state all --search "<title words>"`. File them in order; each depends on the one
before it being merged and, where it reads data, on the data having been
acquired or built (its manifest merged into `data/manifests/`).

| Draft | Task | Needs first |
| --- | --- | --- |
| 01 | Storage and manifest helpers | done (#6) |
| 02 | Acquire TSE candidates | done (#11) |
| 03 | Build the candidates table | done (#18) |
| 04 | Catalog-driven acquirer and five new acquisitions | done (#26) |
| 05 | Municipalities and TSE-IBGE crosswalk | build `tse_candidates` merged (done) |
| 06a | Candidate votes and turnout | 05 built; `acquire/tse_results` merged |
| 06b | Party votes and coalitions | 05 built; `acquire/tse_results` merged |
| 07a | Located polling places | 05 built |
| 07b | Section votes linked to candidacies | 06a built |
| 08 | Candidates build tolerates invalid birth dates | done (#21) |

## Before filing a task

1. Search: `gh issue list --state all --search "<title words>"`.
2. If it reads real data, profile the real files first (every column the
   task names exists in the file it names; values a build will reject;
   keys; row counts) and put the numbers in the task. Fixtures are
   anonymised and can hide defects.
3. Everything it needs exists: dependencies added by a person, fixtures
   committed, input manifests merged.
4. It asks only for what the builder can do (AGENTS.md, "What the builder
   can do"). Anything else is a step for a person, done first.
5. "Done when" items are checkable on fixtures or inputs built in the test,
   and say exactly which parts of anything they mirror.
6. Size: at most about ten files changed. Split larger work.
7. After editing a draft, update the issue (`gh issue edit N --body-file
   ...`) before adding `agent-plan`.

## Before building a plan

- **Files to change:** one full path per bullet, deletions included, no
  braces or globs.
- Nothing under protected paths, `pyproject.toml` or `uv.lock`.
- Every step uses only the builder's commands.
- The "Done when" list matches the issue's.

## Before merging a workflow change

- Run each inline script under bash with sample inputs, and run
  `actionlint`.
- After merging, start a new run (Run workflow or `gh workflow run`);
  re-running an old run uses the old workflow.
