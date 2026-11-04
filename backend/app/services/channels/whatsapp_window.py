"""WhatsApp's 24-hour customer-service window, as pure rules (#2076).

A business may send free-form messages to a customer only for 24 hours after the
customer's last message. These functions say whether that window is open and how an
answer fits a late-answer template. They do no I/O; the customer record that feeds
them is `whatsapp_customers.WindowStore`.
"""

import re
from datetime import datetime, timedelta
from typing import Literal

from app.services.channels.whatsapp_format import utf16_units
from app.services.channels.whatsapp_interactive import shorten

WINDOW = timedelta(hours=24)
WINDOW_MARGIN = timedelta(minutes=5)
"""The window is read as closed this early: a send that takes a while must not land after Meta's cutoff."""

TEMPLATE_BODY_MAX = 1024
"""Meta's limit on a template body, counted in UTF-16 units with the fixed text and the parameter together."""

PREVIEW_UNITS = 200
PREVIEW_ENDING = " Reply to see the full answer."
MAX_FIXED_UNITS = TEMPLATE_BODY_MAX - (PREVIEW_UNITS + utf16_units(PREVIEW_ENDING))
"""The most fixed text a template may carry and still hold a preview."""

CLAIM_LEASE = timedelta(minutes=5)
"""How long a claim on a held run keeps other processes off it; a crash is retried after this."""

FILES_NOT_DELIVERED = (
    "(A chart or file that came with this answer could not be sent after the wait.)"
)

type UndeliveredReason = Literal["window_no_template", "window_template_failed"]

_WHITESPACE = re.compile(r"\s+")


def window_open(
    *, last_inbound_at: datetime | None, closed_at: datetime | None, now: datetime
) -> bool:
    """Whether a free-form message may be sent to the customer now.

    A closure marked in the same second as the customer's latest message does not
    close the window: Meta stamps messages in whole seconds, so the message is
    taken as the later event.
    """
    if last_inbound_at is None:
        return False
    if now >= last_inbound_at + WINDOW - WINDOW_MARGIN:
        return False
    return closed_at is None or closed_at <= last_inbound_at


def closure_is_news(
    *, last_inbound_at: datetime | None, closed_at: datetime | None, at: datetime
) -> bool:
    """Whether a closure at `at` says something the record does not already.

    A closure older than the customer's latest message describes a window that has
    since been reopened (statuses trail by minutes), and a closure already marked
    since that message adds nothing. A closure marked in the same second as the
    message has been superseded by it, so a later closure is news.
    """
    if last_inbound_at is not None and at <= last_inbound_at:
        return False
    return closed_at is None or (last_inbound_at is not None and closed_at <= last_inbound_at)


def flatten(text: str) -> str:
    """One line: every run of whitespace becomes one space (a template parameter refuses breaks and tabs)."""
    return _WHITESPACE.sub(" ", text).strip()


def fits(text: str, *, fixed_length: int, has_files: bool) -> bool:
    """Whether the whole answer fits the template's parameter, measured on the flattened text."""
    if has_files:
        return False
    units = utf16_units(flatten(text))
    return units > 0 and units + fixed_length <= TEMPLATE_BODY_MAX


def preview(text: str) -> str:
    """The start of the answer on one line, with an invitation to reply for the rest."""
    return (shorten(flatten(text), PREVIEW_UNITS) + PREVIEW_ENDING).strip()
