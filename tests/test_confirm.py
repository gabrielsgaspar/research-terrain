"""terrain.confirm and the confirm-run / unblind workflows, on synthetic data only.

Nothing here reads confirm/, sealed/ or GCS: the split, pairs and outcomes are
made up in a MemoryStore, and git checks run in a temporary repository.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import random
import subprocess
from pathlib import Path

import polars as pl
import pytest
import yaml

from terrain import confirm
from terrain.confirm import ConfirmError
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
COMMIT = "a" * 40
PAIRS_PATH = "data/derived/synthetic_pairs/pairs.csv"
OUTCOMES_PATH = "sealed/outcomes/synthetic/outcomes.csv"
ENV = {
    confirm.SHUFFLED: {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/confirm-run.yml@refs/heads/main",
    },
    confirm.REAL: {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/unblind.yml@refs/heads/main",
    },
}


def spec_bytes(**overrides: object) -> bytes:
    raw: dict[str, object] = {
        "id": "0001-synthetic",
        "analysis": "test_synthetic",
        "pap_commit": COMMIT,
        "params": {"effect": "synthetic"},
        # The fields of confirm/specs/TEMPLATE.yaml:
        "idea": "research/ideas/0001-synthetic.md",
        "registered": dt.date(2026, 12, 1),
        "hypothesis": "Synthetic specification for tests.",
        "predicted_sign": "two_sided",
        "sample": "confirm",
        "outcome": {"dataset": "synthetic", "variable": "y", "window": "term_years"},
        "treatment": {"design": "close_pair_swap", "bandwidth_rule": "all pairs"},
        "exposure": "none",
        "fixed_effects": ["municipality_by_year"],
        "inference": {"method": "randomisation", "draws": 999, "cluster": "municipality"},
        "seed_policy": "fixed in the workflow, logged in the ledger",
    }
    raw.update(overrides)
    return yaml.safe_dump({k: v for k, v in raw.items() if v is not None}).encode("utf-8")


def make_world(effect: float = 1.0, municipalities: int = 40, pairs_each: int = 10):
    """A sealed split, close pairs for every municipality, and outcomes where
    the elected side's outcome is higher by `effect`."""
    rng = random.Random(7)
    codes = [str(1_000_001 + i) for i in range(municipalities)]
    half = {c: ("confirm" if i % 2 else "explore") for i, c in enumerate(codes)}
    split = ("code_ibge,half\n" + "".join(f"{c},{half[c]}\n" for c in codes)).encode()
    pairs, outcomes = [], []
    for c in codes:
        for j in range(pairs_each):
            e, o = f"{c}{j:02d}1", f"{c}{j:02d}2"
            pairs.append(
                {
                    "pair_id": f"{c}-{j}",
                    "cd_ibge": c,
                    "elected_sq": e,
                    "other_sq": o,
                    "margin": rng.uniform(0, 0.0025),
                }
            )
            outcomes.append({"sq": e, "y": effect + rng.gauss(0, 0.5)})
            outcomes.append({"sq": o, "y": rng.gauss(0, 0.5)})
    store = MemoryStore()
    store.create(confirm.SPLIT_PATH, split)
    store.create(PAIRS_PATH, pl.DataFrame(pairs).write_csv().encode())
    store.create(OUTCOMES_PATH, pl.DataFrame(outcomes).write_csv().encode())
    confirm_codes = frozenset(c for c in codes if half[c] == "confirm")
    return store, hashlib.sha256(split).hexdigest(), confirm_codes


def read_csv(data: bytes) -> pl.DataFrame:
    return pl.read_csv(
        io.BytesIO(data),
        schema_overrides={
            "cd_ibge": pl.Utf8,
            "elected_sq": pl.Utf8,
            "other_sq": pl.Utf8,
            "sq": pl.Utf8,
        },
    )


def synthetic_analysis(ctx: confirm.RunContext) -> dict:
    """Elected-minus-other outcome, averaged over pairs, with a sign-flip RI p."""
    pairs = ctx.restrict(read_csv(ctx.read(PAIRS_PATH)))
    pairs = ctx.assign(pairs, key=("pair_id",))
    y = read_csv(ctx.read(OUTCOMES_PATH))
    d = (
        pairs.join(y.rename({"sq": "elected_sq", "y": "y_e"}), on="elected_sq")
        .join(y.rename({"sq": "other_sq", "y": "y_o"}), on="other_sq")
        .select((pl.col("y_e") - pl.col("y_o")).alias("d"))["d"]
        .to_list()
    )
    est = sum(d) / len(d)
    rng = random.Random(20261106)
    draws = [sum(x if rng.random() < 0.5 else -x for x in d) / len(d) for _ in range(999)]
    p = (1 + sum(abs(b) >= abs(est) for b in draws)) / 1000
    return {
        "estimates": [{"name": "contrast", "estimate": est, "p_value": p, "confirmatory": True}],
        "counts": {"pairs": len(d)},
    }


@pytest.fixture
def registered():
    def add(name, fn):
        confirm.register(name)(fn)
        added.append(name)

    added: list[str] = []
    add("test_synthetic", synthetic_analysis)
    yield add
    for name in added:
        confirm.ANALYSES.pop(name, None)


# --- the specification ---------------------------------------------------


def test_load_spec_reads_the_documented_fields_and_hashes_the_bytes():
    data = spec_bytes()
    spec = confirm.load_spec(data)
    assert (spec.id, spec.analysis, spec.pap_commit) == ("0001-synthetic", "test_synthetic", COMMIT)
    assert spec.params == {"effect": "synthetic"}
    assert spec.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"window": 0.0025}, "does not use"),
        ({"id": None}, "lacks"),
        ({"id": "direct"}, "id must"),
        ({"analysis": "Not A Name"}, "analysis must"),
        ({"pap_commit": "abc123"}, "40-character"),
        ({"params": [1, 2]}, "params"),
        ({"sample": "explore"}, "confirmation half only"),
        ({"registered": "YYYY-MM-DD"}, "registered must be a date"),
        ({"predicted_sign": "up"}, "predicted_sign"),
        ({"idea": "research/ideas/0002-other.md"}, "idea must"),
        ({"hypothesis": ""}, "hypothesis must be filled in"),
        ({"treatment": {"design": "permute", "bandwidth_rule": "x"}}, "close_pair_swap"),
        ({"inference": {"method": "randomisation", "draws": 9}}, "inference must have"),
        ({"inference": {"method": "bootstrap", "draws": 9, "cluster": "m"}}, "randomisation"),
        ({"outcome": {"dataset": "d", "variable": "v", "window": "all_years"}}, "outcome.window"),
    ],
)
def test_load_spec_refuses_what_it_cannot_use(overrides, message):
    with pytest.raises(ConfirmError, match=message):
        confirm.load_spec(spec_bytes(**overrides))


def test_shuffle_seed_is_fixed_by_the_specification():
    a, b = confirm.load_spec(spec_bytes()), confirm.load_spec(spec_bytes(hypothesis="Changed."))
    assert confirm.shuffle_seed(a.sha256) == confirm.shuffle_seed(a.sha256)
    assert confirm.shuffle_seed(a.sha256) != confirm.shuffle_seed(b.sha256)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def test_check_pap_commit_needs_a_plan_under_confirm_pap_on_the_history(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "confirm" / "pap").mkdir(parents=True)
    (tmp_path / "confirm" / "pap" / "README.md").write_text("outline\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "scaffold")
    readme_only = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "confirm" / "pap" / "0001.md").write_text("plan\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "plan")
    plan = git(tmp_path, "rev-parse", "HEAD")

    confirm.check_pap_commit(tmp_path, plan)
    git(tmp_path, "switch", "-q", "-c", "pap", readme_only)
    (tmp_path / "confirm" / "pap" / "0002.md").write_text("plan 2\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "plan 2")
    git(tmp_path, "switch", "-q", "main")
    git(tmp_path, "merge", "-q", "--no-ff", "-m", "merge plan 2", "pap")
    confirm.check_pap_commit(tmp_path, git(tmp_path, "rev-parse", "HEAD"))
    with pytest.raises(ConfirmError, match="no plan"):
        confirm.check_pap_commit(tmp_path, readme_only)
    git(tmp_path, "switch", "-q", "-c", "side", readme_only)
    (tmp_path / "other.md").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "side")
    with pytest.raises(ConfirmError, match="not on the checked-out history"):
        confirm.check_pap_commit(tmp_path, plan)


# --- the halves and the treatment -------------------------------------------


def test_confirmation_municipalities_needs_the_committed_hash():
    store, split_hash, confirm_codes = make_world()
    assert confirm.confirmation_municipalities(store, split_hash + "\n") == confirm_codes
    with pytest.raises(ConfirmError, match="does not match"):
        confirm.confirmation_municipalities(store, "0" * 64)


def test_flips_depend_on_the_pair_not_on_row_order():
    keys = [(f"p{i}",) for i in range(2000)]
    flips = confirm.flips_for(keys, seed=5)
    assert flips == list(reversed(confirm.flips_for(list(reversed(keys)), seed=5)))
    assert 900 < sum(flips) < 1100
    assert flips != confirm.flips_for(keys, seed=6)


def test_flip_sides_swaps_both_sides_and_negates_the_margin():
    pairs = pl.DataFrame(
        {"elected_sq": ["e1", "e2"], "other_sq": ["o1", "o2"], "margin": [0.1, 0.2]}
    )
    out = confirm.flip_sides(pairs, [True, False], [("elected_sq", "other_sq")], ["margin"])
    assert out.rows() == [("o1", "e1", -0.1), ("e2", "o2", 0.2)]


# --- the run ---------------------------------------------------------------


def test_shuffled_run_finds_nothing_and_the_real_run_finds_the_effect(registered):
    store, split_hash, _ = make_world(effect=1.0)
    spec = confirm.load_spec(spec_bytes())
    shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    real = confirm.run(spec, store, confirm.REAL, split_hash, ENV[confirm.REAL])

    s, r = shuffled["results"]["estimates"][0], real["results"]["estimates"][0]
    assert abs(r["estimate"] - 1.0) < 0.15 and r["p_value"] <= 0.002
    assert abs(s["estimate"]) < 0.2 and s["p_value"] >= 0.05
    assert shuffled["shuffled_check"] == {"alpha": 0.05, "passed": True, "failing": []}
    assert shuffled["pairs"] == real["pairs"] == 200
    assert 70 < shuffled["pairs_flipped"] < 130
    assert "shuffle_seed" not in real and "shuffled_check" not in real


def test_shuffled_run_gives_the_same_numbers_every_time(registered):
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes())
    runs = [
        confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


def test_a_shuffled_run_that_finds_something_fails_its_check(registered):
    def leaky(ctx):  # takes the treatment, then ignores the shuffle: a pipeline bug
        ctx.assign(ctx.restrict(read_csv(ctx.read(PAIRS_PATH))), key=("pair_id",))
        return {
            "estimates": [
                {"name": "contrast", "estimate": 1.0, "p_value": 0.001, "confirmatory": True}
            ]
        }

    registered("test_leaky", leaky)
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes(analysis="test_leaky"))
    out = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    assert out["shuffled_check"] == {"alpha": 0.05, "passed": False, "failing": ["contrast"]}


def test_the_analysis_sees_only_the_confirmation_half(registered):
    seen = {}

    def look(ctx):
        pairs = ctx.restrict(read_csv(ctx.read(PAIRS_PATH)))
        seen["codes"] = set(pairs["cd_ibge"])
        ctx.assign(pairs, key=("pair_id",))
        return {"estimates": [{"name": "x", "estimate": 0.0, "p_value": 1.0, "confirmatory": True}]}

    registered("test_look", look)
    store, split_hash, confirm_codes = make_world()
    confirm.run(
        confirm.load_spec(spec_bytes(analysis="test_look")),
        store,
        confirm.SHUFFLED,
        split_hash,
        ENV[confirm.SHUFFLED],
    )
    assert seen["codes"] == set(confirm_codes)


@pytest.mark.parametrize("bad", ["outcome_first", "split", "no_assign", "assign_twice"])
def test_the_context_enforces_the_order_of_a_run(registered, bad):
    def analysis(ctx):
        pairs = ctx.restrict(read_csv(ctx.read(PAIRS_PATH)))
        if bad == "outcome_first":
            ctx.read(OUTCOMES_PATH)
        if bad == "split":
            ctx.read(confirm.SPLIT_PATH)
        if bad != "no_assign":
            ctx.assign(pairs, key=("pair_id",))
        if bad == "assign_twice":
            ctx.assign(pairs, key=("pair_id",))
        return {"estimates": [{"name": "x", "estimate": 0.0, "p_value": 1.0, "confirmatory": True}]}

    registered("test_order", analysis)
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes(analysis="test_order"))
    with pytest.raises(
        ConfirmError, match="after the treatment|runner reads the split|never took|once"
    ):
        confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])


@pytest.mark.parametrize(
    "mode, environ",
    [
        (confirm.REAL, {}),
        (confirm.REAL, ENV[confirm.SHUFFLED]),
        (confirm.SHUFFLED, ENV[confirm.REAL]),
        (
            confirm.REAL,
            {
                **ENV[confirm.REAL],
                "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/unblind.yml@refs/heads/x",
            },
        ),
        (confirm.SHUFFLED, {"GITHUB_WORKFLOW_REF": ENV[confirm.SHUFFLED]["GITHUB_WORKFLOW_REF"]}),
    ],
)
def test_each_mode_runs_only_in_its_own_workflow_on_main(registered, mode, environ):
    store, split_hash, _ = make_world()
    with pytest.raises(ConfirmError, match="happens only in"):
        confirm.run(confirm.load_spec(spec_bytes()), store, mode, split_hash, environ)


@pytest.mark.parametrize(
    "results",
    [
        {"estimates": []},
        {"estimates": [{"name": "x", "estimate": 1.0, "p_value": 0.5, "confirmatory": False}]},
        {"estimates": [{"name": "x", "estimate": "1.0", "p_value": 0.5, "confirmatory": True}]},
        {
            "estimates": [
                {"name": "x", "estimate": float("nan"), "p_value": 0.5, "confirmatory": True}
            ]
        },
        {"estimates": [{"name": "x", "estimate": 1.0, "p_value": 1.5, "confirmatory": True}]},
        {
            "estimates": [
                {
                    "name": "x",
                    "estimate": 1.0,
                    "p_value": 0.5,
                    "confirmatory": True,
                    "note": "free text",
                }
            ]
        },
        {
            "estimates": [{"name": "x", "estimate": 1.0, "p_value": 0.5, "confirmatory": True}],
            "counts": {"pairs": 1.5},
        },
        {
            "estimates": [{"name": "x", "estimate": 1.0, "p_value": 0.5, "confirmatory": True}],
            "notes": "free text",
        },
    ],
)
def test_results_hold_numbers_and_short_names_only(results):
    with pytest.raises(ConfirmError):
        confirm.validate_results(results)


# --- the ledger --------------------------------------------------------------


def entry_for(output, label, run_id="1", accept=False):
    return confirm.ledger_entry(
        output,
        label,
        run_id=run_id,
        run_url="https://example.invalid/run",
        code_commit=COMMIT,
        date_utc=f"2026-11-07T12:00:0{run_id}Z",
        accept_failed_shuffle=accept,
    )


def test_unblind_needs_a_passing_shuffled_run_of_the_same_specification(registered):
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes())
    with pytest.raises(ConfirmError, match="no shuffled run"):
        confirm.check_unblind(spec, [])

    shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    entries = [entry_for(shuffled, confirm.check_shuffled(spec, []))]
    assert entries[0]["label"] == confirm.LABEL_SHUFFLED
    assert confirm.check_unblind(spec, entries) == confirm.LABEL_UNBLINDED

    edited = confirm.load_spec(spec_bytes(hypothesis="Edited after the shuffled run."))
    with pytest.raises(ConfirmError, match="no shuffled run"):
        confirm.check_unblind(edited, entries)

    failed = {
        **shuffled,
        "shuffled_check": {"alpha": 0.05, "passed": False, "failing": ["contrast"]},
    }
    with pytest.raises(ConfirmError, match="found something"):
        confirm.check_unblind(spec, [entry_for(failed, confirm.LABEL_SHUFFLED)])
    assert (
        confirm.check_unblind(
            spec, [entry_for(failed, confirm.LABEL_SHUFFLED)], accept_failed_shuffle=True
        )
        == confirm.LABEL_UNBLINDED
    )


def test_unblind_runs_once_and_later_runs_are_post_unblinding(registered, tmp_path):
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes())
    shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    confirm.write_ledger_entry(tmp_path, entry_for(shuffled, confirm.LABEL_SHUFFLED, "1"))
    label = confirm.check_unblind(spec, confirm.read_ledger(tmp_path))
    real = confirm.run(spec, store, confirm.REAL, split_hash, ENV[confirm.REAL])
    confirm.write_ledger_entry(tmp_path, entry_for(real, label, "2"))

    entries = confirm.read_ledger(tmp_path)
    with pytest.raises(ConfirmError, match="unblinded before"):
        confirm.check_unblind(spec, entries)
    with pytest.raises(ConfirmError, match="unblinded before"):
        confirm.check_unblind(spec, entries, accept_failed_shuffle=True)
    assert confirm.check_shuffled(spec, entries) == confirm.LABEL_SHUFFLED_POST


def test_ledger_entries_are_never_overwritten_and_labels_match_the_mode(registered, tmp_path):
    store, split_hash, _ = make_world()
    spec = confirm.load_spec(spec_bytes())
    shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    entry = entry_for(shuffled, confirm.LABEL_SHUFFLED)
    confirm.write_ledger_entry(tmp_path, entry)
    with pytest.raises(FileExistsError):
        confirm.write_ledger_entry(tmp_path, entry)
    with pytest.raises(ConfirmError, match="cannot be labelled"):
        entry_for(shuffled, confirm.LABEL_UNBLINDED)


# --- the workflows -----------------------------------------------------------


def load_workflow(name: str) -> dict:
    wf = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))  # YAML 1.1 reads the key `on` as true
    return wf


def steps_text(job: dict) -> list[str]:
    return [yaml.safe_dump(s) for s in job["steps"]]


def index_of(steps: list[str], needle: str) -> int:
    return next(i for i, s in enumerate(steps) if needle in s)


@pytest.mark.parametrize("name, mode", [("confirm-run.yml", "shuffled"), ("unblind.yml", "real")])
def test_workflows_are_manual_main_only_and_use_their_own_mode(name, mode):
    wf = load_workflow(name)
    assert set(wf["on"]) == {"workflow_dispatch"}
    assert wf["permissions"] == {"contents": "read"}
    other = {"shuffled": "real", "real": "shuffled"}[mode]
    for job in wf["jobs"].values():
        assert job["if"] == "github.ref == 'refs/heads/main'"
        text = "".join(steps_text(job))
        assert f"--mode {other}" not in text
        for step in job["steps"]:
            if "uses" in step:
                assert len(step["uses"].split("@")[1].split()[0]) == 40, step["uses"]
        if job.get("permissions", {}).get("id-token") == "write":
            assert job["environment"] == "unblind"
            assert "terrain-unblind@" in text
            assert f"--mode {mode}" in text
            run_step = index_of(steps_text(job), "confirm_run.py run")
            assert index_of(steps_text(job), "google-github-actions/auth") < run_step
            assert index_of(steps_text(job), "confirm_run.py check") < run_step
        else:
            assert "google-github-actions/auth" not in text


def test_unblind_claims_its_branch_after_approval_and_before_any_credential():
    wf = load_workflow("unblind.yml")
    assert wf["concurrency"] == {"group": "unblind", "cancel-in-progress": False}
    run_job = wf["jobs"]["run"]
    assert run_job["needs"] == "check" and run_job["environment"] == "unblind"
    steps = steps_text(run_job)
    claim = index_of(steps, "git/refs")
    assert (
        index_of(steps, "confirm_run.py check")
        < claim
        < index_of(steps, "google-github-actions/auth")
    )
    assert "ledger/unblind-${SPEC}" in steps[claim]
    assert "GH_TOKEN" not in "".join(steps[claim + 1 :])
    assert "environment" not in wf["jobs"]["check"] and "environment" not in wf["jobs"]["record"]


def test_the_script_refuses_a_real_run_outside_its_workflow(tmp_path, monkeypatch, registered):
    loaded = importlib.util.spec_from_file_location(
        "confirm_run", REPO / "scripts" / "confirm_run.py"
    )
    script = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(script)
    store, split_hash, _ = make_world()
    spec_path = tmp_path / "0001-synthetic.yaml"
    spec_path.write_bytes(spec_bytes())
    spec = confirm.load_spec(spec_bytes())
    shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
    ledger = tmp_path / "ledger"
    confirm.write_ledger_entry(ledger, entry_for(shuffled, confirm.LABEL_SHUFFLED))
    monkeypatch.setattr(script, "LEDGER", ledger)
    monkeypatch.setattr(confirm, "check_pap_commit", lambda repo, commit: None)
    monkeypatch.setattr(confirm, "load_registered", lambda: None)
    monkeypatch.setattr("terrain.storage.GCSStore", lambda bucket: store)
    split_file = tmp_path / "split.sha256"
    split_file.write_text(split_hash + "\n", encoding="utf-8")
    monkeypatch.setattr(script, "SPLIT_HASH", split_file)
    monkeypatch.setenv("TERRAIN_BUCKET", "synthetic")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert script.main(["check", "--spec", str(spec_path), "--mode", "real"]) == 0
    assert (
        script.main(
            ["run", "--spec", str(spec_path), "--mode", "real", "--out-dir", str(tmp_path / "o")]
        )
        == 1
    )
    assert not (tmp_path / "o").exists()
