"""Figure 2: polling-place density. Logic: terrain.figures. Contract: figures/README.md."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import polars as pl

from terrain.figures import YEARS, fetch, polling_places, project_points, read_layers
from terrain.storage import GCSStore

MANIFESTS = Path(__file__).resolve().parents[1] / "data" / "manifests" / "build"


def _load(name: str) -> dict:
    return json.loads((MANIFESTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    layers_manifest = _load("figure_layers")
    places_manifest = _load("polling_places")
    with tempfile.TemporaryDirectory() as tmp:
        layers = read_layers(fetch(store, layers_manifest, "figure_layers.parquet", Path(tmp)))
        points = {}
        for year in YEARS:
            path = fetch(store, places_manifest, f"polling_places_{year}.parquet", Path(tmp))
            df = pl.read_parquet(path, columns=["lat", "long"])
            points[year] = project_points(df["lat"], df["long"])
        polling_places(layers, points, out)


if __name__ == "__main__":
    main()
