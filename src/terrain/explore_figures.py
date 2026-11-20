"""PNG figures an explore run may leave next to its record.

Standard library only, so the explore-run record job can import it with the
runner's python before it installs the project. An explore run may write at
most 8 PNGs, each at most 400 KB, in ``<out-dir>/figures/``. The record job
copies them to ``research/explore-runs/<idea>/<run-id>/figures/`` and links
them from the run's ``.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

FIGURES_MAX_COUNT = 8
FIGURE_MAX_BYTES = 400_000  # 400 KB, the same decimal KB as the summary limit
_PNG = b"\x89PNG\r\n\x1a\n"
_FIGURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,70}\.png")


class ExploreError(Exception):
    """An explore script broke its output contract."""


def is_record_figure(path: str, idea: str, run_id: str) -> bool:
    """True when `path` is one figure of the explore-run record `run_id`."""
    prefix = f"research/explore-runs/{idea}/{run_id}/figures/"
    name = path[len(prefix) :] if path.startswith(prefix) else ""
    return bool(name) and "/" not in name and _FIGURE_NAME.fullmatch(name) is not None


def check_figures(out_dir: Path) -> list[str]:
    """PNG names in `out_dir/figures`, or [] when that folder is absent.

    Anything other than at most 8 PNGs of at most 400 KB each stops the run.
    """
    folder = Path(out_dir) / "figures"
    if not folder.exists():
        return []
    if not folder.is_dir():
        raise ExploreError("figures must be a folder of PNG files")
    entries = sorted(folder.iterdir(), key=lambda p: p.name)
    if any(not p.is_file() for p in entries):
        raise ExploreError("figures must contain only PNG files")
    if len(entries) > FIGURES_MAX_COUNT:
        raise ExploreError(
            f"figures holds {len(entries)} files; an explore run may save at most "
            f"{FIGURES_MAX_COUNT}"
        )
    names: list[str] = []
    for path in entries:
        if _FIGURE_NAME.fullmatch(path.name) is None:
            raise ExploreError(f"figures/{path.name} is not a PNG file name")
        size = path.stat().st_size
        if size > FIGURE_MAX_BYTES:
            raise ExploreError(f"figures/{path.name} is over 400 KB")
        if size < len(_PNG) or path.read_bytes()[: len(_PNG)] != _PNG:
            raise ExploreError(f"figures/{path.name} is not a PNG")
        names.append(path.name)
    return names


def stage_figures(out_dir: Path, record_dir: Path, run_id: str) -> list[str]:
    """Copy `out_dir/figures` next to the run record and link each file from the .md.

    `record_dir` is `research/explore-runs/<idea>/`, which already holds
    `<run_id>.md`. Returns the names copied. No figures leaves the record unchanged.
    """
    names = check_figures(out_dir)
    if not names:
        return []
    if not str(run_id).isdigit():
        raise ExploreError(f"run id must be digits, not {run_id!r}")
    record_dir = Path(record_dir)
    md = record_dir / f"{run_id}.md"
    if not md.is_file():
        raise ExploreError(f"missing {md.name}; write the run record before its figures")
    dest = record_dir / run_id / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        (dest / name).write_bytes((Path(out_dir) / "figures" / name).read_bytes())
    body = md.read_text(encoding="utf-8")
    if not body.endswith("\n"):
        body += "\n"
    links = "\n".join(f"- [{name}]({run_id}/figures/{name})" for name in names)
    md.write_text(f"{body}\n## Figures\n\n{links}\n", encoding="utf-8")
    return names
