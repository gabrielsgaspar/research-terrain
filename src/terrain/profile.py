"""Row counts by category for the check a build failed: what a repair sees.

When a build check fails on real data, the error line says how many rows
failed ("2026: 2378 of 55898 recipient rows match no municipality") but not
why. The check counts the rows it examined by category, per period, and
calls `write_profile` before it raises; the build stops as before. The
`data-pipeline` workflow then runs the fixed script
`scripts/profile_failure.py`, which reads that file, checks it here and
prints it in the job log between `BEGIN` and `END`. The campaign tick copies
it from there into the repair task (decision 0016).

A profile holds counts and nothing else, never a value or an identifier:
- the check's name is a code label (`NAME`);
- each category comes from the fixed list `CATEGORIES`;
- each period is a year, a year and month, or "all";
- each count is a whole number of rows.

Anything else is refused, here when the build writes it, in the fixed
script when it prints it, and in the tick when it reads the log.

`text_category` sorts a raw text cell into "empty", "placeholder" or None,
for checks that want to tell missing values apart from bad ones.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path

ENV = "TERRAIN_PROFILE_OUT"  # where the build writes its profile; unset: nothing is written

# The only categories a profile may name, with what each means.
CATEGORIES: Mapping[str, str] = {
    "ok": "passes the check",
    "empty": "null, empty or only spaces",
    "placeholder": "a no-information placeholder (PLACEHOLDERS), such as 'Sem informação'",
    "unparseable": "cannot be read as the column's type",
    "out_of_range": "read, but outside the allowed range",
    "outside_window": "a date outside the build's window",
    "not_in_reference": "a key that matches no row of the reference table",
    "ambiguous": "a key that matches more than one row of the reference table",
    "duplicate": "a key another row already has",
    "inconsistent": "disagrees with another column of the same row",
    "other": "fails the check for another reason",
}

# Text cells that mean "no information", compared without case or accents.
PLACEHOLDERS = frozenset(
    {
        "sem informacao",
        "nao se aplica",
        "nao informado",
        "nao identificado",
        "nao especificado",
        "ignorado",
        "-",
        "--",
        "n/a",
        "#n/a",
        "#n/d",
        "na",
        "nan",
        "null",
        "none",
    }
)

NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
PERIOD = re.compile(r"^(\d{4}|\d{4}-\d{2}|all)$")
MAX_ROWS = 60  # lines of counts in one profile
MAX_COUNT = 10**10 - 1  # at most 10 digits: never shaped like a CPF or a voter ID

BEGIN = "profile: begin"
END = "profile: end"
NONE = "profile: none (the failed check wrote no row counts)"
REFUSED = "profile: refused (the row counts did not pass the checks in terrain.profile)"
_CHECK = re.compile(r"^check: ([a-z][a-z0-9_]{0,39})$")
_COUNT = re.compile(r"^(\d{4}|\d{4}-\d{2}|all) ([a-z_]{2,20}) (\d{1,10})$")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split()).lower()


def text_category(value: object) -> str | None:
    """ "empty", "placeholder" or None (a real value) for one raw text cell."""
    if value is None:
        return "empty"
    text = _fold(str(value))
    if not text:
        return "empty"
    return "placeholder" if text in PLACEHOLDERS else None


def problems(check: object, counts: object) -> list[str]:
    """Why (`check`, `counts`) is not a profile; [] if it is.

    `counts` is a list of [period, category, rows].
    """
    out: list[str] = []
    if not isinstance(check, str) or not NAME.match(check):
        out.append("the check's name must be a code label like recipient_municipality")
    if not isinstance(counts, list | tuple) or not counts:
        return [*out, "counts must be a non-empty list of [period, category, rows]"]
    if len(counts) > MAX_ROWS:
        out.append(f"at most {MAX_ROWS} counts")
    seen: set[tuple[str, str]] = set()
    for row in counts:
        if not isinstance(row, list | tuple) or len(row) != 3:
            out.append("each count is [period, category, rows]")
            continue
        period, category, rows = row
        if not isinstance(period, str) or not PERIOD.match(period):
            out.append("a period is a year, a year and month (2026-03) or all")
        if category not in CATEGORIES:
            out.append(f"unknown category; use one of {', '.join(CATEGORIES)}")
        if isinstance(rows, bool) or not isinstance(rows, int) or not 0 <= rows <= MAX_COUNT:
            out.append("rows must be a whole number from 0 to 9,999,999,999")
        if (period, category) in seen:
            out.append("each period and category once")
        seen.add((str(period), str(category)))
    return sorted(set(out))


def write_profile(
    check: str, counts: Mapping[tuple[str, str], int] | Iterable[tuple[str, str, int]]
) -> Path | None:
    """Write the profile of failing check `check`, if the workflow asked for one.

    `counts` maps (period, category) to rows, or lists (period, category,
    rows). Call it just before raising the check's error. Without the
    environment variable ENV (tests, local runs) nothing is written. A bad
    profile raises ValueError: it is a bug in the check, caught by its tests.
    """
    if isinstance(counts, Mapping):
        triples = [(p, c, n) for (p, c), n in counts.items()]
    else:
        triples = list(counts)
    rows = sorted([str(p), str(c), n] for p, c, n in triples)
    found = problems(check, rows)
    if found:
        raise ValueError(f"bad profile for check {check!r}: {'; '.join(found)}")
    target = os.environ.get(ENV, "")
    if not target:
        return None
    path = Path(target)
    path.write_text(json.dumps({"check": check, "counts": rows}) + "\n", encoding="utf-8")
    return path


def render(check: str, counts: list[list]) -> list[str]:
    """The lines the fixed script prints for a checked profile, BEGIN to END."""
    return [BEGIN, f"check: {check}", *(f"{p} {c} {n}" for p, c, n in counts), END]


def render_file(path: Path) -> list[str]:
    """What `scripts/profile_failure.py` prints for the profile file at `path`."""
    if not path.is_file():
        return [NONE]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [REFUSED]
    if not isinstance(raw, dict) or set(raw) != {"check", "counts"}:
        return [REFUSED]
    if problems(raw["check"], raw["counts"]):
        return [REFUSED]
    return render(raw["check"], sorted(raw["counts"]))


def parse(lines: list[str]) -> list[str] | None:
    """The lines of one printed profile, BEGIN to END, if every line is well formed."""
    if len(lines) < 4 or lines[0] != BEGIN or lines[-1] != END:
        return None
    m = _CHECK.match(lines[1])
    rows = [_COUNT.match(line) for line in lines[2:-1]]
    if m is None or not all(rows):
        return None
    counts = [[r.group(1), r.group(2), int(r.group(3))] for r in rows if r]
    if problems(m.group(1), counts):
        return None
    return lines
