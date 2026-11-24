"""Owner-only capture and review transitions; browser effects stay in the owning run."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.browser_procedure_teaching import (
    MAX_CAPTURE_SECONDS,
    MAX_EVENT_BYTES,
    MAX_EVENTS,
    RETENTION_SECONDS,
    BrowserProcedureTeachingAction,
    BrowserProcedureTeachingCapturedAction,
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingProcedure,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingReview,
    BrowserProcedureTeachingState,
    browser_procedure_canonical_bytes,
    browser_procedure_teaching_stale_revision,
    reviewed_browser_procedure,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingSession
from app.repositories import browser_procedure_teaching as repo
from app.repositories import browser_teaching_view
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingChange,
    BrowserProcedureTeachingList,
    BrowserProcedureTeachingRead,
    BrowserProcedureTeachingStart,
)

from . import _access, _listing
from ._lease import BrowserProcedureTeachingTakeover, discover


def read(row: BrowserProcedureTeachingSession) -> BrowserProcedureTeachingRead:
    return BrowserProcedureTeachingRead.model_validate(
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "run_id": row.run_id,
            "call_id": row.call_id,
            "tab_id": row.tab_id,
            "target_skill_id": row.target_skill_id,
            "title": row.title,
            "allowed_origins": row.allowed_origins,
            "source": row.source,
            "verified_success": row.verified_success,
            "status": row.status,
            "revision": row.revision,
            "reason_code": row.reason_code,
            "events": row.sanitized_events,
            "review": row.review,
            "procedure": row.procedure,
            "generation_state": row.generation_state,
            "generation_mode": row.generation_mode,
            "max_cost_usd": row.max_cost_usd,
            "proposal_id": row.proposal_id,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "capture_ends_at": row.capture_ends_at,
        }
    )


def erase(
    row: BrowserProcedureTeachingSession,
    status: BrowserProcedureTeachingState,
    reason: BrowserProcedureTeachingReason | None,
) -> None:
    row.status = status.value
    row.reason_code = None if reason is None else reason.value
    row.sanitized_events, row.review, row.procedure = [], None, None
    row.title, row.allowed_origins = "", []
    if row.generation_state in {
        BrowserProcedureTeachingGeneration.QUEUED,
        BrowserProcedureTeachingGeneration.GENERATING,
    }:
        row.generation_state = BrowserProcedureTeachingGeneration.CANCELLED.value
    row.revision += 1


def expire(row: BrowserProcedureTeachingSession, now: datetime) -> None:
    if _listing.expired(row.status, row.expires_at, now):
        erase(row, BrowserProcedureTeachingState.EXPIRED, BrowserProcedureTeachingReason.EXPIRED)


def require_capture_time(row: BrowserProcedureTeachingSession, now: datetime) -> None:
    if row.capture_ends_at <= now:
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.TIME_LIMIT)


def pause(row: BrowserProcedureTeachingSession, reason: BrowserProcedureTeachingReason) -> None:
    if row.status == BrowserProcedureTeachingState.RECORDING:
        row.status = BrowserProcedureTeachingState.PAUSED.value
        row.reason_code = reason.value
        row.revision += 1


def record_action(
    row: BrowserProcedureTeachingSession,
    *,
    input_id: UUID,
    action: BrowserProcedureTeachingAction,
    observation: BrowserProcedureTeachingObservation,
    now: datetime,
    direction: Literal["up", "down"] | None = None,
) -> None:
    if observation.origin not in row.allowed_origins:
        pause(row, BrowserProcedureTeachingReason.ORIGIN_REFUSED)
        return
    captured = tuple(
        BrowserProcedureTeachingCapturedAction.model_validate(item) for item in row.sanitized_events
    )
    existing = next((item for item in captured if item.input_id == input_id), None)
    if existing is None and len(captured) >= MAX_EVENTS:
        pause(row, BrowserProcedureTeachingReason.EVENT_LIMIT)
        return
    if row.capture_ends_at <= now:
        pause(row, BrowserProcedureTeachingReason.TIME_LIMIT)
        return
    event = BrowserProcedureTeachingCapturedAction(
        sequence=len(captured) + 1 if existing is None else existing.sequence,
        input_id=input_id,
        action="checkpoint" if observation.human_required else action,
        origin=observation.origin,
        target=None if observation.human_required else observation.target,
        direction=None if observation.human_required else direction,
        human_step=observation.human_required,
    )
    if existing is not None:
        if event != existing:
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.EVENT_CONFLICT)
        return
    events = [*row.sanitized_events, event.model_dump(mode="json")]
    if len(json.dumps(events, ensure_ascii=False).encode()) > MAX_EVENT_BYTES:
        pause(row, BrowserProcedureTeachingReason.BYTE_LIMIT)
        return
    row.sanitized_events = events
    row.revision += 1
    if observation.human_required:
        pause(row, BrowserProcedureTeachingReason.AUTHENTICATION)


async def audit(db: AsyncSession, row: BrowserProcedureTeachingSession, action: str) -> None:
    await record_audit(
        db,
        organization_id=row.organization_id,
        actor_user_id=row.owner_user_id,
        action=action,
        target_type="browser_teaching",
        target_id=str(row.id),
        details={
            "run_id": str(row.run_id),
            "agent_id": str(row.agent_id),
            "status": row.status,
            "revision": row.revision,
            "event_count": len(row.sanitized_events),
            "reason_code": row.reason_code,
        },
    )


def matches(
    row: BrowserProcedureTeachingSession, identity: BrowserProcedureTeachingTakeover
) -> bool:
    return (
        row.organization_id == identity.organization_id
        and row.owner_user_id == identity.user_id
        and row.agent_id == identity.agent_id
        and row.run_id == identity.run_id
        and row.controller_id == identity.controller_id
        and row.call_id == identity.call_id
        and row.tab_id == identity.tab_id
        and row.takeover_id == identity.takeover_id
        and row.connection_id == identity.connection_id
    )


class BrowserProcedureTeachingService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def owned(
        self, ctx: AuthContext, session_id: UUID
    ) -> tuple[AuthContext, BrowserProcedureTeachingSession]:
        current = await _access.person(self.db, ctx)
        row = await repo.session(self.db, current.organization_id, session_id, locked=True)
        if row is None or row.owner_user_id != current.user_id:
            raise NotFoundError(message="Browser teaching not found")
        expire(row, datetime.now(UTC))
        return current, row

    async def get(self, ctx: AuthContext, session_id: UUID) -> BrowserProcedureTeachingRead:
        _, row = await self.owned(ctx, session_id)
        return read(row)

    async def list(
        self, ctx: AuthContext, *, limit: int = 20, cursor: str | None = None
    ) -> BrowserProcedureTeachingList:
        """Discover this current personal owner's captures, without resuming or changing them.

        Like the per-ID read, recovery remains available after a tab ends or
        teaching is disabled. Each page refreshes active membership before
        examining its audience-bound cursor. Expiry is projected, not written.
        """
        current = await _access.person(self.db, ctx)
        owner_user_id = current.subject_id
        if not 1 <= limit <= _listing.MAX_PAGE_SIZE:
            raise refused_field("limit", "Choose a page size between 1 and 100")
        before = (
            None
            if cursor is None
            else _listing.decode_cursor(cursor, current.organization_id, owner_user_id)
        )
        rows = await repo.owned_page(
            self.db, current.organization_id, owner_user_id, limit=limit, before=before
        )
        now = datetime.now(UTC)
        page = rows[:limit]
        return BrowserProcedureTeachingList(
            items=tuple(_listing.summary(row, now) for row in page),
            next_cursor=(
                _listing.encode_cursor(current.organization_id, owner_user_id, page[-1])
                if len(rows) > limit
                else None
            ),
        )

    async def start(
        self, ctx: AuthContext, data: BrowserProcedureTeachingStart, *, skill_id: UUID | None = None
    ) -> BrowserProcedureTeachingRead:
        current = await _access.person(self.db, ctx)
        fingerprint = hashlib.sha256(
            browser_procedure_canonical_bytes(
                {
                    "request": data.model_dump(mode="json"),
                    "skill_id": None if skill_id is None else str(skill_id),
                }
            )
        ).hexdigest()
        existing = await repo.session(
            self.db, current.organization_id, data.request_id, locked=True
        )
        if existing is not None:
            if (
                existing.owner_user_id != current.user_id
                or existing.request_fingerprint != fingerprint
            ):
                raise NotFoundError(message="Browser teaching not found")
            expire(existing, datetime.now(UTC))
            return read(existing)
        identity = await discover(self.redis, data.run_id, data.call_id)
        if (
            identity is None
            or identity.takeover_id != data.takeover_id
            or identity.tab_id != data.tab_id
        ):
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
        admission = await _access.admit(self.db, current, identity, live=True)
        skill = await _access.target(self.db, current, skill_id)
        # One policy lock serializes starts across this organization's runs and
        # makes the bounded outstanding-session admission real under concurrency.
        await repo.policy(self.db, current.organization_id, locked=True)
        admission = await _access.admit(self.db, current, identity, live=True)
        existing = await repo.session(
            self.db, current.organization_id, data.request_id, locked=True
        )
        if existing is not None:
            if (
                existing.owner_user_id != current.user_id
                or existing.request_fingerprint != fingerprint
            ):
                raise NotFoundError(message="Browser teaching not found")
            return read(existing)
        if await browser_teaching_view.lock_view_and_check_active(
            self.db, current.organization_id, identity.run_id, identity.call_id
        ):
            raise ConflictError(
                message="Stop or discard the current browser teaching first",
                details={"reason_code": BrowserProcedureTeachingReason.ALREADY_ACTIVE.value},
            )
        if await repo.active(self.db, current.organization_id, identity.controller_id) is not None:
            raise ConflictError(
                message="Stop or discard the current browser teaching first",
                details={"reason_code": BrowserProcedureTeachingReason.ALREADY_ACTIVE.value},
            )
        if await repo.owner_open_count(self.db, current.organization_id, identity.user_id) >= 20:
            raise ConflictError(message="Review or discard an existing browser teaching first")
        now = datetime.now(UTC)
        row = await repo.create(
            self.db,
            BrowserProcedureTeachingSession(
                id=data.request_id,
                organization_id=current.organization_id,
                owner_user_id=identity.user_id,
                agent_id=identity.agent_id,
                run_id=identity.run_id,
                controller_id=identity.controller_id,
                takeover_id=identity.takeover_id,
                connection_id=identity.connection_id,
                call_id=identity.call_id,
                tab_id=identity.tab_id,
                title=data.title,
                allowed_origins=list(data.allowed_origins),
                target_skill_id=skill_id,
                target_base_version=None if skill is None else skill.version,
                target_base_version_id=None if skill is None else skill.latest_version_id,
                source="manual",
                verified_success=False,
                policy_generation=admission.policy.generation,
                preference_generation=None,
                request_fingerprint=fingerprint,
                status=BrowserProcedureTeachingState.RECORDING.value,
                revision=1,
                sanitized_events=[],
                generation_state=BrowserProcedureTeachingGeneration.NONE.value,
                capture_ends_at=now + timedelta(seconds=MAX_CAPTURE_SECONDS),
                expires_at=now + timedelta(seconds=RETENTION_SECONDS),
            ),
        )
        await audit(self.db, row, "browser_procedure_teaching.started")
        return read(row)

    async def change(
        self,
        ctx: AuthContext,
        session_id: UUID,
        revision: int,
        data: BrowserProcedureTeachingChange,
    ) -> BrowserProcedureTeachingRead:
        current, row = await self.owned(ctx, session_id)
        if row.revision != revision:
            raise browser_procedure_teaching_stale_revision()
        if data.action == "pause":
            if row.status not in {
                BrowserProcedureTeachingState.RECORDING,
                BrowserProcedureTeachingState.PAUSED,
            }:
                raise BrowserProcedureTeachingRefused(
                    BrowserProcedureTeachingReason.REVIEW_REQUIRED
                )
            pause(row, BrowserProcedureTeachingReason.PAUSED_BY_OWNER)
        elif data.action == "resume":
            if row.source != "manual":
                raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
            if (
                row.status != BrowserProcedureTeachingState.PAUSED
                or row.capture_ends_at <= datetime.now(UTC)
            ):
                raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.TIME_LIMIT)
            await _access.authorize(self.db, current, row, live=True)
            identity = await discover(self.redis, row.run_id, row.call_id)
            if (
                identity is None
                or identity.takeover_id != data.takeover_id
                or identity.controller_id != row.controller_id
                or identity.tab_id != row.tab_id
                or identity.user_id != row.owner_user_id
                or identity.organization_id != row.organization_id
                or identity.agent_id != row.agent_id
            ):
                raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
            row.takeover_id, row.connection_id = identity.takeover_id, identity.connection_id
            row.status, row.reason_code = BrowserProcedureTeachingState.RECORDING.value, None
            row.revision += 1
        else:
            if row.status != BrowserProcedureTeachingState.REVIEW or row.generation_state not in {
                BrowserProcedureTeachingGeneration.NONE,
                BrowserProcedureTeachingGeneration.REFUSED,
            }:
                raise BrowserProcedureTeachingRefused(
                    BrowserProcedureTeachingReason.REVIEW_REQUIRED
                )
            admission = await _access.authorize(self.db, current, row, live=False)
            _access.require_reviewable(row, admission.run)
            assert data.review is not None
            procedure = self.reviewed(row, data.review)
            row.review = data.review.model_dump(mode="json")
            row.procedure, row.source_hash = (
                procedure.model_dump(mode="json"),
                procedure.source_hash,
            )
            row.generation_state, row.reason_code = (
                BrowserProcedureTeachingGeneration.NONE.value,
                None,
            )
            row.revision += 1
        await self.db.flush()
        await audit(self.db, row, "browser_procedure_teaching.changed")
        return read(row)

    @staticmethod
    def reviewed(
        row: BrowserProcedureTeachingSession, review: BrowserProcedureTeachingReview
    ) -> BrowserProcedureTeachingProcedure:
        return reviewed_browser_procedure(
            session_id=row.id,
            origins=tuple(row.allowed_origins),
            captured=tuple(
                BrowserProcedureTeachingCapturedAction.model_validate(item)
                for item in row.sanitized_events
            ),
            review=review,
            source="manual" if row.source == "manual" else "refinement",
            verified_success=row.verified_success,
        )

    async def stop(self, ctx: AuthContext, session_id: UUID) -> BrowserProcedureTeachingRead:
        _, row = await self.owned(ctx, session_id)
        if row.status in {
            BrowserProcedureTeachingState.RECORDING,
            BrowserProcedureTeachingState.PAUSED,
        }:
            if row.source == "refinement":
                erase(
                    row,
                    BrowserProcedureTeachingState.DISCARDED,
                    BrowserProcedureTeachingReason.TASK_NOT_COMPLETED,
                )
            else:
                row.status, row.reason_code = BrowserProcedureTeachingState.REVIEW.value, None
                row.revision += 1
            await self.db.flush()
            await audit(self.db, row, "browser_procedure_teaching.stopped")
        return read(row)

    async def discard(self, ctx: AuthContext, session_id: UUID) -> BrowserProcedureTeachingRead:
        _, row = await self.owned(ctx, session_id)
        if row.status == BrowserProcedureTeachingState.PROPOSED:
            raise ConflictError(
                message="Decide the existing skill proposal; teaching discard cannot undo it"
            )
        if row.status not in {
            BrowserProcedureTeachingState.DISCARDED,
            BrowserProcedureTeachingState.EXPIRED,
        }:
            erase(row, BrowserProcedureTeachingState.DISCARDED, None)
            await self.db.flush()
            await audit(self.db, row, "browser_procedure_teaching.discarded")
        return read(row)

    async def pause_live(
        self, identity: BrowserProcedureTeachingTakeover, reason: BrowserProcedureTeachingReason
    ) -> BrowserProcedureTeachingRead | None:
        row = await repo.active(self.db, identity.organization_id, identity.controller_id)
        if row is None or not matches(row, identity):
            return None
        pause(row, reason)
        await self.db.flush()
        return read(row)

    async def append(
        self,
        ctx: AuthContext,
        identity: BrowserProcedureTeachingTakeover,
        *,
        input_id: UUID,
        action: BrowserProcedureTeachingAction,
        observation: BrowserProcedureTeachingObservation,
        direction: Literal["up", "down"] | None = None,
    ) -> BrowserProcedureTeachingRead | None:
        """Only the owning input pipeline calls this; there is no route accepting events."""
        row = await repo.active(self.db, identity.organization_id, identity.controller_id)
        if row is None or not matches(row, identity):
            return None
        now = datetime.now(UTC)
        expire(row, now)
        if row.status != BrowserProcedureTeachingState.RECORDING:
            return read(row)
        await _access.authorize(self.db, ctx, row, live=True)
        live = await discover(self.redis, row.run_id, row.call_id)
        if live != identity:
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
        record_action(
            row,
            input_id=input_id,
            action=action,
            observation=observation,
            direction=direction,
            now=now,
        )
        await self.db.flush()
        return read(row)
