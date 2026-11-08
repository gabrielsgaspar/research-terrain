"""Plain records of what GitHub says, filled in by `terrain.campaigns.github`.

The gate and the tick are pure functions of these records, so tests build
them by hand and never touch the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_REVIEW_HEAD = re.compile(r"^## Agent review: (Approve|Changes needed)", re.M)
_REVIEWED_SHA = re.compile(r"Reviewed commit `([0-9a-f]{7,40})`")
_REFEREE_ROW = re.compile(r"^\| (R[1-7]) \| [^|]*\| ([^|]+?) \|", re.M)
PLAN_PREFIX = "## Agent plan: "


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    created_at: str  # ISO 8601, UTC


@dataclass(frozen=True)
class Review:
    verdict: str  # "approve" or "changes"
    sha: str  # reviewed commit as printed (12 characters)
    referee: dict[str, str]  # R1..R7 -> "OK", "Problem", "Not applicable", "Not checked"
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
