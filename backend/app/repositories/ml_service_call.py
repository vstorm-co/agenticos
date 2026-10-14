"""Reading and writing the ML service usage log."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.channel_bot import ChannelBot
from app.db.models.ml_service_call import MLCallStatus, MLServiceCall, TranscriptionSurface


@dataclass(frozen=True)
class CallFilters:
    """What a listing of the usage log is narrowed to; `None` narrows nothing."""

    service: str | None = None
    agent_id: UUID | None = None
    channel_bot_id: UUID | None = None
    surface: TranscriptionSurface | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True)
class AgentUsage:
    """One agent's or one channel bot's share of a summary."""

    id: UUID
    name: str
    seconds: int
    count: int


@dataclass(frozen=True)
class SurfaceUsage:
    """One surface's share of a summary. `None` is a row older than surfaces."""

    surface: TranscriptionSurface | None
    seconds: int
    count: int


@dataclass(frozen=True)
class UsageSummary:
    """An organization's successful calls to one service over a window."""

    seconds: int
    count: int
    count_unknown_length: int
    by_agent: list[AgentUsage]
    by_channel: list[AgentUsage]
    by_surface: list[SurfaceUsage]


async def record(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requested_by_user_id: UUID | None,
    service: str,
    status: str,
    input_bytes: int,
    units: int,
    unit: str,
    duration_ms: int,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    surface: TranscriptionSurface | None = None,
    agent_id: UUID | None = None,
    channel_bot_id: UUID | None = None,
    audio_ms: int | None = None,
) -> MLServiceCall:
    """Write one call's record."""
    row = MLServiceCall(
        organization_id=organization_id,
        requested_by_user_id=requested_by_user_id,
        service=service,
        status=status,
        input_bytes=input_bytes,
        units=units,
        unit=unit,
        duration_ms=duration_ms,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        provider=provider,
        model=model,
        surface=surface,
        agent_id=agent_id,
        channel_bot_id=channel_bot_id,
        audio_ms=audio_ms,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get(db: AsyncSession, call_id: UUID, *, organization_id: UUID) -> MLServiceCall | None:
    """One call record, or None where it belongs to another tenant.

    The organization is part of the lookup rather than checked afterwards, so a
    row from a different tenant is indistinguishable from one that never existed.
    """
    result = await db.execute(
        select(MLServiceCall).where(
            MLServiceCall.id == call_id,
            MLServiceCall.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


def _conditions(organization_id: UUID, filters: CallFilters) -> list[ColumnElement[bool]]:
    """The WHERE clause of a listing, the organization always first.

    A filter on another tenant's agent or bot is not refused, it is simply ANDed
    with this organization - so it matches nothing rather than saying whether
    that id exists.
    """
    conditions: list[ColumnElement[bool]] = [MLServiceCall.organization_id == organization_id]
    if filters.service is not None:
        conditions.append(MLServiceCall.service == filters.service)
    if filters.agent_id is not None:
        conditions.append(MLServiceCall.agent_id == filters.agent_id)
    if filters.channel_bot_id is not None:
        conditions.append(MLServiceCall.channel_bot_id == filters.channel_bot_id)
    if filters.surface is not None:
        conditions.append(MLServiceCall.surface == filters.surface)
    if filters.since is not None:
        conditions.append(MLServiceCall.created_at >= filters.since)
    if filters.until is not None:
        conditions.append(MLServiceCall.created_at < filters.until)
    return conditions


async def list_for(
    db: AsyncSession,
    *,
    organization_id: UUID,
    filters: CallFilters,
    skip: int,
    limit: int,
) -> list[MLServiceCall]:
    """A page of an organization's calls, newest first."""
    statement = (
        select(MLServiceCall)
        .where(*_conditions(organization_id, filters))
        .order_by(MLServiceCall.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(statement)
    return list(result.scalars().all())


async def count_for(db: AsyncSession, *, organization_id: UUID, filters: CallFilters) -> int:
    """How many calls the organization has made, for the page's total."""
    statement = (
        select(func.count())
        .select_from(MLServiceCall)
        .where(*_conditions(organization_id, filters))
    )
    result = await db.execute(statement)
    return int(result.scalar_one())


async def summarise(
    db: AsyncSession, *, organization_id: UUID, service: str, since: datetime
) -> UsageSummary:
    """An organization's successful calls to `service` since a moment, added up.

    Successful calls only: a refused one transcribed nothing, and the question
    this answers is how much was heard. The breakdowns by agent and by bot
    leave out rows with neither - the ML API's own calls, and those whose agent
    or bot has since been deleted - which the breakdown by surface still counts.
    A name is joined inside the same organization, so a row can never borrow
    another tenant's. Each breakdown is ordered longest first, then by count,
    then by name, so two reads of the same rows list them the same way.

    Seconds are the rows' own `units` added up - each recording rounded up to
    the second when it was recorded, and 0 for one with no length - rather
    than the milliseconds added and rounded once. So the summary is the sum of
    what `GET /ml/calls` lists, to the second, and a row with no length adds
    nothing either way.
    """
    scope = (
        MLServiceCall.organization_id == organization_id,
        MLServiceCall.service == service,
        MLServiceCall.status == MLCallStatus.SUCCEEDED.value,
        MLServiceCall.created_at >= since,
    )
    units = func.sum(MLServiceCall.units)
    count = func.count()

    total_seconds, total, unknown = (
        await db.execute(
            select(units, count, func.count().filter(MLServiceCall.audio_ms.is_(None))).where(
                *scope
            )
        )
    ).one()

    agents = await db.execute(
        select(Agent.id, Agent.name, units, count)
        .join(
            Agent,
            (Agent.id == MLServiceCall.agent_id) & (Agent.organization_id == organization_id),
        )
        .where(*scope)
        .group_by(Agent.id, Agent.name)
    )
    bots = await db.execute(
        select(ChannelBot.id, ChannelBot.name, units, count)
        .join(
            ChannelBot,
            (ChannelBot.id == MLServiceCall.channel_bot_id)
            & (ChannelBot.organization_id == organization_id),
        )
        .where(*scope)
        .group_by(ChannelBot.id, ChannelBot.name)
    )
    surfaces = await db.execute(
        select(MLServiceCall.surface, units, count).where(*scope).group_by(MLServiceCall.surface)
    )
    return UsageSummary(
        seconds=total_seconds or 0,
        count=total,
        count_unknown_length=unknown,
        by_agent=_ordered(
            AgentUsage(id=key, name=name, seconds=seconds or 0, count=n)
            for key, name, seconds, n in agents.all()
        ),
        by_channel=_ordered(
            AgentUsage(id=key, name=name, seconds=seconds or 0, count=n)
            for key, name, seconds, n in bots.all()
        ),
        by_surface=sorted(
            (
                SurfaceUsage(surface=surface, seconds=seconds or 0, count=n)
                for surface, seconds, n in surfaces.all()
            ),
            key=lambda group: (-group.seconds, -group.count, group.surface or ""),
        ),
    )


def _ordered(groups: Iterable[AgentUsage]) -> list[AgentUsage]:
    return sorted(groups, key=lambda group: (-group.seconds, -group.count, group.name))
