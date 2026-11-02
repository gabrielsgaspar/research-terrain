"""Type the polling places of the Legal Amazon (seat, town, rural, ...).

Contract: data/contracts/polling_place_types.md. Logic: terrain.builds.polling_place_types.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.polling_place_types import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
POLLING_PLACES_MANIFEST = MANIFESTS / "build" / "polling_places.json"
LOCALITIES_MANIFEST = MANIFESTS / "acquire" / "ibge_localities.json"
URBAN_MANIFEST = MANIFESTS / "acquire" / "ibge_urbanized_areas.json"
TSE_MANIFEST = MANIFESTS / "acquire" / "tse_polling_places.json"


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
            _load(POLLING_PLACES_MANIFEST),
            _load(LOCALITIES_MANIFEST),
            _load(URBAN_MANIFEST),
            _load(TSE_MANIFEST),
            derived_root=dataset("polling_place_types")["derived"],
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
