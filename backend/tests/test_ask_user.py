"""Tests for the ask-the-user question shapes.

Everything here feeds a string back into a model mid-run, which is why the
edge cases matter more than they look: a malformed transcript does not raise,
it quietly tells the agent something the user never said. Each case below is a
shape the WebSocket client has actually been able to send.
"""

from __future__ import annotations

import pytest
from subagents_pydantic_ai import SubAgentState

# The library binds this itself around every delegation and exports the reader
# rather than the binder, so a test that wants to *be* inside a delegation
# reaches for it here.
from subagents_pydantic_ai._state import bind_subagent_state

from app.agents.ask_user import MAX_QUESTIONS, QuestionItem, asking_delegate, format_answers


class TestQuestionItem:
    def test_a_question_needs_nothing_but_its_text(self):
        """The common case is one open question with no suggestions."""
        item = QuestionItem(question="Which environment?")

        assert item.options == []
        assert item.allow_custom is True

    def test_free_form_can_be_closed_off(self):
        """A question with fixed options must be able to mean only those."""
        item = QuestionItem(question="Region?", options=["eu", "us"], allow_custom=False)

        assert item.allow_custom is False

    def test_a_question_without_text_is_refused(self):
        with pytest.raises(ValueError, match="question"):
            QuestionItem()  # type: ignore[call-arg]

    def test_the_cap_leaves_room_for_a_real_form_but_not_a_survey(self):
        assert MAX_QUESTIONS == 10


class TestFormatAnswers:
    def test_questions_and_answers_are_paired_in_order(self):
        rendered = format_answers(
            [{"question": "Region?"}, {"question": "Environment?"}],
            [{"answer": "eu"}, {"answer": "staging"}],
        )

        assert rendered == "Q: Region?\nA: eu\n\nQ: Environment?\nA: staging"

    def test_a_skipped_question_says_so_rather_than_going_blank(self):
        """Blank would read to the model as an answer of empty string."""
        rendered = format_answers([{"question": "Region?"}], [{"skipped": True}])

        assert rendered == "Q: Region?\nA: (skipped)"

    def test_an_empty_answer_is_reported_as_no_answer(self):
        rendered = format_answers([{"question": "Region?"}], [{"answer": "   "}])

        assert rendered == "Q: Region?\nA: (no answer)"

    def test_a_missing_answer_does_not_shift_the_remaining_ones(self):
        """Fewer answers than questions must not pair Q2 with A1's text."""
        rendered = format_answers(
            [{"question": "Region?"}, {"question": "Environment?"}], [{"answer": "eu"}]
        )

        assert rendered == "Q: Region?\nA: eu\n\nQ: Environment?\nA: (no answer)"

    def test_an_answer_that_is_not_an_object_is_treated_as_absent(self):
        """The client sends this JSON; a bare string here must not crash the run."""
        rendered = format_answers([{"question": "Region?"}], ["eu"])  # type: ignore[list-item]

        assert rendered == "Q: Region?\nA: (no answer)"

    def test_a_non_string_answer_is_rendered_rather_than_dropped(self):
        rendered = format_answers([{"question": "How many?"}], [{"answer": 3}])

        assert rendered == "Q: How many?\nA: 3"

    def test_a_question_with_no_text_still_renders_its_answer(self):
        """A half-formed question is worth less than the answer beside it."""
        rendered = format_answers([{}], [{"answer": "eu"}])

        assert rendered == "Q: \nA: eu"

    def test_nothing_asked_renders_nothing(self):
        assert format_answers([], []) == ""


class TestWhichDelegateIsAsking:
    """`asking_delegate`, and the one thing it is easy to get wrong.

    The name is only readable from inside the delegation, because that is the
    only place the library binds the state. A caller that reads it where the
    *answer* arrives - the socket's receive loop, a different task - gets `None`
    for every question and the transcript quietly stops naming anybody (#1042).
    """

    def test_inside_a_delegation_it_names_the_subagent(self) -> None:
        with bind_subagent_state(SubAgentState(ask_timeout_seconds=300.0, name="researcher")):
            assert asking_delegate() == "researcher"

    def test_outside_one_it_is_none(self) -> None:
        """The main agent asking a question itself, which is the ordinary case."""
        assert asking_delegate() is None

    def test_a_delegation_that_carries_no_name_is_none_rather_than_empty(self) -> None:
        """An older library, or a state built by hand. `None` reads the same as
        the main agent asking, which is the honest answer when nothing said."""
        with bind_subagent_state(SubAgentState(ask_timeout_seconds=300.0)):
            assert asking_delegate() is None
