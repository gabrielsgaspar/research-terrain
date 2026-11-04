"""Figure 5: land without voters. Logic: terrain.figures. Contract: figures/README.md."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import polars as pl

from terrain.figures import fetch, land_without_voters, read_layers
from terrain.storage import GCSStore

MANIFESTS = Path(__file__).resolve().parents[1] / "data" / "manifests" / "build"
COLUMNS = ["x_km", "y_km", "pop_2022", "share_undesignated_2024"]


def _load(name: str) -> dict:
    return json.loads((MANIFESTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    layers_manifest = _load("figure_layers")
    cells_manifest = _load("grid_cells")
    with tempfile.TemporaryDirectory() as tmp:
        layers = read_layers(fetch(store, layers_manifest, "figure_layers.parquet", Path(tmp)))
        cells_path = fetch(store, cells_manifest, "grid_cells.parquet", Path(tmp))
        cells = pl.read_parquet(cells_path, columns=COLUMNS)
        land_without_voters(layers, cells, out)


if __name__ == "__main__":
    main()
