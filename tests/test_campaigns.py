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
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.facts import Comment, Issue, PullRequest, Review, Run, Snapshot, parse_review
from terrain.campaigns.gate import GateContext, evaluate
from terrain.campaigns.rules import evaluate as apply_rules
from terrain.campaigns.spec import (
    KillRule,
    active_campaigns,
    load_campaigns,
    path_allowed,
    validate,
)
from terrain.campaigns.tick import decide

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
    ):
        assert owners.owned(path), path
    for path in (
        "explore/0001_effects.py",
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
    assert "blocked" in actions[0]["body"] and f"@{OWNER}" in actions[0]["body"]
    # blocked and nothing else can run: the owner gets a day to unblock it
    recent = tracking([ledger("started", "s1:filed", "s1:blocked")])
    assert run_decide(root, snap([recent, issue])) == []
    old = tracking([ledger("started", "s1:filed", "s1:blocked", at="2026-11-09T06:00:00Z")])
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
