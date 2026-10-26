"""Agent triggers - the heartbeat that fires scheduled runs, and the run itself.

Two halves (see `docs/design/heartbeat-triggers-plan.md`, sections 3 and 4):

* `check_agent_triggers` is the heartbeat, the `check-agent-triggers` schedule
  (`app/worker/schedules.py`), every minute. Each tick claims the triggers due
  now - `FOR UPDATE SKIP LOCKED`, so a tick that outruns its own minute cannot
  be double-claimed by the next - and queues one `fire-trigger` job per claimed
  trigger in the claim's own transaction, so a slow agent run never holds the
  tick open and no claim is ever left without its fire.
* `fire_trigger` is one fired run, as its own job on the agent pool so it is
  capped by the pool's concurrency and isolated from the tick that scheduled it.
  The work is `AgentTriggerService.fire`, which runs the agent as the trigger's
  creator through the ordinary run path.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.db.session import get_worker_db_context
from app.worker.jobs import FireTrigger

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.mcp_connection import McpConnection

logger = logging.getLogger(__name__)


async def check_agent_triggers() -> None:
    """Heartbeat: claim the triggers due now and queue a fire for each.

    The claim, the advance of each trigger's `next_fire_at` and the queued fires
    commit together: a submit that raised after the claim used to leave it
    unclear whether the run had started (#589), and that question no longer has
    a moment to arise in.
    """
    from app.services.agent_trigger import AgentTriggerService

    async with get_worker_db_context() as db:
        triggers = await AgentTriggerService(db).claim_and_advance(now=datetime.now(UTC))
    logger.info("agent_triggers_check", extra={"queued": len(triggers)})


async def _poll_one_grant(db: AsyncSession, grant: McpConnection, source: str) -> int:
    """Read one connected account, queue a fire for what arrived, and record where it got to.

    Extracted so the tick can isolate a grant: see the caller. Answers how many
    fires were queued.
    """
    from app.services.agent_trigger import AgentTriggerService
    from app.services.mcp_connection import McpConnectionService

    read = await McpConnectionService(db).poll_grant(grant)
    if read is None:
        return 0
    assert grant.organization_id is not None, "a portal grant is always created org-scoped"
    decisions = await AgentTriggerService(db).prepare_polled_fires(
        organization_id=grant.organization_id,
        event_source=source,
        events=read.events,
    )
    service = AgentTriggerService(db)
    for decision in decisions:
        await service.queue_fire(
            decision.trigger_id,
            organization_id=grant.organization_id,
            event_context=decision.event_context,
        )
    # In the fires' own transaction: the cursor moves exactly when the fires for
    # what it read are queued, so a crash re-reads the window - which the
    # delivery-id claim then dedups - rather than dropping a polled message that,
    # unlike a webhook, no provider will ever resend.
    await McpConnectionService(db).store_poll_cursor(grant, cursor=read.cursor)
    return len(decisions)


async def poll_portal_grants() -> None:
    """Heartbeat: read the connected accounts nobody pushes to, and fire what arrived.

    The `poll-portal-grants` schedule, beside `check_agent_triggers`, and the one
    that makes a polled portal a delivery mechanism
    rather than a second kind of trigger. Gmail pushes nothing without a Cloud
    Pub/Sub topic and a registration that expires weekly, so this asks - once a
    minute, one request per connected mailbox - and hands whatever it finds to the
    same match-then-fire path a webhook delivery takes.

    Each mailbox owns a transaction advisory lock until its cursor and queued
    fires commit. Its credential row remains available to independent OAuth
    refreshes. A failed mailbox rolls back its partial work in a savepoint and
    advances its retry timestamp without preventing other tenants from polling.

    **The cursor advances in the transaction that queues the fires.** In any
    other order a crash between the two either loses every message the poll
    read - the cursor says they were handled and nothing handled them - or fires
    them twice. Together, a crash re-reads them, which the delivery-id claim then
    dedups: at-least-once, with the duplicate suppressed, never a silent hole.
    """
    from app.services.mcp_connection import McpConnectionService
    from app.services.portal_catalog import CATALOG, DeliveryMode

    polled_keys = [entry.key for entry in CATALOG if entry.delivery is DeliveryMode.POLLING]
    if not polled_keys:
        return
    # The dedupe claim is what keeps a re-read message from firing twice, and only
    # the API lifespan configures its module - a different process. Unconfigured it
    # fails open, which here is exactly the duplicate spend it exists to stop.
    await _ensure_trigger_dedupe()
    queued = 0
    async with get_worker_db_context() as db:
        candidates = await McpConnectionService(db).portal_poll_candidates(portal_keys=polled_keys)
    for connection_id in candidates:
        async with get_worker_db_context() as db:
            connections = McpConnectionService(db)
            grant = await connections.claim_grant_to_poll(
                connection_id=connection_id, portal_keys=polled_keys
            )
            if grant is None:
                continue
            portal_key = grant.portal_key
            source = _polled_source(portal_key)
            if source is None:
                await connections.record_poll_processing_failure(connection_id)
                continue
            try:
                async with db.begin_nested():
                    took = await _poll_one_grant(db, grant, source)
                queued += took
            except Exception:
                logger.exception(
                    "portal_poll_grant_failed",
                    extra={"portal_key": portal_key, "connection_id": str(connection_id)},
                )
                await connections.record_poll_processing_failure(connection_id)
    logger.info("portal_poll", extra={"queued": queued})


async def _ensure_trigger_dedupe() -> None:
    """Hand the delivery dedupe a Redis in this worker process, once.

    The worker is not the API process, so the lifespan's `configure` never
    reaches it, and an unconfigured claim fails open - a rolled-back poll would
    then re-fire the same message on the next tick. The client lives for the
    worker process.
    """
    from app.clients.redis import RedisClient
    from app.services import trigger_dedupe

    if trigger_dedupe.is_configured():
        return
    client = RedisClient()
    await client.connect()
    trigger_dedupe.configure(client)


async def sweep_sandbox_operations() -> None:
    """Drop sandbox operations older than the retention window.

    A sandbox is reaped half an hour after it goes idle and its files may be swept
    by the service's own TTL, so a log that outlived the answer to "what happened
    here" by years would be a growing table nobody reads. Daily rather than hourly:
    the window is thirty days, so the exact hour a row leaves is not a fact anybody
    depends on, and a delete over a month-old boundary is cheap when it runs once.
    """
    from datetime import timedelta

    from app.db.models.sandbox_operation import OPERATION_RETENTION_DAYS
    from app.repositories import sandbox_operation_repo

    cutoff = datetime.now(UTC) - timedelta(days=OPERATION_RETENTION_DAYS)
    async with get_worker_db_context() as db:
        removed = await sandbox_operation_repo.delete_older_than(db, cutoff=cutoff)
    logger.info("sandbox_log_swept", extra={"removed": removed, "days": OPERATION_RETENTION_DAYS})


def _polled_source(portal_key: str | None) -> str | None:
    """The `event_source` a portal's presets fire through, or `None` for no portal.

    Read off the catalog rather than assumed from the key, because they are not the
    same word: the portal is `google` and the source is `gmail`.
    """
    from app.services.portal_catalog import get_portal

    portal = None if portal_key is None else get_portal(portal_key)
    return None if portal is None else portal.event_source


async def fire_trigger(fire: FireTrigger) -> None:
    """One fired run: run the agent this trigger fires, as its creator.

    Reached from every door - the scheduled check with no `event_context`, an
    inbound event or a polled portal with the rendered context, the run-now
    button - so every kind runs in this one capped, isolated job on the agent
    pool rather than the event kind running in the API process.

    `claimed_at` is the `fire_in_flight_since` the scheduled claim stamped,
    handed back to `fire` as this fire's claim ticket, so the marker is cleared
    only while it still belongs to this claim - a fire that outran the lease must
    not clear the marker a newer claim set. Only the scheduled path sets it; an
    event or manually triggered fire has none and leaves any marker for the lease.
    """
    from app.services.agent_trigger import AgentTriggerService

    async with get_worker_db_context() as db:
        await AgentTriggerService(db).fire(
            fire.trigger_id, event_context=fire.event_context, claimed_at=fire.claimed_at
        )
