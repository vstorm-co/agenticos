"""The personal-data detection service.

What matters here is the contract a caller integrates against: every category
asked for is reported, including the ones that matched nothing; the count is the
number of matches and not the number of categories; and the redacted text says
which category each hole was.

The detectors themselves belong to `pydantic-ai-harness` and are tested there.
What is tested here is that this service reports what they found - and the
checks they apply, since a run of digits reported as a payment card would be a
service nobody could use.
"""

from __future__ import annotations

import pytest

from app.agents.capabilities.guardrails._phone import MAX_PHONE_CHARS, MAX_PHONE_DIGITS
from app.core.exceptions import BadRequestError
from app.services.ml import pii


def test_the_known_categories_are_the_librarys_own() -> None:
    assert set(pii.known_categories()) >= {"email", "iban", "credit_card", "us_ssn"}


def test_phone_is_offered_and_applied_after_the_librarys_patterns() -> None:
    """The guardrails' order: a card or an SSN is a placeholder before the phone pass."""
    assert pii.known_categories()[-1] == "phone"


def test_a_national_number_in_a_default_region_is_found_counted_and_replaced() -> None:
    """The case a `redact_pii_*` edge already redacted and this service returned unchanged."""
    report = pii.scan("call 415-555-0132 about it")

    assert {count.category: count.count for count in report.counts}["phone"] == 1
    assert report.total == 1
    assert report.redacted_text == "call [redacted:phone] about it"


def test_a_number_written_with_a_country_code_is_found_outside_the_default_regions() -> None:
    report = pii.scan("ring +33 1 42 68 53 00", categories=["phone"])

    assert report.redacted_text == "ring [redacted:phone]"


def test_a_national_number_outside_the_default_regions_is_left_alone() -> None:
    """`01 42 68 53 00` is a Paris number, and FR is not a default region."""
    report = pii.scan("ring 01 42 68 53 00", categories=["phone"])

    assert report.total == 0


def test_an_order_id_is_not_reported_as_a_phone_number() -> None:
    report = pii.scan("order ORD-2026-000417 shipped", categories=["phone"])

    assert report.total == 0


def test_phone_and_the_librarys_categories_are_counted_and_redacted_together() -> None:
    report = pii.scan("ada@example.com, 415-555-0132, card 4111111111111111")

    found = {count.category: count.count for count in report.counts}
    assert (found["email"], found["phone"], found["credit_card"]) == (1, 1, 1)
    assert report.total == 3
    assert report.redacted_text == (
        "[redacted:email], [redacted:phone], card [redacted:credit_card]"
    )


def test_a_scan_narrowed_away_from_phone_leaves_the_number() -> None:
    report = pii.scan("415-555-0132 or ada@example.com", categories=["email"])

    assert [count.category for count in report.counts] == ["email"]
    assert report.redacted_text == "415-555-0132 or [redacted:email]"


def test_text_with_more_digits_than_the_phone_matcher_reads_is_refused() -> None:
    """The matcher costs tens of microseconds a digit, and the scan runs on the event loop."""
    with pytest.raises(BadRequestError) as caught:
        pii.scan("1/2/3 " * MAX_PHONE_DIGITS)

    assert caught.value.details is not None
    assert caught.value.details["fields"][0]["field"] == "text"


def test_the_text_ceiling_is_within_what_the_phone_matcher_reads() -> None:
    """The scan checks the phone matcher's digit bound but not its length bound,
    because this ceiling already sits inside it. Raising it past the matcher's
    would let a long text without digits hold the event loop."""
    assert pii.MAX_TEXT_CHARS <= MAX_PHONE_CHARS


def test_the_digit_ceiling_does_not_apply_to_a_scan_without_phone() -> None:
    report = pii.scan("1/2/3 " * MAX_PHONE_DIGITS, categories=["email"])

    assert report.total == 0


def test_a_planted_phone_placeholder_is_not_counted() -> None:
    report = pii.scan("[redacted:phone] and 415-555-0132", categories=["phone"])

    assert report.total == 1


def test_an_address_is_found_counted_and_replaced() -> None:
    report = pii.scan("write to ada@example.com about it")

    assert report.total == 1
    assert {count.category: count.count for count in report.counts}["email"] == 1
    assert "ada@example.com" not in report.redacted_text
    assert "[redacted:email]" in report.redacted_text


def test_two_of_the_same_category_count_as_two() -> None:
    report = pii.scan("ada@example.com and grace@example.com")

    assert report.total == 2


def test_a_category_that_matched_nothing_is_still_reported() -> None:
    """A caller has to be able to tell "looked for and absent" from "not looked for"."""
    report = pii.scan("nothing sensitive here")

    assert {count.category for count in report.counts} == set(pii.known_categories())
    assert report.total == 0
    assert report.redacted_text == "nothing sensitive here"


def test_a_run_of_digits_that_is_not_a_card_is_left_alone() -> None:
    """The library checks Luhn; this proves the service does not route around it."""
    report = pii.scan("order 4111111111111112 shipped")

    assert {count.category: count.count for count in report.counts}["credit_card"] == 0


def test_a_real_card_number_is_found() -> None:
    report = pii.scan("card 4111111111111111 on file")

    assert {count.category: count.count for count in report.counts}["credit_card"] == 1


def test_the_scan_can_be_narrowed_to_the_categories_a_caller_cares_about() -> None:
    report = pii.scan("ada@example.com", categories=["credit_card"])

    assert [count.category for count in report.counts] == ["credit_card"]
    assert report.redacted_text == "ada@example.com"


def test_a_narrowed_scan_keeps_the_librarys_application_order() -> None:
    """`iban` runs before `credit_card` upstream, and a caller's order must not change it."""
    report = pii.scan("nothing", categories=["credit_card", "iban"])

    assert [count.category for count in report.counts] == ["iban", "credit_card"]


def test_a_category_this_deployment_does_not_detect_is_refused_on_the_field() -> None:
    with pytest.raises(BadRequestError) as caught:
        pii.scan("text", categories=["shoe_size"])

    assert caught.value.details is not None
    assert caught.value.details["fields"][0]["field"] == "categories"


def test_an_empty_category_list_is_refused_rather_than_read_as_all() -> None:
    with pytest.raises(BadRequestError):
        pii.scan("text", categories=[])


def test_text_over_the_ceiling_is_refused_before_it_is_scanned() -> None:
    with pytest.raises(BadRequestError) as caught:
        pii.scan("x" * (pii.MAX_TEXT_CHARS + 1))

    assert caught.value.details is not None
    assert caught.value.details["fields"][0]["field"] == "text"


def test_a_caller_cannot_inflate_a_count_by_submitting_the_marker() -> None:
    """The count is markers added, not markers present, so planted ones do not count."""
    planted = "" + "A" * 16 + ""
    report = pii.scan(f"{planted} and ada@example.com")

    assert report.total == 1
