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
        ("at reception Where is the parking?", True),
        ("Where is the parking? Wrong floor,", True),
        ("Where is the parking?", False),
        ("", False),
    ],
)
def test_a_quote_repeats_a_comment_wherever_it_overlaps_it(quote: str, repeats: bool) -> None:
    assert _repeats(quote, COMMENT) is repeats


def test_an_empty_comment_is_never_repeated() -> None:
    assert _repeats("Where is the parking?", "  ") is False
