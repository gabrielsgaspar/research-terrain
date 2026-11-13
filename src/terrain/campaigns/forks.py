"""Forks: variants of a campaign step, proposed after its result is in (decision 0015).

A campaign may carry a fork envelope (`forks:` in `campaign.md`), which
Gabriel approves with the plan: how many forks, how many new datasets,
which kinds, which fork points and a budget of their own. No envelope, no
forks: a campaign without one behaves exactly as before.

A fork lives in `research/campaigns/NNNN-slug/forks/fK.md`, with its drafts
in `forks/fK/drafts/sNN.md`. Code writes these files from the ideation
job's output (`scripts/campaign.py forks-from-json`); nothing a model wrote
is used without passing the checks here. Its steps join the campaign's
steps, marked with the fork's id, and the tick runs them like any other.

What this module enforces (the rules of decision 0015, by number):

- F1: fork tasks follow the explore rules (explore/ and tests/test_explore*
  only); a fork's build task may touch only new files named `*_fK` and
  `data/catalog.yaml`, and only when the fork brings new data.
- F2: a fork is on main before it runs, because the tick reads steps from
  main only; the gate refuses changes to merged fork files.
- F4: an explore run names the parent whose kill rules it inherits
  (`inherits`), copied unchanged; a `question` fork names rules of the
  kill-rule library instead. No threshold is ever written in a fork file,
  and every fork run needs a rule other than "finite".
- F5: one type and one dimension; drafts carry "What differs from the parent".
- F6: a sample fork names what it filters on (`sample_on`, never outcomes)
  and gets the library rule `min_clusters` added.
- F7: new data only from approved publishers, no identifiers, at most 5 GB.
- F10: a registration of an idea with forks lists every fork tried.
- F11: depth one: the parent is a step of the plan, never a fork's step.
- F12: the envelope's own budget bounds every fork step.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from terrain.campaigns.codeowners import CodeOwners

LIBRARY_PATH = "research/campaigns/kill-rule-library.yaml"
PUBLISHERS_PATH = "data/approved-publishers.yaml"
SPECS_DIR = "confirm/specs"

TYPES = ("transform", "sample", "spec", "measure", "question")
VERDICTS = ("killed", "survived")
SAMPLE_ON = ("geography", "biome", "baseline", "years")
# Hard caps on the envelope (the brief, section 6.1).
CAPS = {"max_forks": 5, "max_new_datasets": 2, "max_steps_per_fork": 6, "max_question_forks": 2}
ENVELOPE_KEYS = (
    "max_forks",
    "per_point",
    "max_new_datasets",
    "max_steps_per_fork",
    "types",
    "max_question_forks",
    "on",
    "fork_points",
    "budget",
)
FORK_MAX_SIZE_GB = 5
DELTA_MAX = 600
DIMENSION_MAX = 200
# The library rules code adds or counts (F4, F6).
FINITE = "finite"
MIN_CLUSTERS = "min_clusters"

# What a fork file and its steps may say; anything else is refused, so no
# fork can carry a threshold, an on_kill or a rule of its own.
FORK_KEYS = {
    "id",
    "campaign",
    "parent_step",
    "parent_verdict",
    "order",
    "type",
    "title",
    "dimension",
    "headline",
    "sample_on",
    "evidence",
    "datasets",
    "adopts_downstream",
    "delta",
    "steps",
}
STEP_KEYS = {
    "task": {"id", "kind", "type", "draft", "allowed_paths", "after"},
    "explore_run": {"id", "kind", "script", "inherits", "rules", "after"},
    "pipeline_run": {"id", "kind", "stage", "target", "dataset", "after"},
}
DATASET_KEYS = {"name", "source", "licence", "max_size_gb", "identifiers", "publisher"}
BODY_SECTIONS = ("## Why", "## What differs from the parent", "## What a pass or a fail would mean")
DIFFERS = "## What differs from the parent"

FORK_FILE = re.compile(r"^f([1-9])\.md$")
FORK_ID = re.compile(r"^f[1-9]$")
STEP_ID = re.compile(r"^s(\d{1,2})$")
RULE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
BUILD_DIRS = ("pipeline/", "src/terrain/", "tests/", "data/contracts/")
CATALOG = "data/catalog.yaml"

# A text overlay of repository files: path -> text. The gate passes a fork
# plan pull request's added files this way (read through the API), so the
# same checks run without checking out the pull request.
Overlay = Mapping[str, str]


@dataclass(frozen=True)
class Envelope:
    max_forks: int
    per_point: int
    max_new_datasets: int
    max_steps_per_fork: int
    types: tuple[str, ...]
    max_question_forks: int
    on: tuple[str, ...]
    fork_points: tuple[str, ...] | None  # None: every eligible explore run ("all")
    budget: dict[str, int]


@dataclass(frozen=True)
class LibraryRule:
    name: str
    says: str
    field: str
    op: str
    value: Any
    confirmed: bool
    counts: bool  # False for "finite": it does not count as a rule of its own (F4)
    source: str = ""


@dataclass(frozen=True)
class Fork:
    id: str
    path: str  # repository path of forks/fK.md
    parent_step: str
    parent_verdict: str
    order: int
    type: str
    title: str
    dimension: str
    headline: str
    sample_on: str
    evidence: tuple[str, ...]
    datasets: tuple[dict[str, Any], ...]
    adopts_downstream: bool
    delta: str
    step_ids: tuple[str, ...]
    body: str = field(default="", repr=False)

    @property
    def number(self) -> int:
        return int(self.id[1:])


# -- the envelope ----------------------------------------------------------------------


def _whole(value: object, lo: int, hi: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= lo and (hi is None or value <= hi)


def parse_envelope(raw: object, where: str, problems: list[str]) -> Envelope | None:
    """The `forks:` block, or None (with problems) if it is not one."""
    from terrain.campaigns.spec import BUDGET_KEYS

    if not isinstance(raw, dict):
        problems.append(f"{where}: forks must be a mapping (or left out: no forks)")
        return None
    raw = dict(raw)
    if True in raw and "on" not in raw:  # YAML 1.1 reads a bare `on:` key as true
        raw["on"] = raw.pop(True)
    before = len(problems)
    for key in ENVELOPE_KEYS:
        if key not in raw:
            problems.append(f"{where}: forks is missing '{key}'")
    extra = sorted(str(k) for k in raw if k not in ENVELOPE_KEYS)
    if extra:
        problems.append(f"{where}: forks has unknown keys {extra}")
    if len(problems) > before:
        return None
    for key, cap in CAPS.items():
        if not _whole(raw[key], 0 if key in ("max_new_datasets", "max_question_forks") else 1, cap):
            problems.append(f"{where}: forks.{key} must be a whole number of at most {cap}")
    if not _whole(raw["per_point"], 1, CAPS["max_forks"]):
        problems.append(f"{where}: forks.per_point must be a whole number from 1 to 5")
    types = raw["types"]
    if not (isinstance(types, list) and types and all(t in TYPES for t in types)):
        problems.append(f"{where}: forks.types must list some of {list(TYPES)}")
        types = []
    on = raw["on"]
    if not (isinstance(on, list) and on and all(v in VERDICTS for v in on)):
        problems.append(f"{where}: forks.on must list killed, survived or both")
        on = []
    points = raw["fork_points"]
    if points != "all" and not (
        isinstance(points, list) and points and all(STEP_ID.match(str(p)) for p in points)
    ):
        problems.append(f"{where}: forks.fork_points must be all or a list of step ids")
        points = []
    budget_raw = raw["budget"] if isinstance(raw["budget"], dict) else {}
    budget: dict[str, int] = {}
    for key in sorted(BUDGET_KEYS):
        if not _whole(budget_raw.get(key), 0):
            problems.append(f"{where}: forks.budget.{key} must be a whole number, 0 or more")
        else:
            budget[key] = budget_raw[key]
    extra = sorted(set(budget_raw) - BUDGET_KEYS)
    if extra:
        problems.append(f"{where}: unknown forks.budget keys {extra}")
    if len(problems) > before:
        return None
    if raw["max_question_forks"] > raw["max_forks"] or raw["per_point"] > raw["max_forks"]:
        problems.append(f"{where}: forks.per_point and max_question_forks cannot pass max_forks")
    return Envelope(
        max_forks=raw["max_forks"],
        per_point=raw["per_point"],
        max_new_datasets=raw["max_new_datasets"],
        max_steps_per_fork=raw["max_steps_per_fork"],
        types=tuple(types),
        max_question_forks=raw["max_question_forks"],
        on=tuple(on),
        fork_points=None if points == "all" else tuple(str(p) for p in points),
        budget=budget,
    )


def default_envelope(budget: dict[str, int] | None = None) -> Envelope:
    """The defaults the campaign-design skill offers (and a dry run uses without a block)."""
    return Envelope(
        max_forks=5,
        per_point=3,
        max_new_datasets=2,
        max_steps_per_fork=4,
        types=TYPES,
        max_question_forks=1,
        on=VERDICTS,
        fork_points=None,
        budget=budget
        or {"max_tasks": 10, "max_explore_runs": 7, "max_pipeline_runs": 6, "max_model_jobs": 45},
    )


def counting_rules(rules: tuple, library: dict[str, LibraryRule]) -> list:
    """The kill rules that count for F4: all but the library's "finite" rule."""
    fin = library.get(FINITE)
    if fin is None:
        return list(rules)
    return [r for r in rules if (r.field, r.op, r.value) != (fin.field, fin.op, fin.value)]


def fork_points(c: Any, library: dict[str, LibraryRule]) -> list[str]:
    """The explore-run steps of the plan where forks may be proposed (never a fork's step)."""
    env = c.forks
    if env is None:
        return []
    eligible = [
        s.id
        for s in c.main_steps
        if s.kind == "explore_run" and counting_rules(s.kill_rules, library)
    ]
    if env.fork_points is None:
        return eligible
    return [p for p in env.fork_points if p in eligible]


def check_envelope(c: Any, library: dict[str, LibraryRule], problems: list[str]) -> None:
    """Envelope checks that need the plan's steps."""
    env, where = c.forks, f"{c.folder}/campaign.md"
    if env is None or env.fork_points is None:
        return
    for p in env.fork_points:
        s = c.step(p)
        if s is None or s.fork or s.kind != "explore_run":
            problems.append(f"{where}: forks.fork_points names {p}, which is no explore_run step")
        elif not counting_rules(s.kill_rules, library):
            problems.append(
                f"{where}: forks.fork_points names {p}, whose only kill rule is 'finite' (F4)"
            )


# -- the kill-rule library and the approved publishers ----------------------------------


def _read(root: Path, path: str, overlay: Overlay | None = None) -> str | None:
    if overlay and path in overlay:
        return overlay[path]
    f = root / path
    return f.read_text(encoding="utf-8") if f.is_file() else None


def load_library(root: Path, problems: list[str] | None = None) -> dict[str, LibraryRule]:
    """The kill-rule library by name; problems go to `problems` when given."""
    from terrain.campaigns.spec import OPS

    out: dict[str, LibraryRule] = {}
    sink = problems if problems is not None else []
    text = _read(root, LIBRARY_PATH)
    if text is None:
        return out
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        sink.append(f"{LIBRARY_PATH}: not valid YAML")
        return out
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        sink.append(f"{LIBRARY_PATH}: needs a list 'rules'")
        return out
    for raw in rules:
        if not isinstance(raw, dict):
            sink.append(f"{LIBRARY_PATH}: each rule must be a mapping")
            continue
        name = str(raw.get("name", ""))
        where = f"{LIBRARY_PATH}: rule {name or '?'}"
        missing = [k for k in ("name", "says", "field", "op", "value", "confirmed") if k not in raw]
        if missing:
            sink.append(f"{where}: missing {missing}")
            continue
        if not RULE_NAME.match(name) or name in out:
            sink.append(f"{where}: name must be unique, lowercase with underscores")
            continue
        if raw["op"] not in OPS:
            sink.append(f"{where}: op must be one of {sorted(OPS)}")
            continue
        if raw["op"] in {"<", "<=", ">", ">="} and (
            isinstance(raw["value"], bool) or not isinstance(raw["value"], int | float)
        ):
            sink.append(f"{where}: compares with {raw['op']}, so value must be a number")
            continue
        if not isinstance(raw["confirmed"], bool) or not isinstance(raw.get("counts", True), bool):
            sink.append(f"{where}: confirmed and counts must be true or false")
            continue
        out[name] = LibraryRule(
            name=name,
            says=" ".join(str(raw["says"]).split()),
            field=str(raw["field"]),
            op=str(raw["op"]),
            value=raw["value"],
            confirmed=raw["confirmed"],
            counts=raw.get("counts", True),
            source=str(raw.get("from", "")),
        )
    for needed in (FINITE, MIN_CLUSTERS):
        if needed not in out:
            sink.append(f"{LIBRARY_PATH}: has no rule '{needed}' (decision 0015 names it)")
    return out


def load_publishers(root: Path, problems: list[str] | None = None) -> dict[str, dict]:
    """The approved publishers by id; problems go to `problems` when given."""
    out: dict[str, dict] = {}
    sink = problems if problems is not None else []
    text = _read(root, PUBLISHERS_PATH)
    if text is None:
        return out
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        sink.append(f"{PUBLISHERS_PATH}: not valid YAML")
        return out
    items = data.get("publishers") if isinstance(data, dict) else None
    if not isinstance(items, list):
        sink.append(f"{PUBLISHERS_PATH}: needs a list 'publishers'")
        return out
    for raw in items:
        pid = str(raw.get("id", "")) if isinstance(raw, dict) else ""
        where = f"{PUBLISHERS_PATH}: publisher {pid or '?'}"
        if not isinstance(raw, dict) or not RULE_NAME.match(pid) or pid in out:
            sink.append(f"{where}: needs a unique lowercase id")
            continue
        hosts = raw.get("hosts", [])
        bare = isinstance(hosts, list) and all(isinstance(h, str) and HOST.match(h) for h in hosts)
        if not bare:
            sink.append(f"{where}: hosts must be bare host names (no scheme, no path)")
            continue
        if not isinstance(raw.get("name"), str) or not isinstance(raw.get("catalog", []), list):
            sink.append(f"{where}: needs a name and a list catalog")
            continue
        out[pid] = raw
    return out


def check_records(root: Path) -> list[str]:
    """Problems with the library and the publishers file (CI runs this)."""
    problems: list[str] = []
    load_library(root, problems)
    publishers = load_publishers(root, problems)
    names = catalog_names(root)
    for pid, raw in publishers.items():
        unknown = [n for n in raw.get("catalog", []) if names and n not in names]
        if unknown:
            problems.append(
                f"{PUBLISHERS_PATH}: publisher {pid} lists {unknown}, not in data/catalog.yaml"
            )
    return problems


def catalog_names(root: Path) -> set[str]:
    """Dataset names in data/catalog.yaml (empty if there is none)."""
    text = _read(root, CATALOG)
    try:
        data = yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        return set()
    items = data.get("datasets", []) if isinstance(data, dict) else []
    return {str(e.get("name")) for e in items if isinstance(e, dict)}


# -- fork files -------------------------------------------------------------------------


def fork_files(root: Path, folder: str, overlay: Overlay | None = None) -> list[str]:
    """Repository paths of the campaign's fork files (on disk, plus the overlay's)."""
    found = set()
    d = root / folder / "forks"
    if d.is_dir():
        found |= {f"{folder}/forks/{p.name}" for p in d.iterdir() if p.is_file()}
    for path in overlay or {}:
        if path.startswith(f"{folder}/forks/") and path.count("/") == folder.count("/") + 2:
            found.add(path)
    return sorted(found, key=lambda p: (len(p), p))


def _step_num(sid: str) -> int:
    m = STEP_ID.match(sid)
    return int(m.group(1)) if m else -1


def _fork_step(
    raw: object, fid: str, folder: str, where: str, problems: list[str]
) -> tuple[Any, str, tuple[str, ...]] | None:
    """(Step without kill rules, `inherits`, library rule names) of one fork step."""
    from terrain.campaigns.spec import SCRIPT, STAGES, TARGET, TASK_TYPES, Step

    if not isinstance(raw, dict):
        problems.append(f"{where}: each step must be a mapping")
        return None
    sid, kind = str(raw.get("id", "")), str(raw.get("kind", ""))
    where = f"{where} step {sid or '?'}"
    if not STEP_ID.match(sid):
        problems.append(f"{where}: id must look like s24")
        return None
    if kind not in STEP_KEYS:
        problems.append(f"{where}: kind must be task, explore_run or pipeline_run")
        return None
    extra = sorted(str(k) for k in raw if k not in STEP_KEYS[kind])
    if extra:
        problems.append(
            f"{where}: keys {extra} are not allowed in a fork step (no threshold, rule or "
            "on_kill is ever written in a fork file, decision 0015 F4)"
        )
    after = raw.get("after", [])
    if not isinstance(after, list) or not after:
        problems.append(f"{where}: after must list the step it comes after")
        after = []
    after = tuple(str(a) for a in after)
    if kind == "task":
        ttype = str(raw.get("type", ""))
        draft = str(raw.get("draft", ""))
        paths = raw.get("allowed_paths")
        if ttype not in TASK_TYPES:
            problems.append(f"{where}: type must be explore or build")
        if draft != f"forks/{fid}/drafts/{sid}.md":
            problems.append(f"{where}: draft must be forks/{fid}/drafts/{sid}.md")
        if not isinstance(paths, list) or not paths:
            problems.append(f"{where}: allowed_paths must list the files the task may change")
            paths = []
        step = Step(
            id=sid,
            kind=kind,
            after=after,
            type=ttype,
            draft=f"{folder}/{draft}",
            allowed_paths=tuple(str(p) for p in paths),
            fork=fid,
        )
        return step, "", ()
    if kind == "explore_run":
        script = str(raw.get("script", ""))
        if not SCRIPT.match(script):
            problems.append(f"{where}: script must look like 0007_some_name_{fid}")
        inherits = str(raw.get("inherits") or "")
        rules = raw.get("rules") or []
        if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
            problems.append(f"{where}: rules must be a list of kill-rule library names")
            rules = []
        step = Step(id=sid, kind=kind, after=after, script=script, fork=fid, inherits=inherits)
        return step, inherits, tuple(rules)
    stage, target = str(raw.get("stage", "")), str(raw.get("target", ""))
    if stage not in STAGES:
        problems.append(f"{where}: stage must be acquire or build")
    if not TARGET.match(target):
        problems.append(f"{where}: target must be a pipeline script name")
    step = Step(
        id=sid,
        kind=kind,
        after=after,
        stage=stage,
        target=target,
        dataset=str(raw.get("dataset", "")),
        fork=fid,
    )
    return step, "", ()


def _body(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :])
    return ""


def parse_fork(
    c: Any, path: str, text: str, library: dict[str, LibraryRule], problems: list[str]
) -> tuple[Fork | None, list]:
    """One fork file: the Fork and its steps (kill rules resolved by code), or None."""
    from terrain.campaigns.spec import KillRule, read_front_matter

    name = path.rsplit("/", 1)[-1]
    m = FORK_FILE.match(name)
    where = path
    if not m:
        problems.append(f"{where}: a fork file must be named f1.md to f9.md")
        return None, []
    fid = f"f{m.group(1)}"
    fm = read_front_matter(text)
    if isinstance(fm, str):
        problems.append(f"{where}: {fm}")
        return None, []
    extra = sorted(str(k) for k in fm if k not in FORK_KEYS)
    missing = sorted(
        k for k in FORK_KEYS - {"headline", "sample_on", "title", "delta"} if k not in fm
    )
    if extra:
        problems.append(f"{where}: unknown keys {extra}")
    if missing:
        problems.append(f"{where}: missing keys {missing}")
        return None, []
    if fm.get("id") != fid:
        problems.append(f"{where}: id must be {fid}, the file's name")
    if fm.get("campaign") != c.id:
        problems.append(f'{where}: campaign must be the quoted id "{c.id}"')
    ftype = str(fm.get("type", ""))
    if ftype not in TYPES:
        problems.append(f"{where}: type must be one of {list(TYPES)}")
    order = fm.get("order")
    if not _whole(order, 1):
        problems.append(f"{where}: order must be a whole number from 1")
        order = 0
    verdict = str(fm.get("parent_verdict", ""))
    if verdict not in VERDICTS:
        problems.append(f"{where}: parent_verdict must be killed or survived")
    dimension = fm.get("dimension")
    if not isinstance(dimension, str) or not dimension.strip() or len(dimension) > DIMENSION_MAX:
        problems.append(
            f"{where}: dimension must say, in at most {DIMENSION_MAX} characters, what changes"
        )
        dimension = ""
    elif "\n" in dimension.strip():
        problems.append(f"{where}: dimension must be one line: one declared difference (F5)")
    headline = fm.get("headline")
    if ftype == "question":
        if not isinstance(headline, str) or not headline.strip():
            problems.append(f"{where}: a question fork needs a one-sentence headline")
            headline = ""
    elif headline not in (None, ""):
        problems.append(f"{where}: only a question fork has a headline")
    sample_on = fm.get("sample_on")
    if ftype == "sample":
        if sample_on not in SAMPLE_ON:
            problems.append(
                f"{where}: a sample fork must say what it filters on, one of {list(SAMPLE_ON)}; "
                "never an outcome (F6)"
            )
    elif sample_on not in (None, ""):
        problems.append(f"{where}: only a sample fork has sample_on")
    evidence = fm.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append(f"{where}: evidence must list the run records that motivate it")
        evidence = []
    datasets = fm.get("datasets")
    if not isinstance(datasets, list):
        problems.append(f"{where}: datasets must be a list ([] for none)")
        datasets = []
    adopts = fm.get("adopts_downstream")
    if not isinstance(adopts, bool):
        problems.append(f"{where}: adopts_downstream must be true or false")
        adopts = False
    delta = fm.get("delta") or ""
    if not isinstance(delta, str) or len(delta) > DELTA_MAX or "<!--" in delta or "-->" in delta:
        problems.append(
            f"{where}: delta must be text of at most {DELTA_MAX} characters, no HTML comments"
        )
        delta = ""
    if adopts and not delta.strip():
        problems.append(f"{where}: a fork that adopts the skipped steps needs its delta text")
    body = _body(text)
    if "<!--" in body or "-->" in body:
        problems.append(f"{where}: may not contain HTML comments")
    for heading in BODY_SECTIONS:
        if not any(ln.strip().startswith(heading) for ln in body.split("\n")):
            problems.append(f"{where}: needs a section '{heading}'")
    title_line = next((ln for ln in body.split("\n") if ln.startswith("# ")), "")
    title = str(fm.get("title") or title_line.removeprefix("# ").removeprefix(f"{fid}:").strip())
    raw_steps = fm.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        problems.append(f"{where}: steps must be a non-empty list")
        raw_steps = []
    parent = c.step(str(fm.get("parent_step", "")))
    if parent is None or parent.kind != "explore_run":
        problems.append(
            f"{where}: parent_step {fm.get('parent_step')} is no explore_run of the plan "
            "(a fork varies a step of the plan, never a fork's step: no forks of forks, F11)"
        )
    steps = []
    for raw in raw_steps:
        got = _fork_step(raw, fid, c.folder, where, problems)
        if got is None:
            continue
        step, inherits, names = got
        if step.kind == "explore_run":
            rules: list = []
            if ftype == "question":
                if inherits:
                    problems.append(
                        f"{where} step {step.id}: a question fork's run takes its rules by name "
                        "from the kill-rule library (rules), not from its parent (F4)"
                    )
                for n in names:
                    lib = library.get(n)
                    if lib is None:
                        problems.append(
                            f"{where} step {step.id}: '{n}' is not in the kill-rule library"
                        )
                    else:
                        rules.append(lib)
            else:
                if names:
                    problems.append(
                        f"{where} step {step.id}: only a question fork names library rules; "
                        "this one inherits its parent's (F4)"
                    )
                if parent and inherits != parent.id:
                    problems.append(
                        f"{where} step {step.id}: inherits must name the parent step "
                        f"{fm.get('parent_step')} (F4)"
                    )
                rules = list(parent.kill_rules) if parent and inherits == parent.id else []
                if ftype == "sample":
                    lib = library.get(MIN_CLUSTERS)
                    if lib is None:
                        problems.append(f"{where}: the library has no rule '{MIN_CLUSTERS}' (F6)")
                    else:
                        rules.append(lib)
            resolved: list[KillRule] = []
            for r in rules:
                if isinstance(r, LibraryRule):
                    resolved.append(
                        KillRule(
                            id=f"k{len(resolved) + 1}",
                            says=r.says,
                            field=r.field,
                            op=r.op,
                            value=r.value,
                            confirmed=r.confirmed,
                        )
                    )
                else:
                    resolved.append(r)  # copied unchanged, with its own id
            ids = [r.id for r in resolved]
            if len(ids) != len(set(ids)):  # a library rule after inherited ones: renumber it
                taken: set[str] = set()
                fixed = []
                for r in resolved:
                    rid, n = r.id, len(taken) + 1
                    while rid in taken:
                        rid, n = f"k{n}", n + 1
                    taken.add(rid)
                    fixed.append(KillRule(rid, r.says, r.field, r.op, r.value, r.confirmed))
                resolved = fixed
            if not counting_rules(tuple(resolved), library):
                problems.append(
                    f"{where} step {step.id}: needs a kill rule other than 'finite' (F4); "
                    "this variant can only be a suggestion"
                )
            step = replace_step(step, kill_rules=tuple(resolved), library_rules=names)
        steps.append(step)
    fork = Fork(
        id=fid,
        path=path,
        parent_step=str(fm.get("parent_step", "")),
        parent_verdict=verdict,
        order=order,
        type=ftype,
        title=title,
        dimension=str(dimension).strip(),
        headline=str(headline or "").strip(),
        sample_on=str(sample_on or ""),
        evidence=tuple(str(e) for e in evidence),
        datasets=tuple(d for d in datasets if isinstance(d, dict)),
        adopts_downstream=adopts,
        delta=delta.strip(),
        step_ids=tuple(s.id for s in steps),
        body=body,
    )
    return fork, steps


def replace_step(step: Any, **changes: Any) -> Any:
    from dataclasses import replace

    return replace(step, **changes)


def attach(
    root: Path,
    c: Any,
    problems: list[str],
    overlay: Overlay | None = None,
    library: dict[str, LibraryRule] | None = None,
) -> tuple[tuple[Fork, ...], tuple]:
    """The campaign's forks and their steps, read from main (and the overlay)."""
    paths = fork_files(root, c.folder, overlay)
    if not paths:
        return (), ()
    library = load_library(root) if library is None else library
    if c.forks is None:
        problems.append(
            f"{c.folder}: has fork files but no forks envelope in campaign.md (no envelope, "
            "no forks)"
        )
        return (), ()
    forks, steps = [], []
    for path in paths:
        text = _read(root, path, overlay)
        if text is None:
            continue
        fork, fsteps = parse_fork(c, path, text, library, problems)
        if fork is not None:
            forks.append(fork)
            steps.extend(fsteps)
    forks.sort(key=lambda f: f.number)
    return tuple(forks), tuple(steps)


# -- checks against the repository and the envelope -------------------------------------


def parent_records(root: Path, c: Any, parent: Any) -> dict[str, str]:
    """Record path (.md) -> the parent's verdict on it, for each record of its script."""
    from terrain.campaigns.rules import evaluate

    out: dict[str, str] = {}
    d = root / "research" / "explore-runs" / c.idea
    if not d.is_dir():
        return out
    for md in sorted(d.glob("*.md")):
        first = md.read_text(encoding="utf-8").split("\n", 1)[0]
        if not first.startswith(f"# {parent.script}, run "):
            continue
        js = md.with_suffix(".json")
        if not js.is_file():
            continue
        try:
            results = json.loads(js.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out[md.relative_to(root).as_posix()] = evaluate(parent.kill_rules, results).outcome
    return out


def adoptable(c: Any, parent_id: str) -> list[str]:
    """Plan steps a kill at `parent_id` skips, which a surviving fork may adopt (F9).

    With `skip_dependents`, the steps after it; with `stop`, every step of the
    plan that is not before it; with `continue`, none (a kill skips nothing).
    The tick adopts only those that were in fact skipped and never started.
    """
    from terrain.campaigns.spec import ancestors

    parent = c.step(parent_id)
    if parent is None or parent.fork or parent.kind != "explore_run":
        return []
    main = [s.id for s in c.main_steps]
    if parent.on_kill == "continue":
        return []
    if parent.on_kill == "stop":
        before = ancestors(c, parent_id) | {parent_id}
        return [s for s in main if s not in before]
    deps = c.dependents(parent_id)
    return [s for s in main if s in deps]


def _path_ok(p: str, fork: Fork, ttype: str) -> str:
    """Why allowed path `p` is not allowed in a task of `fork` ("" if it is)."""
    stem = p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if ttype == "build" and p == CATALOG:
        return "" if fork.datasets else f"only a fork with new data may change {CATALOG}"
    if not stem.endswith(f"_{fork.id}"):
        return (
            f"'{p}' is not a new file of this fork: every file a fork writes is named *_{fork.id} "
            "(a fork never changes its parent's files)"
        )
    if ttype == "explore" and not p.startswith(("explore/", "tests/test_explore")):
        return f"an explore task may change only explore/ and tests/test_explore*, not '{p}'"
    if ttype == "build" and not p.startswith(BUILD_DIRS):
        return f"a fork's build task may write only under {', '.join(BUILD_DIRS)}, not '{p}'"
    if p.startswith("research/"):
        return f"'{p}' is a record; a fork's steps write code only"
    return ""


def check(
    root: Path,
    c: Any,
    owners: CodeOwners,
    overlay: Overlay | None = None,
    library: dict[str, LibraryRule] | None = None,
    publishers: dict[str, dict] | None = None,
) -> list[str]:
    """Every problem with the campaign's forks (the brief's section 7.3)."""
    from terrain.campaigns.spec import NOTES_PATH, ancestors, is_protected, path_allowed

    problems: list[str] = []
    library = load_library(root) if library is None else library
    publishers = load_publishers(root) if publishers is None else publishers
    check_envelope(c, library, problems)
    forks = c.fork_files
    if not forks:
        return problems
    env = c.forks
    points = fork_points(c, library)
    main_ids = {s.id for s in c.main_steps}
    top = max((_step_num(s) for s in main_ids), default=0)
    seen_ids: set[str] = set(main_ids)
    closed = c.status in ("done", "stopped")
    if len(forks) > env.max_forks:
        problems.append(
            f"{c.folder}: {len(forks)} forks, more than forks.max_forks {env.max_forks}"
        )
    questions = [f for f in forks if f.type == "question"]
    if len(questions) > env.max_question_forks:
        problems.append(
            f"{c.folder}: {len(questions)} question forks, more than "
            f"forks.max_question_forks {env.max_question_forks}"
        )
    n_data = sum(len(f.datasets) for f in forks)
    if n_data > env.max_new_datasets:
        problems.append(
            f"{c.folder}: the forks bring {n_data} new datasets, more than "
            f"forks.max_new_datasets {env.max_new_datasets}"
        )
    by_point: dict[str, list[Fork]] = {}
    for f in forks:
        by_point.setdefault(f.parent_step, []).append(f)
    for point, at in by_point.items():
        if len(at) > env.per_point:
            problems.append(
                f"{c.folder}: {len(at)} forks at {point}, more than forks.per_point {env.per_point}"
            )
        orders = sorted(f.order for f in at)
        if orders != list(range(1, len(at) + 1)):
            problems.append(f"{c.folder}: the forks at {point} must be in order 1 to {len(at)}")
    fsteps = [s for s in c.steps if s.fork]
    used = {
        "max_tasks": sum(1 for s in fsteps if s.kind == "task"),
        "max_explore_runs": sum(1 for s in fsteps if s.kind == "explore_run"),
        "max_pipeline_runs": sum(1 for s in fsteps if s.kind == "pipeline_run"),
    }
    for key, n in used.items():
        if n > env.budget.get(key, 0):
            problems.append(
                f"{c.folder}: the forks list {n} for forks.budget.{key}, "
                f"which is {env.budget.get(key, 0)}"
            )
    datasets_seen = {str(d.get("name")) for d in c.datasets if isinstance(d, dict)}
    for f in forks:
        where = f.path
        parent = c.step(f.parent_step)
        if parent is None or parent.kind != "explore_run":
            problems.append(f"{where}: parent_step {f.parent_step} is no explore_run of the plan")
            continue
        if parent.fork:
            problems.append(f"{where}: {f.parent_step} is a fork's step; no forks of forks (F11)")
            continue
        if f.parent_step not in points:
            problems.append(f"{where}: {f.parent_step} is not a fork point of this campaign")
        if f.parent_verdict not in env.on:
            problems.append(
                f"{where}: forks.on does not open a fork point on a '{f.parent_verdict}' verdict"
            )
        if f.type not in env.types:
            problems.append(f"{where}: type {f.type} is not in forks.types")
        steps = [c.step(sid) for sid in f.step_ids]
        if not any(s.kind == "explore_run" for s in steps):
            problems.append(f"{where}: a fork needs an explore run, which gives it its verdict")
        if len(steps) > env.max_steps_per_fork:
            problems.append(
                f"{where}: {len(steps)} steps, more than forks.max_steps_per_fork "
                f"{env.max_steps_per_fork}"
            )
        # evidence, and the parent's verdict on record
        verdicts = parent_records(root, c, parent)
        for e in f.evidence:
            if not (e.startswith("research/explore-runs/") and e.endswith((".md", ".json"))):
                problems.append(f"{where}: evidence '{e}' is not a run record")
            elif _read(root, e, overlay) is None:
                problems.append(f"{where}: evidence '{e}' does not exist on main")
        md = {e: e.removesuffix(".json") + ".md" if e.endswith(".json") else e for e in f.evidence}
        on_record = [e for e in f.evidence if md[e] in verdicts]
        if not on_record:
            problems.append(
                f"{where}: no evidence is a run record of {parent.script} (the parent's script)"
            )
        elif not any(verdicts[md[e]] == f.parent_verdict for e in on_record):
            problems.append(
                f"{where}: parent_verdict is {f.parent_verdict}, but {f.parent_step}'s kill rules "
                f"give another verdict on {on_record[0]}"
            )
        # adoption
        if f.adopts_downstream:
            if f.parent_verdict != "killed":
                problems.append(f"{where}: only a fork at a killed point may adopt steps (F9)")
            elif not adoptable(c, f.parent_step):
                problems.append(
                    f"{where}: adopts_downstream, but a kill at {f.parent_step} skips no step"
                )
        # datasets (F7)
        for d in f.datasets:
            name = str(d.get("name", ""))
            dw = f"{where}: dataset '{name}'"
            extra = sorted(set(d) - DATASET_KEYS)
            missing = sorted(DATASET_KEYS - set(d))
            if extra or missing:
                problems.append(f"{dw}: keys must be exactly {sorted(DATASET_KEYS)}")
                continue
            if not name.endswith(f"_{f.id}"):
                problems.append(f"{dw}: a fork's dataset is named *_{f.id}")
            if name in datasets_seen:
                problems.append(f"{dw}: already listed by the campaign or another fork")
            datasets_seen.add(name)
            if d.get("publisher") not in publishers:
                problems.append(
                    f"{dw}: publisher '{d.get('publisher')}' is not in {PUBLISHERS_PATH} (F7)"
                )
            if d.get("identifiers") != "none":
                problems.append(f"{dw}: identifiers must be none (F7)")
            size = d.get("max_size_gb")
            if (
                isinstance(size, bool)
                or not isinstance(size, int | float)
                or not 0 < size <= FORK_MAX_SIZE_GB
            ):
                problems.append(f"{dw}: max_size_gb must be above 0 and at most {FORK_MAX_SIZE_GB}")
        # steps
        own: set[str] = set()
        for s in steps:
            sw = f"{where} step {s.id}"
            if _step_num(s.id) <= top:
                problems.append(f"{sw}: fork step ids continue after the plan's last step s{top}")
            if s.id in seen_ids:
                problems.append(f"{sw}: the id {s.id} is already used")
            seen_ids.add(s.id)
            allowed_after = {f.parent_step} | ancestors(c, f.parent_step) | own
            bad = [a for a in s.after if a not in allowed_after]
            if bad:
                problems.append(
                    f"{sw}: may come after only {f.parent_step}, the steps before it and this "
                    f"fork's earlier steps, not {bad} (no fork depends on another, F11)"
                )
            if f.parent_step not in ancestors(c, s.id):
                problems.append(f"{sw}: must come after {f.parent_step}, the fork point")
            own.add(s.id)
            if s.kind == "task":
                for p in s.allowed_paths:
                    why = _path_ok(p, f, s.type)
                    if p.startswith("/") or ".." in p.split("/") or "*" in p:
                        why = f"'{p}' must be one full file path"
                    elif is_protected(p):
                        why = f"'{p}' is protected (AGENTS.md)"
                    elif path_allowed(NOTES_PATH, (p,)):
                        why = f"'{p}' is the agent notes, which only a close-out writes"
                    elif owners.owned(p) and not closed:
                        why = why or f"'{p}' is owned in CODEOWNERS"
                    if why:
                        problems.append(f"{sw}: {why}")
                draft = _read(root, s.draft, overlay)
                if draft is not None and DIFFERS not in draft:
                    problems.append(f"{s.draft}: needs a section '{DIFFERS}' (F5)")
                if draft is None:
                    problems.append(f"{sw}: its draft {s.draft} does not exist")
                elif not draft.split("\n", 1)[0].startswith("# Task: "):
                    problems.append(f"{s.draft}: the first line must be '# Task: <title>'")
                elif "<!--" in draft or "-->" in draft:
                    problems.append(f"{s.draft}: drafts may not contain HTML comments")
                elif "## Done when" not in draft:
                    problems.append(f"{s.draft}: needs a '## Done when' section")
            elif s.kind == "explore_run":
                if not s.script.endswith(f"_{f.id}"):
                    problems.append(f"{sw}: the script of a fork is named *_{f.id}")
                if not s.script.startswith(f"{c.idea}_"):
                    problems.append(f"{sw}: the script belongs to idea {c.idea}")
                for r in s.kill_rules:
                    if not r.confirmed and c.status == "active":
                        problems.append(
                            f"{sw}: kill rule {r.id} ({r.says}) is not confirmed by the owner"
                        )
            else:
                if s.dataset not in {str(d.get("name")) for d in f.datasets}:
                    problems.append(
                        f"{sw}: runs dataset '{s.dataset}', which the fork does not list"
                    )
                if not s.target.endswith(f"_{f.id}"):
                    problems.append(f"{sw}: the target of a fork is named *_{f.id}")
    return problems


def check_registrations(root: Path, c: Any) -> list[str]:
    """F10: a registered specification of this idea lists every fork tried.

    `src/terrain/confirm.py` refuses unknown keys in a specification, and
    agents never change it or `confirm/`, so the list lives in the spec's
    `hypothesis` text, as one line `Forks tried: f1, f2 (2).` (decision 0015).
    """
    if not c.fork_files:
        return []
    d = root / SPECS_DIR
    if not d.is_dir():
        return []
    ids = ", ".join(f.id for f in c.fork_files)
    want = f"Forks tried in campaign {c.id}: {ids} ({len(c.fork_files)})."
    out = []
    for spec in sorted(d.glob(f"{c.idea}-*.yaml")):
        try:
            raw = yaml.safe_load(spec.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        hyp = raw.get("hypothesis", "") if isinstance(raw, dict) else ""
        if want not in " ".join(str(hyp).split()):
            out.append(
                f"{spec.relative_to(root).as_posix()}: idea {c.idea} had forks; its hypothesis "
                f"must list every fork tried: '{want}' (decision 0015, F10)"
            )
    return out
