"""Agent trigger repository (PostgreSQL async)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger, TriggerAttempt, TriggerOverlap
from app.db.models.resource_grant import Visibility
from app.schemas.agent_trigger import (
    TriggerAttemptReason,
    TriggerAttemptStage,
    TriggerAttemptStatus,
)

# A run in one of these has not finished, so its trigger must not fire again on
# top of it. Every other status is terminal - the run settled, one way or another.
_NON_TERMINAL_STATUSES = (
    RunStatus.RUNNING.value,
    RunStatus.AWAITING_APPROVAL.value,
    RunStatus.AWAITING_ANSWER.value,
)

# How long a `fire_in_flight_since` marker holds a trigger out of the claim. A run
# settles in seconds to minutes; past this lease the fired flow is assumed dead - a
# worker crash that skipped its `finally` - and the schedule is freed rather than
# parked for ever.
FIRE_LEASE = timedelta(hours=1)


async def get(
    db: AsyncSession, trigger_id: UUID, *, organization_id: UUID, for_update: bool = False
) -> AgentTrigger | None:
    statement = select(AgentTrigger).where(
        AgentTrigger.id == trigger_id, AgentTrigger.organization_id == organization_id
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def get_by_id(
    db: AsyncSession, trigger_id: UUID, *, fresh: bool = False, for_update: bool = False
) -> AgentTrigger | None:
    """The trigger by id alone, for the worker: a flow has an id and no tenant.

    Not organization-scoped, because a scheduled flow is dispatched with a
    trigger id and there is no ambient tenant in a worker - the organization is
    read off the row this returns, and every later query is scoped by it.
    """
    query = (
        select(AgentTrigger)
        .where(AgentTrigger.id == trigger_id)
        .execution_options(populate_existing=fresh)
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
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


async def list_for_project(
    db: AsyncSession, *, project_id: UUID, organization_id: UUID
) -> list[AgentTrigger]:
    """Project routines before their foreign-key cascade removes webhook receipts."""
    result = await db.scalars(
        select(AgentTrigger)
        .where(
            AgentTrigger.project_id == project_id, AgentTrigger.organization_id == organization_id
        )
        .order_by(AgentTrigger.created_at, AgentTrigger.id)
    )
    return list(result.all())


async def list_for_connection(
    db: AsyncSession, *, connection_id: UUID, organization_id: UUID
) -> list[AgentTrigger]:
    """The triggers whose webhooks were registered through this connected account.

    For the sweep that runs before the connection is deleted: its FK is
    `ON DELETE SET NULL`, but the shape CHECK refuses a registered hook with no
    connection - deliberately, since such a hook could never be deregistered - so
    the rows must shed their hooks first or the delete fails at flush.
    """
    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.connection_id == connection_id,
            AgentTrigger.organization_id == organization_id,
        )
    )
    return list(result.scalars().all())


async def list_active_for_event_source(
    db: AsyncSession, *, organization_id: UUID, event_source: str
) -> list[AgentTrigger]:
    """The organization's live event triggers on one source, for a polled delivery.

    A webhook delivery names its trigger in the URL; a poll names a *mailbox*, so
    one read can match several triggers - "any message" and "marked important" on
    the same account is the shape the presets invite. Scoped to the organization
    whose grant was polled, because that grant is what authorized reading the
    account at all.

    Ordered by creation so two workers that somehow poll the same grant fire in the
    same order, which is what makes the dedupe claim's winner deterministic.
    """
    result = await db.execute(
        select(AgentTrigger)
        .where(
            AgentTrigger.organization_id == organization_id,
            AgentTrigger.trigger_type == "event",
            AgentTrigger.event_source == event_source,
            AgentTrigger.is_active.is_(True),
        )
        .order_by(AgentTrigger.created_at.asc())
    )
    return list(result.scalars().all())


async def prompts_created_by(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[str]:
    """The prompts of the routines one person set up here - what not to propose to them again."""
    result = await db.execute(
        select(AgentTrigger.prompt).where(
            AgentTrigger.organization_id == organization_id,
            AgentTrigger.created_by_user_id == user_id,
        )
    )
    return list(result.scalars().all())


class RoutinePrompt(NamedTuple):
    prompt: str
    spec: dict[str, object]


async def routine_prompts_for_screening(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[RoutinePrompt]:
    """Prompts with the immutable spec they would fire; unresolved targets are omitted.

    A named environment must resolve, rather than falling back to a different
    agent version. A routine whose latest fire was refused stays out even if
    the current input screen would now accept its prompt. Once retention removes
    the last run, a fire timestamp still distinguishes an unknown verdict from
    a routine that has never fired; an unknown verdict is left out too.
    """
    target = func.coalesce(
        AgentTrigger.pinned_version_id,
        AgentEnvironment.version_id,
        Agent.current_version_id,
    )
    rows = await db.execute(
        select(AgentTrigger.prompt, AgentVersion.spec)
        .join(
            Agent, and_(Agent.id == AgentTrigger.agent_id, Agent.organization_id == organization_id)
        )
        .outerjoin(
            AgentEnvironment,
            and_(
                AgentEnvironment.id == AgentTrigger.environment_id,
                AgentEnvironment.agent_id == Agent.id,
                AgentEnvironment.organization_id == organization_id,
            ),
        )
        .join(AgentVersion, and_(AgentVersion.id == target, AgentVersion.agent_id == Agent.id))
        .outerjoin(AgentRun, AgentRun.id == AgentTrigger.last_run_id)
        .where(
            AgentTrigger.organization_id == organization_id,
            AgentTrigger.created_by_user_id == user_id,
            or_(AgentTrigger.environment_id.is_(None), AgentEnvironment.id.is_not(None)),
            or_(AgentRun.id.is_not(None), AgentTrigger.last_fired_at.is_(None)),
            or_(AgentRun.id.is_(None), AgentRun.status != RunStatus.GUARDRAIL_BLOCKED.value),
        )
    )
    return [RoutinePrompt(row.prompt, row.spec) for row in rows.all()]


async def list_for_organization(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    see_all: bool,
    shared_ids: list[UUID],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[tuple[AgentTrigger, Agent]], int]:
    """Every trigger the caller may see in the organization, each with its agent.

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
    where = [AgentTrigger.organization_id == organization_id, AgentTrigger.one_shot.is_(False)]
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
        select(AgentTrigger, Agent)
        .join(Agent, Agent.id == AgentTrigger.agent_id)
        .where(*where)
        .order_by(AgentTrigger.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [(trigger, agent) for trigger, agent in result.all()], total


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
    runs_as_creator: bool = False,
    local_target: dict[str, Any] | None = None,
    overlap: str = TriggerOverlap.SKIP.value,
    teams_conversation_id: UUID | None = None,
    time_zone: str | None = None,
    result_mode: str = "report",
    answer_to: str = "run_log",
    delivery_conversation_id: UUID | None = None,
    ends_at: datetime | None = None,
    max_failures: int | None = 3,
    notification_channels: Sequence[str] | None = None,
    monthly_budget_usd: Decimal | None = None,
    pinned_version_id: UUID | None = None,
    one_shot: bool = False,
    is_active: bool = True,
    project_id: UUID | None = None,
) -> AgentTrigger:
    trigger = AgentTrigger(
        project_id=project_id,
        one_shot=one_shot,
        is_active=is_active,
        max_failures=max_failures,
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
        pinned_version_id=pinned_version_id,
        next_fire_at=next_fire_at,
        connection_id=connection_id,
        portal_key=portal_key,
        delivery_mode=delivery_mode,
        runs_as_creator=runs_as_creator,
        local_target=local_target,
        overlap=overlap,
        teams_conversation_id=teams_conversation_id,
        time_zone=time_zone,
        result_mode=result_mode,
        answer_to=answer_to,
        delivery_conversation_id=delivery_conversation_id,
        ends_at=ends_at,
        notification_channels=None
        if notification_channels is None
        else list(notification_channels),
        monthly_budget_usd=monthly_budget_usd,
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


async def renew_fire_marker(
    db: AsyncSession, *, trigger_id: UUID, claimed_at: datetime, renewed_at: datetime
) -> bool:
    """Move the in-flight marker forward, but only while it is still this claim's.

    How a fire longer than `FIRE_LEASE` keeps its trigger claimed: the lease is
    sized for a run that died, and only the running fire can tell the difference,
    so it re-stamps the marker on an interval well inside the lease. Conditional
    exactly like :func:`clear_fire_marker`, and for the same reason - a renewal
    racing a heartbeat that already re-claimed must lose, not overwrite. `False`
    says the marker is no longer this fire's to renew (re-claimed, cleared, or the
    trigger deleted); the caller stops touching it.
    """
    result = await db.execute(
        sql_update(AgentTrigger)
        .where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.fire_in_flight_since == claimed_at,
        )
        .values(fire_in_flight_since=renewed_at)
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns `CursorResult`, which does (`resource_grant`
    # documents the same suppression).
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def clear_fire_marker(db: AsyncSession, *, trigger_id: UUID, claimed_at: datetime) -> None:
    """Free the in-flight marker, but only while it is still this claim's own.

    A conditional UPDATE rather than a read-compare-assign on the loaded row: the
    row was loaded when the fire began, and a fire that outran `FIRE_LEASE` may
    since have had its trigger re-claimed by a heartbeat that committed a *newer*
    `fire_in_flight_since`. Comparing against the session's cached value and
    assigning `None` would clear that newer claim's marker and reopen the trigger
    under a fire still in flight; the `WHERE` here re-evaluates against the
    committed row, so a stale ticket simply matches nothing.
    """
    await db.execute(
        sql_update(AgentTrigger)
        .where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.fire_in_flight_since == claimed_at,
        )
        .values(fire_in_flight_since=None)
    )
    await db.flush()


async def claim_due(
    db: AsyncSession, *, now: datetime, limit: int = 100
) -> list[tuple[AgentTrigger, bool]]:
    """The triggers due to fire, each with whether its previous fire is still busy.

    Locked so a second heartbeat takes none of them.

    `FOR UPDATE SKIP LOCKED` is the whole of the no-double-fire guard: two
    concurrent heartbeats each take a disjoint set of rows rather than both
    seeing one due trigger. `of=AgentTrigger` keeps the lock off the joined
    `agent_runs` row, which this only reads.

    Two filters decide "due", and three more decide "busy" - a busy trigger is
    claimed all the same unless its `overlap` is `queue`, since `skip` must
    still advance past the occurrence and `allow` fires over it (#2219):

    * `is_active` and `next_fire_at <= now` - the schedule says so. A null creator
      is deliberately *not* filtered out here: an orphaned schedule (its creator's
      user row hard-deleted, SET NULL clearing the column) can never fire, but
      excluding it from the claim was what left it sitting active-but-dead forever,
      never reaching the one place that disables it. `claim_and_advance` now claims
      it and disables it instead, so the cleanup happens rather than being filtered
      away.

    Busy is any of:

    * a fire is in flight: `fire_in_flight_since` is set and younger than
      `FIRE_LEASE`. The claim sets this marker in the same UPDATE that advances
      `next_fire_at`, and the fired run clears it in a `finally` - so a run slower
      than its interval is not fired on top of itself, and a run that died without
      clearing un-wedges once the lease lapses. This is the guard `last_run_id`
      cannot be: `last_run_id` is written only when `execute` returns, so it names
      the previous run for the whole time the current one executes.
    * the previous run, reached through `last_run_id`, has not reached a
      terminal status. This still bites after the marker clears: a run
      that parks `AWAITING_APPROVAL` returns from `execute` (clearing the marker)
      yet is not terminal, so it keeps the schedule from piling runs behind an
      undecided gate. The caller advances `next_fire_at` under the same
      transaction, so the common case never reaches this join.
    * a non-terminal top-level run sits in the trigger's own run-log
      conversation. The `last_run_id` join is a fast, indexed check on the *linked*
      previous run, but the link and the run are written in two steps: `_run`
      commits its row, and only then does `fire` stamp `last_run_id` against it. A
      worker that dies between those leaves a durable run the schedule must still
      wait behind, with `last_run_id` still naming the previous terminal run - so
      once the lease lapses the join alone would reclaim the trigger and fire over
      it. This `EXISTS` reconciles the conversation directly, catching an
      in-flight run whether or not it was ever linked. Top-level only
      (`parent_run_id IS NULL`): a delegated child shares the conversation but is
      not the fire.

      `running` earns the block as much as `awaiting_approval` does, and for a
      reason the lease cannot cover: a run's row is committed `running` before
      its model is called (#12), so a *concurrent* `run_now` or event fire -
      which takes no lease - is visible here for its whole life, and a schedule
      that ignored it would run the same agent twice into one run log, paying
      for both. What keeps a *crashed* run's durable `running` row from wedging
      the schedule for ever is not this predicate but the stale-run sweep,
      which ends such a row `failed` within its ceiling
      (`app/services/run_reaper.py`); until it does, waiting behind a row that
      claims to be running is the safe reading of it.
    """
    in_flight = aliased(AgentRun)
    has_run_in_flight = (
        select(in_flight.id)
        .where(
            in_flight.conversation_id == AgentTrigger.conversation_id,
            in_flight.parent_run_id.is_(None),
            in_flight.status.in_(_NON_TERMINAL_STATUSES),
        )
        .correlate(AgentTrigger)
        .exists()
    )
    # Written as the negation of "free" so a dangling `last_run_id`, whose
    # joined status is NULL, reads as busy - the safe reading - rather than NULL.
    free = and_(
        (AgentTrigger.last_run_id.is_(None)) | (AgentRun.status.not_in(_NON_TERMINAL_STATUSES)),
        ~has_run_in_flight,
        (AgentTrigger.fire_in_flight_since.is_(None))
        | (AgentTrigger.fire_in_flight_since <= now - FIRE_LEASE),
    )
    busy = func.coalesce(~free, true())
    result = await db.execute(
        select(AgentTrigger, busy)
        .outerjoin(AgentRun, AgentRun.id == AgentTrigger.last_run_id)
        .where(
            AgentTrigger.is_active.is_(True),
            AgentTrigger.next_fire_at <= now,
            AgentTrigger.waiting_device_count == 0,
            (AgentTrigger.overlap != TriggerOverlap.QUEUE.value) | ~busy,
        )
        .order_by(AgentTrigger.next_fire_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True, of=AgentTrigger)
    )
    return [(trigger, bool(is_busy)) for trigger, is_busy in result.tuples().all()]


async def withdraw_creator_consent(
    db: AsyncSession, *, agent_id: UUID, kept_for: UUID | None
) -> int:
    """Switch "run as me" off on an agent's triggers, except those `kept_for` made.

    Returns how many triggers lost it.
    """
    result = await db.execute(
        sql_update(AgentTrigger)
        .where(
            AgentTrigger.agent_id == agent_id,
            AgentTrigger.runs_as_creator.is_(True),
            AgentTrigger.pinned_version_id.is_(None),
            AgentTrigger.created_by_user_id.is_distinct_from(kept_for),
        )
        .values(runs_as_creator=False)
    )
    await db.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def claim_ended(db: AsyncSession, *, now: datetime, limit: int) -> list[AgentTrigger]:
    """Claim unfinished deadline cleanup independently of activation cadence and pause."""
    result = await db.scalars(
        select(AgentTrigger)
        .where(
            AgentTrigger.ends_at <= now,
            or_(
                AgentTrigger.is_active.is_(True),
                AgentTrigger.end_settled_at.is_distinct_from(AgentTrigger.ends_at),
            ),
        )
        .order_by(AgentTrigger.ends_at, AgentTrigger.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(result.all())


async def revoke_member_authority(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> None:
    """A later invitation must not revive this membership's unattended consents."""
    await db.execute(
        sql_update(AgentTrigger)
        .where(
            AgentTrigger.organization_id == organization_id,
            AgentTrigger.created_by_user_id == user_id,
        )
        .values(is_active=False, approved_sources=None, action_consents=[])
    )
    await db.flush()


async def record_attempt(
    db: AsyncSession,
    *,
    trigger_id: UUID,
    organization_id: UUID,
    activation_id: UUID,
    status: TriggerAttemptStatus,
    stage: TriggerAttemptStage,
    reason: TriggerAttemptReason,
) -> TriggerAttempt:
    """An activation's first refusal wins, including across duplicate job delivery."""
    statement = (
        insert(TriggerAttempt)
        .values(
            trigger_id=trigger_id,
            organization_id=organization_id,
            activation_id=activation_id,
            status=status,
            stage=stage,
            reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["trigger_id", "activation_id"])
    )
    await db.execute(statement)
    await db.flush()
    found = await attempt_for_activation(
        db, trigger_id=trigger_id, organization_id=organization_id, activation_id=activation_id
    )
    assert found is not None, "an inserted or duplicate activation has an attempt"
    return found


async def attempt_for_activation(
    db: AsyncSession, *, trigger_id: UUID, organization_id: UUID, activation_id: UUID
) -> TriggerAttempt | None:
    return await db.scalar(
        select(TriggerAttempt).where(
            TriggerAttempt.trigger_id == trigger_id,
            TriggerAttempt.organization_id == organization_id,
            TriggerAttempt.activation_id == activation_id,
        )
    )


async def list_attempts(
    db: AsyncSession, *, trigger_id: UUID, organization_id: UUID, skip: int, limit: int
) -> tuple[list[TriggerAttempt], int]:
    filters = (
        TriggerAttempt.trigger_id == trigger_id,
        TriggerAttempt.organization_id == organization_id,
    )
    rows = await db.scalars(
        select(TriggerAttempt)
        .where(*filters)
        .order_by(TriggerAttempt.occurred_at.desc(), TriggerAttempt.id.desc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count()).select_from(TriggerAttempt).where(*filters))
    return list(rows), int(total or 0)
