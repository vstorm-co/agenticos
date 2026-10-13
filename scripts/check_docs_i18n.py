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

`README.md` and the three policy files beside it are asked the same first two
questions, and a different third. GitHub renders those, GitHub has no
`attr_list`, so a translated heading there cannot pin anything and is expected
to answer to its own anchor. Three things are checked in its place:

- the sections keep their *shape* - as many headings, nested the same way;
- every link the file aims at itself lands on a heading that exists, because
  GitHub serves a dead fragment as the top of the page and says nothing;
- every other link goes where the English one goes, in the same order, and in
  the reader's own language wherever that page has been translated.

The middle one is what catches a translation that stopped halfway: shape alone
cannot, because untranslated headings have the same shape as the English ones
they were copied from. Shape alone also cannot see two sibling sections of the
same depth swapped - that would need a marker in a file people read as source,
and it is not claimed here.

All of these are reported as a defect. `--update` records the fingerprint after a
page has genuinely been retranslated - it is the last step of doing the work, not
a way of making this guard quiet, and running it over a page nobody retranslated
is how a stale translation stops being visible. It therefore takes the paths of
the translations you retranslated, and touches only those.

`docs/howto/translate.md` is the workflow this enforces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docs_i18n import (
    DOCS,
    LOCALES,
    REPO_ROOT,
    anchors,
    english_pages,
    english_source,
    fingerprint,
    github_anchors,
    heading_levels,
    linked_targets,
    locale_of,
    own_fragments,
    record_fingerprint,
    recorded_fingerprint,
    root_pages,
    translation_of,
)


def _name(page: Path) -> str:
    """How a page is named in this report: relative to `docs/`, or to the repository."""
    root = DOCS if page.is_relative_to(DOCS) else REPO_ROOT
    return page.relative_to(root).as_posix()


def translatable() -> list[Path]:
    """Every English file owed a translation: the site's pages and the repository's."""
    return [*english_pages(), *root_pages()]


def missing() -> list[tuple[str, str]]:
    """Every (page, locale) with no translation file at all."""
    return [
        (_name(page), locale)
        for page in translatable()
        for locale in LOCALES
        if not translation_of(page, locale).exists()
    ]


def stale() -> list[tuple[str, str]]:
    """Every (page, locale) whose translation predates the English text."""
    found: list[tuple[str, str]] = []
    for page in translatable():
        current = fingerprint(page)
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if translation.exists() and recorded_fingerprint(translation) != current:
                found.append((_name(page), locale))
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


def restructured() -> list[tuple[str, str, str]]:
    """Every root translation whose section *shape* no longer matches the English.

    A root file gets this instead of the anchor comparison. GitHub renders it,
    GitHub has no `attr_list`, so a translated heading cannot pin its English
    anchor and is *expected* to answer to a different one. What is left to
    compare is the shape: how many headings there are, and how they nest.

    Say only that, because that is all it is. Two sibling sections of the same
    depth swapped leave the shape untouched and pass here - answering that would
    need a per-heading marker in the file, and a README is read as source. What
    this does catch is the failure that actually happens: a translation that
    stops early loses the sections below it, or gains one, and the shape moves.

    `dangling()` and `relinked()` are the other two thirds. Between them they
    caught the first Polish and German README, which stopped halfway with the
    English headings copied across - structurally identical, so invisible here.
    """
    found: list[tuple[str, str, str]] = []
    for page in root_pages():
        expected = heading_levels(page)
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if not translation.exists():
                continue
            actual = heading_levels(translation)
            if actual == expected:
                continue
            complaint = (
                f"{len(actual)} headings against {len(expected)} in English"
                if len(actual) != len(expected)
                else "the same headings at different depths"
            )
            found.append((_name(page), locale, complaint))
    return found


def relinked() -> list[tuple[str, str, str]]:
    """Every root translation that does not send a reader where the English does.

    Link targets are the one part of a page that translation leaves alone, so
    they are comparable outright - same destinations, in the same order, each in
    the reader's own language where a translation of it exists.

    Two things this refuses. A translation that drops or reorders a link, which
    nothing else would see. And the one a reader meets first: a localized README
    whose documentation links land them back in English, which is what picking a
    language was meant to avoid.
    """
    found: list[tuple[str, str, str]] = []
    for page in root_pages():
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if not translation.exists():
                continue
            expected = linked_targets(page, into=locale)
            actual = linked_targets(translation)
            if actual == expected:
                continue
            if len(actual) != len(expected):
                complaint = f"{len(actual)} links against {len(expected)} in English"
            else:
                mine, theirs = next((a, b) for a, b in zip(actual, expected, strict=True) if a != b)
                complaint = f"a link to {mine!r} where it owes one to {theirs!r}"
            found.append((_name(page), locale, complaint))
    return found


def dangling() -> list[tuple[str, str, str]]:
    """Every root translation that links to a heading of its own that is not there.

    The English file's fragments were written against the English headings, so a
    translation has to rewrite each one by hand. Nothing else notices when it
    does not: GitHub serves a dead fragment as the top of the page, silently.
    """
    found: list[tuple[str, str, str]] = []
    for page in root_pages():
        for locale in LOCALES:
            translation = translation_of(page, locale)
            if not translation.exists():
                continue
            available = set(github_anchors(translation))
            found.extend(
                (_name(page), locale, fragment)
                for fragment in dict.fromkeys(own_fragments(translation))
                if fragment not in available
            )
    return found


def orphaned() -> list[str]:
    """Every translation whose English page has been renamed or deleted."""
    stranded = (
        page
        for page in (*DOCS.rglob("*.md"), *REPO_ROOT.glob("*.md"))
        if locale_of(page) is not None and not english_source(page).exists()
    )
    return sorted(_name(page) for page in stranded)


def update(translations: list[Path]) -> int:
    """Record the current English fingerprint on the named translations.

    Named, rather than all of them. Stamping every stale translation is the one
    move this whole design exists to prevent: change two English pages, retranslate
    one, and a blanket `--update` marks both current - the untouched page keeps
    its old text, loses its reader-facing notice, and the gate never mentions it
    again. So the translator says which files they actually retranslated, and
    nothing else is touched.
    """
    written = 0
    for translation in translations:
        if locale_of(translation) is None:
            print(f"{translation} is not a translation - pass `<page>.<locale>.md`.")
            return 1
        source = english_source(translation)
        if not source.exists():
            print(f"{translation} translates {source}, which does not exist.")
            return 1
        if not translation.exists():
            print(f"{translation} does not exist.")
            return 1
        current = fingerprint(source)
        written += recorded_fingerprint(translation) != current
        record_fingerprint(translation, current)
    print(
        f"Stamped {len(translations)} translation(s); "
        f"{written} of them were recording an older revision."
    )
    return 0


def report() -> int:
    absent, behind, moved, orphans = missing(), stale(), adrift(), orphaned()
    reshaped, dead, adrift_links = restructured(), dangling(), relinked()
    if not (absent or behind or moved or orphans or reshaped or dead or adrift_links):
        published, repository = len(english_pages()), len(root_pages())
        locales = ", ".join(LOCALES)
        print(
            f"All {published} published pages and {repository} repository files "
            f"are translated into {locales} and current."
        )
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
    if reshaped:
        print(f"Repository files whose sections do not line up with English ({len(reshaped)}):\n")
        for page, locale, complaint in reshaped:
            print(f"  {page} - {locale} has {complaint}")
        print()
    if adrift_links:
        print(f"Repository files that link somewhere English does not ({len(adrift_links)}):\n")
        for page, locale, complaint in adrift_links:
            print(f"  {page} - {locale} has {complaint}")
        print()
    if dead:
        print(f"Repository files linking to a heading of their own that is gone ({len(dead)}):\n")
        for page, locale, fragment in dead:
            print(f"  {page} - {locale} links to #{fragment}, which no heading answers to")
        print()
    if orphans:
        print(f"Translations of a page that no longer exists ({len(orphans)}):\n")
        for translation in orphans:
            print(f"  {translation}")
        print()
    print("Translate the page, pin each heading's English anchor - or, in a repository")
    print("file, rewrite its own in-page links - then record the revision it now matches:")
    print()
    print("  python3 scripts/check_docs_i18n.py --update <page>.<locale>.md")
    print()
    print("Name only the files you retranslated. docs/howto/translate.md has the workflow.")
    return 1


def show_anchors(page: Path) -> int:
    """Print the anchor each heading of a page answers to, in document order.

    A root file is answered by GitHub's rule rather than Python-Markdown's,
    because GitHub is what renders it. Those anchors are not pinnable - they are
    what a translator has to rewrite the in-page links *to*, rather than a list
    to copy across.
    """
    derive = github_anchors if page.resolve().parent == REPO_ROOT else anchors
    for anchor in derive(page):
        print(anchor)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        nargs="+",
        type=Path,
        metavar="TRANSLATION",
        help="record the current English fingerprint on the named `<page>.<locale>.md` files",
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
    return update(arguments.update) if arguments.update else report()


if __name__ == "__main__":
    sys.exit(main())
