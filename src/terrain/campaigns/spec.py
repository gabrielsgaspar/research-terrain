"""Load and validate campaign files.

A campaign lives in `research/campaigns/NNNN-slug/`:

    campaign.md        front matter (the machine-readable plan) + reasoning
    drafts/<step>.md   one issue draft per task step, filed word for word

`load_campaigns` reads every campaign; `validate` returns one message per
problem, so `uv run python scripts/campaign.py validate` and the tests can
print them all at once.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from terrain.campaigns.codeowners import CodeOwners

CAMPAIGNS_DIR = "research/campaigns"
STATUSES = {"draft", "active", "done", "stopped"}
KINDS = {"task", "explore_run", "pipeline_run"}
TASK_TYPES = {"explore", "build"}
STAGES = {"acquire", "build"}
OPS = {"<", "<=", ">", ">=", "==", "!="}
ON_KILL = {"stop", "skip_dependents", "continue"}
IDENTIFIERS = {"none", "hashed"}
REFEREE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
MAX_ACTIVE = 2

# Paths an agent may never change, whatever a campaign says (AGENTS.md,
# "Scope", and the builder's protected list in agent-build.yml).
PROTECTED_DIRS = (
    ".github/",
    ".claude/",
    "harness/",
    "legacy/",
    "overleaf/",
    "confirm/",
    "data/fixtures/",
    "data/manifests/",
    "data/reference/",
    "sealed/",
)
PROTECTED_FILES = ("pyproject.toml", "uv.lock", "AGENTS.md", "CLAUDE.md")

FOLDER = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]{0,40}$")
STEP_ID = re.compile(r"^s\d{1,2}$")
SCRIPT = re.compile(r"^(\d{4})_[a-z0-9_]{1,60}$")
TARGET = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FIELD = re.compile(r"^[A-Za-z0-9_%.\-]+(\.[A-Za-z0-9_%.\-]+)*$")
OWNER = re.compile(r"^[A-Za-z0-9-]{1,39}$")

REQUIRED_KEYS = {
    "id",
    "title",
    "status",
    "idea",
    "owner",
    "created",
    "end_by",
    "budget",
    "datasets",
    "steps",
}
BUDGET_KEYS = {"max_tasks", "max_explore_runs", "max_pipeline_runs", "max_model_jobs"}


class PlainLoader(yaml.SafeLoader):
    """Safe loader that leaves dates as strings, so a bad date is reported, not raised."""


PlainLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass(frozen=True)
class KillRule:
    id: str
    says: str
    field: str
    op: str
    value: Any
    confirmed: bool


@dataclass(frozen=True)
class Step:
    id: str
    kind: str
    after: tuple[str, ...] = ()
    # task
    type: str = ""
    draft: str = ""  # repository path of the draft
    allowed_paths: tuple[str, ...] = ()
    # explore_run
    script: str = ""
    kill_rules: tuple[KillRule, ...] = ()
    on_kill: str = "skip_dependents"
    # pipeline_run
    stage: str = ""
    target: str = ""
    dataset: str = ""


@dataclass(frozen=True)
class Campaign:
    id: str
    folder: str  # repository path, e.g. research/campaigns/0001-replay
    title: str
    status: str
    idea: str
    owner: str
    created: str
    end_by: str
    budget: dict[str, int]
    datasets: tuple[dict[str, Any], ...]
    steps: tuple[Step, ...]
    referee_not_applicable_ok: tuple[str, ...] = ("R5",)
    problems: tuple[str, ...] = field(default=())

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def dependents(self, step_id: str) -> set[str]:
        """Every step that depends on `step_id`, directly or not."""
        out: set[str] = set()
        frontier = {step_id}
        while frontier:
            nxt = {s.id for s in self.steps if set(s.after) & frontier} - out
            out |= nxt
            frontier = nxt
        return out


def read_front_matter(text: str) -> dict | str:
    """The front matter mapping, or a message saying what is wrong."""
    lines = text.splitlines()
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
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or path.startswith(PROTECTED_DIRS)


def path_allowed(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """True if `path` equals a pattern, or matches one whose `*` stays in one segment."""
    for pattern in patterns:
        if path == pattern:
            return True
        if "*" in pattern and path.count("/") == pattern.count("/"):
            if fnmatch.fnmatchcase(path, pattern):
                return True
    return False


def _as_tuple(value: object) -> tuple:
    return tuple(value) if isinstance(value, list) else ()


def _kill_rule(raw: object, where: str, problems: list[str]) -> KillRule | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: a kill rule must be a mapping")
        return None
    for key in ("id", "says", "field", "op", "value", "confirmed"):
        if key not in raw:
            problems.append(f"{where}: kill rule is missing '{key}'")
    if any(k not in raw for k in ("id", "field", "op", "value")):
        return None
    rule = KillRule(
        id=str(raw["id"]),
        says=str(raw.get("says", "")),
        field=str(raw["field"]),
        op=str(raw["op"]),
        value=raw["value"],
        confirmed=raw.get("confirmed") is True,
    )
    if not re.fullmatch(r"k\d{1,2}", rule.id):
        problems.append(f"{where}: kill rule id '{rule.id}' must look like k1")
    if not FIELD.match(rule.field):
        problems.append(f"{where}: kill rule {rule.id} field '{rule.field}' is not a dotted path")
    if rule.op not in OPS:
        problems.append(f"{where}: kill rule {rule.id} op must be one of {sorted(OPS)}")
    if rule.op in {"<", "<=", ">", ">="} and (
        isinstance(rule.value, bool) or not isinstance(rule.value, int | float)
    ):
        problems.append(
            f"{where}: kill rule {rule.id} compares with {rule.op}, so value must be a number"
        )
    if not rule.says.strip():
        problems.append(f"{where}: kill rule {rule.id} needs 'says', the rule in plain words")
    return rule


def _step(raw: object, folder: str, index: int, problems: list[str]) -> Step | None:
    where = f"{folder}/campaign.md: step {index + 1}"
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be a mapping")
        return None
    sid, kind = str(raw.get("id", "")), str(raw.get("kind", ""))
    where = f"{folder}/campaign.md: step {sid or index + 1}"
    if not STEP_ID.match(sid):
        problems.append(f"{where}: id must look like s1")
    if kind not in KINDS:
        problems.append(f"{where}: kind must be one of {sorted(KINDS)}")
        return None
    after = tuple(str(a) for a in _as_tuple(raw.get("after", [])))
    if "after" in raw and not isinstance(raw["after"], list):
        problems.append(f"{where}: after must be a list of step ids")
    if kind == "task":
        draft = str(raw.get("draft", ""))
        ttype = str(raw.get("type", ""))
        paths = tuple(str(p) for p in _as_tuple(raw.get("allowed_paths")))
        if ttype not in TASK_TYPES:
            problems.append(f"{where}: type must be explore or build")
        if not re.fullmatch(r"drafts/s\d{1,2}\.md", draft) or draft != f"drafts/{sid}.md":
            problems.append(f"{where}: draft must be drafts/{sid}.md")
        if not paths:
            problems.append(f"{where}: allowed_paths must list the files the task may change")
        for p in paths:
            if p.startswith("/") or ".." in p.split("/") or p.endswith("/") or "**" in p:
                problems.append(
                    f"{where}: allowed path '{p}' must be a full file path (one * per name at most)"
                )
            elif is_protected(p):
                problems.append(f"{where}: allowed path '{p}' is protected (AGENTS.md)")
            elif ttype == "explore" and not p.startswith(("explore/", "tests/test_explore")):
                problems.append(
                    f"{where}: an explore task may change only explore/ and "
                    f"tests/test_explore*, not '{p}'"
                )
        return Step(
            id=sid,
            kind=kind,
            after=after,
            type=ttype,
            draft=f"{folder}/{draft}",
            allowed_paths=paths,
        )
    if kind == "explore_run":
        script = str(raw.get("script", ""))
        if not SCRIPT.match(script):
            problems.append(f"{where}: script must look like 0003_some_name")
        rules = []
        for r in _as_tuple(raw.get("kill_rules", [])):
            rule = _kill_rule(r, where, problems)
            if rule:
                rules.append(rule)
        ids = [r.id for r in rules]
        if len(ids) != len(set(ids)):
            problems.append(f"{where}: kill rule ids repeat")
        on_kill = str(raw.get("on_kill", "skip_dependents"))
        if on_kill not in ON_KILL:
            problems.append(f"{where}: on_kill must be one of {sorted(ON_KILL)}")
        return Step(
            id=sid, kind=kind, after=after, script=script, kill_rules=tuple(rules), on_kill=on_kill
        )
    stage, target = str(raw.get("stage", "")), str(raw.get("target", ""))
    if stage not in STAGES:
        problems.append(f"{where}: stage must be acquire or build")
    if not TARGET.match(target):
        problems.append(f"{where}: target must be a pipeline script name such as tse_candidates")
    return Step(
        id=sid,
        kind=kind,
        after=after,
        stage=stage,
        target=target,
        dataset=str(raw.get("dataset", "")),
    )


def _check_graph(c: Campaign, problems: list[str]) -> None:
    where = f"{c.folder}/campaign.md"
    ids = [s.id for s in c.steps]
    if len(ids) != len(set(ids)):
        problems.append(f"{where}: step ids repeat")
    known = set(ids)
    for s in c.steps:
        for a in s.after:
            if a not in known:
                problems.append(f"{where}: step {s.id} is after unknown step '{a}'")
            elif ids.index(a) >= ids.index(s.id):
                problems.append(f"{where}: step {s.id} must come after {a} in the list")


def _check_against_repo(c: Campaign, root: Path, owners: CodeOwners, problems: list[str]) -> None:
    where = f"{c.folder}/campaign.md"
    ideas = list((root / "research" / "ideas").glob(f"{c.idea}-*.md"))
    if not ideas:
        problems.append(f"{where}: idea {c.idea} has no file in research/ideas/")
    dataset_names = {str(d.get("name")) for d in c.datasets if isinstance(d, dict)}
    for s in c.steps:
        if s.kind == "task":
            draft = root / s.draft
            if not draft.is_file():
                problems.append(f"{where}: step {s.id}'s draft {s.draft} does not exist")
            else:
                text = draft.read_text(encoding="utf-8")
                first = text.splitlines()[0] if text.strip() else ""
                if not first.startswith("# Task: "):
                    problems.append(f"{s.draft}: the first line must be '# Task: <title>'")
                if "<!--" in text:
                    problems.append(
                        f"{s.draft}: drafts may not contain HTML comments "
                        "(markers are added when filed)"
                    )
                if "## Done when" not in text:
                    problems.append(f"{s.draft}: needs a '## Done when' section")
            for p in s.allowed_paths:
                if owners.owned(p):
                    problems.append(
                        f"{where}: allowed path '{p}' is owned in CODEOWNERS; "
                        "the gate cannot merge it"
                    )
        elif s.kind == "explore_run":
            m = SCRIPT.match(s.script)
            if m and m.group(1) != c.idea:
                problems.append(
                    f"{where}: step {s.id}'s script {s.script} belongs to idea "
                    f"{m.group(1)}, not {c.idea}"
                )
            exists = (root / "explore" / f"{s.script}.py").is_file()
            earlier = _ancestors(c, s.id)
            made_before = any(
                f"explore/{s.script}.py" in c.step(a).allowed_paths
                for a in earlier
                if c.step(a) and c.step(a).kind == "task"
            )
            if not exists and not made_before:
                problems.append(
                    f"{where}: step {s.id} runs explore/{s.script}.py, which neither exists nor is "
                    "written by an earlier task step it is after"
                )
            if not s.kill_rules:
                problems.append(f"{where}: step {s.id} has no kill rules; say what would kill it")
            for r in s.kill_rules:
                if c.status == "active" and not r.confirmed:
                    problems.append(
                        f"{where}: step {s.id} kill rule {r.id} is not confirmed by the owner"
                    )
        elif s.kind == "pipeline_run":
            if s.dataset not in dataset_names:
                problems.append(
                    f"{where}: step {s.id} uses dataset '{s.dataset}', "
                    "which is not listed in datasets"
                )
            if not (root / "pipeline" / s.stage / f"{s.target}.py").is_file():
                earlier = _ancestors(c, s.id)
                path = f"pipeline/{s.stage}/{s.target}.py"
                if not any(c.step(a) and path in c.step(a).allowed_paths for a in earlier):
                    problems.append(
                        f"{where}: step {s.id} runs {path}, which neither exists "
                        "nor is written by an earlier task step"
                    )


def _ancestors(c: Campaign, step_id: str) -> set[str]:
    out: set[str] = set()
    frontier = set(c.step(step_id).after) if c.step(step_id) else set()
    while frontier:
        out |= frontier
        frontier = {a for f in frontier if c.step(f) for a in c.step(f).after} - out
    return out


def _check_datasets(c: Campaign, problems: list[str]) -> None:
    where = f"{c.folder}/campaign.md"
    for d in c.datasets:
        if not isinstance(d, dict):
            problems.append(f"{where}: each dataset must be a mapping")
            continue
        name = str(d.get("name", ""))
        for key in ("name", "source", "licence", "max_size_gb", "identifiers"):
            if key not in d:
                problems.append(f"{where}: dataset '{name}' is missing '{key}'")
        if name and not TARGET.match(name):
            problems.append(f"{where}: dataset name '{name}' must look like a catalog name")
        size = d.get("max_size_gb")
        if size is not None and (
            isinstance(size, bool) or not isinstance(size, int | float) or size <= 0
        ):
            problems.append(f"{where}: dataset '{name}' max_size_gb must be a positive number")
        if "identifiers" in d and d["identifiers"] not in IDENTIFIERS:
            problems.append(f"{where}: dataset '{name}' identifiers must be none or hashed")


def parse_campaign(root: Path, folder: Path) -> Campaign:
    """Read one campaign folder. Problems are collected on the result, never raised."""
    rel = folder.relative_to(root).as_posix()
    problems: list[str] = []
    path = folder / "campaign.md"
    m = FOLDER.match(folder.name)
    cid = m.group(1) if m else ""
    if not m:
        problems.append(f"{rel}: folder name must be NNNN-slug (lowercase, digits, hyphens)")
    if not path.is_file():
        problems.append(f"{rel}: missing campaign.md")
        return Campaign(cid, rel, "", "draft", "", "", "", "", {}, (), (), problems=tuple(problems))
    fm = read_front_matter(path.read_text(encoding="utf-8"))
    if isinstance(fm, str):
        problems.append(f"{rel}/campaign.md: {fm}")
        return Campaign(cid, rel, "", "draft", "", "", "", "", {}, (), (), problems=tuple(problems))
    where = f"{rel}/campaign.md"
    for key in sorted(REQUIRED_KEYS - fm.keys()):
        problems.append(f"{where}: missing key '{key}'")
    if not isinstance(fm.get("id"), str) or fm.get("id") != cid:
        problems.append(f"{where}: 'id' must be the quoted folder number \"{cid}\"")
    status = str(fm.get("status", ""))
    if status not in STATUSES:
        problems.append(f"{where}: status must be one of {sorted(STATUSES)}")
    idea = fm.get("idea")
    if not isinstance(idea, str) or not re.fullmatch(r"\d{4}", idea):
        problems.append(f"{where}: 'idea' must be a quoted four-digit id")
        idea = ""
    owner = str(fm.get("owner", ""))
    if not OWNER.match(owner):
        problems.append(f"{where}: 'owner' must be a GitHub login")
    created, end_by = parse_date(fm.get("created")), parse_date(fm.get("end_by"))
    if created is None:
        problems.append(f"{where}: 'created' is not a YYYY-MM-DD date")
    if end_by is None:
        problems.append(f"{where}: 'end_by' is not a YYYY-MM-DD date")
    if created and end_by and end_by < created:
        problems.append(f"{where}: 'end_by' is before 'created'")
    if created and end_by and (end_by - created).days > 31:
        problems.append(f"{where}: a campaign may run at most 31 days")
    raw_budget = fm.get("budget") if isinstance(fm.get("budget"), dict) else {}
    budget: dict[str, int] = {}
    for key in sorted(BUDGET_KEYS):
        value = raw_budget.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(f"{where}: budget.{key} must be a whole number, 0 or more")
        else:
            budget[key] = value
    extra = sorted(set(raw_budget) - BUDGET_KEYS)
    if extra:
        problems.append(f"{where}: unknown budget keys {extra}")
    na_ok = tuple(str(r) for r in _as_tuple(fm.get("referee_not_applicable_ok", ["R5"])))
    for r in na_ok:
        if r not in REFEREE_IDS:
            problems.append(f"{where}: referee_not_applicable_ok lists unknown check '{r}'")
    datasets = tuple(fm.get("datasets") or ()) if isinstance(fm.get("datasets", []), list) else ()
    if not isinstance(fm.get("datasets", []), list):
        problems.append(f"{where}: datasets must be a list")
    steps: list[Step] = []
    raw_steps = fm.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        problems.append(f"{where}: steps must be a non-empty list")
        raw_steps = []
    for i, raw in enumerate(raw_steps):
        s = _step(raw, rel, i, problems)
        if s:
            steps.append(s)
    c = Campaign(
        id=cid,
        folder=rel,
        title=str(fm.get("title", "")),
        status=status,
        idea=idea,
        owner=owner,
        created=str(fm.get("created", "")),
        end_by=str(fm.get("end_by", "")),
        budget=budget,
        datasets=datasets,
        steps=tuple(steps),
        referee_not_applicable_ok=na_ok,
    )
    _check_graph(c, problems)
    _check_datasets(c, problems)
    tasks = sum(1 for s in steps if s.kind == "task")
    runs = sum(1 for s in steps if s.kind == "explore_run")
    pipes = sum(1 for s in steps if s.kind == "pipeline_run")
    for key, n in (("max_tasks", tasks), ("max_explore_runs", runs), ("max_pipeline_runs", pipes)):
        if key in budget and budget[key] < n:
            problems.append(f"{where}: budget.{key} is {budget[key]} but the campaign lists {n}")
    return Campaign(**{**c.__dict__, "problems": tuple(problems)})


def load_campaigns(root: Path) -> list[Campaign]:
    d = root / CAMPAIGNS_DIR
    if not d.is_dir():
        return []
    return [parse_campaign(root, p) for p in sorted(d.iterdir()) if p.is_dir()]


def validate(root: Path) -> list[str]:
    """Every problem in every campaign, plus the rules across campaigns."""
    owners = CodeOwners.from_repo(root)
    campaigns = load_campaigns(root)
    problems: list[str] = []
    seen_ids: dict[str, str] = {}
    for c in campaigns:
        problems += list(c.problems)
        if c.id and c.id in seen_ids:
            problems.append(f"{c.folder}: campaign id {c.id} is also used by {seen_ids[c.id]}")
        seen_ids.setdefault(c.id, c.folder)
        if not c.problems:
            extra: list[str] = []
            _check_against_repo(c, root, owners, extra)
            problems += extra
    active = [c for c in campaigns if c.status == "active"]
    if len(active) > MAX_ACTIVE:
        problems.append(
            f"{CAMPAIGNS_DIR}: {len(active)} campaigns are active; at most {MAX_ACTIVE} may be"
        )
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if a.idea and a.idea == b.idea:
                problems.append(f"{a.folder} and {b.folder} are both active on idea {a.idea}")
            pa = {p for s in a.steps for p in s.allowed_paths}
            pb = {p for s in b.steps for p in s.allowed_paths}
            clash = sorted(p for p in pa if path_allowed(p, tuple(pb))) + sorted(
                p for p in pb if path_allowed(p, tuple(pa))
            )
            if clash:
                problems.append(
                    f"{a.folder} and {b.folder} share allowed paths: {sorted(set(clash))}"
                )
    return problems


def active_campaigns(root: Path) -> list[Campaign]:
    """Active campaigns, or none at all if any campaign file has a problem.

    CI runs `validate` on every pull request, so main should always be clean;
    if it is not, nothing runs until a person fixes it.
    """
    if validate(root):
        return []
    return [c for c in load_campaigns(root) if c.status == "active"]


def finished_campaigns(root: Path) -> list[Campaign]:
    """Done or stopped campaigns, whose tracking issues the tick closes.

    None at all if any campaign file has a problem, as for `active_campaigns`.
    """
    if validate(root):
        return []
    return [c for c in load_campaigns(root) if c.status in ("done", "stopped")]
