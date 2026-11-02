# Harness lessons

What setting up and running the agent pipeline, GitHub and GCP has taught
us. Research and data findings live in `research/lessons.md`. Newest first,
same format.

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
