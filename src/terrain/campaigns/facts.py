"""Plain records of what GitHub says, filled in by `terrain.campaigns.github`.

The gate and the tick are pure functions of these records, so tests build
them by hand and never touch the network.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_REVIEW_HEAD = re.compile(r"^## Agent review: (Approve|Changes needed)", re.M)
_REVIEWED_SHA = re.compile(r"Reviewed commit `([0-9a-f]{7,40})`")
_REFEREE_ROW = re.compile(r"^\| (R[1-8]) \| [^|]*\| ([^|]+?) \|", re.M)
PLAN_PREFIX = "## Agent plan: "
# agent-build's comment that starts its one automatic fix round (decision 0019)
BUILD_ROUND_PREFIX = "## Agent build: fix round"
# who posts the agent workflows' comments (plans, reviews, stops, fix rounds)
WORKFLOW_BOT = "github-actions[bot]"
# a line of an owner's merged pull request that unblocks a task issue; the act job of
# campaign-tick.yml checks the same line (bodies are read with "\r\n" made "\n")
UNBLOCKS_LINE = re.compile(r"^Unblocks #(\d+)$", re.M)

# Decision 0021: two comments agent-build's report job posts (github-actions[bot]) and the
# tick reads. Only a comment whose first and last lines match exactly counts.
BUILD_COMMENT_PREFIX = "## Agent build"
CONTRADICTION_FIRST = "## Agent build: contradiction (decision 0021)"
WAITING_FIRST = "## Agent build: waiting for main (decision 0021)"
_TEST_ID = r"[^\s,<>]{1,200}"  # a pytest node id: no spaces or commas, at most 200 characters
_CONTRADICTION_LAST = re.compile(r"^<!-- agent-build-contradiction: run (\d{1,20}) -->$")
_WAITING_LAST = re.compile(
    rf"^<!-- agent-build-waiting-for-main: run (\d{{1,20}}) sha ([0-9a-f]{{12}}) "
    rf"tests ({_TEST_ID}(?:,{_TEST_ID})*) -->$"
)
TEST_ID = re.compile(rf"^{_TEST_ID}$")
# an owner-fix issue (decision 0021): one per failing test, filed by the tick
_OWNERFIX = re.compile(rf"<!-- campaign-ownerfix: ({_TEST_ID}) -->")
QUOTE_CHARS = 300  # a quote of a contradiction is cut to this when the tick repeats it
MAX_QUOTES = 4


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    created_at: str  # ISO 8601, UTC


@dataclass(frozen=True)
class Review:
    verdict: str  # "approve" or "changes"
    sha: str  # reviewed commit as printed (12 characters)
    referee: dict[str, str]  # R1..R8 -> "OK", "Problem", "Not applicable", "Not checked"
    created_at: str


def parse_review(body: str, created_at: str = "") -> Review | None:
    head = _REVIEW_HEAD.search(body or "")
    sha = _REVIEWED_SHA.search(body or "")
    if not head or not sha:
        return None
    referee = {m.group(1): m.group(2).strip() for m in _REFEREE_ROW.finditer(body)}
    verdict = "approve" if head.group(1) == "Approve" else "changes"
    return Review(verdict, sha.group(1), referee, created_at)


@dataclass(frozen=True)
class Plan:
    title: str  # "Plan", "Needs clarification - no plan yet", "withheld", ...
    files: tuple[str, ...] | None
    created_at: str


def latest_plan(comments: list[Comment], bot: str = "github-actions[bot]") -> Plan | None:
    from terrain.campaigns.markers import parse_agent_files

    plans = [c for c in comments if c.author == bot and c.body.startswith(PLAN_PREFIX)]
    if not plans:
        return None
    last = max(plans, key=lambda c: c.created_at)
    title = last.body[len(PLAN_PREFIX) :].split("\n", 1)[0].strip()
    files = parse_agent_files(last.body)
    return Plan(title, tuple(files) if files is not None else None, last.created_at)


@dataclass(frozen=True)
class PullRequest:
    number: int
    author: str
    head_ref: str
    head_sha: str
    state: str  # "open" or "closed"
    merged: bool
    mergeable: bool | None  # None while GitHub is still computing it
    files: tuple[str, ...]
    ci_test: str | None  # conclusion of the `test` check on the head, None if not finished
    gate_status: str | None  # posted `campaign-gate` state on the head, None if none
    labels: tuple[str, ...] = ()
    reviews: tuple[Review, ...] = ()  # agent-review comments, oldest first
    approvals: tuple[str, ...] = ()  # logins whose latest GitHub review approves the head
    issue_body: str = ""  # for agent/issue-N: that issue's body
    issue_title: str = ""
    run_title: str = ""  # for explore/ and data/ branches: the run's display title
    run_conclusion: str | None = None
    created_at: str = ""
    merged_at: str = ""
    # (path, GitHub's status: added, modified, removed, renamed, ...) of each file, and
    # for a renamed file also its old path, as ("old path", "renamed-from")
    changes: tuple[tuple[str, str], ...] = ()
    run_workflow: str = ""  # for explore/, data/ and forks/ branches: the run's workflow file
    # for a fork plan pull request: (path, text) of each added file, read at the head
    added_texts: tuple[tuple[str, str], ...] = ()
    # the newest comment an agent workflow posted on the pull request (decision 0019)
    agent_note: Comment | None = None

    def review_of_head(self) -> Review | None:
        mine = [r for r in self.reviews if self.head_sha.startswith(r.sha)]
        return mine[-1] if mine else None


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]
    author: str
    created_at: str
    comments: tuple[Comment, ...] = ()
    pr: PullRequest | None = None  # the agent PR from agent/issue-N, newest


@dataclass(frozen=True)
class Run:
    id: int
    workflow: str  # file name, e.g. explore-run.yml
    title: str
    status: str  # queued, in_progress, completed
    conclusion: str | None
    created_at: str
    updated_at: str = ""


@dataclass(frozen=True)
class LogFacts:
    """What a failed data-pipeline run's whole log says, beyond its last lines.

    Read by `terrain.campaigns.repair.LogScanner`, already cleaned: the last
    error line ("build failed: ...", "acquire failed: ...", "...BuildError: ...")
    and the last profile `scripts/profile_failure.py` printed (decision 0016).
    """

    error: str = ""  # "" if the log has none
    profile: tuple[str, ...] = ()  # the profile's lines, a one-line "none" or "refused", or ()


@dataclass(frozen=True)
class LabelEvent:
    """One `agent-build` or `needs-human` label added to or removed from an issue.

    What the tick restarts a build from: who removed `needs-human` and when,
    and when a build was last started by a label (`terrain.campaigns.tick`).
    """

    label: str
    action: str  # "labeled" or "unlabeled"
    actor: str
    created_at: str
    id: int = 0  # GitHub's id of the event


@dataclass(frozen=True)
class MainCheck:
    """CI's `test` check on main's head commit."""

    sha: str
    state: str  # "failure", "success" or "pending" (running, or no check yet)
    url: str = ""  # the check run on GitHub


@dataclass(frozen=True)
class Unblock:
    """A merged pull request whose body has a line `Unblocks #<issue>`."""

    pr: int
    issue: int
    author: str
    merged_by: str
    merged_at: str


@dataclass
class Snapshot:
    """Everything the tick reads in one pass."""

    now: str
    enabled: bool
    app_bot: str
    issues: list[Issue] = field(default_factory=list)  # every issue labelled `campaign`
    runs: list[Run] = field(default_factory=list)
    record_prs: dict[int, PullRequest] = field(default_factory=dict)  # run id -> its record PR
    results: dict[str, object] = field(default_factory=dict)  # repo path -> parsed JSON on main
    files_on_main: frozenset[str] = frozenset()
    # failed data-pipeline run id -> the last lines its failed job printed, raw (the
    # tick reads "still exporting" from it; for campaigns with self_repair it also goes
    # into the repair task, cleaned by terrain.campaigns.repair)
    run_logs: dict[int, str] = field(default_factory=dict)
    # the repository's web address (server and owner/name), for links on the status
    # page; "" gives plain paths instead of links
    repo_url: str = ""
    # ideation run id -> its fork plan pull request (branch forks/NNNN-sNN-<run id>)
    fork_prs: dict[int, PullRequest] = field(default_factory=dict)
    # failed data-pipeline run id -> its error line and profile, read from the whole
    # log (decision 0016); only for runs whose log was read
    run_facts: dict[int, LogFacts] = field(default_factory=dict)
    # manifest path on main (data/manifests/<stage>/<target>.json) -> its data-rule notes
    # lines (`terrain.datarule`), only for manifests that have any
    data_rules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # restarts (the tick restarts stalled and unblocked builds):
    # issue number -> its agent-build and needs-human label events, oldest first; only
    # for open task issues that carry one of the two labels
    label_events: dict[int, tuple[LabelEvent, ...]] = field(default_factory=dict)
    # Agent build runs queued or in progress, for any issue (a run cannot be tied to
    # its issue from the API: a fix round's run carries no issue number)
    builds_in_flight: int = 0
    # the agent/issue-<n> branches that exist (agent-build refuses to start on one)
    branches: frozenset[str] = frozenset()
    # CI's test check on main's head commit; None if it was not read
    main_ci: MainCheck | None = None
    # recently merged pull requests with an `Unblocks #<n>` line
    unblocks: tuple[Unblock, ...] = ()

    @property
    def main_red(self) -> bool:
        """Did CI's test check fail on main's head commit?"""
        return self.main_ci is not None and self.main_ci.state == "failure"


def ownerfix_marker(test: str) -> str:
    """The marker of the owner-fix issue for failing test `test` (decision 0021)."""
    return f"<!-- campaign-ownerfix: {test} -->"


def parse_ownerfix(body: str) -> str | None:
    m = _OWNERFIX.search(body or "")
    return m.group(1) if m else None


def cut_quote(text: str) -> str:
    """One quote as the tick repeats it: one line, no hidden markers, cut to QUOTE_CHARS
    characters with a note that says it was cut."""
    one = " ".join((text or "").replace("<!--", "&lt;!--").replace("-->", "--&gt;").split())
    if len(one) <= QUOTE_CHARS:
        return one
    return f"{one[:QUOTE_CHARS].rstrip()}... (cut at {QUOTE_CHARS} characters)"


@dataclass(frozen=True)
class Contradiction:
    """A valid Comment C: the builder found two instructions, neither stricter."""

    run: int  # the build run that posted it
    quotes: tuple[str, ...]  # the quoted texts as written (not yet cut)
    created_at: str


@dataclass(frozen=True)
class Waiting:
    """A valid Comment W: the build waits for main to pass the tests listed."""

    run: int
    sha: str  # first 12 characters of main's head when the build ran
    tests: tuple[str, ...]
    created_at: str


def _lines(comment: Comment) -> list[str]:
    return comment.body.replace("\r\n", "\n").rstrip().split("\n")


def _quotes(middle: list[str]) -> tuple[str, ...]:
    """The block quotes (`> ...` lines) between a comment's first and last lines; with
    none, the whole text between them as one quote."""
    found: list[list[str]] = []
    open_ = False
    for line in middle:
        if line.startswith(">") and line[1:].strip():
            if not open_:
                found.append([])
            found[-1].append(line[1:].strip())
            open_ = True
        else:
            open_ = False
    quotes = [" ".join(q) for q in found] or [" ".join(x.strip() for x in middle if x.strip())]
    return tuple(q for q in quotes if q)[:MAX_QUOTES]


def parse_contradiction(comment: Comment, bot: str = WORKFLOW_BOT) -> Contradiction | None:
    if comment.author != bot:
        return None
    lines = _lines(comment)
    last = _CONTRADICTION_LAST.match(lines[-1]) if len(lines) > 1 else None
    if lines[0] != CONTRADICTION_FIRST or not last:
        return None
    return Contradiction(int(last.group(1)), _quotes(lines[1:-1]), comment.created_at)


def parse_waiting(comment: Comment, bot: str = WORKFLOW_BOT) -> Waiting | None:
    if comment.author != bot:
        return None
    lines = _lines(comment)
    last = _WAITING_LAST.match(lines[-1]) if len(lines) > 1 else None
    if lines[0] != WAITING_FIRST or not last:
        return None
    return Waiting(
        int(last.group(1)), last.group(2), tuple(last.group(3).split(",")), comment.created_at
    )


def contradiction_of(comments: Sequence[Comment]) -> Contradiction | None:
    """The newest valid Comment C on an issue, if any."""
    found = [c for c in map(parse_contradiction, comments) if c]
    return max(found, key=lambda c: c.created_at, default=None)


def latest_waiting(comments: Sequence[Comment]) -> Waiting | None:
    """The newest agent-build comment, if it is a valid Comment W. Any later agent-build
    comment (a fix round, a stop, a contradiction) means the build went on."""
    builds = [
        (c.created_at, k, c)
        for k, c in enumerate(comments)
        if c.author == WORKFLOW_BOT and c.body.startswith(BUILD_COMMENT_PREFIX)
    ]
    return parse_waiting(max(builds, key=lambda b: b[:2])[2]) if builds else None
