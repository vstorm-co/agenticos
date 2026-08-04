#!/usr/bin/env python3
"""Refuse copy that a component wrote itself.

Every user-facing string in the frontend comes from `messages/en.json` through
`next-intl`, and the rule survives exactly as long as something checks it: a
convention that is only written down gets broken by the next feature, silently,
and the Polish UI ships half in English. That is what happened here - nine
hundred strings across a hundred and forty files, in a repository whose own
`.claude/rules/frontend.md` says never to hardcode copy.

What it looks for, in `frontend/src/**/*.tsx`:

* a JSX text node holding words - `<p>Nothing yet.</p>`;
* a word-bearing string in an attribute a person reads: `placeholder`,
  `aria-label`, `title`, `alt`, and the label-ish props components take;
* `toast.success("…")` and friends, which are as user-facing as anything on
  screen and read like plumbing;
* a sentence built by concatenation - `` `Access to ${name}` `` - which is where
  copy hides best, being neither a text node nor an attribute nor a plain string;
* a text node holding an interpolation as well as words - `Owned by {email}` - and
  the plural somebody rolled by hand beside it, `{n} file{n === 1 ? "" : "s"}`, which
  is a sentence only English can build that way.

What it deliberately does not look at:

* tests, which assert the copy and must name it;
* `src/app/[locale]/(dashboard)/dev/**`, a playground for looking at components
  that is not part of the product;
* anything a person never reads - `className`, `href`, `data-*`, `id`, `type`.

False positives get an inline `{/* i18n-exempt: why */}` or a trailing
`// i18n-exempt: why`. The comment is required to carry a reason, because "this
one is fine" is the sentence that turns a gate into a rubber stamp.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
CATALOG = ROOT / "frontend" / "messages" / "en.json"

SKIPPED_DIRS = ("/dev/",)
SKIPPED_NAMES = (".test.tsx", ".test.ts", ".spec.ts", ".stories.tsx", ".generated.ts")

READABLE_ATTRS = (
    "placeholder",
    "aria-label",
    "alt",
    "title",
    "label",
    "description",
    "emptyMessage",
    "confirmLabel",
    "cancelLabel",
    "submitLabel",
    "heading",
    "subtitle",
)
ATTR = re.compile(rf'\b({"|".join(READABLE_ATTRS)})="([^"]*)"')
JSX_TEXT = re.compile(r">\s*([^<>{}\n][^<>{}\n]*?)\s*<")
TOASTS = re.compile(r'\btoast\.(?:success|error|info|warning|message)\(\s*"([^"]+)"')
# Copy hiding in an expression rather than in a text node - `{busy ? "Saving…" :
# "Save"}`, a ternary in a prop, a sentence pushed into an array. Two words is the
# threshold: it is what separates a sentence from an identifier, and every one-word
# label is already caught as a text node or an attribute.
SENTENCE = re.compile(r'"([A-Z][^"\n]*?\s[^"\n]*?)"')
NOT_A_SENTENCE = re.compile(
    r"^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s?[-/]\s?|"  # "Foo / Bar" style tokens
    r"[A-Z]{2,}\s|.*\b(?:px|rem|vh|vw|deg)\b)"
)
# Copy in a text node that also holds an interpolation - `Owned by {email}`,
# `Showing {n} of {m} rows`. `JSX_TEXT` excludes braces by construction, so the first
# sweep read straight past this whole class and left it in English.
MIXED = re.compile(r">([^<>\n]*\{[^{}\n]*\}[^<>\n]*)<")
# A plural somebody rolled by hand: `{n} chunk{n === 1 ? "" : "s"}`. English is the
# only language where this works, which is the point of `plural` in an ICU message.
PLURAL = re.compile(r'\?\s*"([A-Za-z]*)"\s*:\s*"([A-Za-z]*)"')
# The other half of the same habit, where the singular is spelled out: `count === 1 ?
# "1 skill" : ...`. Caught by its digit, which `SENTENCE` requires a capital instead of.
NUMBERED = re.compile(r'"(\d+\s+[A-Za-z][^"\n]*)"')
# A sentence built by concatenation - `Access to ${name}`, `${n} of ${total} shown`.
# A template literal is where copy hides best: it is not a text node, not an attribute
# and not a plain string, so every other rule here reads past it.
TEMPLATE = re.compile(r"`([^`\n]*\$\{[^{}`]*\}[^`\n]*)`")
# Two words with real whitespace between them. `audience${key}Hint` builds a catalog
# key and reads as two words only because the interpolation was replaced by one.
TWO_WORDS = re.compile(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}")
# A URL, a query string, a CSS value, a header - built by interpolation and read by
# a machine.
MACHINE_READ = re.compile(r"[/?&=<>#]|\b(?:px|rem|deg|vh|vw|attachment)\b")
EXEMPT = re.compile(r"i18n-exempt:\s*\S")
WORDS = re.compile(r"[A-Za-z]{2,}")
# A word-bearing string that is still not copy: an icon name, a CSS-ish token, a
# path, a MIME type, a locale tag. Matched whole, so "Save changes" never hits it.
NOT_COPY = re.compile(
    r"^(?:[a-z0-9-]+(?:/[a-z0-9.*+-]+)+|[a-z]+(?:-[a-z0-9]+)+|[A-Za-z]+\.[A-Za-z]{2,4}|"
    r"https?://\S+|&[a-z]+;|[A-Z_]{2,}|\d+(?:\.\d+)?\s*\w{0,3})$"
)


def is_copy(value: str) -> bool:
    """Whether a string is something a person reads, rather than a token."""
    stripped = value.strip()
    if len(stripped) < 2 or not WORDS.search(stripped):
        return False
    return not NOT_COPY.match(stripped)


def is_plural_pair(first: str, second: str) -> bool:
    """Whether two ternary branches are one word and its plural.

    Narrow on purpose: `dir === "asc" ? "desc" : "asc"` is two tokens, not copy, and
    only the `s` shapes - `"" : "s"`, `"file" : "files"` - are a plural in disguise.
    """
    if {first, second} == {"", "s"}:
        return True
    return bool(first) and bool(second) and (second == f"{first}s" or first == f"{second}s")


def offences(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    lines = path.read_text().splitlines()
    in_comment = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        # Comments explain the copy and often quote it - "answers \"Wrote 1 lines to
        # …\"" is a sentence about a string, not one. Tracked across lines because
        # the quoted example is usually in the middle of a block comment.
        was_in_comment = in_comment
        if "/*" in line and "*/" not in line[line.index("/*") :]:
            in_comment = True
        elif "*/" in line:
            in_comment = False
        if was_in_comment or stripped.startswith(("//", "*", "/*")) or EXEMPT.search(line):
            continue
        # Only the code half of a line that also carries a comment: `<p>Done</p> // why`
        # is copy, and the sentence in the comment is not.
        for opener in ("//", "/*"):
            if opener in line:
                line = line[: line.index(opener)]
        # TypeScript, not JSX: `onTest: (() => Promise<void>) | null` looks like a text
        # node to a regex, and a generic parameter is not something anybody reads.
        typescript = "=>" in line or "Promise<" in line
        # An exemption on the line above covers the line below it, which is where a
        # `{/* i18n-exempt: … */}` comment ends up after formatting.
        if number >= 2 and EXEMPT.search(lines[number - 2]):
            continue
        for match in ATTR.finditer(line):
            if is_copy(match.group(2)):
                found.append((number, f'{match.group(1)}="{match.group(2)}"'))
        for match in (() if typescript else JSX_TEXT.finditer(line)):
            # `percent >= 80 && "text-amber-600"` reads as a text node to a regex.
            # An operator between the angle brackets means it is an expression.
            if is_copy(match.group(1)) and not re.search(r"&&|\|\||=>", match.group(1)):
                found.append((number, f"text {match.group(1)!r}"))
        for match in (() if typescript else MIXED.finditer(line)):
            rest = re.sub(r"\{[^{}]*\}", " ", match.group(1))
            if len(WORDS.findall(rest)) >= 2 and not re.search(r"&&|\|\||=>", rest):
                found.append((number, f"text {' '.join(match.group(1).split())!r}"))
        for match in (() if "className" in line else TEMPLATE.finditer(line)):
            body = re.sub(r"\$\{[^{}]*\}", "\x00", match.group(1))
            if TWO_WORDS.search(body) and not MACHINE_READ.search(body):
                found.append((number, f"template {match.group(1)!r}"))
        for match in PLURAL.finditer(line):
            if is_plural_pair(match.group(1), match.group(2)):
                found.append((number, f"plural {match.group(0)!r}"))
        for match in NUMBERED.finditer(line):
            if is_copy(match.group(1)):
                found.append((number, f"string {match.group(1)!r}"))
        for match in TOASTS.finditer(line):
            if is_copy(match.group(1)):
                found.append((number, f"toast {match.group(1)!r}"))
        # Only where a string literal can reach the screen: an import path or a
        # `cn(...)` argument holds spaces too, and neither is copy.
        if not stripped.startswith(("import ", "export ", "from ")) and "className" not in line:
            for match in SENTENCE.finditer(line):
                value = match.group(1)
                if is_copy(value) and not NOT_A_SENTENCE.match(value):
                    found.append((number, f"string {value!r}"))
    return found


def missing_keys(path: Path, catalog: dict) -> list[tuple[int, str]]:
    """Keys a file reads that the catalog does not hold.

    The other half of the rule. The guard above catches copy that never made it *out*
    of a component; this catches a key that never made it *in* - a rename, a typo, or a
    file whose translator is scoped to one namespace while its keys were filed under
    another, which renders the key itself on screen and reports an error nobody sees
    until a person opens that page.
    """
    text = path.read_text()
    namespaces = re.findall(r'useTranslations\(\s*"([^"]+)"', text) + re.findall(
        r'getTranslations\(\s*"([^"]+)"', text
    )
    if not namespaces:
        return []
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(("//", "*", "/*")):
            continue
        for key in re.findall(r'\bt\(\s*"([^"]+)"', line):
            if not any(_holds(catalog, f"{namespace}.{key}") for namespace in namespaces):
                found.append((number, f'{key} (in {", ".join(namespaces)})'))
    return found


def _holds(catalog: dict, dotted: str) -> bool:
    node: object = catalog
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str)


def catalog_keys(node: object, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix.rstrip(".")}
    keys: set[str] = set()
    for key, value in node.items():
        keys |= catalog_keys(value, f"{prefix}{key}.")
    return keys


def main() -> int:
    if not SRC.is_dir():
        print(f"no frontend at {SRC}", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG.read_text())
    failures: list[str] = []
    absent: list[str] = []
    for path in sorted(SRC.rglob("*.tsx")):
        relative = str(path.relative_to(ROOT))
        if path.name.endswith(SKIPPED_NAMES) or any(part in relative for part in SKIPPED_DIRS):
            continue
        for number, what in offences(path):
            failures.append(f"{relative}:{number}: {what}")
        for number, what in missing_keys(path, catalog):
            absent.append(f"{relative}:{number}: {what}")

    if failures:
        # `--all` for somebody working through a backlog; the default keeps a failing
        # build readable.
        shown = failures if "--all" in sys.argv else failures[:200]
        print(f"{len(failures)} hardcoded string(s). Every one belongs in messages/en.json:\n")
        for failure in shown:
            print(f"  {failure}")
        if len(failures) > len(shown):
            print(f"  … and {len(failures) - len(shown)} more (--all to list them)")
        print(
            "\nMove the string into the catalog and read it with useTranslations, or mark a\n"
            "genuine non-string with `i18n-exempt: <reason>` on the line or the one above."
        )
        return 1

    if absent:
        shown = absent if "--all" in sys.argv else absent[:200]
        print(f"{len(absent)} message(s) read but not in messages/en.json:\n")
        for one in shown:
            print(f"  {one}")
        if len(absent) > len(shown):
            print(f"  … and {len(absent) - len(shown)} more (--all to list them)")
        return 1

    keys = catalog_keys(catalog)
    print(f"No hardcoded copy in frontend/src. {len(keys)} messages in en.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
