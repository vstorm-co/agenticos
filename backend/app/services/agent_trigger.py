"""Scheduling an agent to run itself - the service behind agent triggers.

A trigger fires an agent on a schedule, with nobody at the keyboard. Everything
about *what* a run is - its budget, its approvals, its accounting - is unchanged,
because a fired run goes through the same
:meth:`app.services.agent_runner.AgentRunnerService.execute` every other surface
does. This service owns the two halves the runner does not: deciding a trigger is
due without two heartbeats firing it twice, and deciding whom a fired run runs as.

Who may *create* a trigger is `agents:run` **on that agent**, resolved per-resource
through :class:`app.services.agent_registry.AgentRegistryService` - the same grant
-aware check the run path itself makes, not a role gate. Creating a schedule is
asserting "run this agent, repeatedly, as me", so the floor is exactly the
permission to run it once.

Managing an *existing* trigger is stricter, because a trigger runs its stored
prompt with its creator's identity and sandbox. The creator manages their own with
that same `agents:run`; managing someone else's - editing its prompt, deleting it,
firing it now - needs `agents:edit` on the agent, so a member who could merely run
the agent cannot edit another member's trigger into exfiltrating that member's
files. See :meth:`AgentTriggerService._owned`.

Whom a fired run runs *as* is the trigger's creator, re-resolved every fire, the
way a channel mention runs as its sender and an embed widget as its owner. There
is no invented service user: a run nobody can be held to is the thing
:class:`app.core.permissions.AuthContext` refuses to mint. When the creator can no
longer run the agent - they left the organization, or their grant on it was
revoked - the trigger auto-disables and an audit entry records why, rather than
retrying a refusal for ever.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from croniter import croniter
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_run import RunSurface
from app.db.models.agent_trigger import AgentTrigger, ScheduleKind, TriggerType
from app.db.updates import writable
from app.repositories import (
    agent_environment_repo,
    agent_trigger_repo,
    conversation_repo,
    member_repo,
)
from app.schemas.agent_trigger import (
    _EVENT_CONFIG_MODELS,
    TriggerCreate,
    TriggerRead,
    TriggerUpdate,
    _cron_has_next,
)
from app.services import portal_catalog, portals, trigger_events
from app.services.access import AGENT, resolve_access, visible_resource_ids
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_connection import McpConnectionService
from app.services.portal_catalog import DeliveryMode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventFireDecision:
    """A verified, matched delivery that should fire - the route dispatches it.

    Returned by :meth:`AgentTriggerService.prepare_event_fire` rather than firing
    inline, because the fire runs an agent and a provider (GitHub's 10s) would time
    the webhook out. The route hands this to a background task that calls
    :meth:`AgentTriggerService.fire` with the `event_context` off its own session,
    exactly as a channel mention is processed after its webhook returns.
    """

    trigger_id: UUID
    event_context: str


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


def _resolve_cadence(trigger: AgentTrigger, changes: dict[str, Any]) -> None:
    """Normalise a schedule's edited cadence to exactly one of interval/cron.

    A caller may send a new `schedule_kind`, a new cadence field, or both. Where
    the kind is left implicit it is inferred from the field sent - an interval
    means "switch to interval", a cron "switch to cron" - so the common edit needs
    only the value. The shape CHECK requires the chosen kind's field set and the
    other null, so the pair is resolved from the row where the caller left one
    implicit (switching to cron with no new expression keeps the row's) and the
    opposite field is always cleared. Mutates `changes` in place; raises
    `BadRequestError` on a kind with no usable value, so an unschedulable edit is a
    422 naming the field, not a 500.
    """
    if "schedule_kind" in changes:
        kind = changes["schedule_kind"]
    elif "cron_expression" in changes:
        kind = ScheduleKind.CRON.value
    else:
        # `touches_cadence` guarantees a cadence key; interval is what is left.
        kind = ScheduleKind.INTERVAL.value
    if kind == ScheduleKind.INTERVAL.value:
        interval = changes.get("interval_seconds", trigger.interval_seconds)
        if interval is None:
            raise BadRequestError(
                message="an interval schedule needs interval_seconds",
                details={"trigger_id": str(trigger.id)},
            )
        changes["schedule_kind"] = ScheduleKind.INTERVAL.value
        changes["interval_seconds"] = interval
        changes["cron_expression"] = None
    else:
        cron = changes.get("cron_expression", trigger.cron_expression)
        if not cron or not _cron_has_next(cron):
            raise BadRequestError(
                message="a cron schedule needs a valid crontab expression that ever fires",
                details={"trigger_id": str(trigger.id)},
            )
        changes["schedule_kind"] = ScheduleKind.CRON.value
        changes["cron_expression"] = cron
        changes["interval_seconds"] = None


def _audit_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """The applied changes, JSON-safe for the audit's JSONB `details`.

    A resume or a retime puts a recomputed `next_fire_at` datetime in `changes`,
    and the details column's default `json.dumps` cannot encode a datetime - the
    flush that stored it raised, which is why resuming a schedule 500'd where
    pausing (a `bool` only) did not. `jsonable_encoder` turns it into the ISO string
    the column stores, the same encoder the error responses use.
    """
    return cast(dict[str, Any], jsonable_encoder(changes))


def _update_action(changes: dict[str, Any]) -> str:
    """What to call this edit in the trail - pause and resume get their own names."""
    if changes.get("is_active") is True:
        return "agent.trigger_resumed"
    if changes.get("is_active") is False:
        return "agent.trigger_paused"
    return "agent.trigger_updated"


def _parse_json(body: bytes) -> dict[str, Any]:
    """The delivery body as a JSON object, or a 400 the webhook route surfaces.

    A verified delivery whose body is not a JSON object cannot be matched or
    rendered, so it is refused here rather than reaching the match code with the
    wrong type.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BadRequestError(message="Webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise BadRequestError(message="Webhook body must be a JSON object")
    return payload


class AgentTriggerService:
    """Manage and fire an organization's agent triggers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)
        self.connections = McpConnectionService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[AgentTrigger]:
        """Every schedule on this agent.

        Requires only `agents:view` (the registry's default): seeing when an agent
        runs itself is part of understanding what it is.
        """
        agent = await self.agents.get(ctx, agent_id)
        return await agent_trigger_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )

    async def list_for_organization(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> tuple[list[TriggerRead], int]:
        """Every schedule and trigger in the organization the caller may see.

        The org-wide surfaces - the sidebar section, the Activity tab - list
        across agents, so this is a collection read. Access is still per agent,
        not a role gate, and it is exactly the visibility a caller has on the
        agents themselves: `visible_resource_ids` returns the *extra* agents a
        grant shares beyond the caller's scope (`None` when the role sees the
        whole organization), and the repository combines those with the same
        owned-or-org-visible predicate the agent listing uses. Filtering on the
        grant ids alone would under-include - the agent's own page would show a
        trigger the sidebar and Activity tab hid - so the two must, and do, agree.

        Requires `agents:view`, not `agents:run`: seeing that an agent runs itself
        is part of seeing the agent. Managing a row is `agents:run`, resolved per
        row by the write path.

        Returns `TriggerRead`s, not rows, because each is enriched with its
        agent's name - the one field these surfaces need that a bare trigger does
        not carry, resolved by the join rather than a query per row.
        """
        visible = await visible_resource_ids(
            self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW
        )
        rows, total = await agent_trigger_repo.list_for_organization(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            see_all=visible is None,
            shared_ids=visible or [],
            skip=skip,
            limit=limit,
        )
        triggers: list[TriggerRead] = []
        for trigger, agent_name in rows:
            read = TriggerRead.model_validate(trigger)
            read.agent_name = agent_name
            triggers.append(read)
        return triggers, total

    async def list_portal_targets(
        self, ctx: AuthContext, portal_key: str, connection_id: UUID
    ) -> list[portals.PortalTarget]:
        """The targets a portal's preset can point at, from the connected account.

        Empty rather than an error when the portal registers no webhooks, or the
        account cannot be read for the scope - the picker falls back to a free-text
        target, so a listing that cannot answer must not block building a trigger.
        A portal key that names nothing is a 404, because a bad key is a mistake.
        """
        portal = portal_catalog.get_portal(portal_key)
        if portal is None:
            raise NotFoundError(message="Portal not found", details={"portal_key": portal_key})
        adapter = portals.get_adapter(portal_key)
        if adapter is None:
            return []
        token = await self.connections.webhook_access_token(
            ctx, connection_id, required_scopes=portal.read_scopes
        )
        if token is None:
            return []
        return await adapter.list_preset_targets(access_token=token)

    async def create(self, ctx: AuthContext, agent_id: UUID, data: TriggerCreate) -> AgentTrigger:
        """Schedule the agent to run itself, or fire it on an incoming event.

        A schedule is given its next fire, never an immediate one - creating a
        schedule is not a request to run right now. An event trigger is given no
        next fire (nothing is due until a delivery arrives) and its signing secret,
        sealed for this organization through the one vault so no plaintext secret
        is ever stored.

        Raises:
            NotFoundError: If the agent is not runnable by this caller. Reported
                as missing, not forbidden, so agent ids stay unprobeable - the
                rule every per-resource agent route follows.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        if data.environment_id is not None:
            await self._environment_of(ctx, agent.id, data.environment_id)

        now = datetime.now(UTC)
        event_source: str | None = None
        event_config: dict[str, Any] = {}
        event_secret_encrypted: str | None = None
        secret_key_version: int | None = None
        next_fire_at: datetime | None = None
        connection_id: UUID | None = None
        portal_key: str | None = None
        delivery_mode: str | None = None
        portal: portal_catalog.PortalEntry | None = None
        plaintext_secret: str | None = None

        if data.trigger_type == TriggerType.EVENT.value:
            if data.portal_key is not None:
                # A preset: the source and filter come from the catalog and the
                # secret is minted here, so the caller handles neither.
                resolved = portal_catalog.get_preset(data.portal_key, cast(str, data.preset_key))
                if resolved is None:
                    raise BadRequestError(
                        message="Unknown portal or preset",
                        details={"portal_key": data.portal_key, "preset_key": data.preset_key},
                    )
                portal, preset = resolved
                event_source = portal.event_source
                event_config = (
                    _EVENT_CONFIG_MODELS[event_source]
                    .model_validate(dict(preset.event_config))
                    .model_dump()
                )
                plaintext_secret = secrets.token_urlsafe(32)
                portal_key = portal.key
                connection_id = data.connection_id
            else:
                event_source = data.event_source
                event_config = data.event_config or {}
                plaintext_secret = cast(str, data.event_secret)
            sealed = seal(plaintext_secret, scope=VaultScope.organization(ctx.organization_id))
            event_secret_encrypted = sealed.ciphertext
            secret_key_version = sealed.key_version
            # Manual until an auto-registration below succeeds, so a preset whose
            # account lacks the scope or whose provider refuses degrades to the
            # pasted-URL path rather than a half-set trigger.
            delivery_mode = "manual"
        else:
            next_fire_at = _next_fire(
                schedule_kind=data.schedule_kind,
                interval_seconds=data.interval_seconds,
                cron_expression=data.cron_expression,
                now=now,
            )

        trigger = await agent_trigger_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            created_by_user_id=ctx.subject_id,
            prompt=data.prompt,
            name=data.name,
            trigger_type=data.trigger_type,
            schedule_kind=data.schedule_kind,
            interval_seconds=data.interval_seconds,
            cron_expression=data.cron_expression,
            event_source=event_source,
            event_config=event_config,
            event_secret_encrypted=event_secret_encrypted,
            secret_key_version=secret_key_version,
            environment_id=data.environment_id,
            next_fire_at=next_fire_at,
            connection_id=connection_id,
            portal_key=portal_key,
            delivery_mode=delivery_mode,
        )
        # Auto-register the provider webhook for a preset whose portal supports it
        # and whose connected account carries the scope; any miss leaves the
        # trigger `manual` and the caller pastes the URL the response exposes.
        if (
            portal is not None
            and portal.delivery is DeliveryMode.AUTO_WEBHOOK
            and connection_id is not None
        ):
            await self._auto_register_webhook(
                ctx,
                trigger,
                portal=portal,
                connection_id=connection_id,
                target=data.target,
                secret=cast(str, plaintext_secret),
            )
        # Open the run-log conversation now, not on the first fire, so a new
        # trigger is a clickable item in the sidebar the moment it exists - empty
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
            # The sealed secret is never audited - only that a trigger of this
            # shape was created.
            details={
                "trigger_id": str(trigger.id),
                "trigger_type": trigger.trigger_type,
                "schedule_kind": trigger.schedule_kind,
                "interval_seconds": trigger.interval_seconds,
                "cron_expression": trigger.cron_expression,
                "event_source": trigger.event_source,
            },
        )
        # Reload before returning: opening the run-log conversation flushed a
        # `conversation_id` update, and the server-side `updated_at` (onupdate) it
        # triggered is now expired on the instance. Serializing the response reads
        # every attribute in a sync context, where a lazy reload of that one would
        # be a `MissingGreenlet` 500 - the exact failure a mocked service test
        # cannot see, since it never serializes a live row.
        await self.db.refresh(trigger)
        # Reveal the minted secret exactly once - only for a preset the platform
        # could not register itself (manual delivery), where the person wiring the
        # relay needs it to sign deliveries. A transient attribute, never a column:
        # `TriggerCreateRead` reads it on the create response, and `TriggerRead`
        # (every read and the listing) has no such field, so a sealed secret is
        # never re-exposed. A raw trigger's secret is the caller's own and is not
        # echoed back.
        reveal = portal is not None and trigger.delivery_mode == "manual"
        # `setattr`, not `trigger.reveal_secret = …`: it is not a mapped column, so
        # a direct assignment fails the type checker. B010 prefers the assignment,
        # which is exactly what does not type here.
        setattr(trigger, "reveal_secret", plaintext_secret if reveal else None)  # noqa: B010
        return trigger

    async def _auto_register_webhook(
        self,
        ctx: AuthContext,
        trigger: AgentTrigger,
        *,
        portal: portal_catalog.PortalEntry,
        connection_id: UUID,
        target: str | None,
        secret: str,
    ) -> None:
        """Register the trigger's webhook at the provider, or leave it manual.

        Best-effort by design: no adapter, no scope-bearing token, or a provider
        that refuses all leave the trigger `manual` and the caller pastes the URL.
        A registered hook records its id and target so `delete` can remove it.
        """
        adapter = portals.get_adapter(portal.key)
        if adapter is None:
            return
        token = await self.connections.webhook_access_token(
            ctx, connection_id, required_scopes=portal.webhook_admin_scopes
        )
        if token is None:
            return
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        webhook_url = f"{base}/api/v1/webhooks/triggers/{trigger.event_source}/{trigger.id}"
        try:
            registered = await adapter.register_webhook(
                access_token=token, target=target, webhook_url=webhook_url, secret=secret
            )
        except portals.PortalError:
            logger.info(
                "trigger_webhook_manual_fallback",
                extra={"trigger_id": str(trigger.id), "portal": portal.key},
            )
            return
        trigger.provider_webhook_id = registered.provider_webhook_id
        trigger.provider_target = target
        trigger.delivery_mode = "auto_webhook"
        await self.db.flush()

    async def _deregister_webhook(self, ctx: AuthContext, trigger: AgentTrigger) -> None:
        """Remove a trigger's provider webhook, best-effort, before it is deleted.

        Never blocks the delete: an orphaned hook that now 401s on delivery is
        harmless, but a delete that fails because the provider is down is not. A
        manual or schedule trigger has no hook and this is a no-op.
        """
        if not (trigger.provider_webhook_id and trigger.connection_id and trigger.portal_key):
            return
        portal = portal_catalog.get_portal(trigger.portal_key)
        adapter = portals.get_adapter(trigger.portal_key)
        if portal is None or adapter is None:
            return
        try:
            token = await self.connections.webhook_access_token(
                ctx, trigger.connection_id, required_scopes=portal.webhook_admin_scopes
            )
            if token is None:
                return
            await adapter.delete_webhook(
                access_token=token,
                target=trigger.provider_target,
                provider_webhook_id=trigger.provider_webhook_id,
            )
        except Exception:
            logger.warning(
                "trigger_webhook_deregister_failed",
                extra={"trigger_id": str(trigger.id)},
            )

    async def update(
        self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID, data: TriggerUpdate
    ) -> AgentTrigger:
        """Pause, resume, retime, repoint, or reword a schedule.

        Only the fields the caller actually sent are applied, so pausing a trigger
        cannot silently move it back to the default environment.
        """
        trigger = await self._owned(ctx, agent_id, trigger_id)
        changes = writable(data, over=AgentTrigger)

        # Cadence edits: a schedule may be retimed in place - a new interval, a new
        # cron, or a switch between the two - rather than deleted and recreated. An
        # event has no cadence, so any cadence field on one is refused here rather
        # than written through the shape CHECK as a 500.
        cadence_keys = ("schedule_kind", "interval_seconds", "cron_expression")
        touches_cadence = any(key in changes for key in cadence_keys)
        if touches_cadence and trigger.trigger_type != TriggerType.SCHEDULE.value:
            raise BadRequestError(
                message="only a schedule has a cadence to change",
                details={"trigger_id": str(trigger.id)},
            )

        if changes.get("environment_id") is not None:
            await self._environment_of(ctx, agent_id, changes["environment_id"])

        # A cadence change or a resume takes effect from now: a schedule shrunk from
        # daily to minutely, switched to cron, or resumed must not wait out the old
        # cadence's next instant. A cadence change first resolves the pair so exactly
        # one of interval/cron is set - what the shape CHECK requires and the repo
        # writes verbatim; a bare resume recomputes from the row's own cadence.
        if trigger.trigger_type == TriggerType.SCHEDULE.value and (
            touches_cadence or changes.get("is_active") is True
        ):
            if touches_cadence:
                _resolve_cadence(trigger, changes)
            changes["next_fire_at"] = _next_fire(
                schedule_kind=changes.get("schedule_kind", trigger.schedule_kind),
                interval_seconds=changes.get("interval_seconds", trigger.interval_seconds),
                cron_expression=changes.get("cron_expression", trigger.cron_expression),
                now=datetime.now(UTC),
            )
        updated = await agent_trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=_update_action(changes),
            target_type="agent",
            target_id=str(agent_id),
            details={"trigger_id": str(trigger.id), "changes": _audit_changes(changes)},
        )
        return updated

    async def delete(self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID) -> None:
        """Remove a schedule entirely - the agent stops running itself."""
        trigger = await self._owned(ctx, agent_id, trigger_id)
        # Take the provider hook down first, so a deleted trigger stops receiving
        # deliveries; best-effort, never blocking the delete.
        await self._deregister_webhook(ctx, trigger)
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

    async def run_now(self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID) -> AgentTrigger:
        """Accept one extra fire of this schedule, without disturbing its cadence.

        The caller needs `agents:run` on the agent - the floor for scheduling it
        at all, checked by `_owned`. The fire runs as the trigger's creator, the
        same subject a heartbeat fire uses, so a schedule always runs as one
        identity however it was set off. `next_fire_at` is left untouched: running
        now is one extra fire, not a reschedule. A paused schedule is respected -
        `fire` no-ops on an inactive trigger - so this is offered only on a live one.

        The run itself is attributed to the creator, but *who pressed the button*
        is a separate fact and a spend, so it is audited under the caller: without
        this, a member with `agents:run` could set off a run recorded entirely
        under someone else's name.

        **The fire is dispatched, not awaited** (#658). Awaiting it ran the whole
        agent inside the HTTP request, so an agent slower than a proxy's read
        timeout - 60s by default on nginx - answered the caller 504 while the run
        carried on and committed server-side: a failure reported for something that
        was working, and an invitation to press the button again and fire the
        schedule twice. `spawn_after_commit`, not `spawn`, because the fire opens a
        session of its own and must not outrun this request's transaction.

        Returns the trigger as it stands, which is why the route answers 202: the
        run has not happened yet, so `last_run_id` still names the previous one. The
        fire appends to the trigger's run-log conversation as it goes.
        """
        trigger = await self._owned(ctx, agent_id, trigger_id)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.trigger_run_now",
            target_type="agent",
            target_id=str(agent_id),
            details={"trigger_id": str(trigger.id)},
        )
        # Local: the handler imports this module, so hoisting this is a cycle.
        from app.worker.background.trigger_fire import fire_trigger

        spawn_after_commit(self.db, fire_trigger(trigger.id), name=f"trigger-run-now-{trigger.id}")
        return trigger

    async def prepare_event_fire(
        self, source: str, trigger_id: UUID, *, body: bytes, headers: Mapping[str, str]
    ) -> EventFireDecision | None:
        """Authenticate and match an inbound delivery, returning what to fire.

        Called by the webhook route with no auth context - the delivery is
        authenticated by its HMAC signature against the trigger's own secret, not
        a session, and the fire runs as the trigger's creator like every other
        fire. Returns the decision to fire, or `None` when the delivery is
        authentic but there is nothing to do: an unknown trigger, one that is not
        an active event trigger of this source, or one whose filter the payload
        does not match. All of those answer the same way, so a caller cannot use
        the response to tell an existing trigger from a missing one.

        Raises:
            AuthorizationError: The signature did not verify. The one case that is
                not silent, because a misconfigured secret is the integrator's to
                fix and a 403 is how a provider surfaces it.
            BadRequestError: The body is not a JSON object.
        """
        trigger = await agent_trigger_repo.get_by_id(self.db, trigger_id)
        if (
            trigger is None
            or trigger.trigger_type != TriggerType.EVENT.value
            or trigger.event_source != source
            or not trigger.is_active
        ):
            return None
        secret = self._unseal_event_secret(trigger)
        if not trigger_events.verify_signature(source, secret=secret, body=body, headers=headers):
            raise AuthorizationError(
                message="Webhook signature did not verify",
                details={"trigger_id": str(trigger_id)},
            )
        payload = _parse_json(body)
        if not trigger_events.event_matches(
            source, headers=headers, payload=payload, config=trigger.event_config
        ):
            return None
        context = trigger_events.render_context(source, payload=payload)
        return EventFireDecision(trigger_id=trigger.id, event_context=context)

    def _unseal_event_secret(self, trigger: AgentTrigger) -> str:
        """The trigger's signing secret, unsealed for its organization.

        The shape CHECK guarantees an event trigger's secret and its key version
        are both present, so the casts cannot be reached with a null - a guard
        here would be an untestable branch under the 100% gate, the same reason
        `_next_fire` casts rather than checks.
        """
        return unseal(
            cast(str, trigger.event_secret_encrypted),
            scope=VaultScope.organization(trigger.organization_id),
            key_version=cast(int, trigger.secret_key_version),
        )

    async def claim_and_advance(self, *, now: datetime, limit: int = 100) -> list[AgentTrigger]:
        """Claim the triggers due now, advancing each so no later tick re-fires it.

        The claim locks each row `FOR UPDATE SKIP LOCKED`, and advancing
        `next_fire_at` happens under that same lock, so two heartbeats running at
        once take disjoint work and neither leaves a due row behind for the other.
        The worker calls this with no auth context - it is a system sweep, and the
        organization each fired run belongs to is read off its own row.

        Only `next_fire_at` moves here, not `last_fired_at`: claiming is not
        firing, and the dispatched run may still be refused (a creator who lost
        access). The actual fire stamps `last_fired_at` in `fire`, so it means the
        same thing - a run was created - on every entry path, scheduled or event.
        """
        triggers = await agent_trigger_repo.claim_due(self.db, now=now, limit=limit)
        for trigger in triggers:
            trigger.next_fire_at = _next_fire_from(trigger, now=now)
        await self.db.flush()
        return triggers

    async def fire(self, trigger_id: UUID, *, event_context: str | None = None) -> None:
        """Run the agent this trigger fires, as the member who created it.

        Called by the worker with a bare id (a scheduled fire) or by the webhook's
        background task with the delivered `event_context` (an event fire), so it
        re-loads everything and trusts nothing from the caller: a trigger deleted
        or disabled between claim and fire simply does nothing. An event fire
        appends its context to the trigger's prompt, so the agent sees which issue
        or email set it off; a scheduled fire has none and sends the prompt as-is.
        The run goes through `AgentRunnerService.execute`,
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
            # No *active* membership to take a role from - the creator left the
            # organization, was deactivated, or the user row itself is gone and
            # SET NULL cleared the column. Either way the schedule is no longer
            # attributable to an account that could run it, so it stops.
            await self._disable(trigger, reason="creator_not_active")
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

        message = (
            trigger.prompt if event_context is None else f"{trigger.prompt}\n\n{event_context}"
        )
        runner = AgentRunnerService(self.db)
        try:
            _answer, run = await runner.execute(
                ctx,
                trigger.agent_id,
                message,
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
        # Stamp the fire on every path, not just the scheduled heartbeat: without
        # this an event trigger or a Run now reported "never fired" however many
        # runs it made, because only `claim_and_advance` used to set it.
        trigger.last_fired_at = datetime.now(UTC)
        await self.db.flush()
        logger.info(
            "trigger_fired",
            extra={"trigger_id": str(trigger.id), "run_id": str(run.id), "status": run.status},
        )

    async def _creator_context(self, trigger: AgentTrigger) -> AuthContext | None:
        """The creator's current authorization context, or None if they are gone.

        Re-resolved every fire, never cached on the row: authority is whatever the
        creator's membership says *now*, so a role changed yesterday takes effect
        today. None means there is no membership to take a role from, and the
        caller disables the trigger.

        `get_active`, not `get`: deactivating a user leaves the membership row in
        place, so a plain `get` would rebuild the disabled account's old role and
        keep firing on the schedule (or on a signed delivery the deactivated
        creator still holds the secret for) even though that account is refused
        everywhere a person signs in. Only an account that can still sign in may
        run an agent with nobody at the keyboard.
        """
        if trigger.created_by_user_id is None:
            return None
        membership = await member_repo.get_active(
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
        suffix = "triggered" if trigger.trigger_type == TriggerType.EVENT.value else "scheduled"
        conversation = await conversation_repo.create_conversation(
            self.db,
            organization_id=trigger.organization_id,
            user_id=None,
            title=f"{agent_name} - {suffix}",
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
        """The trigger, if it is this agent's and this caller may manage it.

        Three halves, and the third is a privilege boundary, not a lookup. The
        organization scope and the agent match rule out cross-tenant and
        cross-resource reads: without them a caller could pass another agent's
        trigger id to an agent they can run and act on it.

        The third: a trigger runs its stored prompt with its *creator's* identity
        and sandbox, so editing, deleting or firing a trigger you did not create
        is an administrative act over someone else's authority, not the
        `agents:run` that merely lets you fire the agent as yourself. A member who
        could only run the agent would otherwise edit another member's trigger
        prompt - `prompt` is a writable field - and have it exfiltrate the
        creator's per-user files on the next delivery, or press *Run now* to do so
        at once. So managing a trigger the caller did not create needs
        `agents:edit` on the agent (an org admin, or the holder of an explicit edit
        grant); the creator manages their own with the `agents:run` they built it
        on. A refusal is reported as "not found", the same unprobeable answer the
        other two halves give.

        Raises:
            NotFoundError: If the trigger is missing, in another organization, on a
                different agent than the one in the path, or created by someone else
                and the caller lacks `agents:edit`.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        trigger = await agent_trigger_repo.get(
            self.db, trigger_id, organization_id=ctx.organization_id
        )
        if trigger is None or trigger.agent_id != agent.id:
            raise NotFoundError(
                message="Trigger not found", details={"trigger_id": str(trigger_id)}
            )
        if trigger.created_by_user_id != ctx.subject_id and not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT
        ):
            raise NotFoundError(
                message="Trigger not found", details={"trigger_id": str(trigger_id)}
            )
        return trigger
