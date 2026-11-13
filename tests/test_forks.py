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
