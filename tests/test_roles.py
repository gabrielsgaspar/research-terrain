"""harness/roles/ and scripts/role.py: the planner, builder, reviewer and ideation instructions.

The prompt bodies are pinned by SHA-256 below. They were moved unchanged from
the inline `prompt: |` blocks of the three agent workflows. Changing a role
file means changing its hash here too, on purpose.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
ROLES = REPO / "harness" / "roles"

SPEC = importlib.util.spec_from_file_location("role_loader", REPO / "scripts" / "role.py")
role_py = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(role_py)

# role: (workflow file, job, Claude step name, model, max_turns, SHA-256 of the body)
EXPECTED = {
    "planner": (
        "agent-plan.yml",
        "plan",
        "Plan",
        "claude-opus-5-5",
        "40",
        "46d2e7c9b4733d619cf2852c12f7f22af426bbec46614aa4a3b5d15c6aa26d25",
    ),
    "builder": (
        "agent-build.yml",
        "build",
        "Build",
        "claude-sonnet-5-5",
        "160",
        "cf480c40b42188dd58c89f10c097072d4440d18a4576c83fe0cd7b22eec2e98d",
    ),
    "reviewer": (
        "agent-review.yml",
        "review",
        "Review",
        "claude-opus-5-5",
        "50",
        "4aa735da90073e9ddf75dd3b874a0c1d53d30fb82c5fec9f4d1c741ca7f79544",
    ),
    "ideation": (
        "campaign-ideate.yml",
        "ideate",
        "Ideate",
        "claude-opus-5-5",
        "40",
        "ac0292130b951ad66d68ce316254785010280fbb35a7bac24d52c13355fe1b3d",
    ),
}

GOOD = """---
role: planner
model: claude-opus-5-5
max_turns: 40
workflow: .github/workflows/agent-plan.yml
notes:
  - A note.
---

You are the planner.
"""


def read_outputs(text: str) -> dict:
    """Parse a GITHUB_OUTPUT file the way the Actions runner does."""
    out, lines, i = {}, text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, delimiter = line.split("<<", 1)
            end = lines.index(delimiter, i + 1)
            out[key] = "\n".join(lines[i + 1 : end])
            i = end + 1
        elif "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
            i += 1
        else:
            i += 1
    return out


def claude_steps(role):
    file, job, name, *_ = EXPECTED[role]
    steps = yaml.safe_load((WORKFLOWS / file).read_text(encoding="utf-8"))["jobs"][job]["steps"]
    return steps, next(i for i, s in enumerate(steps) if s.get("name") == name)


# --- the real role files ----------------------------------------------------


@pytest.mark.parametrize("role", EXPECTED)
def test_role_body_is_pinned(role):
    body = role_py.load(role)["prompt"]
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == EXPECTED[role][5]


@pytest.mark.parametrize("role", EXPECTED)
def test_role_file_keeps_the_workflows_model_and_turn_limit(role):
    fields = role_py.load(role)
    file, _, _, model, turns, _ = EXPECTED[role]
    assert fields["role"] == role
    assert fields["workflow"] == f".github/workflows/{file}"
    assert (fields["model"], fields["max_turns"]) == (model, turns)


def test_builder_keeps_the_history_of_its_turn_limit():
    assert any(
        "max_turns was 100" in n and "42825610230" in n for n in role_py.load("builder")["notes"]
    )


def test_roles_folder_holds_exactly_the_four_roles_and_a_readme():
    assert sorted(p.name for p in ROLES.iterdir()) == [
        "README.md",
        "builder.md",
        "ideation.md",
        "planner.md",
        "reviewer.md",
    ]


@pytest.mark.parametrize("role", EXPECTED)
def test_outputs_round_trip_through_github_output(role, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert role_py.main([role]) == 0
    got = read_outputs(out.read_text(encoding="utf-8"))
    fields = role_py.load(role)
    assert got == {
        "model": fields["model"],
        "max_turns": fields["max_turns"],
        "prompt": fields["prompt"],
    }


def test_delimiter_never_occurs_in_the_prompt(monkeypatch):
    tokens = iter(["aa", "bb"])
    monkeypatch.setattr(role_py.secrets, "token_hex", lambda n: next(tokens))
    text = role_py.outputs(
        {"model": "claude-x-y", "max_turns": "1", "prompt": "see ROLE_PROMPT_aa\n"}
    )
    assert "prompt<<ROLE_PROMPT_bb\n" in text
    assert read_outputs(text)["prompt"] == "see ROLE_PROMPT_aa\n"


def test_without_github_output_it_prints_a_summary(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert role_py.main(["reviewer"]) == 0
    printed = capsys.readouterr().out
    assert "claude-opus-5-5" in printed and EXPECTED["reviewer"][5] in printed


# --- bad role files -----------------------------------------------------------


def test_a_good_file_loads(tmp_path):
    (tmp_path / "planner.md").write_text(GOOD, encoding="utf-8")
    fields = role_py.load("planner", tmp_path)
    assert fields["prompt"] == "You are the planner.\n"
    assert fields["notes"] == ["A note."]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (GOOD.replace("notes:\n  - A note.\n", "colour: blue\n"), "unknown front matter key"),
        (GOOD.replace("model: claude-opus-5-5\n", ""), "missing front matter key"),
        (GOOD.replace("max_turns: 40\n", ""), "missing front matter key"),
        (GOOD.replace("role: planner\n", ""), "missing front matter key"),
        (
            GOOD.replace("workflow: .github/workflows/agent-plan.yml\n", ""),
            "missing front matter key",
        ),
        (GOOD.replace("claude-opus-5-5", "gpt-5"), "does not match"),
        (GOOD.replace("claude-opus-5-5", "claude-opus 5 --tools x"), "does not match"),
        (GOOD.replace("claude-opus-5-5", "claude-ab"), "does not match"),
        (GOOD.replace("claude-opus-5-5", "Claude-Opus"), "does not match"),
        (GOOD.replace("max_turns: 40", "max_turns: 0"), "whole number from 1 to 200"),
        (GOOD.replace("max_turns: 40", "max_turns: 201"), "whole number from 1 to 200"),
        (GOOD.replace("max_turns: 40", "max_turns: 4.5"), "whole number from 1 to 200"),
        (GOOD.replace("max_turns: 40", "max_turns: -3"), "whole number from 1 to 200"),
        (GOOD.replace("max_turns: 40", "max_turns: forty"), "whole number from 1 to 200"),
        (GOOD.replace("You are the planner.\n", ""), "empty body"),
        (GOOD.replace("You are the planner.\n", "  \n\n"), "empty body"),
        (GOOD.replace("role: planner", "role: builder"), "expected 'planner'"),
        (
            GOOD.replace("agent-plan.yml", "agent-build.yml"),
            "expected '.github/workflows/agent-plan.yml'",
        ),
        (GOOD.replace("role: planner\n", "role: planner\nrole: planner\n"), "appears twice"),
        (GOOD.removeprefix("---\n"), "must start with"),
        (GOOD.replace("---\n\nYou", "\nYou"), "no closing"),
    ],
)
def test_bad_files_are_refused_and_nothing_is_written(text, message, tmp_path, monkeypatch, capsys):
    (tmp_path / "planner.md").write_text(text, encoding="utf-8")
    with pytest.raises(role_py.RoleError, match=message):
        role_py.load("planner", tmp_path)
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(role_py, "ROLES_DIR", tmp_path)
    assert role_py.main(["planner"]) == 1
    assert not out.exists()
    assert "not loaded" in capsys.readouterr().err


@pytest.mark.parametrize("role", ["designer", "../planner", "", "Planner"])
def test_an_unknown_role_is_refused(role, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    with pytest.raises(role_py.RoleError, match="Unknown role"):
        role_py.load(role)
    assert role_py.main([role]) == 1
    assert not out.exists()


def test_a_missing_file_is_refused(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(role_py, "ROLES_DIR", tmp_path)
    with pytest.raises(role_py.RoleError, match="No role file"):
        role_py.load("builder")
    assert role_py.main(["builder"]) == 1
    assert not out.exists()


# --- the workflows ------------------------------------------------------------


def test_no_workflow_has_an_inline_prompt_block():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not line.strip().startswith("prompt: |"), f"{path.name}: {line.strip()}"


@pytest.mark.parametrize("role", EXPECTED)
def test_each_claude_step_takes_its_prompt_model_and_turns_from_the_loader(role):
    steps, at = claude_steps(role)
    claude = steps[at]["with"]
    assert claude["prompt"] == "${{ steps.role.outputs.prompt }}"
    args = claude["claude_args"].splitlines()
    assert args[:2] == [
        "--model ${{ steps.role.outputs.model }}",
        "--max-turns ${{ steps.role.outputs.max_turns }}",
    ]
    assert sum(a.startswith(("--model", "--max-turns")) for a in args) == 2


@pytest.mark.parametrize("role", EXPECTED)
def test_the_loader_runs_for_its_own_role_after_the_checkout_and_before_claude(role):
    steps, at = claude_steps(role)
    loaders = [i for i, s in enumerate(steps) if "scripts/role.py" in str(s.get("run", ""))]
    assert len(loaders) == 1
    (i,) = loaders
    assert steps[i]["id"] == "role"
    assert steps[i]["run"].strip() == f"python3 -I scripts/role.py {role}"
    checkouts = [
        k for k, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts and checkouts[0] < i < at
    assert all(not (i < k < at) for k in checkouts)


def test_the_builder_loads_its_role_before_a_fix_round_switches_branch():
    steps, at = claude_steps("builder")
    loader = next(i for i, s in enumerate(steps) if s.get("id") == "role")
    branch = next(i for i, s in enumerate(steps) if s.get("id") == "branch")
    assert loader < branch < at


def test_other_workflows_do_not_call_the_loader():
    named = {v[0] for v in EXPECTED.values()}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name not in named:
            assert "scripts/role.py" not in path.read_text(encoding="utf-8"), path.name
