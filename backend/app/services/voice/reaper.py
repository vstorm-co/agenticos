"""Hanging up calls whose process died (#54, Q3).

A worker that is SIGKILLed, OOM-killed or deployed over without a drain never
runs its calls' `finally`, and an OpenAI WebRTC call goes on billing for up to
60 minutes. This sweep - every minute, and once at start-up - finds rows with no
`hung_up_at` whose heartbeat went stale (or whose end was recorded but whose
hang-up failed), hangs them up with the call id and the key, records the call's
end from its last heartbeat, closes the run at the cost the heartbeats wrote,
and expires any approval it left pending.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import RunStatus
from app.db.models.voice_call import VoiceEndReason
from app.repositories import agent_run_repo, voice_call_repo
from app.services.voice.hangup import hang_up_row
from app.services.voice.limits import STALE_AFTER_SECONDS

logger = logging.getLogger(__name__)

REAPED_ERROR = "The process holding this call stopped; the call was hung up by the voice sweep."

PROVIDER_SESSION_SECONDS = 3600
"""OpenAI ends every realtime session within an hour, so a call older than this
that still cannot be hung up is no longer the provider's to bill."""


class VoiceCallReaper:
    """The sweep that hangs up calls whose process stopped holding them."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def reap(self, *, now: datetime | None = None) -> int:
        """Hang up every call the provider may still hold. Returns how many were hung up."""
        now = now or datetime.now(UTC)
        rows = await voice_call_repo.list_unhung(
            self.db, stale_before=now - timedelta(seconds=STALE_AFTER_SECONDS)
        )
        reaped = 0
        for row in rows:
            # Read before the writes: an UPDATE through this session expires the
            # row's columns, and an expired column read here would be a lazy load.
            call_id, run_id, provider = row.id, row.run_id, row.provider
            heartbeat_at, cost_usd, seconds = row.heartbeat_at, row.cost_usd, row.seconds
            guardrail_hits = row.guardrail_hits
            started_at, ended_at, end_reason = row.started_at, row.ended_at, row.end_reason
            hung = await hang_up_row(self.db, row)
            abandoned = not hung and started_at < now - timedelta(seconds=PROVIDER_SESSION_SECONDS)
            if ended_at is None:
                await voice_call_repo.end(
                    self.db,
                    call_id,
                    at=heartbeat_at,
                    reason=VoiceEndReason.ABANDONED if abandoned else VoiceEndReason.REAPED,
                    cost_usd=cost_usd,
                    seconds=seconds,
                    guardrail_hits=guardrail_hits,
                )
            if run_id is not None:
                # Only a run still `running` is touched: one its call's own teardown
                # finished keeps that outcome. A connection a reconnect took over was
                # continued, not failed.
                await agent_run_repo.close_voice_run(
                    self.db,
                    run_id=run_id,
                    status=(
                        RunStatus.CANCELLED.value
                        if end_reason == VoiceEndReason.DISCONNECTED.value
                        else RunStatus.FAILED.value
                    ),
                    cost_usd=cost_usd,
                    ended_at=heartbeat_at,
                    error=None if end_reason == VoiceEndReason.DISCONNECTED.value else REAPED_ERROR,
                )
                # An approval its bridge could not expire must not stay pending for ever.
                await agent_run_repo.expire_pending_approvals(
                    self.db, run_id=run_id, decided_at=now
                )
            if hung:
                await voice_call_repo.mark_hung_up(self.db, call_id, at=now)
                reaped += 1
                logger.warning(
                    "voice_call_reaped", extra={"call_id": str(call_id), "provider": provider}
                )
            elif abandoned:
                # Its key is gone or keeps failing, and the provider has ended every
                # session by now: stop retrying it, so it no longer holds a place at
                # the head of the oldest-first queue ahead of calls that can be hung up.
                await voice_call_repo.mark_hung_up(self.db, call_id, at=now)
                logger.warning(
                    "voice_call_abandoned", extra={"call_id": str(call_id), "provider": provider}
                )
        return reaped
