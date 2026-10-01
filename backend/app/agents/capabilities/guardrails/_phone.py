"""Phone numbers - the personal data the harness's PII patterns do not cover.

`pydantic-ai-harness` ships email, IBAN, card and US SSN patterns and no phone
number, so a number reached the model and the reader while the personal data
around it was scrubbed. A phone number cannot join that set as an `extra`
regex: its shape alone does not separate it from an order id, a date or a Unix
timestamp, which is the job Luhn and mod-97 do for a card and an IBAN. This
uses libphonenumber's matcher at `Leniency.STRICT_GROUPING` instead, which
accepts a candidate only when it is a real number in the numbering plan of its
country *and* any separators in it fall where that country groups its digits.
`VALID` alone checks the digits and not the grouping, so it read the
`2026-000417` of `ORD-2026-000417` as the Washington number 202-600-0417.

**Which countries.** A number written with `+` names its own country and is
matched whatever is configured. A national number (`415-555-0132`,
`030 1234567`) only has a meaning relative to a country, so it is read against
each configured region. Every region added also widens what a bare run of
digits can be: `123456789` is a valid Polish landline, so with `PL` configured a
nine-digit order id is redacted too. The list is a field rather than a constant
because the right trade-off depends on the markets an agent serves.

**How much text.** The matcher is pure Python and its cost follows the digits in
the text: a prompt of `1/2/3 1/2/3 ...` costs about 70 us a digit across the four
default regions, and a prompt of repeated numbers keeps a span per number per
region. A text with more than `MAX_PHONE_DIGITS` digits is refused with a `block`
verdict rather than read, and the matcher's own give-up after `max_tries` rejected
candidates is lifted: both leave a number in place, and a redactor that has not
read the whole text must not let it through as if it had.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterable, Sequence
from itertools import islice

import phonenumbers
from pydantic_ai_harness.guardrails import GuardrailResult

PHONE_PLACEHOLDER = "[redacted:phone]"
"""The harness's `[redacted:{name}]` shape, so a phone redaction reads like the rest."""

DEFAULT_PHONE_REGIONS = "US, GB, DE, PL"

MAX_PHONE_DIGITS = 10_000
"""The most digits a text may hold for the phone detector to read it.

About 0.7 s of matching at the four default regions in the worst text measured,
and room for some 900 phone numbers - far more than a prompt, an answer or a tool
result an agent works with holds.
"""

_REGION_SPLIT = re.compile(r"[,\n]")
_DIGIT = re.compile(r"\d")


def parse_phone_regions(raw: str) -> tuple[str, ...]:
    """The region codes in a delimited string, upper-cased, deduplicated, in order.

    Raises:
        ValueError: For a code libphonenumber does not know. Refused rather than
            skipped, because an unknown region matches no national number and the
            mistake would otherwise show up only as a phone number left in place.
            `UK` is the common one; the ISO 3166 code is `GB`.
    """
    regions: list[str] = []
    for part in _REGION_SPLIT.split(raw):
        code = part.strip().upper()
        if not code or code in regions:
            continue
        if code not in phonenumbers.SUPPORTED_REGIONS:
            hint = " (the code for the United Kingdom is GB)" if code == "UK" else ""
            raise ValueError(f"'{code}' is not a two-letter ISO 3166 region code{hint}")
        regions.append(code)
    return tuple(regions)


def _merged(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """The spans in order, with any that overlap or touch combined into one.

    Two regions can match the same number, or overlapping parts of one, and
    cutting each span separately would print two placeholders or cut into text
    an earlier span already replaced.
    """
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def has_too_many_digits(text: str) -> bool:
    """Whether `text` holds more than `MAX_PHONE_DIGITS` digits.

    Stops counting at the bound, so a long text costs a regex scan and no more.
    """
    return next(islice(_DIGIT.finditer(text), MAX_PHONE_DIGITS, None), None) is not None


def redact_phone_numbers(text: str, regions: Sequence[str]) -> tuple[str, int]:
    """`text` with each valid phone number replaced, and how many were replaced.

    Reads the whole text however long it is; a caller taking text from a user
    checks `has_too_many_digits` first.

    The count is of placeholders written, so two regions matching one number
    count it once. `app/services/ml/pii.py` reports it; the guardrail only needs
    the text.

    Args:
        text: The text to read.
        regions: Countries whose national formats are read. Empty matches only
            numbers written in international form, with `+`.
    """
    # `None` is libphonenumber's "no default region": only `+` numbers parse.
    passes: tuple[str | None, ...] = tuple(regions) or (None,)
    spans: list[tuple[int, int]] = []
    for region in passes:
        for match in phonenumbers.PhoneNumberMatcher(
            text,
            region,
            leniency=phonenumbers.Leniency.STRICT_GROUPING,
            # Its default, 65535, stops quietly part-way through a text padded with
            # rejected candidates and leaves every number after them in place.
            # `MAX_PHONE_DIGITS` is what bounds the work instead.
            max_tries=sys.maxsize,
        ):
            spans.append((match.start, match.end))
    if not spans:
        return text, 0

    merged = _merged(spans)
    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.extend((text[cursor:start], PHONE_PLACEHOLDER))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), len(merged)


def phone_numbers(regions: Sequence[str]) -> Callable[[str], GuardrailResult]:
    """A detector that rewrites valid phone numbers out of text.

    Returns a `block` verdict, with the reason as its message, for a text with
    more than `MAX_PHONE_DIGITS` digits.

    Args:
        regions: Countries whose national formats are read. Empty matches only
            numbers written in international form, with `+`.
    """

    def detect(text: str) -> GuardrailResult:
        if has_too_many_digits(text):
            return GuardrailResult.block(
                f"It holds more than {MAX_PHONE_DIGITS:,} digits, "
                "the most phone number redaction reads."
            )
        redacted, found = redact_phone_numbers(text, regions)
        return GuardrailResult.replace(redacted) if found else GuardrailResult.allow()

    return detect
