"""Refuse a Polish or German page about the eval screens that names a concept two ways.

The console's catalogs say one word per concept on the eval screens - the
glossary in `docs/howto/translate.md` - and `frontend/messages/eval-terms.test.ts`
holds them to it. A page about the same screens that still says "case'ów" or
"Draft" gives its reader a second vocabulary, so this applies the same patterns,
read from `frontend/messages/eval-terms.json`, to those pages. It runs in
`make lint`, which every pull request runs: the vitest does not run on a change
to the docs alone.

What a reader does not read as prose is skipped: front matter, fenced blocks,
inline code, link targets, heading anchors and HTML tags, and an English
console label in parentheses after the translated one - „Aktywność (Activity)”,
the form `docs/howto/translate.md` asks for. A name the product shows in English,
such as the seeded **Eval judge**, is listed under `docs.allow`.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TERMS = ROOT / "frontend" / "messages" / "eval-terms.json"

_FENCE = re.compile(r"^\s*(```|~~~)")
_SKIPPED = (
    re.compile(r"`[^`]*`"),
    re.compile(r"\]\([^)]*\)"),
    re.compile(r"\{ ?#[^}]*\}"),
    re.compile(r"<[^>]+>"),
    re.compile(r"\(\*{0,2}[A-Z][A-Za-z0-9 ,'/-]*\*{0,2}\)"),
)


def prose_lines(text: str) -> list[tuple[int, str]]:
    """The page's prose, line by line, with what a reader does not read blanked out."""
    lines: list[tuple[int, str]] = []
    fenced = in_front_matter = False
    for number, line in enumerate(text.splitlines(), 1):
        if number == 1 and line.strip() == "---":
            in_front_matter = True
            continue
        if in_front_matter:
            in_front_matter = line.strip() != "---"
            continue
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for skipped in _SKIPPED:
            line = skipped.sub(" ", line)
        lines.append((number, line))
    return lines


def _patterns(entries: list[dict], *, only: str | None = None) -> list[tuple[re.Pattern[str], str]]:
    return [
        (re.compile(entry["pattern"], re.IGNORECASE), entry["use"])
        for entry in entries
        if ("within" not in entry or entry.get("docs", False))
        and (only is None or entry["key"] == only)
    ]


def offences() -> list[tuple[Path, int, str, str]]:
    """Every mixed form, as (page, line, the form, the glossary word to use)."""
    terms = json.loads(TERMS.read_text(encoding="utf-8"))
    docs = terms["docs"]
    found: list[tuple[Path, int, str, str]] = []
    for locale, entries in terms["mixed"].items():
        allowed = docs["allow"].get(locale, [])
        pages = [(name, _patterns(entries)) for name in docs["pages"]]
        pages += [
            (name, _patterns(entries, only="activity"))
            for name in docs["activityPages"].get(locale, [])
        ]
        for name, patterns in pages:
            page = DOCS / f"{name}.{locale}.md"
            for number, line in prose_lines(page.read_text(encoding="utf-8")):
                for phrase in allowed:
                    line = line.replace(phrase, " ")
                for pattern, use in patterns:
                    found += [
                        (page, number, match.group(0), use) for match in pattern.finditer(line)
                    ]
    return found


def main() -> int:
    found = offences()
    if not found:
        print("The Polish and German eval pages use the glossary's words.")
        return 0
    print(f"Words the eval glossary replaced ({len(found)}):\n")
    for page, number, form, use in found:
        print(f"  {page.relative_to(ROOT)}:{number}: {form!r} - write {use!r}")
    print("\nThe glossary is under 'The words the eval screens use' in docs/howto/translate.md.")
    print("A console label stays English only in parentheses after the translated one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
