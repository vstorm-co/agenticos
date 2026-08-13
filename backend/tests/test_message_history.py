"""Rebuilding a conversation into what a model reads.

The one thing worth pinning here is the empty turn. A caption-less file is
recorded as an empty user row so the file has something to hang off; the file's
bytes are not in this history, so the row reconstructs to an empty text part -
which Anthropic rejects with a 400, taking down every turn after the photo.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.services.agent import build_message_history


def test_a_row_with_text_becomes_a_part_of_the_matching_kind() -> None:
    history = build_message_history(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)


def test_an_empty_row_is_dropped_rather_than_sent_as_an_empty_part() -> None:
    history = build_message_history(
        [
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "the real question"},
        ]
    )

    assert len(history) == 1
    assert history[0].parts[0].content == "the real question"
