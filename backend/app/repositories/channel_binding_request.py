"""Binding request repository (PostgreSQL async): requests to bind an agent to a public line.

Every read and write names the organization: a request id or a bot id from another
organization finds nothing.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.channel_binding_request import (
    BindingRequestStatus,
    BindingVoidReason,
    ChannelBindingRequest,
)
from app.db.models.channel_bot import ChannelBot
from app.db.models.user import User


async def create(db: AsyncSession, **fields: Any) -> ChannelBindingRequest:
    request = ChannelBindingRequest(**fields)
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def get(
    db: AsyncSession, request_id: UUID, *, organization_id: UUID
) -> ChannelBindingRequest | None:
    result = await db.execute(
        select(ChannelBindingRequest).where(
            ChannelBindingRequest.id == request_id,
            ChannelBindingRequest.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def lock(
    db: AsyncSession, request_id: UUID, *, organization_id: UUID
) -> ChannelBindingRequest | None:
    """The request locked until the transaction ends, its columns read again.

    A decision made while this waited for the lock is seen as made: a second approval
    of one request finds it settled.
    """
    result = await db.execute(
        select(ChannelBindingRequest)
        .where(
            ChannelBindingRequest.id == request_id,
            ChannelBindingRequest.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def pending_for(
    db: AsyncSession, *, organization_id: UUID, channel_bot_id: UUID, requester_user_id: UUID
) -> ChannelBindingRequest | None:
    """The person's own pending request for the bot, if they have one."""
    result = await db.execute(
        select(ChannelBindingRequest).where(
            ChannelBindingRequest.organization_id == organization_id,
            ChannelBindingRequest.channel_bot_id == channel_bot_id,
            ChannelBindingRequest.requester_user_id == requester_user_id,
            ChannelBindingRequest.status == BindingRequestStatus.PENDING.value,
        )
    )
    return result.scalar_one_or_none()


def _pending_in(organization_id: UUID) -> tuple[Any, ...]:
    return (
        ChannelBindingRequest.organization_id == organization_id,
        ChannelBindingRequest.status == BindingRequestStatus.PENDING.value,
    )


async def list_pending(
    db: AsyncSession, *, organization_id: UUID, skip: int, limit: int
) -> tuple[list[ChannelBindingRequest], int]:
    """The organization's pending requests, newest first, with the total."""
    where = _pending_in(organization_id)
    result = await db.execute(
        select(ChannelBindingRequest)
        .where(*where)
        .order_by(ChannelBindingRequest.created_at.desc(), ChannelBindingRequest.id)
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(ChannelBindingRequest.id)).where(*where))
    return list(result.scalars().all()), total or 0


async def list_for_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    requester_user_id: UUID | None = None,
) -> list[ChannelBindingRequest]:
    """The pending requests that name this agent, newest first; with `requester_user_id`,
    only that person's."""
    where = [*_pending_in(organization_id), ChannelBindingRequest.agent_id == agent_id]
    if requester_user_id is not None:
        where.append(ChannelBindingRequest.requester_user_id == requester_user_id)
    result = await db.execute(
        select(ChannelBindingRequest)
        .where(*where)
        .order_by(ChannelBindingRequest.created_at.desc(), ChannelBindingRequest.id)
    )
    return list(result.scalars().all())


async def labels(
    db: AsyncSession, requests: list[ChannelBindingRequest]
) -> dict[UUID, tuple[str, str, str | None]]:
    """Each request's agent name, bot name and requester email, in one query."""
    if not requests:
        return {}
    result = await db.execute(
        select(ChannelBindingRequest.id, Agent.name, ChannelBot.name, User.email)
        .join(Agent, Agent.id == ChannelBindingRequest.agent_id)
        .join(ChannelBot, ChannelBot.id == ChannelBindingRequest.channel_bot_id)
        .outerjoin(User, User.id == ChannelBindingRequest.requester_user_id)
        .where(ChannelBindingRequest.id.in_([request.id for request in requests]))
    )
    return {row[0]: (row[1], row[2], row[3]) for row in result.all()}


async def settle(
    db: AsyncSession,
    request: ChannelBindingRequest,
    *,
    status: BindingRequestStatus,
    void_reason: BindingVoidReason | None = None,
    decided_by_user_id: UUID | None = None,
) -> ChannelBindingRequest:
    """End a pending request: decided by a person, or voided for a reason."""
    request.status = status.value
    request.void_reason = void_reason.value if void_reason is not None else None
    request.decided_by_user_id = decided_by_user_id
    request.decided_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(request)
    return request


async def void_pending_for_bot(
    db: AsyncSession,
    *,
    organization_id: UUID,
    channel_bot_id: UUID,
    reason: BindingVoidReason,
) -> int:
    """Void every request pending on the bot, whoever filed it. Returns how many."""
    result = cast(
        CursorResult[Any],
        await db.execute(
            sql_update(ChannelBindingRequest)
            .where(
                *_pending_in(organization_id),
                ChannelBindingRequest.channel_bot_id == channel_bot_id,
            )
            .values(
                status=BindingRequestStatus.VOIDED.value,
                void_reason=reason.value,
                decided_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session="fetch")
        ),
    )
    return result.rowcount or 0
