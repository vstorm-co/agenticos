"""Phone number redaction - what it scrubs, what it leaves, and which countries it reads.

The detector exists because the harness's PII patterns have no phone number, so
the refusal half matters as much as the match: a date, a timestamp or an order
id that a digit-count regex would have taken must come through untouched.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.capabilities import get, load_builtins
from app.agents.capabilities.guardrails import GuardrailsConfig
from app.agents.capabilities.guardrails._capability import GuardrailBlocked, _edge_detector
from app.agents.capabilities.guardrails._phone import (
    DEFAULT_PHONE_REGIONS,
    MAX_PHONE_DIGITS,
    PHONE_PLACEHOLDER,
    _merged,
    has_too_many_digits,
    parse_phone_regions,
    phone_numbers,
    redact_phone_numbers,
)
from app.core.exceptions import BadRequestError


def _redacted(regions: tuple[str, ...], text: str) -> str:
    verdict = phone_numbers(regions)(text)
    return text if verdict.action == "allow" else str(verdict.replacement)


def test_regions_split_upper_case_and_drop_blanks_and_repeats():
    assert parse_phone_regions("us, gb\nDE, ,US") == ("US", "GB", "DE")
    assert parse_phone_regions("") == ()


def test_an_unknown_region_is_refused():
    with pytest.raises(ValueError, match=r"'XX' is not a two-letter ISO 3166 region code$"):
        parse_phone_regions("US, XX")


def test_uk_is_refused_with_the_code_it_should_have_been():
    with pytest.raises(ValueError, match="United Kingdom is GB"):
        parse_phone_regions("UK")


def test_an_international_number_is_redacted_with_no_region_configured():
    assert _redacted((), "call +48 600 123 456 today") == f"call {PHONE_PLACEHOLDER} today"


def test_a_national_number_needs_its_region():
    text = "call 415-555-0132 today"
    assert _redacted((), text) == text
    assert _redacted(("US",), text) == f"call {PHONE_PLACEHOLDER} today"


_DEFAULT = parse_phone_regions(DEFAULT_PHONE_REGIONS)


@pytest.mark.parametrize(
    "number",
    [
        "415-555-0132",
        "(415) 555-0132",
        "415.555.0132",
        "4155550132",
        "+14155550132",
        "+1 (415) 555-0132",
        "+48 600 123 456",
        "+48600123456",
        "600 123 456",
        "+48 22 123 45 67",
        "+44 20 7946 0958",
        "020 7946 0958",
        "+49 30 1234567",
        "030/1234567",
        "+33 1 23 45 67 89",
        "+81 3-1234-5678",
    ],
)
def test_accepted_formats_are_redacted_with_the_default_regions(number: str):
    assert _redacted(_DEFAULT, f"call {number} today") == f"call {PHONE_PLACEHOLDER} today"


@pytest.mark.parametrize(
    "text",
    [
        "shipped on 2026-10-01",
        "due 01.10.2026",
        "invoice 2026/10/01",
        "created at 1727800000",
        "total $1,299.00",
        "razem 1 299,00 zł",
        "Summe €4.150,00",
        "PLN 12 345,67",
        "order 4471",
        "order #88412",
        "ticket 4471-2290",
        "invoice FV/2026/10/0042",
        "SKU 123-4567",
        "postcode 00-950",
        "tracking 9400111202555842",
        # Each of these is a valid US number when its digits are read without
        # their grouping; `VALID` leniency redacted all three.
        "order ORD-2026-000417",
        "ref 2026-10-0001",
        "id 4155-550132",
        "nothing numeric here",
    ],
)
def test_digits_that_are_not_a_phone_number_are_left_alone(text: str):
    assert phone_numbers(_DEFAULT)(text).action == "allow"


def test_a_bare_digit_run_valid_in_a_listed_country_is_redacted():
    """The documented trade-off: ungrouped digits carry no grouping to check, and
    `123456789` is a valid Polish landline, so listing `PL` takes it."""
    assert _redacted(("US",), "order 123456789") == "order 123456789"
    assert _redacted(("PL",), "order 123456789") == f"order {PHONE_PLACEHOLDER}"


def test_a_number_two_regions_both_match_is_replaced_once():
    """`+1` parses under every region; the spans merge rather than cut twice."""
    assert _redacted(("US", "CA"), "ring +1 415 555 0132.") == f"ring {PHONE_PLACEHOLDER}."


def test_the_count_is_of_placeholders_written_not_of_region_matches():
    """`app/services/ml/pii.py` reports this count, so a number two regions both
    read must count once, and text with nothing in it must count zero."""
    assert redact_phone_numbers("ring +1 415 555 0132 or 415-555-0199", ("US", "CA")) == (
        f"ring {PHONE_PLACEHOLDER} or {PHONE_PLACEHOLDER}",
        2,
    )
    assert redact_phone_numbers("nothing here", _DEFAULT) == ("nothing here", 0)


def test_the_digit_bound_counts_digits_not_characters():
    assert not has_too_many_digits("1" * MAX_PHONE_DIGITS)
    assert has_too_many_digits("1" * (MAX_PHONE_DIGITS + 1))
    assert not has_too_many_digits("no digits " * MAX_PHONE_DIGITS)


def test_a_text_with_too_many_digits_is_blocked_rather_than_read():
    """Repeated numbers kept a span per number per region and the matcher costs
    tens of microseconds a digit, so a long prompt of them could take a worker's
    memory and time. Refused, because returning it unread would pass the numbers on."""
    flood = "+1 415-555-0132 " * (MAX_PHONE_DIGITS // 11 + 1)
    verdict = phone_numbers(_DEFAULT)(flood)
    assert verdict.action == "block"
    assert verdict.message == (
        f"It holds more than {MAX_PHONE_DIGITS:,} digits, the most phone number redaction reads."
    )


def test_a_text_at_the_digit_bound_is_still_redacted():
    text = "1 " * (MAX_PHONE_DIGITS - 10) + "call 415-555-0132"
    assert _redacted(("US",), text).endswith(f"call {PHONE_PLACEHOLDER}")


def test_rejected_candidates_do_not_end_the_scan_early():
    """libphonenumber stops after 65535 rejected candidates by default, which left
    any number after that much padding in place."""
    text = "a1 " * 65536 + "call 415-555-0132"
    assert redact_phone_numbers(text, ("US",)) == ("a1 " * 65536 + f"call {PHONE_PLACEHOLDER}", 1)


def test_an_edge_refuses_text_its_phone_redaction_could_not_read():
    detect = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=True,
        phone_regions=("US",),
        keywords=[],
        edge="input",
    )
    assert detect is not None
    with pytest.raises(GuardrailBlocked) as exc:
        detect("+1 415-555-0132 " * MAX_PHONE_DIGITS)
    assert exc.value.edge == "input"
    assert str(exc.value).startswith("This request was blocked by an input guardrail. It holds")
    assert "415" not in str(exc.value)


def test_overlapping_and_touching_spans_merge_and_separate_ones_do_not():
    assert _merged([(30, 40), (5, 20), (5, 20), (10, 25), (25, 28)]) == [(5, 28), (30, 40)]
    assert _merged([(0, 10), (2, 4)]) == [(0, 10)]
    assert _merged([]) == []


def test_every_number_in_the_text_is_redacted():
    text = "UK 020 7946 0958, DE 030 1234567, PL +48 600 123 456"
    assert _redacted(("GB", "DE"), text) == (
        f"UK {PHONE_PLACEHOLDER}, DE {PHONE_PLACEHOLDER}, PL {PHONE_PLACEHOLDER}"
    )


def test_the_default_regions_are_known():
    assert parse_phone_regions(DEFAULT_PHONE_REGIONS) == ("US", "GB", "DE", "PL")


def test_a_stored_config_without_the_field_reads_the_default():
    """Specs published before the field existed hold no `phone_regions` key."""
    config = GuardrailsConfig.model_validate({"redact_pii_out": True})
    assert config.phone_regions == DEFAULT_PHONE_REGIONS


def test_a_config_with_an_unknown_region_does_not_validate():
    with pytest.raises(ValidationError, match="United Kingdom is GB"):
        GuardrailsConfig(phone_regions="UK")


def test_publish_names_the_field_with_the_unknown_region():
    load_builtins()
    with pytest.raises(BadRequestError) as exc:
        get("guardrails").validate_config({"phone_regions": "US, XX"})
    fields = exc.value.details["fields"]
    assert any("phone_regions" in str(problem) for problem in fields)


def test_the_pii_flag_redacts_a_phone_beside_the_harness_patterns():
    """The issue's message: the phone number was the one thing left in it."""
    detect = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=True,
        phone_regions=("US",),
        keywords=[],
        edge="output",
    )
    assert detect is not None
    verdict = detect(
        "Reach jane@example.com on 415-555-0132, card 4111 1111 1111 1111, SSN 123-45-6789"
    )
    assert verdict.action == "replace"
    cleaned = str(verdict.replacement)
    assert "415-555-0132" not in cleaned
    assert PHONE_PLACEHOLDER in cleaned
    for kept_out in ("jane@example.com", "4111", "123-45-6789"):
        assert kept_out not in cleaned


def test_the_harness_patterns_run_before_the_phone_detector():
    """With PL configured `123-45-6789` is a valid Polish number, so order decides
    what the redaction says it removed: it is an SSN, and must be labelled one."""
    detect = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=True,
        phone_regions=("PL",),
        keywords=[],
        edge="input",
    )
    assert detect is not None
    cleaned = str(detect("SSN 123-45-6789").replacement)
    assert cleaned == "SSN [redacted:us_ssn]"


def test_an_edge_without_pii_redaction_leaves_phone_numbers():
    detect = _edge_detector(
        redact_secrets_on=True,
        redact_pii_on=False,
        phone_regions=("US",),
        keywords=[],
        edge="input",
    )
    assert detect is not None
    assert detect("call 415-555-0132").action == "allow"
