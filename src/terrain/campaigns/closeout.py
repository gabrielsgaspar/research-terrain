"""The close-out task: the issue the tick files when a campaign finishes.

The body is generated from the campaign file and what the tick saw, so the
builder gets every fact it needs (steps, verdicts, runs, budget used, the
friction facts: blocks, extra plans and fix rounds, repeated runs, long gaps,
and the checks not run: unfinished steps, kill rules never applied, referee
rows marked not applicable) as data. From those facts the close-out adds at
most three notes of advice to `research/agent-notes.md`, which every agent
reads (decision 0013), and one Scoreboard row; checks in code it only
proposes, in the report.
The close-out PR touches owned paths (the idea file, campaign.md, the notes),
so the owner always approves it: it is where he reads the report and decides.
It also sets the idea's status to the report's recommendation (one of
RECOMMENDED_STATUSES), so the idea's status follows its campaign; approving
the pull request accepts it, and scripts/validate_records.py catches drift.
"""

from __future__ import annotations

from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.spec import NOTES_PATH, Campaign

REPORT_SECTIONS = (
    "Summary",
    "What ran",
    "Results and their limits",
    "Kill rules applied",
    "Budget used",
    "Stops and blocks",
    "Checks not run",
    "Proposed harness changes (at most three)",
    "Suggested next variants (not run)",
    "Decisions for Gabriel",
)


# A campaign with a forks envelope (decision 0015) has one more section, after
# "Kill rules applied", holding the tick's fork facts unchanged.
FORKS_SECTION = "Forks"


def report_sections(c: Campaign) -> tuple[str, ...]:
    """The report's sections, in order, for campaign `c`."""
    if c.forks is None:
        return REPORT_SECTIONS
    i = REPORT_SECTIONS.index("Kill rules applied") + 1
    return (*REPORT_SECTIONS[:i], FORKS_SECTION, *REPORT_SECTIONS[i:])


# The statuses a close-out may recommend for its idea, and then writes to the idea file.
RECOMMENDED_STATUSES = ("promising", "parked", "dead")

# The lines the report opens with, before `## Summary`, one sentence each.
REPORT_OPENING = ("What we tested:", "What happened:", "What it means:", "Decisions for you:")

# The notes file (decision 0013). scripts/validate_records.py enforces these.
NOTE_ROLES = ("design", "planner", "builder", "reviewer", "closeout")
MAX_NOTES = 30  # in the file
MAX_NEW_NOTES = 3  # per close-out
MAX_ADVICE_CHARS = 200
# A note that contains any of these, in any letter case, is refused: notes are
# advice on how to work, never a way to loosen a rule or what a task may touch.
NOTE_BANNED = (
    "skip",
    "ignore",
    "disable",
    "bypass",
    "sealed",
    "confirm/",
    "kill rule",
    "threshold",
    "needs-human",
    "CODEOWNERS",
    ".github",
)
SCOREBOARD_HEADER = (
    "Campaign",
    "Steps",
    "Blocks",
    "Fix rounds",
    "Retries",
    "Hours from start to finish",
    "Notes added",
)

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


def _forks_block(forks: str) -> str:
    if not forks:
        return ""
    return f"""## Forks (written by the tick; copy as is)

The variants this campaign ran inside its envelope (decision 0015), how many
were tried at each fork point, and those refused or only suggested.

{forks}

"""


def _forks_rules(forks: str) -> str:
    if not forks:
        return ""
    return """
  - "Forks" holds the "Forks (written by the tick)" section above unchanged,
    and next to any fork that survived, the number of forks tried at its
    point. A fork's result is never a finding.
  - In "Decisions for Gabriel": recommend `dead` only if the plan's path and
    every fork failed. If only a fork survived, recommend `promising` and say:
    "the idea as first written met its kill criterion; the surviving variant
    is fK" (with its id). Recommend at most one design for the confirmation
    half, and say that its registration must list every fork tried
    (decision 0015, F10)."""


def _variants_rule(forks: str) -> str:
    if not forks:
        return ""
    return """ Add a section `## Variants tried` that lists every
  fork of the Forks table (id, parent step, what changed, verdict), one item
  each."""


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
    not_run: list[str] | None = None,
    forks: str = "",
) -> tuple[str, str]:
    """(title, body) of the close-out issue.

    `not_run` holds the tick's checks not run, one line each (`checks_not_run`
    in `terrain.campaigns.tick`): the report must list every one of them.
    """
    idea_files = sorted(
        p.relative_to(root).as_posix() for p in (root / "research" / "ideas").glob(f"{c.idea}-*.md")
    )
    idea_file = idea_files[0] if idea_files else f"research/ideas/{c.idea}-....md"
    used = ", ".join(
        f"{k} {budget_used.get(k, 0)} of {c.budget.get(k, 0)}" for k in sorted(c.budget)
    )
    sections = "\n".join(f"   - `## {s}`" for s in report_sections(c))
    opening = "\n".join(f"   - `{line}`" for line in REPORT_OPENING)
    n_sections = number_word(len(report_sections(c)))
    rules = "\n".join(f"- {line}" for line in (applied or [])) or "- No kill rule was applied."
    checks = "\n".join(f"- {line}" for line in (not_run or [])) or "None."
    roles = ", ".join(NOTE_ROLES)
    banned = ", ".join(f"`{w}`" for w in NOTE_BANNED)
    score_header = " | ".join(SCOREBOARD_HEADER)
    note_shape = (
        f"- [N001] (role) Advice in one sentence. From: campaign {c.id}, "
        "the friction fact in a few words. Added YYYY-MM-DD."
    )
    score_row = f"| {c.id} | {len(c.steps)} | blocks | fix rounds | retries | hours | notes added |"
    statuses = ", ".join(f"`{x}`" for x in RECOMMENDED_STATUSES)
    status_line = (
        "- YYYY-MM-DD: <status>, the recommendation of campaign "
        f"{c.id}'s close-out report (`{c.folder}/report.md`); Gabriel accepts it "
        "by approving this pull request. <What the campaign found, in a sentence or two.>"
    )
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

{_forks_block(forks)}## Checks not run (written by the tick; copy as is)

Every step that did not finish, every kill rule that was never applied
because its step did not run to a result, and every referee row a review
in this campaign marked "Not applicable", each with its reason.

{checks}

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
  - "Checks not run" lists every item of "Checks not run" above, each with
    its reason as written there. It may say "None" only when that list says
    "None.": every step finished, every kill rule was applied and no referee
    row was marked "Not applicable".
  - "Proposed harness changes (at most three)" has two parts:
    `### Notes added`: the id and full text of each note this task added to
    `{NOTES_PATH}`, and which old notes it merged or removed, if any; or
    "None" if it added none.
    `### Checks in code proposed`: at most three, each with the friction fact
    it answers, the check in one sentence and the file it would touch; or
    "None". These are not applied: Gabriel batches them into tasks later.
  - "Decisions for Gabriel": at most three. Each must change what happens
    next in the repository: the idea's status, whether to register a design
    for the confirmation half, or whether to open a follow-up campaign or
    task. No question about unused budget. The first is always the idea's
    status, with the options {statuses} and one of them recommended.{_forks_rules(forks)}
- `{NOTES_PATH}`: advice for later campaigns, which every agent reads.
  - Add at most {number_word(MAX_NEW_NOTES)} notes under `## Notes`. Each answers one row
    of the friction facts above (a row of a table, or the wall-clock line)
    and is for one role: {roles}. Use exactly this shape, one line each,
    with the next free id (never reuse one):
    `{note_shape}`
  - A note is advice about how to do the work, at most {MAX_ADVICE_CHARS} characters
    of advice. It must not restate or soften a rule, and it must not tell
    an agent to change what a task may touch (files, allowed paths, plans'
    file lists). The validator refuses a note that contains any of these,
    in any letter case, so word the friction fact without them too:
    {banned}.
  - Add one row to the `## Scoreboard` table, copied from the friction facts
    and the ledger: `{score_row}`.
    Blocks is the number of rows in the Blocks table; fix rounds the sum of
    its Fix rounds column; retries the sum of Runs minus one over the run
    steps table; hours the wall-clock hours, as written; notes added the
    number of notes this task added. Columns: {score_header}.
  - If the facts show no friction (every group says "None."), add no note
    and still add the row.
  - The file holds at most {MAX_NOTES} notes. If the new ones would pass that,
    first merge or remove the oldest notes, and say which in the report.
    Change nothing else in the file.
- `research/lessons.md`: one dated entry for the campaign, in the file's
  existing style, citing the run records by path.
- `{idea_file}`: the idea's status follows the report. In the front matter,
  `status` becomes the status the report recommends in its first decision
  (one of {statuses}) and `updated` today's date; `kill_criteria` and every
  other key stay as they are.{_variants_rule(forks)} Add one dated line under
  `## Status`, in this shape, on one item:

  ```markdown
  {status_line}
  ```

- `{c.folder}/campaign.md`: front-matter `status: {final_status}`, nothing else.

## Out of scope

- Any code, any data, any new analysis, any change to kill rules or
  decisions. Suggestions in the report are suggestions: they are not run.
- The harness: `src/terrain/campaigns/`, `harness/`, the workflows in
  `.github/`, `AGENTS.md` and the skills in `.claude/skills/`. Checks in
  code are proposed in the report and nowhere else; notes go only in
  `{NOTES_PATH}`.

## Done when

1. `{c.folder}/ledger.md` holds the table above, unchanged.
2. `{c.folder}/report.md` opens with the four lines listed, one sentence
   each, and then has the {n_sections} sections listed, in that order.
3. Every number in `report.md` appears in a run record it cites by path
   (`research/explore-runs/...`) or in the ledger, the friction facts or
   the checks not run above,
   and every kill rule's outcome matches the ledger's Verdict column.
4. "Results and their limits" says plainly that these are exploration-half
   results and that nothing here is a finding, and has the item
   "Unexplained differences" (both numbers and both paths, or "None found").
5. "Stops and blocks" holds the friction facts unchanged and lists every row
   of their Blocks table; it says "none" only if that table says "None.".
6. "Checks not run" lists every item of "Checks not run" above with its
   reason; it says "None" only if that list says "None.".
7. "Proposed harness changes (at most three)" has the parts "Notes added"
   and "Checks in code proposed"; at most three checks, each with its
   friction fact, the check in one sentence and the file it would touch.
8. "Decisions for Gabriel" has at most three choices, each changing what
   happens next in the repository (the idea's status, registering, a
   follow-up), none about unused budget, each with options and one
   recommendation, and says the recommendation is the agent's, not his. The
   first is the idea's status, recommending one of {statuses}. The
   number on the report's "Decisions for you:" line is how many there are.
9. `research/lessons.md` has one new dated entry. In `{idea_file}`, the
   front-matter `status` is the status the first decision recommends and
   `updated` is today's date, and there is one new dated line under
   `## Status` that names that status, says it is the report's
   recommendation and that Gabriel accepts it by approving this pull
   request; nothing else in either file changes.
10. `{c.folder}/campaign.md` differs only in `status: {final_status}`.
11. In `{NOTES_PATH}`: at most {number_word(MAX_NEW_NOTES)} new notes, every one citing
    campaign {c.id} and a row of the friction facts above; the Scoreboard
    has exactly one new row, for campaign {c.id}; and
    `uv run python scripts/validate_records.py` passes.
12. Nothing outside the files under "In scope" changes: no harness file,
    workflow, `AGENTS.md` or skill.
13. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.

{markers.closeout_marker(c.id)}
"""
    return title, body
