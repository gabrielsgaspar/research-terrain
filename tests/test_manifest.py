import copy
import hashlib
import json

import pytest

from terrain.manifest import (
    ManifestError,
    build_manifest,
    content_hash,
    latest_manifest,
    sha256_file,
    validate_manifest,
    write_manifest,
)
from terrain.storage import MemoryStore

SHA = "a" * 64


def valid(stage="acquire"):
    root = "data/raw/" if stage == "acquire" else "data/derived/"
    prefix = f"{root}src/2026-01-01/"
    return {
        "dataset": "thing",
        "stage": stage,
        "status": "created",
        "gcs_prefix": prefix,
        "created_at": "2026-01-01T00:00:00+00:00",
        "code_commit": "abc",
        "files": [{"path": prefix + "f.csv", "sha256": SHA, "bytes": 1}],
    }


def problems(m, stage="acquire"):
    return validate_manifest(m, stage=stage, dataset="thing")


def test_accepts_valid_manifests():
    assert problems(valid()) == []
    assert problems(valid("build"), "build") == []


def test_rejects_missing_key():
    m = valid()
    del m["code_commit"]
    assert any("missing key: code_commit" in p for p in problems(m))


def test_rejects_wrong_dataset():
    m = valid()
    m["dataset"] = "other"
    assert any("dataset" in p for p in problems(m))


def test_rejects_acquire_prefix_outside_raw():
    m = valid()
    m["gcs_prefix"] = "data/derived/src/"
    m["files"] = []
    assert any("gcs_prefix" in p for p in problems(m))


def test_rejects_build_prefix_outside_derived():
    m = valid("build")
    m["gcs_prefix"] = "data/raw/src/"
    m["files"] = []
    assert any("gcs_prefix" in p for p in problems(m, "build"))


def test_rejects_prefix_without_trailing_slash():
    m = valid()
    m["gcs_prefix"] = "data/raw/src"
    m["files"] = []
    assert any("gcs_prefix" in p for p in problems(m))


def test_rejects_prefix_with_dotdot():
    m = valid()
    m["gcs_prefix"] = "data/raw/../x/"
    m["files"] = []
    assert any("gcs_prefix" in p for p in problems(m))


def test_rejects_file_outside_prefix():
    m = valid()
    m["files"][0]["path"] = "data/raw/elsewhere/f.csv"
    assert any("file outside gcs_prefix" in p for p in problems(m))


def test_rejects_malformed_sha256():
    m = valid()
    m["files"][0]["sha256"] = "XYZ"
    assert any("bad sha256" in p for p in problems(m))


def test_rejects_wrong_stage_and_status():
    m = valid()
    m["stage"] = "build"
    m["status"] = "weird"
    found = problems(m)
    assert any("stage" in p for p in found)
    assert any("status" in p for p in found)


def test_build_manifest_fills_fields(monkeypatch):
    monkeypatch.setenv("CODE_COMMIT", "deadbeef")
    base = valid()
    m = build_manifest(
        dataset="thing",
        stage="acquire",
        status="created",
        gcs_prefix=base["gcs_prefix"],
        files=base["files"],
    )
    assert m["code_commit"] == "deadbeef"
    assert "inputs" not in m
    assert m["created_at"]


def test_build_manifest_build_has_inputs_and_validates():
    base = valid("build")
    m = build_manifest(
        dataset="thing",
        stage="build",
        status="created",
        gcs_prefix=base["gcs_prefix"],
        files=base["files"],
        inputs=["data/manifests/acquire/x.json"],
        code_commit="c",
    )
    assert m["inputs"] == ["data/manifests/acquire/x.json"]
    with pytest.raises(ManifestError):
        build_manifest(
            dataset="thing",
            stage="build",
            status="bad",
            gcs_prefix=base["gcs_prefix"],
            files=base["files"],
            code_commit="c",
        )


def test_write_manifest_writes_local_and_store(tmp_path):
    store = MemoryStore()
    m = valid()
    out = tmp_path / "m.json"
    write_manifest(m, store, out)
    key = m["gcs_prefix"] + "_MANIFEST.json"
    assert json.loads(out.read_text()) == m
    assert json.loads(store.read_bytes(key)) == m
    with pytest.raises(FileExistsError):
        write_manifest(m, store, out)


def test_write_manifest_refuses_invalid(tmp_path):
    m = valid()
    m["files"][0]["sha256"] = "nope"
    with pytest.raises(ManifestError):
        write_manifest(m, MemoryStore(), tmp_path / "m.json")
    assert not (tmp_path / "m.json").exists()


def test_latest_manifest_returns_newest(tmp_path):
    store = MemoryStore()
    for day in ("02", "03", "01"):
        m = copy.deepcopy(valid())
        m["gcs_prefix"] = f"data/raw/src/2026-01-{day}/"
        m["files"] = []
        m["created_at"] = f"2026-01-{day}T00:00:00+00:00"
        write_manifest(m, store, tmp_path / f"{day}.json")
    store.create("data/raw/src/2026-01-03/other.csv", b"x")
    got = latest_manifest(store, "data/raw/src/")
    assert got is not None and got["created_at"].startswith("2026-01-03")


def test_latest_manifest_none_when_empty():
    assert latest_manifest(MemoryStore(), "data/raw/src/") is None


def test_content_hash_stable_and_sensitive():
    assert content_hash("a", "b", 1) == content_hash("a", "b", 1)
    base = content_hash("a", "b", 1)
    assert content_hash("a", "c", 1) != base
    assert content_hash("x", "b", 1) != base
    assert content_hash("a", "b", 2) != base
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_sha256_file(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello world")
    assert sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()
