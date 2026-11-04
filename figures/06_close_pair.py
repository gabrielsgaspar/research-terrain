"""Figure 6: one close pair, the winner's and the loser's strongholds over their exposure.

Logic: terrain.figures. Contract: figures/README.md. Prints one JSON line.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from terrain.figures import close_pair
from terrain.storage import GCSStore

MANIFESTS = Path(__file__).resolve().parents[1] / "data" / "manifests" / "build"
NAMES = (
    "tse_results",
    "section_votes",
    "polling_place_tenure",
    "polling_places",
    "grid_cells",
    "municipalities",
    "figure_layers",
)


def _load(name: str) -> dict:
    return json.loads((MANIFESTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    record = close_pair(store, {name: _load(name) for name in NAMES}, out)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
