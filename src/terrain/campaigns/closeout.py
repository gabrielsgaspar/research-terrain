"""The close-out task: the issue the tick files when a campaign finishes.

The body is generated from the campaign file and what the tick saw, so the
builder gets every fact it needs (steps, verdicts, runs, budget used) as data.
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
    "Suggested next variants (not run)",
    "Decisions for Gabriel",
)


def ledger_table(rows: list[dict[str, str]]) -> str:
    lines = ["| Step | Kind | Status | Verdict | Links |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        cells = [
            r.get(k, "").replace("|", "\\|").replace("\n", " ")
            for k in ("step", "kind", "status", "verdict", "links")
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def closeout_issue(
    c: Campaign,
    root: Path,
    rows: list[dict[str, str]],
    budget_used: dict[str, int],
    reason: str,
    tracking: int | None,
    final_status: str = "done",
    applied: list[str] | None = None,
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

## In scope

- `{c.folder}/ledger.md`: the table above, under a heading
  `# Campaign {c.id} ledger`, unchanged.
- `{c.folder}/report.md`: the report, with exactly these sections, in order:
{sections}
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

## Done when

1. `{c.folder}/ledger.md` holds the table above, unchanged.
2. `{c.folder}/report.md` has the eight sections listed, in that order.
3. Every number in `report.md` appears in a run record it cites by path
   (`research/explore-runs/...`), and every kill rule's outcome matches the
   ledger's Verdict column.
4. "Results and their limits" says plainly that these are exploration-half
   results and that nothing here is a finding.
5. "Decisions for Gabriel" lists each choice with options and one
   recommendation each, and says the recommendation is the agent's, not his.
6. `research/lessons.md` has one new dated entry and `{idea_file}` one new
   dated status line; nothing else in either file changes.
7. `{c.folder}/campaign.md` differs only in `status: {final_status}`.
8. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.

{markers.closeout_marker(c.id)}
"""
    return title, body
