"""Secret requests: the rows a parked run's `request_secret` calls leave behind."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.secret_request import SecretRequest, SecretRequestStatus


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    agent_id: UUID,
    tool_call_id: str,
    secret_name: str,
    kind: str,
    what_for: str,
    requested_by_user_id: UUID | None,
) -> SecretRequest:
    """Record one ask for a secret. The value is never a column here."""
    request = SecretRequest(
        organization_id=organization_id,
        run_id=run_id,
        agent_id=agent_id,
        tool_call_id=tool_call_id,
        secret_name=secret_name,
        kind=kind,
        what_for=what_for,
        status=SecretRequestStatus.PENDING,
        requested_by_user_id=requested_by_user_id,
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def list_for_run(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID
) -> list[SecretRequest]:
    """A run's secret requests, oldest first."""
    result = await db.execute(
        select(SecretRequest)
        .where(
            SecretRequest.run_id == run_id,
            SecretRequest.organization_id == organization_id,
        )
        .order_by(SecretRequest.created_at.asc())
    )
    return list(result.scalars().all())


async def claim(
    db: AsyncSession, *, request_id: UUID, organization_id: UUID
) -> SecretRequest | None:
    """The request a fulfil or decline names, held for the rest of the transaction.

    Locked so a double tap is answered once: the second waits here and finds
    it already decided.
    """
    result = await db.execute(
        select(SecretRequest)
        .where(
            SecretRequest.id == request_id,
            SecretRequest.organization_id == organization_id,
        )
        .with_for_update()
    )
    return result.scalars().first()


async def mark_decided(
    db: AsyncSession,
    *,
    request: SecretRequest,
    status: str,
    decided_by_user_id: UUID | None,
    fulfilled_secret_id: UUID | None = None,
    fulfilled_hint: str | None = None,
) -> SecretRequest:
    """Settle a request. Only the secret's id and hint are ever recorded."""
    request.status = status
    request.decided_by_user_id = decided_by_user_id
    request.decided_at = datetime.now(UTC)
    if fulfilled_secret_id is not None:
        request.fulfilled_secret_id = fulfilled_secret_id
    if fulfilled_hint is not None:
        request.fulfilled_hint = fulfilled_hint
    await db.flush()
    await db.refresh(request)
    return request


async def mark_expired(db: AsyncSession, *, request: SecretRequest) -> SecretRequest:
    """Settle a request whose run expired unanswered."""
    request.status = SecretRequestStatus.EXPIRED
    request.decided_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(request)
    return request
