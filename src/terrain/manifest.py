"""Build, validate, write and find pipeline manifests.

The contract is in `pipeline/README.md`. Validation applies the same
structural rules as the "Check the manifest" step of the data-pipeline
workflow. The workflow's credential scan is deliberately not repeated here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from terrain.storage import Store

ROOTS = {"acquire": "data/raw/", "build": "data/derived/"}
REQUIRED_KEYS = (
    "dataset",
    "stage",
    "status",
    "gcs_prefix",
    "created_at",
    "code_commit",
    "files",
)
MANIFEST_NAME = "_MANIFEST.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """Raised when a manifest breaks the contract."""


def validate_manifest(m: dict[str, Any], *, stage: str, dataset: str) -> list[str]:
    """Return the problems found in `m`; an empty list means it is valid."""
    root = ROOTS[stage]
    problems: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in m:
            problems.append(f"missing key: {key}")
    if m.get("dataset") != dataset:
        problems.append("dataset must equal the target name")
    if m.get("stage") != stage:
        problems.append("stage must equal the stage input")
    if m.get("status") not in ("created", "unchanged"):
        problems.append("status must be created or unchanged")
    prefix = m.get("gcs_prefix", "")
    if not isinstance(prefix, str):
        prefix = ""
    if not prefix.startswith(root) or ".." in prefix or not prefix.endswith("/"):
        problems.append(f"gcs_prefix must be a folder under {root}")
    for f in m.get("files", []):
        if not str(f.get("path", "")).startswith(prefix):
            problems.append(f"file outside gcs_prefix: {f.get('path')}")
        if not _SHA256.fullmatch(str(f.get("sha256", ""))):
            problems.append(f"bad sha256 for {f.get('path')}")
    return problems


def check_manifest(m: dict[str, Any], *, stage: str, dataset: str) -> None:
    problems = validate_manifest(m, stage=stage, dataset=dataset)
    if problems:
        raise ManifestError("; ".join(problems))


def build_manifest(
    *,
    dataset: str,
    stage: str,
    status: str,
    gcs_prefix: str,
    files: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
    inputs: list[str] | None = None,
    notes: str = "",
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Assemble a manifest and validate it. `inputs` is kept for build only."""
    m: dict[str, Any] = {
        "dataset": dataset,
        "stage": stage,
        "status": status,
        "gcs_prefix": gcs_prefix,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "code_commit": (
            code_commit if code_commit is not None else os.environ.get("CODE_COMMIT", "")
        ),
        "sources": sources or [],
        "files": files,
        "notes": notes,
    }
    if stage == "build":
        m["inputs"] = inputs or []
    check_manifest(m, stage=stage, dataset=dataset)
    return m


def write_manifest(m: dict[str, Any], store: Store, local_path: Path) -> None:
    """Validate `m`, write it to `local_path`, then create it in the store."""
    check_manifest(m, stage=m.get("stage", ""), dataset=m.get("dataset", ""))
    data = (json.dumps(m, indent=2) + "\n").encode("utf-8")
    local_path.write_bytes(data)
    store.create(m["gcs_prefix"] + MANIFEST_NAME, data)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(*parts: object) -> str:
    """A short, stable hash of the parts, for build output paths."""
    h = hashlib.sha256()
    for part in parts:
        b = str(part).encode("utf-8")
        h.update(len(b).to_bytes(8, "big"))
        h.update(b)
    return h.hexdigest()[:16]


def latest_manifest(store: Store, prefix: str) -> dict[str, Any] | None:
    """The newest manifest under `prefix` (by `created_at`, then path), or None."""
    best: tuple[str, str] | None = None
    best_m: dict[str, Any] | None = None
    for path in store.list(prefix):
        if not path.endswith(MANIFEST_NAME):
            continue
        m = json.loads(store.read_bytes(path))
        key = (str(m.get("created_at", "")), path)
        if best is None or key > best:
            best, best_m = key, m
    return best_m
