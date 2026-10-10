"""Which agent is each organization's AI Architect (#2063)."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization_assistant import OrganizationAssistant


async def get(db: AsyncSession, organization_id: UUID) -> OrganizationAssistant | None:
    return await db.get(OrganizationAssistant, organization_id)


async def lock_for_install(db: AsyncSession, organization_id: UUID) -> None:
    """Serialize the first install in one organization until this transaction ends.

    Two people opening the console at once would otherwise both find no assistant
    and both create one; the second's row would then fail on the primary key with
    an agent already made for nothing.
    """
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"assistant:{organization_id}")))
    )


async def create(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> OrganizationAssistant:
    row = OrganizationAssistant(organization_id=organization_id, agent_id=agent_id)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession, *, row: OrganizationAssistant, update_data: dict[str, Any]
) -> OrganizationAssistant:
    for field, value in update_data.items():
        setattr(row, field, value)
    await db.flush()
    await db.refresh(row)
    return row


async def for_agent(db: AsyncSession, agent_id: UUID) -> OrganizationAssistant | None:
    """The assistant row an agent is, if it is one."""
    result = await db.execute(
        select(OrganizationAssistant).where(OrganizationAssistant.agent_id == agent_id)
    )
    return result.scalar_one_or_none()
