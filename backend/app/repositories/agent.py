"""Agent registry repositories (PostgreSQL async).

Listing an agent is not a plain org filter: what a member sees depends on their
role scope and on what was shared with them, so `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them here.
"""

from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.resource_grant import Visibility


async def get_many(
    db: AsyncSession, agent_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, Agent]:
    """Several agents at once, by id, inside one organization.

    One statement rather than a lookup per row: the callers are listings that
    need a name beside each of a page of rows, and a query each is how a table of
    thirty becomes thirty round trips.
    """
    if not agent_ids:
        return {}
    result = await db.execute(
        select(Agent).where(Agent.id.in_(list(agent_ids)), Agent.organization_id == organization_id)
    )
    return {agent.id: agent for agent in result.scalars().all()}


async def existing_ids_locked(
    db: AsyncSession, agent_ids: Collection[UUID], *, organization_id: UUID
) -> set[UUID]:
    """Which of these agents still exist, locked so they cannot be deleted until commit.

    For the deferred approval write. A delegate whose gated call was parked can be
    deleted between the call and the run's terminal write - the write is deferred to
    that point - and its id rides on the approval row as a `SET NULL` foreign key.
    Inserting the row would then violate that key and roll the whole parked run
    back, so the writer nulls an id whose agent is gone. `FOR KEY SHARE` - the lock
    an insert referencing the row would itself take - holds the survivors so a
    concurrent delete cannot slip in between this check and that insert, which is
    the guarantee the old inline insert had and a bare existence check would lose.
    """
    if not agent_ids:
        return set()
    result = await db.execute(
        select(Agent.id)
        .where(Agent.id.in_(list(agent_ids)), Agent.organization_id == organization_id)
        .with_for_update(read=True, key_share=True)
    )
    return set(result.scalars().all())


async def get(db: AsyncSession, agent_id: UUID, *, organization_id: UUID) -> Agent | None:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, slug: str, *, organization_id: UUID) -> Agent | None:
    result = await db.execute(
        select(Agent).where(Agent.slug == slug, Agent.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    include_archived: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Agent], int]:
    """Agents this member may see, with a total count.

    Args:
        see_all: True when the role reaches the whole organization; the
            ownership predicate is then skipped entirely.
        shared_ids: Agent ids explicitly shared with this member.
    """
    query = select(Agent).where(Agent.organization_id == organization_id)
    count_query = select(func.count(Agent.id)).where(Agent.organization_id == organization_id)

    if not include_archived:
        query = query.where(Agent.status != AgentStatus.ARCHIVED.value)
        count_query = count_query.where(Agent.status != AgentStatus.ARCHIVED.value)

    if not see_all:
        visible = or_(
            Agent.owner_user_id == user_id,
            Agent.visibility == Visibility.ORG.value,
            Agent.id.in_(shared_ids) if shared_ids else False,
        )
        query = query.where(visible)
        count_query = count_query.where(visible)

    query = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def list_all_published(db: AsyncSession) -> list[Agent]:
    """Every published agent on the deployment, whoever owns it.

    Deliberately unscoped, like :func:`app.repositories.organization.list_all`,
    and for the same narrow reason: work that is *about* the deployment rather
    than about a tenant. The only caller is the scheduled usage report, which has
    no member to scope to and must reach every organization's agents to know
    which of them asked for one. Grep for this function when auditing
    cross-tenant reads.

    Published only. A draft has no audience that agreed to hear from it - its
    notification settings have not been published either - and archived agents
    are not running.
    """
    result = await db.execute(
        select(Agent).where(Agent.status == AgentStatus.PUBLISHED.value).order_by(Agent.created_at)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    slug: str,
    name: str,
    description: str | None,
    draft_spec: dict,
    owner_user_id: UUID | None,
    created_by_user_id: UUID | None,
) -> Agent:
    agent = Agent(
        organization_id=organization_id,
        slug=slug,
        name=name,
        description=description,
        draft_spec=draft_spec,
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def update(db: AsyncSession, *, agent: Agent, update_data: dict) -> Agent:
    for field, value in update_data.items():
        setattr(agent, field, value)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def delete(db: AsyncSession, agent: Agent) -> None:
    await db.delete(agent)
    await db.flush()


async def next_version_number(db: AsyncSession, *, agent_id: UUID) -> int:
    """The next version number for an agent, starting at 1."""
    current = await db.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id)
    )
    return (current or 0) + 1


async def create_version(
    db: AsyncSession,
    *,
    agent_id: UUID,
    organization_id: UUID,
    version: int,
    spec: dict,
    note: str | None,
    published_by_user_id: UUID | None,
) -> AgentVersion:
    row = AgentVersion(
        agent_id=agent_id,
        organization_id=organization_id,
        version=version,
        spec=spec,
        note=note,
        published_by_user_id=published_by_user_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_version(
    db: AsyncSession, version_id: UUID, *, organization_id: UUID
) -> AgentVersion | None:
    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID, limit: int = 50
) -> list[AgentVersion]:
    result = await db.execute(
        select(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.organization_id == organization_id,
        )
        .order_by(AgentVersion.version.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
