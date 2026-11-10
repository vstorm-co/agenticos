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
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILL = ROOT / "backend/app/core/catalog/skill_gallery/software/agenticos-guide"
SITE = "https://vstorm-co.github.io/agenticos/"

#: A copy carries a subset of `docs/`, so a relative link to a page it does not
#: carry would dangle. Those links are pointed at the published page instead.
LINK = re.compile(r"\]\(([^)\s]+?\.md)(#[^)\s]*)?\)")
FENCE = re.compile(
    r"(?P<fence>`{3,}|~{3,}).*?(?P=fence)|(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)",
    re.S,
)

#: The pages carried in the skill, by their path under `docs/`. These answer
#: most questions a person asks the Architect about the product - what a thing
#: is called, what ships, how the pieces fit, MCP both ways, projects, the API, and
#: improving an agent with Improve and evals. The rest are linked from `SKILL.md`
#: and read from the documentation site.
PAGES = (
    "reference/glossary.md",
    "features.md",
    "concepts.md",
    "mcp.md",
    "api.md",
    "projects.md",
    "authoring.md",
    "evals.md",
    "datasets.md",
    "knowledge-gaps.md",
    "workflows.md",
    "virtual-tables.md",
    "desktop.md",
    "mobile.md",
    "sandbox.md",
    "skills.md",
    "context.md",
)


def target(page: str) -> Path:
    """Where a page's copy lives in the skill: flat, under `docs/`."""
    return SKILL / "docs" / page.replace("/", "-")


def _site_url(page: PurePosixPath) -> str:
    path = page.with_suffix("")
    if path.name == "index":
        path = path.parent
    return SITE + ("" if path == PurePosixPath(".") else f"{path}/")


def render(page: str) -> str:
    """The page as the skill carries it.

    Links are rewritten only where the copy cannot resolve them: the skill keeps a
    subset of `docs/`, flat under `docs/`, so `desktop.md` still works while
    `reference/capabilities.md` does not. Code spans and fenced blocks are left
    alone - a link inside them is an example for the reader, not a link.
    """
    text = (DOCS / page).read_text(encoding="utf-8")
    spans = [(m.start(), m.end()) for m in FENCE.finditer(text)]

    def in_code(pos: int) -> bool:
        return any(start <= pos < end for start, end in spans)

    out: list[str] = []
    cursor = 0
    for match in LINK.finditer(text):
        if in_code(match.start()):
            continue
        link, anchor = match.group(1), match.group(2) or ""
        if urlsplit(link).scheme or link.startswith("/"):
            continue
        source = posixpath.normpath((PurePosixPath(page).parent / link).as_posix())
        # The manifest, not already generated files, determines which pages ship.
        destination = target(source).name if source in PAGES else _site_url(PurePosixPath(source))
        out.append(text[cursor : match.start()])
        out.append(f"]({destination}{anchor})")
        cursor = match.end()
    if not out:
        return text
    out.append(text[cursor:])
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report staleness instead of writing")
    args = parser.parse_args()

    stale = [
        page
        for page in PAGES
        if not target(page).exists() or target(page).read_text(encoding="utf-8") != render(page)
    ]
    if args.check:
        for page in stale:
            print(f"stale: {target(page).relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for page in PAGES:
        target(page).parent.mkdir(parents=True, exist_ok=True)
        target(page).write_text(render(page), encoding="utf-8")
    for page in stale:
        print(f"wrote {target(page).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
