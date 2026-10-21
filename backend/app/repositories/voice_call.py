"""Call rows (#54). Writes flush, never commit; every reader is tenant-scoped
except :func:`list_unhung` and :func:`claim_unhung`, which belong to the reaper."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, extract, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent import Agent
from app.db.models.voice_call import VoiceCall, VoiceEndReason

_CHAIN_DEPTH = 20
"""A chain is one call reconnected; twenty reconnects is a loop, not a call."""

_LONGEST_CONNECTION = timedelta(hours=2)
"""Longer than any one connection lasts - the providers end a session within the
hour, and a quiet row stops at its last heartbeat - so a call that started before
a window's start minus this cannot reach into it. Twice the hour, because a bound
too tight drops minutes from the window and one too loose only reads more rows."""


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
    resume_token_hash: str,
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
        resume_token_hash=resume_token_hash,
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


async def start_clock(db: AsyncSession, call_id: UUID, *, at: datetime) -> None:
    """Start the call's clock at `at`: its `started_at`, with its heartbeat.

    The month's minutes count from `started_at`, so it is the moment the call is
    ready - where its caller's timer, its cap and its seconds start - and, until
    then, it moves with each beat of the setup: no path counts setup as call time.
    """
    await db.execute(
        update(VoiceCall).where(VoiceCall.id == call_id).values(started_at=at, heartbeat_at=at)
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
    """Record the provider's hang-up. The first stamp stands: the resume window runs
    from it, and a later teardown or sweep hanging the same call up again must not
    move that window's start."""
    await db.execute(
        update(VoiceCall)
        .where(VoiceCall.id == call_id, VoiceCall.hung_up_at.is_(None))
        .values(hung_up_at=at)
    )
    await db.flush()


async def has_open_successor(db: AsyncSession, call_id: UUID) -> bool:
    """Whether a connection that resumed `call_id` is still open.

    A reconnect continues a call once: a second one while the first is open is the
    same call twice. One that ended - failed before it was ready, say - leaves the
    call free to be resumed again within its window.
    """
    result = await db.execute(
        select(exists().where(VoiceCall.resume_of == call_id, VoiceCall.ended_at.is_(None)))
    )
    return bool(result.scalar())


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


async def usage_by_agent(
    db: AsyncSession, *, organization_id: UUID, start: datetime, end: datetime
) -> list[tuple[UUID | None, str | None, int, int]]:
    """Per agent, most seconds first: call seconds in `[start, end)`, and calls started in it.

    Seconds run to `ended_at`, else to the last heartbeat, clipped to the window
    at both ends: a call running across the month's turn counts its part in each
    month. A reconnect is
    its own row but not a second call, and a call is counted where its first
    connection started. Calls of a deleted agent (their `agent_id` cleared) come
    back together as one row with no id and no name, so the rows still add up to
    every call in the window.
    """
    until = func.coalesce(VoiceCall.ended_at, VoiceCall.heartbeat_at)
    inside = func.least(until, end) - func.greatest(VoiceCall.started_at, start)
    seconds = func.coalesce(func.sum(extract("epoch", inside)), 0)
    result = await db.execute(
        select(
            VoiceCall.agent_id,
            Agent.name,
            seconds,
            func.count().filter(VoiceCall.resume_of.is_(None), VoiceCall.started_at >= start),
        )
        .select_from(VoiceCall)
        .outerjoin(Agent, Agent.id == VoiceCall.agent_id)
        .where(
            VoiceCall.organization_id == organization_id,
            until > start,
            VoiceCall.started_at < end,
            VoiceCall.started_at > start - _LONGEST_CONNECTION,
        )
        .group_by(VoiceCall.agent_id, Agent.name)
        .order_by(seconds.desc(), Agent.name.asc().nullslast())
    )
    return [(row[0], row[1], int(row[2]), int(row[3])) for row in result.all()]


async def chain_seconds(db: AsyncSession, call_id: UUID) -> int | None:
    """Every connection's recorded seconds up the `resume_of` chain, this one included.

    `None` once the chain holds `_CHAIN_DEPTH` connections, so it is not resumed
    again: a sum stopped at the bound would leave the oldest connections' time
    out and hand it back to the reconnect, and Activity (`chains_for_runs`)
    counts no connection past it.

    A connection taken over from another worker was closed at its last heartbeat,
    up to a beat before the provider hung it up; it counts to the hang-up, or
    each hop would hand that beat back to the call's cap.
    """
    hung = extract("epoch", VoiceCall.hung_up_at - VoiceCall.started_at)
    seconds = func.greatest(VoiceCall.seconds, func.coalesce(func.floor(hung), 0))
    total = 0
    current: UUID | None = call_id
    for _ in range(_CHAIN_DEPTH - 1):
        row = (
            await db.execute(
                select(seconds.label("seconds"), VoiceCall.resume_of).where(VoiceCall.id == current)
            )
        ).one_or_none()
        if row is None:
            return total
        total += int(row.seconds)
        current = row.resume_of
        if current is None:
            return total
    return None


async def is_live_run(db: AsyncSession, run_id: UUID) -> bool:
    """Whether a call is still going on this run, so its approvals are the call's to decide."""
    result = await db.execute(
        select(func.count())
        .select_from(VoiceCall)
        .where(VoiceCall.run_id == run_id, VoiceCall.ended_at.is_(None))
    )
    return int(result.scalar_one()) > 0


def _unhung(stale_before: datetime) -> ColumnElement[bool]:
    """Not hung up, and quiet since `stale_before`.

    An ended row qualifies the same way: `end` moves the heartbeat up to the end,
    so a teardown still hanging up after recording its end gets the same grace as
    a live call, and the sweep does not close a run its teardown is finishing.
    """
    return and_(VoiceCall.hung_up_at.is_(None), VoiceCall.heartbeat_at < stale_before)


async def list_unhung(
    db: AsyncSession, *, stale_before: datetime, limit: int = 200
) -> list[VoiceCall]:
    """Calls the provider may still be holding: gone quiet, or ended without a hang-up.

    **Not scoped to an organization**, like `agent_run.list_stale_approvals`: its
    only caller is the reaper, a schedule with no tenant. Nothing returned here
    reaches a caller who could read it. Do not copy this shape into anything a
    route can reach. A listing, not a claim: the reaper claims each row in a
    transaction of its own (:func:`claim_unhung`).
    """
    result = await db.execute(
        select(VoiceCall)
        .where(_unhung(stale_before))
        .order_by(VoiceCall.heartbeat_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def claim_unhung(
    db: AsyncSession, call_id: UUID, *, stale_before: datetime
) -> VoiceCall | None:
    """Lock one row :func:`list_unhung` found, if it still qualifies.

    `None` when it no longer does (hung up or heartbeated since), or when another
    sweep holds it: `SKIP LOCKED`, so a start-up sweep and the scheduled one never
    hang up the same call twice or wait on each other's provider calls. Unscoped
    for the reason :func:`list_unhung` is.
    """
    result = await db.execute(
        select(VoiceCall)
        .where(VoiceCall.id == call_id, _unhung(stale_before))
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def chains_for_runs(
    db: AsyncSession, run_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, VoiceChain]:
    """For each run that opened a call, the call it is the first connection of, summed.

    One recursive query for the whole page, down the `resume_of` links to
    `_CHAIN_DEPTH` connections, rather than a round trip per hop per call. Its
    caller (`voice_chains`) does not ask for a page with no calls on it.
    """
    chain = (
        select(
            VoiceCall.run_id.label("root_run_id"),
            VoiceCall.id,
            VoiceCall.seconds,
            VoiceCall.cost_usd,
            literal(1).label("depth"),
        )
        .where(
            VoiceCall.run_id.in_(run_ids),
            VoiceCall.organization_id == organization_id,
            VoiceCall.resume_of.is_(None),
        )
        .cte("voice_chain", recursive=True)
    )
    hop = aliased(VoiceCall)
    chain = chain.union_all(
        select(chain.c.root_run_id, hop.id, hop.seconds, hop.cost_usd, chain.c.depth + 1)
        .join(chain, hop.resume_of == chain.c.id)
        .where(hop.organization_id == organization_id, chain.c.depth < _CHAIN_DEPTH)
    )
    rows = await db.execute(
        select(
            chain.c.root_run_id,
            func.count(),
            func.sum(chain.c.seconds),
            func.sum(chain.c.cost_usd),
        ).group_by(chain.c.root_run_id)
    )
    return {
        run_id: VoiceChain(connections=int(connections), seconds=int(seconds), cost_usd=cost)
        for run_id, connections, seconds, cost in rows.all()
    }
