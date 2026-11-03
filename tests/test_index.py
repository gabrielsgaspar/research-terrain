import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_index", REPO / "scripts" / "build_index.py")
bi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bi)

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


def test_committed_index_is_current():
    expected = bi.build(REPO)
    actual = (REPO / "research" / "INDEX.md").read_text(encoding="utf-8")
    assert actual == expected, "regenerate with scripts/build_index.py; expected:\n" + expected


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
