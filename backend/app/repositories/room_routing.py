"""Tenant-scoped room policy, proposal and canonical-task linkage persistence."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_trigger import AgentTrigger
from app.db.models.room_routing import RoomLeadPolicy, RoomRoutingProposal, RoomTaskLink


async def policy(
    db: AsyncSession, organization_id: UUID, conversation_id: UUID
) -> RoomLeadPolicy | None:
    return await db.scalar(
        select(RoomLeadPolicy)
        .where(
            RoomLeadPolicy.organization_id == organization_id,
            RoomLeadPolicy.conversation_id == conversation_id,
        )
        .execution_options(populate_existing=True)
    )


async def proposal(
    db: AsyncSession,
    proposal_id: UUID,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    lock: bool = False,
) -> RoomRoutingProposal | None:
    query = select(RoomRoutingProposal).where(
        RoomRoutingProposal.id == proposal_id,
        RoomRoutingProposal.organization_id == organization_id,
        RoomRoutingProposal.conversation_id == conversation_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def for_submission(
    db: AsyncSession,
    submission_id: UUID,
    *,
    organization_id: UUID,
    conversation_id: UUID,
) -> RoomRoutingProposal | None:
    return await db.scalar(
        select(RoomRoutingProposal).where(
            RoomRoutingProposal.organization_id == organization_id,
            RoomRoutingProposal.conversation_id == conversation_id,
            RoomRoutingProposal.submission_id == submission_id,
        )
    )


async def proposals(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    thread_root_message_id: UUID | None,
    limit: int,
    skip: int,
) -> list[RoomRoutingProposal]:
    query = select(RoomRoutingProposal).where(
        RoomRoutingProposal.organization_id == organization_id,
        RoomRoutingProposal.conversation_id == conversation_id,
    )
    if thread_root_message_id is not None:
        query = query.where(RoomRoutingProposal.thread_root_message_id == thread_root_message_id)
    return list(
        (
            await db.scalars(
                query.order_by(RoomRoutingProposal.created_at.desc(), RoomRoutingProposal.id)
                .offset(skip)
                .limit(limit + 1)
            )
        ).all()
    )


async def task_links(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    thread_root_message_id: UUID | None,
    limit: int,
    skip: int,
) -> list[tuple[RoomTaskLink, RoomRoutingProposal]]:
    query = (
        select(RoomTaskLink, RoomRoutingProposal)
        .join(RoomRoutingProposal, RoomRoutingProposal.id == RoomTaskLink.proposal_id)
        .where(
            RoomTaskLink.organization_id == organization_id,
            RoomTaskLink.conversation_id == conversation_id,
            RoomRoutingProposal.organization_id == organization_id,
            RoomRoutingProposal.conversation_id == conversation_id,
        )
    )
    if thread_root_message_id is not None:
        query = query.where(RoomRoutingProposal.thread_root_message_id == thread_root_message_id)
    rows = await db.execute(
        query.order_by(RoomTaskLink.created_at.desc(), RoomTaskLink.id)
        .offset(skip)
        .limit(limit + 1)
    )
    return [(link, item) for link, item in rows]


async def dispatch_version(
    db: AsyncSession,
    trigger_id: UUID,
    *,
    organization_id: UUID,
) -> UUID | None:
    return await db.scalar(
        select(AgentTrigger.pinned_version_id).where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.organization_id == organization_id,
        )
    )


async def save(
    db: AsyncSession,
    row: RoomLeadPolicy | RoomRoutingProposal | RoomTaskLink,
) -> None:
    db.add(row)
    await db.flush()
    await db.refresh(row)
