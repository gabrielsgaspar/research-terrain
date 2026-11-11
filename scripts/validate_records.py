"""Check the front matter of idea and decision records, and the agent notes.

Usage: uv run python scripts/validate_records.py

Prints one line per problem and exits 1 if there are any.
"""

import datetime as dt
import re
import sys
from pathlib import Path

import yaml

from terrain.campaigns.closeout import (
    MAX_ADVICE_CHARS,
    MAX_NEW_NOTES,
    MAX_NOTES,
    NOTE_BANNED,
    NOTE_ROLES,
    SCOREBOARD_HEADER,
)
from terrain.campaigns.spec import NOTES_PATH

REPO = Path(__file__).resolve().parent.parent

IDEA_STATUSES = {
    "proposed",
    "exploring",
    "promising",
    "parked",
    "dead",
    "registered",
    "confirmed",
    "rejected",
}
DECISION_STATUSES = {"proposed", "accepted", "superseded"}
IDEA_KEYS = {
    "id",
    "title",
    "status",
    "created",
    "updated",
    "datasets",
    "kill_criteria",
    "related",
}
DECISION_KEYS = {"id", "title", "status", "date", "supersedes"}
SKIP = {"README.md", "TEMPLATE.md"}
NAME = re.compile(r"^(\d{4})-.+\.md$")
ID = re.compile(r"^\d{4}$")


NOTE = re.compile(
    r"^- \[(?P<id>N\d{3})\] \((?P<role>[a-z]+)\) (?P<advice>.+?\.) "
    r"From: campaign (?P<campaign>\d{4}), (?P<fact>.+)\. Added (?P<added>\d{4}-\d{2}-\d{2})\.$"
)
NOTE_ID = re.compile(r"^- \[(N\d{3})\]")
HOURS = re.compile(r"^\d+(\.\d+)?$")


class PlainLoader(yaml.SafeLoader):
    """Safe loader that leaves dates as strings, so a bad date is reported, not raised."""


PlainLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_front_matter(path: Path) -> dict | str:
    """Return the front matter mapping, or a message saying what is wrong."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return "missing front matter"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.load("\n".join(lines[1:i]), Loader=PlainLoader)  # noqa: S506
            except yaml.YAMLError as exc:
                return f"front matter is not valid YAML ({exc.__class__.__name__})"
            if not isinstance(data, dict):
                return "front matter is not a mapping"
            return data
    return "front matter has no closing ---"


def parse_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def catalog_names(root: Path) -> set[str]:
    path = root / "data" / "catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {d["name"] for d in data.get("datasets", []) if "name" in d}


def collect(root: Path) -> list[Path]:
    files: list[Path] = []
    for folder in ("ideas", "decisions"):
        d = root / "research" / folder
        if d.is_dir():
            files += sorted(p for p in d.glob("*.md") if p.name not in SKIP)
    return files


def check_keys(label: str, fm: dict, required: set[str]) -> list[str]:
    missing = sorted(required - fm.keys())
    return [f"{label}: missing key '{k}'" for k in missing]


def check_date(label: str, fm: dict, key: str) -> list[str]:
    if key in fm and parse_date(fm[key]) is None:
        return [f"{label}: '{key}' is not a valid YYYY-MM-DD date"]
    return []


def validate(root: Path = REPO) -> list[str]:
    problems: list[str] = []
    catalog = catalog_names(root)
    parsed: list[tuple[str, str, dict]] = []  # (label, kind, front matter)
    for path in collect(root):
        label = path.relative_to(root).as_posix()
        kind = path.parent.name
        fm = read_front_matter(path)
        if isinstance(fm, str):
            problems.append(f"{label}: {fm}")
            continue
        m = NAME.match(path.name)
        if m is None:
            problems.append(f"{label}: file name does not start with NNNN-")
        else:
            rid = fm.get("id")
            if not isinstance(rid, str) or not ID.match(rid):
                problems.append(f"{label}: 'id' must be a quoted four-digit string")
            elif rid != m.group(1):
                problems.append(f"{label}: id '{rid}' does not match file name")
        parsed.append((label, kind, fm))

    ids = {str(fm["id"]) for _, _, fm in parsed if "id" in fm}
    decision_ids = {str(fm["id"]) for _, k, fm in parsed if k == "decisions" and "id" in fm}

    titles: dict[str, str] = {}
    for label, kind, fm in parsed:
        required = IDEA_KEYS if kind == "ideas" else DECISION_KEYS
        problems += check_keys(label, fm, required)
        title = fm.get("title")
        if "title" in fm:
            if not isinstance(title, str) or not title.strip():
                problems.append(f"{label}: 'title' must be a non-empty string")
            elif title in titles:
                problems.append(f"{label}: duplicate title (also {titles[title]})")
            else:
                titles[title] = label
        if kind == "ideas":
            problems += check_idea(label, fm, catalog, ids)
        else:
            problems += check_decision(label, fm, decision_ids)
    if (root / NOTES_PATH).is_file():
        problems += check_agent_notes(root)
    return problems


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def check_agent_notes(root: Path) -> list[str]:
    """research/agent-notes.md: notes in the fixed shape, then the Scoreboard table."""
    label = NOTES_PATH
    lines = (root / NOTES_PATH).read_text(encoding="utf-8").splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if [lines[i] for i in heads] != ["## Notes", "## Scoreboard"]:
        return [f"{label}: needs exactly the headings '## Notes' then '## Scoreboard'"]
    notes_at, board_at = heads
    out: list[str] = []
    seen: set[str] = set()
    cited: list[tuple[str, str]] = []  # (note id, campaign)
    count = 0
    for n, line in enumerate(lines[notes_at + 1 : board_at], start=notes_at + 2):
        if not line.strip():
            continue
        count += 1
        m = NOTE.match(line)
        found = NOTE_ID.match(line)
        name = f"note {found.group(1)}" if found else f"line {n}"
        lowered = line.lower()
        out += [
            f"{label}: {name} contains '{w}', which a note may not mention"
            for w in NOTE_BANNED
            if w.lower() in lowered
        ]
        if m is None:
            out.append(
                f"{label}: {name} is not in the shape '- [N001] (role) Advice. "
                "From: campaign NNNN, fact. Added YYYY-MM-DD.'"
            )
            continue
        nid = m.group("id")
        if nid in seen:
            out.append(f"{label}: note {nid} has a duplicate id")
        seen.add(nid)
        if m.group("role") not in NOTE_ROLES:
            out.append(f"{label}: note {nid} has role '{m.group('role')}', not one of {NOTE_ROLES}")
        advice = m.group("advice")
        if len(advice) > MAX_ADVICE_CHARS:
            out.append(
                f"{label}: note {nid} advice is {len(advice)} characters (at most "
                f"{MAX_ADVICE_CHARS})"
            )
        if re.search(r"[.!?] ", advice):
            out.append(f"{label}: note {nid} advice must be one sentence")
        if parse_date(m.group("added")) is None:
            out.append(f"{label}: note {nid} 'Added' is not a valid YYYY-MM-DD date")
        cited.append((nid, m.group("campaign")))
    if count > MAX_NOTES:
        out.append(f"{label}: {count} notes; at most {MAX_NOTES}")

    table = [ln for ln in lines[board_at + 1 :] if ln.strip()]
    if len(table) < 2 or _cells(table[0]) != list(SCOREBOARD_HEADER):
        out.append(f"{label}: the Scoreboard table must have the header {SCOREBOARD_HEADER}")
        return out
    if set(_cells(table[1])) != {"---"} or len(_cells(table[1])) != len(SCOREBOARD_HEADER):
        out.append(f"{label}: the Scoreboard's second line must be the table separator")
    boarded: set[str] = set()
    for row in table[2:]:
        cells = _cells(row)
        if not row.startswith("|") or len(cells) != len(SCOREBOARD_HEADER):
            out.append(f"{label}: Scoreboard row '{row}' needs {len(SCOREBOARD_HEADER)} cells")
            continue
        cid, steps, blocks, fixes, retries, hours, added = cells
        where = f"{label}: Scoreboard row for campaign {cid}"
        if not ID.match(cid):
            out.append(f"{label}: Scoreboard campaign '{cid}' is not a four-digit id")
        elif cid in boarded:
            out.append(f"{where} appears twice")
        elif not any((root / "research" / "campaigns").glob(f"{cid}-*/campaign.md")):
            out.append(f"{where}: no such campaign in research/campaigns/")
        boarded.add(cid)
        for head, value in zip(
            SCOREBOARD_HEADER[1:5], (steps, blocks, fixes, retries), strict=True
        ):
            if not value.isdigit():
                out.append(f"{where}: '{head}' must be a whole number, not '{value}'")
        if not HOURS.match(hours):
            out.append(f"{where}: hours must be a number, not '{hours}'")
        if not added.isdigit() or int(added) > MAX_NEW_NOTES:
            out.append(f"{where}: notes added must be 0 to {MAX_NEW_NOTES}, not '{added}'")
    out += [
        f"{label}: note {nid} cites campaign {cid}, which has no Scoreboard row"
        for nid, cid in cited
        if cid not in boarded
    ]
    return out


def check_idea(label: str, fm: dict, catalog: set[str], ids: set[str]) -> list[str]:
    out: list[str] = []
    if "status" in fm and fm["status"] not in IDEA_STATUSES:
        out.append(f"{label}: bad status {fm['status']!r}")
    out += check_date(label, fm, "created")
    out += check_date(label, fm, "updated")
    created, updated = parse_date(fm.get("created")), parse_date(fm.get("updated"))
    if created and updated and updated < created:
        out.append(f"{label}: 'updated' is before 'created'")
    if "datasets" in fm:
        ds = fm["datasets"]
        if not isinstance(ds, list):
            out.append(f"{label}: 'datasets' must be a list")
        else:
            out += [f"{label}: unknown dataset {d!r}" for d in ds if d not in catalog]
    if "kill_criteria" in fm:
        kc = fm["kill_criteria"]
        if (
            not isinstance(kc, list)
            or not kc
            or not all(isinstance(k, str) and k.strip() for k in kc)
        ):
            out.append(f"{label}: 'kill_criteria' must be a non-empty list of strings")
    if "related" in fm:
        rel = fm["related"]
        if not isinstance(rel, list):
            out.append(f"{label}: 'related' must be a list")
        else:
            out += [f"{label}: unknown related id {r!r}" for r in rel if r not in ids]
    return out


def check_decision(label: str, fm: dict, decision_ids: set[str]) -> list[str]:
    out: list[str] = []
    if "status" in fm and fm["status"] not in DECISION_STATUSES:
        out.append(f"{label}: bad status {fm['status']!r}")
    out += check_date(label, fm, "date")
    sup = fm.get("supersedes")
    if "supersedes" in fm and sup is not None and sup not in decision_ids:
        out.append(f"{label}: 'supersedes' {sup!r} is not an existing decision id")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else REPO
    problems = validate(root)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
