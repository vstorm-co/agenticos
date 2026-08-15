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
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_conversation_service
from app.core.exceptions import AppException, AuthorizationError, BadRequestError, NotFoundError
from app.db.models.conversation import Conversation
from app.db.session import get_db_context
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessagePart,
    ToolCallComplete,
    ToolCallCreate,
)
from app.services.conversation import ConversationService
from app.services.transcript import what_arrived
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
        content = msg["content"]
        # An empty text part is not history, it is a 400: Anthropic rejects one,
        # and a row with no text carries nothing to the model regardless. A
        # caption-less file is recorded as an empty user turn so the file has a
        # row to hang off (transcript.py), but the file's bytes are not in the
        # history this reconstructs - so the empty row is pure liability here.
        if not content.strip():
            continue
        if msg["role"] == "user":
            model_history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif msg["role"] == "assistant":
            model_history.append(ModelResponse(parts=[TextPart(content=content)]))
        elif msg["role"] == "system":
            model_history.append(ModelRequest(parts=[SystemPromptPart(content=content)]))

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
            to the run once one is open. `None` when the database was briefly
            unavailable - the one failure that is logged and carried on from,
            because a lost message must not abort a turn. A refusal is raised
            instead, and there is no third case: this is never `None` because
            something was rejected.
    """

    conversation_id: str | None
    newly_created: bool
    message_id: UUID | None = None


def _conversation_uuid(conversation_id: str) -> UUID:
    """Parse a client-supplied conversation id, refusing rather than crashing.

    The value arrives over the socket, so a malformed one is input and not a
    defect. It used to raise `ValueError` into a bare `except Exception` and
    disappear with the message it carried.
    """
    try:
        return UUID(conversation_id)
    except ValueError as exc:
        raise BadRequestError(
            message="Not a conversation id",
            details={"conversation_id": conversation_id},
        ) from exc


async def _resolve_in_org(
    conv_service: ConversationService,
    conversation_id: UUID,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> Conversation:
    """The conversation, if it is this organization's and this reader's.

    The service reports another tenant's row as missing so ids stay unprobeable,
    which is right for an HTTP route and wrong to swallow here: from a socket,
    "gone" and "not yours" are the same refusal and both must stop the turn
    before anything is written. So one refusal, naming neither.
    """
    try:
        return await conv_service.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    except NotFoundError as exc:
        raise AuthorizationError(
            message="Conversation not found in this organization",
            details={"conversation_id": str(conversation_id)},
        ) from exc


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

    A blank `user_message` beside `file_ids` is written naming what arrived -
    the body :func:`what_arrived` composes, the same one `TranscriptService.record`
    writes for every non-streaming surface. The dashboard's composer substitutes
    its own placeholder before sending, so only a raw client reaches this - and
    used to leave the one blank user turn left in the product (#750). A typed
    message is never replaced.

    Raises:
        BadRequestError: If `requested_conversation_id` is not a UUID, or a
            file in `file_ids` is not one, or is already attached to a message.
        NotFoundError: If a file in `file_ids` is not the caller's own -
            another user's id answers like one that does not exist (#706).
        AuthorizationError: If the requested conversation is not this
            organization's. A database failure is logged and swallowed - a lost
            message must not abort a turn - but a refusal must abort, and a
            defect in this module must surface rather than read as one.
    """
    newly_created = False
    message_id: UUID | None = None
    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)

            if requested_conversation_id:
                current_conversation_id = requested_conversation_id
                requested = _conversation_uuid(requested_conversation_id)
                # The tenant is what makes the rest of this function safe, and
                # it used to be omitted: `get_conversation` takes it keyword-only
                # and required, so every resumed turn raised `TypeError` into the
                # `except` below and was logged as a persistence failure. The
                # guard that followed never ran, and neither did the write - so
                # every message after the first was silently dropped (#5).
                conv = await _resolve_in_org(
                    conv_service, requested, organization_id=organization_id, user_id=user.id
                )
                if not conv.title and user_message:
                    await conv_service.update_conversation(
                        requested,
                        ConversationUpdate(title=truncate_title(user_message)),
                        organization_id=organization_id,
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

            content = user_message
            if not content and file_ids:
                content = what_arrived(
                    await conv_service.list_attached_files(file_ids, user_id=user.id)
                )
            user_msg = await conv_service.add_message(
                UUID(current_conversation_id),
                MessageCreate(role="user", content=content),
                organization_id=organization_id,
                user_id=user.id,
            )
            message_id = user_msg.id
            if file_ids:
                try:
                    await conv_service.link_files_to_message(user_msg.id, file_ids, user_id=user.id)
                except AppException:
                    # A refusal - an id that is not the caller's own unlinked
                    # upload - must abort the turn, not read as a transient
                    # persistence failure (#706).
                    raise
                except Exception as e:
                    logger.warning("Failed to link files: %s", e)
    except AppException:
        # A refusal - another organization's conversation, an archived one, an
        # id that is not a UUID. The caller turns it into an error frame; it is
        # not something to log and carry on from.
        raise
    except SQLAlchemyError as e:
        # The only thing swallowed here, and the only thing the promise above
        # was ever about: the database was briefly unavailable. Everything else
        # - a signature that no longer binds, an attribute that moved - is a
        # defect in this module, and #5 is what swallowing one costs: it read
        # as a transient persistence failure for as long as it took to lose
        # every resumed turn in the deployment.
        logger.warning("Failed to persist the user's turn: %s", e)

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
    parts: list[MessagePart] | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    usage: UsageReport | None = None,
    run_id: UUID | None = None,
    parked_tool_call_ids: Collection[str] = (),
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

    `parts` is the order the turn happened in, which `content` and `thinking`
    cannot carry between them: a turn that writes, calls three tools and then
    summarises has two blocks of text and one column to put them in. Storing the
    sequence that was streamed is what makes a reloaded conversation the one
    somebody watched rather than a client's reconstruction of it. None means "no
    order recorded" - a single-part turn, or a caller that predates this - and is
    the signal to fall back to reconstructing one.

    `run_id` is what makes this turn readable from run history rather than only
    from the conversation. It is written here rather than linked afterwards
    because by this point the run row exists - unlike the prompt, which is
    persisted before the run is built. It is passed beside `data` rather than
    inside it: `MessageCreate` is bound from a request body elsewhere, and a run
    id a caller could set is one they could aim at another organization's run.

    `parked_tool_call_ids` names the calls the turn stopped on, so their rows are
    stored `awaiting_approval` rather than `running` - the parked state otherwise
    lives only on `agent_runs` and the `approvals` rows, and a reloaded
    conversation read the one call somebody has to decide about as a step that
    ran (#601). The resume settles the row through the transcript service, and an
    expiry settles it with the timeout notice.
    """
    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)
            spent_in, spent_out, spent_usd = (
                (0, 0, Decimal(0))
                if run_id is None
                else await conversation_repo.attributed_to_run(db, run_id)
            )
            assistant_msg = await conv_service.add_message(
                UUID(conversation_id),
                organization_id=organization_id,
                run_id=run_id,
                data=MessageCreate(
                    role="assistant",
                    content=output,
                    thinking=thinking,
                    parts=parts,
                    model_name=model_name,
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    # Stored, not only streamed. It used to live in the `complete`
                    # frame alone, so it existed for as long as the tab did and a
                    # reopened conversation showed no cost anywhere - which is
                    # exactly when "what did that answer cost" gets asked.
                    # The *difference* from what this run's earlier turns already
                    # claim, not the run row's figure: a run that parked and was
                    # resumed writes two assistant turns - this one and the
                    # continuation the transcript service writes - and the row is
                    # cumulative, so stamping both with it counts the parked half
                    # twice. Nothing is attributed yet on an ordinary turn, where
                    # the difference is the whole of it.
                    input_tokens=None if usage is None else usage.input_tokens - spent_in,
                    output_tokens=None if usage is None else usage.output_tokens - spent_out,
                    cost_usd=None if usage is None else usage.cost_usd - spent_usd,
                    # Beside the total, because without it the total lies: a turn
                    # that reached an unpriced model is booked at zero for that
                    # request, and rendered identically to one measured exactly
                    # (#772).
                    cost_is_partial=None if usage is None else usage.cost_is_partial,
                    # Only the token count. The window it is a share of belongs to
                    # whichever model answers next, and the chat lets somebody
                    # switch that between turns - a share stored against a model
                    # they have since left is wrong in the one direction that
                    # costs a run (#774).
                    context_used_tokens=(
                        None
                        if usage is None or usage.context is None
                        else usage.context.used_tokens
                    ),
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
                        parked=tc["tool_call_id"] in parked_tool_call_ids,
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
    except Exception:
        # Broad on purpose, unlike its sibling above: by this point the answer
        # has been streamed and raising cannot un-stream it, so the caller is
        # told with `None` and the turn completes. `exception` rather than
        # `warning` because that is the whole of the record - #5 sat behind a
        # one-line warning here and in `persist_user_turn` for as long as it
        # took somebody to bind the signature by hand.
        logger.exception("Failed to persist the assistant's turn")
        return None
