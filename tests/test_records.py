import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "validate_records", REPO / "scripts" / "validate_records.py"
)
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

IDEA = """---
id: "0001"
title: "{title}"
status: {status}
created: {created}
updated: {updated}
datasets: {datasets}
kill_criteria: {kill}
related: {related}
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

DEFAULTS = {
    "title": "An idea",
    "status": "proposed",
    "created": "2026-11-01",
    "updated": "2026-11-02",
    "datasets": "[ds_one]",
    "kill": '["Wrong sign"]',
    "related": '["0001"]',
}


def idea(**kw) -> str:
    return IDEA.format(**{**DEFAULTS, **kw})


def make_tree(root: Path, idea_text: str | None = None, extra=None) -> Path:
    (root / "data").mkdir()
    (root / "data" / "catalog.yaml").write_text("datasets:\n  - name: ds_one\n", encoding="utf-8")
    ideas = root / "research" / "ideas"
    decisions = root / "research" / "decisions"
    ideas.mkdir(parents=True)
    decisions.mkdir(parents=True)
    (ideas / "0001-an-idea.md").write_text(idea_text or idea(), encoding="utf-8")
    (decisions / "0001-a-decision.md").write_text(DECISION, encoding="utf-8")
    for rel, text in (extra or {}).items():
        (root / rel).write_text(text, encoding="utf-8")
    return root


def test_real_records_validate():
    assert vr.validate(REPO) == []


def test_valid_tree_has_no_problems(tmp_path):
    assert vr.validate(make_tree(tmp_path)) == []
    assert vr.main([str(tmp_path)]) == 0


CASES = [
    ("no front matter", "# Just a heading\n", "missing front matter"),
    ("bad status", idea(status="maybe"), "bad status"),
    (
        "id mismatch",
        idea().replace('id: "0001"', 'id: "0007"'),
        "does not match file name",
    ),
    ("bad date", idea(created="2026-13-45"), "not a valid YYYY-MM-DD"),
    ("updated before created", idea(updated="2026-10-01"), "before 'created'"),
    ("unknown dataset", idea(datasets="[nope]"), "unknown dataset"),
    ("unknown related", idea(related='["0099"]'), "unknown related id"),
    ("empty kill criteria", idea(kill="[]"), "kill_criteria"),
]


@pytest.mark.parametrize(("name", "text", "message"), CASES, ids=[c[0] for c in CASES])
def test_each_problem_is_caught(tmp_path, capsys, name, text, message):
    make_tree(tmp_path, text)
    problems = vr.validate(tmp_path)
    assert len(problems) == 1
    assert message in problems[0]
    assert vr.main([str(tmp_path)]) == 1
    assert message in capsys.readouterr().out


def test_duplicate_title_is_caught(tmp_path):
    make_tree(
        tmp_path,
        idea(title="A decision"),  # same title as the decision record
    )
    problems = vr.validate(tmp_path)
    assert len(problems) == 1
    assert "duplicate title" in problems[0]
    assert vr.main([str(tmp_path)]) == 1


def test_unquoted_id_is_rejected(tmp_path):
    make_tree(tmp_path, idea().replace('id: "0001"', "id: 0001"))
    assert any("quoted" in p for p in vr.validate(tmp_path))
