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
    ToolCallPartDelta,
)
from pydantic_ai.messages import (
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
)

from app.agents.capabilities.budget import BudgetExceeded
from app.core.exceptions import AppException, AuthorizationError
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_context
from app.services.agent import (
    build_message_history,
    persist_assistant_turn,
    persist_user_turn,
    send_event,
)
from app.services.agent_chat import (
    ChatAgentRunner,
    display_output,
    requested_agent_id,
    requested_environment_id,
    requested_model_profile_id,
)
from app.services.attachments import load_attached_files
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
            self.current_conversation_id, newly_created = await persist_user_turn(
                self.user,
                user_message,
                file_ids,
                requested_conversation_id=data.get("conversation_id"),
                current_conversation_id=self.current_conversation_id,
                organization_id=self.organization_id,
            )
        except AuthorizationError as e:
            await send_event(self.websocket, "error", {"message": e.message})
            return
        if newly_created and self.current_conversation_id:
            await send_event(
                self.websocket,
                "conversation_created",
                {"conversation_id": self.current_conversation_id},
            )

        await send_event(self.websocket, "user_prompt", {"content": user_message})

        try:
            model_history = build_message_history(self.conversation_history)
            # The files, not a prompt built from them. Where an attachment goes
            # depends on whether the agent has a workspace, and only `prepare`
            # knows that - so the routing happens one layer down.
            attachments = await self._attached_files(file_ids)

            collected_tool_calls: list[dict[str, Any]] = []
            collected_thinking: list[str] = []

            async def stream(agent_run: Any) -> None:
                await self._stream_agent_run(
                    agent_run, user_message, collected_tool_calls, collected_thinking
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
                    ask_user=self._ask_user,
                    stream=stream,
                    # The chat may run a published agent on another of the
                    # organization's models. Only the model changes; the run
                    # records which one, and the budget is the agent's.
                    model_profile_id=requested_model_profile_id(data),
                    environment_id=requested_environment_id(data),
                )
            output = turn.output
            model_label = turn.model_label
            agent_version_id = turn.agent_version_id

            # Update in-memory history only after a complete agent run
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": output})
            assistant_msg_id: str | None = None
            if self.current_conversation_id:
                assistant_msg_id = await persist_assistant_turn(
                    self.current_conversation_id,
                    output,
                    model_label,
                    collected_tool_calls,
                    organization_id=self.organization_id,
                    thinking="".join(collected_thinking) or None,
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                )

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

    async def _ask_user(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pause the run: ask the client questions and block until they answer.

        Emits an `ask_user` event with the whole batch, then awaits a future the
        frame dispatcher completes when the matching `ask_user_response` arrives.
        The client returns a list of answers parallel to the questions.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
        self._ask_user_future = fut
        try:
            await send_event(self.websocket, "ask_user", {"questions": questions})
            return await fut
        finally:
            self._ask_user_future = None

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
        collected_thinking: list[str],
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
                    await self._stream_request_events(request_stream, collected_thinking)
            elif Agent.is_call_tools_node(node):
                await send_event(self.websocket, "call_tools_start", {})
                async with node.stream(agent_run.ctx) as handle_stream:
                    await self._stream_tool_events(handle_stream, collected_tool_calls)
            elif Agent.is_end_node(node) and agent_run.result is not None:
                await send_event(
                    self.websocket,
                    "final_result",
                    {"output": display_output(agent_run.result.output)},
                )

    async def _stream_request_events(
        self, request_stream: Any, collected_thinking: list[str]
    ) -> None:
        """Forward model-request events (text/thinking/tool deltas + final-result start)."""
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                await send_event(
                    self.websocket,
                    "part_start",
                    {"index": event.index, "part_type": type(event.part).__name__},
                )
                if isinstance(event.part, TextPart) and event.part.content:
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": event.part.content},
                    )
                elif isinstance(event.part, ThinkingPart) and event.part.content:
                    if collected_thinking:
                        collected_thinking.append(" ")
                    collected_thinking.append(event.part.content)
                    await send_event(
                        self.websocket,
                        "thinking_delta",
                        {"index": event.index, "content": event.part.content},
                    )
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": event.delta.content_delta},
                    )
                elif isinstance(event.delta, ThinkingPartDelta):
                    if event.delta.content_delta:
                        collected_thinking.append(event.delta.content_delta)
                        await send_event(
                            self.websocket,
                            "thinking_delta",
                            {"index": event.index, "content": event.delta.content_delta},
                        )
                elif isinstance(event.delta, ToolCallPartDelta):
                    await send_event(
                        self.websocket,
                        "tool_call_delta",
                        {"index": event.index, "args_delta": event.delta.args_delta},
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
    ) -> None:
        """Forward tool-call/result events; collect tool calls (with results) for persistence."""
        pending: dict[str, dict[str, Any]] = {}
        async for tool_event in handle_stream:
            if isinstance(tool_event, FunctionToolCallEvent):
                tc = {
                    "tool_call_id": tool_event.part.tool_call_id,
                    "tool_name": tool_event.part.tool_name,
                    "args": tool_event.part.args_as_dict(raise_if_invalid=False),
                }
                collected_tool_calls.append(tc)
                pending[tool_event.part.tool_call_id] = tc
                await send_event(self.websocket, "tool_call", tc)
            elif isinstance(tool_event, FunctionToolResultEvent):
                tc = pending.get(tool_event.tool_call_id)
                if tc is not None:
                    tc["result"] = str(tool_event.result.content)
                await send_event(
                    self.websocket,
                    "tool_result",
                    {
                        "tool_call_id": tool_event.tool_call_id,
                        "content": str(tool_event.result.content),
                    },
                )
