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


@dataclass(frozen=True, slots=True)
class Element:
    """One thing on the page a person could act on.

    `index` is stable only within the snapshot it came from. A page that re-renders
    between the snapshot and the click renumbers everything, which is why an
    operation is carried out against coordinates captured *with* the index rather
    than re-resolved from it.
    """

    index: int
    role: str
    """What it is, in the accessibility tree's vocabulary: button, link, textbox..."""

    label: str
    """What it says, as a person reads it - the accessible name, already truncated."""

    x: float
    y: float
    """Viewport coordinates of its centre, in CSS pixels."""

    value: str | None = None
    """What a field currently holds, so the loop can tell empty from filled."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The page at one moment, as the loop sees it."""

    url: str
    title: str
    elements: tuple[Element, ...]
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
            row += f" [currently: {clean_label(element.value)}]"
        lines.append(row)
    return "\n".join(lines)
