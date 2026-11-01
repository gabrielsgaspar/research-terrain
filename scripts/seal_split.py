"""Draw and seal the exploration/confirmation split. Run once, locally.

    uv run python scripts/seal_split.py municipalities.csv --out ../split-sealed

`municipalities.csv` needs columns `code_ibge` and `uf` (the Legal Amazon
list from IBGE). The script uses a system random source with no seed, so the
split can never be regenerated. It writes, OUTSIDE the repository:

    split.csv                     the full split  -> upload to the sealed bucket
    explore_municipalities.csv    exploration half -> upload to data/derived/split/

and prints the SHA-256 of split.csv, which you commit as confirm/split.sha256.
Never commit split.csv itself.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from terrain.split import EXPLORE, read_municipalities, serialize, sha256_hex, stratified_split

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("municipalities", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="folder outside the repository")
    parser.add_argument("--confirm-share", type=float, default=0.5)
    args = parser.parse_args()

    out = args.out.resolve()
    if out == REPO or REPO in out.parents:
        print("Refusing: --out must be outside the repository.", file=sys.stderr)
        return 1
    if (REPO / "confirm" / "split.sha256").exists():
        print("Refusing: confirm/split.sha256 exists; the split is sealed.", file=sys.stderr)
        return 1

    rows = read_municipalities(args.municipalities.read_text(encoding="utf-8-sig"))
    assignment = stratified_split(rows, random.SystemRandom(), args.confirm_share)
    data = serialize(assignment)

    out.mkdir(parents=True, exist_ok=True)
    (out / "split.csv").write_bytes(data)
    explore = [code for code in sorted(assignment) if assignment[code] == EXPLORE]
    (out / "explore_municipalities.csv").write_text(
        "code_ibge\n" + "\n".join(explore) + "\n", encoding="utf-8"
    )
    n_confirm = len(assignment) - len(explore)
    print(f"{len(assignment)} municipalities: {len(explore)} explore, {n_confirm} confirm")
    print(f"Wrote {out / 'split.csv'} and {out / 'explore_municipalities.csv'}")
    print(sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
