"""Tenant-bound room submissions, their queue head and reconciled run state."""

from uuid import UUID

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent_run import AgentRun
from app.db.models.room_submission import RoomSubmission

ACTIVE = ("queued", "running", "awaiting_approval", "awaiting_answer")


async def get(
    db: AsyncSession, request_id: UUID, *, organization_id: UUID, lock: bool = False
) -> RoomSubmission | None:
    query = select(RoomSubmission).where(
        RoomSubmission.id == request_id,
        RoomSubmission.organization_id == organization_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def for_client(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    requester_id: UUID,
    client_message_id: str,
) -> RoomSubmission | None:
    return await db.scalar(
        select(RoomSubmission).where(
            RoomSubmission.organization_id == organization_id,
            RoomSubmission.conversation_id == conversation_id,
            RoomSubmission.requester_id == requester_id,
            RoomSubmission.client_message_id == client_message_id,
        )
    )


async def for_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> RoomSubmission | None:
    return await db.scalar(
        select(RoomSubmission).where(
            RoomSubmission.organization_id == organization_id,
            RoomSubmission.run_id == run_id,
        )
    )


async def add(db: AsyncSession, submission: RoomSubmission) -> RoomSubmission:
    db.add(submission)
    await db.flush()
    await db.refresh(submission)
    return submission


async def save(db: AsyncSession, submission: RoomSubmission) -> None:
    db.add(submission)
    await db.flush()


async def list_requests(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    skip: int,
    limit: int,
) -> tuple[list[RoomSubmission], int]:
    where = (
        RoomSubmission.organization_id == organization_id,
        RoomSubmission.conversation_id == conversation_id,
        RoomSubmission.agent_id.is_not(None),
    )
    rows = await db.scalars(
        select(RoomSubmission)
        .where(*where)
        .order_by(
            case((RoomSubmission.status.in_(ACTIVE), 0), else_=1),
            case((RoomSubmission.status.in_(ACTIVE), RoomSubmission.ordinal)),
            RoomSubmission.ordinal.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count()).select_from(RoomSubmission).where(*where))
    return list(rows.all()), total or 0


async def active_count(db: AsyncSession, *, conversation_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(RoomSubmission)
            .where(
                RoomSubmission.conversation_id == conversation_id,
                RoomSubmission.status.in_(ACTIVE),
            )
        )
        or 0
    )


async def head(db: AsyncSession, conversation_id: UUID) -> RoomSubmission | None:
    """The first unresolved request, including one parked on a human decision."""
    return await db.scalar(
        select(RoomSubmission)
        .where(
            RoomSubmission.conversation_id == conversation_id,
            RoomSubmission.status.in_(ACTIVE),
        )
        .order_by(RoomSubmission.ordinal)
        .limit(1)
    )


async def ready(db: AsyncSession) -> list[RoomSubmission]:
    """Only queued heads, so parked rooms do not consume dispatch slots."""
    earlier = aliased(RoomSubmission)
    return list(
        (
            await db.scalars(
                select(RoomSubmission)
                .where(
                    RoomSubmission.status == "queued",
                    ~exists(
                        select(earlier.id).where(
                            earlier.conversation_id == RoomSubmission.conversation_id,
                            earlier.status.in_(ACTIVE),
                            earlier.ordinal < RoomSubmission.ordinal,
                        )
                    ),
                )
                .order_by(RoomSubmission.ordinal)
                .limit(100)
            )
        ).all()
    )


async def unsettled_runs(db: AsyncSession) -> list[tuple[RoomSubmission, AgentRun]]:
    rows = await db.execute(
        select(RoomSubmission, AgentRun)
        .join(AgentRun, AgentRun.id == RoomSubmission.run_id)
        .where(
            RoomSubmission.status.in_(("running", "awaiting_approval", "awaiting_answer")),
            AgentRun.status != RoomSubmission.status,
        )
        .order_by(RoomSubmission.ordinal)
        .limit(100)
    )
    return [(submission, run) for submission, run in rows.all()]
