"""The approval card: one page, printed by code from a campaign's own files.

A campaign plan can run to 90 KB across many files, and Gabriel approves it
with one click. `render_card` prints, as Markdown, what that click approves:
the phases, every kill rule, every new dataset, the limits, what agents may
touch and the papers to read first. It reads only the campaign file's front
matter and its "Read before this runs" section, plus the size and hash of
the draft files; no model writes or edits it, and it adds nothing that is
not in those files beyond fixed explanations of what a field means.

    uv run python scripts/campaign.py card 0007
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from terrain.campaigns.spec import (
    CAMPAIGNS_DIR,
    Campaign,
    KillRule,
    Step,
    ancestors,
    load_campaigns,
    read_front_matter,
)

# Top-level folders where campaign work normally lives; any other path is listed.
USUAL_DIRS = ("pipeline/", "explore/", "src/", "tests/", "data/")
READ_FIRST = "## Read before this runs"
WORDS = 14  # a "few words" for a dataset's source or licence

ON_KILL = {
    "stop": "a kill stops the campaign",
    "skip_dependents": "a kill skips the steps after it",
    "continue": "a kill is recorded and the campaign goes on",
}
SELF_REPAIR_YES = (
    "yes. A data step still failing after both retries gets one repair task from a fixed "
    "template, limited to the paths of the build tasks before it; at most 1 per step and "
    "2 per campaign (decision 0014)"
)
IDENTIFIERS = {"none": "no identifiers", "hashed": "identifiers kept only as salted hashes"}

# "p below a level": the rule compares a p-value field, or says "p below".
P_FIELD = re.compile(r"(^|_)(p|pval|pvalue)(_|$)", re.I)
P_SAYS = re.compile(r"\bp(-value)?\s+(is\s+)?(below|under|less than)\b", re.I)


class CardError(Exception):
    """The card cannot be printed; the message says why."""


def is_p_rule(rule: KillRule) -> bool:
    """True for a rule of the form "p below a level" (kill-rules.md, "False stops")."""
    if rule.op not in ("<", "<="):
        return False
    if isinstance(rule.value, bool) or not isinstance(rule.value, int | float):
        return False
    if not 0 < rule.value < 1:
        return False
    return bool(P_FIELD.search(rule.field.split(".")[-1]) or P_SAYS.search(rule.says))


def _pct(x: float) -> str:
    return f"{round(x * 100, 2):g}%"


def _n(count: object, noun: str) -> str:
    """'1 task', '3 tasks'."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _step_num(step_id: str) -> int:
    return int(step_id[1:])


def _id_range(ids: list[str]) -> str:
    """s1, s2, s3, s5 -> "s1-s3, s5" (numeric order)."""
    nums = sorted(_step_num(i) for i in ids)
    parts: list[str] = []
    start = prev = nums[0]
    for n in [*nums[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(f"s{start}" if start == prev else f"s{start}-s{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(parts)


def _few_words(text: str, *, by_comma: bool) -> str:
    """The start of `text`, ending in '…' if cut: up to the first ';', and with
    `by_comma` up to the first comma outside brackets that leaves at least
    two words (not for "built from" lists); then at most WORDS words."""
    text = " ".join(str(text).split())
    out = text.split(";")[0].strip()
    if by_comma and not out.lower().startswith("built from"):
        depth = 0
        for i, ch in enumerate(out):
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "," and depth == 0 and len(out[:i].split()) >= 2:
                out = out[:i]
                break
    words = out.split()
    cut = len(words) > WORDS or out != text
    out = " ".join(words[:WORDS])
    return f"{out} …" if cut else out


def phases(c: Campaign) -> list[tuple[list[Step], Step | None]]:
    """Steps grouped into phases, each ending at an explore run.

    A phase is an explore run and every step it comes after that no earlier
    phase holds. Steps no explore run comes after form a last phase with no gate.
    """
    out: list[tuple[list[Step], Step | None]] = []
    taken: set[str] = set()
    for gate in (s for s in c.steps if s.kind == "explore_run"):
        ids = (ancestors(c, gate.id) | {gate.id}) - taken
        taken |= ids
        out.append(([s for s in c.steps if s.id in ids], gate))
    rest = [s for s in c.steps if s.id not in taken]
    if rest:
        out.append((rest, None))
    return out


def _phase_line(n: int, steps: list[Step], gate: Step | None) -> str:
    builds = sum(1 for s in steps if s.kind == "task" and s.type == "build")
    explores = sum(1 for s in steps if s.kind == "task" and s.type == "explore")
    tasks = [
        _n(count, f"{kind} task")
        for count, kind in ((builds, "build"), (explores, "explore"))
        if count
    ] or ["no tasks"]
    fetched = [s.dataset for s in steps if s.kind == "pipeline_run" and s.stage == "acquire"]
    built = [s.dataset for s in steps if s.kind == "pipeline_run" and s.stage == "build"]
    data = []
    if fetched:
        data.append("fetches " + ", ".join(f"`{d}`" for d in fetched))
    if built:
        data.append("builds " + ", ".join(f"`{d}`" for d in built))
    if not data:
        data.append("no data fetched or built")
    if gate is None:
        end = "no explore run ends it"
    else:
        k = len(gate.kill_rules)
        end = (
            f"ends at {gate.id}, explore run `{gate.script}` "
            f"({_n(k, 'kill rule')}; {ON_KILL.get(gate.on_kill, gate.on_kill)})"
        )
    label = f"Phase {n}" if gate is not None else "After the last explore run"
    return f"- **{label}, {_id_range([s.id for s in steps])}:** " + "; ".join(
        [" and ".join(tasks), *data, end]
    )


def _rule_line(step: Step, rule: KillRule) -> str:
    line = (
        f"- {step.id} {rule.id}: {' '.join(rule.says.split())} "
        f"(`{rule.field}` {rule.op} {_value(rule.value)})"
    )
    if not rule.confirmed:
        line += " **Not yet confirmed.**"
    if is_p_rule(rule):
        line += (
            f" *p-value rule: if the design is valid, it fires by chance about "
            f"{_pct(rule.value)} of the time.*"
        )
    return line


def _dataset_line(d: dict) -> str:
    size = d.get("max_size_gb")
    ident = d.get("identifiers")
    return (
        f"- `{d.get('name', '')}`: {_few_words(d.get('source', ''), by_comma=True)}"
        f" · licence: {_few_words(d.get('licence', ''), by_comma=False)}"
        f" · at most {_value(size)} GB · {IDENTIFIERS.get(str(ident), f'identifiers: {ident}')}"
    )


def read_first_lines(text: str) -> list[str] | None:
    """The lines of the campaign file's "Read before this runs" section, or None."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == READ_FIRST)
    except StopIteration:
        return None
    body: list[str] = []
    for ln in lines[start + 1 :]:
        if ln.startswith("# ") or ln.startswith("## "):
            break
        body.append(ln.rstrip())
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return body


def _plan_files(root: Path, c: Campaign) -> tuple[int, int, str]:
    """Count, total bytes and SHA-256 (first 12 hex) of campaign.md and drafts/*.md."""
    folder = root / c.folder
    files = [folder / "campaign.md", *sorted((folder / "drafts").glob("*.md"))]
    digest = hashlib.sha256()
    size = 0
    for f in files:
        data = f.read_bytes()
        size += len(data)
        digest.update(f.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).digest())
    return len(files), size, digest.hexdigest()[:12]


def find_campaign(root: Path, campaign_id: str) -> Campaign:
    cid = campaign_id.strip().zfill(4)
    for c in load_campaigns(root):
        if c.id == cid:
            return c
    raise CardError(f"No campaign {cid} in {CAMPAIGNS_DIR}/.")


def render_card(root: Path, campaign_id: str) -> str:
    """The approval card for one campaign, as Markdown. Raises CardError."""
    c = find_campaign(root, campaign_id)
    if c.problems:
        # A rule or dataset the parser could not read would be missing from the card.
        raise CardError(
            f"Campaign {c.id} has problems, so no card is printed:\n"
            + "\n".join(f"  - {p}" for p in c.problems)
        )
    text = (root / c.folder / "campaign.md").read_text(encoding="utf-8")
    n_files, size, digest = _plan_files(root, c)
    out: list[str] = [
        f"**Campaign {c.id}: {c.title}**",
        "",
        f"Idea {c.idea} · ends {c.end_by} (created {c.created}) · status {c.status} · "
        f"{len(c.steps)} steps.",
        f"Printed by `uv run python scripts/campaign.py card {c.id}` from {n_files} plan "
        f"files ({round(size / 1024)} KB, SHA-256 {digest}); no model wrote it.",
        "",
        "### What runs",
        "",
    ]
    for n, (steps, gate) in enumerate(phases(c), start=1):
        out.append(_phase_line(n, steps, gate))

    out += ["", "### What stops it", ""]
    rules = [(s, r) for s in c.steps if s.kind == "explore_run" for r in s.kill_rules]
    out += [_rule_line(s, r) for s, r in rules] or ["- No kill rules."]
    p_rules = [r for _, r in rules if is_p_rule(r)]
    if p_rules:
        total = sum(r.value for r in p_rules)
        out.append(
            f"- **p-value rules: {len(p_rules)}.** Together they stop a valid design up to "
            f"{_pct(total)} of the time (the sum of their levels)."
        )
    else:
        out.append("- **p-value rules: none**, so no false-stop rate to add up.")

    out += ["", "### New data", ""]
    out += [_dataset_line(d) for d in c.datasets] or ["- None: only data already in the bucket."]

    b = c.budget
    out += [
        "",
        "### Limits",
        "",
        f"- Budget: at most {_n(b.get('max_tasks'), 'task')}, "
        f"{_n(b.get('max_explore_runs'), 'explore run')}, "
        f"{_n(b.get('max_pipeline_runs'), 'pipeline run')} and "
        f"{_n(b.get('max_model_jobs'), 'model job')}.",
        f"- Self-repair: {SELF_REPAIR_YES if c.self_repair else 'no'}.",
    ]
    fm_reason = _oversize_reason(text)
    if fm_reason:
        out.append(f"- Why {len(c.steps)} steps, in {c.owner}'s words: “{fm_reason}”")

    paths = sorted({p for s in c.steps for p in s.allowed_paths})
    unusual = sorted(p for p in paths if not p.startswith(USUAL_DIRS))
    globs = [p for p in paths if "*" in p]
    out += ["", "### What an agent may touch", ""]
    line = f"- {_n(len(paths), 'distinct file')} across all steps"
    if globs:
        line += f", of which {len(globs)} {'is a pattern' if len(globs) == 1 else 'are patterns'}"
        line += " with * (" + ", ".join(f"`{p}`" for p in globs) + ")"
    out.append(line + ".")
    if unusual:
        for p in unusual:
            where = ", ".join(s.id for s in c.steps if p in s.allowed_paths)
            out.append(f"- Outside {', '.join(USUAL_DIRS)}: `{p}` ({where}).")
    else:
        out.append(f"- None outside {', '.join(USUAL_DIRS)}.")

    out += ["", "### Read before this runs", ""]
    lines = read_first_lines(text)
    out += lines if lines else ["The campaign file has no such section."]
    return "\n".join(out) + "\n"


def _oversize_reason(text: str) -> str:
    fm = read_front_matter(text)
    reason = fm.get("oversize_reason") if isinstance(fm, dict) else None
    return " ".join(reason.split()) if isinstance(reason, str) and reason.strip() else ""
