"""Separate the human transcript from the input text a model may replay."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import overload

from pydantic_ai.messages import (
    CompactionPart,
    ModelMessage,
    SystemPromptPart,
    UserPromptPart,
)
from pydantic_ai_harness.guardrails import GuardrailResult

from app.agents.capabilities.guardrails import GuardrailBlocked
from app.services.message_history import REFUSED_TURN, ModelHistory

InputScreen = Callable[[str], GuardrailResult]


def screened_copy(
    prompt: str, attachment_context: str | None, screen: InputScreen | None
) -> str | None:
    """A durable replacement of the whole replay projection, including file briefings.

    None preserves the ordinary replay contract. A replacement is kept even if
    the agent later switches its guardrail off; raw text stays in the audit view.
    """
    if screen is None:
        return None
    original = prompt + (attachment_context or "")
    try:
        verdict = screen(original)
    except GuardrailBlocked:
        return REFUSED_TURN
    if verdict.action == "block":
        return REFUSED_TURN
    if verdict.action == "replace":
        return str(verdict.replacement)
    return None


@overload
def screen_history(
    history: list[ModelMessage], screen: InputScreen | None
) -> list[ModelMessage]: ...


@overload
def screen_history(
    history: Sequence[ModelMessage] | None, screen: InputScreen | None
) -> Sequence[ModelMessage] | None: ...


def screen_history(
    history: Sequence[ModelMessage] | None, screen: InputScreen | None
) -> Sequence[ModelMessage] | None:
    """Defend legacy replay before compaction, without changing a caller's snapshot."""
    if history is None or screen is None:
        return history
    messages: list[ModelMessage] = []
    for message in history:
        parts = [
            replace(part, content=_screened_text(part.content, screen))
            if isinstance(part, (UserPromptPart, CompactionPart, SystemPromptPart))
            and isinstance(part.content, str)
            and (
                not isinstance(part, SystemPromptPart)
                or part.content.startswith("Summary of previous conversation:\n\n")
            )
            else part
            for part in message.parts
        ]
        messages.append(replace(message, parts=parts))
    return (
        ModelHistory(messages, revision=history.revision)
        if isinstance(history, ModelHistory)
        else messages
    )


def _screened_text(text: str, screen: InputScreen) -> str:
    cleaned = screened_copy(text, None, screen)
    return text if cleaned is None else cleaned
