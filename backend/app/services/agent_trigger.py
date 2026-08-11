"""Scheduling an agent to run itself - the service behind agent triggers.

A trigger fires an agent on a schedule, with nobody at the keyboard. Everything
about *what* a run is - its budget, its approvals, its accounting - is unchanged,
because a fired run goes through the same
:meth:`app.services.agent_runner.AgentRunnerService.execute` every other surface
does. This service owns the two halves the runner does not: deciding a trigger is
due without two heartbeats firing it twice, and deciding whom a fired run runs as.

Who may manage a trigger is `agents:run` **on that agent**, resolved per-resource
through :class:`app.services.agent_registry.AgentRegistryService` - the same grant
-aware check the run path itself makes, not a role gate. Creating a schedule is
asserting "run this agent, repeatedly, as me", so the floor is exactly the
permission to run it once.

Whom a fired run runs *as* is the trigger's creator, re-resolved every fire, the
way a channel mention runs as its sender and an embed widget as its owner. There
is no invented service user: a run nobody can be held to is the thing
:class:`app.core.permissions.AuthContext` refuses to mint. When the creator can no
longer run the agent - they left the organization, or their grant on it was
revoked - the trigger auto-disables and an audit entry records why, rather than
retrying a refusal for ever.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from croniter import croniter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import RunSurface
from app.db.models.agent_trigger import AgentTrigger, ScheduleKind
from app.repositories import (
    agent_environment_repo,
    agent_trigger_repo,
    conversation_repo,
    member_repo,
)
from app.schemas.agent_trigger import TriggerCreate, TriggerUpdate
from app.services.agent_registry import AgentRegistryService

logger = logging.getLogger(__name__)


def _cron_next(expression: str, *, now: datetime) -> datetime:
    """The first instant a cron expression matches strictly after `now`.

    Evaluated in UTC: `now` is tz-aware UTC and croniter carries that tzinfo
    through, so `0 9 * * *` fires at 09:00 UTC. The expression is validated when
    the trigger is created (:class:`app.schemas.agent_trigger.TriggerCreate`), so
    one read back off a row parses here.
    """
    # croniter ships no type information; the cast is what annotates the result.
    return cast(datetime, croniter(expression, now).get_next(datetime))


def _next_fire(
    *, schedule_kind: str, interval_seconds: int | None, cron_expression: str | None, now: datetime
) -> datetime:
    """When a schedule with these fields should next fire, measured from `now`.

    Both kinds answer "the next time strictly after now", never a burst of
    catch-up runs a worker owes nobody after being down: an interval is
    `now + interval` rather than `last_fire + interval`, and cron takes the
    next matching instant, not every one it missed. The database CHECK
    (`ck_trigger_schedule_shape`) and the create-time schema both guarantee the
    kind's own field is present, so the casts cannot be reached with a null - a
    guard here would be an untestable branch under the 100% gate.
    """
    if schedule_kind == ScheduleKind.CRON.value:
        return _cron_next(cast(str, cron_expression), now=now)
    return now + timedelta(seconds=cast(int, interval_seconds))


def _next_fire_from(trigger: AgentTrigger, *, now: datetime) -> datetime:
    """When this trigger should next fire, measured from `now` - either kind."""
    return _next_fire(
        schedule_kind=trigger.schedule_kind,
        interval_seconds=trigger.interval_seconds,
        cron_expression=trigger.cron_expression,
        now=now,
    )


def _update_action(changes: dict[str, Any]) -> str:
    """What to call this edit in the trail - pause and resume get their own names."""
    if changes.get("is_active") is True:
        return "agent.trigger_resumed"
    if changes.get("is_active") is False:
        return "agent.trigger_paused"
    return "agent.trigger_updated"


class AgentTriggerService:
    """Manage and fire an organization's agent triggers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[AgentTrigger]:
        """Every schedule on this agent.

        Requires only `agents:view` (the registry's default): seeing when an agent
        runs itself is part of understanding what it is.
        """
        agent = await self.agents.get(ctx, agent_id)
        return await agent_trigger_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )

    async def create(self, ctx: AuthContext, agent_id: UUID, data: TriggerCreate) -> AgentTrigger:
        """Schedule the agent to run itself, on an interval or a cron expression.

        Raises:
            NotFoundError: If the agent is not runnable by this caller. Reported
                as missing, not forbidden, so agent ids stay unprobeable - the
                rule every per-resource agent route follows.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        if data.environment_id is not None:
            await self._environment_of(ctx, agent.id, data.environment_id)

        now = datetime.now(UTC)
        trigger = await agent_trigger_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            created_by_user_id=ctx.subject_id,
            prompt=data.prompt,
            schedule_kind=data.schedule_kind,
            interval_seconds=data.interval_seconds,
            cron_expression=data.cron_expression,
            environment_id=data.environment_id,
            # The schedule's next occurrence, never immediate: creating a schedule
            # is not a request to run right now, and an immediate fire would make a
            # mistyped trigger spend before it could be deleted.
            next_fire_at=_next_fire(
                schedule_kind=data.schedule_kind,
                interval_seconds=data.interval_seconds,
                cron_expression=data.cron_expression,
                now=now,
            ),
        )
        # Open the run-log conversation now, not on the first fire, so a new
        # schedule is a clickable item in the sidebar the moment it exists - empty
        # until a fire appends to it. `_run_log` stays the idempotent fallback for
        # a conversation later deleted, whose SET NULL reopens a fresh one.
        await self._run_log(trigger, agent_name=agent.name)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.trigger_created",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "trigger_id": str(trigger.id),
                "schedule_kind": trigger.schedule_kind,
                "interval_seconds": trigger.interval_seconds,
                "cron_expression": trigger.cron_expression,
            },
        )
        return trigger

    async def update(
        self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID, data: TriggerUpdate
    ) -> AgentTrigger:
        """Pause, resume, retime, repoint, or reword a schedule.

        Only the fields the caller actually sent are applied, so pausing a trigger
        cannot silently move it back to the default environment.
        """
        trigger = await self._owned(ctx, agent_id, trigger_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("environment_id") is not None:
            await self._environment_of(ctx, agent_id, changes["environment_id"])
        updated = await agent_trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=_update_action(changes),
            target_type="agent",
            target_id=str(agent_id),
            details={"trigger_id": str(trigger.id), "changes": changes},
        )
        return updated

    async def delete(self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID) -> None:
        """Remove a schedule entirely - the agent stops running itself."""
        trigger = await self._owned(ctx, agent_id, trigger_id)
        await agent_trigger_repo.delete(self.db, trigger)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.trigger_deleted",
            target_type="agent",
            target_id=str(agent_id),
            details={"trigger_id": str(trigger_id)},
        )

    async def claim_and_advance(self, *, now: datetime, limit: int = 100) -> list[AgentTrigger]:
        """Claim the triggers due now, advancing each so no later tick re-fires it.

        The claim locks each row `FOR UPDATE SKIP LOCKED`, and advancing
        `next_fire_at` happens under that same lock, so two heartbeats running at
        once take disjoint work and neither leaves a due row behind for the other.
        The worker calls this with no auth context - it is a system sweep, and the
        organization each fired run belongs to is read off its own row.
        """
        triggers = await agent_trigger_repo.claim_due(self.db, now=now, limit=limit)
        for trigger in triggers:
            trigger.next_fire_at = _next_fire_from(trigger, now=now)
            trigger.last_fired_at = now
        await self.db.flush()
        return triggers

    async def fire(self, trigger_id: UUID) -> None:
        """Run the agent this trigger schedules, as the member who created it.

        Called by the worker with a bare id, so it re-loads everything and trusts
        nothing from the claim: a trigger deleted or disabled between claim and
        fire simply does nothing. The run goes through `AgentRunnerService.execute`,
        so a budget it cannot afford ends the run `BUDGET_EXCEEDED` and returns
        here normally - never raising, so the flow is not retried into spending
        the same organization's money again.

        A refusal from the authorization layer is treated the same way, but with a
        different cause: it means the creator can no longer run this agent, so the
        trigger is disabled rather than retried (the "silently retried refusal"
        #44 guards against, reached through the authz door instead of the budget
        one).
        """
        trigger = await agent_trigger_repo.get_by_id(self.db, trigger_id)
        if trigger is None or not trigger.is_active:
            logger.info("trigger_fire_skipped", extra={"trigger_id": str(trigger_id)})
            return

        ctx = await self._creator_context(trigger)
        if ctx is None:
            # No membership to take a role from - the creator left the
            # organization, or the user row itself is gone and SET NULL cleared
            # the column. Either way the schedule is no longer attributable.
            await self._disable(trigger, reason="creator_not_a_member")
            return

        try:
            agent = await self.agents.get(ctx, trigger.agent_id, perm=Perm.AGENTS_RUN)
        except (NotFoundError, AuthorizationError):
            # The grants-aware pre-check, mirroring the run path's own
            # `resolve_access`. A creator who kept a role with `agents:run` but
            # lost the grant on *this* agent is refused here, before a run is
            # opened - not inside execute(), where the refusal would raise and
            # Prefect would retry it.
            await self._disable(trigger, reason="creator_cannot_run_agent")
            return

        conversation_id = await self._run_log(trigger, agent_name=agent.name)

        from app.services.agent_runner import AgentRunnerService

        runner = AgentRunnerService(self.db)
        try:
            _answer, run = await runner.execute(
                ctx,
                trigger.agent_id,
                trigger.prompt,
                surface=RunSurface.SCHEDULE,
                conversation_id=conversation_id,
                environment_id=trigger.environment_id,
            )
        except (NotFoundError, AuthorizationError):
            # Access was withdrawn between the pre-check and the run. Same verdict:
            # disable, do not raise into a retry.
            await self._disable(trigger, reason="creator_cannot_run_agent")
            return

        trigger.last_run_id = run.id
        await self.db.flush()
        logger.info(
            "trigger_fired",
            extra={"trigger_id": str(trigger.id), "run_id": str(run.id), "status": run.status},
        )

    async def _creator_context(self, trigger: AgentTrigger) -> AuthContext | None:
        """The creator's current authorization context, or None if they are gone.

        Re-resolved every fire, never cached on the row: authority is whatever the
        creator's membership says *now*, so a role changed yesterday takes effect
        today. None means there is no membership to take a role from - the creator
        left the organization - and the caller disables the trigger.
        """
        if trigger.created_by_user_id is None:
            return None
        membership = await member_repo.get(
            self.db,
            organization_id=trigger.organization_id,
            user_id=trigger.created_by_user_id,
        )
        if membership is None:
            return None
        return AuthContext(
            user_id=trigger.created_by_user_id,
            organization_id=trigger.organization_id,
            role=membership.role,
        )

    async def _run_log(self, trigger: AgentTrigger, *, agent_name: str) -> UUID:
        """The one conversation this trigger appends every fire to, opened once.

        Opened eagerly when the trigger is created, so a new schedule is a
        clickable item straight away, and reused after; the fire path calls this
        too, as the idempotent fallback. Per trigger, not per fire: a trigger on
        the interval floor would otherwise mint ~1440 conversations a day. A null
        id means the conversation was never opened or was since deleted (the FK is
        SET NULL), and both want a fresh log.
        """
        if trigger.conversation_id is not None:
            return trigger.conversation_id
        conversation = await conversation_repo.create_conversation(
            self.db,
            organization_id=trigger.organization_id,
            user_id=None,
            title=f"{agent_name} - scheduled",
        )
        trigger.conversation_id = conversation.id
        await self.db.flush()
        return conversation.id

    async def _disable(self, trigger: AgentTrigger, *, reason: str) -> None:
        """Turn a trigger off and record why, for a creator who can no longer run it.

        The audit entry is the durable, admin-visible record - written with no
        actor because the platform, not a person, made the call. (A push
        notification to an admin is the plan's deferred fast-follow, batched with
        the run-completed notification, since both need the email-template build.)
        """
        trigger.is_active = False
        await self.db.flush()
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=trigger.organization_id,
            action="agent.trigger_disabled",
            target_type="agent",
            target_id=str(trigger.agent_id),
            details={
                "trigger_id": str(trigger.id),
                "reason": reason,
                "created_by_user_id": (
                    None if trigger.created_by_user_id is None else str(trigger.created_by_user_id)
                ),
            },
        )
        logger.warning(
            "trigger_disabled",
            extra={"trigger_id": str(trigger.id), "reason": reason},
        )

    async def _environment_of(self, ctx: AuthContext, agent_id: UUID, environment_id: UUID) -> None:
        """Refuse an environment that is not this agent's.

        Without this, an environment id from another agent would schedule a run of
        a version of something else entirely, surfacing as "not found" only when
        the fire arrived.
        """
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent_id:
            raise NotFoundError(
                message="Environment not found",
                details={"environment_id": str(environment_id)},
            )

    async def _owned(self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID) -> AgentTrigger:
        """The trigger, if it is this agent's and this caller may run it.

        Both halves are checked: the organization scope alone would let a caller
        pass another agent's trigger id to an agent they *can* run and edit it,
        which is a cross-resource escalation inside one tenant.

        Raises:
            NotFoundError: If the trigger is missing, in another organization, or
                on a different agent than the one in the path.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        trigger = await agent_trigger_repo.get(
            self.db, trigger_id, organization_id=ctx.organization_id
        )
        if trigger is None or trigger.agent_id != agent.id:
            raise NotFoundError(
                message="Trigger not found", details={"trigger_id": str(trigger_id)}
            )
        return trigger
