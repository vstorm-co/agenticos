"""What a call leaves in the conversation (#54)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio
import pytest

from app.services.voice.transcript import SpeechClock, SpokenToolCall, TurnWriter, trim_to_played

pytestmark = pytest.mark.anyio


def test_an_answer_heard_for_two_seconds_keeps_about_thirty_characters_at_a_word_boundary():
    text = "It is eighteen degrees and cloudy in Warsaw, with rain expected by the evening."
    trimmed = trim_to_played(text, 2000)
    assert trimmed == "It is eighteen degrees and"
    assert text.startswith(trimmed)


def test_an_answer_heard_to_the_end_is_kept_whole():
    assert trim_to_played("Short.", 5000) == "Short."


def test_an_answer_cut_before_its_first_word_keeps_nothing():
    assert trim_to_played("Hello there", 0) == ""


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_speech_over_the_agent_is_an_interruption_with_the_time_it_was_heard():
    clock = _Clock()
    speech = SpeechClock(now=clock)
    speech.output_started()
    clock.t = 101.5

    assert speech.input_started() == 1500


def test_speech_after_the_agent_finished_is_not_an_interruption():
    clock = _Clock()
    speech = SpeechClock(now=clock)
    speech.output_started()
    clock.t = 103
    speech.output_ended()

    assert speech.input_started() is None and not speech.agent_speaking


def _writer():
    session = MagicMock()

    @asynccontextmanager
    async def sessions():
        yield session

    writer = TurnWriter(
        sessions=sessions,
        call_id=uuid4(),
        conversation_id=uuid4(),
        run_id=uuid4(),
        agent_id=uuid4(),
        agent_version_id=None,
    )
    return writer, session


@pytest.fixture
def read():
    """The writes are mocked here; `tests/integration/test_voice_turns.py` builds the
    real `MessageRead` from real rows."""
    with patch(
        "app.services.voice.transcript._read",
        side_effect=lambda message, tool_calls: (message, tool_calls),
    ) as built:
        yield built


def test_turn_ids_count_up_across_both_speakers():
    writer, _ = _writer()
    first, second = writer.next_turn_id("user"), writer.next_turn_id("assistant")
    assert first.endswith(":1:user") and second.endswith(":2:assistant")
    assert first.split(":")[0] == second.split(":")[0]


@pytest.mark.usefixtures("read")
async def test_each_turn_is_saved_under_the_id_its_captions_carried():
    created = AsyncMock(side_effect=lambda db, **kw: SimpleNamespace(id=uuid4(), **kw))
    writer, _ = _writer()
    with patch("app.services.voice.transcript.conversation_repo.create_voice_turn", created):
        await writer.user_turn("Weather in Warsaw?", turn_id="c:1:user")
        await writer.assistant_turn(
            "Eighteen and cloudy.", turn_id="c:2:assistant", interrupted=False, tools=()
        )

    assert [call.kwargs["turn_id"] for call in created.await_args_list] == [
        "c:1:user",
        "c:2:assistant",
    ]


async def test_tool_calls_land_inline_under_the_assistant_turn(read):
    message = SimpleNamespace(id=uuid4())
    row = SimpleNamespace()
    with (
        patch(
            "app.services.voice.transcript.conversation_repo.create_voice_turn",
            AsyncMock(return_value=message),
        ) as created,
        patch(
            "app.services.voice.transcript.conversation_repo.create_tool_call",
            AsyncMock(return_value=SimpleNamespace()),
        ) as started,
        patch(
            "app.services.voice.transcript.conversation_repo.complete_tool_call",
            AsyncMock(return_value=row),
        ) as completed,
    ):
        writer, _ = _writer()
        tool = SpokenToolCall(
            tool_call_id="call_1",
            tool_name="get_weather",
            args={"city": "Warsaw"},
            started_at=datetime.now(UTC),
            result="18C",
            completed_at=datetime.now(UTC),
        )
        saved = await writer.assistant_turn(
            "Let me check.", turn_id="c:1:assistant", interrupted=False, tools=[tool]
        )

    parts = created.await_args.kwargs["parts"]
    assert parts == [
        {"type": "text", "text": "Let me check."},
        {"type": "tool", "tool_call_id": "call_1"},
    ]
    assert started.await_args.kwargs["message_id"] == message.id
    assert completed.await_args.kwargs["result"] == "18C"
    assert saved == (message, [row])


async def test_an_empty_user_turn_is_not_written():
    with patch(
        "app.services.voice.transcript.conversation_repo.create_voice_turn", AsyncMock()
    ) as created:
        writer, _ = _writer()
        assert await writer.user_turn("   ", turn_id="c:1:user") is None
    created.assert_not_awaited()


async def test_silence_with_no_tools_writes_no_assistant_turn():
    with patch(
        "app.services.voice.transcript.conversation_repo.create_voice_turn", AsyncMock()
    ) as created:
        writer, _ = _writer()
        assert (
            await writer.assistant_turn("  ", turn_id="c:1:assistant", interrupted=True, tools=())
            is None
        )
    created.assert_not_awaited()


async def test_a_turn_already_written_is_not_written_again_with_its_tools():
    """A retried write after a reconnect lands once, and so do its tool rows."""
    tool = SpokenToolCall(
        tool_call_id="call_1", tool_name="send_email", args={}, started_at=datetime.now(UTC)
    )
    with (
        patch(
            "app.services.voice.transcript.conversation_repo.create_voice_turn",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.voice.transcript.conversation_repo.create_tool_call", AsyncMock()
        ) as started,
    ):
        writer, _ = _writer()
        assert (
            await writer.assistant_turn(
                "", turn_id="c:1:assistant", interrupted=False, tools=[tool]
            )
            is None
        )
        assert await writer.user_turn("Again", turn_id="c:1:user") is None
    started.assert_not_awaited()


async def test_a_tool_still_running_when_the_turn_ends_is_left_open(read):
    message = SimpleNamespace(id=uuid4())
    with (
        patch(
            "app.services.voice.transcript.conversation_repo.create_voice_turn",
            AsyncMock(return_value=message),
        ) as created,
        patch("app.services.voice.transcript.conversation_repo.create_tool_call", AsyncMock()),
        patch(
            "app.services.voice.transcript.conversation_repo.complete_tool_call", AsyncMock()
        ) as completed,
    ):
        writer, _ = _writer()
        tool = SpokenToolCall(
            tool_call_id="call_2", tool_name="lookup", args={}, started_at=datetime.now(UTC)
        )
        await writer.assistant_turn("", turn_id="c:1:assistant", interrupted=False, tools=[tool])

    assert created.await_args.kwargs["parts"] == [{"type": "tool", "tool_call_id": "call_2"}]
    completed.assert_not_awaited()


def test_a_saved_turn_reads_without_a_session():
    """Built from what the writer wrote: nothing on it is lazily loaded."""
    from app.db.models.conversation import Message
    from app.services.voice.transcript import _read

    message = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content="Eighteen.",
        turn_id="c:2:assistant",
        interrupted=True,
        created_at=datetime.now(UTC),
    )

    read = _read(message, tool_calls=[])

    assert (read.turn_id, read.interrupted, read.tool_calls, read.files) == (
        "c:2:assistant",
        True,
        [],
        [],
    )


async def test_a_turn_already_being_written_is_saved_when_the_call_is_cut_off(read):
    """The pump is cancelled when a call ends; a turn it was writing must still land,
    and a write cut off mid-way would also break its pooled connection."""
    writer, _ = _writer()
    written: list[str] = []

    async def slow_create(db, **kwargs):
        await anyio.sleep(0.2)
        written.append(kwargs["role"])
        return SimpleNamespace(id=uuid4())

    with patch("app.services.voice.transcript.conversation_repo.create_voice_turn", slow_create):
        with anyio.move_on_after(0.1):
            await writer.user_turn("hello", turn_id="c:1:user")

    assert written == ["user"]
