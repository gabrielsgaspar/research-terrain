"""The Legal Amazon's 1 km census cells with population and land tenure.

Contract: data/contracts/grid_cells.md. Logic: terrain.builds.grid_cells.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.grid_cells import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
GRID_2022_MANIFEST = MANIFESTS / "acquire" / "ibge_grid_2022.json"
GRID_2010_MANIFEST = MANIFESTS / "acquire" / "ibge_grid_2010.json"
BOUNDARIES_MANIFEST = MANIFESTS / "acquire" / "ibge_boundaries_2024.json"
CNFP_MANIFEST = MANIFESTS / "acquire" / "cnfp_public_forests.json"
MUNICIPALITIES_MANIFEST = MANIFESTS / "build" / "municipalities.json"


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
            _load(GRID_2022_MANIFEST),
            _load(GRID_2010_MANIFEST),
            _load(BOUNDARIES_MANIFEST),
            _load(CNFP_MANIFEST),
            _load(MUNICIPALITIES_MANIFEST),
            derived_root=dataset("grid_cells")["derived"],
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
