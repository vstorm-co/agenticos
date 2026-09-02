"""An answer a chat can watch being written (#514).

A channel bot posted one finished message and nothing before it, so a question
that took twelve seconds and three tool calls bought twelve seconds of silence -
indistinguishable from a bot that had crashed. The silence was longest exactly
when the most was happening, because a tool call produces no text at all while
it runs.

What is asserted here is the part that is the same on every platform: what the
message says at each moment, and how often it is rewritten. How a given platform
posts and edits is its adapter's business.
"""

import contextlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ToolCallPart,
)

from app.services.agent_runner import AgentRunnerService
from app.services.channels.live_reply import (
    EDIT_INTERVAL,
    WORKING,
    LiveReply,
    channel_stream,
    doing,
)


@contextlib.asynccontextmanager
async def _yielding(value: object) -> AsyncIterator[object]:
    """`prepared.iterate` as an async context manager, without a real agent."""
    yield value


pytestmark = pytest.mark.anyio


class _Clock:
    """A hand-wound clock, so the throttle is tested rather than waited for."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def _reply() -> tuple[LiveReply, AsyncMock, _Clock]:
    push = AsyncMock()
    clock = _Clock()
    return LiveReply(push, now=clock), push, clock


class TestWhatTheMessageSays:
    async def test_a_tool_says_what_it_is_doing_at_once(self):
        """This is the message that breaks the silence - a status arriving a
        second late has missed most of the point."""
        reply, push, _clock = _reply()

        await reply.working_on(doing("web_search"))

        push.assert_awaited_once_with("Searching the web…")

    async def test_the_message_opens_as_an_ellipsis_and_nothing_more(self):
        """A sentence claims more than "your question arrived": it reads as the
        answer starting, and has to be deleted a second later when the real one
        does. Every chat client already reads three dots this way."""
        reply, push, _clock = _reply()

        await reply.add("")

        assert push.await_args is None or push.await_args.args[0] == WORKING

    async def test_a_tool_nobody_wrote_a_sentence_for_falls_back(self):
        """A person watching a chat should not have to learn that
        `mcp_github_list_pull_requests` is a thing this product has - but by then
        something is happening, so it says so rather than showing the ellipsis."""
        assert doing("mcp_github_list_pull_requests") == "Working on it…"

    async def test_text_replaces_the_status_once_there_is_any(self):
        """A status line under an answer that has started arriving is noise."""
        reply, push, clock = _reply()
        await reply.working_on("Searching the web…")

        clock.tick(EDIT_INTERVAL)
        await reply.add("Here is ")

        assert push.await_args.args[0] == "Here is "

    async def test_a_status_does_not_overwrite_an_answer_in_progress(self):
        """A second tool call after the model has started writing must not wipe
        out what somebody is already reading."""
        reply, push, clock = _reply()
        clock.tick(EDIT_INTERVAL)
        await reply.add("Here is ")
        push.reset_mock()

        await reply.working_on("Drawing a chart…")

        push.assert_not_awaited()

    async def test_the_whole_answer_is_kept_not_just_the_last_fragment(self):
        reply, _push, clock = _reply()
        await reply.add("Here ")
        clock.tick(EDIT_INTERVAL)
        await reply.add("we go")

        assert reply.text == "Here we go"


class TestHowOftenItIsRewritten:
    async def test_fragments_inside_one_interval_cost_one_edit(self):
        """Editing per token is hundreds of writes a second against somebody
        else's self-hosted server, and all three platforms rate-limit."""
        reply, push, clock = _reply()
        clock.tick(EDIT_INTERVAL)

        for word in ("a ", "b ", "c ", "d "):
            await reply.add(word)

        push.assert_awaited_once_with("a ")

    async def test_the_next_interval_pushes_again(self):
        reply, push, clock = _reply()
        clock.tick(EDIT_INTERVAL)
        await reply.add("a ")
        clock.tick(EDIT_INTERVAL)
        await reply.add("b")

        assert push.await_count == 2
        assert push.await_args.args[0] == "a b"

    async def test_unchanged_text_is_not_rewritten(self):
        """A model that pauses mid-sentence should not cost a write per second
        saying the same thing."""
        reply, push, clock = _reply()
        await reply.working_on("Searching the web…")
        clock.tick(EDIT_INTERVAL * 5)
        await reply.working_on("Searching the web…")

        push.assert_awaited_once()

    async def test_a_failed_edit_costs_that_frame_and_nothing_else(self):
        """The answer is sent whole at the end whatever happened here, so a
        platform that rate-limited us mid-answer must not also lose it."""
        push = AsyncMock(side_effect=RuntimeError("429"))
        clock = _Clock()
        reply = LiveReply(push, now=clock)

        await reply.working_on("Searching the web…")
        clock.tick(EDIT_INTERVAL)
        await reply.add("and here is the answer")

        assert reply.text == "and here is the answer"


class TestWhichHalfOfTheRunnerIsUsed:
    """One settle path, two ways of getting an answer into it.

    Both go through `_run`, so a channel that watches an answer being written is
    metered exactly like an HTTP caller that waits for it. A second copy of the
    settle path is how the streaming chat came to bill nothing for a year
    (agenticos#16).
    """

    async def _answer(self, *, stream, deferred=None):
        prepared = MagicMock()
        prepared.execute = AsyncMock(return_value="waited for")

        agent_run = MagicMock()
        agent_run.result = "streamed"
        prepared.iterate = MagicMock(return_value=_yielding(agent_run))

        result = await AgentRunnerService._answer(
            prepared,
            user_prompt="hi",
            message_history=None,
            deferred_tool_results=deferred,
            stream=stream,
        )
        return result, prepared

    async def test_a_surface_that_cannot_stream_waits_for_the_answer(self):
        result, prepared = await self._answer(stream=None)

        assert result == "waited for"
        prepared.iterate.assert_not_called()

    async def test_a_stream_drives_the_graph_instead(self):
        driven = AsyncMock()

        result, prepared = await self._answer(stream=driven)

        assert result == "streamed"
        prepared.execute.assert_not_awaited()
        driven.assert_awaited_once()

    async def test_a_resumed_run_is_waited_for_even_with_a_stream(self):
        """`iterate()` carries no deferred results, and a resumed run is one
        somebody already waited for once."""
        result, prepared = await self._answer(stream=AsyncMock(), deferred=object())

        assert result == "waited for"
        prepared.iterate.assert_not_called()


class TestTheFinalEditNeverLosesTheAnswer:
    """`live_reply` promises the answer arrives whole at the end whatever
    happened. `_deliver` edits the watched placeholder into the final answer; a
    failed edit must fall through to a fresh post with the whole answer, not
    blank it and post an empty message under a `…` that never resolves.
    """

    @staticmethod
    def _answered(**overrides: object) -> MagicMock:
        answered = MagicMock()
        answered.awaiting_approval_run_id = overrides.get("awaiting_approval_run_id")
        answered.image_png = overrides.get("image_png")
        answered.attachments = overrides.get("attachments", [])
        return answered

    @staticmethod
    def _router() -> tuple[object, AsyncMock]:
        from app.services.channels.router import ChannelMessageRouter

        router = ChannelMessageRouter()
        router._send_reply = AsyncMock()  # type: ignore[method-assign]
        return router, router._send_reply

    async def test_a_failed_final_edit_reposts_the_whole_answer(self):
        router, send_reply = self._router()
        adapter = MagicMock(update_reply=AsyncMock(side_effect=RuntimeError("rate limited")))
        incoming = MagicMock(platform="mattermost", platform_chat_id="c1")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            await router._deliver(
                MagicMock(api_base_url=None), incoming, "the whole answer", self._answered(), "h1"
            )

        send_reply.assert_awaited_once()
        assert send_reply.await_args.args[2] == "the whole answer"

    async def test_a_successful_edit_with_no_extra_posts_nothing_further(self):
        router, send_reply = self._router()
        adapter = MagicMock(update_reply=AsyncMock())
        incoming = MagicMock(platform="mattermost", platform_chat_id="c1")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            await router._deliver(
                MagicMock(api_base_url=None), incoming, "answered", self._answered(), "h1"
            )

        send_reply.assert_not_awaited()


class TestTheMentionPlaceholderOpensOnlyIfSomethingIsSaid:
    """A handle that names a colleague, not an agent of ours, raises before a
    token is streamed. The eager placeholder used to be posted before that was
    known, so the bot left a "…" hanging under two people's conversation
    (agenticos#634). Opened lazily, the first push is what posts it, and a run
    that streams nothing posts nothing.
    """

    @staticmethod
    def _router() -> object:
        from app.services.channels.router import ChannelMessageRouter

        return ChannelMessageRouter()

    async def test_a_reply_that_never_pushes_opens_no_placeholder(self):
        adapter = MagicMock(begin_reply=AsyncMock(return_value="h1"), update_reply=AsyncMock())

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            _live, handle_of = self._router()._lazy_reply(
                MagicMock(api_base_url=None),
                MagicMock(platform="mattermost", platform_chat_id="c1"),
            )

        adapter.begin_reply.assert_not_awaited()
        assert handle_of() is None

    async def test_the_first_push_posts_the_placeholder_and_captures_the_handle(self):
        adapter = MagicMock(begin_reply=AsyncMock(return_value="h1"), update_reply=AsyncMock())

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            live, handle_of = self._router()._lazy_reply(
                MagicMock(api_base_url=None),
                MagicMock(platform="mattermost", platform_chat_id="c1"),
            )
            await live.add("the answer as it arrives")

        adapter.begin_reply.assert_awaited_once()
        assert handle_of() == "h1"


class TestAnEmptyAnswerTellsItsReasonsApart:
    """An empty turn is not always a parked approval. Budget and a bare empty
    answer must not be told "that needs approval", which points at a decision
    that was never raised."""

    @staticmethod
    def _answered(*, run_id: object = None, status: object) -> MagicMock:
        answered = MagicMock()
        answered.awaiting_approval_run_id = run_id
        answered.status = status
        return answered

    def test_a_parked_run_links_to_the_decision(self):
        from app.db.models.agent_run import RunStatus
        from app.services.channels.router import _empty_answer

        message = _empty_answer(self._answered(run_id="run-9", status=RunStatus.AWAITING_APPROVAL))

        assert "needs approval" in message
        assert "run-9" in message

    def test_a_budget_stop_says_the_ceiling_was_hit_not_approval(self):
        from app.db.models.agent_run import RunStatus
        from app.services.channels.router import _empty_answer

        message = _empty_answer(self._answered(status=RunStatus.BUDGET_EXCEEDED))

        assert "usage limit" in message
        assert "approval" not in message

    def test_an_answer_empty_for_any_other_reason_does_not_claim_approval(self):
        from app.db.models.agent_run import RunStatus
        from app.services.channels.router import _empty_answer

        for status in (RunStatus.FAILED, RunStatus.COMPLETED):
            message = _empty_answer(self._answered(status=status))
            assert "approval" not in message
            assert "usage limit" not in message


class TestTheEventsTheStreamActuallyReads:
    """The consuming half, which had no test - and that is why the reply looked
    broken in every channel for as long as it did.

    Watching one, the answer appeared a sentence in, grew, and then jumped as the
    beginning arrived with the finished text. The cause was `channel_stream`
    listening to `PartDeltaEvent` alone: `PartStartEvent` carries the *first*
    chunk of a text part's content and no delta repeats it, so the streamed
    message was the answer minus its opening until the final send replaced the
    whole thing.

    Every test above this one drives `LiveReply` directly, which is correct and
    was never the broken half.
    """

    @staticmethod
    def _model_node(*events: object) -> Any:
        """A model-request node whose stream yields these events."""

        async def _events() -> Any:
            for event in events:
                yield event

        stream = MagicMock()
        stream.__aenter__ = AsyncMock(return_value=_events())
        stream.__aexit__ = AsyncMock(return_value=False)
        node = MagicMock()
        node.stream = MagicMock(return_value=stream)
        return node

    async def _driven(self, *events: object) -> LiveReply:
        reply, _push, _clock = _reply()
        node = self._model_node(*events)

        async def _nodes() -> AsyncIterator[object]:
            yield node

        agent_run = MagicMock()
        agent_run.ctx = object()
        agent_run.__aiter__ = lambda _self: _nodes()

        with (
            patch.object(Agent, "is_model_request_node", return_value=True),
            patch.object(Agent, "is_call_tools_node", return_value=False),
        ):
            await channel_stream(reply)(agent_run)
        return reply

    async def test_the_first_chunk_arrives_with_the_part_that_starts(self):
        """The defect, stated as the thing somebody saw: without this the reply
        opens mid-sentence."""
        reply = await self._driven(
            PartStartEvent(index=0, part=TextPart(content="Dzień ")),
            PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="dobry, ")),
            PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="w czym pomóc?")),
        )

        assert reply.text == "Dzień dobry, w czym pomóc?"

    async def test_a_second_text_part_contributes_its_own_first_chunk(self):
        """A model that says something, calls a tool and speaks again emits two
        text parts, and the second one opens the same way the first did."""
        reply = await self._driven(
            PartStartEvent(index=0, part=TextPart(content="Sprawdzam")),
            PartStartEvent(index=1, part=TextPart(content=" - gotowe.")),
        )

        assert reply.text == "Sprawdzam - gotowe."

    async def test_a_tool_call_starting_is_not_the_answer(self):
        """The same event fires for a tool call, and its arguments are not text
        somebody should read in a chat."""
        reply = await self._driven(
            PartStartEvent(index=0, part=ToolCallPart(tool_name="web_search", args="{}")),
            PartDeltaEvent(index=1, delta=TextPartDelta(content_delta="Znalazłem.")),
        )

        assert reply.text == "Znalazłem."

    async def test_thinking_is_not_the_answer_either(self):
        """A model that exposes its reasoning emits it as its own part kind, and a
        chat window is not where that belongs."""
        reply = await self._driven(
            PartStartEvent(index=0, part=ThinkingPart(content="the user wants...")),
            PartStartEvent(index=1, part=TextPart(content="Tak.")),
        )

        assert reply.text == "Tak."
