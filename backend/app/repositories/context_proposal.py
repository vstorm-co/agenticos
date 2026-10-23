"""Data access for the authoring assistant's proposed context file changes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.skill_proposal import ProposalStatus


async def get(
    db: AsyncSession, proposal_id: UUID, *, organization_id: UUID
) -> ContextProposal | None:
    result = await db.execute(
        select(ContextProposal).where(
            ContextProposal.id == proposal_id,
            ContextProposal.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_pending_for_context(
    db: AsyncSession, *, organization_id: UUID, context_id: UUID
) -> ContextProposal | None:
    """The waiting proposal a newer one replaces, so a file has one waiting at a time."""
    result = await db.execute(
        select(ContextProposal).where(
            ContextProposal.organization_id == organization_id,
            ContextProposal.context_id == context_id,
            ContextProposal.status == ProposalStatus.PENDING.value,
        )
    )
    return result.scalars().first()


async def list_for_organization(
    db: AsyncSession, *, organization_id: UUID, status: str | None = None
) -> list[ContextProposal]:
    statement = select(ContextProposal).where(ContextProposal.organization_id == organization_id)
    if status is not None:
        statement = statement.where(ContextProposal.status == status)
    result = await db.execute(statement.order_by(ContextProposal.created_at.desc()))
    return list(result.scalars().all())


async def files_with_pending(
    db: AsyncSession, *, organization_id: UUID
) -> list[tuple[ContextFile, int]]:
    """Every context file with proposed changes nobody has decided, and how many."""
    result = await db.execute(
        select(ContextFile, func.count())
        .join(ContextProposal, ContextProposal.context_id == ContextFile.id)
        .where(
            ContextProposal.organization_id == organization_id,
            ContextProposal.status == ProposalStatus.PENDING.value,
        )
        .group_by(ContextFile.id)
        .order_by(ContextFile.name)
    )
    return [(file, int(count)) for file, count in result.all()]


async def create(
    db: AsyncSession, *, organization_id: UUID, context_id: UUID, values: dict[str, Any]
) -> ContextProposal:
    proposal = ContextProposal(organization_id=organization_id, context_id=context_id, **values)
    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def update(
    db: AsyncSession, *, proposal: ContextProposal, values: dict[str, Any]
) -> ContextProposal:
    for field, value in values.items():
        setattr(proposal, field, value)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def decide(
    db: AsyncSession, *, proposal: ContextProposal, status: ProposalStatus, decided_by: UUID | None
) -> ContextProposal:
    return await update(
        db,
        proposal=proposal,
        values={
            "status": status.value,
            "decided_by_user_id": decided_by,
            "decided_at": datetime.now(UTC),
        },
    )
