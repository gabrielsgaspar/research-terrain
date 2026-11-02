"""Build the TSE candidate-votes and turnout tables.

Contract: data/contracts/tse_results.md. Logic: terrain.builds.tse_results.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.tse_results import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

ACQUIRE_MANIFEST = REPO / "data" / "manifests" / "acquire" / "tse_results.json"
CANDIDATES_MANIFEST = REPO / "data" / "manifests" / "build" / "tse_candidates.json"
MUNICIPALITIES_MANIFEST = REPO / "data" / "manifests" / "build" / "municipalities.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    acquire_manifest = json.loads(ACQUIRE_MANIFEST.read_text(encoding="utf-8"))
    candidates_manifest = json.loads(CANDIDATES_MANIFEST.read_text(encoding="utf-8"))
    municipalities_manifest = json.loads(MUNICIPALITIES_MANIFEST.read_text(encoding="utf-8"))
    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            acquire_manifest,
            candidates_manifest,
            municipalities_manifest,
            derived_root=dataset("tse_results")["derived"],
            tmp_dir=Path(tmp),
            code_commit=os.environ.get("CODE_COMMIT", ""),
        )
        if manifest["status"] == "created":
            write_manifest(manifest, store, args.manifest_out)
        else:
            args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))


if __name__ == "__main__":
    try:
        main()
    except BuildError as err:
        raise SystemExit(f"build failed: {err}") from err
