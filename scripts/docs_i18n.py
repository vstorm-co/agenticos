"""What a translated documentation page is, and whether it still matches English.

A translation is `<page>.<locale>.md` sitting beside `<page>.md`, and it carries
the fingerprint of the English text it was made from in its front matter. That
one number is what tells a stale translation from a current one, and three
things read it: the build hook that stamps a notice on a page whose English
source has moved on, the `make lint` gate that refuses to let one ship unnoticed,
and `--update`, which records it once a page has actually been retranslated.

All three have to agree on what the fingerprint means, so it is defined here and
only here. The rule is deliberately blunt - any edit to the English page, down to
a typo, marks every translation of it stale - because the alternative is a
heuristic that decides for you which English edits mattered, and the ones it gets
wrong are invisible.

Stdlib only: the guards run under the system interpreter, with no virtualenv.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"

DEFAULT_LOCALE = "en"
LOCALES = ("pl", "de", "es")

FINGERPRINT_KEY = "source_sha"
FINGERPRINT_LENGTH = 12

# Working material rather than site pages, and the two files `exclude_docs` keeps
# in the repository: delivery state in board shorthand, and the decisions a
# contributor reads before their first change. None of them is published, so none
# of them is owed a translation.
WORKING_NOTES = frozenset({"design", "plans", "audits"})
UNPUBLISHED = frozenset({"ROADMAP.md", "about/design.md", "assets/screens/README.md"})

_SUFFIX = re.compile(r"\.(?P<locale>[a-z]{2})\.md$")
_FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
_KEY = re.compile(rf"^{FINGERPRINT_KEY}:\s*(?P<value>\S+)\s*$", re.MULTILINE)

_FENCE = re.compile(r"^\s*(```|~~~)")
# No space required after the hashes, and a trailing run of them is decoration.
# That is Python-Markdown's own rule rather than CommonMark's, and the
# difference is not academic: three prose lines in `code-review.md` open on an
# issue number and are rendered as headings (#1605).
_HEADING = re.compile(r"^#{1,6}(?P<text>.*?)\s*#*\s*$")
_EXPLICIT_ANCHOR = re.compile(r"\s*\{\s*#(?P<anchor>[^}\s]+)\s*\}\s*$")
_INLINE_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\([^)]*\)")
_NOT_SLUGGABLE = re.compile(r"[^\w\s-]")
_SEPARATORS = re.compile(r"[-\s]+")
_ALREADY_NUMBERED = re.compile(r"^(.*)_([0-9]+)$")


def locale_of(page: Path) -> str | None:
    """The locale a file is written in, or None when it is the English source."""
    match = _SUFFIX.search(page.name)
    if match is None or match.group("locale") not in LOCALES:
        return None
    return match.group("locale")


def english_source(translation: Path) -> Path:
    """The English page a translation was made from."""
    return translation.with_name(_SUFFIX.sub(".md", translation.name))


def translation_of(source: Path, locale: str) -> Path:
    """Where the `locale` translation of an English page belongs."""
    return source.with_name(f"{source.name[: -len('.md')]}.{locale}.md")


def english_pages() -> list[Path]:
    """Every English page the site publishes, in path order."""
    pages: list[Path] = []
    for page in sorted(DOCS.rglob("*.md")):
        relative = page.relative_to(DOCS)
        if set(relative.parts) & WORKING_NOTES or relative.as_posix() in UNPUBLISHED:
            continue
        if locale_of(page) is None:
            pages.append(page)
    return pages


def _slugify(heading: str) -> str:
    """The anchor Python-Markdown's `toc` extension derives from a heading.

    Reproduced rather than imported because the guards run under the system
    interpreter. `tests/test_check_docs_i18n.py` checks it against the anchors
    the real build emits for every English heading on the site, which is what
    keeps "reproduced" from meaning "approximately".
    """
    text = _INLINE_LINK.sub(lambda link: link.group("text"), heading)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _SEPARATORS.sub("-", _NOT_SLUGGABLE.sub("", text).strip().lower())


def _unique(anchor: str, taken: set[str]) -> str:
    """What `toc` does to the second heading that slugs to the same thing."""
    while anchor in taken or not anchor:
        numbered = _ALREADY_NUMBERED.match(anchor)
        anchor = f"{numbered.group(1)}_{int(numbered.group(2)) + 1}" if numbered else f"{anchor}_1"
    taken.add(anchor)
    return anchor


def anchors(page: Path) -> list[str]:
    """The anchor every heading on a page answers to, in document order.

    A heading in a translation carries its English anchor explicitly -
    `## Berechtigungen { #permissions }` - so that one cross-page link with a
    fragment in it resolves in all four languages instead of only in English.
    `mkdocs build --strict` does not check fragments, so nothing else would
    notice a translated heading quietly moving one.
    """
    found: list[str] = []
    taken: set[str] = set()
    in_fence = False
    for line in page.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            continue
        text = heading.group("text")
        explicit = _EXPLICIT_ANCHOR.search(text)
        found.append(_unique(explicit.group("anchor") if explicit else _slugify(text), taken))
    return found


def fingerprint(source: Path) -> str:
    """The fingerprint of an English page's current text."""
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


def recorded_fingerprint(translation: Path) -> str | None:
    """The fingerprint a translation records, or None when it records none."""
    front_matter = _FRONT_MATTER.match(translation.read_text(encoding="utf-8"))
    if front_matter is None:
        return None
    key = _KEY.search(front_matter.group("body"))
    return key.group("value") if key else None


def record_fingerprint(translation: Path, value: str) -> None:
    """Write `value` into a translation's front matter, adding the block if needed."""
    text = translation.read_text(encoding="utf-8")
    front_matter = _FRONT_MATTER.match(text)
    if front_matter is None:
        translation.write_text(f"---\n{FINGERPRINT_KEY}: {value}\n---\n\n{text}", encoding="utf-8")
        return
    body = front_matter.group("body")
    updated = (
        _KEY.sub(f"{FINGERPRINT_KEY}: {value}", body)
        if _KEY.search(body)
        else f"{body}\n{FINGERPRINT_KEY}: {value}"
    )
    translation.write_text(f"---\n{updated}\n---\n{text[front_matter.end() :]}", encoding="utf-8")
