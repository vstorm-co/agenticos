"""Refuse a documentation paragraph long enough that nobody finds what is in it.

The site was swept to zero paragraphs over `MAX_WORDS`, and the reason is not
style: a fact appended to a paragraph over months is a fact a reader scans past.
`governance.md` held one carrying ten independent rules about how a trigger's
refusals behave, and `channels.md` eighteen of the same shape.

The fix at the time was to split each at its own seams - a bullet list, a tabbed
block, or an admonition where the fact is one a reader has to have seen *before*
acting. This guard is what keeps the count at zero.

A paragraph opening on a table row, a fence, an indent, an admonition, a list
marker, a heading or a blockquote is not prose and is skipped; so is everything
under `docs/design`, `docs/plans` and `docs/audits`, which are working notes
rather than pages.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_WORDS = 115
DOCS = Path(__file__).resolve().parent.parent / "docs"
WORKING_NOTES = {"design", "plans", "audits"}
NOT_PROSE = ("|", "```", "    ", "\t", "!!!", "???", "-", "*", "=", ">", ":", "#", "<")


def _is_prose(block: str) -> bool:
    return bool(block) and not block.startswith(NOT_PROSE) and not block[0].isdigit()


def offences() -> list[tuple[Path, int, str]]:
    """Every over-long prose paragraph, as (path, word count, its first line)."""
    found: list[tuple[Path, int, str]] = []
    for page in sorted(DOCS.rglob("*.md")):
        if set(page.relative_to(DOCS).parts) & WORKING_NOTES:
            continue
        for block in page.read_text(encoding="utf-8").split("\n\n"):
            if not _is_prose(block):
                continue
            words = len(block.split())
            if words > MAX_WORDS:
                found.append((page, words, block.splitlines()[0]))
    return found


def main() -> int:
    found = offences()
    if not found:
        print(f"No documentation paragraph over {MAX_WORDS} words.")
        return 0
    print(f"Documentation paragraphs over {MAX_WORDS} words ({len(found)}):\n")
    for page, words, opening in found:
        print(f"  {page.relative_to(DOCS.parent)} - {words} words")
        print(f"    {opening[:96]}…\n")
    print("Split each at its own seams: a paragraph per idea, a bullet list where the")
    print("content is a list, or an admonition where a reader must see it before acting.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
