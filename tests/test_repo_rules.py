"""Rules about the repository itself, checked on every PR.

Data lives in GCS, never in git; the only data allowed in the repository is
small text fixtures. These tests make that a failing check, not a convention.
"""

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "overleaf",
    "local",
    "_local",
    ".ruff_cache",
    ".pytest_cache",
    "__marimo__",
}
DATA_SUFFIXES = {
    ".parquet",
    ".csv",
    ".tsv",
    ".dta",
    ".sav",
    ".rds",
    ".xlsx",
    ".xls",
    ".zip",
    ".gz",
    ".tif",
    ".tiff",
    ".gpkg",
    ".shp",
    ".dbf",
    ".geojson",
    ".feather",
    ".pkl",
    ".npy",
}
FIXTURE_TEXT_SUFFIXES = {".csv", ".tsv", ".json", ".geojson", ".txt", ".md", ".xml"}
FIXTURE_MAX_BYTES = 200_000

REQUIRED = [
    "AGENTS.md",
    "README.md",
    "data/catalog.yaml",
    "research/questions.md",
    "research/lessons.md",
    "research/ideas/TEMPLATE.md",
    "confirm/specs/TEMPLATE.yaml",
]


def repo_files():
    """Files git would commit: tracked, plus untracked ones not ignored.

    Falls back to walking the tree when git is unavailable.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8")
        for name in out.split("\0"):
            if name and (REPO / name).is_file():
                yield Path(name)
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield Path(root, name).relative_to(REPO)


def test_required_files_exist():
    missing = [path for path in REQUIRED if not (REPO / path).is_file()]
    assert not missing, f"missing: {missing}"


def test_no_data_files_outside_fixtures():
    offenders = [
        str(path)
        for path in repo_files()
        if path.suffix.lower() in DATA_SUFFIXES and path.parts[:2] != ("data", "fixtures")
    ]
    assert not offenders, f"data files belong in GCS, not git: {offenders}"


def test_fixtures_are_small_text_files():
    fixtures = REPO / "data" / "fixtures"
    for path in fixtures.rglob("*"):
        if path.is_file() and path.name != ".gitkeep":
            assert path.suffix.lower() in FIXTURE_TEXT_SUFFIXES, f"{path}: fixtures must be text"
            assert path.stat().st_size <= FIXTURE_MAX_BYTES, f"{path}: fixture over 200 KB"


def test_split_hash_is_well_formed_if_sealed():
    path = REPO / "confirm" / "split.sha256"
    if path.exists():
        assert re.fullmatch(r"[0-9a-f]{64}\n?", path.read_text(encoding="utf-8")), (
            "split.sha256 must be one hash"
        )


def test_idea_files_follow_the_template():
    ideas = REPO / "research" / "ideas"
    for path in ideas.glob("[0-9][0-9][0-9][0-9]-*.md"):
        text = path.read_text(encoding="utf-8")
        for heading in ("## Claim", "## Prediction", "## Status"):
            assert heading in text, f"{path.name} lacks {heading}"


# Paths that must stay committable, and paths that must never be committed.
NOT_IGNORED = [
    "pipeline/acquire/x.py",
    "pipeline/build/x.py",
    "src/terrain/builds/x.py",
    "data/manifests/acquire/x.json",
    "data/manifests/build/x.json",
    "data/contracts/x.md",
    "data/reference/x.yaml",
    "data/fixtures/tse/x.csv",
    "confirm/ledger/x.jsonl",
    "explore/x.py",
    "harness/x.md",
]
IGNORED = ["data/x.parquet", "x.csv", "gha-creds-1.json", ".env", "key.pem", "build/x"]


def _ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path], cwd=REPO, capture_output=True
    )
    return result.returncode == 0


def test_gitignore_keeps_project_paths_and_blocks_data():
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        import pytest

        pytest.skip("git is not available")
    wrongly_ignored = [p for p in NOT_IGNORED if _ignored(p)]
    assert not wrongly_ignored, f".gitignore hides project paths: {wrongly_ignored}"
    not_blocked = [p for p in IGNORED if not _ignored(p)]
    assert not not_blocked, f".gitignore lets these through: {not_blocked}"


def test_text_files_are_read_and_written_with_an_explicit_encoding():
    """Windows defaults to cp1252, so `write_text(s)` there corrupts accented
    text that a UTF-8 read then rejects. Every text read, write and open names
    its encoding (as a keyword, or as read_text's first positional argument)."""
    import ast

    problems = []
    for root in ("src", "tests", "pipeline", "explore", "scripts"):
        for path in sorted((REPO / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                keywords = {k.arg for k in node.keywords}
                func = node.func
                where = f"{path.relative_to(REPO)}:{node.lineno}"
                if isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
                    positional = node.args[:1] if func.attr == "read_text" else node.args[1:2]
                    if "encoding" not in keywords and not positional:
                        problems.append(f"{where}: .{func.attr}() without an encoding")
                elif (
                    isinstance(func, ast.Name) and func.id == "open" and "encoding" not in keywords
                ):
                    mode = "r"
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        mode = str(node.args[1].value)
                    for k in node.keywords:
                        if k.arg == "mode" and isinstance(k.value, ast.Constant):
                            mode = str(k.value.value)
                    if "b" not in mode:
                        problems.append(f"{where}: open() in text mode without an encoding")
    assert not problems, "\n".join(problems)
