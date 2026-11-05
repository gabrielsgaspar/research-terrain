"""Exposure of unrepresented 1 km cells to the close council races of their municipality.

Contract: data/contracts/cell_displacement.md. Logic: terrain.builds.cell_displacement.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.cell_displacement import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests" / "build"


def _load(name: str) -> dict:
    return json.loads((MANIFESTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            _load("grid_cells"),
            _load("cell_exposure"),
            _load("polling_places"),
            _load("section_votes"),
            _load("tse_results"),
            derived_root=dataset("cell_displacement")["derived"],
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
