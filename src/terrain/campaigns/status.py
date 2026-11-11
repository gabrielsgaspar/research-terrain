"""The status page: one issue that shows where every campaign stands.

The tick renders the page from the views it has just built (`tick.decide`
with `status_page=True`) and from the files on main, and rewrites the issue
titled STATUS_TITLE only when the rendered body differs from the one on
GitHub. The page holds no clock time of its own: every time on it is the
time of a ledger comment, so a repeated tick with nothing new renders the
same body and does nothing.

The issue is found by its hidden marker (`markers.status_marker`), which no
other reader in the tick or the gate looks for; text copied onto the page
from GitHub has its HTML comments defused, so the page never carries a
step, tracking, close-out, repair or ledger marker.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.facts import Issue, Snapshot
from terrain.campaigns.gate import GateContext, closeout_paths
from terrain.campaigns.spec import Campaign, read_front_matter
from terrain.campaigns.tick import (
    IN_FLIGHT,
    NEEDS_YOU,
    NEEDS_YOU_DEFAULT,
    CampaignView,
    StepState,
    _items,
    _ledger_events,
    _own_issues,
    _task_state,
    _time,
    breaker_line,
)

STATUS_TITLE = "Research Terrain: status"
MAX_CHARS = 20_000  # the whole body; GitHub allows 65,536
ITEM_CHARS = 1_000  # one line or table cell, so no single item can crowd out the rest
HANDLED_LINES = 10
CLOSED_CAMPAIGNS = 5

NOTHING_WAITS = "Nothing. Everything is running or finished."

# A step's state in plain words, for the "Running" table.
PLAIN = {
    "unstarted": "not started",
    "waiting": "waiting for an earlier step",
    "filed": "filed; the planner starts next",
    "planning": "the planner is writing a plan",
    "plan_ready": "planned; the build starts next",
    "building": "the builder is writing the pull request",
    "in_review": "in review",
    "mergeable": "passed every check; the tick merges it next",
    "awaiting_gate": "passed; the gate check is posted next",
    "waiting_run": "the run was started and should appear soon",
    "running": "the run is going",
    "recording": "the run ended; its record is being written",
    "retry_waiting": "the run failed; it starts again once the run limits allow",
    "repair_waiting": "the run still fails; a repair task is filed once no other task is going",
    "repair_filing": "a repair task was just filed",
    "repair_merged": "the repair merged; the run starts again",
    "blocked": "blocked (see Waiting on you)",
    "done": "done",
    "skipped": "skipped",
}

# Ledger lines the tick wrote for things it handled by itself (tick.decide's wording).
_RETRY = re.compile(r"^(s\d{1,2}): run \d+ ended '[a-z_]+'\. Retrying by itself")
_REPAIR = re.compile(
    r"^(s\d{1,2}): (run \d+ ended '[a-z_]+' after \d+ retries\. Filing a repair task"
    r"|repair filed as #\d+\.|repair PR #\d+ merged\.|started .+ again after the repair)"
)
_UNBLOCKED = re.compile(r"^(s\d{1,2}|close-out): unblocked\.$")
_FINISHED = re.compile(r"^Campaign finished: (.+?)\. Filing the close-out task\.$")


def _safe(text: str) -> str:
    """Text from GitHub, with HTML comments defused so it carries no hidden marker."""
    return text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")


def _clip(text: str, n: int = ITEM_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _when(iso: str) -> str:
    """A ledger time as `2026-11-10 11:30 UTC`."""
    return _time(iso).astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _file(snap: Snapshot, path: str) -> str:
    return f"[`{path}`]({snap.repo_url}/blob/main/{path})" if snap.repo_url else f"`{path}`"


def _links(st: StepState, snap: Snapshot) -> str:
    """Like `StepState.links`, with the run and the record as links."""
    parts = []
    if st.issue:
        parts.append(f"#{st.issue.number}")
    if st.repair and st.repair is not st.issue:
        parts.append(f"repair #{st.repair.number}")
    if st.pr:
        parts.append(f"PR #{st.pr.number}")
    if st.run:
        run = f"run {st.run.id}"
        parts.append(f"[{run}]({snap.repo_url}/actions/runs/{st.run.id})" if snap.repo_url else run)
    if st.record:
        parts.append(_file(snap, st.record))
    return ", ".join(parts)


def _campaign(c: Campaign, tracking: Issue | None) -> str:
    return f"{c.id} {_safe(c.title)}" + (f" (#{tracking.number})" if tracking else "")


def _closeout_state(
    v: CampaignView, snap: Snapshot, gctx: GateContext, root: Path
) -> StepState | None:
    """The close-out task's state, as the tick reads it, or None before it is filed."""
    if v.closeout is None:
        return None
    return _task_state(v.closeout, closeout_paths(v.campaign, root), snap, gctx, allow_owned=True)


# -- the sections -------------------------------------------------------------------


def _block_item(
    c: Campaign, label: str, st: StepState, snap: Snapshot, tracking: Issue | None
) -> str:
    cause = _safe(st.detail.strip())
    stop = "" if cause.endswith(".") else "."
    action = NEEDS_YOU.get(st.cause, NEEDS_YOU_DEFAULT)
    where = _links(st, snap) or (f"#{tracking.number}" if tracking else "no links")
    item = (
        f"- Campaign {c.id}, {label} ({where}): blocked. Cause: {cause}{stop} Needs you: {action}."
    )
    if st.run_again:
        item += f"\n  - {st.run_again}"
    return _clip(item)


def waiting_on_you(
    views: Sequence[CampaignView], snap: Snapshot, gctx: GateContext, root: Path
) -> list[str]:
    """One line per thing Gabriel must do: blocks, reports to approve, pauses,
    and a circuit breaker that holds (its blocks follow it).

    Once a campaign's close-out is filed, its steps no longer hold anything up
    (nothing more starts), so only the close-out itself can be listed.
    """
    out: list[str] = []
    for v in views:
        c, tracking = v.campaign, v.tracking
        if tracking is None:
            continue
        if "campaign-pause" in tracking.labels:
            out.append(
                f"- Campaign {c.id} is paused (#{tracking.number}). To let it go on, remove "
                "the `campaign-pause` label in the right-hand column of that issue."
            )
        cst = _closeout_state(v, snap, gctx, root)
        if cst is None and v.breaker:
            out.append(
                _clip(f"- Campaign {c.id} (#{tracking.number}): {breaker_line(c, v.breaker)}")
            )
        if cst is None:
            for s in c.steps:
                st = v.states[s.id]
                if st.status == "blocked":
                    out.append(_block_item(c, f"step {s.id}", st, snap, tracking))
        elif cst.status == "blocked":
            out.append(_block_item(c, "close-out", cst, snap, tracking))
        elif cst.status == "mergeable" and c.owner not in cst.pr.approvals:
            out.append(
                f"- Campaign {c.id}: the report is ready in PR #{cst.pr.number}. To accept it, "
                "open the pull request, choose Files changed, then Review changes, then "
                "Approve; it is then merged for you. To reject it, close the pull request."
            )
    return out


def _now(v: CampaignView, cst: StepState | None, snap: Snapshot) -> str:
    """What the campaign is doing, in plain words."""
    parts = []
    for s in v.campaign.steps:
        st = v.states[s.id]
        if st.status not in IN_FLIGHT:
            continue
        words = PLAIN.get(st.status, st.status)
        if st.status == "in_review" and st.detail:
            words += f": {_safe(st.detail)}"
        if st.repairing:
            words = f"its repair task: {words}"
        where = _links(st, snap)
        parts.append(f"{s.id}{f' ({where})' if where else ''}: {words}")
    if cst is not None:
        where = _links(cst, snap)
        parts.append(f"close-out ({where}): {PLAIN.get(cst.status, cst.status)}")
    if not parts:
        blocked = [s.id for s in v.campaign.steps if v.states[s.id].status == "blocked"]
        if blocked:
            parts.append(f"{', '.join(blocked)} blocked (see Waiting on you)")
        else:
            parts.append("nothing in progress")
    if v.tracking is not None and "campaign-pause" in v.tracking.labels:
        parts.insert(0, "paused")
    elif v.tracking is None:
        parts = ["the tracking issue is being opened"]
    return "; ".join(parts)


def running(
    views: Sequence[CampaignView], snap: Snapshot, gctx: GateContext, root: Path
) -> list[list[str]]:
    """One table row per active campaign."""
    rows = []
    for v in views:
        c = v.campaign
        done = sum(1 for st in v.states.values() if st.status == "done")
        skipped = sum(1 for st in v.states.values() if st.status == "skipped")
        steps = f"{done} of {len(c.steps)}" + (f" ({skipped} skipped)" if skipped else "")
        last = max(v.events.values(), key=_time, default="")
        rows.append(
            [
                _campaign(c, v.tracking),
                steps,
                _now(v, _closeout_state(v, snap, gctx, root), snap),
                _when(last) if last else "none yet",
                f"{v.used['max_model_jobs']} of {c.budget['max_model_jobs']}",
                c.end_by,
            ]
        )
    return rows


def _kind(line: str, events: set[str]) -> bool:
    """Is this ledger line one the tick handled by itself (and does its event say so)?"""
    for pattern, event in (
        (_RETRY, ":retry:"),
        (_REPAIR, ":repair:"),
        (_UNBLOCKED, ":unblocked"),
    ):
        m = pattern.match(line)
        if m:
            sid = "closeout" if m.group(1) == "close-out" else m.group(1)
            return any(e.startswith(sid + event) for e in events)
    return False


def handled(campaigns: Sequence[Campaign], snap: Snapshot) -> list[str]:
    """Every retry, repair and unblock line in the ledgers, newest first."""
    found: list[tuple[str, int, str, str]] = []
    for c in campaigns:
        _, tracking, _ = _own_issues(c, snap)
        for cm in tracking.comments if tracking else ():
            parsed = markers.parse_ledger(cm.body) if cm.author == snap.app_bot else None
            if not parsed or parsed[0] != c.id:
                continue
            for k, line in enumerate(_items(cm.body)):
                if _kind(line, parsed[1]):
                    found.append((cm.created_at, k, c.id, line))
    found.sort(key=lambda f: (_time(f[0]), -f[1], f[2]), reverse=True)
    return [
        _clip(f"- {_when(when)}, campaign {cid}: {_safe(line)}") for when, _, cid, line in found
    ]


def recently_closed(ended: Sequence[Campaign], snap: Snapshot, root: Path) -> list[str]:
    """Done and stopped campaigns, the most recently finished first."""
    rows: list[tuple[str, str, str]] = []
    for c in ended:
        _, tracking, _ = _own_issues(c, snap)
        events = _ledger_events(tracking, c.id, snap.app_bot)
        when = events.get("finished") or events.get("closed") or ""
        reason = ""
        for cm in tracking.comments if tracking else ():
            if cm.author != snap.app_bot or not markers.parse_ledger(cm.body):
                continue
            for line in _items(cm.body):
                m = _FINISHED.match(line)
                reason = reason or (m.group(1) if m else "")
        how = f"{c.status}: {_safe(reason)}" if reason else c.status
        report = f"{c.folder}/report.md"
        link = f"report {_file(snap, report)}" if (root / report).is_file() else "no report file"
        at = f", finished {_when(when)}" if when else ""
        rows.append((when, c.id, f"- {_campaign(c, tracking)}: {how}{at}; {link}."))
    dated = sorted((r for r in rows if r[0]), key=lambda r: (_time(r[0]), r[1]), reverse=True)
    undated = sorted((r for r in rows if not r[0]), key=lambda r: r[1], reverse=True)
    return [_clip(line) for _, _, line in dated + undated]


def _records(root: Path, folder: str) -> list[tuple[str, dict]]:
    out = []
    for path in sorted((root / "research" / folder).glob("[0-9][0-9][0-9][0-9]-*.md")):
        fm = read_front_matter(path.read_text(encoding="utf-8"))
        if isinstance(fm, dict):
            out.append((path.relative_to(root).as_posix(), fm))
    return out


def loose_ends(
    active: Sequence[Campaign], ended: Sequence[Campaign], snap: Snapshot, root: Path
) -> list[str]:
    """Ideas left open after their campaigns finished, and decisions still proposed."""
    out = []
    for path, fm in _records(root, "ideas"):
        idea, status = str(fm.get("id", "")), str(fm.get("status", ""))
        done = [c.id for c in ended if c.idea == idea]
        if status in ("proposed", "exploring") and done and not any(c.idea == idea for c in active):
            out.append(
                f"- Idea {idea} ({_file(snap, path)}) is still `{status}` although campaign"
                f"{'s' if len(done) > 1 else ''} {', '.join(done)} finished and none is "
                "active: give it the status its campaigns found."
            )
    for path, fm in _records(root, "decisions"):
        if str(fm.get("status", "")) == "proposed":
            out.append(
                f"- Decision {fm.get('id', '')} ({_file(snap, path)}) is still `proposed`: "
                "accept or reject it."
            )
    return [_clip(_safe(line)) for line in out]


# -- the page -------------------------------------------------------------------------


@dataclass
class _Section:
    title: str
    items: list[str]
    empty: str
    noun: str  # what the left-out line counts
    header: list[str] = field(default_factory=list)  # a table: items are its rows
    left_out: int = 0

    def text(self) -> str:
        if not self.items and not self.left_out:
            return f"## {self.title}\n\n{self.empty}"
        shown = "\n".join([*self.header, *self.items]) if self.items else ""
        cut = f"{self.left_out} more {self.noun} left out." if self.left_out else ""
        return f"## {self.title}\n\n" + "\n\n".join(x for x in (shown, cut) if x)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(_clip(x).replace("|", "\\|").replace("\n", " ") for x in cells) + " |"


def _page(sections: list[_Section]) -> str:
    intro = (
        "Where every campaign stands and what is waiting for you, rewritten by the "
        "`campaign-tick` workflow whenever something changes. Times are those of the "
        "ledger comments on each tracking issue."
    )
    body = "\n\n".join([intro, *(s.text() for s in sections)])
    return f"{body}\n\n{markers.status_marker()}"


def fit(sections: list[_Section], limit: int = MAX_CHARS) -> str:
    """The page, cut to `limit` characters: items go from the end of the least
    important list first (the last section), each cut counted in its list."""
    body = _page(sections)
    while len(body) > limit:
        cuttable = [s for s in sections if s.items]
        if not cuttable:
            break
        cuttable[-1].items.pop()
        cuttable[-1].left_out += 1
        body = _page(sections)
    return body


def render(
    views: Sequence[CampaignView],
    ended: Sequence[Campaign],
    snap: Snapshot,
    gctx: GateContext,
    root: Path,
    limit: int = MAX_CHARS,
) -> str:
    """The status page's body. Pure: GitHub facts from `snap`, records from `root`."""
    active = [v.campaign for v in views]
    lines = handled([*active, *ended], snap)
    closed = recently_closed(ended, snap, root)
    sections = [
        _Section("Waiting on you", waiting_on_you(views, snap, gctx, root), NOTHING_WAITS, "items"),
        _Section(
            "Running",
            [_row(r) for r in running(views, snap, gctx, root)],
            "No campaign is active.",
            "campaigns",
            header=[
                _row(["Campaign", "Steps done", "Now", "Last ledger event", "Model jobs", "Ends"]),
                _row(["---"] * 6),
            ],
        ),
        _Section(
            "Handled without you",
            lines[:HANDLED_LINES],
            "Nothing yet: no automatic retry, repair or unblocked step.",
            "lines",
            left_out=max(len(lines) - HANDLED_LINES, 0),
        ),
        _Section(
            "Recently closed",
            closed[:CLOSED_CAMPAIGNS],
            "None yet.",
            "campaigns",
            left_out=max(len(closed) - CLOSED_CAMPAIGNS, 0),
        ),
        _Section("Loose ends", loose_ends(active, ended, snap, root), "None.", "items"),
    ]
    return fit(sections, limit)


def status_issue(snap: Snapshot) -> Issue | None:
    """The open status issue the agent App filed (the oldest, if there are several)."""
    found = [
        i
        for i in snap.issues
        if i.state == "open" and i.author == snap.app_bot and markers.parse_status(i.body)
    ]
    return min(found, key=lambda i: i.number, default=None)


def _same(a: str, b: str) -> bool:
    return a.replace("\r\n", "\n").strip() == b.replace("\r\n", "\n").strip()


def page_actions(body: str, snap: Snapshot) -> list[dict]:
    """Create the status issue, rewrite its body, or (body unchanged) nothing."""
    issue = status_issue(snap)
    if issue is None:
        return [
            {
                "type": "create_issue",
                "title": STATUS_TITLE,
                "body": body,
                "labels": ["campaign"],
                "then_labels": [],
            }
        ]
    if _same(issue.body, body):
        return []
    return [{"type": "edit_body", "issue": issue.number, "body": body}]
