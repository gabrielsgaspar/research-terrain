"""Simplified map layers for the paper figures.

Contract: data/contracts/figure_layers.md. Logic: terrain.builds.figure_layers.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.figure_layers import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

ACQUIRE = REPO / "data" / "manifests" / "acquire"
NATURALEARTH_MANIFEST = ACQUIRE / "naturalearth_basemap.json"
IBGE_MANIFEST = ACQUIRE / "ibge_boundaries_2024.json"
CNFP_MANIFEST = ACQUIRE / "cnfp_public_forests.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            _load(NATURALEARTH_MANIFEST),
            _load(IBGE_MANIFEST),
            _load(CNFP_MANIFEST),
            derived_root=dataset("figure_layers")["derived"],
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
