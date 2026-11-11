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

Code-owner review (CODEOWNERS plus the ruleset) is a second, separate lock:
the App cannot merge an owned path even if the gate said success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from terrain.campaigns import markers
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import PullRequest
from terrain.campaigns.spec import NOTES_PATH, Campaign, is_protected, path_allowed

TASK_BRANCH = re.compile(r"^agent/issue-(\d+)$")
RECORD_BRANCH = re.compile(r"^explore/(\d{4}_[a-z0-9_]{1,60})-(\d+)$")
MANIFEST_BRANCH = re.compile(r"^data/(acquire|build)-([a-z][a-z0-9_]{0,63})-(\d+)$")


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
        "research/INDEX.md",
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


def evaluate(pr: PullRequest, ctx: GateContext) -> GateResult:
    if pr.author != ctx.app_bot:
        return GateResult("success", "Not an agent pull request; its author merges it.")
    if pr.state != "open":
        return GateResult("failure", "The pull request is not open.")

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
        if step:
            kind, (cid, sid) = "task", step
        elif closeout:
            kind, cid = "closeout", closeout
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
            draft_path = ctx.root / step.draft
            if not draft_path.is_file():
                failures.append(f"draft {step.draft} is not on main")
            else:
                title, body = markers.draft_body(draft_path.read_text(encoding="utf-8"))
                if markers.strip_marker(pr.issue_body) != body or pr.issue_title != title:
                    failures.append(f"the issue no longer matches its approved draft {step.draft}")
        elif kind == "record":
            script = m_rec.group(1)
            if script != step.script:
                failures.append(f"the run is of {script}, but step {sid} runs {step.script}")
            idea = script[:4]
            allowed_files = (
                f"research/explore-runs/{idea}/{run_id}.md",
                f"research/explore-runs/{idea}/{run_id}.json",
                "research/INDEX.md",
            )
            bad = [f for f in pr.files if f not in allowed_files]
            if bad:
                failures.append(
                    f"a record PR may change only its record and the index, not {bad[:5]}"
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
        elif kind == "task" and campaign.step(sid).type == "explore":
            na_ok = set(campaign.referee_not_applicable_ok)
            for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
                status = review.referee.get(rid, "Not checked")
                if status == "OK" or (status == "Not applicable" and rid in na_ok):
                    continue
                failures.append(f"referee {rid} is '{status}'")

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
