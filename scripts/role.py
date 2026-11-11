"""Load one agent role's instructions for its workflow.

    python3 -I scripts/role.py <role>

Reads harness/roles/<role>.md from the repository this script sits in and,
when GITHUB_OUTPUT is set, appends three step outputs to that file: `model`,
`max_turns` and `prompt` (the file's body, as a multi-line value). Without
GITHUB_OUTPUT it prints a short summary instead, for local use.

A role file is a small front matter between two `---` lines, a blank line,
then the body, which is the prompt exactly as the agent receives it:

    ---
    role: builder
    model: claude-sonnet-5-5
    max_turns: 160
    workflow: .github/workflows/agent-build.yml
    notes:
      - One line of history or explanation.
    ---

    You are the builder ...

Any problem stops the step with a clear message and writes nothing. The
model and turn limit go into claude_args, so they are checked against a
strict pattern first. Standard library only: workflows run this with the
runner's own python3, before any project dependency is installed.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = ROOT / "harness" / "roles"

# Each role and the one workflow that uses it.
WORKFLOWS = {
    "planner": ".github/workflows/agent-plan.yml",
    "builder": ".github/workflows/agent-build.yml",
    "reviewer": ".github/workflows/agent-review.yml",
}
REQUIRED = ("role", "model", "max_turns", "workflow")
OPTIONAL = ("notes",)
MODEL = re.compile(r"^claude-[a-z0-9-]{3,40}$")
TURNS = re.compile(r"^[0-9]+$")
MAX_TURNS = 200


class RoleError(Exception):
    """A role file that cannot be used; the message says why."""


def parse(text: str, role: str) -> dict:
    """Return the checked front matter of a role file, with its body as `prompt`."""
    if not text.startswith("---\n"):
        raise RoleError(f"{role}.md must start with a '---' line.")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise RoleError(f"{role}.md has no closing '---' line after its front matter.")
    head, body = text[4:end].split("\n"), text[end + 5 :]
    body = body.removeprefix("\n")

    fields: dict = {}
    key = None
    for line in head:
        if not line.strip():
            continue
        if line.startswith("  - ") and key == "notes":
            fields["notes"].append(line[4:].strip())
            continue
        match = re.fullmatch(r"([a-z_]+):(?: (.*))?", line)
        if not match:
            raise RoleError(f"{role}.md: front matter line not understood: {line!r}")
        key, value = match.group(1), (match.group(2) or "").strip()
        if key not in REQUIRED + OPTIONAL:
            raise RoleError(f"{role}.md: unknown front matter key {key!r}.")
        if key in fields:
            raise RoleError(f"{role}.md: front matter key {key!r} appears twice.")
        if key == "notes":
            if value:
                raise RoleError(f"{role}.md: notes must be a list of '  - ' lines.")
            fields["notes"] = []
        else:
            fields[key] = value
    missing = [k for k in REQUIRED if not fields.get(k)]
    if missing:
        raise RoleError(f"{role}.md: missing front matter key(s): {', '.join(missing)}.")

    if fields["role"] != role:
        raise RoleError(f"{role}.md says role {fields['role']!r}; expected {role!r}.")
    if fields["workflow"] != WORKFLOWS[role]:
        raise RoleError(
            f"{role}.md says workflow {fields['workflow']!r}; expected {WORKFLOWS[role]!r}."
        )
    if not MODEL.fullmatch(fields["model"]):
        raise RoleError(f"{role}.md: model {fields['model']!r} does not match {MODEL.pattern}.")
    if not TURNS.fullmatch(fields["max_turns"]) or not 1 <= int(fields["max_turns"]) <= MAX_TURNS:
        raise RoleError(
            f"{role}.md: max_turns {fields['max_turns']!r} "
            f"is not a whole number from 1 to {MAX_TURNS}."
        )
    if not body.strip():
        raise RoleError(f"{role}.md has an empty body: there is no prompt.")
    fields["prompt"] = body
    return fields


def load(role: str, roles_dir: Path | None = None) -> dict:
    """Read and check harness/roles/<role>.md."""
    if role not in WORKFLOWS:
        raise RoleError(f"Unknown role {role!r}; expected one of: {', '.join(WORKFLOWS)}.")
    path = (roles_dir or ROLES_DIR) / f"{role}.md"
    if not path.is_file():
        raise RoleError(f"No role file at {path}.")
    return parse(path.read_text(encoding="utf-8"), role)


def outputs(fields: dict) -> str:
    """The GITHUB_OUTPUT text: model, max_turns and the prompt under a random delimiter."""
    prompt = fields["prompt"]
    delimiter = f"ROLE_PROMPT_{secrets.token_hex(16)}"
    while delimiter in prompt:
        delimiter = f"ROLE_PROMPT_{secrets.token_hex(16)}"
    # The runner takes everything between the `prompt<<` line and the
    # newline before the delimiter line, so the added "\n" keeps the
    # prompt's own final newline.
    return (
        f"model={fields['model']}\n"
        f"max_turns={fields['max_turns']}\n"
        f"prompt<<{delimiter}\n{prompt}\n{delimiter}\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 -I scripts/role.py <planner|builder|reviewer>", file=sys.stderr)
        return 2
    role = argv[0]
    try:
        fields = load(role)
    except (RoleError, OSError, UnicodeDecodeError) as e:
        print(f"::error::Role {role!r} not loaded: {e}", file=sys.stderr)
        return 1
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8", newline="\n") as f:
            f.write(outputs(fields))
        print(f"Loaded harness/roles/{role}.md: {fields['model']}, {fields['max_turns']} turns.")
    else:
        digest = hashlib.sha256(fields["prompt"].encode("utf-8")).hexdigest()
        print(f"role:      {role}")
        print(f"model:     {fields['model']}")
        print(f"max_turns: {fields['max_turns']}")
        print(f"workflow:  {fields['workflow']}")
        print(f"prompt:    {len(fields['prompt'])} characters, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
