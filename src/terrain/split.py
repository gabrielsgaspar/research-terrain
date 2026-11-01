"""Stratified exploration/confirmation split of municipalities.

The split is drawn once, before any outcome data exists, with a system random
source (no seed), so it cannot be regenerated or tuned later. The full split is
stored in the sealed bucket; only its SHA-256 is committed, in
`confirm/split.sha256`. See research/decisions/0001-split-sample.md.
"""

from __future__ import annotations

import csv
import hashlib
import io
import random
from collections import defaultdict
from collections.abc import Iterable

EXPLORE = "explore"
CONFIRM = "confirm"


def read_municipalities(text: str) -> list[tuple[str, str]]:
    """Parse a CSV with columns `code_ibge` and `uf` into (code, uf) pairs.

    Codes must be unique 7-digit IBGE codes.
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = {"code_ibge", "uf"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows, seen = [], set()
    for row in reader:
        code, uf = row["code_ibge"].strip(), row["uf"].strip().upper()
        if not (len(code) == 7 and code.isdigit()):
            raise ValueError(f"not a 7-digit IBGE code: {code!r}")
        if code in seen:
            raise ValueError(f"duplicate code: {code}")
        seen.add(code)
        rows.append((code, uf))
    if not rows:
        raise ValueError("no municipalities")
    return rows


def stratified_split(
    rows: Iterable[tuple[str, str]], rng: random.Random, confirm_share: float = 0.5
) -> dict[str, str]:
    """Assign each municipality to EXPLORE or CONFIRM, stratified by state.

    Within each state, round(n * confirm_share) municipalities go to CONFIRM;
    when that is not a whole number, the extra one is decided by `rng`.
    """
    if not 0 < confirm_share < 1:
        raise ValueError("confirm_share must be between 0 and 1")
    by_uf: dict[str, list[str]] = defaultdict(list)
    for code, uf in rows:
        by_uf[uf].append(code)
    assignment: dict[str, str] = {}
    for uf in sorted(by_uf):
        codes = sorted(by_uf[uf])
        rng.shuffle(codes)
        exact = len(codes) * confirm_share
        n_confirm = int(exact) + (1 if rng.random() < exact - int(exact) else 0)
        for i, code in enumerate(codes):
            assignment[code] = CONFIRM if i < n_confirm else EXPLORE
    return assignment


def serialize(assignment: dict[str, str]) -> bytes:
    """Deterministic CSV bytes: sorted by code, LF line endings."""
    lines = ["code_ibge,half"] + [f"{code},{assignment[code]}" for code in sorted(assignment)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
