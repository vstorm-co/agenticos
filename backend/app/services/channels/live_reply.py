"""An answer a chat can watch being written.

A channel bot used to post one finished message and nothing before it. Ask an
agent something that takes twelve seconds and three tool calls and the chat sits
silent for twelve seconds, which is indistinguishable from a bot that crashed -
and the silence is longest exactly when the most is happening, because a tool
call produces no text at all while it runs.

Every platform we serve can edit a message it has already sent, so all three can
do the same thing: post something the moment the question arrives, then change
it as the answer appears. This module is the part that is the same on all of
them - what to say, and how often to say it. Each adapter contributes only how
its own platform posts and edits.

**The throttle is not a nicety.** Editing per token would mean hundreds of writes
a second against somebody else's self-hosted server, and Mattermost, Slack and
Telegram all rate-limit. One edit a second, and only when the text actually
changed, keeps it readable and keeps us a good citizen of a server we do not own.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ToolReturnPart,
)

from app.services.agent_runner import AgentIteration, RunStream
from app.services.channels.base import AnswerStep, NativeAnswer, StepSource

logger = logging.getLogger(__name__)

EDIT_INTERVAL = 1.0
"""Seconds between edits of the message being written.

Fast enough to read as live, slow enough that a long answer costs a couple of
dozen writes rather than a couple of thousand.
"""

# What the bot says while a tool runs and there is no text yet. Named after the
# capability rather than the tool where a name would mean nothing to the person
# waiting - "create_chart" is our vocabulary, not theirs.
_DOING: dict[str, str] = {
    "search_knowledge": "Looking through the knowledge base…",
    "web_search": "Searching the web…",
    "create_chart": "Drawing a chart…",
    "run_python": "Running some code…",
    "run_shell": "Running a command…",
    # The rest of what an agent commonly does while a chat waits (#2068).
    "search_documents": "Looking through the documents…",
    "web_fetch": "Reading a web page…",
    "browse_web": "Browsing the web…",
    "browse_page": "Browsing the web…",
    "generate_image": "Drawing an image…",
    "publish_artifact": "Building a page…",
    "search_conversations": "Looking through earlier conversations…",
    "read_context": "Reading the background notes…",
    "execute": "Running a command…",
    "read_file": "Reading a file…",
    "write_file": "Writing a file…",
    "edit_file": "Editing a file…",
    "task": "Asking a specialist…",
    "ask_user_question": "Preparing a question…",
}

WORKING = "…"
"""What the message says before anything is known.

Three dots rather than a sentence. The message exists to say "your question
arrived and something is happening"; a sentence claims more than that, is read
as the answer starting, and has to be deleted a second later when the real one
begins. Every chat client already reads an ellipsis this way.
"""


_USING_A_TOOL = "Working on it…"
"""What a tool nobody wrote a sentence for looks like while it runs.

Not the bare ellipsis the message opens with: by this point something *is*
happening and the silence has a cause, which is worth saying even when we cannot
say what it is.
"""


_MAX_SOURCES = 5
"""How many pages one step links; a search returning twenty is still five links."""


def step_sources(content: object) -> tuple[StepSource, ...]:
    """The pages a tool's result names, so its step can link them (#2084).

    Read by shape rather than by tool: anything in the result with an `http`
    `url` beside a `title` is a page - a web search's hits, a fetched page, an
    MCP tool that returns links. A result naming none links none.
    """
    found: dict[str, StepSource] = {}

    def walk(value: object) -> None:
        if len(found) >= _MAX_SOURCES:
            return
        if isinstance(value, BaseModel):
            walk(value.model_dump())
        elif isinstance(value, Mapping):
            url, title = value.get("url"), value.get("title")
            if isinstance(url, str) and url.startswith("http") and url not in found:
                found[url] = StepSource(url=url, title=title if isinstance(title, str) else url)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(content)
    return tuple(found.values())[:_MAX_SOURCES]


def doing(tool_name: str) -> str:
    """What to show while `tool_name` runs.

    A tool nobody wrote a sentence for falls back to the generic one rather than
    to its own id: a person watching a chat should not have to learn that
    `mcp_github_list_pull_requests` is a thing this product has.
    """
    return _DOING.get(tool_name, _USING_A_TOOL)


class LiveReply:
    """The message being written, and when to push it.

    Holds what has been streamed and what was last sent, so an edit only happens
    when the two differ - a model that pauses mid-sentence should not cost a
    write per second saying the same thing.
    """

    def __init__(
        self, push: Callable[[str], Awaitable[None]], *, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._push = push
        self._now = now
        self._text = ""
        self._status = WORKING
        self._sent: str | None = None
        self._pushed_at = 0.0

    @property
    def text(self) -> str:
        """Everything the model has written so far."""
        return self._text

    def _shown(self) -> str:
        """What the message should read right now.

        Text as soon as there is any: a status line under an answer that has
        started arriving is noise, and the answer is what somebody is reading.
        """
        return self._text or self._status

    async def add(self, delta: str) -> None:
        """Take a fragment of the answer, and push if it is time."""
        self._text += delta
        await self._maybe_push()

    async def working_on(self, status: str) -> None:
        """Say what is happening while there is nothing to read yet.

        Pushed immediately rather than on the next tick: this is the message
        that breaks a silence, and a status arriving a second late has missed
        most of the point.
        """
        self._status = status
        if not self._text:
            await self._flush()

    async def step(self, step: AnswerStep) -> None:
        """A tool call starting is a status; how it ended is not worth an edit."""
        if step.status == "in_progress":
            await self.working_on(step.title)

    async def _maybe_push(self) -> None:
        if self._now() - self._pushed_at >= EDIT_INTERVAL:
            await self._flush()

    async def _flush(self) -> None:
        shown = self._shown()
        if shown == self._sent:
            return
        self._pushed_at = self._now()
        self._sent = shown
        try:
            await self._push(shown)
        except Exception:
            # A failed edit costs this frame and nothing else. The answer is
            # sent whole at the end whatever happened here, so a platform that
            # rate-limited us mid-answer must not also lose the answer.
            logger.warning("Could not update a live reply", exc_info=True)


class StreamedReply:
    """An answer written into a platform's own streamed message (#2084).

    The text is appended rather than rewritten, at the same once-a-second pace,
    and each tool call is a step of its own instead of a status line the answer
    then replaces. Ending it hands over what is still unsent - or reports that
    the finished answer is not a continuation of what was streamed, which an
    output guardrail redacting the text makes happen, so the caller rewrites the
    message whole.
    """

    def __init__(self, native: NativeAnswer, *, now: Callable[[], float] = time.monotonic) -> None:
        self._native = native
        self._now = now
        self._text = ""
        self._sent = 0
        self._pushed_at = 0.0

    @property
    def text(self) -> str:
        """Everything the model has written so far."""
        return self._text

    @property
    def handle(self) -> str:
        """The streamed message, for rewriting it whole."""
        return self._native.handle

    async def add(self, delta: str) -> None:
        """Take a fragment of the answer, and append it if it is time."""
        self._text += delta
        if self._now() - self._pushed_at >= EDIT_INTERVAL:
            await self._flush()

    async def step(self, step: AnswerStep) -> None:
        """Show a step, after whatever text came before it."""
        await self._flush()
        try:
            await self._native.step(step)
        except Exception:
            # A missing row in the timeline costs nothing the answer needs.
            logger.warning("Could not show a step of a streamed answer", exc_info=True)

    async def finish(self, answer: str, *, failed: bool, feedback_run_id: str | None) -> bool:
        """End the stream; `False` when `answer` has to replace what was streamed.

        Raises whatever the platform raised for the final call, so the caller can
        post the answer some other way rather than lose it.
        """
        await self._flush()
        streamed = self._text[: self._sent]
        continues = answer.startswith(streamed)
        rest = answer[len(streamed) :] if continues else ""
        await self._native.finish(rest, failed=failed, feedback_run_id=feedback_run_id)
        return continues

    async def _flush(self) -> None:
        pending = self._text[self._sent :]
        if not pending:
            return
        self._pushed_at = self._now()
        try:
            await self._native.append(pending)
        except Exception:
            # Left unsent, so the next flush or the finish carries it instead.
            logger.warning("Could not append to a streamed answer", exc_info=True)
            return
        self._sent = len(self._text)


class AnswerSink(Protocol):
    """Where a channel run's text and steps go: an edited placeholder or a native stream."""

    async def add(self, delta: str) -> None: ...

    async def step(self, step: AnswerStep) -> None: ...


def channel_stream(reply: AnswerSink) -> RunStream:
    """Drive an agent run into `reply`.

    Three kinds of event matter to a chat window: a text part starting, the
    deltas that continue it, and a tool starting - which is the beginning of a
    silence somebody has to be told about. Tool results and the end node are
    detail a chat should not carry.

    **The part start is not optional, and reading it as optional is what made the
    reply look broken.** `PartStartEvent` carries the *first* chunk of a text
    part's content, and no delta repeats it - so listening to deltas alone
    streamed an answer with its opening missing, and the finished text sent at the
    end then replaced the whole message. Watching it, the reply appeared a
    sentence in, grew, and then jumped as the beginning arrived. This docstring
    used to say part starts were "already covered by the text", which is where the
    belief was written down.

    Only a `TextPart`: the same event fires for a tool call and, on a model that
    exposes it, for thinking - neither of which is the answer.

    A tool call is a step from its call to its result, named by what it does
    rather than by its id; a result asking the model to retry is a failed step.
    """
    titles: dict[str, str] = {}

    async def stream(agent_run: AgentIteration[Any, Any]) -> None:
        async for node in agent_run:
            if Agent.is_model_request_node(node):
                async with node.stream(agent_run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                            await reply.add(event.part.content)
                        elif isinstance(event, PartDeltaEvent) and isinstance(
                            event.delta, TextPartDelta
                        ):
                            await reply.add(event.delta.content_delta)
            elif Agent.is_call_tools_node(node):
                async with node.stream(agent_run.ctx) as tool_stream:
                    async for event in tool_stream:
                        if isinstance(event, FunctionToolCallEvent):
                            call_id = event.part.tool_call_id
                            titles[call_id] = doing(event.part.tool_name)
                            await reply.step(AnswerStep(call_id, titles[call_id], "in_progress"))
                        elif isinstance(event, FunctionToolResultEvent):
                            call_id = event.tool_call_id
                            failed = isinstance(event.part, RetryPromptPart)
                            await reply.step(
                                AnswerStep(
                                    call_id,
                                    titles.get(call_id, _USING_A_TOOL),
                                    "error" if failed else "complete",
                                    sources=(
                                        step_sources(event.part.content)
                                        if isinstance(event.part, ToolReturnPart)
                                        else ()
                                    ),
                                )
                            )

    return stream
