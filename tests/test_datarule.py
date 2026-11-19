"""terrain.datarule: a repair's data rule covers at most 1% of every period (decision 0016)."""

from __future__ import annotations

import pytest

from terrain.datarule import MAX_SHARE, DataRuleError, check_rule, rules_in_notes

WHAT = "CGU rows whose recipient municipality is a placeholder count as no municipality"


def test_a_bounded_rule_returns_its_notes_line():
    line = check_rule(
        "placeholder_recipient",
        WHAT,
        "value_brl",
        {"2025": (0.0, 2_000_000.0), "2026": (14_999.5, 1_500_000.0)},
    )
    assert line == (
        f"data_rule placeholder_recipient: {WHAT} | weight value_brl | "
        "2025 0.00% (0 of 2000000), 2026 1.00% (14999.50 of 1500000) | "
        "max 1.00% in 2026, limit 1%"
    )
    # the builds join notes with "; ": the close-out reads the rule back
    notes = "; ".join(["dropped_rows=3", line, "rows_without_payment_month=0"])
    assert rules_in_notes(notes) == (line,)
    assert rules_in_notes("dropped_rows=3") == () and rules_in_notes(None) == ()


def test_a_rule_over_the_limit_in_any_period_stops_the_build():
    with pytest.raises(DataRuleError, match=r"covers 1\.01% of rows in 2026 .*above the 1% limit"):
        check_rule("placeholder_recipient", WHAT, "rows", {"2025": (0, 100), "2026": (101, 10_000)})
    assert MAX_SHARE == 0.01


@pytest.mark.parametrize(
    "name, what, unit, by_period",
    [
        ("Placeholder", WHAT, "rows", {"2026": (1, 100)}),  # not a code label
        ("placeholder", "", "rows", {"2026": (1, 100)}),  # no class of rows named
        ("placeholder", "rows; and more", "rows", {"2026": (1, 100)}),
        ("placeholder", "rows | more", "rows", {"2026": (1, 100)}),
        ("placeholder", "CPF 12345678901 rows", "rows", {"2026": (1, 100)}),
        ("placeholder", "x" * 161, "rows", {"2026": (1, 100)}),
        ("placeholder", WHAT, "reais paid", {"2026": (1, 100)}),
        ("placeholder", WHAT, "rows", {}),  # never measured
        ("placeholder", WHAT, "rows", {"Belém": (1, 100)}),
        ("placeholder", WHAT, "rows", {"2026": (5, 1)}),
        ("placeholder", WHAT, "rows", {"2026": (-1, 100)}),
    ],
)
def test_a_badly_stated_rule_is_refused(name, what, unit, by_period):
    with pytest.raises(DataRuleError):
        check_rule(name, what, unit, by_period)


def test_an_empty_period_counts_as_zero():
    line = check_rule("placeholder", WHAT, "rows", {"2026": (0, 0)})
    assert "2026 0.00% (0 of 0)" in line
