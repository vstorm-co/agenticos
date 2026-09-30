"""`WorkflowRunSocket` - start or follow a workflow run over a WebSocket (#1792).

One socket follows one run at a time. A client sends a frame, and is sent the
run and then its events as they are written:

* `{"type": "start", "workflow_id", "input"}` starts a run of the live version
  as the connected member, the same admission a `POST /workflow-runs` makes.
  With a `conversation_id` of the member's own and a `message`, it is the
  chat's door instead, for a workflow that starts from a chat message: the
  message is written to that conversation, the run starts with the message,
  the conversation and the member, and its answer is written back there when
  it ends.
* `{"type": "attach", "run_id", "after"}` follows a run already going, from a
  cursor a previous event carried. A client that lost its connection
  reconnects with its last cursor and picks up exactly where it stopped:
  events are durable rows written before they are sent, so nothing is lost
  and nothing re-runs.

The server sends `{"type": "run", "run"}` when it starts following and again
when the run ends, `{"type": "event", "event", "cursor"}` for each event, and
`{"type": "error", "code", "message"}` for a frame it refused.

The socket's credential and the member's access are re-checked before every
frame is acted on and before every read of the stream, so a revoked session or
a withdrawn grant stops the stream at its next poll rather than when the
socket happens to close.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import AppException, AuthenticationError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext
from app.db.models.workflow_run import WorkflowRunTrigger
from app.db.session import get_db_context
from app.repositories import conversation as conversation_repo
from app.repositories import member_repo
from app.schemas.workflow_run import WorkflowRunRead
from app.services import rate_limit
from app.services.workflow_execution import WorkflowExecutionService, events
from app.services.ws_auth import authenticate_socket_token

logger = logging.getLogger(__name__)

# How long a socket waits before reading a quiet run's stream again.
POLL_SECONDS = 1.0
# The most events one read sends; a longer backlog is read again at once.
_PAGE = 100
_REVOKED_CLOSE_CODE = 4001
_TERMINAL = {"succeeded", "failed", "cancelled", "budget_exceeded"}


class _StartFrame(BaseModel):
    workflow_id: UUID
    input: dict[str, Any] = Field(default_factory=dict)
    conversation_id: UUID | None = None
    message: str | None = Field(default=None, min_length=1, max_length=20_000)


class _AttachFrame(BaseModel):
    run_id: UUID
    after: str | None = None


class WorkflowRunSocket:
    """One WebSocket following one workflow run."""

    def __init__(self, websocket: WebSocket, *, organization_id: UUID, auth_token: str) -> None:
        self.websocket = websocket
        self.organization_id = organization_id
        self._auth_token = auth_token
        self._stream: asyncio.Task[None] | None = None

    async def handle_frame(self, data: dict[str, Any]) -> None:
        """Start or attach, replacing whatever run the socket was following.

        Any other frame is dropped before the credential is read, so a stream
        of no-op frames costs no queries.
        """
        kind = data.get("type")
        if kind not in ("start", "attach"):
            return
        ctx = await self._context()
        if ctx is None:
            await self._close_revoked()
            return
        await self.stop()
        try:
            if kind == "start":
                run = await self._start(ctx, _StartFrame.model_validate(data))
                run_id, after = run.id, None
            else:
                frame = _AttachFrame.model_validate(data)
                run_id, after = frame.run_id, frame.after
        except PydanticValidationError:
            await self._send("error", code="BAD_FRAME", message="This frame is not valid")
            return
        except AppException as exc:
            await self._send("error", code=exc.code, message=exc.message)
            return
        self._stream = asyncio.create_task(self._follow(run_id, after))

    async def stop(self) -> None:
        """Stop following the current run, if any. The run itself goes on."""
        task = self._stream
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _start(self, ctx: AuthContext, frame: _StartFrame) -> WorkflowRunRead:
        # The allowance `POST /workflow-runs` spends, under the same key: a socket
        # is a second door to the same start, not a way around its limit.
        decision = await rate_limit.consume(
            surface="workflow_run", caller=f"user:{ctx.subject_id}", limit=rate_limit.run_limit()
        )
        if not decision.allowed:
            raise RateLimitError(
                message="Too many workflow runs in the last minute. Wait and try again.",
                details={"retry_after_seconds": decision.retry_after_seconds},
            )
        async with get_db_context() as db:
            runs = WorkflowExecutionService(db)
            if frame.conversation_id is None:
                return await runs.start(
                    ctx,
                    frame.workflow_id,
                    triggered_by=WorkflowRunTrigger.WEBSOCKET,
                    run_input=frame.input,
                )
            # The chat's door: the reply destination is the member's own
            # conversation, checked here and frozen on the run - never a field
            # a caller could point at someone else's thread.
            conversation = await conversation_repo.get_conversation_by_id(db, frame.conversation_id)
            if (
                conversation is None
                or conversation.organization_id != ctx.organization_id
                or conversation.user_id != ctx.user_id
                or frame.message is None
            ):
                raise NotFoundError(
                    message="Conversation not found",
                    details={"conversation_id": str(frame.conversation_id)},
                )
            await conversation_repo.create_message(
                db, conversation_id=conversation.id, role="user", content=frame.message
            )
            return await runs.start(
                ctx,
                frame.workflow_id,
                triggered_by=WorkflowRunTrigger.CHAT,
                run_input={
                    "prompt": frame.message,
                    "conversation_id": str(conversation.id),
                    "user_id": str(ctx.user_id),
                },
                reply_conversation_id=conversation.id,
            )

    async def _follow(self, run_id: UUID, after: str | None) -> None:
        """Send the run, then every event after `after`, until the run has ended."""
        cursor = after
        announced = False
        while True:
            ctx = await self._context()
            if ctx is None:
                await self._close_revoked()
                return
            try:
                async with get_db_context() as db:
                    runs = WorkflowExecutionService(db)
                    # The run before its events: a run read as ended has written
                    # its last event already, so the read below includes it.
                    run = await runs.get(ctx, run_id)
                    page = await runs.events_since(ctx, run_id, after=cursor, limit=_PAGE)
            except AppException as exc:
                await self._send("error", code=exc.code, message=exc.message)
                return
            if not announced:
                await self._send("run", run=run.model_dump(mode="json"))
                announced = True
            for event in page.items:
                await self._send(
                    "event",
                    event=event.model_dump(mode="json"),
                    cursor=events.encode_cursor(event.seq),
                )
            cursor = page.next_cursor
            if run.status.value in _TERMINAL and len(page.items) < _PAGE:
                await self._send("run", run=run.model_dump(mode="json"))
                return
            if len(page.items) < _PAGE:
                await asyncio.sleep(POLL_SECONDS)

    async def _context(self) -> AuthContext | None:
        """The member's authority now, or None if the session or membership has gone.

        `allow_expired=True` for the reason `AgentSession._reauthorize` gives: the
        socket outlives its access token by design, so an aged-out token is not
        a revocation - a revoked session or a suspended account is.
        """
        async with get_db_context() as db:
            try:
                user = await authenticate_socket_token(db, self._auth_token, allow_expired=True)
            except AuthenticationError:
                return None
            membership = await member_repo.get_active(
                db, organization_id=self.organization_id, user_id=user.id
            )
            if membership is None:
                return None
            return AuthContext(
                user_id=user.id, organization_id=self.organization_id, role=membership.role
            )

    async def _send(self, kind: str, **body: Any) -> None:
        # A socket that went away mid-send has nobody to tell; the receive loop
        # sees the disconnect and stops the stream.
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.websocket.send_json({"type": kind, **body})

    async def _close_revoked(self) -> None:
        with contextlib.suppress(RuntimeError):
            await self.websocket.close(code=_REVOKED_CLOSE_CODE, reason="Session revoked")


__all__ = ["WorkflowRunSocket"]
