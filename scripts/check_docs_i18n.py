"""Refuse a locale that presents itself as complete while it is not.

The site publishes four languages from one `docs/` tree, and
`fallback_to_default` means a page nobody has translated still answers on
`/de/...` - in English, under a German URL, inside a German navigation. Nothing
fails, nothing warns, and a reader has no way to tell that page from a translated
one. The same is true one step later: an English page edited after it was
translated leaves three translations quietly describing what the product used to
do.

So this guard asks three questions of every published page, for every locale:

- is there a translation at all?
- does it record the fingerprint of the English text as it stands now?
- does every heading in it still answer to the anchor the English page answers
  to?

The third is the one `mkdocs build --strict` cannot ask. It validates a link's
path and not its `#fragment`, so a translated heading that moves an anchor breaks
every cross-page link into it, in one language, with a green build. Translations
pin their anchors - `## Berechtigungen { #permissions }` - and this compares the
two lists in document order, which also catches a section dropped or reordered.

All three are reported as a defect. `--update` records the fingerprint after a
page has genuinely been retranslated - it is the last step of doing the work, not
a way of making this guard quiet, and running it over a page nobody retranslated
is how a stale translation stops being visible.

`docs/howto/translate.md` is the workflow this enforces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docs_i18n import (
    DOCS,
    LOCALES,
    anchors,
    english_pages,
    english_source,
    fingerprint,
    locale_of,
    record_fingerprint,
    recorded_fingerprint,
    translation_of,
)


def missing() -> list[tuple[str, str]]:
    """Every (page, locale) with no translation file at all."""
    return [
        (page.relative_to(DOCS).as_posix(), locale)
        for page in english_pages()
        for locale in LOCALES
        if not translation_of(page, locale).exists()
    ]


def stale() -> list[tuple[str, str]]:
    """Every (page, locale) whose translation predates the English text."""
    found: list[tuple[str, str]] = []
    for page in english_pages():
        current = fingerprint(page)
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if translation.exists() and recorded_fingerprint(translation) != current:
                found.append((page.relative_to(DOCS).as_posix(), locale))
    return found


def adrift() -> list[tuple[str, str, str]]:
    """Every (page, locale, complaint) whose headings no longer line up."""
    found: list[tuple[str, str, str]] = []
    for page in english_pages():
        expected = anchors(page)
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if not translation.exists():
                continue
            actual = anchors(translation)
            if actual == expected:
                continue
            name = page.relative_to(DOCS).as_posix()
            if len(actual) != len(expected):
                found.append(
                    (name, locale, f"{len(actual)} headings against {len(expected)} in English")
                )
                continue
            first = next(a for a, b in zip(actual, expected, strict=True) if a != b)
            wanted = expected[actual.index(first)]
            found.append((name, locale, f"anchor {first!r} where English answers to {wanted!r}"))
    return found


def orphaned() -> list[str]:
    """Every translation whose English page has been renamed or deleted."""
    return sorted(
        page.relative_to(DOCS).as_posix()
        for page in DOCS.rglob("*.md")
        if locale_of(page) is not None and not english_source(page).exists()
    )


def update() -> int:
    """Record the current English fingerprint on every translation that exists."""
    written = 0
    for page in english_pages():
        current = fingerprint(page)
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if translation.exists() and recorded_fingerprint(translation) != current:
                record_fingerprint(translation, current)
                written += 1
    print(f"Recorded the English fingerprint on {written} translation(s).")
    return 0


def report() -> int:
    absent, behind, moved, orphans = missing(), stale(), adrift(), orphaned()
    if not (absent or behind or moved or orphans):
        pages = len(english_pages())
        print(f"All {pages} published pages are translated into {', '.join(LOCALES)} and current.")
        return 0

    if absent:
        print(f"Pages with no translation ({len(absent)}):\n")
        for page, locale in absent:
            print(f"  {page} - missing {locale}")
        print()
    if behind:
        print(f"Translations older than their English page ({len(behind)}):\n")
        for page, locale in behind:
            print(f"  {page} - {locale} was made from an older revision")
        print()
    if moved:
        print(f"Translations whose headings do not line up with English ({len(moved)}):\n")
        for page, locale, complaint in moved:
            print(f"  {page} - {locale} has {complaint}")
        print()
    if orphans:
        print(f"Translations of a page that no longer exists ({len(orphans)}):\n")
        for translation in orphans:
            print(f"  {translation}")
        print()
    print("Translate the page, pin each heading's English anchor, then")
    print("`python3 scripts/check_docs_i18n.py --update` to record the English revision it")
    print("now matches. docs/howto/translate.md has the workflow.")
    return 1


def show_anchors(page: Path) -> int:
    """Print the anchor each heading of a page answers to, in document order."""
    for anchor in anchors(page):
        print(anchor)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="record the current English fingerprint on every existing translation",
    )
    parser.add_argument(
        "--anchors",
        type=Path,
        metavar="PAGE",
        help="print the anchor each heading of PAGE answers to, which a translation has to pin",
    )
    arguments = parser.parse_args()
    if arguments.anchors is not None:
        return show_anchors(arguments.anchors)
    return update() if arguments.update else report()


if __name__ == "__main__":
    sys.exit(main())
