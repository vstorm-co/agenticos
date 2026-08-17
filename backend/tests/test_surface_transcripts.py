"""Every non-streaming surface records the transcript its run produced.

A run reaches :class:`~app.services.agent_runner.AgentRunnerService` from six
places, and for most of the platform's life only web chat recorded what was
said. The embedded widget left its conversation empty, a channel `@mention` and
a channel bot's default agent wrote nothing - or two lines of text with no tool
calls, no model and no version - and the HTTP API and every resumed run recorded
nothing at all. An organization was billed for an answer given to a visitor on a
client's site, with no row saying what was asked or what was said back (#205).

The fix moved the write into :meth:`AgentRunnerService._run`, the one place a
non-streaming run executes, so a surface cannot forget it. These tests drive each
surface's *real* entry point - the widget session, an `@slug` mention, a bot's
default agent - and assert the turns land at the repository boundary: the
question, the answer attributed to the model and version that produced it, and
the tool calls with their arguments and their results. Asserting that
`transcript.record` was called would prove the wiring and nothing about the
rows; asserting the rows is the point, because the rows are what was missing.

The transcript only ever carries the prompt, the answer, the tool arguments and
results, and the model label, so no persisted row can leak a credential - the
secrets a run unseals never reach it. The two surfaces not here are tested where
their own machinery is: `tests/test_agent_session.py` keeps a failed web-chat
turn's partial answer, and `tests/test_agent_runner.py` with
`tests/test_transcript.py` cover a run resumed after an approval, whose
continuation records over HTTP rather than the socket a conversation streams.

The same harness answers the other half of #39, and it is here rather than in a
file of its own because the surface's real entry point has to be driven either
way: **a run that failed is still in history, with what it spent.** Audit
finding 3 was that only web chat committed, so a failed run on any other surface
flushed its cost and rolled it back - no row, no budget impact, and an
organization billed by a provider for a request nothing recorded.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import SpendLedger, record_ambient_usage
from app.agents.capabilities.compaction import ContextGauge
from app.agents.capabilities.system_reminders import ReminderState
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus, RunSurface
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.channels.mentions import ChannelAgentRouter
from app.services.embed_session import EmbedSession

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _db() -> MagicMock:
    """A session whose SAVEPOINT is a no-op and whose commit is awaitable.

    `_run` commits its own terminal write, and `TranscriptService.record`
    wraps the transcript in `begin_nested()`; both have to be satisfiable for
    the assertions to sit on the repository boundary that
    `tests/integration/test_transcript_savepoint.py` exercises against a real
    database.
    """
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=None))
    db.begin_nested = MagicMock(side_effect=_noop_savepoint)
    return db


def _searched_then_answered(output: str) -> MagicMock:
    """A finished run that searched the knowledge base before answering.

    The tool call and its return are both present, which is what an ordinary
    (non-resumed) turn produces - so the transcript writes one closed step.
    """
    messages = [
        ModelResponse(
            parts=[ToolCallPart(tool_name="search_kb", args={"q": "refund"}, tool_call_id="c1")]
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="search_kb", content="30 days", tool_call_id="c1")]
        ),
    ]
    return MagicMock(output=output, new_messages=MagicMock(return_value=messages))


class _Iteration:
    """A run to iterate, standing in for the library's own.

    It yields no nodes. Which frames a surface sends is pinned in
    `tests/test_agent_session.py` and `tests/test_embed_frames.py`; what these
    tests are about is the rows a turn leaves behind. The outcome is awaited on
    the first step so that a model which raises does so where the real one would -
    inside the loop, with the settle path around it.
    """

    def __init__(self, outcome: AsyncMock) -> None:
        self._outcome = outcome
        self._started = False
        self.result: Any = None

    def __aiter__(self) -> _Iteration:
        return self

    async def __anext__(self) -> Any:
        if self._started:
            raise StopAsyncIteration
        self._started = True
        self.result = await self._outcome()
        raise StopAsyncIteration


@asynccontextmanager
async def _iterating(outcome: AsyncMock) -> AsyncIterator[_Iteration]:
    yield _Iteration(outcome)


@contextmanager
def _run_yielding(agent_run: AsyncMock) -> Iterator[tuple[dict[str, PreparedRun], MagicMock]]:
    """Stub the build, the terminal write and the transcript's repository.

    `prepare` is replaced with one that opens a real :class:`PreparedRun` around
    the `conversation_id` the surface passed - so the transcript lands in the
    conversation the surface chose, not one this harness invented - and drives
    `agent_run` as the model call. Everything else in `_run` and `finish` is
    real, including `TranscriptService.record`.

    Yields the captured prepared run and the mocked conversation repository, so a
    test can read back the exact turns the surface caused to be written.
    """
    captured: dict[str, PreparedRun] = {}

    def prepare(
        _ctx: Any, agent_id: uuid.UUID, *, conversation_id: uuid.UUID | None = None, **_kwargs: Any
    ) -> PreparedRun:
        built = MagicMock()
        built.ledger = SpendLedger()
        built.model_label = "gpt-4.1"
        built.context = ContextGauge()
        built.reminder_state = ReminderState()
        built.agent.run = agent_run
        # The streaming half, for a surface that shows an answer arriving. The
        # widget is one since #634, so its turns reach `iterate` rather than `run`.
        built.agent.iter = MagicMock(side_effect=lambda *_a, **_k: _iterating(agent_run))
        prepared = PreparedRun(
            run=MagicMock(
                id=uuid.uuid4(),
                agent_id=agent_id,
                agent_version_id=uuid.uuid4(),
                conversation_id=conversation_id,
            ),
            agent=MagicMock(),
            spec=MagicMock(),
            built=built,
            approvals=MagicMock(parked={}, requested=[]),
        )
        captured["prepared"] = prepared
        return prepared

    with (
        patch.object(AgentRunnerService, "prepare", new=AsyncMock(side_effect=prepare)),
        patch("app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()),
        patch("app.services.transcript.conversation_repo") as conversations,
    ):
        conversations.create_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        # What this run's earlier turns already claim of its cost, subtracted so a
        # resumed run does not count its parked half twice.
        conversations.attributed_to_run = AsyncMock(return_value=(0, 0, Decimal(0)))
        conversations.create_tool_call = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        conversations.complete_tool_call = AsyncMock()
        conversations.get_open_tool_call_in_run = AsyncMock(return_value=None)
        yield captured, conversations


def _assert_full_turn(
    conversations: MagicMock, run: MagicMock, *, question: str, answer: str
) -> None:
    """The question, the answer, and the tool call all reached the transcript."""
    assert len(conversations.create_message.await_args_list) == 2
    user, assistant = (call.kwargs for call in conversations.create_message.await_args_list)
    assert (user["role"], user["content"], user["run_id"]) == ("user", question, run.id)
    assert (assistant["role"], assistant["content"], assistant["run_id"]) == (
        "assistant",
        answer,
        run.id,
    )
    # Attributed to the model and version that ran, not to whatever the agent
    # says today - a bot that recorded "role and content only" was the #205 case.
    assert assistant["model_name"] == "gpt-4.1"
    assert (assistant["agent_id"], assistant["agent_version_id"]) == (
        run.agent_id,
        run.agent_version_id,
    )
    tool = conversations.create_tool_call.await_args.kwargs
    assert (tool["tool_name"], tool["args"]) == ("search_kb", {"q": "refund"})
    assert conversations.complete_tool_call.await_args.kwargs["result"] == "30 days"


def _widget_session(db: MagicMock, *, embed: MagicMock | None = None) -> EmbedSession:
    """A widget session whose turn opens `db`.

    The factory rather than the session itself: `EmbedSession` opens one per turn
    so an idle socket holds no pooled connection (#39).
    """

    @asynccontextmanager
    async def sessions() -> AsyncIterator[MagicMock]:
        yield db

    return EmbedSession(
        sessions=sessions,
        embed=embed if embed is not None else _embed(),
        visitor=None,
        websocket=MagicMock(),
    )


@contextmanager
def _the_widgets_rows() -> Iterator[None]:
    """The conversation the turn opens, its history, and the owner's membership."""
    with (
        patch(
            "app.services.embed_session.conversation_repo.create_conversation",
            new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        ),
        patch(
            "app.services.embed_session.conversation_repo.count_messages",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.embed_session.conversation_repo.get_messages_by_conversation",
            new=AsyncMock(return_value=[]),
        ),
        # The thread the model is told. Read through the service since #49,
        # because where a summary has run that is where the history starts.
        patch("app.services.embed_session.ConversationService") as reader,
        patch(
            "app.services.access.member_repo.get_active",
            new=AsyncMock(return_value=MagicMock(role="builder")),
        ),
    ):
        reader.return_value.model_history = AsyncMock(return_value=[])
        yield


def _embed(*, context: str | None = None) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        name="Support",
        context=context,
    )


class TestAWidgetRunRecordsItsTranscript:
    """The widget is the billing-integrity case #205 opens with: a public URL
    with a model behind it, answering a visitor on somebody else's site. A run
    with a cost and no transcript is a bill nobody can reconstruct."""

    async def test_a_widget_run_records_the_question_the_answer_and_the_tool_call(self) -> None:
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, conversations),
            _the_widgets_rows(),
        ):
            answer, _run = await session._answer("What's your refund window?")

        assert answer == "The refund window is 30 days."
        _assert_full_turn(
            conversations,
            captured["prepared"].run,
            question="What's your refund window?",
            answer="The refund window is 30 days.",
        )

    async def test_a_broken_widget_run_still_records_what_the_visitor_asked(self) -> None:
        """The run that failed is the one somebody opens. Without the question
        there is a charge on the organization's month and nothing that says what
        it paid for."""
        session = _widget_session(_db())
        run = AsyncMock(side_effect=RuntimeError("provider down"))

        with (
            _run_yielding(run) as (captured, conversations),
            _the_widgets_rows(),
            pytest.raises(RuntimeError),
        ):
            await session._answer("What's your refund window?")

        recorded = conversations.create_message.await_args_list
        assert [call.kwargs["role"] for call in recorded] == ["user"]
        assert recorded[0].kwargs["content"] == "What's your refund window?"

    async def test_the_transcript_holds_the_visitors_words_not_the_prompt_around_them(self) -> None:
        """The operator's placement note is addressed to the model, not to a reader.

        The widget prepends it to the first message, so recording what was *sent*
        made the opening turn of every conversation read as the visitor reciting a
        briefing about the page they were on.
        """
        session = _widget_session(_db(), embed=_embed(context="the pricing page"))
        run = AsyncMock(return_value=_searched_then_answered("Thirty days."))

        with _run_yielding(run) as (_captured, conversations), _the_widgets_rows():
            await session._answer("What's your refund window?")

        asked = conversations.create_message.await_args_list[0].kwargs
        assert asked["content"] == "What's your refund window?"


class TestAFailedRunIsStillInHistoryWithItsCost:
    """The other half of #39, per surface, because the fix is central.

    Audit finding 3: only web chat committed, so a failed run on any other
    surface flushed its cost and rolled it back. No row, no budget impact, and an
    organization billed by a provider for a request nothing recorded. The fix is
    one `commit` inside `AgentRunnerService._run` - which is exactly the kind of
    fix that regresses quietly, because it is one line and no test named a
    surface.

    Each case is the real failure rather than an immediate one: the model is
    called, tokens are spent, and *then* something breaks. Recording the spend
    through `record_ambient_usage` means these also prove the metering wrapper is
    live on the surface - the ambient call finds an active ledger or it finds
    nothing, which is agenticos#16 from the other direction.
    """

    @staticmethod
    def _spent_then_broke() -> AsyncMock:
        """A turn that embeds something, and then the provider goes away."""

        async def run(*_args: Any, **_kwargs: Any) -> None:
            record_ambient_usage(
                "text-embedding-3-small", RequestUsage(input_tokens=1000), "openai"
            )
            raise RuntimeError("the provider went away")

        return AsyncMock(side_effect=run)

    async def test_a_broken_widget_run_keeps_its_row_its_status_and_its_cost(self) -> None:
        db = _db()
        session = _widget_session(db)

        with (
            _run_yielding(self._spent_then_broke()),
            _the_widgets_rows(),
            patch(
                "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
            ) as finish_run,
            pytest.raises(RuntimeError),
        ):
            await session._answer("What's your refund window?")

        recorded = finish_run.await_args.kwargs
        assert recorded["status"] == RunStatus.FAILED.value
        assert recorded["cost_usd"] == Decimal("0.00002")
        # The commit is what makes the row outlive the turn: the session context
        # rolls back on the exception this test is asserting through.
        db.commit.assert_awaited()

    async def test_a_broken_api_run_keeps_its_row_its_status_and_its_cost(self) -> None:
        """Through `execute`, which is what the route calls and all the route
        does - the HTTP layer adds a response model and nothing else."""
        db = _db()
        context = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.BUILDER.value
        )

        with (
            _run_yielding(self._spent_then_broke()),
            patch(
                "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
            ) as finish_run,
            pytest.raises(RuntimeError),
        ):
            await AgentRunnerService(db).execute(
                context,
                uuid.uuid4(),
                "What's your refund window?",
                surface=RunSurface.API,
            )

        recorded = finish_run.await_args.kwargs
        assert recorded["status"] == RunStatus.FAILED.value
        assert recorded["cost_usd"] == Decimal("0.00002")
        db.commit.assert_awaited()


class TestAMentionRecordsItsTranscript:
    """`@support what is the refund window` runs as the sender through the runner,
    so it leaves the same transcript a web-chat run does - the mention path used
    to pass a `conversation_id` through and write nothing into it."""

    async def test_a_mention_records_the_full_turn(self) -> None:
        conversation_id = uuid.uuid4()
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, conversations),
            patch(
                "app.services.channels.mentions.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="builder")),
            ),
            patch(
                "app.services.channels.mentions.agent_repo.get_by_slug",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "app.services.channels.mentions.agent_exposure_repo.get_for_bot",
                new=AsyncMock(return_value=MagicMock(is_active=True)),
            ),
            patch.object(
                ChannelAgentRouter,
                "_with_usage",
                new=AsyncMock(side_effect=lambda _ctx, answer, _run, **_kw: answer),
            ),
        ):
            answered = await ChannelAgentRouter(_db()).answer(
                "@support what is the refund window",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                conversation_id=conversation_id,
                platform_chat_id="C123",
            )

        assert answered.text == "The refund window is 30 days."
        assert captured["prepared"].run.conversation_id == conversation_id
        _assert_full_turn(
            conversations,
            captured["prepared"].run,
            question="what is the refund window",
            answer="The refund window is 30 days.",
        )


class TestTheDefaultAgentRecordsItsTranscript:
    """A bot with one exposed agent answers an unaddressed message through it. It
    used to record `role` and `content` only - so #205's "tool calls, model and
    agent version, not only text" is exactly what this asserts."""

    async def test_the_default_agent_records_its_tool_calls_model_and_version(self) -> None:
        conversation_id = uuid.uuid4()
        exposure, agent = MagicMock(is_active=True), MagicMock(id=uuid.uuid4(), slug="support")
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, conversations),
            patch(
                "app.services.channels.mentions.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(exposure, agent)]),
            ),
            patch(
                "app.services.channels.mentions.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="builder")),
            ),
            patch.object(
                ChannelAgentRouter,
                "_with_usage",
                new=AsyncMock(side_effect=lambda _ctx, answer, _run, **_kw: answer),
            ),
        ):
            answered = await ChannelAgentRouter(_db()).answer_default(
                "what is the refund window",
                platform="telegram",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                conversation_id=conversation_id,
                platform_chat_id="123",
            )

        assert answered.text == "The refund window is 30 days."
        assert captured["prepared"].run.conversation_id == conversation_id
        _assert_full_turn(
            conversations,
            captured["prepared"].run,
            question="what is the refund window",
            answer="The refund window is 30 days.",
        )

    async def test_a_channel_turn_links_the_file_it_ran_on_to_the_user_message(self) -> None:
        """A file dropped on a bot is stored, read by the agent, and then belongs
        to the turn it was asked about. It used to keep `message_id` NULL for
        ever, because only web chat linked one - and `chat_files` carries no
        organization, so an unlinked row is scoped by `user_id` alone and the
        conversation holding the question does not know the file exists (#690).
        """
        exposure, agent = MagicMock(is_active=True), MagicMock(id=uuid.uuid4(), slug="support")
        run = AsyncMock(return_value=_searched_then_answered("Row 12 is the outlier."))
        attachment = MagicMock(id=uuid.uuid4(), filename="q3.csv", parsed_content="a,b\n1,2")
        user_message, assistant_message = MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())

        with (
            _run_yielding(run) as (_captured, conversations),
            patch("app.services.transcript.chat_file_repo") as chat_files,
            patch(
                "app.services.channels.mentions.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(exposure, agent)]),
            ),
            patch(
                "app.services.channels.mentions.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="builder")),
            ),
            patch.object(
                ChannelAgentRouter,
                "_with_usage",
                new=AsyncMock(side_effect=lambda _ctx, answer, _run, **_kw: answer),
            ),
        ):
            conversations.create_message = AsyncMock(side_effect=[user_message, assistant_message])
            conversations.attributed_to_run = AsyncMock(return_value=(0, 0, Decimal(0)))
            chat_files.link_to_message = AsyncMock()
            await ChannelAgentRouter(_db()).answer_default(
                "which row is the outlier",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                platform_chat_id="C123",
                attachments=[attachment],
            )

        linked = chat_files.link_to_message.await_args.kwargs
        assert linked["file_ids"] == [attachment.id]
        assert linked["message_id"] == user_message.id

    async def test_a_captionless_image_on_a_workspaceless_agent_leaves_a_named_user_turn(
        self,
    ) -> None:
        """A photo with no words under it, on an agent with no workspace, yields
        no prompt text at all: the image reaches the model as bytes beside an
        empty string. The turn still happened and was billed, so the transcript
        holds a user message naming what arrived - not a blank one - and the
        file hangs off it (#704).
        """
        exposure, agent = MagicMock(is_active=True), MagicMock(id=uuid.uuid4(), slug="support")
        run = AsyncMock(return_value=_searched_then_answered("A dashboard."))
        attachment = MagicMock(
            id=uuid.uuid4(),
            filename="photo.jpg",
            file_type="image",
            size=1024,
            mime_type="image/jpeg",
            storage_path=f"uploads/{uuid.uuid4().hex}.jpg",
        )
        user_message, assistant_message = MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())

        with (
            _run_yielding(run) as (_captured, conversations),
            patch("app.services.transcript.chat_file_repo") as chat_files,
            patch("app.services.attachments.get_file_storage") as storage,
            patch(
                "app.services.channels.mentions.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[(exposure, agent)]),
            ),
            patch(
                "app.services.channels.mentions.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="builder")),
            ),
            patch.object(
                ChannelAgentRouter,
                "_with_usage",
                new=AsyncMock(side_effect=lambda _ctx, answer, _run, **_kw: answer),
            ),
        ):
            storage.return_value.load = AsyncMock(return_value=b"\x89PNG")
            conversations.create_message = AsyncMock(side_effect=[user_message, assistant_message])
            conversations.attributed_to_run = AsyncMock(return_value=(0, 0, Decimal(0)))
            chat_files.link_to_message = AsyncMock()
            await ChannelAgentRouter(_db()).answer_default(
                "",
                platform="telegram",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                platform_chat_id="123",
                attachments=[attachment],
            )

        asked = conversations.create_message.await_args_list[0].kwargs
        assert (asked["role"], asked["content"]) == ("user", "Attached image: photo.jpg")
        assert chat_files.link_to_message.await_args.kwargs["message_id"] == user_message.id


class TestKeepingASummaryOnASurfaceThatIsNotTheChat:
    """A channel thread is long-lived and never rolls over, so it is the surface
    a per-turn summary costs the most on: every message past the window bought
    one, over a history one turn longer each time (#49)."""

    async def test_a_summary_is_written_to_the_conversation_it_summarised(self) -> None:
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, _conversations),
            _the_widgets_rows(),
            patch("app.services.agent_runner.ConversationService") as service,
        ):
            service.return_value.keep_summary = AsyncMock()
            service.return_value.keep_overhead = AsyncMock()

            def summarise(*_args: Any, **_kwargs: Any) -> Any:
                captured["prepared"].built.context.summarized = True
                return _searched_then_answered("The refund window is 30 days.")

            run.side_effect = summarise
            await session._answer("What's your refund window?")

        kept = service.return_value.keep_summary
        assert kept.await_args.args[0] == captured["prepared"].run.conversation_id

    async def test_a_turn_that_summarised_nothing_writes_nothing(self) -> None:
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (_captured, _conversations),
            _the_widgets_rows(),
            patch("app.services.agent_runner.ConversationService") as service,
        ):
            service.return_value.keep_summary = AsyncMock()
            service.return_value.keep_overhead = AsyncMock()
            await session._answer("What's your refund window?")

        service.return_value.keep_summary.assert_not_awaited()

    async def test_what_a_request_carries_is_recorded_on_every_turn(self) -> None:
        """Not only a summarising one: it is what the next turn needs before it
        has a response of its own to measure (#49)."""
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, _conversations),
            _the_widgets_rows(),
            patch("app.services.agent_runner.ConversationService") as service,
        ):
            service.return_value.keep_summary = AsyncMock()
            service.return_value.keep_overhead = AsyncMock()

            def measure(*_args: Any, **_kwargs: Any) -> Any:
                captured["prepared"].built.context.overhead = 3_865
                return _searched_then_answered("The refund window is 30 days.")

            run.side_effect = measure
            await session._answer("What's your refund window?")

        assert service.return_value.keep_overhead.await_args.args[1] == 3_865

    async def test_the_reminder_cadence_is_written_back_when_it_advanced(self) -> None:
        """So a reminder set to fire every N requests resumes next turn (#787)."""
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (captured, _conversations),
            _the_widgets_rows(),
            patch("app.services.agent_runner.ConversationService") as service,
        ):
            service.return_value.keep_summary = AsyncMock()
            service.return_value.keep_overhead = AsyncMock()
            service.return_value.keep_reminder_state = AsyncMock()

            def advance(*_args: Any, **_kwargs: Any) -> Any:
                captured["prepared"].built.reminder_state.request_count = 2
                captured["prepared"].built.reminder_state.fire_counts["0"] = 1
                return _searched_then_answered("The refund window is 30 days.")

            run.side_effect = advance
            await session._answer("What's your refund window?")

        kept = service.return_value.keep_reminder_state
        assert kept.await_args.args[1] == {"request_count": 2, "fire_counts": {"0": 1}}

    async def test_a_turn_whose_cadence_did_not_advance_writes_nothing(self) -> None:
        """An agent with no reminders never writes an empty cadence blob."""
        session = _widget_session(_db())
        run = AsyncMock(return_value=_searched_then_answered("The refund window is 30 days."))

        with (
            _run_yielding(run) as (_captured, _conversations),
            _the_widgets_rows(),
            patch("app.services.agent_runner.ConversationService") as service,
        ):
            service.return_value.keep_summary = AsyncMock()
            service.return_value.keep_overhead = AsyncMock()
            service.return_value.keep_reminder_state = AsyncMock()
            await session._answer("What's your refund window?")

        service.return_value.keep_reminder_state.assert_not_awaited()
