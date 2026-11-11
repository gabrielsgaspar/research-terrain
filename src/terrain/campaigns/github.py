"""The one module that talks to GitHub: reads facts for the gate and the tick.

Read-only. It uses the token in GH_TOKEN (the workflow's GITHUB_TOKEN with
read scopes), the API address in GITHUB_API_URL (set on every Actions
runner; code here holds no URL, as tests/test_acquire.py requires) and the
standard library only. Nothing here writes to GitHub:
the gate workflow posts its status with a fixed `gh api` call, and the tick's
actions are carried out by a separate job that runs no repository code.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from terrain.campaigns import markers
from terrain.campaigns.facts import (
    Comment,
    Issue,
    PullRequest,
    Run,
    Snapshot,
    parse_review,
)
from terrain.campaigns.gate import MANIFEST_BRANCH, RECORD_BRANCH, TASK_BRANCH

_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
REVIEW_BOT = "github-actions[bot]"
LOG_TAIL_BYTES = 64 * 1024  # of a job log, kept while reading; the rest is dropped
LOG_TAIL_LINES = 200
FAILED = ("failure", "timed_out")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirects as errors, so the token is never sent to the address they name."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


class GitHub:
    def __init__(self, repo: str, token: str | None = None, api: str | None = None) -> None:
        self.repo = repo
        self.token = token if token is not None else os.environ.get("GH_TOKEN", "")
        self.api = (api if api is not None else os.environ.get("GITHUB_API_URL", "")).rstrip("/")
        if not self.api:
            raise RuntimeError("GITHUB_API_URL is not set (Actions sets it on every runner)")

    def _request(self, url: str) -> tuple[Any, str]:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https host)
            link = resp.headers.get("Link", "")
            return json.loads(resp.read().decode("utf-8") or "null"), link

    def _text_tail(self, url: str) -> str:
        """The end of a plain-text download, such as a job log.

        GitHub answers a log request with a redirect to a short-lived storage
        address that carries its own signature; that address is read without
        the token. Only the last LOG_TAIL_BYTES are kept.
        """
        req = urllib.request.Request(url)
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "") if exc.code in (301, 302, 307) else ""
            if urllib.parse.urlsplit(location).scheme != "https":
                raise
            resp = urllib.request.urlopen(location, timeout=60)  # noqa: S310 (https only)
        tail = b""
        with resp:
            while chunk := resp.read(LOG_TAIL_BYTES):
                tail = (tail + chunk)[-LOG_TAIL_BYTES:]
        lines = tail.decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-LOG_TAIL_LINES:])

    def failed_job_log(self, run_id: int) -> str:
        """The last lines the failed job of run `run_id` printed ("" if none failed)."""
        jobs = self.get(f"/actions/runs/{run_id}/jobs", filter="latest", per_page=100)
        jobs = (jobs or {}).get("jobs", [])
        job = next((j for j in jobs if j.get("conclusion") == "failure"), None) or next(
            (j for j in jobs if j.get("conclusion") in ("timed_out", "cancelled")), None
        )
        if job is None:
            return ""
        return self._text_tail(f"{self.api}/repos/{self.repo}/actions/jobs/{job['id']}/logs")

    def get(self, path: str, **params: Any) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data, _ = self._request(f"{self.api}/repos/{self.repo}{path}{query}")
        return data

    def pages(self, path: str, key: str | None = None, limit: int = 10, **params: Any) -> list:
        """Every item of a paginated list (at most `limit` pages of 100)."""
        params.setdefault("per_page", 100)
        url = f"{self.api}/repos/{self.repo}{path}?{urllib.parse.urlencode(params)}"
        out: list = []
        for _ in range(limit):
            data, link = self._request(url)
            out.extend(data[key] if key else data)
            m = _NEXT.search(link or "")
            if not m:
                break
            url = m.group(1)
        return out

    # -- pull requests -------------------------------------------------------

    def comments(self, number: int) -> tuple[Comment, ...]:
        raw = self.pages(f"/issues/{number}/comments")
        return tuple(Comment(c["user"]["login"], c.get("body") or "", c["created_at"]) for c in raw)

    def pull_request(self, number: int, with_issue: bool = True) -> PullRequest:
        pr = self.get(f"/pulls/{number}")
        head_ref, head_sha = pr["head"]["ref"], pr["head"]["sha"]
        files = tuple(f["filename"] for f in self.pages(f"/pulls/{number}/files", limit=5))
        checks = self.get(f"/commits/{head_sha}/check-runs", check_name="test").get(
            "check_runs", []
        )
        ci = None
        if checks:
            newest = max(checks, key=lambda c: c.get("id", 0))  # a re-run replaces older runs
            if newest.get("status") == "completed":
                ci = newest.get("conclusion")
        statuses = self.pages(f"/commits/{head_sha}/statuses", limit=1)
        gate = next((s["state"] for s in statuses if s.get("context") == "campaign-gate"), None)
        reviews = tuple(
            r
            for c in self.comments(number)
            if c.author == REVIEW_BOT
            for r in [parse_review(c.body, c.created_at)]
            if r is not None
        )
        latest: dict[str, str] = {}
        for rv in self.pages(f"/pulls/{number}/reviews", limit=3):
            if rv.get("commit_id") == head_sha and rv.get("state") in (
                "APPROVED",
                "CHANGES_REQUESTED",
            ):
                latest[rv["user"]["login"]] = rv["state"]
        approvals = tuple(sorted(u for u, s in latest.items() if s == "APPROVED"))
        issue_body = issue_title = run_title = ""
        run_conclusion = None
        m = TASK_BRANCH.match(head_ref)
        if m and with_issue:
            issue = self.get(f"/issues/{m.group(1)}")
            issue_body, issue_title = issue.get("body") or "", issue.get("title") or ""
        m = RECORD_BRANCH.match(head_ref) or MANIFEST_BRANCH.match(head_ref)
        if m:
            run = self.get(f"/actions/runs/{m.group(m.lastindex)}")
            run_title, run_conclusion = run.get("display_title", ""), run.get("conclusion")
        return PullRequest(
            number=number,
            author=pr["user"]["login"],
            head_ref=head_ref,
            head_sha=head_sha,
            state=pr["state"],
            merged=bool(pr.get("merged")),
            mergeable=pr.get("mergeable"),
            files=files,
            ci_test=ci,
            gate_status=gate,
            labels=tuple(lb["name"] for lb in pr.get("labels", [])),
            reviews=reviews,
            approvals=approvals,
            issue_body=issue_body,
            issue_title=issue_title,
            run_title=run_title,
            run_conclusion=run_conclusion,
            created_at=pr.get("created_at", ""),
            merged_at=pr.get("merged_at") or "",
        )

    def pr_for_branch(self, branch: str) -> PullRequest | None:
        owner = self.repo.split("/")[0]
        found = self.get("/pulls", state="all", head=f"{owner}:{branch}", per_page=10)
        if not found:
            return None
        newest = max(found, key=lambda p: p["number"])
        return self.pull_request(newest["number"])

    # -- the tick's snapshot -------------------------------------------------

    def runs(self, workflow: str, created_since: str) -> list[Run]:
        raw = self.pages(
            f"/actions/workflows/{workflow}/runs",
            key="workflow_runs",
            limit=3,
            event="workflow_dispatch",
            created=f">={created_since}",
        )
        return [
            Run(
                r["id"],
                workflow,
                r.get("display_title", ""),
                r["status"],
                r.get("conclusion"),
                r["created_at"],
                r.get("updated_at", ""),
            )
            for r in raw
        ]

    def run_logs(self, runs: list[Run], campaigns: frozenset[str]) -> dict[int, str]:
        """Log tails of failed data-pipeline runs of `campaigns`: the newest run of each
        step, when it failed. A log that cannot be read gives ""."""
        newest: dict[str, Run] = {}
        for r in runs:
            found = markers.parse_run_title(r.title)
            if r.workflow == "data-pipeline.yml" and found and found[0] in campaigns:
                if r.title not in newest or r.created_at > newest[r.title].created_at:
                    newest[r.title] = r
        logs: dict[int, str] = {}
        for r in newest.values():
            if r.status != "completed" or r.conclusion not in FAILED:
                continue
            try:
                logs[r.id] = self.failed_job_log(r.id)
            except (OSError, ValueError):  # HTTP and network errors, a bad answer
                logs[r.id] = ""
        return logs

    def snapshot(
        self,
        now: str,
        enabled: bool,
        app_bot: str,
        since: str,
        root: Path,
        log_campaigns: frozenset[str] = frozenset(),
    ) -> Snapshot:
        issues: list[Issue] = []
        for raw in self.pages("/issues", state="all", labels="campaign"):
            if "pull_request" in raw:
                continue
            number = raw["number"]
            pr = self.pr_for_branch(f"agent/issue-{number}")
            issues.append(
                Issue(
                    number=number,
                    title=raw.get("title") or "",
                    body=raw.get("body") or "",
                    state=raw["state"],
                    labels=tuple(lb["name"] for lb in raw.get("labels", [])),
                    author=raw["user"]["login"],
                    created_at=raw["created_at"],
                    comments=self.comments(number),
                    pr=pr,
                )
            )
        runs = self.runs("explore-run.yml", since) + self.runs("data-pipeline.yml", since)
        record_prs: dict[int, PullRequest] = {}
        for r in runs:
            if r.status != "completed" or r.conclusion != "success" or " campaign " not in r.title:
                continue
            if r.workflow == "explore-run.yml":
                script = r.title.split(" ")[1]
                branch = f"explore/{script}-{r.id}"
            else:
                parts = r.title.split(" ")  # Data pipeline <stage> <target> campaign ...
                branch = f"data/{parts[2]}-{parts[3]}-{r.id}"
            pr = self.pr_for_branch(branch)
            if pr:
                record_prs[r.id] = pr
        results: dict[str, object] = {}
        runs_dir = root / "research" / "explore-runs"
        for path in sorted(runs_dir.glob("*/*.json")) if runs_dir.is_dir() else []:
            try:
                results[path.relative_to(root).as_posix()] = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except ValueError:
                continue
        on_main = (
            frozenset(
                p.relative_to(root).as_posix()
                for p in (root / "data" / "manifests").rglob("*.json")
            )
            if (root / "data" / "manifests").is_dir()
            else frozenset()
        )
        logs = self.run_logs(runs, log_campaigns) if log_campaigns else {}
        return Snapshot(now, enabled, app_bot, issues, runs, record_prs, results, on_main, logs)


def safe_snapshot(gh: GitHub, **kw: Any) -> Snapshot:
    """`snapshot`, turning HTTP errors into a clear exception message."""
    try:
        return gh.snapshot(**kw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API error {exc.code} on {exc.url}") from exc
