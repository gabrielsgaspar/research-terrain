---
id: "0019"
title: "Task builds get one automatic fix round"
status: proposed
date: 2026-11-22
supersedes: null
---

# 0019: Task builds get one automatic fix round

Date: 2026-11-22. Status: proposed, drafted by Claude for Gabriel from his
request of 2026-11-22. It takes effect when Gabriel merges the pull request
that adds it, with the changes to `agent-build.yml`, `campaign-tick.yml`,
`harness/roles/builder.md` (rule 9), the tick and the status page in
`src/terrain/campaigns/`, and `AGENTS.md`. It changes no check: verify,
the gate, the path rules and the secret scan stay exactly as strict.

## The question

Pipeline runs recover by themselves: a failed run is started again twice,
and a campaign may add a repair (decisions 0010, 0014, 0016). Task builds
do not. Any failure in agent-build's build or verify job adds
`needs-human`, and the campaign waits for Gabriel, even when the fix is a
small one that the builder could make if it saw the error. Two runs on
2026-11-22 show it:

- Run 45023206392 (campaign 0013): verify's pytest failed 2 of 2,019
  tests in the new test file. The builder never saw the output.
- Run 45034395581 (campaign 0014): the builder stopped because the full
  pytest ran longer than Claude Code's 2-minute command limit (since fixed
  by #476). Nothing in the work was wrong.

Can a task build get one more try, with the error in hand, without
letting the builder pass by weakening its own tests?

## Decision

1. **One automatic fix round.** When the first build of a campaign task
   fails in a way the builder can fix, agent-build's report job does not
   add `needs-human`. It posts one comment on the issue, "## Agent build:
   fix round", with the reason and, if verify's ruff or pytest failed, the
   last 60 lines of that command's output. It then dispatches agent-build
   again for the same issue, with that comment as the review comment: the
   same mechanism agent-review uses for its fix rounds. The builder reads
   the comment as data in `.agent-build/review.md`.
   - A campaign task: an issue the agent App filed, labelled `campaign`,
     with a campaign step, repair or close-out marker.
   - What the builder can fix: it stopped (`blocked`) or returned no
     usable result, it left uncommitted changes or made no commits, or
     verify's `ruff check`, `ruff format --check` or `pytest` failed.
   - What it cannot fix stays a stop for Gabriel, as today: the guard, a
     missing or edited plan, an existing branch, the sandbox set-up,
     `uv sync`, a nested repository or submodule, a path the plan does not
     allow, the secret scan, and the publish job. A path or secret refusal
     is a guardrail, not a bug, and the next try would be checked over the
     same commits anyway.
   - Where the round starts. If verify failed, from the first attempt's
     commits: a small job with read access to Actions copies the first
     run's commit bundle into the new run, and the build checks that the
     bundle's head is the commit the comment names. If the build job
     failed, there is no bundle, so the round starts from main.
   - Once only. The round runs only after a first build (not after a
     review fix round, which keeps its own limit of three), and only if
     the issue has no earlier fix-round comment. If the second attempt also
     fails, the report job adds `needs-human` as before, and its comment
     says it was the automatic round.
   - The budget. Each fix-round comment counts as one model job against
     the campaign's `max_model_jobs` (the extra build), and the close-out's
     friction table counts it as a fix.
2. **No passing by deleting tests.** In the automatic round, verify adds
   one check before ruff and pytest:
   - every test the first attempt's commits wrote (each `test_*` function
     and method in its `tests/**/test_*.py` files) still exists at the new
     head. Verify reads the files with Python's `ast` module and runs none
     of them;
   - every test file and test name that the plan's "Done when" list names
     in backticks still exists, unless the plan deletes that file.
   The pull request body says that the change came through the automatic
   round, links the first run, and lists the first attempt's tests that
   the round changed, so the reviewer can read them.
3. **No duplicate steps.** Campaign 0013 step s5 was filed twice, #456 at
   14:41:59 UTC and #459 at 14:42:35 UTC. The two ticks did not overlap:
   the workflow already has a concurrency group (`campaign-tick`, one
   running and one pending, never cancelled while running). Tick
   45034144931's act job filed #456 and ended at 14:42:05; tick
   45034234510's decide job started at 14:42:07 and its list of
   `campaign` issues did not yet show #456, eight seconds old. So the act
   job now checks, right before it files any issue with a campaign step,
   repair or close-out marker, whether an open issue already carries
   exactly that marker, reading the newest open issues without a label
   filter. If one does, it files nothing and says so; this is not a
   failure. The concurrency group stays as it is.
4. **Merges wait for checks.** Tick run 45040286988 failed because GitHub
   refused a merge with HTTP 405, "Required status check "test" is in
   progress". The act job now reads that answer as "wait for the next
   tick": it prints a notice and does not fail. Any other refusal still
   fails the job.
5. **Stray files.** The untracked `.bashrc`, `.gitconfig`, `.idea` and
   `.mcp.json` in run 45034395581 come from Claude Code's sandbox runtime.
   To stop sandboxed commands from writing them, it mounts `/dev/null` over
   a fixed list of files (`.gitconfig`, `.gitmodules`, `.bashrc`,
   `.bash_profile`, `.zshrc`, `.zprofile`, `.profile`, `.ripgreprc`,
   `.mcp.json`) and folders (`.vscode`, `.idea`, `.claude/commands`,
   `.claude/agents`) in the working directory. Where one does not exist,
   the mount creates an empty placeholder, and git inside the sandbox lists
   it as untracked. A local session shows the same set as character
   devices 1,3 (`/dev/null`), and they are absent outside the sandbox.
   The build now adds these names to the checkout's `.git/info/exclude`,
   next to `.agent-build/`, so they can never block the commit check or be
   committed. `.git/info/exclude` hides only untracked files, and verify
   still checks every committed path.
6. **The status page names the reason.** In "Waiting on you", a step
   blocked by `needs-human` shows the start of the agent's last comment
   (its first 200 characters, headings and footer removed) instead of
   "an agent stopped and labelled it needs-human". The ledger keeps the
   fixed wording, so block ids do not change.

## What stays

Every check in verify, the gate and the act job's closed list of actions.
The secret scan still reads every commit, the first attempt's included,
and the path check still reads every commit's paths. Agent-review's fix
rounds, at most three per pull request. The builder's tools, model and
turn limit. No new action type: the fix round is a `workflow_dispatch` of
agent-build by its own report job, which gets `actions: write` for it, as
agent-review's posting job has.

## Risks and how they are handled

- **The builder weakens a test instead of fixing the code.** Deleting or
  renaming a first-attempt test fails verify. Loosening an assertion
  cannot be caught by code; the pull request body lists every
  first-attempt test the round changed, and the agent review and the gate
  still stand between the round and main.
- **The output quoted in the comment carries a secret.** It comes from
  verify, which holds no secret, and from tests on synthetic data. The
  report job scans the comment for token prefixes before posting, as for
  every reason, and drops the output if one matches.
- **A loop.** At most one fix-round comment per issue, checked twice:
  by the report job before it posts, and by the dispatched build, which
  stops if the issue has more than one.
- **The first run's bundle is gone.** Artifacts live seven days. The
  copy job fails, the build stops before Claude starts, and the report
  adds `needs-human` with that reason.
- **The marker check misses a just-filed issue too.** It reads at the
  moment of filing, without the label index the decide job uses, so the
  window is seconds rather than the length of a tick. A duplicate that
  still slips through is visible on the status page and costs one plan.
