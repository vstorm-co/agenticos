"""Agent trigger repository (PostgreSQL async)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.resource_grant import Visibility

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


async def get_by_conversation_id(db: AsyncSession, conversation_id: UUID) -> AgentTrigger | None:
    """The trigger whose run-log is this conversation, or None if it is not one.

    How a conversation read decides whether the thread is a trigger's run-log and
    whose agent's access governs it. One trigger opens and owns one log, so this
    is at most one row; the caller scopes the agent it points at to the
    conversation's own organization rather than trusting this to cross tenants.
    """
    result = await db.execute(
        select(AgentTrigger).where(AgentTrigger.conversation_id == conversation_id)
    )
    return result.scalars().first()


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


async def list_for_organization(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    see_all: bool,
    shared_ids: list[UUID],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[tuple[AgentTrigger, str]], int]:
    """Every trigger the caller may see in the organization, each with its agent's name.

    The visibility predicate is the *same* one agent listings use
    (`agent_repo.list_visible`), applied to each trigger's agent: a trigger is
    shown when the caller sees its agent - because they own it, because it is
    org-visible, or because it was shared with them (`shared_ids`, the grants
    `visible_resource_ids` returns) - or when `see_all` says the role reaches the
    whole organization. Filtering on the shared ids alone would under-include:
    the agent's own page shows a trigger on an org-visible agent, and the org-wide
    surfaces must not disagree with it. The join onto `agents` also supplies the
    name each surface shows beside a row displayed away from its agent's page.
    """
    where = [AgentTrigger.organization_id == organization_id]
    if not see_all:
        where.append(
            or_(
                Agent.owner_user_id == user_id,
                Agent.visibility == Visibility.ORG.value,
                AgentTrigger.agent_id.in_(shared_ids) if shared_ids else false(),
            )
        )
    total = (
        await db.execute(
            select(func.count())
            .select_from(AgentTrigger)
            .join(Agent, Agent.id == AgentTrigger.agent_id)
            .where(*where)
        )
    ).scalar_one()
    result = await db.execute(
        select(AgentTrigger, Agent.name)
        .join(Agent, Agent.id == AgentTrigger.agent_id)
        .where(*where)
        .order_by(AgentTrigger.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [(trigger, name) for trigger, name in result.all()], total


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    created_by_user_id: UUID | None,
    prompt: str,
    name: str | None,
    trigger_type: str,
    schedule_kind: str,
    interval_seconds: int | None,
    cron_expression: str | None,
    event_source: str | None,
    event_config: dict[str, Any],
    event_secret_encrypted: str | None,
    secret_key_version: int | None,
    environment_id: UUID | None,
    next_fire_at: datetime | None,
    connection_id: UUID | None = None,
    portal_key: str | None = None,
    delivery_mode: str | None = None,
) -> AgentTrigger:
    trigger = AgentTrigger(
        organization_id=organization_id,
        agent_id=agent_id,
        created_by_user_id=created_by_user_id,
        prompt=prompt,
        name=name,
        trigger_type=trigger_type,
        schedule_kind=schedule_kind,
        interval_seconds=interval_seconds,
        cron_expression=cron_expression,
        event_source=event_source,
        event_config=event_config,
        event_secret_encrypted=event_secret_encrypted,
        secret_key_version=secret_key_version,
        environment_id=environment_id,
        next_fire_at=next_fire_at,
        connection_id=connection_id,
        portal_key=portal_key,
        delivery_mode=delivery_mode,
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

    * `is_active` and `next_fire_at <= now` - the schedule says so. A null creator
      is deliberately *not* filtered out here: an orphaned schedule (its creator's
      user row hard-deleted, SET NULL clearing the column) can never fire, but
      excluding it from the claim was what left it sitting active-but-dead forever,
      never reaching the one place that disables it. `claim_and_advance` now claims
      it and disables it instead, so the cleanup happens rather than being filtered
      away.
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
            AgentTrigger.next_fire_at <= now,
            (AgentTrigger.last_run_id.is_(None)) | (AgentRun.status.not_in(_NON_TERMINAL_STATUSES)),
        )
        .order_by(AgentTrigger.next_fire_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True, of=AgentTrigger)
    )
    return list(result.scalars().all())
