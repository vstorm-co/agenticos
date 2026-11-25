"""Owner-scoped transfer journals; the service owns transitions and transactions."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import LockScope, hold_name
from app.db.models.portability_operation import PortabilityOperation
from app.schemas.portability_operation import TransferDirection, TransferStatus


async def lock_owner(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> None:
    await hold_name(db, LockScope.PORTABILITY_PER_OWNER, f"{organization_id}/{user_id}")


async def get(
    db: AsyncSession,
    identity: UUID,
    *,
    organization_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> PortabilityOperation | None:
    query = (
        select(PortabilityOperation)
        .where(
            PortabilityOperation.id == identity,
            PortabilityOperation.organization_id == organization_id,
            PortabilityOperation.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def for_request(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, request_id: UUID
) -> PortabilityOperation | None:
    return await db.scalar(
        select(PortabilityOperation).where(
            PortabilityOperation.organization_id == organization_id,
            PortabilityOperation.user_id == user_id,
            PortabilityOperation.request_id == request_id,
        )
    )


async def get_for_worker(
    db: AsyncSession, identity: UUID, *, for_update: bool = False
) -> PortabilityOperation | None:
    """A job carries this server-minted identity; execution must rebuild authority."""
    query = (
        select(PortabilityOperation)
        .where(PortabilityOperation.id == identity)
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def count_open(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, now: datetime
) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(PortabilityOperation)
            .where(
                PortabilityOperation.organization_id == organization_id,
                PortabilityOperation.user_id == user_id,
                PortabilityOperation.status.not_in(("ready", "failed", "expired")),
                PortabilityOperation.expires_at > now,
            )
        )
        or 0
    )


async def create(
    db: AsyncSession,
    *,
    identity: UUID,
    organization_id: UUID,
    user_id: UUID,
    api_key_id: UUID | None,
    request_id: UUID,
    request_hash: str,
    direction: TransferDirection,
    status: TransferStatus,
    request: dict[str, JsonValue],
    expires_at: datetime,
) -> PortabilityOperation:
    row = PortabilityOperation(
        id=identity,
        organization_id=organization_id,
        user_id=user_id,
        api_key_id=api_key_id,
        request_id=request_id,
        request_hash=request_hash,
        direction=direction,
        status=status,
        request=request,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def save(db: AsyncSession, row: PortabilityOperation) -> None:
    await db.flush()
    await db.refresh(row)


async def expired(
    db: AsyncSession, *, now: datetime, limit: int = 100
) -> list[PortabilityOperation]:
    result = await db.scalars(
        select(PortabilityOperation)
        .where(
            PortabilityOperation.expires_at <= now,
        )
        .order_by(PortabilityOperation.expires_at, PortabilityOperation.id)
        .limit(limit)
    )
    return list(result)


async def delete(db: AsyncSession, row: PortabilityOperation) -> None:
    await db.delete(row)
    await db.flush()
