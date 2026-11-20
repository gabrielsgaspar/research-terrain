"""Party numbers across elections (terrain.parties)."""

import pytest

from terrain import parties


def test_a_renamed_party_keeps_its_number():
    assert parties.successor("15", 2016, 2024) == "15"  # PMDB to MDB
    assert parties.successor("22", 2016, 2024) == "22"  # PR to PL


@pytest.mark.parametrize(
    ("number", "start", "end", "expected"),
    [
        ("31", 2016, 2020, "19"),  # PHS into Podemos (2019)
        ("44", 2016, 2020, "51"),  # PRP into Patriota (2019)
        ("44", 2016, 2024, "25"),  # ... and Patriota into PRD (2023)
        ("25", 2018, 2022, "44"),  # DEM into União Brasil (2022), in time for the election
        ("25", 2020, 2024, "44"),  # 25 is PRD in 2024, but DEM's 2020 number goes to 44
        ("14", 2020, 2024, "25"),  # PTB into PRD (2023)
        ("17", 2018, 2022, "44"),
        ("19", 2022, 2026, "20"),  # Podemos takes PSC's number when it absorbs PSC (2023)
        ("20", 2022, 2026, "20"),  # ... and PSC's 20 stays
        ("31", 2016, 2024, "20"),  # PHS into Podemos, then Podemos to 20
        ("19", 2018, 2022, "19"),
        ("56", 2004, 2008, "22"),  # PRONA into PR
        ("18", 2000, 2004, "22"),  # PST into PL; 18 is REDE from 2015
        ("18", 2016, 2020, "18"),
    ],
)
def test_successor_follows_mergers(number, start, end, expected):
    assert parties.successor(number, start, end) == expected


def test_a_merger_year_belongs_to_the_later_election():
    assert parties.successor("25", 2022, 2026) == "25"  # already União Brasil's era: PRD
    assert parties.successor("25", 2018, 2021) == "25"
    assert parties.successor("10", 2020, 2020) == "10"
    with pytest.raises(ValueError, match="before"):
        parties.successor("10", 2024, 2020)


def test_federation_groups():
    pairs = [("13", "2"), ("65", "2"), ("43", " 2 "), ("10", "-1"), ("20", None), (None, "3")]
    pairs += [("30", ""), ("13", "2")]
    groups = parties.federation_groups(pairs)
    assert groups == {"13": "F2", "65": "F2", "43": "F2"}
    assert parties.group_of("13", groups) == "F2"
    assert parties.group_of("10", groups) == "P10"


def test_a_party_in_two_federations_stops():
    with pytest.raises(parties.FederationError, match="two federations"):
        parties.federation_groups([("13", "2"), ("13", "3")])
