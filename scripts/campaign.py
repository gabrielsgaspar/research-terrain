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
    uv run python scripts/campaign.py ideation-context --campaign 0007 --step s15 --out DIR
        Write the page the ideation model reads first for that fork point (offline).
    uv run python scripts/campaign.py forks-from-json --campaign 0007 --step s15 \
            --run-id N --in answer.json --out DIR [--dry-run] [--run-url URL]
        Turn the ideation job's answer into fork files that pass every check
        (written into the checkout, unless --dry-run), and write DIR/result.json,
        DIR/comment.md and DIR/pr-body.md (offline; decision 0015). With
        --dry-run a campaign without a `forks:` block gets the default envelope.

The GitHub commands read GITHUB_REPOSITORY, GH_TOKEN (read-only is enough),
AGENT_APP_BOT (the agent App's login, e.g. terrain-agent[bot]) and, for
decide, CAMPAIGNS_ENABLED (`true` to run). They never write to GitHub. Each
prints how much of GitHub's request allowance is left (the gate also writes
it to the run's summary). When GitHub says a rate limit was reached, the gate
posts `pending` (or nothing, if it could not read the pull request's head)
and the tick does nothing this run; both try again later, and exit 0. For
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


RATE_PENDING = "GitHub's API rate limit was reached; the gate checks again within the hour."


def _summary(line: str) -> None:
    """Print a line, and add it to the run's summary when there is one (Actions)."""
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{line}\n\n")


def cmd_gate(root: Path, args: argparse.Namespace) -> int:
    from terrain.campaigns.github import GitHub, RateLimited

    gh = GitHub(_env("GITHUB_REPOSITORY"))
    try:
        if args.pr:
            pr = gh.pull_request(int(args.pr))
        else:
            found = gh.pr_for_branch(args.branch)
            if found is None or found.state != "open" or found.head_sha != args.sha:
                print("No open pull request with that head; nothing to do.")
                Path(args.out).write_text(json.dumps({"skip": True}), encoding="utf-8")
                _summary(gh.rate.line())
                return 0
            pr = found
    except RateLimited as exc:
        # Pending needs the head commit: from --sha, or from the pull request if it
        # was read before the limit. Without it nothing is posted, and the hourly
        # sweep evaluates the pull request again.
        number, sha = gh.seen_head or (int(args.pr or 0), args.sha or "")
        sha = sha if re.fullmatch(r"[0-9a-f]{40}", sha or "") else ""
        out = (
            {
                "skip": False,
                "pr": number,
                "sha": sha,
                "state": "pending",
                "description": RATE_PENDING,
                "details": [],
            }
            if sha
            else {"skip": True}
        )
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        _summary(f"{exc}. " + ("Posting pending." if sha else "Nothing is posted this run."))
        _summary(gh.rate.line())
        return 0
    _summary(gh.rate.line())
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
    # Failed data-pipeline runs' log lines: every campaign reads them for "still
    # exporting" (an Earth Engine run started again without a retry); only
    # self_repair campaigns put them in repair tasks (decision 0014).
    logged = frozenset(c.id for c in campaigns)
    gh = GitHub(repo)
    try:
        return safe_snapshot(
            gh,
            now=now,
            enabled=enabled,
            app_bot=ctx.app_bot,
            since=since,
            root=root,
            log_campaigns=logged,
            repo_url=f"{server.rstrip('/')}/{repo}",
            active=logged,
            ended=frozenset(c.id for c in finished_campaigns(root)),
        )
    finally:
        print(gh.rate.line())


def cmd_decide(root: Path, args: argparse.Namespace) -> int:
    ctx = _context(root)
    enabled = os.environ.get("CAMPAIGNS_ENABLED", "").strip() == "true"
    campaigns = list(ctx.campaigns)
    finished = finished_campaigns(root)
    actions: list[dict] = []
    if (campaigns or finished) and enabled:
        from terrain.campaigns.github import RateLimited

        try:
            snap = _snapshot(root, ctx, enabled)
        except RateLimited as exc:
            # Nothing is decided from half a picture: no action this run.
            print(f"{exc}. This tick does nothing; the next one reads GitHub again.")
            snap = None
        if snap is not None:
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


def _ideation_campaign(root: Path, cid: str, sid: str, dry_run: bool):  # noqa: ANN202
    """(campaign, base overlay, problem) for an ideation command."""
    from terrain.campaigns import forks
    from terrain.campaigns.ideation import parent_verdict, with_envelope
    from terrain.campaigns.spec import parse_campaign

    if not re.fullmatch(r"\d{4}", cid) or not re.fullmatch(r"s\d{1,2}", sid):
        return None, {}, "campaign must look like 0007 and step like s15"
    found = [c for c in load_campaigns(root) if c.id == cid]
    if not found:
        return None, {}, f"no campaign {cid}"
    c, base = found[0], {}
    if dry_run and c.forks is None:
        base = with_envelope(root, c, forks.default_envelope())
        c = parse_campaign(root, root / c.folder, base)
    if c.problems:
        return None, {}, f"campaign {cid} has problems: {c.problems[0]}"
    if c.forks is None:
        return None, {}, f"campaign {cid} has no forks envelope"
    if not dry_run and c.status != "active":
        return None, {}, f"campaign {cid} is not active"
    if sid not in forks.fork_points(c, forks.load_library(root)):
        return None, {}, f"{sid} is not a fork point of campaign {cid}"
    _, verdict, _ = parent_verdict(root, c, sid)
    if verdict not in c.forks.on:
        return None, {}, f"{sid}'s verdict on record ({verdict or 'none'}) opens no fork point"
    return c, base, ""


def cmd_ideation_context(root: Path, args: argparse.Namespace) -> int:
    from terrain.campaigns.ideation import brief

    c, _, problem = _ideation_campaign(root, args.campaign, args.step, args.dry_run)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "point.md").write_text(brief(root, c, args.step, args.dry_run), encoding="utf-8")
    print(f"Wrote {out / 'point.md'}.")
    return 0


def cmd_forks_from_json(root: Path, args: argparse.Namespace) -> int:
    from terrain.campaigns.ideation import Built, build, comment

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c, base, problem = _ideation_campaign(root, args.campaign, args.step, args.dry_run)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    try:
        data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    b = build(root, c, args.step, data, base) if data is not None else None
    b = b or Built("none", "the ideation job returned no usable answer", 0)
    if not args.dry_run:
        for path, text in sorted(b.files.items()):
            target = root / path
            if target.exists():
                print(f"{path} exists already; fork files are append-only", file=sys.stderr)
                return 1
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    fids = [f for f, _, _ in b.written]
    text = comment(b, c, args.step, args.run_url, args.dry_run)
    (out / "comment.md").write_text(text, encoding="utf-8")
    title = f"Forks: campaign {c.id} step {args.step} ({', '.join(fids) or 'none'})"
    pr_body = (
        f"The ideation job for fork point {args.step} of campaign {c.id} (decision 0015). "
        "Code wrote every file from its answer and checked each against the envelope; the "
        "campaign gate checks them again, and the tick merges this when it passes.\n\n" + text
    )
    (out / "pr-body.md").write_text(pr_body, encoding="utf-8")
    result = {
        "decision": b.decision,
        "proposed": b.proposed,
        "refused": len(b.refused),
        "forks": fids,
        "files": sorted(b.files),
        "branch": f"forks/{c.id}-{args.step}-{args.run_id}",
        "title": title,
        "dry_run": bool(args.dry_run),
    }
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(text)
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
    i = sub.add_parser("ideation-context")
    i.add_argument("--campaign", required=True)
    i.add_argument("--step", required=True)
    i.add_argument("--out", required=True)
    i.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("forks-from-json")
    f.add_argument("--campaign", required=True)
    f.add_argument("--step", required=True)
    f.add_argument("--run-id", required=True)
    f.add_argument("--in", dest="inp", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--run-url", default="")
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
    if args.cmd == "ideation-context":
        return cmd_ideation_context(root, args)
    if args.cmd == "forks-from-json":
        if not re.fullmatch(r"\d{1,20}", args.run_id):
            parser.error("--run-id must be a run number")
        return cmd_forks_from_json(root, args)
    if args.cmd == "gate":
        if not args.pr and not (args.branch and args.sha):
            parser.error("gate needs --pr, or --branch and --sha")
        return cmd_gate(root, args)
    return cmd_decide(root, args)


if __name__ == "__main__":
    sys.exit(main())
