"""Agent environment repository (PostgreSQL async)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_environment import AgentEnvironment


async def get(
    db: AsyncSession, environment_id: UUID, *, organization_id: UUID
) -> AgentEnvironment | None:
    result = await db.execute(
        select(AgentEnvironment).where(
            AgentEnvironment.id == environment_id,
            AgentEnvironment.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID
) -> list[AgentEnvironment]:
    """Every environment of one agent, default first, then by name.

    A stable order because the Builder renders this as a list and the default
    is the row everything else is compared against.
    """
    result = await db.execute(
        select(AgentEnvironment)
        .where(
            AgentEnvironment.agent_id == agent_id,
            AgentEnvironment.organization_id == organization_id,
        )
        .order_by(AgentEnvironment.is_default.desc(), AgentEnvironment.name)
    )
    return list(result.scalars().all())


async def get_default_for_agent(db: AsyncSession, *, agent_id: UUID) -> AgentEnvironment | None:
    """The environment a surface that names none gets.

    Not organization-scoped: the agent id always comes from a row already
    loaded inside one organization, and the partial unique index means at most
    one row can match.
    """
    result = await db.execute(
        select(AgentEnvironment).where(
            AgentEnvironment.agent_id == agent_id,
            AgentEnvironment.is_default.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, *, agent_id: UUID, name: str) -> AgentEnvironment | None:
    """The row occupying a name, for the duplicate check that beats the
    constraint to it - an IntegrityError is not an answer anyone can read."""
    result = await db.execute(
        select(AgentEnvironment).where(
            AgentEnvironment.agent_id == agent_id,
            AgentEnvironment.name == name,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    name: str,
    version_id: UUID,
    is_default: bool = False,
    created_by_user_id: UUID | None = None,
    logfire_token_secret_id: UUID | None = None,
    service_name: str | None = None,
) -> AgentEnvironment:
    environment = AgentEnvironment(
        organization_id=organization_id,
        agent_id=agent_id,
        name=name,
        version_id=version_id,
        is_default=is_default,
        created_by_user_id=created_by_user_id,
        logfire_token_secret_id=logfire_token_secret_id,
        service_name=service_name,
    )
    db.add(environment)
    await db.flush()
    await db.refresh(environment)
    return environment


async def update(
    db: AsyncSession, *, environment: AgentEnvironment, update_data: dict[str, Any]
) -> AgentEnvironment:
    for field, value in update_data.items():
        setattr(environment, field, value)
    await db.flush()
    await db.refresh(environment)
    return environment


async def delete(db: AsyncSession, *, environment: AgentEnvironment) -> None:
    await db.delete(environment)
    await db.flush()
