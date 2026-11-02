"""Build the municipalities table and the TSE-IBGE crosswalk.

Contract: pipeline/README.md. Logic: terrain.builds.municipalities.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.municipalities import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
IBGE_MANIFEST = MANIFESTS / "acquire" / "ibge_municipalities.json"
HIDALGO_MANIFEST = MANIFESTS / "acquire" / "polling_stations_geocoded.json"
CANDIDATES_MANIFEST = MANIFESTS / "build" / "tse_candidates.json"
VARIANTS = REPO / "data" / "reference" / "tse_ibge_name_variants.yaml"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            read(IBGE_MANIFEST),
            read(HIDALGO_MANIFEST),
            read(CANDIDATES_MANIFEST),
            derived_root=dataset("municipalities")["derived"],
            tmp_dir=Path(tmp),
            variants_path=VARIANTS,
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
