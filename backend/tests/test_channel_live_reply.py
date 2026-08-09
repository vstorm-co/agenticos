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
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent_runner import AgentRunnerService
from app.services.channels.live_reply import EDIT_INTERVAL, WORKING, LiveReply, doing


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

    async def test_a_tool_nobody_wrote_a_sentence_for_falls_back(self):
        """A person watching a chat should not have to learn that
        `mcp_github_list_pull_requests` is a thing this product has."""
        assert doing("mcp_github_list_pull_requests") == WORKING

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
