"""What a run recorded about itself.

Every surface has always produced an `agent_runs` row. Writing the transcript was
the caller's job, and four callers did not do it: the embedded widget, a channel
mention, the HTTP API and every resumed run recorded nothing, so an organization
was billed for an answer with no row saying what was asked or what came back. The
channel bot's own write recorded two lines of text and dropped the tool calls,
the model and the version.

These tests are about the rows, not about the calls: what a reader of run history
can see afterwards, and - just as much - what is deliberately not written. A
blank assistant message for a run that parked would read as the agent answering
with silence, and an invented user turn on a resume would put words in somebody's
mouth.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.services.transcript import RecordedToolCall, TranscriptService, tool_calls_in

pytestmark = pytest.mark.anyio


def _run(*, in_a_conversation: bool = True) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        conversation_id=uuid.uuid4() if in_a_conversation else None,
    )


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _session() -> AsyncMock:
    """A mocked session whose SAVEPOINT is a no-op.

    `record` wraps its writes in `db.begin_nested()` so a failed transcript write
    rolls back only itself and cannot poison the transaction the run row commits
    in. A unit test mocking the repository boundary still has to satisfy that
    context manager, so it stands in a no-op that yields and rolls nothing back;
    the savepoint's real behaviour - the run surviving a failed transcript - is
    proved against a database in `tests/integration/test_transcript_savepoint.py`.
    """
    db = AsyncMock()
    db.begin_nested = MagicMock(side_effect=_noop_savepoint)
    return db


def _called(tool_name: str, tool_call_id: str, **args: object) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args=args, tool_call_id=tool_call_id)]
    )


def _returned(tool_name: str, tool_call_id: str, content: str) -> ModelRequest:
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=tool_name, content=content, tool_call_id=tool_call_id)]
    )


class TestReadingToolCallsOffARun:
    def test_a_call_and_what_it_returned_are_one_record(self):
        calls = tool_calls_in(
            [
                _called("send_email", "c1", to="ada@example.com"),
                _returned("send_email", "c1", "sent"),
            ]
        )

        assert calls == [
            RecordedToolCall(
                tool_call_id="c1",
                tool_name="send_email",
                args={"to": "ada@example.com"},
                result="sent",
            )
        ]

    def test_a_call_the_model_was_told_to_retry_records_the_refusal(self):
        """It happened and it failed. Dropping it would leave an argument list
        with no outcome, which reads as "still running" for ever."""
        calls = tool_calls_in(
            [
                _called("send_email", "c1", to="not-an-address"),
                ModelRequest(
                    parts=[
                        RetryPromptPart(
                            content="to is not a valid address",
                            tool_name="send_email",
                            tool_call_id="c1",
                        )
                    ]
                ),
            ]
        )

        assert calls[0].result == "to is not a valid address"

    def test_a_call_that_never_came_back_has_no_result(self):
        """The run parked on it, was stopped, or broke. `None` is not the empty
        string: a client draws "waiting" for one and "returned nothing" for the
        other."""
        calls = tool_calls_in([_called("charge_card", "c1", amount=500)])

        assert (calls[0].tool_name, calls[0].result) == ("charge_card", None)

    def test_several_calls_keep_the_order_they_were_made_in(self):
        calls = tool_calls_in(
            [
                _called("search", "c1", q="refunds"),
                _returned("search", "c1", "3 hits"),
                _called("send_email", "c2", to="ada@example.com"),
                _returned("send_email", "c2", "sent"),
            ]
        )

        assert [call.tool_name for call in calls] == ["search", "send_email"]

    def test_a_conversation_with_no_tool_calls_records_none(self):
        calls = tool_calls_in(
            [
                ModelRequest(parts=[UserPromptPart(content="how many are open?")]),
                ModelResponse(parts=[TextPart(content="two")]),
            ]
        )

        assert calls == []


class TestWritingTheTranscript:
    @pytest.fixture
    def conversations(self):
        """The repository boundary, which is where the assertions belong."""
        with patch("app.services.transcript.conversation_repo") as repo:
            repo.create_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            repo.create_tool_call = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            repo.complete_tool_call = AsyncMock()
            yield repo

    async def test_both_turns_are_written_against_the_run(self, conversations):
        run = _run()

        await TranscriptService(_session()).record(
            run, prompt="how many are open?", answer="two", model_label="gpt-4.1"
        )

        prompt, answer = (call.kwargs for call in conversations.create_message.await_args_list)
        assert (prompt["role"], prompt["content"], prompt["run_id"]) == (
            "user",
            "how many are open?",
            run.id,
        )
        assert (answer["role"], answer["content"], answer["run_id"]) == ("assistant", "two", run.id)
        assert answer["model_name"] == "gpt-4.1"

    async def test_the_answer_is_attributed_to_the_version_that_ran(self, conversations):
        """An agent is rewritten between runs. Attributing last Tuesday's answer
        to the spec it has today would rewrite what it was told to do."""
        run = _run()

        await TranscriptService(_session()).record(run, prompt="hello", answer="hi")

        answer = conversations.create_message.await_args_list[1].kwargs
        assert (answer["agent_id"], answer["agent_version_id"]) == (
            run.agent_id,
            run.agent_version_id,
        )

    async def test_a_tool_call_is_written_with_its_arguments_and_its_result(self, conversations):
        """ "The agent sent an email" is not reviewable; "to whom" is the whole
        question an approver and an auditor are asking."""
        await TranscriptService(_session()).record(
            _run(),
            prompt="email ada",
            answer="done",
            tool_calls=[
                RecordedToolCall(
                    tool_call_id="c1",
                    tool_name="send_email",
                    args={"to": "ada@example.com"},
                    result="sent",
                )
            ],
        )

        written = conversations.create_tool_call.await_args.kwargs
        assert (written["tool_name"], written["args"]) == ("send_email", {"to": "ada@example.com"})
        assert conversations.complete_tool_call.await_args.kwargs["result"] == "sent"

    async def test_a_call_that_never_returned_is_left_open_rather_than_completed(
        self, conversations
    ):
        """Completing it with an empty result would say the tool answered."""
        await TranscriptService(_session()).record(
            _run(),
            prompt="charge it",
            answer="waiting on approval",
            tool_calls=[
                RecordedToolCall(tool_call_id="c1", tool_name="charge_card", args={"amount": 500})
            ],
        )

        conversations.create_tool_call.assert_awaited_once()
        conversations.complete_tool_call.assert_not_awaited()

    async def test_a_resumed_run_writes_no_user_turn(self, conversations):
        """It picks up at the tool call it stopped on. There is no new question,
        and inventing one would put words in somebody's mouth."""
        await TranscriptService(_session()).record(_run(), prompt=None, answer="finished")

        assert [call.kwargs["role"] for call in conversations.create_message.await_args_list] == [
            "assistant"
        ]

    async def test_a_run_that_produced_no_answer_still_records_the_question(self, conversations):
        """A run that parked, was stopped or broke. A blank assistant message
        would read as the agent replying with silence - and the question is what
        makes the run interpretable at all."""
        await TranscriptService(_session()).record(_run(), prompt="charge it", answer="")

        assert [call.kwargs["role"] for call in conversations.create_message.await_args_list] == [
            "user"
        ]

    async def test_a_run_with_no_conversation_writes_nothing(self, conversations):
        """The API may run an agent without one. There is nowhere to write a
        turn, and the run row is still the record that it happened."""
        await TranscriptService(_session()).record(
            _run(in_a_conversation=False), prompt="hello", answer="hi"
        )

        conversations.create_message.assert_not_awaited()

    async def test_a_failed_write_does_not_take_the_answer_down_with_it(
        self, conversations, caplog
    ):
        """The answer is already produced and the money already spent. Losing
        either to a failed insert would be the worst possible trade."""
        conversations.create_message = AsyncMock(side_effect=RuntimeError("no connection"))

        await TranscriptService(_session()).record(_run(), prompt="hello", answer="hi")

        assert "transcript_write_failed" in caplog.text
