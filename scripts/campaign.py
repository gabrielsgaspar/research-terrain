"""Campaign commands for people and workflows.

    uv run python scripts/campaign.py validate
        Check every campaign file; one line per problem, exit 1 if any.
    uv run python scripts/campaign.py status
        Print each campaign and its steps (offline; reads only the files).
    uv run python scripts/campaign.py card 0007
        Print the approval card for one campaign: one Markdown page, built by
        code from its files, of what approving it means (offline).
    uv run python scripts/campaign.py gate --pr N --out gate.json
        Evaluate the campaign gate for pull request N (reads GitHub).
    uv run python scripts/campaign.py gate --branch B --sha S --out gate.json
        The same, for the open pull request whose head is B at commit S.
    uv run python scripts/campaign.py decide --out actions.json
        The tick: work out this run's actions for every active campaign,
        and the status page's.
    GH_TOKEN=$(gh auth token) uv run python scripts/campaign.py page
        Print the status page as the tick would write it now (reads GitHub).

The GitHub commands read GITHUB_REPOSITORY, GH_TOKEN (read-only is enough),
AGENT_APP_BOT (the agent App's login, e.g. terrain-agent[bot]) and, for
decide, CAMPAIGNS_ENABLED (`true` to run). They never write to GitHub. For
`page` on your own machine, GITHUB_REPOSITORY defaults to the `origin`
remote, AGENT_APP_BOT to terrain-agent[bot] and the API to github.com.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from terrain.campaigns.card import CardError, render_card  # noqa: E402
from terrain.campaigns.codeowners import CodeOwners  # noqa: E402
from terrain.campaigns.gate import GateContext, evaluate  # noqa: E402
from terrain.campaigns.spec import (  # noqa: E402
    active_campaigns,
    finished_campaigns,
    load_campaigns,
    validate,
)
from terrain.campaigns.tick import decide, render_status_page  # noqa: E402

LOCAL_APP_BOT = "terrain-agent[bot]"  # the login agent-review.yml names as APP_BOT
PAGE_COMMAND = "uv run python scripts/campaign.py page"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _context(root: Path) -> GateContext:
    repo = _env("GITHUB_REPOSITORY")
    return GateContext(
        app_bot=_env("AGENT_APP_BOT"),
        repo_owner=repo.split("/")[0],
        campaigns=tuple(active_campaigns(root)),
        codeowners=CodeOwners.from_repo(root),
        root=root,
    )


def cmd_validate(root: Path) -> int:
    problems = validate(root) + list(CodeOwners.from_repo(root).problems)
    for p in problems:
        print(p)
    if not problems:
        print(f"{len(load_campaigns(root))} campaign(s), no problems.")
    return 1 if problems else 0


def cmd_status(root: Path) -> int:
    for c in load_campaigns(root):
        print(f"{c.id} {c.status:8} idea {c.idea}  {c.title}  (ends {c.end_by})")
        for s in c.steps:
            what = s.draft or s.script or f"{s.stage} {s.target}"
            after = f" after {','.join(s.after)}" if s.after else ""
            print(f"    {s.id} {s.kind:12} {what}{after}")
    return 0


def cmd_card(root: Path, campaign_id: str) -> int:
    try:
        print(render_card(root, campaign_id), end="")
    except CardError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def cmd_gate(root: Path, args: argparse.Namespace) -> int:
    from terrain.campaigns.github import GitHub

    gh = GitHub(_env("GITHUB_REPOSITORY"))
    if args.pr:
        pr = gh.pull_request(int(args.pr))
    else:
        found = gh.pr_for_branch(args.branch)
        if found is None or found.state != "open" or found.head_sha != args.sha:
            print("No open pull request with that head; nothing to do.")
            Path(args.out).write_text(json.dumps({"skip": True}), encoding="utf-8")
            return 0
        pr = found
    result = evaluate(pr, _context(root))
    out = {
        "skip": False,
        "pr": pr.number,
        "sha": pr.head_sha,
        "state": result.state,
        "description": result.description,
        "details": list(result.details),
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"PR #{pr.number} at {pr.head_sha[:12]}: {result.state}: {result.description}")
    for d in result.details:
        print(f"  - {d}")
    return 0


def _snapshot(root: Path, ctx: GateContext, enabled: bool):  # noqa: ANN202 (a Snapshot)
    from terrain.campaigns.github import GitHub, safe_snapshot

    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    campaigns = list(ctx.campaigns)
    # Runs matter only to active campaigns; with none, read only today's.
    since = min(c.created for c in campaigns) if campaigns else now[:10]
    repo = _env("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "").strip() or "https://github.com"
    # Failed runs' log lines, for repair tasks (decision 0014): self_repair campaigns only.
    repairs = frozenset(c.id for c in campaigns if c.self_repair)
    return safe_snapshot(
        GitHub(repo),
        now=now,
        enabled=enabled,
        app_bot=ctx.app_bot,
        since=since,
        root=root,
        log_campaigns=repairs,
        repo_url=f"{server.rstrip('/')}/{repo}",
    )


def cmd_decide(root: Path, args: argparse.Namespace) -> int:
    ctx = _context(root)
    enabled = os.environ.get("CAMPAIGNS_ENABLED", "").strip() == "true"
    campaigns = list(ctx.campaigns)
    finished = finished_campaigns(root)
    actions: list[dict] = []
    if (campaigns or finished) and enabled:
        snap = _snapshot(root, ctx, enabled)
        actions = decide(campaigns, snap, ctx, root, finished, status_page=True)
    elif not enabled:
        print("CAMPAIGNS_ENABLED is not 'true': nothing to do.")
    else:
        problems = validate(root)
        print(
            "No active campaign." if not problems else "Campaign files have problems; nothing runs:"
        )
        for p in problems:
            print(f"  - {p}")
    Path(args.out).write_text(json.dumps(actions, indent=2), encoding="utf-8")
    print(f"{len(actions)} action(s).")
    for a in actions:
        target = a.get("issue") or a.get("pr") or a.get("workflow") or a.get("title", "")
        print(f"  - {a['type']}: {target}")
    return 0


def _origin_repo(root: Path) -> str:
    """owner/name of the `origin` remote, or "" if there is none."""
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def cmd_page(root: Path) -> int:
    """Print the status page for the repository as it is now (local reading)."""
    defaults = {
        "GITHUB_REPOSITORY": _origin_repo(root),
        "AGENT_APP_BOT": LOCAL_APP_BOT,
        "GITHUB_API_URL": "https://api.github.com",
    }
    for name, value in defaults.items():
        if not os.environ.get(name, "").strip() and value:
            os.environ[name] = value
    if not os.environ.get("GH_TOKEN", "").strip():
        print("GH_TOKEN is not set. Run: GH_TOKEN=$(gh auth token) " + PAGE_COMMAND)
        return 1
    ctx = _context(root)
    snap = _snapshot(root, ctx, enabled=True)
    print(render_status_page(list(ctx.campaigns), snap, ctx, root, finished_campaigns(root)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    sub.add_parser("status")
    k = sub.add_parser("card")
    k.add_argument("id", help="the campaign number, such as 0007")
    g = sub.add_parser("gate")
    g.add_argument("--pr")
    g.add_argument("--branch")
    g.add_argument("--sha")
    g.add_argument("--out", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--out", required=True)
    sub.add_parser("page")
    args = parser.parse_args(argv)
    root = REPO
    if args.cmd == "validate":
        return cmd_validate(root)
    if args.cmd == "status":
        return cmd_status(root)
    if args.cmd == "card":
        return cmd_card(root, args.id)
    if args.cmd == "page":
        return cmd_page(root)
    if args.cmd == "gate":
        if not args.pr and not (args.branch and args.sha):
            parser.error("gate needs --pr, or --branch and --sha")
        return cmd_gate(root, args)
    return cmd_decide(root, args)


if __name__ == "__main__":
    sys.exit(main())
