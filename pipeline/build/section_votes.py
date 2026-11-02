"""Build the section votes of the Legal Amazon, linked to candidacies.

Contract: data/contracts/section_votes.md. Logic: terrain.builds.section_votes.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.section_votes import BuildError, build
from terrain.catalog import REPO, dataset
from terrain.manifest import write_manifest
from terrain.storage import GCSStore

MANIFESTS = REPO / "data" / "manifests"
SECTIONS_MANIFEST = MANIFESTS / "acquire" / "tse_votes_by_section.json"
RESULTS_MANIFEST = MANIFESTS / "build" / "tse_results.json"
MUNICIPALITIES_MANIFEST = MANIFESTS / "build" / "municipalities.json"
CANDIDATES_MANIFEST = MANIFESTS / "build" / "tse_candidates.json"


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
            _load(SECTIONS_MANIFEST),
            _load(RESULTS_MANIFEST),
            _load(MUNICIPALITIES_MANIFEST),
            derived_root=dataset("section_votes")["derived"],
            candidates_manifest=_load(CANDIDATES_MANIFEST),
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
