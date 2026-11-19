"""Print the row counts of the check a failed data-pipeline run stopped on.

The `data-pipeline` workflow runs this fixed script only after a failed
step: `uv run python scripts/profile_failure.py <profile.json>`. The file is
the one the build wrote with `terrain.profile.write_profile`. The script
prints counts of rows per period and category and nothing else (never a
value or an identifier), between `profile: begin` and `profile: end`, for
the campaign tick to copy into a repair task (decision 0016). With no file,
or a file that fails the checks in `terrain.profile`, it prints one line
saying so. It always exits 0: the job has failed already.
"""

from __future__ import annotations

import sys
from pathlib import Path

from terrain.profile import render_file


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) == 2 else Path("")
    print("\n".join(render_file(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
