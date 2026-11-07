import importlib.util
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "explore" / "0001_kill_criterion_1_window.py"
SPEC = importlib.util.spec_from_file_location("kc1_window", SCRIPT)
win = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(win)
kc1 = win.kc1
census = win.census

HALF = frozenset({"1500107"})


def paired(rows):
    """rows: (elected_sq, other_sq, margin, inverted)."""
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(rows),
            "sg_ue": ["01"] * len(rows),
            "elected_sq": [r[0] for r in rows],
            "other_sq": [r[1] for r in rows],
            "margin": [r[2] for r in rows],
            "inverted": [r[3] for r in rows],
        },
        schema_overrides={"margin": pl.Float64},
    )


def strong(sqs):
    return pl.DataFrame(
        {
            "cd_eleicao": [1] * len(sqs),
            "sg_ue": ["01"] * len(sqs),
            "sq_candidato": sqs,
            "cd_ibge": ["1500107"] * len(sqs),
            "nr_zona": [7] * len(sqs),
            "nr_local_votacao": list(range(1, len(sqs) + 1)),
        }
    )


def tenure(n):
    return pl.DataFrame(
        {
            "ano": [2020] * n,
            "cd_ibge": ["1500107"] * n,
            "sg_ue": ["01"] * n,
            "nr_zona": [7] * n,
            "nr_local_votacao": list(range(1, n + 1)),
            "dist_indigenous_km": [1.0] * n,
            "dist_settlement_km": [1.0] * n,
        }
    )


# pairs: 0.3% (a, b), exactly 0.25% (c, d), inverted at 0.1% (e, f)
PAIRS = paired([("a", "b", 0.003, False), ("c", "d", 0.0025, False), ("e", "f", 0.001, True)])
SQS = ["a", "b", "c", "d", "e", "f"]


def test_window_membership():
    counts = win.window_counts(PAIRS, strong(SQS), tenure(6))
    assert counts["0.25%"]["candidates"] == 2  # c, d only
    assert counts["0.50%"]["candidates"] == 4  # a, b, c, d; never e, f
    assert counts["0.25%"]["indigenous"]["5km"] == 2
    assert counts["0.50%"]["indigenous"]["5km"] == 4


def test_counts_equal_kc1_with_each_windows_close_candidates():
    counts = win.window_counts(PAIRS, strong(SQS), tenure(6))
    for name, threshold in win.WINDOWS.items():
        close = census.close_candidates(PAIRS, threshold)
        assert counts[name] == kc1.band_counts(
            kc1.candidate_distances(close, strong(SQS), tenure(6))
        )


class CountingStore:
    def __init__(self, files):
        self.files = files
        self.downloads = []

    def download(self, remote, local):
        self.downloads.append(remote)
        self.files[Path(remote).name].write_parquet(local)


def _fake_year(monkeypatch, tmp_path):
    sv = pl.DataFrame({"cd_ibge": ["1500107", "9999999"]})
    files = {
        "candidate_votes_2020.parquet": pl.DataFrame({"cd_ibge": ["1500107"]}),
        "turnout_2020.parquet": pl.DataFrame({"cd_ibge": ["1500107"]}),
        "polling_place_tenure_2020.parquet": tenure(6),
        "section_votes_2020_PA.parquet": sv,
    }
    names = {
        "tse_results": ["candidate_votes_2020.parquet", "turnout_2020.parquet"],
        "polling_place_tenure": ["polling_place_tenure_2020.parquet"],
        "section_votes": ["section_votes_2020_PA.parquet"],
    }

    def fake_paths(manifest, pattern):
        import re

        return [f"gs://bucket/{manifest}/{n}" for n in names[manifest] if re.search(pattern, n)]

    monkeypatch.setattr(census, "_paths", fake_paths)
    monkeypatch.setattr(census, "main_election", lambda cv: 1)
    monkeypatch.setattr(census, "candidacy_votes", lambda cv, year, main: cv)
    monkeypatch.setattr(census, "within_list_pairs", lambda c: c)
    monkeypatch.setattr(census, "valid_votes", lambda t, main: t)
    monkeypatch.setattr(census, "margins", lambda p, v: PAIRS)
    monkeypatch.setattr(census, "place_candidate_votes", lambda s, main: s)
    monkeypatch.setattr(census, "strongholds", lambda s: strong(SQS))
    return CountingStore(files)


def test_one_download_per_file_and_no_outcome_reads(monkeypatch, tmp_path):
    store = _fake_year(monkeypatch, tmp_path)
    out = win._year(store, tmp_path, HALF, 2020)
    assert set(out) == {"0.25%", "0.50%"}
    assert len(store.downloads) == 4
    assert len(set(store.downloads)) == 4
    for path in store.downloads:
        for banned in ("cell_outcomes", "cell_exposure", "cell_displacement"):
            assert banned not in path


def test_results_hold_both_windows_and_verdicts():
    one = win.window_counts(PAIRS, strong(SQS), tenure(6))
    results = win._results({"2020": one, "2024": one})
    assert list(results) == ["0.25%", "0.50%"]
    for block in results.values():
        assert {"2020", "2024", "pooled", "verdict"} <= set(block)
        assert block["verdict"]["kill_criterion_1"] in {"met", "not met"}
    assert results["0.25%"]["pooled"]["candidates"] == 4
    assert results["0.50%"]["pooled"]["candidates"] == 8
    summary = win._summary(results)
    assert summary.startswith("Kill criterion 1 at 0.25%")


def test_script_reuses_kc1_and_restricts():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "spec_from_file_location" in source
    assert "0001_kill_criterion_1.py" in source
    assert "def band_counts" not in source
    assert "def candidate_distances" not in source
    assert "exploration_municipalities(" in source
    assert "restrict(" in source
