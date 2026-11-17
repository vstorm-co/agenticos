"""Owner-only teaching transitions and the server-side event append.

No route accepts recorder events. `record` is called only by the capture
attached to the held tab in the run's worker; the API can start, pause, resume,
stop, read and discard. Each transition re-checks current authority.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.browser_teaching import (
    MAX_CAPTURE_SECONDS,
    MAX_EVENT_BYTES,
    MAX_EVENTS,
    RETENTION_SECONDS,
    Action,
    CapturedStep,
    Observation,
    TeachingConflict,
    TeachingReason,
    TeachingRefused,
    TeachingState,
    encoded_size,
)
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.browser_teaching import BrowserTeachingSession
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingChange, TeachingRead, TeachingStart

from . import _access, _hold
from ._hold import Hold

_HARD_LIMITS = frozenset(
    {TeachingReason.EVENT_LIMIT, TeachingReason.BYTE_LIMIT, TeachingReason.TIME_LIMIT}
)
_OPEN = frozenset({TeachingState.RECORDING, TeachingState.PAUSED, TeachingState.REVIEW})


def read(row: BrowserTeachingSession) -> TeachingRead:
    return TeachingRead(
        id=row.id,
        agent_id=row.agent_id,
        run_id=row.run_id,
        call_id=row.call_id,
        tab_id=row.tab_id,
        title=row.title,
        allowed_origins=tuple(row.allowed_origins),
        status=TeachingState(row.status),
        revision=row.revision,
        reason_code=None if row.reason_code is None else TeachingReason(row.reason_code),
        events=tuple(CapturedStep.model_validate(item) for item in row.sanitized_events),
        created_at=row.created_at,
        capture_ends_at=row.capture_ends_at,
        expires_at=row.expires_at,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pause(row: BrowserTeachingSession, reason: TeachingReason) -> None:
    if row.status == TeachingState.RECORDING:
        row.status = TeachingState.PAUSED.value
        row.reason_code = reason.value
        row.revision += 1


def erase(
    row: BrowserTeachingSession, status: TeachingState, reason: TeachingReason | None
) -> None:
    """Remove every payload; keep only the minimal audit metadata."""
    row.status = status.value
    row.reason_code = None if reason is None else reason.value
    row.sanitized_events = []
    row.allowed_origins = []
    row.title = ""
    row.hold_id = None
    row.revision += 1


def expire_if_due(row: BrowserTeachingSession, now: datetime) -> bool:
    if row.status in _OPEN and row.expires_at <= now:
        erase(row, TeachingState.EXPIRED, TeachingReason.EXPIRED)
        return True
    return False


def matches(row: BrowserTeachingSession, hold: Hold) -> bool:
    return (
        row.organization_id == hold.organization_id
        and row.owner_user_id == hold.user_id
        and row.agent_id == hold.agent_id
        and row.run_id == hold.run_id
        and row.call_id == hold.call_id
        and row.tab_id == hold.tab_id
        and row.hold_id == hold.hold_id
    )


async def audit(db: AsyncSession, row: BrowserTeachingSession, action: str) -> None:
    """Audit with ids, state and counts only - never origins, titles or steps."""
    await record_audit(
        db,
        organization_id=row.organization_id,
        actor_user_id=row.owner_user_id,
        action=action,
        target_type="browser_teaching",
        target_id=str(row.id),
        details={
            "run_id": str(row.run_id),
            "status": row.status,
            "revision": row.revision,
            "event_count": len(row.sanitized_events),
            "reason_code": row.reason_code,
        },
    )


class BrowserTeachingService:
    def __init__(self, db: AsyncSession, redis: RedisClient | None) -> None:
        self.db, self.redis = db, redis

    async def _live_hold(
        self, organization_id: UUID, user_id: UUID, run_id: UUID, call_id: str
    ) -> Hold:
        hold = None if self.redis is None else await _hold.current(self.redis, run_id, call_id)
        if hold is None or hold.user_id != user_id or hold.organization_id != organization_id:
            raise TeachingRefused(TeachingReason.NOT_HELD)
        return hold

    async def _owned(self, ctx: AuthContext, session_id: UUID) -> BrowserTeachingSession:
        """The caller's own row, locked. Another person's row is indistinguishable from none."""
        user_id = _access.human_subject(ctx)
        row = await repo.get(self.db, ctx.organization_id, session_id, locked=True)
        if row is None or row.owner_user_id != user_id:
            raise NotFoundError(
                message="Browser teaching not found", details={"session_id": session_id}
            )
        if expire_if_due(row, datetime.now(UTC)):
            await audit(self.db, row, "browser_teaching.expired")
        return row

    async def start(
        self, ctx: AuthContext, body: TeachingStart, request_key: str | None
    ) -> TeachingRead:
        user_id = _access.human_subject(ctx)
        organization_id = ctx.organization_id
        _access.require_enabled(organization_id)
        key = _digest(request_key or str(uuid4()))
        fingerprint = _digest(body.model_dump_json())
        earlier = await repo.by_request(self.db, organization_id, user_id, key)
        if earlier is not None:
            if earlier.request_fingerprint != fingerprint:
                raise TeachingConflict(TeachingReason.REQUEST_REUSED)
            return read(earlier)
        run = await _access.authority(self.db, organization_id, user_id, body.run_id)
        hold = await self._live_hold(organization_id, user_id, run.id, body.call_id)
        if hold.agent_id != run.agent_id:
            raise TeachingRefused(TeachingReason.NOT_HELD)
        if await repo.active_for_view(self.db, organization_id, run.id, body.call_id) is not None:
            raise TeachingConflict(TeachingReason.ALREADY_RECORDING)
        now = datetime.now(UTC)
        row = BrowserTeachingSession(
            id=uuid4(),
            organization_id=organization_id,
            owner_user_id=user_id,
            agent_id=run.agent_id,
            run_id=run.id,
            call_id=body.call_id,
            tab_id=hold.tab_id,
            hold_id=hold.hold_id,
            title=body.title,
            allowed_origins=list(body.allowed_origins),
            request_key=key,
            request_fingerprint=fingerprint,
            status=TeachingState.RECORDING.value,
            revision=1,
            sanitized_events=[],
            capture_ends_at=now + timedelta(seconds=MAX_CAPTURE_SECONDS),
            expires_at=now + timedelta(seconds=RETENTION_SECONDS),
        )
        try:
            async with self.db.begin_nested():
                row = await repo.create(self.db, row)
        except IntegrityError:
            # A concurrent start won the request key or the view's single active slot.
            raced = await repo.by_request(self.db, organization_id, user_id, key)
            if raced is not None and raced.request_fingerprint == fingerprint:
                return read(raced)
            raise TeachingConflict(TeachingReason.ALREADY_RECORDING) from None
        await audit(self.db, row, "browser_teaching.started")
        return read(row)

    async def get(self, ctx: AuthContext, session_id: UUID) -> TeachingRead:
        return read(await self._owned(ctx, session_id))

    async def change(
        self, ctx: AuthContext, session_id: UUID, body: TeachingChange, revision: int | None
    ) -> TeachingRead:
        row = await self._owned(ctx, session_id)
        if revision is None or revision != row.revision:
            raise TeachingConflict(TeachingReason.STALE_REVISION)
        if body.action == "pause":
            if row.status != TeachingState.RECORDING:
                raise TeachingConflict(TeachingReason.WRONG_STATE)
            pause(row, TeachingReason.PAUSED_BY_OWNER)
            await audit(self.db, row, "browser_teaching.paused")
            return read(row)
        if row.status != TeachingState.PAUSED:
            raise TeachingConflict(TeachingReason.WRONG_STATE)
        if row.reason_code is not None and TeachingReason(row.reason_code) in _HARD_LIMITS:
            raise TeachingRefused(TeachingReason(row.reason_code))
        _access.require_enabled(row.organization_id)
        if row.capture_ends_at <= datetime.now(UTC):
            raise TeachingRefused(TeachingReason.TIME_LIMIT)
        await _access.authority(self.db, row.organization_id, row.owner_user_id, row.run_id)
        hold = await self._live_hold(
            row.organization_id, row.owner_user_id, row.run_id, row.call_id
        )
        if hold.agent_id != row.agent_id or hold.tab_id != row.tab_id:
            raise TeachingRefused(TeachingReason.NOT_HELD)
        row.hold_id = hold.hold_id
        row.status = TeachingState.RECORDING.value
        row.reason_code = None
        row.revision += 1
        await audit(self.db, row, "browser_teaching.resumed")
        return read(row)

    async def stop(self, ctx: AuthContext, session_id: UUID) -> TeachingRead:
        """Close capture and enter review. Stopping a stopped session returns it unchanged."""
        row = await self._owned(ctx, session_id)
        if row.status == TeachingState.REVIEW:
            return read(row)
        if row.status not in (TeachingState.RECORDING, TeachingState.PAUSED):
            raise TeachingConflict(TeachingReason.WRONG_STATE)
        row.status = TeachingState.REVIEW.value
        row.hold_id = None
        row.revision += 1
        await audit(self.db, row, "browser_teaching.stopped")
        return read(row)

    async def discard(self, ctx: AuthContext, session_id: UUID) -> None:
        """Erase the payload. It does not undo anything the person did in the browser."""
        row = await self._owned(ctx, session_id)
        if row.status in _OPEN:
            erase(row, TeachingState.DISCARDED, None)
            await audit(self.db, row, "browser_teaching.discarded")

    async def release(self, hold: Hold, reason: TeachingReason) -> None:
        """The hold ended: pause the session bound to it, if one is recording."""
        row = await repo.active_for_view(
            self.db, hold.organization_id, hold.run_id, hold.call_id, locked=True
        )
        if row is not None and matches(row, hold) and row.status == TeachingState.RECORDING:
            pause(row, reason)
            await audit(self.db, row, "browser_teaching.paused")

    async def record(
        self,
        hold: Hold,
        *,
        input_id: UUID,
        action: Action,
        observation: Observation,
        direction: Literal["up", "down"] | None = None,
    ) -> None:
        """Append one structural step for the current hold, after every check.

        Nothing is recorded unless the view has a recording session bound to
        exactly this hold. A failed check pauses capture with a reason code
        rather than dropping events silently; a limit is never truncated.
        """
        row = await repo.active_for_view(
            self.db, hold.organization_id, hold.run_id, hold.call_id, locked=True
        )
        if row is None or row.status != TeachingState.RECORDING or not matches(row, hold):
            return
        reason = await self._refusal(row, hold, observation)
        if reason is not None:
            pause(row, reason)
            await audit(self.db, row, "browser_teaching.paused")
            return
        earlier = next(
            (item for item in row.sanitized_events if item.get("input_id") == str(input_id)), None
        )
        stored = None if earlier is None else CapturedStep.model_validate(earlier)
        if stored is None and len(row.sanitized_events) >= MAX_EVENTS:
            pause(row, TeachingReason.EVENT_LIMIT)
            await audit(self.db, row, "browser_teaching.paused")
            return
        human = observation.authentication
        step = CapturedStep(
            sequence=len(row.sanitized_events) + 1 if stored is None else stored.sequence,
            input_id=input_id,
            action="checkpoint" if human else action,
            origin=observation.origin,
            target=None if human else observation.target,
            direction=None if human else direction,
            human_step=human,
        )
        if stored is not None:
            # A repeated input is a no-op; the same input id with another payload is a conflict.
            if stored != step:
                pause(row, TeachingReason.EVENT_CONFLICT)
                await audit(self.db, row, "browser_teaching.paused")
            return
        steps = [*row.sanitized_events, step.model_dump(mode="json")]
        if encoded_size(steps) > MAX_EVENT_BYTES:
            pause(row, TeachingReason.BYTE_LIMIT)
            await audit(self.db, row, "browser_teaching.paused")
            return
        row.sanitized_events = steps
        row.revision += 1
        if human:
            pause(row, TeachingReason.AUTHENTICATION)
            await audit(self.db, row, "browser_teaching.paused")

    async def _refusal(
        self, row: BrowserTeachingSession, hold: Hold, observation: Observation
    ) -> TeachingReason | None:
        now = datetime.now(UTC)
        if not _access.deployment_enabled(row.organization_id):
            return TeachingReason.DISABLED
        if row.capture_ends_at <= now or row.expires_at <= now:
            return TeachingReason.TIME_LIMIT
        try:
            await _access.authority(self.db, row.organization_id, row.owner_user_id, row.run_id)
        except TeachingRefused as refused:
            return refused.reason
        live = (
            None
            if self.redis is None
            else await _hold.current(self.redis, hold.run_id, hold.call_id)
        )
        if live != hold:
            return TeachingReason.OWNERSHIP_LOST
        if observation.origin not in row.allowed_origins:
            return TeachingReason.ORIGIN_REFUSED
        return None
