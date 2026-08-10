"""Agent trigger repository (PostgreSQL async)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger

# A run in one of these has not finished, so its trigger must not fire again on
# top of it. Every other status is terminal - the run settled, one way or another.
_NON_TERMINAL_STATUSES = (RunStatus.RUNNING.value, RunStatus.AWAITING_APPROVAL.value)


async def get(db: AsyncSession, trigger_id: UUID, *, organization_id: UUID) -> AgentTrigger | None:
    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, trigger_id: UUID) -> AgentTrigger | None:
    """The trigger by id alone, for the worker: a flow has an id and no tenant.

    Not organization-scoped, because a scheduled flow is dispatched with a
    trigger id and there is no ambient tenant in a worker - the organization is
    read off the row this returns, and every later query is scoped by it.
    """
    result = await db.execute(select(AgentTrigger).where(AgentTrigger.id == trigger_id))
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID
) -> list[AgentTrigger]:
    result = await db.execute(
        select(AgentTrigger)
        .where(
            AgentTrigger.agent_id == agent_id,
            AgentTrigger.organization_id == organization_id,
        )
        .order_by(AgentTrigger.created_at.asc())
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    created_by_user_id: UUID | None,
    prompt: str,
    schedule_kind: str,
    interval_seconds: int | None,
    cron_expression: str | None,
    environment_id: UUID | None,
    next_fire_at: datetime,
) -> AgentTrigger:
    trigger = AgentTrigger(
        organization_id=organization_id,
        agent_id=agent_id,
        created_by_user_id=created_by_user_id,
        prompt=prompt,
        schedule_kind=schedule_kind,
        interval_seconds=interval_seconds,
        cron_expression=cron_expression,
        environment_id=environment_id,
        next_fire_at=next_fire_at,
    )
    db.add(trigger)
    await db.flush()
    await db.refresh(trigger)
    return trigger


async def update(
    db: AsyncSession, *, trigger: AgentTrigger, update_data: dict[str, Any]
) -> AgentTrigger:
    """Apply the fields a caller actually sent.

    Takes a dict rather than named arguments so "not sent" stays distinguishable
    from "cleared to null" - pausing a schedule must not silently move it back to
    the default environment.
    """
    for field_name, value in update_data.items():
        setattr(trigger, field_name, value)
    await db.flush()
    await db.refresh(trigger)
    return trigger


async def delete(db: AsyncSession, trigger: AgentTrigger) -> None:
    await db.delete(trigger)
    await db.flush()


async def claim_due(db: AsyncSession, *, now: datetime, limit: int = 100) -> list[AgentTrigger]:
    """The triggers due to fire, locked so a second heartbeat takes none of them.

    `FOR UPDATE SKIP LOCKED` is the whole of the no-double-fire guard: two
    concurrent heartbeats each take a disjoint set of rows rather than both
    seeing one due trigger. `of=AgentTrigger` keeps the lock off the joined
    `agent_runs` row, which this only reads.

    Two filters decide "due":

    * `is_active`, a non-null creator, and `next_fire_at <= now` - the schedule
      says so and it is still attributable to someone.
    * the previous run, reached through `last_run_id`, has reached a terminal
      status (or there is none). This is the no-overlap guard: a run that outlives
      its own interval must finish before the next fire, or a slow agent would be
      firing on top of itself. The caller advances `next_fire_at` under the same
      transaction, so the common case never reaches this join.
    """
    result = await db.execute(
        select(AgentTrigger)
        .outerjoin(AgentRun, AgentRun.id == AgentTrigger.last_run_id)
        .where(
            AgentTrigger.is_active.is_(True),
            AgentTrigger.created_by_user_id.is_not(None),
            AgentTrigger.next_fire_at <= now,
            (AgentTrigger.last_run_id.is_(None)) | (AgentRun.status.not_in(_NON_TERMINAL_STATUSES)),
        )
        .order_by(AgentTrigger.next_fire_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True, of=AgentTrigger)
    )
    return list(result.scalars().all())
