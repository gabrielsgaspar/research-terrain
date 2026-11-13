"""Forks (decision 0015): the envelope, fork files, the kill-rule library, publishers.

Most tests replay campaign 0007 from its own files and run records, copied
into tmp_path, with the default envelope added: its first-stage run (s15)
was killed (F 2.44 against a rule of at least 10), and the same run showed a
yes/no measure with F 12.28. Nothing here calls the network or a model.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest
import yaml

from terrain.campaigns import forks
from terrain.campaigns.card import render_card
from terrain.campaigns.codeowners import CodeOwners
from terrain.campaigns.spec import load_campaigns, validate

REPO = Path(__file__).resolve().parents[1]
C07 = "research/campaigns/0007-gold-and-the-ballot"
RECORD = "research/explore-runs/0007/43438404852"  # s15's run: killed, F 2.44

ENVELOPE = """\
forks:
  max_forks: 5
  per_point: 3
  max_new_datasets: 2
  max_steps_per_fork: 4
  types: [transform, sample, spec, measure, question]
  max_question_forks: 1
  on: [killed, survived]
  fork_points: all
  budget:
    max_tasks: 10
    max_explore_runs: 7
    max_pipeline_runs: 6
    max_model_jobs: 45
"""

DELTA = "Use geo_exposed (yes/no) wherever the draft says geo_gold_per_km2."

FORK_DRAFT = """\
# Task: first stage with a yes/no gold measure (explore, fork f1 of campaign 0007)

## Goal

Run campaign 0007's first stage (step s15) with gold exposure as yes/no.

## What differs from the parent

Only the exposure: `geo_exposed` (yes/no) instead of `geo_gold_per_km2`.

## Done when

1. `uv run pytest` passes.
"""


def fork_text(**over) -> str:
    """Fork f1 of campaign 0007, as in the brief's section 6.2, with changes."""
    fm = {
        "id": "f1",
        "campaign": "0007",
        "parent_step": "s15",
        "parent_verdict": "killed",
        "order": 1,
        "type": "transform",
        "dimension": "exposure: yes/no (geo_exposed) instead of density",
        "headline": None,
        "sample_on": None,
        "evidence": [f"{RECORD}.md"],
        "datasets": [],
        "adopts_downstream": True,
        "delta": DELTA,
        "steps": [
            {
                "id": "s24",
                "kind": "task",
                "type": "explore",
                "draft": "forks/f1/drafts/s24.md",
                "allowed_paths": [
                    "explore/0007_gold_first_stage_f1.py",
                    "tests/test_explore_gold_first_stage_f1.py",
                ],
                "after": ["s15"],
            },
            {
                "id": "s25",
                "kind": "explore_run",
                "script": "0007_gold_first_stage_f1",
                "inherits": "s15",
                "after": ["s24"],
            },
        ],
    }
    body = over.pop("body", None)
    fm.update(over)
    fm = {k: v for k, v in fm.items() if v != "DROP"}
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n\n" + (
        body
        or textwrap.dedent(
            """\
                # f1: yes/no gold measure

                ## Why (from the ideation job)

                The same run gave F 12.28 with a yes/no measure.

                ## What differs from the parent

                The exposure measure only.

                ## What a pass or a fail would mean

                A pass: the politics phase can use the yes/no measure. A fail: the idea is dead.
                """
        )
    )


def replay_repo(root: Path, envelope: str = ENVELOPE, status: str = "active") -> Path:
    """Campaign 0007's files and records in `root`, active, with `envelope` added."""
    for d in (C07, "research/ideas", "research/explore-runs/0007", "pipeline"):
        shutil.copytree(REPO / d, root / d)
    (root / "explore").mkdir()
    for f in (REPO / "explore").glob("0007_*.py"):
        shutil.copy(f, root / "explore" / f.name)
    for f in (
        "data/catalog.yaml",
        forks.PUBLISHERS_PATH,
        forks.LIBRARY_PATH,
        ".github/CODEOWNERS",
    ):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / f, root / f)
    path = root / C07 / "campaign.md"
    text = path.read_text(encoding="utf-8").replace("status: done", f"status: {status}", 1)
    if envelope:
        text = text.replace("self_repair: true\n", "self_repair: true\n" + envelope, 1)
    path.write_text(text, encoding="utf-8")
    return root


def add_fork(root: Path, fid: str = "f1", text: str | None = None, drafts=None) -> None:
    folder = root / C07 / "forks"
    (folder / fid / "drafts").mkdir(parents=True, exist_ok=True)
    (folder / f"{fid}.md").write_text(text or fork_text(), encoding="utf-8")
    for sid, draft in (drafts or {"s24": FORK_DRAFT}).items():
        (folder / fid / "drafts" / f"{sid}.md").write_text(draft, encoding="utf-8")


def campaign_0007(root: Path):
    (c,) = [c for c in load_campaigns(root) if c.id == "0007"]
    return c


# -- the records Gabriel owns ------------------------------------------------------------


def test_library_and_publishers_on_main_are_valid():
    assert forks.check_records(REPO) == []
    lib = forks.load_library(REPO)
    table = {n: (r.field, r.op, r.value) for n, r in lib.items()}
    assert table == {
        "first_stage_strength": ("first_stage.f_cluster", "<", 10),
        "pretrend_ratio": ("placebo.lead_ratio", ">", 0.5),
        "power_mde_sd": ("power.mde_sd", ">", 0.10),
        "power_mde_share": ("power.mde_share", ">", 0.25),
        "finite": ("estimates.finite", "!=", True),
        "min_clusters": ("sample.n_clusters", "<", 100),
    }
    assert not lib["finite"].counts and all(r.counts for n, r in lib.items() if n != "finite")
    # the new rule waits for Gabriel; the others he confirmed in campaigns 0004 to 0007
    assert [n for n, r in lib.items() if not r.confirmed] == ["min_clusters"]
    assert "new, proposed; confirm or change" in lib["min_clusters"].source
    pubs = forks.load_publishers(REPO)
    assert {"tse", "ibge", "mapbiomas", "base_dos_dados", "world_bank", "fred", "anm"} <= set(pubs)
    assert (
        "never select name, cpf, cnpj, phone or e-mail"
        in " ".join(pubs["base_dos_dados"]["rules"]).lower()
    )


def test_new_records_are_owned_and_fork_files_are_not():
    owners = CodeOwners.from_repo(REPO)
    assert owners.owned(forks.LIBRARY_PATH) and owners.owned(forks.PUBLISHERS_PATH)
    assert owners.owned("tests/test_forks.py") and owners.owned("src/terrain/campaigns/forks.py")
    # the tick merges fork plans, so fork files are not owned; the gate keeps them append-only
    for path in (f"{C07}/forks/f1.md", f"{C07}/forks/f1/drafts/s24.md"):
        assert not owners.owned(path), path


@pytest.mark.parametrize(
    "text, problem",
    [
        ("rules: {}\n", "needs a list 'rules'"),
        (
            "rules:\n  - {name: x1, says: s, field: a, op: '<', value: big, confirmed: true}\n",
            "value must be a number",
        ),
        (
            "rules:\n  - {name: finite, says: s, field: a, op: '!=', value: true, "
            "confirmed: true}\n",
            "has no rule 'min_clusters'",
        ),
    ],
)
def test_a_bad_library_is_reported(tmp_path, text, problem):
    (tmp_path / forks.LIBRARY_PATH).parent.mkdir(parents=True)
    (tmp_path / forks.LIBRARY_PATH).write_text(text, encoding="utf-8")
    assert any(problem in p for p in forks.check_records(tmp_path))


def test_publisher_hosts_are_bare_names(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / forks.PUBLISHERS_PATH).write_text(
        "publishers:\n  - {id: xx, name: X, hosts: ['https://x.test/a'], catalog: []}\n",
        encoding="utf-8",
    )
    assert any("bare host names" in p for p in forks.check_records(tmp_path))


# -- the envelope -------------------------------------------------------------------------


def test_campaigns_without_forks_are_unchanged():
    """Every real campaign: no envelope, no fork files, the plan's steps only."""
    assert validate(REPO) == []
    for c in load_campaigns(REPO):
        assert c.forks is None and c.fork_files == () and c.main_steps == c.steps
        assert "- Forks: no (no `forks:` block" in render_card(REPO, c.id)


def test_the_default_envelope_validates_and_opens_points(tmp_path):
    root = replay_repo(tmp_path)
    assert validate(root) == []
    c = campaign_0007(root)
    assert c.forks == forks.default_envelope()
    # s9 and s15 have rules other than "finite"; s23 has only "finite" (F4)
    assert forks.fork_points(c, forks.load_library(root)) == ["s9", "s15"]
    card = render_card(root, "0007")
    assert "- Forks: yes, at most 5 variants (3 per point, 1 question fork, 4 steps each" in card
    assert "their own budget: 10 tasks, 7 explore runs, 6 pipeline runs, 45 model jobs" in card


@pytest.mark.parametrize(
    "line, value, problem",
    [
        ("max_forks: 5", "max_forks: 6", "forks.max_forks must be a whole number of at most 5"),
        ("max_new_datasets: 2", "max_new_datasets: 3", "forks.max_new_datasets"),
        ("max_steps_per_fork: 4", "max_steps_per_fork: 7", "forks.max_steps_per_fork"),
        ("max_question_forks: 1", "max_question_forks: 3", "forks.max_question_forks"),
        ("per_point: 3", "per_point: 0", "forks.per_point"),
        ("types: [transform, sample, spec, measure, question]", "types: [hunch]", "forks.types"),
        ("on: [killed, survived]", "on: [maybe]", "forks.on"),
        ("fork_points: all", "fork_points: some", "forks.fork_points"),
        ("fork_points: all", "fork_points: [s23]", "whose only kill rule is 'finite'"),
        ("fork_points: all", "fork_points: [s14]", "names s14, which is no explore_run"),
        ("    max_model_jobs: 45\n", "", "forks.budget.max_model_jobs"),
        ("max_forks: 5", "max_forks: 5\n  extra_key: 1", "unknown keys ['extra_key']"),
    ],
)
def test_envelope_caps_and_keys(tmp_path, line, value, problem):
    root = replay_repo(tmp_path, ENVELOPE.replace(line, value, 1))
    problems = validate(root)
    assert any(problem in p for p in problems), problems


def test_fork_files_without_an_envelope_are_refused(tmp_path):
    root = replay_repo(tmp_path, envelope="")
    add_fork(root)
    assert any("has fork files but no forks envelope" in p for p in validate(root))


# -- a fork file ----------------------------------------------------------------------------


def test_the_yes_no_fork_validates_and_inherits_s15s_rules(tmp_path):
    """The brief's section 10: the fork of 0007's killed s15, as in section 6.2."""
    root = replay_repo(tmp_path)
    add_fork(root)
    assert validate(root) == []
    c = campaign_0007(root)
    (f1,) = c.fork_files
    assert (f1.parent_step, f1.parent_verdict, f1.type, f1.step_ids) == (
        "s15",
        "killed",
        "transform",
        ("s24", "s25"),
    )
    assert [s.id for s in c.steps][-2:] == ["s24", "s25"] and len(c.main_steps) == 23
    s15, s25 = c.step("s15"), c.step("s25")
    assert s25.fork == "f1" and s25.inherits == "s15"
    assert s25.kill_rules == s15.kill_rules and len(s25.kill_rules) == 3  # copied unchanged
    assert c.step("s24").draft == f"{C07}/forks/f1/drafts/s24.md"
    # a kill at s15 (on_kill: stop) skips every later step of the plan: s16 to s23
    assert forks.adoptable(c, "s15") == [f"s{n}" for n in range(16, 24)]


def mutate_step(index: int, **changes):
    steps = yaml.safe_load(fork_text().split("---\n")[1])["steps"]
    steps[index].update(changes)
    return {"steps": steps}


@pytest.mark.parametrize(
    "over, problem",
    [
        # restates a threshold, or writes a rule of its own (F4)
        (
            mutate_step(1, kill_rules=[{"id": "k1", "field": "f", "op": "<", "value": 9}]),
            "keys ['kill_rules'] are not allowed in a fork step",
        ),
        (mutate_step(1, value=9), "keys ['value'] are not allowed"),
        (mutate_step(1, on_kill="continue"), "keys ['on_kill'] are not allowed"),
        (mutate_step(1, inherits="s9"), "inherits must name the parent step s15"),
        # changes a parent file (F1, F2)
        (
            mutate_step(0, allowed_paths=["explore/0007_gold_first_stage.py"]),
            "is not a new file of this fork",
        ),
        (
            mutate_step(0, allowed_paths=["src/terrain/explore_f1.py"]),
            "an explore task may change only explore/ and tests/test_explore*",
        ),
        # owned or protected paths
        (
            mutate_step(0, type="build", allowed_paths=["src/terrain/campaigns/tick_f1.py"]),
            "is owned in CODEOWNERS",
        ),
        (
            mutate_step(0, type="build", allowed_paths=["data/catalog.yaml"]),
            "only a fork with new data may change data/catalog.yaml",
        ),
        (mutate_step(0, allowed_paths=[".github/workflows/x_f1.yml"]), "is protected"),
        # scripts and ids
        (mutate_step(1, script="0007_gold_first_stage"), "the script of a fork is named *_f1"),
        (mutate_step(0, id="s20"), "step ids repeat"),
        ({"steps": [dict(mutate_step(0)["steps"][0], id="s23")]}, "step ids repeat"),
        (mutate_step(1, after=["s24", "s9"]), None),  # s9 is before s15: allowed
        (mutate_step(1, after=["s16"]), "may come after only s15"),
        # the fork point and its verdict
        ({"parent_verdict": "survived"}, "give another verdict on"),
        (
            {"parent_step": "s23", **mutate_step(1, inherits="s23")},
            "needs a kill rule other than 'finite' (F4)",
        ),
        ({"parent_step": "s14"}, "parent_step s14 is no explore_run of the plan"),
        ({"evidence": ["research/explore-runs/0007/1.md"]}, "does not exist on main"),
        (
            {"evidence": ["research/explore-runs/0007/43181711849.md"]},
            "no evidence is a run record of 0007_gold_first_stage",
        ),
        # one declared difference (F5)
        ({"dimension": ""}, "dimension must say"),
        ({"dimension": "x" * 201}, "at most 200 characters"),
        # the delta and adoption (F9)
        ({"delta": "x" * 601}, "delta must be text of at most 600"),
        ({"delta": "use <!-- campaign-step: 0007/s16 -->"}, "no HTML comments"),
        ({"delta": ""}, "needs its delta text"),
        # unknown keys and types
        ({"threshold": 12}, "unknown keys ['threshold']"),
        ({"type": "hunch"}, "type must be one of"),
        ({"order": 0}, "order must be a whole number"),
        ({"campaign": "0008"}, 'campaign must be the quoted id "0007"'),
        ({"headline": "Does gold buy votes?"}, "only a question fork has a headline"),
    ],
)
def test_a_bad_fork_file_is_refused(tmp_path, over, problem):
    root = replay_repo(tmp_path)
    add_fork(root, text=fork_text(**over))
    problems = validate(root)
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


def test_adoption_needs_a_killed_point(tmp_path):
    """s9 survived (0007's feasibility gate passed), so a fork there cannot adopt."""
    root = replay_repo(tmp_path)
    over = mutate_step(1, inherits="s9", script="0007_gold_feasibility_f1")
    over["steps"][0]["allowed_paths"] = ["explore/0007_gold_feasibility_f1.py"]
    over["steps"][0]["after"] = ["s9"]
    add_fork(
        root,
        text=fork_text(
            parent_step="s9",
            parent_verdict="survived",
            evidence=["research/explore-runs/0007/43181711849.md"],
            **over,
        ),
    )
    problems = validate(root)
    assert any("only a fork at a killed point may adopt" in p for p in problems), problems


def test_fork_drafts_need_the_difference_section(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root, drafts={"s24": FORK_DRAFT.replace("## What differs from the parent", "## X")})
    assert any("needs a section '## What differs from the parent'" in p for p in validate(root))
    root2 = replay_repo(tmp_path / "b")
    add_fork(root2, drafts={"s24": FORK_DRAFT + "\n<!-- campaign-step: 0007/s24 -->\n"})
    assert any("may not contain HTML comments" in p for p in validate(root2))


def test_fork_file_needs_its_three_sections(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root, text=fork_text(body="# f1: x\n\n## Why\n\nBecause.\n"))
    problems = validate(root)
    assert any("needs a section '## What differs from the parent'" in p for p in problems)
    assert any("needs a section '## What a pass or a fail would mean'" in p for p in problems)


# -- question and sample forks (F4, F6) -------------------------------------------------------


def question_fork(rules, **over) -> str:
    steps = yaml.safe_load(fork_text().split("---\n")[1])["steps"]
    del steps[1]["inherits"]
    steps[1]["rules"] = rules
    steps[0]["allowed_paths"] = ["explore/0007_gold_entry_f1.py"]
    steps[1]["script"] = "0007_gold_entry_f1"
    fm = {
        "type": "question",
        "headline": "Does the gold price change who runs for council where gold lies?",
        "dimension": "outcome: candidate entry instead of garimpo area",
        "adopts_downstream": False,
        "delta": "",
        "steps": steps,
    }
    fm.update(over)
    return fork_text(**fm)


def test_a_question_fork_takes_library_rules_by_name(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root, text=question_fork(["power_mde_sd", "finite"]))
    assert validate(root) == []
    s25 = campaign_0007(root).step("s25")
    assert [(r.id, r.field, r.op, r.value) for r in s25.kill_rules] == [
        ("k1", "power.mde_sd", ">", 0.10),
        ("k2", "estimates.finite", "!=", True),
    ]
    assert s25.library_rules == ("power_mde_sd", "finite")


@pytest.mark.parametrize(
    "rules, over, problem",
    [
        (["finite"], {}, "needs a kill rule other than 'finite' (F4)"),
        (["power_mde_cheap"], {}, "'power_mde_cheap' is not in the kill-rule library"),
        (["power_mde_sd"], {"headline": None}, "a question fork needs a one-sentence headline"),
    ],
)
def test_a_bad_question_fork_is_refused(tmp_path, rules, over, problem):
    root = replay_repo(tmp_path)
    add_fork(root, text=question_fork(rules, **over))
    assert any(problem in p for p in validate(root))


def test_question_fork_cannot_inherit_and_others_cannot_name_rules(tmp_path):
    root = replay_repo(tmp_path)
    text = question_fork(["power_mde_sd"])
    add_fork(root, text=text.replace("rules:\n", "inherits: s15\n  rules:\n", 1))
    assert any("takes its rules by name" in p for p in validate(root))
    root2 = replay_repo(tmp_path / "b")
    add_fork(root2, text=fork_text(**mutate_step(1, rules=["power_mde_sd"])))
    assert any("only a question fork names library rules" in p for p in validate(root2))


def sample_fork(sample_on="geography") -> str:
    return fork_text(
        type="sample",
        sample_on=sample_on,
        dimension="sample: the Legal Amazon only",
        adopts_downstream=False,
        delta="",
    )


def test_a_sample_fork_gets_min_clusters_and_waits_for_its_confirmation(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root, text=sample_fork())
    s25 = campaign_0007(root).step("s25")
    assert [r.field for r in s25.kill_rules] == [
        "first_stage.f_cluster",
        "placebo.lead_ratio",
        "estimates.finite",
        "sample.n_clusters",
    ]
    assert s25.kill_rules[-1].id == "k4"
    # min_clusters is new and unconfirmed in the library on main, so it cannot run yet
    assert any("is not confirmed by the owner" in p for p in validate(root))
    lib = root / forks.LIBRARY_PATH
    text = lib.read_text(encoding="utf-8")
    lib.write_text(text.replace("confirmed: false", "confirmed: true"), encoding="utf-8")
    assert validate(root) == []


@pytest.mark.parametrize("sample_on", [None, "outcome", "garimpo_share"])
def test_a_sample_fork_must_filter_on_what_is_fixed_before_the_outcome(tmp_path, sample_on):
    root = replay_repo(tmp_path)
    add_fork(root, text=sample_fork(sample_on))
    assert any("never an outcome (F6)" in p for p in validate(root))


# -- new data (F7) -----------------------------------------------------------------------------


def data_fork(**dataset_over) -> str:
    d = {
        "name": "mapbiomas_water_f1",
        "source": "MapBiomas Água, Earth Engine asset",
        "licence": "CC BY 4.0",
        "max_size_gb": 2,
        "identifiers": "none",
        "publisher": "mapbiomas",
    }
    d.update(dataset_over)
    d = {k: v for k, v in d.items() if v != "DROP"}
    over = mutate_step(0, type="build")
    over["steps"][0]["allowed_paths"] = [
        "data/catalog.yaml",
        "pipeline/acquire/mapbiomas_water_f1.py",
    ]
    over["steps"].insert(
        1,
        {
            "id": "s25",
            "kind": "pipeline_run",
            "stage": "acquire",
            "target": "mapbiomas_water_f1",
            "dataset": "mapbiomas_water_f1",
            "after": ["s24"],
        },
    )
    over["steps"][2].update({"id": "s26", "after": ["s25"]})
    over["steps"].insert(
        2,
        {
            "id": "s27",
            "kind": "task",
            "type": "explore",
            "draft": "forks/f1/drafts/s27.md",
            "allowed_paths": ["explore/0007_gold_first_stage_f1.py"],
            "after": ["s24"],
        },
    )
    over["steps"][3]["after"] = ["s25", "s27"]
    return fork_text(type="measure", datasets=[d], adopts_downstream=False, delta="", **over)


DATA_DRAFTS = {"s24": FORK_DRAFT, "s27": FORK_DRAFT}


def test_a_measure_fork_may_bring_data_from_an_approved_publisher(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root, text=data_fork(), drafts=DATA_DRAFTS)
    assert validate(root) == [], validate(root)
    assert campaign_0007(root).all_datasets[-1]["name"] == "mapbiomas_water_f1"


@pytest.mark.parametrize(
    "over, problem",
    [
        ({"publisher": "some_blog"}, "is not in data/approved-publishers.yaml (F7)"),
        ({"identifiers": "hashed"}, "identifiers must be none (F7)"),
        ({"max_size_gb": 6}, "max_size_gb must be above 0 and at most 5"),
        ({"publisher": "DROP"}, "keys must be exactly"),
    ],
)
def test_new_data_outside_the_rules_is_refused(tmp_path, over, problem):
    root = replay_repo(tmp_path)
    add_fork(root, text=data_fork(**over), drafts=DATA_DRAFTS)
    assert any(problem in p for p in validate(root))


# -- caps across forks ---------------------------------------------------------------------------


def numbered_fork(k: int, order: int, **over) -> str:
    base, run = 22 + 2 * k, 23 + 2 * k
    steps = [
        {
            "id": f"s{base}",
            "kind": "task",
            "type": "explore",
            "draft": f"forks/f{k}/drafts/s{base}.md",
            "allowed_paths": [f"explore/0007_gold_first_stage_f{k}.py"],
            "after": ["s15"],
        },
        {
            "id": f"s{run}",
            "kind": "explore_run",
            "script": f"0007_gold_first_stage_f{k}",
            "inherits": "s15",
            "after": [f"s{base}"],
        },
    ]
    text = fork_text(id=f"f{k}", order=order, steps=steps, **over)
    return text.replace("# f1:", f"# f{k}:")


def test_more_forks_at_a_point_than_per_point_are_refused(tmp_path):
    root = replay_repo(tmp_path)
    for k in range(1, 5):
        add_fork(root, f"f{k}", numbered_fork(k, k), {f"s{22 + 2 * k}": FORK_DRAFT})
    problems = validate(root)
    assert any("4 forks at s15, more than forks.per_point 3" in p for p in problems), problems


def test_fork_orders_and_the_fork_budget(tmp_path):
    root = replay_repo(tmp_path, ENVELOPE.replace("max_explore_runs: 7", "max_explore_runs: 1"))
    add_fork(root, "f1", numbered_fork(1, 1), {"s24": FORK_DRAFT})
    add_fork(root, "f2", numbered_fork(2, 3), {"s26": FORK_DRAFT})
    problems = validate(root)
    assert any("the forks at s15 must be in order 1 to 2" in p for p in problems)
    assert any(
        "the forks list 2 for forks.budget.max_explore_runs, which is 1" in p for p in problems
    )


def test_too_many_steps_in_one_fork(tmp_path):
    root = replay_repo(tmp_path, ENVELOPE.replace("max_steps_per_fork: 4", "max_steps_per_fork: 1"))
    add_fork(root)
    assert any("2 steps, more than forks.max_steps_per_fork 1" in p for p in validate(root))


def test_no_forks_of_forks(tmp_path):
    """F11: a fork's own run is never a fork point."""
    root = replay_repo(tmp_path)
    add_fork(root)
    over = mutate_step(1, inherits="s25", script="0007_gold_first_stage_f2")
    over["steps"][0].update(
        {
            "id": "s26",
            "draft": "forks/f2/drafts/s26.md",
            "after": ["s25"],
            "allowed_paths": ["explore/0007_gold_first_stage_f2.py"],
        }
    )
    over["steps"][1].update({"id": "s27", "after": ["s26"]})
    add_fork(root, "f2", fork_text(id="f2", parent_step="s25", **over), {"s26": FORK_DRAFT})
    assert any(
        "parent_step s25 is no explore_run of the plan" in p and "F11" in p for p in validate(root)
    )


# -- the gate's view: fork files read from a pull request, not from disk -------------------------


def test_fork_files_can_come_from_an_overlay(tmp_path):
    root = replay_repo(tmp_path)
    from terrain.campaigns.spec import parse_campaign

    overlay = {f"{C07}/forks/f1.md": fork_text(), f"{C07}/forks/f1/drafts/s24.md": FORK_DRAFT}
    c = parse_campaign(root, root / C07, overlay)
    assert c.problems == () and [f.id for f in c.fork_files] == ["f1"]
    assert forks.check(root, c, CodeOwners.from_repo(root), overlay) == []
    assert not (root / C07 / "forks").exists()


# -- F10: a registration lists every fork tried ---------------------------------------------------


def test_a_registration_of_an_idea_with_forks_lists_them(tmp_path):
    root = replay_repo(tmp_path)
    add_fork(root)
    c = campaign_0007(root)
    (root / forks.SPECS_DIR).mkdir(parents=True)
    spec = root / forks.SPECS_DIR / "0007-gold-yes-no.yaml"
    spec.write_text("hypothesis: Gold moves garimpo.\n", encoding="utf-8")
    (problem,) = forks.check_registrations(root, c)
    assert "Forks tried in campaign 0007: f1 (1)." in problem
    spec.write_text(
        "hypothesis: Gold moves garimpo. Forks tried in campaign 0007: f1 (1).\n",
        encoding="utf-8",
    )
    assert forks.check_registrations(root, c) == []


def test_registrations_on_main_list_their_forks():
    for c in load_campaigns(REPO):
        assert forks.check_registrations(REPO, c) == []


# =============================================================================================
# The machinery: the tick, the gate, the act job, forks-from-json and the review (pull request 2)
# =============================================================================================

import json  # noqa: E402

from terrain.campaigns import ideation, markers  # noqa: E402
from terrain.campaigns.facts import Comment, Issue, PullRequest, Review, Run, Snapshot  # noqa: E402
from terrain.campaigns.gate import GateContext, evaluate  # noqa: E402
from terrain.campaigns.spec import active_campaigns  # noqa: E402
from terrain.campaigns.tick import decide  # noqa: E402

BOT = "terrain-agent[bot]"
OWNER = "gabrielsgaspar"
SHA = "a" * 40
T0 = "2026-11-13T14:00:00Z"  # s15 recorded
NOW = "2026-11-13T15:00:00Z"
LATER = "2026-11-13T18:00:00Z"  # more than two hours after NOW
RUN_IDS = {"s9": 43181711849, "s15": 43438404852}
IDEATE_PATH = ".github/workflows/campaign-ideate.yml"
REFEREE_OK = {f"R{i}": "OK" for i in range(1, 9)}


def merged_pr(number: int, head_ref: str, **over) -> PullRequest:
    base = dict(
        number=number,
        author=BOT,
        head_ref=head_ref,
        head_sha=SHA,
        state="closed",
        merged=True,
        mergeable=None,
        files=(),
        ci_test="success",
        gate_status="success",
    )
    base.update(over)
    return PullRequest(**base)


def task_issue_of(root: Path, c, sid: str, number: int, pr=None, extra: str = "") -> Issue:
    title, body = markers.draft_body((root / c.step(sid).draft).read_text(encoding="utf-8"))
    tail = markers.step_marker("0007", sid)
    s = c.step(sid)
    if s.fork:
        tail += "\n" + markers.fork_marker("0007", s.fork)
    return Issue(
        number,
        title,
        f"{body}{extra}\n\n{tail}\n",
        "closed" if pr and pr.merged else "open",
        ("campaign",),
        BOT,
        T0,
        (),
        pr,
    )


def run_of(c, sid: str, run_id: int, conclusion="success", status="completed") -> Run:
    s = c.step(sid)
    if s.kind == "explore_run":
        title = markers.explore_run_title(s.script, "0007", sid)
        wf = "explore-run.yml"
    else:
        title = markers.pipeline_run_title(s.stage, s.target, "0007", sid)
        wf = "data-pipeline.yml"
    return Run(run_id, wf, title, status, conclusion, T0, T0)


def write_record(root: Path, script: str, run_id: int, results: dict) -> None:
    d = root / "research" / "explore-runs" / "0007"
    (d / f"{run_id}.json").write_text(json.dumps(results), encoding="utf-8")
    (d / f"{run_id}.md").write_text(f"# {script}, run {run_id}\n", encoding="utf-8")


def results_of(root: Path) -> dict:
    d = root / "research" / "explore-runs" / "0007"
    return {
        f"research/explore-runs/0007/{p.name}": json.loads(p.read_text(encoding="utf-8"))
        for p in d.glob("*.json")
    }


def ledger_comment(*events: str, at: str = T0, body: str = "- x") -> Comment:
    return Comment(BOT, f"{body}\n\n" + markers.ledger_marker("0007", list(events)), at)


def none_comment(sid: str, at: str = T0) -> Comment:
    facts = {"proposed": 0, "refused": 0, "forks": []}
    return Comment(BOT, "no fork\n\n" + markers.ideation_marker("0007", sid, facts), at)


def snapshot_0007(
    root: Path,
    now: str = NOW,
    done: tuple[str, ...] = tuple(f"s{n}" for n in range(1, 16)),
    comments: tuple[Comment, ...] = (),
    issues: tuple[Issue, ...] = (),
    runs: tuple[Run, ...] = (),
    record_prs: dict | None = None,
    fork_prs: dict | None = None,
) -> Snapshot:
    """Campaign 0007 with the plan's steps in `done` finished as they did (s15 killed)."""
    c = campaign_0007(root)
    out_issues, out_runs, recs = [], [], {}
    for n, sid in enumerate(done):
        s = c.step(sid)
        if s.kind == "task":
            pr = merged_pr(200 + n, f"agent/issue-{100 + n}")
            out_issues.append(task_issue_of(root, c, sid, 100 + n, pr))
        else:
            rid = RUN_IDS.get(sid, 1000 + n)
            out_runs.append(run_of(c, sid, rid))
            branch = (
                f"explore/{s.script}-{rid}"
                if s.kind == "explore_run"
                else f"data/{s.stage}-{s.target}-{rid}"
            )
            recs[rid] = merged_pr(300 + n, branch)
    track = Issue(
        1,
        "Campaign 0007",
        f"x\n{markers.tracking_marker('0007')}",
        "open",
        ("campaign",),
        BOT,
        T0,
        (ledger_comment("started"), *comments),
    )
    recs.update(record_prs or {})
    return Snapshot(
        now=now,
        enabled=True,
        app_bot=BOT,
        issues=[track, *out_issues, *issues],
        runs=[*out_runs, *runs],
        record_prs=recs,
        results=results_of(root),
        fork_prs=fork_prs or {},
    )


def gate_ctx(root: Path) -> GateContext:
    return GateContext(BOT, OWNER, tuple(active_campaigns(root)), CodeOwners.from_repo(root), root)


def tick(root: Path, s: Snapshot) -> list[dict]:
    return decide(active_campaigns(root), s, gate_ctx(root), root)


def events_of(actions) -> set[str]:
    out = set()
    for a in actions:
        if a["type"] == "comment":
            found = markers.parse_ledger(a["body"])
            out |= found[1] if found else set()
    return out


def ledger_text(actions) -> str:
    return "\n".join(a["body"] for a in actions if a["type"] == "comment")


def dispatches(actions, workflow: str) -> list[dict]:
    return [a["inputs"] for a in actions if a["type"] == "dispatch" and a["workflow"] == workflow]


def filed(actions) -> list[dict]:
    return [a for a in actions if a["type"] == "create_issue"]


# -- the 0007 replay through the tick ---------------------------------------------------------


def test_without_an_envelope_the_killed_s15_closes_the_campaign_as_before(tmp_path):
    """Section 8: no `forks:` block, the same behaviour: s15's kill stops 0007."""
    root = replay_repo(tmp_path, envelope="")
    actions = tick(root, snapshot_0007(root))
    assert not dispatches(actions, "campaign-ideate.yml")
    assert not {e for e in events_of(actions) if ":ideate" in e or e.startswith("adopt:")}
    (closeout,) = filed(actions)
    assert markers.parse_closeout(closeout["body"]) == "0007"
    assert "Campaign finished: a kill rule stopped it." in ledger_text(actions)
    assert "## Forks" not in closeout["body"]


def test_the_killed_s15_opens_a_fork_point_and_starts_ideation_once(tmp_path):
    root = replay_repo(tmp_path)
    actions = tick(root, snapshot_0007(root, comments=(none_comment("s9"),)))
    assert dispatches(actions, "campaign-ideate.yml") == [{"campaign": "0007", "step": "s15"}]
    assert "- s15: fork point; ideation started." in ledger_text(actions)
    assert not filed(actions)  # no close-out while ideation runs
    # the next tick: ideation in flight, nothing started twice, still no close-out
    again = tick(
        root,
        snapshot_0007(root, comments=(none_comment("s9"), ledger_comment("s15:ideate", at=NOW))),
    )
    assert not dispatches(again, "campaign-ideate.yml") and not filed(again)


def test_s9_survived_is_a_fork_point_too_with_both_verdicts_listed(tmp_path):
    root = replay_repo(tmp_path)
    actions = tick(root, snapshot_0007(root))
    assert {d["step"] for d in dispatches(actions, "campaign-ideate.yml")} == {"s9", "s15"}
    root2 = replay_repo(tmp_path / "b", ENVELOPE.replace("on: [killed, survived]", "on: [killed]"))
    actions = tick(root2, snapshot_0007(root2))
    assert dispatches(actions, "campaign-ideate.yml") == [{"campaign": "0007", "step": "s15"}]


def test_ideation_that_times_out_never_blocks_the_campaign(tmp_path):
    root = replay_repo(tmp_path)
    started = (none_comment("s9"), ledger_comment("s15:ideate", at=NOW))
    actions = tick(root, snapshot_0007(root, now=LATER, comments=started))
    assert "- s15: ideation timed out; no forks at s15." in ledger_text(actions)
    (closeout,) = filed(actions)
    assert markers.parse_closeout(closeout["body"]) == "0007"
    assert "### How many were tried" in closeout["body"]


def test_no_fork_advisable_closes_the_point(tmp_path):
    root = replay_repo(tmp_path)
    actions = tick(root, snapshot_0007(root, comments=(none_comment("s9"), none_comment("s15"))))
    assert "- s15: ideation found no fork to run (0 proposed, 0 refused" in ledger_text(actions)
    assert len(filed(actions)) == 1  # the close-out


def fork_plan_pr(root: Path, files: dict[str, str], **over) -> PullRequest:
    base = dict(
        number=90,
        author=BOT,
        head_ref="forks/0007-s15-777",
        head_sha=SHA,
        state="open",
        merged=False,
        mergeable=True,
        files=tuple(files),
        ci_test="success",
        gate_status="success",
        run_title="Ideate campaign 0007/s15",
        run_conclusion="success",
        run_workflow=IDEATE_PATH,
        changes=tuple((p, "added") for p in files),
        added_texts=tuple(files.items()),
    )
    base.update(over)
    return PullRequest(**base)


FORK_FILES = {f"{C07}/forks/f1.md": fork_text(), f"{C07}/forks/f1/drafts/s24.md": FORK_DRAFT}


def test_the_tick_merges_a_fork_plan_the_gate_passes(tmp_path):
    root = replay_repo(tmp_path)
    pr = fork_plan_pr(root, FORK_FILES)
    assert evaluate(pr, gate_ctx(root)).state == "success"
    comments = (none_comment("s9"), ledger_comment("s15:ideate", at=NOW))
    actions = tick(root, snapshot_0007(root, comments=comments, fork_prs={777: pr}))
    assert {"type": "merge", "pr": 90, "sha": SHA} in actions
    assert "- s15: the ideation proposed forks in PR #90" in ledger_text(actions)
    assert not filed(actions)


def with_fork(tmp_path, envelope: str = ENVELOPE) -> Path:
    root = replay_repo(tmp_path, envelope)
    add_fork(root)
    return root


POINT_DONE = (none_comment("s9"), ledger_comment("s15:ideate"))


def test_a_fork_task_is_filed_from_its_draft_with_the_fork_marker(tmp_path):
    root = with_fork(tmp_path)
    actions = tick(root, snapshot_0007(root, comments=POINT_DONE))
    assert "- s15: forks f1 on main; they run after the plan's own steps" in ledger_text(actions)
    (issue,) = filed(actions)
    title, body = markers.draft_body(FORK_DRAFT)
    assert issue["title"] == title and issue["labels"] == ["campaign", "explore"]
    assert issue["body"] == (
        f"{body}\n\n{markers.step_marker('0007', 's24')}\n{markers.fork_marker('0007', 'f1')}\n"
    )
    assert not {e for e in events_of(actions) if e.startswith("adopt:")}


def fork_done(root: Path, f_cluster: float, lead: float = 0.05, run_id: int = 555):
    """s24 merged and s25 run and recorded with these numbers."""
    write_record(
        root,
        "0007_gold_first_stage_f1",
        run_id,
        {
            "first_stage": {"f_cluster": f_cluster},
            "placebo": {"lead_ratio": lead},
            "estimates": {"finite": True},
        },
    )
    c = campaign_0007(root)
    s24 = task_issue_of(root, c, "s24", 150, merged_pr(250, "agent/issue-150"))
    run = run_of(c, "s25", run_id)
    rec = merged_pr(350, f"explore/0007_gold_first_stage_f1-{run_id}")
    return (s24,), (run,), {run_id: rec}


def test_the_yes_no_fork_survives_and_adopts_s16_to_s23(tmp_path):
    """The brief's section 10: F 12.28 and lead ratio 0.05 (s15's own side result)."""
    root = with_fork(tmp_path)
    issues, runs, recs = fork_done(root, 12.28)
    actions = tick(
        root, snapshot_0007(root, comments=POINT_DONE, issues=issues, runs=runs, record_prs=recs)
    )
    text = ledger_text(actions)
    assert "Verdict: **survived (fork)**. Fork f1 (transform: exposure: yes/no" in text
    assert "is one of 1 tried at s15; a fork result is never a finding." in text
    adopt = [e for e in events_of(actions) if e.startswith("adopt:")]
    assert adopt == ["adopt:f1:s15:" + ",".join(f"s{n}" for n in range(16, 24))]
    assert "- f1 adopts s16 to s23: the plan's step s15 was killed and fork f1" in text
    # s16, the first adopted task, is filed: its approved draft plus the fork's delta
    (issue,) = filed(actions)
    draft = (root / C07 / "drafts" / "s16.md").read_text(encoding="utf-8")
    title, body = markers.draft_body(draft)
    assert issue["title"] == title
    assert issue["body"] == (
        f"{body}\n\n## Fork delta (f1)\n\n{DELTA}\n\n{markers.step_marker('0007', 's16')}\n"
        f"{markers.adopted_marker('0007', 's16', 'f1')}\n"
    )
    # and the gate accepts exactly that issue for s16's pull request
    pr = task_pr_of(issue, files=("src/terrain/bigquery.py",))
    assert evaluate(pr, gate_ctx(root)).state == "success"
    changed = task_pr_of(
        dict(issue, body=issue["body"].replace(DELTA, "Something else.")),
        files=("src/terrain/bigquery.py",),
    )
    assert "no longer matches its approved draft" in evaluate(changed, gate_ctx(root)).description


def task_pr_of(issue: dict, files=("explore/0007_gold_first_stage_f1.py",), **over) -> PullRequest:
    base = dict(
        number=60,
        author=BOT,
        head_ref="agent/issue-61",
        head_sha=SHA,
        state="open",
        merged=False,
        mergeable=True,
        files=tuple(files),
        ci_test="success",
        gate_status="success",
        reviews=(Review("approve", SHA[:12], dict(REFEREE_OK), NOW),),
        issue_body=issue["body"],
        issue_title=issue["title"],
    )
    base.update(over)
    return PullRequest(**base)


def test_after_adoption_the_adopted_steps_run_on_the_plans_budget(tmp_path):
    root = with_fork(tmp_path)
    issues, runs, recs = fork_done(root, 12.28)
    adopt = "adopt:f1:s15:" + ",".join(f"s{n}" for n in range(16, 24))
    comments = (*POINT_DONE, ledger_comment(adopt))
    from terrain.campaigns.tick import view

    c = campaign_0007(root)
    v = view(
        c,
        snapshot_0007(root, comments=comments, issues=issues, runs=runs, record_prs=recs),
        gate_ctx(root),
    )
    assert v.adoption[0] == "f1" and v.states["s16"].status == "unstarted"
    assert v.states["s17"].status == "waiting"  # waits for s16, no longer skipped
    assert v.used["max_tasks"] == 7 and v.fork_used["max_tasks"] == 1  # F12
    assert v.fork_used["max_model_jobs"] == 1  # the ideation job (no plan or review here)


def test_the_yes_no_fork_killed_at_9_finishes_the_campaign(tmp_path):
    root = with_fork(tmp_path)
    issues, runs, recs = fork_done(root, 9.0)
    actions = tick(
        root, snapshot_0007(root, comments=POINT_DONE, issues=issues, runs=runs, record_prs=recs)
    )
    assert "Verdict: **killed (fork)**" in ledger_text(actions)
    assert not {e for e in events_of(actions) if e.startswith("adopt:")}
    (closeout,) = filed(actions)
    body = closeout["body"]
    assert markers.parse_closeout(body) == "0007"
    assert "## Forks (written by the tick; copy as is)" in body
    assert "| f1 | s15 | transform | exposure: yes/no (geo_exposed) instead of density |" in body
    assert "| killed (fork) | k1 (" in body and "observed 9.0" in body
    assert "- s15: 0 proposed, 0 refused by the envelope check, 1 ran, 0 survived" not in body
    assert "1 ran, 0 survived" in body
    assert "weaker evidence than one test set in advance" in body
    assert "`## Forks`" in body and "recommend `dead` only if the plan's path and" in body
    assert "## Variants tried" in body
    assert "| s25 (f1) | explore_run | done | killed (fork) |" in body


def second_fork(root: Path) -> None:
    text = numbered_fork(2, 2).replace("s26", "s26").replace("s27", "s27")
    add_fork(root, "f2", text, {"s26": FORK_DRAFT})


def test_every_declared_fork_runs_before_adoption(tmp_path):
    """F3: f1 survived, f2 has not run yet: no adoption; f2's task is filed."""
    root = with_fork(tmp_path)
    second_fork(root)
    issues, runs, recs = fork_done(root, 12.28)
    actions = tick(
        root, snapshot_0007(root, comments=POINT_DONE, issues=issues, runs=runs, record_prs=recs)
    )
    assert not {e for e in events_of(actions) if e.startswith("adopt:")}
    (issue,) = filed(actions)
    assert markers.parse_step(issue["body"]) == ("0007", "s26")
    assert markers.parse_fork(issue["body"]) == ("0007", "f2")


def test_the_first_survivor_in_declared_order_adopts(tmp_path):
    """f1 killed, f2 survived: f2 adopts."""
    root = with_fork(tmp_path)
    second_fork(root)
    issues, runs, recs = fork_done(root, 9.0)
    write_record(
        root,
        "0007_gold_first_stage_f2",
        556,
        {
            "first_stage": {"f_cluster": 15.0},
            "placebo": {"lead_ratio": 0.1},
            "estimates": {"finite": True},
        },
    )
    c = campaign_0007(root)
    s26 = task_issue_of(root, c, "s26", 151, merged_pr(251, "agent/issue-151"))
    runs += (run_of(c, "s27", 556),)
    recs[556] = merged_pr(351, "explore/0007_gold_first_stage_f2-556")
    actions = tick(
        root,
        snapshot_0007(root, comments=POINT_DONE, issues=(*issues, s26), runs=runs, record_prs=recs),
    )
    adopt = [e for e in events_of(actions) if e.startswith("adopt:")]
    assert adopt == ["adopt:f2:s15:" + ",".join(f"s{n}" for n in range(16, 24))]


def test_a_forks_run_is_never_a_fork_point(tmp_path):
    """F11: s25's verdict opens nothing."""
    root = with_fork(tmp_path)
    issues, runs, recs = fork_done(root, 12.28)
    actions = tick(
        root, snapshot_0007(root, comments=POINT_DONE, issues=issues, runs=runs, record_prs=recs)
    )
    assert not dispatches(actions, "campaign-ideate.yml")


def test_fork_steps_wait_while_a_plan_step_can_start(tmp_path):
    """F13: after s9 survived, a fork at s9 waits while the plan's s10 can start."""
    root = replay_repo(tmp_path)
    over = mutate_step(1, inherits="s9", script="0007_gold_feasibility_f1")
    over["steps"][0]["allowed_paths"] = ["explore/0007_gold_feasibility_f1.py"]
    over["steps"][0]["after"] = ["s9"]
    add_fork(
        root,
        text=fork_text(
            parent_step="s9",
            parent_verdict="survived",
            evidence=["research/explore-runs/0007/43181711849.md"],
            adopts_downstream=False,
            delta="",
            **over,
        ),
    )
    assert validate(root) == []
    snap9 = snapshot_0007(
        root,
        done=tuple(f"s{n}" for n in range(1, 10)),
        comments=(ledger_comment("s9:ideate"),),
    )
    actions = tick(root, snap9)
    (issue,) = filed(actions)
    assert markers.parse_step(issue["body"]) == ("0007", "s10")  # the plan first


def test_the_forks_budget_is_their_own(tmp_path):
    """F12: with no fork task left in the envelope's budget, the fork waits; the plan's
    budget is untouched, and the campaign finishes saying the step did not run."""
    root = with_fork(tmp_path, ENVELOPE.replace("max_tasks: 10", "max_tasks: 0"))
    assert any("forks.budget.max_tasks" in p for p in validate(root))  # refused when declared
    root = with_fork(tmp_path / "b", ENVELOPE.replace("max_model_jobs: 45", "max_model_jobs: 1"))
    actions = tick(root, snapshot_0007(root, comments=POINT_DONE))
    # the one model job went to the ideation, so the fork's task cannot start
    assert not filed(actions) or markers.parse_closeout(filed(actions)[0]["body"])
    closeout = filed(actions)[0]["body"]
    assert "Step s24 (task) did not finish" in closeout


# -- the gate ---------------------------------------------------------------------------------


def test_the_gate_refuses_a_pull_request_that_edits_a_merged_fork_file(tmp_path):
    """F2: fork files are append-only, whoever opens the pull request, but the owner."""
    root = with_fork(tmp_path)
    path = f"{C07}/forks/f1.md"
    for author in (BOT, "someone-else"):
        pr = merged_pr(
            70,
            "agent/issue-71",
            state="open",
            merged=False,
            author=author,
            files=(path,),
            changes=((path, "modified"),),
        )
        result = evaluate(pr, gate_ctx(root))
        assert result.state == "failure" and "append-only" in result.description
    pr = merged_pr(
        70,
        "fix/forks",
        state="open",
        merged=False,
        author=OWNER,
        files=(path,),
        changes=((path, "removed"),),
    )
    assert evaluate(pr, gate_ctx(root)).state == "success"
    renamed = merged_pr(
        70,
        "x",
        state="open",
        merged=False,
        author="someone-else",
        files=("elsewhere.md",),
        changes=(("elsewhere.md", "renamed"), (path, "renamed-from")),
    )
    assert evaluate(renamed, gate_ctx(root)).state == "failure"


@pytest.mark.parametrize(
    "over, words",
    [
        ({}, "every check passes"),
        ({"ci_test": None}, "waiting for CI"),
        ({"run_conclusion": None}, "waiting for the ideation run"),
        ({"run_title": "Ideate (dry run) campaign 0007/s15"}, "does not come from this campaign"),
        ({"run_workflow": ".github/workflows/explore-run.yml"}, "does not come from"),
        (
            {"head_ref": "forks/0007-s14-777", "run_title": "Ideate campaign 0007/s14"},
            "s14 is not a fork point",
        ),
        ({"changes": ((f"{C07}/forks/f1.md", "modified"),)}, "append-only"),
        ({"author": "someone"}, "Not an agent pull request"),
    ],
)
def test_the_gate_for_a_fork_plan(tmp_path, over, words):
    root = replay_repo(tmp_path)
    pr = fork_plan_pr(root, FORK_FILES, **over)
    assert words in evaluate(pr, gate_ctx(root)).description


def test_the_gate_refuses_a_fork_plan_the_checks_refuse(tmp_path):
    root = replay_repo(tmp_path)
    bad = dict(FORK_FILES)
    bad[f"{C07}/forks/f1.md"] = fork_text(**mutate_step(1, value=9))
    result = evaluate(fork_plan_pr(root, bad), gate_ctx(root))
    assert result.state == "failure" and "the fork checks refuse it" in result.description
    outside = {**FORK_FILES, "explore/0007_x_f1.py": "x"}
    result = evaluate(fork_plan_pr(root, outside), gate_ctx(root))
    assert result.state == "failure" and "files outside" in result.description
    # a fork already on main cannot be added again
    add_fork(root)
    result = evaluate(fork_plan_pr(root, FORK_FILES), gate_ctx(root))
    assert result.state == "failure"


def test_a_fork_task_needs_r8_and_its_own_marker(tmp_path):
    root = with_fork(tmp_path)
    c = campaign_0007(root)
    issue = task_issue_of(root, c, "s24", 61)
    pr = task_pr_of({"title": issue.title, "body": issue.body})
    assert evaluate(pr, gate_ctx(root)).state == "success"
    for status in ("Not applicable", "Problem", None):
        referee = dict(REFEREE_OK)
        if status is None:
            referee.pop("R8")
        else:
            referee["R8"] = status
        rv = (Review("approve", SHA[:12], referee, NOW),)
        result = evaluate(replace_pr(pr, reviews=rv), gate_ctx(root))
        assert result.state == "failure" and "R8 (fork discipline)" in result.description
    no_marker = replace_pr(
        pr,
        issue_body=markers.strip_marker(issue.body) + "\n\n" + markers.step_marker("0007", "s24"),
    )
    assert "does not carry the marker of fork f1" in evaluate(no_marker, gate_ctx(root)).description


def replace_pr(pr: PullRequest, **over) -> PullRequest:
    from dataclasses import replace

    return replace(pr, **over)


def test_r8_is_not_needed_outside_forks_and_cannot_be_waived(tmp_path):
    root = with_fork(tmp_path, ENVELOPE)
    text = (root / C07 / "campaign.md").read_text(encoding="utf-8")
    (root / C07 / "campaign.md").write_text(
        text.replace("referee_not_applicable_ok: [R5]", "referee_not_applicable_ok: [R5, R8]"),
        encoding="utf-8",
    )
    assert any("unknown check 'R8'" in p for p in validate(root))


# -- the act job's fixed list ------------------------------------------------------------------


def run_act_script(tmp_path, monkeypatch, actions):
    import io
    import urllib.request

    text = (REPO / ".github" / "workflows" / "campaign-tick.yml").read_text(encoding="utf-8")
    start = text.index("python3 -I - <<'PY'\n") + len("python3 -I - <<'PY'\n")
    script = textwrap.dedent(text[start : text.index("\n          PY\n", start)])
    calls = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout=0):
        body = json.loads(req.data) if req.data else None
        calls.append(
            (req.get_method(), req.full_url.removeprefix("https://api.github.com/repos/o/r"), body)
        )
        return Answer(b"")

    file = tmp_path / "actions.json"
    file.write_text(json.dumps(actions), encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    for k, v in {"REPO": "o/r", "APP_TOKEN": "t", "APP_BOT": BOT, "ACTIONS": str(file)}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit) as done:
        exec(compile(script, "campaign-tick act", "exec"), {"__name__": "__main__"})
    return done.value.code, calls


@pytest.mark.parametrize(
    "inputs, ok",
    [
        ({"campaign": "0007", "step": "s15"}, True),
        ({"campaign": "7", "step": "s15"}, False),
        ({"campaign": "0007", "step": "s15; echo"}, False),
        ({"campaign": "0007", "step": "s15", "dry_run": "true"}, False),
        ({"campaign": "0007"}, True),  # a missing input is GitHub's to refuse, not a new one
    ],
)
def test_the_act_job_starts_ideation_only_with_valid_inputs(tmp_path, monkeypatch, inputs, ok):
    action = {"type": "dispatch", "workflow": "campaign-ideate.yml", "inputs": inputs}
    code, calls = run_act_script(tmp_path, monkeypatch, [action])
    if ok:
        assert code == 0
        assert calls == [
            (
                "POST",
                "/actions/workflows/campaign-ideate.yml/dispatches",
                {"ref": "main", "inputs": inputs},
            )
        ]
    else:
        assert code == 1 and calls == []


# -- forks-from-json: code writes every file -----------------------------------------------------


def answer(*props, decision="fork", suggestions=()) -> dict:
    return {
        "decision": decision,
        "reason": "The same run's yes/no measure had F 12.28.",
        "forks": list(props),
        "suggestions": list(suggestions),
    }


YES_NO = {
    "type": "transform",
    "title": "yes/no gold measure",
    "dimension": "exposure: yes/no (geo_exposed) instead of density",
    "rationale": "robust.binary.f_cluster is 12.28 in research/explore-runs/0007/43438404852.json.",
    "pass_fail": "A pass: the politics phase can use it. A fail: the first stage is weak.",
    "evidence": ["research/explore-runs/0007/43438404852.json"],
    "datasets": [],
    "steps": [
        {
            "kind": "task",
            "type": "explore",
            "title": "first stage with yes/no gold",
            "draft": "## Goal\n\nRe-run s15 with geo_exposed in "
            "explore/0007_gold_first_stage_fK.py.\n\n"
            "## Done when\n\n1. `uv run pytest` passes.\n",
            "allowed_paths": [
                "explore/0007_gold_first_stage_fK.py",
                "tests/test_explore_gold_first_stage_fK.py",
            ],
            "after": [],
        },
        {"kind": "explore_run", "script": "0007_gold_first_stage_fK", "after": [0]},
    ],
    "adopts_downstream": True,
    "delta": "Use geo_exposed (yes/no) wherever the draft says geo_gold_per_km2.",
    "cost": {"tasks": 1, "runs": 1},
}


def test_forks_from_json_writes_files_that_pass_every_check(tmp_path):
    root = replay_repo(tmp_path)
    c = campaign_0007(root)
    bad_sample = dict(
        YES_NO,
        type="sample",
        title="only where garimpo grew",
        sample_on="garimpo_share",
        dimension="sample: where garimpo grew",
    )
    b = ideation.build(
        root,
        c,
        "s15",
        answer(
            YES_NO,
            bad_sample,
            suggestions=[
                {
                    "title": "close races near gold",
                    "why_not_run": "needs new data beyond the envelope",
                }
            ],
        ),
    )
    assert [f for f, _, _ in b.written] == ["f1"]
    assert b.proposed == 2 and len(b.refused) == 1
    assert "never an outcome (F6)" in b.refused[0][1]
    assert sorted(b.files) == [f"{C07}/forks/f1.md", f"{C07}/forks/f1/drafts/s24.md"]
    fm = yaml.safe_load(b.files[f"{C07}/forks/f1.md"].split("---\n")[1])
    assert fm["steps"][1] == {
        "id": "s25",
        "kind": "explore_run",
        "script": "0007_gold_first_stage_f1",
        "inherits": "s15",
        "after": ["s24"],
    }
    assert fm["evidence"][0] == f"{RECORD}.md" and fm["adopts_downstream"] is True
    draft = b.files[f"{C07}/forks/f1/drafts/s24.md"]
    assert draft.startswith(
        "# Task: first stage with yes/no gold (explore, fork f1 of campaign 0007)"
    )
    assert "explore/0007_gold_first_stage_f1.py" in draft and "_fK" not in draft
    assert "## What differs from the parent" in draft
    # written to disk, the result validates
    for path, text in b.files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    assert validate(root) == []
    text = ideation.comment(b, c, "s15", "https://example.test/run", dry_run=False)
    assert markers.parse_ideation(text) == (
        "0007",
        "s15",
        {"proposed": 2, "refused": 1, "forks": ["f1"]},
    )
    assert "### Refused by the envelope check\n\n- only where garimpo grew:" in text
    assert "- close races near gold: needs new data beyond the envelope" in text


def test_forks_from_json_respects_the_room_and_says_none(tmp_path):
    root = replay_repo(tmp_path)
    c = campaign_0007(root)
    props = [dict(YES_NO, title=f"variant {k}") for k in range(4)]
    b = ideation.build(root, c, "s15", answer(*props))
    assert [f for f, _, _ in b.written] == ["f1", "f2", "f3"]  # per_point 3
    assert b.refused[-1] == ("variant 3", "the envelope allows no more forks at this point")
    none = ideation.build(root, c, "s15", answer(decision="none"))
    assert none.files == {} and none.decision == "none"
    text = ideation.comment(none, c, "s15", "u", dry_run=False)
    assert markers.parse_ideation(text)[2]["forks"] == []
    garbage = ideation.build(root, c, "s15", "not json")
    assert garbage.decision == "none" and "no usable answer" in garbage.reason


def test_forks_from_json_command_and_its_dry_run(tmp_path, monkeypatch):
    import importlib.util

    root = replay_repo(tmp_path / "repo", envelope="", status="done")
    spec = importlib.util.spec_from_file_location("cli", REPO / "scripts" / "campaign.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "REPO", root)
    (tmp_path / "answer.json").write_text(json.dumps(answer(YES_NO)), encoding="utf-8")
    args = [
        "forks-from-json",
        "--campaign",
        "0007",
        "--step",
        "s15",
        "--run-id",
        "9",
        "--in",
        str(tmp_path / "answer.json"),
        "--out",
        str(tmp_path / "out"),
    ]
    # a done campaign without an envelope: only a dry run, with the default envelope
    assert cli.main(args) == 1
    assert cli.main([*args, "--dry-run"]) == 0
    result = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert result["forks"] == ["f1"] and result["dry_run"] is True
    assert not (root / C07 / "forks").exists()  # a dry run writes nothing
    comment = (tmp_path / "out" / "comment.md").read_text(encoding="utf-8")
    assert "Dry run: nothing was written" in comment and markers.parse_ideation(comment) is None
    # an active campaign with an envelope: the files are written into the checkout
    root2 = replay_repo(tmp_path / "repo2")
    monkeypatch.setattr(cli, "REPO", root2)
    assert cli.main(args) == 0
    assert (root2 / C07 / "forks" / "f1.md").is_file() and validate(root2) == []
    # a second answer never overwrites f1: code gives the next fork its own id
    assert cli.main(args) == 0
    assert (root2 / C07 / "forks" / "f2.md").is_file() and validate(root2) == []


def test_the_workflow_carries_the_schema_and_reuses_the_review_scan():
    import re

    text = (REPO / IDEATE_PATH).read_text(encoding="utf-8")
    m = re.search(r"--json-schema '(\{.*\})'", text)
    assert m and json.loads(m.group(1)) == ideation.SCHEMA
    review = (REPO / ".github/workflows/agent-review.yml").read_text(encoding="utf-8")
    assert re.search(r'TOKEN_PREFIX = re\.compile\(r"([^"]+)"\)', review)
    assert "python3 -I scripts/role.py ideation" in text
    assert "permissions:\n      contents: read\n    steps:" in text  # the model job only reads
    for job in yaml.safe_load(text)["jobs"].values():
        assert job["permissions"] == {"contents": "read"}


# -- the review: R8 for a fork's task ------------------------------------------------------------


def run_compose(tmp_path, monkeypatch, referee, task_type="explore", fork="f1"):
    text = (REPO / ".github/workflows/agent-review.yml").read_text(encoding="utf-8")
    step = text.index("- name: Check Claude's result and build the comment\n")
    start = text.index("python3 -I - <<'EOF'\n", step) + len("python3 -I - <<'EOF'\n")
    script = textwrap.dedent(text[start : text.index("\n          EOF\n", start)])
    work = tmp_path / "agent-review"
    (work / "data").mkdir(parents=True)
    (work / "data" / "done-when.json").write_text(
        json.dumps([{"id": "D1", "item": "it works"}]), encoding="utf-8"
    )
    (work / "scope.json").write_text("[]", encoding="utf-8")
    result = {
        "verdict": "approve",
        "must_fix": [],
        "nice_to_have": [],
        "checked": [{"id": "D1", "status": "verified", "how": "read it"}],
        "referee": [{"id": r, "status": s, "note": "n"} for r, s in referee.items()],
    }
    out = tmp_path / "out.txt"
    env = {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "STRUCTURED": json.dumps(result),
        "TASK_TYPE": task_type,
        "FORK": fork,
        "HEAD_SHA": SHA,
        "PLAN_URL": "p",
        "RUN_URL": "r",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "JOB_TOKEN": "",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    exec(compile(script, "agent-review compose", "exec"), {"__name__": "__main__"})
    got = out.read_text(encoding="utf-8")
    return got.split("verdict=", 1)[1].split("\n", 1)[0], got


def test_the_review_requires_r8_for_a_fork_task(tmp_path, monkeypatch):
    from terrain.campaigns.facts import parse_review

    ok = {f"R{i}": "ok" for i in range(1, 9)}
    verdict, out = run_compose(tmp_path / "a", monkeypatch, ok)
    assert verdict == "approve" and "| R8 | Fork discipline | OK |" in out
    review = parse_review(out.split("<<", 1)[1], NOW)
    assert review.referee["R8"] == "OK"
    missing = {k: v for k, v in ok.items() if k != "R8"}
    verdict, out = run_compose(tmp_path / "b", monkeypatch, missing)
    assert verdict == "changes" and "no entry for R8" in out
    verdict, out = run_compose(tmp_path / "c", monkeypatch, dict(ok, R8="not_applicable"))
    assert verdict == "changes" and "never Not applicable" in out
    # a fork's build task: R8 only; any other build task: no referee rows
    verdict, out = run_compose(tmp_path / "d", monkeypatch, {"R8": "ok"}, "build")
    assert verdict == "approve" and "### Referee (fork task)" in out
    verdict, out = run_compose(tmp_path / "e", monkeypatch, {}, "build", fork="")
    assert verdict == "approve" and "### Referee" not in out


def test_the_reviewer_and_ideation_roles_say_what_they_must():
    reviewer = (REPO / "harness/roles/reviewer.md").read_text(encoding="utf-8")
    assert (
        "R8 Fork discipline (fork tasks only)" in reviewer and "never `not_applicable`" in reviewer
    )
    role = (REPO / "harness/roles/ideation.md").read_text(encoding="utf-8")
    for words in (
        "Prefer the cheapest fork that could change a decision",
        "Never choose a sample by outcomes",
        "Never propose a duplicate",
        "`decision: none`",
        "`suggestions`, never under `forks`",
        "what a pass and what a fail would each mean",
    ):
        assert words in role, words


# -- the status page ------------------------------------------------------------------------------


def test_the_status_page_shows_forks_used_and_each_forks_state(tmp_path):
    from terrain.campaigns.tick import render_status_page

    root = with_fork(tmp_path)
    issues, runs, recs = fork_done(root, 12.28)
    s = snapshot_0007(root, comments=POINT_DONE, issues=issues, runs=runs, record_prs=recs)
    page = render_status_page(active_campaigns(root), s, gate_ctx(root), root)
    assert "; forks: 1 of 5 |" in page and "forks: f1 survived (fork)" in page


def test_every_real_campaign_decides_without_any_fork_action(tmp_path):
    """Section 8: the existing campaign folders, replayed through validate and decide."""
    assert validate(REPO) == []
    for c in load_campaigns(REPO):
        track = Issue(
            1,
            "t",
            f"x\n{markers.tracking_marker(c.id)}",
            "open",
            ("campaign",),
            BOT,
            T0,
            (Comment(BOT, "- x\n\n" + markers.ledger_marker(c.id, ["started"]), T0),),
        )
        s = Snapshot(now=NOW, enabled=True, app_bot=BOT, issues=[track])
        from dataclasses import replace

        actions = decide([replace(c, status="active")], s, gate_ctx(REPO), REPO)
        assert not dispatches(actions, "campaign-ideate.yml"), c.id
        assert not {e for e in events_of(actions) if ":ideate" in e or e.startswith("adopt:")}
