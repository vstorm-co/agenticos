"""WhatsApp reply buttons and lists for a question or an approval, without the I/O (#2076).

Every limit is counted in UTF-16 code units, as the rest of the channel counts them.

Meta's interactive messages have hard limits: at most three reply buttons with
20-character titles, or a list of at most ten rows with 24-character titles. This
module fits a prompt's choices into one of them, or says they do not fit.
"""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from typing import Any

from app.services.channels.base import ChannelChoice
from app.services.channels.whatsapp_format import cluster_ends, utf16_units

BUTTON_TITLE_MAX = 20
MAX_BUTTONS = 3
BUTTON_BODY_MAX = 1024
ROW_TITLE_MAX = 24
ROW_DESCRIPTION_MAX = 72
MAX_ROWS = 10
LIST_BODY_MAX = 4096

LIST_BUTTON = "Choose"
CHOOSE_BELOW = "Choose an answer below."
_ELLIPSIS = "…"


@dataclass(frozen=True)
class InteractivePlan:
    """What to send: optional ordinary text first, then the interactive object."""

    preamble: str | None
    interactive: dict[str, Any]


def shorten(label: str, limit: int) -> str:
    """The label as it is when it fits `limit` UTF-16 units, else cut on a character boundary and ended with `…`."""
    if utf16_units(label) <= limit:
        return label
    prefix = [0, *accumulate(utf16_units(char) for char in label)]
    ends = cluster_ends(label)
    fits = bisect_right(ends, limit - utf16_units(_ELLIPSIS), key=lambda end: prefix[end])
    return label[: ends[fits - 1] if fits else 0].rstrip() + _ELLIPSIS


def unique_titles(labels: list[str], limit: int) -> list[str]:
    """Titles within `limit` that differ from each other; a repeat gets ` (2)`, ` (3)` and so on."""
    seen: set[str] = set()
    titles: list[str] = []
    for label in labels:
        title = shorten(label, limit)
        count = 1
        while title in seen:
            count += 1
            suffix = f" ({count})"
            title = shorten(label, limit - len(suffix)) + suffix
        seen.add(title)
        titles.append(title)
    return titles


def plan_interactive(body: str, choices: list[ChannelChoice]) -> InteractivePlan | None:
    """Fit a prompt's choices into reply buttons or a list; `None` when they fit neither.

    A body over the type's limit goes first as ordinary text, and the interactive
    message carries a short pointer instead.
    """
    if not choices or len(choices) > MAX_ROWS:
        return None
    labels = [choice.label for choice in choices]
    buttons = len(choices) <= MAX_BUTTONS and all(
        utf16_units(label) <= BUTTON_TITLE_MAX for label in labels
    )
    limit = BUTTON_BODY_MAX if buttons else LIST_BODY_MAX
    preamble = None if utf16_units(body) <= limit else body
    text = body if preamble is None else CHOOSE_BELOW
    if buttons:
        titles = unique_titles(labels, BUTTON_TITLE_MAX)
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": choice.value, "title": title}}
                    for choice, title in zip(choices, titles, strict=True)
                ]
            },
        }
        return InteractivePlan(preamble=preamble, interactive=interactive)
    rows: list[dict[str, str]] = []
    for choice, title in zip(choices, unique_titles(labels, ROW_TITLE_MAX), strict=True):
        row = {"id": choice.value, "title": title}
        if title != choice.label:
            row["description"] = shorten(choice.label, ROW_DESCRIPTION_MAX)
        rows.append(row)
    interactive = {
        "type": "list",
        "body": {"text": text},
        "action": {"button": LIST_BUTTON, "sections": [{"title": "Choices", "rows": rows}]},
    }
    return InteractivePlan(preamble=preamble, interactive=interactive)
