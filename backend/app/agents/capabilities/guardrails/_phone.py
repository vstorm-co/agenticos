"""Phone numbers - the personal data the harness's PII patterns do not cover.

`pydantic-ai-harness` ships email, IBAN, card and US SSN patterns and no phone
number, so a number reached the model and the reader while the personal data
around it was scrubbed. A phone number cannot join that set as an `extra`
regex: its shape alone does not separate it from an order id, a date or a Unix
timestamp, which is the job Luhn and mod-97 do for a card and an IBAN. This
uses libphonenumber's matcher at `Leniency.VALID` instead, which accepts a
candidate only when it is a real number in the numbering plan of its country.

**Which countries.** A number written with `+` names its own country and is
matched whatever is configured. A national number (`415-555-0132`,
`030 1234567`) only has a meaning relative to a country, so it is read against
each configured region. Every region added also widens what a bare run of
digits can be: `123456789` is a valid Polish landline, so with `PL` configured a
nine-digit order id is redacted too. The list is a field rather than a constant
because the right trade-off depends on the markets an agent serves.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

import phonenumbers
from pydantic_ai_harness.guardrails import GuardrailResult

PHONE_PLACEHOLDER = "[redacted:phone]"
"""The harness's `[redacted:{name}]` shape, so a phone redaction reads like the rest."""

DEFAULT_PHONE_REGIONS = "US, GB, DE, PL"

_REGION_SPLIT = re.compile(r"[,\n]")


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


def phone_numbers(regions: Sequence[str]) -> Callable[[str], GuardrailResult]:
    """A detector that rewrites valid phone numbers out of text.

    Args:
        regions: Countries whose national formats are read. Empty matches only
            numbers written in international form, with `+`.
    """
    # `None` is libphonenumber's "no default region": only `+` numbers parse.
    passes: tuple[str | None, ...] = tuple(regions) or (None,)

    def detect(text: str) -> GuardrailResult:
        spans: list[tuple[int, int]] = []
        for region in passes:
            for match in phonenumbers.PhoneNumberMatcher(
                text, region, leniency=phonenumbers.Leniency.VALID
            ):
                spans.append((match.start, match.end))
        if not spans:
            return GuardrailResult.allow()

        # Two regions can match the same number, or overlapping parts of one, so
        # the spans are merged before anything is cut.
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        pieces: list[str] = []
        cursor = 0
        for start, end in merged:
            pieces.extend((text[cursor:start], PHONE_PLACEHOLDER))
            cursor = end
        pieces.append(text[cursor:])
        return GuardrailResult.replace("".join(pieces))

    return detect
