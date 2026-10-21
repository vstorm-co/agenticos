"""The `ask_user` card inside a call, answered by a tap or aloud (#54)."""

import anyio
import pytest
from pydantic_ai_harness.ask_user import (
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
    Question,
    QuestionOption,
)

from app.schemas.voice import QuestionsFrame, QuestionsSettledFrame, ServerFrame
from app.services.voice.questions import VoiceQuestions

pytestmark = pytest.mark.anyio


def _request(*headers: str) -> AskUserRequest:
    return AskUserRequest(
        id="q1",
        questions=tuple(
            Question(
                header=header,
                question=f"Which {header}?",
                options=(QuestionOption(label="Small"), QuestionOption(label="Large")),
            )
            for header in headers
        ),
    )


class _Card:
    """The call view: what the card was sent, and a way to act once it shows."""

    def __init__(self) -> None:
        self.sent: list[ServerFrame] = []
        self.shown = anyio.Event()

    async def send(self, frame: ServerFrame) -> None:
        self.sent.append(frame)
        if isinstance(frame, QuestionsFrame):
            self.shown.set()


async def _ask(
    questions: VoiceQuestions, card: _Card, request: AskUserRequest, act
) -> AskUserResponse:
    answer: list[AskUserResponse] = []

    async def asking() -> None:
        answer.append(await questions(request))

    async with anyio.create_task_group() as group:
        group.start_soon(asking)
        await card.shown.wait()
        act()
    return answer[0]


async def test_a_tap_on_the_card_answers_it_and_closes_it():
    card = _Card()
    questions = VoiceQuestions(send=card.send)

    response = await _ask(
        questions,
        card,
        _request("Size"),
        lambda: questions.answer("q1", [{"selected": ["Large"]}]),
    )

    assert response.answers == (AskUserAnswer(header="Size", selected=("Large",)),)
    shown = card.sent[0]
    assert isinstance(shown, QuestionsFrame) and shown.questions[0]["header"] == "Size"
    assert card.sent[-1] == QuestionsSettledFrame(type="questions_settled", id="q1")


async def test_what_the_caller_says_answers_every_question_on_the_card():
    card = _Card()
    questions = VoiceQuestions(send=card.send)

    response = await _ask(
        questions, card, _request("Size", "Colour"), lambda: questions.heard("large and red")
    )

    assert response.answers == (
        AskUserAnswer(header="Size", custom_answer="large and red"),
        AskUserAnswer(header="Colour", custom_answer="large and red"),
    )


async def test_silence_and_words_with_no_card_open_answer_nothing():
    card = _Card()
    questions = VoiceQuestions(send=card.send)
    questions.heard("hello")  # no card: nothing to answer

    response = await _ask(
        questions,
        card,
        _request("Size"),
        lambda: (questions.heard("   "), questions.answer("q1", [{"selected": ["Small"]}])),
    )

    assert response.answers == (AskUserAnswer(header="Size", selected=("Small",)),)


async def test_an_answer_for_another_card_or_a_second_answer_is_not_taken():
    card = _Card()
    questions = VoiceQuestions(send=card.send)
    taken: list[bool] = []

    def act() -> None:
        taken.append(questions.answer("other", [{"selected": ["Small"]}]))
        taken.append(questions.answer("q1", [{"selected": ["Large"]}]))
        taken.append(questions.answer("q1", [{"selected": ["Small"]}]))
        questions.heard("too late")

    response = await _ask(questions, card, _request("Size"), act)

    assert taken == [False, True, False]
    assert response.answers == (AskUserAnswer(header="Size", selected=("Large",)),)
    assert questions.answer("q1", []) is False


async def test_a_card_nobody_answers_is_declined_and_closed():
    card = _Card()
    questions = VoiceQuestions(send=card.send, timeout=0.01)

    response = await questions(_request("Size"))

    assert response.cancelled
    assert card.sent[-1] == QuestionsSettledFrame(type="questions_settled", id="q1")
