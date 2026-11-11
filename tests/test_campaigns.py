"""Campaigns: the spec validator, kill rules, CODEOWNERS, the gate and the tick.

Every test builds a small repository in tmp_path and hand-made GitHub facts.
Nothing here calls the network.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from terrain.campaigns import markers
from terrain.campaigns.closeout import REPORT_OPENING, REPORT_SECTIONS, number_word
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import Comment, Issue, PullRequest, Review, Run, Snapshot, parse_review
from terrain.campaigns.gate import GateContext, evaluate
from terrain.campaigns.rules import evaluate as apply_rules
from terrain.campaigns.spec import (
    KillRule,
    active_campaigns,
    finished_campaigns,
    load_campaigns,
    path_allowed,
    validate,
)
from terrain.campaigns.tick import (
    NEEDS_YOU,
    NEEDS_YOU_DEFAULT,
    WORKFLOW_NAMES,
    block_id,
    decide,
)

REPO = Path(__file__).resolve().parents[1]
BOT = "terrain-agent[bot]"
OWNER = "gabrielsgaspar"
SHA = "a" * 40
NOW = "2026-11-10T12:00:00Z"

CODEOWNERS = """\
/.github/ @gabrielsgaspar
/AGENTS.md @gabrielsgaspar
/research/ideas/ @gabrielsgaspar
/research/campaigns/*/campaign.md @gabrielsgaspar
/research/campaigns/*/drafts/ @gabrielsgaspar
/src/terrain/campaigns/ @gabrielsgaspar
"""

DRAFT = """\
# Task: count close races (explore)

## Goal

Count them.

## Done when

1. `uv run pytest` passes.
"""


def campaign_text(**over) -> str:
    fields = {
        "status": "active",
        "end_by": "2026-11-20",
        "max_tasks": 1,
        "max_explore_runs": 1,
        "confirmed": "true",
        "on_kill": "skip_dependents",
        "extra_steps": "",
    }
    fields.update(over)
    return textwrap.dedent(
        """\
        ---
        id: "0001"
        title: "Count close races"
        status: {status}
        idea: "0003"
        owner: gabrielsgaspar
        created: 2026-11-08
        end_by: {end_by}
        budget:
          max_tasks: {max_tasks}
          max_explore_runs: {max_explore_runs}
          max_pipeline_runs: 0
          max_model_jobs: 10
        datasets: []
        steps:
          - id: s1
            kind: task
            type: explore
            draft: drafts/s1.md
            allowed_paths:
              - explore/0003_count.py
              - tests/test_explore_count.py
            after: []
          - id: s2
            kind: explore_run
            script: 0003_count
            after: [s1]
            kill_rules:
              - id: k1
                says: "Fewer than 60 races at 1%"
                field: races.1pct
                op: "<"
                value: 60
                confirmed: {confirmed}
            on_kill: {on_kill}
        {extra_steps}---

        # 0001: Count close races
        """
    ).format(**fields)


def make_repo(root: Path, text: str | None = None, draft: str = DRAFT) -> Path:
    (root / "research" / "ideas").mkdir(parents=True)
    (root / "research" / "ideas" / "0003-mayors.md").write_text(
        '---\nid: "0003"\n---\n', encoding="utf-8"
    )
    folder = root / "research" / "campaigns" / "0001-count"
    (folder / "drafts").mkdir(parents=True)
    (folder / "campaign.md").write_text(text or campaign_text(), encoding="utf-8")
    (folder / "drafts" / "s1.md").write_text(draft, encoding="utf-8")
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(CODEOWNERS, encoding="utf-8")
    (root / "explore").mkdir()
    return root


def ctx(root: Path) -> GateContext:
    return GateContext(BOT, OWNER, tuple(active_campaigns(root)), CodeOwners.from_repo(root), root)


def issue_body(root: Path) -> tuple[str, str]:
    title, body = markers.draft_body(
        (root / "research/campaigns/0001-count/drafts/s1.md").read_text(encoding="utf-8")
    )
    return title, f"{body}\n\n{markers.step_marker('0001', 's1')}\n"


REFEREE_OK = {f"R{i}": "OK" for i in range(1, 8)}


def task_pr(root: Path, **over) -> PullRequest:
    title, body = issue_body(root)
    base = dict(
        number=20,
        author=BOT,
        head_ref="agent/issue-10",
        head_sha=SHA,
        state="open",
        merged=False,
        mergeable=True,
        files=("explore/0003_count.py", "tests/test_explore_count.py"),
        ci_test="success",
        gate_status="success",
        reviews=(Review("approve", SHA[:12], dict(REFEREE_OK), NOW),),
        issue_body=body,
        issue_title=title,
    )
    base.update(over)
    return PullRequest(**base)


# -- the spec ----------------------------------------------------------------


def test_real_campaigns_validate():
    """Every campaign on this branch is valid (CI runs this on every PR)."""
    assert validate(REPO) == []
    assert CodeOwners.from_repo(REPO).problems == ()


def test_valid_campaign_has_no_problems(tmp_path):
    root = make_repo(tmp_path)
    assert validate(root) == []
    (c,) = load_campaigns(root)
    assert c.id == "0001" and [s.id for s in c.steps] == ["s1", "s2"]
    assert active_campaigns(root) == [c]


@pytest.mark.parametrize(
    "over, message",
    [
        ({"confirmed": "false"}, "is not confirmed by the owner"),
        ({"max_explore_runs": 0}, "budget.max_explore_runs is 0 but the campaign lists 1"),
        ({"end_by": "2026-11-01"}, "'end_by' is before 'created'"),
        ({"end_by": "2026-12-31"}, "at most 31 days"),
        ({"on_kill": "explode"}, "on_kill must be one of"),
        ({"status": "running"}, "status must be one of"),
    ],
)
def test_each_problem_is_caught(tmp_path, over, message):
    root = make_repo(tmp_path, campaign_text(**over))
    problems = validate(root)
    assert any(message in p for p in problems), problems
    assert active_campaigns(root) == []


def test_protected_and_owned_paths_are_refused(tmp_path):
    text = campaign_text().replace("- tests/test_explore_count.py", "- AGENTS.md")
    problems = validate(make_repo(tmp_path, text))
    assert any("'AGENTS.md' is protected" in p for p in problems)
    text = (
        campaign_text()
        .replace("type: explore", "type: build")
        .replace("- tests/test_explore_count.py", "- src/terrain/campaigns/gate.py")
    )
    problems = validate(make_repo(tmp_path / "b", text))
    assert any("owned in CODEOWNERS" in p for p in problems)


def test_owned_paths_are_allowed_in_closed_campaigns(tmp_path):
    for status in ("done", "stopped"):
        text = (
            campaign_text(status=status)
            .replace("type: explore", "type: build")
            .replace("- tests/test_explore_count.py", "- src/terrain/campaigns/gate.py")
        )
        problems = validate(make_repo(tmp_path / status, text))
        assert not any("owned in CODEOWNERS" in p for p in problems), problems


def test_explore_task_paths_are_limited(tmp_path):
    text = campaign_text().replace("- tests/test_explore_count.py", "- src/terrain/count.py")
    problems = validate(make_repo(tmp_path, text))
    assert any("an explore task may change only" in p for p in problems)


def test_run_of_an_unwritten_script_is_refused(tmp_path):
    text = campaign_text().replace("script: 0003_count", "script: 0003_other")
    problems = validate(make_repo(tmp_path, text))
    assert any("neither exists nor is written by an earlier task step" in p for p in problems)


def test_draft_must_be_plain_and_complete(tmp_path):
    problems = validate(make_repo(tmp_path, draft="# Task: x\n\n<!-- hidden -->\n"))
    assert any("may not contain HTML comments" in p for p in problems)
    assert any("needs a '## Done when' section" in p for p in problems)


def test_two_active_campaigns_on_one_idea_are_refused(tmp_path):
    root = make_repo(tmp_path)
    other = root / "research" / "campaigns" / "0002-again"
    (other / "drafts").mkdir(parents=True)
    (other / "campaign.md").write_text(
        campaign_text().replace('id: "0001"', 'id: "0002"'), encoding="utf-8"
    )
    (other / "drafts" / "s1.md").write_text(DRAFT, encoding="utf-8")
    problems = validate(root)
    assert any("both active on idea 0003" in p for p in problems)
    assert any("share allowed paths" in p for p in problems)
    assert active_campaigns(root) == []


def test_template_parses(tmp_path):
    """TEMPLATE.md, with its placeholders filled, is a valid campaign."""
    text = (REPO / "research" / "campaigns" / "TEMPLATE.md").read_text(encoding="utf-8")
    text = text.replace('"NNNN"', '"0001"').replace("YYYY-MM-DD", "2026-11-08", 2)
    text = text.replace('idea: "0001"', 'idea: "0003"').replace("0001_example", "0003_example")
    root = make_repo(tmp_path, text)
    assert validate(root) == []


def sized_campaign(n_steps: int, created: str, reason: str | None = None) -> str:
    """A valid campaign of `n_steps` steps: one task, then explore runs of its script."""
    extra = "".join(
        f"  - id: s{i}\n    kind: explore_run\n    script: 0003_count\n    after: [s1]\n"
        '    kill_rules:\n      - id: k1\n        says: "Fewer than 60 races at 1%"\n'
        '        field: races.1pct\n        op: "<"\n        value: 60\n'
        "        confirmed: true\n"
        for i in range(3, n_steps + 1)
    )
    text = campaign_text(max_explore_runs=n_steps - 1, extra_steps=extra)
    text = text.replace("created: 2026-11-08", f"created: {created}")
    if reason is not None:
        text = text.replace("datasets: []", f'oversize_reason: "{reason}"\ndatasets: []')
    return text


@pytest.mark.parametrize(
    "n_steps, created, reason, flagged",
    [
        (9, "2026-11-12", None, True),
        (9, "2026-11-12", "   ", True),
        (9, "2026-11-12", "One acquire per year; splitting loses nothing but adds a PR", False),
        (19, "2026-11-10", None, False),
        (8, "2026-11-12", None, False),
    ],
)
def test_more_than_eight_steps_needs_a_reason(tmp_path, n_steps, created, reason, flagged):
    """From 2026-11-12, a campaign of more than 8 steps must say why in oversize_reason."""
    root = make_repo(tmp_path, sized_campaign(n_steps, created, reason))
    (c,) = load_campaigns(root)
    assert len(c.steps) == n_steps
    problems = validate(root)
    if flagged:
        assert any(f"{n_steps} steps" in p and "oversize_reason" in p for p in problems), problems
    else:
        assert problems == []


def test_path_allowed():
    assert path_allowed("explore/0003_a.py", ("explore/0003_a.py",))
    assert path_allowed("tests/test_explore_a.py", ("tests/test_explore_*.py",))
    assert not path_allowed("tests/sub/test_explore_a.py", ("tests/test_explore_*.py",))
    assert not path_allowed("explore/0003_b.py", ("explore/0003_a.py",))


# -- kill rules ----------------------------------------------------------------


def rule(op: str, value, field: str = "races.1pct") -> KillRule:
    return KillRule("k1", "x", field, op, value, True)


def test_rules_kill_survive_and_unreadable():
    results = {"races": {"1pct": 45}, "flag": True}
    assert apply_rules((rule("<", 60),), results).outcome == "killed"
    assert apply_rules((rule(">=", 60),), results).outcome == "survived"
    assert apply_rules((rule("<", 60, "races.2pct"),), results).outcome == "unreadable"
    assert apply_rules((rule("<", 60, "flag"),), results).outcome == "unreadable"
    assert apply_rules((rule("==", True, "flag"),), results).outcome == "killed"
    both = (rule("<", 60), replace(rule("<", 1, "missing"), id="k2"))
    assert apply_rules(both, results).outcome == "killed"
    assert (
        apply_rules((rule("<", 1, "races.1pct"),), {"races": {"1pct": float("nan")}}).outcome
        == "unreadable"
    )


# -- CODEOWNERS ---------------------------------------------------------------


def test_codeowners_matching():
    owners = CodeOwners.parse(CODEOWNERS)
    assert owners.owned("research/ideas/0003-mayors.md")
    assert owners.owned("research/campaigns/0001-count/campaign.md")
    assert owners.owned("research/campaigns/0001-count/drafts/s1.md")
    assert not owners.owned("research/campaigns/0001-count/report.md")
    assert owners.owned(".github/workflows/ci.yml")
    assert not owners.owned("explore/0003_count.py")
    assert not owners.owned("docs/AGENTS.md")
    assert CodeOwners.parse("[section]\n").problems


def test_repo_codeowners_protect_the_gate():
    owners = CodeOwners.from_repo(REPO)
    for path in (
        "AGENTS.md",
        ".github/workflows/campaign-tick.yml",
        "src/terrain/campaigns/gate.py",
        "scripts/campaign.py",
        "research/ideas/0001-electoral-strongholds.md",
        "confirm/pap/README.md",
        "src/terrain/registered/r0001/analysis.py",
        "src/terrain/confirm.py",
        "scripts/confirm_run.py",
        "src/terrain/explore.py",
        "scripts/seal_split.py",
        "scripts/gcp/setup_gcs.sh",
        "src/terrain/split.py",
        "src/terrain/builds/cell_outcomes.py",
        "src/terrain/builds/cell_enforcement.py",
        "pipeline/build/cell_outcomes.py",
        "pipeline/build/cell_enforcement.py",
        "tests/test_split.py",
        "tests/test_explore.py",
        "tests/test_build_cell_outcomes.py",
        "tests/test_build_cell_enforcement.py",
        "tests/test_repo_rules.py",
    ):
        assert owners.owned(path), path
    for path in (
        "explore/0001_effects.py",
        "tests/test_explore_effects.py",
        "research/explore-runs/0001/1.json",
        "research/lessons.md",
    ):
        assert not owners.owned(path), path


# -- the gate -----------------------------------------------------------------


def test_gate_passes_a_clean_campaign_pr(tmp_path):
    root = make_repo(tmp_path)
    result = evaluate(task_pr(root), ctx(root))
    assert result.state == "success", result.details


def test_gate_leaves_people_alone(tmp_path):
    root = make_repo(tmp_path)
    assert evaluate(task_pr(root, author=OWNER), ctx(root)).state == "success"


def test_gate_outside_a_campaign_waits_for_the_owner(tmp_path):
    root = make_repo(tmp_path)
    pr = task_pr(root, issue_body="no marker")
    assert evaluate(pr, ctx(root)).state == "pending"
    assert evaluate(replace(pr, approvals=(OWNER,)), ctx(root)).state == "success"


@pytest.mark.parametrize(
    "over, state, words",
    [
        ({"files": ("explore/0003_count.py", "src/terrain/x.py")}, "failure", "outside step s1"),
        ({"ci_test": None}, "pending", "waiting for CI"),
        ({"ci_test": "failure"}, "failure", "CI's test check"),
        ({"reviews": ()}, "pending", "waiting for an agent review"),
        (
            {"reviews": (Review("approve", "b" * 12, dict(REFEREE_OK), NOW),)},
            "pending",
            "waiting for an agent review",
        ),
        ({"reviews": (Review("changes", SHA[:12], {}, NOW),)}, "pending", "asked for changes"),
        (
            {
                "reviews": (
                    Review("approve", SHA[:12], {**REFEREE_OK, "R2": "Not applicable"}, NOW),
                )
            },
            "failure",
            "referee R2",
        ),
        (
            {"issue_title": "Task: something else"},
            "failure",
            "no longer matches its approved draft",
        ),
    ],
)
def test_gate_checks(tmp_path, over, state, words):
    root = make_repo(tmp_path)
    result = evaluate(task_pr(root, **over), ctx(root))
    assert result.state == state, result
    assert any(words in d for d in result.details) or words in result.description


def test_gate_allows_r5_not_applicable(tmp_path):
    root = make_repo(tmp_path)
    review = Review("approve", SHA[:12], {**REFEREE_OK, "R5": "Not applicable"}, NOW)
    assert evaluate(task_pr(root, reviews=(review,)), ctx(root)).state == "success"


def test_gate_record_pr(tmp_path):
    root = make_repo(tmp_path)
    pr = PullRequest(
        number=30,
        author=BOT,
        head_ref="explore/0003_count-555",
        head_sha=SHA,
        state="open",
        merged=False,
        mergeable=True,
        files=(
            "research/explore-runs/0003/555.md",
            "research/explore-runs/0003/555.json",
            "research/INDEX.md",
        ),
        ci_test="success",
        gate_status="success",
        run_title=markers.explore_run_title("0003_count", "0001", "s2"),
        run_conclusion="success",
    )
    assert evaluate(pr, ctx(root)).state == "success"
    bad = replace(pr, files=(*pr.files, "research/lessons.md"))
    assert evaluate(bad, ctx(root)).state == "failure"
    manual = replace(pr, run_title="Explore 0003_count ")
    assert evaluate(manual, ctx(root)).state == "pending"


def test_parse_review_reads_the_reviewer_comment():
    body = textwrap.dedent(
        """\
        ## Agent review: Approve

        Reviewed commit `abcdef123456` against [the plan](x), after CI's `test` check passed on it.

        ### Referee (explore task)

        | | Check | Status | Note |
        | --- | --- | --- | --- |
        | R1 | Exploration half only | OK | fine |
        | R5 | Plausible magnitudes | Not applicable | no run |
        """
    )
    review = parse_review(body)
    assert review.verdict == "approve" and review.sha == "abcdef123456"
    assert review.referee == {"R1": "OK", "R5": "Not applicable"}


# -- the tick -----------------------------------------------------------------


def tracking(comments=(), labels=("campaign",), state="open") -> Issue:
    return Issue(
        1,
        "Campaign 0001",
        f"x\n{markers.tracking_marker('0001')}",
        state,
        labels,
        BOT,
        "2026-11-08T00:00:00Z",
        tuple(comments),
    )


def ledger(*events: str, at: str = "2026-11-10T11:30:00Z") -> Comment:
    return Comment(BOT, "- x\n\n" + markers.ledger_marker("0001", list(events)), at)


def plan_comment(files=("explore/0003_count.py", "tests/test_explore_count.py")) -> Comment:
    hidden = json.dumps([{"path": f, "change": "add"} for f in files])
    return Comment(
        "github-actions[bot]",
        f"## Agent plan: Plan\n\nSteps\n\n<!-- agent-files: {hidden} -->",
        "2026-11-09T01:00:00Z",
    )


def step_issue(root, comments=(), labels=("campaign", "explore", "agent-plan"), pr=None) -> Issue:
    title, body = issue_body(root)
    return Issue(10, title, body, "open", labels, BOT, "2026-11-09T00:00:00Z", tuple(comments), pr)


def snap(issues, **kw) -> Snapshot:
    return Snapshot(
        now=kw.pop("now", NOW),
        enabled=kw.pop("enabled", True),
        app_bot=BOT,
        issues=list(issues),
        **kw,
    )


def run_decide(root, s):
    return decide(active_campaigns(root), s, ctx(root), root)


def types(actions):
    return [a["type"] for a in actions]


def test_tick_opens_the_tracking_issue_first(tmp_path):
    root = make_repo(tmp_path)
    actions = run_decide(root, snap([]))
    assert types(actions) == ["create_issue"]
    assert markers.tracking_marker("0001") in actions[0]["body"]


def test_tick_does_nothing_when_disabled_or_paused(tmp_path):
    root = make_repo(tmp_path)
    assert run_decide(root, snap([], enabled=False)) == []
    assert run_decide(root, snap([tracking(labels=("campaign", "campaign-pause"))])) == []


def test_tick_files_the_first_task_from_its_draft(tmp_path):
    root = make_repo(tmp_path)
    actions = run_decide(root, snap([tracking()]))
    assert types(actions) == ["comment", "create_issue"]
    created = actions[1]
    title, body = issue_body(root)
    assert created["title"] == title and created["body"] == body
    assert created["labels"] == ["campaign", "explore"] and created["then_labels"] == ["agent-plan"]


def test_tick_swaps_labels_for_a_plan_inside_the_allowed_paths(tmp_path):
    root = make_repo(tmp_path)
    t = tracking([ledger("started", "s1:filed")])
    actions = run_decide(root, snap([t, step_issue(root, [plan_comment()])]))
    assert types(actions) == ["swap_labels"]


def test_tick_blocks_a_plan_outside_the_allowed_paths(tmp_path):
    root = make_repo(tmp_path)
    t = tracking([ledger("started", "s1:filed")])
    issue = step_issue(root, [plan_comment(("explore/0003_count.py", "src/terrain/x.py"))])
    actions = run_decide(root, snap([t, issue]))
    assert types(actions) == ["comment"]
    body = actions[0]["body"]
    cause = "the plan lists files outside the step's allowed paths: ['src/terrain/x.py']"
    assert (
        f"- s1: **blocked**. Cause: {cause}. Needs you: {NEEDS_YOU['plan_paths']}. (#10) @{OWNER}"
        in body
    )
    name = f"s1:blocked:{block_id(cause, '#10')}"
    assert markers.parse_ledger(body) == ("0001", {name})
    # blocked and nothing else can run: the owner gets a day to unblock it
    recent = tracking([ledger("started", "s1:filed", name)])
    assert run_decide(root, snap([recent, issue])) == []
    old = tracking([ledger("started", "s1:filed", name, at="2026-11-09T06:00:00Z")])
    actions = run_decide(root, snap([old, issue]))
    assert "close out campaign 0001" in actions[-1]["title"]


def test_tick_merges_when_the_gate_passes(tmp_path):
    root = make_repo(tmp_path)
    t = tracking([ledger("started", "s1:filed")])
    issue = step_issue(
        root, [plan_comment()], labels=("campaign", "explore", "agent-build"), pr=task_pr(root)
    )
    actions = run_decide(root, snap([t, issue]))
    assert actions == [{"type": "merge", "pr": 20, "sha": SHA}]


def test_tick_asks_for_the_gate_status_when_it_is_missing(tmp_path):
    root = make_repo(tmp_path)
    t = tracking([ledger("started", "s1:filed")])
    issue = step_issue(
        root,
        [plan_comment()],
        labels=("campaign", "explore", "agent-build"),
        pr=task_pr(root, gate_status=None),
    )
    actions = run_decide(root, snap([t, issue]))
    assert actions == [
        {"type": "dispatch", "workflow": "campaign-gate.yml", "inputs": {"pr": "20"}}
    ]


def merged_issue(root):
    return step_issue(
        root,
        [plan_comment()],
        labels=("campaign", "explore", "agent-build"),
        pr=task_pr(root, merged=True, state="closed"),
    )


def test_tick_dispatches_the_run_after_the_merge(tmp_path):
    root = make_repo(tmp_path)
    (root / "explore" / "0003_count.py").write_text("", encoding="utf-8")
    t = tracking([ledger("started", "s1:filed")])
    actions = run_decide(root, snap([t, merged_issue(root)]))
    assert types(actions) == ["comment", "dispatch"]
    assert "s1:merged" in actions[0]["body"] and "s2:dispatched" in actions[0]["body"]
    assert actions[1]["inputs"] == {"script": "0003_count", "campaign": "0001/s2"}
    # the next tick, before the run shows up, does not start it again
    t2 = tracking([ledger("started", "s1:filed", "s1:merged", "s2:dispatched")])
    assert run_decide(root, snap([t2, merged_issue(root)])) == []


def record_run():
    return Run(
        555,
        "explore-run.yml",
        markers.explore_run_title("0003_count", "0001", "s2"),
        "completed",
        "success",
        "2026-11-09T05:00:00Z",
        "2026-11-09T05:30:00Z",
    )


def record_pr(**over):
    base = dict(
        number=30,
        author=BOT,
        head_ref="explore/0003_count-555",
        head_sha=SHA,
        state="open",
        merged=False,
        mergeable=True,
        files=("research/explore-runs/0003/555.md", "research/explore-runs/0003/555.json"),
        ci_test="success",
        gate_status="success",
        run_title=markers.explore_run_title("0003_count", "0001", "s2"),
        run_conclusion="success",
    )
    base.update(over)
    return PullRequest(**base)


def test_tick_merges_the_record_then_applies_the_kill_rule(tmp_path):
    root = make_repo(tmp_path)
    events = ("started", "s1:filed", "s1:merged", "s2:dispatched")
    s = snap(
        [tracking([ledger(*events)]), merged_issue(root)],
        runs=[record_run()],
        record_prs={555: record_pr()},
    )
    assert run_decide(root, s) == [{"type": "merge", "pr": 30, "sha": SHA}]
    s = snap(
        [tracking([ledger(*events)]), merged_issue(root)],
        runs=[record_run()],
        record_prs={555: record_pr(merged=True, state="closed")},
        results={"research/explore-runs/0003/555.json": {"races": {"1pct": 45}}},
    )
    actions = run_decide(root, s)
    assert "Verdict: **killed**" in actions[0]["body"]
    assert "Campaign finished" in actions[0]["body"]
    assert actions[1]["title"].startswith("Task: close out campaign 0001")
    assert markers.closeout_marker("0001") in actions[1]["body"]
    row = "| s2 | explore_run | done | killed | PR #30, run 555, `research/explore-runs/0003/555"
    assert row in actions[1]["body"]
    assert "s2: k1 (Fewer than 60 races at 1%)" in actions[1]["body"]


def failed_block_line(actions) -> str:
    """The ledger's block line for a failed run, with its sub-lines."""
    body = next(a["body"] for a in actions if a["type"] == "comment")
    start = body.index("**blocked**. Cause: run ")
    return body[body.rfind("\n", 0, start) + 1 : body.index("\n\n<!--", start)]


def test_tick_failed_explore_run_gives_the_values_to_start_it_again(tmp_path):
    root = make_repo(tmp_path)
    events = ("started", "s1:filed", "s1:merged", "s2:dispatched")
    failed = replace(record_run(), conclusion="failure")
    actions = run_decide(
        root, snap([tracking([ledger(*events)]), merged_issue(root)], runs=[failed])
    )
    line = failed_block_line(actions)
    assert line.startswith("- s2: **blocked**. Cause: run 555 ended 'failure'.")
    assert f"Needs you: {NEEDS_YOU['run_failed']}." in line
    assert "Re-run failed jobs" in line and "Run workflow on main" in line
    assert "Re-run jobs once the cause is fixed" not in line
    # the same workflow and inputs the tick dispatched for this step
    assert line.endswith(
        "\n  - Run workflow values: workflow **Explore run**, "
        "script `0003_count`, campaign `0001/s2`"
    )


def test_tick_failed_pipeline_run_gives_the_values_to_start_it_again(tmp_path):
    extra = (
        "  - id: s3\n    kind: pipeline_run\n    stage: build\n    target: tse_candidates\n"
        "    dataset: tse_candidates\n"
    )
    dataset = (
        "datasets:\n  - name: tse_candidates\n    source: TSE\n    licence: open\n"
        "    max_size_gb: 1\n    identifiers: none\n"
    )
    text = campaign_text(extra_steps=extra).replace("max_pipeline_runs: 0", "max_pipeline_runs: 1")
    root = make_repo(tmp_path, text.replace("datasets: []\n", dataset))
    (root / "pipeline" / "build").mkdir(parents=True)
    (root / "pipeline" / "build" / "tse_candidates.py").write_text("", encoding="utf-8")
    assert validate(root) == []
    first = run_decide(root, snap([tracking([ledger("started", "s1:filed")]), step_issue(root)]))
    dispatch = next(a for a in first if a["type"] == "dispatch")
    assert dispatch["workflow"] == "data-pipeline.yml"
    title = markers.pipeline_run_title("build", "tse_candidates", "0001", "s3")
    failed = Run(
        556, "data-pipeline.yml", title, "completed", "failure", "2026-11-10T10:00:00Z", None
    )
    t = tracking([ledger("started", "s1:filed", "s3:dispatched")])
    line = failed_block_line(run_decide(root, snap([t, step_issue(root)], runs=[failed])))
    assert line.startswith("- s3: **blocked**. Cause: run 556 ended 'failure'.")
    assert "Re-run jobs once the cause is fixed" not in line
    values = "\n  - Run workflow values: workflow **Data pipeline**, "
    assert values in line
    for key, value in dispatch["inputs"].items():
        assert f"{key} `{value}`" in line.split(values, 1)[1]
    assert line.endswith("stage `build`, target `tse_candidates`, campaign `0001/s3`")


def test_tick_names_the_run_workflows_as_github_shows_them():
    for file, name in WORKFLOW_NAMES.items():
        text = (REPO / ".github" / "workflows" / file).read_text(encoding="utf-8")
        assert text.splitlines()[0] == f"name: {name}"


def test_tick_unreadable_results_block_the_step(tmp_path):
    root = make_repo(tmp_path)
    events = ("started", "s1:filed", "s1:merged", "s2:dispatched")
    s = snap(
        [tracking([ledger(*events)]), merged_issue(root)],
        runs=[record_run()],
        record_prs={555: record_pr(merged=True, state="closed")},
        results={"research/explore-runs/0003/555.json": {"other": 1}},
    )
    body = run_decide(root, s)[0]["body"]
    assert "s2: **blocked**" in body and "could not be applied" in body


def test_tick_respects_the_budget_and_the_end_date(tmp_path):
    root = make_repo(tmp_path, campaign_text(end_by="2026-11-09"))
    actions = run_decide(root, snap([tracking()]))
    assert "create_issue" not in [
        a["type"]
        for a in actions
        if a.get("then_labels") == ["agent-plan"] and "close out" not in a.get("title", "")
    ]


def test_tick_stop_files_the_closeout(tmp_path):
    root = make_repo(tmp_path)
    t = tracking([ledger("started")], labels=("campaign", "campaign-stop"))
    actions = run_decide(root, snap([t]))
    assert "Stopped by the owner" in actions[0]["body"]
    assert "status: stopped" in actions[1]["body"]


def test_tick_one_run_in_flight_across_campaigns(tmp_path):
    """A second campaign's run waits while another run is in flight."""
    root = make_repo(tmp_path)
    (root / "explore" / "0003_count.py").write_text("", encoding="utf-8")
    (root / "explore" / "0004_other.py").write_text("", encoding="utf-8")
    (root / "research" / "ideas" / "0004-align.md").write_text("---\n---\n", encoding="utf-8")
    other = root / "research" / "campaigns" / "0002-other"
    other.mkdir(parents=True)
    text = textwrap.dedent(
        """\
        ---
        id: "0002"
        title: "Other"
        status: active
        idea: "0004"
        owner: gabrielsgaspar
        created: 2026-11-08
        end_by: 2026-11-20
        budget: {max_tasks: 0, max_explore_runs: 1, max_pipeline_runs: 0, max_model_jobs: 0}
        datasets: []
        steps:
          - id: s1
            kind: explore_run
            script: 0004_other
            kill_rules:
              - {id: k1, says: "none", field: n, op: "<", value: 1, confirmed: true}
        ---
        """
    )
    (other / "campaign.md").write_text(text, encoding="utf-8")
    assert validate(root) == []
    t1 = tracking([ledger("started", "s1:filed", "s1:merged", "s2:dispatched")])
    t2 = Issue(
        2,
        "Campaign 0002",
        markers.tracking_marker("0002"),
        "open",
        ("campaign",),
        BOT,
        NOW,
        (Comment(BOT, markers.ledger_marker("0002", ["started"]), NOW),),
    )
    running = replace(record_run(), status="in_progress", conclusion=None)
    actions = run_decide(root, snap([t1, t2, merged_issue(root)], runs=[running]))
    assert not [a for a in actions if a["type"] == "dispatch"]


# -- blocks: each one reported, with its cause ---------------------------------


def posted(actions, at: str) -> list[Comment]:
    """The tick's ledger comments, as GitHub would show them on the next tick."""
    return [Comment(BOT, a["body"], at) for a in actions if a["type"] == "comment"]


def bad_plan(at: str = "2026-11-09T01:00:00Z") -> Comment:
    return replace(plan_comment(("explore/0003_count.py", "src/terrain/x.py")), created_at=at)


def good_plan(at: str) -> Comment:
    return replace(plan_comment(), created_at=at)


def test_tick_reports_each_block_and_each_unblock(tmp_path):
    """Blocked, unblocked, blocked for another reason: two mentions and one unblocked line."""
    root = make_repo(tmp_path)
    ledgers = [ledger("started", "s1:filed", at="2026-11-09T00:30:00Z")]
    issue = step_issue(root, [bad_plan()])
    first = run_decide(root, snap([tracking(ledgers), issue], now="2026-11-09T02:00:00Z"))
    ledgers += posted(first, "2026-11-09T02:00:00Z")
    # a new plan inside the allowed paths: unblocked, and the labels swap
    issue = step_issue(root, [bad_plan(), good_plan("2026-11-09T03:00:00Z")])
    second = run_decide(root, snap([tracking(ledgers), issue], now="2026-11-09T04:00:00Z"))
    assert types(second) == ["comment", "swap_labels"]
    assert second[0]["body"].startswith("- s1: unblocked.\n")
    ledgers += posted(second, "2026-11-09T04:00:00Z")
    # the agent stops on it: blocked again, for another cause
    issue = replace(issue, labels=("campaign", "explore", "agent-build", "needs-human"))
    third = run_decide(root, snap([tracking(ledgers), issue], now="2026-11-09T05:00:00Z"))
    ledgers += posted(third, "2026-11-09T05:00:00Z")
    bodies = [c.body for c in ledgers]
    blocked = [b for b in bodies if "**blocked**" in b]
    assert len(blocked) == 2 and all(f"@{OWNER}" in b for b in blocked)
    assert "Cause: the plan lists files outside" in blocked[0]
    assert "Cause: an agent stopped and labelled it needs-human. Needs you: " in blocked[1]
    assert NEEDS_YOU["needs_human"] in blocked[1]
    assert sum(b.count("unblocked.") for b in bodies) == 1
    # the same block seen again on the next tick: nothing new
    assert run_decide(root, snap([tracking(ledgers), issue], now="2026-11-09T06:00:00Z")) == []


def test_tick_reports_the_same_block_again_after_an_unblock(tmp_path):
    root = make_repo(tmp_path)
    stopped = step_issue(root, [plan_comment()], labels=("campaign", "explore", "needs-human"))
    going = step_issue(root, [plan_comment()])  # plan ready, labels swap next
    ledgers = [ledger("started", "s1:filed")]
    for n, issue in enumerate((stopped, going, stopped)):
        actions = run_decide(root, snap([tracking(ledgers), issue]))
        ledgers += posted(actions, f"2026-11-10T11:4{n}:00Z")
    found = set()
    for c in ledgers:
        found |= markers.parse_ledger(c.body)[1]
    name = f"s1:blocked:{block_id('an agent stopped and labelled it needs-human', '#10')}"
    assert {name, name + "-2", name.replace("blocked", "unblocked")} <= found
    assert sum("**blocked**" in c.body and f"@{OWNER}" in c.body for c in ledgers) == 2


def test_tick_grace_counts_from_the_newest_block(tmp_path):
    root = make_repo(tmp_path)
    issue = step_issue(root, [plan_comment()], labels=("campaign", "explore", "needs-human"))
    now_id = block_id("an agent stopped and labelled it needs-human", "#10")
    old_id = block_id("no plan two hours after filing", "#10")
    two_days_ago = "2026-11-08T12:00:00Z"
    history = [
        ledger("started", "s1:filed", f"s1:blocked:{old_id}", at=two_days_ago),
        ledger(f"s1:unblocked:{old_id}", at="2026-11-08T13:00:00Z"),
    ]
    # the newest block was posted an hour ago: no close-out yet
    recent = tracking([*history, ledger(f"s1:blocked:{now_id}", at="2026-11-10T11:00:00Z")])
    assert run_decide(root, snap([recent, issue])) == []
    # an older block that never cleared does not shorten the day either
    never_cleared = tracking(
        [
            ledger("started", "s1:filed", f"s1:blocked:{old_id}", at=two_days_ago),
            ledger(f"s1:blocked:{now_id}", at="2026-11-10T11:00:00Z"),
        ]
    )
    actions = run_decide(root, snap([never_cleared, issue]))
    assert types(actions) == ["comment"] and actions[0]["body"] == (
        "- s1: unblocked.\n\n" + markers.ledger_marker("0001", [f"s1:unblocked:{old_id}"]) + "\n"
    )
    # a day after the newest block: the campaign closes out
    old = tracking([*history, ledger(f"s1:blocked:{now_id}", at="2026-11-09T11:00:00Z")])
    assert "close out campaign 0001" in run_decide(root, snap([old, issue]))[-1]["title"]


def test_tick_reads_the_old_block_event_name(tmp_path):
    """Ledgers from before blocks had ids hold a plain `s1:blocked`: an earlier block."""
    root = make_repo(tmp_path)
    issue = step_issue(root, [plan_comment()], labels=("campaign", "explore", "needs-human"))
    recent = tracking([ledger("started", "s1:filed", "s1:blocked")])
    assert run_decide(root, snap([recent, issue])) == []  # still the same block, in its day
    old = tracking([ledger("started", "s1:filed", "s1:blocked", at="2026-11-09T06:00:00Z")])
    assert "close out campaign 0001" in run_decide(root, snap([old, issue]))[-1]["title"]
    going = step_issue(root, [plan_comment()])  # plan ready, labels swap next
    actions = run_decide(root, snap([recent, going]))
    assert markers.parse_ledger(actions[0]["body"]) == ("0001", {"s1:unblocked"})
    assert "- s1: unblocked." in actions[0]["body"]
    # after that, a new block gets an id and a mention
    cleared = tracking([ledger("started", "s1:filed", "s1:blocked", "s1:unblocked")])
    body = run_decide(root, snap([cleared, issue]))[0]["body"]
    assert "s1: **blocked**" in body and f"@{OWNER}" in body


def test_tick_unknown_block_kinds_get_the_default_action(tmp_path):
    root = make_repo(tmp_path)
    issue = replace(step_issue(root, [plan_comment()]), state="closed")
    body = run_decide(root, snap([tracking([ledger("started", "s1:filed")]), issue]))[0]["body"]
    assert f"Needs you: {NEEDS_YOU_DEFAULT}. (#10) @{OWNER}" in body


# -- closing the tracking issue after the close-out ---------------------------------


def closeout_issue(merged=True, labels=("campaign", "agent-build"), **pr_over) -> Issue:
    body = f"x\n{markers.closeout_marker('0001')}"
    base = dict(
        number=41,
        author=BOT,
        head_ref="agent/issue-40",
        head_sha=SHA,
        state="closed" if merged else "open",
        merged=merged,
        mergeable=True,
        files=("research/campaigns/0001-count/report.md",),
        ci_test="success",
        gate_status="success",
    )
    base.update(pr_over)
    return Issue(
        40,
        "Task: close out campaign 0001",
        body,
        "closed" if merged else "open",
        labels,
        BOT,
        "2026-11-10T00:00:00Z",
        (plan_comment(("research/campaigns/0001-count/report.md",)),),
        PullRequest(**base),
    )


def run_decide_finished(root, s):
    return decide(active_campaigns(root), s, ctx(root), root, finished_campaigns(root))


def test_tick_closes_a_finished_campaigns_tracking_issue(tmp_path):
    root = make_repo(tmp_path, campaign_text(status="done"))
    assert active_campaigns(root) == [] and [c.id for c in finished_campaigns(root)] == ["0001"]
    t = tracking([ledger("started", "finished", "closeout:filed")])
    actions = run_decide_finished(root, snap([t, closeout_issue()]))
    assert types(actions) == ["comment", "close_issue"]
    assert actions[0]["issue"] == 1 and actions[1] == {"type": "close_issue", "issue": 1}
    assert "Close-out PR #41 merged" in actions[0]["body"]
    assert markers.parse_ledger(actions[0]["body"]) == ("0001", {"closed"})


def test_tick_closing_is_idempotent_and_waits_for_the_merge(tmp_path):
    root = make_repo(tmp_path, campaign_text(status="done"))
    # the ledger comment was posted but the close failed: close again, no second comment
    posted = tracking([ledger("started", "closed")])
    assert run_decide_finished(root, snap([posted, closeout_issue()])) == [
        {"type": "close_issue", "issue": 1}
    ]
    # already closed, close-out not merged, paused, or no close-out at all: nothing
    assert run_decide_finished(root, snap([tracking(state="closed"), closeout_issue()])) == []
    assert run_decide_finished(root, snap([tracking(), closeout_issue(merged=False)])) == []
    paused = tracking(labels=("campaign", "campaign-pause"))
    assert run_decide_finished(root, snap([paused, closeout_issue()])) == []
    assert run_decide_finished(root, snap([tracking()])) == []
    # someone else's issue with a tracking marker is not the campaign's
    fake = replace(tracking(), author="someone")
    assert run_decide_finished(root, snap([fake, closeout_issue()])) == []


def test_tick_closes_when_an_active_campaigns_closeout_merges(tmp_path):
    """The close-out merged after this tick's checkout, so the file still says active."""
    root = make_repo(tmp_path)
    t = tracking(
        [ledger("started", "stopped", "finished", "closeout:filed")],
        labels=("campaign", "campaign-stop"),
    )
    actions = run_decide(root, snap([t, closeout_issue()]))
    assert types(actions) == ["comment", "close_issue"]
    found = markers.parse_ledger(actions[0]["body"])
    assert found == ("0001", {"closeout:merged", "closed"})


# -- the close-out: Gabriel approves, the tick merges ------------------------------


STOPPED = ("started", "stopped", "finished", "closeout:filed")


def ready_closeout(approvals=()) -> Issue:
    """An open close-out PR that the gate passes and GitHub can merge."""
    return closeout_issue(
        merged=False,
        issue_body=f"x\n{markers.closeout_marker('0001')}",
        reviews=(Review("approve", SHA[:12], {}, NOW),),
        approvals=approvals,
    )


def stopped_tracking(*extra: str) -> Issue:
    return tracking([ledger(*STOPPED, *extra)], labels=("campaign", "campaign-stop"))


def test_closeout_approved_by_the_owner_is_merged(tmp_path):
    root = make_repo(tmp_path)
    actions = run_decide(root, snap([stopped_tracking(), ready_closeout((OWNER,))]))
    assert [a for a in actions if a["type"] == "merge"] == [{"type": "merge", "pr": 41, "sha": SHA}]
    assert f"- Close-out approved by @{OWNER}; merging PR #41." in actions[0]["body"]
    assert "the report is ready" not in actions[0]["body"]
    # the next tick (merge not yet seen) tries the merge again but posts nothing twice
    found = markers.parse_ledger(actions[0]["body"])[1]
    again = run_decide(root, snap([stopped_tracking(*found), ready_closeout((OWNER,))]))
    assert again == [{"type": "merge", "pr": 41, "sha": SHA}]


@pytest.mark.parametrize("approvals", [(), ("someone-else",), ("someone-else", BOT)])
def test_closeout_without_the_owners_approval_is_not_merged(tmp_path, approvals):
    root = make_repo(tmp_path)
    actions = run_decide(root, snap([stopped_tracking(), ready_closeout(approvals)]))
    assert types(actions) == ["comment"]
    assert (
        f"- @{OWNER} the report is ready: PR #41. To accept it, open the pull request, choose "
        "Files changed, then Review changes, then Approve. It is then merged for you. "
        "To reject it, close the pull request." in actions[0]["body"]
    )
    # a repeated tick does not post the ready message twice
    assert run_decide(root, snap([stopped_tracking("closeout:ready"), ready_closeout()])) == []


def test_closeout_blocks_are_reported_like_steps(tmp_path):
    root = make_repo(tmp_path)
    stuck = ready_closeout()
    stuck = replace(stuck, labels=(*stuck.labels, "needs-human"))
    body = run_decide(root, snap([stopped_tracking(), stuck]))[0]["body"]
    assert "- close-out: **blocked**. Cause: an agent stopped and labelled it needs-human." in body
    assert f"@{OWNER}" in body
    (name,) = markers.parse_ledger(body)[1]
    assert name.startswith("closeout:blocked:") and len(name) == len("closeout:blocked:") + 8
    assert run_decide(root, snap([stopped_tracking(name), stuck])) == []
    # unblocked, and an old plain `closeout:blocked` reads as an earlier block
    for old in (name, "closeout:blocked"):
        body = run_decide(root, snap([stopped_tracking(old), ready_closeout()]))[0]["body"]
        assert "- close-out: unblocked." in body and "the report is ready" in body


def act_script() -> str:
    text = (REPO / ".github" / "workflows" / "campaign-tick.yml").read_text(encoding="utf-8")
    start = text.index("python3 -I - <<'PY'\n") + len("python3 -I - <<'PY'\n")
    return textwrap.dedent(text[start : text.index("\n          PY\n", start)])


def run_act(tmp_path, monkeypatch, actions, issues):
    """Run the tick's act script against a fake API; returns (exit code, calls)."""
    import io
    import urllib.request

    calls: list[tuple[str, str, object]] = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout=0):
        path = req.full_url.removeprefix("https://api.github.com/repos/o/r")
        body = json.loads(req.data) if req.data else None
        calls.append((req.get_method(), path, body))
        if req.get_method() == "GET":
            return Answer(json.dumps(issues[int(path.rsplit("/", 1)[1])]).encode())
        return Answer(b"")

    file = tmp_path / "actions.json"
    file.write_text(json.dumps(actions), encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("REPO", "o/r")
    monkeypatch.setenv("APP_TOKEN", "test")
    monkeypatch.setenv("ACTIONS", str(file))
    with pytest.raises(SystemExit) as done:
        exec(compile(act_script(), "campaign-tick act", "exec"), {"__name__": "__main__"})
    return done.value.code, calls


def test_act_closes_only_campaign_tracking_issues(tmp_path, monkeypatch):
    issues = {
        1: {"body": f"x\n{markers.tracking_marker('0001')}"},
        2: {"body": f"x\n{markers.step_marker('0001', 's1')}"},  # a step, not tracking
        3: {"body": f"{markers.tracking_marker('0001')}", "pull_request": {}},  # a PR
    }
    code, calls = run_act(tmp_path, monkeypatch, [{"type": "close_issue", "issue": 1}], issues)
    assert code == 0
    assert calls[-1] == ("PATCH", "/issues/1", {"state": "closed", "state_reason": "completed"})
    for n in (2, 3):
        code, calls = run_act(tmp_path, monkeypatch, [{"type": "close_issue", "issue": n}], issues)
        assert code == 1 and [c[0] for c in calls] == ["GET"]


# -- the GitHub reader, against canned API answers ---------------------------------


class FakeGitHub:
    """`terrain.campaigns.github.GitHub` with `_request` answered from a dict."""

    def __new__(cls, answers: dict[str, object]):
        from terrain.campaigns.github import GitHub

        class _Fake(GitHub):
            def _request(self, url: str):
                path = url.removeprefix("https://api.github.com/repos/o/r")
                for key, value in answers.items():
                    if path.split("?")[0] == key.split("?")[0] and all(
                        part in path for part in key.split("?")[1:]
                    ):
                        return value, ""
                raise AssertionError(f"unexpected request {path}")

        return _Fake("o/r", token="", api="https://api.github.com")


def test_github_reader_builds_the_facts(tmp_path):
    root = make_repo(tmp_path)
    (root / "research" / "explore-runs" / "0003").mkdir(parents=True)
    (root / "research" / "explore-runs" / "0003" / "555.json").write_text(
        '{"races": {"1pct": 70}}', encoding="utf-8"
    )
    title, body = issue_body(root)
    review = (
        "## Agent review: Approve\n\nReviewed commit `aaaaaaaaaaaa` against x.\n\n"
        "| R1 | Exploration half only | OK | ok |\n"
    )
    answers = {
        "/issues?labels=campaign": [
            {
                "number": 10,
                "title": title,
                "body": body,
                "state": "open",
                "labels": [{"name": "campaign"}],
                "user": {"login": BOT},
                "created_at": NOW,
            }
        ],
        "/issues/10/comments": [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "## Agent plan: Plan\n",
                "created_at": NOW,
            }
        ],
        "/pulls?head=o%3Aagent%2Fissue-10": [{"number": 20}],
        "/pulls/20": {
            "number": 20,
            "user": {"login": BOT},
            "head": {"ref": "agent/issue-10", "sha": SHA},
            "state": "open",
            "merged": False,
            "mergeable": True,
            "labels": [],
            "created_at": NOW,
        },
        "/pulls/20/files": [{"filename": "explore/0003_count.py"}],
        f"/commits/{SHA}/check-runs": {
            "check_runs": [
                {"id": 1, "status": "completed", "conclusion": "failure"},
                {"id": 2, "status": "completed", "conclusion": "success"},
            ]
        },
        f"/commits/{SHA}/statuses": [{"context": "campaign-gate", "state": "success"}],
        "/issues/20/comments": [
            {"user": {"login": "github-actions[bot]"}, "body": review, "created_at": NOW}
        ],
        "/pulls/20/reviews": [{"user": {"login": OWNER}, "state": "APPROVED", "commit_id": SHA}],
        "/issues/10": {"title": title, "body": body},
        "/actions/workflows/explore-run.yml/runs": {
            "workflow_runs": [
                {
                    "id": 555,
                    "display_title": markers.explore_run_title("0003_count", "0001", "s2"),
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ]
        },
        "/actions/workflows/data-pipeline.yml/runs": {"workflow_runs": []},
        "/pulls?head=o%3Aexplore%2F0003_count-555": [],
    }
    gh = FakeGitHub(answers)
    pr = gh.pull_request(20)
    assert pr.ci_test == "success"  # the newest check run wins
    assert pr.gate_status == "success" and pr.approvals == (OWNER,)
    assert pr.review_of_head().verdict == "approve" and pr.issue_title == title
    s = gh.snapshot(now=NOW, enabled=True, app_bot=BOT, since="2026-11-08", root=root)
    assert [i.number for i in s.issues] == [10] and s.issues[0].pr.number == 20
    assert [r.id for r in s.runs] == [555] and s.record_prs == {}
    assert s.results == {"research/explore-runs/0003/555.json": {"races": {"1pct": 70}}}


@pytest.mark.parametrize(
    "reviews, approvals",
    [
        ([("APPROVED", SHA)], (OWNER,)),
        ([("APPROVED", SHA), ("CHANGES_REQUESTED", SHA)], ()),  # changes requested after
        ([("APPROVED", "b" * 40)], ()),  # an approval of an older commit
        ([("COMMENTED", SHA)], ()),
    ],
)
def test_github_reader_counts_only_approvals_of_the_head(reviews, approvals):
    """What the close-out merge rests on: the owner's latest review approves the head."""
    gh = FakeGitHub(
        {
            "/pulls/41": {
                "number": 41,
                "user": {"login": BOT},
                "head": {"ref": "agent/issue-40", "sha": SHA},
                "state": "open",
                "merged": False,
                "mergeable": True,
                "labels": [],
            },
            "/pulls/41/files": [{"filename": "research/campaigns/0001-count/report.md"}],
            f"/commits/{SHA}/check-runs": {"check_runs": []},
            f"/commits/{SHA}/statuses": [],
            "/issues/41/comments": [],
            "/pulls/41/reviews": [
                {"user": {"login": OWNER}, "state": state, "commit_id": sha}
                for state, sha in reviews
            ],
        }
    )
    assert gh.pull_request(41, with_issue=False).approvals == approvals


# -- friction facts in the close-out issue ----------------------------------------


def closeout_body(actions) -> str:
    (body,) = [a["body"] for a in actions if "close out campaign" in a.get("title", "")]
    return body


def friction_groups(body: str) -> dict[str, str]:
    """The friction facts of a close-out body, by group heading."""
    facts = body.split("## Friction facts (written by the tick; copy as is)\n", 1)[1]
    facts = facts.split("\n## In scope", 1)[0]
    groups = {}
    for part in facts.split("### ")[1:]:
        head, _, text = part.partition("\n")
        groups[head] = text.strip()
    return groups


def test_closeout_carries_every_block_and_the_fix_rounds(tmp_path):
    """Two blocks on s1 (one cleared, one not) and one fix round on its PR."""
    root = make_repo(tmp_path)
    ledgers = [ledger("started", "s1:filed", at="2026-11-09T00:30:00Z")]
    replanned = step_issue(root, [bad_plan(), good_plan("2026-11-09T03:00:00Z")])
    for now, issue in (
        ("2026-11-09T02:00:00Z", step_issue(root, [bad_plan()])),
        ("2026-11-09T04:00:00Z", replanned),
    ):
        ledgers += posted(run_decide(root, snap([tracking(ledgers), issue], now=now)), now)
    reviews = (
        Review("changes", "b" * 12, dict(REFEREE_OK), "2026-11-09T04:30:00Z"),
        Review("approve", SHA[:12], dict(REFEREE_OK), "2026-11-09T04:40:00Z"),
    )
    issue = replace(
        replanned,
        labels=("campaign", "explore", "agent-build", "needs-human"),
        pr=task_pr(root, reviews=reviews),
    )
    now = "2026-11-09T05:00:00Z"
    ledgers += posted(run_decide(root, snap([tracking(ledgers), issue], now=now)), now)
    stop = tracking(ledgers, labels=("campaign", "campaign-stop"))
    body = closeout_body(run_decide(root, snap([stop, issue], now="2026-11-09T07:00:00Z")))
    groups = friction_groups(body)
    blocks = groups["Blocks"]
    outside = "the plan lists files outside the step's allowed paths: ['src/terrain/x.py']"
    assert f"| s1 | {outside} | 2026-11-09T02:00:00Z | 2.0 |" in blocks
    stopped = "an agent stopped and labelled it needs-human"
    assert f"| s1 | {stopped} | 2026-11-09T05:00:00Z | never |" in blocks
    assert blocks.count("\n| s1 |") == 2
    # two plans, two agent reviews: one fix round, 2 + 2 * 2 model jobs
    tasks = groups["Task steps with more than one plan or a fix round"]
    assert "| s1 | 2 | 1 | 6 |" in tasks
    time = groups["Time"]
    assert "2026-11-09T00:30:00Z) to `finished` (2026-11-09T07:00:00Z): 6.5 hours." in time
    assert time.count("\n| 2.0 |") == 2 and "| 1.5 |" in time
    # the report must list those blocks; "none" only without block rows
    assert '"Stops and blocks" copies the friction facts above' in body


def test_closeout_counts_the_runs_of_a_run_step(tmp_path):
    root = make_repo(tmp_path)
    events = ("started", "s1:filed", "s1:merged", "s2:dispatched")
    failed = replace(record_run(), id=554, conclusion="failure", created_at="2026-11-09T04:00:00Z")
    s = snap(
        [tracking([ledger(*events)]), merged_issue(root)],
        runs=[failed, record_run()],
        record_prs={555: record_pr(merged=True, state="closed")},
        results={"research/explore-runs/0003/555.json": {"races": {"1pct": 45}}},
    )
    groups = friction_groups(closeout_body(run_decide(root, s)))
    assert (
        "| s2 | 2 | 554 failure, 555 success |" in groups["Run steps that took more than one run"]
    )


def test_closeout_without_friction_says_none(tmp_path):
    root = make_repo(tmp_path)
    # one plan, one approving review, one run, no block
    events = ("started", "s1:filed", "s1:merged", "s2:dispatched")
    s = snap(
        [tracking([ledger(*events)]), merged_issue(root)],
        runs=[record_run()],
        record_prs={555: record_pr(merged=True, state="closed")},
        results={"research/explore-runs/0003/555.json": {"races": {"1pct": 45}}},
    )
    groups = friction_groups(closeout_body(run_decide(root, s)))
    assert groups["Blocks"] == "None."
    assert groups["Task steps with more than one plan or a fix round"] == (
        "None.\n\nOne plan and no fix round: s1."
    )
    assert groups["Run steps that took more than one run"] == "None."
    # stopped before anything happened: every group says none
    stop = tracking(labels=("campaign", "campaign-stop"))
    groups = friction_groups(closeout_body(run_decide(root, snap([stop]))))
    assert list(groups) == [
        "Blocks",
        "Task steps with more than one plan or a fix round",
        "Run steps that took more than one run",
        "Time",
    ]
    for head in list(groups)[:3]:
        assert groups[head] == "None."
    assert ": 0.0 hours." in groups["Time"] and groups["Time"].endswith("\n\nNone.")


def test_closeout_body_names_every_report_section_in_order(tmp_path):
    root = make_repo(tmp_path)
    body = closeout_body(run_decide(root, snap([tracking(labels=("campaign", "campaign-stop"))])))
    assert len(REPORT_SECTIONS) == 9
    assert REPORT_SECTIONS.index("Proposed harness changes (at most three)") == (
        REPORT_SECTIONS.index("Stops and blocks") + 1
    )
    places = [body.index(f"   - `## {s}`") for s in REPORT_SECTIONS]
    assert places == sorted(places)
    openings = [body.index(f"   - `{line}`") for line in REPORT_OPENING]
    assert openings == sorted(openings) and openings[-1] < places[0]
    done = body.split("## Done when", 1)[1]
    assert f"then has the {number_word(len(REPORT_SECTIONS))} sections listed" in done
    assert "nine sections" in done and "eight sections" not in body
    assert "## Friction facts (written by the tick; copy as is)" in body
    assert body.index("## Friction facts") < body.index("## In scope")


def test_closeout_reads_the_cause_of_an_old_block_line(tmp_path):
    """Ledgers from before blocks had ids wrote `s1: **blocked**: cause (links)`."""
    root = make_repo(tmp_path)
    old = Comment(
        BOT,
        "- s1: **blocked**: no plan two hours after filing (#10). @gabrielsgaspar\n\n"
        + markers.ledger_marker("0001", ["s1:blocked"]),
        "2026-11-09T03:00:00Z",
    )
    t = tracking(
        [ledger("started", "s1:filed", at="2026-11-09T00:00:00Z"), old],
        labels=("campaign", "campaign-stop"),
    )
    groups = friction_groups(closeout_body(run_decide(root, snap([t, step_issue(root)]))))
    assert (
        "| s1 | no plan two hours after filing | 2026-11-09T03:00:00Z | never |"
        in (groups["Blocks"])
    )
