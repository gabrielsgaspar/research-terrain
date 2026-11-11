"""Gold exposure per municipality and real gold and soybean prices (idea 0007).

Contract: data/contracts/gold_exposure.md. Logic: terrain.builds.gold_exposure.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.gold_exposure import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"


def _load(stage: str, name: str) -> dict:
    return json.loads((MANIFESTS / stage / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    exposure = dataset("gold_exposure")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            _load("acquire", "anm_sigmine"),
            _load("acquire", "sgb_gold_occurrences"),
            _load("acquire", "gold_price"),
            _load("acquire", "ibge_boundaries_2024"),
            _load("build", "municipalities"),
            _load("acquire", "cnfp_public_forests"),
            derived_root=exposure["derived"],
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
