# Thin session wrapper - the route is lifecycle plumbing only; orchestration lives here.
import asyncio
import contextlib
import logging
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.messages import (
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
)

from app.agents.ask_user import QuestionItem, render_answer
from app.agents.capabilities.budget import BudgetExceeded
from app.agents.subagent_events import SubagentEvent
from app.core.exceptions import AppException
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_context
from app.schemas.conversation import MessagePart
from app.services.agent import (
    build_message_history,
    persist_assistant_turn,
    persist_user_turn,
    send_event,
)
from app.services.agent_chat import (
    ChatAgentRunner,
    OpenedRun,
    display_output,
    requested_agent_id,
    requested_environment_id,
    requested_model_profile_id,
)
from app.services.attachments import load_attached_files
from app.services.chat_timeline import TurnTimeline
from app.services.usage_report import usage_frame

logger = logging.getLogger(__name__)

# Said to a frame that names no agent. There is nothing else a frame could run:
# the general assistant the template shipped is gone, and guessing an agent on
# the user's behalf would mean something they never picked answering them.
_PICK_AN_AGENT = "Pick an agent to chat with. If none is listed, publish one in the Builder first."


class AgentSession:
    """One WebSocket session with the AI agent."""

    def __init__(
        self,
        websocket: WebSocket,
        user: User,
        organization: Organization,
    ) -> None:
        self.websocket = websocket
        self.user = user
        self.organization_id = organization.id
        self.conversation_history: list[dict[str, str]] = []
        self.current_conversation_id: str | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._ask_user_future: asyncio.Future[list[dict[str, Any]]] | None = None
        # One question round on the wire at a time. The client renders a single
        # `ask_user` form and its `ask_user_response` carries no correlation, and
        # `_ask_user_future` is one slot - so two delegates asking at once (a
        # fan-out of sync delegates, each reaching `ask_parent`) would otherwise
        # have the second overwrite the first's future and strand it. The lock
        # holds each round until its answer arrives, so questions queue rather
        # than collide.
        self._ask_lock = asyncio.Lock()

    async def handle_frame(self, data: dict[str, Any]) -> None:
        """Dispatch one incoming WebSocket frame.

        A `stop` cancels the running turn; an `ask_user_response` unblocks a
        paused run; any other control frame is ignored; a bare message starts a
        new turn as a cancellable background task.
        """
        msg_type = data.get("type")

        if msg_type == "stop":
            await self._cancel_turn()
            return

        if msg_type == "ask_user_response":
            fut = self._ask_user_future
            if fut is not None and not fut.done():
                answers = data.get("answers")
                fut.set_result(answers if isinstance(answers, list) else [])
            return

        if msg_type is not None:
            return

        if self._turn_task is not None and not self._turn_task.done():
            logger.warning("Ignoring message received while a turn is already in progress")
            return
        task = asyncio.create_task(self._run_turn(data))
        self._turn_task = task
        task.add_done_callback(self._on_turn_done)

    def _on_turn_done(self, task: asyncio.Task[None]) -> None:
        """Clear the turn slot and surface unexpected crashes."""
        if self._turn_task is task:
            self._turn_task = None
        if not task.cancelled():
            exc = task.exception()
            if isinstance(exc, WebSocketDisconnect):
                logger.info("Client disconnected during agent turn")
            elif exc is not None:
                logger.error("Agent turn task crashed", exc_info=exc)

    async def _run_turn(self, data: dict[str, Any]) -> None:
        """Run one turn, emitting a terminal `complete` even when stopped."""
        try:
            await self.process_message(data)
        except asyncio.CancelledError:
            await send_event(
                self.websocket,
                "complete",
                {
                    "conversation_id": self.current_conversation_id,
                    "stopped": True,
                },
            )
            raise

    async def _cancel_turn(self) -> None:
        """Cancel the in-flight turn task and wait for it to unwind."""
        task = self._turn_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def shutdown(self) -> None:
        """Cancel any in-flight turn."""
        await self._cancel_turn()

    async def process_message(self, data: dict[str, Any]) -> None:
        """Process one user turn: persist input, run the agent, stream events, persist output."""
        user_message = data.get("message", "")
        file_ids = data.get("file_ids", [])

        if not user_message and not file_ids:
            await send_event(self.websocket, "error", {"message": "Empty message"})
            return
        # Refused before the user turn is persisted: a message nothing will
        # answer does not belong in the transcript.
        try:
            agent_id = requested_agent_id(data)
        except AppException as exc:
            await send_event(self.websocket, "error", {"message": exc.message})
            return
        if agent_id is None:
            await send_event(self.websocket, "error", {"message": _PICK_AN_AGENT})
            return
        try:
            prompt = await persist_user_turn(
                self.user,
                user_message,
                file_ids,
                requested_conversation_id=data.get("conversation_id"),
                current_conversation_id=self.current_conversation_id,
                organization_id=self.organization_id,
            )
        except AppException as e:
            # Every refusal the write can raise, not only the cross-org one:
            # an archived conversation and an id that is not a UUID reach here
            # too, and both used to be logged inside `persist_user_turn` and
            # answered as though the turn had been recorded.
            await send_event(self.websocket, "error", {"message": e.message})
            return
        self.current_conversation_id = prompt.conversation_id
        if prompt.newly_created and self.current_conversation_id:
            await send_event(
                self.websocket,
                "conversation_created",
                {"conversation_id": self.current_conversation_id},
            )

        await send_event(self.websocket, "user_prompt", {"content": user_message})

        collected_tool_calls: list[dict[str, Any]] = []
        # Everything the model produces, in the order it produces it - the text,
        # the reasoning and where the tool calls sat between them. It is what gets
        # stored, so a reloaded conversation is the one somebody watched rather
        # than a reconstruction of it; see `chat_timeline.TurnTimeline`.
        #
        # It also holds what the model has said so far, for every turn that does
        # not end with an answer: one that failed, was stopped or lost its socket,
        # and one that parked on an approval. `turn.output` is the answer where
        # there is one and empty where there is not; nothing can tell in advance
        # which path a turn is on, and the alternative is throwing away a
        # half-written answer on exactly the runs somebody opens afterwards.
        timeline = TurnTimeline()
        # The run row, as soon as `prepare` opens one. A list because the
        # callback is `list.append` and a turn opens at most one run - it is
        # empty when the run was refused before it existed.
        opened: list[OpenedRun] = []
        # Whether the assistant turn reached the database. Read by the `finally`,
        # which exists for the paths where `turn` was never assigned and so
        # cannot be consulted.
        answered = False

        # Declared above the `try` because the `finally` reads all five, and a
        # failure inside it - the history, the attachment lookup - must not turn
        # a lost answer into a `NameError`.
        try:
            model_history = build_message_history(self.conversation_history)
            # The files, not a prompt built from them. Where an attachment goes
            # depends on whether the agent has a workspace, and only `prepare`
            # knows that - so the routing happens one layer down.
            attachments = await self._attached_files(file_ids)

            async def stream(agent_run: Any) -> None:
                await self._stream_agent_run(
                    agent_run,
                    user_message,
                    collected_tool_calls,
                    timeline,
                )

            # One session for the whole turn: the run row, the approvals it
            # parks and the cost it books are a single unit of work, and
            # `finish` writes back to the row `prepare` opened.
            async with get_db_context() as db:
                turn = await ChatAgentRunner(db).run(
                    user=self.user,
                    organization_id=self.organization_id,
                    agent_id=agent_id,
                    user_input=user_message,
                    message_history=model_history,
                    attachments=attachments,
                    conversation_id=(
                        UUID(self.current_conversation_id) if self.current_conversation_id else None
                    ),
                    prompt_message_id=prompt.message_id,
                    ask_user=self._ask_one,
                    stream=stream,
                    on_run_open=opened.append,
                    subagent_events=self._subagent_event,
                    # The chat may run a published agent on another of the
                    # organization's models. Only the model changes; the run
                    # records which one, and the budget is the agent's.
                    model_profile_id=requested_model_profile_id(data),
                    environment_id=requested_environment_id(data),
                )
            # `turn.output` is what the run *ended* with; a turn that parked ended
            # with nothing, so its words are on the timeline (#509).
            output = turn.output or timeline.text
            model_label = turn.model_label
            agent_version_id = turn.agent_version_id

            self.conversation_history.append({"role": "user", "content": user_message})
            # Only when there was something to say - tidiness, not a broken
            # request being fixed. Skipping the assistant entry can leave two
            # `user` entries in a row (park with no text, decide, type again),
            # and `_agent_graph._clean_message_history` merges those into one
            # `ModelRequest` before every model call; the empty `TextPart` this
            # avoids was harmless too, dropped by the Anthropic adapter and sent
            # as `content: ""` by the OpenAI one.
            if output:
                self.conversation_history.append({"role": "assistant", "content": output})
            assistant_msg_id: str | None = None
            if self.current_conversation_id:
                assistant_msg_id = await persist_assistant_turn(
                    self.current_conversation_id,
                    output,
                    model_label,
                    collected_tool_calls,
                    organization_id=self.organization_id,
                    thinking=timeline.thinking,
                    parts=timeline.stored(),
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    usage=turn.usage,
                    run_id=turn.run_id,
                )
                # Written, so the `finally` below has nothing left to save. It
                # cannot read `turn` to work that out - the whole point of it is
                # the paths where `turn` was never assigned.
                answered = True

            if assistant_msg_id:
                await send_event(
                    self.websocket,
                    "message_saved",
                    {
                        "message_id": assistant_msg_id,
                        "conversation_id": self.current_conversation_id,
                    },
                )

            # Before `complete`, so a client that draws the panel has it while the
            # turn is still on screen. The queue and the email carry the same rows;
            # this is a shortcut for whoever is already looking at the tab.
            if turn.parked:
                await send_event(
                    self.websocket,
                    "tool_approval_required",
                    {
                        "run_id": str(turn.run_id),
                        "action_requests": [
                            {
                                "id": str(parked.approval_id),
                                "tool_call_id": parked.tool_call_id,
                                "tool_name": parked.tool_name,
                                "args": parked.tool_args,
                            }
                            for parked in turn.parked
                        ],
                        # Editing a parked call is not offered: the arguments were
                        # already recorded on the row the approver is deciding
                        # about, and letting the chat rewrite them would mean
                        # approving something other than what was asked.
                        "review_configs": [
                            {"tool_name": parked.tool_name, "allow_edit": False}
                            for parked in turn.parked
                        ],
                    },
                )

            await send_event(
                self.websocket,
                "complete",
                {
                    "conversation_id": self.current_conversation_id,
                    # What the turn cost, on the frame that says it is over.
                    # Its own event would be one the client could receive after
                    # `complete` and draw against the next turn.
                    "usage": usage_frame(turn.usage),
                },
            )
        except WebSocketDisconnect:
            raise
        except (AppException, BudgetExceeded) as exc:
            # A refusal - an agent that is unpublished, archived, or not theirs
            # to see - and a budget stop are the platform working, not a crash.
            # The client is told plainly; nothing answers in the named agent's
            # place.
            logger.info("Agent turn refused: %s", exc)
            await send_event(self.websocket, "error", {"message": str(exc)})
        except Exception as e:
            logger.exception("Error processing agent request")
            await send_event(self.websocket, "error", {"message": str(e)})
        finally:
            if not answered:
                await self._persist_partial_turn(
                    opened,
                    agent_id=agent_id,
                    output=timeline.text,
                    tool_calls=collected_tool_calls,
                    thinking=timeline.thinking,
                    parts=timeline.stored(),
                )

    async def _persist_partial_turn(
        self,
        opened: list[OpenedRun],
        *,
        agent_id: UUID,
        output: str,
        tool_calls: list[dict[str, Any]],
        thinking: str | None,
        parts: list[MessagePart] | None,
    ) -> None:
        """Keep what the agent produced on a turn that did not finish.

        A run that failed, hit its budget, was stopped or lost its socket never
        returns a `ChatTurn`, so the write on the success path is skipped and
        everything the model had already streamed was discarded - leaving the run
        in history pointing at a transcript with the question and nothing else.
        That is the run somebody opens.

        Written from the collectors rather than from a result, because there is no
        result: this is the text that reached the client. `usage` is deliberately
        absent - the accounting is on the run row, written by `finish`, and a
        partial figure invented here would disagree with it.

        Nothing is written when nothing was produced. A turn refused before its
        run existed - an unpublished agent, a membership revoked mid-session - has
        an empty `opened` and no output, and a blank assistant message would read
        as the agent having answered with silence.
        """
        if not opened or not (output or tool_calls):
            return
        run = opened[0]
        if self.current_conversation_id is None:
            return
        await persist_assistant_turn(
            self.current_conversation_id,
            output,
            run.model_label,
            tool_calls,
            organization_id=self.organization_id,
            thinking=thinking,
            parts=parts,
            agent_id=agent_id,
            agent_version_id=run.agent_version_id,
            run_id=run.run_id,
        )

    async def _ask_one(self, question: str, options: list[str]) -> str:
        """Put one question to the client and return the answer as a string.

        The shape `AgentDeps.ask_user` promises, and what a delegate's `ask_parent`
        calls. It adapts the one-question protocol to this surface's batch channel -
        a list of one - so the WebSocket keeps a single wire format for one question
        and several, and the delegate reads back the rendered answer.
        """
        item = QuestionItem(question=question, options=options)
        answers = await self._ask_user([item.model_dump()])
        return render_answer(answers[0] if answers else None)

    async def _ask_user(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pause the run: ask the client questions and block until they answer.

        Emits an `ask_user` event with the whole batch, then awaits a future the
        frame dispatcher completes when the matching `ask_user_response` arrives.
        The client returns a list of answers parallel to the questions.

        Held under `_ask_lock` so a second round - another delegate's question -
        waits for this one's answer rather than overwriting its future.
        """
        async with self._ask_lock:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
            self._ask_user_future = fut
            try:
                await send_event(self.websocket, "ask_user", {"questions": questions})
                return await fut
            finally:
                self._ask_user_future = None

    async def _subagent_event(self, event: SubagentEvent) -> None:
        """Forward one frame from inside a delegation, under the frame's own name.

        The wire `type` *is* the frame's `kind` rather than a name chosen here.
        Two spellings of one frame - the literal in the union and a string in this
        method - is a drift nothing would catch: the client would keep switching on
        a case the server had stopped sending, and a delegation would simply not
        appear. `kind` stays in the payload as well, so the client narrows the
        object it already parsed instead of re-deriving the discriminator from the
        envelope.

        `cost_usd` is sent as a JSON number. Pydantic serialises a `Decimal` as a
        string in JSON mode, and this wire already reports a turn's cost as a
        number (see `usage_report.usage_frame`) - a delegation's share of that cost
        is the same quantity and must not arrive in a different shape.

        Nothing is awaited on the client's behalf: `send_event` answers `False` on
        a closed socket rather than raising, so a background delegation whose
        frames outlive the tab does not take the run down with it.
        """
        frame = event.model_dump(mode="json")
        cost = frame.get("cost_usd")
        if cost is not None:
            frame["cost_usd"] = float(cost)
        await send_event(self.websocket, event.kind, frame)

    async def _attached_files(self, file_ids: list[Any]) -> list[ChatFile]:
        """The rows for the files this frame attached.

        Read on their own session: the turn's own session is opened later and
        held for the run, and this is a lookup rather than part of that unit of
        work.
        """
        if not file_ids:
            return []
        async with get_db_context() as file_db:
            return await load_attached_files(file_db, file_ids)

    async def _stream_agent_run(
        self,
        agent_run: Any,
        user_message: str,
        collected_tool_calls: list[dict[str, Any]],
        timeline: TurnTimeline,
    ) -> None:
        """Drive the agent_run iterator, dispatching each node to its streaming helper."""
        async for node in agent_run:
            if Agent.is_user_prompt_node(node):
                prompt_text = (
                    node.user_prompt if isinstance(node.user_prompt, str) else user_message
                )
                await send_event(self.websocket, "user_prompt_processed", {"prompt": prompt_text})
            elif Agent.is_model_request_node(node):
                await send_event(self.websocket, "model_request_start", {})
                async with node.stream(agent_run.ctx) as request_stream:
                    await self._stream_request_events(request_stream, timeline)
            elif Agent.is_call_tools_node(node):
                await send_event(self.websocket, "call_tools_start", {})
                async with node.stream(agent_run.ctx) as handle_stream:
                    await self._stream_tool_events(handle_stream, collected_tool_calls, timeline)
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
                await send_event(
                    self.websocket,
                    "final_result",
                    {"output": display_output(agent_run.result.output)},
                )

    async def _stream_request_events(self, request_stream: Any, timeline: TurnTimeline) -> None:
        """Forward model-request events (text/thinking/tool deltas + final-result start).

        `timeline` records exactly what was sent as `text_delta` and
        `thinking_delta`, and where each block sat, so a turn that never finishes
        can still be written down as what the person watching it actually saw -
        and a turn that does finish reloads in the order it was watched in.
        """
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                await send_event(
                    self.websocket,
                    "part_start",
                    {"index": event.index, "part_type": type(event.part).__name__},
                )
                if isinstance(event.part, TextPart) and event.part.content:
                    timeline.add_text(event.part.content)
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": event.part.content},
                    )
                elif isinstance(event.part, ThinkingPart) and event.part.content:
                    timeline.add_thinking(event.part.content)
                    await send_event(
                        self.websocket,
                        "thinking_delta",
                        {"index": event.index, "content": event.part.content},
                    )
            elif isinstance(event, PartDeltaEvent):
                delta = event.delta
                if isinstance(delta, TextPartDelta):
                    timeline.add_text(delta.content_delta)
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": delta.content_delta},
                    )
                elif isinstance(delta, ThinkingPartDelta):
                    # Only when there is something to show. A reasoning delta can
                    # carry a `signature_delta` alone - the provider's proof it
                    # produced the reasoning - and forwarding that would put
                    # base64 in the reasoning pane and in the stored trace.
                    if delta.content_delta:
                        timeline.add_thinking(delta.content_delta)
                        await send_event(
                            self.websocket,
                            "thinking_delta",
                            {"index": event.index, "content": delta.content_delta},
                        )
                else:
                    # A tool-call delta, and the only kind left:
                    # `ModelResponsePartDelta` is text, thinking or tool-call, so
                    # an `isinstance` here was a third condition that could not be
                    # false.
                    await send_event(
                        self.websocket,
                        "tool_call_delta",
                        {"index": event.index, "args_delta": delta.args_delta},
                    )
            elif isinstance(event, FinalResultEvent):
                await send_event(
                    self.websocket,
                    "final_result_start",
                    {"tool_name": event.tool_name},
                )

    async def _stream_tool_events(
        self,
        handle_stream: Any,
        collected_tool_calls: list[dict[str, Any]],
        timeline: TurnTimeline,
    ) -> None:
        """Forward tool-call/result events; collect tool calls (with results) for persistence.

        The call is recorded on `timeline` when it is *requested*, which is where it
        sat in the turn. Recording it on its result instead would reorder any two
        calls that did not come back in the order they were made.
        """
        pending: dict[str, dict[str, Any]] = {}
        async for tool_event in handle_stream:
            if isinstance(tool_event, FunctionToolCallEvent):
                tc = {
                    "tool_call_id": tool_event.part.tool_call_id,
                    "tool_name": tool_event.part.tool_name,
                    "args": tool_event.part.args_as_dict(raise_if_invalid=False),
                }
                collected_tool_calls.append(tc)
                timeline.add_tool(tool_event.part.tool_call_id)
                pending[tool_event.part.tool_call_id] = tc
                await send_event(self.websocket, "tool_call", tc)
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
                tc = pending.get(tool_event.tool_call_id)
                if tc is not None:
                    tc["result"] = content
                await send_event(
                    self.websocket,
                    "tool_result",
                    {"tool_call_id": tool_event.tool_call_id, "content": content},
                )
