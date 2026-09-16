"""Finding personal data in text, on the detectors the guardrails already use.

FA-073 asks for personal data detection as a service a caller reaches directly.
The detectors exist - `app/agents/capabilities/guardrails` configures the same
ones onto an agent's edges - so the service is the same vocabulary reached
without an agent, rather than a second opinion about what personal data is. Two
vocabularies would be worse than one: an organization would redact one set of
categories inside a run and report another outside it.

**What comes back is a count and a redaction, not the matches.** A span would be
more useful to a caller drawing highlights, and the library does not expose one:
its detectors answer with rewritten text. Recovering offsets would mean reading
its private pattern table and re-running the checksums it applies, which is
exactly the kind of copy that silently stops agreeing with the original. So the
contract is honest about the shape available - per category, how many were
found, and the text with each match replaced - and a caller that needs to mark
up the original has the replaced text to align against.

**Category names are the library's**, so a category added upstream reaches this
service and the guardrails together, and `known_categories` is what the API
offers rather than a list typed here that would go stale.
"""

from __future__ import annotations

import secrets
import string
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai_harness.guardrails.detectors import DEFAULT_PII_PATTERNS, personal_data

from app.core.field_errors import refused_field

MAX_TEXT_CHARS = 200_000
"""How much text one call may scan.

Every pattern here is linear in the text and there are four of them, but the
scan is synchronous work on the event loop, so the ceiling is about what one
request may do to a worker rather than about the regexes.
"""

PLACEHOLDER = "[redacted:{name}]"
"""What a match is replaced with. The library substitutes the category name."""


@dataclass(frozen=True)
class CategoryCount:
    """How many matches one category accounted for."""

    category: str
    count: int


@dataclass(frozen=True)
class PiiReport:
    """What a scan found, and the text with it taken out."""

    counts: tuple[CategoryCount, ...]
    total: int
    redacted_text: str


def known_categories() -> tuple[str, ...]:
    """The categories this deployment can detect, in the order they are applied."""
    return tuple(DEFAULT_PII_PATTERNS)


def scan(text: str, *, categories: Sequence[str] | None = None) -> PiiReport:
    """Count the personal data in `text` per category, and redact it.

    Args:
        text: The text to scan. Longer than `MAX_TEXT_CHARS` is refused.
        categories: Restrict the scan to these categories. `None` scans every
            one the deployment knows.

    Returns:
        The per-category counts - including the zeros, so a caller can see that
        a category was looked for and found nothing - the total, and the text
        with every match replaced.

    Raises:
        BadRequestError: If the text is too long, or a category is not one this
            deployment detects. Both name the field, because both are the
            caller's input rather than a state of the deployment.
    """
    if len(text) > MAX_TEXT_CHARS:
        raise refused_field(
            "text",
            f"One scan reads at most {MAX_TEXT_CHARS} characters; split the document and "
            "scan the parts.",
        )
    selected = _selected(categories)
    counts = tuple(CategoryCount(category=name, count=_count(text, name)) for name in selected)
    detector = personal_data(only=list(selected), placeholder=PLACEHOLDER)
    verdict = detector(text)
    redacted = verdict.replacement if isinstance(verdict.replacement, str) else text
    return PiiReport(
        counts=counts,
        total=sum(entry.count for entry in counts),
        redacted_text=redacted,
    )


def _selected(categories: Sequence[str] | None) -> tuple[str, ...]:
    """The categories to scan, in the library's own application order.

    The order matters to the result and not only to tidiness: `iban` is applied
    before `credit_card` upstream so that the digit groups of a spaced account
    number are not claimed as a card, and a caller listing the two the other way
    round must not change that.
    """
    known = known_categories()
    if categories is None:
        return known
    unknown = sorted(set(categories) - set(known))
    if unknown:
        raise refused_field(
            "categories",
            f"This deployment detects {', '.join(known)}; it does not detect {', '.join(unknown)}.",
        )
    chosen = set(categories)
    if not chosen:
        raise refused_field(
            "categories", "Name at least one category, or omit the field to scan all."
        )
    return tuple(name for name in known if name in chosen)


def _count(text: str, category: str) -> int:
    """How many matches one category has in `text`.

    Counted by redacting with a marker instead of the readable placeholder and
    counting the markers. The marker is sixteen random letters between two
    private-use characters, so a caller cannot submit text that inflates its own
    count, and the occurrences already in the text are subtracted anyway.
    """
    marker = "" + "".join(secrets.choice(string.ascii_uppercase) for _ in range(16)) + ""
    verdict = personal_data(only=[category], placeholder=marker)(text)
    if not isinstance(verdict.replacement, str):
        return 0
    return verdict.replacement.count(marker) - text.count(marker)
