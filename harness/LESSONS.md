# Harness lessons

What setting up and running the agent pipeline, GitHub and GCP has taught
us. Research and data findings live in `research/lessons.md`. Newest first,
same format.

## Patterns so far (2026-11-02)

About twenty failures in the first two days. None put bad code on main or
bad data in the bucket: each was stopped by a check, a blocked build or a
plan review. They fall into five groups:

| Group | Examples | Share | What prevents it now |
| --- | --- | --- | --- |
| Mistakes in what a person or chat assistant wrote (tasks, fixtures, workflow scripts) | quoting bug, unanchored `build/`, fixtures that hid bad dates, ambiguous "same as X", over-broad Done when | largest | the checklists in `harness/issue-drafts/README.md`; workflow scripts run under bash before merging |
| A pipeline limit met for the first time | offline installs, no `rm`, literal plan paths, turn limits | second | limits written down in AGENTS.md and in each workflow's comments |
| One-time setup | nested action allowlist, App not installed, GCS list prefix | done | GCS smoke test; setup steps recorded here |
| Process slips | issue not updated, duplicate issue | small | the filing checklist |
| Outside us | GitHub API error | rare | start a new run later |

Expect the rate to fall: each first use of a capability (first build, first
deletion, first big task) has now happened once.

## 2026-11-02: Validate on every state, not one (section votes)
- Tried: task 07b and its first fix, both checked on Pará only.
- Result: the build failed twice on the full Legal Amazon: first on
  annulled candidacies, then on four states' incomplete 2004 files.
- Why: Pará was complete and representative for one check, not for all.
- Implication: before shipping a build or its fix, run it on the real files
  for every state and year it covers, exactly as the pipeline will. The
  coverage fix was run that way (54 state-year files) before it was sent.

## 2026-11-02: A task's facts were checked on one case, not the general one (07b)
- Tried: task 07b, whose draft said annulled votes show as 0 in the results.
- Result: true for 2012 only; other years omit those candidacies, so the
  build stopped on its unmatched check.
- Why: the draft generalised from the 2012 Pará check.
- Implication: when a task states how the data behaves, check every year it
  covers, not the first one that shows the pattern.

## 2026-11-02: Review findings now go back to the builder (fix loop)
- Tried: three must-fix findings (PRs #38, #52 and the results build) each
  needed a person to patch the branch.
- Result: agent-review now dispatches agent-build for a fix round when its
  verdict is "Changes needed", at most three rounds per PR.
- Why: the findings were specific and within the plan's files; a person
  added nothing but copying.
- Implication: a fix round checks out the existing branch at the reviewed
  commit, reads the review's Must fix list as data, may change only the
  plan's files, and passes the same verify over all the branch's commits.
  The review comment is accepted only if it is agent-review's own verdict for
  the current head. After three rounds, a failed dispatch or any failure, the
  PR or issue gets needs-human.

## 2026-11-02: A task's threshold used the wrong unit, and a failed build left files behind (tse_results)
- Tried: the first real run of the candidate-votes build.
- Result: it stopped on 2008: 1,834 of 646,941 rows unmatched (0.28%) against
  a 0.1% limit. It had already uploaded the 2000 and 2004 files, which stay
  in the bucket without a manifest.
- Why: the draft quoted "140 SQs unmatched in 2008" (distinct SQ values,
  which repeat across municipalities before 2012) next to a limit on rows.
  The true figure is 1,458 candidacies (0.43%), a real gap in the TSE's 2008
  candidate file. Separately, the build uploaded each year as it went.
- Implication: thresholds state their unit and are checked against the real
  number in the same unit before a task is filed; this one now counts
  candidacies and allows 1%. Every build writes all outputs locally and
  uploads only after every check passes (the polling-places build already
  did). Reproduced end to end on the real files before shipping the fix.

## 2026-11-02: A test passed on Linux CI and failed on Windows (tse_parties)
- Tried: running the full suite locally on Windows.
- Result: `test_changing_the_source_of_tse_candidates_changes_the_path` failed
  with a UnicodeDecodeError; CI on Linux passed.
- Why: `Path.write_text(text)` without an encoding writes cp1252 on Windows,
  so accented characters in the copied module were not valid UTF-8 when read
  back. Nine calls in the tests had no explicit encoding.
- Implication: every text read, write and `open()` names its encoding; a
  repository test walks the code and fails on any call that does not.

## 2026-11-02: The secret scan flagged ordinary Python as a credential (issue #44)
- Tried: building task 06a.
- Result: verify stopped on a line in `src/terrain/builds/tse_results.py`
  matching "KEY= or TOKEN= assignment with a long value". Nothing was pushed.
- Why: that pattern matched any name ending in KEY followed by 16
  non-space characters, so a line such as
  `TURNOUT_KEY = CANDIDATE_VOTES_KEY[:3]` looked like a secret. Builds with
  composite keys name constants that way.
- Implication: the pattern now needs a secret-like value (20+ token
  characters with at least one digit and one letter, ending the
  assignment), case-insensitive, and also covers SECRET and PASSWORD. It
  still catches `.env`-style and quoted secrets, and fires on no current
  code. Known token prefixes are checked separately, unchanged.

## 2026-11-02: A task named a column that is in a different file (issue #46)
- Tried: task 07a, which asked for Hidalgo's `panel_id`.
- Result: the planner found `panel_id` is not in the geocoded file and made
  "add a fixture or drop the column" a step for a person; the builder
  stopped without guessing. Nothing was built.
- Why: the draft was written from the README's description of the release,
  not from the files; `panel_id` lives in `panel_ids.csv.gz`, joined on
  `local_id`.
- Implication: every column a task names is checked against the real file
  first (the filing checklist's step 2 covers columns, not just values).
  Fixture and draft fixed.

## 2026-11-02: Exploration needed its own runner (explore-run)
- Tried: planning the feasibility census.
- Result: there was nowhere to run it: `data-pipeline` runs only acquire and
  build scripts, as the acquire and build accounts.
- Why: exploration was designed (split sample, analysis account, `explore/`)
  but not built.
- Implication: `explore-run` runs a merged `explore/` script as
  `terrain-analysis`, and opens a PR recording every run in
  `research/explore-runs/`. `terrain.explore` holds the contract; a test
  fails if a script does not restrict to the exploration half.

## 2026-11-02: Allowlists were not enforced inside the sandbox (PR #38)
- Tried: the reviewer on task 05, allowed only `git log`.
- Result: it reported running `ls` and `cat` as well. Nothing changed, but
  the allowlist did not hold.
- Why: Claude Code's sandbox defaults to `autoAllowBashIfSandboxed: true`,
  which runs any sandboxed command without checking `--allowedTools`. The
  same was true for the planner and the builder (inherited from Alteram).
  The sandbox itself still limited files, network and secrets.
- Implication: `autoAllowBashIfSandboxed` is false in `.claude/settings.json`
  and in each workflow's settings. Watch the first builder run after the
  change: a command it relied on but is not listed (for example `tail` in a
  pipe) is now refused. Apply the same change to Alteram.

## 2026-11-02: A build's output path must hash every module it relies on (PR #38)
- Tried: the municipalities build, whose path hashed only its own module.
- Result: the reviewer flagged that a fix to `terrain.ods`, which parses both
  IBGE inputs, would keep the same path, so a rebuild would report
  `unchanged` and keep the old output.
- Why: the hash covered the build file, not the code it imports.
- Implication: builds hash their own code and every data-handling module they
  import, with input SHA-256s sorted (AGENTS.md). Drafts 06a and 06b import
  helpers from the candidates build, so they must hash it too.

## 2026-11-02: The plan's file list is now structured data
- Tried: two plans in a row had file lists verify could not read (brace
  shorthand; a deletion mentioned only in a step).
- Result: both were caught by reading the plan, not by a check.
- Why: verify parsed a Markdown section the planner wrote freely.
- Implication: the planner returns `files` (path, add / modify / delete,
  why); the workflow validates every path, prints the list, and embeds it as
  JSON that verify and the reviewer read. A bad list, an empty result or a
  credential match now posts a "withheld" notice on the issue instead of
  failing silently. Old plans still work through the Markdown fallback.

## 2026-11-02: The planner ran out of turns on a large task (issue #26)
- Tried: planning task 04 (16 files: a new module, six scripts, deletions,
  tests).
- Result: the planner finished its plan in 21 turns, but the limit was 20,
  so the action failed and nothing was posted.
- Why: the limits (planner 20, reviewer 30, builder 60) were sized for
  Alteram's small tasks; data tasks read and touch more files.
- Implication: limits raised to planner 40, reviewer 50, builder 100. Tasks
  stay small enough to finish well inside them: aim for at most about ten
  files changed, and split larger work into separate issues.

## 2026-11-02: A plan listed files with brace shorthand (issue #26)
- Tried: re-planning task 04.
- Result: the plan listed five new scripts as
  `pipeline/acquire/{a,b,c,d,e}.py` and mentioned deleting
  `src/terrain/sources/__init__.py` only inside a step. Verify matches
  plan paths exactly, so the build would have failed on six files. Caught
  in plan review, before building.
- Why: nothing told the planner the file list is parsed literally.
- Implication: AGENTS.md now requires one full path per bullet, deletions
  included. The durable fix is BUILD_PLAN item 0.2 (a JSON file list in the
  plan, parsed instead of markdown).

## 2026-11-02: A plan asked the builder for a command it did not have (issue #26)
- Tried: task 04, whose plan deletes `src/terrain/sources/tse.py` and its
  test after moving the logic.
- Result: the builder wrote most of the work, then stopped as blocked: its
  allowed commands could not delete a file. It also flagged that "Done
  when" item 5 would wrongly catch the root prefixes in `manifest.py`.
- Why: neither the planner nor the task knew the builder's command list.
- Implication: `git rm` is now allowed (verify still rejects unplanned or
  protected deletions), the builder's full command list is in AGENTS.md so
  plans stay within it, and the task's item 5 now exempts the root
  prefixes.

## 2026-11-02: An unanchored `build/` in .gitignore hid two project folders (candidates build)
- Tried: recording the first `build` manifest.
- Result: `git add` refused `data/manifests/build/`. The same pattern also
  hid `pipeline/build/`, so ruff never checked the merged build script (it
  had a lint error) and `git add -A` would silently skip new files there.
- Why: `build/` in .gitignore matches a folder of that name anywhere, not
  only the Python build folder at the root.
- Implication: directory patterns are anchored (`/build/`), and
  `tests/test_repo_rules.py` lists paths that must stay committable and
  paths that must stay ignored. Rule in AGENTS.md.

## 2026-11-02: A failed record step left data in GCS that main did not know about
- Tried: rerunning a build after its PR step failed.
- Result: the rerun would have reported `unchanged` and opened no PR, so the
  manifest would never reach main.
- Why: the record step skipped every `unchanged` run.
- Implication: an `unchanged` run is now recorded when main has no manifest
  for that output, so rerunning repairs a failed record step.

## 2026-11-02: Test zips with the current time made a hash test flaky (issue #18)
- Tried: running the suite repeatedly.
- Result: `test_same_inputs_give_the_same_path` failed about one run in
  three: two zips built from the same fixture a second apart had different
  SHA-256s, so different output paths.
- Why: `ZipFile.writestr(name, ...)` stamps entries with the current time.
- Implication: test zips use a fixed timestamp. Rule in AGENTS.md.

## 2026-11-02: Search issues before filing a draft (issue #23)
- Tried: filing task 08 a second time.
- Result: the planner answered "duplicate of #21, done in PR #22"; posting
  its comment then failed on a transient GitHub API error.
- Why: the draft had already been filed and built.
- Implication: before filing, run `gh issue list --state all --search
  "<title words>"`. GitHub API errors ("Something went wrong") are
  transient: start a new run a few minutes later.

## 2026-11-02: Anonymised fixtures hid a real-data defect (candidates build)
- Tried: the first real run of the candidates build, after all tests passed.
- Result: it stopped on 17 invalid birth dates (such as 29 February 1950)
  in the 2000 file. Nothing was written.
- Why: the fixtures set every birth date to 1 July to anonymise them, which
  also removed the invalid ones; the build parsed dates strictly.
- Implication: before writing a build task, profile the real files for
  values the build will reject, and put the counts in the task. Builds
  decide per column between stopping and null-plus-count (AGENTS.md).

## 2026-11-02: Workflow scripts need the same testing as Python code (data-pipeline)
- Tried: the first real `data-pipeline` acquire run.
- Result: the data was downloaded and verified, but the PR step failed on a
  Python f-string with escaped quotes inside a shell string.
- Why: inline scripts in workflow YAML are not covered by pytest.
- Implication: run every inline script under bash locally before merging a
  workflow change. Moving checks into tested Python is on the roadmap.

## 2026-11-02: Check the issue text, not the draft, before re-planning (issue #11)
- Tried: re-planning task 2 after improving its draft.
- Result: the plan matched the old draft. Issue #11 still had the old text,
  and the local main was behind the merged draft.
- Why: editing a draft file does not edit the issue.
- Implication: `git pull`, then `gh issue edit N --body-file <draft>`, then
  check the issue (`gh issue view N`) before adding `agent-plan`.

## 2026-11-02: Ambiguous tasks get literal readings (issue #6)
- Tried: asking the manifest validator to apply "the same rules" as the
  workflow's manifest check.
- Result: the builder copied the workflow's credential regex as well.
- Why: "the same as X" did not say which parts of X.
- Implication: tasks that mirror something say exactly which parts.

## 2026-11-02: A plan that greps for token prefixes cannot be posted (issue #6)
- Tried: re-planning issue #6 after adding the "no prefixes in code" rule.
- Result: the planner obeyed the rule for code, then added a Done-when check
  that grepped for the prefixes by name; the comment step's scan refused to
  post the plan.
- Why: the rule named code only, so the planner tried to enforce it with a
  check that contained the very strings it banned.
- Implication: the rule now covers plans, comments, checks and commands, and
  says the workflows' scan is the only credential check.

## 2026-11-02: Token prefixes in code trip the secret scan (issue #6)
- Tried: the storage-helpers task, which asked manifest validation to apply
  "the same rules" as the workflow's manifest check.
- Result: verify failed. The builder copied the workflow's credential regex
  into `src/terrain/manifest.py`, and the literal prefixes in it matched the
  secret scan (the escaped ones did not).
- Why: the task was ambiguous; the scan cannot tell a pattern from a secret.
- Implication: credential scanning stays in the workflows; tasks that mirror
  a workflow check say which parts to mirror. Rule added to AGENTS.md.

## 2026-11-02: Agents cannot add dependencies (issue #6)
- Tried: the storage-helpers task, whose plan added `google-cloud-storage`.
- Result: the builder stopped as blocked. It installs offline
  (`UV_OFFLINE=1`) from what `uv.lock` lists, so a new package cannot be
  resolved.
- Why: by design. The builder's sandbox has no general network, so an agent
  can never pull a package nobody approved.
- Implication: a person adds dependencies in their own PR before the task;
  tasks and plans never list `pyproject.toml` or `uv.lock`. Rule added to
  AGENTS.md.

## 2026-11-01: "Re-run" replays the old workflow (gcs-smoke)
- Tried: re-running the GCS smoke test after fixing it on main.
- Result: it kept failing with the old code; the path showed the old run ID.
- Why: re-running a run uses that run's original commit.
- Implication: after a workflow change, start a new run (Run workflow or
  `gh workflow run`), never Re-run.

## 2026-11-01: GCS listings drop the trailing slash (gcs-smoke)
- Tried: prefix-scoped IAM conditions on `data/raw/`.
- Result: creating objects worked, listing `data/raw/` was refused.
- Why: `gcloud storage ls` sends the prefix as `data/raw`.
- Implication: conditions allow both `data/raw/...` and exactly `data/raw`
  (`scripts/gcp/setup_gcs.sh`).

## 2026-11-01: A GitHub App must be installed, not just created (issue #3)
- Tried: publishing the first agent PR.
- Result: a 404 from the installation lookup.
- Why: the App existed but was not installed on the repository.
- Implication: check https://github.com/settings/installations when an App
  token step fails with 404.

## 2026-11-01: Action allowlists cover nested actions (agent-plan)
- Tried: allowlisting the actions the workflows call.
- Result: the planner was blocked on `oven-sh/setup-bun`, which
  `anthropics/claude-code-action` calls internally.
- Why: the policy applies to every action in the run, not just top-level.
- Implication: read each action's `action.yml` before writing an allowlist.
