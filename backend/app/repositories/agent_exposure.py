"""Agent exposure repository (PostgreSQL async)."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_exposure import AgentExposure


async def get(
    db: AsyncSession, exposure_id: UUID, *, organization_id: UUID
) -> AgentExposure | None:
    result = await db.execute(
        select(AgentExposure).where(
            AgentExposure.id == exposure_id,
            AgentExposure.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID
) -> list[AgentExposure]:
    result = await db.execute(
        select(AgentExposure)
        .where(
            AgentExposure.agent_id == agent_id,
            AgentExposure.organization_id == organization_id,
        )
        .order_by(AgentExposure.created_at.asc())
    )
    return list(result.scalars().all())


async def active_surfaces_for_agents(
    db: AsyncSession, *, organization_id: UUID, agent_ids: list[UUID]
) -> dict[UUID, list[str]]:
    """Which surfaces each agent is actively available on.

    One grouped query for a whole page rather than one per row, for the same
    reason as ``resource_grant.count_for_resources``: the agent gallery wants a
    channel badge on every card. Paused bindings are excluded - a card saying
    "Slack" about an agent that stopped answering there is worse than no badge.
    Agents with no active binding are simply absent from the result.
    """
    if not agent_ids:
        return {}
    result = await db.execute(
        select(AgentExposure.agent_id, AgentExposure.surface)
        .where(
            AgentExposure.organization_id == organization_id,
            AgentExposure.agent_id.in_(agent_ids),
            AgentExposure.is_active.is_(True),
        )
        .distinct()
        .order_by(AgentExposure.agent_id, AgentExposure.surface)
    )
    surfaces: dict[UUID, list[str]] = {}
    for agent_id, surface in result.all():
        surfaces.setdefault(agent_id, []).append(surface)
    return surfaces


async def get_for_bot(
    db: AsyncSession, *, agent_id: UUID, channel_bot_id: UUID
) -> AgentExposure | None:
    """The binding between this agent and this bot, active or not.

    Returns paused rows too, and every caller must say what it does with them.
    Filtering here instead would make a paused binding indistinguishable from no
    binding to the one place that needs the difference - the duplicate check,
    which would otherwise let a second row race the unique constraint.

    Not organization-scoped, and it does not need to be: both ids come from rows
    already loaded inside one organization, and the unique constraint on the pair
    means at most one row can match.
    """
    result = await db.execute(
        select(AgentExposure).where(
            AgentExposure.agent_id == agent_id,
            AgentExposure.channel_bot_id == channel_bot_id,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    surface: str,
    channel_bot_id: UUID,
    created_by_user_id: UUID | None,
    max_per_run_usd: Decimal | None = None,
    monthly_usd: Decimal | None = None,
) -> AgentExposure:
    exposure = AgentExposure(
        organization_id=organization_id,
        agent_id=agent_id,
        surface=surface,
        channel_bot_id=channel_bot_id,
        created_by_user_id=created_by_user_id,
        max_per_run_usd=max_per_run_usd,
        monthly_usd=monthly_usd,
    )
    db.add(exposure)
    await db.flush()
    await db.refresh(exposure)
    return exposure


async def update(
    db: AsyncSession, *, exposure: AgentExposure, update_data: dict[str, Any]
) -> AgentExposure:
    """Apply the fields a caller actually sent.

    Takes a dict rather than named arguments so "not sent" stays distinguishable
    from "cleared to null" - somebody pausing a binding must not silently drop
    the budget another person set on it.
    """
    for field_name, value in update_data.items():
        setattr(exposure, field_name, value)
    db.add(exposure)
    await db.flush()
    await db.refresh(exposure)
    return exposure


async def delete(db: AsyncSession, exposure: AgentExposure) -> None:
    await db.delete(exposure)
    await db.flush()
