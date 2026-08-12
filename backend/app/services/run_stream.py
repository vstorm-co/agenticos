"""One turn, as frames, for every socket that shows an answer arriving.

There were two of these. The dashboard's chat iterated the agent's graph and sent
nine kinds of frame; the embedded widget awaited the whole answer and sent one -
so a hosted page showed a lump of text after thirty seconds of nothing, and it
showed it for that reason rather than because a public socket cannot carry more.
Two loops over one transport is two protocols, and the second one always loses:
it was the surface that forgot `message_history`, and it would have been the
surface that forgot the next thing too.

So the loop lives here and the surfaces differ only in **where a frame goes**.
`FrameSink` is that difference: the dashboard sends every frame to the member who
is watching, and a public surface passes one that drops what its operator has not
agreed to show. Filtering at the sink rather than in a renderer is the whole
point of that shape - `show_thinking: false` has to mean the reasoning never left
the server, because hidden in CSS it is an agent's reasoning sitting in a
stranger's devtools.

What is *not* here is anything a surface owns: persistence, the transcript, the
approval panel, `ask_user`. A frame that needs somebody to answer it needs a
somebody, and only the surface knows whether it has one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.messages import TextPart, ThinkingPart, ThinkingPartDelta

from app.services.agent_chat import display_output
from app.services.chat_timeline import TurnTimeline

logger = logging.getLogger(__name__)

type FrameSink = Callable[[str, dict[str, Any]], Awaitable[None]]
"""Where one frame goes, named by its kind.

The kind is the wire `type`, and it is passed rather than chosen by the sink so
that a surface which filters frames filters on the same names the client switches
on. A sink never raises: a visitor who closed the tab must not take the run with
them, and both implementations answer a dead socket by logging.
"""


class RunFrames:
    """Drives an iterated agent run, emitting one frame vocabulary.

    Collects as it goes, because a turn that never finishes still has to be
    written down as what the person watching it actually saw: `timeline` records
    the text and the reasoning in the order they arrived, and `tool_calls` records
    what was called with what and what came back.
    """

    def __init__(
        self,
        *,
        emit: FrameSink,
        timeline: TurnTimeline | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        prompt: str = "",
    ) -> None:
        self.emit = emit
        self.timeline = timeline if timeline is not None else TurnTimeline()
        self.tool_calls = tool_calls if tool_calls is not None else []
        self.prompt = prompt

    async def drive(self, agent_run: Any) -> None:
        """Iterate the run, dispatching each node to its streaming half.

        `agent_run`, and `request_stream` / `handle_stream` below, are Pydantic AI's
        run- and node-stream objects. Their static types are the generic,
        context-manager-yielded streams the library does not export for
        annotation, and each node is narrowed with `Agent.is_*_node` rather than by
        type - so `Any` here is the boundary the narrowing runs behind, not a
        shortcut around one.
        """
        async for node in agent_run:
            if Agent.is_user_prompt_node(node):
                said = node.user_prompt if isinstance(node.user_prompt, str) else self.prompt
                await self.emit("user_prompt_processed", {"prompt": said})
            elif Agent.is_model_request_node(node):
                await self.emit("model_request_start", {})
                async with node.stream(agent_run.ctx) as request_stream:
                    await self.request(request_stream)
            elif Agent.is_call_tools_node(node):
                await self.emit("call_tools_start", {})
                async with node.stream(agent_run.ctx) as handle_stream:
                    await self.tools(handle_stream)
            else:
                # The end node, and the only kind left. Iterating an `AgentRun`
                # yields a user-prompt, a model-request or a call-tools node, or
                # `End` - `AgentRun._task_to_node` has no fourth answer, and the
                # graph's one other node is reachable only through
                # `agent_run.next()`, which this does not use. `End` also means
                # the graph run holds its `EndMarker`, so `agent_run.result` is
                # populated there. `is_end_node(node) and agent_run.result is not
                # None` was therefore a condition that could not be false, and
                # had it ever been it would have dropped the frame carrying the
                # answer without saying anything. Whatever made it false now
                # raises instead, and reaches the client as `error`.
                await self.emit("final_result", {"output": display_output(agent_run.result.output)})

    async def request(self, request_stream: Any) -> None:
        """Forward model-request events: text, reasoning, tool deltas, final-result start.

        `timeline` records exactly what was sent as `text_delta` and
        `thinking_delta`, and where each block sat, so a turn that never finishes
        can still be written down as what the person watching it actually saw -
        and a turn that does finish reloads in the order it was watched in.
        """
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                await self.emit(
                    "part_start", {"index": event.index, "part_type": type(event.part).__name__}
                )
                if isinstance(event.part, TextPart) and event.part.content:
                    self.timeline.add_text(event.part.content)
                    await self.emit(
                        "text_delta", {"index": event.index, "content": event.part.content}
                    )
                elif isinstance(event.part, ThinkingPart) and event.part.content:
                    self.timeline.add_thinking(event.part.content)
                    await self.emit(
                        "thinking_delta", {"index": event.index, "content": event.part.content}
                    )
            elif isinstance(event, PartDeltaEvent):
                delta = event.delta
                if isinstance(delta, TextPartDelta):
                    self.timeline.add_text(delta.content_delta)
                    await self.emit(
                        "text_delta", {"index": event.index, "content": delta.content_delta}
                    )
                elif isinstance(delta, ThinkingPartDelta):
                    # Only when there is something to show. A reasoning delta can
                    # carry a `signature_delta` alone - the provider's proof it
                    # produced the reasoning - and forwarding that would put
                    # base64 in the reasoning pane and in the stored trace.
                    if delta.content_delta:
                        self.timeline.add_thinking(delta.content_delta)
                        await self.emit(
                            "thinking_delta", {"index": event.index, "content": delta.content_delta}
                        )
                else:
                    # A tool-call delta, and the only kind left:
                    # `ModelResponsePartDelta` is text, thinking or tool-call, so
                    # an `isinstance` here was a third condition that could not be
                    # false.
                    await self.emit(
                        "tool_call_delta", {"index": event.index, "args_delta": delta.args_delta}
                    )
            elif isinstance(event, FinalResultEvent):
                await self.emit("final_result_start", {"tool_name": event.tool_name})

    async def tools(self, handle_stream: Any) -> None:
        """Forward tool-call and tool-result events, collecting both for persistence.

        The call is recorded on `timeline` when it is *requested*, which is where
        it sat in the turn. Recording it on its result instead would reorder any
        two calls that did not come back in the order they were made.
        """
        pending: dict[str, dict[str, Any]] = {}
        async for tool_event in handle_stream:
            if isinstance(tool_event, FunctionToolCallEvent):
                call = {
                    "tool_call_id": tool_event.part.tool_call_id,
                    "tool_name": tool_event.part.tool_name,
                    "args": tool_event.part.args_as_dict(raise_if_invalid=False),
                }
                self.tool_calls.append(call)
                self.timeline.add_tool(tool_event.part.tool_call_id)
                pending[tool_event.part.tool_call_id] = call
                await self.emit("tool_call", call)
            elif isinstance(tool_event, FunctionToolResultEvent):
                # `.part`, not `.result`. Pydantic AI 2 renamed the field when
                # `ToolResultEvent` became the shared base of the function and
                # output events; reading the old name raised `AttributeError`
                # inside the stream, which reached the user as
                # "❌ Error: 'FunctionToolResultEvent' object has no attribute
                # 'result'" on every tool call in web chat. A `RetryPromptPart`
                # arrives here too and also carries `content` - the retry message -
                # so a failed call is reported rather than swallowed.
                content = str(tool_event.part.content)
                call = pending.get(tool_event.tool_call_id)
                if call is not None:
                    call["result"] = content
                await self.emit(
                    "tool_result", {"tool_call_id": tool_event.tool_call_id, "content": content}
                )
