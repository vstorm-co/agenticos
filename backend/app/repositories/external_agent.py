"""Remote A2A agents an organization registered to delegate to (#2092)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.external_agent import ExternalAgent


async def create(db: AsyncSession, **fields: Any) -> ExternalAgent:
    agent = ExternalAgent(**fields)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def get(db: AsyncSession, agent_id: UUID, *, organization_id: UUID) -> ExternalAgent | None:
    result = await db.execute(
        select(ExternalAgent).where(
            ExternalAgent.id == agent_id, ExternalAgent.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_many(
    db: AsyncSession, agent_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, ExternalAgent]:
    if not agent_ids:
        return {}
    result = await db.execute(
        select(ExternalAgent).where(
            ExternalAgent.id.in_(agent_ids), ExternalAgent.organization_id == organization_id
        )
    )
    return {agent.id: agent for agent in result.scalars().all()}


async def get_by_slug(
    db: AsyncSession, slug: str, *, organization_id: UUID
) -> ExternalAgent | None:
    result = await db.execute(
        select(ExternalAgent).where(
            ExternalAgent.slug == slug, ExternalAgent.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, *, organization_id: UUID) -> list[ExternalAgent]:
    result = await db.execute(
        select(ExternalAgent)
        .where(ExternalAgent.organization_id == organization_id)
        .order_by(ExternalAgent.name)
    )
    return list(result.scalars().all())


async def update(
    db: AsyncSession, *, agent: ExternalAgent, update_data: dict[str, Any]
) -> ExternalAgent:
    for field, value in update_data.items():
        setattr(agent, field, value)
    await db.flush()
    await db.refresh(agent)
    return agent


async def delete(db: AsyncSession, agent: ExternalAgent) -> None:
    await db.delete(agent)
    await db.flush()
