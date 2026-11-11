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


def test_parked_status_is_accepted(tmp_path):
    assert vr.validate(make_tree(tmp_path, idea(status="parked"))) == []


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


# -- research/agent-notes.md --------------------------------------------------

NOTES_HEAD = "# Agent notes\n\nAdvice, not rules.\n\n## Notes\n\n"
BOARD = (
    "\n## Scoreboard\n\n"
    "| Campaign | Steps | Blocks | Fix rounds | Retries | Hours from start to finish "
    "| Notes added |\n| --- | --- | --- | --- | --- | --- | --- |\n"
)
ROW = "| 0007 | 5 | 2 | 1 | 0 | 30.5 | 1 |\n"


def note(nid="N001", role="planner", advice="List the test file next to the script it tests."):
    return (
        f"- [{nid}] ({role}) {advice} From: campaign 0007, plan withheld for a missing "
        "test file. Added 2026-11-20.\n"
    )


def notes_tree(root: Path, notes: str = "", rows: str = ROW) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    make_tree(root)
    (root / "research" / "campaigns" / "0007-x").mkdir(parents=True)
    (root / "research" / "campaigns" / "0007-x" / "campaign.md").write_text("x", encoding="utf-8")
    (root / "research" / "agent-notes.md").write_text(
        NOTES_HEAD + notes + BOARD + rows, encoding="utf-8"
    )
    return root


def test_real_agent_notes_exist_and_validate():
    assert (REPO / vr.NOTES_PATH).is_file()
    assert vr.check_agent_notes(REPO) == []


def test_agent_notes_valid(tmp_path):
    assert vr.validate(notes_tree(tmp_path, note() + note("N002", "reviewer"))) == []
    # the empty starting file: no notes, no rows
    assert vr.validate(notes_tree(tmp_path / "e", rows="")) == []


NOTE_CASES = [
    ("not a note", "- a loose line\n", "line 7 is not in the shape"),
    ("bad role", note(role="tick"), "note N001 has role 'tick'"),
    ("long advice", note(advice="Do " + "x" * 200 + "."), "note N001 advice is 204 characters"),
    ("two sentences", note(advice="Read it. Then plan."), "note N001 advice must be one sentence"),
    ("duplicate id", note() + note(), "note N001 has a duplicate id"),
    ("bad date", note().replace("2026-11-20", "2026-13-01"), "note N001 'Added' is not a valid"),
]


@pytest.mark.parametrize(("name", "notes", "message"), NOTE_CASES, ids=[c[0] for c in NOTE_CASES])
def test_each_agent_note_problem_is_caught(tmp_path, name, notes, message):
    problems = vr.validate(notes_tree(tmp_path, notes))
    assert len(problems) == 1, problems
    assert message in problems[0]


@pytest.mark.parametrize("word", vr.NOTE_BANNED)
def test_agent_notes_refuse_banned_words_in_any_case(tmp_path, word):
    for i, variant in enumerate((word, word.upper(), word.title())):
        advice = f"Check the {variant} item before planning."
        problems = vr.validate(notes_tree(tmp_path / str(i), note("N004", advice=advice)))
        assert problems == [
            f"research/agent-notes.md: note N004 contains '{word}', which a note may not mention"
        ]


def test_agent_notes_at_most_thirty(tmp_path):
    notes = "".join(note(f"N{i:03d}") for i in range(1, 32))
    assert vr.validate(notes_tree(tmp_path, notes)) == [
        "research/agent-notes.md: 31 notes; at most 30"
    ]
    assert vr.validate(notes_tree(tmp_path / "ok", notes.rsplit("- [N031]", 1)[0])) == []


SCOREBOARD_CASES = [
    ("no headings", None, "needs exactly the headings"),
    ("bad header", BOARD.replace("Retries", "Reruns") + ROW, "must have the header"),
    ("twice", BOARD + ROW + ROW, "campaign 0007 appears twice"),
    ("unknown campaign", BOARD + ROW.replace("0007", "0009"), "no such campaign"),
    ("not a number", BOARD + ROW.replace("| 5 |", "| five |"), "'Steps' must be a whole number"),
    ("bad hours", BOARD + ROW.replace("30.5", "about 30"), "hours must be a number"),
    ("too many added", BOARD + ROW.replace("| 1 |\n", "| 4 |\n"), "notes added must be 0 to 3"),
    ("short row", BOARD + "| 0007 | 5 |\n", "needs 7 cells"),
]


@pytest.mark.parametrize(
    ("name", "tail", "message"), SCOREBOARD_CASES, ids=[c[0] for c in SCOREBOARD_CASES]
)
def test_each_scoreboard_problem_is_caught(tmp_path, name, tail, message):
    root = notes_tree(tmp_path)
    text = "# Agent notes\n" if tail is None else NOTES_HEAD + tail
    (root / "research" / "agent-notes.md").write_text(text, encoding="utf-8")
    problems = vr.validate(root)
    assert len(problems) == 1, problems
    assert message in problems[0]


def test_a_note_needs_its_campaigns_scoreboard_row(tmp_path):
    problems = vr.validate(notes_tree(tmp_path, note(), rows=""))
    assert problems == [
        "research/agent-notes.md: note N001 cites campaign 0007, which has no Scoreboard row"
    ]
