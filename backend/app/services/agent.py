"""Shared agent service utilities.

Houses framework-agnostic helpers used by every WebSocket agent route:
  - `AgentConnectionManager` + `send_event` - WebSocket fan-out
  - `build_message_history` - convert dicts to provider-native messages
  - `persist_user_turn` / `persist_assistant_turn` - DB persistence
  - `normalize_tool_args` / `truncate_title` - small utilities

Framework-specific concerns (multimodal input, streaming events) stay in the route.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from app.api.deps import get_conversation_service
from app.core.exceptions import AuthorizationError
from app.db.session import get_db_context
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    ToolCallComplete,
    ToolCallCreate,
)
from app.services.usage_report import UsageReport

logger = logging.getLogger(__name__)


async def send_event(websocket: WebSocket, event_type: str, data: Any) -> bool:
    """Send a JSON event to a WebSocket client.

    Returns True if sent successfully, False if the connection is already closed.
    """
    try:
        await websocket.send_json({"type": event_type, "data": data})
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


class AgentConnectionManager:
    """WebSocket connection manager for AI agent."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and store a new WebSocket connection."""
        # Echo back the application subprotocol chosen during auth (if any)
        subprotocol = getattr(websocket.state, "accept_subprotocol", None)
        await websocket.accept(subprotocol=subprotocol)
        self.active_connections.append(websocket)
        logger.info(
            "Agent WebSocket connected. Total connections: %d", len(self.active_connections)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            "Agent WebSocket disconnected. Total connections: %d", len(self.active_connections)
        )

    async def send_event(self, websocket: WebSocket, event_type: str, data: Any) -> bool:
        """Forward to the module-level :func:`send_event`."""
        return await send_event(websocket, event_type, data)


def build_message_history(history: list[dict[str, str]]) -> list[ModelRequest | ModelResponse]:
    """Convert conversation history to PydanticAI message format."""
    model_history: list[ModelRequest | ModelResponse] = []

    for msg in history:
        if msg["role"] == "user":
            model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
        elif msg["role"] == "assistant":
            model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
        elif msg["role"] == "system":
            model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))

    return model_history


def truncate_title(text: str, limit: int = 50) -> str:
    """Return text truncated to `limit` characters."""
    return text[:limit] if len(text) > limit else text


@dataclass(frozen=True)
class PersistedPrompt:
    """What writing the user's turn produced, for the caller to act on.

    Attributes:
        conversation_id: The thread the turn was written to, resolved or created.
        newly_created: Whether the conversation was created by this call. The
            caller emits a `conversation_created` event when it was.
        message_id: The row the prompt was written to, so the caller can link it
            to the run once one is open. `None` when the write failed - which is
            logged and swallowed, because a lost message must not abort a turn.
    """

    conversation_id: str | None
    newly_created: bool
    message_id: UUID | None = None


async def persist_user_turn(
    user: Any,
    user_message: str,
    file_ids: list[Any],
    requested_conversation_id: str | None,
    current_conversation_id: str | None,
    organization_id: UUID,
) -> PersistedPrompt:
    """Resolve the conversation, persist the user message, and link any uploaded files.

    `organization_id` is the session's active organization; new conversations are
    created inside it, and resuming a conversation that belongs to a different org
    is refused. Ownership by user alone is not enough - a user can belong to several
    organizations, and a run must not read one org's knowledge while billed to another.

    The prompt is written before a run exists, and so carries no `run_id` yet: a
    build that refuses - a deleted secret, a model profile removed in a deploy -
    must not lose what somebody typed. `PersistedPrompt.message_id` is how the
    caller closes that gap once the run row is open.

    Raises:
        AuthorizationError: If the requested conversation belongs to another
            organization. Persistence failures are logged and swallowed - a lost
            message must not abort a turn - but a scope violation must.
    """
    newly_created = False
    message_id: UUID | None = None
    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)

            if requested_conversation_id:
                current_conversation_id = requested_conversation_id
                conv = await conv_service.get_conversation(
                    UUID(requested_conversation_id), user_id=user.id
                )
                if conv.organization_id != organization_id:
                    raise AuthorizationError(
                        message="Conversation belongs to a different organization",
                        details={"conversation_id": requested_conversation_id},
                    )
                if not conv.title and user_message:
                    await conv_service.update_conversation(
                        UUID(requested_conversation_id),
                        ConversationUpdate(title=truncate_title(user_message)),
                        user_id=user.id,
                    )
            elif not current_conversation_id:
                conversation = await conv_service.create_conversation(
                    ConversationCreate(
                        user_id=user.id,
                        organization_id=organization_id,
                        title=truncate_title(user_message),
                    )
                )
                current_conversation_id = str(conversation.id)
                newly_created = True

            user_msg = await conv_service.add_message(
                UUID(current_conversation_id),
                MessageCreate(role="user", content=user_message),
                organization_id=organization_id,
                user_id=user.id,
            )
            message_id = user_msg.id
            if file_ids:
                try:
                    await conv_service.link_files_to_message(user_msg.id, file_ids)
                except Exception as e:
                    logger.warning("Failed to link files: %s", e)
    except AuthorizationError:
        raise
    except Exception as e:
        logger.warning("Failed to persist conversation: %s", e)

    return PersistedPrompt(
        conversation_id=current_conversation_id,
        newly_created=newly_created,
        message_id=message_id,
    )


def normalize_tool_args(args: Any) -> dict[str, Any]:
    """Coerce a tool-call `args` payload to a dict (handles JSON strings + None)."""
    if isinstance(args, str):
        return json.loads(args) if args.strip() else {}
    if args is None:
        return {}
    return args


async def persist_assistant_turn(
    conversation_id: str,
    output: str,
    model_name: str | None,
    collected_tool_calls: list[dict[str, Any]],
    organization_id: UUID,
    thinking: str | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    usage: UsageReport | None = None,
    run_id: UUID | None = None,
) -> str | None:
    """Persist the assistant message and any tool calls. Returns the saved message id.

    `organization_id` is the session's active organization, and it is checked
    rather than trusted: `conversation_id` reaches here from the socket, where
    it started as a client-supplied value. `persist_user_turn` refuses one
    belonging to another organization, and this refuses to write into one.

    `agent_id` and `agent_version_id` are recorded per message rather than
    per conversation because the agent can be changed mid-thread, and because
    an agent is rewritten between turns: attributing the whole conversation to
    the last one selected - or to the spec it has today - would rewrite who
    said what, and with which instructions.

    `usage` is stored for the same reason it is streamed: the cost of an answer is
    asked about after the fact. A turn nobody could measure passes `None`, which
    reads back as "not recorded" rather than as free.

    `run_id` is what makes this turn readable from run history rather than only
    from the conversation. It is written here rather than linked afterwards
    because by this point the run row exists - unlike the prompt, which is
    persisted before the run is built. It is passed beside `data` rather than
    inside it: `MessageCreate` is bound from a request body elsewhere, and a run
    id a caller could set is one they could aim at another organization's run.
    """
    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)
            assistant_msg = await conv_service.add_message(
                UUID(conversation_id),
                organization_id=organization_id,
                run_id=run_id,
                data=MessageCreate(
                    role="assistant",
                    content=output,
                    thinking=thinking,
                    model_name=model_name,
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    # Stored, not only streamed. It used to live in the `complete`
                    # frame alone, so it existed for as long as the tab did and a
                    # reopened conversation showed no cost anywhere - which is
                    # exactly when "what did that answer cost" gets asked.
                    input_tokens=None if usage is None else usage.input_tokens,
                    output_tokens=None if usage is None else usage.output_tokens,
                    cost_usd=None if usage is None else usage.cost_usd,
                ),
            )
            for tc in collected_tool_calls:
                try:
                    tc_obj = await conv_service.start_tool_call(
                        assistant_msg.id,
                        ToolCallCreate(
                            tool_call_id=tc["tool_call_id"],
                            tool_name=tc["tool_name"],
                            args=normalize_tool_args(tc.get("args")),
                            started_at=datetime.now(UTC),
                        ),
                    )
                    if tc.get("result"):
                        await conv_service.complete_tool_call(
                            tc_obj.id,
                            ToolCallComplete(
                                result=tc["result"],
                                completed_at=datetime.now(UTC),
                                success=True,
                            ),
                        )
                except Exception as e:
                    logger.warning("Failed to persist tool call: %s", e)
            return str(assistant_msg.id)
    except Exception as e:
        logger.warning("Failed to persist assistant response: %s", e)
        return None
