"""The tick: what each active campaign should do next.

`decide` is a pure function. It reads a `Snapshot` of GitHub and the campaign
files on main, and returns a list of actions (file an issue, swap a label,
merge a pull request, start a workflow, post a ledger comment). The workflow
`campaign-tick.yml` runs it with a read-only token and hands the actions to
a separate job that holds the App token and runs no repository code.

Every decision is re-derived from GitHub on every tick (issue markers, plan
and review comments, run titles, ledger comments), so the tick has no state
to lose and a repeated tick does nothing twice.

Pacing, to stay gentle on the subscription's usage limits:
- at most one task (issue to merged PR) in flight per campaign;
- at most one run (explore or pipeline, until its record is merged) in
  flight across all campaigns, so two record PRs never race on the index;
- at most one new step started per campaign per tick.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.closeout import closeout_issue
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import Issue, PullRequest, Run, Snapshot, latest_plan
from terrain.campaigns.gate import GateContext, closeout_paths, evaluate
from terrain.campaigns.rules import evaluate as apply_rules
from terrain.campaigns.spec import Campaign, Step, is_protected, path_allowed

GATE_WORKFLOW = "campaign-gate.yml"
EXPLORE_WORKFLOW = "explore-run.yml"
PIPELINE_WORKFLOW = "data-pipeline.yml"

PLAN_TIMEOUT = dt.timedelta(hours=2)
BUILD_TIMEOUT = dt.timedelta(hours=12)
RUN_APPEAR_TIMEOUT = dt.timedelta(hours=2)
RECORD_TIMEOUT = dt.timedelta(hours=3)
BLOCK_GRACE = dt.timedelta(hours=24)  # time the owner has to unblock a step before close-out

IN_FLIGHT = {
    "filed",
    "planning",
    "plan_ready",
    "building",
    "in_review",
    "mergeable",
    "awaiting_gate",
    "waiting_run",
    "running",
    "recording",
}
RUN_IN_FLIGHT = {"waiting_run", "running", "recording", "in_review", "mergeable", "awaiting_gate"}


@dataclass
class StepState:
    status: str  # unstarted, skipped, done, blocked, or one of IN_FLIGHT
    detail: str = ""
    verdict: str = ""  # explore: killed, survived, unreadable; task: merged; pipeline: recorded
    verdict_lines: list[str] = field(default_factory=list)
    issue: Issue | None = None
    pr: PullRequest | None = None
    run: Run | None = None

    record: str = ""  # path of the explore-run record, once merged

    def links(self) -> str:
        parts = []
        if self.issue:
            parts.append(f"#{self.issue.number}")
        if self.pr:
            parts.append(f"PR #{self.pr.number}")
        if self.run:
            parts.append(f"run {self.run.id}")
        if self.record:
            parts.append(f"`{self.record}`")
        return ", ".join(parts)


@dataclass
class CampaignView:
    campaign: Campaign
    tracking: Issue | None
    closeout: Issue | None
    states: dict[str, StepState]
    events: dict[str, str]  # ledger event -> time it was posted
    used: dict[str, int]


def _time(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def _older(now: str, then: str, delta: dt.timedelta) -> bool:
    return bool(then) and _time(now) - _time(then) > delta


def _ledger_events(tracking: Issue | None, cid: str, app_bot: str) -> dict[str, str]:
    events: dict[str, str] = {}
    if tracking is None:
        return events
    for c in tracking.comments:
        if c.author != app_bot:
            continue
        found = markers.parse_ledger(c.body)
        if found and found[0] == cid:
            for e in found[1]:
                events.setdefault(e, c.created_at)
    return events


def _plan_problem(
    files: tuple[str, ...] | None, allowed: tuple[str, ...], owners: CodeOwners, allow_owned: bool
) -> str:
    if files is None:
        return "the plan has no machine-readable file list"
    if not files:
        return "the plan lists no files"
    outside = [f for f in files if not path_allowed(f, allowed)]
    if outside:
        return f"the plan lists files outside the step's allowed paths: {outside[:5]}"
    if not allow_owned:
        prot = [f for f in files if is_protected(f) or owners.owned(f)]
        if prot:
            return f"the plan lists protected or owned paths: {prot[:5]}"
    return ""


def _task_state(
    issue: Issue,
    allowed: tuple[str, ...],
    snap: Snapshot,
    gctx: GateContext,
    allow_owned: bool = False,
) -> StepState:
    st = StepState("filed", issue=issue, pr=issue.pr)
    pr = issue.pr
    if pr and pr.merged:
        st.status, st.verdict = "done", "merged"
        return st
    if issue.state == "closed":
        st.status, st.detail = "blocked", "the issue was closed without a merged pull request"
        return st
    if "needs-human" in issue.labels or (pr and "needs-human" in pr.labels):
        st.status, st.detail = "blocked", "an agent stopped and labelled it needs-human"
        return st
    plan = latest_plan(list(issue.comments))
    if plan is None:
        if _older(snap.now, issue.created_at, PLAN_TIMEOUT):
            st.status, st.detail = "blocked", "no plan two hours after filing"
        else:
            st.status = "planning"
        return st
    if plan.title != "Plan":
        st.status, st.detail = "blocked", f"the planner answered '{plan.title}'"
        return st
    problem = _plan_problem(plan.files, allowed, gctx.codeowners, allow_owned)
    if problem:
        st.status, st.detail = "blocked", problem
        return st
    if pr is None:
        if "agent-build" not in issue.labels:
            st.status = "plan_ready"
        elif _older(snap.now, plan.created_at, BUILD_TIMEOUT):
            st.status, st.detail = "blocked", "no pull request twelve hours after the plan"
        else:
            st.status = "building"
        return st
    if pr.state != "open":
        st.status, st.detail = "blocked", f"PR #{pr.number} was closed without merging"
        return st
    return _pr_state(st, pr, gctx)


def _pr_state(st: StepState, pr: PullRequest, gctx: GateContext) -> StepState:
    g = evaluate(pr, gctx)
    if g.state == "failure":
        st.status, st.detail = "blocked", g.description
    elif g.state == "pending":
        st.status, st.detail = "in_review", g.description
    elif pr.gate_status != "success":
        st.status, st.detail = "awaiting_gate", "the gate passes but its status is not posted yet"
    elif pr.mergeable is False:
        st.status, st.detail = "blocked", f"PR #{pr.number} has a merge conflict"
    elif pr.mergeable is None:
        st.status, st.detail = "in_review", "GitHub is still computing whether it can merge"
    else:
        st.status = "mergeable"
    return st


def _run_state(
    c: Campaign, s: Step, snap: Snapshot, gctx: GateContext, events: dict[str, str]
) -> StepState:
    if s.kind == "explore_run":
        title = markers.explore_run_title(s.script, c.id, s.id)
        workflow = EXPLORE_WORKFLOW
    else:
        title = markers.pipeline_run_title(s.stage, s.target, c.id, s.id)
        workflow = PIPELINE_WORKFLOW
    runs = sorted(
        (r for r in snap.runs if r.workflow == workflow and r.title == title),
        key=lambda r: r.created_at,
    )
    dispatched = events.get(f"{s.id}:dispatched", "")
    if not runs:
        if not dispatched:
            return StepState("unstarted")
        if _older(snap.now, dispatched, RUN_APPEAR_TIMEOUT):
            return StepState("blocked", "the run was started but never appeared")
        return StepState("waiting_run")
    run = runs[-1]
    st = StepState("running", run=run)
    if run.status != "completed":
        return st
    if run.conclusion != "success":
        st.status, st.detail = "blocked", f"run {run.id} ended '{run.conclusion}'"
        return st
    pr = snap.record_prs.get(run.id)
    st.pr = pr
    finished = run.updated_at or run.created_at
    if pr is None:
        manifest = f"data/manifests/{s.stage}/{s.target}.json"
        if (
            s.kind == "pipeline_run"
            and manifest in snap.files_on_main
            and _older(snap.now, finished, dt.timedelta(hours=1))
        ):
            st.status, st.verdict, st.detail = (
                "done",
                "recorded",
                "the manifest was already up to date",
            )
        elif _older(snap.now, finished, RECORD_TIMEOUT):
            st.status, st.detail = "blocked", "no record pull request three hours after the run"
        else:
            st.status = "recording"
        return st
    if pr.merged:
        if s.kind == "pipeline_run":
            st.status, st.verdict = "done", "recorded"
            return st
        path = f"research/explore-runs/{s.script[:4]}/{run.id}.json"
        if path not in snap.results:
            st.status = "recording"  # merged after this tick's checkout; next tick reads it
            return st
        st.record = path.removesuffix(".json") + ".md"
        verdict = apply_rules(s.kill_rules, snap.results[path])
        st.verdict, st.verdict_lines = verdict.outcome, verdict.lines()
        if verdict.outcome == "unreadable":
            st.status, st.detail = "blocked", "a kill rule could not be applied to the results"
        else:
            st.status = "done"
        return st
    if pr.state != "open":
        st.status, st.detail = "blocked", f"record PR #{pr.number} was closed without merging"
        return st
    return _pr_state(st, pr, gctx)


def _own_issues(c: Campaign, snap: Snapshot) -> tuple[list[Issue], Issue | None, Issue | None]:
    """The App's issues, oldest first, and the campaign's tracking and close-out issues."""
    mine = sorted((i for i in snap.issues if i.author == snap.app_bot), key=lambda i: i.number)
    tracking = next((i for i in mine if markers.parse_tracking(i.body) == c.id), None)
    closeout = next((i for i in mine if markers.parse_closeout(i.body) == c.id), None)
    return mine, tracking, closeout


def view(c: Campaign, snap: Snapshot, gctx: GateContext) -> CampaignView:
    mine, tracking, closeout = _own_issues(c, snap)
    events = _ledger_events(tracking, c.id, snap.app_bot)
    by_step: dict[str, Issue] = {}
    for i in mine:
        found = markers.parse_step(i.body)
        if found and found[0] == c.id:
            by_step.setdefault(found[1], i)
    states: dict[str, StepState] = {}
    stop_all = False
    for s in c.steps:
        if s.kind == "task":
            issue = by_step.get(s.id)
            st = (
                _task_state(issue, s.allowed_paths, snap, gctx) if issue else StepState("unstarted")
            )
        else:
            st = _run_state(c, s, snap, gctx, events)
        if st.status == "unstarted":
            deps = [states[a] for a in s.after]
            if stop_all:
                st = StepState("skipped", "an earlier kill rule stopped the campaign")
            for a in s.after:
                dep, dep_step = states[a], c.step(a)
                if dep.status == "skipped":
                    st = StepState("skipped", f"step {a} was skipped")
                elif (
                    dep.status == "done"
                    and dep.verdict == "killed"
                    and dep_step.on_kill != "continue"
                ):
                    st = StepState("skipped", f"step {a} was killed")
            if st.status == "unstarted" and not all(d.status == "done" for d in deps):
                st.status = "waiting"
        if st.status == "done" and st.verdict == "killed" and s.on_kill == "stop":
            stop_all = True
        states[s.id] = st
    if stop_all:
        for s in c.steps:
            if states[s.id].status in ("unstarted", "waiting"):
                states[s.id] = StepState("skipped", "an earlier kill rule stopped the campaign")
    used = {
        "max_tasks": sum(1 for s in c.steps if s.kind == "task" and states[s.id].issue),
        "max_explore_runs": sum(
            1
            for s in c.steps
            if s.kind == "explore_run" and (states[s.id].run or f"{s.id}:dispatched" in events)
        ),
        "max_pipeline_runs": sum(
            1
            for s in c.steps
            if s.kind == "pipeline_run" and (states[s.id].run or f"{s.id}:dispatched" in events)
        ),
        "max_model_jobs": 0,
    }
    jobs = 0
    for issue in [*by_step.values(), *([closeout] if closeout else [])]:
        jobs += sum(1 for cm in issue.comments if cm.body.startswith("## Agent plan: "))
        if issue.pr:
            jobs += 2 * len(issue.pr.reviews)  # each review follows one build
    used["max_model_jobs"] = jobs
    return CampaignView(c, tracking, closeout, states, events, used)


def _tracking_body(c: Campaign) -> str:
    return f"""Tracking issue for campaign {c.id}, **{c.title}**
(`{c.folder}/campaign.md`, idea {c.idea}). Written by the `campaign-tick`
workflow; each comment below is a ledger entry.

Controls (labels on this issue):
- `campaign-pause`: the tick does nothing for this campaign until it is removed.
- `campaign-stop`, or closing this issue: no new steps start, nothing more is
  merged, and the close-out task is filed.
- The repository variable `CAMPAIGNS_ENABLED` set to anything but `true`
  stops every campaign.

@{c.owner} is mentioned only when something is blocked and when the report
is ready.

{markers.tracking_marker(c.id)}
"""


def _reason(v: CampaignView, stopped: bool, today: dt.date) -> str:
    c, states = v.campaign, v.states
    if stopped:
        return "the owner stopped it"
    if any(s.verdict == "killed" and c.step(k).on_kill == "stop" for k, s in states.items()):
        return "a kill rule stopped it"
    if today > dt.date.fromisoformat(c.end_by):
        return f"its end date ({c.end_by}) passed"
    if any(s.status == "blocked" for s in states.values()):
        return "every step that could go on is blocked"
    if any(s.status in ("unstarted", "waiting") for s in states.values()):
        return "its budget ran out"
    return "every step finished"


def decide(
    campaigns: list[Campaign],
    snap: Snapshot,
    gctx: GateContext,
    root: Path,
    ended: Sequence[Campaign] = (),
) -> list[dict]:
    """The actions for this tick, ledger comments first within each campaign.

    `campaigns` are the active ones. `ended` (done or stopped) only get their
    tracking issue closed once their close-out PR is merged (`close_tracking`).
    """
    if not snap.enabled:
        return []
    actions: list[dict] = []
    views = [view(c, snap, gctx) for c in campaigns]
    runs_in_flight = sum(
        1
        for v in views
        for s in v.campaign.steps
        if s.kind != "task" and v.states[s.id].status in RUN_IN_FLIGHT
    )
    today = _time(snap.now).date()
    for v in views:
        c = v.campaign
        if v.tracking is None:
            actions.append(
                {
                    "type": "create_issue",
                    "title": f"Campaign {c.id}: {c.title}",
                    "body": _tracking_body(c),
                    "labels": ["campaign"],
                    "then_labels": [],
                }
            )
            continue
        if "campaign-pause" in v.tracking.labels:
            continue
        stopped = v.tracking.state == "closed" or "campaign-stop" in v.tracking.labels
        new: list[tuple[str, str]] = []  # (event, line)
        doing: list[dict] = []

        def event(name: str, line: str, new=new, v=v) -> None:
            if name not in v.events and name not in {e for e, _ in new}:
                new.append((name, line))

        event("started", f"Campaign {c.id} started.")
        if stopped:
            event("stopped", "Stopped by the owner: no new steps, no merges.")
        for s in c.steps:
            st = v.states[s.id]
            if st.issue:
                event(f"{s.id}:filed", f"{s.id}: filed as #{st.issue.number}.")
            if st.status == "done" and s.kind == "task":
                event(f"{s.id}:merged", f"{s.id}: PR #{st.pr.number} merged.")
            if st.status == "done" and s.kind == "explore_run":
                lines = "\n".join(f"  - {ln}" for ln in st.verdict_lines)
                event(
                    f"{s.id}:verdict",
                    f"{s.id}: run {st.run.id} recorded (PR #{st.pr.number}). Verdict: "
                    f"**{st.verdict}**.\n{lines}",
                )
            if st.status == "done" and s.kind == "pipeline_run":
                event(f"{s.id}:recorded", f"{s.id}: {s.stage} {s.target} recorded ({st.links()}).")
            if st.status == "skipped":
                event(f"{s.id}:skipped", f"{s.id}: skipped ({st.detail}).")
            if st.status == "blocked":
                extra = (
                    ("\n" + "\n".join(f"  - {ln}" for ln in st.verdict_lines))
                    if st.verdict_lines
                    else ""
                )
                event(
                    f"{s.id}:blocked",
                    f"{s.id}: **blocked**: {st.detail} ({st.links() or 'no links'}). "
                    f"@{c.owner}{extra}",
                )
            if stopped:
                continue
            if st.status == "plan_ready":
                doing.append(
                    {
                        "type": "swap_labels",
                        "issue": st.issue.number,
                        "remove": "agent-plan",
                        "add": "agent-build",
                    }
                )
            elif st.status == "mergeable":
                doing.append({"type": "merge", "pr": st.pr.number, "sha": st.pr.head_sha})
            elif st.status == "awaiting_gate":
                doing.append(
                    {
                        "type": "dispatch",
                        "workflow": GATE_WORKFLOW,
                        "inputs": {"pr": str(st.pr.number)},
                    }
                )

        can_start = not stopped and today <= dt.date.fromisoformat(c.end_by)
        tasks_in_flight = sum(
            1 for s in c.steps if s.kind == "task" and v.states[s.id].status in IN_FLIGHT
        )
        started = False
        for s in c.steps:
            st = v.states[s.id]
            if started or not can_start or st.status != "unstarted":
                continue
            if s.kind == "task":
                if (
                    tasks_in_flight
                    or v.used["max_tasks"] >= c.budget["max_tasks"]
                    or v.used["max_model_jobs"] >= c.budget["max_model_jobs"]
                ):
                    continue
                title, body = markers.draft_body((root / s.draft).read_text(encoding="utf-8"))
                labels = ["campaign", "explore"] if s.type == "explore" else ["campaign"]
                doing.append(
                    {
                        "type": "create_issue",
                        "title": title,
                        "body": f"{body}\n\n{markers.step_marker(c.id, s.id)}\n",
                        "labels": labels,
                        "then_labels": ["agent-plan"],
                    }
                )
                started = True
            else:
                key = "max_explore_runs" if s.kind == "explore_run" else "max_pipeline_runs"
                if runs_in_flight or v.used[key] >= c.budget[key]:
                    continue
                if s.kind == "explore_run":
                    doing.append(
                        {
                            "type": "dispatch",
                            "workflow": EXPLORE_WORKFLOW,
                            "inputs": {"script": s.script, "campaign": f"{c.id}/{s.id}"},
                        }
                    )
                else:
                    doing.append(
                        {
                            "type": "dispatch",
                            "workflow": PIPELINE_WORKFLOW,
                            "inputs": {
                                "stage": s.stage,
                                "target": s.target,
                                "campaign": f"{c.id}/{s.id}",
                            },
                        }
                    )
                event(
                    f"{s.id}:dispatched",
                    f"{s.id}: started `{s.script or s.stage + ' ' + s.target}`.",
                )
                runs_in_flight += 1
                started = True

        in_flight = any(st.status in IN_FLIGHT for st in v.states.values())
        startable = False
        if can_start and not started:
            for s in c.steps:
                st = v.states[s.id]
                if st.status != "unstarted":
                    continue
                if s.kind == "task":
                    startable |= (
                        v.used["max_tasks"] < c.budget["max_tasks"]
                        and v.used["max_model_jobs"] < c.budget["max_model_jobs"]
                    )
                else:
                    key = "max_explore_runs" if s.kind == "explore_run" else "max_pipeline_runs"
                    startable |= v.used[key] < c.budget[key]
        finished = (not in_flight and not started and not startable) or (stopped and not in_flight)
        if stopped and in_flight:
            finished = True  # nothing in flight will merge now; close out what there is
        if finished and not stopped:
            # a block posted less than a day ago (or not yet posted) gives the
            # owner time to unblock it before the campaign closes
            for sid, st in v.states.items():
                when = v.events.get(f"{sid}:blocked", "")
                if st.status == "blocked" and (not when or not _older(snap.now, when, BLOCK_GRACE)):
                    finished = False
        if finished:
            reason = _reason(v, stopped, today)
            if v.closeout is None:
                rows = [
                    {
                        "step": s.id,
                        "kind": s.kind,
                        "status": v.states[s.id].status,
                        "verdict": v.states[s.id].verdict or v.states[s.id].detail,
                        "links": v.states[s.id].links(),
                    }
                    for s in c.steps
                ]
                final = "stopped" if stopped else "done"
                applied = [
                    f"{s.id}: {line}" for s in c.steps for line in v.states[s.id].verdict_lines
                ]
                title, body = closeout_issue(
                    c, root, rows, v.used, reason, v.tracking.number, final, applied
                )
                doing.append(
                    {
                        "type": "create_issue",
                        "title": title,
                        "body": body,
                        "labels": ["campaign"],
                        "then_labels": ["agent-plan"],
                    }
                )
                event("finished", f"Campaign finished: {reason}. Filing the close-out task.")
            else:
                cst = _task_state(v.closeout, closeout_paths(c, root), snap, gctx, allow_owned=True)
                event("closeout:filed", f"Close-out filed as #{v.closeout.number}.")
                if cst.status == "plan_ready":
                    doing.append(
                        {
                            "type": "swap_labels",
                            "issue": v.closeout.number,
                            "remove": "agent-plan",
                            "add": "agent-build",
                        }
                    )
                elif cst.status == "awaiting_gate":
                    doing.append(
                        {
                            "type": "dispatch",
                            "workflow": GATE_WORKFLOW,
                            "inputs": {"pr": str(cst.pr.number)},
                        }
                    )
                elif cst.status == "mergeable":
                    event(
                        "closeout:ready",
                        f"@{c.owner} the report is ready for you: PR #{cst.pr.number}. "
                        "Read it, decide, and merge it yourself.",
                    )
                elif cst.status == "blocked":
                    event(
                        "closeout:blocked",
                        f"@{c.owner} the close-out task is blocked: {cst.detail} ({cst.links()}).",
                    )
                elif cst.status == "done":
                    event("closeout:merged", "Close-out merged. The campaign is done.")
                    if v.tracking.state == "open":
                        event("closed", "Closing this tracking issue.")
                        doing.append({"type": "close_issue", "issue": v.tracking.number})
        if new:
            body = "\n".join(f"- {line}" for _, line in new)
            body += "\n\n" + markers.ledger_marker(c.id, [e for e, _ in new]) + "\n"
            actions.append({"type": "comment", "issue": v.tracking.number, "body": body})
        actions.extend(doing)
    for c in ended:
        actions.extend(close_tracking(c, snap))
    return actions


def close_tracking(c: Campaign, snap: Snapshot) -> list[dict]:
    """A done or stopped campaign: once its close-out PR is merged, close the tracking issue.

    The close-out PR sets `status: done` (or `stopped`), so from then on the campaign is
    no longer active and `decide` would never look at it again. This posts one last
    ledger comment and closes the issue. A repeated tick posts nothing twice, and does
    nothing once the issue is closed.
    """
    _, tracking, closeout = _own_issues(c, snap)
    if tracking is None or tracking.state != "open" or "campaign-pause" in tracking.labels:
        return []
    if closeout is None or closeout.pr is None or not closeout.pr.merged:
        return []
    actions: list[dict] = []
    if "closed" not in _ledger_events(tracking, c.id, snap.app_bot):
        line = (
            f"Close-out PR #{closeout.pr.number} merged. The campaign is {c.status}; "
            "closing this tracking issue."
        )
        body = f"- {line}\n\n{markers.ledger_marker(c.id, ['closed'])}\n"
        actions.append({"type": "comment", "issue": tracking.number, "body": body})
    actions.append({"type": "close_issue", "issue": tracking.number})
    return actions
