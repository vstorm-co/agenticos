"""Agent exposure repository (PostgreSQL async)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
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
    reason as `resource_grant.count_for_resources`: the agent gallery wants a
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


async def list_active_for_bot(
    db: AsyncSession, *, channel_bot_id: UUID
) -> list[tuple[AgentExposure, Agent]]:
    """Every agent actively answering on this bot, with the agent row itself.

    The agent comes back alongside the binding because the two callers both
    need its slug: one to run the only agent a bot serves, the other to tell
    the sender which handles they could have mentioned. Paused bindings are
    excluded - an agent someone switched off is not an answer to either
    question.

    Not organization-scoped: the bot id comes from a row already loaded inside
    one organization, and every binding cascades from that bot.
    """
    result = await db.execute(
        select(AgentExposure, Agent)
        .join(Agent, Agent.id == AgentExposure.agent_id)
        .where(
            AgentExposure.channel_bot_id == channel_bot_id,
            AgentExposure.is_active.is_(True),
        )
        .order_by(Agent.slug)
    )
    return [(exposure, agent) for exposure, agent in result.all()]


async def active_agents_for_bots(
    db: AsyncSession, *, channel_bot_ids: list[UUID]
) -> dict[UUID, list[Agent]]:
    """Which agents answer on each of these bots, in one query.

    The channels listing asks it of every row at once, the same way the agent
    gallery asks `active_surfaces_for_agents` for its badges - a query per bot
    is a page that gets slower the more channels an organization has.

    Paused bindings are excluded: a bot whose only agent is switched off answers
    nothing, and a listing that named it would be describing a channel that is
    silent. Bots with no active binding are simply absent from the result.
    """
    if not channel_bot_ids:
        return {}
    result = await db.execute(
        select(AgentExposure.channel_bot_id, Agent)
        .join(Agent, Agent.id == AgentExposure.agent_id)
        .where(
            AgentExposure.channel_bot_id.in_(channel_bot_ids),
            AgentExposure.is_active.is_(True),
        )
        .order_by(AgentExposure.channel_bot_id, Agent.slug)
    )
    found: dict[UUID, list[Agent]] = {}
    for channel_bot_id, agent in result.all():
        found.setdefault(channel_bot_id, []).append(agent)
    return found


async def bound_agent_by_bot(db: AsyncSession, *, channel_bot_ids: list[UUID]) -> dict[UUID, UUID]:
    """Which agent each of these bots is bound to, paused bindings included.

    Distinct from `active_agents_for_bots`, and the difference is the whole
    point: that one answers "who is answering here" and skips a paused binding,
    while this answers "is this bot taken" - and a paused binding still occupies
    `uq_exposure_bot`. The picker needs this one, or it offers a bot that
    refuses with a 409 the moment somebody chooses it.
    """
    if not channel_bot_ids:
        return {}
    result = await db.execute(
        select(AgentExposure.channel_bot_id, AgentExposure.agent_id).where(
            AgentExposure.channel_bot_id.in_(channel_bot_ids)
        )
    )
    taken: dict[UUID, UUID] = {}
    for channel_bot_id, agent_id in result.all():
        taken[channel_bot_id] = agent_id
    return taken


async def bound_to_bot(db: AsyncSession, *, channel_bot_id: UUID) -> AgentExposure | None:
    """The binding this bot already has, whoever it belongs to, or `None`.

    A bot serves one agent, so this is the whole answer rather than a first row
    of several - `uq_exposure_bot` is what makes that true. Paused bindings
    count: one still occupies the constraint, and a caller told "that bot is
    free" and then refused by the database has been told the wrong thing.

    Not organization-scoped, like its neighbours here: the bot id comes from a
    row already loaded inside one organization, and every binding cascades from
    that bot.
    """
    result = await db.execute(
        select(AgentExposure).where(AgentExposure.channel_bot_id == channel_bot_id)
    )
    return result.scalars().first()


async def get_for_bot(
    db: AsyncSession, *, agent_id: UUID, channel_bot_id: UUID
) -> AgentExposure | None:
    """The binding between this agent and this bot, active or not.

    Returns paused rows too, and every caller must say what it does with them.
    Filtering here instead would make a paused binding indistinguishable from no
    binding to the one place that needs the difference - the duplicate check,
    which would otherwise let a second row race the unique constraint.

    Not organization-scoped, and it does not need to be: both ids come from rows
    already loaded inside one organization, and `uq_exposure_bot` means at most
    one row can match the bot at all.
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
    environment_id: UUID | None = None,
    session_scope: str | None = None,
    prompt: str | None = None,
) -> AgentExposure:
    exposure = AgentExposure(
        organization_id=organization_id,
        agent_id=agent_id,
        surface=surface,
        channel_bot_id=channel_bot_id,
        created_by_user_id=created_by_user_id,
        environment_id=environment_id,
        session_scope=session_scope,
        prompt=prompt,
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
    from "cleared to null" - somebody pausing a binding must not silently move
    it back to the default environment.
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
