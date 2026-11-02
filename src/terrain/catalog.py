"""Read `data/catalog.yaml`. Every script gets dataset paths and URLs from here."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "data" / "catalog.yaml"


def load_catalog(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    """All dataset entries in the catalog."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(doc["datasets"])


def dataset(name: str, path: Path = CATALOG_PATH) -> dict[str, Any]:
    """The entry called `name`; raises `KeyError` if there is none."""
    for entry in load_catalog(path):
        if entry.get("name") == name:
            return entry
    raise KeyError(name)
