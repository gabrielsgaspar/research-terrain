import json
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import box, shape

from terrain.grid import ALBERS, centre_lonlat, km_to_lonlat, parse_name, to_albers_km

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "fixtures" / "ibge" / "BR1KM_2022_sample.geojson"


def cells() -> list[tuple[str, object]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [(f["properties"]["nome_1KM"], shape(f["geometry"])) for f in data["features"]]


def test_parse_name():
    assert parse_name("1KME4717N11118") == (4717, 11118)


@pytest.mark.parametrize(
    "name",
    ["", "1KME4717", "1KME4717N", "200ME47210N111032", "1KME4717N11118\n", "x1KME1N2", "1kme1n2"],
)
def test_malformed_names_raise(name):
    with pytest.raises(ValueError, match="not a 1 km cell name"):
        parse_name(name)


def test_the_projection_is_ibges_albers():
    assert "+proj=aea" in ALBERS and "+lon_0=-54" in ALBERS and "+ellps=GRS80" in ALBERS


def test_every_fixture_centre_lies_inside_its_cell_and_the_cell_matches_its_name():
    found = cells()
    assert len(found) == 263
    for name, polygon in found:
        x, y = parse_name(name)
        lon, lat = centre_lonlat(x, y)
        assert polygon.contains(shapely.Point(float(lon), float(lat))), name
        assert shapely.hausdorff_distance(to_albers_km(polygon), box(x, y, x + 1, y + 1)) < 0.005


def test_centre_lonlat_is_vectorised_and_inverts_to_albers():
    x = np.array([4717, 4718])
    y = np.array([11118, 11107])
    lon, lat = centre_lonlat(x, y)
    assert lon.shape == (2,) and lat.shape == (2,)
    back = to_albers_km(shapely.points(lon, lat))
    assert shapely.get_x(back) == pytest.approx(x + 0.5, abs=1e-6)
    assert shapely.get_y(back) == pytest.approx(y + 0.5, abs=1e-6)
    lon2, lat2 = km_to_lonlat(x + 0.5, y + 0.5)
    assert lon2 == pytest.approx(lon) and lat2 == pytest.approx(lat)
