"""What looks wrong in a published HTML page, in words the model that wrote it can act on.

A page renders in a frame nobody on the run can see, so a page that is broken in
the ways models break pages - no doctype, a class the kit never defined, a table
with no head, icons with no icon library, a bound page that never asks for its
records - publishes and looks bad with nothing saying why. :func:`lint_page`
reads the markup and says so. It is a heuristic over the source, not a renderer:
it never refuses a page, and the caller returns what it finds as a warning for
the model to fix and publish again.

The kit's class vocabulary is read from the stylesheets themselves when this
module is imported, one set per `agenticos-<version>.css`, so a class added to a
kit is known here without a second list to keep in step.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "core" / "catalog" / "artifact_lib"

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_CLASS = re.compile(r"\.(ao-[a-z0-9]+(?:-[a-z0-9]+)*)")
# A class name in script text: `"ao-badge"`, `"ao-badge-" + tone`. Not a custom
# property (`--ao-danger`) or an attribute (`data-ao-tab`), hence the lookbehind.
_SCRIPT_CLASS = re.compile(r"(?<![\w$-])ao-[a-z0-9]+(?:-[a-z0-9]+)*")


def class_vocabulary(css: str) -> frozenset[str]:
    """Every `ao-` class a stylesheet has a rule for, comments left out."""
    return frozenset(_CSS_CLASS.findall(_CSS_COMMENT.sub("", css)))


def _kits() -> dict[int, frozenset[str]]:
    kits: dict[int, frozenset[str]] = {}
    for path in _LIBRARY_ROOT.glob("agenticos-*.css"):
        version = path.stem.removeprefix("agenticos-")
        if version.isdigit():
            kits[int(version)] = class_vocabulary(path.read_text(encoding="utf-8"))
    return kits


KIT_CLASSES: Mapping[int, frozenset[str]] = _kits()
"""Each served kit stylesheet's classes, by its version."""

LATEST_KIT = max(KIT_CLASSES)
"""The kit version a new page should load."""

LUCIDE_FILE = "lucide-1.46.0.min.js"
"""The icon library a page loads for `data-lucide`, as the library set names it."""

_DOCTYPE = re.compile(rb"\A(?:\xef\xbb\xbf)?(?:\s+|<!--.*?-->)*<!doctype\s+html\b", re.I | re.S)
_KIT_CSS = re.compile(r"(?:^|/)lib/agenticos-(\d+)\.css(?:[?#]|$)")
_KIT_JS = re.compile(r"(?:^|/)lib/agenticos-(\d+)\.js(?:[?#]|$)")
_LUCIDE = re.compile(r"(?:^|/)lib/lucide-[\d.]+(?:\.min)?\.js(?:[?#]|$)")
_ASKS_BRIDGE = re.compile(r"\bagenticos\s*\.\s*(?:onData|data)\b")
_KIT_3_CALL = re.compile(r"\bAO\s*\.\s*(onData|records)\b")
_BUILDS_TABLE = re.compile(r"createElement\(\s*['\"`]table['\"`]|<table\b", re.I)
_BUILDS_HEAD = re.compile(r"createTHead|thead", re.I)
_SHOWN_CLASSES = 8


@dataclass
class _Table:
    styled: bool
    head: bool = False


class _Page(HTMLParser):
    """What the lint needs from a page's markup, collected in one pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.viewport = False
        self.stylesheets: list[str] = []
        self.sources: list[str] = []
        self.classes: set[str] = set()
        self.icons = False
        self.tables: list[_Table] = []
        self.script: list[str] = []
        self.style: list[str] = []
        self._open: list[_Table] = []
        self._raw: str | None = None

    @property
    def inside(self) -> str | None:
        """The raw-text element the parser is in - `script` or `style` - or `None`."""
        return self._raw

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        classes = values.get("class", "").split()
        self.classes.update(name for name in classes if name.startswith("ao-"))
        self.icons = self.icons or "data-lucide" in values
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.viewport = True
        elif tag == "link" and "stylesheet" in values.get("rel", "").lower().split():
            self.stylesheets.append(values.get("href", ""))
        elif tag in ("script", "style"):
            if values.get("src"):
                self.sources.append(values["src"])
            self._raw = tag
        elif tag == "table":
            table = _Table(styled="ao-table" in classes)
            self.tables.append(table)
            self._open.append(table)
        elif tag == "thead" and self._open:
            self._open[-1].head = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._raw = None
        elif tag == "table" and self._open:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        if self._raw == "script":
            self.script.append(data)
        elif self._raw == "style":
            self.style.append(data)


def _versions(pattern: re.Pattern[str], addresses: list[str]) -> set[int]:
    return {int(found.group(1)) for address in addresses if (found := pattern.search(address))}


def _named(classes: Collection[str]) -> str:
    shown = sorted(classes)[:_SHOWN_CLASSES]
    more = len(classes) - len(shown)
    return ", ".join(f"`{name}`" for name in shown) + (f" and {more} more" if more else "")


def _class_problem(page: _Page, script: str, css_versions: set[int]) -> str | None:
    used = page.classes | set(_SCRIPT_CLASS.findall(script))
    own = class_vocabulary("\n".join(page.style))
    known = own.union(*(KIT_CLASSES.get(version, frozenset()) for version in css_versions))
    unknown = used - known
    if not unknown:
        return None
    latest = f"lib/agenticos-{LATEST_KIT}.css"
    if not css_versions:
        return (
            f"It uses {_named(unknown)} but loads no page kit stylesheet, so they do nothing. "
            f'Add `<link rel="stylesheet" href="{latest}">` to `<head>`.'
        )
    loaded = ", ".join(f"`lib/agenticos-{version}.css`" for version in sorted(css_versions))
    if LATEST_KIT not in css_versions and unknown <= KIT_CLASSES[LATEST_KIT]:
        return f"{loaded} has no {_named(unknown)}; `{latest}` does, so load that instead."
    return (
        f"{loaded} defines no {_named(unknown)}, so they do nothing. Use the kit's own "
        "classes (the `artifact-pages` guide lists them) or style them in the page's `<style>`."
    )


def _table_problems(page: _Page, script: str) -> list[str]:
    builds = _BUILDS_TABLE.search(script) is not None
    problems: list[str] = []
    headless = builds or any(not table.head for table in page.tables)
    if headless and not _BUILDS_HEAD.search(script):
        problems.append(
            "A table has no `<thead>`, so its header row is not drawn as one. Put the header "
            "row in `<thead>` and the rows in `<tbody>` (`table.createTHead()`, "
            "`table.createTBody()`), or draw bound records with `AO.records`."
        )
    unstyled = builds or any(not table.styled for table in page.tables)
    if unstyled and "ao-table" not in _SCRIPT_CLASS.findall(script):
        problems.append(
            "A table has no `ao-table` class, so it is drawn with the browser's defaults. Use "
            '`<div class="ao-table-wrap"><table class="ao-table">`.'
        )
    return problems


def lint_page(data: bytes, *, bound: Collection[str] = ()) -> list[str]:
    """What looks wrong in an HTML page, one sentence each, in the order to fix them.

    Args:
        data: The page as published.
        bound: The names of the page's bindings; a bound page whose script never
            asks for its data is one of the problems.

    Returns:
        Each problem as a sentence that says what to change, or `[]`. Checked: a
        `<script>` that is never closed; a doctype first and a viewport meta; `ao-` classes, in the markup or named in
        a script, that neither the kit version the page loads nor its own `<style>`
        defines; a table without `<thead>` or without `ao-table`; `data-lucide`
        without the icon library; `AO.onData` or `AO.records` without
        `agenticos-3.js`; and a bound page that never calls `agenticos.onData`.
    """
    page = _Page()
    page.feed(data.decode("utf-8", errors="replace"))
    page.close()
    # Still inside a script when the page ran out: its closing tag never came.
    unclosed = page.inside == "script"
    script = "\n".join(page.script)
    css_versions = _versions(_KIT_CSS, page.stylesheets)
    js_versions = _versions(_KIT_JS, page.sources)
    kit_3 = any(version >= 3 for version in js_versions)

    problems: list[str] = []
    if unclosed:
        problems.append(
            "A `<script>` is never closed - `<\\/script>` is an escape inside a JavaScript "
            "string, not a closing tag - so the browser reads the rest of the page as script "
            "and none of it runs. End each script with `</script>`."
        )
    if not _DOCTYPE.match(data):
        problems.append(
            "It does not start with `<!doctype html>`, so it is drawn in quirks mode: tables "
            "lose the page's text size, among other things. Make that the first line."
        )
    if not page.viewport:
        problems.append(
            'It has no `<meta name="viewport" content="width=device-width, initial-scale=1">`, '
            "so a phone shows it zoomed out. Add it to `<head>`."
        )
    if (classes := _class_problem(page, script, css_versions)) is not None:
        problems.append(classes)
    problems.extend(_table_problems(page, script))
    icons = page.icons or "data-lucide" in script
    if icons and not any(_LUCIDE.search(source) for source in page.sources):
        problems.append(
            f"It uses `data-lucide` icons but does not load `lib/{LUCIDE_FILE}`, so they stay "
            "blank. Load it before the kit's script."
        )
    calls = sorted(set(_KIT_3_CALL.findall(script)))
    if calls and not kit_3:
        named = " and ".join(f"`AO.{call}`" for call in calls)
        problems.append(
            f"It calls {named}, which only `lib/agenticos-3.js` has, so its script stops there. "
            "Load `lib/agenticos-3.js` (in place of any older kit script), or call "
            "`agenticos.onData` directly."
        )
    asks = _ASKS_BRIDGE.search(script) is not None or (kit_3 and "onData" in calls)
    if bound and not asks:
        problems.append(
            f"It is bound to {', '.join(sorted(bound))} but its script never calls "
            "`agenticos.onData`, so it will show no records. Render them inside "
            "`agenticos.onData(function (data) { ... })` - `AO.records` draws a binding as a "
            "table - and publish again."
        )
    return problems
