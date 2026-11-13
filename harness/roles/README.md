# Agent roles

Every agent role in this repository and where its instructions live. Role
names are the same as in `research/agent-notes.md` (design, planner,
builder, reviewer, closeout), so each agent reads the notes for its own role.

| Role | Instructions | May | May not |
| --- | --- | --- | --- |
| planner | `harness/roles/planner.md`, loaded by `.github/workflows/agent-plan.yml` | Read the repository and `git log`; return one plan with its file list. | Change any file, label, issue or setting; plan work that AGENTS.md puts out of scope. |
| builder | `harness/roles/builder.md`, loaded by `.github/workflows/agent-build.yml` | Edit the files the plan lists; run `uv sync`, ruff, pytest and the listed git commands; commit. | Touch files outside the plan, push, use the network or add a dependency. |
| reviewer | `harness/roles/reviewer.md`, loaded by `.github/workflows/agent-review.yml` | Read the diff, the checkout of main and `git log`; return a verdict, must-fix items and referee rows. | Change anything, run the code, approve or merge. |
| ideation | `harness/roles/ideation.md`, loaded by `.github/workflows/campaign-ideate.yml` | Read the repository and `git log`; propose up to the envelope's number of forks at a fork point, or say none is advisable (decision 0015). | Change any file, write a threshold, a step id or a file outside a fork's `*_fK` names; propose a sample chosen on outcomes. Code writes every file from its answer. |
| closeout | `src/terrain/campaigns/closeout.py`, a template in code because the gate rebuilds it to check the issue | Write the campaign's ledger and report, a lessons entry, at most three notes, the idea's status line and the campaign's status. | Change code, data, kill rules, decisions or the harness; run new analysis. |
| repair | `src/terrain/campaigns/repair.py`, a template in code for the same reason | Fix a failing data-pipeline step within the allowed paths of the build steps it comes after (decision 0014). | Touch protected or owned paths, explore scripts, kill rules or campaign files. |
| design | `.claude/skills/campaign-design/`, a local skill run with Gabriel | Interview Gabriel, write a campaign file and its drafts, validate them and open the PR. | Decide for Gabriel, look at outcomes to set a rule, or merge. |

Close-out and repair have no workflow of their own: the campaign tick files
the template as an issue, and the planner, builder and reviewer work it,
reading it as data.

## Role files

Each file in this folder has a short front matter and a body:

- `role`: planner, builder, reviewer or ideation;
- `model`: the model the workflow runs, matching `^claude-[a-z0-9-]{3,40}$`;
- `max_turns`: the turn limit, a whole number from 1 to 200;
- `workflow`: the workflow that loads it;
- `notes` (optional): one line each, history behind a value.

The body is the prompt, exactly as the agent receives it. The planner, builder and reviewer prompts
were adapted from Alteram (https://github.com/gabrielsgaspar/alteram) and
moved here from the workflow files unchanged. Each workflow runs
`python3 -I scripts/role.py <role>` on its checkout of main just before
Claude starts, and passes the model, turn limit and prompt to the Claude
step. Everything else (tools, permissions, sandbox, output schema, tokens)
stays in the workflow.

This folder is under `harness/`: protected and owned in
`.github/CODEOWNERS`, so only Gabriel changes it. `tests/test_roles.py` pins
each body with a SHA-256, so any change to a prompt is also a visible edit
of that test.
