import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "incumbency_gate_uniform10_f1", REPO / "explore" / "0012_incumbency_gate_uniform10_f1.py"
)
fork = importlib.util.module_from_spec(SPEC)
sys.modules["incumbency_gate_uniform10_f1"] = fork
SPEC.loader.exec_module(fork)
parent = fork.parent

SEEDS = (1, 2, 3, 4, 5)


def make_panel(seed: int, races: int = 40, margin_cap: float = 0.2) -> pl.DataFrame:
    """Two rows per race, five elections, built from the seed."""
    rng = np.random.default_rng(seed)
    rows = []
    for e in parent.ELECTIONS:
        for i in range(races):
            m = float(rng.uniform(0.0005, margin_cap))
            for sign in (1, -1):
                rows.append(
                    {
                        "election": e,
                        "cd_ibge": f"15{i:05d}",
                        "uf": "PA",
                        "party": f"P{sign}",
                        "margin": sign * m,
                        "win": sign > 0,
                        "fin_female": bool(rng.integers(0, 2)),
                        "fin_age": float(np.round(rng.normal(50, 8))),
                        "fin_higher_ed": bool(rng.integers(0, 2)),
                        "party_held_mayor_lag": bool(rng.integers(0, 2)),
                        "ln_pop": float(rng.normal(9, 1)),
                        "n_mayor_cands": 3,
                        "bench_fed": int(rng.integers(0, 3)) if e >= 2012 else None,
                        "finalist_eligible": bool(rng.random() < 0.9),
                    }
                )
    return pl.DataFrame(rows, infer_schema_length=None)


def small_draws(panel: pl.DataFrame, n: int = 49) -> np.ndarray:
    return parent.sign_draws(parent.n_races(panel), draws=n)


def test_design_constants():
    assert fork.H == 0.10
    assert fork.KERNEL == "uniform"
    for name in ("READ_COLUMNS", "SEED", "DRAWS", "BALANCE", "RULE_FIELDS", "GateError"):
        assert getattr(fork, name) is getattr(parent, name)


@pytest.mark.parametrize("seed", SEEDS)
def test_every_fit_gets_h_and_kernel(seed, monkeypatch):
    calls = []

    def recorder(name):
        original = getattr(parent, name)

        def wrapped(table, *args, **kwargs):
            calls.append((name, args, kwargs, table.height))
            return original(table, *args, **kwargs)

        monkeypatch.setattr(parent, name, wrapped)

    for name in ("counts_at", "balance_at", "placebo_at", "power_at"):
        recorder(name)
    panel = make_panel(seed)
    fork.build_results(panel, small_draws(panel))

    assert len(calls) == 8  # four blocks, all rows and the S2 sample
    assert sorted({c[0] for c in calls}) == ["balance_at", "counts_at", "placebo_at", "power_at"]
    for name, args, kwargs, _ in calls:
        # signature: (table, [draws,] h, kernel, ...)
        values = [v for v in (*args, *kwargs.values()) if isinstance(v, (float, str))]
        assert 0.10 in values, name
        assert "uniform" in values, name
        assert 0.135 not in values and "triangular" not in values, name
    heights = sorted({c[3] for c in calls})
    assert len(heights) == 2 and heights[0] < heights[1]


def test_window_edge_is_in_and_just_above_is_out():
    rows = []
    for i, m in enumerate((0.05, 0.10, 0.1001)):
        for sign in (1, -1):
            rows.append(
                {
                    "election": 2012,
                    "cd_ibge": f"15{i:05d}",
                    "margin": sign * m,
                    "win": sign > 0,
                    "finalist_eligible": True,
                }
            )
    table = parent.prepare(pl.DataFrame(rows))
    counts = parent.counts_at(table, fork.H, fork.KERNEL)
    assert counts["rows_h"]["e2012"] == 4
    assert counts["races_h"]["e2012"] == 2
    weights = parent.kernel_weights([0.05, 0.10, 0.1001], fork.H, fork.KERNEL)
    assert weights.tolist() == [1.0, 1.0, 0.0]
    # the parent's triangular fit at 0.135 weights the same rows differently
    assert parent.kernel_weights([0.05, 0.10], parent.H, parent.KERNEL).tolist() != [1.0, 1.0]


@pytest.mark.parametrize("seed", SEEDS)
def test_results_carry_every_rule_key_and_design(seed):
    panel = make_panel(seed)
    results = fork.build_results(panel, small_draws(panel))
    for field in (*fork.RULE_FIELDS, "estimates.finite", "design.h", "design.kernel"):
        assert parent._get(results, field) is not None, field
    assert results["design"] == {"h": 0.10, "kernel": "uniform", "seed": 20261122, "draws": 49}
    assert results["placebo"]["fail"] in (0, 1)
    assert isinstance(results["estimates"]["finite"], bool)
    for key in ("counts", "balance", "placebo", "power", "window"):
        assert key in results["s2_sample"], key
    assert "window" in results
    assert set(results["s2_sample"]["balance"]["covariates"]) == set(fork.BALANCE) - {
        "finalist_eligible"
    }
    # counts are inside the 10% window
    table = parent.prepare(panel)
    inside = table.filter(pl.col("margin").abs() <= 0.10 + 1e-12)
    assert results["counts"]["rows_h"]["e2012"] == inside.filter(pl.col("election") == 2012).height


@pytest.mark.parametrize("seed", SEEDS)
def test_matches_the_parent_functions_called_at_the_fork_design(seed):
    panel = make_panel(seed)
    draws = small_draws(panel)
    table = parent.prepare(panel)
    got = fork.build_results(panel, draws)
    expected = parent._clean(
        {
            "counts": parent.counts_at(table, 0.10, "uniform"),
            "balance": parent.balance_at(table, draws, 0.10, "uniform"),
            "placebo": parent.placebo_at(table, draws, 0.10, "uniform"),
            "power": parent.power_at(table, draws, 0.10, "uniform"),
        }
    )
    for key, value in expected.items():
        assert got[key] == value, key
    assert got["design"]["kernel"] != parent.KERNEL


def test_load_panel_restricts_to_the_half_and_reads_only_parent_columns():
    full = make_panel(1, races=6)
    half = frozenset(f"15{i:05d}" for i in range(3))
    calls = []

    def read(name: str, columns: list[str]) -> pl.DataFrame:
        calls.append(columns)
        year = int(name.removeprefix("panel_"))
        frame = full.filter(pl.col("election") == year).select(columns)
        return fork._restrict_half(frame, half)

    panel = parent.load_panel(read, half, columns=fork.READ_COLUMNS)
    assert set(panel["cd_ibge"].to_list()) == set(half)
    assert all(c == parent.READ_COLUMNS for c in calls)
    for column in fork.READ_COLUMNS:
        assert not column.endswith("_next"), column
        assert not column.startswith("amend_after"), column


def test_restrict_half_drops_rows_outside_the_half():
    frame = make_panel(1, races=4).filter(pl.col("election") == 2012)
    kept = fork._restrict_half(frame, frozenset({"1500000", "1500001"}))
    assert set(kept["cd_ibge"].to_list()) == {"1500000", "1500001"}


def test_main_restricts_with_the_national_half():
    source = (REPO / "explore" / "0012_incumbency_gate_uniform10_f1.py").read_text(encoding="utf-8")
    assert "exploration_municipalities(store, national=True)" in source
    assert "restrict(" in source
    assert "columns=READ_COLUMNS" in source
