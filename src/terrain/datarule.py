"""Bounded data rules: the one change to a dataset's rows a repair may make.

Decision 0016. A repair task (decision 0014) may add a data rule, a line of
build code that treats a named class of rows differently (for example: CGU
rows whose recipient municipality is the placeholder 'Sem informação' count
as rows with no municipality), only if:

1. it targets one named class of rows (`name`, and `what` in one line);
2. it covers at most MAX_SHARE (1%) of the step's key value, or of its rows
   when the step has no key value, in every period, and the build proves
   it: `check_rule` measures the share in each period, raises above the
   limit and returns the line the build puts in its manifest notes;
3. it changes no threshold, check or kill rule;
4. it is listed in the close-out report: the tick copies every `data_rule`
   line of the step's manifest into the report's Repairs table.

Anything else (a rule over the limit, a looser check, a new source) blocks
the repair for Gabriel. A build that calls `check_rule` hashes this module
into its output path, like any other `terrain` module it uses.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

MAX_SHARE = 0.01
PREFIX = "data_rule "

NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
PERIOD = re.compile(r"^(\d{4}|\d{4}-\d{2}|all)$")
WHAT_CHARS = 160
_LONG_NUMBER = re.compile(r"\d{11}")


class DataRuleError(ValueError):
    """A data rule that is badly stated or covers more than MAX_SHARE of a period."""


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}"


def check_rule(
    name: str, what: str, unit: str, by_period: Mapping[str, tuple[float, float]]
) -> str:
    """The manifest-notes line of data rule `name`, after checking its bound.

    `unit` is what the share is measured in: the step's key value (a column
    name such as `value_brl`) or `rows`. `by_period` maps each period of the
    output (a year, a year and month, or "all") to (covered, total): how much
    of `unit` the rule's rows hold and how much the period holds in all.
    Raises DataRuleError if the rule is badly stated or if any period's
    share is above MAX_SHARE.
    """
    what = " ".join(str(what).split())
    if not NAME.match(str(name)):
        raise DataRuleError("a data rule's name is a code label like placeholder_recipient")
    if (
        not what
        or len(what) > WHAT_CHARS
        or any(ch in what for ch in ";|")
        or _LONG_NUMBER.search(what)
    ):
        raise DataRuleError(
            f"data rule {name}: say which rows it targets in one line of at most "
            f"{WHAT_CHARS} characters, without ';', '|' or long numbers"
        )
    if not NAME.match(str(unit)):
        raise DataRuleError(f"data rule {name}: the unit is rows or a column name")
    if not by_period:
        raise DataRuleError(f"data rule {name}: measure it in every period of the output")
    shares: list[tuple[str, float, float, float]] = []
    for period in sorted(by_period):
        covered, total = by_period[period]
        if not PERIOD.match(str(period)):
            raise DataRuleError(f"data rule {name}: a period is a year, a year and month or all")
        if not 0 <= covered <= total:
            raise DataRuleError(f"data rule {name}: in {period}, 0 <= covered <= total must hold")
        share = covered / total if total else 0.0
        if share > MAX_SHARE:
            raise DataRuleError(
                f"data rule {name} covers {share:.2%} of {unit} in {period} "
                f"({_num(covered)} of {_num(total)}), above the {MAX_SHARE:.0%} limit "
                "(decision 0016)"
            )
        shares.append((period, share, covered, total))
    top = max(shares, key=lambda s: s[1])
    periods = ", ".join(f"{p} {s:.2%} ({_num(c)} of {_num(t)})" for p, s, c, t in shares)
    return (
        f"{PREFIX}{name}: {what} | weight {unit} | {periods} | "
        f"max {top[1]:.2%} in {top[0]}, limit {MAX_SHARE:.0%}"
    )


def rules_in_notes(notes: object) -> tuple[str, ...]:
    """Every data-rule line in a manifest's notes (joined with '; ' by the builds)."""
    if not isinstance(notes, str):
        return ()
    return tuple(part.strip() for part in notes.split("; ") if part.strip().startswith(PREFIX))
