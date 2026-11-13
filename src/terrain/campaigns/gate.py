"""`campaign-gate`: may this pull request be merged without a person?

The gate is a required status check on main. It is plain code that reads the
pull request and the campaign files on main; no model takes part.

- A pull request that the agent App did not open is not the gate's business:
  success, and its author merges it as before.
- An agent pull request outside an active campaign waits (pending) until a
  code owner approves its head commit, which is how agent work was merged
  before campaigns.
- An agent pull request inside an active campaign passes only if every check
  below passes. The tick merges it; nobody else needs to.
- A repair pull request (its issue carries a `campaign-repair` marker,
  decision 0014) fails unless its campaign is active with `self_repair: true`,
  its step is a pipeline_run, every file is a repair file and neither
  protected nor owned, and the issue is the tick's template, unchanged.
- Forks (decision 0015). A fork plan pull request (branch
  `forks/NNNN-sNN-<run id>`, opened by the App from that campaign's ideation
  run for that step) passes only if every file is added under the
  campaign's `forks/` folder, the files pass the fork checks (read through
  the API, never checked out) and CI passes. A fork's task passes only if its
  issue is the fork's draft and the review's R8 (fork discipline) is OK; a
  step a fork adopted, only if its issue is the approved draft plus the
  fork's delta section. Fork files are append-only: any pull request that
  changes or deletes one fails, whoever opened it, unless the owner did.

Code-owner review (CODEOWNERS plus the ruleset) is a second, separate lock:
the App cannot merge an owned path even if the gate said success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from terrain.campaigns import forks, markers, repair
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import PullRequest
from terrain.campaigns.spec import (
    NOTES_PATH,
    Campaign,
    is_protected,
    parse_campaign,
    path_allowed,
)

TASK_BRANCH = re.compile(r"^agent/issue-(\d+)$")
RECORD_BRANCH = re.compile(r"^explore/(\d{4}_[a-z0-9_]{1,60})-(\d+)$")
MANIFEST_BRANCH = re.compile(r"^data/(acquire|build)-([a-z][a-z0-9_]{0,63})-(\d+)$")
FORK_BRANCH = re.compile(r"^forks/(\d{4})-(s\d{1,2})-(\d+)$")
FORK_PATH = re.compile(r"^research/campaigns/[^/]+/forks/")
IDEATE_PATH = ".github/workflows/campaign-ideate.yml"


@dataclass(frozen=True)
class GateResult:
    state: str  # "success", "pending" or "failure"
    description: str  # at most 140 characters (GitHub's limit)
    details: tuple[str, ...] = field(default=())
    campaign: str = ""
    step: str = ""


@dataclass(frozen=True)
class GateContext:
    app_bot: str  # login of the agent App, e.g. terrain-agent[bot]
    repo_owner: str
    campaigns: tuple[Campaign, ...]  # active and valid only
    codeowners: CodeOwners
    root: Path  # checkout of main, for drafts and idea files


def _short(text: str) -> str:
    return text if len(text) <= 140 else text[:137] + "..."


def closeout_paths(c: Campaign, root: Path) -> tuple[str, ...]:
    ideas = sorted(
        p.relative_to(root).as_posix() for p in (root / "research" / "ideas").glob(f"{c.idea}-*.md")
    )
    return (
        f"{c.folder}/report.md",
        f"{c.folder}/ledger.md",
        f"{c.folder}/campaign.md",
        "research/lessons.md",
        NOTES_PATH,
        *ideas,
    )


def _outside(pr: PullRequest, ctx: GateContext, why: str) -> GateResult:
    if ctx.repo_owner in pr.approvals:
        return GateResult(
            "success", _short(f"{why}; approved by @{ctx.repo_owner} on this commit.")
        )
    return GateResult(
        "pending", _short(f"{why}: @{ctx.repo_owner} approves the head commit, then merges.")
    )


def _checks(pr: PullRequest, label: str, failures: list[str], cid: str, sid: str) -> GateResult:
    """CI and the agent review of the head commit, after the other `failures`."""
    pending: list[str] = []
    if pr.ci_test is None:
        pending.append("waiting for CI's test check on the head commit")
    elif pr.ci_test != "success":
        failures.append(f"CI's test check is '{pr.ci_test}' on the head commit")
    review = pr.review_of_head()
    if review is None:
        pending.append(f"waiting for an agent review of {pr.head_sha[:12]}")
    elif review.verdict != "approve":
        pending.append("the agent review asked for changes (fix rounds run on their own)")
    if failures:
        return GateResult(
            "failure", _short(f"{label}: {failures[0]}"), tuple(failures + pending), cid, sid
        )
    if pending:
        return GateResult("pending", _short(f"{label}: {pending[0]}"), tuple(pending), cid, sid)
    return GateResult("success", _short(f"{label}: every check passes."), (), cid, sid)


def _repair(pr: PullRequest, ctx: GateContext, cid: str, sid: str, n: int) -> GateResult:
    """The gate for a repair pull request (decision 0014): anything unexpected fails."""
    label = f"Campaign {cid} step {sid} repair"
    campaign = next((c for c in ctx.campaigns if c.id == cid), None)
    if campaign is None:
        return GateResult("failure", _short(f"{label}: the campaign is not active."), (), cid, sid)
    if not campaign.self_repair:
        return GateResult(
            "failure", _short(f"{label}: the campaign does not allow repairs."), (), cid, sid
        )
    step = campaign.step(sid)
    if step is None or step.kind != "pipeline_run":
        return GateResult(
            "failure", _short(f"{label}: there is no pipeline_run step {sid}."), (), cid, sid
        )
    if not 1 <= n <= repair.MAX_PER_STEP:
        return GateResult(
            "failure", _short(f"{label}: a step gets at most one repair."), (), cid, sid
        )
    failures: list[str] = []
    paths = repair.repair_paths(campaign, step, ctx.codeowners)
    if not pr.files:
        failures.append("the pull request changes no files")
    bad = [f for f in pr.files if not path_allowed(f, paths)]
    if bad:
        failures.append(f"files outside the repair's allowed files: {bad[:5]}")
    prot = [f for f in pr.files if is_protected(f) or ctx.codeowners.owned(f)]
    if prot:
        failures.append(f"protected or owned paths: {prot[:5]}")
    if not repair.matches_template(campaign, step, pr.issue_title, pr.issue_body, paths, n):
        failures.append("the issue is not the repair template the tick files for this step")
    return _checks(pr, label, failures, cid, sid)


def fork_edits(pr: PullRequest) -> list[str]:
    """Fork files this pull request changes, renames or deletes (F2: append-only)."""
    return sorted({p for p, status in pr.changes if FORK_PATH.match(p) and status != "added"})


def _fork_plan(pr: PullRequest, ctx: GateContext, cid: str, sid: str) -> GateResult:
    """The gate for a fork plan pull request (decision 0015): anything unexpected fails."""
    label = f"Campaign {cid} step {sid} fork plan"

    def fail(why: str, details: tuple[str, ...] = ()) -> GateResult:
        return GateResult("failure", _short(f"{label}: {why}"), details, cid, sid)

    campaign = next((c for c in ctx.campaigns if c.id == cid), None)
    if campaign is None:
        return fail("the campaign is not active.")
    if campaign.forks is None:
        return fail("the campaign has no forks envelope.")
    if pr.run_title != markers.ideation_run_title(cid, sid) or pr.run_workflow != IDEATE_PATH:
        return fail("the branch does not come from this campaign's ideation run for this step.")
    library = forks.load_library(ctx.root)
    if sid not in forks.fork_points(campaign, library):
        return fail(f"{sid} is not a fork point of the campaign.")
    if pr.run_conclusion is None:
        return GateResult(
            "pending", _short(f"{label}: waiting for the ideation run to finish"), (), cid, sid
        )
    failures: list[str] = []
    if pr.run_conclusion != "success":
        failures.append(f"the ideation run ended '{pr.run_conclusion}'")
    if not pr.files:
        failures.append("the pull request changes no files")
    folder = f"{campaign.folder}/forks/"
    not_added = [p for p, s in pr.changes if s != "added"]
    if not_added:
        failures.append(f"a fork plan only adds files; it changes {not_added[:5]}")
    outside = [p for p in pr.files if not p.startswith(folder)]
    if outside:
        failures.append(f"files outside {folder}: {outside[:5]}")
    overlay = dict(pr.added_texts)
    unread = [p for p in pr.files if p not in overlay]
    if unread and not outside:
        failures.append(f"files the gate could not read: {unread[:5]}")
    if not failures:
        on_main = {f.id for f in campaign.fork_files}
        fids = sorted({p[len(folder) :].split("/")[0].removesuffix(".md") for p in pr.files})
        again = [f for f in fids if f in on_main]
        if again:
            failures.append(f"forks already on main: {again} (fork files are append-only)")
        c2 = parse_campaign(ctx.root, ctx.root / campaign.folder, overlay)
        problems = list(c2.problems) + forks.check(ctx.root, c2, ctx.codeowners, overlay)
        if problems:
            failures.append(f"the fork checks refuse it: {problems[0]}")
        new = [f for f in c2.fork_files if f.id in fids]
        if not problems and any(f.parent_step != sid for f in new):
            failures.append(f"a fork in it is not at {sid}")
        if not problems and not new:
            failures.append("it adds no fork file")
        failures += problems[1:4]
    return _checks_ci(pr, label, failures, cid, sid)


def _checks_ci(pr: PullRequest, label: str, failures: list[str], cid: str, sid: str) -> GateResult:
    """CI only (a fork plan holds no code, so there is no agent review)."""
    pending: list[str] = []
    if pr.ci_test is None:
        pending.append("waiting for CI's test check on the head commit")
    elif pr.ci_test != "success":
        failures.append(f"CI's test check is '{pr.ci_test}' on the head commit")
    if failures:
        return GateResult(
            "failure", _short(f"{label}: {failures[0]}"), tuple(failures + pending), cid, sid
        )
    if pending:
        return GateResult("pending", _short(f"{label}: {pending[0]}"), tuple(pending), cid, sid)
    return GateResult("success", _short(f"{label}: every check passes."), (), cid, sid)


def _expected_issue(campaign: Campaign, step, pr: PullRequest, ctx: GateContext) -> str:
    """Why the issue is not what the tick files for this step ("" if it is).

    A fork's task: its draft, with the fork marker. A step a fork adopted: the
    approved draft plus the fork's delta section (F9). Any other: its draft.
    """
    draft_path = ctx.root / step.draft
    if not draft_path.is_file():
        return f"draft {step.draft} is not on main"
    title, body = markers.draft_body(draft_path.read_text(encoding="utf-8"))
    adopted = markers.parse_adopted(pr.issue_body)
    if step.fork and markers.parse_fork(pr.issue_body) != (campaign.id, step.fork):
        return f"the issue of fork step {step.id} does not carry the marker of fork {step.fork}"
    if adopted:
        acid, asid, fid = adopted
        fork = campaign.fork(fid)
        if (
            acid != campaign.id
            or asid != step.id
            or step.fork
            or fork is None
            or not fork.adopts_downstream
            or fork.parent_verdict != "killed"
            or step.id not in forks.adoptable(campaign, fork.parent_step)
        ):
            return f"the issue says fork {fid} adopted step {step.id}, which it may not (F9)"
        body = f"{body}\n\n{markers.delta_section(fid, fork.delta)}"
    if markers.strip_marker(pr.issue_body) != body or pr.issue_title != title:
        extra = " plus the fork's delta" if adopted else ""
        return f"the issue no longer matches its approved draft {step.draft}{extra}"
    return ""


def evaluate(pr: PullRequest, ctx: GateContext) -> GateResult:
    edits = fork_edits(pr)
    if edits and pr.author != ctx.repo_owner:
        return GateResult(
            "failure",
            _short(f"Fork files are append-only (decision 0015, F2); this changes {edits[:3]}."),
            tuple(edits),
        )
    if pr.author != ctx.app_bot:
        return GateResult("success", "Not an agent pull request; its author merges it.")
    if pr.state != "open":
        return GateResult("failure", "The pull request is not open.")
    m_fork = FORK_BRANCH.match(pr.head_ref)
    if m_fork:
        return _fork_plan(pr, ctx, m_fork.group(1), m_fork.group(2))

    kind, cid, sid = "", "", ""
    run_id = ""
    m_task, m_rec, m_man = (
        TASK_BRANCH.match(pr.head_ref),
        RECORD_BRANCH.match(pr.head_ref),
        MANIFEST_BRANCH.match(pr.head_ref),
    )
    if m_task:
        step = markers.parse_step(pr.issue_body)
        closeout = markers.parse_closeout(pr.issue_body)
        fixing = markers.parse_repair(pr.issue_body)
        if step:
            kind, (cid, sid) = "task", step
        elif closeout:
            kind, cid = "closeout", closeout
        elif fixing:
            return _repair(pr, ctx, *fixing)
    elif m_rec or m_man:
        run_id = m_rec.group(2) if m_rec else m_man.group(3)
        found = markers.parse_run_title(pr.run_title)
        if found:
            kind = "record" if m_rec else "manifest"
            cid, sid = found
    if not kind:
        return _outside(pr, ctx, "Agent pull request outside a campaign")
    campaign = next((c for c in ctx.campaigns if c.id == cid), None)
    if campaign is None:
        return _outside(pr, ctx, f"Campaign {cid} is not active")

    failures: list[str] = []
    pending: list[str] = []
    if not pr.files:
        failures.append("the pull request changes no files")

    if kind == "closeout":
        allowed = closeout_paths(campaign, ctx.root)
        outside = [f for f in pr.files if f not in allowed]
        if outside:
            failures.append(f"files outside the close-out list: {outside[:5]}")
    else:
        step = campaign.step(sid)
        expected = {"task": "task", "record": "explore_run", "manifest": "pipeline_run"}[kind]
        if step is None or step.kind != expected:
            return GateResult(
                "failure",
                _short(f"Campaign {cid} has no {expected} step {sid}."),
                campaign=cid,
                step=sid,
            )
        if kind == "task":
            allowed_files = step.allowed_paths
            bad = [f for f in pr.files if not path_allowed(f, allowed_files)]
            if bad:
                failures.append(f"files outside step {sid}'s allowed paths: {bad[:5]}")
            mismatch = _expected_issue(campaign, step, pr, ctx)
            if mismatch:
                failures.append(mismatch)
        elif kind == "record":
            script = m_rec.group(1)
            if script != step.script:
                failures.append(f"the run is of {script}, but step {sid} runs {step.script}")
            idea = script[:4]
            allowed_files = (
                f"research/explore-runs/{idea}/{run_id}.md",
                f"research/explore-runs/{idea}/{run_id}.json",
            )
            bad = [f for f in pr.files if f not in allowed_files]
            if bad:
                failures.append(
                    f"a record PR may change only its record (.md and .json), not {bad[:5]}"
                )
        else:
            stage, target = m_man.group(1), m_man.group(2)
            if (stage, target) != (step.stage, step.target):
                failures.append(
                    f"the run is {stage} {target}, but step {sid} runs {step.stage} {step.target}"
                )
            manifest = f"data/manifests/{stage}/{target}.json"
            bad = [f for f in pr.files if f != manifest]
            if bad:
                failures.append(f"a manifest PR may change only {manifest}, not {bad[:5]}")
        if kind != "manifest":
            prot = [f for f in pr.files if is_protected(f)]
            if prot:
                failures.append(f"protected paths: {prot[:5]}")
        owned = [f for f in pr.files if ctx.codeowners.owned(f)]
        if owned:
            failures.append(f"paths owned in CODEOWNERS, which only a person merges: {owned[:5]}")
        if kind in ("record", "manifest") and pr.run_conclusion != "success":
            failures.append(f"the run that made this record ended '{pr.run_conclusion}'")

    if pr.ci_test is None:
        pending.append("waiting for CI's test check on the head commit")
    elif pr.ci_test != "success":
        failures.append(f"CI's test check is '{pr.ci_test}' on the head commit")

    if kind in ("task", "closeout"):
        review = pr.review_of_head()
        if review is None:
            pending.append(f"waiting for an agent review of {pr.head_sha[:12]}")
        elif review.verdict != "approve":
            pending.append("the agent review asked for changes (fix rounds run on their own)")
        elif kind == "task":
            step = campaign.step(sid)
            na_ok = set(campaign.referee_not_applicable_ok)
            rows = ("R1", "R2", "R3", "R4", "R5", "R6", "R7") if step.type == "explore" else ()
            for rid in rows:
                status = review.referee.get(rid, "Not checked")
                if status == "OK" or (status == "Not applicable" and rid in na_ok):
                    continue
                failures.append(f"referee {rid} is '{status}'")
            if step.fork:
                # R8, fork discipline: always required, never "Not applicable" (F5, F6)
                status = review.referee.get("R8", "Not checked")
                if status != "OK":
                    failures.append(f"referee R8 (fork discipline) is '{status}'")

    label = f"Campaign {cid}" + (f" step {sid}" if sid else " close-out")
    if failures:
        return GateResult(
            "failure", _short(f"{label}: {failures[0]}"), tuple(failures + pending), cid, sid
        )
    if pending:
        return GateResult("pending", _short(f"{label}: {pending[0]}"), tuple(pending), cid, sid)
    if kind == "closeout":
        return GateResult(
            "success",
            _short(f"{label}: checks pass; @{campaign.owner} reviews and merges it."),
            (),
            cid,
            sid,
        )
    return GateResult("success", _short(f"{label}: every check passes."), (), cid, sid)
