"""The plumbing lane's bounds (decision 0020), checked on every pull request.

This file is owned in `.github/CODEOWNERS`: only Gabriel changes it. It checks
the lane's two files against the bounds the decision sets:

- `ops/limits.yaml` has exactly the eight keys, each a whole number inside its
  bound, and `ops/` holds no other file (point 2 (a) and point 3);
- `tests/conftest.py`, if it exists, names none of the words point 2 (b) bans,
  and its `pytest_configure` only registers markers; it is the only
  `conftest.py` in the repository.

The seed rule of point 2 (c) needs a diff against main, so it waits for the
session that lets agents open lane pull requests.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import yaml

from terrain.campaigns import limits

REPO = Path(__file__).resolve().parents[1]

# Decision 0020, point 3 (the last key amended 2026-11-24): key -> (minimum, maximum).
# Written here as well as in terrain.campaigns.limits, so a change to either one fails.
BOUNDS = {
    "plan_timeout_hours": (1, 6),
    "build_timeout_hours": (6, 24),
    "run_appear_timeout_hours": (1, 6),
    "record_timeout_hours": (1, 6),
    "ideation_timeout_hours": (1, 6),
    "fork_plan_timeout_hours": (2, 12),
    "max_auto_retries": (0, 3),
    "max_auto_build_restarts_per_step": (0, 2),
}

# Decision 0020, point 2 (b): names that never appear in tests/conftest.py.
BANNED = (
    "skip",
    "skipif",
    "xfail",
    "importorskip",
    "deselect",
    "collect_ignore",
    "collect_ignore_glob",
    "pytest_plugins",
    "setattr",
    "monkeypatch",
    "pytest_ignore_collect",
    "pytest_deselected",
    "pytest_pyfunc_call",
)
BANNED_PREFIXES = ("pytest_collection_", "pytest_runtest_", "pytest_report_")
_BANNED_WORD = re.compile(
    r"\b(?:"
    + "|".join(re.escape(n) for n in BANNED)
    + "|"
    + "|".join(re.escape(p) + r"\w*" for p in BANNED_PREFIXES)
    + r")\b"
)
SKIP_DIRS = {".git", ".venv", "node_modules", "overleaf", "__pycache__"}


def repo_files() -> list[Path]:
    """Files git would commit (tracked, and untracked ones not ignored); without git,
    every file outside hidden and tool folders."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
            cwd=REPO,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8")
        return [Path(n) for n in out.split("\0") if n and (REPO / n).is_file()]
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        found += [Path(root, name).relative_to(REPO) for name in files]
    return found


def banned_in(source: str) -> list[str]:
    """The banned names that appear anywhere in `source` (code, strings or comments)."""
    return sorted(set(_BANNED_WORD.findall(source)))


def configure_problems(source: str) -> list[str]:
    """What `pytest_configure` does besides registering markers ([] if nothing)."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name != "pytest_configure":
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # its docstring
        for stmt in body:
            call = stmt.value if isinstance(stmt, ast.Expr) else None
            ok = (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "addinivalue_line"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "config"
                and len(call.args) == 2
                and not call.keywords
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "markers"
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)
            )
            if not ok:
                problems.append(f"line {stmt.lineno}: {ast.unparse(stmt)[:80]}")
    return problems


def test_the_bounds_match_the_code():
    assert limits.BOUNDS == BOUNDS


def test_the_limits_file_has_exactly_the_eight_keys_inside_their_bounds():
    data = yaml.safe_load((REPO / "ops" / "limits.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert sorted(data) == sorted(BOUNDS) and len(data) == 8
    for key, (low, high) in BOUNDS.items():
        value = data[key]
        assert type(value) is int, f"{key} is {value!r}, not a whole number"
        assert low <= value <= high, f"{key} is {value}, outside its bound {low} to {high}"
    # and the tick's own reader accepts it as it is
    assert limits.load(REPO) == limits.Limits(**data)


def test_ops_holds_no_other_file():
    in_ops = sorted(p.as_posix() for p in repo_files() if p.parts[0] == "ops")
    assert in_ops == ["ops/limits.yaml"]


def test_tests_conftest_is_the_only_conftest():
    found = sorted(p.as_posix() for p in repo_files() if p.name == "conftest.py")
    assert found in ([], ["tests/conftest.py"]), found


def test_tests_conftest_names_nothing_banned_and_only_registers_markers():
    path = REPO / "tests" / "conftest.py"
    if not path.is_file():
        return
    source = path.read_text(encoding="utf-8")
    assert banned_in(source) == []
    assert configure_problems(source) == []


def test_the_conftest_checks_catch_what_they_ban():
    for bad in (
        "import pytest\nskip = pytest.mark.skip\n",
        "def f(monkeypatch):\n    pass\n",
        "collect_ignore = ['x']\n",
        "def pytest_collection_modifyitems(items):\n    pass\n",
        "def pytest_runtest_setup(item):\n    pass\n",
        "def pytest_report_teststatus(report):\n    pass\n",
        "x = getattr(object, 'setattr', None)\n",
        "pytest_plugins = ['p']\n",
    ):
        assert banned_in(bad), bad
    fine = (
        'def pytest_configure(config):\n    """Markers."""\n'
        '    config.addinivalue_line("markers", "slow: a slow test")\n'
    )
    assert banned_in(fine) == [] and configure_problems(fine) == []
    for bad in (
        "def pytest_configure(config):\n    config.option.x = 1\n",
        'def pytest_configure(config):\n    config.addinivalue_line("filterwarnings", "x")\n',
        "def pytest_configure(config):\n    import os\n",
    ):
        assert configure_problems(bad), bad
