"""Tests for the ask-the-user question shapes.

Everything here feeds a string back into a model mid-run, which is why the
edge cases matter more than they look: a malformed transcript does not raise,
it quietly tells the agent something the user never said. Each case below is a
shape the WebSocket client has actually been able to send.
"""

from __future__ import annotations

import pytest
from pydantic_ai_harness.ask_user import (
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
    Question,
    QuestionOption,
    check_response,
)
from subagents_pydantic_ai import SubAgentState

# The library binds this itself around every delegation and exports the reader
# rather than the binder, so a test that wants to *be* inside a delegation
# reaches for it here.
from subagents_pydantic_ai._state import bind_subagent_state

from app.agents.ask_user import (
    MAX_QUESTIONS,
    QuestionChoice,
    QuestionItem,
    answers_to_response,
    asking_delegate,
    format_answers,
    render_answer,
    wire_questions,
)


class TestQuestionItem:
    def test_a_question_needs_nothing_but_its_text(self):
        """The common case is one open question with no suggestions."""
        item = QuestionItem(question="Which environment?")

        assert item.options == []
        assert item.allow_custom is True

    def test_free_form_can_be_closed_off(self):
        """A question with fixed options must be able to mean only those."""
        item = QuestionItem(
            question="Region?",
            options=[QuestionChoice(label="eu"), QuestionChoice(label="us")],
            allow_custom=False,
        )

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


def _request(*, multi: bool = False) -> AskUserRequest:
    return AskUserRequest(
        questions=(
            Question(
                header="Region",
                question="Where should it run?",
                options=(
                    QuestionOption(label="eu", description="Frankfurt"),
                    QuestionOption(label="us"),
                ),
                multi_select=multi,
            ),
            Question(
                header="Size",
                question="How big?",
                options=(QuestionOption(label="small"), QuestionOption(label="large")),
            ),
        )
    )


class TestTheAskUserCard:
    """#2064. The surface's answers are client input; nothing it sends may fail
    the run, and what reaches the model must pass the harness's own check."""

    def test_the_card_carries_headers_descriptions_and_multi_select(self) -> None:
        [region, _size] = wire_questions(_request(multi=True))

        assert region["header"] == "Region"
        assert region["options"][0] == {"label": "eu", "description": "Frankfurt"}
        assert region["multi_select"] is True

    def test_picks_and_typed_answers_become_the_harness_response(self) -> None:
        request = _request(multi=True)

        response = answers_to_response(
            request, [{"selected": ["us", "eu", "us"]}, {"answer": "medium\x07"}]
        )

        check_response(request, response)
        assert response.answers == (
            AskUserAnswer(header="Region", selected=("us", "eu")),
            AskUserAnswer(header="Size", custom_answer="medium"),
        )

    def test_a_label_not_offered_and_a_second_single_pick_are_dropped(self) -> None:
        request = _request()

        response = answers_to_response(
            request, [{"selected": ["mars", "eu", "us"]}, {"selected": ["galaxy"]}]
        )

        check_response(request, response)
        assert response.answers == (
            AskUserAnswer(header="Region", selected=("eu",)),
            AskUserAnswer(header="Size", custom_answer="(skipped)"),
        )

    def test_skipping_everything_is_declining(self) -> None:
        request = _request()

        for answers in ([{"skipped": True}, {"skipped": True, "answer": "x"}], [], ["eu", None]):
            assert answers_to_response(request, answers) == AskUserResponse(cancelled=True)

    def test_a_picked_answer_is_shown_by_its_labels(self) -> None:
        assert render_answer({"selected": ["eu", "us"]}) == "eu, us"


@pytest.mark.anyio
async def test_a_surface_that_answers_later_parks_the_question() -> None:
    """A chat puts the question as buttons once the turn ends (#2064)."""
    from pydantic_ai.exceptions import CallDeferred
    from pydantic_ai_harness.ask_user import AskUserRequest

    from app.agents.ask_user import park_the_question

    with pytest.raises(CallDeferred):
        await park_the_question(AskUserRequest(questions=()))


def test_a_parked_question_s_step_waits_for_an_answer_and_any_other_for_approval() -> None:
    from app.agents.ask_user import parked_status

    assert parked_status("ask_user_question") == "awaiting_answer"
    assert parked_status("send_email") == "awaiting_approval"
