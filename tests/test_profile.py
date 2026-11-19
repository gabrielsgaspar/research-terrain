"""terrain.profile and scripts/profile_failure.py: row counts, never values (decision 0016)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from terrain import profile
from terrain.campaigns.repair import scan_log

REPO = Path(__file__).resolve().parents[1]
COUNTS = {("2026", "ok"): 53520, ("2026", "placeholder"): 2301, ("2026", "not_in_reference"): 77}


def load_script():
    spec = importlib.util.spec_from_file_location(
        "profile_failure", REPO / "scripts" / "profile_failure.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_profile_writes_only_when_the_workflow_asks(tmp_path, monkeypatch):
    monkeypatch.delenv(profile.ENV, raising=False)
    assert profile.write_profile("recipient_municipality", COUNTS) is None
    out = tmp_path / "profile.json"
    monkeypatch.setenv(profile.ENV, str(out))
    assert profile.write_profile("recipient_municipality", COUNTS) == out
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw == {
        "check": "recipient_municipality",
        "counts": [
            ["2026", "not_in_reference", 77],
            ["2026", "ok", 53520],
            ["2026", "placeholder", 2301],
        ],
    }
    # a list of (period, category, rows) works the same
    profile.write_profile("recipient_municipality", [(p, c, n) for (p, c), n in COUNTS.items()])
    assert json.loads(out.read_text(encoding="utf-8")) == raw


@pytest.mark.parametrize(
    "check, counts",
    [
        ("Recipient municipality", {("2026", "ok"): 1}),  # not a code label
        ("recipient", {("2026", "Sem informação"): 1}),  # a value as a category
        ("recipient", {("2026", "sao_paulo"): 1}),  # not in the fixed list
        ("recipient", {("Belém", "ok"): 1}),  # a value as a period
        ("recipient", {("2026", "ok"): 12345678901}),  # shaped like a CPF
        ("recipient", {("2026", "ok"): -1}),
        ("recipient", {("2026", "ok"): True}),
        ("recipient", {}),
        ("recipient", {(str(1900 + i), "ok"): 1 for i in range(profile.MAX_ROWS + 1)}),
    ],
)
def test_write_profile_refuses_anything_but_counts(tmp_path, monkeypatch, check, counts):
    monkeypatch.setenv(profile.ENV, str(tmp_path / "profile.json"))
    with pytest.raises(ValueError, match="bad profile"):
        profile.write_profile(check, counts)
    assert not (tmp_path / "profile.json").exists()


def test_text_category_tells_missing_from_placeholders():
    assert profile.text_category(None) == "empty"
    assert profile.text_category("   ") == "empty"
    assert profile.text_category(" Sem  Informação ") == "placeholder"
    assert profile.text_category("NÃO SE APLICA") == "placeholder"
    assert profile.text_category("Belém") is None
    assert set(profile.CATEGORIES) >= {"ok", "empty", "placeholder", "other"}


def test_the_fixed_script_prints_what_the_tick_reads(tmp_path, monkeypatch, capsys):
    script = load_script()
    out = tmp_path / "profile.json"
    monkeypatch.setenv(profile.ENV, str(out))
    profile.write_profile("recipient_municipality", COUNTS)
    assert script.main(["profile_failure.py", str(out)]) == 0
    printed = capsys.readouterr().out
    lines = printed.splitlines()
    assert lines == [
        profile.BEGIN,
        "check: recipient_municipality",
        "2026 not_in_reference 77",
        "2026 ok 53520",
        "2026 placeholder 2301",
        profile.END,
    ]
    # what the tick's scanner reads back from the job log, timestamps and all
    stamped = "\n".join(f"2026-11-10T10:00:00.1234567Z {line}" for line in lines)
    assert scan_log(stamped).profile == tuple(lines)


def test_the_fixed_script_says_when_there_is_nothing_to_print(tmp_path, capsys):
    script = load_script()
    assert script.main(["profile_failure.py", str(tmp_path / "missing.json")]) == 0
    assert capsys.readouterr().out.strip() == profile.NONE
    edited = tmp_path / "edited.json"
    for text in (
        "not json",
        json.dumps({"check": "x", "counts": [["2026", "Sem informação", 3]]}),
        json.dumps({"check": "x", "counts": [["2026", "ok", 3]], "values": ["a"]}),
    ):
        edited.write_text(text, encoding="utf-8")
        assert script.main(["profile_failure.py", str(edited)]) == 0
        assert capsys.readouterr().out.strip() == profile.REFUSED


def test_the_pipeline_workflow_profiles_a_failed_run():
    text = (REPO / ".github" / "workflows" / "data-pipeline.yml").read_text(encoding="utf-8")
    run = text.index("- name: Run pipeline/")
    step = text.index("- name: Profile the failed check")
    assert "TERRAIN_PROFILE_OUT: ${{ runner.temp }}/profile.json" in text[run:step]
    body = text[step : text.index("- name:", step + 1)]
    assert "if: failure()" in body
    assert 'uv run python scripts/profile_failure.py "${RUNNER_TEMP}/profile.json"' in body
