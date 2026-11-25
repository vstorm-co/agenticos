"""Personal chat queue receipts and explicit Run as task transfer."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Auth, DBSession
from app.schemas.accepted_queued_message import (
    AcceptedQueuedMessageCreate,
    AcceptedQueuedMessageList,
    AcceptedQueuedMessageRead,
)
from app.schemas.conversation_task import ConversationTaskRead
from app.services.accepted_queued_message import AcceptedQueuedMessageService

router = APIRouter()


@router.post(
    "/{conversation_id}/queued-messages",
    response_model=AcceptedQueuedMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def accept_queued_message(
    conversation_id: UUID,
    body: AcceptedQueuedMessageCreate,
    db: DBSession,
    ctx: Auth,
) -> Any:
    """Durably accept one exact local queue item before its current turn ends."""
    return await AcceptedQueuedMessageService(db).accept(ctx, conversation_id, body)


@router.get(
    "/{conversation_id}/queued-messages",
    response_model=AcceptedQueuedMessageList,
)
async def list_queued_messages(
    conversation_id: UUID,
    db: DBSession,
    ctx: Auth,
    cursor: UUID | None = Query(default=None),
) -> Any:
    """Recover the owner's unresolved outbox items in bounded pages."""
    return await AcceptedQueuedMessageService(db).list_pending(ctx, conversation_id, cursor)


@router.get(
    "/{conversation_id}/queued-messages/{receipt_id}",
    response_model=AcceptedQueuedMessageRead,
)
async def get_queued_message(
    conversation_id: UUID,
    receipt_id: UUID,
    db: DBSession,
    ctx: Auth,
) -> Any:
    """Read one owned receipt to reconcile a transfer/send race or lost response."""
    return await AcceptedQueuedMessageService(db).get_for_owner(ctx, conversation_id, receipt_id)


@router.delete(
    "/{conversation_id}/queued-messages/{receipt_id}",
    response_model=AcceptedQueuedMessageRead,
)
async def cancel_queued_message(
    conversation_id: UUID,
    receipt_id: UUID,
    db: DBSession,
    ctx: Auth,
) -> Any:
    """Cancel a still-pending queue item and release only its reserved uploads."""
    return await AcceptedQueuedMessageService(db).cancel(ctx, conversation_id, receipt_id)


@router.post(
    "/{conversation_id}/queued-messages/{receipt_id}/run-as-task",
    response_model=ConversationTaskRead,
)
async def run_queued_message_as_task(
    conversation_id: UUID,
    receipt_id: UUID,
    db: DBSession,
    ctx: Auth,
) -> Any:
    """Transfer a queue receipt into one server-created private task topic."""
    return await AcceptedQueuedMessageService(db).run_as_task(ctx, conversation_id, receipt_id)
