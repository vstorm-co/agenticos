"""Which of the authoring assistant's quotes repeat an erased person's comment.

A quote is taken word for word from a run's text, where a comment sits between
the next comment and the question, so it can hold the comment, sit inside it,
or run across its edge. Any of those keeps part of what they wrote.
"""

import pytest

from app.repositories.personal_data import _repeats

COMMENT = "Wrong floor, ask   Anna at reception"


@pytest.mark.parametrize(
    ("quote", "repeats"),
    [
        ("ask Anna", True),
        ("Wrong floor, ask Anna at reception Where is the parking?", True),
        ("Anna at reception Where is the parking?", True),
        ("Where is the parking? Wrong floor, ask", True),
        ("at reception Where is the parking?", False),
        ("Where is the parking? Wrong floor,", False),
        ("Where is the parking?", False),
        ("", False),
    ],
)
def test_a_quote_repeats_a_comment_it_holds_or_runs_across(quote: str, repeats: bool) -> None:
    assert _repeats(quote, COMMENT) is repeats


@pytest.mark.parametrize(
    ("quote", "comment"),
    [
        ("Please book a flight to Oslo", "ok"),
        ("What is the price", "price is wrong"),
        ("The booking failed", "  "),
    ],
)
def test_words_shared_by_chance_are_not_a_repeat(quote: str, comment: str) -> None:
    assert _repeats(quote, comment) is False


def test_a_short_comment_repeats_only_whole() -> None:
    assert _repeats("Where is it? Too slow", "Too slow") is True
    assert _repeats("Where is it? Too", "Too slow") is False
