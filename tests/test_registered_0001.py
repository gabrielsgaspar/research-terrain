"""Idea 0001's registered analysis (`terrain.registered.r0001`), on synthetic data only.

The world (`tests/world_0001.py`) is made up; nothing here reads confirm/, sealed/ or
GCS. No test runs the analysis at the registered window (0.25%): the plan forbids that
on any data before registration, so every run below uses 0.5%.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import world_0001 as W

from terrain import confirm
from terrain import strongholds as sh
from terrain.registered.r0001 import analysis as A
from terrain.registered.r0001 import frozen as fz
from terrain.storage import MemoryStore

REPO = Path(__file__).resolve().parents[1]
WINDOW = 0.005  # never the registered 0.0025
DRAWS = 200
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


def load_explore(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "explore" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Recording(MemoryStore):
    """A MemoryStore that remembers every path downloaded."""

    def __init__(self) -> None:
        super().__init__()
        self.downloaded: list[str] = []

    def download(self, path: str, local_file: Path) -> None:
        self.downloaded.append(path)
        super().download(path, local_file)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    store = Recording()
    manifests = tmp_path_factory.mktemp("manifests")
    W.write_world(store, manifests)
    store.create(confirm.SPLIT_PATH, W.split_csv())
    return store, manifests


@pytest.fixture(scope="module")
def explored(world, tmp_path_factory):
    store, manifests = world
    return A.run_exploration(
        store, W.explore_half(), WINDOW, tmp_path_factory.mktemp("run"), DRAWS, manifests=manifests
    )


# --- The frozen copies


def test_frozen_functions_are_verbatim_copies_of_the_explore_scripts():
    """Same syntax tree as the original, once the module prefixes are removed."""
    text = (REPO / "src" / "terrain" / "registered" / "r0001" / "frozen.py").read_text(
        encoding="utf-8"
    )
    frozen = {
        n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef | ast.ClassDef)
    }
    sections = re.findall(r"# --- From explore/(\S+) at", text)
    assert sections, "frozen.py names its sources"
    checked = 0
    for file in sections:
        source = (REPO / "explore" / file).read_text(encoding="utf-8")
        originals = {
            n.name: n
            for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef | ast.ClassDef)
        }
        block = text.split(f"# --- From explore/{file} at")[1].split("# --- From explore/")[0]
        for name in re.findall(r"^(?:def|class) (\w+)", block, flags=re.M):
            original_name = "_counts" if name == "_cell_counts" else name
            original = ast.get_source_segment(source, originals[original_name])
            original = original.replace("pb._counts(", "_cell_counts(")
            original = re.sub(r"\b(pb|pw|ef|census|kc1|mp|wn)\.", "", original)
            if name != original_name:
                original = original.replace(f"def {original_name}(", f"def {name}(", 1)
            assert ast.dump(ast.parse(original)) == ast.dump(
                ast.parse(ast.get_source_segment(text, frozen[name]))
            ), f"{name} differs from explore/{file}"
            checked += 1
    assert checked >= 60


# --- Equal to the explore scripts on the same synthetic data


@pytest.fixture(scope="module")
def effects_run(world, tmp_path_factory):
    """explore/0001_effects.py on the same world and draws, in its results.json shape."""
    store, manifests = world
    tmp = tmp_path_factory.mktemp("effects")
    ef = load_explore("test_reg_effects", "0001_effects.py")
    ef.census.MANIFESTS = manifests
    parts = {k: [] for k in ef.SPECS}
    counts = {k: {} for k in ef.SPECS}
    dropped, types = {}, {"5km": {}, "2km": {}}
    for year in ef.ELECTIONS:
        got = ef._year(store, tmp, W.explore_half(), year)
        dropped[str(year)] = got["dropped"]
        for label in ef.SPECS:
            parts[label].append(got["parts"][label])
            counts[label][year] = got["counts"][label]
        for band, per in got["types"].items():
            types[band][str(year)] = per
    specs = {label: ef.pw.assemble(label, parts[label]) for label in ef.SPECS}
    observed, sims = ef.pw.run_ri(specs, DRAWS, ef.pw.SEED)
    per_election = ef.pw._per_election(counts, specs)
    estimates = {}
    for label, spec in specs.items():
        estimates[label] = ef.report_estimate(spec, observed, sims)
        estimates[label]["counts"] = per_election[label]
    assert tuple(ef.SPECS) == A.EFFECT_LABELS
    out = {
        "estimates": estimates,
        "outcome_cells_dropped": dropped,
        "type_counts": {
            band: {"per_election": per, "pooled": ef.pw.pool_type_counts(per)}
            for band, per in types.items()
        },
    }
    return json.loads(json.dumps(out))


@pytest.fixture(scope="module")
def kc1_run(world, tmp_path_factory):
    store, manifests = world
    kc1 = load_explore("test_reg_kc1", "0001_kill_criterion_1.py")
    kc1.census.MANIFESTS = manifests
    tmp = tmp_path_factory.mktemp("kc1")
    per = {str(y): kc1._year(store, tmp, W.explore_half(), y) for y in A.ALL_ELECTIONS}
    return json.loads(
        json.dumps({**per, "pooled": kc1.pool(per), "verdict": kc1.verdict(kc1.pool(per))})
    )


def test_every_estimate_of_run_42298466207_comes_out_identical(explored, effects_run):
    """explore/0001_effects.py and the registered analysis, same world, same draws."""
    for label in A.EFFECT_LABELS:
        assert json.dumps(effects_run["estimates"][label], sort_keys=True) == json.dumps(
            explored["estimates"][label], sort_keys=True
        ), label
    assert explored["outcome_cells_dropped"] == effects_run["outcome_cells_dropped"]
    assert json.loads(json.dumps(explored["type_counts"])) == effects_run["type_counts"]
    direct = explored["estimates"]["direct"]["slots"]["Y4"]["beta"]
    assert direct["slope"] > 0 and direct["ri_p"] <= 0.01  # the world has an effect


def test_the_validation_script_reports_a_reproduction_and_catches_a_difference(
    explored, effects_run, kc1_run
):
    rc = load_explore("test_reg_check", "0001_registered_check.py")
    assert rc.WINDOW == 0.005
    c = rc.check(explored, effects_run, kc1_run)
    assert c["reproduced"] is True and c["mismatches"] == 0
    assert c["numbers_compared"]["effects"] > 500 and c["numbers_compared"]["kill_criterion_1"] > 30
    assert set(c["computed_not_reported"]) == {*rc.NEW_BLOCKS, "balance"}
    changed = json.loads(json.dumps(effects_run))
    changed["estimates"]["ring2"]["slots"]["Y4"]["beta"]["slope"] *= 1 + 1e-6
    changed["estimates"]["split5"]["slots"]["Y2"]["delta"]["ri_p"] += 1e-12
    c = rc.check(explored, changed, kc1_run)
    assert c["reproduced"] is False and c["mismatches"] == 2
    assert rc.summary(c).startswith("Reproduced: no.")
    assert "direct_adj" not in json.dumps(c["first_mismatches"])  # new blocks are never printed


def test_kill_criterion_1_counts_equal_the_kill_criterion_1_script(explored, kc1_run):
    per = {y: v for y, v in kc1_run.items() if y.isdigit()}
    assert explored["kill_criterion_1"]["per_election"] == per
    assert explored["kill_criterion_1"]["pooled"] == kc1_run["pooled"]
    assert explored["kill_criterion_1"]["met"] is False


def test_alignment_kinds_count_as_the_alignment_script(world, tmp_path):
    store, manifests = world
    al = load_explore("test_reg_align", "0004_alignment_counts.py")
    reader = A.Reader(
        store.download,
        lambda df: df.filter(pl.col("cd_ibge").cast(pl.Utf8).is_in(sorted(W.explore_half()))),
        "files",
        tmp_path,
        manifests,
    )
    cands = A.load_candidates(reader)
    for year in (2008, 2024):
        t = A.treatment_year(reader, cands, year, WINDOW)
        cv = reader.read("tse_results", rf"candidate_votes_{year}\.parquet$")
        main = sh.main_election(cv)
        now = cands.filter(pl.col("ano_eleicao") == year)
        mayors, _ = al.elected_mayor(cv, main, year)
        coalitions = reader.read(
            "tse_parties", rf"coalitions_{year}\.parquet$", A.COALITION_COLUMNS
        )
        coalition, _ = al.mayor_coalition(mayors, now, coalitions, main)
        pairs = t["pairs"].rename({"w": "elected_sq", "l": "other_sq"})
        counts = al.pair_types(pairs, al.council_parties(now, main), coalition, year)
        kinds = t["align"]
        assert kinds.count("aligned") == counts["aligned"] > 0
        assert kinds.count("unaligned") == counts["unaligned"] > 0
        assert kinds.count("mixed") == counts["mixed"]
        assert kinds.count("left_out") == counts["left_out_side"] + counts["left_out_mayor"]


def test_balance_equals_the_window_script_on_the_same_differences():
    wn = load_explore("test_reg_window", "0001_window.py")
    rng = np.random.default_rng(4)
    diff = rng.normal(size=(300, len(A.COVARIATES)))
    diff[:7, 2] = np.nan
    got = A.balance([diff[:120], diff[120:]], DRAWS, fz.SEED)
    want = wn.balance_by_window(
        diff, np.zeros(300), wn.sign_matrix(300, DRAWS, fz.SEED), A.COVARIATES, (0.01,), ("all",)
    )[0]
    assert got["omnibus_p"] == want["omnibus_p"]
    for name in A.COVARIATES:
        assert got["covariates"][name]["diff"] == want["covariates"][name]["diff"]
        assert got["covariates"][name]["p"] == want["covariates"][name]["p"]


@pytest.mark.parametrize("fallback", [False, True])
def test_the_fallback_decides_which_estimates_are_confirmatory(explored, fallback):
    results = dict(explored, fallback=fallback)
    results["confirmatory"] = {
        "kill_criterion_4": "direct_adj" if fallback else "direct",
        "kill_criterion_2": "direct_pre_adj" if fallback else "direct_pre",
    }
    ledger = confirm.validate_results(A.ledger_results(results))
    names = [e["name"] for e in ledger["estimates"] if e["confirmatory"]]
    suffix = "_adj" if fallback else ""
    assert names == [f"direct{suffix}_y4_beta", f"direct_pre{suffix}_y4_beta"]
    assert ledger["counts"]["fallback"] == int(fallback)
    assert explored["fallback"] == (explored["balance"]["omnibus_p"] < A.FALLBACK_P)


# --- Z, the incumbency term


def test_only_pairs_with_exactly_one_incumbent_contribute_to_z():
    pairs = pl.DataFrame(
        {
            "cd_eleicao": [1, 1, 1, 1, 1],
            "sg_ue": ["A"] * 5,
            "w": ["w1", "w2", "w3", "w4", "w5"],
            "l": ["l1", "l2", "l3", "l4", "l5"],
        }
    )
    flags = {
        "w1": 1.0,
        "l1": 0.0,
        "w2": 0.0,
        "l2": 1.0,
        "w3": 1.0,
        "l3": 1.0,
        "w4": 0.0,
        "l4": 0.0,
        "w5": 1.0,
        "l5": None,
    }
    inc = pl.DataFrame(
        {
            "cd_eleicao": [1] * 10,
            "sg_ue": ["A"] * 10,
            "sq_candidato": list(flags),
            "incumbent": list(flags.values()),
        }
    )
    assert A.incumbent_sign(pairs, inc)["s"].to_list() == [1.0, -1.0, 0.0, 0.0, 0.0]


def test_z_is_the_same_whichever_side_won(world, tmp_path):
    """Swapping a pair's sides negates its term of D and its sign: Z does not change."""
    store, manifests = world
    reader = A.Reader(store.download, lambda df: df, "files", tmp_path, manifests)
    cands = A.load_candidates(reader)
    t = A.treatment_year(reader, cands, 2012, WINDOW)
    pairs = t["pairs"]
    flipped = pairs.with_columns(pl.col("l").alias("w"), pl.col("w").alias("l"))
    cells = reader.read("grid_cells", r"grid_cells\.parquet$", A.GRID_COLUMNS)
    dist = sh.cell_place_distances(cells.select(sh.CELL), t["located"])

    def z(p):
        terms = fz.pair_terms(dist, t["totals"], t["shares"], p, "exp2")
        return (
            A.z_terms(terms, A.incumbent_sign(p, t["inc"]))
            .group_by(sh.CELL)
            .agg(pl.col("t").sum())
            .sort(sh.CELL)
        )

    assert A.incumbent_sign(pairs, t["inc"])["s"].abs().sum() > 0
    assert z(pairs).equals(z(flipped))
    d = fz.pair_terms(dist, t["totals"], t["shares"], pairs, "exp2")
    d_flipped = fz.pair_terms(dist, t["totals"], t["shares"], flipped, "exp2")
    assert np.allclose(d["t"].to_numpy(), -d_flipped["t"].to_numpy())


def test_the_adjusted_estimate_is_the_joint_regression_coefficient():
    rng = np.random.default_rng(1)
    n = 400
    x, z = rng.normal(size=n), rng.normal(size=n)
    y = 2.0 * x + 0.5 * z + rng.normal(size=n)
    design = fz.Design(
        y_tilde=y - y.mean(),
        group=np.zeros(n, dtype=np.int64),
        election=np.full(n, 2008),
        muni=np.array(["m"] * n),
        rows=np.arange(n),
        cols=np.arange(n),
        vals=x,
        n_pairs=n,
    )
    adj = A.Adjusted("a", design, z - z.mean(), {"Y4": y - y.mean(), "Y2": y - y.mean()})
    got = A.adjusted_estimates(adj, np.ones(n))
    xs = np.column_stack([x - x.mean(), z - z.mean()])
    coef = np.linalg.lstsq(xs, y - y.mean(), rcond=None)[0]
    assert np.isclose(got[("Y4", "beta")], coef[0]) and np.isclose(got[("Y4", "gamma")], coef[1])
    flipped = A.adjusted_estimates(adj, -np.ones(n))
    assert np.isclose(flipped[("Y4", "beta")], -coef[0])  # D flips, Z stays


# --- Order, refusals, stops


def test_the_registered_window_is_refused_before_registration(world, tmp_path):
    store, manifests = world
    before = len(store.downloaded)
    with pytest.raises(confirm.ConfirmError, match="before registration"):
        A.run_exploration(store, W.explore_half(), 0.0025, tmp_path, DRAWS, manifests=manifests)
    assert len(store.downloaded) == before


def test_kill_criterion_1_stops_the_run_before_any_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "TENURE", ((30.0, 30.0),) * 4)  # no stronghold near anything
    store = Recording()
    W.write_world(store, tmp_path / "m", with_builds=False)
    out = A.run_exploration(
        store, W.explore_half(), WINDOW, tmp_path, DRAWS, manifests=tmp_path / "m"
    )
    assert out["stopped"] == "kill_criterion_1" and out["kill_criterion_1"]["met"] is True
    assert not [p for p in store.downloaded if "cell_outcomes" in p]
    assert confirm.validate_results(A.ledger_results(out))["stopped"] == "kill_criterion_1"


def spec_text(window: str = "0.0025", draws: str = "2000") -> bytes:
    """The draft spec with its placeholders filled (and, for synthetic runs, 0.5%)."""
    text = (REPO / "harness" / "drafts" / "specs" / "0001-direct.yaml").read_text(encoding="utf-8")
    text = text.replace("FILL-IN-YYYY-MM-DD", "2026-12-01").replace(
        "FILL-IN-40-CHARACTER-COMMIT-HASH", "a" * 40
    )
    text = text.replace("  window: 0.0025 ", f"  window: {window} ").replace(
        "  draws: 2000\n", f"  draws: {draws}\n"
    )
    return text.encode("utf-8")


def test_the_draft_spec_loads_once_filled_and_describes_this_analysis():
    raw = (REPO / "harness" / "drafts" / "specs" / "0001-direct.yaml").read_bytes()
    with pytest.raises(confirm.ConfirmError):
        confirm.load_spec(raw)  # unfilled placeholders never load
    spec = confirm.load_spec(spec_text())
    assert spec.analysis == A.ANALYSIS and spec.id == "0001-direct"
    settings = A.check_spec(dict(spec.raw))
    assert (settings.window, settings.draws, settings.seed) == (0.0025, 2000, 20261106)
    bad = dict(spec.raw, exposure="ring2")
    with pytest.raises(confirm.ConfirmError, match="exposure"):
        A.check_spec(bad)


# --- Through confirm-run and unblind, on the synthetic confirmation half


@pytest.fixture(scope="module")
def through_runner(world):
    store, manifests = world
    old = A.MANIFESTS
    A.MANIFESTS = manifests
    try:
        spec = confirm.load_spec(spec_text("0.005", str(DRAWS)))
        split_hash = hashlib.sha256(W.split_csv()).hexdigest()
        shuffled = confirm.run(spec, store, confirm.SHUFFLED, split_hash, ENV[confirm.SHUFFLED])
        real = confirm.run(spec, store, confirm.REAL, split_hash, ENV[confirm.REAL])
        again = confirm.run(spec, store, confirm.REAL, split_hash, ENV[confirm.REAL])
    finally:
        A.MANIFESTS = old
    return shuffled, real, again


def estimate(output, name):
    return next(e for e in output["results"]["estimates"] if e["name"] == name)


def test_shuffled_finds_nothing_and_unblind_finds_the_effect(through_runner):
    shuffled, real, _ = through_runner
    assert shuffled["shuffled_check"]["passed"] is True
    confirmatory = [e["name"] for e in real["results"]["estimates"] if e["confirmatory"]]
    fallback = real["results"]["counts"]["fallback"]
    assert fallback == int(real["results"]["values"]["balance_omnibus_p"] < A.FALLBACK_P)
    kc4 = "direct_adj" if fallback else "direct"
    assert confirmatory == [f"{kc4}_y4_beta", f"{kc4.replace('direct', 'direct_pre')}_y4_beta"]
    for name in ("direct_y4_beta", "direct_adj_y4_beta"):
        assert estimate(real, name)["p_value"] <= 0.01 and estimate(real, name)["estimate"] > 0
        assert estimate(shuffled, name)["p_value"] >= 0.05
    assert real["results"]["counts"]["kc1_met"] == 0
    assert real["results"]["counts"]["pairs_one_incumbent"] > 0
    assert 0 < shuffled["pairs_flipped"] < shuffled["pairs"] == 5 * 80


def test_the_real_run_is_deterministic(through_runner):
    _, real, again = through_runner
    assert json.dumps(real, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_the_runner_reads_only_the_confirmation_half_and_its_sealed_outcomes(world, through_runner):
    store, _ = world
    sealed = [p for p in store.downloaded if p.startswith("sealed/")]
    assert sealed and all(p.startswith("sealed/outcomes/cell_outcomes/") for p in sealed)
