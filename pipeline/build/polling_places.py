"""Build the located polling places of Brazil (every municipality with a TSE code).

Contract: data/contracts/polling_places.md. Logic: terrain.builds.polling_places.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.polling_places import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
TSE_MANIFEST = MANIFESTS / "acquire" / "tse_polling_places.json"
HIDALGO_MANIFEST = MANIFESTS / "acquire" / "polling_stations_geocoded.json"
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
            _load(TSE_MANIFEST),
            _load(HIDALGO_MANIFEST),
            _load(MUNICIPALITIES_MANIFEST),
            derived_root=dataset("polling_places")["derived"],
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
