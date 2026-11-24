"""The learning loop: one close-out at a time, a cause for every stop, the failure log.

Every test builds a small repository in tmp_path and hand-made GitHub facts, with
the helpers of tests/test_campaigns.py. Nothing here calls the network.
"""

from __future__ import annotations

import ast
import itertools
import re
from dataclasses import replace
from pathlib import Path

import pytest
from test_campaigns import (
    BOT,
    NOW,
    OWNER,
    SHA,
    FakeGitHub,
    add_campaign_0002,
    closeout_issue,
    ctx,
    make_repo,
    plan_comment,
    snap,
    step_issue,
    tracking,
)

from terrain.campaigns import closeout, markers, status, tick
from terrain.campaigns.closeout import (
    CATEGORIES,
    FAILURE_LOG_PATH,
    NOTE_CATEGORIES,
    SCOREBOARD_HEADER,
    STOP_CAUSES,
    Stop,
    appended,
    block_cause,
    failure_log_section,
    failure_log_section_of,
    next_note_id,
    stop_counts,
)
from terrain.campaigns.facts import Comment, Issue, Review
from terrain.campaigns.gate import closeout_paths, evaluate
from terrain.campaigns.spec import NOTES_PATH, active_campaigns, finished_campaigns
from terrain.campaigns.tick import decide

REPO = Path(__file__).resolve().parents[1]
TICK = REPO / "src" / "terrain" / "campaigns" / "tick.py"
GATE = REPO / "src" / "terrain" / "campaigns" / "gate.py"


# -- a cause for every stop: the table covers everything the tick can produce ----------


def test_every_cause_has_one_of_the_five_categories():
    assert CATEGORIES == ("plumbing", "spec", "design", "agent", "handled")
    assert set(NOTE_CATEGORIES) == {"agent", "spec", "design"}
    for key, cause in STOP_CAUSES.items():
        assert cause.category in CATEGORIES, key
        assert cause.words, key
        if cause.detail:
            re.compile(cause.detail)


def _functions(tree: ast.AST) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]


def _assigned(fn: ast.FunctionDef, name: str) -> list[ast.expr]:
    """Every value the function assigns to the local `name`."""
    return [
        n.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
    ]


LABELS: list[str] = []  # every `label = ...` of the gate, for a function that takes one


def _render(expr: ast.expr, fn: ast.FunctionDef, depth: int = 0) -> list[str] | None:
    """The texts an expression can give: constants as they are, every value inside an
    f-string as "0001", both arms of a conditional, and a local name as each value the
    function gives it. None if some part cannot be rendered."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.JoinedStr):
        parts: list[list[str]] = []
        for value in expr.values:
            if isinstance(value, ast.Constant):
                parts.append([str(value.value)])
            elif isinstance(value.value, ast.Name) and value.value.id == "label" and depth < 3:
                labels = [
                    r for v in _assigned(fn, "label") for r in (_render(v, fn, depth + 1) or [])
                ]
                parts.append(labels or LABELS or ["0001"])
            else:
                parts.append(["0001"])
        return ["".join(p) for p in itertools.product(*parts)]
    if isinstance(expr, ast.IfExp):
        a, b = _render(expr.body, fn, depth + 1), _render(expr.orelse, fn, depth + 1)
        return None if a is None or b is None else a + b
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        a, b = _render(expr.left, fn, depth + 1), _render(expr.right, fn, depth + 1)
        return None if a is None or b is None else [x + y for x in a for y in b]
    if isinstance(expr, ast.Call) and getattr(expr.func, "id", "") == "_short" and expr.args:
        return _render(expr.args[0], fn, depth + 1)
    if isinstance(expr, ast.Name) and depth < 3:
        values = _assigned(fn, expr.id)
        out = [_render(v, fn, depth + 1) for v in values]
        return None if not values or any(o is None for o in out) else [x for o in out for x in o]
    return None


def _blocked_states(tree: ast.AST) -> list[tuple[ast.FunctionDef, ast.expr, str]]:
    """(function, detail expression, cause literal or "") of every blocked step state the
    tick builds: `StepState("blocked", detail, cause=...)`, and assignments that set
    `status` to "blocked" with a detail in the same statement or the next one."""
    found = []
    for fn in _functions(tree):
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "StepState"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "blocked"
            ):
                detail = node.args[1] if len(node.args) > 1 else None
                kw = {k.arg: k.value for k in node.keywords}
                detail = kw.get("detail", detail)
                cause = kw.get("cause")
                literal = cause.value if isinstance(cause, ast.Constant) else ""
                if detail is not None:
                    found.append((fn, detail, literal))
            body = getattr(node, "body", None)
            for stmts in (body, getattr(node, "orelse", None)):
                if not isinstance(stmts, list):
                    continue
                for k, stmt in enumerate(stmts):
                    pairs = _attribute_pairs(stmt)
                    status = pairs.get("status")
                    if not (isinstance(status, ast.Constant) and status.value == "blocked"):
                        continue
                    detail = pairs.get("detail")
                    if detail is None and k + 1 < len(stmts):
                        detail = _attribute_pairs(stmts[k + 1]).get("detail")
                    cause = pairs.get("cause")
                    literal = cause.value if isinstance(cause, ast.Constant) else ""
                    if detail is not None:
                        found.append((fn, detail, literal))
    return found


def _attribute_pairs(stmt: ast.stmt) -> dict[str, ast.expr]:
    """`st.a, st.b = x, y` -> {"a": x, "b": y}; `st.a = x` -> {"a": x}."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return {}
    target, value = stmt.targets[0], stmt.value
    if isinstance(target, ast.Attribute):
        return {target.attr: value}
    if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple):
        return {
            t.attr: v
            for t, v in zip(target.elts, value.elts, strict=False)
            if isinstance(t, ast.Attribute)
        }
    return {}


def _cause_literals(tree: ast.AST) -> set[str]:
    """Every string the tick gives a step state's `cause`."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                pairs = _attribute_pairs(ast.Assign(targets=[target], value=node.value))
                cause = pairs.get("cause")
                if isinstance(cause, ast.Constant) and isinstance(cause.value, str):
                    out.add(cause.value)
        if isinstance(node, ast.keyword) and node.arg == "cause":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out.add(node.value.value)
    return out - {""}


def test_every_cause_the_tick_can_produce_has_a_category():
    """An unknown cause is a test failure, never a silent default: every cause the tick
    names, and every block it can post, maps to a row of STOP_CAUSES."""
    tree = ast.parse(TICK.read_text(encoding="utf-8"))
    named = _cause_literals(tree) | set(tick.NEEDS_YOU) | {tick.SKIP_CAUSE}
    missing = sorted(named - set(STOP_CAUSES))
    assert not missing, f"causes the tick names with no row in closeout.STOP_CAUSES: {missing}"

    blocks = _blocked_states(tree)
    assert len(blocks) >= 15, "the scan found too few blocked states; is it still reading tick.py?"
    problems = []
    for fn, detail, literal in blocks:
        source = ast.unparse(detail)
        if source == "g.description":
            continue  # the gate's failure descriptions: the next test
        if fn.name == "_task_state" and source == "problem":
            continue  # _plan_problem's answers: checked below
        texts = _render(detail, fn)
        if texts is None:
            problems.append(f"{fn.name}: cannot read the block detail `{source}`")
            continue
        for text in texts:
            cause = block_cause(text)
            if cause == "unrecognised":
                problems.append(f"{fn.name}: no cause for the block detail {text!r}")
            elif literal and literal in STOP_CAUSES and cause not in (literal, "budget"):
                problems.append(f"{fn.name}: {text!r} reads as {cause}, the tick says {literal}")
    plan_problem = next(f for f in _functions(tree) if f.name == "_plan_problem")
    for node in ast.walk(plan_problem):
        if isinstance(node, ast.Return) and node.value is not None:
            for text in _render(node.value, plan_problem) or []:
                if text and block_cause(text) != "plan_paths":
                    problems.append(f"_plan_problem: {text!r} is not plan_paths")
    assert not problems, "\n".join(problems)


def test_every_gate_failure_reads_as_a_gate_failure():
    """A gate failure blocks with the gate's description as its cause text."""
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    LABELS[:] = [
        r for fn in _functions(tree) for v in _assigned(fn, "label") for r in _render(v, fn) or []
    ]
    assert len(LABELS) >= 3
    texts = []
    for fn in _functions(tree):
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "GateResult"
                and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "failure"
            ):
                rendered = _render(node.args[1], fn)
                assert rendered, f"{fn.name}: cannot read `{ast.unparse(node.args[1])}`"
                texts += rendered
    assert len(texts) >= 8
    wrong = [t for t in texts if block_cause(t) != "gate_failed"]
    assert not wrong, wrong


@pytest.mark.parametrize(
    ("detail", "cause"),
    [
        ("the repair task: no plan two hours after filing", "no_plan"),
        ("run 7 ended 'timed_out'. Retried 2 times", "run_timed_out"),
        (
            "run 7 ended 'failure'. Retried 2 times. Not repaired: the campaign's 2 repairs "
            "are used",
            "run_failed",
        ),
        (
            "its build stopped without a pull request. Not started again: the model-job budget "
            "is used up",
            "budget",
        ),
        ("the planner answered 'Needs clarification - no plan yet'", "planner_question"),
        ("record PR #4 was closed without merging", "pr_closed"),
        ("Campaign 0013 step s1: CI's test check is 'failure' on the head commit", "gate_failed"),
        ("no plan 2 hours after filing", "no_plan"),
        ("no pull request 12 hours after the plan", "build_stalled"),
        ("the build stalled again after 2 automatic restarts", "build_stalled"),
        ("no record pull request 3 hours after the run", "record_missing"),
        ("something no tick ever wrote", "unrecognised"),
    ],
)
def test_block_cause_reads_the_ledgers_cause_text(detail, cause):
    assert block_cause(detail) == cause


def test_the_history_of_0013_and_0014_reads_as_gabriel_described_it():
    """Their report rows: needs-human, needs-human, a stall (no restart by the tick)."""
    assert block_cause("an agent stopped and labelled it needs-human") == "needs_human"
    assert block_cause("no pull request twelve hours after the plan") == "build_stalled"
    assert STOP_CAUSES["build_stalled"].category == "plumbing"
    assert STOP_CAUSES["needs_human_main"].category == "plumbing"
    assert STOP_CAUSES["build_stalled_restarted"].category == "handled"


# -- one close-out at a time ------------------------------------------------------------

DAY = "2026-11-10T"


def _stopped(issue: Issue) -> Issue:
    return replace(issue, labels=("campaign", "campaign-stop"))


def _closeouts(actions) -> list[str]:
    return [
        markers.parse_closeout(a["body"])
        for a in actions
        if a["type"] == "create_issue" and markers.parse_closeout(a["body"])
    ]


def _ledger_of(actions, issue: int) -> list[Comment]:
    return [
        Comment(BOT, a["body"], NOW)
        for a in actions
        if a.get("issue") == issue and a["type"] == "comment"
    ]


def _two_ready(tmp_path) -> tuple[Path, Issue, Issue]:
    root = make_repo(tmp_path)
    (root / "explore" / "0003_count.py").write_text("", encoding="utf-8")
    second = _stopped(add_campaign_0002(root))
    first = _stopped(
        tracking(
            [
                Comment(
                    BOT,
                    "- x\n\n" + markers.ledger_marker("0001", ["started"]),
                    "2026-11-09T00:00:00Z",
                )
            ]
        )
    )
    return root, first, second


def _decide(root, issues, now=NOW, ended=()):
    return decide(active_campaigns(root), snap(issues, now=now), ctx(root), root, list(ended))


def test_two_campaigns_ready_at_once_file_one_closeout(tmp_path):
    root, first, second = _two_ready(tmp_path)
    actions = _decide(root, [first, second])
    assert _closeouts(actions) == ["0001"]
    (wait,) = _ledger_of(actions, 2)
    assert markers.parse_ledger(wait.body) == ("0002", {"stopped", "closeout:waiting:1"})
    assert (
        "Campaign finished: the owner stopped it. Its close-out task waits for campaign "
        "0001's close-out to merge (one close-out at a time)." in wait.body
    )
    # the next tick: 0001's close-out issue is open, so 0002 still waits and posts nothing new
    first = replace(first, comments=(*first.comments, *_ledger_of(actions, 1)))
    second = replace(second, comments=(*second.comments, wait))
    filed = replace(closeout_issue(merged=False), pr=None, labels=("campaign", "agent-plan"))
    again = _decide(root, [first, second, filed], now="2026-11-10T13:00:00Z")
    assert _closeouts(again) == [] and _ledger_of(again, 2) == []
    # the status page says why 0002's close-out is not filed yet
    page = tick.render_status_page(
        active_campaigns(root), snap([first, second, filed]), ctx(root), root
    )
    assert "close-out: waiting for campaign 0001's close-out to merge" in page


def test_the_second_closeout_is_filed_after_the_first_merges(tmp_path):
    root, first, second = _two_ready(tmp_path)
    actions = _decide(root, [first, second])
    second = replace(second, comments=(*second.comments, *_ledger_of(actions, 2)))
    # 0001's close-out PR merged: its campaign file now says done, so 0001 is not active
    folder = root / "research" / "campaigns" / "0001-count" / "campaign.md"
    folder.write_text(
        folder.read_text(encoding="utf-8").replace("status: active", "status: done"),
        encoding="utf-8",
    )
    assert [c.id for c in active_campaigns(root)] == ["0002"]
    later = "2026-11-11T09:00:00Z"
    merged = closeout_issue(merged=True)
    after = _decide(root, [first, second, merged], now=later, ended=finished_campaigns(root))
    assert _closeouts(after) == ["0002"]
    body = next(a["body"] for a in after if a["type"] == "create_issue")
    # its wall-clock ends where its work ended, not when the other close-out merged
    assert f"to the end of the work (`closeout:waiting:1`, {NOW}): " in body
    assert "The close-out then waited 21.0 hours for another campaign's close-out" in body
    # it is filed from main as it is now: the notes file's ids, the failure log's base
    assert f"## {later[:10]}: campaign 0002" in failure_log_section_of(body)


def test_an_open_closeout_holds_the_slot_until_it_merges_or_closes(tmp_path):
    root, first, second = _two_ready(tmp_path)
    open_pr = closeout_issue(merged=False)
    views = {
        v.campaign.id: v
        for v in (tick.view(c, snap([first, open_pr]), ctx(root)) for c in active_campaigns(root))
    }
    assert tick._closeout_open(views["0001"])
    closed = replace(open_pr, state="closed", pr=replace(open_pr.pr, state="closed"))
    v = tick.view(active_campaigns(root)[0], snap([first, closed]), ctx(root))
    assert not tick._closeout_open(v)
    # filed but not yet in the issue list: the `finished` event holds it
    filing = replace(
        first,
        comments=(
            Comment(BOT, "- x\n\n" + markers.ledger_marker("0001", ["started", "finished"]), NOW),
        ),
    )
    v = tick.view(active_campaigns(root)[0], snap([filing]), ctx(root))
    assert tick._closeout_open(v)


def test_the_oldest_end_of_work_files_first(tmp_path):
    """0002 has waited since yesterday; 0001 is ready only now. 0002 goes first."""
    root, first, second = _two_ready(tmp_path)
    events = ["started", "stopped"]
    began = Comment(BOT, "- x\n\n" + markers.ledger_marker("0002", events), "2026-11-09T01:00:00Z")
    waited = Comment(
        BOT,
        "- x\n\n" + markers.ledger_marker("0002", ["closeout:waiting:1"]),
        "2026-11-09T12:00:00Z",
    )
    second = replace(second, comments=(began, waited))
    actions = _decide(root, [first, second])
    assert _closeouts(actions) == ["0002"]
    (wait,) = _ledger_of(actions, 1)
    assert "waits for campaign 0002's close-out to merge" in wait.body


# -- stops by cause ---------------------------------------------------------------------


def _line(sid: str, detail: str, links: str = "#10") -> str:
    return f"- {sid}: **blocked**. Cause: {detail}. Needs you: x. ({links}) @{OWNER}"


def _comment(cid: str, lines: list[str], events: list[str], at: str) -> Comment:
    return Comment(BOT, "\n".join(lines) + "\n\n" + markers.ledger_marker(cid, events), at)


def test_stops_by_cause_count_what_needed_gabriel(tmp_path):
    """A needs-human block (answered by his label removal), a stall the tick restarted, a
    second stall it did not, a wait for main and a retry."""
    root = make_repo(tmp_path)
    comments = [
        _comment("0001", ["- x"], ["started", "s1:filed"], "2026-11-09T00:00:00Z"),
        _comment(
            "0001",
            [_line("s1", "an agent stopped and labelled it needs-human")],
            ["s1:blocked:aaaaaaaa"],
            "2026-11-09T02:00:00Z",
        ),
        _comment(
            "0001",
            ["- s1: the owner removed needs-human"],
            ["s1:restart:owner-20260909030000"],
            "2026-11-09T03:00:00Z",
        ),
        _comment("0001", ["- s1: unblocked."], ["s1:unblocked:aaaaaaaa"], "2026-11-09T03:00:00Z"),
        _comment(
            "0001",
            [_line("s1", "no pull request twelve hours after the build was started again")],
            ["s1:blocked:bbbbbbbb"],
            "2026-11-09T15:00:00Z",
        ),
        _comment("0001", ["- s1: restarting"], ["s1:restart:bbbbbbbb"], "2026-11-09T15:00:00Z"),
        _comment("0001", ["- s1: unblocked."], ["s1:unblocked:bbbbbbbb"], "2026-11-09T15:30:00Z"),
        _comment(
            "0001",
            [_line("s1", "no pull request twelve hours after the plan")],
            ["s1:blocked:cccccccc"],
            "2026-11-10T04:00:00Z",
        ),
        _comment("0001", ["- s1: unblocked."], ["s1:unblocked:cccccccc"], "2026-11-10T05:00:00Z"),
        _comment("0001", ["- s2: retrying"], ["s2:retry:1"], "2026-11-10T06:00:00Z"),
    ]
    t = tracking(comments, labels=("campaign", "campaign-stop"))
    w = Comment(
        "github-actions[bot]",
        "## Agent build: waiting for main (decision 0021)\n\nx\n\n"
        "<!-- agent-build-waiting-for-main: run 77 sha 0123456789ab "
        "tests tests/test_x.py::test_y -->",
        "2026-11-09T10:00:00Z",
    )
    issue = step_issue(root, [plan_comment(), w], labels=("campaign", "explore", "agent-build"))
    v = tick.view(
        active_campaigns(root)[0], snap([t, issue], now="2026-11-10T08:00:00Z"), ctx(root)
    )
    stops = tick.stop_facts(
        v, snap([t, issue], now="2026-11-10T08:00:00Z"), reason="the owner stopped it"
    )
    by = [(s.step, s.fact, s.cause, s.category, s.needed_you) for s in stops]
    assert ("s1", "block", "needs_human", "agent", True) in by
    assert ("s1", "block", "build_stalled_restarted", "handled", False) in by
    assert ("s1", "block", "build_stalled", "plumbing", True) in by
    assert ("s1", "restart", "restart_stalled", "handled", False) in by
    assert ("s1", "wait for main", "waiting_for_main", "plumbing", True) in by
    assert ("s2", "retry", "retry", "handled", False) in by
    # the owner's restart answered the needs-human block: not a second stop
    assert not [s for s in stops if s.fact == "unblock by you"]
    assert stop_counts(stops) == (3, 2)
    hours = {s.cause: s.hours for s in stops if s.fact in ("block", "wait for main")}
    assert hours["needs_human"] == 1.0 and hours["build_stalled"] == 1.0
    assert hours["waiting_for_main"] == pytest.approx(22.0)  # never restarted: until the end


def test_a_needs_human_after_a_second_wait_for_main_is_plumbing(tmp_path):
    root = make_repo(tmp_path)

    def wait(run: int, at: str) -> Comment:
        return Comment(
            "github-actions[bot]",
            "## Agent build: waiting for main (decision 0021)\n\nx\n\n"
            f"<!-- agent-build-waiting-for-main: run {run} sha 0123456789ab "
            "tests tests/t.py::test_a -->",
            at,
        )

    issue = step_issue(
        root, [plan_comment(), wait(1, "2026-11-09T02:00:00Z"), wait(2, "2026-11-09T05:00:00Z")]
    )
    comments = [
        _comment("0001", ["- x"], ["started", "s1:filed"], "2026-11-09T00:00:00Z"),
        _comment("0001", ["- s1: restart"], ["s1:restart:main-1"], "2026-11-09T03:00:00Z"),
        _comment(
            "0001",
            [_line("s1", "an agent stopped and labelled it needs-human")],
            ["s1:blocked:dddddddd"],
            "2026-11-09T05:10:00Z",
        ),
    ]
    t = tracking(comments, labels=("campaign", "campaign-stop"))
    s = snap([t, issue], now="2026-11-09T09:10:00Z")
    stops = tick.stop_facts(tick.view(active_campaigns(root)[0], s, ctx(root)), s)
    facts = [(x.fact, x.cause, x.hours) for x in stops]
    assert ("block", "needs_human_main", 4.0) in facts
    assert ("wait for main", "waiting_for_main", 1.0) in facts  # the first wait, restarted
    assert ("restart", "restart_main", None) in facts
    # the second wait is the block's cause, not one more stop
    assert sum(1 for f in facts if f[0] == "wait for main") == 1
    assert stop_counts(stops) == (2, 2)


def test_the_closeout_carries_stops_by_cause_and_the_tick_numbers(tmp_path):
    root = make_repo(tmp_path)
    comments = [
        _comment("0001", ["- x"], ["started", "s1:filed"], "2026-11-09T00:00:00Z"),
        _comment(
            "0001",
            [_line("s1", "no pull request twelve hours after the plan")],
            ["s1:blocked:cccccccc"],
            "2026-11-09T04:00:00Z",
        ),
    ]
    t = tracking(comments, labels=("campaign", "campaign-stop"))
    actions = _decide(root, [t, step_issue(root, [plan_comment()])], now="2026-11-09T06:00:00Z")
    body = next(a["body"] for a in actions if a["type"] == "create_issue")
    stops = body.split("## Stops by cause (written by the tick; copy as is)\n", 1)[1].split(
        "\n## ", 1
    )[0]
    assert "| s1 | block | no pull request in time after the build started (a stall): " in stops
    assert "| plumbing | yes | 2026-11-09T04:00:00Z | 2.0 |" in stops
    assert "`| 0001 | 2 | blocks | fix rounds | retries | hours | notes added | 1 | 1 |`" in body
    assert "Notes learn only from agent, spec and design stops." in body
    assert "A\n    plumbing or handled fact gives no agent note" in body
    section = failure_log_section_of(body)
    assert section.startswith("## 2026-11-09: campaign 0001 (Count close races)")
    assert "1 plumbing stop, 2.0 hours lost." in section
    assert "| s1 | block | no pull request in time after the build started (a stall)" in section
    scope = body.split("## In scope", 1)[1].split("## Out of scope", 1)[0]
    assert f"- `{FAILURE_LOG_PATH}`: append the failure log section above at the end" in scope


def test_without_a_plumbing_stop_the_section_says_so(tmp_path):
    root = make_repo(tmp_path)
    c = active_campaigns(root)[0]
    text = failure_log_section(c, [Stop("s1", "fix round", "fix_round", "1")], "2026-11-24")
    assert text.endswith("No plumbing stop.")
    assert "fix round" not in text


# -- the failure log: append only ----------------------------------------------------------

LOG = (
    "# Failure log\n\nIntro.\n\n## 2026-11-24: the history so far\n\n"
    "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
)


def _closeout_pr(root: Path, section: str | None, head: str | None, files=None):
    c = active_campaigns(root)[0]
    body = f"x\n{markers.closeout_marker('0001')}"
    if section is not None:
        body = (
            "## Failure log section (written by the tick; append as is)\n\nAppend it.\n\n"
            f"~~~~markdown\n{section}\n~~~~\n\n{body}"
        )
    files = files or ("research/campaigns/0001-count/report.md", FAILURE_LOG_PATH)
    pr = replace(
        closeout_issue(merged=False).pr,
        issue_body=body,
        reviews=(Review("approve", SHA[:12], {}, NOW),),
        files=tuple(files),
        changes=tuple((f, "modified") for f in files),
        added_texts=((FAILURE_LOG_PATH, head),) if head is not None else (),
    )
    assert FAILURE_LOG_PATH in closeout_paths(c, root)
    return pr


def test_gate_lets_a_closeout_append_its_section(tmp_path):
    root = make_repo(tmp_path)
    (root / "harness").mkdir()
    (root / FAILURE_LOG_PATH).write_text(LOG, encoding="utf-8")
    section = "## 2026-11-25: campaign 0001 (Count close races)\n\nNo plumbing stop."
    pr = _closeout_pr(root, section, appended(LOG, section))
    assert evaluate(pr, ctx(root)).state == "success"


@pytest.mark.parametrize(
    ("head", "words"),
    [
        (
            lambda s: appended(LOG.replace("| 1 | 2 |", "| 1 | 3 |"), s),
            "earlier sections are never edited",
        ),
        (
            lambda s: appended(LOG, s.replace("No plumbing stop.", "Nothing went wrong.")),
            "earlier sections",
        ),
        (lambda s: LOG, "earlier sections are never edited"),
        (lambda s: s, "earlier sections are never edited"),
    ],
    ids=[
        "edits an earlier section",
        "rewrites its section",
        "appends nothing",
        "drops the history",
    ],
)
def test_gate_refuses_an_edit_of_the_failure_log(tmp_path, head, words):
    root = make_repo(tmp_path)
    (root / "harness").mkdir()
    (root / FAILURE_LOG_PATH).write_text(LOG, encoding="utf-8")
    section = "## 2026-11-25: campaign 0001 (Count close races)\n\nNo plumbing stop."
    result = evaluate(_closeout_pr(root, section, head(section)), ctx(root))
    assert result.state == "failure" and words in " ".join(result.details)


def test_gate_refuses_a_closeout_that_leaves_out_or_removes_the_log(tmp_path):
    root = make_repo(tmp_path)
    (root / "harness").mkdir()
    (root / FAILURE_LOG_PATH).write_text(LOG, encoding="utf-8")
    section = "## 2026-11-25: campaign 0001 (Count close races)\n\nNo plumbing stop."
    missing = _closeout_pr(root, section, None, files=("research/campaigns/0001-count/report.md",))
    result = evaluate(missing, ctx(root))
    assert result.state == "failure" and "must append its section" in result.description
    removed = replace(_closeout_pr(root, section, None), changes=((FAILURE_LOG_PATH, "removed"),))
    assert "may not be removed" in evaluate(removed, ctx(root)).description
    unread = _closeout_pr(root, section, None)
    assert "could not be read" in evaluate(unread, ctx(root)).description
    # an issue filed before the failure log: the log stays as it is
    old = _closeout_pr(root, None, appended(LOG, section))
    assert (
        "may change only by the section its issue carries" in evaluate(old, ctx(root)).description
    )
    untouched = _closeout_pr(root, None, None, files=("research/campaigns/0001-count/report.md",))
    assert evaluate(untouched, ctx(root)).state == "success"


def test_github_reader_reads_the_failure_log_of_a_closeout_pr():
    import base64

    text = "# Failure log\n\nné\n"
    answers = {
        "/pulls/41": {
            "head": {"ref": "agent/issue-40", "sha": SHA},
            "user": {"login": BOT},
            "state": "open",
        },
        "/pulls/41/files": [{"filename": FAILURE_LOG_PATH, "status": "modified"}],
        f"/commits/{SHA}/check-runs": {"check_runs": []},
        f"/commits/{SHA}/statuses": [],
        "/issues/41/comments": [],
        "/pulls/41/reviews": [],
        "/issues/40": {"body": f"x\n{markers.closeout_marker('0001')}", "title": "close out"},
        f"/contents/{FAILURE_LOG_PATH}": {
            "encoding": "base64",
            "content": base64.b64encode(text.encode("utf-8")).decode(),
        },
    }
    gh = FakeGitHub(answers)
    pr = gh.pull_request(41)
    assert pr.added_texts == ((FAILURE_LOG_PATH, text),)


# -- notes, the Scoreboard and the status page ---------------------------------------------


def test_next_note_id_never_reuses_a_removed_one(tmp_path):
    assert next_note_id(REPO) == "N014"  # N009 to N013 were removed; the intro names them
    (tmp_path / "research").mkdir()
    assert next_note_id(tmp_path) == "N001"
    (tmp_path / NOTES_PATH).write_text(
        "Removed: N041.\n\n## Notes\n\n- [N002] x\n", encoding="utf-8"
    )
    assert next_note_id(tmp_path) == "N042"


def test_plumbing_notes_were_removed_and_the_agents_note_kept():
    text = (REPO / NOTES_PATH).read_text(encoding="utf-8")
    notes = text.split("## Notes", 1)[1].split("## Scoreboard", 1)[0]
    assert "- [N008] (planner)" in notes  # #451: a flaky Poisson fit the agent wrote
    for nid in ("N009", "N010", "N011", "N012", "N013"):
        assert f"[{nid}]" not in notes


def test_the_scoreboard_rows_carry_the_stops():
    rows = {r["Campaign"]: r for r in closeout.read_scoreboard(REPO)}
    assert list(SCOREBOARD_HEADER[-2:]) == ["Stops for Gabriel", "Plumbing stops"]
    assert (rows["0013"]["Stops for Gabriel"], rows["0013"]["Plumbing stops"]) == ("3", "2")
    assert (rows["0014"]["Stops for Gabriel"], rows["0014"]["Plumbing stops"]) == ("3", "3")
    assert rows["0007"]["Plumbing stops"] == "n/a"


def test_status_page_shows_the_stops_of_the_last_five_campaigns(tmp_path):
    assert status.stops_line(REPO) == (
        "Stops for you, last 5 campaigns: 0010 0, 0011 0, 0012 0, 0013 3 (2 plumbing), "
        "0014 3 (3 plumbing)"
    )
    assert status.stops_line(tmp_path) == ""
    root = make_repo(tmp_path / "r")
    (root / NOTES_PATH).write_text(
        "## Notes\n\n## Scoreboard\n\n| " + " | ".join(SCOREBOARD_HEADER) + " |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 0001 | 2 | 1 | 0 | 0 | 3.0 | 0 | 1 | 0 |\n",
        encoding="utf-8",
    )
    page = tick.render_status_page(active_campaigns(root), snap([]), ctx(root), root)
    assert "## Recently closed\n\nStops for you, last 1 campaign: 0001 1" in page


def test_the_failure_log_starts_from_the_history():
    text = (REPO / FAILURE_LOG_PATH).read_text(encoding="utf-8")
    assert text.startswith("# Failure log\n")
    for words in (
        "#476",
        "#484",
        "#502",
        "#509",
        "#485",
        "#486",
        "#514",
        "#507, #508",
        "0008 s9",
        "0009 s5",
        "0011",
    ):
        assert words in text, words
    sections = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert sections == ["## 2026-11-24: the history so far (from Gabriel's notes of 22 November)"]
