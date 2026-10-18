"""Questions inside a call (#54): the `ask_user` card, answered by a tap or aloud.

The agent's `ask_user` - and its text twin's, and their delegates' - reaches the
caller as the card a chat shows, drawn in the call view. The caller can tap an
answer, or just say it: the next thing they are heard to say while a card is
open answers every question on it, word for word, and the model reads that
against what it asked. A card nobody answers within two minutes is declined,
which the model is told and carries on from.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import anyio
from pydantic_ai_harness.ask_user import AskUserRequest, AskUserResponse

from app.agents.ask_user import answers_to_response, wire_questions
from app.schemas.voice import QuestionsFrame, QuestionsSettledFrame
from app.services.voice.approvals import SendFrame

QUESTION_TIMEOUT_SECONDS = 120


@dataclass
class _Open:
    request: AskUserRequest
    future: asyncio.Future[AskUserResponse]


class VoiceQuestions:
    """The `ask_questions` channel of one call, and the socket side of its answers."""

    def __init__(self, *, send: SendFrame, timeout: float = QUESTION_TIMEOUT_SECONDS) -> None:
        self._send = send
        self._timeout = timeout
        self._open: _Open | None = None
        # One card at a time, as a chat's: a second question waits for the first.
        self._lock = anyio.Lock()

    async def __call__(self, request: AskUserRequest) -> AskUserResponse:
        """Put `request` to the caller and wait for their answer."""
        async with self._lock:
            future: asyncio.Future[AskUserResponse] = asyncio.get_running_loop().create_future()
            self._open = _Open(request=request, future=future)
            try:
                await self._send(
                    QuestionsFrame(
                        type="questions",
                        id=request.id,
                        questions=wire_questions(request),
                        timeout_seconds=int(self._timeout),
                    )
                )
                response = AskUserResponse(cancelled=True)
                with anyio.move_on_after(self._timeout):
                    response = await future
            finally:
                self._open = None
                with anyio.CancelScope(shield=True):
                    await self._send(QuestionsSettledFrame(type="questions_settled", id=request.id))
            return response

    def answer(self, question_id: str, answers: list[Any]) -> bool:
        """The caller's taps on the card. `False` for a card this call is not waiting on."""
        waiting = self._open
        if waiting is None or waiting.request.id != question_id or waiting.future.done():
            return False
        waiting.future.set_result(answers_to_response(waiting.request, answers))
        return True

    def heard(self, text: str) -> None:
        """What the caller said: the answer to every question on an open card."""
        waiting = self._open
        if waiting is None or waiting.future.done() or not text.strip():
            return
        spoken = [{"answer": text}] * len(waiting.request.questions)
        waiting.future.set_result(answers_to_response(waiting.request, spoken))
