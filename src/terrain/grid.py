"""IBGE's statistical grid: cell names and the Albers equal-area projection.

A 1 km cell is named `1KME<e>N<n>`: the square whose lower-left corner is at easting
`e` km and northing `n` km in IBGE's Albers projection. Its centre is (e + 0.5, n + 0.5).
Longitude and latitude are SIRGAS 2000 degrees (GRS80, so no datum shift from Albers).
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any

import numpy as np
import shapely
from pyproj import Transformer

ALBERS = (
    "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 "
    "+y_0=10000000 +ellps=GRS80 +units=m +no_defs"
)
LONLAT = "+proj=longlat +ellps=GRS80 +no_defs"
NAME_PATTERN = r"^1KME([0-9]+)N([0-9]+)$"
_NAME = re.compile(NAME_PATTERN)


def parse_name(name: str) -> tuple[int, int]:
    """`(x_km, y_km)` of a 1 km cell name; `ValueError` for anything else."""
    found = _NAME.fullmatch(name) if isinstance(name, str) else None
    if found is None:
        raise ValueError(f"not a 1 km cell name: {name!r}")
    return int(found.group(1)), int(found.group(2))


@cache
def _to_lonlat() -> Transformer:
    return Transformer.from_crs(ALBERS, LONLAT, always_xy=True)


@cache
def _to_albers() -> Transformer:
    return Transformer.from_crs(LONLAT, ALBERS, always_xy=True)


def km_to_lonlat(x_km: Any, y_km: Any) -> tuple[np.ndarray, np.ndarray]:
    """Albers km (any point) to longitude and latitude in degrees."""
    x = np.asarray(x_km, dtype=float) * 1000.0
    y = np.asarray(y_km, dtype=float) * 1000.0
    lon, lat = _to_lonlat().transform(x, y)
    return np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)


def centre_lonlat(x_km: Any, y_km: Any) -> tuple[np.ndarray, np.ndarray]:
    """Centre of the cell with lower-left corner (`x_km`, `y_km`), in degrees."""
    return km_to_lonlat(np.asarray(x_km, dtype=float) + 0.5, np.asarray(y_km, dtype=float) + 0.5)


def _coords_to_albers_km(coords: np.ndarray) -> np.ndarray:
    x, y = _to_albers().transform(coords[:, 0], coords[:, 1])
    return np.column_stack([np.asarray(x) / 1000.0, np.asarray(y) / 1000.0])


def to_albers_km(geometries: Any) -> Any:
    """Shapely geometries in degrees (one, or an array) to Albers km."""
    return shapely.transform(geometries, _coords_to_albers_km)
