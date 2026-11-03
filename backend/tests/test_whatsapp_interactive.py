"""The WhatsApp interactive builder: buttons, lists and the limits Meta enforces (#2076)."""

import pytest

from app.services.channels.base import ChannelChoice
from app.services.channels.whatsapp_format import utf16_units
from app.services.channels.whatsapp_interactive import (
    CHOOSE_BELOW,
    LIST_BUTTON,
    plan_interactive,
    shorten,
    unique_titles,
)


def _choices(*labels: str) -> list[ChannelChoice]:
    return [ChannelChoice(label=label, value=f"v{index}") for index, label in enumerate(labels)]


@pytest.mark.security
def test_an_approval_is_two_buttons():
    choices = [
        ChannelChoice(label="Approve", value="approve:1", style="primary"),
        ChannelChoice(label="Reject", value="reject:1", style="danger"),
    ]
    plan = plan_interactive("Run search?", choices)
    assert plan is not None
    assert plan.preamble is None
    assert plan.interactive == {
        "type": "button",
        "body": {"text": "Run search?"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "approve:1", "title": "Approve"}},
                {"type": "reply", "reply": {"id": "reject:1", "title": "Reject"}},
            ]
        },
    }


def test_four_choices_become_a_list():
    plan = plan_interactive("Pick", _choices("a", "b", "c", "d"))
    assert plan is not None
    interactive = plan.interactive
    assert interactive["type"] == "list"
    assert interactive["action"]["button"] == LIST_BUTTON
    (section,) = interactive["action"]["sections"]
    assert section["title"] == "Choices"
    assert section["rows"] == [{"id": f"v{i}", "title": t} for i, t in enumerate("abcd")]


def test_a_long_label_moves_a_question_to_a_list():
    long_label = "Send the quarterly report now"[:30].ljust(30, "x")
    plan = plan_interactive("Pick", _choices("Yes", long_label))
    assert plan is not None
    assert plan.interactive["type"] == "list"
    short_row, long_row = plan.interactive["action"]["sections"][0]["rows"]
    assert "description" not in short_row
    assert long_row["title"].endswith("…")
    assert len(long_row["title"]) <= 24
    assert long_row["description"] == long_label


def test_a_long_description_is_shortened_too():
    plan = plan_interactive("Pick", _choices("y" * 100, "n"))
    assert plan is not None
    row = plan.interactive["action"]["sections"][0]["rows"][0]
    assert len(row["description"]) == 72
    assert row["description"].endswith("…")


def test_more_than_ten_choices_fall_back():
    assert plan_interactive("Pick", _choices(*[str(i) for i in range(11)])) is None


def test_no_choices_fall_back():
    assert plan_interactive("Pick", []) is None


def test_ten_choices_still_fit_a_list():
    plan = plan_interactive("Pick", _choices(*[str(i) for i in range(10)]))
    assert plan is not None
    assert len(plan.interactive["action"]["sections"][0]["rows"]) == 10


def test_a_long_body_is_sent_before_the_buttons():
    body = "x" * 1500
    plan = plan_interactive(body, _choices("Yes", "No"))
    assert plan is not None
    assert plan.preamble == body
    assert plan.interactive["body"] == {"text": CHOOSE_BELOW}
    listed = plan_interactive(body, _choices("a", "b", "c", "d", "e"))
    assert listed is not None
    assert listed.preamble is None
    assert listed.interactive["body"] == {"text": body}


def test_a_list_body_over_its_limit_is_sent_before_the_list():
    body = "x" * 4097
    plan = plan_interactive(body, _choices("a", "b", "c", "d"))
    assert plan is not None
    assert plan.preamble == body
    assert plan.interactive["body"] == {"text": CHOOSE_BELOW}


def test_shortened_titles_stay_unique():
    first = "z" * 25 + "one"
    second = "z" * 25 + "two"
    titles = unique_titles([first, second, first], 24)
    assert len(set(titles)) == 3
    assert all(len(title) <= 24 for title in titles)
    assert titles[2].endswith(" (3)")


def test_equal_short_labels_get_a_counter():
    assert unique_titles(["Yes", "Yes"], 20) == ["Yes", "Yes (2)"]


def test_buttons_with_equal_labels_stay_unique():
    plan = plan_interactive("Pick", _choices("Yes", "Yes"))
    assert plan is not None
    titles = [b["reply"]["title"] for b in plan.interactive["action"]["buttons"]]
    assert titles == ["Yes", "Yes (2)"]


def test_shortening_never_splits_a_grapheme():
    shortened = shorten("ab" + "👍🏽" * 20, 20)
    assert utf16_units(shortened) <= 20
    assert shortened.endswith("…")
    body = shortened[:-1]
    assert not body.endswith("\U0001f44d")
    assert body.count("👍") == body.count("\U0001f3fd")
    assert shorten("short", 20) == "short"


def test_shortening_counts_utf16_units():
    for limit in (20, 24):
        shortened = shorten("😀" * 40, limit)
        assert utf16_units(shortened) <= limit
        assert shortened == "😀" * ((limit - 1) // 2) + "…"
    assert shorten("😀" * 10, 20) == "😀" * 10
    assert shorten("😀" * 11, 20) != "😀" * 11


def test_an_emoji_label_that_is_too_long_in_units_becomes_a_list():
    label = "😀" * 13  # 13 code points, 26 UTF-16 units
    plan = plan_interactive("Pick", _choices(label, "No"))
    assert plan is not None
    assert plan.interactive["type"] == "list"
    row = plan.interactive["action"]["sections"][0]["rows"][0]
    assert utf16_units(row["title"]) <= 24
    assert row["description"] == label


def test_an_emoji_body_over_the_limit_in_units_goes_first():
    body = "😀" * 600  # 600 code points, 1200 units
    plan = plan_interactive(body, _choices("Yes", "No"))
    assert plan is not None
    assert plan.preamble == body
    edge = "😀" * 512
    kept = plan_interactive(edge, _choices("Yes", "No"))
    assert kept is not None
    assert kept.preamble is None
