"""Decision 0021, build side: the quote check, waiting for main, and the two comments.

All offline. The comment formats are an interface read by the tick (session D2),
so they are compared byte for byte.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from terrain.campaigns import contradiction as c

REPO = Path(__file__).resolve().parents[1]

SOURCES = {
    "issue": "Done when:\n  3. `estimates.finite` is true\n  on the new table.",
    "plan": "Keep the parent's rule for\testimates.finite.",
    "review": "Must fix: keep   the parent's rule.",
    "AGENTS.md": "No check is ever loosened.",
}


def read(source):
    return SOURCES.get(source)


def quote(text, source="issue", level=3):
    return {"text": text, "source": source, "level": level}


def done(*resolved):
    return {"status": "done", "summary": "ok", "contradictions_resolved": list(resolved)}


def resolved(winner, loser, why="the parent's rule is stricter", tests=("tests/t.py::test_a",)):
    return {"winner": winner, "loser": loser, "why": why, "tests": list(tests)}


# --- the quote check ---------------------------------------------------------


def test_a_quote_found_word_for_word():
    assert c.quote_problem(quote("`estimates.finite` is true"), read) is None


def test_whitespace_differences_do_not_matter():
    # newlines and tabs in the source, runs of spaces in the quote
    assert (
        c.quote_problem(
            quote("Done when: 3.  `estimates.finite`\n is true on the new   table."), read
        )
        is None
    )
    assert c.quote_problem(quote("rule for estimates.finite.", "plan", 4), read) is None
    assert c.quote_problem(quote("keep the parent's rule.", "review", 5), read) is None


def test_a_quote_not_found_is_named():
    problem = c.quote_problem(quote("`estimates.finite` is false"), read)
    assert "is not word for word" in problem
    assert "estimates.finite" in problem and "issue" in problem


def test_case_and_wording_must_match():
    assert c.quote_problem(quote("No Check is ever loosened.", "AGENTS.md", 1), read)
    assert c.quote_problem(quote("No check is loosened.", "AGENTS.md", 1), read)


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "", "source": "issue", "level": 3},
        {"text": "   ", "source": "issue", "level": 3},
        {"text": "x" * 5001, "source": "issue", "level": 3},
        {"text": "No check", "source": "../AGENTS.md", "level": 1},
        {"text": "No check", "source": "/etc/passwd", "level": 1},
        {"text": "No check", "source": "a b", "level": 1},
        {"text": "No check", "source": "src/", "level": 1},
        {"text": "No check", "source": "AGENTS.md", "level": 0},
        {"text": "No check", "source": "AGENTS.md", "level": 7},
        {"text": "No check", "source": "AGENTS.md", "level": "1"},
        {"text": "No check", "source": "AGENTS.md", "level": True},
        {"text": "No check", "source": "AGENTS.md"},
        "No check",
        None,
    ],
)
def test_malformed_quotes_fail(bad):
    assert c.quote_problem(bad, read)


def test_an_unreadable_source_fails():
    assert "could not be read" in c.quote_problem(
        quote("x y", "research/decisions/9999-x.md", 1), read
    )


# --- the result: contradiction ------------------------------------------------


def contradiction(*quotes):
    return {"status": "contradiction", "summary": "s", "quotes": list(quotes)}


def test_exactly_two_quotes_are_required():
    a, b = quote("`estimates.finite` is true"), quote("No check is ever loosened.", "AGENTS.md", 1)
    for quotes in ([], [a], [a, b, a]):
        out = c.check_result(contradiction(*quotes), read, "77")
        assert out.kind == "blocked"
        assert f"{len(quotes)} quotes" in out.reason and "exactly two" in out.reason
    assert c.check_result({"status": "contradiction", "summary": "s"}, read, "77").kind == "blocked"
    assert c.check_result({"status": "contradiction", "quotes": "ab"}, read, "77").kind == "blocked"


def test_a_contradiction_with_two_good_quotes_carries_comment_c():
    a, b = quote("`estimates.finite` is true"), quote("No check is ever loosened.", "AGENTS.md", 1)
    out = c.check_result(contradiction(a, b), read, "4500")
    assert out.kind == "contradiction" and out.comment == c.render_contradiction([a, b], "4500")
    assert out.quotes == [a, b]


def test_a_failed_quote_makes_the_run_blocked_and_names_it():
    a, b = quote("`estimates.finite` is true"), quote("Loosen everything.", "AGENTS.md", 1)
    out = c.check_result(contradiction(a, b), read, "77")
    assert (
        out.kind == "blocked" and "Loosen everything." in out.reason and "AGENTS.md" in out.reason
    )
    assert out.comment == ""


def test_two_identical_quotes_are_not_a_contradiction():
    a = quote("`estimates.finite` is true")
    assert c.check_result(contradiction(a, dict(a)), read, "77").kind == "blocked"


def test_a_quote_that_looks_like_a_token_is_refused():
    sources = {**SOURCES, "issue": "use sk-ant-abc123 here"}
    a, b = quote("use sk-ant-abc123 here"), quote("No check is ever loosened.", "AGENTS.md", 1)
    out = c.check_result(contradiction(a, b), sources.get, "77")
    assert out.kind == "blocked" and "token" in out.reason


@pytest.mark.parametrize(
    "result", [None, [], "done", {"status": "blocked"}, {"status": "other"}, {}]
)
def test_unusable_results_are_blocked(result):
    assert c.check_result(result, read, "77").kind == "blocked"


# --- the result: done -------------------------------------------------------------


def test_done_without_contradictions_is_ok_and_has_no_section():
    for result in (
        {"status": "done", "summary": "s"},
        done(),
        {"status": "done", "contradictions_resolved": None},
    ):
        out = c.check_result(result, read, "77")
        assert out.kind == "ok" and out.section == ""


def test_done_with_a_resolved_contradiction_renders_the_pr_section():
    win = quote("No check is ever loosened.", "AGENTS.md", 1)
    lose = quote("`estimates.finite` is true")
    out = c.check_result(done(resolved(win, lose)), read, "77")
    assert out.kind == "ok"
    assert out.section == (
        "## Contradiction (decision 0021)\n"
        "\n"
        "The builder met instructions that cannot both hold, applied the winner and tested it.\n"
        "\n"
        "### Contradiction 1\n"
        "\n"
        "**Winner** (source: AGENTS.md, level 1):\n"
        "\n"
        "~~~~text\n"
        "No check is ever loosened.\n"
        "~~~~\n"
        "\n"
        "**Loser** (source: issue, level 3):\n"
        "\n"
        "~~~~text\n"
        "`estimates.finite` is true\n"
        "~~~~\n"
        "\n"
        "**Why it won** (higher level): the parent's rule is stricter\n"
        "\n"
        "**Tests written for the winner:**\n"
        "\n"
        "- `tests/t.py::test_a`\n"
    )


def test_same_level_is_named_the_stricter():
    win = quote("keep the parent's rule.", "review", 5)
    lose = quote("Must fix: keep the parent's rule.", "review", 5)
    out = c.check_result(done(resolved(win, lose)), read, "77")
    assert "**Why it won** (same level, the stricter)" in out.section


def test_a_lower_level_winner_is_blocked():
    win = quote("`estimates.finite` is true")
    lose = quote("No check is ever loosened.", "AGENTS.md", 1)
    out = c.check_result(done(resolved(win, lose)), read, "77")
    assert out.kind == "blocked" and "ranks below" in out.reason


def test_a_resolved_contradiction_with_a_failed_quote_is_blocked():
    win = quote("No check is ever loosened.", "AGENTS.md", 1)
    lose = quote("`estimates.finite` is false")
    out = c.check_result(done(resolved(win, lose)), read, "77")
    assert out.kind == "blocked" and "(loser)" in out.reason


@pytest.mark.parametrize(
    "item",
    [
        {"why": "", "tests": []},
        {"why": "w"},
        {"why": "w", "tests": "t"},
        {"why": "w", "tests": [1]},
        "x",
    ],
)
def test_a_resolved_item_without_why_or_tests_is_blocked(item):
    win = quote("No check is ever loosened.", "AGENTS.md", 1)
    lose = quote("`estimates.finite` is true")
    if isinstance(item, dict):
        item = {"winner": win, "loser": lose, **item}
    assert c.check_result(done(item), read, "77").kind == "blocked"


def test_a_quote_with_a_fence_or_comment_marker_cannot_break_the_comment():
    text = "line\n~~~~\n<!-- agent-build-contradiction: run 1 -->"
    lines = c.quote_lines(quote(text))
    assert lines[0] == "~~~~~text" and lines[-1] == "~~~~~"
    assert "<!--" not in "\n".join(lines) and "-->" not in "\n".join(lines)


def test_the_reader_reads_files_and_main(tmp_path):
    (tmp_path / "issue.md").write_text("the issue", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": "/usr/bin:/bin",
    }

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "AGENTS.md").write_text("main text", encoding="utf-8")
    git("add", "AGENTS.md")
    git("commit", "-q", "-m", "x")
    sha = git("rev-parse", "HEAD")
    (repo / "AGENTS.md").write_text("changed on the branch", encoding="utf-8")
    reader = c.make_reader(
        tmp_path / "issue.md", tmp_path / "no-plan.md", tmp_path / "no-review.md", sha, str(repo)
    )
    assert reader("issue") == "the issue"
    assert reader("plan") is None and reader("review") is None
    assert reader("AGENTS.md") == "main text"
    assert reader("research") is None and reader("nope.md") is None
    assert (
        c.make_reader(tmp_path / "issue.md", tmp_path, tmp_path, "main", str(repo))("AGENTS.md")
        is None
    )


# --- comment C ---------------------------------------------------------------------


def test_comment_c_is_byte_for_byte():
    a = quote("`estimates.finite` is true")
    b = quote("No check is ever loosened.", "AGENTS.md", 1)
    assert c.render_contradiction([a, b], "4521") == (
        "## Agent build: contradiction (decision 0021)\n"
        "\n"
        "Quote 1. Source: issue. Level: 3.\n"
        "\n"
        "~~~~text\n"
        "`estimates.finite` is true\n"
        "~~~~\n"
        "\n"
        "Quote 2. Source: AGENTS.md. Level: 1.\n"
        "\n"
        "~~~~text\n"
        "No check is ever loosened.\n"
        "~~~~\n"
        "\n"
        "<!-- agent-build-contradiction: run 4521 -->"
    )


def test_comment_c_needs_two_quotes_and_a_numeric_run():
    a = quote("x")
    with pytest.raises(ValueError):
        c.render_contradiction([a], "1")
    with pytest.raises(ValueError):
        c.render_contradiction([a, a], "1; rm")


# --- failing ids -------------------------------------------------------------------

PYTEST_LOG = """\
============================= test session starts ==============================
FAILED tests/test_a.py::test_one - assert 1 == 2
FAILED tests/test_a.py::TestK::test_two - AssertionError
FAILED tests/test_p.py::test_param[a-1] - ValueError: x - y
FAILED tests/test_p.py::test_param[x-y-2] - KeyError
FAILED tests/test_a.py::test_one - assert 1 == 2
ERROR tests/test_broken.py
FAILED tests/test_bare.py::test_bare
ERROR: usage: pytest [options]
=========== 4 failed, 1 error in 3.21s ===========
"""


def test_failing_ids_are_parsed_in_order_without_repeats():
    assert c.failing_ids(PYTEST_LOG) == [
        "tests/test_a.py::test_one",
        "tests/test_a.py::TestK::test_two",
        "tests/test_p.py::test_param[a-1]",
        "tests/test_p.py::test_param[x-y-2]",
        "tests/test_broken.py",
        "tests/test_bare.py::test_bare",
    ]


@pytest.mark.parametrize(
    "log",
    [
        "",
        "1 passed in 0.1s\n",
        "FAILED tests/test_p.py::test_param[a b] - x\n",  # a space in the id
        "FAILED tests/test_p.py::test_param[a,b] - x\n",  # a comma in the id
        "FAILED tests/test_p.py::test_param[a - x\n",  # an unclosed bracket
        "FAILED -x::y - no\n",  # looks like an option
        "FAILED tests/t.py::a-->b - no\n",
        "FAILED tests/test_x.py::test_a[<lambda>] - no\n",  # < and > are not in the tick's id class
        "FAILED tests/test_x.py::test_a[a>b] - no\n",  # would end the marker
        "FAILED tests/test_a.py::" + "t" * 200 + " - long\n",  # over 200 characters
        "FAILED tests/a.py::ok - x\nFAILED tests/t.py::t[a b] - y\n",  # one bad id spoils all
    ],
)
def test_unusable_failing_ids_give_none(log):
    assert c.failing_ids(log) is None


def test_an_id_of_exactly_200_characters_is_kept():
    node = "tests/" + "t" * 194
    assert len(node) == 200 and c.failing_ids(f"FAILED {node} - x\n") == [node]


# --- waiting for main ----------------------------------------------------------------

IDS = ["tests/test_a.py::test_one", "tests/test_p.py::test_param[a-1]"]
BOTH_FAIL = (
    "FAILED tests/test_a.py::test_one - x\n"
    "FAILED tests/test_p.py::test_param[a-1] - y\n"
    "FAILED tests/z.py::z - z\n"
)


def test_all_ids_fail_on_main_means_waiting():
    assert c.decide_waiting(IDS, BOTH_FAIL) == "waiting_for_main"


def test_one_id_passing_on_main_means_the_task_is_at_fault():
    assert c.decide_waiting(IDS, "FAILED tests/test_a.py::test_one - x\n2 failed\n") == "task_fault"


@pytest.mark.parametrize(
    "main_log",
    [
        "",
        "ERROR: not found: tests/test_new.py::test_x\n(no match in any of [<Module>])\n",
        "FAILED tests/t.py::t[a b] - x\n",
    ],
)
def test_nothing_usable_on_main_means_the_task_is_at_fault(main_log):
    assert c.decide_waiting(IDS, main_log) == "task_fault"


def test_no_ids_is_never_waiting():
    assert c.decide_waiting([], BOTH_FAIL) == "task_fault"


# --- comment W -------------------------------------------------------------------------


def test_comment_w_is_byte_for_byte():
    ids = ["tests/test_a.py::test_one", "tests/test_p.py::test_param[a-1]"]
    assert c.render_waiting(ids, "4600", "0123456789abcdef0123") == (
        "## Agent build: waiting for main (decision 0021)\n"
        "\n"
        "tests/test_a.py::test_one\n"
        "tests/test_p.py::test_param[a-1]\n"
        "\n"
        "<!-- agent-build-waiting-for-main: run 4600 sha 0123456789ab "
        "tests tests/test_a.py::test_one,tests/test_p.py::test_param[a-1] -->"
    )


@pytest.mark.parametrize(
    ("ids", "run", "sha"),
    [
        ([], "1", "0123456789ab"),
        (["a b"], "1", "0123456789ab"),
        (["a,b"], "1", "0123456789ab"),
        (["x" * 201], "1", "0123456789ab"),
        (["t"], "x", "0123456789ab"),
        (["t"], "1", "0123456789"),
        (["t"], "1", "ZZZZZZZZZZZZ"),
    ],
)
def test_comment_w_refuses_what_the_tick_could_not_read(ids, run, sha):
    with pytest.raises(ValueError):
        c.render_waiting(ids, run, sha)


# --- step outputs and the command line -----------------------------------------------------


def test_write_outputs_uses_a_block_for_multiline_values(tmp_path):
    out = tmp_path / "out"
    c.write_outputs(str(out), {"kind": "blocked", "reason": "a\nb"})
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "kind=blocked"
    name, _, delimiter = lines[1].partition("<<")
    assert name == "reason" and lines[2:] == ["a", "b", delimiter]


def run_cli(monkeypatch, tmp_path, *args):
    out = tmp_path / "gh-out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    code = c.main(list(args))
    return code, out.read_text(encoding="utf-8") if out.exists() else ""


def cli_files(tmp_path, result):
    for name, text in (("issue", SOURCES["issue"]), ("plan", SOURCES["plan"])):
        (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return [
        "check-result",
        "--result",
        str(tmp_path / "result.json"),
        "--issue",
        str(tmp_path / "issue.md"),
        "--plan",
        str(tmp_path / "plan.md"),
        "--review",
        str(tmp_path / "review.md"),
        "--base",
        "0" * 40,
        "--run",
        "9",
        "--section-out",
        str(tmp_path / "section.md"),
    ]


def test_cli_contradiction_fails_the_step_and_outputs_comment_c(tmp_path, monkeypatch, capsys):
    a = quote("`estimates.finite` is true")
    b = quote("Keep the parent's rule", "plan", 4)
    code, out = run_cli(monkeypatch, tmp_path, *cli_files(tmp_path, contradiction(a, b)))
    assert code == 1
    assert "kind=contradiction\n" in out and "contradiction_comment<<" in out
    assert "<!-- agent-build-contradiction: run 9 -->" in out and "fixable" not in out


def test_cli_blocked_is_fixable_from_main(tmp_path, monkeypatch, capsys):
    a = quote("not in the issue")
    code, out = run_cli(monkeypatch, tmp_path, *cli_files(tmp_path, contradiction(a, a)))
    assert code == 1 and "kind=blocked\n" in out and "fixable=fresh\n" in out


def test_cli_done_writes_the_section(tmp_path, monkeypatch, capsys):
    a = quote("`estimates.finite` is true")
    b = quote("Keep the parent's rule", "plan", 4)
    code, out = run_cli(monkeypatch, tmp_path, *cli_files(tmp_path, done(resolved(a, b))))
    assert code == 0 and out == "kind=ok\n"
    assert (
        (tmp_path / "section.md")
        .read_text(encoding="utf-8")
        .startswith("## Contradiction (decision 0021)\n")
    )


def test_cli_done_without_contradictions_writes_no_section(tmp_path, monkeypatch, capsys):
    code, out = run_cli(
        monkeypatch, tmp_path, *cli_files(tmp_path, {"status": "done", "summary": "s"})
    )
    assert code == 0 and not (tmp_path / "section.md").exists()


def test_cli_unreadable_result_is_blocked(tmp_path, monkeypatch, capsys):
    args = cli_files(tmp_path, {})
    (tmp_path / "result.json").write_text("not json", encoding="utf-8")
    code, out = run_cli(monkeypatch, tmp_path, *args)
    assert code == 1 and "kind=blocked" in out


def test_cli_failing_ids_decide_and_render(tmp_path, capsys):
    log = tmp_path / "task.log"
    log.write_text(PYTEST_LOG, encoding="utf-8")
    assert c.main(["failing-ids", str(log)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "tests/test_a.py::test_one" and len(printed) == 6
    log.write_text("1 passed\n", encoding="utf-8")
    assert c.main(["failing-ids", str(log)]) == 1

    ids = tmp_path / "ids.txt"
    ids.write_text("\n".join(IDS) + "\n", encoding="utf-8")
    main_log = tmp_path / "main.log"
    main_log.write_text(BOTH_FAIL, encoding="utf-8")
    assert c.main(["decide-waiting", "--ids", str(ids), "--main-log", str(main_log)]) == 0
    assert capsys.readouterr().out == "waiting_for_main\n"
    assert (
        c.main(["render-waiting", "--ids", str(ids), "--run", "5", "--sha", "0123456789abcdef"])
        == 0
    )
    assert capsys.readouterr().out.rstrip("\n") == c.render_waiting(IDS, "5", "0123456789abcdef")


def test_cli_render_waiting_can_write_step_outputs(tmp_path, monkeypatch):
    ids = tmp_path / "ids.txt"
    ids.write_text("\n".join(IDS) + "\n", encoding="utf-8")
    code, out = run_cli(
        monkeypatch,
        tmp_path,
        "render-waiting",
        "--ids",
        str(ids),
        "--run",
        "5",
        "--sha",
        "0123456789abcdef",
        "--github-output",
    )
    assert code == 0 and out.startswith("waiting=true\nwaiting_comment<<")
    assert c.render_waiting(IDS, "5", "0123456789abcdef") in out


# --- the workflow's inline scripts, run with fake gh and uv ------------------------------
#
# The scripts in agent-build.yml are not covered by the module's tests alone, so
# these run the real `run:` text of verify's pytest step, verify's run on main
# and report's step, with the helpers of tests/test_build_fix_round.py.

import importlib.util  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_spec = importlib.util.spec_from_file_location("tbfr", REPO / "tests" / "test_build_fix_round.py")
tbfr = importlib.util.module_from_spec(_spec)
sys.modules["tbfr"] = tbfr
_spec.loader.exec_module(tbfr)

MODULE = REPO / "src" / "terrain" / "campaigns" / "contradiction.py"
COMMENT_C = c.render_contradiction(
    [quote("`estimates.finite` is true"), quote("No check is ever loosened.", "AGENTS.md", 1)],
    "900",
)
COMMENT_W = c.render_waiting(IDS, "900", "0123456789abcdef")
needs_bash = pytest.mark.skipif(sys.platform == "win32", reason="the step scripts are bash")


def edited(calls):
    return [call for call in calls if call.startswith("issue edit")]


def dispatched(calls):
    return [call for call in calls if call.startswith("workflow run")]


@needs_bash
def test_report_posts_comment_c_without_needs_human_in_a_campaign(tmp_path):
    code, calls, body, stop = tbfr.run_report(tmp_path, CONTRADICTION_COMMENT=COMMENT_C, FIXABLE="")
    assert code == 0 and stop == ""
    assert body.rstrip("\n") == COMMENT_C
    assert body.splitlines()[0] == "## Agent build: contradiction (decision 0021)"
    assert body.splitlines()[-1] == "<!-- agent-build-contradiction: run 900 -->"
    assert not edited(calls) and not dispatched(calls)


@needs_bash
def test_report_posts_comment_c_and_adds_needs_human_outside_a_campaign(tmp_path):
    code, calls, body, _ = tbfr.run_report(
        tmp_path, CONTRADICTION_COMMENT=COMMENT_C, CAMPAIGN="false"
    )
    assert code == 0 and body.rstrip("\n") == COMMENT_C
    assert any("--add-label needs-human" in call for call in edited(calls))
    assert not dispatched(calls)


@needs_bash
def test_report_does_not_post_a_contradiction_that_looks_like_a_token(tmp_path):
    comment = COMMENT_C.replace("No check", "sk-ant-abc No check")
    code, calls, body, stop = tbfr.run_report(
        tmp_path, CONTRADICTION_COMMENT=comment, FIXABLE="fresh"
    )
    assert code == 0 and body == "" and "token" in stop
    assert not dispatched(calls)


@needs_bash
def test_report_posts_comment_w_without_fix_round_or_needs_human(tmp_path):
    code, calls, body, stop = tbfr.run_report(
        tmp_path, WAITING="true", WAITING_COMMENT=COMMENT_W, FAKE_EARLIER="0"
    )
    assert code == 0 and stop == "" and body.rstrip("\n") == COMMENT_W
    assert body.splitlines()[0] == "## Agent build: waiting for main (decision 0021)"
    assert not edited(calls) and not dispatched(calls)


@needs_bash
def test_the_second_wait_adds_needs_human_and_starts_no_round(tmp_path):
    code, calls, body, stop = tbfr.run_report(
        tmp_path, WAITING="true", WAITING_COMMENT=COMMENT_W, FAKE_EARLIER="1"
    )
    assert code == 0 and body == ""
    assert "second wait" in stop and "decision 0021" in stop
    assert any("--add-label needs-human" in call for call in edited(calls))
    assert not dispatched(calls)


@needs_bash
def test_a_failure_on_main_outside_a_campaign_is_handled_as_before(tmp_path):
    code, calls, body, stop = tbfr.run_report(
        tmp_path, WAITING="true", WAITING_COMMENT=COMMENT_W, CAMPAIGN="false", FAKE_EARLIER="0"
    )
    assert code == 0 and body == "" and "needs-human" in stop
    assert edited(calls)


@needs_bash
def test_without_waiting_or_contradiction_report_still_starts_the_fix_round(tmp_path):
    code, calls, body, _ = tbfr.run_report(tmp_path)
    assert code == 0 and body.startswith("## Agent build: fix round")
    assert dispatched(calls)


FAKE_UV_FAILING = """\
#!/usr/bin/env bash
case "$*" in
  "sync --locked" | "sync --locked --offline") exit 0 ;;
  "run ruff check ." | "run ruff format --check .") exit 0 ;;
  "run pytest") cat "${FAKE_DIR}/pytest-task.log"; exit 1 ;;
  "run pytest -- "*) cat "${FAKE_DIR}/pytest-main.log"; exit 1 ;;
esac
exit 3
"""


def fake_uv(tmp_path, task_log, main_log=""):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "uv").write_text(FAKE_UV_FAILING, encoding="utf-8")
    (bindir / "uv").chmod(0o755)
    (tmp_path / "pytest-task.log").write_text(task_log, encoding="utf-8")
    (tmp_path / "pytest-main.log").write_text(main_log, encoding="utf-8")
    (tmp_path / "contradiction.py").write_text(MODULE.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "FAKE_DIR": str(tmp_path),
        "RUN_ID": "900",
    }
    return env, out


def run_step(job, name, env, cwd):
    script = tbfr.step(job, name)["run"]
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, cwd=cwd, text=True)


@needs_bash
def test_verify_saves_the_failing_ids_when_pytest_fails(tmp_path):
    env, out = fake_uv(tmp_path, "FAILED tests/test_a.py::test_one - x\n1 failed\n")
    done = run_step("verify", "ruff check, ruff format --check, pytest", env, tmp_path)
    assert done.returncode == 1
    outputs = tbfr.read_outputs(out)
    assert outputs["pytest_ids"] == "true" and outputs["fixable"] == "bundle"
    assert (tmp_path / "failing-ids.txt").read_text(
        encoding="utf-8"
    ) == "tests/test_a.py::test_one\n"


@needs_bash
def test_verify_saves_no_ids_when_pytest_fails_without_a_usable_id(tmp_path):
    env, out = fake_uv(tmp_path, "FAILED tests/t.py::t[a b] - x\nINTERNALERROR\n")
    done = run_step("verify", "ruff check, ruff format --check, pytest", env, tmp_path)
    assert done.returncode == 1
    assert "pytest_ids" not in tbfr.read_outputs(out)
    assert (tmp_path / "failing-ids.txt").read_text(encoding="utf-8") == ""


def main_checkout(tmp_path):
    repo = tmp_path / "main-head"
    repo.mkdir()
    commit = [
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    ]
    for args in (["init", "-q", "-b", "main"], commit):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


@needs_bash
def test_all_failing_ids_failing_on_main_gives_waiting_for_main(tmp_path):
    env, out = fake_uv(tmp_path, "", main_log=BOTH_FAIL)
    (tmp_path / "failing-ids.txt").write_text("\n".join(IDS) + "\n", encoding="utf-8")
    repo = main_checkout(tmp_path)
    done = run_step("verify", "Run the failing tests on main", env, repo)
    assert done.returncode == 0, done.stderr
    outputs = tbfr.read_outputs(out)
    assert outputs["waiting"] == "true"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert outputs["waiting_comment"] == c.render_waiting(IDS, "900", head.strip())


@needs_bash
def test_an_id_passing_on_main_leaves_the_failure_with_the_task(tmp_path):
    env, out = fake_uv(tmp_path, "", main_log="FAILED tests/test_a.py::test_one - x\n")
    (tmp_path / "failing-ids.txt").write_text("\n".join(IDS) + "\n", encoding="utf-8")
    done = run_step("verify", "Run the failing tests on main", env, main_checkout(tmp_path))
    assert done.returncode == 0 and "waiting" not in tbfr.read_outputs(out)


@pytest.mark.parametrize(
    "node", ["tests/test_x.py::test_a[<lambda>]", "tests/t.py::t[a<b]", "tests/t.py::t[a>b]"]
)
def test_ids_with_angle_brackets_are_refused(node):
    assert not c.valid_node_id(node)
    with pytest.raises(ValueError):
        c.render_waiting([node], "1", "0123456789ab")
