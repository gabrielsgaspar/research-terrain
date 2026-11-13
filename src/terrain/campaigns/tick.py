"""The tick: what each active campaign should do next.

`decide` is a pure function. It reads a `Snapshot` of GitHub and the campaign
files on main, and returns a list of actions (file an issue, swap a label,
merge a pull request, start a workflow, post a ledger comment). The workflow
`campaign-tick.yml` runs it with a read-only token and hands the actions to
a separate job that holds the App token and runs no repository code.

Every decision is re-derived from GitHub on every tick (issue markers, plan
and review comments, run titles, ledger comments), so the tick has no state
to lose and a repeated tick does nothing twice.

Pacing, to stay gentle on the subscription's usage limits (a run is in
flight until its record is merged):
- at most one task (issue to merged PR) in flight per campaign;
- at most MAX_PIPELINE_RUNS_IN_FLIGHT data-pipeline runs in flight across all
  campaigns. Their records are one manifest file per target, and the
  workflow has one concurrency group per target, so independent ones do not
  conflict; research/INDEX.md, which they once raced on, is not in git;
- at most one explore run in flight across all campaigns, and none while a
  data-pipeline run of the same campaign is in flight;
- at most one new task or explore run started per campaign per tick; data
  pipeline runs start as far as the limits above and the budget allow.
Retries and the run after a repair follow the same limits (`RunSlots`).

A run step whose run ended 'failure' or 'timed_out' is started again by the
tick, at most MAX_AUTO_RETRIES times per step, before the owner is asked.
A data-pipeline run that stopped only because its exports are still running
(its log says `still exporting: N of M done`, `terrain.earthengine`) is no
failure: it is started again without using a retry, while N grows from one
such run to the next, at most MAX_CONTINUES times per step.
In a campaign with `self_repair: true`, a pipeline_run step that still fails
then gets one repair task (`terrain.campaigns.repair`, decision 0014); once
it merges, the step runs once more, and only then is the owner asked.

Forks (decision 0015), only in a campaign with a `forks:` envelope: when an
explore run of the plan gets a verdict the envelope lists, the tick starts one
ideation job (`campaign-ideate.yml`) for that fork point and merges the fork
plan pull request the gate passes; fork steps then start only when no step of
the plan can (F13), within the envelope's budget (F12); every declared fork at
a point runs (F3); and once every fork at a killed point has a verdict, the
first surviving fork in the declared order adopts the steps that kill skipped
(F9), fixed by one ledger event (`adopt:fK:sNN:...`).

A circuit breaker per campaign: while BREAKER_BLOCKS or more of its blocks,
posted within BREAKER_WINDOW and not unblocked since, are in the ledger, the
tick starts nothing new in it (no step, no retry, no repair, no run after a
repair). Work in flight goes on and merges through the gate go on. The
breaker holding and lifting each get one ledger line (`breaker:held:<k>`,
`breaker:lifted:<k>`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from terrain.campaigns import forks, markers, repair
from terrain.campaigns.closeout import closeout_issue, table
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import (
    PLAN_PREFIX,
    Issue,
    PullRequest,
    Run,
    Snapshot,
    latest_plan,
)
from terrain.campaigns.gate import GateContext, closeout_paths, evaluate
from terrain.campaigns.rules import evaluate as apply_rules
from terrain.campaigns.spec import Campaign, Step, is_protected, path_allowed

GATE_WORKFLOW = "campaign-gate.yml"
EXPLORE_WORKFLOW = "explore-run.yml"
PIPELINE_WORKFLOW = "data-pipeline.yml"
IDEATE_WORKFLOW = "campaign-ideate.yml"
# Each run workflow's name as GitHub shows it in the Actions tab (its `name:`).
WORKFLOW_NAMES = {EXPLORE_WORKFLOW: "Explore run", PIPELINE_WORKFLOW: "Data pipeline"}

PLAN_TIMEOUT = dt.timedelta(hours=2)
BUILD_TIMEOUT = dt.timedelta(hours=12)
RUN_APPEAR_TIMEOUT = dt.timedelta(hours=2)
RECORD_TIMEOUT = dt.timedelta(hours=3)
BLOCK_GRACE = dt.timedelta(hours=24)  # time the owner has to unblock a step before close-out
# Forks (decision 0015): an ideation job with no result after IDEATION_TIMEOUT, or a
# fork plan pull request not merged FORK_PLAN_TIMEOUT after the ideation started,
# means "no forks at this point"; ideation never blocks a campaign.
IDEATION_TIMEOUT = dt.timedelta(hours=2)
FORK_PLAN_TIMEOUT = dt.timedelta(hours=6)
IDEATE_EVENT = re.compile(r"^s\d{1,2}:ideate$")

# A failed run step is started again by itself this many times, counted from the
# ledger's `<step>:retry:<k>` events (not from runs, so runs started by hand do not
# use them up). Only these conclusions are retried: 'cancelled' means someone stopped it.
MAX_AUTO_RETRIES = 2
RETRY_CONCLUSIONS = {"failure", "timed_out"}
# A run that ran out of time with exports still running prints this line; the tick
# starts it again (`<step>:continue:<k>:<N>` in the ledger) without using a retry,
# only while N grows, at most MAX_CONTINUES times per step.
STILL_EXPORTING = re.compile(r"still exporting: (\d+) of (\d+) done")
MAX_CONTINUES = 10

# The circuit breaker (see the module docstring). Only block events of the newer
# kind, `<step>:blocked:<id>`, count; the close-out's blocks do not.
BREAKER_BLOCKS = 3
BREAKER_WINDOW = dt.timedelta(hours=24)
_STEP_BLOCK = re.compile(r"^(s\d{1,2}):blocked:[0-9a-f]{8}(?:-\d+)?$")

# Runs in flight across all campaigns (see the module docstring).
MAX_PIPELINE_RUNS_IN_FLIGHT = 3
MAX_EXPLORE_RUNS_IN_FLIGHT = 1

# What the owner does about each kind of block, named by where to click on GitHub.
NEEDS_YOU = {
    "needs_human": (
        "open the issue or pull request, read the agent's last comment, fix what it asks, "
        "then remove the `needs-human` label in the right-hand column"
    ),
    "no_plan": (
        "open the Actions tab, look for a failed Agent plan run for this issue, "
        "then remove and re-add the `agent-plan` label on the issue"
    ),
    "plan_paths": (
        "open the issue and read the plan's Files to change; for a new plan, "
        "remove and re-add the `agent-plan` label on the issue"
    ),
    "run_failed": (
        "open the run from the Actions tab and read the failed step's log. "
        "If the cause was outside the code (a server error, a timeout, an export "
        "still running), choose Re-run failed jobs. If a fix was merged since the run "
        "started, a re-run would use the old code: open the Actions tab, choose the "
        "workflow, choose Run workflow on main, and enter the values below (campaign "
        "too, although the form says to leave it empty)"
    ),
    "record_missing": (
        "open the run from the Actions tab and read its record job; "
        "choose Re-run failed jobs if it failed"
    ),
    "conflict": (
        "open the pull request, choose Resolve conflicts (or Update branch) "
        "at the bottom of the Conversation tab"
    ),
    "unreadable": (
        "open the record and compare its results with the step's kill rules in campaign.md; "
        "to end the campaign, add `campaign-stop` to this issue"
    ),
    "pr_closed": (
        "open the pull request, read why it was closed, and choose Reopen pull request "
        "if that was a mistake"
    ),
}
NEEDS_YOU_DEFAULT = "open the links and read the last comment"

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
    "retry_waiting",  # a failed run to start again once the run limits allow
    "resume_waiting",  # a run still exporting, to start again once the run limits allow
    "repair_waiting",  # a repair to file once no other task of the campaign is in flight
    "repair_filing",  # a repair filed, its issue not seen yet
    "repair_merged",  # a merged repair: the run starts again once the run limits allow
}
RUN_IN_FLIGHT = {"waiting_run", "running", "recording", "in_review", "mergeable", "awaiting_gate"}


@dataclass
class StepState:
    status: str  # unstarted, skipped, done, blocked, or one of IN_FLIGHT
    detail: str = ""
    cause: str = ""  # for a block: its kind, a key of NEEDS_YOU ("" for the default)
    verdict: str = ""  # explore: killed, survived, unreadable; task: merged; pipeline: recorded
    verdict_lines: list[str] = field(default_factory=list)
    issue: Issue | None = None
    pr: PullRequest | None = None
    run: Run | None = None

    record: str = ""  # path of the explore-run record, once merged
    run_again: str = ""  # for a failed run: the workflow and inputs to start it again
    retry: int = 0  # for a failed run the tick may start again: the number of that retry
    # for a run still exporting the tick starts again: (k, N done, M in all)
    resume: tuple[int, int, int] | None = None
    repair: Issue | None = None  # for a pipeline_run step: its repair issue, once seen
    repairing: bool = False  # the repair task (not a run) is what is in flight

    def links(self) -> str:
        parts = []
        if self.issue:
            parts.append(f"#{self.issue.number}")
        if self.repair and self.repair is not self.issue:
            parts.append(f"repair #{self.repair.number}")
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
    used: dict[str, int]  # the plan's budget used (adopted steps included, forks not)
    # the blocks that hold the circuit breaker; empty while it does not hold
    breaker: tuple[str, ...] = ()
    # forks (decision 0015): the envelope's budget used, and the adoption, if any:
    # (fork id, fork point, the adopted steps)
    fork_used: dict[str, int] = field(default_factory=dict)
    adoption: tuple[str, str, tuple[str, ...]] | None = None


@dataclass
class RunSlots:
    """Runs in flight across all campaigns, and whether one more may start."""

    pipeline: int = 0
    explore: int = 0
    pipeline_of: dict[str, int] = field(default_factory=dict)  # campaign id -> pipeline runs

    @classmethod
    def count(cls, views: Sequence[CampaignView]) -> RunSlots:
        slots = cls()
        for v in views:
            for s in v.campaign.steps:
                st = v.states[s.id]
                if s.kind != "task" and st.status in RUN_IN_FLIGHT and not st.repairing:
                    slots.take(v.campaign, s)
        return slots

    def wait(self, c: Campaign, s: Step) -> str:
        """What run step `s` of campaign `c` waits for; empty if it may start now."""
        if s.kind == "pipeline_run":
            if self.pipeline >= MAX_PIPELINE_RUNS_IN_FLIGHT:
                n = MAX_PIPELINE_RUNS_IN_FLIGHT
                return f"once fewer than {n} data-pipeline runs are in flight"
            return ""
        if self.explore >= MAX_EXPLORE_RUNS_IN_FLIGHT:
            return "once no other explore run is in flight"
        if self.pipeline_of.get(c.id, 0):
            return "once this campaign's data-pipeline runs are recorded"
        return ""

    def take(self, c: Campaign, s: Step) -> None:
        """Count run step `s` of campaign `c` as in flight."""
        if s.kind == "pipeline_run":
            self.pipeline += 1
            self.pipeline_of[c.id] = self.pipeline_of.get(c.id, 0) + 1
        else:
            self.explore += 1


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
        st.cause = "needs_human"
        return st
    plan = latest_plan(list(issue.comments))
    if plan is None:
        if _older(snap.now, issue.created_at, PLAN_TIMEOUT):
            st.status, st.detail, st.cause = "blocked", "no plan two hours after filing", "no_plan"
        else:
            st.status = "planning"
        return st
    if plan.title != "Plan":
        st.status, st.detail = "blocked", f"the planner answered '{plan.title}'"
        return st
    problem = _plan_problem(plan.files, allowed, gctx.codeowners, allow_owned)
    if problem:
        st.status, st.detail, st.cause = "blocked", problem, "plan_paths"
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
        st.cause = "pr_closed"
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
        st.cause = "conflict"
    elif pr.mergeable is None:
        st.status, st.detail = "in_review", "GitHub is still computing whether it can merge"
    else:
        st.status = "mergeable"
    return st


def run_dispatch(c: Campaign, s: Step) -> dict:
    """The dispatch action that starts run step `s`: its workflow and inputs."""
    if s.kind == "explore_run":
        workflow = EXPLORE_WORKFLOW
        inputs = {"script": s.script, "campaign": f"{c.id}/{s.id}"}
    else:
        workflow = PIPELINE_WORKFLOW
        inputs = {"stage": s.stage, "target": s.target, "campaign": f"{c.id}/{s.id}"}
    return {"type": "dispatch", "workflow": workflow, "inputs": inputs}


def _run_again(c: Campaign, s: Step) -> str:
    """What to enter under Run workflow to start run step `s` by hand, as the tick does."""
    action = run_dispatch(c, s)
    values = ", ".join(f"{k} `{v}`" for k, v in action["inputs"].items())
    return f"Run workflow values: workflow **{WORKFLOW_NAMES[action['workflow']]}**, {values}"


def _step_runs(c: Campaign, s: Step, snap: Snapshot) -> list[Run]:
    """The runs of run step `s`, oldest first: those with its workflow and its title."""
    if s.kind == "explore_run":
        title = markers.explore_run_title(s.script, c.id, s.id)
        workflow = EXPLORE_WORKFLOW
    else:
        title = markers.pipeline_run_title(s.stage, s.target, c.id, s.id)
        workflow = PIPELINE_WORKFLOW
    return sorted(
        (r for r in snap.runs if r.workflow == workflow and r.title == title),
        key=lambda r: r.created_at,
    )


def _retries(sid: str, events: dict[str, str]) -> int:
    """How many times the tick started step `sid` again by itself, from the ledger."""
    return sum(1 for k in range(1, MAX_AUTO_RETRIES + 1) if f"{sid}:retry:{k}" in events)


def _continues(sid: str, events: dict[str, str]) -> list[tuple[int, int]]:
    """(k, N done) of each time the tick started step `sid` again while it was exporting."""
    pattern = re.compile(rf"{re.escape(sid)}:continue:(\d+):(\d+)")
    found = [m for m in map(pattern.fullmatch, events) if m]
    return sorted((int(m.group(1)), int(m.group(2))) for m in found)


def _continue_event(sid: str, events: dict[str, str]) -> str:
    """The ledger event of the last time step `sid` was started again while exporting."""
    before = _continues(sid, events)
    return f"{sid}:continue:{before[-1][0]}:{before[-1][1]}" if before else ""


def _still_exporting(
    s: Step, run: Run, snap: Snapshot, events: dict[str, str]
) -> tuple[tuple[int, int, int] | None, str]:
    """(k, N, M) when failed run `run` was still exporting and may be started again.

    Otherwise None, with why not when its log does say it was still exporting.
    """
    if s.kind != "pipeline_run" or run.conclusion != "failure":
        return None, ""
    found = STILL_EXPORTING.findall(snap.run_logs.get(run.id, ""))
    if not found:
        return None, ""
    done, total = (int(x) for x in found[-1])
    before = _continues(s.id, events)
    if len(before) >= MAX_CONTINUES:
        return None, f"still exporting ({done} of {total} done) after {MAX_CONTINUES} more runs"
    if before and done <= before[-1][1]:
        return None, (
            f"still exporting, but {done} of {total} done is no more than the "
            f"{before[-1][1]} of the run before"
        )
    return (len(before) + 1, done, total), ""


def _repair_event(sid: str, stage: str = "") -> str:
    """The ledger event of a stage of step `sid`'s repair: "" (filing), filed, merged, run."""
    base = f"{sid}:repair:{repair.MAX_PER_STEP}"
    return f"{base}:{stage}" if stage else base


def _run_state(
    c: Campaign, s: Step, snap: Snapshot, gctx: GateContext, events: dict[str, str]
) -> StepState:
    runs = _step_runs(c, s, snap)
    dispatched = events.get(f"{s.id}:dispatched", "")
    if not runs:
        if not dispatched:
            return StepState("unstarted")
        if _older(snap.now, dispatched, RUN_APPEAR_TIMEOUT):
            return StepState("blocked", "the run was started but never appeared")
        return StepState("waiting_run")
    run = runs[-1]
    retries = _retries(s.id, events)
    retried = events.get(f"{s.id}:retry:{retries}", "") if retries else ""
    repaired = events.get(_repair_event(s.id, "run"), "")
    resumed = events.get(_continue_event(s.id, events), "")
    restarted = max((t for t in (retried, repaired, resumed) if t), key=_time, default="")
    if restarted and _time(restarted) > _time(run.created_at):
        # the newest run is older than the newest restart: the fresh run has not appeared yet
        if _older(snap.now, restarted, RUN_APPEAR_TIMEOUT):
            return StepState("blocked", "the run was started again but never appeared", run=run)
        return StepState("waiting_run", run=run)
    st = StepState("running", run=run)
    if run.status != "completed":
        return st
    if run.conclusion != "success":
        st.status, st.detail = "blocked", f"run {run.id} ended '{run.conclusion}'"
        st.cause = "run_failed"
        st.run_again = _run_again(c, s)
        done = [f"Retried {retries} time{'s' if retries > 1 else ''}"] if retries else []
        done += ["repaired once"] if repaired else []
        if done:
            st.detail += ". " + ", ".join(done)[0].upper() + ", ".join(done)[1:] + "."
        st.resume, why_not = _still_exporting(s, run, snap, events)
        if st.resume:
            _, n, m = st.resume
            st.detail = f"run {run.id} is still exporting ({n} of {m} done)"
            return st
        if why_not:
            st.detail = f"{st.detail.rstrip('.')}. It was {why_not}."
        if run.conclusion in RETRY_CONCLUSIONS and retries < MAX_AUTO_RETRIES and not repaired:
            st.retry = retries + 1
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
            st.cause = "record_missing"
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
            st.cause = "unreadable"
        else:
            st.status = "done"
        return st
    if pr.state != "open":
        st.status, st.detail = "blocked", f"record PR #{pr.number} was closed without merging"
        st.cause = "pr_closed"
        return st
    return _pr_state(st, pr, gctx)


def _repair_state(
    c: Campaign,
    s: Step,
    st: StepState,
    issue: Issue | None,
    snap: Snapshot,
    gctx: GateContext,
    events: dict[str, str],
) -> StepState:
    """Step `s`'s state once a repair was filed for it (decision 0014).

    Until the repair merges, the step is its repair task: in flight, or
    blocked with the task's cause. Once merged, it waits for the tick to start
    the run again; once that run is started, the run is read as usual.
    """
    filing = events.get(_repair_event(s.id), "")
    if issue is None and not filing:
        return st
    since = issue.created_at if issue else filing
    newer = st.run is not None and _time(st.run.created_at) > _time(since)
    if _repair_event(s.id, "run") in events or st.status == "done" or newer:
        # the run after the repair, or one started by hand since it was filed: read as usual
        st.repair = issue
        return st
    if issue is None:
        if _older(snap.now, filing, RUN_APPEAR_TIMEOUT):
            return StepState("blocked", "the repair task was filed but never appeared", run=st.run)
        return StepState(
            "repair_filing", "the repair task was just filed", run=st.run, repairing=True
        )
    rst = _task_state(issue, repair.repair_paths(c, s, gctx.codeowners), snap, gctx)
    out = StepState(rst.status, issue=issue, pr=rst.pr, run=st.run, repair=issue)
    if rst.status == "done":
        out.status = "repair_merged"
        out.detail = f"repair PR #{rst.pr.number} merged; the run starts again"
    elif rst.status == "blocked":
        out.detail, out.cause = f"the repair task: {rst.detail}", rst.cause
    else:
        out.detail, out.repairing = rst.detail, True
    return out


def _repairs(c: Campaign, v: CampaignView) -> int:
    """How many repairs campaign `c` has filed, from the ledger and its issues."""
    return sum(
        1
        for s in c.steps
        if s.kind == "pipeline_run" and (v.states[s.id].repair or _repair_event(s.id) in v.events)
    )


def _no_repair(c: Campaign, s: Step, st: StepState, v: CampaignView, gctx: GateContext) -> str:
    """Why failed run step `s` gets no repair now ("" if it may get one).

    "-" means it is not a repair case at all (the campaign does not allow
    repairs, the step is no pipeline_run, the run did not fail or still has
    retries, or this step was repaired already).
    """
    if not (
        c.self_repair
        and s.kind == "pipeline_run"
        and st.status == "blocked"
        and st.cause == "run_failed"
        and st.run is not None
        and st.run.conclusion in RETRY_CONCLUSIONS
        and not st.retry
        and not st.resume
        and _retries(s.id, v.events) >= MAX_AUTO_RETRIES
        and st.repair is None
        and _repair_event(s.id) not in v.events
    ):
        return "-"
    if _repairs(c, v) >= repair.MAX_PER_CAMPAIGN:
        return f"the campaign's {repair.MAX_PER_CAMPAIGN} repairs are used"
    if v.used["max_model_jobs"] >= c.budget["max_model_jobs"]:
        return "the model-job budget is used up"
    if not repair.repair_paths(c, s, gctx.codeowners):
        return "no task step it comes after lists a file a repair may change"
    return ""


def _own_issues(c: Campaign, snap: Snapshot) -> tuple[list[Issue], Issue | None, Issue | None]:
    """The App's issues, oldest first, and the campaign's tracking and close-out issues."""
    mine = sorted((i for i in snap.issues if i.author == snap.app_bot), key=lambda i: i.number)
    tracking = next((i for i in mine if markers.parse_tracking(i.body) == c.id), None)
    closeout = next((i for i in mine if markers.parse_closeout(i.body) == c.id), None)
    return mine, tracking, closeout


def _plans(issue: Issue) -> int:
    """How many plans were posted on the issue (each is one model job)."""
    return sum(1 for cm in issue.comments if cm.body.startswith(PLAN_PREFIX))


def _model_jobs(issue: Issue) -> int:
    """Model jobs an issue used: one per plan, two per agent review (each follows one build)."""
    return _plans(issue) + (2 * len(issue.pr.reviews) if issue.pr else 0)


ADOPT_EVENT = re.compile(r"^adopt:(f[1-9]):(s\d{1,2}):((?:s\d{1,2},?)+)$")


def adoption_event(fid: str, point: str, steps: Sequence[str]) -> str:
    """The ledger event that fixes an adoption: `adopt:f1:s15:s16,s17,...` (F9)."""
    return f"adopt:{fid}:{point}:{','.join(steps)}"


def _adoption_of(events: dict[str, str]) -> tuple[str, str, tuple[str, ...]] | None:
    """The campaign's adoption from its ledger (at most one per campaign)."""
    found = sorted((events[e], e) for e in events if ADOPT_EVENT.match(e))
    if not found:
        return None
    m = ADOPT_EVENT.match(found[0][1])
    return m.group(1), m.group(2), tuple(m.group(3).split(","))


def view(
    c: Campaign,
    snap: Snapshot,
    gctx: GateContext,
    adoption: tuple[str, str, tuple[str, ...]] | None = None,
) -> CampaignView:
    """Every step's state. `adoption` (else the ledger's) un-skips the adopted steps."""
    mine, tracking, closeout = _own_issues(c, snap)
    events = _ledger_events(tracking, c.id, snap.app_bot)
    adoption = adoption or _adoption_of(events)
    adopted = set(adoption[2]) if adoption else set()
    point = adoption[1] if adoption else ""
    by_step: dict[str, Issue] = {}
    by_repair: dict[str, Issue] = {}
    for i in mine:
        found = markers.parse_step(i.body)
        if found and found[0] == c.id:
            by_step.setdefault(found[1], i)
        fixing = markers.parse_repair(i.body)
        if fixing and fixing[0] == c.id and fixing[2] == repair.MAX_PER_STEP:
            by_repair.setdefault(fixing[1], i)
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
            if s.kind == "pipeline_run":
                st = _repair_state(c, s, st, by_repair.get(s.id), snap, gctx, events)
        if st.status == "unstarted":
            deps = [states[a] for a in s.after]
            # a stop holds the plan's steps, never a fork's (forks at that point still
            # run) and never a step a fork adopted (F9)
            if stop_all and not s.fork and s.id not in adopted:
                st = StepState("skipped", "an earlier kill rule stopped the campaign")
            parent = c.fork(s.fork).parent_step if s.fork and c.fork(s.fork) else ""
            for a in s.after:
                dep, dep_step = states[a], c.step(a)
                if a == parent or (s.id in adopted and a == point):
                    continue  # a fork point: its verdict, whatever it is, is what forks follow
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
        if (
            st.status == "done"
            and st.verdict == "killed"
            and s.on_kill == "stop"
            and not s.fork
            and s.id != point
        ):
            stop_all = True
        states[s.id] = st
    if stop_all:
        for s in c.steps:
            if states[s.id].status in ("unstarted", "waiting") and not (s.fork or s.id in adopted):
                states[s.id] = StepState("skipped", "an earlier kill rule stopped the campaign")

    def started(s: Step) -> bool:
        return bool(states[s.id].run) or f"{s.id}:dispatched" in events

    def runs_of(kind: str, fork: bool) -> int:
        return sum(1 for s in c.steps if s.kind == kind and bool(s.fork) == fork and started(s))

    plan_issues = [by_step[s.id] for s in c.steps if s.id in by_step and not s.fork]
    fork_issues = [by_step[s.id] for s in c.steps if s.id in by_step and s.fork]
    used = {
        "max_tasks": sum(
            1 for s in c.steps if s.kind == "task" and not s.fork and states[s.id].issue
        ),
        "max_explore_runs": runs_of("explore_run", False),
        "max_pipeline_runs": runs_of("pipeline_run", False),
        "max_model_jobs": sum(
            _model_jobs(i)
            for i in [*plan_issues, *by_repair.values(), *([closeout] if closeout else [])]
        ),
    }
    fork_used = {
        "max_tasks": sum(1 for s in c.steps if s.kind == "task" and s.fork and states[s.id].issue),
        "max_explore_runs": runs_of("explore_run", True),
        "max_pipeline_runs": runs_of("pipeline_run", True),
        # each fork task's plans and reviews, and one job per ideation (F12)
        "max_model_jobs": sum(_model_jobs(i) for i in fork_issues)
        + sum(1 for e in events if IDEATE_EVENT.match(e)),
    }
    recent = breaker_blocks(events, snap.now)
    breaker = recent if len(recent) >= BREAKER_BLOCKS else ()
    return CampaignView(c, tracking, closeout, states, events, used, breaker, fork_used, adoption)


# -- forks (decision 0015) ---------------------------------------------------------------


@dataclass
class PointState:
    """A fork point: open (ideation not started), ideating, plan (a fork plan pull
    request in flight) or closed (forks on main, none advisable, timed out, failed)."""

    step: str
    status: str
    detail: str = ""
    pr: PullRequest | None = None
    facts: dict = field(default_factory=dict)  # the ideation comment's counts


def ideation_comment(v: CampaignView, sid: str, app_bot: str) -> tuple[dict, str] | None:
    """The newest ideation comment of fork point `sid` on the tracking issue: (facts, body)."""
    found = None
    for cm in v.tracking.comments if v.tracking else ():
        parsed = markers.parse_ideation(cm.body) if cm.author == app_bot else None
        if parsed and parsed[:2] == (v.campaign.id, sid):
            found = (parsed[2], cm.body)
    return found


def _fork_plan_pr(c: Campaign, sid: str, snap: Snapshot) -> PullRequest | None:
    prefix = f"forks/{c.id}-{sid}-"
    prs = [pr for pr in snap.fork_prs.values() if pr.head_ref.startswith(prefix)]
    return max(prs, key=lambda pr: pr.number, default=None)


def point_state(v: CampaignView, sid: str, snap: Snapshot, gctx: GateContext) -> PointState:
    c = v.campaign
    at = c.forks_at(sid)
    if at:
        return PointState(sid, "closed", "forks " + ", ".join(f.id for f in at))
    found = ideation_comment(v, sid, snap.app_bot)
    facts = found[0] if found else {}
    pr = _fork_plan_pr(c, sid, snap)
    started = v.events.get(f"{sid}:ideate", "")
    if pr is not None:
        if pr.merged:
            # merged after this tick's checkout: the next tick reads the fork files
            return PointState(sid, "plan", "merged; the fork files are read next", pr, facts)
        if pr.state != "open":
            return PointState(sid, "closed", f"PR #{pr.number} was closed", pr, facts)
        if started and _older(snap.now, started, FORK_PLAN_TIMEOUT):
            return PointState(sid, "closed", f"PR #{pr.number} did not merge in time", pr, facts)
        st = _pr_state(StepState("in_review"), pr, gctx)
        if st.status == "blocked":
            return PointState(sid, "closed", f"PR #{pr.number}: {st.detail}", pr, facts)
        return PointState(sid, "plan", st.status, pr, facts)
    if found and not facts.get("forks"):
        return PointState(sid, "closed", "none", None, facts)
    if f"{sid}:ideate:skip" in v.events:
        return PointState(sid, "closed", "skipped")
    if started:
        if _older(snap.now, started, IDEATION_TIMEOUT):
            return PointState(sid, "closed", "timeout", None, facts)
        return PointState(sid, "ideating", "", None, facts)
    return PointState(sid, "open")


def open_points(v: CampaignView, root: Path) -> list[str]:
    """The fork points of the plan whose verdict the envelope lists (F11: never a fork's)."""
    c = v.campaign
    if c.forks is None:
        return []
    library = forks.load_library(root)
    return [
        sid
        for sid in forks.fork_points(c, library)
        if v.states[sid].status == "done" and v.states[sid].verdict in c.forks.on
    ]


def budget_left(v: CampaignView, s: Step) -> bool:
    """May step `s` start within its budget: the envelope's for a fork's step (F12),
    the plan's for any other (adopted steps included)."""
    c = v.campaign
    if s.fork:
        b, u = (c.forks.budget if c.forks else {}), v.fork_used
    else:
        b, u = c.budget, v.used
    if s.kind == "task":
        return u.get("max_tasks", 0) < b.get("max_tasks", 0) and u.get("max_model_jobs", 0) < b.get(
            "max_model_jobs", 0
        )
    key = "max_explore_runs" if s.kind == "explore_run" else "max_pipeline_runs"
    return u.get(key, 0) < b.get(key, 0)


def fork_outcome(v: CampaignView, fork_id: str, can_start: bool, now: str) -> str:
    """survived, killed, cannot run, or pending: what fork `fork_id` came to so far."""
    c = v.campaign
    f = c.fork(fork_id)
    steps = [c.step(sid) for sid in f.step_ids if c.step(sid)]
    states = [v.states[s.id] for s in steps]
    runs = [v.states[s.id] for s in steps if s.kind == "explore_run"]
    if any(st.status == "done" and st.verdict == "killed" for st in runs):
        return "killed"
    if runs and all(st.status == "done" for st in states):
        return "survived" if all(st.verdict == "survived" for st in runs) else "cannot run"
    if any(st.status in IN_FLIGHT for st in states):
        return "pending"
    for s, st in zip(steps, states, strict=True):
        if st.status == "blocked":
            when = v.events.get(_holding_block(s.id, st, v.events), "")
            if not when or not _older(now, when, BLOCK_GRACE):
                return "pending"
            return "cannot run"
    waiting = [
        s for s, st in zip(steps, states, strict=True) if st.status in ("unstarted", "waiting")
    ]
    if not waiting or not can_start or any(st.status == "skipped" for st in states):
        return "cannot run"
    nxt = next((s for s in waiting if v.states[s.id].status == "unstarted"), None)
    if nxt is not None and not budget_left(v, nxt):
        return "cannot run"
    return "pending"


def find_adoption(
    v: CampaignView, can_start: bool, now: str
) -> tuple[str, str, tuple[str, ...]] | None:
    """The adoption to make now (F9), or None.

    Only at a killed fork point of the plan, once every fork there has a
    verdict or cannot run (F3: no stop at the first survivor); the first
    surviving fork in the declared order with `adopts_downstream` adopts the
    steps that kill skipped and that never started. At most one per campaign.
    """
    c = v.campaign
    if v.adoption or not c.fork_files:
        return None
    for s in c.main_steps:
        st = v.states[s.id]
        if s.kind != "explore_run" or st.status != "done" or st.verdict != "killed":
            continue
        at = c.forks_at(s.id)
        if not at:
            continue
        outcomes = {f.id: fork_outcome(v, f.id, can_start, now) for f in at}
        if "pending" in outcomes.values():
            return None
        adopter = next(
            (f for f in at if outcomes[f.id] == "survived" and f.adopts_downstream), None
        )
        if adopter is None:
            continue
        steps = tuple(
            sid
            for sid in forks.adoptable(c, s.id)
            if v.states[sid].status == "skipped"
            and v.states[sid].issue is None
            and v.states[sid].run is None
            and f"{sid}:dispatched" not in v.events
        )
        if steps:
            return adopter.id, s.id, steps
    return None


def verdict_words(c: Campaign, s: Step, st: StepState) -> str:
    """A step's verdict as reports print it: a fork's reads "survived (fork)" (F8)."""
    if s.fork and s.kind == "explore_run" and st.verdict in ("killed", "survived"):
        return f"{st.verdict} (fork)"
    return st.verdict


def fork_note(c: Campaign, s: Step) -> str:
    """After a fork run's verdict: which fork, and how many were tried at its point (F8)."""
    f = c.fork(s.fork) if s.fork else None
    if f is None:
        return ""
    n = len(c.forks_at(f.parent_step))
    return (
        f" Fork {f.id} ({f.type}: {f.dimension}) is one of {n} tried at {f.parent_step}; "
        "a fork result is never a finding."
    )


def _point_closed_events(v: CampaignView, ps: PointState) -> list[tuple[str, str]]:
    sid, d = ps.step, ps.detail
    if d.startswith("forks "):
        return [
            (
                f"{sid}:ideate:merged",
                f"{sid}: {d} on main; they run after the plan's own steps (decision 0015).",
            )
        ]
    if d == "none":
        n, r = ps.facts.get("proposed", 0), ps.facts.get("refused", 0)
        return [
            (
                f"{sid}:ideate:none",
                f"{sid}: ideation found no fork to run ({n} proposed, {r} refused by the "
                "envelope check); its comment above says why.",
            )
        ]
    if d == "timeout":
        return [(f"{sid}:ideate:timeout", f"{sid}: ideation timed out; no forks at {sid}.")]
    if d == "skipped":
        return []
    return [
        (f"{sid}:ideate:failed", f"{sid}: the fork plan did not merge ({d}); no forks at {sid}.")
    ]


def task_issue(
    c: Campaign, s: Step, root: Path, adoption: tuple[str, str, tuple[str, ...]] | None
) -> dict:
    """The create_issue action for task step `s`: its draft, word for word.

    A fork's task also carries the fork's marker. A step a fork adopted gets the
    approved draft plus a section holding the fork's delta, and the adopted
    marker (F9); the gate checks both.
    """
    title, body = markers.draft_body((root / s.draft).read_text(encoding="utf-8"))
    tail = [markers.step_marker(c.id, s.id)]
    if s.fork:
        tail.append(markers.fork_marker(c.id, s.fork))
    if adoption and s.id in adoption[2] and c.fork(adoption[0]):
        fid = adoption[0]
        body = f"{body}\n\n{markers.delta_section(fid, c.fork(fid).delta)}"
        tail.append(markers.adopted_marker(c.id, s.id, fid))
    labels = ["campaign", "explore"] if s.type == "explore" else ["campaign"]
    return {
        "type": "create_issue",
        "title": title,
        "body": f"{body}\n\n" + "\n".join(tail) + "\n",
        "labels": labels,
        "then_labels": ["agent-plan"],
    }


def _listed(body: str, heading: str) -> list[str]:
    """The `- ` items under `heading` in an ideation comment, made safe to copy."""
    out, inside = [], False
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("#"):
            inside = line.strip().lstrip("#").strip() == heading
        elif inside and line.startswith("- "):
            item = line[2:].replace("<!--", "&lt;!--").replace("-->", "--&gt;").strip()
            out.append(item if len(item) <= 300 else item[:299] + "…")
    return out


REFUSED_HEADING = "Refused by the envelope check"
SUGGESTED_HEADING = "Suggestions outside the envelope"


def forks_facts(v: CampaignView, snap: Snapshot, root: Path) -> str:
    """The forks, for the close-out report, written by code (decision 0015, F8)."""
    c = v.campaign

    def why(f) -> str:  # noqa: ANN001 (a Fork)
        lines = f.body.replace("\r\n", "\n").split("\n")
        start = next((i for i, ln in enumerate(lines) if ln.startswith("## Why")), None)
        text = next((ln.strip() for ln in lines[start + 1 :] if ln.strip()), "") if start else ""
        return text if len(text) <= 200 else text[:199] + "…"

    rows = []
    for f in c.fork_files:
        steps = [c.step(sid) for sid in f.step_ids if c.step(sid)]
        runs = [s for s in steps if s.kind == "explore_run"]
        outcome = fork_outcome(v, f.id, False, snap.now)
        verdict = f"{outcome} (fork)" if outcome in ("survived", "killed") else outcome
        numbers = "; ".join(ln for s in runs for ln in v.states[s.id].verdict_lines) or "none"
        rows.append(
            [
                f.id,
                f.parent_step,
                f.type,
                f.dimension,
                why(f),
                ", ".join(f.step_ids),
                verdict,
                numbers,
            ]
        )
    tried = []
    points = sorted({f.parent_step for f in c.fork_files} | set(open_points(v, root)), key=_num)
    for sid in points:
        found = ideation_comment(v, sid, snap.app_bot)
        facts = found[0] if found else {}
        at = c.forks_at(sid)
        ran = [f for f in at if any(_begun(v, c.step(x)) for x in f.step_ids if c.step(x))]
        survived = [f for f in at if fork_outcome(v, f.id, False, snap.now) == "survived"]
        proposed = facts.get("proposed", len(at))
        refused = facts.get("refused", 0)
        note = "" if found else " (no ideation comment: the numbers are the forks on main)"
        tried.append(
            f"- {sid}: {proposed} proposed, {refused} refused by the envelope check, "
            f"{len(ran)} ran, {len(survived)} survived{note}."
        )
    if not tried:
        tried = ["- None: no fork point opened."]
    refused_lines, suggested = [], []
    for sid in points:
        found = ideation_comment(v, sid, snap.app_bot)
        if found:
            refused_lines += [f"{sid}: {x}" for x in _listed(found[1], REFUSED_HEADING)]
            suggested += [f"{sid}: {x}" for x in _listed(found[1], SUGGESTED_HEADING)]
    adoption = (
        f"Fork {v.adoption[0]} adopted {_id_range(v.adoption[2])} after {v.adoption[1]} was killed."
        if v.adoption
        else "No fork adopted the plan's skipped steps."
    )
    header = [
        "Fork",
        "Parent step",
        "Type",
        "What changed",
        "Why",
        "Steps",
        "Verdict",
        "The numbers its kill rules read",
    ]
    return f"""### Forks table

{table(header, rows) if rows else "None: no fork was declared."}

{adoption}

### How many were tried

{chr(10).join(tried)}

A pass among several variants is weaker evidence than one test set in advance: each
fork that survived is one of the number tried at its point, on the exploration half.

### Refused and suggested variants

{chr(10).join(f"- {x}" for x in refused_lines + suggested) or "None."}"""


def _num(sid: str) -> int:
    return int(sid[1:]) if sid[1:].isdigit() else 0


def _begun(v: CampaignView, s: Step) -> bool:
    st = v.states[s.id]
    return bool(st.issue or st.run) or f"{s.id}:dispatched" in v.events


def _id_range(ids: Sequence[str]) -> str:
    return ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}"


def _tasks_in_flight(v: CampaignView) -> int:
    """Tasks of the campaign in flight: task steps, and repairs being worked."""
    return sum(
        1
        for s in v.campaign.steps
        if v.states[s.id].status in IN_FLIGHT and (s.kind == "task" or v.states[s.id].repairing)
    )


def block_id(cause: str, links: str) -> str:
    """A block's id: the first 8 hex characters of the SHA-256 of its cause and links."""
    return hashlib.sha256(f"{cause}\n{links}".encode()).hexdigest()[:8]


def _unblocked(block_event: str) -> str:
    """`s1:blocked:ab12cd34` -> `s1:unblocked:ab12cd34` (and `s1:blocked` -> `s1:unblocked`)."""
    sid, _, rest = block_event.partition(":blocked")
    return f"{sid}:unblocked{rest}"


def _blocks(sid: str, events: dict[str, str]) -> list[str]:
    """Every block event of step `sid` in the ledger, including the old plain `sid:blocked`."""
    plain = f"{sid}:blocked"
    return sorted(e for e in events if e == plain or e.startswith(plain + ":"))


def _holding_block(sid: str, st: StepState, events: dict[str, str]) -> str:
    """The ledger event of the block that holds step `sid` now, posted or not yet.

    Each distinct block (cause, issue, pull request or run) gets its own event,
    `sid:blocked:<id>`. The same block coming back after it was unblocked gets
    `sid:blocked:<id>-2`, `-3` and so on, so it is reported again. A plain
    `sid:blocked` from before blocks had ids, never unblocked, is taken to be
    the block that still holds.
    """
    plain = f"{sid}:blocked"
    if plain in events and _unblocked(plain) not in events:
        return plain
    base = f"{plain}:{block_id(st.detail, st.links())}"
    name, n = base, 1
    while name in events and _unblocked(name) in events:
        n += 1
        name = f"{base}-{n}"
    return name


def _block_line(label: str, st: StepState, owner: str) -> str:
    cause = st.detail.strip()
    stop = "" if cause.endswith(".") else "."
    action = NEEDS_YOU.get(st.cause, NEEDS_YOU_DEFAULT)
    lines = [*st.verdict_lines, st.run_again] if st.run_again else st.verdict_lines
    extra = "".join(f"\n  - {ln}" for ln in lines)
    return (
        f"{label}: **blocked**. Cause: {cause}{stop} Needs you: {action}. "
        f"({st.links() or 'no links'}) @{owner}{extra}"
    )


def _block_events(
    sid: str, st: StepState, owner: str, events: dict[str, str], label: str = ""
) -> list[tuple[str, str]]:
    """Ledger events for step `sid`'s blocks: an unblocked line for each block that
    no longer holds, and the block that holds now. Already posted ones are dropped
    by the caller."""
    holding = _holding_block(sid, st, events) if st.status == "blocked" else ""
    out = [
        (_unblocked(name), f"{label or sid}: unblocked.")
        for name in _blocks(sid, events)
        if name != holding and _unblocked(name) not in events
    ]
    if holding:
        out.append((holding, _block_line(label or sid, st, owner)))
    return out


def breaker_blocks(events: dict[str, str], now: str) -> tuple[str, ...]:
    """The step blocks that count toward the circuit breaker, oldest first: of the
    newer kind, posted within BREAKER_WINDOW before `now`, and not unblocked since."""
    return tuple(
        sorted(
            (
                e
                for e, when in events.items()
                if _STEP_BLOCK.match(e)
                and _unblocked(e) not in events
                and not _older(now, when, BREAKER_WINDOW)
            ),
            key=lambda e: (_time(events[e]), e),
        )
    )


def breaker_line(c: Campaign, blocks: Sequence[str]) -> str:
    """The circuit breaker's message, in plain words, naming the blocked steps."""
    sids = {b.partition(":")[0] for b in blocks}
    steps = ", ".join(s.id for s in c.steps if s.id in sids)
    hours = int(BREAKER_WINDOW.total_seconds() // 3600)
    return (
        f"Paused by the circuit breaker: {len(blocks)} steps blocked within {hours} hours "
        f"({steps}). Nothing new starts until fewer than {BREAKER_BLOCKS} blocks fall in "
        f"the last {hours} hours, or you clear the blocks."
    )


def _breaker_events(v: CampaignView, held: bool) -> list[tuple[str, str]]:
    """The ledger event for the breaker now: holding (once per occasion), or lifting."""
    k = 0
    while f"breaker:held:{k + 1}" in v.events:
        k += 1
    open_ = k > 0 and f"breaker:lifted:{k}" not in v.events
    if held and not open_:
        return [
            (f"breaker:held:{k + 1}", f"{breaker_line(v.campaign, v.breaker)} @{v.campaign.owner}")
        ]
    if open_ and not v.breaker:
        return [
            (
                f"breaker:lifted:{k}",
                f"Circuit breaker lifted: fewer than {BREAKER_BLOCKS} blocks in the last "
                f"{int(BREAKER_WINDOW.total_seconds() // 3600)} hours. New steps start again.",
            )
        ]
    return []


def checks_not_run(v: CampaignView) -> list[str]:
    """What the campaign never checked, for the close-out report, one line each.

    Every step that did not finish, every kill rule that was never applied
    because its step did not run to a result (or its results could not be
    read), and every referee row the review of a merged pull request marked
    "Not applicable".
    """
    c, out = v.campaign, []
    for s in c.steps:
        st = v.states[s.id]
        if st.status != "done":
            why = f"{st.status}: {st.detail}" if st.detail else st.status
            out.append(f"Step {s.id} ({s.kind}) did not finish ({why.strip().rstrip('.')}).")
    for s in c.steps:
        st = v.states[s.id]
        if st.status == "done" and st.verdict != "unreadable":
            continue
        reason = (
            "the run's results could not be read for it"
            if st.verdict == "unreadable"
            else f"step {s.id} did not run to a result"
        )
        for k in s.kill_rules:
            out.append(f"Kill rule {k.id} of step {s.id} ({k.says}) was never applied: {reason}.")
    for s in c.steps:
        pr = v.states[s.id].pr
        review = pr.review_of_head() if pr and pr.merged else None
        for rid, status in sorted((review.referee if review else {}).items()):
            if status == "Not applicable":
                out.append(
                    f"Referee {rid} was marked Not applicable in the review of step {s.id} "
                    f"(PR #{pr.number})."
                )
    return out


# -- friction facts: what slowed the campaign down, for the close-out report ------


def _hours(start: str, end: str) -> float:
    return (_time(end) - _time(start)).total_seconds() / 3600


def _cause_in(line: str, label: str) -> str:
    """The cause in a ledger line that reports a block of `label`, or "" if it is not one."""
    new = f"{label}: **blocked**. Cause: "
    old = f"{label}: **blocked**: "  # before blocks had causes and ids
    if line.startswith(new):
        return line[len(new) :].split(" Needs you: ", 1)[0].strip().removesuffix(".")
    if line.startswith(old):
        return line[len(old) :].rsplit(" (", 1)[0].strip()
    return ""


def _items(body: str) -> list[str]:
    """The top-level `- ` lines of a ledger comment, without the dash."""
    return [ln[2:] for ln in body.replace("\r\n", "\n").split("\n") if ln.startswith("- ")]


def _block_causes(
    tracking: Issue | None, cid: str, app_bot: str, new: Sequence[tuple[str, str]]
) -> dict[str, str]:
    """Block event -> its cause, as the ledger line that reported it says."""
    comments: list[tuple[set[str], list[str]]] = []
    for cm in tracking.comments if tracking else ():
        found = markers.parse_ledger(cm.body) if cm.author == app_bot else None
        if found and found[0] == cid:
            comments.append((found[1], _items(cm.body)))
    comments += [({name}, [line]) for name, line in new]
    causes: dict[str, str] = {}
    for names, items in comments:
        for name in sorted(names):
            sid, sep, _ = name.partition(":blocked")
            if not sep or name in causes:
                continue
            label = "close-out" if sid == "closeout" else sid
            cause = next((x for x in (_cause_in(it, label) for it in items) if x), "")
            if cause:
                causes[name] = cause
    return causes


def friction_facts(v: CampaignView, snap: Snapshot, new: Sequence[tuple[str, str]] = ()) -> str:
    """What slowed the campaign down, as plain facts from the ledger and GitHub.

    `new` holds the ledger events this tick is about to post; the campaign is
    taken to finish now if its `finished` event is not posted yet. No model is
    involved: every number is counted from what the tick already reads.
    """
    c = v.campaign
    events = dict(v.events)
    for name, _ in new:
        events.setdefault(name, snap.now)
    events.setdefault("finished", snap.now)
    causes = _block_causes(v.tracking, c.id, snap.app_bot, new)

    blocks = sorted(
        (events[name], sid, name)
        for sid in [*(s.id for s in c.steps), "closeout"]
        for name in _blocks(sid, events)
    )
    block_rows = [
        [
            "close-out" if sid == "closeout" else sid,
            causes.get(name, "not readable from the ledger line"),
            when,
            f"{_hours(when, events[_unblocked(name)]):.1f}"
            if _unblocked(name) in events
            else "never",
        ]
        for when, sid, name in blocks
    ]

    task_rows, smooth = [], []
    for s in c.steps:
        issue = v.states[s.id].issue
        if s.kind != "task" or issue is None:
            continue
        plans = _plans(issue)
        fixes = max(len(issue.pr.reviews) - 1, 0) if issue.pr else 0
        if plans > 1 or fixes:
            task_rows.append([s.id, str(plans), str(fixes), str(_model_jobs(issue))])
        else:
            smooth.append(s.id)

    repair_rows = []
    for s in c.steps:
        st = v.states[s.id]
        if s.kind != "pipeline_run" or not (st.repair or _repair_event(s.id) in events):
            continue
        fix = st.repair
        pr = fix.pr if fix else None
        if _repair_event(s.id, "run") in events:
            after = st.run.conclusion if st.run and st.status != "waiting_run" else ""
            ended = f"merged; the run after it: {after or st.status}"
        elif st.status == "blocked":
            ended = f"blocked: {st.detail}"
        else:
            ended = st.status
        repair_rows.append(
            [
                s.id,
                f"#{fix.number}" if fix else "never appeared",
                f"PR #{pr.number}" if pr else "none",
                str(_model_jobs(fix)) if fix else "0",
                ended,
            ]
        )

    run_rows = []
    for s in c.steps:
        runs = _step_runs(c, s, snap) if s.kind != "task" else []
        if len(runs) > 1:
            ended = ", ".join(f"{r.id} {r.conclusion or r.status}" for r in runs)
            run_rows.append([s.id, str(len(runs)), ended])

    at: dict[str, list[str]] = {}
    for name, when in events.items():
        at.setdefault(when, []).append(name)
    times = sorted(at, key=_time)
    all_gaps = sorted(
        ((_hours(a, b), a, b) for a, b in zip(times, times[1:], strict=False)),
        key=lambda g: (-g[0], _time(g[1])),
    )
    gaps = all_gaps[:3]
    gaps_left = len(all_gaps) - len(gaps)

    def names(when: str) -> str:
        return ", ".join(f"`{n}`" for n in sorted(at[when])) + f" ({when})"

    gap_rows = [[f"{h:.1f}", names(a), names(b)] for h, a, b in gaps]

    def group(rows: list[list[str]], header: list[str]) -> str:
        return table(header, rows) if rows else "None."

    started = events.get("started", "")
    wall = (
        f"Wall-clock time from `started` ({started}) to `finished` ({events['finished']}): "
        f"{_hours(started, events['finished']):.1f} hours."
        if started
        else "Wall-clock time: none (the ledger has no `started` event)."
    )
    smooth_line = f"\n\nOne plan and no fix round: {', '.join(smooth)}." if smooth else ""
    gaps_line = (
        f"\n\n{gaps_left} shorter gap{'s' if gaps_left > 1 else ''} left out." if gaps_left else ""
    )
    return f"""### Blocks

{group(block_rows, ["Step", "Cause", "Posted", "Hours until unblocked"])}

### Task steps with more than one plan or a fix round

{group(task_rows, ["Step", "Plans posted", "Fix rounds", "Model jobs"])}{smooth_line}

### Run steps that took more than one run

{group(run_rows, ["Step", "Runs", "Run ids and how they ended"])}

### Repairs

{group(repair_rows, ["Step", "Repair issue", "Pull request", "Model jobs", "How it ended"])}

### Time

{wall}

The three longest gaps between two ledger events:

{group(gap_rows, ["Hours", "After", "Before"])}{gaps_line}"""


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
    point = v.adoption[1] if v.adoption else ""
    if any(
        s.verdict == "killed" and c.step(k).on_kill == "stop" and not c.step(k).fork and k != point
        for k, s in states.items()
    ):
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
    status_page: bool = False,
) -> list[dict]:
    """The actions for this tick, ledger comments first within each campaign.

    `campaigns` are the active ones. `ended` (done or stopped) only get their
    tracking issue closed once their close-out PR is merged (`close_tracking`).
    With `status_page` (the workflow's tick), the last action creates or
    rewrites the status issue, and only when its body would change
    (`terrain.campaigns.status`).
    """
    if not snap.enabled:
        return []
    actions, views = _advance(campaigns, snap, gctx, root)
    for c in ended:
        actions.extend(close_tracking(c, snap))
    if status_page:
        from terrain.campaigns import status  # status reads this module's views

        actions.extend(status.page_actions(status.render(views, ended, snap, gctx, root), snap))
    return actions


def render_status_page(
    campaigns: list[Campaign],
    snap: Snapshot,
    gctx: GateContext,
    root: Path,
    ended: Sequence[Campaign] = (),
) -> str:
    """The status page as this tick would write it, for reading it locally."""
    from terrain.campaigns import status

    _, views = _advance(campaigns, snap, gctx, root)
    return status.render(views, ended, snap, gctx, root)


def _advance(
    campaigns: list[Campaign], snap: Snapshot, gctx: GateContext, root: Path
) -> tuple[list[dict], list[CampaignView]]:
    """Each active campaign's actions, and the views they were decided from.

    The views carry the states this tick leaves the steps in (a retry or a
    repair just started, for example), which is what the status page shows.
    """
    actions: list[dict] = []
    views = [view(c, snap, gctx) for c in campaigns]
    slots = RunSlots.count(views)
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
        can_start = not stopped and today <= dt.date.fromisoformat(c.end_by)
        # the circuit breaker: nothing new starts (no step, retry, repair or run
        # after a repair); work in flight and merges go on
        held = bool(v.breaker) and can_start and v.closeout is None
        for name, line in _breaker_events(v, held):
            event(name, line)
        if not held:
            v.breaker = ()
        breaker_wait = "once the circuit breaker lifts"
        filed_repair = False
        for s in c.steps:
            st = v.states[s.id]
            why_not = _no_repair(c, s, st, v, gctx) if can_start else "-"
            if why_not == "" and (held or _tasks_in_flight(v)):
                wait = breaker_wait if held else "once no other task is in flight"
                st = StepState(
                    "repair_waiting",
                    f"run {st.run.id} ended '{st.run.conclusion}' after {MAX_AUTO_RETRIES} "
                    f"retries; a repair is filed {wait}",
                    run=st.run,
                )
            elif why_not == "":
                event(
                    _repair_event(s.id),
                    f"{s.id}: run {st.run.id} ended '{st.run.conclusion}' after "
                    f"{MAX_AUTO_RETRIES} retries. Filing a repair task to fix the code "
                    f"(repair {_repairs(c, v) + 1} of at most {repair.MAX_PER_CAMPAIGN} "
                    "in this campaign).",
                )
                title, body = repair.repair_issue(
                    c,
                    s,
                    st.run.id,
                    snap.run_logs.get(st.run.id, ""),
                    repair.repair_paths(c, s, gctx.codeowners),
                    repair.MAX_PER_STEP,
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
                st = StepState(
                    "repair_filing", "the repair task was just filed", run=st.run, repairing=True
                )
                filed_repair = True
            elif why_not != "-":
                st.detail += f" Not repaired: {why_not}."
            if st.status == "repair_merged" and not can_start:
                st.status = "blocked"
                st.detail = (
                    f"{st.detail.split(';')[0]}, but the campaign is stopped or past its end "
                    "date, so the run was not started again"
                )
                st.cause, st.run_again = "run_failed", _run_again(c, s)
            elif st.status == "repair_merged" and (held or slots.wait(c, s)):
                st.detail = f"{st.detail} {breaker_wait if held else slots.wait(c, s)}"
            elif st.status == "repair_merged":
                event(
                    _repair_event(s.id, "run"),
                    f"{s.id}: started `{s.stage} {s.target}` again after the repair "
                    f"(PR #{st.pr.number}).",
                )
                doing.append(run_dispatch(c, s))
                slots.take(c, s)
                st = StepState("waiting_run", run=st.run, repair=st.repair)
            v.states[s.id] = st
            if st.retry and can_start:
                if held or slots.wait(c, s):
                    st = StepState(
                        "retry_waiting",
                        f"run {st.run.id} ended '{st.run.conclusion}'; it starts again "
                        f"{breaker_wait if held else slots.wait(c, s)}",
                        run=st.run,
                    )
                else:
                    event(
                        f"{s.id}:retry:{st.retry}",
                        f"{s.id}: run {st.run.id} ended '{st.run.conclusion}'. Retrying by "
                        f"itself ({st.retry} of {MAX_AUTO_RETRIES}) with a fresh run.",
                    )
                    doing.append(run_dispatch(c, s))
                    slots.take(c, s)
                    st = StepState("waiting_run", run=st.run)
                v.states[s.id] = st
            if st.resume and can_start:
                k, n, m = st.resume
                if held or slots.wait(c, s):
                    st = StepState(
                        "resume_waiting",
                        f"run {st.run.id} is still exporting ({n} of {m} done); it starts "
                        f"again {breaker_wait if held else slots.wait(c, s)}",
                        run=st.run,
                    )
                else:
                    event(
                        f"{s.id}:continue:{k}:{n}",
                        f"{s.id}: run {st.run.id} is still exporting ({n} of {m} done). "
                        f"Starting it again by itself ({k} of at most {MAX_CONTINUES}); "
                        "this is no failure and uses no retry.",
                    )
                    doing.append(run_dispatch(c, s))
                    slots.take(c, s)
                    st = StepState("waiting_run", run=st.run)
                v.states[s.id] = st
            if st.issue and s.kind == "task":
                event(f"{s.id}:filed", f"{s.id}: filed as #{st.issue.number}.")
            if st.repair:
                event(_repair_event(s.id, "filed"), f"{s.id}: repair filed as #{st.repair.number}.")
            if st.repair and st.repair.pr and st.repair.pr.merged:
                event(
                    _repair_event(s.id, "merged"),
                    f"{s.id}: repair PR #{st.repair.pr.number} merged.",
                )
            if st.status == "done" and s.kind == "task":
                event(f"{s.id}:merged", f"{s.id}: PR #{st.pr.number} merged.")
            if st.status == "done" and s.kind == "explore_run":
                lines = "\n".join(f"  - {ln}" for ln in st.verdict_lines)
                event(
                    f"{s.id}:verdict",
                    f"{s.id}: run {st.run.id} recorded (PR #{st.pr.number}). Verdict: "
                    f"**{verdict_words(c, s, st)}**.{fork_note(c, s)}\n{lines}",
                )
            if st.status == "done" and s.kind == "pipeline_run":
                event(f"{s.id}:recorded", f"{s.id}: {s.stage} {s.target} recorded ({st.links()}).")
            if st.status == "skipped":
                event(f"{s.id}:skipped", f"{s.id}: skipped ({st.detail}).")
            for name, line in _block_events(s.id, st, c.owner, v.events):
                event(name, line)
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

        # forks (decision 0015): fork points, their ideation and fork plans
        points_busy = points_waiting = False
        ideating = 0
        for sid in open_points(v, root) if not stopped and v.closeout is None else []:
            ps = point_state(v, sid, snap, gctx)
            if ps.status == "closed":
                for name, line in _point_closed_events(v, ps):
                    event(name, line)
            elif ps.status == "plan":
                points_busy = True
                event(
                    f"{sid}:ideate:pr",
                    f"{sid}: the ideation proposed forks in PR #{ps.pr.number}; the gate checks "
                    "them and the tick merges it.",
                )
                if ps.detail == "mergeable":
                    doing.append({"type": "merge", "pr": ps.pr.number, "sha": ps.pr.head_sha})
                elif ps.detail == "awaiting_gate":
                    doing.append(
                        {
                            "type": "dispatch",
                            "workflow": GATE_WORKFLOW,
                            "inputs": {"pr": str(ps.pr.number)},
                        }
                    )
            elif ps.status == "ideating":
                points_busy = True
            elif not can_start:
                pass  # past the end date: no new ideation
            elif len(c.fork_files) >= c.forks.max_forks:
                event(
                    f"{sid}:ideate:skip",
                    f"{sid}: fork point, but the envelope's {c.forks.max_forks} forks are all "
                    "used; no ideation.",
                )
            elif v.fork_used["max_model_jobs"] + ideating >= c.forks.budget["max_model_jobs"]:
                event(
                    f"{sid}:ideate:skip",
                    f"{sid}: fork point, but the forks' model-job budget is used up; no ideation.",
                )
            elif held:
                points_waiting = True
            else:
                event(f"{sid}:ideate", f"{sid}: fork point; ideation started.")
                doing.append(
                    {
                        "type": "dispatch",
                        "workflow": IDEATE_WORKFLOW,
                        "inputs": {"campaign": c.id, "step": sid},
                    }
                )
                ideating += 1
                points_busy = True
        if not stopped and v.closeout is None:
            found = find_adoption(v, can_start, snap.now)
            if found:
                fid, point, steps = found
                event(
                    adoption_event(fid, point, steps),
                    f"{fid} adopts {_id_range(steps)}: the plan's step {point} was killed and "
                    f"fork {fid} survived (fork), the first in the declared order of "
                    f"{len(c.forks_at(point))} tried there. Their issues are the approved drafts "
                    f"plus the fork's delta.",
                )
                adopted = view(c, snap, gctx, found)
                v.states.update(
                    {sid: adopted.states[sid] for sid in steps if v.states[sid].status == "skipped"}
                )
                v.adoption, v.used = found, adopted.used

        tasks_in_flight = _tasks_in_flight(v)
        started = filed_repair  # anything started this tick
        paced = filed_repair  # a task, explore run or repair: one per campaign per tick
        # F13: a fork's step starts only when no step of the plan can start
        plan_startable = any(
            v.states[s.id].status == "unstarted" and budget_left(v, s) for s in c.main_steps
        )
        for s in c.steps:
            st = v.states[s.id]
            if not can_start or held or st.status != "unstarted":
                continue
            if paced and (s.kind != "pipeline_run" or filed_repair):
                continue
            if s.fork and plan_startable:
                continue
            if not budget_left(v, s):
                continue
            used = v.fork_used if s.fork else v.used
            if s.kind == "task":
                if tasks_in_flight:
                    continue
                doing.append(task_issue(c, s, root, v.adoption))
                started = paced = True
            else:
                key = "max_explore_runs" if s.kind == "explore_run" else "max_pipeline_runs"
                if slots.wait(c, s):
                    continue
                doing.append(run_dispatch(c, s))
                event(
                    f"{s.id}:dispatched",
                    f"{s.id}: started `{s.script or s.stage + ' ' + s.target}`.",
                )
                slots.take(c, s)
                used[key] += 1  # several pipeline runs may start in one tick
                started = True
                paced |= s.kind == "explore_run"

        in_flight = any(st.status in IN_FLIGHT for st in v.states.values()) or points_busy
        startable = points_waiting
        if can_start and not started:
            for s in c.steps:
                if v.states[s.id].status == "unstarted":
                    startable |= budget_left(v, s)
        finished = (not in_flight and not started and not startable) or (stopped and not in_flight)
        if stopped and in_flight:
            finished = True  # nothing in flight will merge now; close out what there is
        if finished and not stopped:
            # a block posted less than a day ago (or not yet posted) gives the
            # owner time to unblock it before the campaign closes; the day counts
            # from the newest block of the step that still holds
            for sid, st in v.states.items():
                if st.status != "blocked":
                    continue
                when = v.events.get(_holding_block(sid, st, v.events), "")
                if not when or not _older(snap.now, when, BLOCK_GRACE):
                    finished = False
        if finished:
            reason = _reason(v, stopped, today)
            if v.closeout is None:
                rows = [
                    {
                        "step": s.id + (f" ({s.fork})" if s.fork else ""),
                        "kind": s.kind,
                        "status": v.states[s.id].status,
                        "verdict": verdict_words(c, s, v.states[s.id]) or v.states[s.id].detail,
                        "links": v.states[s.id].links(),
                    }
                    for s in c.steps
                ]
                final = "stopped" if stopped else "done"
                applied = [
                    f"{s.id}: {line}" for s in c.steps for line in v.states[s.id].verdict_lines
                ]
                title, body = closeout_issue(
                    c,
                    root,
                    rows,
                    v.used,
                    reason,
                    v.tracking.number,
                    final,
                    applied,
                    friction_facts(v, snap, new),
                    checks_not_run(v),
                    forks_facts(v, snap, root) if c.forks else "",
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
                for name, line in _block_events("closeout", cst, c.owner, v.events, "close-out"):
                    event(name, line)
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
                elif cst.status == "mergeable" and c.owner in cst.pr.approvals:
                    # the owner's GitHub review approves this exact head commit:
                    # that is how the owner accepts the report (decision 0012)
                    event(
                        f"closeout:approved:{cst.pr.head_sha[:12]}",
                        f"Close-out approved by @{c.owner}; merging PR #{cst.pr.number}.",
                    )
                    doing.append({"type": "merge", "pr": cst.pr.number, "sha": cst.pr.head_sha})
                elif cst.status == "mergeable":
                    event(
                        "closeout:ready",
                        f"@{c.owner} the report is ready: PR #{cst.pr.number}. To accept it, "
                        "open the pull request, choose Files changed, then Review changes, "
                        "then Approve. It is then merged for you. To reject it, close the "
                        "pull request.",
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
    return actions, views


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
