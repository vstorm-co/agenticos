"""Build-time fixups the site needs and no MkDocs plugin provides.

The one job here is the release-notes page, which shows `CHANGELOG.md` from the
repository root rather than keeping a second copy of it that drifts. Two things
stop that from being a `pymdownx.snippets` include:

- The changelog's internal links are written for GitHub -
  `[the spec reference](docs/reference/spec.md)`. Read from a page that already
  lives inside `docs/`, each of those resolves to `docs/docs/...`, which
  `mkdocs build --strict` fails on.
- A snippet is expanded by a markdown extension, which runs *after* every hook,
  so nothing in this file could reach the included text to fix it.

So the page carries a marker and this hook substitutes the changelog into it,
rewriting the links on the way through. The file stays correct on GitHub and the
page stays correct on the site.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

RELEASE_NOTES = "release-notes.md"
CHANGELOG_MARKER = "<!-- changelog -->"

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
_DOCS_LINK = re.compile(r"\]\(docs/(?=[\w./#-]+\))")
_LEADING_HEADING = re.compile(r"\A#\s.*?\n", re.DOTALL)


def _changelog_body() -> str:
    """The changelog from its first release heading, with site-relative links.

    The file opens on a title and a preamble that the page states in its own
    words; keeping both would print them twice.
    """
    text = _CHANGELOG.read_text(encoding="utf-8")
    start = text.index("\n## ")
    return _DOCS_LINK.sub("](", text[start + 1 :]).strip()


def on_page_markdown(
    markdown: str, *, page: Page, config: MkDocsConfig, files: Files
) -> str | None:
    """Substitute the changelog into the release-notes page."""
    if page.file.src_uri != RELEASE_NOTES:
        return None
    return markdown.replace(CHANGELOG_MARKER, _changelog_body())
