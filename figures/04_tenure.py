"""Figure 4: indigenous lands, settlements, undesignated forest. Logic: terrain.figures."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from terrain.figures import fetch, read_layers, tenure
from terrain.storage import GCSStore

MANIFESTS = Path(__file__).resolve().parents[1] / "data" / "manifests" / "build"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    manifest = json.loads((MANIFESTS / "figure_layers.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        path = fetch(store, manifest, "figure_layers.parquet", Path(tmp))
        tenure(read_layers(path), out)


if __name__ == "__main__":
    main()
