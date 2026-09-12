"""Build-time fixups the site needs and no MkDocs plugin provides.

Two jobs. The first is telling a reader when the page in front of them is not
the translation its URL and its navigation imply - `fallback_to_default` serves
the English page under `/de/...` when nobody has translated it, and a page whose
English source moved on after it was translated looks exactly like a current one.
Both get an admonition in the reader's own language saying which they are
reading; `scripts/docs_i18n.py` defines what "current" means.

The second is the release-notes page, which shows `CHANGELOG.md` from the
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
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# MkDocs loads a hook straight from its path, without putting that path on
# `sys.path`, so a plain `import docs_i18n` fails however the two files sit
# beside each other.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_i18n import DEFAULT_LOCALE, FINGERPRINT_KEY, english_source, fingerprint

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

RELEASE_NOTES = "release-notes.md"
LLMS_TXT = "llms.txt"
CHANGELOG_MARKER = "<!-- changelog -->"

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
_DOCS_LINK = re.compile(r"\]\(docs/(?=[\w./#-]+\))")
_LEADING_HEADING = re.compile(r"\A#\s.*?\n", re.DOTALL)

# One admonition per locale rather than one English sentence for everybody: the
# reader this is addressed to is the one who chose a language and is now being
# handed something else, so it has to be readable to them. The language switcher
# in the header is two inches away, which is why neither notice links anywhere.
UNTRANSLATED = {
    "pl": (
        "Ta strona nie została jeszcze przetłumaczona",
        "Czytasz angielski oryginał. Tłumaczenie tej strony jeszcze nie powstało.",
    ),
    "de": (
        "Diese Seite ist noch nicht übersetzt",
        "Sie lesen das englische Original. Eine Übersetzung dieser Seite gibt es noch nicht.",
    ),
    "es": (
        "Esta página todavía no está traducida",
        "Estás leyendo el original en inglés. Aún no existe una traducción de esta página.",
    ),
}

OUT_OF_DATE = {
    "pl": (
        "To tłumaczenie jest nieaktualne",
        "Angielski oryginał zmienił się od czasu powstania tego tłumaczenia, więc część treści może już nie opisywać obecnego zachowania. Wersja angielska jest rozstrzygająca.",
    ),
    "de": (
        "Diese Übersetzung ist veraltet",
        "Das englische Original hat sich seit dieser Übersetzung geändert, daher beschreiben Teile davon möglicherweise nicht mehr das aktuelle Verhalten. Maßgeblich ist die englische Fassung.",
    ),
    "es": (
        "Esta traducción está desactualizada",
        "El original en inglés ha cambiado desde que se hizo esta traducción, así que algunas partes pueden no describir el comportamiento actual. La versión en inglés es la que manda.",
    ),
}


def _changelog_body() -> str:
    """The changelog from its first release heading, with site-relative links.

    The file opens on a title and a preamble that the page states in its own
    words; keeping both would print them twice.
    """
    text = _CHANGELOG.read_text(encoding="utf-8")
    start = text.index("\n## ")
    return _DOCS_LINK.sub("](", text[start + 1 :]).strip()


def _admonition(notice: tuple[str, str]) -> str:
    title, body = notice
    return f'!!! warning "{title}"\n\n    {body}\n\n'


def _translation_notice(page: Page, locale: str) -> str | None:
    """The notice this page owes its reader, if it owes one.

    `page.file.locale` is the language of the file actually being rendered, so
    it disagreeing with the language being built *is* the fallback: English text
    about to be served under a localized URL.
    """
    if locale == DEFAULT_LOCALE:
        return None
    if page.file.locale != locale:
        return _admonition(UNTRANSLATED[locale])
    source = english_source(Path(page.file.abs_src_path))
    if page.meta.get(FINGERPRINT_KEY) != fingerprint(source):
        return _admonition(OUT_OF_DATE[locale])
    return None


def on_page_markdown(
    markdown: str, *, page: Page, config: MkDocsConfig, files: Files
) -> str | None:
    """Mark an untranslated or outdated page, and fill in the release notes."""
    if english_source(Path(page.file.src_uri)).as_posix() == RELEASE_NOTES:
        markdown = markdown.replace(CHANGELOG_MARKER, _changelog_body())
    notice = _translation_notice(page, config.theme["language"])
    if notice is None:
        return markdown
    heading = _LEADING_HEADING.match(markdown)
    if heading is None:
        return notice + markdown
    return f"{heading.group()}\n{notice}{markdown[heading.end() :]}"


def on_post_build(*, config: MkDocsConfig) -> None:
    """Copy `llms.txt` from the repository root into the built site.

    The file is how a language model is meant to discover what a project is, so
    it has to be served at the site root - and it is also the first thing
    somebody browsing the repository looks for, so it has to be at the
    repository root. Copying beats keeping two of them: the version that would
    drift is the one nobody edits, and it is the one the models read.

    `docs_dir` cannot reach outside itself, which is why this is a hook rather
    than a file in `docs/`.
    """
    source = Path(__file__).resolve().parent.parent / LLMS_TXT
    shutil.copyfile(source, Path(config.site_dir) / LLMS_TXT)
