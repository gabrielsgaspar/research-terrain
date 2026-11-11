"""The hidden markers that tie GitHub issues, comments and runs to a campaign.

Every marker is written by code (the tick) and read by code (the tick and the
gate). The tick keeps no state of its own: each run re-reads these markers,
so a failed or repeated run never files, dispatches or merges twice.
"""

from __future__ import annotations

import json
import re

_STEP = re.compile(r"<!-- campaign-step: (\d{4})/(s\d{1,2}) -->")
_TRACKING = re.compile(r"<!-- campaign-tracking: (\d{4}) -->")
_CLOSEOUT = re.compile(r"<!-- campaign-closeout: (\d{4}) -->")
_STATUS = re.compile(r"<!-- campaign-status: 0000 -->")
_REPAIR = re.compile(r"<!-- campaign-repair: (\d{4})/(s\d{1,2})/(\d) -->")
_LEDGER = re.compile(r"<!-- campaign-ledger: (\d{4}) (\[.*?\]) -->", re.S)
_AGENT_FILES = re.compile(r"<!-- agent-files: (\[.*?\]) -->", re.S)
_RUN_TITLE = re.compile(r" campaign (\d{4})/(s\d{1,2})$")


def step_marker(cid: str, sid: str) -> str:
    return f"<!-- campaign-step: {cid}/{sid} -->"


def tracking_marker(cid: str) -> str:
    return f"<!-- campaign-tracking: {cid} -->"


def closeout_marker(cid: str) -> str:
    return f"<!-- campaign-closeout: {cid} -->"


def repair_marker(cid: str, sid: str, n: int) -> str:
    """The marker of repair task `n` of run step `sid` (decision 0014)."""
    return f"<!-- campaign-repair: {cid}/{sid}/{n} -->"


def status_marker() -> str:
    """The marker of the status page, the one issue that shows every campaign."""
    return "<!-- campaign-status: 0000 -->"


def ledger_marker(cid: str, events: list[str]) -> str:
    return f"<!-- campaign-ledger: {cid} {json.dumps(sorted(events), separators=(',', ':'))} -->"


def parse_step(body: str) -> tuple[str, str] | None:
    m = _STEP.search(body or "")
    return (m.group(1), m.group(2)) if m else None


def parse_tracking(body: str) -> str | None:
    m = _TRACKING.search(body or "")
    return m.group(1) if m else None


def parse_closeout(body: str) -> str | None:
    m = _CLOSEOUT.search(body or "")
    return m.group(1) if m else None


def parse_status(body: str) -> bool:
    return bool(_STATUS.search(body or ""))


def parse_repair(body: str) -> tuple[str, str, int] | None:
    m = _REPAIR.search(body or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def parse_ledger(body: str) -> tuple[str, set[str]] | None:
    m = _LEDGER.search(body or "")
    if not m:
        return None
    try:
        events = json.loads(m.group(2))
    except ValueError:
        return None
    if not isinstance(events, list):
        return None
    return m.group(1), {str(e) for e in events}


def parse_agent_files(plan_body: str) -> list[str] | None:
    """Paths from the planner's hidden file list, or None if it has none."""
    m = _AGENT_FILES.search(plan_body or "")
    if not m:
        return None
    try:
        files = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(files, list):
        return None
    return [str(f.get("path", "")) for f in files if isinstance(f, dict)]


def explore_run_title(script: str, cid: str, sid: str) -> str:
    """The run-name explore-run.yml gives a campaign run."""
    return f"Explore {script} campaign {cid}/{sid}"


def pipeline_run_title(stage: str, target: str, cid: str, sid: str) -> str:
    """The run-name data-pipeline.yml gives a campaign run."""
    return f"Data pipeline {stage} {target} campaign {cid}/{sid}"


def parse_run_title(title: str) -> tuple[str, str] | None:
    m = _RUN_TITLE.search(title or "")
    return (m.group(1), m.group(2)) if m else None


def strip_marker(body: str) -> str:
    """The issue body without the step marker line, for comparing with its draft."""
    lines = [
        ln
        for ln in (body or "").replace("\r\n", "\n").split("\n")
        if not _STEP.fullmatch(ln.strip())
    ]
    return "\n".join(lines).strip()


def draft_body(draft_text: str) -> tuple[str, str]:
    """(title, body) an issue gets from a draft: the title is the first line without '# '."""
    text = draft_text.replace("\r\n", "\n").strip()
    first, _, rest = text.partition("\n")
    return first.removeprefix("# ").strip(), rest.strip()
