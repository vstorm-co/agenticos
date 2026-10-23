"""Refuse a Polish or German page about the eval screens that names a concept two ways.

The console's catalogs say one word per concept on the eval screens - the
glossary in `docs/howto/translate.md` - and `frontend/messages/eval-terms.test.ts`
holds them to it. A page about the same screens that still says "case'ów" or
"Draft" gives its reader a second vocabulary, so this applies the same patterns,
read from `frontend/messages/eval-terms.json`, to those pages. It runs in
`make lint`, which every pull request runs: the vitest does not run on a change
to the docs alone.

What a reader does not read as prose is skipped: front matter other than the
titles and descriptions a search result shows, fenced blocks, inline code, link
targets, heading anchors and HTML tags, and an English console label in
parentheses right after the bold translated one - **Aktywność** (Activity), the
form `docs/howto/translate.md` asks for, also when the label ends the line above. A name the product shows in English,
such as the seeded **Eval judge**, is listed under `docs.allow`.

Each line is matched on its own, so a mixed form split across two lines, or an
inline code span opened with double backticks, is not seen.
"""

import json
import re
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TERMS = ROOT / "frontend" / "messages" / "eval-terms.json"

_FENCE = re.compile(r"^\s*(```|~~~)")
_SHOWN = re.compile(r"^(\w*title|\w*description):(.*)$")
_SKIPPED = (
    re.compile(r"`[^`]*`"),
    re.compile(r"\]\([^)]*\)"),
    re.compile(r"\{ ?#[^}]*\}"),
    re.compile(r"<[^>]+>"),
    re.compile(r"(?<=\*\*) ?\([^()]*\)"),
)
_LABEL_ABOVE = re.compile(r"^\s*\([^()]*\)")


class Entry(TypedDict):
    """One mixed form in `eval-terms.json`, as the guard reads it."""

    key: str
    pattern: str
    use: str
    within: NotRequired[list[str]]
    docs: NotRequired[bool]


def prose_lines(text: str) -> list[tuple[int, str]]:
    """The page's prose, line by line, with what a reader does not read blanked out."""
    lines: list[tuple[int, str]] = []
    in_front_matter = False
    fence: str | None = None
    previous = ""
    for number, line in enumerate(text.splitlines(), 1):
        after_label = previous.rstrip().endswith("**")
        previous = line
        if number == 1 and line.strip() == "---":
            in_front_matter = True
            continue
        if in_front_matter:
            in_front_matter = line.strip() != "---"
            shown = _SHOWN.match(line)
            if shown is None:
                continue
            line = shown.group(2)
        elif marker := _FENCE.match(line):
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1) == fence:
                fence = None
            continue
        elif fence is not None:
            continue
        if after_label:
            line = _LABEL_ABOVE.sub(" ", line)
        for skipped in _SKIPPED:
            line = skipped.sub(" ", line)
        lines.append((number, line))
    return lines


def _patterns(
    entries: list[Entry], *, only: str | None = None
) -> list[tuple[re.Pattern[str], str]]:
    return [
        (re.compile(entry["pattern"], re.IGNORECASE), entry["use"])
        for entry in entries
        if ("within" not in entry or entry.get("docs", False))
        and (only is None or entry["key"] == only)
    ]


def _checked() -> list[tuple[Path, list[tuple[re.Pattern[str], str]], list[str]]]:
    """Every page the terms name, with the patterns it is held to and its allowed phrases."""
    terms = json.loads(TERMS.read_text(encoding="utf-8"))
    docs = terms["docs"]
    checked: list[tuple[Path, list[tuple[re.Pattern[str], str]], list[str]]] = []
    for locale, entries in terms["mixed"].items():
        allowed: list[str] = docs["allow"].get(locale, [])
        checked += [
            (DOCS / f"{name}.{locale}.md", _patterns(entries), allowed) for name in docs["pages"]
        ]
        checked += [
            (DOCS / f"{name}.{locale}.md", _patterns(entries, only="activity"), allowed)
            for name in docs["activityPages"].get(locale, [])
        ]
    return checked


def missing() -> list[Path]:
    """The pages `eval-terms.json` names that are not in `docs/`."""
    return [page for page, _, _ in _checked() if not page.is_file()]


def offences() -> list[tuple[Path, int, str, str]]:
    """Every mixed form, as (page, line, the form, the glossary word to use)."""
    found: list[tuple[Path, int, str, str]] = []
    for page, patterns, allowed in _checked():
        for number, line in prose_lines(page.read_text(encoding="utf-8")):
            for phrase in allowed:
                line = line.replace(phrase, " ")
            for pattern, use in patterns:
                found += [(page, number, match.group(0), use) for match in pattern.finditer(line)]
    return found


def main() -> int:
    absent = missing()
    if absent:
        print("Pages named under 'docs' in frontend/messages/eval-terms.json that do not exist:\n")
        for page in absent:
            print(f"  {page.relative_to(ROOT)}")
        return 1
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
