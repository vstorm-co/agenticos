"""Phone number redaction - what it scrubs, what it leaves, and which countries it reads.

The detector exists because the harness's PII patterns have no phone number, so
the refusal half matters as much as the match: a date, a timestamp or an order
id that a digit-count regex would have taken must come through untouched.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from pydantic_ai_harness.guardrails import GuardrailResult

from app.agents.capabilities import get, load_builtins
from app.agents.capabilities.guardrails import GuardrailsConfig
from app.agents.capabilities.guardrails import _capability as capability_module
from app.agents.capabilities.guardrails._capability import (
    GuardrailBlocked,
    TextDetector,
    _edge_detector,
    phone_numbers,
)
from app.core.exceptions import BadRequestError
from app.core.phone import (
    DEFAULT_PHONE_REGIONS,
    MAX_PHONE_CHARS,
    MAX_PHONE_DIGITS,
    MAX_PHONE_REGIONS,
    MAX_PHONE_REGIONS_CHARS,
    PHONE_PLACEHOLDER,
    _merged,
    parse_phone_regions,
    phone_limits,
    phone_text_error,
    redact_phone_numbers,
)


def _pii_edge(
    regions: tuple[str, ...] = ("US",),
    *,
    edge: str = "input",
    secrets: bool = False,
    pii: bool = True,
) -> TextDetector:
    detector = _edge_detector(
        redact_secrets_on=secrets,
        redact_pii_on=pii,
        phone_regions=regions,
        keywords=[],
        edge=edge,
    )
    assert detector is not None
    return detector


def _redacted(regions: tuple[str, ...], text: str) -> str:
    verdict = phone_numbers(regions)(text)
    return text if verdict.action == "allow" else str(verdict.replacement)


def test_regions_split_upper_case_and_drop_blanks_and_repeats():
    assert parse_phone_regions("us, gb\nDE, ,US") == ("US", "GB", "DE")
    assert parse_phone_regions("") == ()


def test_regions_accept_the_character_limit():
    assert parse_phone_regions("us".ljust(MAX_PHONE_REGIONS_CHARS)) == ("US",)


@pytest.mark.parametrize("fragment", ["US,", ",\n", " ", "X"])
def test_oversized_regions_are_refused_before_splitting(fragment: str):
    raw = (fragment * (MAX_PHONE_REGIONS_CHARS + 1))[: MAX_PHONE_REGIONS_CHARS + 1]
    with (
        patch("app.core.phone.re.split", side_effect=AssertionError("must not split")),
        pytest.raises(ValueError, match=f"at most {MAX_PHONE_REGIONS_CHARS} characters"),
    ):
        parse_phone_regions(raw)


def test_validation_refuses_a_large_stored_region_setting():
    load_builtins()
    # Repeated valid codes used to allocate millions of strings before deduplication.
    raw = "US," * (16 * 1024 * 1024 // 3)
    with (
        patch("app.core.phone.re.split", side_effect=AssertionError("must not split")),
        pytest.raises(BadRequestError) as exc,
    ):
        get("guardrails").validate_config({"phone_regions": raw})
    assert any(
        "phone_regions" in str(problem)
        and f"at most {MAX_PHONE_REGIONS_CHARS} characters" in str(problem)
        for problem in exc.value.details["fields"]
    )


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
    assert phone_text_error("1" * MAX_PHONE_DIGITS, _DEFAULT) is None
    assert phone_text_error("1" * (MAX_PHONE_DIGITS + 1), _DEFAULT) is not None
    assert phone_text_error("no digits " * MAX_PHONE_DIGITS, _DEFAULT) is None


@pytest.mark.parametrize(
    "text,reason",
    [
        (
            "+1 415-555-0132 " * (MAX_PHONE_DIGITS // 11 + 1),
            f"holds more than {MAX_PHONE_DIGITS:,} digits",
        ),
        ("(" * (MAX_PHONE_CHARS + 1), f"is longer than {MAX_PHONE_CHARS:,} characters"),
    ],
    ids=["digits", "characters"],
)
def test_text_over_either_limit_is_blocked(text: str, reason: str):
    verdict = phone_numbers(_DEFAULT)(text)
    assert verdict.action == "block"
    assert verdict.message == f"It {reason}, the most phone number redaction reads."


@pytest.mark.parametrize(
    "text",
    [
        "1 " * (MAX_PHONE_DIGITS - 10) + "call 415-555-0132",
        "(" * (MAX_PHONE_CHARS - len(" call 415-555-0132")) + " call 415-555-0132",
    ],
    ids=["digits", "characters"],
)
def test_text_at_either_limit_is_still_redacted(text: str):
    assert _redacted(("US",), text).endswith(f"call {PHONE_PLACEHOLDER}")


def test_rejected_candidates_do_not_end_the_scan_early():
    """libphonenumber stops after 65535 rejected candidates by default, which left
    any number after that much padding in place."""
    text = "a1 " * 65536 + "call 415-555-0132"
    assert redact_phone_numbers(text, ("US",)) == ("a1 " * 65536 + f"call {PHONE_PLACEHOLDER}", 1)


def test_an_edge_refuses_text_its_phone_redaction_could_not_read():
    detect = _pii_edge()
    with pytest.raises(GuardrailBlocked) as exc:
        detect("+1 415-555-0132 " * MAX_PHONE_DIGITS)
    assert exc.value.edge == "input"
    assert str(exc.value).startswith("This request was blocked by an input guardrail. It holds")
    assert "415" not in str(exc.value)


def test_an_edge_refuses_a_long_text_before_any_redactor_reads_it(
    monkeypatch: pytest.MonkeyPatch,
):
    """The phone detector refuses it anyway, and the harness patterns ahead of it
    took some 30 s to scan a prompt the size of a request body first."""

    def unread(text: str) -> GuardrailResult:
        raise AssertionError("a redactor read text the edge refuses")

    monkeypatch.setattr(capability_module, "redact_secrets", unread)
    monkeypatch.setattr(capability_module, "redact_personal_data", unread)
    detect = _pii_edge(edge="tool_result", secrets=True)
    with pytest.raises(GuardrailBlocked) as exc:
        detect("x " * MAX_PHONE_CHARS)
    assert exc.value.edge == "tool_result"
    assert str(exc.value).endswith(
        f"It is longer than {MAX_PHONE_CHARS:,} characters, the most phone number redaction reads."
    )


def test_an_edge_without_pii_redaction_reads_a_long_text():
    """The length bound is the phone detector's, so an edge that does not run it
    keeps reading a long text as it did."""
    detect = _pii_edge(secrets=True, pii=False)
    assert detect("x " * MAX_PHONE_CHARS).action == "allow"


_SIXTEEN = (
    "US",
    "GB",
    "DE",
    "PL",
    "FR",
    "IT",
    "ES",
    "NL",
    "BE",
    "AT",
    "CH",
    "SE",
    "NO",
    "DK",
    "FI",
    "IE",
)


def test_the_limits_are_shared_out_over_more_than_four_regions():
    """Each region is a full pass of the matcher, so the text a pass may read
    shrinks as passes are added and the total stays the four-region one."""
    for regions in ((), ("US",), _DEFAULT):
        assert phone_limits(regions) == (MAX_PHONE_CHARS, MAX_PHONE_DIGITS)
    assert len(_SIXTEEN) == MAX_PHONE_REGIONS
    assert phone_limits(_SIXTEEN) == (MAX_PHONE_CHARS // 4, MAX_PHONE_DIGITS // 4)


def test_more_regions_block_a_text_the_default_four_read():
    """Sixteen passes over a text with the four-region allowance of digits took
    about 2.6 s; the allowance is a quarter of it there."""
    detect = phone_numbers(_SIXTEEN)
    digits = "1/2/3 " * (phone_limits(_SIXTEEN)[1] // 3 + 1)
    assert phone_numbers(_DEFAULT)(digits).action != "block"
    assert detect(digits).message == (
        f"It holds more than {MAX_PHONE_DIGITS // 4:,} digits, the most phone number redaction reads."
    )
    long_text = "(" * (phone_limits(_SIXTEEN)[0] + 1)
    assert phone_numbers(_DEFAULT)(long_text).action == "allow"
    assert detect(long_text).message == (
        f"It is longer than {MAX_PHONE_CHARS // 4:,} characters, the most phone number redaction reads."
    )


def test_an_edge_refuses_early_at_its_own_regions_limit():
    detect = _pii_edge(_SIXTEEN)
    with pytest.raises(GuardrailBlocked, match=f"longer than {MAX_PHONE_CHARS // 4:,} characters"):
        detect("x " * MAX_PHONE_CHARS)


def test_more_regions_than_the_bound_are_refused():
    """All 245 regions libphonenumber knows took 40 s on one prompt, and at that
    count the shared-out limits would refuse nearly every text at run time."""
    assert parse_phone_regions(", ".join(_SIXTEEN)) == _SIXTEEN
    with pytest.raises(
        ValueError, match=f"At most {MAX_PHONE_REGIONS} regions can be listed, and 17 are"
    ):
        parse_phone_regions(", ".join((*_SIXTEEN, "PT")))


def test_publish_refuses_more_regions_than_the_bound():
    load_builtins()
    with pytest.raises(BadRequestError) as exc:
        get("guardrails").validate_config({"phone_regions": ", ".join((*_SIXTEEN, "PT"))})
    assert any("phone_regions" in str(problem) for problem in exc.value.details["fields"])


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
    detect = _pii_edge(edge="output")
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
    detect = _pii_edge(("PL",))
    cleaned = str(detect("SSN 123-45-6789").replacement)
    assert cleaned == "SSN [redacted:us_ssn]"


def test_guardrails_count_digits_after_other_pii_has_been_redacted():
    text = "123-45-6789 " * (MAX_PHONE_DIGITS // 9 + 1) + "call 415-555-0132"
    verdict = _pii_edge()(text)
    assert verdict.action == "replace"
    assert str(verdict.replacement).endswith(f"call {PHONE_PLACEHOLDER}")
    assert "123-45-6789" not in str(verdict.replacement)


def test_an_edge_without_pii_redaction_leaves_phone_numbers():
    detect = _pii_edge(secrets=True, pii=False)
    assert detect("call 415-555-0132").action == "allow"
