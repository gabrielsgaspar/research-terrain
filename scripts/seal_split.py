"""Draw and seal an exploration/confirmation split. Run once per split, locally.

The Legal Amazon split (decision 0001, sealed on 2026-11-02):

    uv run python scripts/seal_split.py legal_amazon.csv --out ../split-sealed

`legal_amazon.csv` has columns `code_ibge` and `uf`. It writes, OUTSIDE the
repository, split.csv (-> gs://research-terrain/sealed/split/) and
explore_municipalities.csv (-> gs://research-terrain/data/derived/split/), and
prints the SHA-256 of split.csv, committed as confirm/split.sha256.

The split of the municipalities outside the Legal Amazon (decision 0011):

    uv run python scripts/seal_split.py non_amazon.csv \\
        --non-amazon legal_amazon.csv --out ../split-non-amazon-sealed

`non_amazon.csv` (from the non_amazon_municipalities build) has columns
`code_ibge`, `uf` and `population`; it is stratified by state and population
tercile. `legal_amazon.csv` is only read to check that no code is in both.
It writes split_non_amazon.csv (-> sealed/split/) and
explore_municipalities_non_amazon.csv (-> data/derived/split/), and prints
the SHA-256 of split_non_amazon.csv, committed as
confirm/split_non_amazon.sha256.

Both use a system random source with no seed, so a split can never be
regenerated. Never commit either split file itself.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

from terrain.split import (
    CONFIRM,
    EXPLORE,
    population_strata,
    read_municipalities,
    read_population_municipalities,
    serialize,
    sha256_hex,
    stratified_split,
)

REPO = Path(__file__).resolve().parents[1]


def _refuse(message: str) -> int:
    print(f"Refusing: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("municipalities", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="folder outside the repository")
    parser.add_argument("--confirm-share", type=float, default=0.5)
    parser.add_argument(
        "--non-amazon",
        type=Path,
        metavar="LEGAL_AMAZON_CSV",
        help="draw the split outside the Legal Amazon (decision 0011)",
    )
    args = parser.parse_args(argv)

    out = args.out.resolve()
    if out == REPO or REPO in out.parents:
        return _refuse("--out must be outside the repository.")
    confirm = REPO / "confirm"
    text = args.municipalities.read_text(encoding="utf-8-sig")

    if args.non_amazon is None:
        name, explore_name, hash_file = "split.csv", "explore_municipalities.csv", "split.sha256"
        if (confirm / hash_file).exists():
            return _refuse(f"confirm/{hash_file} exists; the split is sealed.")
        strata = read_municipalities(text)
    else:
        name, explore_name = "split_non_amazon.csv", "explore_municipalities_non_amazon.csv"
        hash_file = "split_non_amazon.sha256"
        if not (confirm / "split.sha256").exists():
            return _refuse("the Legal Amazon split (confirm/split.sha256) must be sealed first.")
        if (confirm / hash_file).exists():
            return _refuse(f"confirm/{hash_file} exists; the split is sealed.")
        rows = read_population_municipalities(text)
        amazon = {
            code for code, _ in read_municipalities(args.non_amazon.read_text(encoding="utf-8-sig"))
        }
        both = sorted({code for code, _, _ in rows} & amazon)
        if both:
            return _refuse(f"{len(both)} codes are also in the Legal Amazon list: {both[:10]}")
        strata = population_strata(rows)

    assignment = stratified_split(strata, random.SystemRandom(), args.confirm_share)
    data = serialize(assignment)

    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data)
    explore = [code for code in sorted(assignment) if assignment[code] == EXPLORE]
    (out / explore_name).write_text("code_ibge\n" + "\n".join(explore) + "\n", encoding="utf-8")

    halves = Counter((stratum, assignment[code]) for code, stratum in strata)
    for stratum in sorted({s for _, s in strata}):
        print(f"{stratum}: {halves[stratum, EXPLORE]} explore, {halves[stratum, CONFIRM]} confirm")
    n_confirm = len(assignment) - len(explore)
    print(f"{len(assignment)} municipalities: {len(explore)} explore, {n_confirm} confirm")
    print(f"Wrote {out / name} and {out / explore_name}")
    print(sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
