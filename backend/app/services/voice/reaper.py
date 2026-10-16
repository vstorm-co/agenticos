"""Hanging up calls whose process died (#54, Q3).

A worker that is SIGKILLed, OOM-killed or deployed over without a drain never
runs its calls' `finally`, and an OpenAI WebRTC call goes on billing for up to
60 minutes. This sweep - every minute, and once at start-up - finds rows with no
`hung_up_at` whose heartbeat went stale (or whose end was recorded but whose
hang-up failed), hangs them up with the call id and the key, records the call's
end from its last heartbeat, closes the run at the cost the heartbeats wrote,
and expires any approval it left pending.

Each row is closed in a transaction of its own. One row that cannot be closed -
a key that no longer unseals, a failing write - is logged and left for the next
pass rather than rolling back the rows before it and, at the head of the
oldest-first queue, stopping every pass after it. A row's own transaction also
keeps its provider hang-up from holding the locks of every other row.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import RunStatus
from app.db.models.voice_call import VoiceCall, VoiceEndReason
from app.repositories import agent_run_repo, voice_call_repo
from app.services.voice.hangup import hang_up_row
from app.services.voice.limits import STALE_AFTER_SECONDS
from app.services.voice.transcript import SessionFactory

logger = logging.getLogger(__name__)

REAPED_ERROR = "The process holding this call stopped; the call was hung up by the voice sweep."

PROVIDER_SESSION_SECONDS = 3600
"""OpenAI ends every realtime session within an hour, so a call older than this
that still cannot be hung up is no longer the provider's to bill."""


async def close_orphaned(
    db: AsyncSession, row: VoiceCall, *, reason: VoiceEndReason, now: datetime
) -> bool:
    """Close a connection no live process will close: the sweep's, and a reconnect's
    for a connection another worker still holds. Returns whether the provider no
    longer holds the call.

    Hangs up first, so a call that cannot be hung up within the provider's own hour
    is ended as `abandoned` rather than `reason`. The end and the run's close are
    stamped at the last heartbeat - the last moment anything proved the call alive
    - so the same dead connection counts the same minutes whichever path closes
    it. Only a run still `running` is closed, and as `cancelled` when the
    connection was continued by a reconnect (`disconnected`), else as failed.
    """
    # Read before the writes: an UPDATE through this session expires the row's
    # columns, and an expired column read afterwards would be a lazy load.
    call_id, run_id, provider = row.id, row.run_id, row.provider
    heartbeat_at, cost_usd, seconds = row.heartbeat_at, row.cost_usd, row.seconds
    guardrail_hits = row.guardrail_hits
    started_at, ended_at, end_reason = row.started_at, row.ended_at, row.end_reason
    hung = await hang_up_row(db, row)
    abandoned = not hung and started_at < now - timedelta(seconds=PROVIDER_SESSION_SECONDS)
    if ended_at is None:
        end_reason = (VoiceEndReason.ABANDONED if abandoned else reason).value
        await voice_call_repo.end(
            db,
            call_id,
            at=heartbeat_at,
            reason=VoiceEndReason(end_reason),
            cost_usd=cost_usd,
            seconds=seconds,
            guardrail_hits=guardrail_hits,
        )
    if run_id is not None:
        continued = end_reason == VoiceEndReason.DISCONNECTED.value
        await agent_run_repo.close_voice_run(
            db,
            run_id=run_id,
            status=RunStatus.CANCELLED.value if continued else RunStatus.FAILED.value,
            cost_usd=cost_usd,
            ended_at=heartbeat_at,
            error=None if continued else REAPED_ERROR,
        )
        # An approval its bridge could not expire must not stay pending for ever.
        await agent_run_repo.expire_pending_approvals(db, run_id=run_id, decided_at=now)
    if hung:
        await voice_call_repo.mark_hung_up(db, call_id, at=now)
    elif abandoned:
        # Its key is gone or keeps failing, and the provider has ended every
        # session by now: stop retrying it, so it no longer holds a place at
        # the head of the oldest-first queue ahead of calls that can be hung up.
        await voice_call_repo.mark_hung_up(db, call_id, at=now)
        logger.warning(
            "voice_call_abandoned", extra={"call_id": str(call_id), "provider": provider}
        )
    return hung


class VoiceCallReaper:
    """The sweep that hangs up calls whose process stopped holding them."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def reap(self, *, now: datetime | None = None) -> int:
        """Hang up every call the provider may still hold. Returns how many were hung up."""
        now = now or datetime.now(UTC)
        stale_before = now - timedelta(seconds=STALE_AFTER_SECONDS)
        async with self._sessions() as db:
            listed = await voice_call_repo.list_unhung(db, stale_before=stale_before)
            call_ids = [row.id for row in listed]
        reaped = 0
        for call_id in call_ids:
            try:
                async with self._sessions() as db:
                    # `None` when another sweep holds it, or it was hung up or
                    # heartbeated since the listing.
                    row = await voice_call_repo.claim_unhung(db, call_id, stale_before=stale_before)
                    if row is None:
                        continue
                    provider = row.provider
                    hung = await close_orphaned(db, row, reason=VoiceEndReason.REAPED, now=now)
            except Exception:
                logger.exception("voice_call_reap_failed", extra={"call_id": str(call_id)})
                continue
            if hung:
                reaped += 1
                logger.warning(
                    "voice_call_reaped", extra={"call_id": str(call_id), "provider": provider}
                )
        return reaped
