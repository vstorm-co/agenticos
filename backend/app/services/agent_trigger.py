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
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.agent_trigger import AgentTrigger, ScheduleKind, TriggerType
from app.db.updates import writable
from app.repositories import (
    agent_environment_repo,
    agent_run_repo,
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
from app.services import portal_catalog, portals, trigger_dedupe, trigger_events
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


def _is_auto_webhook(trigger: AgentTrigger) -> bool:
    """Whether the platform registered this trigger's webhook at its provider.

    The three fields the registration recorded, all present together or not at
    all: a manual event trigger and a schedule carry none of them. Named once so
    the rotate path and the delete path agree on what an auto-registered hook is -
    a hook the platform holds the secret for, and must teach a new secret to when
    it rotates.
    """
    return bool(trigger.provider_webhook_id and trigger.connection_id and trigger.portal_key)


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

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[TriggerRead]:
        """Every schedule on this agent, each flagged whether this caller manages it.

        Requires only `agents:view` (the registry's default): seeing when an agent
        runs itself is part of understanding what it is. `can_manage` is the
        `agents:edit`-on-the-agent the write path enforces, resolved once for the
        agent, OR ownership of the row - so the page renders edit, pause, run-now
        and delete for exactly the rows the caller could act on, and a Viewer with
        an explicit grant is no longer hidden from their own.
        """
        agent = await self.agents.get(ctx, agent_id)
        rows = await agent_trigger_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        can_edit = await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT)
        reads: list[TriggerRead] = []
        for trigger in rows:
            read = TriggerRead.model_validate(trigger)
            read.can_manage = can_edit or trigger.created_by_user_id == ctx.subject_id
            reads.append(read)
        return reads

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
        # `agents:edit` resolved once per agent, not once per row: an org-wide list
        # is many triggers over few agents, and the answer is the agent's.
        can_edit: dict[UUID, bool] = {}
        for trigger, agent in rows:
            read = TriggerRead.model_validate(trigger)
            read.agent_name = agent.name
            read.agent_has_avatar = agent.has_avatar
            read.agent_avatar_color = agent.avatar_color
            if agent.id not in can_edit:
                can_edit[agent.id] = await resolve_access(
                    self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT
                )
            read.can_manage = can_edit[agent.id] or trigger.created_by_user_id == ctx.subject_id
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
                # A preset: the source comes from the catalog and the secret is
                # minted here, so the caller handles neither. The filter is the
                # preset's defaults with the caller's optional `event_config`
                # override merged over, then validated against the source the
                # catalog resolves - so a bad override key is a 422 naming it
                # rather than a 500 or a filter stored to match nothing.
                resolved = portal_catalog.get_preset(data.portal_key, cast(str, data.preset_key))
                if resolved is None:
                    raise BadRequestError(
                        message="Unknown portal or preset",
                        details={"portal_key": data.portal_key, "preset_key": data.preset_key},
                    )
                portal, preset = resolved
                event_source = portal.event_source
                event_config = self._merged_preset_config(event_source, preset, data.event_config)
                plaintext_secret = secrets.token_urlsafe(32)
                portal_key = portal.key
                # Resolve the caller-supplied connection against their own
                # organization before it is stored, whatever the delivery mode:
                # only the auto_webhook path unwraps a token for it, so without
                # this a manual or polling preset would persist another tenant's
                # `mcp_connections.id` on the row unchecked. A foreign or bogus id
                # is the same unprobeable 404 every org-scoped connection lookup
                # gives.
                if data.connection_id is not None:
                    await self.connections.get_org_connection(ctx, data.connection_id)
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
        # The creator can always manage what they just made; the list surfaces
        # resolve this per row, a single create response states it directly.
        setattr(trigger, "can_manage", True)  # noqa: B010
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
        if not _is_auto_webhook(trigger):
            return
        # `_is_auto_webhook` guarantees these three are set together; the casts
        # annotate what the guard already proved, the same idiom `_unseal_event_secret`
        # uses for a field the shape CHECK guarantees.
        portal_key = cast(str, trigger.portal_key)
        portal = portal_catalog.get_portal(portal_key)
        adapter = portals.get_adapter(portal_key)
        if portal is None or adapter is None:
            return
        try:
            token = await self.connections.webhook_access_token(
                ctx, cast(UUID, trigger.connection_id), required_scopes=portal.webhook_admin_scopes
            )
            if token is None:
                return
            await adapter.delete_webhook(
                access_token=token,
                target=trigger.provider_target,
                provider_webhook_id=cast(str, trigger.provider_webhook_id),
            )
        except Exception:
            logger.warning(
                "trigger_webhook_deregister_failed",
                extra={"trigger_id": str(trigger.id)},
            )

    async def update(
        self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID, data: TriggerUpdate
    ) -> AgentTrigger:
        """Pause, resume, retime, repoint, reword, or refilter a trigger.

        Only the fields the caller actually sent are applied, so pausing a trigger
        cannot silently move it back to the default environment.

        An event trigger's *filter* is editable in place too: changing which issue
        actions fire is a filter edit, not a different trigger, so `event_config`
        is re-validated against the source's typed model and written - while the
        source and the secret stay immutable (repointing an event is a different
        trigger, made by deleting this one and creating that).
        """
        trigger = await self._owned(ctx, agent_id, trigger_id)
        changes = writable(data, over=AgentTrigger)

        # A filter edit, the event mirror of a cadence edit: an event trigger's
        # `event_config` is re-normalised against its source, and one sent for a
        # schedule (which has no filter) is refused rather than stored to mean
        # nothing - the same shape the cadence-on-event refusal below has.
        if "event_config" in changes:
            changes["event_config"] = self._validated_event_config(trigger, changes["event_config"])

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
        # `_owned` let this caller through, so they manage it - say so on the read.
        setattr(updated, "can_manage", True)  # noqa: B010
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

    def _merged_preset_config(
        self,
        event_source: str,
        preset: portal_catalog.PortalPreset,
        override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The preset's filter with the caller's override merged over, validated.

        A preset carries a filter template for its source (a GitHub `issue_opened`
        fires on the `opened` action); the caller may narrow it further per source
        - an email preset filtered to a subject or sender. The override is merged
        key-by-key over the preset's defaults and the result validated against the
        source's typed model, filling defaults and refusing an unknown key. A bad
        override is the same 422 a hand-typed config gives, not a 500 from the raw
        pydantic error nor a filter stored to match nothing.
        """
        try:
            return cast(
                dict[str, Any],
                _EVENT_CONFIG_MODELS[event_source]
                .model_validate({**dict(preset.event_config), **(override or {})})
                .model_dump(),
            )
        except PydanticValidationError as exc:
            raise ValidationError(
                message="event_config is not valid for this preset's source",
                details={"errors": exc.errors(include_url=False, include_input=False)},
            ) from exc

    def _validated_event_config(
        self, trigger: AgentTrigger, config: dict[str, Any]
    ) -> dict[str, Any]:
        """The edited filter, normalised against the trigger's source, or a refusal.

        Only an event trigger's filter is editable, so the source is read off the
        row and the new config validated against exactly the typed model create
        used - filling defaults and refusing an unknown key. A schedule has no
        filter, so one sent for it is a 400; a key the source refuses is the same
        422 create gives, not a config stored to match nothing.
        """
        if trigger.trigger_type != TriggerType.EVENT.value:
            raise BadRequestError(
                message="only an event trigger has an event_config to change",
                details={"trigger_id": str(trigger.id)},
            )
        model = _EVENT_CONFIG_MODELS[cast(str, trigger.event_source)]
        try:
            return cast(dict[str, Any], model.model_validate(config).model_dump())
        except PydanticValidationError as exc:
            raise ValidationError(
                message="event_config is not valid for this trigger's source",
                details={"errors": exc.errors(include_url=False, include_input=False)},
            ) from exc

    async def rotate_secret(
        self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID
    ) -> AgentTrigger:
        """Re-seal an event trigger's signing secret, revealing the new one once.

        The URL is the trigger's identity and never changes; the secret is a
        credential and is replaceable - a re-seal and a fresh plaintext shown
        exactly once, the same shape as every other key in this product. A schedule
        has no secret, so rotating one is refused. Management-gated through `_owned`:
        the creator, or the holder of `agents:edit` on the agent.

        An auto-registered hook signs its deliveries with the old secret, so a
        rotation must teach the provider the new one or every delivery would 403
        after it. The hook is re-registered at the same URL with the new secret; if
        the account can no longer register it - a revoked scope, a provider refusal,
        the portal gone from the catalog - the trigger falls back to manual and the
        revealed secret is what the person re-pastes, exactly as create's fallback.

        The new ciphertext is flushed *before* the provider hook is touched, on
        purpose. In the other order, any failure between the provider call and
        the commit rolled the row back to the old secret while the provider was
        already signing with a new one that then existed nowhere - unrecoverable
        without redoing the whole integration. This way the one residual window
        (a crash between the flush and the provider call) leaves a hook signing
        with the old secret and a row holding the new: deliveries 403 until
        somebody rotates again, which is exactly the action that repairs it.
        """
        trigger = await self._owned(ctx, agent_id, trigger_id)
        if trigger.trigger_type != TriggerType.EVENT.value:
            raise BadRequestError(
                message="only an event trigger has a secret to rotate",
                details={"trigger_id": str(trigger.id)},
            )
        plaintext = secrets.token_urlsafe(32)
        sealed = seal(plaintext, scope=VaultScope.organization(ctx.organization_id))
        updated = await agent_trigger_repo.update(
            self.db,
            trigger=trigger,
            update_data={
                "event_secret_encrypted": sealed.ciphertext,
                "secret_key_version": sealed.key_version,
            },
        )
        if _is_auto_webhook(updated):
            await self._reregister_hook(ctx, updated, secret=plaintext)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.trigger_secret_rotated",
            target_type="agent",
            target_id=str(agent_id),
            # The new secret never reaches the trail - only that it was rotated and
            # how the trigger delivers now.
            details={"trigger_id": str(updated.id), "delivery_mode": updated.delivery_mode},
        )
        # An auto-registered hook now holds the new secret, so nothing is revealed;
        # a manual trigger (or an auto one that fell back) needs the plaintext to
        # update its provider, shown once here and never again - `TriggerRead`, what
        # every other read serializes, has no such field.
        reveal = updated.delivery_mode != "auto_webhook"
        setattr(updated, "reveal_secret", plaintext if reveal else None)  # noqa: B010
        # `_owned` let this caller through, so they manage it - say so on the read.
        setattr(updated, "can_manage", True)  # noqa: B010
        return updated

    async def _reregister_hook(
        self, ctx: AuthContext, trigger: AgentTrigger, *, secret: str
    ) -> None:
        """Move an auto-registered hook onto a new secret, or fall back to manual.

        Deletes the provider's old hook and registers a fresh one at the same URL
        signed with `secret`. `_is_auto_webhook` guarantees the `portal_key`, so a
        portal that has since left the catalog is the one miss handled here; every
        other miss - no adapter, a revoked scope, a provider refusal - is
        `_auto_register_webhook`'s own manual fallback, reached by leaving the
        trigger manual before it runs so a failed re-register does not keep a
        provider_webhook_id whose hook was just deleted.
        """
        portal = portal_catalog.get_portal(cast(str, trigger.portal_key))
        target = trigger.provider_target
        await self._deregister_webhook(ctx, trigger)
        trigger.provider_webhook_id = None
        trigger.provider_target = None
        trigger.delivery_mode = "manual"
        if portal is None:
            return
        await self._auto_register_webhook(
            ctx,
            trigger,
            portal=portal,
            connection_id=cast(UUID, trigger.connection_id),
            target=target,
            secret=secret,
        )

    async def run_now(self, ctx: AuthContext, agent_id: UUID, trigger_id: UUID) -> AgentTrigger:
        """Fire this trigger once, on demand, without disturbing how it normally fires.

        Works for either kind, and is deliberately offered on both. A schedule
        fires one extra time with `next_fire_at` left untouched - running now is an
        extra fire, not a reschedule. An **event trigger** fires too, as a manual
        test-fire: the agent runs its base prompt with no delivery context
        (`event_context=None`), so it is the way to confirm the agent, its prompt
        and its budget behave without standing up a provider, signing a payload or
        waiting for a real delivery. What it does *not* exercise is the signature
        path or a real payload's rendered context.

        The caller needs `agents:run` on the agent - the floor for scheduling it
        at all, checked by `_owned`. The fire runs as the trigger's creator, the
        same subject a heartbeat or a delivered event uses, so a trigger always
        runs as one identity however it was set off. A paused trigger is respected
        - `fire` no-ops on an inactive one - so this is offered only on a live one.

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
        # `_owned` let this caller through, so they manage it - say so on the read.
        setattr(trigger, "can_manage", True)  # noqa: B010
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
        # At-least-once delivery: a redelivery of an event already dispatched must
        # not fire a second run and a second spend. Claim the provider's delivery
        # id; a delivery that carries none, or a Redis that cannot be reached, fails
        # open and fires, and a duplicate answers the same nothing-to-do `None` an
        # unmatched delivery does, so it stays unprobeable. The claim is released by
        # the route if the fire's hand-off then fails (`release_event_claim`).
        delivery = trigger_events.delivery_id(source, headers)
        if delivery is not None and not await trigger_dedupe.claim_event_delivery(
            trigger_id=trigger.id, delivery_id=delivery
        ):
            return None
        context = trigger_events.render_context(source, payload=payload)
        return EventFireDecision(trigger_id=trigger.id, event_context=context)

    async def release_event_claim(
        self, source: str, trigger_id: UUID, headers: Mapping[str, str]
    ) -> None:
        """Give back the dedupe claim on a delivery whose fire was not dispatched.

        `prepare_event_fire` claims before returning the decision, so a hand-off
        that then raises - Prefect unreachable - must release the claim or the
        provider's resend is dropped and the event lost. A delivery with no provider
        id was never claimed, so this is a no-op for it.
        """
        delivery = trigger_events.delivery_id(source, headers)
        if delivery is not None:
            await trigger_dedupe.release_event_delivery(trigger_id=trigger_id, delivery_id=delivery)

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

        An orphaned schedule - one whose creator's user row was hard-deleted, so
        `created_by_user_id` is null - is claimed now (the query no longer filters
        it out) and disabled here rather than dispatched: it can never run, and
        `fire` would only disable it after a wasted flow run. Dispatching is left to
        the schedules that can still fire.
        """
        triggers = await agent_trigger_repo.claim_due(self.db, now=now, limit=limit)
        live: list[AgentTrigger] = []
        for trigger in triggers:
            if trigger.created_by_user_id is None:
                await self._disable(trigger, reason="creator_not_active")
                continue
            trigger.next_fire_at = _next_fire_from(trigger, now=now)
            # Mark the fire in flight in the same committed UPDATE that advances the
            # schedule, so no window opens in which a slow run's trigger looks
            # claimable to the next tick. This timestamp is the claim's ticket: the
            # scheduled fire this claim dispatches is handed it back as `claimed_at`
            # and clears the marker only while it still matches (`fire`), so a fire
            # that outran the lease cannot clear a newer claim's marker. A dispatch
            # that never started a run leaves the marker for the lease to free rather
            # than clearing it eagerly - the child flow may have started even when the
            # submit call raised.
            trigger.fire_in_flight_since = now
            live.append(trigger)
        await self.db.flush()
        return live

    async def fire(
        self,
        trigger_id: UUID,
        *,
        event_context: str | None = None,
        claimed_at: datetime | None = None,
    ) -> None:
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

        A run that fails on something the runner re-raises rather than records - a
        provider 5xx, a revoked key, a timeout - is neither a refusal nor a reason
        to disable. `_run` has already committed the row as `failed`, so the fire
        is in Activity; `fire` recovers that row from the trigger's conversation to
        stamp `last_run_id` and returns, rather than letting the error fail the
        Prefect flow and retry the same outage against the same money. The recovered
        row is identified by *this* fire having advanced the conversation's tail past
        the previous fire's run - an error before the run existed leaves the tail
        where it was, and stamping it would name the wrong fire.

        Only a durably recorded failure is swallowed. A run that reached a terminal
        state whose write never committed - a finalization or persistence step
        raising after the answer was in hand - is re-raised, so the half-written
        state rolls back and the flow is marked failed rather than reporting a run
        that no row records.

        `claimed_at` is the `fire_in_flight_since` the heartbeat's claim stamped, and
        it is this fire's claim ticket: passing it says "clear the marker when this
        ends - however it ends: a completed run, a recorded failure, a disable, or a
        skip - but only while the marker is still the one my claim set". Only the
        scheduled worker path passes it. `run_now` and an event fire reach `fire`
        with no claim behind them, and a marker they find belongs to a concurrent
        scheduled fire still relying on it: clearing it would reopen the trigger to
        the next tick mid-run, the self-overlap `0025` exists to close.

        The identity check is what keeps a slow fire from clearing a *newer* claim's
        marker. If this fire outran the lease, `claim_due` may have re-claimed the
        trigger and stamped a fresh `fire_in_flight_since` for a second fire now in
        flight; this one finishing must not clear that, or the trigger reopens under
        the newer fire. So it clears only when the marker still equals the timestamp
        it was dispatched with. The lease still frees a marker a crashed scheduled
        fire never cleared, and a dispatch that never started a run leaves the marker
        for the lease to free rather than clearing it eagerly - the child flow may
        have started even when the submit call raised.
        """
        trigger = await agent_trigger_repo.get_by_id(self.db, trigger_id)
        if trigger is None:
            logger.info("trigger_fire_skipped", extra={"trigger_id": str(trigger_id)})
            return
        try:
            await self._fire_loaded(trigger, event_context=event_context)
        finally:
            if claimed_at is not None and trigger.fire_in_flight_since == claimed_at:
                trigger.fire_in_flight_since = None
                await self.db.flush()

    async def _fire_loaded(
        self, trigger: AgentTrigger, *, event_context: str | None = None
    ) -> None:
        """The fire itself, once the row is loaded - split out so `fire` can clear the
        scheduled path's in-flight marker in a `finally` around every path through it."""
        if not trigger.is_active:
            logger.info("trigger_fire_skipped", extra={"trigger_id": str(trigger.id)})
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
        # This trigger's tail before the fire opens a run of its own. Every fire ends
        # by stamping `last_run_id` against the run it created, so the run named here
        # is exactly the newest row in the trigger's run-log conversation. It is how
        # the failure path tells this fire's run apart from a previous fire's:
        # `execute` creates the run row inside `prepare`, so an error before that
        # leaves the tail unchanged, and stamping `last_run_id` against it would name
        # the wrong fire - the trigger appends every fire to one conversation (#589).
        previous_run_id = trigger.last_run_id
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
        except BadRequestError:
            # The agent is no longer runnable - unpublished back to a draft,
            # archived, or its version withdrawn - so `get_runnable_spec` refuses
            # inside execute. Left active, every cadence would dispatch another run
            # that fails exactly here; disable it instead of retrying a certainty,
            # the same verdict the authz refusal gets for the same reason. Caught
            # before the blanket `Exception` below, which would otherwise find no run
            # of this fire's to recover and simply return, leaving the schedule to
            # dispatch the same doomed run every cadence.
            await self._disable(trigger, reason="agent_not_runnable")
            return
        except Exception:
            # The run failed on something the runner re-raises instead of recording
            # as a terminal status - a provider 5xx, a revoked key, a timeout. `_run`
            # commits the row as `failed` before re-raising, so the failure is in
            # Activity; letting it propagate would only fail the Prefect flow for a
            # run already accounted for and retry the same outage. Recover the row
            # from the trigger's own conversation, stamp it, and return.
            logger.exception("trigger_fire_run_errored", extra={"trigger_id": str(trigger.id)})
            run = await agent_run_repo.latest_run_for_conversation(
                self.db, conversation_id, organization_id=ctx.organization_id
            )
            if run is None or run.id == previous_run_id:
                # No run row for *this* fire: the error struck before one was created
                # - a spec that no longer builds, a model profile deleted since
                # publish - or the tail is still the previous fire's run. Nothing of
                # this fire's to stamp; the next interval tries again once the cause
                # is fixed.
                return
            if run.status == RunStatus.RUNNING.value:
                # The error struck after `create_run` flushed the row `running` but
                # before `_run` could record it terminal - `workspaces.open`,
                # `build_agent` and delegation setup all run after the row exists, and
                # an error from any of them escapes `_run`'s `finally`. Nothing else
                # will ever finish this run, and a non-terminal `last_run_id` makes
                # `claim_due`'s no-overlap guard skip the trigger on every tick for
                # ever. It can only be this fire's own orphan - `claim_due` proved the
                # previous run terminal at claim time, and an in-flight run's row is
                # invisible to other transactions until its own commit lands - so
                # settle it before stamping.
                run.status = RunStatus.FAILED.value
                run.ended_at = datetime.now(UTC)
                run.error = "fire failed before the runner could record the run"
            elif run.status != RunStatus.FAILED.value:
                # This fire produced a terminal or parked write that never durably
                # committed: a finalization or persistence step - the transcript, the
                # conversation state, the run's own commit - failed after the run had
                # finished, so `_run` never reached its commit and the row is only
                # flushed, not durable. Unlike a recorded failure this is not an
                # outcome to leave for the next fire: swallowing it would let the
                # worker context commit a completed run with no transcript behind it
                # while Prefect sees success. Re-raise, so the half-written state rolls
                # back and the flow is marked failed.
                raise

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
