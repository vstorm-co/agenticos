"""Which templates a bot may use for a late answer (#2076)."""

from typing import Any

import pytest

from app.services.channels.whatsapp_format import utf16_units
from app.services.channels.whatsapp_templates import (
    LateTemplate,
    stored_template,
    to_stored,
    usable_templates,
)
from app.services.channels.whatsapp_window import MAX_FIXED_UNITS

BODY = "Update from Acme: {{1}} Open the chat to continue."


def entry(
    body: str = BODY,
    *,
    status: str = "APPROVED",
    category: str = "UTILITY",
    extra: list[dict[str, Any]] | None = None,
    name: str = "late_answer",
) -> dict[str, Any]:
    return {
        "name": name,
        "language": "en_US",
        "status": status,
        "category": category,
        "components": [{"type": "BODY", "text": body}, *(extra or [])],
    }


def test_an_approved_utility_template_with_one_variable_is_usable() -> None:
    [template] = usable_templates([entry()])
    assert template == LateTemplate(name="late_answer", language="en_US", body=BODY)
    assert template.parameter_name is None
    assert template.fixed_length == utf16_units(BODY.replace("{{1}}", ""))


def test_a_named_variable_is_sent_by_name() -> None:
    [template] = usable_templates([entry("Hello: {{answer}} Bye.")])
    assert template.parameter_name == "answer"
    assert template.fixed_length == utf16_units("Hello:  Bye.")


@pytest.mark.parametrize(
    "listing",
    [
        entry(category="MARKETING"),
        entry(status="PENDING"),
        entry("A {{1}} and {{2}} b."),
        entry("No variable here."),
        entry("A {{2}} b."),
        entry("A {{Bad Name}} b."),
        entry("A {{1} b {{"),
    ],
)
def test_only_approved_utility_templates_with_one_body_variable_are_usable(
    listing: dict[str, Any],
) -> None:
    assert usable_templates([listing]) == []


@pytest.mark.parametrize(
    "extra",
    [
        [{"type": "FOOTER", "text": "Reply {{1}}"}],
        [{"type": "HEADER", "format": "TEXT", "text": "Hi {{1}}"}],
        [{"type": "HEADER", "format": "IMAGE"}],
        [{"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://x/{{1}}"}]}],
    ],
)
def test_a_variable_outside_the_body_or_a_media_header_makes_it_unusable(
    extra: list[dict[str, Any]],
) -> None:
    assert usable_templates([entry(extra=extra)]) == []


def test_a_text_header_without_a_variable_is_fine() -> None:
    extra = [{"type": "HEADER", "format": "TEXT", "text": "Acme"}]
    assert len(usable_templates([entry(extra=extra)])) == 1


def test_a_body_too_long_for_a_preview_is_not_usable() -> None:
    # The trailing "z" counts as fixed text too.
    assert usable_templates([entry("a" * MAX_FIXED_UNITS + "{{1}}z")]) == []
    assert len(usable_templates([entry("a" * (MAX_FIXED_UNITS - 1) + "{{1}}z")])) == 1


def test_two_bodies_are_not_usable() -> None:
    both = entry(extra=[{"type": "BODY", "text": "again {{1}}"}])
    assert usable_templates([both]) == []


def test_malformed_entries_are_skipped_not_raised() -> None:
    listing: list[object] = [
        "nope",
        None,
        {"status": "APPROVED", "category": "UTILITY"},
        entry() | {"components": "x"},
        entry() | {"components": ["x", {"type": "BODY", "text": 5}]},
        entry() | {"name": 5},
        entry(),
    ]
    assert len(usable_templates(listing)) == 1


def test_a_stored_template_reads_back_and_garbage_reads_as_none() -> None:
    [template] = usable_templates([entry()])
    assert stored_template(to_stored(template)) == template
    assert stored_template(None) is None
    assert stored_template({"name": 1}) is None
    assert stored_template({"name": "n", "language": "en", "body": "{{1}} and {{2}}"}) is None


def _buttons(*buttons: object) -> dict[str, Any]:
    return {"type": "BUTTONS", "buttons": list(buttons)}


def _quick(text: object = "Show me") -> dict[str, Any]:
    return {"type": "QUICK_REPLY", "text": text}


def test_one_quick_reply_is_the_templates_button() -> None:
    [template] = usable_templates([entry(extra=[_buttons(_quick())])])
    assert template.button == "Show me"


def test_a_template_with_no_buttons_has_none() -> None:
    [template] = usable_templates([entry()])
    assert template.button is None


def test_two_quick_replies_make_a_template_unusable() -> None:
    one_component = entry(extra=[_buttons(_quick("A"), _quick("B"))])
    two_components = entry(extra=[_buttons(_quick("A")), _buttons(_quick("B"))])
    assert usable_templates([one_component, two_components]) == []


def test_a_url_button_beside_one_quick_reply_is_fine() -> None:
    url = {"type": "URL", "text": "Site", "url": "https://example.test"}
    [template] = usable_templates([entry(extra=[_buttons(url, _quick())])])
    assert template.button == "Show me"


def test_buttons_that_are_not_a_list_or_not_mappings_are_skipped() -> None:
    odd = [
        entry(extra=[{"type": "BUTTONS", "buttons": None}]),
        entry(extra=[{"type": "BUTTONS"}]),
        entry(extra=[_buttons("nope", None, _quick())]),
    ]
    assert [t.button for t in usable_templates(odd)] == [None, None, "Show me"]


def test_a_quick_reply_with_no_text_is_usable_without_a_button() -> None:
    listing = [
        entry(extra=[_buttons({"type": "QUICK_REPLY"})]),
        entry(extra=[_buttons(_quick(""))]),
    ]
    templates = usable_templates(listing)
    assert [t.button for t in templates] == [None, None]


def test_the_button_round_trips_through_storage() -> None:
    [with_button] = usable_templates([entry(extra=[_buttons(_quick())])])
    [without] = usable_templates([entry()])
    assert to_stored(with_button)["button"] == "Show me"
    assert "button" not in to_stored(without)
    assert stored_template(to_stored(with_button)) == with_button
    assert stored_template(to_stored(without)) == without


def test_a_stored_button_that_is_not_text_is_dropped_and_the_template_kept() -> None:
    stored = {"name": "n", "language": "en", "body": "A {{1}} b.", "button": 5}
    template = stored_template(stored)
    assert template is not None and template.button is None
