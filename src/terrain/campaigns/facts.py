"""Plain records of what GitHub says, filled in by `terrain.campaigns.github`.

The gate and the tick are pure functions of these records, so tests build
them by hand and never touch the network.
"""

from __future__ import annotations

import re
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
