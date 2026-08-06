#!/usr/bin/env python3
"""Find double backticks where they render literally.

Double-backtick spans are reStructuredText. Markdown has no such construct: it
reads the pair as an empty code span followed by plain text, so a README that
meant to show a flag prints two backticks, the flag, and two more. The same is
true of TSDoc, which editors render as Markdown in hover tooltips.

Python files are checked too, docstrings included. They used to be exempt as
Sphinx-flavoured RST, but nothing here builds Sphinx docs — the one place a
docstring is rendered is an editor hover, and editors render Markdown. Sphinx
roles (:class:`Thing`, :mod:`app.agents.spec`) use single backticks and are
untouched either way. Whole lines are scanned, string literals included: a
runtime string holding a double-backtick span ends up in a chat message or a
tool description, which is Markdown territory again.

This file exempts itself — it has to be able to name the pattern it detects — and
skips any nested checkout, because a git worktree holds another branch's files plus
a copy of this script, whose error message spells the pattern out.

Usage::

    python scripts/check_backticks.py            # report, exit 1 if any found
    python scripts/check_backticks.py --fix      # rewrite them to single

Exits 1 when anything is found (so it can gate CI), 0 when clean.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

# A pair of exactly two backticks: three or more is a fence or an escaped span,
# and matching those would rewrite real code blocks into broken ones.
PAIR = re.compile(r"(?<!`)``(?!`)(?P<body>[^`\n]+?)(?<!`)``(?!`)")

MARKDOWN_SUFFIXES = {".md", ".mdx"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
PYTHON_SUFFIXES = {".py"}

# This script's own docstring, regex and messages must be able to spell the
# pattern out - and so must every copy of it. Matched by name rather than by
# absolute path: a copy under a worktree is a different path and was reported as
# three findings on line 170 of a file nobody had edited.
SELF = Path(__file__).name

SKIP_DIRS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "node_modules",
    "htmlcov",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
}


def markdown_prose(text: str) -> Iterator[tuple[int, str]]:
    """Lines outside fenced code blocks, which are the only ones that render."""
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def typescript_comments(text: str) -> Iterator[tuple[int, str]]:
    """Comment text only.

    A string literal may legitimately hold two backticks — building a fenced
    block with an escaped template literal is the normal way to do it — and
    rewriting one would corrupt what it renders.
    """
    in_block = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if in_block:
            yield number, line
            if "*/" in line:
                in_block = False
            continue
        if stripped.startswith("/*"):
            yield number, line
            if "*/" not in stripped[2:]:
                in_block = True
            continue
        if stripped.startswith("//"):
            yield number, line


def scan(path: Path) -> list[tuple[int, str]]:
    """Every offending line in one file, as (line number, line)."""
    if path.name == SELF:
        return []
    if path.suffix in MARKDOWN_SUFFIXES:
        lines = markdown_prose(path.read_text(encoding="utf-8"))
    elif path.suffix in TYPESCRIPT_SUFFIXES:
        lines = typescript_comments(path.read_text(encoding="utf-8"))
    elif path.suffix in PYTHON_SUFFIXES:
        lines = enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
    else:
        return []
    return [(number, line) for number, line in lines if PAIR.search(line)]


def fix(path: Path) -> int:
    """Rewrite the offending lines in place. Returns how many were changed."""
    original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    offenders = {number for number, _ in scan(path)}
    if not offenders:
        return 0

    for number in offenders:
        index = number - 1
        original[index] = PAIR.sub(lambda match: f"`{match.group('body')}`", original[index])

    path.write_text("".join(original), encoding="utf-8")
    return len(offenders)


def is_nested_checkout(directory: Path) -> bool:
    """Whether this directory is a checkout of its own rather than part of this one.

    A git worktree holds a `.git` file, a clone holds a `.git` directory, and either
    way the files under it belong to some other branch. Scanning one reports findings
    twice, reports them against paths that are not on this branch, and - since a copy
    of this script lives there too - fails on the error message it is about to print.

    Detected rather than named: `.claude/worktrees/` is where this repository puts
    them, but skipping every directory called `worktrees` both misses one placed
    anywhere else and silently stops reading a `docs/worktrees/` that is only a
    directory with a name.
    """
    return (directory / ".git").exists()


def walk(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for directory, subdirectories, filenames in os.walk(root):
            here = Path(directory)
            # Pruned in place, which is what `os.walk` reads to decide where to go
            # next - the reason this is not `rglob`. Skipping a nested checkout means
            # not descending into it, not filtering its files out one at a time.
            subdirectories[:] = [
                name
                for name in subdirectories
                if name not in SKIP_DIRS and not is_nested_checkout(here / name)
            ]
            for name in sorted(filenames):
                path = here / name
                if path.suffix in MARKDOWN_SUFFIXES | TYPESCRIPT_SUFFIXES | PYTHON_SUFFIXES:
                    yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path()])
    parser.add_argument("--fix", action="store_true", help="rewrite them to single backticks")
    args = parser.parse_args()

    found = 0
    for path in sorted(walk(args.paths or [Path()])):
        if args.fix:
            changed = fix(path)
            if changed:
                found += changed
                print(f"fixed {changed} line(s) in {path}")
            continue
        for number, line in scan(path):
            found += 1
            print(f"{path}:{number}: {line.strip()}")

    if not found:
        print("No double backticks in Markdown, TypeScript comments or Python files.")
        return 0
    if args.fix:
        print(f"\nRewrote {found} line(s).")
        return 0

    print(f"\n{found} line(s) use ``double backticks``, which render literally. Run with --fix.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
