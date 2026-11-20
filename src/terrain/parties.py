"""Party numbers across elections: mergers, and federations within one election.

TSE files name a party by its ballot number (`nr_partido`). A rename keeps the number (PMDB
to MDB, PR to PL, PRB to Republicanos), so nothing is needed for it. A merger does not: the
absorbed party's number disappears, and a number can come back later as another party (25
was DEM until 2022 and is PRD from 2023; 44 was PRP until 2019 and is União Brasil from
2022). The surviving party can also take the absorbed one's number: Podemos (19) became 20
when it absorbed PSC (20) in 2023. `successor` follows a party number from one election to a
later one through the mergers in `MERGERS`.

A federation (from 2022) is a group of parties that runs as one for four years.
`federation_groups` reads the (party, federation) pairs of one election into the group each
party counts with.

Used by the amendments panel (party vote shares at t0 and t1) and the mayoral incumbency
panel (the party at e+4, the party at e-4 and the bench at e-2). Party numbers are not
personal data.
"""

from __future__ import annotations

from collections.abc import Iterable

# (year the TSE approved the merger, absorbed or merged number, number afterwards). A merger
# approved in year Y applies between an election before Y and one in Y or later; the
# October elections of a merger year already use the new number (União Brasil ran in 2022).
MERGERS: tuple[tuple[int, str, str], ...] = (
    (2003, "18", "22"),  # PST into PL
    (2003, "30", "22"),  # PGT into PL
    (2003, "41", "14"),  # PSD (founded 1987) into PTB
    (2006, "56", "22"),  # PRONA and PL form PR (22), approved after the 2006 election
    (2007, "26", "14"),  # PAN into PTB
    (2019, "31", "19"),  # PHS into Podemos
    (2019, "44", "51"),  # PRP into Patriota
    (2019, "54", "65"),  # PPL into PCdoB
    (2022, "25", "44"),  # DEM and PSL form União Brasil (44)
    (2022, "17", "44"),
    (2023, "90", "77"),  # PROS into Solidariedade
    (2023, "14", "25"),  # PTB and Patriota form PRD (25)
    (2023, "51", "25"),
    (2023, "19", "20"),  # PSC into Podemos, which takes PSC's number (20)
)


def _by_year() -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for year, old, new in MERGERS:
        out.setdefault(year, {})[old] = new
    return out


_MERGERS_BY_YEAR = _by_year()


def successor(number: str, from_year: int, to_year: int) -> str:
    """The number of party `number` (of the election in `from_year`) at the election in
    `to_year`: the mergers approved in from_year+1 .. to_year, applied year by year.

    The mergers of one year apply at once, so a number freed in a year and given to another
    party in a later year is not confused (25: DEM to União Brasil in 2022, PTB to PRD in
    2023).
    """
    if to_year < from_year:
        raise ValueError("to_year is before from_year")
    current = str(number)
    for year in sorted(_MERGERS_BY_YEAR):
        if from_year < year <= to_year:
            current = _MERGERS_BY_YEAR[year].get(current, current)
    return current


class FederationError(ValueError):
    """A party is in two federations of one election."""


def federation_groups(pairs: Iterable[tuple[str | None, str | None]]) -> dict[str, str]:
    """The group each party counts with in one election: `F<federation>` for the members of
    a federation, from (party, federation) pairs. Pairs with an empty, null or `-1`
    federation, or no party, are not federations. Parties not in the result count alone
    (`group_of`). Stops if a party is in two federations.
    """
    groups: dict[str, str] = {}
    for party, federation in pairs:
        if party is None or federation is None:
            continue
        party, federation = str(party).strip(), str(federation).strip()
        if not party or federation in ("", "-1"):
            continue
        group = "F" + federation
        if groups.setdefault(party, group) != group:
            raise FederationError("a party is in two federations of one election")
    return groups


def group_of(party: str, groups: dict[str, str]) -> str:
    """The group of `party`: its federation's (`federation_groups`), or `P<party>`."""
    return groups.get(party, "P" + party)
