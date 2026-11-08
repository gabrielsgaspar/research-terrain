"""Which paths `.github/CODEOWNERS` gives to a person.

The gate never merges a pull request that touches an owned path, and the
ruleset on main requires a code owner's review for those paths, so the agent
App cannot merge them even if the gate were wrong.

Only the pattern forms this repository uses are supported: an optional
leading `/` (anchored at the root), a trailing `/` (a directory and
everything under it), `*` within one path segment and `**` across segments.
Anything else in the file is reported by `problems`, so a pattern that would
be read differently from GitHub fails CI instead of being ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CODEOWNERS = ".github/CODEOWNERS"
_ALLOWED = re.compile(r"^/?[A-Za-z0-9_.*\-/]+$")


def _to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    body = pattern.lstrip("/")
    directory = body.endswith("/")
    body = body.rstrip("/")
    out = ""
    i = 0
    while i < len(body):
        if body.startswith("**", i):
            out += ".*"
            i += 2
        elif body[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(body[i])
            i += 1
    prefix = "" if anchored else "(?:.*/)?"
    suffix = "/.*" if directory else "(?:/.*)?"
    return re.compile(f"^{prefix}{out}{suffix}$")


@dataclass(frozen=True)
class CodeOwners:
    rules: tuple[tuple[str, tuple[str, ...]], ...]
    problems: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> CodeOwners:
        rules: list[tuple[str, tuple[str, ...]]] = []
        problems: list[str] = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            pattern, owners = parts[0], tuple(parts[1:])
            if not _ALLOWED.match(pattern):
                problems.append(
                    f"{CODEOWNERS}:{n}: pattern '{pattern}' uses syntax the gate does not read"
                )
            if not owners:
                problems.append(f"{CODEOWNERS}:{n}: pattern '{pattern}' names no owner")
            rules.append((pattern, owners))
        return cls(tuple(rules), tuple(problems))

    @classmethod
    def from_repo(cls, root: Path) -> CodeOwners:
        path = root / CODEOWNERS
        if not path.is_file():
            return cls(())
        return cls.parse(path.read_text(encoding="utf-8"))

    def owners_of(self, path: str) -> tuple[str, ...]:
        """Owners of `path`: the last matching rule wins, as on GitHub."""
        found: tuple[str, ...] = ()
        for pattern, owners in self.rules:
            if _to_regex(pattern).match(path):
                found = owners
        return found

    def owned(self, path: str) -> bool:
        return bool(self.owners_of(path))
