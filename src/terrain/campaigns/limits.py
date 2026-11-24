"""The tick's operational limits, read from `ops/limits.yaml` (decision 0020).

The file is the plumbing lane's one data file: exactly the keys of `BOUNDS`,
each a whole number inside its bound. The bounds are here, in owned code, and
`tests/test_ops_limits.py` checks the real file against them.

`load` reads the file at the start of every tick (`terrain.campaigns.github`
builds the tick's `Snapshot` with it). A missing file, a missing or unknown
key, a value that is not a whole number, or a value outside its bound raises
`LimitsError`, naming the key and its bound, and the tick stops. There is no
default to fall back to.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

PATH = "ops/limits.yaml"
# This checkout's root: the tick runs from a checkout of main, so this is the file on main.
REPO_ROOT = Path(__file__).resolve().parents[3]

# key -> (minimum, maximum), both included. Decision 0020, point 3; the last key is
# amended there (2026-11-24) from `build_restarts_per_block`.
BOUNDS: dict[str, tuple[int, int]] = {
    "plan_timeout_hours": (1, 6),
    "build_timeout_hours": (6, 24),
    "run_appear_timeout_hours": (1, 6),
    "record_timeout_hours": (1, 6),
    "ideation_timeout_hours": (1, 6),
    "fork_plan_timeout_hours": (2, 12),
    "max_auto_retries": (0, 3),
    "max_auto_build_restarts_per_step": (0, 2),
}


class LimitsError(ValueError):
    """ops/limits.yaml cannot be used; the tick stops."""


@dataclass(frozen=True)
class Limits:
    """The values in ops/limits.yaml, checked against `BOUNDS`."""

    plan_timeout_hours: int
    build_timeout_hours: int
    run_appear_timeout_hours: int
    record_timeout_hours: int
    ideation_timeout_hours: int
    fork_plan_timeout_hours: int
    max_auto_retries: int
    max_auto_build_restarts_per_step: int

    def __post_init__(self) -> None:
        for f in fields(self):
            check(f.name, getattr(self, f.name))

    @property
    def plan_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.plan_timeout_hours)

    @property
    def build_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.build_timeout_hours)

    @property
    def run_appear_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.run_appear_timeout_hours)

    @property
    def record_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.record_timeout_hours)

    @property
    def ideation_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.ideation_timeout_hours)

    @property
    def fork_plan_timeout(self) -> dt.timedelta:
        return dt.timedelta(hours=self.fork_plan_timeout_hours)


def bound(key: str) -> str:
    """`plan_timeout_hours` -> "1 to 6"."""
    low, high = BOUNDS[key]
    return f"{low} to {high}"


def check(key: str, value: object) -> int:
    """`value` for `key` if it is a whole number inside the key's bound; else LimitsError."""
    if key not in BOUNDS:
        known = ", ".join(BOUNDS)
        raise LimitsError(f"{PATH}: unknown key {key!r}; the only keys are {known}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitsError(
            f"{PATH}: {key} is {value!r}, not a whole number; it must be {bound(key)}"
        )
    low, high = BOUNDS[key]
    if not low <= value <= high:
        raise LimitsError(f"{PATH}: {key} is {value}, outside its bound {bound(key)}")
    return value


class _UniqueKeys(yaml.SafeLoader):
    """A safe loader that refuses a key written twice (PyYAML keeps the last)."""


def _mapping(loader: _UniqueKeys, node: yaml.MappingNode) -> dict:
    seen: set[object] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise LimitsError(f"{PATH}: {key} is written twice; it must be {bound_or_any(key)}")
        seen.add(key)
    return loader.construct_mapping(node)


def bound_or_any(key: object) -> str:
    return bound(key) if isinstance(key, str) and key in BOUNDS else "one of " + ", ".join(BOUNDS)


_UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(text: str) -> Limits:
    """The limits in `text` (the file's content), or LimitsError."""
    try:
        data = yaml.load(text, Loader=_UniqueKeys)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as exc:
        every = ", ".join(f"{k} ({bound(k)})" for k in BOUNDS)
        raise LimitsError(f"{PATH} is not valid YAML ({exc}); it must hold {every}") from exc
    if not isinstance(data, dict):
        every = ", ".join(f"{k} ({bound(k)})" for k in BOUNDS)
        raise LimitsError(f"{PATH} must be a mapping of {every}")
    for key in data:
        if key not in BOUNDS:
            check(str(key), None)  # raises: unknown key
    for key in BOUNDS:
        if key not in data:
            raise LimitsError(f"{PATH}: {key} is missing; it must be {bound(key)}")
    return Limits(**{key: check(key, data[key]) for key in BOUNDS})


def load(root: Path = REPO_ROOT) -> Limits:
    """The limits in `root`/ops/limits.yaml, or LimitsError."""
    path = root / PATH
    if not path.is_file():
        every = ", ".join(f"{k} ({bound(k)})" for k in BOUNDS)
        raise LimitsError(f"{PATH} is missing; the tick needs every key: {every}")
    return parse(path.read_text(encoding="utf-8"))
