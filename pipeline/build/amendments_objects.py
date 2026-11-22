"""What the amendment money of the amendments panel's rows is, split by half.

Contract: data/contracts/amendments_objects.md. Logic: terrain.builds.amendments_objects.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.amendments_objects import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
REFERENCE = REPO / "data" / "reference"


def _load(stage: str, name: str) -> dict:
    return json.loads((MANIFESTS / stage / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    entry = dataset("amendments_objects")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            _load("acquire", "tse_general"),
            _load("acquire", "cgu_amendments"),
            _load("build", "tse_results"),
            _load("build", "tse_candidates"),
            _load("build", "municipalities"),
            _load("acquire", "camara_deputies"),
            labels_path=REFERENCE / "pix_object_labels.yaml",
            codebook_path=REFERENCE / "pix_object_codebook.md",
            derived_root=entry["derived"],
            sealed_root=entry["sealed"],
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
