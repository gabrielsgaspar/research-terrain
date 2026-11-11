"""scripts/build_index.py: research/INDEX.md, built where it is read, never committed."""

import ast
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build_index.py"
_spec = importlib.util.spec_from_file_location("build_index", SCRIPT)
bi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bi)
_vspec = importlib.util.spec_from_file_location(
    "validate_records", REPO / "scripts" / "validate_records.py"
)
vr = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(vr)

IDEA = """---
id: "{id}"
title: "{title}"
status: {status}
created: 2026-11-01
updated: 2026-11-02
datasets: [ds_one, ds_two]
kill_criteria: ["Wrong sign"]
related: []
---

# body
"""

DECISION = """---
id: "0001"
title: "A decision"
status: accepted
date: 2026-11-01
supersedes: null
---

# body
"""


def make_tree(root: Path, lessons: str = "") -> Path:
    ideas = root / "research" / "ideas"
    decisions = root / "research" / "decisions"
    ideas.mkdir(parents=True)
    decisions.mkdir(parents=True)
    (ideas / "0001-first.md").write_text(
        IDEA.format(id="0001", title="First idea", status="proposed"), encoding="utf-8"
    )
    (decisions / "0001-a-decision.md").write_text(DECISION, encoding="utf-8")
    (root / "research" / "lessons.md").write_text(lessons, encoding="utf-8")
    return root


def test_new_idea_adds_a_row(tmp_path):
    make_tree(tmp_path)
    before = bi.ideas_table(tmp_path)
    (tmp_path / "research" / "ideas" / "0002-second.md").write_text(
        IDEA.format(id="0002", title="Second idea", status="dead"), encoding="utf-8"
    )
    after = bi.ideas_table(tmp_path)
    assert len(after.splitlines()) == len(before.splitlines()) + 1
    assert "| 0002 | [Second idea](ideas/0002-second.md) | dead |" in after
    assert "ds_one, ds_two" in after
    assert "Second idea" in bi.build(tmp_path)


def test_status_change_changes_output(tmp_path):
    make_tree(tmp_path)
    before = bi.build(tmp_path)
    (tmp_path / "research" / "ideas" / "0001-first.md").write_text(
        IDEA.format(id="0001", title="First idea", status="exploring"), encoding="utf-8"
    )
    after = bi.build(tmp_path)
    assert after != before
    assert "exploring" in after
    assert "proposed" not in after


def test_build_is_deterministic(tmp_path):
    make_tree(tmp_path)
    assert bi.build(tmp_path) == bi.build(tmp_path)
    assert bi.build(tmp_path).endswith("\n")
    assert not bi.build(tmp_path).endswith("\n\n")


def test_broken_record_is_skipped(tmp_path):
    make_tree(tmp_path)
    (tmp_path / "research" / "ideas" / "0003-broken.md").write_text("# no front\n", "utf-8")
    assert "0003" not in bi.ideas_table(tmp_path)


def test_only_ten_newest_lessons_and_no_template(tmp_path):
    lines = ["## YYYY-MM-DD: short title (idea NNNN, issue #N)", ""]
    for day in range(12, 0, -1):
        lines += [f"## 2026-10-{day:02d}: Lesson {day}, with punctuation", "", "text", ""]
    make_tree(tmp_path, "\n".join(lines))
    out = bi.lessons_list(tmp_path)
    assert len(out.splitlines()) == 10
    assert "short title" not in out
    assert "Lesson 12" in out
    assert "Lesson 3," in out
    assert "Lesson 2," not in out
    assert "(lessons.md#lesson-12-with-punctuation)" in out


def test_explore_runs_count_and_newest(tmp_path):
    make_tree(tmp_path)
    runs = tmp_path / "research" / "explore-runs" / "0001"
    runs.mkdir(parents=True)
    for name in ("900.md", "1500.md", "200.md"):
        (runs / name).write_text("run", encoding="utf-8")
    (runs / "1500.json").write_text("{}", encoding="utf-8")
    out = bi.explore_runs(tmp_path)
    assert "| 0001 | 3 | [1500](explore-runs/0001/1500.md) |" in out


def test_pipe_in_title_is_escaped(tmp_path):
    make_tree(tmp_path)
    (tmp_path / "research" / "ideas" / "0001-first.md").write_text(
        IDEA.format(id="0001", title="A | B", status="proposed"), encoding="utf-8"
    )
    assert "A \\| B" in bi.ideas_table(tmp_path)


def test_main_writes_the_file(tmp_path):
    make_tree(tmp_path)
    assert bi.main([str(tmp_path)]) == 0
    written = (tmp_path / "research" / "INDEX.md").read_text(encoding="utf-8")
    assert written == bi.build(tmp_path)


# --- built where it is read: plain python3, no project environment ----------


def plain_python() -> str:
    found = shutil.which("python3")
    if found is None:
        pytest.skip("python3 is not on PATH")
    return found


def run_builder(*args: str) -> subprocess.CompletedProcess:
    """The builder as the planner and reviewer workflows run it: `python3 -I`."""
    return subprocess.run(
        [plain_python(), "-I", str(SCRIPT), *args],
        cwd=REPO.parent,  # not the repository, so nothing is imported from it by accident
        capture_output=True,
        check=False,
    )


def test_builder_imports_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    outside = sorted(n for n in names if n not in sys.stdlib_module_names)
    assert outside == [], f"build_index.py imports outside the standard library: {outside}"


def test_python3_isolated_builds_a_small_tree(tmp_path):
    make_tree(tmp_path, "## 2026-10-01: A lesson\n")
    done = run_builder(str(tmp_path))
    assert done.returncode == 0, done.stderr.decode("utf-8")
    written = (tmp_path / "research" / "INDEX.md").read_text(encoding="utf-8")
    assert written == bi.build(tmp_path)
    assert "| 0001 | [First idea](ideas/0001-first.md) | proposed |" in written
    assert "- 2026-10-01: [A lesson](lessons.md#a-lesson)" in written


def test_python3_isolated_builds_this_repository():
    done = run_builder("--stdout")
    assert done.returncode == 0, done.stderr.decode("utf-8")
    out = done.stdout.decode("utf-8")
    assert out == bi.build(REPO)
    for path in sorted((REPO / "research" / "ideas").glob("0*.md")):
        assert f"(ideas/{path.name})" in out, path.name
    for path in sorted((REPO / "research" / "decisions").glob("0*.md")):
        assert f"(decisions/{path.name})" in out, path.name


def test_front_matter_reads_as_the_validator_reads_it():
    """The builder's small parser agrees with PyYAML on every field it shows."""
    keys = ("id", "title", "status", "updated", "datasets", "date")
    for folder in ("ideas", "decisions"):
        for path in sorted((REPO / "research" / folder).glob("0*.md")):
            mine = bi.parse_front_matter(path.read_text(encoding="utf-8"))
            theirs = vr.read_front_matter(path)
            assert isinstance(theirs, dict), path
            assert mine is not None, path
            for k in keys:
                if k in theirs:
                    assert mine.get(k) == theirs[k], (path.name, k)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\nid: \"0001\"\nt: 'it''s'\n---\n", {"id": "0001", "t": "it's"}),
        ("---\nds: [a, b]\nnone: []\nn: null\n---\n", {"ds": ["a", "b"], "none": [], "n": None}),
        (
            '---\nds:\n  - a\n  - "b, c"\nd: 2026-11-01\n---\n',
            {"ds": ["a", "b, c"], "d": "2026-11-01"},
        ),
        ('---\ntitle: "A: b? \\"c\\""\n---\n', {"title": 'A: b? "c"'}),
        ("---\nbudget:\n  max: 1\nid: x\n---\n", {"budget": None, "id": "x"}),
    ],
)
def test_parse_front_matter(text, expected):
    assert bi.parse_front_matter(text) == expected


@pytest.mark.parametrize("text", ["# no front\n", "---\nid: x\n", "---\nnot a key\n---\n"])
def test_parse_front_matter_refuses_what_it_cannot_read(text):
    assert bi.parse_front_matter(text) is None


# --- why dead and parked ideas ended ------------------------------------------

STATUS_LOG = """
## Status

- 2026-11-01: proposed. First line.
- 2026-11-09: parked. Wrapped over
  two lines.
- 2026-11-03: exploring, written later in the file but older.

## Log

- 2026-12-01: not a status line.
"""


def test_newest_status_line_is_the_latest_dated_item_on_one_line():
    assert bi.newest_status_line(STATUS_LOG) == "2026-11-09: parked. Wrapped over two lines."
    same_day = STATUS_LOG.replace("2026-11-03", "2026-11-09")
    assert bi.newest_status_line(same_day).startswith("2026-11-09: exploring, written later")
    assert bi.newest_status_line("## Status\n\nNo items.\n") == ""


def test_only_dead_and_parked_ideas_show_why_they_ended(tmp_path):
    make_tree(tmp_path)
    ideas = tmp_path / "research" / "ideas"
    for rid, status in (("0002", "dead"), ("0003", "parked"), ("0004", "promising")):
        text = IDEA.format(id=rid, title=f"Idea {rid}", status=status)
        (ideas / f"{rid}-x.md").write_text(text + STATUS_LOG, encoding="utf-8")
    (ideas / "0005-y.md").write_text(
        IDEA.format(id="0005", title="No log", status="dead"), encoding="utf-8"
    )
    out = bi.ended_ideas(tmp_path)
    why = "2026-11-09: parked. Wrapped over two lines."
    assert out.splitlines() == [
        f"- 0002, dead: {why} ([idea file](ideas/0002-x.md))",
        f"- 0003, parked: {why} ([idea file](ideas/0003-x.md))",
        "- 0005, dead: No Status line. ([idea file](ideas/0005-y.md))",
    ]
    assert "## Why dead and parked ideas ended" in bi.build(tmp_path)
    assert bi.ended_ideas(make_tree(tmp_path / "fresh")) == "None."


def test_every_dead_or_parked_idea_in_this_repository_says_why():
    out = bi.ended_ideas(REPO)
    for _, path, fm in bi.records(REPO, "ideas"):
        if fm.get("status") in ("dead", "parked"):
            line = next(ln for ln in out.splitlines() if f"(ideas/{path.name})" in ln)
            assert "No Status line." not in line, path.name


# --- not in git ----------------------------------------------------------------


def test_index_is_not_tracked_by_git():
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--", "research/INDEX.md"],
            cwd=REPO,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8")
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", "research/INDEX.md"],
            cwd=REPO,
            capture_output=True,
        ).returncode
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    assert tracked == "", "research/INDEX.md is generated on demand; remove it from git"
    assert ignored == 0, "research/INDEX.md must be listed in .gitignore"
