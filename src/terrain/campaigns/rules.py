"""Apply a step's kill rules to the `results.json` of an explore run.

A rule is met when `results[field] <op> value` is true; a met rule kills the
step. A field that is missing, or not a number where the rule compares
numbers, makes the verdict `unreadable`: that never counts as a pass, it
stops the step and asks the owner. A met rule wins over an unreadable one:
either way the step does not go on.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

from terrain.campaigns.spec import KillRule

_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}
_MISSING = object()


@dataclass(frozen=True)
class RuleResult:
    rule: KillRule
    observed: Any  # the value read, or None if unreadable
    met: bool | None  # None: could not be applied


@dataclass(frozen=True)
class Verdict:
    outcome: str  # "killed", "survived" or "unreadable"
    results: tuple[RuleResult, ...]

    def lines(self) -> list[str]:
        out = []
        for r in self.results:
            if r.met is None:
                state = "could not be applied (field missing or not a number)"
            else:
                state = "met: the step is killed" if r.met else "not met"
            shown = "missing" if r.met is None else repr(r.observed)
            out.append(
                f"{r.rule.id} ({r.rule.says}): `{r.rule.field} {r.rule.op} {r.rule.value!r}`, "
                f"observed {shown}, {state}"
            )
        return out


def lookup(results: Any, dotted: str) -> Any:
    """`results['a']['b']` for 'a.b'; list items by index ('a.0'). _MISSING if absent."""
    node = results
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _is_number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def apply_rule(rule: KillRule, results: Any) -> RuleResult:
    value = lookup(results, rule.field)
    if value is _MISSING:
        return RuleResult(rule, None, None)
    numeric = rule.op in {"<", "<=", ">", ">="} or _is_number(rule.value)
    if numeric and not _is_number(value):
        return RuleResult(rule, None, None)
    if value != value:  # NaN never passes or fails a rule
        return RuleResult(rule, None, None)
    return RuleResult(rule, value, bool(_OPS[rule.op](value, rule.value)))


def evaluate(rules: tuple[KillRule, ...], results: Any) -> Verdict:
    applied = tuple(apply_rule(r, results) for r in rules)
    if any(r.met for r in applied):
        return Verdict("killed", applied)
    if any(r.met is None for r in applied):
        return Verdict("unreadable", applied)
    return Verdict("survived", applied)
