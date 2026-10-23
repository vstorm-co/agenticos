#!/usr/bin/env python3
"""Copy the documentation pages the Architect answers from into its skill.

The Architect answered "can I use AgenticOS from Claude Code?" by searching the
web, when `docs/mcp.md` has the exact command. Its skill now carries the pages
that answer most questions about the product itself; the backend image does not
contain `docs/`, so the skill holds copies - written here, from the one source,
and checked by `backend/tests/test_architect_guide.py`.

Usage::

    python3 scripts/gen_architect_guide.py          # rewrite the copies
    python3 scripts/gen_architect_guide.py --check  # exit 1 if they are stale
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILL = ROOT / "backend/app/core/catalog/skill_gallery/software/agenticos-guide"

#: The pages carried in the skill, by their path under `docs/`. Five that answer
#: most questions a person asks the Architect about the product - what a thing
#: is called, what ships, how the pieces fit, MCP both ways, and the API. The
#: rest are linked from `SKILL.md` and read from the documentation site.
PAGES = (
    "reference/glossary.md",
    "features.md",
    "concepts.md",
    "mcp.md",
    "api.md",
)


def target(page: str) -> Path:
    """Where a page's copy lives in the skill: flat, under `docs/`."""
    return SKILL / "docs" / page.replace("/", "-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report staleness instead of writing")
    args = parser.parse_args()

    stale = [
        page
        for page in PAGES
        if not target(page).exists() or target(page).read_text() != (DOCS / page).read_text()
    ]
    if args.check:
        for page in stale:
            print(f"stale: {target(page).relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for page in PAGES:
        target(page).parent.mkdir(parents=True, exist_ok=True)
        target(page).write_text((DOCS / page).read_text())
    for page in stale:
        print(f"wrote {target(page).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
