"""What a run recorded about itself.

Every surface has always produced an `agent_runs` row. Writing the transcript was
the caller's job, and four callers did not do it: the embedded widget, a channel
mention, the HTTP API and every resumed run recorded nothing, so an organization
was billed for an answer with no row saying what was asked or what came back. The
channel bot's own write recorded two lines of text and dropped the tool calls,
the model and the version.

These tests are about the rows, not about the calls: what a reader of run history
can see afterwards, and - just as much - what is deliberately not written. An
assistant message with neither an answer nor a call under it would read as the
agent replying with silence, and an invented user turn on a resume would put
words in somebody's mouth. A run that answered nothing but *did* something is the
opposite case, and it is written: the calls are what happened.
"""

from __future__ import annotations

import logging
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

from app.services.transcript import (
    RecordedToolCall,
    TranscriptService,
    settled_calls_in,
    tool_calls_in,
)

pytestmark = pytest.mark.anyio


def _run(
    *, in_a_conversation: bool = True, channel_identity_id: uuid.UUID | None = None
) -> MagicMock:
    # `channel_identity_id` is named rather than left to the mock: an attribute
    # nobody set answers with a `MagicMock`, and this one is written to a column.
    return MagicMock(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        conversation_id=uuid.uuid4() if in_a_conversation else None,
        channel_identity_id=channel_identity_id,
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

    def test_a_call_the_model_was_told_to_retry_records_a_notice_not_its_text(self, caplog):
        """It happened and it failed, so dropping it would read as "still
        running" for ever - but the retry text is written by whatever raised,
        and `web_search` builds one out of the vendor exception it caught, so
        storing it put the failing endpoint and its query string in a row every
        member who can read the run sees weeks later (#695). The row names the
        tool and the retry; the vendor's text goes to the log beside the write.
        """
        vendor_text = "Tavily search failed: 401 for url 'https://api.tavily.com/search?k=sk-9f2c'"
        with caplog.at_level(logging.WARNING, logger="app.services.transcript"):
            calls = tool_calls_in(
                [
                    _called("web_search", "c1", query="refunds"),
                    ModelRequest(
                        parts=[
                            RetryPromptPart(
                                content=vendor_text,
                                tool_name="web_search",
                                tool_call_id="c1",
                            )
                        ]
                    ),
                ]
            )

        assert calls[0].result == (
            "The web_search call failed and the model was asked to try again. "
            "The server log has the full error."
        )
        assert vendor_text in caplog.text

    def test_a_return_holding_a_url_is_stored_whole(self):
        """The success case is the tool's own answer, not a vendor's exception -
        trimming it too would eat the results a person opens the run to read."""
        calls = tool_calls_in(
            [
                _called("web_search", "c1", query="refunds"),
                _returned("web_search", "c1", "3 hits, best: https://example.com/refunds"),
            ]
        )

        assert calls[0].result == "3 hits, best: https://example.com/refunds"

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


class TestReadingWhatAnInheritedCallReturned:
    """The half `tool_calls_in` drops, which is the whole of a resume's work.

    An approved call was made by the execution that parked, so a resume produces
    its return and not the call - and a return with nothing to hang it on is
    dropped. That is why the one call somebody deliberately reviewed was the one
    call whose output the transcript did not hold.
    """

    def test_a_return_with_no_call_beside_it_is_what_the_approved_call_produced(self):
        settled = settled_calls_in([_returned("execute", "c1", "6 sheets")])

        assert settled == {"c1": "6 sheets"}

    def test_a_call_made_and_returned_here_is_not_an_inherited_one(self):
        """It is a step of its own, and `tool_calls_in` already has it. Counting
        it twice would settle a row that is not open and draw the call twice."""
        settled = settled_calls_in(
            [_called("execute", "c1", command="ls"), _returned("execute", "c1", "a b c")]
        )

        assert settled == {}

    def test_a_refusal_settles_the_call_with_a_notice_not_its_text(self, caplog):
        """A call the model was told to retry did happen and did fail, so it
        settles the row rather than leaving it "still running" for ever - but
        with the same sentence :func:`tool_calls_in` stores, because the resume
        shape writes to the same column the streaming shape does (#695)."""
        vendor_text = "Client error '401 Unauthorized' for url 'https://api.tavily.com/search'"
        with caplog.at_level(logging.WARNING, logger="app.services.transcript"):
            settled = settled_calls_in(
                [
                    ModelRequest(
                        parts=[
                            RetryPromptPart(
                                content=vendor_text, tool_name="web_search", tool_call_id="c1"
                            )
                        ]
                    )
                ]
            )

        assert settled == {
            "c1": (
                "The web_search call failed and the model was asked to try again. "
                "The server log has the full error."
            )
        }
        assert vendor_text in caplog.text

    def test_a_settled_retry_is_logged_once_across_both_readers(self, caplog):
        """`agent_runner` reads one run's messages through both functions, so a
        retry that settles an inherited call used to reach the log twice - once
        from `tool_calls_in` collecting a result it then dropped, once from
        here. One failure, one WARNING."""
        vendor_text = "Client error '401 Unauthorized' for url 'https://api.tavily.com/search'"
        messages = [
            ModelRequest(
                parts=[
                    RetryPromptPart(content=vendor_text, tool_name="web_search", tool_call_id="c1")
                ]
            )
        ]
        with caplog.at_level(logging.WARNING, logger="app.services.transcript"):
            assert tool_calls_in(messages) == []
            assert "c1" in settled_calls_in(messages)

        assert sum(vendor_text in record.getMessage() for record in caplog.records) == 1


class TestWritingTheTranscript:
    @pytest.fixture
    def conversations(self):
        """The repository boundary, which is where the assertions belong."""
        with patch("app.services.transcript.conversation_repo") as repo:
            repo.create_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            repo.create_tool_call = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            repo.complete_tool_call = AsyncMock()
            yield repo

    @pytest.fixture
    def files(self):
        """The other repository this writes through: what a turn arrived with."""
        with patch("app.services.transcript.chat_file_repo") as repo:
            repo.link_to_message = AsyncMock()
            yield repo

    async def test_a_file_that_arrived_with_a_turn_is_linked_to_it(self, conversations, files):
        """The defect this closes: a file posted in a channel became nothing.

        `AttachmentRouter` appends a briefing about each file to the prompt for the
        *model*, and that briefing was the only trace of the file anywhere - so a
        person reading the thread in `/chat` was shown `co tu widzisz` followed by
        `--- Attached file: … (/uploads/…, 43 KB, image)`. The dashboard's own
        uploads have been rows since they existed.
        """
        attachment = MagicMock(id=uuid.uuid4())

        await TranscriptService(_session()).record(
            _run(), prompt="co tu widzisz", answer="A dashboard.", attachments=[attachment]
        )

        linked = files.link_to_message.await_args.kwargs
        asked = conversations.create_message.await_args_list[0].kwargs
        assert linked["file_ids"] == [attachment.id]
        assert (linked["message_id"], asked["role"]) == (
            conversations.create_message.return_value.id,
            "user",
        ), "the file hangs off the turn that brought it, not off the answer"

    async def test_a_file_with_no_caption_still_gets_a_turn_to_hang_off(self, conversations, files):
        """Somebody drops an image and says nothing. That is a turn."""
        attachment = MagicMock(id=uuid.uuid4())

        await TranscriptService(_session()).record(
            _run(), prompt="", answer="A dashboard.", attachments=[attachment]
        )

        asked = conversations.create_message.await_args_list[0].kwargs
        assert (asked["role"], asked["content"]) == ("user", "")
        assert files.link_to_message.await_args.kwargs["file_ids"] == [attachment.id]

    async def test_a_turn_that_arrived_with_nothing_links_nothing(self, conversations, files):
        """And does not open a savepoint to say so.

        The link rides a SAVEPOINT of its own, which costs a round trip to open
        and release. Almost every turn in a deployment carries no file, so the
        empty list is answered before the savepoint rather than inside it.
        """
        await TranscriptService(_session()).record(_run(), prompt="hello", answer="hi")

        files.link_to_message.assert_not_awaited()

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

    async def test_a_turn_from_a_channel_records_which_chat_account_wrote_it(self, conversations):
        """A room is one thread with several people in it, so `role="user"` does
        not say who spoke - and whose list the thread appears in is read off this.
        """
        identity_id = uuid.uuid4()
        run = _run(channel_identity_id=identity_id)

        await TranscriptService(_session()).record(run, prompt="hej", answer="czesc")

        prompt, answer = (call.kwargs for call in conversations.create_message.await_args_list)
        assert prompt["channel_identity_id"] == identity_id
        assert "channel_identity_id" not in answer, "the agent has no chat account"

    async def test_a_turn_typed_into_the_dashboard_records_none(self, conversations):
        """Null is the honest value: there is no chat account behind it."""
        await TranscriptService(_session()).record(_run(), prompt="hej", answer="czesc")

        prompt = conversations.create_message.await_args_list[0].kwargs
        assert prompt["channel_identity_id"] is None

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

    async def test_a_parked_call_is_written_awaiting_approval_not_running(self, conversations):
        """The parked state lives on `agent_runs` and the `approvals` rows, so the
        transcript row was the one place a reloaded conversation could not see it:
        the one call somebody has to decide about read as a step that ran (#601)."""
        await TranscriptService(_session()).record(
            _run(),
            prompt="email ada",
            answer="",
            tool_calls=[
                RecordedToolCall(
                    tool_call_id="c1", tool_name="search", args={"q": "ada"}, result="1 hit"
                ),
                RecordedToolCall(
                    tool_call_id="c2", tool_name="send_email", args={"to": "ada@example.com"}
                ),
            ],
            parked=frozenset({"c2"}),
        )

        statuses = {
            call.kwargs["tool_call_id"]: call.kwargs["status"]
            for call in conversations.create_tool_call.await_args_list
        }
        assert statuses == {"c1": "running", "c2": "awaiting_approval"}

    async def test_a_call_that_merely_never_returned_is_not_marked_as_waiting(self, conversations):
        """A run that broke or was stopped mid-call also leaves a call with no
        result, and nobody can approve it into finishing - `awaiting_approval` is
        only for the calls the run parked on."""
        await TranscriptService(_session()).record(
            _run(),
            prompt="charge it",
            answer="",
            tool_calls=[
                RecordedToolCall(tool_call_id="c1", tool_name="charge_card", args={"amount": 500})
            ],
        )

        assert conversations.create_tool_call.await_args.kwargs["status"] == "running"

    async def test_a_resumed_run_writes_no_user_turn(self, conversations):
        """It picks up at the tool call it stopped on. There is no new question,
        and inventing one would put words in somebody's mouth."""
        await TranscriptService(_session()).record(_run(), prompt=None, answer="finished")

        assert [call.kwargs["role"] for call in conversations.create_message.await_args_list] == [
            "assistant"
        ]

    async def test_a_run_that_produced_no_answer_and_called_nothing_records_the_question(
        self, conversations
    ):
        """A run refused or stopped before it did anything. An assistant message
        with nothing under it would read as the agent replying with silence - and
        the question is what makes the run interpretable at all."""
        await TranscriptService(_session()).record(_run(), prompt="charge it", answer="")

        assert [call.kwargs["role"] for call in conversations.create_message.await_args_list] == [
            "user"
        ]

    async def test_a_continuation_that_parked_again_still_records_what_it_ran(self, conversations):
        """The shape a resumed run stops in, and the one that used to vanish.

        A continuation runs the approved call, then reaches a second gated one and
        parks: no answer, so nothing was written at all - not the command that ran,
        not what it returned. It ran, it cost money and it changed a workspace, and
        history showed the run going from one approval straight to the next.
        """
        await TranscriptService(_session()).record(
            _run(),
            prompt=None,
            answer="",
            tool_calls=[
                RecordedToolCall(
                    tool_call_id="c1",
                    tool_name="execute",
                    args={"command": "python read.py"},
                    result="6 sheets",
                ),
                RecordedToolCall(
                    tool_call_id="c2", tool_name="execute", args={"command": "python parse.py"}
                ),
            ],
        )

        answer = conversations.create_message.await_args.kwargs
        assert (answer["role"], answer["content"]) == ("assistant", "")
        assert [
            call.kwargs["tool_call_id"] for call in conversations.create_tool_call.await_args_list
        ] == ["c1", "c2"]
        # The one the run is now parked on is left open; the one that ran is not.
        conversations.complete_tool_call.assert_awaited_once()
        assert conversations.complete_tool_call.await_args.kwargs["result"] == "6 sheets"

    async def test_the_approved_call_gets_the_result_it_was_waiting_for(self, conversations):
        """The row the run left open when it parked, closed by the resume that ran
        it. Without this the one call a person reviewed is the one call that opens
        onto nothing, live and after a reload (agenticos#506)."""
        row = MagicMock(id=uuid.uuid4())
        conversations.get_open_tool_call_in_run = AsyncMock(return_value=row)
        run = _run()

        await TranscriptService(_session()).record(
            run, prompt=None, answer="Six sheets.", settled={"c1": "6 sheets"}
        )

        looked_up = conversations.get_open_tool_call_in_run.await_args.kwargs
        assert (looked_up["run_id"], looked_up["tool_call_id"]) == (run.id, "c1")
        completed = conversations.complete_tool_call.await_args.kwargs
        assert (completed["db_tool_call"], completed["result"]) == (row, "6 sheets")

    async def test_a_result_for_a_call_nothing_recorded_writes_no_row(self, conversations):
        """A return with no step in the transcript belongs to a call that was
        never written. Inventing a row would put a step in a turn that has no
        other trace of it."""
        conversations.get_open_tool_call_in_run = AsyncMock(return_value=None)

        await TranscriptService(_session()).record(
            _run(), prompt=None, answer="done", settled={"c1": "6 sheets"}
        )

        conversations.complete_tool_call.assert_not_awaited()

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
        either to a failed insert would be the worst possible trade.

        The cause is logged with the traceback rather than as a bare warning: the
        run row surviving is what makes this recoverable, and a swallowed
        exception nobody recorded leaves a reader knowing only that a transcript
        is missing."""
        conversations.create_message = AsyncMock(side_effect=RuntimeError("no connection"))

        await TranscriptService(_session()).record(_run(), prompt="hello", answer="hi")

        assert "transcript_write_failed" in caplog.text
        assert "no connection" in caplog.text
        assert "RuntimeError" in caplog.text

    async def test_a_files_link_that_fails_costs_the_files_and_not_the_turn(
        self, conversations, caplog
    ):
        """The link is the one write here touching rows the conversation does not
        own, so it gets a SAVEPOINT of its own. Sharing the transcript's would
        mean a run that has already spent money losing its answer and its tool
        calls because a file could not be attached to the question."""
        with patch("app.services.transcript.chat_file_repo") as chat_files:
            chat_files.link_to_message = AsyncMock(side_effect=RuntimeError("deadlock detected"))

            await TranscriptService(_session()).record(
                _run(),
                prompt="which row is the outlier?",
                answer="row 12",
                attachments=[MagicMock(id=uuid.uuid4())],
            )

        assert "transcript_file_link_failed" in caplog.text
        roles = [call.kwargs["role"] for call in conversations.create_message.await_args_list]
        assert roles == ["user", "assistant"]
