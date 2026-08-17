#!/usr/bin/env python3
"""Ban ASCII banner comments.

A comment that is a horizontal rule - `# --- sending ---------`,
`// ==== internals ====` - is decoration, not information. It signposts a
section that the code's own structure (a class, a function, a well-named module)
should already mark, it drifts out of date the moment the section moves, and the
format itself reads as machine-generated. Plain "why" comments are welcome; a
rule drawn in dashes is not.

Detected: a line whose first non-whitespace is a comment marker (`#` or `//`)
followed by a run of three or more rule characters (`- = ~ *`). Anchoring to a
line-leading marker is what keeps a dashed string literal from tripping it - a
banner always sits on its own line.

The fix is to delete the line. If a section genuinely needs a heading, a short
plain comment (`# Sending`) says the same thing without the rule.

Usage::

    python scripts/check_comments.py            # report, exit 1 if any found

Exits 1 when a banner is found, 0 when clean.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml"}

SKIP_DIRS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "node_modules",
    "htmlcov",
    "dist",
    "build",
    "site",
    ".claude",
}

# A line-leading comment marker, then optional space, then a rule of one repeated
# character (`---`, `====`, `~~~`, `***`). `\1{2,}` ties the run to a single
# character, so `-*-` (a coding cookie) and prose with a lone dash do not match.
BANNER = re.compile(r"^\s*(?:#|//)\s*([-=~*])\1{2,}")


def _is_nested_checkout(directory: Path) -> bool:
    """Another checkout — a worktree holds a `.git` file, a clone a `.git` directory.

    Detected rather than named, for the reasons `check_backticks.is_nested_checkout`
    spells out: a worktree can be placed anywhere, and a directory merely called
    `worktrees` is part of this branch.
    """
    return (directory / ".git").exists()


def _iter_files(root: Path) -> Iterator[Path]:
    for directory, subdirectories, filenames in os.walk(root):
        here = Path(directory)
        # Pruned in place, which is what `os.walk` reads to decide where to descend -
        # `rglob` filtered after descending, ~7 minutes on a tree with worktrees (#635).
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in SKIP_DIRS and not _is_nested_checkout(here / name)
        ]
        for name in sorted(filenames):
            path = here / name
            if path.suffix in SUFFIXES:
                yield path


def main() -> int:
    found = False
    for path in sorted(_iter_files(REPO_ROOT)):
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if BANNER.match(line):
                found = True
                rel = path.relative_to(REPO_ROOT)
                print(f"{rel}:{lineno}: banner comment - delete the rule. {line.strip()[:60]}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
