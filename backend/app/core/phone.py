"""Phone matching shared by guardrails and the PII service.

Strict grouping avoids treating IDs such as ORD-2026-000417 as phone numbers.
National formats need a configured region; international (+) formats do not.
Both callers check the scan limits before matching; see the guardrails README.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from itertools import islice

import phonenumbers

PHONE_PLACEHOLDER = "[redacted:phone]"
DEFAULT_PHONE_REGIONS = "US, GB, DE, PL"
MAX_PHONE_CHARS = 200_000
MAX_PHONE_DIGITS = 10_000
MAX_PHONE_REGIONS = 16
MAX_PHONE_REGIONS_CHARS = 256
_BUDGET_REGIONS = 4
_DIGIT = re.compile(r"\d")


def parse_phone_regions(raw: str) -> tuple[str, ...]:
    """Normalize and deduplicate codes, rejecting unknown or excessive regions."""
    # Bound allocations before splitting: duplicates and blanks do not count
    # toward the region limit, and a stored draft can be validated repeatedly.
    if len(raw) > MAX_PHONE_REGIONS_CHARS:
        raise ValueError(f"Phone regions must be at most {MAX_PHONE_REGIONS_CHARS} characters")
    regions: list[str] = []
    for part in re.split(r"[,\n]", raw):
        code = part.strip().upper()
        if not code or code in regions:
            continue
        if code not in phonenumbers.SUPPORTED_REGIONS:
            hint = " (the code for the United Kingdom is GB)" if code == "UK" else ""
            raise ValueError(f"'{code}' is not a two-letter ISO 3166 region code{hint}")
        regions.append(code)
    if len(regions) > MAX_PHONE_REGIONS:
        raise ValueError(
            f"At most {MAX_PHONE_REGIONS} regions can be listed, and {len(regions)} are: "
            "each one is another pass over every text, and the text each pass may "
            "read shrinks to keep the total in bounds"
        )
    return tuple(regions)


def phone_limits(regions: Sequence[str]) -> tuple[int, int]:
    """Character and digit ceilings, scaled down for more than four matcher passes."""
    passes = max(_BUDGET_REGIONS, len(regions))
    return MAX_PHONE_CHARS * _BUDGET_REGIONS // passes, MAX_PHONE_DIGITS * _BUDGET_REGIONS // passes


def phone_text_error(text: str, regions: Sequence[str], *, check_digits: bool = True) -> str | None:
    """Refusal reason, or None. The early guardrail check only checks length."""
    chars, digits = phone_limits(regions)
    if len(text) > chars:
        return f"It is longer than {chars:,} characters, the most phone number redaction reads."
    # Stop counting after the first digit beyond the allowance.
    if check_digits and next(islice(_DIGIT.finditer(text), digits, None), None) is not None:
        return f"It holds more than {digits:,} digits, the most phone number redaction reads."
    return None


def _merged(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge duplicate, overlapping and touching matches from different regions."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def redact_phone_numbers(text: str, regions: Sequence[str]) -> tuple[str, int]:
    """Redact and count matches in text the caller has checked with phone_text_error."""
    # No default region means only international (+) numbers parse.
    passes: tuple[str | None, ...] = tuple(regions) or (None,)
    spans: list[tuple[int, int]] = []
    for region in passes:
        for match in phonenumbers.PhoneNumberMatcher(
            text,
            region,
            leniency=phonenumbers.Leniency.STRICT_GROUPING,
            # Never silently stop after rejected candidates; callers bound the work.
            max_tries=sys.maxsize,
        ):
            spans.append((match.start, match.end))
    merged = _merged(spans)
    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.extend((text[cursor:start], PHONE_PLACEHOLDER))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), len(merged)
