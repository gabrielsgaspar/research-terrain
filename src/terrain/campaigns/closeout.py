"""The close-out task: the issue the tick files when a campaign finishes.

The body is generated from the campaign file and what the tick saw, so the
builder gets every fact it needs (steps, verdicts, runs, budget used, the
friction facts: blocks, extra plans and fix rounds, repeated runs, long gaps,
and the checks not run: unfinished steps, kill rules never applied, referee
rows marked not applicable) as data. From those facts the close-out adds at
most three notes of advice to `research/agent-notes.md`, which every agent
reads (decision 0013), and one Scoreboard row; checks in code it only
proposes, in the report.
The learning loop: every friction fact gets a cause and a category from
STOP_CAUSES. Notes learn only from agent, spec and design stops; plumbing
stops go to FAILURE_LOG_PATH, in a dated section the tick writes and the
close-out appends unchanged (the gate checks it). The tick files one
close-out at a time, so note ids (chosen by code, `next_note_id`) and
Scoreboard rows never clash.
The close-out PR touches owned paths (the idea file, campaign.md, the notes),
so the owner always approves it: it is where he reads the report and decides.
It also sets the idea's status to the report's recommendation (one of
RECOMMENDED_STATUSES), so the idea's status follows its campaign; approving
the pull request accepts it, and scripts/validate_records.py catches drift.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.spec import NOTES_PATH, Campaign

# -- the learning loop: a cause and a category for every stop ------------------------
#
# Every friction fact the tick hands the close-out (a block, a fix round, a retry, a
# restart, an unblock, a skip, a wait for main, the reason the campaign ended) gets one
# cause, a key of STOP_CAUSES, and so one category:
#   plumbing: the harness let the work down (a limit, a timeout, a stall with no PR, a
#             closed-PR stop, a race between ticks, a test broken on main, a runner or API
#             failure). It goes to FAILURE_LOG_PATH, never into an agent note.
#   spec:     a contradiction, or an unclear issue, plan or draft.
#   design:   a kill rule, a budget or the campaign's design stopped the work.
#   agent:    an agent's own error, such as a failing test it wrote or a fix round.
#   handled:  the tick resolved it without Gabriel (automatic restarts and retries).
# Only agent, spec and design facts give agent notes (NOTE_CATEGORIES).

FAILURE_LOG_PATH = "harness/failure-log.md"
CATEGORIES = ("plumbing", "spec", "design", "agent", "handled")
NOTE_CATEGORIES = ("agent", "spec", "design")
REPAIR_PREFIX = "the repair task: "


@dataclass(frozen=True)
class StopCause:
    category: str  # one of CATEGORIES
    words: str  # the cause in plain words, as the close-out issue shows it
    # for a block: a regular expression its cause text (the ledger line's "Cause:") matches;
    # "" for a cause the tick names some other way
    detail: str = ""


# The one table. Order matters for blocks: the first cause whose `detail` matches wins.
STOP_CAUSES: dict[str, StopCause] = {
    # blocks, read from the cause text of the ledger line that posted them
    "budget": StopCause(
        "design", "the model-job budget was used up", r"the model-job budget is used up"
    ),
    "needs_human": StopCause(
        "agent",
        "an agent stopped and asked for a person (needs-human)",
        r"^an agent stopped and labelled it needs-human",
    ),
    "no_plan": StopCause(
        "plumbing",
        "no plan in time after filing (the plan run failed or never ran)",
        # "two hours", or the hours ops/limits.yaml names ("2 hours")
        r"^no plan .+ after filing",
    ),
    "planner_question": StopCause(
        "spec", "the planner asked a question instead of planning", r"^the planner answered '"
    ),
    "plan_paths": StopCause(
        "spec",
        "the plan's file list does not fit the step (its allowed paths or its lane)",
        # no file list, no files, files outside the step, protected or owned paths, or a
        # lane refused by decision 0020
        r"^the plan (has no machine-readable file list|lists )",
    ),
    "build_stalled": StopCause(
        "plumbing",
        "no pull request in time after the build started (a stall)",
        # also the block once the automatic restarts are used up
        r"^(no pull request .+ after |the build stalled again after )",
    ),
    "branch_exists": StopCause(
        "plumbing",
        "an earlier build's branch was left behind, so the build could not start again",
        r"^an earlier build's branch ",
    ),
    "pr_closed": StopCause(
        "plumbing",
        "a pull request was closed without merging",
        r"^(record )?PR #\d+ was closed without merging",
    ),
    "issue_closed": StopCause(
        "plumbing",
        "the issue was closed without a merged pull request",
        r"^the issue was closed without a merged pull request",
    ),
    "conflict": StopCause(
        "plumbing",
        "a merge conflict: two pull requests changed the same lines",
        r"^PR #\d+ has a merge conflict",
    ),
    "gate_failed": StopCause(
        "agent",
        "the campaign gate refused the pull request",
        r"^(Campaign \d{4}\b|Fork files are append-only|The pull request is not open)",
    ),
    "stopped_or_ended": StopCause(
        "design",
        "the campaign was stopped or past its end date, so a run was not started again",
        r"but the campaign is stopped or past its end date",
    ),
    "run_timed_out": StopCause("plumbing", "a run ran out of time", r"^run \d+ ended 'timed_out'"),
    "still_exporting": StopCause(
        "handled",
        "a run still exporting, started again by the tick",
        r"^run \d+ is still exporting",
    ),
    "run_failed": StopCause(
        "agent", "a run failed after its retries (the code failed on the data)", r"^run \d+ ended '"
    ),
    "never_appeared": StopCause(
        "plumbing",
        "a run or task was started but never appeared (a runner or API failure)",
        r"never appeared$",
    ),
    "record_missing": StopCause(
        "plumbing",
        "no record pull request in time after the run",
        r"^no record pull request .+ after the run",
    ),
    "unreadable": StopCause(
        "agent",
        "a kill rule could not be applied to the run's results",
        r"^a kill rule could not be applied",
    ),
    # a needs-human block whose agent-build comment before it was the second
    # "waiting for main" (decision 0021): the test was broken on main
    "needs_human_main": StopCause("plumbing", "the build waited twice for a test broken on main"),
    # a stall block the tick itself restarted (#502)
    "build_stalled_restarted": StopCause("handled", "a stall the tick restarted by itself"),
    # a block line the table cannot read (ledgers older than this table); shown as such
    "unrecognised": StopCause("plumbing", "a block whose cause text this table does not know"),
    # the other friction facts
    "fix_round": StopCause("agent", "a fix round: the first build or review did not pass"),
    "extra_plan": StopCause("spec", "more than one plan: the first was not usable"),
    "retry": StopCause("handled", "a failed run the tick started again by itself"),
    "continue": StopCause("handled", "a run still exporting, started again by the tick"),
    "repair": StopCause("agent", "a run failed after both retries and got a repair task"),
    "restart_stalled": StopCause("handled", "the tick restarted a stalled build"),
    "restart_red": StopCause("handled", "the tick restarted a build once main was green"),
    "restart_main": StopCause("handled", "the tick restarted a build once main passed its tests"),
    "main_red_stop": StopCause("plumbing", "the build stopped while main was red"),
    "waiting_for_main": StopCause("plumbing", "the build waited for a test broken on main"),
    "owner_unblock": StopCause(
        "agent", "you restarted or unblocked a build the tick saw no block on"
    ),
    "decision_0021": StopCause("spec", "two instructions contradicted each other (decision 0021)"),
    "kill_skip": StopCause("design", "skipped because a kill rule stopped an earlier step"),
    "kill_rule": StopCause("design", "a kill rule ended the campaign"),
    "budget_ran_out": StopCause("design", "the campaign's budget ran out"),
    "end_date": StopCause("design", "the campaign's end date passed"),
}


def block_cause(detail: str) -> str:
    """The STOP_CAUSES key of a block, from the cause text of its ledger line.

    A repair's block ("the repair task: ...") takes the cause of the text after
    the prefix. Text the table does not know gives "unrecognised", never a guess.
    """
    text = detail.strip().removeprefix(REPAIR_PREFIX)
    for key, cause in STOP_CAUSES.items():
        if cause.detail and re.search(cause.detail, text):
            return key
    return "unrecognised"


@dataclass(frozen=True)
class Stop:
    """One friction fact with its cause: what the learning loop counts and learns from."""

    step: str  # "s1", or "close-out", or "campaign" for the reason it ended
    fact: str  # what happened, in a few words ("block", "wait for main", "retry", ...)
    cause: str  # a key of STOP_CAUSES
    detail: str  # the tick's own words
    when: str = ""  # when it was posted (ISO 8601, UTC), if known
    hours: float | None = None  # hours lost, if the ledger shows them
    needed_you: bool = False  # it waited for Gabriel

    @property
    def category(self) -> str:
        return STOP_CAUSES[self.cause].category


def stop_counts(stops: Sequence[Stop]) -> tuple[int, int]:
    """(stops for Gabriel, plumbing stops), the Scoreboard's last two columns."""
    mine = [s for s in stops if s.needed_you]
    return len(mine), sum(1 for s in mine if s.category == "plumbing")


def _hours_text(hours: float | None) -> str:
    return f"{hours:.1f}" if hours is not None else "-"


STOPS_HEADER = ["Step", "Fact", "Cause", "Category", "Needed you", "Posted", "Hours lost"]


def stops_table(stops: Sequence[Stop]) -> str:
    """Every friction fact with its cause and category, or "None."."""
    if not stops:
        return "None."
    rows = [
        [
            s.step,
            s.fact,
            f"{STOP_CAUSES[s.cause].words}: {s.detail}" if s.detail else STOP_CAUSES[s.cause].words,
            s.category,
            "yes" if s.needed_you else "no",
            s.when or "-",
            _hours_text(s.hours),
        ]
        for s in stops
    ]
    return table(STOPS_HEADER, rows)


FAILURE_LOG_HEADER = ["Step", "Stop", "Cause", "Hours lost"]
_FENCE = "~~~~"
_LOG_HEADING = "## Failure log section (written by the tick; append as is)"
_LOG_BLOCK = re.compile(
    re.escape(_LOG_HEADING) + r"\n.*?\n" + _FENCE + r"markdown\n(.*?)\n" + _FENCE + r"\n", re.S
)


def failure_log_section(c: Campaign, stops: Sequence[Stop], day: str) -> str:
    """The dated section this close-out appends to FAILURE_LOG_PATH: each plumbing stop,
    with its cause and hours lost. Written by code; the close-out agent copies it."""
    plumbing = [s for s in stops if s.category == "plumbing"]
    rows = [
        [s.step, s.fact, f"{STOP_CAUSES[s.cause].words}: {s.detail}", _hours_text(s.hours)]
        for s in plumbing
    ]
    lost = sum(s.hours for s in plumbing if s.hours is not None)
    summary = (
        f"{len(plumbing)} plumbing stop{'s' if len(plumbing) != 1 else ''}, {lost:.1f} hours lost."
        if plumbing
        else "No plumbing stop."
    )
    body = table(FAILURE_LOG_HEADER, rows) if rows else ""
    text = (
        f"## {day}: campaign {c.id} ({c.title})\n\n"
        "Written by the campaign tick from the close-out's categorised friction facts. "
        f"{summary}" + (f"\n\n{body}" if body else "")
    )
    return text.replace(_FENCE, "~ ~ ~ ~")


def failure_log_section_of(body: str) -> str | None:
    """The failure-log section a close-out issue carries, or None (issues filed before it)."""
    m = _LOG_BLOCK.search((body or "").replace("\r\n", "\n"))
    return m.group(1) if m else None


def appended(base: str, section: str) -> str:
    """`base` (the log on main) with `section` appended after one blank line."""
    base = base.replace("\r\n", "\n").rstrip("\n")
    return (f"{base}\n\n" if base else "") + section.strip("\n") + "\n"


def failure_log_problem(head: str | None, base: str, section: str | None, touched: bool) -> str:
    """Why a close-out PR's change to FAILURE_LOG_PATH is refused ("" if it is not).

    `head` is the file at the PR's head commit (None if it could not be read),
    `base` the file on main, `section` the one the close-out issue carries. The
    only change allowed is appending exactly that section: earlier sections are
    never edited.
    """
    if section is None:  # an issue filed before the failure log: the log stays as it is
        refused = f"{FAILURE_LOG_PATH} may change only by the section its issue carries"
        return refused if touched else ""
    if not touched:
        return f"the close-out must append its section to {FAILURE_LOG_PATH}"
    if head is None:
        return f"{FAILURE_LOG_PATH} could not be read at the head commit"
    if head.replace("\r\n", "\n").rstrip() != appended(base, section).rstrip():
        return (
            f"{FAILURE_LOG_PATH} may only gain the issue's section at its end; "
            "earlier sections are never edited"
        )
    return ""


_NOTE_NUMBER = re.compile(r"\bN(\d{3})\b")


def next_note_id(root: Path) -> str:
    """The id of the next note: one more than the highest id the notes file names
    anywhere (removed notes are named in its introduction, so no id is used twice)."""
    path = root / NOTES_PATH
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return f"N{max((int(n) for n in _NOTE_NUMBER.findall(text)), default=0) + 1:03d}"


def read_scoreboard(root: Path) -> list[dict[str, str]]:
    """The Scoreboard rows of the notes file, by column name, in file order."""
    path = root / NOTES_PATH
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Scoreboard")
    except ValueError:
        return []
    rows = [ln for ln in lines[start + 1 :] if ln.startswith("|")]
    if not rows:
        return []
    header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    out = []
    for row in rows[2:]:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) == len(header):
            out.append(dict(zip(header, cells, strict=True)))
    return out


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
    "Stops for Gabriel",
    "Plumbing stops",
)
# Rows for campaigns before this one may say "n/a" in the last two columns: their
# ledgers and reports do not always show a stop's cause.
SCOREBOARD_NA_BEFORE = "0015"

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
    stops: Sequence[Stop] = (),
    today: str = "",
) -> tuple[str, str]:
    """(title, body) of the close-out issue.

    `not_run` holds the tick's checks not run, one line each (`checks_not_run`
    in `terrain.campaigns.tick`): the report must list every one of them.
    `stops` are the friction facts with their causes (`stop_facts` in the tick);
    with `today` (YYYY-MM-DD) the issue also carries the dated section the
    close-out appends to FAILURE_LOG_PATH.
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
    first_id = next_note_id(root)
    note_shape = (
        f"- [{first_id}] (role) Advice in one sentence. From: campaign {c.id}, "
        "the friction fact in a few words. Added YYYY-MM-DD."
    )
    mine, plumbing = stop_counts(stops)
    score_row = (
        f"| {c.id} | {len(c.steps)} | blocks | fix rounds | retries | hours | notes added "
        f"| {mine} | {plumbing} |"
    )
    learn = ", ".join(NOTE_CATEGORIES[:-1]) + f" or {NOTE_CATEGORIES[-1]}"
    log_block = (
        f"""{_LOG_HEADING}

Append the text between the two `{_FENCE}` lines to the end of
`{FAILURE_LOG_PATH}`, after one blank line, unchanged. Change nothing else in
that file: earlier sections are never edited, and the gate refuses any other
change.

{_FENCE}markdown
{failure_log_section(c, stops, today)}
{_FENCE}

"""
        if today
        else ""
    )
    log_scope = (
        f"""
- `{FAILURE_LOG_PATH}`: append the failure log section above at the end,
  unchanged. Nothing else in the file changes."""
        if today
        else ""
    )
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

## Stops by cause (written by the tick; copy as is)

Every friction fact above, and the reason the campaign ended, with its cause
and category (`STOP_CAUSES` in `src/terrain/campaigns/closeout.py`).
"Needed you" says whether it waited for Gabriel; hours lost run until it was
unblocked, or until the work ended.

{stops_table(stops)}

{log_block}{_forks_block(forks)}## Checks not run (written by the tick; copy as is)

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
  - "Stops and blocks" copies the friction facts and the "Stops by cause"
    table above as they are, and lists every row of their Blocks table. It
    may say "none" only when that table says "None.".
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
  - Notes learn only from agent, spec and design stops. Each note answers
    one row of "Stops by cause" whose category is one of {learn}. A
    plumbing or handled fact gives no agent note: a plumbing stop is the
    harness's fault and goes to `{FAILURE_LOG_PATH}` instead (the section
    above), and a handled one the tick already resolved.
  - Add at most {number_word(MAX_NEW_NOTES)} notes under `## Notes`, each for one role:
    {roles}. Use exactly this shape, one line each, numbering from
    {first_id} up (the tick chose it; never reuse an id):
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
    number of notes this task added. The last two numbers, stops for
    Gabriel and plumbing stops, are the tick's, from "Stops by cause":
    copy them as they are. Columns: {score_header}.
  - If no row of "Stops by cause" is {learn}, add no note and still add
    the row.
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
{log_scope}

- `{c.folder}/campaign.md`: front-matter `status: {final_status}`, nothing else.

## Out of scope

- Any code, any data, any new analysis, any change to kill rules or
  decisions. Suggestions in the report are suggestions: they are not run.
- The harness: `src/terrain/campaigns/`, `harness/` (but for appending
  the failure log section, if this issue carries one), the workflows in
  `.github/`, `AGENTS.md` and the skills in `.claude/skills/`. Checks in
  code are proposed in the report and nowhere else; notes go only in
  `{NOTES_PATH}`.

## Done when

1. `{c.folder}/ledger.md` holds the table above, unchanged.
2. `{c.folder}/report.md` opens with the four lines listed, one sentence
   each, and then has the {n_sections} sections listed, in that order.
3. Every number in `report.md` appears in a run record it cites by path
   (`research/explore-runs/...`) or in the ledger, the friction facts, the
   stops by cause or the checks not run above,
   and every kill rule's outcome matches the ledger's Verdict column.
4. "Results and their limits" says plainly that these are exploration-half
   results and that nothing here is a finding, and has the item
   "Unexplained differences" (both numbers and both paths, or "None found").
5. "Stops and blocks" holds the friction facts and the stops by cause
   unchanged and lists every row of their Blocks table; it says "none" only
   if that table says "None.".
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
    campaign {c.id} and a row of "Stops by cause" whose category is one of
    {learn}, numbered from {first_id}; the Scoreboard has exactly one new
    row, for campaign {c.id}, ending in the tick's `| {mine} | {plumbing} |`; and
    `uv run python scripts/validate_records.py` passes.
12. Nothing outside the files under "In scope" changes: no harness file
    (but for the appended failure log section), workflow, `AGENTS.md` or
    skill.
13. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.

{markers.closeout_marker(c.id)}
"""
    return title, body
