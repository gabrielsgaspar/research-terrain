"""Outcomes per polling place, election and year, split by half (exploration derived, rest sealed).

Contract: data/contracts/place_outcomes.md. Logic: terrain.builds.place_outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.builds.place_outcomes import BuildError, build
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
    outcomes = dataset("place_outcomes")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = build(
            store,
            _load("build", "polling_places"),
            _load("build", "school_polling_match"),
            _load("acquire", "inep_schools"),
            _load("acquire", "ibge_boundaries_2024"),
            _load("acquire", "viirs_annual"),
            _load("acquire", "mapbiomas_coverage_national"),
            dataset("viirs_annual")["earthengine"],
            dataset("mapbiomas_coverage_national")["earthengine"],
            derived_root=outcomes["derived"],
            sealed_root=outcomes["sealed"],
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
