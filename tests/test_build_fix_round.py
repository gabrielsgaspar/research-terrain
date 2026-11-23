"""Decision 0019: task builds get one automatic fix round.

These tests run the scripts embedded in `.github/workflows/agent-build.yml`
and `campaign-tick.yml`, with fake `gh`, `uv` and GitHub API answers. Git runs
only in a repository built in tmp_path. Nothing here calls the network.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
HEAD = "b" * 40
ISSUE = "456"

needs_bash = pytest.mark.skipif(sys.platform == "win32", reason="the step scripts are bash")


def jobs(name: str = "agent-build.yml") -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["jobs"]


def step(job: str, name: str) -> dict:
    return next(s for s in jobs()[job]["steps"] if s.get("name") == name)


def heredoc(text: str, opening: str, end: str) -> str:
    start = text.index(opening) + len(opening)
    return textwrap.dedent(text[start : text.index(end, start)])


def read_outputs(path: Path) -> dict:
    """A GITHUB_OUTPUT file, parsed the way the Actions runner does."""
    out, lines, i = {}, path.read_text(encoding="utf-8").split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, delimiter = line.split("<<", 1)
            end = lines.index(delimiter, i + 1)
            out[key] = "\n".join(lines[i + 1 : end])
            i = end + 1
        else:
            if "=" in line:
                key, value = line.split("=", 1)
                out[key] = value
            i += 1
    return out


def run_python(script: str, env: dict, monkeypatch, cwd: Path | None = None) -> object:
    """Run an embedded Python script in this process; returns its exit code (None if 0)."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if cwd is not None:
        monkeypatch.chdir(cwd)
    try:
        exec(compile(script, "workflow step", "exec"), {"__name__": "__main__"})
    except SystemExit as stop:
        return stop.code or None
    return None


def marker(run: str = "900", head: str = HEAD) -> str:
    return f"<!-- agent-build-fix: run={run}{f' head={head}' if head else ''} -->"


def fix_comment(body: str, author: str = "github-actions[bot]", issue: str = ISSUE) -> dict:
    return {
        "user": {"login": author},
        "issue_url": f"https://api.github.com/repos/o/r/issues/{issue}",
        "body": body,
    }


# -- the workflow's shape ----------------------------------------------------------------


def test_only_the_prior_job_may_read_other_runs():
    all_jobs = jobs()
    prior = all_jobs["prior"]
    assert prior["permissions"] == {"actions": "read", "issues": "read"}
    assert prior["if"] == "github.event_name == 'workflow_dispatch'"
    # it runs no repository code: no checkout, and its artifact comes from a named run
    assert not any("actions/checkout" in s.get("uses", "") for s in prior["steps"])
    # the build job's token, which Claude can read, stays read-only and gets no actions scope
    assert all_jobs["build"]["permissions"] == {"contents": "read", "issues": "read"}
    assert all_jobs["build"]["needs"] == "prior"
    assert all_jobs["build"]["if"].startswith("${{ !cancelled() && ")
    assert all_jobs["report"]["permissions"] == {"issues": "write", "actions": "write"}
    assert all_jobs["verify"]["permissions"] == {"contents": "read"}


def test_a_labelled_build_runs_past_the_skipped_prior_job():
    """prior is skipped unless dispatched. A job with no `if` (an implicit success()) is
    skipped when any job before it in the needs chain was, so every job after prior must
    say when it runs. Builds 45238232851 and 45238246955 skipped verify and publish."""
    all_jobs = jobs()

    def before(name: str) -> set[str]:
        needs = all_jobs[name].get("needs", [])
        direct = {needs} if isinstance(needs, str) else set(needs)
        return direct.union(*(before(n) for n in direct)) if direct else set()

    after_prior = [n for n in all_jobs if "prior" in before(n)]
    assert sorted(after_prior) == ["build", "publish", "report", "verify"]
    for name in after_prior:
        cond = str(all_jobs[name].get("if", ""))
        assert cond.startswith(("${{ !cancelled() && ", "${{ always() && ")), name
    # verify and publish still run only after every job they need succeeded
    assert "needs.build.result == 'success'" in all_jobs["verify"]["if"]
    publish = all_jobs["publish"]["if"]
    assert all(f"needs.{n}.result == 'success'" in publish for n in ("build", "verify"))


def test_the_build_excludes_the_sandbox_placeholders():
    """sandbox-runtime's protected files and folders (Claude Code 2.1.330), decision 0019."""
    run = step("build", "Create the branch and write the issue and plan to files")["run"]
    start = run.index("printf '/%s\\n'")
    block = run[start : run.index(">> .git/info/exclude", start)]
    names = set(block.replace("\\", " ").split()) - {"printf", "'/%s\\n'"}
    runtime = {".gitconfig", ".gitmodules", ".bashrc", ".bash_profile", ".zshrc", ".zprofile"}
    runtime |= {".profile", ".ripgreprc", ".mcp.json", ".vscode", ".idea"}
    runtime |= {".claude/commands", ".claude/agents"}
    assert runtime <= names
    # never a path the repository tracks, which info/exclude would not hide anyway
    tracked = subprocess.run(
        ["git", "ls-files", *sorted(names)], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    assert tracked == ""


def test_verify_runs_every_check_it_ran_before():
    names = [s.get("name") or s.get("uses", "") for s in jobs()["verify"]["steps"]]
    checks = [
        "Scan every commit's metadata, file names and added lines for secrets",
        "Check every commit's paths against the plan",
        "Check that an automatic fix round keeps the tests",
        "ruff check, ruff format --check, pytest",
    ]
    assert [n for n in names if n in checks] == checks
    run = step("verify", "ruff check, ruff format --check, pytest")["run"]
    for command in ("uv sync --locked", "uv run ruff check .", "uv run ruff format --check ."):
        assert command in run
    assert "uv run pytest 2>&1" in run
    # none of them is skipped for a fix round
    for name in checks[:2] + checks[3:]:
        assert "if" not in step("verify", name)


# -- verify: the round keeps the first attempt's tests ------------------------------------


def git(cwd: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.test"]
    cmd += ["-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit(cwd: Path, files: dict[str, str | None], message: str) -> str:
    for path, text in files.items():
        if text is None:
            git(cwd, "rm", "-q", path)
        else:
            (cwd / path).parent.mkdir(parents=True, exist_ok=True)
            (cwd / path).write_text(text, encoding="utf-8")
            git(cwd, "add", path)
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


FIRST_TESTS = """\
def test_one():
    assert 1 + 1 == 2


def test_two():
    assert 2 * 2 == 4


class TestShape:
    def test_rows(self):
        assert len([1, 2]) == 2
"""


def plan_text(done_when: str = "- [ ] `uv run pytest` passes.", files=None) -> str:
    files = files or [{"path": "tests/test_new.py", "change": "add"}]
    return (
        "## Agent plan: Plan\n\n**Done when**\n" + done_when + "\n\n"
        f"<!-- agent-files: {json.dumps(files)} -->\n\n---\n_footer_\n"
    )


@pytest.fixture
def first_attempt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base = commit(repo, {"tests/test_old.py": "def test_old():\n    pass\n"}, "main")
    prior = commit(repo, {"tests/test_new.py": FIRST_TESTS, "src/x.py": "X = 1\n"}, "first")
    return repo, base, prior


def run_kept(repo, base, prior, monkeypatch, plan=None):
    script = heredoc(
        step("verify", "Check that an automatic fix round keeps the tests")["run"],
        "python3 -I - <<'EOF'\n",
        "\nEOF\n",
    )
    (repo.parent / "plan.md").write_text(plan or plan_text(), encoding="utf-8")
    out = repo.parent / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {
        "BASE_SHA": base,
        "PRIOR_HEAD": prior,
        "PLAN": str(repo.parent / "plan.md"),
        "GITHUB_OUTPUT": str(out),
    }
    code = run_python(script, env, monkeypatch, cwd=repo)
    return code, read_outputs(out)


def test_a_round_that_fixes_the_code_and_keeps_the_tests_passes(first_attempt, monkeypatch):
    repo, base, prior = first_attempt
    more = FIRST_TESTS.replace("2 * 2 == 4", "2 * 2 == 4.0") + "\n\ndef test_three():\n    pass\n"
    commit(repo, {"src/x.py": "X = 2\n", "tests/test_new.py": more}, "fix")
    code, out = run_kept(repo, base, prior, monkeypatch)
    assert code is None
    assert out["changed"] == "tests/test_new.py::test_two"
    # formatting alone is no change
    commit(
        repo, {"tests/test_new.py": more.replace("    assert 1 + 1", "    assert (1 + 1)")}, "fmt"
    )
    assert run_kept(repo, base, prior, monkeypatch)[1]["changed"] == "tests/test_new.py::test_two"


@pytest.mark.parametrize(
    "change, lost",
    [
        (FIRST_TESTS.replace("def test_two", "def helper_two"), "test_two"),
        (FIRST_TESTS.replace("def test_rows", "def test_cols"), "TestShape::test_rows"),
        (FIRST_TESTS.replace("def test_one", "@pytest.mark.skip\ndef _test_one"), "test_one"),
        (None, "TestShape::test_rows, test_one, test_two"),
    ],
)
def test_a_round_that_drops_a_first_attempt_test_fails(first_attempt, monkeypatch, change, lost):
    repo, base, prior = first_attempt
    commit(repo, {"tests/test_new.py": change}, "weaken")
    code, out = run_kept(repo, base, prior, monkeypatch)
    assert code == 1
    assert out["reason"].startswith("The automatic fix round dropped tests (decision 0019): ")
    assert f"lost the first attempt's tests {lost}" in out["reason"]


def test_a_test_file_that_no_longer_parses_fails(first_attempt, monkeypatch):
    repo, base, prior = first_attempt
    commit(repo, {"tests/test_new.py": "def test_one(:\n"}, "broken")
    code, out = run_kept(repo, base, prior, monkeypatch)
    assert code == 1 and '"tests/test_new.py" no longer parses as Python' in out["reason"]


def test_the_done_when_list_names_tests_that_must_exist(first_attempt, monkeypatch):
    repo, base, prior = first_attempt
    commit(repo, {"src/x.py": "X = 2\n"}, "fix")
    named = "- [ ] `tests/test_new.py::TestShape::test_rows` and `test_two` pass; `src/x.py` set."
    assert run_kept(repo, base, prior, monkeypatch, plan_text(named))[0] is None
    for missing, says in (
        ("- [ ] `tests/test_gone.py` covers it.", '"tests/test_gone.py", which does not exist'),
        ("- [ ] `tests/test_new.py::test_nine` passes.", '"tests/test_new.py::test_nine"'),
        ("- [ ] `test_nine` checks the sign.", "names test_nine, and no test file defines it"),
    ):
        code, out = run_kept(repo, base, prior, monkeypatch, plan_text(missing))
        assert code == 1 and says in out["reason"], missing
    # a file the plan deletes may be gone; text outside Done when is not read
    deleting = [{"path": "tests/test_gone.py", "change": "delete"}]
    plan = plan_text("- [ ] `tests/test_gone.py` is deleted.", deleting)
    assert run_kept(repo, base, prior, monkeypatch, plan)[0] is None
    plan = plan_text().replace("**Done when**", "**Steps**\n- `test_nine`\n\n**Done when**")
    assert run_kept(repo, base, prior, monkeypatch, plan)[0] is None


def test_a_fresh_round_checks_only_the_done_when_list(first_attempt, monkeypatch):
    repo, base, prior = first_attempt
    commit(repo, {"tests/test_new.py": None}, "fresh start drops it")
    code, out = run_kept(repo, base, "", monkeypatch)
    assert code is None and out["changed"] == "none"
    code, out = run_kept(repo, base, "", monkeypatch, plan_text("- [ ] `test_two` passes."))
    assert code == 1


# -- verify: the failing output for the comment --------------------------------------------


FAKE_UV = """\
#!/usr/bin/env bash
case "$*" in
  "sync --locked") exit 0 ;;
  "run ruff check .") echo "ruff check output"; exit "${RUFF_EXIT:-0}" ;;
  "run ruff format --check .") echo "formatted"; exit 0 ;;
  "run pytest")
    long="$(printf 'x%.0s' $(seq 1 400))"
    for i in $(seq 1 100); do printf 'line %s \\033[31mred\\033[0m %s\\n' "$i" "$long"; done
    exit 1 ;;
esac
exit 3
"""


def run_checks(tmp_path, ruff_exit: str = "0") -> tuple[int, dict]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(FAKE_UV, encoding="utf-8")
    (bindir / "uv").chmod(0o755)
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "RUFF_EXIT": ruff_exit,
    }
    script = step("verify", "ruff check, ruff format --check, pytest")["run"]
    done = subprocess.run(["bash", "-c", script], env=env, capture_output=True, cwd=tmp_path)
    return done.returncode, read_outputs(out)


@needs_bash
def test_a_failed_pytest_gives_its_last_60_lines(tmp_path):
    code, out = run_checks(tmp_path)
    assert code == 1
    assert (out["reason"], out["fixable"], out["check"]) == ("pytest failed.", "bundle", "pytest")
    lines = out["tail"].split("\n")
    assert len(lines) == 60 and lines[0].startswith("line 41 red xxx")
    assert lines[-1].startswith("line 100 red ")
    assert "\x1b" not in out["tail"] and max(len(line) for line in lines) == 300


@needs_bash
def test_a_failed_ruff_stops_before_pytest(tmp_path):
    code, out = run_checks(tmp_path, ruff_exit="1")
    assert code == 1
    assert (out["reason"], out["check"], out["tail"]) == (
        "ruff check failed.",
        "ruff check",
        "ruff check output",
    )


# -- report: start the round, or stop --------------------------------------------------------


FAKE_GH = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${FAKE_DIR}/calls.txt"
case "$1 $2" in
  "api --paginate") echo "${FAKE_EARLIER:-0}" ;;
  "api --method") cat > "${FAKE_DIR}/posted.json"; echo 777 ;;
  "workflow run") exit "${FAKE_DISPATCH:-0}" ;;
  "issue comment") cp "$5" "${FAKE_DIR}/stopped.md" ;;
  "issue edit") ;;
esac
"""


def run_report(tmp_path, **over) -> tuple[int, list[str], str, str]:
    """Run report's step with a fake gh: (exit code, gh calls, fix-round body, stop body)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    for name in ("calls.txt", "posted.json", "stopped.md"):
        (tmp_path / name).unlink(missing_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "FAKE_DIR": str(tmp_path),
        "GH_REPO": "o/r",
        "ISSUE": ISSUE,
        "REASON": "pytest failed.",
        "RUN_URL": "https://github.test/o/r/actions/runs/900",
        "RUN_ID": "900",
        "FIRST": "true",
        "CAMPAIGN": "true",
        "RETRY": "",
        "FIXABLE": "bundle",
        "CHECK": "pytest",
        "TAIL": "FAILED tests/test_new.py::test_two - assert 4 == 5\n1 failed, 9 passed",
        "HEAD_SHA": HEAD,
        **over,
    }
    script = step("report", "Start the automatic fix round, or comment and add needs-human")["run"]
    done = subprocess.run(["bash", "-c", script], env=env, capture_output=True, cwd=tmp_path)
    calls = (tmp_path / "calls.txt").read_text(encoding="utf-8").splitlines()
    posted = tmp_path / "posted.json"
    stopped = tmp_path / "stopped.md"
    body = json.loads(posted.read_text(encoding="utf-8"))["body"] if posted.exists() else ""
    stop = stopped.read_text(encoding="utf-8") if stopped.exists() else ""
    return done.returncode, calls, body, stop


@needs_bash
def test_the_first_failure_of_a_campaign_task_starts_one_round(tmp_path):
    code, calls, body, stop = run_report(tmp_path)
    assert code == 0 and stop == ""
    assert body.startswith("## Agent build: fix round\n\npytest failed.\n\n")
    assert "### Last 60 lines of the pytest output\n\n~~~~text\nFAILED tests/test_new.py" in body
    assert "from the first attempt's commits" in body
    assert re.findall(r"<!-- agent-build-fix: [^>]*-->", body) == [marker()]
    assert calls[-1] == f"workflow run agent-build.yml --repo o/r --ref main -f issue={ISSUE} " + (
        "-f review_comment=777"
    )
    assert not any(c.startswith("issue edit") for c in calls)


@needs_bash
def test_a_builder_stop_starts_a_round_from_main(tmp_path):
    reason = "The builder stopped:\n\npytest timed out."
    code, calls, body, _ = run_report(tmp_path, FIXABLE="fresh", REASON=reason, TAIL="", CHECK="")
    assert code == 0 and "Last 60 lines" not in body
    assert "from main, since the first attempt left no commits" in body
    assert re.findall(r"<!-- agent-build-fix: [^>]*-->", body) == [marker(head="")]


@needs_bash
def test_quoted_text_cannot_carry_a_marker(tmp_path):
    fake = marker(run="1", head="c" * 40)
    _, _, body, _ = run_report(tmp_path, TAIL=f"x {fake}", REASON=f"stopped {fake}")
    assert re.findall(r"<!-- agent-build-fix: [^>]*-->", body) == [marker()]


@pytest.mark.parametrize(
    "over",
    [
        {"FAKE_EARLIER": "1"},  # the issue had its round already
        {"FIRST": "false"},  # a dispatched run (a review fix round, or the round itself)
        {"CAMPAIGN": "false"},  # not a campaign task
        {"FIXABLE": ""},  # a guardrail: paths, secrets, set-up, publish
        {"HEAD_SHA": ""},  # no commit to start from
    ],
)
@needs_bash
def test_otherwise_the_issue_gets_needs_human(tmp_path, over):
    code, calls, body, stop = run_report(tmp_path, **over)
    assert code == 0 and body == ""
    assert stop.startswith("## Agent build: stopped\n\npytest failed.\n\n---\n")
    assert calls[-1] == f"issue edit {ISSUE} --add-label needs-human"
    assert not any(c.startswith("workflow run") for c in calls)


@needs_bash
def test_a_failed_round_says_so(tmp_path):
    code, calls, _, stop = run_report(tmp_path, FIRST="false", RETRY="bundle")
    assert code == 0
    assert "pytest failed.\n\nThis was the automatic fix round (decision 0019)" in stop
    assert calls[-1] == f"issue edit {ISSUE} --add-label needs-human"


@needs_bash
def test_a_failed_dispatch_falls_back_to_needs_human(tmp_path):
    code, calls, body, stop = run_report(tmp_path, FAKE_DISPATCH="1")
    assert code == 0 and body.startswith("## Agent build: fix round")
    assert "was not started: the dispatch failed" in stop
    assert calls[-1] == f"issue edit {ISSUE} --add-label needs-human"


# -- prior and build: reading the fix-round comment ---------------------------------------------


def run_prior(tmp_path, monkeypatch, comment: dict) -> tuple[object, dict]:
    script = heredoc(
        step("prior", "Find the first attempt that the fix-round comment names")["run"],
        "python3 -I - <<'PY'\n",
        "\nPY\n",
    )
    (tmp_path / "comment.json").write_text(json.dumps(comment), encoding="utf-8")
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {
        "COMMENT": str(tmp_path / "comment.json"),
        "INPUT_ISSUE": ISSUE,
        "GITHUB_OUTPUT": str(out),
    }
    return run_python(script, env, monkeypatch), read_outputs(out)


def test_prior_copies_only_for_a_round_from_commits(tmp_path, monkeypatch):
    body = f"## Agent build: fix round\n\nx\n\n{marker()}\n"
    assert run_prior(tmp_path, monkeypatch, fix_comment(body)) == (
        None,
        {"run": "900", "head": HEAD},
    )
    fresh = f"## Agent build: fix round\n\nx\n\n{marker(head='')}\n"
    assert run_prior(tmp_path, monkeypatch, fix_comment(fresh)) == (None, {})
    review = "## Agent review: Changes needed\n\nReviewed commit `abc1234`"
    assert run_prior(tmp_path, monkeypatch, fix_comment(review)) == (None, {})
    assert run_prior(tmp_path, monkeypatch, fix_comment(body, author="someone"))[0] == 1
    assert run_prior(tmp_path, monkeypatch, fix_comment(body, issue="457"))[0] == 1


def run_round(tmp_path, monkeypatch, comment: dict, prior_head: str = HEAD):
    run = step("build", "Resolve the issue and, for a fix round, the review")["run"]
    script = heredoc(
        run, "OUT=\"${RUNNER_TEMP}/agent-out/review.md\" python3 -I - <<'PY'\n", "\nPY\n"
    )
    (tmp_path / "review.json").write_text(json.dumps(comment), encoding="utf-8")
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {
        "REVIEW": str(tmp_path / "review.json"),
        "ISSUE_NUMBER": ISSUE,
        "OUT": str(tmp_path / "review.md"),
        "PRIOR_HEAD": prior_head,
        "GITHUB_OUTPUT": str(out),
    }
    code = run_python(script, env, monkeypatch)
    review = tmp_path / "review.md"
    return code, read_outputs(out), review.read_text(encoding="utf-8") if review.exists() else ""


def test_the_round_gives_the_builder_the_comment_as_data(tmp_path, monkeypatch):
    body = (
        "## Agent build: fix round\n\npytest failed.\n\n### Last 60 lines of the pytest output\n\n"
        f"~~~~text\nFAILED x\n~~~~\n\nThe first build failed.\n\n{marker()}\n\n---\n_footer_\n"
    )
    code, out, review = run_round(tmp_path, monkeypatch, fix_comment(body))
    assert code is None
    assert out == {"retry": "bundle", "prior_run": "900", "prior_head": HEAD}
    assert review.startswith("# Automatic fix round (from agent-build, decision 0019)\n\n")
    assert "pytest failed." in review and "FAILED x" in review
    assert "agent-build-fix" not in review and "_footer_" not in review
    fresh = body.replace(marker(), marker(head=""))
    assert (
        run_round(tmp_path, monkeypatch, fix_comment(fresh), prior_head="")[1]["retry"] == "fresh"
    )


def test_the_round_stops_if_the_first_commits_were_not_copied(tmp_path, monkeypatch, capsys):
    body = f"## Agent build: fix round\n\nx\n\n{marker()}\n"
    code, _, review = run_round(tmp_path, monkeypatch, fix_comment(body), prior_head="")
    assert code == 1 and review == ""
    assert "could not be copied into this run" in capsys.readouterr().out
    for bad in (fix_comment(body, author="someone"), fix_comment(body, issue="457")):
        assert run_round(tmp_path, monkeypatch, bad)[0] == 1


# -- the tick's act job: no duplicate task, and merges wait for checks -----------------------------


def act_script() -> str:
    text = (WORKFLOWS / "campaign-tick.yml").read_text(encoding="utf-8")
    return heredoc(text, "python3 -I - <<'PY'\n", "\n          PY\n")


def run_act(tmp_path, monkeypatch, actions, open_issues=(), merge_error=None):
    calls: list[tuple[str, str]] = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout=0):
        path = req.full_url.removeprefix("https://api.github.com/repos/o/r")
        calls.append((req.get_method(), path))
        if req.get_method() == "GET" and path.startswith("/issues?"):
            page = int(path.rsplit("page=", 1)[1])
            return Answer(json.dumps(list(open_issues)[(page - 1) * 100 : page * 100]).encode())
        if req.get_method() == "PUT" and merge_error:
            code, message = merge_error
            raise urllib.error.HTTPError(
                req.full_url, code, "Not Allowed", {}, io.BytesIO(json.dumps(message).encode())
            )
        if req.get_method() == "POST" and path == "/issues":
            return Answer(json.dumps({"number": 500}).encode())
        return Answer(b"")

    file = tmp_path / "actions.json"
    file.write_text(json.dumps(actions), encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    env = {"REPO": "o/r", "APP_TOKEN": "t", "APP_BOT": "terrain-agent[bot]", "ACTIONS": str(file)}
    return run_python(act_script(), env, monkeypatch), calls


STEP = "<!-- campaign-step: 0013/s5 -->"
FILE = {
    "type": "create_issue",
    "title": "Task: s5",
    "body": f"Do it.\n\n{STEP}\n",
    "labels": ["campaign", "explore"],
    "then_labels": ["agent-plan"],
}


def test_act_files_a_task_once(tmp_path, monkeypatch):
    twin = {"number": 456, "body": f"Do it.\n\n{STEP}\n"}
    code, calls = run_act(tmp_path, monkeypatch, [FILE], [twin])
    assert code is None and ("POST", "/issues") not in calls
    # another step, a pull request or a fork's marker for the same step id is no twin
    others = [
        {"number": 1, "body": "<!-- campaign-step: 0013/s50 -->"},
        {"number": 2, "body": STEP, "pull_request": {}},
        {"number": 3, "body": "<!-- campaign-step: 0014/s5 -->"},
    ]
    code, calls = run_act(tmp_path, monkeypatch, [FILE], others)
    assert code is None and calls[-2:] == [("POST", "/issues"), ("POST", "/issues/500/labels")]
    # the twin is found past the first page of open issues
    many = [{"number": n, "body": "x"} for n in range(1000, 1150)] + [twin]
    assert ("POST", "/issues") not in run_act(tmp_path, monkeypatch, [FILE], many)[1]


def test_act_checks_repairs_and_closeouts_too_but_not_other_issues(tmp_path, monkeypatch):
    repair = {**FILE, "body": "Fix.\n\n<!-- campaign-repair: 0013/s5/1 -->\n"}
    twin = {"number": 7, "body": repair["body"]}
    assert ("POST", "/issues") not in run_act(tmp_path, monkeypatch, [repair], [twin])[1]
    tracking = {**FILE, "body": "<!-- campaign-tracking: 0013 -->", "labels": ["campaign"]}
    code, calls = run_act(tmp_path, monkeypatch, [tracking], [twin])
    assert code is None and calls == [("POST", "/issues"), ("POST", "/issues/500/labels")]


MERGE = {"type": "merge", "pr": 470, "sha": "a" * 40}
RUNNING = {
    "message": (
        'Repository rule violations found\n\nRequired status check "test" is in progress.\n\n'
    ),
    "status": "405",
}


def test_act_waits_while_a_required_check_runs(tmp_path, monkeypatch, capsys):
    code, calls = run_act(tmp_path, monkeypatch, [MERGE], merge_error=(405, RUNNING))
    assert code is None and calls == [("PUT", "/pulls/470/merge")]
    assert "::notice::PR #470 waits for the next tick" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        (405, {"message": "Pull Request is not mergeable"}),
        (405, {"message": 'Required status check "test" is expected.'}),
        (409, {"message": "Head branch was modified."}),
        (403, RUNNING),
    ],
)
def test_act_still_fails_on_any_other_refusal(tmp_path, monkeypatch, capsys, error):
    code, _ = run_act(tmp_path, monkeypatch, [MERGE], merge_error=error)
    assert code == 1
    printed = capsys.readouterr().out
    assert "::error::merge failed" in printed and error[1]["message"][:20] in printed
