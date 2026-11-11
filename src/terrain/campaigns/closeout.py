"""The close-out task: the issue the tick files when a campaign finishes.

The body is generated from the campaign file and what the tick saw, so the
builder gets every fact it needs (steps, verdicts, runs, budget used, and the
friction facts: blocks, extra plans and fix rounds, repeated runs, long gaps)
as data. The report proposes harness changes but never makes them.
The close-out PR touches owned paths (the idea file, campaign.md), so the
owner always merges it: it is where he reads the report and decides.
"""

from __future__ import annotations

from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.spec import Campaign

REPORT_SECTIONS = (
    "Summary",
    "What ran",
    "Results and their limits",
    "Kill rules applied",
    "Budget used",
    "Stops and blocks",
    "Proposed harness changes (at most three)",
    "Suggested next variants (not run)",
    "Decisions for Gabriel",
)


# The lines the report opens with, before `## Summary`, one sentence each.
REPORT_OPENING = ("What we tested:", "What happened:", "What it means:", "Decisions for you:")

_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def number_word(n: int) -> str:
    """`9` -> `nine` (digits from eleven on)."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def table(header: list[str], rows: list[list[str]]) -> str:
    """A Markdown table; pipes and line breaks inside cells are escaped."""

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(x.replace("|", "\\|").replace("\n", " ") for x in cells) + " |"

    return "\n".join([line(header), line(["---"] * len(header)), *map(line, rows)])


def ledger_table(rows: list[dict[str, str]]) -> str:
    keys = ("step", "kind", "status", "verdict", "links")
    return table(
        ["Step", "Kind", "Status", "Verdict", "Links"], [[r.get(k, "") for k in keys] for r in rows]
    )


def closeout_issue(
    c: Campaign,
    root: Path,
    rows: list[dict[str, str]],
    budget_used: dict[str, int],
    reason: str,
    tracking: int | None,
    final_status: str = "done",
    applied: list[str] | None = None,
    friction: str = "None given.",
) -> tuple[str, str]:
    """(title, body) of the close-out issue."""
    idea_files = sorted(
        p.relative_to(root).as_posix() for p in (root / "research" / "ideas").glob(f"{c.idea}-*.md")
    )
    idea_file = idea_files[0] if idea_files else f"research/ideas/{c.idea}-....md"
    used = ", ".join(
        f"{k} {budget_used.get(k, 0)} of {c.budget.get(k, 0)}" for k in sorted(c.budget)
    )
    sections = "\n".join(f"   - `## {s}`" for s in REPORT_SECTIONS)
    opening = "\n".join(f"   - `{line}`" for line in REPORT_OPENING)
    n_sections = number_word(len(REPORT_SECTIONS))
    rules = "\n".join(f"- {line}" for line in (applied or [])) or "- No kill rule was applied."
    title = f"Task: close out campaign {c.id} ({c.title})"
    body = f"""## Goal

Campaign {c.id} (`{c.folder}/campaign.md`) has finished: {reason}. Write its
report and records, so Gabriel can read one document and decide what comes
next. Nothing in this task runs analysis or reads data: every number comes
from the run records listed below, which are on main.

## Idea

`{idea_file}`; the campaign file `{c.folder}/campaign.md`; decision 0010
(`research/decisions/0010-campaigns.md`). Tracking issue: {f"#{tracking}" if tracking else "none"}.

## The ledger (written by the tick; copy it as is)

{ledger_table(rows)}

Budget used: {used}.

Kill rules, as the tick applied them to the run records:

{rules}

## Friction facts (written by the tick; copy as is)

What slowed the campaign down, counted by the tick from the ledger, the
issues, the plan and review comments, the pull requests and the runs. A fix
round is one agent review after the first.

{friction}

## In scope

- `{c.folder}/ledger.md`: the table above, under a heading
  `# Campaign {c.id} ledger`, unchanged.
- `{c.folder}/report.md`: the report. Its first four lines, before
  `## Summary`, are these, each followed by one sentence (on the last, the
  sentence starts with the number of decisions in "Decisions for Gabriel"):
{opening}
  Then exactly these sections, in order:
{sections}
  What the sections must hold:
  - "Results and their limits" has an item "Unexplained differences": every
    quantity that differs between two run records (for example, two records
    giving different numbers of pairs for the same window), with both numbers
    and both record paths. It says "None found" if there is none.
  - "Stops and blocks" copies the friction facts above as they are, and lists
    every row of their Blocks table. It may say "none" only when that table
    says "None.".
  - "Proposed harness changes (at most three)": for each proposal, the
    friction fact it answers, the change in one sentence, the file it would
    touch, and whether it is a check in code or a change of wording. Prefer a
    check in code. If the friction facts show no friction, the section says
    "None". These are proposals only: Gabriel picks which become tasks.
  - "Decisions for Gabriel": at most three. Each must change what happens
    next in the repository: the idea's status, whether to register a design
    for the confirmation half, or whether to open a follow-up campaign or
    task. No question about unused budget.
- `research/lessons.md`: one dated entry for the campaign, in the file's
  existing style, citing the run records by path.
- `{idea_file}`: one dated line under `## Status` saying what the campaign
  found. The front-matter `status` and `kill_criteria` stay as they are:
  Gabriel changes them, not this task.
- `{c.folder}/campaign.md`: front-matter `status: {final_status}`, nothing else.
- `research/INDEX.md`: regenerated with `uv run python scripts/build_index.py`
  only if a test says it is out of date.

## Out of scope

- Any code, any data, any new analysis, any change to kill rules or
  decisions. Suggestions in the report are suggestions: they are not run.
- The harness: `src/terrain/campaigns/`, `harness/`, the workflows in
  `.github/`, `AGENTS.md` and the skills in `.claude/skills/`. Proposed
  harness changes are written in the report and nowhere else.

## Done when

1. `{c.folder}/ledger.md` holds the table above, unchanged.
2. `{c.folder}/report.md` opens with the four lines listed, one sentence
   each, and then has the {n_sections} sections listed, in that order.
3. Every number in `report.md` appears in a run record it cites by path
   (`research/explore-runs/...`) or in the ledger or friction facts above,
   and every kill rule's outcome matches the ledger's Verdict column.
4. "Results and their limits" says plainly that these are exploration-half
   results and that nothing here is a finding, and has the item
   "Unexplained differences" (both numbers and both paths, or "None found").
5. "Stops and blocks" holds the friction facts unchanged and lists every row
   of their Blocks table; it says "none" only if that table says "None.".
6. "Proposed harness changes (at most three)" has at most three proposals,
   each with its friction fact, the change in one sentence, the file it would
   touch, and check in code or change of wording; or "None" if the friction
   facts show no friction.
7. "Decisions for Gabriel" has at most three choices, each changing what
   happens next in the repository (the idea's status, registering, a
   follow-up), none about unused budget, each with options and one
   recommendation, and says the recommendation is the agent's, not his. The
   number on the report's "Decisions for you:" line is how many there are.
8. `research/lessons.md` has one new dated entry and `{idea_file}` one new
   dated status line; nothing else in either file changes.
9. `{c.folder}/campaign.md` differs only in `status: {final_status}`.
10. Nothing outside the files under "In scope" changes: no harness file,
    workflow, `AGENTS.md` or skill.
11. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.

{markers.closeout_marker(c.id)}
"""
    return title, body
