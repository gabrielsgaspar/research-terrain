"""Rank the repository's research records by how many search terms they mention.

    uv run python .claude/skills/campaign-design/scripts/novelty_scan.py TERM [TERM ...]
        [--top 25] [--lines 3]

Searches ideas, lessons, decisions, questions, explore-run summaries,
campaigns, literature notes and refs.bib, issue drafts and explore scripts.
Matching is case-insensitive and accent-insensitive; a term with spaces
matches as a phrase. Prints, best first, each file with the terms it matched
and its first matching lines. Reads only files; no network.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GLOBS = (
    "research/ideas/*.md",
    "research/lessons.md",
    "research/decisions/*.md",
    "research/questions.md",
    "research/explore-runs/*/*.md",
    "research/campaigns/*/*.md",
    "research/references/*.md",
    "research/references/refs.bib",
    "harness/issue-drafts/*.md",
    "harness/LESSONS.md",
    "explore/*.py",
)


def fold(text: str) -> str:
    """Lowercase without accents, so 'prefeito' matches 'Prefeito' and 'eleição' 'eleicao'."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def scan(root: Path, terms: list[str], top: int, lines: int) -> list[str]:
    patterns = {t: re.compile(re.escape(fold(t))) for t in terms}
    hits: list[tuple[int, int, str, list[str], list[str]]] = []
    for glob in GLOBS:
        for path in sorted(root.glob(glob)):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            folded = fold(text)
            found = [t for t, p in patterns.items() if p.search(folded)]
            if not found:
                continue
            count = sum(len(p.findall(folded)) for p in patterns.values())
            shown = []
            for n, line in enumerate(text.splitlines(), 1):
                if any(p.search(fold(line)) for p in patterns.values()):
                    shown.append(f"    {n}: {line.strip()[:160]}")
                    if len(shown) >= lines:
                        break
            hits.append((len(found), count, path.relative_to(root).as_posix(), found, shown))
    hits.sort(key=lambda h: (-h[0], -h[1], h[2]))
    out = []
    for n_terms, count, rel, found, shown in hits[:top]:
        out.append(f"{rel}  [{n_terms}/{len(terms)} terms, {count} mentions: {', '.join(found)}]")
        out.extend(shown)
    if len(hits) > top:
        out.append(f"... {len(hits) - top} more files; raise --top to see them")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("terms", nargs="+")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--lines", type=int, default=3)
    args = parser.parse_args(argv)
    result = scan(REPO, args.terms, args.top, args.lines)
    print("\n".join(result) if result else "No file mentions any of these terms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
