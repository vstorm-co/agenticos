"""Retention and lease reconciliation. Runs whether or not the feature is enabled.

Every open session expires 24 hours after it started and its payload is erased.
A recording whose hold is gone, whose time is up, or whose owner lost authority
is paused, so a crashed worker cannot leave capture open. The sweep never
resumes or creates recording; a missed tick is simply done by the next one.
"""

from contextlib import suppress
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_teaching import TeachingReason, TeachingRefused, TeachingState
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.session import get_db_context
from app.repositories import browser_teaching as repo
from app.services import live_browse

from . import _access, _hold
from ._service import audit, expire_if_due, pause


async def _recording_refusal(
    db: AsyncSession, row: BrowserTeachingSession, now: datetime
) -> TeachingReason | None:
    if row.capture_ends_at <= now:
        return TeachingReason.TIME_LIMIT
    if not _access.deployment_enabled(row.organization_id):
        return TeachingReason.DISABLED
    redis = live_browse.client()
    if redis is not None:
        # Without Redis no hold can be read here; capture itself refuses every
        # event then, so the lease check waits for a tick that can make it.
        held = await _hold.current(redis, row.run_id, row.call_id)
        if held is None or held.hold_id != row.hold_id or held.user_id != row.owner_user_id:
            return TeachingReason.OWNERSHIP_LOST
    try:
        await _access.authority(db, row.organization_id, row.owner_user_id, row.run_id)
    except TeachingRefused as refused:
        return refused.reason
    return None


async def sweep_browser_teachings() -> int:
    """Expire or pause what must stop; answer how many rows changed."""
    now = datetime.now(UTC)
    with suppress(RedisError, OSError):
        await live_browse.connect_in_worker()
    async with get_db_context() as db:
        candidates = await repo.sweep_candidates(db, now)
    changed = 0
    for organization_id, session_id in candidates:
        async with get_db_context() as db:
            row = await repo.get(db, organization_id, session_id, locked=True)
            if row is None:
                continue
            revision = row.revision
            if expire_if_due(row, now):
                await audit(db, row, "browser_teaching.expired")
            elif row.status == TeachingState.RECORDING:
                reason = await _recording_refusal(db, row, now)
                if reason is not None:
                    pause(row, reason)
                    await audit(db, row, "browser_teaching.paused")
            # Round-robin: a long-lived paused row must not keep the batch from others.
            row.updated_at = now
            changed += row.revision != revision
    return changed
