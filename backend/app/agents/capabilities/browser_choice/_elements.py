"""The page reduced to a table of things that can be chosen.

This is the whole premise of the capability. A browser agent that *generates* its
next action can emit any string, so the page's text is an instruction channel into
the model and the only defence is telling it not to listen. A browser agent that
*chooses* an entry from a table built server-side from the live DOM cannot act on
an option the page did not put in the table. The prompt still says page text is
data; this is what enforces it.

Everything here is pure - a snapshot in, a table or a bounded candidate set out -
so the part that decides what the model may pick is tested without a browser.
`_page.py` is the thin CDP layer that produces a :class:`Snapshot`, and it is the
only module in this package that needs one.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_LABEL = 80
"""How much of an element's label reaches the model.

A page can put a paragraph in an `aria-label`, and forty of those is the whole
context window spent describing a table nobody reads to the end. Truncated at a
word boundary where one is near, so the label stays a label.
"""

HARD_CANDIDATE_CAP = 200
"""The most elements that may ever be offered as choices in one step.

The decision model's pick-one is capped at 255 options (pydantic/pydantic-ai#8484)
and a request that exceeds it fails rather than degrading, so the ceiling is
enforced here instead of discovered there. 200 leaves headroom for the format to
grow an option without this becoming a second place to remember the cap.
"""


EDITABLE_ROLES = frozenset(
    {"textbox", "search", "email", "password", "number", "tel", "url", "date", "time"}
)
"""The roles `TYPE_TEXT` may be carried out against.

The operation and the target are two independent answers, so a model can pair
`TYPE_TEXT` with a link. Typing begins by focusing the element, and focusing a
link means clicking it - so an incompatible pair does not merely fail, it
performs a *different* action with side effects. Checked before dispatch rather
than discovered afterwards.
"""


@dataclass(frozen=True, slots=True)
class Element:
    """One thing on the page a person could act on.

    `index` is stable only within the snapshot it came from; `path` is what
    survives one. A page that re-renders between the snapshot and the action
    renumbers everything, so an action resolves `path` and checks that what it
    found still describes itself the way the table said it did. Coordinates are
    read from *that* resolution, never from the snapshot - a stale centre is how a
    click lands on whatever moved into the position instead.
    """

    index: int
    role: str
    """What it is, in the accessibility tree's vocabulary: button, link, textbox..."""

    label: str
    """What it says, as a person reads it - the accessible name, already truncated."""

    path: str = ""
    """A CSS selector that resolves to this element alone, as the collector built it.

    Empty only for an element a test constructed. The page layer refuses to act on
    one, because an action it cannot verify is an action on an unknown element.
    """

    value: str | None = None
    """A dropdown's selected option, and nothing else's contents.

    Deliberately not a text field's value. The loop needs to tell a filled field
    from an empty one, which :attr:`filled` answers - and the *contents* would
    reach the decision endpoint in the next step's element table, which is how a
    password the host model had just typed would be disclosed to a third party
    one step after being redacted from the history.

    A dropdown is the exception rather than an inconsistency: its selection is
    one of the options already listed beside it, and without it the loop cannot
    tell a chosen list from an unchosen one.
    """

    filled: bool = False
    """Whether a text field holds anything. Never what."""

    options: tuple[str, ...] = ()
    """A dropdown's choices, for a native `<select>` and nothing else.

    Carried on the element rather than emitted as choosable elements of their
    own, which is the obvious design and the wrong one: a country list is two
    hundred options, and putting them in the table would spend the whole
    candidate cap describing one field. So a dropdown is one row, its choices
    are shown with it, and `SELECT` is answered with a value the way `TYPE_TEXT`
    is - which is also how a person describes it: choose Poland from the list.
    """

    @property
    def editable(self) -> bool:
        """Whether `TYPE_TEXT` can be carried out against this element."""
        return self.role in EDITABLE_ROLES


MAX_PAGE_TEXT = 1_500
"""How much of the page's own words reach the decision model.

Without any, the model cannot tell that the goal has been reached: a price, a
confirmation, "no results" are ordinary text, not interactive elements, so a
browse that had already succeeded could only guess at `DONE`. Bounded because
this is sent on every step, and a long article would be the whole budget spent
describing a page the model has already acted on.
"""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The page at one moment, as the loop sees it."""

    url: str
    title: str
    elements: tuple[Element, ...]
    text: str = ""
    """The page's visible words, bounded, for deciding whether the goal is met."""

    scroll_y: float = 0.0
    scroll_height: float = 0.0
    viewport_height: float = 0.0

    @property
    def at_bottom(self) -> bool:
        """Whether scrolling further would reveal anything.

        The loop reads this to tell "nothing here yet" from "nothing here at all":
        a `SCROLL` chosen at the bottom of a page is a step that will produce the
        identical snapshot, and three of those is how a browse reaches its ceiling
        having done nothing.
        """
        return self.scroll_y + self.viewport_height >= self.scroll_height - 1


def clean_label(raw: str) -> str:
    """One line, bounded, with the page's whitespace and control characters gone.

    Control characters are stripped rather than escaped because this string is
    rendered into a table the model reads and into a frame a browser draws; a
    newline in an element's name would split one row into two, which is a page
    editing the table it is supposed to be described by.
    """
    collapsed = " ".join(raw.split())
    if len(collapsed) <= MAX_LABEL:
        return collapsed
    cut = collapsed[:MAX_LABEL]
    spaced = cut.rsplit(" ", 1)
    # Only honour a word boundary that is actually near the end; a label whose
    # first space is at character 3 would otherwise be truncated to one word.
    if len(spaced) == 2 and len(spaced[0]) >= MAX_LABEL // 2:
        cut = spaced[0]
    return cut.rstrip() + "…"


def candidates(elements: tuple[Element, ...], cap: int) -> tuple[Element, ...]:
    """The elements that may be offered as choices this step, at most `cap` of them.

    Truncation is by document order and nothing else. Ranking by a heuristic -
    proximity to the goal, size, "importance" - would put the decision the
    capability exists to make back into a scoring function nobody can inspect, and
    would make two runs over the same page offer different tables.

    The loop's answer to a page too dense for the cap is to scroll, which produces
    a different viewport and therefore a different set - not to guess which of 400
    links mattered.
    """
    limit = min(cap, HARD_CANDIDATE_CAP)
    return elements[:limit]


def render_table(elements: tuple[Element, ...]) -> str:
    """The candidate set as the text a decision model reads.

    One element per line, index first, so a pick and a row are the same thing in
    two places. A field's current value is shown when it has one, because "the
    search box already says paris" is the difference between typing and moving on.
    """
    if not elements:
        return "(no interactive elements in view)"
    lines = []
    for element in elements:
        row = f"{element.index}. {element.role}: {element.label}"
        if element.value:
            row += f" [selected: {clean_label(element.value)}]"
        elif element.filled:
            # That it has something in it, not what. See `Element.value`.
            row += " [filled]"
        if element.options:
            row += f" [choices: {render_options(element.options)}]"
        lines.append(row)
    return "\n".join(lines)


MAX_COLLECTED_OPTIONS = 200
"""How many of a dropdown's choices are carried out of the page at all.

Larger than :data:`MAX_SHOWN_OPTIONS`, because the count that follows the shown
ones has to mean something and because the model may name a choice it cannot
see. Bounded all the same: a `<select>` can hold every airport in the world, and
an unbounded read of one is a page deciding how much this deployment allocates.
"""

MAX_SHOWN_OPTIONS = 12
"""How many of a dropdown's choices are written into the table.

Enough to recognise what kind of list it is; not a country list rendered in
full on every step. The count that follows is what tells the model the rest are
there, so it can still name one it cannot see.
"""


def render_options(options: tuple[str, ...]) -> str:
    """A dropdown's choices as one bounded phrase."""
    shown = ", ".join(options[:MAX_SHOWN_OPTIONS])
    extra = len(options) - MAX_SHOWN_OPTIONS
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def page_text(raw: str) -> str:
    """The page's visible words, collapsed and bounded, for the decision prompt.

    Bounded from the front: what a page says first is what it is about, and a
    truncation from the end would keep a footer over a heading.
    """
    collapsed = " ".join(raw.split())
    return collapsed[:MAX_PAGE_TEXT]
