"""Call rows (#54). Writes flush, never commit; every reader is tenant-scoped
except :func:`list_unhung`, which belongs to the reaper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import extract, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.voice_call import VoiceCall, VoiceEndReason

_CHAIN_DEPTH = 20
"""A chain is one call reconnected; twenty reconnects is a loop, not a call."""


@dataclass(frozen=True)
class VoiceChain:
    """One call as Activity shows it: every connection of it, summed."""

    connections: int
    seconds: int
    cost_usd: Decimal


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    user_id: UUID | None,
    conversation_id: UUID | None,
    embed_id: UUID | None,
    surface: str,
    provider: str,
    model: str,
    transport: str,
    secret_id: UUID | None,
    worker_id: str,
    resume_of: UUID | None,
    started_at: datetime,
) -> VoiceCall:
    call = VoiceCall(
        organization_id=organization_id,
        agent_id=agent_id,
        run_id=run_id,
        user_id=user_id,
        conversation_id=conversation_id,
        embed_id=embed_id,
        surface=surface,
        provider=provider,
        model=model,
        transport=transport,
        secret_id=secret_id,
        worker_id=worker_id,
        resume_of=resume_of,
        started_at=started_at,
        heartbeat_at=started_at,
    )
    db.add(call)
    await db.flush()
    await db.refresh(call)
    return call


async def get(db: AsyncSession, call_id: UUID, *, organization_id: UUID) -> VoiceCall | None:
    result = await db.execute(
        select(VoiceCall).where(
            VoiceCall.id == call_id, VoiceCall.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def set_provider_call_id(db: AsyncSession, call_id: UUID, *, provider_call_id: str) -> None:
    await db.execute(
        update(VoiceCall).where(VoiceCall.id == call_id).values(provider_call_id=provider_call_id)
    )
    await db.flush()


async def heartbeat(
    db: AsyncSession, call_id: UUID, *, at: datetime, cost_usd: Decimal, seconds: int
) -> None:
    await db.execute(
        update(VoiceCall)
        .where(VoiceCall.id == call_id)
        .values(heartbeat_at=at, cost_usd=cost_usd, seconds=seconds)
    )
    await db.flush()


async def end(
    db: AsyncSession,
    call_id: UUID,
    *,
    at: datetime,
    reason: VoiceEndReason,
    cost_usd: Decimal,
    seconds: int,
    guardrail_hits: int,
) -> None:
    """Record our side's end.

    The first end names the time and the reason. The figures take the larger of
    what is stored and what is given: a reconnect may end a half-open connection
    from its last heartbeat while the worker holding it still runs, and that
    worker's teardown, arriving later, carries the final cost and seconds.
    """
    await db.execute(
        update(VoiceCall)
        .where(VoiceCall.id == call_id, VoiceCall.ended_at.is_(None))
        .values(ended_at=at, end_reason=reason.value)
    )
    await db.execute(
        update(VoiceCall)
        .where(VoiceCall.id == call_id)
        .values(
            heartbeat_at=func.greatest(VoiceCall.heartbeat_at, at),
            cost_usd=func.greatest(VoiceCall.cost_usd, cost_usd),
            seconds=func.greatest(VoiceCall.seconds, seconds),
            guardrail_hits=func.greatest(VoiceCall.guardrail_hits, guardrail_hits),
        )
    )
    await db.flush()


async def mark_hung_up(db: AsyncSession, call_id: UUID, *, at: datetime) -> None:
    await db.execute(update(VoiceCall).where(VoiceCall.id == call_id).values(hung_up_at=at))
    await db.flush()


async def count_open_for_user(db: AsyncSession, *, user_id: UUID, fresh_since: datetime) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(VoiceCall)
        .where(
            VoiceCall.user_id == user_id,
            VoiceCall.ended_at.is_(None),
            VoiceCall.heartbeat_at >= fresh_since,
        )
    )
    return int(result.scalar_one())


async def count_open_for_embed(db: AsyncSession, *, embed_id: UUID, fresh_since: datetime) -> int:
    """Calls still open on one embed, from every visitor together."""
    result = await db.execute(
        select(func.count())
        .select_from(VoiceCall)
        .where(
            VoiceCall.embed_id == embed_id,
            VoiceCall.ended_at.is_(None),
            VoiceCall.heartbeat_at >= fresh_since,
        )
    )
    return int(result.scalar_one())


async def seconds_since(db: AsyncSession, *, organization_id: UUID, since: datetime) -> int:
    """Call seconds this organization used since `since`: to `ended_at`, else to the last heartbeat."""
    until = func.coalesce(VoiceCall.ended_at, VoiceCall.heartbeat_at)
    result = await db.execute(
        select(func.coalesce(func.sum(extract("epoch", until - VoiceCall.started_at)), 0)).where(
            VoiceCall.organization_id == organization_id, VoiceCall.started_at >= since
        )
    )
    return int(result.scalar_one())


async def usage_by_agent(
    db: AsyncSession, *, organization_id: UUID, start: datetime, end: datetime
) -> list[tuple[UUID | None, str | None, int, int]]:
    """Per agent, most seconds first: call seconds and calls started in `[start, end)`.

    Seconds are counted like :func:`seconds_since`. A reconnect is its own row
    but not a second call, so only the first connection of a chain is counted -
    which means a reconnect inside the window whose first connection started
    before it adds its seconds and no call. Calls of a deleted agent (their
    `agent_id` cleared) come back together as one row with no id and no name,
    so the rows still add up to every call in the window.
    """
    until = func.coalesce(VoiceCall.ended_at, VoiceCall.heartbeat_at)
    seconds = func.coalesce(func.sum(extract("epoch", until - VoiceCall.started_at)), 0)
    result = await db.execute(
        select(
            VoiceCall.agent_id,
            Agent.name,
            seconds,
            func.count().filter(VoiceCall.resume_of.is_(None)),
        )
        .select_from(VoiceCall)
        .outerjoin(Agent, Agent.id == VoiceCall.agent_id)
        .where(
            VoiceCall.organization_id == organization_id,
            VoiceCall.started_at >= start,
            VoiceCall.started_at < end,
        )
        .group_by(VoiceCall.agent_id, Agent.name)
        .order_by(seconds.desc(), Agent.name.asc().nullslast())
    )
    return [(row[0], row[1], int(row[2]), int(row[3])) for row in result.all()]


async def chain_seconds(db: AsyncSession, call_id: UUID) -> int:
    """Every connection's recorded seconds up the `resume_of` chain, this one included."""
    total = 0
    current: UUID | None = call_id
    for _ in range(_CHAIN_DEPTH):
        if current is None:
            break
        row = (
            await db.execute(
                select(VoiceCall.seconds, VoiceCall.resume_of).where(VoiceCall.id == current)
            )
        ).one_or_none()
        if row is None:
            break
        total += row.seconds
        current = row.resume_of
    return total


async def is_live_run(db: AsyncSession, run_id: UUID) -> bool:
    """Whether a call is still going on this run, so its approvals are the call's to decide."""
    result = await db.execute(
        select(func.count())
        .select_from(VoiceCall)
        .where(VoiceCall.run_id == run_id, VoiceCall.ended_at.is_(None))
    )
    return int(result.scalar_one()) > 0


async def list_unhung(
    db: AsyncSession, *, stale_before: datetime, limit: int = 200
) -> list[VoiceCall]:
    """Calls the provider may still be holding: ended without a hang-up, or gone quiet.

    **Not scoped to an organization**, like `agent_run.list_stale_approvals`: its
    only caller is the reaper, a schedule with no tenant. Nothing returned here
    reaches a caller who could read it. Do not copy this shape into anything a
    route can reach.
    """
    result = await db.execute(
        select(VoiceCall)
        .where(
            VoiceCall.hung_up_at.is_(None),
            or_(VoiceCall.ended_at.is_not(None), VoiceCall.heartbeat_at < stale_before),
        )
        .order_by(VoiceCall.heartbeat_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def chains_for_runs(
    db: AsyncSession, run_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, VoiceChain]:
    """For each run that opened a call, the call it is the first connection of, summed."""
    if not run_ids:
        return {}
    roots = (
        await db.execute(
            select(VoiceCall.id, VoiceCall.run_id).where(
                VoiceCall.run_id.in_(run_ids),
                VoiceCall.organization_id == organization_id,
                VoiceCall.resume_of.is_(None),
            )
        )
    ).all()
    chains: dict[UUID, VoiceChain] = {}
    for root_id, run_id in roots:
        # Selected by `run_id IN run_ids`, so never null here.
        assert run_id is not None
        connections, seconds, cost = 0, 0, Decimal(0)
        frontier = [root_id]
        for _ in range(_CHAIN_DEPTH):
            if not frontier:
                break
            rows = (
                await db.execute(
                    select(VoiceCall.id, VoiceCall.seconds, VoiceCall.cost_usd).where(
                        VoiceCall.id.in_(frontier)
                    )
                )
            ).all()
            connections += len(rows)
            seconds += sum(row.seconds for row in rows)
            cost += sum((row.cost_usd for row in rows), Decimal(0))
            frontier = list(
                (
                    await db.execute(select(VoiceCall.id).where(VoiceCall.resume_of.in_(frontier)))
                ).scalars()
            )
        chains[run_id] = VoiceChain(connections=connections, seconds=seconds, cost_usd=cost)
    return chains
