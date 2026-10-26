"""Agent environment repository (PostgreSQL async)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import AgentVersion
from app.db.models.agent_environment import AgentEnvironment, AgentEnvironmentConnection


async def lock(db: AsyncSession, environment_id: UUID) -> None:
    """Hold the environment's row until the transaction ends.

    `FOR UPDATE` conflicts with the key-share lock a new row's foreign key takes
    on the row it references, so a run naming this environment cannot be
    written while the lock is held - it waits, and fails on the foreign key if
    the environment is gone by then.
    """
    await db.execute(
        select(AgentEnvironment.id).where(AgentEnvironment.id == environment_id).with_for_update()
    )


async def get(
    db: AsyncSession, environment_id: UUID, *, organization_id: UUID
) -> AgentEnvironment | None:
    result = await db.execute(
        select(AgentEnvironment)
        .execution_options(populate_existing=True)
        .where(
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
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def get_default_for_agent(db: AsyncSession, *, agent_id: UUID) -> AgentEnvironment | None:
    """The environment a surface that names none gets.

    Not organization-scoped: the agent id always comes from a row already
    loaded inside one organization, and the partial unique index means at most
    one row can match.
    """
    result = await db.execute(
        select(AgentEnvironment)
        .execution_options(populate_existing=True)
        .where(
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
    tracks_latest: bool = False,
    created_by_user_id: UUID | None = None,
    logfire_token_secret_id: UUID | None = None,
    service_name: str | None = None,
) -> AgentEnvironment:
    environment = AgentEnvironment(
        organization_id=organization_id,
        agent_id=agent_id,
        tracks_latest=tracks_latest,
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


async def following_latest(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID
) -> list[AgentEnvironment]:
    """The environments a publish moves - the ones that asked to be moved.

    A publish repoints these and nothing else. It used to repoint the default
    whatever mode it was in, which made "publish" and "deploy" one word.
    """
    result = await db.execute(
        select(AgentEnvironment)
        .execution_options(populate_existing=True)
        .where(
            AgentEnvironment.agent_id == agent_id,
            AgentEnvironment.organization_id == organization_id,
            AgentEnvironment.tracks_latest.is_(True),
        )
    )
    return list(result.scalars().all())


async def delete(db: AsyncSession, *, environment: AgentEnvironment) -> None:
    await db.delete(environment)
    await db.flush()


async def list_connections(
    db: AsyncSession, *, environment_ids: Sequence[UUID], organization_id: UUID
) -> list[AgentEnvironmentConnection]:
    """The connection overrides of several environments, in a stable order."""
    if not environment_ids:
        return []
    result = await db.execute(
        select(AgentEnvironmentConnection)
        .where(
            AgentEnvironmentConnection.environment_id.in_(list(environment_ids)),
            AgentEnvironmentConnection.organization_id == organization_id,
        )
        .order_by(AgentEnvironmentConnection.kind, AgentEnvironmentConnection.created_at)
    )
    return list(result.scalars().all())


async def replace_connections(
    db: AsyncSession,
    *,
    environment_id: UUID,
    organization_id: UUID,
    connections: Sequence[AgentEnvironmentConnection],
) -> None:
    """Make `connections` the environment's whole set of overrides.

    The set is edited as one list in the Builder, so it is written as one:
    a partial update would have to say which override a row is, and the only
    identity an override has is what it overrides.
    """
    await db.execute(
        sql_delete(AgentEnvironmentConnection).where(
            AgentEnvironmentConnection.environment_id == environment_id,
            AgentEnvironmentConnection.organization_id == organization_id,
        )
    )
    for connection in connections:
        connection.environment_id = environment_id
        connection.organization_id = organization_id
        db.add(connection)
    await db.flush()


async def served(
    db: AsyncSession, *, organization_id: UUID
) -> list[tuple[AgentEnvironment, AgentVersion]]:
    """Every environment of the organization's agents, with the version it serves."""
    result = await db.execute(
        select(AgentEnvironment, AgentVersion)
        .join(AgentVersion, AgentVersion.id == AgentEnvironment.version_id)
        .where(AgentEnvironment.organization_id == organization_id)
        .order_by(AgentEnvironment.agent_id, AgentEnvironment.created_at)
    )
    return list(result.tuples().all())
