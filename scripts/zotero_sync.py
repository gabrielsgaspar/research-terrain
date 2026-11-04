"""Write refs.bib and note stubs from the curated Zotero group library.

    uv run python scripts/zotero_sync.py [--references-dir research/references]

Reads ZOTERO_READ_KEY and ZOTERO_GROUP_ID from the environment. Prints a JSON
report. Never prints the key, the group id or a URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from terrain.zotero import fetch_items, sync


def get(url: str, headers: dict[str, str]) -> tuple[dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310
        return dict(resp.headers), resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--references-dir", type=Path, default=Path("research/references"))
    args = parser.parse_args()

    missing = [v for v in ("ZOTERO_READ_KEY", "ZOTERO_GROUP_ID") if not os.environ.get(v)]
    if missing:
        print("missing environment variable: " + ", ".join(missing), file=sys.stderr)
        return 2
    items = fetch_items(get, os.environ["ZOTERO_GROUP_ID"], os.environ["ZOTERO_READ_KEY"])
    report = sync(items, args.references_dir)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
